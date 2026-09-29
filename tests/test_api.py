"""HTTP API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fwb.api import create_app
from fwb.controlplane.store import Store
from fwb.controlplane.workbench import Workbench
from fwb.scenario import record_request


@pytest.fixture
def client():
    return TestClient(create_app(Workbench(Store(":memory:"))))


def body(**kw):
    kw.setdefault("deadline_seconds", 0.5)
    return record_request(**kw).model_dump(mode="json")


def test_pages_and_health(client):
    assert client.get("/api/health").json()["catalogue_version"] == "v1"
    assert "Federated Patient Record" in client.get("/").text
    assert "Control-Plane Workbench" in client.get("/workbench").text


def test_full_change_flow_over_http(client):
    changes = client.get("/api/wb/changes").json()
    cid = next(c["id"] for c in changes if "vital-signs" in c["title"])
    assert client.post(f"/api/wb/changes/{cid}/approve", json={"text": "Approved after review."}, headers={"X-Persona": "cso"}).status_code == 409
    imp = client.post(f"/api/wb/changes/{cid}/impact").json()
    assert imp["base_version"] == 1
    r = client.post(f"/api/wb/changes/{cid}/approve", json={"text": "Approved after review."}, headers={"X-Persona": "cso"})
    assert r.status_code == 200 and r.json()["applied_version"] == 2
    assert client.post("/api/record", json=body()).json()["catalogue_version"] == "v2"
    assert client.post("/api/record?version=1", json=body()).json()["catalogue_version"] == "v1"
    assert client.get("/api/wb/versions/1/diff/2").json()[0]["area"] == "record-class mapping"


def test_create_change_validation(client):
    r = client.post("/api/wb/changes", json={"title": "x", "ops": [{"op": "nonsense"}]}, headers={"X-Persona": "analyst"})
    assert r.status_code == 422
    r = client.post("/api/wb/changes", json={"title": "Suspend imaging", "rationale": "Maintenance",
                                             "ops": [{"op": "set_source_lifecycle", "source": "imaging", "lifecycle": "suspended"}]},
                    headers={"X-Persona": "analyst"})
    assert r.status_code == 200 and r.json()["required_roles"] == ["clinical-safety-officer"]


def test_onboarding_and_conformance_endpoints(client):
    assert client.get("/api/wb/onboarding").json() == ["gp-legacy"]
    c = client.post("/api/wb/onboarding/gp-legacy", headers={"X-Persona": "analyst"}).json()
    assert c["newly_live"] == ["gp-legacy"]
    conf = client.post(f"/api/wb/changes/{c['id']}/conformance/gp-legacy").json()
    assert conf["overall"] == "warn"
    assert client.post("/api/wb/sources/gp/conformance").json()["overall"] in ("pass", "warn")


def test_replay_endpoint(client):
    rid = client.post("/api/record", json=body()).json()["request_id"]
    assert rid in [r["request_id"] for r in client.get("/api/wb/requests").json()]
    rp = client.post(f"/api/wb/replay/{rid}").json()
    assert rp["original_version"] == rp["compared_version"] == 1 and rp["record_changes"]["changes"] == []


def test_overview_and_identity(client):
    ov = client.get("/api/wb/overview").json()
    assert ov["version"] == 1 and len(ov["drafts"]) == 4 and ov["identity_attention"] == 1
    q = client.get("/api/wb/identity").json()
    assert q[0]["state"] == "below threshold" and q[0]["person_id"] == "NID-DEMO-1002"
