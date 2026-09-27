"""The human-readable audit snapshot (Milestone 004).

Why this exists
---------------
An investigator must be able to answer "what does the laboratory currently
claim?" by reading a rendered report, not by reading source code. Every claim in
the report carries an **epistemic label** and a **source reference**, so a reader
can tell a measurement from a record, and can follow any claim back to the event,
record, or configuration it came from.

The three truths the milestone insists on keeping apart
-----------------------------------------------------
``MACHINE TRUTH``
    What the records and cryptographic mechanisms say.
``DISPLAY TRUTH``
    What this report shows a human.
``EXPERIMENTAL TRUTH``
    What has actually been exercised in the real environment.

A green test suite proves none of these on its own. This module is deliberately
built so that ``UNVERIFIED`` and ``UNAVAILABLE`` are first-class outcomes, and
so that a missing value can never be rendered as ``0``, ``false``, ``[]`` or
``"none"`` unless that is genuinely what was observed.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from babylab.isolation import IsolationReport, IsolationStatus

#: The twelve sections every audit report carries, in display order.
AUDIT_SECTIONS: tuple[str, ...] = (
    "SUBJECT",
    "FOUNDATION",
    "RUNTIME",
    "BIRTH",
    "PROVENANCE",
    "CONTROL",
    "ISOLATION",
    "COGNITIVE COMPONENTS",
    "ENVIRONMENT",
    "EXPERIMENTAL STATUS",
    "UNVERIFIED CLAIMS",
    "FAULTS",
)


class Label(str, enum.Enum):
    """How a displayed claim was established.

    These are deliberately narrow and are NOT interchangeable. Overloading a
    label is a defect, because the whole purpose is to let a reader weigh each
    claim according to how it was actually obtained.
    """

    #: Read directly from a probe executed in this process, right now.
    OBSERVED = "OBSERVED"
    #: Computed from OBSERVED values by a rule stated in this module.
    DERIVED = "DERIVED"
    #: Read from a human-owned record file on disk (birth record, seals, config).
    RECORDED = "RECORDED"
    #: Carried over from a prior milestone's frozen artifact, not re-measured.
    INHERITED = "INHERITED"
    #: A real claim that this milestone has NOT proven. Never a synonym for PASS.
    UNVERIFIED = "UNVERIFIED"
    #: The value could not be obtained at all. Not zero, not empty, not false.
    UNAVAILABLE = "UNAVAILABLE"
    #: An access or operation was refused by policy.
    DENIED = "DENIED"
    #: An operation was attempted and did not succeed.
    FAILED = "FAILED"
    #: State was not determined and cannot be inferred from what is present.
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


#: Precise meanings, rendered verbatim into the report so a reader never has to
#: guess what a label licenses them to believe.
LABEL_MEANINGS: dict[Label, str] = {
    Label.OBSERVED: "measured by a probe run in this process at report time",
    Label.DERIVED: "computed from observed values by a stated rule",
    Label.RECORDED: "read from a human-owned record file on disk",
    Label.INHERITED: "carried from a prior milestone's frozen artifact, not re-measured",
    Label.UNVERIFIED: "a real claim this milestone has not proven; never a synonym for PASS",
    Label.UNAVAILABLE: "the value could not be obtained; not zero, empty, false or none",
    Label.DENIED: "an access or operation was refused by policy",
    Label.FAILED: "an operation was attempted and did not succeed",
    Label.UNKNOWN: "state was not determined and cannot be inferred",
}


@dataclass(frozen=True)
class Claim:
    """One displayed statement, with how it was established and where from."""

    text: str
    label: Label
    #: What a reader can follow to check this: an event id, a record path, a
    #: configuration key, or the probe that produced it.
    source: str

    def render(self) -> str:
        return f"{self.text}  [{self.label.value}]  <- {self.source}"


@dataclass(frozen=True)
class Fault:
    """An inconsistency the laboratory refuses to resolve silently."""

    severity: str  # "WARNING" or "ERROR"
    message: str
    source: str = ""


@dataclass
class AuditReport:
    """The complete, renderable answer to "what does the laboratory claim?"."""

    sections: dict[str, list[Claim]] = field(default_factory=dict)
    faults: list[Fault] = field(default_factory=list)

    def section(self, name: str) -> list[Claim]:
        return self.sections.get(name, [])

    def all_claims(self) -> list[Claim]:
        out: list[Claim] = []
        for name in AUDIT_SECTIONS:
            out.extend(self.sections.get(name, []))
        return out

    def unverified(self) -> list[Claim]:
        return [c for c in self.all_claims() if c.label is Label.UNVERIFIED]

    def render(self) -> str:
        """The canonical human-readable audit text."""
        lines: list[str] = ["=" * 78, "  BABY LAB :: LABORATORY AUDIT", "=" * 78]
        for name in AUDIT_SECTIONS:
            lines.append("")
            lines.append(f"-- {name} " + "-" * max(0, 74 - len(name)))
            claims = self.section(name)
            if not claims:
                lines.append("  (no claims recorded)")
                continue
            for claim in claims:
                lines.append("  " + claim.render())
        lines.append("")
        lines.append("-- FAULT DISPLAY " + "-" * 55)
        if not self.faults:
            lines.append("  no inconsistencies detected")
        for fault in self.faults:
            lines.append(f"  {fault.severity}: {fault.message}")
            if fault.source:
                lines.append(f"    source: {fault.source}")
        lines.append("")
        lines.append("-- LABEL DEFINITIONS " + "-" * 55)
        for label in Label:
            lines.append(f"  {label.value:<13} {LABEL_MEANINGS[label]}")
        lines.append("")
        lines.append("=" * 78)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Inconsistency detection (section 15)
# ---------------------------------------------------------------------------

def detect_authority_faults(
    *,
    record_exists: bool,
    key_attached: bool,
    subject_id: str = "",
) -> list[Fault]:
    """Surface a key/record mismatch instead of choosing a convenient reading."""
    faults: list[Fault] = []
    if record_exists and not key_attached:
        faults.append(
            Fault(
                "WARNING",
                "Subject record exists. Signing key absent. "
                "Agency is therefore NOT ATTACHED.",
                source=f"birth record subject_id={subject_id or 'unknown'}",
            )
        )
    if key_attached and not record_exists:
        faults.append(
            Fault(
                "ERROR",
                "Signing key exists without a corresponding subject record. "
                "Authority state is inconsistent.",
                source="keyring BABY_AI role present; birth record absent",
            )
        )
    return faults


def isolation_claims(isolation: IsolationReport) -> tuple[list[Claim], list[Claim]]:
    """Build the ISOLATION section and its UNVERIFIED claims.

    The status is reported exactly as measured. ``UNVERIFIED`` is never rendered
    as a pass, and ``VERIFIED`` is unreachable unless a write was attempted and
    denied.
    """
    claims: list[Claim] = []
    unverified: list[Claim] = []

    status = isolation.status
    label = {
        IsolationStatus.VERIFIED: Label.OBSERVED,
        IsolationStatus.UNVERIFIED: Label.UNVERIFIED,
        IsolationStatus.NOT_IMPLEMENTED: Label.OBSERVED,
    }[status]
    claims.append(
        Claim(
            f"OS isolation: {status.value}",
            label,
            source="babylab.isolation.assess_isolation",
        )
    )
    claims.append(
        Claim(
            f"Enforcement layer in force: {isolation.layer.value}",
            Label.OBSERVED,
            source="babylab.isolation.assess_isolation",
        )
    )

    for measurement in isolation.measurements:
        claims.append(
            Claim(
                f"{measurement.name}",
                Label.OBSERVED,
                source=measurement.source,
            )
        )

    if isolation.write_attempt_denied:
        claims.append(
            Claim(
                "A write from the lower-privilege identity was attempted and denied",
                Label.OBSERVED,
                source="babylab.isolation write attempt",
            )
        )
    else:
        unverified.append(
            Claim(
                "No write from a lower-privilege execution identity has been "
                "attempted and denied, so no OS-level boundary is proven",
                Label.UNVERIFIED,
                source="babylab.isolation.assess_isolation",
            )
        )

    for reason in isolation.reasons:
        claims.append(Claim(f"reason: {reason}", Label.OBSERVED, source="measured"))
    for prerequisite in isolation.prerequisites:
        unverified.append(
            Claim(
                f"prerequisite: {prerequisite}",
                Label.UNVERIFIED,
                source="babylab.isolation.assess_isolation",
            )
        )
    return claims, unverified
