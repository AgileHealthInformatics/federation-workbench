"""One adapter per interface pattern: a new source of a known pattern joins by
catalogue configuration, not code."""

from .base import WINDOWED, Adapter, AdapterResponse, RawStatement, SubRequest
from .dicomweb import DicomWebReportsAdapter
from .eventfeed import EventFeedAdapter
from .fhir import FhirSearchAdapter
from .openehr import OpenEhrAqlAdapter
from .sql import SqlServiceAdapter

REGISTRY: dict[str, Adapter] = {
    "sql-service": SqlServiceAdapter(),
    "openehr-aql": OpenEhrAqlAdapter(),
    "fhir-r4-search": FhirSearchAdapter(),
    "event-feed": EventFeedAdapter(),
    "dicomweb-reports": DicomWebReportsAdapter(),
}

__all__ = ["REGISTRY", "WINDOWED", "Adapter", "AdapterResponse", "RawStatement", "SubRequest"]
