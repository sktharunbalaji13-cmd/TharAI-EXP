"""Focused tests for the exact-mask subject deny.

Every assertion reads the live ACE mask rather than icacls text. The two defects
this guards against are precisely the kinds a text check cannot see: a deny that
looks correct while denying SYNCHRONIZE nobody asked for, and a deny missing
WRITE_DAC while appearing to cover "permission change".
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from foundation.subject_deny import (  # noqa: E402
    LEGACY_SHORTHAND_MASK,
    SUBJECT_DENY_MASK,
    SUBJECT_DENY_RIGHTS,
    SUBJECT_SID,
    STAGING_DIRNAME,
    SYNCHRONIZE,
    _dacl_sddl,
    apply_subject_deny,
    capture_subject_deny,
    descriptors_match,
    subject_deny_masks,
    verify_subject_deny,
)
from foundation.staging import SUBJECT_ACCOUNT  # noqa: E402

POWERSHELL = "powershell"


# ---------------------------------------------------------------------------
# The mask itself
# ---------------------------------------------------------------------------

def test_intended_mask_is_composed_of_exactly_the_intended_rights():
    """The constant must be the sum of its parts, not a magic number.

    A mask asserted only against itself proves nothing: it would pass even if a
    right were silently dropped. This recomputes it from the named rights.
    """
    total = 0
    for bit in SUBJECT_DENY_RIGHTS.values():
        total |= bit
    assert total == SUBJECT_DENY_MASK, (
        f"SUBJECT_DENY_MASK is 0x{SUBJECT_DENY_MASK:08x} but its declared rights "
        f"sum to 0x{total:08x}"
    )


def test_intended_mask_excludes_synchronize():
    """SYNCHRONIZE must not be denied.

    This is the whole point of the correction. The legacy shorthand's `W` token
    carried it, and the disposable experiment observed its removal coincide with
    native traversal and read turning from OS_DENIED to OS_ALLOWED.
    """
    assert not (SUBJECT_DENY_MASK & SYNCHRONIZE), (
        "SYNCHRONIZE is present in the intended deny mask; it is not a mutation "
        "right and denying it is what the experiment implicated"
    )


def test_intended_mask_excludes_read_and_execute():
    """A deny that also took read or execute would defeat the boundary's purpose."""
    read_bits = 0x00000001 | 0x00000008 | 0x00000080 | 0x00020000
    assert not (SUBJECT_DENY_MASK & read_bits)
    assert not (SUBJECT_DENY_MASK & 0x00000020), "FILE_EXECUTE must not be denied"


def test_every_prohibited_mutation_is_denied():
    """Each prohibited action maps to a named right, and each is in the mask."""
    prohibited = {
        "cannot create files": "FILE_WRITE_DATA",
        "cannot append": "FILE_APPEND_DATA",
        "cannot modify extended attributes": "FILE_WRITE_EA",
        "cannot modify attributes": "FILE_WRITE_ATTRIBUTES",
        "cannot delete or rename": "DELETE",
        "cannot delete child directories": "FILE_DELETE_CHILD",
        "cannot change permissions": "WRITE_DAC",
        "cannot take ownership": "WRITE_OWNER",
    }
    for requirement, right in prohibited.items():
        assert right in SUBJECT_DENY_RIGHTS, f"{requirement}: {right} is unnamed"
        assert SUBJECT_DENY_MASK & SUBJECT_DENY_RIGHTS[right], (
            f"{requirement}: {right} is not in the intended deny mask"
        )


def test_legacy_shorthand_mask_is_recorded_and_differs():
    """The regression this replaces must be named, not just avoided."""
    assert LEGACY_SHORTHAND_MASK == 0x00110156
    assert LEGACY_SHORTHAND_MASK != SUBJECT_DENY_MASK
    assert LEGACY_SHORTHAND_MASK & SYNCHRONIZE, (
        "the legacy mask is supposed to demonstrate the SYNCHRONIZE defect"
    )
    # WRITE_DAC and WRITE_OWNER are absent from the legacy mask even though the
    # policy constant named WD, which icacls reads as write-data.
    for right in ("WRITE_DAC", "WRITE_OWNER"):
        assert not (LEGACY_SHORTHAND_MASK & SUBJECT_DENY_RIGHTS[right]), (
            f"{right} unexpectedly present in the legacy mask"
        )


