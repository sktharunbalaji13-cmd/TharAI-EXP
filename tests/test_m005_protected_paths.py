"""Milestone 005 -- protected path inventory and ACL parsing."""

from __future__ import annotations

import unittest
from pathlib import Path

from babylab.osboundary import (
    TEST_PRINCIPAL_NAME,
    UNSAFE_DENY_TARGETS,
    AceEntry,
    parse_icacls,
    protected_paths,
    snapshot_acl,
    subject_workspace_paths,
)
from tests.support import LabTestCase


class TestProtectedPathInventory(unittest.TestCase):
    def test_inventory_is_not_empty(self):
        self.assertTrue(protected_paths())

    def test_every_entry_has_a_path_and_rationale(self):
        for entry in protected_paths():
            with self.subTest(entry=entry.name):
                self.assertTrue(entry.path)
                self.assertTrue(entry.rationale)

    def test_required_artefacts_are_all_present(self):
        names = {p.name for p in protected_paths()}
        for required in (
            "event_log", "provenance_ledger", "provenance_seals",
            "provenance_keyring", "provenance_private_keys", "control_token",
            "birth_records", "research_records", "snapshots",
            "protected_configuration", "research_documentation",
            "source_repository",
        ):
            self.assertIn(required, names)

    def test_paths_are_resolved_from_the_project_layout(self):
        for entry in protected_paths():
            with self.subTest(entry=entry.name):
                self.assertIsInstance(entry.path, Path)

    def test_only_the_two_append_only_streams_are_marked(self):
        """M001/M002 require append; everything else is deny-mutation."""
        appendable = {p.name for p in protected_paths() if p.append_only_for_subject}
        self.assertEqual(appendable, {"event_log", "provenance_ledger"})

    def test_protected_and_subject_workspaces_are_disjoint(self):
        protected = {str(p.path) for p in protected_paths()}
        workspace = {str(p.path) for p in subject_workspace_paths()}
        self.assertFalse(protected & workspace)

    def test_workspace_paths_are_the_intended_write_areas(self):
        names = {p.name for p in subject_workspace_paths()}
        self.assertEqual(names, {"experimental_workspace", "temporary_workspace"})

    def test_test_principal_is_named_as_a_test_principal(self):
        self.assertEqual(TEST_PRINCIPAL_NAME, "BABY_AI_TEST")


class TestAclParsing(unittest.TestCase):
    SAMPLE = (
        "C:\\repo\\human_control BUILTIN\\Administrators:(I)(F)\n"
        "C:\\repo\\human_control NT AUTHORITY\\Authenticated Users:(I)(M)\n"
        "C:\\repo\\human_control BABY_AI_TEST:(DENY)(W)\n"
        "\n"
        "Successfully processed 1 files; Failed processing 0 files\n"
    )

    def test_parse_extracts_trustee_not_path(self):
        """Regression for the M004 parser that read the path as the trustee.

        That bug reported a clean boundary on a world-writable directory, so it
        is pinned here permanently.
        """
        entries = parse_icacls(self.SAMPLE)
        trustees = [e.trustee for e in entries]
        self.assertIn("NT AUTHORITY\\Authenticated Users", trustees)
        self.assertFalse(
            any(t.startswith("C:") for t in trustees),
            "the leading path must never be mistaken for a trustee",
        )

    def test_inherited_entries_are_flagged(self):
        """Inherited ACEs carry (I); an explicitly added DENY must not."""
        entries = parse_icacls(self.SAMPLE)
        inherited = {e.trustee for e in entries if e.inherited}
        self.assertIn("BUILTIN\\Administrators", inherited)
        self.assertIn("NT AUTHORITY\\Authenticated Users", inherited)
        explicit = [e for e in entries if not e.inherited]
        self.assertEqual([e.trustee for e in explicit], [TEST_PRINCIPAL_NAME])

    def test_deny_entries_are_flagged(self):
        entries = parse_icacls(self.SAMPLE)
        denies = [e for e in entries if e.is_deny]
        self.assertEqual(len(denies), 1)
        self.assertEqual(denies[0].trustee, TEST_PRINCIPAL_NAME)

    def test_broad_write_is_detected(self):
        entries = parse_icacls(self.SAMPLE)
        broad = [e for e in entries if e.is_broad() and e.can_write()]
        self.assertEqual([e.trustee for e in broad], ["NT AUTHORITY\\Authenticated Users"])

    def test_success_footer_is_ignored(self):
        self.assertEqual(len(parse_icacls(self.SAMPLE)), 3)

    def test_empty_input_yields_no_entries(self):
        self.assertEqual(parse_icacls(""), ())

    def test_acl_entry_write_detection(self):
        self.assertTrue(AceEntry("X", "(M)", False, False).can_write())
        self.assertTrue(AceEntry("X", "(F)", False, False).can_write())
        self.assertFalse(AceEntry("X", "(RX)", False, False).can_write())
        self.assertFalse(AceEntry("X", "(DENY)(W)", False, True).is_broad())


class TestUnsafeDenyTargetsAreNamed(unittest.TestCase):
    def test_human_lockout_targets_are_documented(self):
        """A deny aimed at these would lock the operator out, which s11 forbids."""
        self.assertIn("Everyone", UNSAFE_DENY_TARGETS)
        self.assertIn("Authenticated Users", UNSAFE_DENY_TARGETS)


class TestSnapshotAclIsRecoverable(LabTestCase):
    def test_snapshot_records_owner_entries_and_timestamp(self):
        snap = snapshot_acl(self.paths.human_control)
        self.assertEqual(snap.path, str(self.paths.human_control))
        self.assertTrue(snap.captured_at)
        payload = snap.to_dict()
        self.assertIn("owner", payload)
        self.assertIn("entries", payload)
        self.assertIn("broad_write_trustees", payload)

    def test_snapshot_of_missing_path_is_empty_not_raising(self):
        snap = snapshot_acl(Path("C:/definitely/not/here"))
        self.assertEqual(snap.entries, ())

    def test_real_protected_paths_expose_broad_write_trustees(self):
        """The measured state of this host, asserted rather than assumed."""
        from babylab.osboundary import measure_protected_paths

        snapshots = measure_protected_paths()
        self.assertTrue(snapshots, "protected paths must exist to be measured")
        for snap in snapshots:
            with self.subTest(path=Path(snap.path).name):
                self.assertIsInstance(snap.broad_write_trustees(), tuple)


if __name__ == "__main__":
    unittest.main()
