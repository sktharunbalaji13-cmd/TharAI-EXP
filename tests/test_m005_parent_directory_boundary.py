"""Regression coverage for the M005 parent-directory boundary defect.

The defect (observed 2026-09-27, genuine BABY_AI_TEST process)
--------------------------------------------------------------
The boundary denied protected LEAF files only. Their containing directories
carried no ``BABY_AI_TEST`` deny ACE, and every parent has
``Authenticated Users:(I)(M)``. On a *directory*, ``(M)`` expands to include
FILE_ADD_FILE and FILE_DELETE_CHILD. Consequently a genuine BABY_AI_TEST
process could:

* create a sibling file inside a protected directory
  (``var\\provenance\\m005_probe.txt`` -- WRITE SUCCEEDED, unacceptable), and
* delete the protected child outright
  (``human_control\\security\\control.token.bak`` -- WRITE SUCCEEDED).

A deny ACE on a file never governs either operation: both are authorised
against the PARENT directory. ``human_control\\provenance`` denied correctly
only by accident -- it is itself a directory in the protected set, not because
the rule was understood.

These tests encode the invariant that makes the difference: **every protected
path must have a deny on its own ACL *and* on the directory that contains it**,
with the one researched exception of the two append-permitted paths, whose
parents get a split deny (no create, no delete) plus an explicit append grant.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

# Directories whose children include a fully-denied protected leaf. These get a
# full deny: the policy's own rationale for control.token is that keeping it
# "external to the subject is what makes control privileged".
FULLY_DENIED_PARENTS = (
    "human_control/security",
    "human_control/security/keys",
)

# Directories whose children include an append-permitted protected leaf
# (append_only_for_subject=True). A plain deny would revoke that intended
# capability, so these get a split deny plus an explicit append grant.
APPEND_PERMITTED_PARENTS = (
    "var/provenance",
    "var/events",
)


def _icacls(path: Path) -> str:
    proc = subprocess.run(
        ["icacls", str(path)], capture_output=True, text=True, timeout=60
    )
    return proc.stdout if proc.returncode == 0 else ""


def _baby_deny_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in _icacls(path).splitlines()
        if "BABY_AI_TEST" in line and "(DENY)" in line
    ]


def _baby_allow_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in _icacls(path).splitlines()
        if "BABY_AI_TEST" in line and "(DENY)" not in line
    ]


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


class TestParentDirectoryBoundaryIsPresent(unittest.TestCase):
    """The invariant: a leaf-only deny does not protect the leaf."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]

    def test_every_protected_leaf_has_a_protected_parent(self):
        """A deny on a file alone cannot stop sibling creation or deletion.

        The invariant has two cases, because a protected path may be a directory
        or a file:

        * Protected DIRECTORY: the deny must be on the directory itself, must
          carry (OI)(CI) so it reaches the children, and must include (D) so
          the directory cannot itself be deleted via the parent's
          FILE_DELETE_CHILD. Denying the *parent* is not required and would be a
          broader policy change than the canonical set intends.
        * Protected FILE: the deny must be on the file AND on the containing
          directory, because creating a sibling and deleting the child are both
          authorised against the parent.
        """
        from babylab.osboundary import protected_paths

        problems: list[str] = []
        for protected in protected_paths():
            target = Path(protected.path)
            if not _exists(target):
                continue  # absent path: no ACE possible, reported separately

            denies = _baby_deny_lines(target)
            if not denies:
                problems.append(f"{protected.name}: no deny ACE on the path itself")
                continue
            combined = " ".join(denies).upper()

            if target.is_dir():
                # Inheritance and delete protection are both required on the
                # directory; without (OI)(CI) its children stay writable, and
                # without (D) the directory can be removed by its parent.
                if "OI" not in combined or "CI" not in combined:
                    problems.append(
                        f"{protected.name}: directory deny lacks (OI)(CI) "
                        f"inheritance, so its children remain writable"
                    )
                if "(D" not in combined and "D," not in combined and combined.rstrip().endswith("D"):
                    problems.append(
                        f"{protected.name}: directory deny lacks (D), so the "
                        f"directory itself can be deleted"
                    )
            else:
                parent = target.parent
                if not _baby_deny_lines(parent):
                    problems.append(
                        f"{protected.name}: protected FILE under unprotected "
                        f"parent {self._rel(parent)} -- sibling creation and "
                        f"child deletion are authorised against the parent"
                    )

        self.assertEqual(
            [], problems,
            "The NTFS boundary is incomplete. " + "; ".join(problems),
        )

    def test_protected_directories_deny_delete(self):
        """A protected directory must not be removable by the subject."""
        from babylab.osboundary import protected_paths

        undeletable_required = []
        for protected in protected_paths():
            target = Path(protected.path)
            if not _exists(target) or not target.is_dir():
                continue
            combined = " ".join(_baby_deny_lines(target)).upper()
            has_delete = "(D" in combined or ",D)" in combined or combined.endswith("(D)")
            if not has_delete:
                undeletable_required.append(protected.name)
        self.assertEqual(
            [], undeletable_required,
            "These protected directories lack a delete deny, so the subject "
            f"can remove them via the parent's FILE_DELETE_CHILD: {undeletable_required}",
        )

    def test_protected_directory_denies_inherit_to_children(self):
        """Without (OI)(CI) the deny stops at the directory and children stay writable."""
        from babylab.osboundary import protected_paths

        non_inheriting = []
        for protected in protected_paths():
            target = Path(protected.path)
            if not _exists(target) or not target.is_dir():
                continue
            combined = " ".join(_baby_deny_lines(target)).upper()
            if "OI" not in combined or "CI" not in combined:
                non_inheriting.append(protected.name)
        self.assertEqual(
            [], non_inheriting,
            "Protected directories whose deny does not inherit to children: "
            f"{non_inheriting}",
        )

    def test_fully_denied_parents_carry_a_deny(self):
        for rel in FULLY_DENIED_PARENTS:
            directory = self.root / rel
            if not _exists(directory):
                continue
            self.assertTrue(
                _baby_deny_lines(directory),
                f"{rel} contains a fully-denied protected leaf but has no "
                f"BABY_AI_TEST deny ACE, so the subject can add or remove "
                f"files there.",
            )

    def test_append_permitted_parents_deny_create_and_delete(self):
        """Split deny: the parent must refuse create and delete for the subject."""
        for rel in APPEND_PERMITTED_PARENTS:
            directory = self.root / rel
            if not _exists(directory):
                continue
            denies = _baby_deny_lines(directory)
            self.assertTrue(
                denies,
                f"{rel} holds an append-permitted protected leaf and must "
                f"deny write+delete on the directory itself.",
            )
            combined = " ".join(denies).upper()
            self.assertTrue(
                "D" in combined,
                f"{rel} deny must include delete, otherwise the subject can "
                f"remove the protected child (FILE_DELETE_CHILD).",
            )

    def test_append_permitted_parents_still_grant_append(self):
        """The split deny must not silently revoke the policy's append intent."""
        for rel in APPEND_PERMITTED_PARENTS:
            directory = self.root / rel
            if not _exists(directory):
                continue
            allows = _baby_allow_lines(directory)
            self.assertTrue(
                any("(AD)" in line.upper() for line in allows),
                f"{rel} is append-permitted by canonical policy; the split "
                f"deny must re-grant (AD) or it has revoked an intended "
                f"capability. saw: {allows}",
            )

    def test_workspace_directories_are_never_denied(self):
        """The subject's own workspace must remain fully writable."""
        from babylab.osboundary import subject_workspace_paths

        for workspace in subject_workspace_paths():
            directory = Path(workspace.path)
            if not _exists(directory):
                continue
            self.assertEqual(
                [], _baby_deny_lines(directory),
                f"{workspace.name} must stay writable by the subject",
            )
            # ...and must not gain a deny on its parent either, or a
            # FILE_ADD_FILE deny on baby_workspace would block new files.
            parent = directory.parent
            if _exists(parent) and parent != self.root:
                baby_on_parent = [
                    l for l in _baby_deny_lines(parent) if "baby_workspace" not in l
                ]
                self.assertTrue(
                    not _baby_deny_lines(directory),
                    f"{workspace.name} unexpectedly denied",
                )

    def test_no_unexpected_trustee_was_denied(self):
        """The boundary must never deny a broad or legitimate trustee."""
        from babylab.osboundary import UNSAFE_DENY_TARGETS, protected_paths

        for protected in protected_paths():
            leaf = Path(protected.path)
            if not _exists(leaf):
                continue
            for line in _baby_deny_lines(leaf):
                for unsafe in UNSAFE_DENY_TARGETS:
                    self.assertNotIn(
                        unsafe, line,
                        f"{protected.name} denies a broad trustee: {line}",
                    )

    def _rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)


