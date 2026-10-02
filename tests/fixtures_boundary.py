"""Adversarial fixtures for the property verifier. TEST-ONLY, DISPOSABLE.

Every fixture here is a **synthetic descriptor record** unless explicitly marked as a
real filesystem tree. Synthetic descriptors are the right unit because the verifier
consumes descriptors, and a synthetic ACE is unambiguous in a way an ``icacls``
invocation is not: it can express exactly one right at a time, which is precisely
what the letter vocabulary cannot do and what the negative-control tests need.

The real-filesystem layer lives in ``test_security_verify_real.py`` and covers only
what synthetic records cannot: that the *reader* is faithful, and that the verifier
agrees with what Windows actually does.

Deliberately absent: no production path, and no attempt to build a same-SID fixture
via ``/inheritance:d``. That operation is the M016-rejected one and collapses
same-SID ACEs, so a fixture relying on it would test the defect rather than the
verifier. Same-SID multiplicity is built directly instead.
"""
from __future__ import annotations

from dataclasses import replace

from foundation.security_verify import (
    ADMIN_SID, AU_SID, DELETE, FILE_APPEND_DATA, FILE_DELETE_CHILD, FILE_EXECUTE,
    FILE_READ_ATTRIBUTES, FILE_READ_DATA, FILE_READ_EA,
    FILE_WRITE_ATTRIBUTES, FILE_WRITE_DATA, FILE_WRITE_EA, GENERIC_ALL,
    OPERATOR_SID, READ_CONTROL, SUBJECT_SID, SYSTEM_SID, SYNCHRONIZE,
    USERS_SID, WRITE_DAC, WRITE_OWNER,
    AceRecord, DescriptorRecord, expand_generic,
)

#: M016's exact candidate deny. Omits SYNCHRONIZE; includes WRITE_DAC/WRITE_OWNER.
M016_DENY = 0x000D0156
#: M015's legacy deny. Carries SYNCHRONIZE; omits WRITE_DAC/WRITE_OWNER.
LEGACY_DENY = 0x00110156

#: What Windows actually stores for a FullControl ACE on this host, read from the
#: live descriptor. Not GENERIC_ALL -- icacls /grant:(F) is written out in full.
FULL_CONTROL = 0x001F01FF

SUBJECT_READ = (FILE_READ_DATA | FILE_READ_EA | FILE_READ_ATTRIBUTES
                | READ_CONTROL | SYNCHRONIZE)
SUBJECT_READ_EXECUTE = SUBJECT_READ | FILE_EXECUTE
FULL = FULL_CONTROL

_SUBJECT = "THARUNBALAJI-LA\\BABY_AI_TEST"
_OPERATOR = "THARUNBALAJI-LA\\k.tharun balaji"
_ADMIN = "BUILTIN\\Administrators"
_SYSTEM = "NT AUTHORITY\\SYSTEM"
_AU = "NT AUTHORITY\\Authenticated Users"
_USERS = "BUILTIN\\Users"


def _allow(sid: str, name: str, mask: int, *, inherited: bool = False,
           inheritance: str = "ContainerInherit, ObjectInherit") -> AceRecord:
    return AceRecord(name, sid, True, mask, inheritance, "None", inherited)


def _deny(sid: str, name: str, mask: int, *, inherited: bool = False,
          inheritance: str = "ContainerInherit, ObjectInherit") -> AceRecord:
    return AceRecord(name, sid, False, mask, inheritance, "None", inherited)


def _boundary_aces(subject_mask: int, deny: int = M016_DENY) -> tuple[AceRecord, ...]:
    """The intended subject/admin shape, parameterised by mask and deny."""
    return (
        _deny(SUBJECT_SID, _SUBJECT, deny),
        _allow(SUBJECT_SID, _SUBJECT, subject_mask),
        _allow(OPERATOR_SID, _OPERATOR, FULL),
        _allow(SYSTEM_SID, _SYSTEM, FULL),
        _allow(ADMIN_SID, _ADMIN, FULL),
    )


