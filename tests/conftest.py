from __future__ import annotations

import asyncio
import os

os.environ.setdefault("FWB_STORE", ":memory:")
os.environ.setdefault("FWB_IMAGING_DELAY", "0.1")  # let the slow imaging mock answer, to keep the suite quick

import pytest  # noqa: E402

from fwb.controlplane.store import Store  # noqa: E402
from fwb.controlplane.workbench import Workbench  # noqa: E402
from fwb.sources import state  # noqa: E402


@pytest.fixture
def wb() -> Workbench:
    """A fresh control plane with the seeded demo change requests."""
    return Workbench(Store(":memory:"))


@pytest.fixture(autouse=True)
def no_outages():
    state.OFFLINE.clear()
    yield
    state.OFFLINE.clear()


def run(coro):
    return asyncio.run(coro)


def cr_by_title(wb: Workbench, fragment: str) -> int:
    return next(c["id"] for c in wb.changes() if fragment in c["title"])


def changes_for(impact_or_diff, name: str | None = None):
    people = impact_or_diff["people"] if "people" in impact_or_diff else [impact_or_diff]
    return [c for p in people if name is None or p["name"] == name for c in p["changes"]]
