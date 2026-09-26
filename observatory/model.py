"""The cognitive state model.

The one rule this module exists to enforce
------------------------------------------
**A field that the subject did not report is absent, and an absent field is
never rendered as a value.**

The specification's own example is the test case::

    memory_activity: unavailable      <- correct
    memory_activity: []               <- a lie

An empty list and an unreported list are different facts. Rendering the first
as the second would let a reader conclude "the subject checked its memory and
found nothing", when the truth is "the subject never said anything about its
memory". In a laboratory whose entire purpose is to observe without
interfering, that substitution is the cardinal sin.

So the model has no defaults for cognitive fields. A
:class:`~observatory.model.CognitiveState` is a bag of *reported* domains, and
:func:`observatory.model.StateValue` carries the epistemic status of each one.

Epistemic status
----------------
========================  ==========================================
:attr:`EpistemicStatus`   Meaning
========================  ==========================================
``OBSERVED``              Present verbatim in a subject event payload.
``DERIVED``               Computed by the Observatory from one or
                          more events. The source event IDs are
                          always carried alongside.
``UNAVAILABLE``           The subject exists but did not report this
                          domain. We do not know; absence is not zero.
``UNKNOWN``               Not determinable even in principle with the
                          telemetry the system exposes.
========================  ==========================================

Every value also carries ``source_event_ids``, so any element the renderer
displays can be traced back to the canonical event store (§14). A value with no
source events and a status other than ``UNAVAILABLE``/``UNKNOWN`` is a bug, and
:meth:`StateValue.validate` says so.

No curriculum
-------------
Domains are named strings, not an enum. The specification lists
``perception``, ``memory``, ``context`` and so on as *possibilities*, and is
explicit that they are not a developmental sequence (see
``docs/decisions/ADR-004-no-event-taxonomy.md``). Hardcoding that list as a
required field set would smuggle a curriculum back in through the read side.
A subject that reports only ``tooling`` is represented faithfully.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Iterable

from babylab.errors import ValidationError

#: Version of the cognitive state schema. Bumped when the meaning of a field
#: changes, so that a stored snapshot can be interpreted correctly years later.
STATE_SCHEMA = "babylab/cognitive-state/v1"

#: Conventional domain names. These are *suggestions for subjects and tooling*,
#: not a required set, and nothing in this module validates against them. They
#: exist so the renderer can order and group familiar domains pleasantly.
CONVENTIONAL_DOMAINS = (
    "active_context",
    "perception",
    "memory",
    "hypothesis",
    "decision",
    "action",
    "tool_use",
    "experiment",
    "result",
    "learning",
    "code_modification",
    "environment",
)


class EpistemicStatus(str, enum.Enum):
    """How the Observatory came to hold a value."""

    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value

    @property
    def is_claim(self) -> bool:
        """True when the status asserts something about the subject.

        ``UNAVAILABLE`` and ``UNKNOWN`` are *absences* of claims. They are
        still worth displaying — a researcher needs to know the difference
        between "nothing happened" and "nothing was reported" — but they must
        never be counted as observations.
        """
        return self in (EpistemicStatus.OBSERVED, EpistemicStatus.DERIVED)


#: Rendered for each status when a domain has no usable value. Deliberately
#: shouty. The reader should not be able to mistake these for data.
STATUS_PLACEHOLDER = {
    EpistemicStatus.UNAVAILABLE: "UNAVAILABLE",
    EpistemicStatus.UNKNOWN: "UNKNOWN",
}


@dataclass(frozen=True)
class StateValue:
    """One reported (or explicitly unreported) domain of subject state.

    Attributes
    ----------
    domain:
        Name of the state domain, e.g. ``"memory"``. A free string: see the
        module docstring on curricula.
    status:
        Epistemic status of ``value``.
    value:
        The reported value, or ``None`` when the status is an absence.
    source_event_ids:
        Event IDs in the canonical store that justify this value. Required for
        ``OBSERVED`` and ``DERIVED``; empty for the absence statuses.
    note:
        Human-readable explanation, shown in ``--detail`` output. Used to say
        *why* something is unavailable, which is often the interesting part.
    """

    domain: str
    status: EpistemicStatus
    value: Any = None
    source_event_ids: tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.domain, str) or not self.domain.strip():
            raise ValidationError("StateValue.domain must be a non-empty string")
        if not isinstance(self.status, EpistemicStatus):
            raise ValidationError(f"status must be an EpistemicStatus, got {self.status!r}")
        object.__setattr__(self, "source_event_ids", tuple(self.source_event_ids))
        self.validate()

    def validate(self) -> None:
        if self.status.is_claim:
            if self.value is None:
                raise ValidationError(
                    f"domain {self.domain!r} is {self.status.value} but carries no "
                    f"value; that would display an absence as a claim"
                )
            if not self.source_event_ids:
                raise ValidationError(
                    f"domain {self.domain!r} is {self.status.value} but cites no "
                    f"source event; every displayed element must be traceable to "
                    f"the canonical event store"
                )
        else:
            if self.value is not None:
                raise ValidationError(
                    f"domain {self.domain!r} is {self.status.value} and must not "
                    f"carry a value"
                )
            if self.source_event_ids:
                raise ValidationError(
                    f"domain {self.domain!r} is {self.status.value} and must not "
                    f"cite source events"
                )

    # -- constructors -----------------------------------------------------
    @classmethod
    def observed(
        cls, domain: str, value: Any, source_event_ids: Iterable[str], note: str = ""
    ) -> "StateValue":
        return cls(domain, EpistemicStatus.OBSERVED, value, tuple(source_event_ids), note)

    @classmethod
    def derived(
        cls, domain: str, value: Any, source_event_ids: Iterable[str], note: str = ""
    ) -> "StateValue":
        return cls(domain, EpistemicStatus.DERIVED, value, tuple(source_event_ids), note)

    @classmethod
    def unavailable(cls, domain: str, note: str = "") -> "StateValue":
        return cls(domain, EpistemicStatus.UNAVAILABLE, None, (), note)

    @classmethod
    def unknown(cls, domain: str, note: str = "") -> "StateValue":
        return cls(domain, EpistemicStatus.UNKNOWN, None, (), note)

    # -- presentation -----------------------------------------------------
    def display(self) -> str:
        """The value as it should appear in the terminal.

        For absence statuses this is always the shouty placeholder, never
        ``[]``, ``None``, ``0`` or an empty string — and never the note, because
        a note is prose and prose in the value column is one refactor away from
        being read as data. Explanations belong in ``--detail`` output, which
        the renderer keeps in a separate column.
        """
        if not self.status.is_claim:
            return STATUS_PLACEHOLDER[self.status]
        return _compact(self.value)

    def is_claim(self) -> bool:
        return self.status.is_claim

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "status": self.status.value,
            "value": self.value if self.status.is_claim else None,
            "source_event_ids": list(self.source_event_ids),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StateValue":
        if not isinstance(data, dict):
            raise ValidationError(f"StateValue expects an object, got {type(data).__name__}")
        try:
            status = EpistemicStatus(data.get("status"))
        except ValueError as exc:
            raise ValidationError(f"unknown epistemic status {data.get('status')!r}") from exc
        return cls(
            domain=data.get("domain"),
            status=status,
            value=data.get("value"),
            source_event_ids=tuple(data.get("source_event_ids") or ()),
            note=data.get("note") or "",
        )


@dataclass(frozen=True)
class StateTransition:
    """One version of the derived state, and the events that caused it.

    This is what makes §13 answerable. ``observatory.cli history`` prints these,
    and each one names the events it was derived from, so "what caused this
    change?" always has an answer that points at the event store.
    """

    version: int
    cause_event_ids: tuple[str, ...]
    reason: str
    changed_domains: tuple[str, ...] = ()
    timestamp: str = ""

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValidationError(f"state version starts at 1, got {self.version}")
        object.__setattr__(self, "cause_event_ids", tuple(self.cause_event_ids))
        object.__setattr__(self, "changed_domains", tuple(self.changed_domains))
        if not self.cause_event_ids:
            raise ValidationError(
                "a state transition must cite at least one cause event; a change "
                "with no cause is not a change, it is a fabrication"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "cause_event_ids": list(self.cause_event_ids),
            "reason": self.reason,
            "changed_domains": list(self.changed_domains),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StateTransition":
        return cls(
            version=data.get("version"),
            cause_event_ids=tuple(data.get("cause_event_ids") or ()),
            reason=data.get("reason") or "",
            changed_domains=tuple(data.get("changed_domains") or ()),
            timestamp=data.get("timestamp") or "",
        )


@dataclass(frozen=True)
class CognitiveState:
    """An immutable snapshot of everything the subject has reported.

    ``domains`` holds only domains the subject actually reported, plus
    explicitly-marked absences the deriver chose to record. Nothing is
    defaulted. ``reported_by`` records the subject ID, or ``None`` when no
    subject is attached — in which case ``domains`` is necessarily empty.
    """

    subject_id: str | None
    version: int
    timestamp: str
    domains: dict[str, StateValue] = field(default_factory=dict)
    last_event_id: str | None = None
    last_event_seq: int = 0

    def __post_init__(self) -> None:
        for name, value in self.domains.items():
            if name != value.domain:
                raise ValidationError(
                    f"domain key {name!r} disagrees with StateValue.domain {value.domain!r}"
                )
        if self.subject_id is None and self.domains:
            claiming = [k for k, v in self.domains.items() if v.is_claim()]
            if claiming:
                raise ValidationError(
                    "a state with no subject attached may not carry claimed "
                    f"domains: {sorted(claiming)}. Milestone 002 has no subject, "
                    "so there is nothing that could have reported these."
                )

    # -- access -----------------------------------------------------------
    def get(self, domain: str) -> StateValue:
        """Reported value, or an explicit UNAVAILABLE marker.

        Returning a marked absence rather than ``None`` means a caller cannot
        accidentally treat a missing domain as a falsy value. It has to handle
        the absence deliberately.
        """
        existing = self.domains.get(domain)
        if existing is not None:
            return existing
        return StateValue.unavailable(domain, note="not reported by the subject")

    def reported(self) -> dict[str, StateValue]:
        """Only the domains that carry a claim."""
        return {k: v for k, v in self.domains.items() if v.is_claim()}

    def is_empty(self) -> bool:
        return not self.reported()

    def ordered_domains(self) -> list[str]:
        """Conventional domains first, then anything else, alphabetically.

        Presentation only. An unrecognised domain is still shown, because the
        subject is free to report something the Observatory has never heard of
        and hiding it would be a form of censorship.
        """
        conventional = [d for d in CONVENTIONAL_DOMAINS if d in self.domains]
        extra = sorted(d for d in self.domains if d not in CONVENTIONAL_DOMAINS)
        return conventional + extra

    def all_source_event_ids(self) -> list[str]:
        seen: list[str] = []
        for value in self.domains.values():
            for event_id in value.source_event_ids:
                if event_id not in seen:
                    seen.append(event_id)
        return seen

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": STATE_SCHEMA,
            "subject_id": self.subject_id,
            "version": self.version,
            "timestamp": self.timestamp,
            "last_event_id": self.last_event_id,
            "last_event_seq": self.last_event_seq,
            "domains": {name: value.to_dict() for name, value in sorted(self.domains.items())},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CognitiveState":
        if not isinstance(data, dict):
            raise ValidationError(f"CognitiveState expects an object, got {type(data).__name__}")
        raw_domains = data.get("domains") or {}
        if not isinstance(raw_domains, dict):
            raise ValidationError("CognitiveState.domains must be an object")
        return cls(
            subject_id=data.get("subject_id"),
            version=data.get("version") or 0,
            timestamp=data.get("timestamp") or "",
            domains={k: StateValue.from_dict(v) for k, v in raw_domains.items()},
            last_event_id=data.get("last_event_id"),
            last_event_seq=data.get("last_event_seq") or 0,
        )

    @classmethod
    def empty(cls, subject_id: str | None = None, timestamp: str = "") -> "CognitiveState":
        """The state of a subject that has reported nothing.

        Note the absence of a ``version``. Version 1 is reserved for the first
        *reported* state, so an empty state is not a numbered version of
        anything. This keeps ``history`` from showing a transition that no
        event caused.
        """
        return cls(subject_id=subject_id, version=0, timestamp=timestamp, domains={})

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        subject = self.subject_id or "NO_SUBJECT"
        return f"CognitiveState({subject}, v{self.version}, {len(self.domains)} domains)"


def _compact(value: Any) -> str:
    """One-line rendering of an arbitrary JSON value."""
    import json

    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover - default=str covers most
        return str(value)