def correct_descriptor(*, deny: int = M016_DENY, owner_sid: str = OPERATOR_SID,
                       owner: str = _OPERATOR, path: str | None = None,
                       kind: str = "dir") -> DescriptorRecord:
    """Case A -- the intended shape on a **directory**.

    Explicit, protected, subject read-only. Note what the subject's allow does
    *not* carry: ``FILE_TRAVERSE``. M019 T-TRAV-3 established that
    ``SeChangeNotifyPrivilege`` bypasses the traverse check, so demanding 0x20 here
    would be reintroducing G5 -- and the matrix case R depends on this fixture
    staying that way.

    ``kind`` exists because 0x20 is not one right. On a directory it is
    FILE_TRAVERSE; on a file it is FILE_EXECUTE, which no privilege bypasses. A
    fixture that did not distinguish them would be testing the conflation rather
    than the verifier, so the two shapes are separate constructors.
    """
    return DescriptorRecord(
        path=path or (r"C:\fixture\subject_runtime" if kind == "dir"
                      else r"C:\fixture\subject_runtime\config\weights.bin"),
        path_type=kind, exists=True, owner=owner, owner_sid=owner_sid,
        access_sddl="D:PAI(synthetic)", access_rules_protected=True,
        aces=_boundary_aces(SUBJECT_READ, deny))


def correct_executable_descriptor(*, executable: bool = True,
                                  owner_sid: str = OPERATOR_SID,
                                  owner: str = _OPERATOR,
                                  label: str = "runtime-payload") -> DescriptorRecord:
    """The runtime's loadable payload: a **file** the subject must be able to run.

    M019 T-BABY-5 is deliberately asymmetric -- execute on the runtime, not on
    model or config -- so the executable case and the data case are different
    fixtures on different object kinds, not one fixture with a flag.
    """
    mask = SUBJECT_READ_EXECUTE if executable else SUBJECT_READ
    return DescriptorRecord(
        path=rf"C:\fixture\subject_runtime\runtime\{label}",
        path_type="file", exists=True, owner=owner, owner_sid=owner_sid,
        access_sddl="D:PAI(synthetic)", access_rules_protected=True,
        aces=_boundary_aces(mask))


def vulnerable_descriptor(granted: int, *, base: DescriptorRecord | None = None,
                         label: str = "vulnerable") -> DescriptorRecord:
    """A descriptor on which ``granted`` is **effectively** available to the subject.

    The adversarial property must be genuinely violated, not merely accompanied by
    a deny that overrides it -- a deny wins over an allow, so a fixture that both
    denies and grants a right tests nothing. So the deny is reduced by exactly the
    targeted bit and the right is granted explicitly.

    That is also the real-world failure mode: the deny mask **omitted** a right. It
    is precisely M015's defect -- ``0x00110156`` has no WRITE_DAC -- and precisely
    what M016's exact-mask work existed to fix.
    """
    base = base or correct_descriptor()
    reduced_deny = M016_DENY & ~granted
    aces = tuple(
        replace(a, mask=reduced_deny) if (a.sid == SUBJECT_SID and not a.is_allow) else a
        for a in base.aces
    )
    aces = aces + (_allow(SUBJECT_SID, _SUBJECT, granted),)
    return replace(base, path=rf"C:\fixture\{label}", aces=aces)


def vulnerable_file(granted: int, *, executable: bool = True,
                    label: str = "vulnerable-file") -> DescriptorRecord:
    """:func:`vulnerable_descriptor` on a **file**, with execute as required.

    Pairs the granted right with M019's per-file execute requirement so a file
    case cannot silently inherit the directory shape.
    """
    return vulnerable_descriptor(
        granted, base=correct_executable_descriptor(executable=executable),
        label=label)


# ---------------------------------------------------------------------------
# A-U. Each returns (descriptor, property, expected verdict on that property).
# ---------------------------------------------------------------------------

def case_b_write_dac_granted():
    """WRITE_DAC accidentally granted because the deny omitted it."""
    return vulnerable_descriptor(WRITE_DAC, label="B"), \
        "subject_denied_write_dac", "FAIL"


def case_c_write_owner_granted():
    """WRITE_OWNER accidentally granted because the deny omitted it."""
    return vulnerable_descriptor(WRITE_OWNER, label="C"), \
        "subject_denied_write_owner", "FAIL"


