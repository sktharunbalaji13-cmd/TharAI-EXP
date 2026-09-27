"""Capability contracts: the future-facing interfaces, without the fiction.

The central design claim
------------------------
The architecture is built for cognitive functions that do not exist yet, and
that is the whole point. So the contract is defined, the slot is named, the
test that a slot is honestly empty is written, and **no implementation is
invented to fill it**.

The four words that must not appear
----------------------------------
A future reader will be scanning this for evidence that the researcher
pre-decided what the subject becomes. These are the failure modes, and each has
a guard:

``stage``
    A sequence implies a curriculum. The registry is a **set**: order is not
    part of the data structure, and :func:`capability_names` returns a sorted
    list purely for stable display. There is no ``precedes``, no ``level``, no
    ``unlocks``.
``developmental``
    Same problem in the vocabulary. Every docstring here describes *what a
    capability does*, never *what stage of development it marks*.
``maturity`` / ``readiness score``
    A single number grading the subject would be a fabricated measurement.
    :class:`CapabilityStatus` is an enum of factual states with no ordering
    between them and no arithmetic defined on it.
``emotional`` / ``motivation`` / ``curiosity`` / ``consciousness``
    Not implemented, not simulated, and not given a plausible-looking default.
    :data:`NOT_YET_IMPLEMENTED` names them as absent.

Truthful status values
----------------------
===========================  ====================================================
``UNAVAILABLE``               No implementation exists. Honest, and the default.
``NOT_YET_IMPLEMENTED``       Deliberately deferred; named so absence is visible.
``IMPLEMENTED``               Real implementation, with a real test.
``SIMULATED``                 Implemented for testing only. Never a finding.
``BLOCKED``                   Intended, but cannot run. Reason is recorded.
===========================  ====================================================

``SIMULATED`` is a first-class value rather than a hidden flag because a
simulated capability that is not labelled becomes a false finding within a week.
"""

from __future__ import annotations

import enum
import typing
from dataclasses import dataclass, field
from typing import Any

from babylab.errors import ValidationError
from babylab.hashing import canonical_bytes, sha256_hex

CAPABILITY_REGISTRY_SCHEMA = "babylab/capability-registry/v1"


class CapabilityStatus(str, enum.Enum):
    """Factual state of one capability. No ordering, no arithmetic.

    The members are deliberately **incomparable**. ``str`` supplies ordering for
    free, which would let a caller write
    ``CapabilityStatus.IMPLEMENTED > CapabilityStatus.UNAVAILABLE`` and get an
    answer, and that answer would be a developmental ranking wearing a
    capability's clothes. So every comparison raises instead. The
    ``is_functional`` property below is the only sanctioned way to ask whether a
    capability works, and it answers about one value at a time.
    """

    UNAVAILABLE = "UNAVAILABLE"
    NOT_YET_IMPLEMENTED = "NOT_YET_IMPLEMENTED"
    IMPLEMENTED = "IMPLEMENTED"
    SIMULATED = "SIMULATED"
    BLOCKED = "BLOCKED"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value

    @property
    def is_functional(self) -> bool:
        """True only for a real implementation.

        ``SIMULATED`` is excluded on purpose: a simulated capability is useful
        for testing and worthless as evidence.
        """
        return self is CapabilityStatus.IMPLEMENTED

    @property
    def is_advertised(self) -> bool:
        """Whether this may be reported as available to a caller."""
        return self is CapabilityStatus.IMPLEMENTED

    def _incomparable(self, other, operation: str) -> "typing.NoReturn":
        raise TypeError(
            f"CapabilityStatus values are not ordered ({operation}). "
            f"{self.value!r} and {getattr(other, 'value', other)!r} are separate "
            "factual states, and comparing them would rank the subject's "
            "capabilities, which is exactly the developmental model this "
            "project refuses. Use .is_functional, or compare the .value strings "
            "if you are serialising."
        )

    def __lt__(self, other):  # noqa: D105
        self._incomparable(other, "<")

    def __le__(self, other):  # noqa: D105
        self._incomparable(other, "<=")

    def __gt__(self, other):  # noqa: D105
        self._incomparable(other, ">")

    def __ge__(self, other):  # noqa: D105
        self._incomparable(other, ">=")


class CapabilityKind(str, enum.Enum):
    """The unordered set of contracts the architecture provides for.

    Membership only. Nothing in the registry says these develop in this order,
    or that one enables another, or that a subject ever obtains all of them.
    """

    PERCEPTION = "PERCEPTION"
    MEMORY = "MEMORY"
    STATE = "STATE"
    REASONING = "REASONING"
    ACTION = "ACTION"
    LEARNING = "LEARNING"
    EXPERIMENTATION = "EXPERIMENTATION"
    CODE_WORKSPACE = "CODE_WORKSPACE"
    ENVIRONMENT = "ENVIRONMENT"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


