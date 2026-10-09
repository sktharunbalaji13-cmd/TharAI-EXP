"""M060 -- post-recovery reconciliation versioning. Read-only.

Two different questions, two different functions. Confusing them caused the
M059 open audit item this module closes:

* :func:`reconcile_incident_state` asks: "Does the observed state match the
  known M052M *incident* state?" The defining incident marker is the
  accidental explicit DENY ACE (subject SID, ``0x00000001``). After the M057
  recovery this correctly evaluates to FAIL -- the incident no longer exists.
* :func:`reconcile_post_recovery_state` asks: "Does the observed state match
  the *verified M057 recovered* state?" Every dimension is pinned to the
  M057-verified values. Only an exact match passes.

The pre-existing :func:`tests.m052p_governance.reconcile_read_only` is left
byte-identical and remains the full historical incident record (18 checks,
disposable rehearsal included). Nothing here modifies it, wraps it
destructively, or reinterprets its FALSE-after-recovery checks as failure.

Safety boundary
---------------
This module is read-only. It performs descriptor reads, content hashing, and
ledger/gate reads only. It imports no writer: no OS ACL-mutation primitives,
no subprocess execution, no owner/inheritance mutation, and no filesystem
writers of any kind. It does not depend on the spent M057 execution artifact
as an implementation dependency. There is no code path here that can mutate
production, provenance, or seals.

Expectation sources
--------------------
Post-recovery expectations are pinned to the M057-verified values, with the
binding documented per constant below (milestone report values, themselves
verified against the sealed PROV-000016 authorisation and the PROV-000017
execution record). Incident-marker expectations come from
:mod:`tests.m052n_incident`. No new authorisation is created.

Result model
------------
Each assessment returns per-check ``PASS``/``FAIL`` and an overall verdict
of ``PASS``, ``FAIL``, or ``INCONCLUSIVE``. Unreadable or missing evidence
yields ``INCONCLUSIVE`` -- absence of evidence is never presented as PASS,
and a FALSE incident marker is reported as "incident absent", never as a
generic security failure.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from foundation import security_verify as sv
from tests import m052n_incident as N
from tests import m052o_recovery as O
from tests import m052p_governance as P
from tests import path_policy as pp

__all__ = [
    "POST_RECOVERY_DESCRIPTOR_FP", "POST_RECOVERY_CONTENT_SHA",
    "POST_RECOVERY_OWNER_SID", "POST_RECOVERY_ACES",
    "INCIDENT_NAMED_ACE", "EXPECTED_SEAL_HEAD",
    "collect_evidence", "assess_incident_state", "assess_post_recovery_state",
    "reconcile_incident_state", "reconcile_post_recovery_state",
    "legacy_incident_reconciliation_note",
]

#: Expected post-recovery descriptor hash. Binding: M057 verified poststate
#: (execution result poststate_fingerprint == expected d63ff646...), re-verified
#: read-only in M058/M059. Means: exactly the incident descriptor minus the
#: one accidental ACE, owner/protection/content/unrelated ACEs preserved.
POST_RECOVERY_DESCRIPTOR_FP = (
    "d63ff646bec494c198db9031491558f2744ea40bb2b1af016090e980865c1f27")

#: Expected file content hash. Binding: unchanged across M052M/M054/M056/M057,
#: verified read-only at every gate (55250a71..., 25 bytes).
POST_RECOVERY_CONTENT_SHA = (
    "55250a71209a4d397dc51f3f12da105455a5d20ace53062416d26079fded0cdf")

#: Expected owner. Binding: verified unchanged at every gate (operator SID -1001).
POST_RECOVERY_OWNER_SID = "S-1-5-21-2406520953-1060965512-844951592-1001"

#: Expected full ACE set after recovery: the four inherited unrelated ALLOWs,
#: byte-exact, in canonical descriptor_state encoding. Binding: M057 verified
#: unrelated_aces + M058/M059 re-verification.
POST_RECOVERY_ACES = (
    "ALLOW|S-1-5-11|0x001301bf|inh",
    "ALLOW|S-1-5-18|0x001f01ff|inh",
    "ALLOW|S-1-5-32-544|0x001f01ff|inh",
    "ALLOW|S-1-5-32-545|0x001200a9|inh",
)

#: The defining M052M incident marker: exact accidental ACE encoding.
#: Source: tests.m052n_incident (AFFECTED_RELATIVE_PATH, ACCIDENTAL_MASK).
INCIDENT_NAMED_ACE = f"DENY|{sv.SUBJECT_SID}|{N.ACCIDENTAL_MASK:#010x}|expl"

#: Ledger head expected after M057. Binding: sealed PROV-000017 execution record.
EXPECTED_SEAL_HEAD = "PROV-000017"

PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"


def collect_evidence(target: Path) -> dict[str, Any] | None:
    """Read-only collection of the security evidence for ``target``.

    Returns ``None`` when the target cannot be observed at all, so callers
    report INCONCLUSIVE rather than guessing. Reads the descriptor, the file
    bytes (hashed, never stored), and the identity-relevant fields only.
    """
    try:
        candidate = Path(target)
        if not candidate.exists():
            return None
        state = O.incident_state(candidate)
    except Exception:                                        # noqa: BLE001
        return None
    if not state.get("readable"):
        return None
    try:
        content_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
    except Exception:                                        # noqa: BLE001
        return None
    return {
        "target": str(candidate),
        "name": candidate.name,
        "readable": True,
        "aces": list(state.get("aces") or []),
        "descriptor_fp": O._descriptor_hash(state),
        "content_sha256": content_sha,
        "owner_sid": state.get("owner_sid"),
        "protected": state.get("protected"),
    }


def _verdict(checks: dict[str, str]) -> str:
    if any(v == INCONCLUSIVE for v in checks.values()):
        return INCONCLUSIVE
    return PASS if all(v == PASS for v in checks.values()) else FAIL


def assess_incident_state(evidence: dict[str, Any] | None) -> dict[str, Any]:
    """Does the observed state match the known M052M *incident* state?

    The incident is defined by its marker: the accidental explicit DENY ACE
    for the subject SID with mask ``0x00000001`` on the affected fixture.
    ``PASS`` means the incident marker is present; ``FAIL`` means the
    incident state is absent (which is the *expected* outcome after the M057
    recovery -- it must not be read as a security failure).
    """
    checks: dict[str, str] = {}
    if evidence is None or not evidence.get("readable"):
        return {"mode": "INCIDENT_STATE",
                "question": "Does the observed state match the known M052M incident state?",
                "verdict": INCONCLUSIVE,
                "checks": {"evidence_readable": INCONCLUSIVE},
                "detail": "target could not be observed; absence of evidence is not PASS"}
    checks["evidence_readable"] = PASS
    aces = evidence.get("aces") or []
    checks["incident_ace_present"] = (
        PASS if INCIDENT_NAMED_ACE in aces else FAIL)
    checks["incident_target_identity"] = (
        PASS if Path(evidence.get("target", "")).name == Path(P.AFFECTED).name
        else FAIL)
    checks["no_d3_mask"] = (
        PASS if not any("0x000d0156" in a.lower() for a in aces) else FAIL)
    verdict = _verdict(checks)
    return {
        "mode": "INCIDENT_STATE",
        "question": "Does the observed state match the known M052M incident state?",
        "verdict": verdict,
        "checks": checks,
        "meaning_of_fail": ("the incident state is absent (expected after M057 recovery); "
                            "not a security failure"),
        "descriptor_fp": evidence.get("descriptor_fp"),
    }


def assess_post_recovery_state(evidence: dict[str, Any] | None) -> dict[str, Any]:
    """Does the observed state match the *verified M057 recovered* state?

    Every dimension is pinned to the M057-verified values (see constant
    bindings above). ``PASS`` requires an exact match; anything else is
    ``FAIL``; unobservable evidence is ``INCONCLUSIVE``.
    """
    if evidence is None or not evidence.get("readable"):
        return {"mode": "POST_RECOVERY_STATE",
                "question": ("Does the observed state match the verified state "
                             "after M057 recovery?"),
                "verdict": INCONCLUSIVE,
                "checks": {"evidence_readable": INCONCLUSIVE},
                "detail": "target could not be observed; absence of evidence is not PASS"}
    aces = evidence.get("aces") or []
    checks = {
        "evidence_readable": PASS,
        "target_is_expected_fixture":
            PASS if Path(evidence.get("target", "")).name == Path(P.AFFECTED).name
            else FAIL,
        "accidental_ace_absent":
            PASS if INCIDENT_NAMED_ACE not in aces else FAIL,
        "no_subject_ace_remains":
            PASS if not [a for a in aces if sv.SUBJECT_SID in a] else FAIL,
        "descriptor_matches_post_recovery":
            PASS if evidence.get("descriptor_fp") == POST_RECOVERY_DESCRIPTOR_FP
            else FAIL,
        "content_unchanged":
            PASS if evidence.get("content_sha256") == POST_RECOVERY_CONTENT_SHA
            else FAIL,
        "owner_unchanged":
            PASS if evidence.get("owner_sid") == POST_RECOVERY_OWNER_SID else FAIL,
        "protection_unchanged":
            PASS if evidence.get("protected") is False else FAIL,
        "unrelated_aces_unchanged":
            PASS if sorted(aces) == sorted(POST_RECOVERY_ACES) else FAIL,
        "d3_absent":
            PASS if not any("0x000d0156" in a.lower() for a in aces) else FAIL,
    }
    return {
        "mode": "POST_RECOVERY_STATE",
        "question": ("Does the observed state match the verified state "
                     "after M057 recovery?"),
        "verdict": _verdict(checks),
        "checks": checks,
        "observed_descriptor_fp": evidence.get("descriptor_fp"),
        "observed_content_sha256": evidence.get("content_sha256"),
    }


def legacy_incident_reconciliation_note() -> dict[str, Any]:
    """Where the full historical incident record lives (preserved, not replaced).

    :func:`tests.m052p_governance.reconcile_read_only` -- the 18-check
    incident-state reconciliation with its disposable rehearsal -- is
    intentionally untouched by M060. Its checks 02/05/09 assert the incident
    state and therefore evaluate FALSE after recovery; that is the preserved
    historical meaning, not a defect to repair. This function documents the
    binding so no consumer mistakes the new mode for a rewrite of the old one.
    """
    return {
        "historical_function": "tests.m052p_governance.reconcile_read_only",
        "status": "PRESERVED_UNCHANGED",
        "incident_assertions": {
            "02_accidental_ace_present": "len(subject_aces) == 1",
            "05_ace_type_and_mask_unchanged": "requires non-empty subject ACEs",
            "09_no_second_accidental_ace": "exact incident path list",
        },
        "post_recovery_meaning": ("FALSE on 02/05/09 means the incident state is "
                                  "absent (recovery succeeded), not that recovery failed"),
    }


def reconcile_incident_state(target: Path | None = None) -> dict[str, Any]:
    """Incident-state reconciliation against a live target (read-only).

    Default target is the canonical production fixture, read through the
    verification (read-only) path. After M057 the expected verdict on
    production is FAIL -- incident absent -- which is success evidence for
    recovery, not a security failure.
    """
    resolved = (pp.read_production_for_verification(P.AFFECTED)
                if target is None else Path(target))
    return assess_incident_state(collect_evidence(resolved))


def reconcile_post_recovery_state(target: Path | None = None) -> dict[str, Any]:
    """Post-recovery reconciliation against a live target (read-only).

    Verifies the recovered-state assessment plus the surrounding coherence
    that makes the assessment meaningful: the sealed provenance head is still
    the M057 execution record, both gates remain closed, and the subject was
    not launched. All supporting reads are read-only (ledger verify, gate
    state, launch check); nothing is appended, sealed, or mutated.
    """
    from babylab.paths import default_paths
    from provenance.keyring import Keyring
    from provenance.ledger import ProvenanceLedger
    from tests import m052l_interlock as L
    import tests.m042_security_regression as sr

    resolved = (pp.read_production_for_verification(P.AFFECTED)
                if target is None else Path(target))
    assessment = assess_post_recovery_state(collect_evidence(resolved))
    extra: dict[str, str] = {}
    try:
        paths = default_paths()
        keyring = Keyring(paths.keyring, paths.private_key_dir)
        ledger = ProvenanceLedger(
            paths.provenance_ledger, keyring, seal_dir=paths.protected_provenance)
        report = ledger.verify(deep=True)
        seal = ledger.verify_seal()
        extra["provenance_chain_intact"] = PASS if report.intact else FAIL
        extra["sealed_head_is_expected_execution"] = (
            PASS if seal is not None and seal.intact
            and seal.head_entry_id == EXPECTED_SEAL_HEAD else FAIL)
    except Exception:                                        # noqa: BLE001
        extra["provenance_chain_intact"] = INCONCLUSIVE
        extra["sealed_head_is_expected_execution"] = INCONCLUSIVE
    try:
        extra["gate_1_closed"] = (
            PASS if L.evaluate(None)["gate_1"]["state"] == "CLOSED" else FAIL)
        extra["gate_2_closed"] = (
            PASS if L.interlock_state()["gate_2_open"] is False else FAIL)
        extra["subject_not_launched"] = (
            PASS if sr.check_no_launch()["baby_ai_test_password_value_read"] is False
            else FAIL)
    except Exception:                                        # noqa: BLE001
        extra["gate_1_closed"] = INCONCLUSIVE
        extra["gate_2_closed"] = INCONCLUSIVE
        extra["subject_not_launched"] = INCONCLUSIVE
    checks = {**assessment["checks"], **extra}
    return {
        "mode": "POST_RECOVERY_STATE",
        "question": assessment["question"],
        "assessment_verdict": assessment["verdict"],
        "verdict": _verdict(checks),
        "checks": checks,
        "observed_descriptor_fp": assessment.get("observed_descriptor_fp"),
        "observed_content_sha256": assessment.get("observed_content_sha256"),
    }
