"""HTTP API: the record view (reading) and the control-plane workbench (governing)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import __version__, audit
from .broker import RequestRejected
from .controlplane.ops import OpError
from .controlplane.store import Store
from .controlplane.workbench import PERSONAS, GovernanceError, Workbench
from .data import ROOT
from .ips import to_ips
from .models import PatientRecord, RecordRequest
from .prov import to_prov
from .sources import state

STATIC = Path(__file__).parent / "static"


class NewChange(BaseModel):
    title: str
    rationale: str = ""
    ops: list[dict[str, Any]]


class Decision(BaseModel):
    text: str


class Outage(BaseModel):
    offline: list[str]


def create_app(wb: Workbench) -> FastAPI:
    app = FastAPI(
        title="Federation control-plane workbench",
        version=__version__,
        description="Govern the catalogue, terminology and identity links behind a federated patient record: change requests, "
        "impact analysis, clinical sign-off, conformance testing, onboarding, versioning and replay. All data is synthetic.",
    )
    app.state.wb = wb

    @app.exception_handler(GovernanceError)
    async def _gov(_: Request, e: GovernanceError):
        return JSONResponse(status_code=409, content={"detail": str(e)})

    @app.exception_handler(OpError)
    async def _op(_: Request, e: OpError):
        return JSONResponse(status_code=422, content={"detail": str(e)})

    @app.exception_handler(KeyError)
    async def _key(_: Request, e: KeyError):
        return JSONResponse(status_code=404, content={"detail": str(e).strip("'")})

    def ver(version: int | None) -> int:
        return version or wb.current_version()

    # -- pages -------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    def record_page() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/workbench", include_in_schema=False)
    def workbench_page() -> FileResponse:
        return FileResponse(STATIC / "workbench.html")

    # -- reading -------------------------------------------------------------
    @app.get("/api/health", tags=["service"])
    def health() -> dict:
        return {"status": "ok", "version": __version__, "catalogue_version": f"v{wb.current_version()}"}

    @app.get("/api/patients", tags=["record"])
    def patients(version: int | None = None) -> list[dict]:
        return wb.objects(ver(version))[2].persons()

    @app.get("/api/catalogue", tags=["control plane"])
    def catalogue(version: int | None = None) -> dict:
        return wb.objects(ver(version))[0].data

    @app.get("/api/catalogue/cdif", tags=["control plane"])
    def cdif(version: int | None = None) -> JSONResponse:
        return JSONResponse(wb.objects(ver(version))[0].to_cdif_jsonld(), media_type="application/ld+json")

    @app.get("/api/terminology", tags=["control plane"])
    def terminology(version: int | None = None) -> dict:
        return wb.objects(ver(version))[1].data

    @app.post("/api/record", tags=["record"], response_model=None)
    async def record(req: RecordRequest, format: Literal["record", "ips", "prov"] = "record", version: int | None = None) -> PatientRecord | dict:
        """Assemble the federated record under the current (or a named) catalogue version."""
        try:
            rec = await wb.assemble(req, ver(version))
        except RequestRejected as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return to_ips(rec) if format == "ips" else to_prov(rec) if format == "prov" else rec

    @app.get("/api/demo/outages", tags=["demo controls"])
    def get_outages() -> Outage:
        return Outage(offline=sorted(state.OFFLINE))

    @app.put("/api/demo/outages", tags=["demo controls"])
    def set_outages(body: Outage) -> Outage:
        state.OFFLINE.clear()
        state.OFFLINE.update(body.offline)
        return Outage(offline=sorted(state.OFFLINE))

    @app.get("/api/audit", tags=["service"])
    def get_audit(limit: int = 20) -> list[dict]:
        return audit.recent(limit)

    # -- workbench -------------------------------------------------------------
    @app.get("/api/wb/personas", tags=["workbench"])
    def personas() -> list[dict]:
        return list(PERSONAS.values())

    @app.get("/api/wb/overview", tags=["workbench"])
    def overview() -> dict:
        cat, term, _ = wb.objects()
        lifecycles: dict[str, int] = {}
        for s in cat.sources.values():
            for e in s["exposes"]:
                lifecycles[e["mapping"].get("lifecycle")] = lifecycles.get(e["mapping"].get("lifecycle"), 0) + 1
        elements: dict[str, int] = {}
        for m in term.data["concept_maps"]:
            for e in m["elements"]:
                elements[e.get("lifecycle", "approved")] = elements.get(e.get("lifecycle", "approved"), 0) + 1
        changes = wb.store.changes()
        return {
            "version": wb.current_version(),
            "versions": len(wb.versions()),
            "drafts": [{"id": c["id"], "title": c["title"], "required_roles": c["required_roles"], "has_impact": bool(c["impact"])}
                       for c in changes if c["status"] == "draft"],
            "applied": sum(c["status"] == "applied" for c in changes),
            "sources": [{"id": s["id"], "label": s["label"], "lifecycle": s.get("lifecycle"), "interface": s["capability"]["interface"]}
                        for s in cat.sources.values()],
            "exposure_lifecycles": lifecycles,
            "element_lifecycles": elements,
            "identity_attention": sum(1 for x in wb.identity_queue() if x["state"] == "below threshold"),
            "events": wb.store.events(limit=12),
        }

    @app.get("/api/wb/mappings", tags=["workbench"])
    def mappings() -> dict:
        cat, term, _ = wb.objects()
        exposures = [{"source": s["id"], "source_label": s["label"], "source_lifecycle": s.get("lifecycle"), "record_class": e["record_class"],
                      "native": e["native"], "code_system": e.get("code_system"), **e["mapping"]}
                     for s in cat.sources.values() for e in s["exposes"]]
        maps = []
        for m in term.data["concept_maps"]:
            els = []
            for e in m["elements"]:
                tgt = term.medicines.get(e["target"], {}).get("display") if m["target"] == "urn:demo:dmd" else term.display(m["target"], e["target"])
                els.append({**e, "lifecycle": e.get("lifecycle", "approved"), "target_display": tgt})
            maps.append({k: m[k] for k in ("id", "version", "lifecycle", "source", "target")} | {"author": m.get("author"), "elements": els,
                        "source_name": term.system_names.get(m["source"], m["source"]), "target_name": term.system_names.get(m["target"], m["target"])})
        return {"exposures": exposures, "concept_maps": maps}

    @app.get("/api/wb/identity", tags=["workbench"])
    def identity() -> list[dict]:
        return wb.identity_queue()

    @app.get("/api/wb/sources", tags=["workbench"])
    def sources() -> list[dict]:
        return list(wb.objects()[0].sources.values())

    @app.post("/api/wb/sources/{source_id}/conformance", tags=["workbench"])
    async def retest(source_id: str) -> dict:
        return await wb.conformance_live(source_id)

    @app.get("/api/wb/changes", tags=["workbench"])
    def changes() -> list[dict]:
        return wb.changes()

    @app.get("/api/wb/changes/{cid}", tags=["workbench"])
    def change(cid: int) -> dict:
        return wb.change(cid)

    @app.post("/api/wb/changes", tags=["workbench"])
    def new_change(body: NewChange, x_persona: str = Header("analyst")) -> dict:
        return wb.create_change(x_persona, body.title, body.rationale, body.ops)

    @app.post("/api/wb/changes/{cid}/impact", tags=["workbench"])
    async def impact(cid: int) -> dict:
        return await wb.impact(cid)

    @app.post("/api/wb/changes/{cid}/conformance/{source_id}", tags=["workbench"])
    async def conformance(cid: int, source_id: str) -> dict:
        return await wb.conformance(cid, source_id)

    @app.post("/api/wb/changes/{cid}/approve", tags=["workbench"])
    def approve(cid: int, body: Decision, x_persona: str = Header(...)) -> dict:
        return wb.approve(cid, x_persona, body.text)

    @app.post("/api/wb/changes/{cid}/reject", tags=["workbench"])
    def reject(cid: int, body: Decision, x_persona: str = Header(...)) -> dict:
        return wb.reject(cid, x_persona, body.text)

    @app.get("/api/wb/onboarding", tags=["workbench"])
    def packs() -> list[str]:
        return sorted(p.stem for p in (ROOT / "onboarding").glob("*.json"))

    @app.post("/api/wb/onboarding/{name}", tags=["workbench"])
    def import_pack(name: str, x_persona: str = Header("analyst")) -> dict:
        if name not in packs():
            raise HTTPException(status_code=404, detail=f"No onboarding pack {name!r}")
        return wb.import_pack(x_persona, name)

    @app.get("/api/wb/versions", tags=["workbench"])
    def versions() -> list[dict]:
        return wb.versions()

    @app.get("/api/wb/versions/{a}/diff/{b}", tags=["workbench"])
    def version_diff(a: int, b: int) -> list[dict]:
        return wb.version_diff(a, b)

    @app.get("/api/wb/requests", tags=["workbench"])
    def requests(limit: int = 30) -> list[dict]:
        return wb.store.requests(limit)

    @app.post("/api/wb/replay/{request_id}", tags=["workbench"])
    async def replay(request_id: str, version: int | None = Query(None)) -> dict:
        return await wb.replay(request_id, version)

    @app.get("/api/wb/events", tags=["workbench"])
    def events(limit: int = 100) -> list[dict]:
        return wb.store.events(limit=limit)

    return app


def default_store() -> Store:
    return Store(os.environ.get("FWB_STORE", ".fwb/controlplane.db"))


app = create_app(Workbench(default_store()))
