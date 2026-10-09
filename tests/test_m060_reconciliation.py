"""M060 -- tests for the incident vs post-recovery reconciliation distinction.

All cases use disposable fixtures (tests.m052o_recovery._fixture), synthetic
evidence variations (no filesystem writes at all), or read-only live
production reads. No test mutates production, provenance, or seals.

CASE A -- incident-shaped fixture: incident PASS, post-recovery FAIL.
CASE B -- recovered state: incident FAIL, post-recovery PASS (live production,
         read-only; passes iff production is in the verified recovered state),
         plus clean-fixture incident FAIL.
CASE C -- unexpected state: neither mode PASS.
CASE D -- correct descriptor shape but wrong content: post-recovery FAIL.
CASE E -- accidental ACE gone but unrelated ACE changed: post-recovery FAIL.
CASE F -- owner/protection changed: post-recovery FAIL.
CASE G -- unavailable evidence: INCONCLUSIVE, never PASS.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from tests import m052o_recovery as O
from tests import m060_reconciliation as R


def _incident_fixture():
    return O._fixture(seed_accidental=True)


def _clean_fixture():
    return O._fixture(seed_accidental=False)


def test_modes_are_semantically_distinct():
    assert R.assess_incident_state.__name__ != R.assess_post_recovery_state.__name__
    assert "incident" in R.reconcile_incident_state.__name__
    assert "post_recovery" in R.reconcile_post_recovery_state.__name__
    note = R.legacy_incident_reconciliation_note()
    assert note["status"] == "PRESERVED_UNCHANGED"
    assert note["historical_function"] == "tests.m052p_governance.reconcile_read_only"


def test_case_a_incident_fixture():
    base, _root, target = _incident_fixture()
    try:
        assert Path(target).exists()
        ev = R.collect_evidence(target)
        assert ev is not None
        incident = R.assess_incident_state(ev)
        assert incident["mode"] == "INCIDENT_STATE"
        assert incident["verdict"] == "PASS", incident["checks"]
        post = R.assess_post_recovery_state(ev)
        assert post["mode"] == "POST_RECOVERY_STATE"
        assert post["verdict"] == "FAIL", post["checks"]
        assert post["checks"]["accidental_ace_absent"] == "FAIL"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_case_b_clean_fixture_is_not_incident():
    base, _root, target = _clean_fixture()
    try:
        ev = R.collect_evidence(target)
        assert ev is not None
        incident = R.assess_incident_state(ev)
        assert incident["verdict"] == "FAIL"
        assert incident["checks"]["incident_ace_present"] == "FAIL"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_case_b_live_production_recovered_state():
    """Read-only live check: production must be incident-FAIL and post-recovery-PASS."""
    from tests import m052p_governance as P
    from tests import path_policy as pp
    live = pp.read_production_for_verification(P.AFFECTED)
    ev = R.collect_evidence(live)
    assert ev is not None
    assert R.assess_incident_state(ev)["verdict"] == "FAIL"
    post = R.assess_post_recovery_state(ev)
    assert post["verdict"] == "PASS", post["checks"]


def test_case_c_unexpected_state_passes_neither():
    base, _root, target = _clean_fixture()
    try:
        ev = dict(R.collect_evidence(target))
        ev["descriptor_fp"] = "f" * 64
        ev["aces"] = ["ALLOW|S-1-5-32-544|0x001f01ff|inh"]
        assert R.assess_incident_state(ev)["verdict"] == "FAIL"
        result = R.assess_post_recovery_state(ev)
        assert result["verdict"] == "FAIL"
        assert result["verdict"] != "PASS"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _live_evidence():
    from tests import m052p_governance as P
    from tests import path_policy as pp
    ev = R.collect_evidence(pp.read_production_for_verification(P.AFFECTED))
    assert ev is not None
    assert R.assess_post_recovery_state(ev)["verdict"] == "PASS"
    return dict(ev)


def test_case_d_content_change_fails_post_recovery():
    ev = _live_evidence()
    ev["content_sha256"] = "0" * 64
    result = R.assess_post_recovery_state(ev)
    assert result["verdict"] == "FAIL"
    assert result["checks"]["content_unchanged"] == "FAIL"


def test_case_e_unrelated_acl_change_fails_post_recovery():
    ev = _live_evidence()
    aces = list(ev["aces"])
    aces[0] = "ALLOW|S-1-5-32-544|0x001200a9|inh"
    ev["aces"] = aces
    result = R.assess_post_recovery_state(ev)
    assert result["verdict"] == "FAIL"
    assert result["checks"]["unrelated_aces_unchanged"] == "FAIL"


def test_case_f_owner_protection_change_fails_post_recovery():
    ev = _live_evidence()
    ev["owner_sid"] = "S-1-5-21-2406520953-1060965512-844951592-1001-CHANGED"
    assert R.assess_post_recovery_state(ev)["verdict"] == "FAIL"
    ev = _live_evidence()
    ev["protected"] = True
    result = R.assess_post_recovery_state(ev)
    assert result["verdict"] == "FAIL"
    assert result["checks"]["protection_unchanged"] == "FAIL"


def test_case_g_unavailable_evidence_is_inconclusive_never_pass():
    assert R.assess_incident_state(None)["verdict"] == "INCONCLUSIVE"
    assert R.assess_post_recovery_state(None)["verdict"] == "INCONCLUSIVE"
    assert R.assess_incident_state(None)["verdict"] != "PASS"
    assert R.assess_post_recovery_state(None)["verdict"] != "PASS"
    missing = R.collect_evidence(Path("Z:/no/such/path/m016_read_fixture.exe"))
    assert missing is None
    assert R.reconcile_incident_state(
        Path("Z:/no/such/path/m016_read_fixture.exe")
    )["verdict"] == "INCONCLUSIVE"


def test_module_introduces_no_writer_or_execution_dependency():
    import pathlib
    source = pathlib.Path(R.__file__).read_text(encoding="utf-8")
    # Code forms only (docstring prose may describe what is absent).
    for token in ("m057_execution", "import subprocess", "from subprocess",
                  "K._ps", "_ps(", "_REMOVE_SCRIPT", "Set-Acl", "icacls",
                  "SetAccessControl(", "AddAccessRule(",
                  "RemoveAccessRuleSpecific("):
        assert token not in source, f"forbidden token in read-only module: {token}"
    assert "import" in source  # sanity: source was actually read
