"""Command line.

    fwb serve                 # record view on :8000/ and workbench on :8000/workbench
    fwb record                # Jane Smith's record under the current catalogue
    fwb demo                  # scripted walk-through of the governance workflow (in memory)
    fwb reset                 # delete the local control-plane store and re-seed on next start
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


def _store_path() -> str:
    return os.environ.get("FWB_STORE", ".fwb/controlplane.db")


def _print_diff(title: str, people: list[dict]) -> None:
    print(f"\n  {title}")
    for p in people:
        for c in p["changes"]:
            mark = {"hides": "HIDES ", "raises": "RAISES", "visible": "      "}[c["safety"]]
            print(f"    {mark} {p['name']:<11} {c['kind']:<14} {c['section']:<12} {c['item']:<24} {c['detail']}")


async def _demo() -> int:
    from .controlplane.store import Store
    from .controlplane.workbench import GovernanceError, Workbench

    wb = Workbench(Store(":memory:"))
    print(f"Catalogue v{wb.current_version()} seeded. Draft change requests:")
    for c in wb.changes():
        print(f"  #{c['id']}  {c['title']}  (needs: {', '.join(c['required_roles'])})")

    print("\n1. Impact of deprecating Hospital A's amlodipine formulary code (#2)")
    imp = await wb.impact(2)
    _print_diff(f"hides {imp['totals']['hides']}, raises {imp['totals']['raises']}, other {imp['totals']['visible']}", imp["people"])
    wb.reject(2, "cso", "Would hide a stopped-elsewhere discrepancy for a current patient. Map the new code first.")
    print("  -> rejected by the clinical safety officer")

    print("\n2. Onboard the archived previous-practice system (#4)")
    await wb.impact(4)
    for who, text in (("cso", "Read v2 map reviewed."), ("analyst", "Looks fine to me.")):
        try:
            wb.approve(4, who, text)
        except GovernanceError as e:
            print(f"  blocked: {e}")
    conf = await wb.conformance(4, "gp-legacy")
    print(f"  conformance: {conf['overall']}")
    for ch in conf["checks"]:
        print(f"    {ch['id']} {ch['status']:<5} {ch['name']}: {ch['detail']}")
    try:
        wb.approve(4, "analyst", "Looks fine to me, approving.")
    except GovernanceError as e:
        print(f"  blocked: {e}")
    c = wb.approve(4, "cso", "Read v2 map reviewed against source terms; historic-only authority accepted.")
    print(f"  -> applied as catalogue v{c['applied_version']}")
    _print_diff("record changes", c["impact"]["people"])

    print("\n3. Confirm Sam Patel's pharmacy match (#3)")
    await wb.impact(3)
    c = wb.approve(3, "steward", "Verified by phone: DOB and address match.")
    print(f"  -> applied as catalogue v{c['applied_version']}")
    _print_diff("record changes", c["impact"]["people"])

    print("\n4. Replay Jane Smith's record under v1 and compare with now")
    from .scenario import record_request

    rec = await wb.assemble(record_request("NID-DEMO-1001", deadline_seconds=1.0), version=1)
    rp = await wb.replay(rec.request_id)
    print(f"  catalogue v{rp['original_version']} -> v{rp['compared_version']}: {len(rp['catalogue_changes'])} catalogue changes, "
          f"{len(rp['record_changes']['changes'])} record changes")
    return 0


def _record(args: argparse.Namespace) -> int:
    from .controlplane.store import Store
    from .controlplane.workbench import Workbench
    from .scenario import record_request

    wb = Workbench(Store(_store_path()))
    rec = asyncio.run(wb.assemble(record_request(args.subject, deadline_seconds=args.deadline), version=args.version))
    print(f"{rec.demographics.name} (synthetic)  catalogue {rec.catalogue_version}  {rec.overall_status.upper()}")
    for s in rec.sources:
        print(f"  {s.source:<11} {s.status.value:<21} {s.items_returned:>3}  {s.detail}")
    for sec in rec.sections:
        print(f"\n{sec.label.upper()}" + (f"  ({sec.summary})" if sec.summary else ""))
        for e in sec.entries:
            print(f"  {e.display:<34} {e.status or '':<10} {e.reconciliation:<14} {', '.join(e.sources)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="fwb", description="Federation control-plane workbench")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    r = sub.add_parser("record")
    r.add_argument("--subject", default="NID-DEMO-1001")
    r.add_argument("--version", type=int)
    r.add_argument("--deadline", type=float, default=3.0)
    sub.add_parser("demo")
    sub.add_parser("reset")
    args = p.parse_args(argv)
    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("fwb.api:app", host=args.host, port=args.port)
        return 0
    if args.cmd == "reset":
        path = Path(_store_path())
        if path.exists():
            path.unlink()
            print(f"Removed {path}; it will be re-seeded on next start.")
        else:
            print(f"No store at {path}.")
        return 0
    if args.cmd == "demo":
        return asyncio.run(_demo())
    return _record(args)


if __name__ == "__main__":
    sys.exit(main())
