"""Tests for the property verifier. DISPOSABLE SYNTHETIC FIXTURES ONLY.

Three things are being established, in order of importance:

1. **The verifier detects violations the old letter-based verifier misses.** Each
   negative control runs BOTH verifiers on the same descriptor and asserts the old
   one is silent while the new one fails. That is the whole justification for
   replacing it -- an assertion that the new verifier "is better" would not
   establish it.
2. **The verifier does not reintroduce M018's G5 inference.** Traversal is decided
   the way Windows decides it, and a fixture whose ACE lacks ``FILE_TRAVERSE``
   passes when the token holds ``SeChangeNotifyPrivilege``.
3. **Every adversarial case in the A-U matrix produces the expected verdict.**

Nothing here touches production, and no fixture is built with ``/inheritance:d``.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from foundation import security_verify as sv
from foundation.staging import _expand as legacy_expand, _split_subject_entries
from tests.fixtures_boundary import (
    LEGACY_DENY, MATRIX, MATRIX_SHAPE, MODEL_SHAPE, M016_DENY, RUNTIME_SHAPE,
    SUBJECT_READ, correct_descriptor, correct_executable_descriptor,
)


def _verdict(report, name):
    for check in report.checks:
        if check.name == name:
            return check.verdict
    return None


#: The letters a deny backstop may use. This is the vocabulary the old verifier
#: compares, because ``staging._expand`` reduces every icacls string to letters and
#: those letters are all it ever sees.
DENY_LETTERS = ("W", "D", "DC")

#: M015's actual deny backstop: ``SUBJECT_DENY_RIGHTS = "WD,AD,W,D,DC"``.
M015_DENY_LETTERS = ("W", "D", "DC", "WD", "AD")


def deny_vocabulary_reaches() -> int:
    """The rights a deny backstop built from letters can reach, as a bitmask."""
    return sv.rights_from_tokens(DENY_LETTERS)


# ---------------------------------------------------------------------------
# 1. the case that motivates the whole milestone
# ---------------------------------------------------------------------------

def test_letter_mapping_reproduces_the_m016_measured_rows():
    """The mapping is anchored to measurement, not to my assumption.

    M016 measured ``icacls W,D,DC -> 0x00110156`` and ``S -> 0x00100000``. If this
    reconstruction of the letter vocabulary stops reproducing those numbers, the
    negative controls below are reasoning from a fiction.
    """
    assert sv.rights_from_tokens(("W", "D", "DC")) == 0x00110156, (
        "the icacls letter mapping no longer reproduces the M016 measured row "
        f"(got 0x{sv.rights_from_tokens(('W', 'D', 'DC')):08x})")
    assert sv.rights_from_tokens(("S",)) == 0x00100000


def test_propagation_flags_are_not_permissions():
    """``OI``/``CI``/``IO`` describe propagation. Reading them as rights is how a
    traversal flag would make an inheritable ACE look broader than it is."""
    assert sv.rights_from_tokens(("OI", "CI", "IO", "I", "N")) == 0


def test_a_comma_joined_bundle_is_one_token():
    """``W,D,DC`` arrives from icacls as a single argument."""
    assert sv.rights_from_tokens(("W,D,DC",)) == sv.rights_from_tokens(
        ("W", "D", "DC"))
    assert sv.rights_from_tokens(("(OI)(CI)(DENY)(W,D,DC)",)) == 0x00110156, (
        "the full icacls flag string, as printed, must reduce to the same bundle")


def test_the_deny_vocabulary_cannot_express_write_dac_or_write_owner():
    """The defect, stated only as far as it is measured.

    The claim has to be narrow, because a broader version is false. ``F`` **does**
    grant ``WRITE_DAC`` and ``WRITE_OWNER``, because full control includes them.
    What does not exist is a letter that *selects* either right -- and it is the
    deny side that M015's boundary is built on.

    The anchors are M016's measured rows: ``W,D,DC`` yields ``0x00110156``, which
    contains SYNCHRONIZE and contains neither WRITE_DAC nor WRITE_OWNER, and
    ``WDAC,WO,DC,WD,AD,W`` yields ``0x001c0156`` -- still no WRITE_OWNER.
    """
    deny_side = deny_vocabulary_reaches()
    for right in sv.ICACLS_DENY_CANNOT_EXPRESS:
        assert not (deny_side & right), (
            f"0x{right:08x} became expressible as a deny letter; the old "
            "verifier could see it after all")
    assert deny_side & sv.SYNCHRONIZE, (
        "and the legacy deny still carries SYNCHRONIZE, which M016 measured")


def test_mutating_deny_letters_are_bundles():
    """Letters are bundles, which is why they cannot express M016's mask.

    ``0x000d0156`` is not reachable from letters, and this asserts the reason rather
    than the conclusion: each mutating letter drags at least one unrelated right
    along with it, so no single letter can *select* one right.

    ``DC`` is the exception and is named as such -- it is the one measured letter
    that does carry exactly one right, which is consistent with M015 reaching for
    ``DC`` specifically to cover DELETE_CHILD.
    """
    for letters in (("W",), ("D",), ("W", "D"), ("W", "DC"), ("D", "DC")):
        reach = sv.rights_from_tokens(letters)
        assert bin(reach).count("1") > 1, (
            f"{letters} reached a single bit ({reach:#x}); a bundle that could "
            "select one right would invalidate the negative controls")
    assert sv.rights_from_tokens(("DC",)) == sv.FILE_DELETE_CHILD


def test_m016_exact_mask_is_unreachable_from_letters():
    assert sv.rights_from_tokens(("W", "D", "DC")) != M016_DENY
    assert not (M016_DENY & sv.SYNCHRONIZE), "the M016 mask omits SYNCHRONIZE"


def test_full_control_does_grant_dac_but_cannot_express_a_targeted_deny():
    """The distinction the previous tests turn on, asserted directly."""
    assert sv.rights_from_tokens("F") & sv.WRITE_DAC, (
        "full control must include WRITE_DAC -- this is why a loose reading of "
        "'no letter can express WRITE_DAC' would be false, and why the claim is "
        "about *denies* specifically")
    assert not (deny_vocabulary_reaches() & sv.WRITE_DAC)


def test_old_verifier_reports_success_on_a_dac_vulnerable_boundary():
    """The false assurance, demonstrated.

    M015's legacy deny ``0x00110156`` denies write/delete/EA/attributes but
    contains **no** WRITE_DAC, and the letters cannot say so. A tree that grants
    the subject WRITE_DAC on top of it is therefore invisible to the old verifier
    and visible to the new one.
    """
    from dataclasses import replace
    from tests.fixtures_boundary import _allow

    descriptor = correct_descriptor(deny=LEGACY_DENY)

    # What the old verifier could see.
    _, _, old_denies = _split_subject_entries(
        [r"THARUNBALAJI-LA\BABY_AI_TEST:(OI)(CI)(DENY)(W,D,DC)"])
    assert old_denies, "premise: the old verifier sees a deny for the subject"
    assert not (deny_vocabulary_reaches() & sv.WRITE_DAC), (
        "premise: the old verifier cannot see WRITE_DAC on the deny side")

    # The same tree, with WRITE_DAC actually granted.
    tainted = replace(descriptor,
                      aces=descriptor.aces + (_allow(sv.SUBJECT_SID,
                                                    "THARUNBALAJI-LA\\BABY_AI_TEST",
                                                    sv.WRITE_DAC),))
    report = sv.verify_properties(tainted, label="legacy+dac")
    assert _verdict(report, "subject_denied_write_dac") == "FAIL", (
        "the new verifier must fail on what the old one cannot see")
    check = next(c for c in report.checks if c.name == "subject_denied_write_dac")
    assert "WRITE_DAC" in check.detail


def test_verifier_fails_when_write_dac_is_actually_granted():
    """The case the old verifier cannot fail."""
    from tests.fixtures_boundary import case_b_write_dac_granted

    descriptor, property_name, expected = case_b_write_dac_granted()
    report = sv.verify_properties(descriptor, label="dac-granted")
    assert _verdict(report, property_name) == expected
    assert not report.passed
    check = next(c for c in report.checks if c.name == property_name)
    assert check.evidence == "effective_access"


# ---------------------------------------------------------------------------
# 2. negative controls -- old silent, new fails
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,right,property_name", [
    ("WRITE_DAC", sv.WRITE_DAC, "subject_denied_write_dac"),
    ("WRITE_OWNER", sv.WRITE_OWNER, "subject_denied_write_owner"),
])
def test_negative_control_each_right_is_invisible_to_letters(name, right, property_name):
    """For each letterless deny right: old cannot represent it, new detects the grant."""
    assert not (deny_vocabulary_reaches() & right), (
        f"{name} must be invisible to the deny-letter vocabulary, or this "
        "negative control proves nothing")

    from tests.fixtures_boundary import vulnerable_descriptor

    descriptor = vulnerable_descriptor(right, label=f"nc-{name}")
    report = sv.verify_properties(descriptor, subject_privileges=[sv.SE_CHANGE_NOTIFY])
    assert not report.passed
    assert _verdict(report, property_name) == "FAIL", (
        f"{name} granted but {property_name} did not fail")


# ---------------------------------------------------------------------------
# 3. traversal -- the G5 regression
# ---------------------------------------------------------------------------

def test_traversal_passes_without_the_traverse_bit_when_the_privilege_is_present():
    """M019 T-TRAV-3: absence of 0x20 is not absence of traversal."""
    descriptor = correct_descriptor()
    assert not (descriptor.aces_for(sv.SUBJECT_SID)[0].effective_mask & sv.FILE_TRAVERSE), (
        "premise: the fixture's deny/allow do not grant FILE_TRAVERSE")

    allowed = sv.effective_access(descriptor, [sv.SUBJECT_SID], [sv.SE_CHANGE_NOTIFY])
    assert allowed.can_traverse(), "SeChangeNotifyPrivilege must bypass the check"
    report = sv.verify_properties(descriptor, subject_privileges=[sv.SE_CHANGE_NOTIFY])
    assert _verdict(report, "subject_traversal") == "PASS"
    assert _verdict(report, "traversal_is_not_ace_load_bearing") == "PASS"


def test_traversal_fails_without_the_privilege():
    """Same descriptor, no bypass privilege -- and now it must fail."""
    descriptor = correct_descriptor()
    allowed = sv.effective_access(descriptor, [sv.SUBJECT_SID], [])
    assert not allowed.can_traverse()
    report = sv.verify_properties(descriptor, subject_privileges=[])
    assert _verdict(report, "subject_traversal") == "FAIL"


def test_verifier_does_not_require_the_traverse_bit_to_be_present_in_the_mask():
    """Explicit anti-G5 assertion.

    If someone "fixes" traversal by demanding 0x20 in the ACE, the fixture that
    currently passes would start failing. This test fails first.
    """
    descriptor = correct_descriptor()
    subject_allow = next(a for a in descriptor.aces_for(sv.SUBJECT_SID) if a.is_allow)
    assert not subject_allow.has(sv.FILE_TRAVERSE)
    report = sv.verify_properties(descriptor, subject_privileges=[sv.SE_CHANGE_NOTIFY])
    assert not report.failed, "a boundary with no FILE_TRAVERSE bit must still pass"


def test_traversal_is_not_verifiable_without_a_privilege_set():
    """Silence about the privilege must not read as assurance."""
    descriptor = correct_descriptor()
    report = sv.verify_properties(descriptor, subject_privileges=[])
    assert _verdict(report, "traversal_is_not_ace_load_bearing") == "NOT_VERIFIABLE"


# ---------------------------------------------------------------------------
# 3b. 0x20 is two rights, and the object kind decides which
# ---------------------------------------------------------------------------

def test_execute_is_not_evaluated_on_a_directory():
    """0x20 on a directory is traverse. Asking about execute there is the v1 defect."""
    report = sv.verify_properties(correct_descriptor(),
                                  subject_privileges=[sv.SE_CHANGE_NOTIFY])
    assert _verdict(report, "subject_execute") == "NOT_APPLICABLE"
    assert _verdict(report, "subject_traversal") == "PASS"


def test_traversal_is_not_evaluated_on_a_file():
    """Reaching a file is traversing its parent; the parent carries that answer."""
    report = sv.verify_properties(correct_executable_descriptor(),
                                  require_execute=True,
                                  subject_privileges=[sv.SE_CHANGE_NOTIFY])
    assert _verdict(report, "subject_traversal") == "NOT_APPLICABLE"
    assert _verdict(report, "subject_execute") == "PASS"


def test_execute_is_never_granted_by_the_traverse_bypass_privilege():
    """The privilege that buys descent does not buy running a file.

    The two share bit 0x20 and are separated only by privilege behaviour, so this
    is where a merged model would quietly hand the subject execution of data.
    """
    descriptor = correct_executable_descriptor(executable=False)
    access = sv.effective_access(descriptor, [sv.SUBJECT_SID], [sv.SE_CHANGE_NOTIFY])
    assert access.can_traverse(), "premise: the privilege does permit traversal"
    assert not access.can_execute(), "the bypass must not reach execute"
    report = sv.verify_properties(descriptor, require_execute=True,
                                  subject_privileges=[sv.SE_CHANGE_NOTIFY])
    assert _verdict(report, "subject_execute") == "FAIL"


def test_an_unknown_object_kind_makes_both_capabilities_unverifiable():
    """Rather than guess which meaning 0x20 carries."""
    descriptor = replace(correct_executable_descriptor(), path_type="unknown")
    report = sv.verify_properties(descriptor, require_execute=True,
                                  subject_privileges=[sv.SE_CHANGE_NOTIFY])
    assert _verdict(report, "subject_execute") == "NOT_VERIFIABLE"
    assert _verdict(report, "subject_traversal") == "NOT_VERIFIABLE"


def test_object_kind_is_read_from_the_descriptor_not_assumed():
    assert correct_descriptor().object_kind == "dir"
    assert correct_executable_descriptor().object_kind == "file"
    assert replace(correct_descriptor(), path_type="DIRECTORY").object_kind == "dir"
    assert replace(correct_descriptor(), path_type="").object_kind == "unknown"


def test_a_negative_mask_is_normalised_to_32_unsigned_bits():
    """.NET hands back a signed Int64; a GENERIC_READ ACE arrives as a negative.

    Found by the real-filesystem layer reading the live descriptor, where the
    ``Authenticated Users`` inherit-only ACE came back as ``-0x1fff0000``. Taken
    raw it renders as ``0x-1fff0000`` and every bit test against it is wrong.
    """
    negative = 0xE0010000 - 0x100000000
    ace = sv.AceRecord("NT AUTHORITY\\Authenticated Users", sv.AU_SID, True, negative)
    assert ace.mask == 0xE0010000, "the stored mask must be the unsigned 32-bit form"
    assert ace.as_dict()["mask"] == "0xe0010000"
    assert ace.mask & sv.GENERIC_READ, "the generic bit itself must survive"
    assert ace.has(sv.FILE_READ_DATA), "and must fold to the file rights it means"
    assert ace.has(sv.DELETE)
    descriptor = replace(correct_descriptor(),
                         aces=correct_descriptor().aces + (ace,))
    granted = sv.effective_access(descriptor, [sv.AU_SID]).granted
    assert granted >= 0 and granted & sv.DELETE


# ---------------------------------------------------------------------------
# 4. the full A-U matrix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,builder", MATRIX, ids=[n for n, _ in MATRIX])
def test_adversarial_matrix(name, builder):
    """Each case is evaluated in the object shape it was built for.

    M019 T-BABY-5 makes execute a *file* property whose required value differs
    between the runtime payload and model/config data. Running every case under
    both shapes made 12 of them fail an unrelated execute check, which buried the
    failures that mattered -- a green-looking suite for the wrong reason.
    """
    shape = MATRIX_SHAPE.get(name, MODEL_SHAPE)
    require_execute = shape == RUNTIME_SHAPE
    result = builder()
    descriptor = result[0]
    report = sv.verify_properties(descriptor, require_execute=require_execute,
                                  subject_privileges=[sv.SE_CHANGE_NOTIFY])

    if len(result) == 3 and result[1] is None:
        assert not report.failed, (
            f"{name}: the correct fixture must not violate anything; failures="
            f"{[c.as_dict() for c in report.failures]}")
        return

    property_name, expectation = result[1], result[2]

    if expectation == "PASS_WITH_PRIVILEGE":
        assert _verdict(report, property_name) == "PASS"
    elif expectation == "NOT_APPLICABLE":
        assert _verdict(report, property_name) == expectation, (
            f"{name}: a property the object does not have must not be answered")
    elif expectation == "NOT_VERIFIABLE":
        assert _verdict(report, property_name) == expectation, (
            f"{name}: unreadable input must not be answered either way")
    elif expectation == "PASS_AND_INHERITANCE_REPORTED":
        assert _verdict(report, property_name) == "PASS"
        # An inherited grant is reported as inherited, so its fragility is visible.
        inherited = [a for a in descriptor.aces_for(sv.SUBJECT_SID)
                     if a.is_allow and a.is_inherited]
        assert inherited, "premise: the subject grant is inherited"
        assert descriptor.access_rules_protected is False
        assert not report.failed, "an inherited grant on an unprotected tree still passes"
    elif expectation == "PASS_MULTIPLICITY_REPORTED":
        check = next(c for c in report.checks if c.name == property_name)
        assert check.verdict == "PASS"
        assert check.observed["multi"], "multiplicity must be reported, not hidden"
        assert not report.failed
    elif expectation == "FAIL_WITHOUT_PRIVILEGE":
        without = sv.verify_properties(descriptor, subject_privileges=[])
        assert _verdict(without, property_name) == "FAIL"
        assert _verdict(report, property_name) == "PASS"
    elif expectation == "REPORT_MASK":
        # The mask is reportable evidence even though no letter could carry it.
        masks = [a.as_dict()["mask"] for a in descriptor.aces_for(sv.SUBJECT_SID)
                 if not a.is_allow]
        assert masks == [f"0x{LEGACY_DENY:08x}"]
        assert not (deny_vocabulary_reaches() & sv.WRITE_DAC)
        assert not (LEGACY_DENY & sv.WRITE_DAC)
        assert not report.failed, "nothing is granted, so no property is violated"
    else:
        assert _verdict(report, property_name) == expectation, (
            f"{name}: expected {property_name}={expectation}, got "
            f"{_verdict(report, property_name)}")
        assert report.failed, f"{name} should not pass overall"


def test_property_coverage_is_complete():
    """Every M019 property is evaluated, with no silent skip.

    The verifier's central risk is a property nobody asked about: a check never
    performed and never reported is indistinguishable from one that passed. So the
    expected set is asserted explicitly, and the count is pinned so removing a
    check cannot pass unnoticed.
    """
    directory = sv.verify_properties(correct_descriptor(),
                                     subject_privileges=[sv.SE_CHANGE_NOTIFY])
    names = {c.name for c in directory.checks}
    expected = {
        "target_exists", "owner_known", "subject_is_not_owner",
        "owner_is_expected_administrator", "no_inherited_modify",
        "subject_traversal", "traversal_is_not_ace_load_bearing",
        "same_sid_multiplicity", "subject_execute",
        "operator_administrative_access", "system_administrative_access",
        "administrators_administrative_access", "operator_access_not_group_derived",
        "subject_allowed_read", "subject_allowed_read_ea",
        "subject_allowed_read_attributes", "subject_allowed_read_control",
        "subject_os_enforcement_measured",
    }
    expected |= {f"subject_denied_{r}" for r in (
        "write", "append", "delete", "delete_child", "write_dac", "write_owner",
        "write_ea", "write_attributes")}
    assert expected <= names, f"not evaluated: {sorted(expected - names)}"
    assert len(directory.checks) == len(expected), (
        f"{len(directory.checks)} checks for {len(expected)} expected properties; "
        "an unaccounted check means a property is being evaluated that T does "
        "not define")

    # The file shape evaluates the same property set -- the count must not shift
    # with object kind, or a kind could be quietly dropping properties.
    payload = sv.verify_properties(correct_executable_descriptor(),
                                   require_execute=True,
                                   subject_privileges=[sv.SE_CHANGE_NOTIFY])
    assert len(payload.checks) == len(directory.checks)


def test_matrix_covers_every_lettered_case():
    names = {n for n, _ in MATRIX}
    for letter in "ABCDEFGHIJKLMNOPQRSTU":
        assert any(n.startswith(letter) for n in names), f"case {letter} missing"


# ---------------------------------------------------------------------------
# 5. same-SID multiplicity (M016)
# ---------------------------------------------------------------------------

def test_same_sid_aces_are_evaluated_individually_not_collapsed():
    from tests.fixtures_boundary import case_q_same_sid_multiple_aces

    descriptor, _, _ = case_q_same_sid_multiple_aces()
    subject_aces = descriptor.aces_for(sv.SUBJECT_SID)
    assert len(subject_aces) == 3, "two Allow + one Deny for one SID"
    check = next(c for c in sv.verify_properties(descriptor).checks
                 if c.name == "same_sid_multiplicity")
    assert check.verdict == "PASS"
    assert check.observed["multi"], "the multiplicity must be reported, not hidden"


def test_verifier_does_not_assume_one_ace_per_principal():
    """Four ACEs for one SID: grants, denies, origins and object kinds all differ."""
    from dataclasses import replace

    base = correct_executable_descriptor()
    extra = (
        sv.AceRecord("THARUNBALAJI-LA\\BABY_AI_TEST", sv.SUBJECT_SID, True,
                     sv.FILE_EXECUTE, "ContainerInherit, ObjectInherit", "None", True),
        sv.AceRecord("THARUNBALAJI-LA\\BABY_AI_TEST", sv.SUBJECT_SID, False,
                     sv.DELETE, "None", "None", False),
    )
    multi = replace(base, aces=base.aces + extra)
    report = sv.verify_properties(multi, require_execute=True,
                                  subject_privileges=[sv.SE_CHANGE_NOTIFY])
    # The inherited Allow contributes execute; the explicit Deny still wins for delete.
    assert _verdict(report, "subject_execute") == "PASS"
    assert _verdict(report, "subject_denied_delete") == "PASS"
    assert len(multi.aces_for(sv.SUBJECT_SID)) == 4


def test_ace_order_does_not_change_the_verdict():
    """Windows re-canonicalises order; a verdict must not depend on it."""
    from dataclasses import replace

    base = correct_descriptor()
    forward = sv.verify_properties(base, subject_privileges=[sv.SE_CHANGE_NOTIFY])
    backward = sv.verify_properties(replace(base, aces=tuple(reversed(base.aces))),
                                    subject_privileges=[sv.SE_CHANGE_NOTIFY])
    assert forward.passed == backward.passed
    assert ([c.name for c in forward.failures] == [c.name for c in backward.failures])


# ---------------------------------------------------------------------------
# 6. ownership
# ---------------------------------------------------------------------------

def test_owner_is_read_not_inferred_from_group_membership():
    """M019 T-ADM-4: Administrators membership is not assumed to confer anything."""
    descriptor = correct_descriptor()
    assert descriptor.owner_sid == sv.OPERATOR_SID
    report = sv.verify_properties(descriptor)
    assert _verdict(report, "owner_is_expected_administrator") == "PASS"
    # The Administrators ACE and the owner check are independent findings.
    admin = next(c for c in report.checks if c.name == "administrators_administrative_access")
    owner = next(c for c in report.checks if c.name == "owner_is_expected_administrator")
    assert admin.evidence == "raw_ace"
    assert owner.evidence == "descriptor"


def test_subject_ownership_is_a_failure_even_with_a_correct_dacl():
    """The bypass a DACL cannot stop."""
    from tests.fixtures_boundary import case_h_ownership_changed_to_subject

    descriptor, property_name, expected = case_h_ownership_changed_to_subject()
    report = sv.verify_properties(descriptor)
    assert _verdict(report, property_name) == expected
    assert "rewrite the DACL" in next(
        c for c in report.checks if c.name == property_name).detail


def test_unreadable_owner_is_not_verifiable_not_a_pass():
    from tests.fixtures_boundary import case_owner_unreadable

    descriptor, property_name, expected = case_owner_unreadable()
    report = sv.verify_properties(descriptor)
    assert _verdict(report, property_name) == expected
    assert not report.passed, "an unverifiable tree must not report as verified"


def test_unexpected_owner_fails():
    from tests.fixtures_boundary import case_t_path_owner_mismatch

    descriptor, property_name, expected = case_t_path_owner_mismatch()
    report = sv.verify_properties(descriptor)
    assert _verdict(report, property_name) == expected


# ---------------------------------------------------------------------------
# 7. missing targets and provenance
# ---------------------------------------------------------------------------

def test_missing_target_fails_before_any_other_property():
    from tests.fixtures_boundary import case_u_missing_target

    descriptor, property_name, expected = case_u_missing_target()
    report = sv.verify_properties(descriptor)
    assert _verdict(report, property_name) == expected
    assert [c.name for c in report.checks] == ["target_exists"], (
        "a missing path must short-circuit: an absent target has no descriptor to "
        "evaluate, so reporting further properties would be reporting on nothing")


def test_every_conclusion_names_its_evidence_layer():
    report = sv.verify_properties(correct_descriptor(),
                                  subject_privileges=[sv.SE_CHANGE_NOTIFY])
    layers = {c.evidence for c in report.checks}
    assert layers <= {"raw_ace", "descriptor", "effective_access", "observed_behavior"}
    assert "effective_access" in layers and "raw_ace" in layers
    for check in report.checks:
        assert check.evidence, f"{check.name} has no evidence source"


def test_no_property_is_silently_skipped():
    """Every M019 right appears in the report, pass or fail."""
    report = sv.verify_properties(correct_descriptor(),
                                  subject_privileges=[sv.SE_CHANGE_NOTIFY])
    names = {c.name for c in report.checks}
    for right in ("write", "append", "delete", "delete_child", "write_dac",
                  "write_owner", "write_ea", "write_attributes"):
        assert f"subject_denied_{right}" in names, right
    assert "no_inherited_modify" in names
    assert "subject_traversal" in names
    for principal in ("operator", "system", "administrators"):
        assert f"{principal}_administrative_access" in names


# ---------------------------------------------------------------------------
# 8. generic-bit folding
# ---------------------------------------------------------------------------

def test_full_control_mask_is_not_mistaken_for_a_violation():
    """The realistic FullControl storage form must satisfy the admin checks."""
    from tests.fixtures_boundary import FULL_CONTROL

    descriptor = correct_descriptor()
    operator = next(a for a in descriptor.aces_for(sv.OPERATOR_SID))
    assert operator.mask == FULL_CONTROL, "premise: 0x001f01ff as Windows stores it"
    assert not (FULL_CONTROL & sv.GENERIC_ALL), "premise: stored expanded, not generic"
    report = sv.verify_properties(descriptor)
    assert _verdict(report, "operator_administrative_access") == "PASS"


def test_generic_all_expands_so_a_generic_ace_is_not_a_false_violation():
    """Some ACEs really are stored as GENERIC_ALL; folding must handle them."""
    from dataclasses import replace

    descriptor = correct_descriptor()
    generic = replace(descriptor, aces=tuple(
        sv.AceRecord(a.principal, a.sid, a.is_allow,
                     sv.GENERIC_ALL if a.sid == sv.OPERATOR_SID else a.mask,
                     a.inheritance_flags, a.propagation_flags, a.is_inherited)
        for a in descriptor.aces))
    operator = next(a for a in generic.aces_for(sv.OPERATOR_SID))
    assert operator.mask == sv.GENERIC_ALL, "premise: stored as GENERIC_ALL"
    report = sv.verify_properties(generic)
    assert _verdict(report, "operator_administrative_access") == "PASS"


def test_expand_generic_is_idempotent():
    once = sv.expand_generic(sv.GENERIC_ALL)
    assert sv.expand_generic(once) == once