def case_d_write_ea_granted():
    """FILE_WRITE_EA accidentally granted."""
    return vulnerable_descriptor(FILE_WRITE_EA, label="D"), \
        "subject_denied_write_ea", "FAIL"


def case_e_write_attributes_granted():
    """FILE_WRITE_ATTRIBUTES accidentally granted."""
    return vulnerable_descriptor(FILE_WRITE_ATTRIBUTES, label="E"), \
        "subject_denied_write_attributes", "FAIL"


def case_f_write_granted():
    """Plain write granted."""
    return vulnerable_descriptor(FILE_WRITE_DATA | FILE_APPEND_DATA, label="F"), \
        "subject_denied_write", "FAIL"


def case_g_delete_granted():
    """Delete granted."""
    return vulnerable_descriptor(DELETE | FILE_DELETE_CHILD, label="G"), \
        "subject_denied_delete", "FAIL"


def case_h_ownership_changed_to_subject():
    """The subject owns the path -- the bypass the DACL cannot stop."""
    d = correct_descriptor()
    return replace(d, owner=_SUBJECT, owner_sid=SUBJECT_SID), \
        "subject_is_not_owner", "FAIL"


def case_i_operator_admin_removed():
    d = correct_descriptor()
    kept = tuple(a for a in d.aces if a.sid != OPERATOR_SID)
    return replace(d, aces=kept + (_allow(OPERATOR_SID, _OPERATOR, READ_CONTROL),)), \
        "operator_administrative_access", "FAIL"


def case_j_system_removed():
    d = correct_descriptor()
    kept = tuple(a for a in d.aces if a.sid != SYSTEM_SID)
    return replace(d, aces=kept), "system_administrative_access", "FAIL"


def case_k_administrators_removed():
    d = correct_descriptor()
    kept = tuple(a for a in d.aces if a.sid != ADMIN_SID)
    return replace(d, aces=kept), "administrators_administrative_access", "FAIL"


def case_l_subject_write_granted():
    return vulnerable_descriptor(FILE_WRITE_DATA | FILE_APPEND_DATA, label="L"), \
        "subject_denied_write", "FAIL"


def case_m_subject_delete_granted():
    return vulnerable_descriptor(DELETE | FILE_DELETE_CHILD, label="M"), \
        "subject_denied_delete", "FAIL"


def case_n_subject_acl_modification_granted():
    return vulnerable_descriptor(WRITE_DAC, label="N"), \
        "subject_denied_write_dac", "FAIL"


def case_o_subject_ownership_modification_granted():
    return vulnerable_descriptor(WRITE_OWNER, label="O"), \
        "subject_denied_write_owner", "FAIL"


def case_p_inherited_differs_from_explicit():
    """The same grant inherited rather than explicit -- C2's origin requirement.

    Built directly rather than via ``/inheritance:d``: that operation collapses
    same-SID ACEs on this host, so using it would test the M016 defect instead of
    the verifier.

    An **inherited** Allow must not satisfy a property that requires an explicit
    one, because inheritance can be withdrawn by a parent change while an explicit
    ACE cannot. The report is expected to FAIL, which is what makes this a real
    adversarial case rather than a description.
    """
    from foundation.security_verify import effective_access

    d = correct_descriptor()
    aces = tuple(
        replace(a, is_inherited=True) if a.sid == SUBJECT_SID and a.is_allow else a
        for a in d.aces)
    derived = replace(d, aces=aces, access_rules_protected=False)
    # The subject's read grant is inherited; on an unprotected tree a parent change
    # can withdraw it, so the tree is not verifiably correct.
    inherited_allow = any(a.sid == SUBJECT_SID and a.is_allow and a.is_inherited
                          for a in derived.aces)
    assert inherited_allow, "premise: the subject grant really is inherited"
    assert effective_access(derived, [SUBJECT_SID]).permits(FILE_READ_DATA)
    return derived, "no_inherited_modify", "PASS_AND_INHERITANCE_REPORTED"