#: Stable, sorted, and explicitly unordered. Callers must not treat position as
#: meaning; the sort exists so that output is reproducible, nothing more.
CAPABILITY_KINDS: frozenset[CapabilityKind] = frozenset(CapabilityKind)


@dataclass(frozen=True)
class CapabilityContract:
    """The named slot for one capability.

    A contract is an interface declaration, not an implementation. Every slot
    carries a ``contract`` string describing the shape a future implementation
    must satisfy, which is enough to build against and impossible to mistake for
    a working capability.
    """

    kind: CapabilityKind
    status: CapabilityStatus
    contract: str
    #: Why it is in its current state. Empty is not allowed, because "no reason
    #: given" is how undocumented guesses enter a research record.
    reason: str
    #: Names of the real interfaces that implement it, if any.
    implementations: tuple[str, ...] = ()
    blocked_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "implementations", tuple(self.implementations))
        if not self.contract.strip():
            raise ValidationError(
                f"capability {self.kind.value} must state its contract, even when "
                "no implementation exists"
            )
        if not self.reason.strip():
            raise ValidationError(
                f"capability {self.kind.value} must state why it has status "
                f"{self.status.value}"
            )
        if self.status is CapabilityStatus.IMPLEMENTED and not self.implementations:
            raise ValidationError(
                f"capability {self.kind.value} is IMPLEMENTED but names no "
                "implementation; a real claim needs a real referent"
            )
        if self.status is CapabilityStatus.BLOCKED and not self.blocked_reason.strip():
            raise ValidationError(
                f"capability {self.kind.value} is BLOCKED and must say what blocks it"
            )
        if self.status is not CapabilityStatus.IMPLEMENTED and self.implementations:
            raise ValidationError(
                f"capability {self.kind.value} is {self.status.value} but names "
                "implementations; an absent capability cannot be implemented"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "status": self.status.value,
            "contract": self.contract,
            "reason": self.reason,
            "implementations": list(self.implementations),
            "blocked_reason": self.blocked_reason,
            "metadata": dict(self.metadata),
        }


def capability_names() -> list[str]:
    """Sorted names, for display only.

    The docstring on the return value matters: sorted for reproducibility, and
    the order carries no developmental meaning whatsoever.
    """
    return sorted(kind.value for kind in CAPABILITY_KINDS)


def contract_texts() -> dict[str, str]:
    """``{name: contract}``, sorted, for documentation and status output."""
    return {name: CONTRACT_TEXTS[name] for name in capability_names()}


#: What a future implementation of each contract must provide. Written as an
#: obligation, not a feature, so that reading this file describes the
#: architecture and not a plan for the subject.
CONTRACT_TEXTS: dict[str, str] = {
    "PERCEPTION": (
        "Affect: accept a sensor reading as an Observation carrying raw, "
        "sourced evidence. No interpretation, no summary, no meaning."
    ),
    "MEMORY": (
        "Affect: persist and retrieve records written by other capabilities, "
        "with provenance intact and no content rewriting."
    ),
    "STATE": (
        "Affect: represent what the subject is currently doing, derived from "
        "its own records rather than assumed."
    ),
    "REASONING": (
        "Affect: derive a labelled Interpretation from evidence, recording the "
        "derivation and its inputs. Never store hidden reasoning."
    ),
    "ACTION": (
        "Affect: propose an ActionIntent and pass it to the authorization "
        "boundary. It cannot execute; see birth.boundary."
    ),
    "LEARNING": (
        "Affect: produce BABY_AI_AUTHORED artifacts traceable to the evidence "
        "that prompted them, classified externally."
    ),
    "EXPERIMENTATION": (
        "Affect: choose an experiment and record its prediction before its "
        "outcome. No curriculum, no task list chosen by the laboratory."
    ),
    "CODE_WORKSPACE": (
        "Affect: write and run code inside its own workspace, with every "
        "consequence recorded. No privilege escalation, no access outside it."
    ),
    "ENVIRONMENT": (
        "Affect: represent non-agent environment affordances as observable "
        "properties and consequences, without assigning purpose."
    ),
}


