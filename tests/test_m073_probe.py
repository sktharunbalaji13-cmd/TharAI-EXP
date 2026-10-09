"""M073 -- evidence-contract classification + fail-closed runner tests.

Pure-data tests (synthetic ProbeRecords) plus tmp_path target-existence checks.
No subject impersonation, no privileged probes, no production fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.m073_probe import (
    CANONICAL_PATH_IDS,
    EvidenceLog,
    ProbeRecord,
    ProbeRefused,
    ProbeResult,
    attempt_probe,
    check_evidence_complete,
    check_target_allowlisted,
    check_token,
    classify,
)

SID = "S-1-5-21-2406520953-1060965512-844951592-1022"
TARGET = "C:/repo/human_control/security/keys/private"
OTHER = "C:/repo/docs"


def _denied(**over) -> ProbeRecord:
    base = dict(probe_id="p1", path_id="provenance_private_keys", target=TARGET,
                operation="write", token_sid=SID, token_verified=True,
                started_at="2026-10-09T00:00:00Z", ended_at="2026-10-09T00:00:05Z",
                capture_method="subject-token write attempt",
                expected="OS_DENIED", observed="OS_DENIED",
                workspace_control_passed=True)
    base.update(over)
    return ProbeRecord(**base)


def test_1_pass_only_on_observed_denial():
    result, _ = classify(_denied())
    assert result == ProbeResult.PASS


def test_2_unexpected_access_is_fail():
    result, reasons = classify(_denied(observed="ACCESS_ALLOWED"))
    assert result == ProbeResult.FAIL, reasons


def test_3_non_permission_error_never_passes():
    for outcome in ("PATH_MISSING", "TIMEOUT", "UNREADABLE_TARGET",
                    "ENVIRONMENT_ERROR"):
        result, _ = classify(_denied(observed=outcome))
        assert result == ProbeResult.INCONCLUSIVE, outcome


def test_4_token_mismatch_refused_and_inconclusive():
    with pytest.raises(ProbeRefused):
        check_token(_denied(token_verified=False), SID)
    with pytest.raises(ProbeRefused):
        check_token(_denied(token_sid="S-1-5-999"), SID)
    result, _ = classify(_denied(token_verified=False))
    assert result == ProbeResult.INCONCLUSIVE


def test_5_missing_or_mismatched_target_refused():
    with pytest.raises(ProbeRefused):
        check_target_allowlisted(_denied(target=""), TARGET)
    with pytest.raises(ProbeRefused):
        check_target_allowlisted(_denied(), OTHER)
    with pytest.raises(ProbeRefused):
        attempt_probe(_denied(), intended_target=OTHER,
                      expected_sid=SID, authorized=True)


def test_6_workspace_control_failure_is_not_protection_proof():
    for value in (False, None):
        result, _ = classify(_denied(workspace_control_passed=value))
        assert result == ProbeResult.INCONCLUSIVE, value


def test_7_missing_timestamps_never_fresh_proof():
    with pytest.raises(ProbeRefused):
        check_evidence_complete(_denied(started_at="", ended_at=""))
    with pytest.raises(ProbeRefused):
        check_evidence_complete(_denied(capture_method=""))
    result, _ = classify(_denied(started_at="", ended_at=""))
    assert result == ProbeResult.INCONCLUSIVE


def test_8_cross_path_evidence_refused():
    rec = _denied(path_id="docs", target=OTHER)
    with pytest.raises(ProbeRefused):
        check_target_allowlisted(rec, TARGET)
    log = EvidenceLog().append(_denied()).append(rec)
    assert len(log.records) == 2
    assert len(log.for_path("provenance_private_keys")) == 1
    assert len(log.for_path("docs")) == 1


def test_9_log_is_append_only():
    log = EvidenceLog()
    second = log.append(_denied())
    assert log.records == ()
    assert len(second.records) == 1
    third = second.append(_denied(probe_id="p2"))
    assert [r.probe_id for r in third.records] == ["p1", "p2"]


def test_10_runner_refuses_without_prerequisites_and_without_mechanism():
    with pytest.raises(ProbeRefused, match="authorization"):
        attempt_probe(_denied(), intended_target=TARGET,
                      expected_sid=SID, authorized=False)
    with pytest.raises(ProbeRefused, match="NOT READY"):
        attempt_probe(_denied(), intended_target=TARGET,
                      expected_sid=SID, authorized=True)


def test_canonical_ids_match_protected_paths_source():
    from babylab.osboundary import protected_paths
    names = {p.name for p in protected_paths()}
    assert set(CANONICAL_PATH_IDS) == names


def test_module_contains_no_execution_or_privilege_machinery():
    source = Path(__import__("tests.m073_probe", fromlist=["x"]).__file__
                   ).read_text(encoding="utf-8")
    for token in ("import subprocess", "from subprocess", "LogonUser",
                  "CreateProcess", "Impersonat", "SeImpersonate",
                  "SetAccessControl", "AddAccessRule", "Set-Acl", "icacls",
                  "AdjustToken", "socket.", "firewall", "rmtree", "mkdir",
                  "open(", "os.replace", "os.remove"):
        assert token not in source, token


def test_reporting_changes_no_operational_state(tmp_path: Path):
    from babylab.hashing import file_sha256
    from babylab.paths import default_paths
    from provenance.keyring import Keyring
    from provenance.ledger import ProvenanceLedger
    paths = default_paths()
    watched = [paths.provenance_ledger,
               paths.root / "research" / "experiment-log.md",
               paths.root / "subject_runtime" / "runtime" / "m016_read_fixture.exe"]
    before = [file_sha256(p) for p in watched]
    keyring = Keyring(paths.keyring, paths.private_key_dir)
    ledger = ProvenanceLedger(paths.provenance_ledger, keyring,
                              seal_dir=paths.protected_provenance)
    n_before = sum(1 for _ in ledger.iter_entries())
    rec = _denied()
    classify(rec)
    log = EvidenceLog().append(rec)
    assert len(log.records) == 1
    after = [file_sha256(p) for p in watched]
    n_after = sum(1 for _ in ledger.iter_entries())
    assert before == after
    assert n_before == n_after == 18
    assert tmp_path.exists()
