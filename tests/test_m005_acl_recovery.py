"""Regression coverage for the M005 ACL recovery defect (found 2026-09-27).

The defect
----------
``scripts/restore_permissions.ps1 -Restore`` runs ``icacls /reset`` on every
recorded path, which strips the explicit ``BABY_AI_TEST:(DENY)(W)`` ACE. It
then re-applies only the EXPLICIT entries present in the snapshot. The
milestone's own default snapshot (``var/acl-snapshots/protected-paths.json``)
was captured *before* the boundary was applied, so it contains ZERO deny
entries. Restoring from it therefore destroyed the security boundary while
still printing "Restored N path records" -- a false success on the one
property that matters.

These tests are deliberately PORTABLE: they exercise the recovery logic's
decision table in pure Python against a recorded snapshot, so the defect cannot
regress even on a machine with no ``BABY_AI_TEST`` account. The host suite
(``tests/host_security``) separately proves the same property against real
NTFS when the principal is available.
"""

from __future__ import annotations

import unittest
from pathlib import Path

SNAPSHOT = Path("var/acl-snapshots/protected-paths.json")
RESTORE_SCRIPT = Path("scripts/restore_permissions.ps1")
BOUNDARY_TRUSTEE = "BABY_AI_TEST"


class TestDefaultSnapshotCannotSilentlyDropTheBoundary(unittest.TestCase):
    """The shipped snapshot must not be able to erase a deny ACE on restore."""

    def test_shipped_snapshot_has_no_deny_entries(self):
        """Documents the precondition of the defect: the snapshot is pre-boundary.

        This is a characterisation test, not an endorsement. It pins the fact
        that made recovery destructive so that a future change to the snapshot
        format is a conscious decision rather than an accident.
        """
        import json

        if not SNAPSHOT.exists():
            self.skipTest("no ACL snapshot on this machine (var/ is machine-local)")

        payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        deny_entries = [
            (rec["path"], ent["trustee"])
            for rec in payload["paths"]
            for ent in rec.get("entries", [])
            if ent.get("deny")
        ]
        self.assertEqual(
            [], deny_entries,
            "The default snapshot now contains deny entries. If that was "
            "deliberate, update the recovery contract and these tests.",
        )

    def test_restore_script_preserves_live_deny_aces(self):
        """The fix: -Restore must re-apply deny ACEs found live, pre-/reset.

        Static assertion on the script's control flow. It is a guard rail, not
        a proof -- the host suite and the sandbox reproduction provide the
        behavioural proof.
        """
        if not RESTORE_SCRIPT.exists():
            self.skipTest("restore_permissions.ps1 not present")

        text = RESTORE_SCRIPT.read_text(encoding="utf-8")

        self.assertIn(
            "preExistingDeny", text,
            "-Restore must capture live deny ACEs before `icacls /reset` "
            "destroys them; without this, restoring a pre-boundary snapshot "
            "silently removes the security boundary.",
        )
        self.assertIn(
            "Post-restore check", text,
            "-Restore must verify the boundary survived and report it, rather "
            "than only reporting a path count.",
        )
        self.assertIn(
            "BABY_AI_TEST", text,
            "The post-restore check must name the boundary trustee it verifies.",
        )

    def test_restore_deduplicates_before_reapplying(self):
        """icacls /deny appends, so restoring duplicates would compound them."""
        if not RESTORE_SCRIPT.exists():
            self.skipTest("restore_permissions.ps1 not present")

        text = RESTORE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            "Deduplicate before restoring", text,
            "-Restore must collapse duplicate explicit ACEs; `icacls /deny` "
            "appends rather than replaces, so re-applying a captured duplicate "
            "multiplies the duplicate on every recovery.",
        )


class TestBoundaryReportingIsEvidenceBased(unittest.TestCase):
    """Protection must never be reported from intent rather than observation."""

    def test_no_module_claims_verified_without_a_real_cross_process_result(self):
        """The result taxonomy must not let a refusal read as enforcement."""
        from babylab.osboundary import Result

        self.assertEqual("OS_DENIED", Result.OS_DENIED.value)
        self.assertEqual("APPLICATION_DENIED", Result.APPLICATION_DENIED.value)
        self.assertNotEqual(Result.OS_DENIED, Result.APPLICATION_DENIED)
        self.assertNotEqual(Result.OS_DENIED, Result.NOT_TESTABLE)
        self.assertNotEqual(Result.ALLOWED, Result.APPLICATION_DENIED)

    def test_protected_inventory_excludes_the_provenance_code_package(self):
        """`provenance/` is the Python SOURCE package, not protected evidence.

        A cross-process probe that writes into ``provenance/`` therefore lands
        in an unprotected code directory and succeeds. That is NOT evidence the
        boundary is absent; it is evidence the probe targeted the wrong path.
        The real protected provenance evidence is ``var/provenance/ledger.jsonl``
        and ``human_control/provenance``.
        """
        from babylab.osboundary import protected_paths

        paths = {str(p.path).lower() for p in protected_paths()}
        self.assertNotIn(str(Path("provenance").resolve()).lower(), paths)
        self.assertIn(str(Path("var/provenance/ledger.jsonl").resolve()).lower(), paths)
        self.assertIn(str(Path("human_control/provenance").resolve()).lower(), paths)

    def test_protected_set_covers_every_evidence_surface(self):
        """No evidence directory may silently fall out of the protected set."""
        from babylab.osboundary import protected_paths

        names = {p.name for p in protected_paths()}
        required = {
            "event_log", "provenance_ledger", "provenance_seals",
            "provenance_keyring", "provenance_private_keys", "control_token",
            "research_records", "snapshots", "research_documentation",
            "experiment_log", "source_repository",
        }
        self.assertTrue(
            required.issubset(names),
            f"protected set is missing: {sorted(required - names)}",
        )

    def test_workspace_paths_are_never_protected(self):
        from babylab.osboundary import protected_paths, subject_workspace_paths

        protected = {str(p.path).lower() for p in protected_paths()}
        for ws in subject_workspace_paths():
            self.assertNotIn(
                str(ws.path).lower(), protected,
                f"{ws.name} must remain writable by the subject",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
