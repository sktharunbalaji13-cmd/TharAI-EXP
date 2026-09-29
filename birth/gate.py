"""The birth safety gate: a point decision, not a readiness assessment.

Gate vs readiness
-----------------
M003's ``birth.readiness`` asks "is the laboratory prepared?" as a long-lived
assessment with states VERIFIED/UNVERIFIED/NOT_IMPLEMENTED/BLOCKED. The gate
asks a narrower question at a single moment: "may this birth proceed *now*?"
Its answers are ``PASS``/``FAIL``/``UNKNOWN``, and the only value that permits
anything is an explicit ``PASS`` on every mandatory prerequisite.

The two rules that make a gate a gate
-------------------------------------
1. **UNKNOWN never becomes PASS.** An unknowable prerequisite is not a
   permission; it is a block with a reason. There is no "probably fine".
2. **Absence is FAIL, not UNKNOWN.** "No model is configured" is an observed
   fact about the laboratory, not a gap in our knowledge. Conflating the two
   would let every missing thing through on the grounds that it cannot be
   checked.

What the gate checks, and how
-----------------------------
Each prerequisite is evaluated against the *current* machine state, not against
a previous milestone's report. Reading M005's evidence file and calling it a
check would be assuming security from a previous milestone; the gate re-inspects
the ACLs directly. Where a check cannot be performed without side effects (for
example, writing to the event store to prove it is writable), the gate checks
readability and internal consistency instead, and says so.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable


class GateResult(str, enum.Enum):
    """The only three answers a gate may give."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class PrerequisiteResult:
    """One evaluated prerequisite."""

    name: str
    result: GateResult
    detail: str
    #: If False, this prerequisite is advisory: it is reported but cannot block.
    #: Every M009 prerequisite below is mandatory, so this exists for future
    #: milestones to use explicitly rather than by accident.
    mandatory: bool = True
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def blocks(self) -> bool:
        """Whether this result stops a birth. Only PASS does not."""
        return self.mandatory and self.result is not GateResult.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "result": self.result.value,
            "detail": self.detail,
            "mandatory": self.mandatory,
            "blocks": self.blocks,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class GateVerdict:
    """The gate's decision, with every prerequisite that produced it."""

    verdict: str  # "PROCEED" or "BLOCKED"
    reason: str
    prerequisites: tuple[PrerequisiteResult, ...]
    evaluated_at: str

    @property
    def may_proceed(self) -> bool:
        return self.verdict == "PROCEED"

    def blocking(self) -> tuple[PrerequisiteResult, ...]:
        return tuple(p for p in self.prerequisites if p.blocks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "evaluated_at": self.evaluated_at,
            "prerequisites": [p.to_dict() for p in self.prerequisites],
            "blocking": [p.name for p in self.blocking()],
        }


#: The fourteen checks, in evaluation order. Order matters only for the report:
#: every check always runs, so a single evaluation shows the whole picture
#: rather than stopping at the first failure and hiding the rest.
PREREQUISITE_ORDER = (
    "model_runtime_availability",
    "model_artifact_identity",
    "model_artifact_digest",
    "runtime_verification",
    "subject_identity_capability",
    "key_custody",
    "environment_availability",
    "environment_version",
    "subject_interface_availability",
    "provenance_availability",
    "protected_evidence_integrity",
    "m005_isolation_status",
    "observatory_availability",
    "configuration_integrity",
)


class BirthGate:
    """Evaluates the fourteen prerequisites against live machine state.

    Check functions are injected so tests can exercise every failure mode
    without touching the real laboratory. The default checks are the real ones;
    a test that substitutes a stub is testing the gate's *logic*, and says so.
    """

    def __init__(
        self,
        checks: dict[str, Callable[[], PrerequisiteResult]] | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        from birth import gate_checks  # local import: keeps module import light

        self._checks = dict(checks) if checks else gate_checks.default_checks()
        self._clock = clock or (lambda: "1970-01-01T00:00:00.000Z")

    def prerequisite_names(self) -> tuple[str, ...]:
        return PREREQUISITE_ORDER

    def evaluate(self) -> GateVerdict:
        """Run every check. All of them, even after a failure."""
        results: list[PrerequisiteResult] = []
        for name in PREREQUISITE_ORDER:
            check = self._checks.get(name)
            if check is None:
                results.append(PrerequisiteResult(
                    name=name, result=GateResult.UNKNOWN,
                    detail=f"no check is registered for {name!r}; an "
                           "unevaluated prerequisite blocks by default",
                ))
                continue
            try:
                results.append(check())
            except Exception as exc:  # noqa: BLE001 - a crashing check blocks
                results.append(PrerequisiteResult(
                    name=name, result=GateResult.UNKNOWN,
                    detail=f"check raised {type(exc).__name__}: {exc}; a check "
                           "that cannot run is not a check that passed",
                ))
        blocking = [r for r in results if r.blocks]
        if blocking:
            first = blocking[0]
            return GateVerdict(
                verdict="BLOCKED",
                reason=f"{first.name}: {first.detail}",
                prerequisites=tuple(results),
                evaluated_at=self._clock(),
            )
        return GateVerdict(
            verdict="PROCEED",
            reason="every mandatory prerequisite explicitly passed",
            prerequisites=tuple(results),
            evaluated_at=self._clock(),
        )


__all__ = [
    "BirthGate",
    "GateResult",
    "GateVerdict",
    "PREREQUISITE_ORDER",
    "PrerequisiteResult",
]