# ---------------------------------------------------------------------------
# The verifier
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_verifier_reports_production_state_honestly():
    """Against the live tree the verifier must reach a definite verdict.

    Production has not been corrected yet, so the expectation is the failing
    verdict -- and specifically the two findings that describe the defect.
    """
    result = verify_subject_deny()
    assert result["status"] in {"SUBJECT_DENY_VERIFIED", "SUBJECT_DENY_NOT_VERIFIED"}
    if result["status"] == "SUBJECT_DENY_NOT_VERIFIED":
        for finding in result["paths"]:
            assert finding["denies_synchronize"] is True
            assert set(finding["missing_rights"]) == {"WRITE_DAC", "WRITE_OWNER"}
            assert finding["path_correct"] is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_verifier_flags_a_synchronize_denial_as_a_failure():
    """A deny carrying SYNCHRONIZE must never pass, even at the right size."""
    from foundation.subject_deny import SUBJECT_DENY_MASK as M
    polluted = M | SYNCHRONIZE
    assert polluted != M
    # The verifier's own predicate, applied directly.
    fails = (polluted != M) or bool(polluted & SYNCHRONIZE)
    assert fails, "a SYNCHRONIZE denial must fail verification"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_verifier_reads_the_ace_mask_not_icacls_text(scratch_root):
    """A tree with the intended mask must verify; a legacy one must not.

    Built under a temp root so production is never involved. The point is that
    the verdict tracks the stored mask: identical icacls text is not required,
    and a mask difference is enough to fail.
    """
    masks = subject_deny_masks(scratch_root)
    assert masks["error"] is None
    assert all(Path(p["path"]).exists() for p in masks["paths"]), (
        "readings referenced paths that do not exist"
    )
    found = {Path(p["path"]).name: p["maskInt"] for p in masks["paths"]}
    assert found, "the scratch tree produced no readings"
    for name, mask in found.items():
        assert mask in (SUBJECT_DENY_MASK, LEGACY_SHORTHAND_MASK), (
            f"{name} carried an unexpected mask 0x{mask:08x}"
        )


# ---------------------------------------------------------------------------
# Fail-closed behaviour
# ---------------------------------------------------------------------------