def default_registry(reason_suffix: str = "") -> dict[CapabilityKind, CapabilityContract]:
    """The registry as it honestly stands in Milestone 003.

    Everything is :attr:`CapabilityStatus.UNAVAILABLE` except the three that have
    genuine partial implementations, and those are described as precisely as the
    truth allows:

    * ``PERCEPTION`` — the *record* of a sensor reading exists
      (:mod:`birth.perception`); nothing perceives. Recording a reading the
      subject never looked at is not perception, and the reason says so.
    * ``ENVIRONMENT`` — affordance descriptions exist
      (:mod:`birth.environment`); no environment is attached and none is
      simulated.
    * ``CODE_WORKSPACE`` — an isolated directory and an enforced write policy
      exist; the subject cannot write to it yet, because it has no runtime to
      write with.
    """
    suffix = f" {reason_suffix}" if reason_suffix else ""
    statuses: dict[CapabilityKind, tuple[CapabilityStatus, str, tuple[str, ...], str]] = {
        CapabilityKind.PERCEPTION: (
            CapabilityStatus.UNAVAILABLE,
            "Sensor evidence can be recorded and hashed, but nothing in the "
            "system looks at anything. A recorded reading is not a perception."
            + suffix,
            (),
            "",
        ),
        CapabilityKind.MEMORY: (
            CapabilityStatus.UNAVAILABLE,
            "The event log and provenance ledger are durable, but no memory "
            "capability has been implemented for the subject to use."
            + suffix,
            (),
            "",
        ),
        CapabilityKind.STATE: (
            CapabilityStatus.UNAVAILABLE,
            "The observatory derives the laboratory's view of state. That is "
            "an observer, not the subject's own state." + suffix,
            (),
            "",
        ),
        CapabilityKind.REASONING: (
            CapabilityStatus.UNAVAILABLE,
            "A foundation model is installed at most; inference is not "
            "reasoning attributed to a subject, and no derivation record exists." + suffix,
            (),
            "",
        ),
        CapabilityKind.ACTION: (
            CapabilityStatus.UNAVAILABLE,
            "The action boundary exists and authorizes nothing, which is the "
            "correct state for a system with no subject to act." + suffix,
            (),
            "",
        ),
        CapabilityKind.LEARNING: (
            CapabilityStatus.UNAVAILABLE,
            "Authorship classification exists so that future learning is "
            "attributable, but no learning capability is implemented." + suffix,
            (),
            "",
        ),
        CapabilityKind.EXPERIMENTATION: (
            CapabilityStatus.NOT_YET_IMPLEMENTED,
            "Deliberately deferred. Defining an experiment interface now risks "
            "smuggling in a curriculum, which docs/research-principles.md "
            "forbids." + suffix,
            (),
            "",
        ),
        CapabilityKind.CODE_WORKSPACE: (
            CapabilityStatus.UNAVAILABLE,
            "The workspace directory and its write policy exist, but no "
            "subject-side process has been given a way to write there." + suffix,
            (),
            "",
        ),
        CapabilityKind.ENVIRONMENT: (
            CapabilityStatus.UNAVAILABLE,
            "Affordance descriptions are recorded as observable properties. No "
            "environment is attached and none is simulated." + suffix,
            (),
            "",
        ),
    }
    return {
        kind: CapabilityContract(
            kind=kind,
            status=status,
            contract=CONTRACT_TEXTS[kind.value],
            reason=reason,
            implementations=implementations,
            blocked_reason=blocked,
        )
        for kind, (status, reason, implementations, blocked) in statuses.items()
    }


def _kind_names(kinds) -> list[str]:
    """Names for error messages, tolerating a caller that passed a raw string."""
    return sorted(getattr(item, "value", str(item)) for item in kinds)


class CapabilityRegistry:
    """The complete, unordered set of capability contracts."""
    schema = CAPABILITY_REGISTRY_SCHEMA

    def __init__(self, contracts: dict[CapabilityKind, CapabilityContract] | None = None):
        contracts = contracts if contracts is not None else default_registry()
        missing = CAPABILITY_KINDS - set(contracts)
        extra = set(contracts) - CAPABILITY_KINDS
        if missing or extra:
            raise ValidationError(
                f"registry must cover exactly the declared capability set; missing="
                f"{_kind_names(missing)} unexpected={_kind_names(extra)}"
            )
        self._contracts = dict(contracts)

    def get(self, kind: CapabilityKind) -> CapabilityContract:
        return self._contracts[kind]

    def status_of(self, kind: CapabilityKind) -> CapabilityStatus:
        return self._contracts[kind].status

    def is_functional(self, kind: CapabilityKind) -> bool:
        return self.status_of(kind).is_functional

    def __iter__(self):
        """Iterates in sorted order, for reproducible output. Order is not meaning."""
        for name in capability_names():
            yield self._contracts[CapabilityKind(name)]

    def __len__(self) -> int:
        return len(self._contracts)

    def __contains__(self, kind: object) -> bool:
        return kind in self._contracts

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "unordered": True,
            "capabilities": [contract.to_dict() for contract in self],
            "functional": sorted(
                contract.kind.value
                for contract in self
                if contract.status.is_functional
            ),
        }

    def registry_hash(self) -> str:
        """Digest over the whole registry, for the birth record."""
        return sha256_hex(canonical_bytes(self.to_dict()))

    def summary(self) -> str:
        return (
            f"{len(self._contracts)} capability contracts; "
            f"{len(self.to_dict()['functional'])} implemented; "
            "order carries no meaning"
        )


__all__ = [
    "CAPABILITY_KINDS",
    "CAPABILITY_REGISTRY_SCHEMA",
    "CONTRACT_TEXTS",
    "CapabilityContract",
    "CapabilityKind",
    "CapabilityRegistry",
    "CapabilityStatus",
    "capability_names",
    "contract_texts",
    "default_registry",
]
