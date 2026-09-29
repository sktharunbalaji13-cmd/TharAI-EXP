"""Provenance for subject records: who recorded, and what the content is.

Two axes, kept apart
--------------------
A provenance question has two parts, and M008 refuses to answer either one from
the content itself:

* **Source** -- which infrastructure produced this record. ``SUBJECT`` here
  means "emitted through the subject interface by laboratory code", never "the
  subject said so". Determined by *channel*, never by payload fields.
* **Origin** -- what kind of thing the content is. An observation is
  ``OBSERVED``; a laboratory computation is ``DERIVED``; something the subject
  interface emitted is ``SUBJECT_GENERATED``; a foundation completion is
  ``INHERITED_PRETRAINED``; and what is not known is ``UNAVAILABLE`` -- which is
  never zero, empty, false, or absent unless absence itself was observed.

The critical case
-----------------
A subject-interface proposal that says ``{"author": "LABORATORY"}`` is still
``SUBJECT_GENERATED`` content, and a foundation completion that says
``{"author": "BABY_AI"}`` is still ``INHERITED_PRETRAINED``. Origin is derived
from how the content arrived, and a payload field cannot change it. The test
that proves this checks the actual behaviour, not a comment claiming it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

from babylab.hashing import canonical_bytes, sha256_hex


class Source(str, enum.Enum):
    """Which infrastructure produced a record. Determined by channel."""

    HUMAN = "HUMAN"
    ENVIRONMENT = "ENVIRONMENT"
    FOUNDATION_MODEL = "FOUNDATION_MODEL"
    SUBJECT = "SUBJECT"
    LABORATORY_DERIVED = "LABORATORY_DERIVED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class Origin(str, enum.Enum):
    """What kind of thing the content is. Determined by how it arrived."""

    #: Measured by the environment or the laboratory.
    OBSERVED = "OBSERVED"
    #: Computed from observed values by a stated rule.
    DERIVED = "DERIVED"
    #: Emitted through the subject interface. Says nothing about authorship.
    SUBJECT_GENERATED = "SUBJECT_GENERATED"
    #: Emitted by a pretrained model over inherited weights. Not an experience.
    INHERITED_PRETRAINED = "INHERITED_PRETRAINED"
    #: Not known. Never zero, empty, false, or absent unless absence was observed.
    UNAVAILABLE = "UNAVAILABLE"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class ProvenanceAttribution:
    """One record's full provenance: source, origin, and the basis for both."""

    record_id: str
    source: Source
    origin: Origin
    basis: str
    recorded_at: str
    content_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "source": self.source.value,
            "origin": self.origin.value,
            "basis": self.basis,
            "recorded_at": self.recorded_at,
            "content_digest": self.content_digest,
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.to_dict()))


def attribute_record(
    *,
    record_id: str,
    channel: Source,
    content: Any,
    recorded_at: str,
) -> ProvenanceAttribution:
    """Attribute a record by its channel, ignoring what the content claims.

    ``channel`` is the infrastructure that produced the record. A payload that
    asserts a different source is recorded *as content* and does not change the
    attribution. That is the whole anti-self-authorship mechanism at this layer,
    and it is behavioural rather than documentary: the function genuinely never
    inspects the content's ``author`` or ``role`` fields.
    """
    origin = _origin_for(channel)
    return ProvenanceAttribution(
        record_id=record_id,
        source=channel,
        origin=origin,
        basis=(
            f"attributed by recording channel ({channel.value}); content claims "
            "are not consulted"
        ),
        recorded_at=recorded_at,
        content_digest=(sha256_hex(canonical_bytes(_stable(content)))
                        if content is not None else ""),
    )


def _origin_for(channel: Source) -> Origin:
    return {
        Source.HUMAN: Origin.OBSERVED,
        Source.ENVIRONMENT: Origin.OBSERVED,
        Source.FOUNDATION_MODEL: Origin.INHERITED_PRETRAINED,
        Source.SUBJECT: Origin.SUBJECT_GENERATED,
        Source.LABORATORY_DERIVED: Origin.DERIVED,
    }[channel]


def _stable(value: Any):
    if isinstance(value, dict):
        return {k: _stable(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_stable(v) for v in value]
    return value


__all__ = ["Origin", "ProvenanceAttribution", "Source", "attribute_record"]
