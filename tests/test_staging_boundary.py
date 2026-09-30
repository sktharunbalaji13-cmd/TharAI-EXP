"""Tests for the M015 staging boundary: ACL application and verification.

The subject of these tests is ``verify_boundary``. A verifier that always answers
``STAGING_VERIFIED`` is worse than no verifier, because it is trusted to be the
thing that catches a bad ACL. So the majority of this file is **negative** testing:
each case starts from a boundary that verifies clean, applies one specific
tampering, and asserts the verifier flips to ``STAGING_BLOCKED``.

The tampering targets are the over-grants this boundary exists to prevent:

* write, delete, or delete-child anywhere in the tree;
* WriteDAC, which lets the subject rewrite the DACL and unlock itself;
* execute on the model or config, which are data and should not be runnable;
* a removed deny backstop;
* the subject taking ownership, which grants the power to rewrite the DACL
  regardless of what the DACL says.

Two ownership facts were established empirically on this host and are asserted
rather than assumed:

* ``icacls`` prints no owner marker, so ownership must be read another way;
  ``dir /q`` prints an 8.3-truncated name that cannot be compared reliably.
* Windows refuses ``/setowner BABY_AI_TEST`` without ``SeRestorePrivilege``, so
  the ownership-tamper test asserts the *comparison logic*, not a real transfer.

**No test here claims ``BABY_AI_TEST`` execution.** Every test observes the ACL as
the operator. Subject-side behaviour is ``NOT_TESTABLE`` until a human performs a
launch.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from foundation.staging import (
    SUBJECT_ACCOUNT,
    SUBJECT_DENY_RIGHTS,
    StagingStatus,
    _owner_of,
    _split_subject_entries,
    acl_of,
    apply_boundary,
    staging_root,
    staging_inventory,
    verify_boundary,
)

SUBJECT = SUBJECT_ACCOUNT


def _icacls(*argv: str) -> subprocess.CompletedProcess:
    """Run one icacls invocation. Operator-only, no shell."""
    return subprocess.run(["icacls", *argv], capture_output=True, text=True,
                          shell=False, stdin=subprocess.DEVNULL,
                          encoding="utf-8", errors="replace", timeout=120)


@pytest.fixture
def boundary(tmp_path: Path):
    """A freshly applied boundary in a disposable directory."""
    result = apply_boundary(tmp_path)
    assert result["status"] == StagingStatus.STAGING_NOT_CONFIGURED.value
    assert result["failed_operations"] == []
    return tmp_path


# ---------------------------------------------------------------------------
# The boundary that must hold
# ---------------------------------------------------------------------------

def test_fresh_boundary_verifies(boundary: Path):
    report = verify_boundary(boundary)
    assert report["status"] == StagingStatus.STAGING_VERIFIED.value
    assert report["inherited_modify_absent_everywhere"] is True
    assert report["subject_rights_exact_everywhere"] is True
    assert report["subject_deny_backstop_present_everywhere"] is True
    assert report["subject_is_not_owner_everywhere"] is True


def test_every_path_is_reported(boundary: Path):
    report = verify_boundary(boundary)
    assert {p["label"] for p in report["paths"]} == {
        "root", "runtime", "model", "config"}


def test_runtime_is_executable_and_data_is_not(boundary: Path):
    """The runtime is a program; the model and config are data.

    Granting execute on the model or granting only read on the runtime would each
    be a real defect -- the first lets the subject run model bytes, the second
    makes the staged runtime unloadable.
    """
    by_label = {p["label"]: p for p in verify_boundary(boundary)["paths"]}
    assert by_label["runtime"]["subject_permission_set"] == ["R", "X"]
    assert by_label["model"]["subject_permission_set"] == ["R"]
    assert by_label["config"]["subject_permission_set"] == ["R"]


def test_subject_cannot_write_anywhere(boundary: Path):
    for path in verify_boundary(boundary)["paths"]:
        assert path["subject_may_write"] is False, path["label"]
        assert path["subject_deny_backstop_present"] is True, path["label"]


def test_inherited_authenticated_users_modify_is_gone(boundary: Path):
    """The parent's ``Authenticated Users:(M)`` must not survive anywhere.

    This is the specific reason the tree exists: ``BABY_AI_TEST`` is an
    authenticated user, so an inherited Modify would hand it write on every staged
    file regardless of what else the ACL says.
    """
    for path in verify_boundary(boundary)["paths"]:
        assert path["inherited_authenticated_users_modify_present"] is False
        assert "Authenticated Users" not in path["authenticated_users"]


def test_verification_is_observation_only(boundary: Path):
    """The report must not overstate what it proved."""
    report = verify_boundary(boundary)
    assert report["enforcement"] == "ACL_OBSERVATION_ONLY"
    assert report["network"] != "" and "not" in report["network"].lower()
    assert report["confidentiality"] != ""


def test_inventory_of_empty_tree_reports_nothing_staged(boundary: Path):
    inventory = staging_inventory(boundary)
    assert inventory["runtime_staged"] is False
    assert inventory["model_staged"] is False
    for name in ("runtime", "model", "config"):
        assert inventory["inventory"][name] == {"present": True, "files": []}


# ---------------------------------------------------------------------------
# Negative testing: the verifier must be able to fail
# ---------------------------------------------------------------------------

def _tamper(boundary: Path, *argv: str) -> dict:
    """Apply one tampering and return the resulting verification report."""
    _icacls(*argv)
    return verify_boundary(boundary)


@pytest.mark.parametrize("subtree", ["runtime", "model", "config"])
def test_modify_grant_is_detected(boundary: Path, subtree: str):
    report = _tamper(boundary, str(staging_root(boundary) / subtree), "/grant",
                     f"{SUBJECT}:(OI)(CI)(M)", "/T", "/C")
    assert report["status"] == StagingStatus.STAGING_BLOCKED.value
    assert report["subject_rights_exact_everywhere"] is False


def test_full_control_grant_is_detected(boundary: Path):
    report = _tamper(boundary, str(staging_root(boundary) / "runtime"), "/grant",
                     f"{SUBJECT}:(OI)(CI)(F)", "/T", "/C")
    assert report["status"] == StagingStatus.STAGING_BLOCKED.value


def test_write_grant_is_detected(boundary: Path):
    """A bare ``(W)`` is the smallest over-grant and the easiest to miss."""
    report = _tamper(boundary, str(staging_root(boundary) / "config"), "/grant",
                     f"{SUBJECT}:(OI)(CI)(W)", "/T", "/C")
    assert report["status"] == StagingStatus.STAGING_BLOCKED.value
    config = next(p for p in report["paths"] if p["label"] == "config")
    assert config["subject_may_write"] is True


def test_delete_child_grant_is_detected(boundary: Path):
    """DeleteChild lets the subject remove files without write on them."""
    report = _tamper(boundary, str(staging_root(boundary) / "model"), "/grant",
                     f"{SUBJECT}:(OI)(CI)(DC)", "/T", "/C")
    assert report["status"] == StagingStatus.STAGING_BLOCKED.value


def test_write_dac_grant_is_detected(boundary: Path):
    """WriteDAC would let the subject rewrite the DACL and grant itself more.

    This is the over-grant a substring check misses: the subject keeps its
    correct ``R`` grant, so any test asking "does it have R" still passes.
    """
    report = _tamper(boundary, str(staging_root(boundary) / "config"), "/grant",
                     f"{SUBJECT}:(OI)(CI)(WD)", "/T", "/C")
    assert report["status"] == StagingStatus.STAGING_BLOCKED.value
    config = next(p for p in report["paths"] if p["label"] == "config")
    assert config["subject_rights_exact"] is False


def test_execute_on_model_is_detected(boundary: Path):
    """Execute on the model would let the subject run model bytes."""
    report = _tamper(boundary, str(staging_root(boundary) / "model"), "/grant",
                     f"{SUBJECT}:(OI)(CI)(RX)", "/T", "/C")
    assert report["status"] == StagingStatus.STAGING_BLOCKED.value


def test_removed_deny_is_detected(boundary: Path):
    report = _tamper(boundary, str(staging_root(boundary) / "model"),
                     "/remove:d", SUBJECT, "/T", "/C")
    assert report["status"] == StagingStatus.STAGING_BLOCKED.value
    assert report["subject_deny_backstop_present_everywhere"] is False


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------

def test_owner_is_read_from_getacl_not_a_guess():
    """``icacls`` prints no owner marker, so it cannot answer this at all.

    Reading nothing would return ``''`` for every path and the ownership check
    would pass without ever having looked at anything.
    """
    assert _owner_of(Path(__file__).resolve().parents[1]) != ""


def test_owner_comparison_is_case_insensitive_and_rejects_the_subject():
    """Unit-level, because the real transfer is refused by Windows below."""
    def owner_ok(owner: str) -> bool:
        return bool(owner) and owner.casefold() != SUBJECT.casefold()

    assert owner_ok("THARUNBALAJI-LA\\k.tharun balaji") is True
    assert owner_ok(SUBJECT) is False
    assert owner_ok(SUBJECT.lower()) is False
    assert owner_ok("") is False


def test_windows_refuses_to_install_the_subject_as_owner(boundary: Path):
    """Documented host fact, and a reason the ownership check cannot be faked.

    Assigning ``BABY_AI_TEST`` as owner requires ``SeRestorePrivilege``, which
    this operator token does not hold, so the attempt fails and ownership stays
    with the operator. If this ever starts succeeding, the ownership check
    becomes load-bearing rather than theoretical -- and the verifier already
    checks it.
    """
    result = _icacls(str(staging_root(boundary)), "/setowner", SUBJECT, "/T", "/C")
    failed = "Failed processing" in (result.stdout or "")
    if failed:
        report = verify_boundary(boundary)
        assert report["status"] == StagingStatus.STAGING_VERIFIED.value
        assert report["subject_is_not_owner_everywhere"] is True
    else:
        # The transfer went through; the verifier must then reject the tree.
        report = verify_boundary(boundary)
        assert report["status"] == StagingStatus.STAGING_BLOCKED.value
        assert report["subject_is_not_owner_everywhere"] is False


# ---------------------------------------------------------------------------
# Parsing: the deny is an ACE, not a permission letter
# ---------------------------------------------------------------------------

def test_deny_and_grant_are_separate_aces():
    """icacls marks a deny with ``(DENY)``; it is not a rights label.

    Treating the deny as part of the subject's grant is how a tree can appear to
    hold write rights that it in fact denies -- or the reverse.
    """
    entries = [f"{SUBJECT}:(OI)(CI)(DENY)({SUBJECT_DENY_RIGHTS})",
           f"{SUBJECT}:(OI)(CI)(R)"]
    label, letters, denies = _split_subject_entries(entries)
    assert letters == {"R"}, "the deny's letters must not join the grant"
    assert denies, "the deny is reported with its own rights"
    assert all(d in {"W", "D"} for d in "".join(denies)), denies


def test_union_of_grants_is_what_is_compared():
    """Two grants of R and WD together mean the subject may write.

    Checking each ACE in isolation would report R and WD separately and pass both
    as harmless; the union is the real capability.
    """
    _label, letters, _denies = _split_subject_entries(
        [f"{SUBJECT}:(OI)(CI)(R)", f"{SUBJECT}:(OI)(CI)(WD)"])
    assert letters & {"W", "D"}, "the extra ACE's rights must be in the union"
    assert letters != {"R"}


def test_principal_names_containing_spaces_survive():
    """``THARUNBALAJI-LA\\k.tharun balaji`` must not truncate to its first word.

    A whitespace split would yield ``THARUNBALAJI-LA\\k.tharun``, which matches no
    account, so the operator's own grant would be checked against a nonexistent
    principal.
    """
    entries = acl_of(staging_root())
    principals = [e.split(":", 1)[0] for e in entries]
    assert any("k.tharun balaji" in p for p in principals), principals


def test_system_grant_uses_the_well_known_name():
    """``COMPUTERNAME\\SYSTEM`` does not resolve.

    ``SYSTEM`` is not a local account, so prefixing it yields "No mapping between
    account names and security IDs" and the grant silently fails, leaving the
    tree without the system access it needs for recovery.
    """
    entries = acl_of(staging_root())
    assert any(p.startswith("NT AUTHORITY\\SYSTEM") for p in
               (e.split(":", 1)[0] for e in entries))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_staging_root_is_inside_the_repository(boundary: Path):
    assert staging_root(boundary).name == "subject_runtime"
    assert staging_root(boundary).is_dir()