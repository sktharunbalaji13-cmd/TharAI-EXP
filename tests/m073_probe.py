"""M073 -- Tier-2 re-probe evidence contract, classification, and safe runner gates.

READ-ONLY / NO-EXECUTION by construction. This module defines the evidence
record, the pure PASS/FAIL/INCONCLUSIVE/NOT_RUN classifier, prerequisite
gates, and an append-only evidence log. It contains NO execution machinery:
no subprocess, no impersonation, no token acquisition, no ACL readers or
writers, no network calls. ``attempt_probe()`` therefore always refuses --
there is no code path here that could observe as, or on behalf of, a subject.
Real probes require a future authorized milestone with a real subject-token
mechanism; this module is the contract that future work must satisfy.

Classification rules (binding):
* PASS requires an *observed* OS-level denial under a *verified* intended
  subject token, on the exact allowlisted target, with complete timestamps and
  capture metadata, plus a passing workspace control where one is required.
  ACL listings, inspections, declarations, and fixture results can never yield
  PASS -- only a real observation can.
* Unexpected access (the operation succeeded) is FAIL.
* A non-permission error (missing path, timeout, unreadable target) is
  INCONCLUSIVE -- never misread as a successful denial.
* Unverified/mismatched token, target mismatch, failed workspace control, or
  incomplete timestamps/evidence is INCONCLUSIVE (or refused pre-observation).
* NOT_RUN means the runner refused before any observation (missing identity
  mechanism, missing authorization, unallowlisted target).
* Evidence is append-only: records are never overwritten or mutated in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePath
from typing import Any


class ProbeResult(str, Enum):
    """Result vocabulary. Closed set; UNKNOWN is never a pass."""

    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_RUN = "NOT_RUN"


class ProbeRefused(RuntimeError):
    """A prerequisite gate refused before (or instead of) observation."""


#: Canonical protected-path identifiers. Source: babylab/osboundary.py
#: protected_paths() (13 entries, 2 absent: birth_records,
#: protected_configuration). The runner below binds probes to these ids only.
CANONICAL_PATH_IDS = (
    "event_log",
    "provenance_ledger",
    "provenance_seals",
    "provenance_keyring",
    "provenance_private_keys",
    "control_token",
    "birth_records",
    "research_records",
    "snapshots",
    "protected_configuration",
    "research_documentation",
    "experiment_log",
    "source_repository",
)


@dataclass(frozen=True)
class ProbeRecord:
    """One direct-probe evidence record. Frozen: append-only, never edited."""

    probe_id: str
    path_id: str
    target: str
    operation: str
    token_sid: str | None = None
    token_verified: bool = False
    started_at: str = ""
    ended_at: str = ""
    capture_method: str = ""
    expected: str = ""
    observed: str = ""
    workspace_control_passed: bool | None = None
    workspace_control_required: bool = True
    acl_evidence_at: str | None = None
    failure_detail: str = ""
    evidence_refs: tuple[str, ...] = ()
    reviewer_disposition: str = ""
    result: ProbeResult = ProbeResult.NOT_RUN


def _norm(path: str) -> str:
    return PurePath(str(path)).as_posix().lower()


def check_target_allowlisted(record: ProbeRecord, intended_target: str) -> None:
    """Refuse when the record does not name exactly the intended target."""
    if not (record.target or "").strip() or not (intended_target or "").strip():
        raise ProbeRefused("refused: missing target (record or intention)")
    if _norm(record.target) != _norm(intended_target):
        raise ProbeRefused(
            f"refused: target {record.target!r} is not the intended probe "
            f"target {intended_target!r}; evidence for one path cannot satisfy "
            f"another")


def check_token(record: ProbeRecord, expected_sid: str) -> None:
    """Refuse when token identity is unverified or mismatched."""
    if not record.token_verified:
        raise ProbeRefused("refused: subject-token identity not verified; "
                           "an unverified observation is INCONCLUSIVE, never PASS")
    if not record.token_sid or record.token_sid != expected_sid:
        raise ProbeRefused(
            f"refused: token {record.token_sid!r} is not the intended subject "
            f"token {expected_sid!r}")


def check_evidence_complete(record: ProbeRecord) -> None:
    """Refuse incomplete evidence before it can be mistaken for fresh proof."""
    missing = [name for name in ("started_at", "ended_at", "capture_method",
                                 "operation", "observed", "expected")
               if not str(getattr(record, name) or "").strip()]
    if missing:
        raise ProbeRefused(
            f"refused: incomplete evidence ({', '.join(missing)}); missing "
            f"timestamps or capture metadata cannot be silently treated as proof")


def classify(record: ProbeRecord) -> tuple[ProbeResult, list[str]]:
    """Classify gated evidence. Pure function; performs no observation.

    Returns (result, reasons). Refusals are raised by the check_* gates, not
    here, so this function only ever grades evidence that passed gating.
    """
    reasons: list[str] = []
    if not record.token_verified:
        return ProbeResult.INCONCLUSIVE, ["token identity not verified"]
    observed = (record.observed or "").strip().upper()
    expected = (record.expected or "").strip().upper()
    if not observed or not expected:
        return ProbeResult.INCONCLUSIVE, ["observed/expected outcome not recorded"]
    if observed in ("PATH_MISSING", "TIMEOUT", "UNREADABLE_TARGET",
                    "ENVIRONMENT_ERROR"):
        return ProbeResult.INCONCLUSIVE, [
            f"non-permission outcome {observed} is not a denial proof"]
    if observed != expected:
        if "ALLOW" in observed or "SUCCESS" in observed or "GRANTED" in observed:
            return ProbeResult.FAIL, ["unexpected access: operation was not denied"]
        return ProbeResult.INCONCLUSIVE, [
            f"observed {observed} does not match expected {expected}"]
    if record.workspace_control_required and record.workspace_control_passed is not True:
        return ProbeResult.INCONCLUSIVE, [
            "workspace control did not pass; a broken test environment is not "
            "protection proof"]
    if not (record.started_at or "").strip() or not (record.ended_at or "").strip():
        return ProbeResult.INCONCLUSIVE, ["timestamps missing; not fresh proof"]
    return ProbeResult.PASS, ["observed OS-level denial under verified token"]


@dataclass(frozen=True)
class EvidenceLog:
    """Append-only collection of probe records. Frozen tuple: no overwrite."""

    records: tuple[ProbeRecord, ...] = ()

    def append(self, record: ProbeRecord) -> "EvidenceLog":
        return EvidenceLog(records=(*self.records, record))

    def for_path(self, path_id: str) -> tuple[ProbeRecord, ...]:
        return tuple(r for r in self.records if r.path_id == path_id)


def attempt_probe(record: ProbeRecord, *, intended_target: str,
                  expected_sid: str, authorized: bool) -> ProbeRecord:
    """Fail-closed probe entry point. NEVER observes; always refuses.

    Gates run in order (target, token, completeness, authorization) so tests
    can prove each gate fires; the terminal refusal names the missing
    subject-token mechanism. There is deliberately no execution branch:
    adding real observation requires a future authorized milestone, not a
    flag flip here.
    """
    check_target_allowlisted(record, intended_target)
    check_token(record, expected_sid)
    check_evidence_complete(record)
    if not authorized:
        raise ProbeRefused("refused: no explicit human authorization for this probe")
    raise ProbeRefused(
        "refused: NOT READY -- no authorized subject-token execution mechanism "
        "exists (Tier-3 absent); real observation requires a future explicitly "
        "authorized milestone with token separation")


__all__ = [
    "ProbeResult", "ProbeRefused", "CANONICAL_PATH_IDS", "ProbeRecord",
    "EvidenceLog", "check_target_allowlisted", "check_token",
    "check_evidence_complete", "classify", "attempt_probe",
]
