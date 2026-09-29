"""The environment event stream: append-only, hash-chained, externally generated.

Two rules
---------
**The environment runtime writes events; the actor does not.** An action submits
a *request*. What actually happened is recorded by the environment after it
validates and applies. This is what keeps an actor from being able to narrate
itself: the only thing a caller contributes is the request, and the resulting
event is written by code the caller does not control.

**History is never rewritten.** Restoring a snapshot does not truncate or edit
anything; it starts a new branch. The chain is a linked list of hashes, so
altering any past event invalidates every event after it, and
:func:`EventStream.verify` will say so.

Payload discipline
------------------
Events carry digests and identifiers, not bulk state. A raw observation dumped
into the chain would make it expensive to verify and would turn an audit log
into a data store. The state a transition refers to is identified by its hash;
the state itself lives in the environment.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Iterable

from babylab.hashing import canonical_bytes, sha256_hex

#: The zero hash that anchors the chain.
GENESIS_HASH = "0" * 64

#: Event source. A component name, not an authorship claim -- authorship for
#: environment facts is SYSTEM, recorded in the provenance ledger.
ENVIRONMENT_SOURCE = "babylab.environment"


class EventType(str, enum.Enum):
    """The complete set of things an environment can record."""

    ENVIRONMENT_CREATED = "environment_created"
    OBSERVATION_GENERATED = "observation_generated"
    ACTION_REQUESTED = "action_requested"
    ACTION_VALIDATED = "action_validated"
    ACTION_REJECTED = "action_rejected"
    ACTION_APPLIED = "action_applied"
    STATE_TRANSITIONED = "state_transitioned"
    RESOURCE_CHANGED = "resource_changed"
    SNAPSHOT_CREATED = "snapshot_created"
    SNAPSHOT_RESTORED = "snapshot_restored"
    ENVIRONMENT_FAULT = "environment_fault"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class EnvironmentEvent:
    """One immutable fact about what the environment did."""

    event_id: str
    sequence: int
    timestamp: str
    event_type: EventType
    environment_id: str
    state_version: int
    state_hash: str
    prev_hash: str
    payload: dict[str, Any] = field(default_factory=dict)
    #: Set on events produced inside a branch, so lineage is visible in the log.
    branch_id: str = "main"
    event_hash: str = ""

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id must be a non-empty string")
        object.__setattr__(self, "payload", dict(self.payload))

    def hashed_fields(self) -> dict[str, Any]:
        """Exactly the fields covered by the chain hash.

        Deliberately excludes ``event_hash`` itself, and deliberately excludes
        nothing else. If a field were left out, editing it would not break the
        chain -- so the exclusion list is kept to the minimum that is logically
        necessary.
        """
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "event_type": self.event_type.value,
            "environment_id": self.environment_id,
            "state_version": self.state_version,
            "state_hash": self.state_hash,
            "prev_hash": self.prev_hash,
            "payload": self.payload,
            "branch_id": self.branch_id,
        }

    def compute_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.hashed_fields()))

    def to_dict(self) -> dict[str, Any]:
        return {**self.hashed_fields(), "event_hash": self.event_hash}


class ChainVerification:
    """Result of checking the event chain."""

    def __init__(self, intact: bool, checked: int, problems: list[str]) -> None:
        self.intact = intact
        self.checked = checked
        self.problems = problems

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return self.intact

    def to_dict(self) -> dict[str, Any]:
        return {
            "intact": self.intact,
            "checked": self.checked,
            "problems": list(self.problems),
        }


class EventStream:
    """Append-only chain of environment events.

    There is no ``update``, ``delete`` or ``truncate``. Restoring a snapshot
    appends; it does not rewind.
    """

    def __init__(self, environment_id: str) -> None:
        self._environment_id = environment_id
        self._events: list[EnvironmentEvent] = []
        self._branch_id = "main"

    # -- appending -------------------------------------------------------
    def append(
        self,
        event_type: EventType,
        *,
        timestamp: str,
        state_version: int,
        state_hash: str,
        payload: dict[str, Any] | None = None,
        branch_id: str | None = None,
    ) -> EnvironmentEvent:
        """Record one event. The only way anything enters the stream."""
        previous = self._events[-1].event_hash if self._events else GENESIS_HASH
        sequence = len(self._events) + 1
        event = EnvironmentEvent(
            event_id=f"{self._environment_id}-e{sequence:06d}",
            sequence=sequence,
            timestamp=timestamp,
            event_type=event_type,
            environment_id=self._environment_id,
            state_version=state_version,
            state_hash=state_hash,
            prev_hash=previous,
            payload=dict(payload or {}),
            branch_id=branch_id or self._branch_id,
        )
        sealed = EnvironmentEvent(
            **{**event.hashed_fields(), "event_type": event.event_type,
               "payload": event.payload, "event_hash": event.compute_hash()},
        )
        self._events.append(sealed)
        return sealed

    def set_branch(self, branch_id: str) -> None:
        """Subsequent events belong to a branch. Never edits past events."""
        self._branch_id = branch_id

    @property
    def branch_id(self) -> str:
        return self._branch_id

    # -- reading ---------------------------------------------------------
    def events(self) -> tuple[EnvironmentEvent, ...]:
        return tuple(self._events)

    def of_type(self, event_type: EventType) -> tuple[EnvironmentEvent, ...]:
        return tuple(e for e in self._events if e.event_type is event_type)

    def by_id(self, event_id: str) -> EnvironmentEvent | None:
        for event in self._events:
            if event.event_id == event_id:
                return event
        return None

    def __len__(self) -> int:
        return len(self._events)

    # -- integrity -------------------------------------------------------
    def verify(self) -> ChainVerification:
        """Re-derive every hash and check the links.

        A rewritten event shows up here as either a changed hash or a broken
        ``prev_hash`` link, which is the point: the chain is what makes history
        tamper-evident even though this process can still hold the objects in
        memory.
        """
        problems: list[str] = []
        previous = GENESIS_HASH
        for index, event in enumerate(self._events, start=1):
            if event.sequence != index:
                problems.append(
                    f"event {event.event_id} has sequence {event.sequence}, "
                    f"expected {index}"
                )
            if event.prev_hash != previous:
                problems.append(
                    f"event {event.event_id} does not link to its predecessor"
                )
            recomputed = event.compute_hash()
            if recomputed != event.event_hash:
                problems.append(
                    f"event {event.event_id} hash does not match its contents; "
                    "the event was altered after it was recorded"
                )
            previous = event.event_hash
        return ChainVerification(not problems, len(self._events), problems)

    def branch_ids(self) -> tuple[str, ...]:
        seen: list[str] = []
        for event in self._events:
            if event.branch_id not in seen:
                seen.append(event.branch_id)
        return tuple(seen)

    def export(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self._events]

    @classmethod
    def rehydrate(cls, environment_id: str, exported: Iterable[dict[str, Any]]) -> "EventStream":
        """Rebuild a stream from exported events, preserving the chain.

        Used to verify a stored stream offline. The events are re-created
        verbatim -- including their recorded hashes -- so :meth:`verify` then
        reports honestly whether the stored history is intact.
        """
        stream = cls(environment_id)
        for payload in exported:
            stream._events.append(EnvironmentEvent(
                event_id=payload["event_id"],
                sequence=payload["sequence"],
                timestamp=payload["timestamp"],
                event_type=EventType(payload["event_type"]),
                environment_id=payload["environment_id"],
                state_version=payload["state_version"],
                state_hash=payload["state_hash"],
                prev_hash=payload["prev_hash"],
                payload=payload["payload"],
                branch_id=payload.get("branch_id", "main"),
                event_hash=payload["event_hash"],
            ))
        if stream._events:
            stream._branch_id = stream._events[-1].branch_id
        return stream


__all__ = [
    "ENVIRONMENT_SOURCE",
    "GENESIS_HASH",
    "ChainVerification",
    "EnvironmentEvent",
    "EventStream",
    "EventType",
]