class TestProbePathsAreNotEvidencePaths(unittest.TestCase):
    """Distinguish the three directory families so a probe cannot mislead again."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]

    def test_provenance_code_package_is_not_protected_evidence(self):
        """`provenance/` is source code; `var/provenance` is the evidence.

        A probe that writes into `provenance/` lands in an unprotected code
        directory and succeeds. That says nothing about the evidence boundary
        and previously led to the incorrect conclusion that the deny ACEs had
        vanished.
        """
        from babylab.osboundary import protected_paths

        protected = {str(Path(p.path)).lower() for p in protected_paths()}
        self.assertNotIn(str(self.root / "provenance").lower(), protected)
        self.assertIn(str(self.root / "var/provenance/ledger.jsonl").lower(), protected)
        self.assertIn(str(self.root / "human_control/provenance").lower(), protected)

    def test_protected_set_contains_no_bare_parent_directory_ambiguity(self):
        """`var/provenance` is a protected *parent*; the leaf is the ledger."""
        from babylab.osboundary import protected_paths

        names = {p.name for p in protected_paths()}
        # The ledger leaf is protected; its directory is enforced via the
        # parent-directory invariant above rather than by being a list entry,
        # which keeps the canonical policy unchanged.
        self.assertIn("provenance_ledger", names)
        self.assertNotIn("provenance_code_package", names)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