def case_q_same_sid_multiple_aces():
    """Two Allow ACEs for one SID, same type, different masks (M016's fixture).

    The verifier must evaluate both rather than collapse them, and must report the
    multiplicity. The property under test is the multiplicity *report itself*.
    """
    d = correct_descriptor()
    aces = d.aces + (_allow(SUBJECT_SID, _SUBJECT, FILE_READ_ATTRIBUTES),)
    multi = replace(d, aces=aces)
    subject_aces = multi.aces_for(SUBJECT_SID)
    assert len([a for a in subject_aces if a.is_allow]) == 2, "premise: two Allows"
    return multi, "same_sid_multiplicity", "PASS_MULTIPLICITY_REPORTED"


def case_r_traversal_differs_from_raw_expectation():
    """M019 T-TRAV: the ACE lacks FILE_TRAVERSE; the subject traverses anyway."""
    d = correct_descriptor()          # SUBJECT_READ has no FILE_TRAVERSE
    return d, "subject_traversal", "PASS_WITH_PRIVILEGE"


def case_s_privilege_dependent_traversal_absent():
    """Same ACE, but no SeChangeNotifyPrivilege -- traversal must then fail."""
    d = correct_descriptor()
    return d, "subject_traversal", "FAIL_WITHOUT_PRIVILEGE"


def case_t_path_owner_mismatch():
    d = correct_descriptor(owner_sid="S-1-5-21-9-9-9-1005", owner="CONTOSO\\someone")
    return replace(d, aces=d.aces + (_allow("S-1-5-21-9-9-9-1005", "CONTOSO\\someone",
                                            READ_CONTROL),)), \
        "owner_is_expected_administrator", "FAIL"


def case_u_missing_target():
    d = correct_descriptor()
    return replace(d, exists=False, aces=()), "target_exists", "FAIL"


def case_au_modify_inherited():
    """The P1 condition: inherited Authenticated Users Modify (M019 T-WR-11)."""
    return DescriptorRecord(
        path=r"C:\fixture\subject_runtime", path_type="dir", exists=True,
        owner=_OPERATOR, owner_sid=OPERATOR_SID, access_sddl="D:AI(synthetic)",
        access_rules_protected=False,
        aces=(_allow(AU_SID, _AU, 0x001301BF, inherited=True),
              _allow(USERS_SID, _USERS, SUBJECT_READ, inherited=True),
              _allow(OPERATOR_SID, _OPERATOR, FULL, inherited=True))), \
        "no_inherited_modify", "FAIL"


def case_owner_unreadable():
    d = correct_descriptor()
    return replace(d, owner="UNRESOLVED", owner_sid="UNRESOLVED"), \
        "owner_known", "NOT_VERIFIABLE"


def case_legacy_deny_missing_dac_and_owner():
    """M015's legacy mask: the deny itself omits WRITE_DAC and WRITE_OWNER.

    Nothing grants them either, so the subject has no access -- the report is PASS
    on those properties. The point is that **the mask is now visible**. The old
    letter vocabulary cannot state these rights on the deny side at all, so this
    omission was invisible; the new verifier reads the mask and the omission is
    reportable evidence rather than an unstated absence.
    """
    return correct_descriptor(deny=LEGACY_DENY), "subject_denied_write_dac", "REPORT_MASK"


# --- object-kind cases: the two capabilities that share one bit ---------------

def case_v_model_data_file_is_executable():
    """A model weight file granted execute. M019 T-BABY-5 forbids it.

    A directory fixture cannot express this: 0x20 on a directory is traverse,
    which the subject must have. 0x20 on a **file** is execute, which the subject
    must not have for model or config. The over-grant hands the subject the
    ability to run data as code, which is the harm T-BABY-5 names.
    """
    return correct_executable_descriptor(executable=True, label="config\\weights.bin"), \
        "subject_execute", "FAIL"


def case_w_runtime_payload_not_executable():
    """The runtime payload the subject cannot run. The other half of T-BABY-5.

    A read-only grant on the loadable file leaves the runtime unloadable, which is
    an under-grant rather than an over-grant -- and is just as much a failure of
    the intended boundary, which is why the check is a two-sided one.
    """
    return correct_executable_descriptor(executable=False), "subject_execute", "FAIL"


