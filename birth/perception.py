"""Sensor evidence and the interpretation of it, kept apart.

The separation this module exists to maintain
---------------------------------------------
Three different things, routinely confused, each with its own record:

1. **Foundation** — a raw reading from a named sensor: what was measured, by
   what, with what units and uncertainty. :class:`FoundationEvidence`.
2. **Interpretation** — this laboratory's reading of that evidence: "that is a
   cup", "the surface is hot". :class:`Interpretation`.
3. **Representation** — anything internal to a subject. Not modelled here, and
   the absence is deliberate.

The rule: an :class:`Interpretation` must name the evidence it came from. A
claim that cannot be traced to a foundation reading is not an interpretation of
that evidence; it is an assertion, and the field it belongs in is
``unsupported_assertion`` on the interpretation record, where it is visible.

An example of what not to do
----------------------------
Sensor reports ``{"reflectance": 0.72}`` at 620 nm. Writing "this is a red
object" is an interpretation, not a measurement, and its confidence is a guess.
Writing "this object is a cup" is an interpretation of a *shape* reading, and
needs a shape reading to exist. Neither is a foundation fact. :func:`interpret`
will happily accept both, provided each names its input, and will reject either
if it does not.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Any

from babylab.clock import Clock, format_timestamp
from babylab.errors import ValidationError
from babylab.hashing import canonical_bytes, sha256_hex

FOUNDATION_EVIDENCE_SCHEMA = "babylab/foundation-evidence/v1"
INTERPRETATION_SCHEMA = "babylab/interpretation/v1"


class EvidenceKind(str, enum.Enum):
    """What sort of foundation evidence this is.

    These are physical modalities, not meanings. There is no ``OBJECT`` member,
    because "object" is an interpretation and listing it here would invite one.
    """

    IMAGE = "IMAGE"
    DEPTH = "DEPTH"
    AUDIO = "AUDIO"
    TEXT = "TEXT"
    PROXIMITY = "PROXIMITY"
    TEMPERATURE = "TEMPERATURE"
    FORCE = "FORCE"
    LIGHT = "LIGHT"
    OTHER = "OTHER"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass(frozen=True)
class FoundationEvidence:
    """A raw sensor reading, and nothing more.

    ``readings`` is whatever the sensor reported: numbers with units, an image
    digest, a waveform summary. It is stored verbatim so that a later
    interpretation can be re-derived and checked against the original.
    """

    evidence_id: str
    sensor_id: str
    kind: EvidenceKind
    readings: dict[str, Any]
    captured_at: str = ""
    source: str = "birth.perception"
    digest: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    schema: str = FOUNDATION_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ValidationError("evidence_id must be a non-empty string")
        if not self.sensor_id.strip():
            raise ValidationError(
                "sensor_id must be non-empty. Unsourced evidence cannot be "
                "interpreted, because there is nothing to check the reading "
                "against."
            )
        if not isinstance(self.readings, dict) or not self.readings:
            raise ValidationError(
                "readings must be a non-empty object; empty evidence is not evidence"
            )
        if not self.digest:
            object.__setattr__(self, "digest", self.compute_digest())

    def compute_digest(self) -> str:
        return sha256_hex(
            canonical_bytes(
                {
                    "sensor_id": self.sensor_id,
                    "kind": self.kind.value,
                    "readings": self.readings,
                    "captured_at": self.captured_at,
                }
            )
        )

    def verify_digest(self) -> bool:
        return self.compute_digest() == self.digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "evidence_id": self.evidence_id,
            "sensor_id": self.sensor_id,
            "kind": self.kind.value,
            "readings": self.readings,
            "captured_at": self.captured_at,
            "source": self.source,
            "digest": self.digest,
            "metadata": dict(self.metadata),
        }

    def to_event_payload(self) -> dict[str, Any]:
        """Payload for an ``observation.recorded`` event.

        The full reading travels in the event log. Readings are small by
        construction; if a future sensor produces something large, it belongs in
        ``var/`` with a digest in the event, and that change should be made
        deliberately.
        """
        return {
            "headline": f"Foundation evidence recorded from {self.sensor_id}",
            "evidence_id": self.evidence_id,
            "sensor_id": self.sensor_id,
            "kind": self.kind.value,
            "digest": self.digest,
            "captured_at": self.captured_at,
            "readings": self.readings,
        }


@dataclass(frozen=True)
class Interpretation:
    """This laboratory's reading of foundation evidence.

    ``derived_from`` is required and must be non-empty. An interpretation with no
    named input is not a reading of anything, and requiring the field is how that
    gets caught at construction time rather than a year into the analysis.
    """

    interpretation_id: str
    claim: str
    derived_from: tuple[str, ...]
    confidence: float | None = None
    kind: EvidenceKind = EvidenceKind.OTHER
    method: str = ""
    made_by: str = "system:lab"
    timestamp: str = ""
    unsupported_assertion: bool = False
    schema: str = INTERPRETATION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "derived_from", tuple(self.derived_from))
        if not self.interpretation_id:
            raise ValidationError("interpretation_id must be a non-empty string")
        if not self.claim.strip():
            raise ValidationError("claim must be a non-empty string")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValidationError(
                f"confidence must be within [0, 1] or None when unmeasured, got "
                f"{self.confidence}"
            )
        if not self.derived_from:
            object.__setattr__(self, "unsupported_assertion", True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interpretation_id": self.interpretation_id,
            "claim": self.claim,
            "kind": self.kind.value,
            "derived_from": list(self.derived_from),
            "confidence": self.confidence,
            "method": self.method,
            "made_by": self.made_by,
            "timestamp": self.timestamp,
            "unsupported_assertion": self.unsupported_assertion,
        }

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "headline": f"Interpretation recorded: {self.claim[:60]}",
            "interpretation_id": self.interpretation_id,
            "claim": self.claim,
            "kind": self.kind.value,
            "derived_from": list(self.derived_from),
            "confidence": self.confidence,
            "unsupported_assertion": self.unsupported_assertion,
            "made_by": self.made_by,
        }


def record_evidence(
    sensor_id: str,
    kind: EvidenceKind,
    readings: dict[str, Any],
    now: Any = None,
    evidence_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> FoundationEvidence:
    """Record a raw sensor reading. No interpretation happens here."""
    moment = now if now is not None else Clock().now()
    return FoundationEvidence(
        evidence_id=evidence_id or f"EVID-{uuid.uuid4().hex[:12]}",
        sensor_id=sensor_id,
        kind=kind,
        readings=dict(readings),
        captured_at=format_timestamp(moment),
        metadata=dict(metadata or {}),
    )


def interpret(
    claim: str,
    derived_from: list[str] | tuple[str, ...] = (),
    evidence: list[FoundationEvidence] | None = None,
    confidence: float | None = None,
    method: str = "",
    kind: EvidenceKind = EvidenceKind.OTHER,
    made_by: str = "system:lab",
    now: Any = None,
    interpretation_id: str | None = None,
) -> Interpretation:
    """Build an interpretation, verifying that its inputs exist.

    Passing ``evidence`` lets the function check that every id named in
    ``derived_from`` corresponds to a reading that was actually recorded. That
    check is the useful part: it turns "the model said so" into "there is a
    recording with this digest behind that statement".
    """
    known = {item.evidence_id for item in (evidence or [])}
    cited = tuple(derived_from)
    if known and cited:
        missing = [item for item in cited if item not in known]
        if missing:
            raise ValidationError(
                f"interpretation cites evidence that was never recorded: {missing}"
            )
    moment = now if now is not None else Clock().now()
    return Interpretation(
        interpretation_id=interpretation_id or f"INTERP-{uuid.uuid4().hex[:12]}",
        claim=claim,
        derived_from=cited,
        confidence=confidence,
        kind=kind,
        method=method,
        made_by=made_by,
        timestamp=format_timestamp(moment),
    )


__all__ = [
    "FOUNDATION_EVIDENCE_SCHEMA",
    "INTERPRETATION_SCHEMA",
    "EvidenceKind",
    "FoundationEvidence",
    "Interpretation",
    "interpret",
    "record_evidence",
]
