"""The single serialisable structure the Observatory exposes.

Why one snapshot type
---------------------
The terminal view, the future web view, and the tests should not each invent
their own notion of "what the Observatory currently knows". They all render this
one object. That means the future browser UI is a rendering concern only: it
subscribes to snapshots over a socket or an HTTP endpoint and never reads the
event log itself.

The snapshot is therefore the API. ``observatory.api.json_snapshot`` is the
contract, and it is stable enough to build a client against before the client
exists.

Nothing in the snapshot is synthesised. If a field is present, it came from an
event or from the subject registry; if a value is absent, the corresponding
epistemic status is recorded instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from observatory.attribution import Attribution
from observatory.derive import StateDeriver
from observatory.graph import StateGraph, build_graph
from observatory.model import CognitiveState
from observatory.reader import ObservatoryReader
from observatory.subject import SubjectRegistry

#: Version of the snapshot envelope. Clients should check it.
SNAPSHOT_SCHEMA = "babylab/observatory-snapshot/v1"


@dataclass
class ObservatorySnapshot:
    """Everything a view needs, at one instant."""

    subject_status: str
    subject_banner: str
    subject_detail: str | None
    state: CognitiveState
    graph: StateGraph
    recent_events: list[Attribution] = field(default_factory=list)
    ingest: dict[str, int] = field(default_factory=dict)
    reader_state: dict[str, Any] = field(default_factory=dict)
    deriver_stats: dict[str, int] = field(default_factory=dict)
    faults: list[str] = field(default_factory=list)
    generated_at: str = ""
    #: Milestone 003: what the birth subsystem reports. Read-only, and present
    #: even when it says nothing is installed, because "no model, no subject" is
    #: the most important thing this display has to be able to say.
    birth: dict[str, Any] = field(default_factory=dict)
    #: Milestone 004: the measured trust boundary, supplied by the caller.
    #: A plain dict on purpose. The Observatory is a *view*; letting it measure
    #: the boundary itself would create a second source of truth for the single
    #: most safety-critical claim in the system. An absent key renders as
    #: UNAVAILABLE in the trust-boundary section rather than as a default that
    #: could be mistaken for a measurement.
    trust: dict[str, Any] = field(default_factory=dict)
    #: Milestone 005: the measured OS boundary. Same discipline as ``trust`` --
    #: a plain dict supplied by the caller, never computed by the view, and an
    #: absent key renders as UNAVAILABLE rather than as an inferred value.
    os_boundary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """The serialisable form. This is the API contract."""
        return {
            "schema": SNAPSHOT_SCHEMA,
            "generated_at": self.generated_at,
            "subject": {
                "status": self.subject_status,
                "banner": self.subject_banner,
                "detail": self.subject_detail,
            },
            "birth": dict(self.birth),
            "trust": dict(self.trust),
            "os_boundary": dict(self.os_boundary),
            "state": self.state.to_dict(),
            "graph": self.graph.to_dict(),
            "recent_events": [a.to_dict() for a in self.recent_events],
            "ingest": self.ingest,
            "reader": self.reader_state,
            "deriver": self.deriver_stats,
            "faults": list(self.faults),
        }

    def traceable_event_ids(self) -> list[str]:
        """Every event ID any displayed element depends on.

        A view that shows a number can call this and offer the reader the
        provenance of the number. If a value is displayed whose event IDs do not
        appear here, it came from nowhere, which is the bug this method exists
        to make detectable (§14).
        """
        ids = set(self.state.all_source_event_ids())
        for node in self.graph.nodes.values():
            ids.update(node.source_event_ids)
        for edge in self.graph.edges:
            ids.update(edge.source_event_ids)
        # The record-events section displays event IDs directly, so those are
        # displayed elements too and must be traceable like anything else.
        for attribution in self.recent_events:
            ids.add(attribution.event_id)
        # The birth section displays the id of the event that announced the
        # birth, so that id is displayed and must be traceable too.
        birth_event_id = self.birth.get("birth_event_id")
        if birth_event_id:
            ids.add(str(birth_event_id))
        return sorted(ids)


def compose_snapshot(
    registry: SubjectRegistry,
    reader: ObservatoryReader,
    deriver: StateDeriver,
    *,
    now: float = 0.0,
    timestamp: str = "",
    recent_attributions: list[Attribution] | None = None,
    faults: list[str] | None = None,
    birth: dict[str, Any] | None = None,
) -> ObservatorySnapshot:
    """Build a snapshot from the three collaborating components.

    Passed in rather than constructed internally, so tests and the future API
    can compose a snapshot from recorded inputs without a live event store.
    """
    state = deriver.snapshot(now, timestamp=timestamp)
    return ObservatorySnapshot(
        subject_status=registry.status.value,
        subject_banner=registry.describe(),
        subject_detail=registry.detail(),
        state=state,
        graph=build_graph(state),
        recent_events=list(recent_attributions or []),
        ingest=reader.state(),
        reader_state=reader.state(),
        deriver_stats=deriver.stats(),
        faults=list(faults or []),
        generated_at=timestamp,
        birth=dict(birth or {}),
    )