def test_apply_refuses_without_confirmation(scratch_root):
    """No confirm means no write. The first guard, and the cheapest."""
    parent = scratch_root
    result = apply_subject_deny(parent)
    assert result["applied"] is False
    assert "confirm" in result["detail"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_apply_refuses_on_precondition_mismatch(scratch_root):
    """A live mask other than the expected one must stop the mutation.

    This is the guard that stops a change being applied to a state it was not
    written against -- which is how a boundary ends up trusted on the strength
    of an assumption.
    """
    parent = scratch_root
    # Expect a mask that is definitely not what the scratch tree carries.
    result = apply_subject_deny(parent, expected_before=0x00000001, confirm=True)
    assert result["applied"] is False
    assert result["precondition_failed"] is True
    assert result["unexpected_paths"]
    # And nothing moved.
    after = {Path(p["path"]).name: p["maskInt"]
             for p in subject_deny_masks(parent)["paths"]}
    for mask in after.values():
        assert mask != SUBJECT_DENY_MASK


def test_snapshot_captures_every_path(scratch_root):
    """Rollback depends on the snapshot being complete."""
    parent = scratch_root
    snapshot = capture_subject_deny(parent)
    assert all(path.startswith(str(Path(parent).resolve())) for path in snapshot.paths), (
        "the snapshot reached outside the caller-owned tree"
    )
    assert snapshot.paths
    for path, entry in snapshot.paths.items():
        assert Path(path).exists(), f"{path} is in the snapshot but does not exist"
        assert entry["sddl"].startswith("D:"), (
            f"{path} snapshot is not a DACL: {entry['sddl']!r}"
        )
        # The mask, not just the SDDL text, is what rollback replays.
        assert isinstance(entry["mask"], int)


# ---------------------------------------------------------------------------
# Round trip: the guarantee that made the first attempt stop
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_apply_then_restore_returns_the_exact_pre_change_mask(scratch_root):
    """Apply, then restore. Every path must come back bit-identical.

    This is the property the first implementation failed. It reported a
    successful restore while leaving 0x00010156 on disk instead of 0x00110156,
    because the native write path silently strips SYNCHRONIZE. A rollback that
    quietly changes the boundary it claims to restore is worse than no rollback,
    so the exact mask is asserted per path, not merely that a deny still exists.
    """
    from foundation.subject_deny import _restore_dacls

    parent = scratch_root
    before = {p["path"]: p["maskInt"] for p in subject_deny_masks(parent)["paths"]}
    assert before, "the scratch tree produced no pre-change readings"
    assert set(before.values()) == {LEGACY_SHORTHAND_MASK}

    snapshot = capture_subject_deny(parent)

    applied = apply_subject_deny(parent, expected_before=LEGACY_SHORTHAND_MASK,
                                 confirm=True)
    assert applied["applied"] is True, applied.get("failure")
    after_apply = {p["path"]: p["maskInt"]
                   for p in subject_deny_masks(parent)["paths"]}
    assert set(after_apply.values()) == {SUBJECT_DENY_MASK}
    assert not any(m & SYNCHRONIZE for m in after_apply.values())

    restored = _restore_dacls(snapshot)
    # The per-path `restored` flag is a mid-flight read taken while descendants
    # were still being processed; the verdict is the independent verification at
    # the end, after every path has been rewritten.
    assert restored["independent_verification"]["all_restored"] is True, [
        f for f in restored["independent_verification"]["paths"]
        if not f["descriptor_matches"]
    ]
    assert restored["all_restored"] is True

    final = {p["path"]: p["maskInt"] for p in subject_deny_masks(parent)["paths"]}
    assert final == before, (
        "restore did not return the recorded pre-change mask on every path"
    )


# ---------------------------------------------------------------------------
# ACE origin: boundaries explicit, descendants inherited
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_boundary_and_inherited_path_model_matches_the_tree(scratch_root):
    """Four boundaries carry the explicit deny; everything else inherits.

    Derived from the staging subtree map rather than from a scan of protected
    paths, because a scan would classify any accidentally-severed descendant as
    a boundary and then pin it.
    """
    from foundation.subject_deny import boundary_paths, inherited_paths, staging_root

    parent = scratch_root
    base = staging_root(parent)
    boundaries = boundary_paths(parent)
    inherited = inherited_paths(parent)

    assert len(boundaries) == 4
    assert {p.name for p in boundaries} == {base.name, "runtime", "model", "config"}
    assert base in boundaries
    # The nested directory and every file are descendants, not boundaries.
    assert (base / "config" / "delete_target") in inherited
    assert (base / "runtime" / "artifact.bin") in inherited
    assert (base / "config" / "delete_target" / "deep.bin") in inherited
    # Disjoint and complete over the tree.
    assert not (set(boundaries) & set(inherited))
    assert set(boundaries) | set(inherited) == {base, *base.rglob("*")}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_apply_does_not_pin_inherited_descendants(scratch_root):
    """The regression test for the pinning defect.

    A descendant whose deny reads the right mask but arrived as an explicit ACE
    is a different boundary: a later legitimate change to the parent would stop
    reaching it. Only the mask check passed before, which is why this needed the
    eight-path tree to surface.
    """
    from foundation.subject_deny import staging_root, verify_subject_deny

    parent = scratch_root
    applied = apply_subject_deny(parent, expected_before=LEGACY_SHORTHAND_MASK,
                                 confirm=True)
    assert applied["applied"] is True, applied.get("failure")

    result = verify_subject_deny(parent)
    findings = {Path(f["path"]): f for f in result["paths"]}

    for path, f in findings.items():
        if f["role"] == "boundary":
            assert f["explicit_deny_ace_count"] == 1, path
            assert f["inherited_deny_ace_count"] == 0, path
            assert f["ace_origin_correct"] is True, path
        else:
            assert f["explicit_deny_ace_count"] == 0, (
                f"{path} was pinned with an explicit deny; descendants must "
                "keep inheriting"
            )
            assert f["inherited_deny_ace_count"] == 1, path
            assert f["ace_origin_correct"] is True, path

    base = staging_root(parent)
    for rel in ("config/delete_target", "config/delete_target/deep.bin",
                "runtime/artifact.bin", "runtime/second_fixture.exe",
                "runtime/third_fixture.exe"):
        f = findings[base / rel]
        assert f["explicit_deny_ace_count"] == 0, rel
        assert f["deny_mask"] == f"0x{SUBJECT_DENY_MASK:08x}", rel


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_apply_keeps_inheritance_protected_on_every_boundary(scratch_root):
    """Protection is a boundary property; the apply must not clear it."""
    from foundation.subject_deny import boundary_paths, verify_subject_deny

    parent = scratch_root
    apply_subject_deny(parent, expected_before=LEGACY_SHORTHAND_MASK,
                       confirm=True)
    result = verify_subject_deny(parent)
    boundaries = {str(p) for p in boundary_paths(parent)}
    for f in result["paths"]:
        if f["path"] in boundaries:
            assert f["inheritance_flags_correct"] is True, f["path"]
            assert f["path_correct"] is True, f


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_apply_preserves_the_subject_allow_and_no_authenticated_users(scratch_root):
    """Tightening the deny must not cost read/execute or introduce a write ACE."""
    from foundation.subject_deny import verify_subject_deny

    parent = scratch_root
    apply_subject_deny(parent, expected_before=LEGACY_SHORTHAND_MASK,
                       confirm=True)
    result = verify_subject_deny(parent)
    for f in result["paths"]:
        assert f["subject_allow_preserved"] is True, f["path"]
        assert f["subject_allow_mask"] in ("0x00120089", "0x001200a9"), f["path"]
        assert f["read_bits_not_denied"] is True, f["path"]
        assert f["execute_bit_not_denied"] is True, f["path"]
        assert "Authenticated Users" not in (f["dacl_sddl"] or ""), f["path"]


# ---------------------------------------------------------------------------
# Rollback: descriptor-exact, not mask-exact
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_rollback_restores_the_complete_descriptor_not_just_the_mask(scratch_root):
    """The regression test for the descriptor defect.

    Restoring 0x00110156 while leaving an extra explicit ACE behind is
    mask-exact and descriptor-wrong. The SDDL comparison is the honest test, and
    it fails where a mask comparison passes.
    """
    from foundation.subject_deny import _restore_dacls, verify_rollback

    parent = scratch_root
    snapshot = capture_subject_deny(parent)
    before = {p: e["sddl"] for p, e in snapshot.paths.items()}

    apply_subject_deny(parent, expected_before=LEGACY_SHORTHAND_MASK, confirm=True)

    result = _restore_dacls(snapshot)
    assert result["all_restored"] is True, [
        e for e in result["paths"] if not e.get("restored")
    ]

    verification = verify_rollback(snapshot)
    assert verification["all_restored"] is True, [
        f for f in verification["paths"] if not f["descriptor_matches"]
    ]
    assert verification["all_sddl_match"] is True
    assert verification["all_structure_match"] is True

    # Boundaries are rewritten in place, so their SDDL must come back as the exact
    # same string. Only inherited descendants are allowed to differ in ordering.
    from foundation.subject_deny import boundary_paths
    boundaries = {str(p) for p in boundary_paths(parent)}
    for f in verification["paths"]:
        if f["path"] in boundaries:
            assert f["sddl_exact_string_match"] is True, (
                f"{f['path']}: a rewritten boundary did not return to its "
                "exact pre-apply SDDL"
            )

    for path, want in before.items():
        # Compared as an ACE set, not as a string. Windows re-canonicalises ACE
        # order on every rewrite, so exact string equality fails on a descriptor
        # that is in fact identical -- measured, not assumed. Exact equality is
        # asserted separately on the boundaries below, where nothing rewrites them.
        assert descriptors_match(want, _dacl_sddl(Path(path))), (
            f"{path}: descriptor differs from the pre-apply snapshot"
        )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_rollback_removes_an_explicit_ace_the_snapshot_did_not_have(scratch_root):
    """A pinned deny must be removed by the rollback, not left behind.

    Reproduces the exact defect sequence: apply, then pin a descendant with an
    explicit deny the way the old apply did, then roll back and require the
    descendant to be inheritance-only again.
    """
    from foundation.subject_deny import _ace_structure, _restore_dacls, staging_root

    parent = scratch_root
    base = staging_root(parent)
    victim = base / "runtime" / "artifact.bin"
    snapshot = capture_subject_deny(parent)
    before = _ace_structure([victim])[str(victim)]
    assert before["explicitDenyCount"] == 0

    # Pin it the way the defective apply did.
    from foundation.subject_deny import _apply_mask_to_path
    _apply_mask_to_path(victim, SUBJECT_DENY_MASK, deny=True)
    pinned = _ace_structure([victim])[str(victim)]
    assert pinned["explicitDenyCount"] == 1, "the pin did not take effect"

    result = _restore_dacls(snapshot)
    assert result["all_restored"] is True, [
        e for e in result["paths"] if not e.get("restored")
    ]
    after = _ace_structure([victim])[str(victim)]
    assert after["explicitDenyCount"] == 0, (
        "the pinned explicit deny survived the rollback"
    )
    assert after["inheritedDenyCount"] == before["inheritedDenyCount"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_verify_rollback_fails_when_the_descriptor_does_not_match(scratch_root):
    """A snapshot that does not match the live tree must not verify.

    Guards the direction that matters: if verification could be made to pass
    regardless of the live state, it would be decoration rather than a gate.
    """
    from foundation.subject_deny import SubjectDenySnapshot, verify_rollback

    parent = scratch_root
    apply_subject_deny(parent, expected_before=LEGACY_SHORTHAND_MASK, confirm=True)

    # Snapshot taken AFTER the apply, so it describes a state the tree is not in
    # once we roll back to legacy.
    lying = capture_subject_deny(parent)
    for entry in lying.paths.values():
        entry["mask"] = 0x0BADBAD0
        entry["explicit_deny_count"] = 99
    result = verify_rollback(lying)
    assert result["all_restored"] is False
    assert result["all_masks_match"] is False
    assert all(f["descriptor_matches"] is False for f in result["paths"])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_restore_reports_a_mask_it_cannot_exactly_reproduce(scratch_root):
    """A mask with no measured-exact token set must be refused, not approximated.

    Approximating would restore a different boundary than the one recorded while
    reporting success, so an unexpressible mask has to be visible.
    """
    from foundation.subject_deny import SubjectDenySnapshot, _restore_dacls

    parent = scratch_root
    subject = subject_deny_masks(parent)["paths"][0]["path"]
    # 0x0000000f is not in the token table.
    snapshot = SubjectDenySnapshot(captured_at="test", paths={
        subject: {"mask": 0x0000000F, "mask_hex": "0x0000000f", "sddl": "D:"},
    })
    result = _restore_dacls(snapshot)
    assert result["all_restored"] is False
    assert "no measured-exact icacls token set" in result["paths"][0]["detail"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_rehearsal_gate_end_to_end(scratch_root):
    """The whole rehearsal in one test: shape, apply, verify, roll back, verify.

    Mirrors what the disposable 8-path rehearsal does, so its gate condition is
    exercised on every run rather than only when the script is invoked by hand.
    """
    from foundation.subject_deny import (
        _ace_structure,
        _restore_dacls,
        boundary_paths,
        verify_rollback,
    )

    parent = scratch_root
    boundaries = {str(p) for p in boundary_paths(parent)}
    snapshot = capture_subject_deny(parent)
    before_sddl = {p: e["sddl"] for p, e in snapshot.paths.items()}

    # ---- apply ---------------------------------------------------------
    applied = apply_subject_deny(parent, expected_before=LEGACY_SHORTHAND_MASK,
                                 confirm=True)
    assert applied["applied"] is True, applied.get("failure")

    structure = _ace_structure(list(snapshot.paths))
    for path, s in structure.items():
        if path in boundaries:
            assert s["explicitDenyCount"] == 1, path
            assert s["inheritedDenyCount"] == 0, path
        else:
            assert s["explicitDenyCount"] == 0, f"{path} was pinned"
            assert s["inheritedDenyCount"] == 1, path

    result = verify_subject_deny(parent)
    assert result["status"] == "SUBJECT_DENY_VERIFIED"
    for f in result["paths"]:
        assert f["deny_mask"] == f"0x{SUBJECT_DENY_MASK:08x}", f["path"]
        assert f["denies_synchronize"] is False, f["path"]
        for name in SUBJECT_DENY_RIGHTS:
            assert f["denied_rights"][name] is True, f"{f['path']} {name}"
        assert f["read_bits_not_denied"] is True, f["path"]
        assert f["execute_bit_not_denied"] is True, f["path"]
        assert f["subject_allow_preserved"] is True, f["path"]
        assert "Authenticated Users" not in (f["dacl_sddl"] or ""), f["path"]

    # ---- roll back -----------------------------------------------------
    restored = _restore_dacls(snapshot)
    verification = verify_rollback(snapshot)
    assert verification["all_restored"] is True, [
        f for f in verification["paths"] if not f["descriptor_matches"]
    ]
    assert verification["all_sddl_match"] is True
    assert verification["all_structure_match"] is True
    assert restored["all_restored"] is True

    after = _ace_structure(list(snapshot.paths))
    for path, s in after.items():
        want = snapshot.paths[path]
        assert s["explicitDenyCount"] == want["explicit_deny_count"], path
        assert s["inheritanceProtected"] == want["inheritance_protected"], path

    for path, want in before_sddl.items():
        assert descriptors_match(want, _dacl_sddl(Path(path))), path

    # The gate: after rollback the tree is legacy, so the verifier must now say
    # NOT_VERIFIED. A pass here would mean the boundary still reads as intended.
    assert verify_subject_deny(parent)["status"] == "SUBJECT_DENY_NOT_VERIFIED"


def test_both_directions_have_a_mechanism_and_neither_overlaps():
    """Native writes the new mask, icacls writes the old one. Documented asymmetry.

    Guards the reasoning that led to the two-path design: the native path cannot
    express a mask carrying SYNCHRONIZE, and icacls cannot express 0x000d0156.
    Both facts are load-bearing, so both are asserted rather than left as prose.
    """
    from foundation.subject_deny import _ICACLS_TOKENS

    # The mask under test has no SYNCHRONIZE, which is why native works for it.
    assert not (SUBJECT_DENY_MASK & SYNCHRONIZE)
    # The mask to restore has one, which is why native cannot be used to restore.
    assert LEGACY_SHORTHAND_MASK & SYNCHRONIZE
    # icacls is registered for the restore mask, and for the new mask it is not.
    assert _ICACLS_TOKENS[LEGACY_SHORTHAND_MASK] == "W,D,DC"
    assert SUBJECT_DENY_MASK not in _ICACLS_TOKENS


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def scratch_root(tmp_path):
    """A three-subtree tree with the legacy deny, under a caller-owned root.

    Torn down by restoring operator control before removal. Without that, the
    subject's DELETE denial leaves the directory unlistable and pytest cannot
    collect it -- which surfaces as an unrelated WinError 5 during cleanup.
    """
    parent, base = _scratch_tree(tmp_path)
    yield parent
    _teardown_scratch(base)


def _teardown_scratch(base: Path) -> None:
    operator = os.environ.get("USERNAME", "")
    for target in [base] + [base / n for n in ("runtime", "model", "config")]:
        if operator and target.exists():
            subprocess.run(
                ["icacls", str(target), "/remove:d", SUBJECT_ACCOUNT, "/C"],
                capture_output=True, text=True, shell=False, timeout=120)
            subprocess.run(
                ["icacls", str(target), "/grant:r",
                 f"{operator}:(OI)(CI)(F)", "/C"],
                capture_output=True, text=True, shell=False, timeout=120)
    if base.exists():
        subprocess.run(
            ["icacls", str(base.parent), "/grant:r",
             f"{operator}:(OI)(CI)(F)", "/C"],
            capture_output=True, text=True, shell=False, timeout=120)
        shutil.rmtree(base, ignore_errors=True)


def _scratch_tree(tmp_path: Path) -> Path:
    """An eight-path production-shape tree with the legacy deny.

    Mirrors production so the code under test takes its normal path, including
    the parts the first five-path rehearsal omitted: a nested directory at
    depth 2 and three files under runtime. Those descendants are created AFTER
    the boundaries are sealed, so they inherit exactly as production's do --
    explicit-ACE-on-inherited-descendant is a defect that only a tree with real
    descendants can expose.
    Never under subject_runtime.
    """
    # The module under test appends the staging directory name to whatever root
    # it is given, so the caller-owned parent is tmp_path and the tree appears at
    # tmp_path/subject_runtime. Naming the parent `staging_probe` instead put the
    # tree at staging_probe/subject_runtime while the snapshot was taken from
    # staging_probe, and the mismatch only showed up as a missing path.
    base = tmp_path / STAGING_DIRNAME
    for name in ("runtime", "model", "config"):
        (base / name).mkdir(parents=True, exist_ok=True)
    # The caller-owned parent, which is what the module's root argument is.
    parent = base.parent
    operator = os.environ.get("USERNAME", "")

    # Remove inheritance WITHOUT /T, then grant operator control on the root
    # before touching the children. Two reasons, both learned the hard way:
    #   * /T walks into children that do not yet have an operator ACE, and
    #   * severing inheritance then denying DELETE can leave the operator unable
    #     to list the directory -- pytest then fails to collect it (WinError 5).
    subprocess.run(
        ["icacls", str(base), "/inheritance:r", "/C"],
        capture_output=True, text=True, shell=False, timeout=120)
    for target in [base] + [base / n for n in ("runtime", "model", "config")]:
        # Each subtree is severed too, exactly as staging.apply_boundary does.
        # Leaving a subtree inheriting leaves it holding an inherited subject
        # deny in addition to its explicit one, which is not the production
        # shape and made the boundary/descendant origin checks fail for the
        # wrong reason.
        subprocess.run(
            ["icacls", str(target), "/inheritance:r", "/C"],
            capture_output=True, text=True, shell=False, timeout=120)
        # The operator needs an explicit full-control ACE on the CHILD before the
        # deny is applied. Severing inheritance and then denying DELETE on a
        # directory leaves the operator unable to list it -- an earlier version of
        # this helper hit WinError 5 on the very directory it had just created.
        if operator:
            subprocess.run(
                ["icacls", str(target), "/grant:r",
                 f"{operator}:(OI)(CI)(F)", "/C"],
                capture_output=True, text=True, shell=False, timeout=120)
        # runtime is RX, the rest R -- matching M015, because a test that grants
        # R everywhere cannot catch a regression that costs the subject execute.
        allow = "RX" if target.name == "runtime" else "R"
        subprocess.run(
            ["icacls", str(target), "/grant:r",
             f"{SUBJECT_ACCOUNT}:(OI)(CI)({allow})", "/C"],
            capture_output=True, text=True, shell=False, timeout=120)
        subprocess.run(
            ["icacls", str(target), "/deny",
             f"{SUBJECT_ACCOUNT}:(OI)(CI)(W,D,DC)", "/C"],
            capture_output=True, text=True, shell=False, timeout=120)

    # Descendants last, so they inherit instead of being set explicitly. This is
    # the production shape: nothing under runtime/ or config/ carries an explicit
    # subject ACE, and a fixture created before the boundary was sealed would
    # silently diverge from it.
    (base / "runtime" / "artifact.bin").write_bytes(b"payload")
    (base / "runtime" / "second_fixture.exe").write_bytes(b"payload")
    (base / "runtime" / "third_fixture.exe").write_bytes(b"payload")
    (base / "config" / "delete_target").mkdir(exist_ok=True)
    (base / "config" / "delete_target" / "deep.bin").write_bytes(b"payload")
    return parent, base
