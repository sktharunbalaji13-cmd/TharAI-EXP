"""Local, append-only event system.

Milestone 001 scope: infrastructure only. No event in this package is
fabricated to look like agent behaviour; every event written during this
milestone describes something the laboratory actually did.
"""

from events.model import (
    EVENT_ID_RE,
    EVENT_TYPE_RE,
    HASHED_FIELDS,
    INFRASTRUCTURE_NAMESPACES,
    Event,
    format_event_id,
    parse_event_id,
)
from events.store import GENESIS_HASH, ChainReport, EventStore, StoredEvent

__all__ = [
    "Event",
    "EventStore",
    "StoredEvent",
    "ChainReport",
    "GENESIS_HASH",
    "EVENT_ID_RE",
    "EVENT_TYPE_RE",
    "HASHED_FIELDS",
    "INFRASTRUCTURE_NAMESPACES",
    "format_event_id",
    "parse_event_id",
]
