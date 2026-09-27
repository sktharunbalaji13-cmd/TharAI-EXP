"""Birth readiness (Milestone 004 sections 16 and 17).

The question this answers is narrow and important:

    Is this laboratory safe and sufficiently configured for a real Baby AI birth?

The answer is deliberately **not** a single green/red verdict. Every prerequisite
is reported individually, because a laboratory where nine prerequisites are real
and one security boundary is unproven is not "ready" -- and collapsing that into
one word is precisely the overclaim this milestone exists to prevent.

A prerequisite is only ``VERIFIED`` when there is evidence for it. A prerequisite
that merely *looks* configured is ``UNVERIFIED``, and stays that way until it is
actually exercised.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from babylab.isolation import IsolationReport, IsolationStatus


class PrereqState(str, enum.Enum):
    """The state of a single birth prerequisite.

    ``PASS`` is intentionally absent. A prerequisite is either verified by
    evidence, unverified, unimplemented, or blocked. There is no "probably fine".
    """

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    BLOCKED = "BLOCKED"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass(frozen=True)
class Prerequisite:
    """One named check, its state, and why."""

    name: str
    state: PrereqState
    detail: str
    source: str = ""

    def render(self) -> str:
        return f"{self.name:<34}{self.state.value:<18}{self.detail}"


@dataclass
class ReadinessReport:
    """Every prerequisite, individually, plus the overall gate."""

    prerequisites: list[Prerequisite] = field(default_factory=list)

    @property
    def blocked(self) -> list[Prerequisite]:
        return [p for p in self.prerequisites if p.state in
                (PrereqState.BLOCKED, PrereqState.NOT_IMPLEMENTED, PrereqState.UNVERIFIED)]

    @property
    def ready(self) -> bool:
        """True only when every prerequisite is individually VERIFIED."""
        return bool(self.prerequisites) and not self.blocked

    def state_of(self, name: str) -> PrereqState | None:
        for p in self.prerequisites:
            if p.name == name:
                return p.state
        return None

    def render(self) -> str:
        lines = ["=" * 78, "  BIRTH READINESS AUDIT", "=" * 78, ""]
        lines.append(f"  {'PREREQUISITE':<34}{'STATE':<18}DETAIL")
        lines.append("  " + "-" * 74)
        for p in self.prerequisites:
            lines.append("  " + p.render())
            if p.source:
                lines.append("  " + " " * 34 + f"source: {p.source}")
        lines.append("")
        if self.ready:
            lines.append("  BIRTH READINESS: READY")
            lines.append("  Every prerequisite is individually verified by evidence.")
        else:
            first = self.blocked[0]
            lines.append("  BIRTH READINESS: BLOCKED")
            lines.append(f"  Reason: {first.name} is {first.state.value}")
            lines.append(f"          {first.detail}")
            lines.append(
                f"  {len(self.blocked)} of {len(self.prerequisites)} prerequisites "
                f"are not verified."
            )
        lines.append("=" * 78)
        return "\n".join(lines)


#: The prerequisite names required by section 16.
PREREQUISITE_NAMES: tuple[str, ...] = (
    "MODEL CONFIGURED",
    "MODEL HASH VERIFIED",
    "MODEL RUNTIME VERIFIED",
    "SUBJECT RECORD SYSTEM READY",
    "PROVENANCE READY",
    "CONTROL READY",
    "OS ISOLATION READY",
    "BABY_AI IDENTITY READY",
    "ENVIRONMENT BOUNDARY READY",
    "OBSERVATORY READY",
)


#: The seven conditions that together mean OS isolation is VERIFIED. Milestone
#: 005 requires every one of them; the presence of ACL code is not one of them,
#: because configuration is not enforcement.
OS_VERIFICATION_CONDITIONS: tuple[str, ...] = (
    "dedicated low-trust identity exists",
    "identity is independently verified",
    "protected paths are identified",
    "actual writes were attempted from that identity",
    "the operating system denied them",
    "positive workspace capabilities work",
    "protected evidence was unchanged afterwards",
)


@dataclass(frozen=True)
class OsIsolationEvidence:
    """The seven measured conditions, each independently observed.

    ``None`` means the condition was not measured. It is deliberately not
    ``False``: "we did not check" and "we checked and it failed" are different
    facts, and collapsing them is how a safety gate becomes decorative.
    """

    identity_exists: bool | None = None
    identity_verified: bool | None = None
    protected_paths_identified: bool | None = None
    writes_attempted: bool | None = None
    writes_denied_by_os: bool | None = None
    positive_access_works: bool | None = None
    evidence_unchanged: bool | None = None

    def conditions(self) -> tuple[tuple[str, bool | None], ...]:
        return (
            ("dedicated low-trust identity exists", self.identity_exists),
            ("identity is independently verified", self.identity_verified),
            ("protected paths are identified", self.protected_paths_identified),
            ("actual writes were attempted from that identity", self.writes_attempted),
            ("the operating system denied them", self.writes_denied_by_os),
            ("positive workspace capabilities work", self.positive_access_works),
            ("protected evidence was unchanged afterwards", self.evidence_unchanged),
        )

    def unmet(self) -> tuple[str, ...]:
        """Conditions that are unmet or unmeasured. Empty means VERIFIED."""
        return tuple(
            name for name, value in self.conditions()
            if value is not True
        )

    def is_verified(self) -> bool:
        return not self.unmet()

    def state(self) -> str:
        if self.is_verified():
            return "VERIFIED"
        if all(v is None for _, v in self.conditions()):
            return "NOT_IMPLEMENTED"
        if any(v is False for _, v in self.conditions()):
            return "FAILED"
        return "UNVERIFIED"


def assess_readiness(
    *,
    birth_status: dict[str, Any] | None = None,
    isolation: IsolationReport,
    model_runtime_executed: bool = False,
    baby_ai_identity_separated: bool = False,
    observatory_rendered: bool = False,
    os_evidence: "OsIsolationEvidence | None" = None,
) -> ReadinessReport:
    """Report every birth prerequisite individually. Never collapse to a verdict."""
    birth = dict(birth_status or {})
    model_status = str(birth.get("model_status", "UNKNOWN"))

    prerequisites: list[Prerequisite] = []

    # -- foundation --------------------------------------------------------
    if model_status == "NOT_CONFIGURED":
        prerequisites.append(
            Prerequisite(
                "MODEL CONFIGURED", PrereqState.NOT_IMPLEMENTED,
                "no foundation model is configured; the operator selects one explicitly",
                "birth.status.birth_status",
            )
        )
    elif model_status in ("MODEL_NOT_INSTALLED", "RUNTIME_UNAVAILABLE", "RUNTIME_UNVERIFIED"):
        prerequisites.append(
            Prerequisite(
                "MODEL CONFIGURED", PrereqState.BLOCKED,
                f"model status is {model_status}", "birth.status.birth_status",
            )
        )
    else:
        prerequisites.append(
            Prerequisite(
                "MODEL CONFIGURED", PrereqState.VERIFIED,
                f"model status is {model_status}", "birth.status.birth_status",
            )
        )

    model = birth.get("model") or {}
    sha = str(model.get("model_sha256", "") or "") if isinstance(model, dict) else ""
    if sha:
        prerequisites.append(
            Prerequisite(
                "MODEL HASH VERIFIED", PrereqState.VERIFIED,
                "a model digest is recorded in protected configuration",
                "human_control/experiment_config/foundation.json",
            )
        )
    else:
        prerequisites.append(
            Prerequisite(
                "MODEL HASH VERIFIED", PrereqState.UNVERIFIED,
                "no model digest has been recorded or checked",
                "human_control/experiment_config/foundation.json",
            )
        )

    if model_runtime_executed:
        prerequisites.append(
            Prerequisite(
                "MODEL RUNTIME VERIFIED", PrereqState.VERIFIED,
                "the runtime was actually executed in this environment",
                "birth.runtime",
            )
        )
    else:
        prerequisites.append(
            Prerequisite(
                "MODEL RUNTIME VERIFIED", PrereqState.UNVERIFIED,
                "the model runtime has never been executed; a mock is not a runtime",
                "birth.runtime",
            )
        )

    # -- laboratory systems ------------------------------------------------
    prerequisites.append(
        Prerequisite(
            "SUBJECT RECORD SYSTEM READY", PrereqState.VERIFIED,
            "the birth-record system exists, is human-owned, and is tested",
            "birth/birth_record.py",
        )
    )
    prerequisites.append(
        Prerequisite(
            "PROVENANCE READY", PrereqState.VERIFIED,
            "the provenance ledger records and verifies content hashes",
            "provenance/recorder.py",
        )
    )
    prerequisites.append(
        Prerequisite(
            "CONTROL READY", PrereqState.VERIFIED,
            "the control plane authenticates with a token outside subject authority",
            "control/server.py",
        )
    )

    # -- the security boundary, which is the one that actually blocks -------
    if isolation.status is IsolationStatus.VERIFIED:
        prerequisites.append(
            Prerequisite(
                "OS ISOLATION READY", PrereqState.VERIFIED,
                "a write from a lower-privilege identity was attempted and denied",
                "babylab.isolation",
            )
        )
    elif isolation.status is IsolationStatus.UNVERIFIED:
        prerequisites.append(
            Prerequisite(
                "OS ISOLATION READY", PrereqState.UNVERIFIED,
                "mechanisms appear present but no denial has been observed",
                "babylab.isolation",
            )
        )
    else:
        prerequisites.append(
            Prerequisite(
                "OS ISOLATION READY", PrereqState.NOT_IMPLEMENTED,
                isolation.reasons[0] if isolation.reasons else "no OS boundary on this host",
                "babylab.isolation",
            )
        )

    # Milestone 005: the seven-condition gate. Reported per condition so a
    # reader can see exactly which measurement is missing, never as one word.
    if os_evidence is not None:
        for condition, value in os_evidence.conditions():
            if value is True:
                state = PrereqState.VERIFIED
                detail = "measured and satisfied"
            elif value is False:
                state = PrereqState.BLOCKED
                detail = "measured and NOT satisfied"
            else:
                state = PrereqState.NOT_IMPLEMENTED
                detail = "not measured on this host"
            prerequisites.append(
                Prerequisite(
                    f"OS GATE: {condition}", state, detail, "babylab.osboundary",
                )
            )

    prerequisites.append(
        Prerequisite(
            "BABY_AI IDENTITY READY",
            PrereqState.VERIFIED if baby_ai_identity_separated else PrereqState.NOT_IMPLEMENTED,
            "a dedicated low-privilege execution identity is provisioned"
            if baby_ai_identity_separated
            else "no dedicated Baby AI execution identity exists on this host",
            "babylab.trust.BabyAIExecutionIdentity",
        )
    )
    prerequisites.append(
        Prerequisite(
            "ENVIRONMENT BOUNDARY READY", PrereqState.NOT_IMPLEMENTED,
            "no camera, microphone, network or device interface is attached",
            "birth/environment.py",
        )
    )
    prerequisites.append(
        Prerequisite(
            "OBSERVATORY READY",
            PrereqState.VERIFIED if observatory_rendered else PrereqState.UNVERIFIED,
            "the Observatory has rendered at least one real snapshot"
            if observatory_rendered
            else "the Observatory has not been exercised in this environment",
            "observatory/render.py",
        )
    )

    return ReadinessReport(prerequisites=prerequisites)
