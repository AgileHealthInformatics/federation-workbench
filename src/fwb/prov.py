"""W3C PROV export (PROV-JSON shape).

Statements are entities derived from native values through mapping and
transformation activities; reconciled entries are entities derived from their
member statements through a reconciliation activity, so a clinician-facing
line can be traced back to every native record behind it.
"""

from __future__ import annotations

from typing import Any

from .models import PatientRecord


def to_prov(record: PatientRecord) -> dict[str, Any]:
    entity: dict[str, Any] = {}
    activity: dict[str, Any] = {}
    agent: dict[str, Any] = {"fwb:broker": {"prov:type": "prov:SoftwareAgent", "fwb:catalogueVersion": record.catalogue_version}}
    gen: dict[str, Any] = {}
    der: dict[str, Any] = {}
    assoc: dict[str, Any] = {}

    for s in record.sources:
        agent[f"fwb:source/{s.source}"] = {"prov:type": "prov:Organization", "prov:label": s.label}

    for st in record.statements:
        native = f"fwb:native/{st.id}"
        stmt = f"fwb:statement/{st.id}"
        retrieval = f"fwb:retrieval/{record.request_id}/{st.source}"
        entity[native] = {"fwb:sourceRecord": st.record_id, "prov:value": st.value, "fwb:code": st.native_code.code if st.native_code else None}
        entity[stmt] = {"fwb:concept": st.concept.code if st.concept else None, "fwb:grade": st.grade.value,
                        "prov:value": st.rendered_value if st.rendered_value is not None else st.value}
        activity.setdefault(retrieval, {"prov:type": "fwb:Retrieval", "prov:endTime": st.retrieved_at.isoformat()})
        assoc[f"_:a-{st.id}"] = {"prov:activity": retrieval, "prov:agent": f"fwb:source/{st.source}"}
        gen[f"_:g-{st.id}"] = {"prov:entity": native, "prov:activity": retrieval}
        prev = native
        for n, step in enumerate(st.transformation_chain):
            act = f"fwb:{step.kind}/{step.id}@{step.version}"
            activity.setdefault(act, {"prov:type": f"fwb:{step.kind}", "prov:label": step.detail})
            nxt = stmt if n == len(st.transformation_chain) - 1 else f"fwb:intermediate/{st.id}/{n}"
            entity.setdefault(nxt, {})
            der[f"_:d-{st.id}-{n}"] = {"prov:generatedEntity": nxt, "prov:usedEntity": prev, "prov:activity": act}
            prev = nxt

    for sec in record.sections:
        for e in sec.entries:
            ent = f"fwb:entry/{e.id}"
            act = f"fwb:reconciliation/{record.request_id}/{e.id}"
            entity[ent] = {"prov:label": e.display, "fwb:reconciliation": e.reconciliation, "fwb:flags": e.flags}
            activity[act] = {"prov:type": "fwb:Reconciliation"}
            assoc[f"_:a-{e.id}"] = {"prov:activity": act, "prov:agent": "fwb:broker"}
            for m in e.members:
                der[f"_:r-{e.id}-{m}"] = {"prov:generatedEntity": ent, "prov:usedEntity": f"fwb:statement/{m}", "prov:activity": act}

    return {
        "prefix": {"prov": "http://www.w3.org/ns/prov#", "fwb": "urn:fwb:"},
        "entity": entity, "activity": activity, "agent": agent,
        "wasGeneratedBy": gen, "wasDerivedFrom": der, "wasAssociatedWith": assoc,
    }