def case_x_traverse_bit_granted_on_data_file():
    """0x20 on a data file is execute, not traverse -- and it must not be read
    as the traversal property passing.

    The failure this guards is subtle: a verifier that treats 0x20 as "traverse"
    would report the traversal property satisfied by this ACE while the subject
    has quietly gained the ability to execute a model file.
    """
    d = correct_executable_descriptor(executable=True, label="config\\weights.bin")
    return d, "subject_execute", "FAIL"


def case_y_object_kind_unknown():
    """An object whose kind could not be read.

    Every conclusion that depends on what 0x20 means is unavailable, and the
    verifier must say so rather than pick the convenient reading.
    """
    d = replace(correct_descriptor(), path_type="unknown")
    return d, "subject_execute", "NOT_VERIFIABLE"


def case_z_directory_asked_about_execute():
    """A directory evaluated against the execute property.

    The property does not exist for the object, so the honest verdict is
    NOT_APPLICABLE. Returning PASS or FAIL here would be the conflation itself.
    """
    return correct_descriptor(), "subject_execute", "NOT_APPLICABLE"


#: The matrix, in the order the milestone specifies.
#:
#: Each entry carries the ``require_execute`` flag its object kind implies. M019
#: T-BABY-5 makes that flag differ between the runtime payload and model/config
#: data, and running a case under the wrong flag made it fail an unrelated check --
#: a green-looking suite for the wrong reason. Carrying the flag with the fixture
#: removes the possibility of the two drifting apart.
RUNTIME_SHAPE = "runtime"
MODEL_SHAPE = "model"

MATRIX_SHAPE = {
    "V_model_data_file_executable": MODEL_SHAPE,
    "X_traverse_bit_on_data_file": MODEL_SHAPE,
    "W_runtime_payload_not_executable": RUNTIME_SHAPE,
}

MATRIX: tuple[tuple[str, callable], ...] = (
    ("A_correct", lambda: (correct_descriptor(), None, None)),
    ("B_write_dac_granted", case_b_write_dac_granted),
    ("C_write_owner_granted", case_c_write_owner_granted),
    ("D_write_ea_granted", case_d_write_ea_granted),
    ("E_write_attributes_granted", case_e_write_attributes_granted),
    ("F_write_granted", case_f_write_granted),
    ("G_delete_granted", case_g_delete_granted),
    ("H_ownership_changed", case_h_ownership_changed_to_subject),
    ("I_operator_admin_removed", case_i_operator_admin_removed),
    ("J_system_removed", case_j_system_removed),
    ("K_administrators_removed", case_k_administrators_removed),
    ("L_subject_write_granted", case_l_subject_write_granted),
    ("M_subject_delete_granted", case_m_subject_delete_granted),
    ("N_subject_acl_modification_granted", case_n_subject_acl_modification_granted),
    ("O_subject_ownership_modification_granted", case_o_subject_ownership_modification_granted),
    ("P_inherited_vs_explicit", case_p_inherited_differs_from_explicit),
    ("Q_same_sid_multiple_aces", case_q_same_sid_multiple_aces),
    ("R_traversal_differs_from_raw", case_r_traversal_differs_from_raw_expectation),
    ("S_privilege_dependent_traversal", case_s_privilege_dependent_traversal_absent),
    ("T_path_owner_mismatch", case_t_path_owner_mismatch),
    ("U_missing_target", case_u_missing_target),
    ("V_model_data_file_executable", case_v_model_data_file_is_executable),
    ("W_runtime_payload_not_executable", case_w_runtime_payload_not_executable),
    ("X_traverse_bit_on_data_file", case_x_traverse_bit_granted_on_data_file),
    ("Y_object_kind_unknown", case_y_object_kind_unknown),
    ("Z_directory_asked_about_execute", case_z_directory_asked_about_execute),
    ("AU_inherited_modify", case_au_modify_inherited),
    ("OWNER_unreadable", case_owner_unreadable),
    ("LEGACY_deny_missing_dac_owner", case_legacy_deny_missing_dac_and_owner),
)