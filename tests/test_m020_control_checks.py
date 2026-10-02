"""Mutation tests: every M020 control must be *able* to fail.

A guard that cannot fail is not a guard. This is the same lesson as M017's
protected-state gate (``$protA``/``$protE`` never assigned, so the comparison was
vacuous) and M015's probe-guard flag/keyword mismatch (every lookup missed, so the
guard silently skipped everything while appearing to check).

Each test here corrupts one input and asserts the corresponding check changes its
verdict. If a control stops biting, the test fails -- which is the only way to know
a verifier is doing work rather than returning PASS.

Nothing is written to disk: source is tampered in memory only.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from foundation import security_verify as sv
from tests.fixtures_boundary import (
    MATRIX, MATRIX_SHAPE, MODEL_SHAPE, RUNTIME_SHAPE, correct_descriptor,
    vulnerable_descriptor,
)


def _verdict(report, name):
    return next((c.verdict for c in report.checks if c.name == name), None)


# ---------------------------------------------------------------------------
# verifier controls
# ---------------------------------------------------------------------------

def test_owner_check_bites_when_the_owner_becomes_the_subject():
    from tests.fixtures_boundary import case_h_ownership_changed_to_subject

    descriptor, _, _ = case_h_ownership_changed_to_subject()
    assert _verdict(sv.verify_properties(descriptor),
                    "subject_is_not_owner") == "FAIL"


def test_expected_owner_check_bites_on_a_mismatch():
    from tests.fixtures_boundary import case_t_path_owner_mismatch

    descriptor, _, _ = case_t_path_owner_mismatch()
    assert _verdict(sv.verify_properties(descriptor),
                    "owner_is_expected_administrator") == "FAIL"


def test_traversal_check_bites_when_the_privilege_is_removed():
    """The G5 regression, as a falsifiable control.

    Removing ``SeChangeNotifyPrivilege`` from the token must flip traversal from
    PASS to FAIL. If it does not, the verifier is reading the ACE after all and the
    M019 correction was not implemented.
    """
    descriptor = correct_descriptor()
    with_priv = sv.verify_properties(descriptor,
                                     subject_privileges=[sv.SE_CHANGE_NOTIFY])
    without = sv.verify_properties(descriptor, subject_privileges=[])
    assert _verdict(with_priv, "subject_traversal") == "PASS"
    assert _verdict(without, "subject_traversal") == "FAIL"


def test_inherited_modify_check_bites():
    from tests.fixtures_boundary import case_au_modify_inherited

    descriptor, _, _ = case_au_modify_inherited()
    assert _verdict(sv.verify_properties(descriptor),
                    "no_inherited_modify") == "FAIL"


@pytest.mark.parametrize("right,prop", [
    (sv.WRITE_DAC, "subject_denied_write_dac"),
    (sv.WRITE_OWNER, "subject_denied_write_owner"),
    (sv.FILE_WRITE_EA, "subject_denied_write_ea"),
    (sv.FILE_WRITE_ATTRIBUTES, "subject_denied_write_attributes"),
    (sv.FILE_WRITE_DATA, "subject_denied_write"),
    (sv.DELETE, "subject_denied_delete"),
])
def test_each_denial_check_bites(right, prop):
    """Every ``subject_denied_*`` check must be capable of FAIL."""
    good = sv.verify_properties(correct_descriptor(),
                                subject_privileges=[sv.SE_CHANGE_NOTIFY])
    assert _verdict(good, prop) == "PASS", f"{prop} should pass on a correct tree"

    bad = sv.verify_properties(vulnerable_descriptor(right),
                               subject_privileges=[sv.SE_CHANGE_NOTIFY])
    assert _verdict(bad, prop) == "FAIL", f"{prop} did not bite"


@pytest.mark.parametrize("principal,prop", [
    (sv.OPERATOR_SID, "operator_administrative_access"),
    (sv.SYSTEM_SID, "system_administrative_access"),
    (sv.ADMIN_SID, "administrators_administrative_access"),
])
def test_each_admin_check_bites(principal, prop):
    descriptor = correct_descriptor()
    good = sv.verify_properties(descriptor)
    assert _verdict(good, prop) == "PASS", f"{prop} should pass when granted"

    stripped = replace(descriptor, aces=tuple(
        a for a in descriptor.aces if a.sid != principal))
    assert _verdict(sv.verify_properties(stripped), prop) == "FAIL", (
        f"{prop} did not bite")


def test_read_grant_check_bites_when_the_read_is_withdrawn():
    descriptor = correct_descriptor()
    without_read = replace(descriptor, aces=tuple(
        a for a in descriptor.aces
        if not (a.sid == sv.SUBJECT_SID and a.is_allow)))
    report = sv.verify_properties(without_read,
                                  subject_privileges=[sv.SE_CHANGE_NOTIFY])
    assert _verdict(report, "subject_allowed_read") == "FAIL"


def test_execute_check_bites_in_both_directions():
    """M019 T-BABY-5 is two-sided: the runtime payload must run, data must not.

    Checking only the over-grant would let an under-grant through, and an
    under-grant is exactly the case C3 treats as a failure: a read-only grant on
    the loadable file leaves the runtime unloadable.
    """
    from tests.fixtures_boundary import correct_executable_descriptor

    runnable = correct_executable_descriptor(executable=True)
    assert _verdict(sv.verify_properties(runnable, require_execute=True),
                    "subject_execute") == "PASS"

    data = correct_executable_descriptor(executable=False)
    assert _verdict(sv.verify_properties(data, require_execute=False),
                    "subject_execute") == "PASS"

    # The same data file, graded against the runtime's requirement.
    assert _verdict(sv.verify_properties(data, require_execute=True),
                    "subject_execute") == "FAIL"
    # The same payload, graded against a data requirement.
    assert _verdict(sv.verify_properties(runnable, require_execute=False),
                    "subject_execute") == "FAIL"


def test_execute_is_undecidable_on_a_directory():
    """The check must not manufacture an answer for an object that lacks the
    capability -- and it must not quietly pass either."""
    report = sv.verify_properties(correct_descriptor())
    assert _verdict(report, "subject_execute") == "NOT_APPLICABLE"


def test_unknown_object_kind_makes_execute_unverifiable():
    descriptor = replace(correct_descriptor(), path_type="unknown")
    assert _verdict(sv.verify_properties(descriptor),
                    "subject_execute") == "NOT_VERIFIABLE"


def test_the_traverse_bypass_privilege_cannot_grant_execute():
    """The one bit that could hide the conflation, asserted directly."""
    from tests.fixtures_boundary import correct_executable_descriptor

    descriptor = correct_executable_descriptor(executable=False)
    access = sv.effective_access(descriptor, [sv.SUBJECT_SID],
                                 [sv.SE_CHANGE_NOTIFY])
    assert access.can_traverse(), "premise: traversal is permitted"
    assert not access.can_execute(), "execute must not follow from traversal"


def test_unreadable_owner_control_bites():
    from tests.fixtures_boundary import case_owner_unreadable

    descriptor, _, _ = case_owner_unreadable()
    report = sv.verify_properties(descriptor)
    assert _verdict(report, "owner_known") == "NOT_VERIFIABLE"
    assert not report.passed


# ---------------------------------------------------------------------------
# effective-access model
# ---------------------------------------------------------------------------

def test_deny_overrides_allow():
    """A deny that covers a right an allow grants must win."""
    descriptor = correct_descriptor()
    aces = descriptor.aces + (
        sv.AceRecord("THARUNBALAJI-LA\\BABY_AI_TEST", sv.SUBJECT_SID, True,
                     sv.DELETE, "None", "None", False),)
    tainted = replace(descriptor, aces=aces)
    access = sv.effective_access(tainted, [sv.SUBJECT_SID])
    assert access.permits(sv.DELETE) or access.denies(sv.DELETE), (
        "premise: delete is denied by the fixture's deny ACE")
    assert not access.permits(sv.DELETE), "deny must override allow"


def test_generic_folding_is_required_for_a_generic_all_ace():
    """Without folding, a GENERIC_ALL ACE looks like it grants nothing M019 needs."""
    descriptor = correct_descriptor()
    generic = replace(descriptor, aces=tuple(
        sv.AceRecord(a.principal, a.sid, a.is_allow,
                     sv.GENERIC_ALL if a.sid == sv.SYSTEM_SID else a.mask,
                     a.inheritance_flags, a.propagation_flags, a.is_inherited)
        for a in descriptor.aces))
    assert _verdict(sv.verify_properties(generic),
                    "system_administrative_access") == "PASS"


# ---------------------------------------------------------------------------
# probe-contract controls
# ---------------------------------------------------------------------------

def test_mutation_classifier_bites_when_a_read_only_operation_deletes():
    """The classifier must detect a mutating body, not merely report labels.

    Rewrites the probe source **in memory**. No file is written.
    """
    from tests import test_probe_operation_contract as contract

    quote = chr(34)
    real = f'Run({quote}workspace_read{quote}, () => {{ File.ReadAllText(wf); bump(); }});'
    tampered = f'Run({quote}workspace_read{quote}, () => {{ File.Delete(wf); bump(); }});'
    assert real in contract.SOURCE, "premise: the expected body is present"

    assert not contract._operation_region_contains("workspace_read", "File.Delete")
    original = contract.SOURCE
    try:
        contract.SOURCE = original.replace(real, tampered)
        assert contract._operation_region_contains("workspace_read", "File.Delete"), (
            "the classifier did not notice a READ_ONLY operation deleting a file")
    finally:
        contract.SOURCE = original
    assert not contract._operation_region_contains("workspace_read", "File.Delete")


def test_source_operation_scanner_bites_when_an_operation_is_added():
    """An undeclared operation must be detected, or the contract is not closed."""
    from tests import test_probe_operation_contract as contract

    original = contract.SOURCE
    try:
        contract.SOURCE = original + '\nConsole.WriteLine("probe=sneaky_new_op result=X");\n'
        assert "sneaky_new_op" in contract._source_operations()
        undeclared = contract._source_operations() - set(contract.OPERATION_CONTRACT)
        assert "sneaky_new_op" in undeclared
    finally:
        contract.SOURCE = original


def test_traverse_composition_scanner_bites_when_the_helper_renames():
    """The three traversal labels are composed, so a rename must be detected.

    ``Traverse`` emits ``"probe=" + label + "_to_leaf"``. If the helper or its base
    label changed, a hand-written contract list would still pass; recovering the
    names from the source is what prevents that.
    """
    from tests import test_probe_operation_contract as contract

    original = contract.SOURCE
    try:
        contract.SOURCE = original.replace('static void Traverse', 'static void Walk')
        assert "traverse_to_leaf" not in contract._source_operations(), (
            "a renamed traversal helper should stop producing the old labels")
    finally:
        contract.SOURCE = original
    assert "traverse_to_leaf" in contract._source_operations()


# ---------------------------------------------------------------------------
# the matrix itself
# ---------------------------------------------------------------------------

def test_every_adversarial_case_distinguishes_itself_from_the_correct_fixture():
    """No adversarial case may be indistinguishable from the correct one.

    A fixture that does not change the outcome is not testing anything, and a
    matrix of them would read as coverage while providing none.
    """
    baseline = sv.verify_properties(correct_descriptor(),
                                    subject_privileges=[sv.SE_CHANGE_NOTIFY])
    baseline_names = {c.name for c in baseline.failures}

    # Cases that must legitimately look like the correct fixture. Each is listed with
    # the reason it is not an adversarial violation, so the exemption is auditable
    # rather than a way to quiet a genuine indistinguishability.
    legitimately_clean = {
        "A_correct": "this IS the baseline",
        "P_inherited_vs_explicit": "an inherited grant is not a violation; the "
                                   "check reports its fragility instead",
        "Q_same_sid_multiple_aces": "multiplicity is reported, not violated",
        "R_traversal_differs_from_raw": "deliberately the same descriptor as A, "
                                        "graded under the privilege; what makes it "
                                        "distinct is the bypass_privilege evidence "
                                        "the check records, asserted by the "
                                        "PASS_WITH_PRIVILEGE branch",
        "S_privilege_dependent_traversal": "the privilege is supplied in this run",
        "Z_directory_asked_about_execute": "the object has no execute capability",
        "Y_object_kind_unknown": "reported NOT_VERIFIABLE, which is not a FAIL",
        "OWNER_unreadable": "reported NOT_VERIFIABLE, which is not a FAIL",
        "LEGACY_deny_missing_dac_owner": "nothing is granted, so nothing is violated",
    }

    indistinguishable = []
    for name, builder in MATRIX:
        if name in legitimately_clean:
            continue
        descriptor = builder()[0]
        require_execute = MATRIX_SHAPE.get(name, MODEL_SHAPE) == RUNTIME_SHAPE
        report = sv.verify_properties(descriptor, require_execute=require_execute,
                                      subject_privileges=[sv.SE_CHANGE_NOTIFY])
        if {c.name for c in report.failures} == baseline_names:
            indistinguishable.append(name)

    assert not indistinguishable, (
        f"adversarial cases indistinguishable from the correct fixture: "
        f"{indistinguishable}")


def test_the_matrix_fails_on_the_current_production_shape():
    """Applied to what production actually is, the verifier must not pass.

    P1 is fully inherited with inherited ``Authenticated Users`` Modify, so
    ``no_inherited_modify`` must fail. Read-only: the descriptor is read, nothing is
    changed. This is the alarm, and M020 must not soften it.
    """
    import sys
    if sys.platform != "win32":
        pytest.skip("Windows ACL semantics")
    from pathlib import Path

    descriptor = sv.read_descriptor(
        Path(__file__).resolve().parents[1] / "subject_runtime")
    report = sv.verify_properties(descriptor,
                                  subject_privileges=[sv.SE_CHANGE_NOTIFY])
    assert _verdict(report, "no_inherited_modify") == "FAIL", (
        "production still exposes inherited Authenticated Users Modify; if this "
        "ever passes, either production changed or the check is broken")
    assert not report.passed
    assert descriptor.exists and descriptor.aces, (
        "the read must have returned real descriptor content, not an empty shell")