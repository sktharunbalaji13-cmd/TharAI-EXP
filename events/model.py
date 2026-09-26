"""The event model: the primary observable record of the experiment.

Design constraints
------------------
1. **Append-only.** An event, once written, is never edited. Corrections are
   new events that reference the old one.
2. **Self-describing.** Every event validates against a fixed shape without
   reference to external schema files, so a reader from ten years ago can
   still parse the log.
3. **Extensible but not vague.** ``event_type`` is a dotted
   ``namespace.action`` string. Milestone 001 registers only infrastructure
   namespaces. No developmental, cognitive or goal-related vocabulary is
   pre-registered, because pre-registering it would quietly imply a
   developmental curriculum (docs/research-principles.md).
4. **Tamper-evident.** Each event carries the hash of its predecessor, forming
   a chain. Rewriting or deleting a historical event breaks the chain at that
   point and every point after it.

See docs/event-model.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from babylab.clock import format_timestamp, parse_timestamp
from babylab.errors import ValidationError
from babylab.hashing import canonical_bytes, sha256_hex

#: ``EVENT-`` followed by at least six digits. Width grows naturally past
#: 999999 rather than wrapping and colliding with an existing identifier.
EVENT_ID_RE = re.compile(r"^EVENT-\d{6,}$")

#: ``namespace.action``, lowercase words separated by single dots.
EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

#: Fields that constitute the hashed body of an event, in canonical order.
HASHED_FIELDS = ("event_id", "seq", "timestamp", "event_type", "source", "payload", "prev_hash")

#: Namespaces registered by Milestone 001. This list is deliberately limited to
#: laboratory infrastructure. It is documentation, not a whitelist: any
#: syntactically valid event type is accepted, because the point of the
#: experiment is not to know in advance what events will occur.
INFRASTRUCTURE_NAMESPACES = ("system", "security", "provenance", "control", "observer", "trust")


@dataclass(frozen=True)
class Event:
    """A single immutable observation.

    Attributes
    ----------
    event_id:
        Monotonic identifier, ``EVENT-000001`` style.
    seq:
        Integer sequence number, equal to the numeric part of ``event_id``.
        Carried separately so that ordering survives lexicographic sorting
        subtleties in downstream tooling.
    timestamp:
        RFC 3339 UTC, millisecond precision.
    event_type:
        Dotted ``namespace.action`` string.
    source:
        Dotted component name that produced the event, e.g. ``"observer"`` or
        ``"control.server"``. This is a component name, not an authorship
        claim; authorship lives in the provenance ledger.
    payload:
        JSON object with event-specific detail.
    prev_hash:
        ``hash`` of the preceding event, or 64 zeros for the first event.
    hash:
        SHA-256 over the canonical encoding of :data:`HASHED_FIELDS`.
    """

    event_id: str
    seq: int
    timestamp: str
    event_type: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    prev_hash: str = "0" * 64
    hash: str = ""

    # -- construction -----------------------------------------------------
    @classmethod
    def create(
        cls,
        seq: int,
        event_type: str,
        source: str,
        payload: dict[str, Any] | None = None,
        moment=None,
        prev_hash: str = "0" * 64,
    ) -> "Event":
        """Build a complete, sealed, validated event."""
        from babylab.clock import Clock

        if seq < 1:
            raise ValidationError(f"seq must be >= 1, got {seq}")
        timestamp = format_timestamp(moment) if moment is not None else Clock().timestamp()
        event = cls(
            event_id=format_event_id(seq),
            seq=seq,
            timestamp=timestamp,
            event_type=event_type,
            source=source,
            payload=dict(payload or {}),
            prev_hash=prev_hash,
            hash="",
        )
        event.validate()
        return event.seal()

    # -- serialisation ----------------------------------------------------
    def hashed_body(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in HASHED_FIELDS}

    def compute_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.hashed_body()))

    def seal(self) -> "Event":
        """Return a copy with ``hash`` populated.

        Idempotent: ``hash`` is not part of :data:`HASHED_FIELDS`, so sealing
        a sealed event reproduces the same digest.
        """
        sealed = self.compute_hash()
        return Event(**{**self.__dict__, "hash": sealed})

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "source": self.source,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
            "hash": self.hash,
        }

    def to_json(self) -> str:
        """Canonical single-line JSON, ready for JSON Lines output."""
        from babylab.hashing import canonical_json

        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Any) -> "Event":
        event = cls(
            event_id=_require_str(data, "event_id"),
            seq=_require_int(data, "seq"),
            timestamp=_require_str(data, "timestamp"),
            event_type=_require_str(data, "event_type"),
            source=_require_str(data, "source"),
            payload=_require_dict(data, "payload"),
            prev_hash=_require_str(data, "prev_hash"),
            hash=_require_str(data, "hash"),
        )
        event.validate_sealed()
        return event

    @classmethod
    def from_json(cls, text: str) -> "Event":
        import json

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"line is not valid JSON: {exc}") from exc
        return cls.from_dict(data)

    # -- validation -------------------------------------------------------
    def validate(self) -> None:
        """Validate an event that may not yet be sealed.

        An empty ``hash`` is permitted here because it means "not sealed yet".
        Anything read back from the store is checked with
        :meth:`validate_sealed`, which does not permit it.
        """
        if not isinstance(self.seq, int) or isinstance(self.seq, bool):
            raise ValidationError(f"seq must be an integer, got {self.seq!r}")
        if not EVENT_ID_RE.match(str(self.event_id)):
            raise ValidationError(
                f"event_id {self.event_id!r} does not match EVENT-<digits>"
            )
        if int(str(self.event_id).split("-")[1]) != self.seq:
            raise ValidationError(
                f"event_id {self.event_id!r} disagrees with seq {self.seq}"
            )
        try:
            parse_timestamp(self.timestamp)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if not EVENT_TYPE_RE.match(str(self.event_type)):
            raise ValidationError(
                f"event_type {self.event_type!r} must be dotted lowercase, "
                f"e.g. 'system.started'"
            )
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValidationError("source must be a non-empty string")
        if not isinstance(self.payload, dict):
            raise ValidationError(
                f"payload must be a JSON object, got {type(self.payload).__name__}"
            )
        if not re.match(r"^[0-9a-f]{64}$", str(self.prev_hash)):
            raise ValidationError("prev_hash must be 64 lowercase hex characters")
        if self.hash and not re.match(r"^[0-9a-f]{64}$", str(self.hash)):
            raise ValidationError("hash must be 64 lowercase hex characters")

    def validate_sealed(self) -> None:
        """Validate an event read back from durable storage."""
        self.validate()
        if not self.hash:
            raise ValidationError("stored event has no hash; it was never sealed")

    def namespace(self) -> str:
        return self.event_type.split(".", 1)[0]

    def headline(self) -> str:
        """Single-line human summary for the terminal observer.

        Producers may supply ``payload.headline`` for a nicer sentence. When
        they do not, the observer renders the event type on its own rather than
        this module inventing prose. Infrastructure should not narrate, and
        inventing a narrative here would risk the log describing things that
        did not happen.
        """
        value = self.payload.get("headline")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return self.event_type


def format_event_id(seq: int) -> str:
    return f"EVENT-{seq:06d}"


def parse_event_id(event_id: str) -> int:
    match = EVENT_ID_RE.match(str(event_id))
    if match is None:
        raise ValidationError(f"malformed event_id {event_id!r}")
    return int(str(event_id).split("-")[1])


# -- field coercion helpers ------------------------------------------------
def _require_str(data: dict, name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str):
        raise ValidationError(f"field {name!r} must be a string, got {value!r}")
    return value


def _require_int(data: dict, name: str) -> int:
    value = data.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"field {name!r} must be an integer, got {value!r}")
    return value


def _require_dict(data: dict, name: str) -> dict:
    value = data.get(name)
    if not isinstance(value, dict):
        raise ValidationError(f"field {name!r} must be an object, got {value!r}")
    return value
