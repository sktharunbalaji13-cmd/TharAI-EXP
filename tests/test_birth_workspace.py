"""Tests for the subject code workspace's write isolation.

Two layers are tested, because there are two layers:

1. **Containment.** The workspace root *is* the subject code area, so any path
   resolving outside it is refused. This is the primary mechanism and it holds
   regardless of configuration.
2. **Directory policy.** If the root is ever misconfigured to be broader — the
   repository root, say — the named laboratory and human-owned directories are
   still refused. That is the layer that keeps a misconfiguration from silently
   handing the subject the laboratory.

Both record their refusals, because a system that quietly blocks everything and a
system that is being correctly constrained look identical from outside until you
read the refusals.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from babylab.errors import AuthorizationError, ValidationError
from babylab.paths import ProjectPaths
from birth.workspace import (
    HUMAN_OWNED_DIRECTORIES,
    LAB_CODE_DIRECTORIES,
    SUBJECT_CODE_DIRECTORIES,
    CodeWorkspace,
    WorkspaceState,
)


class WorkspaceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = ProjectPaths(Path(self._tmp.name).resolve())
        self.paths.ensure_directories()
        self.workspace = CodeWorkspace.create(self.paths)


class TestContainment(WorkspaceTestCase):
    def test_subject_may_write_its_own_code(self) -> None:
        digest = self.workspace.write_subject_file("hello.py", "print('hi')\n")
        self.assertTrue(self.workspace.root.joinpath("hello.py").is_file())
        self.assertEqual(len(digest), 64)
        self.assertEqual(self.workspace.subject_written_file_count(), 1)

    def test_traversal_is_refused(self) -> None:
        for attempt in ("../escape.py", "../../escape.py", "a/../../escape.py"):
            with self.subTest(attempt=attempt):
                with self.assertRaises(AuthorizationError):
                    self.workspace.write_subject_file(attempt, "x")

    def test_absolute_path_is_refused(self) -> None:
        with self.assertRaises(AuthorizationError):
            self.workspace.write_subject_file("C:/Windows/System32/x.dll", "x")

    def test_repository_relative_spelling_does_not_grant_access(self) -> None:
        """``birth/x.py`` inside the workspace is a *different* path from the repo's."""
        self.workspace.write_subject_file("birth/x.py", "# mine, in my workspace\n")
        self.assertTrue(self.workspace.root.joinpath("birth", "x.py").is_file())
        self.assertNotIn("birth/x.py", self.workspace.lab_written)
        self.assertIn("birth/x.py", self.workspace.subject_written)

    def test_missing_root_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CodeWorkspace(
                root=Path(self._tmp.name) / "nope", repository_root=self.paths.root
            )

    def test_repository_relative_path_is_computed_from_the_root(self) -> None:
        self.assertEqual(
            self.workspace.repository_relative("a/b.py"),
            "baby_workspace/code/a/b.py",
        )


class TestDirectoryPolicy(unittest.TestCase):
    """The defence-in-depth layer, exercised with a deliberately broad root."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = ProjectPaths(Path(self._tmp.name).resolve())
        self.paths.ensure_directories()
        # Simulate the misconfiguration this layer exists to contain: a workspace
        # rooted at the repository rather than at the subject code area.
        self.broad = CodeWorkspace(root=self.paths.root, repository_root=self.paths.root)

    def test_lab_code_is_refused(self) -> None:
        for name in LAB_CODE_DIRECTORIES:
            with self.subTest(directory=name):
                with self.assertRaises(AuthorizationError):
                    self.broad.write_subject_file(f"{name}/sneaky.py", "x = 1")
        self.assertEqual(self.broad.subject_written_file_count(), 0)
        self.assertEqual(len(self.broad.refusals), len(LAB_CODE_DIRECTORIES))

    def test_human_owned_is_refused(self) -> None:
        for name in HUMAN_OWNED_DIRECTORIES:
            with self.subTest(directory=name):
                with self.assertRaises(AuthorizationError):
                    self.broad.write_subject_file(f"{name}/sneaky.md", "x")
        self.assertEqual(len(self.broad.refusals), len(HUMAN_OWNED_DIRECTORIES))

    def test_the_directory_itself_is_refused_not_just_its_contents(self) -> None:
        with self.assertRaises(AuthorizationError):
            self.broad.write_subject_file("human_control", "x")

    def test_refusal_names_the_offending_directory(self) -> None:
        with self.assertRaises(AuthorizationError):
            self.broad.write_subject_file("birth/x.py", "x")
        refusal = self.broad.refusals[0]
        self.assertEqual(refusal["role"], "BABY_AI")
        self.assertIn("birth", refusal["reason"])

    def test_nested_lab_path_is_refused(self) -> None:
        with self.assertRaises(AuthorizationError):
            self.broad.write_subject_file("birth/deep/nested/x.py", "x")

    def test_similar_prefix_is_not_matched(self) -> None:
        """``births/`` is not ``birth/``. A prefix match that ignored the slash
        would refuse a directory the subject legitimately owns."""
        self.broad.write_subject_file("births/mine.py", "x = 1\n")
        self.assertEqual(self.broad.subject_written_file_count(), 1)


class TestReporting(WorkspaceTestCase):
    def test_reports_zero_subject_files_honestly(self) -> None:
        payload = self.workspace.to_dict()
        self.assertEqual(payload["subject_written_file_count"], 0)
        self.assertEqual(payload["state"], "EMPTY")
        self.assertEqual(payload["subject_written"], {})

    def test_lab_and_subject_writes_are_distinguished(self) -> None:
        self.workspace.write_lab_file("scaffolding/notes.md", "lab wrote this")
        self.workspace.write_subject_file("subject.py", "# subject wrote this")
        payload = self.workspace.to_dict()
        self.assertIn("scaffolding/notes.md", payload["lab_written"])
        self.assertIn("subject.py", payload["subject_written"])
        self.assertNotIn("scaffolding/notes.md", payload["subject_written"])

    def test_state_reflects_a_refusal(self) -> None:
        self.assertIs(self.workspace.state(), WorkspaceState.EMPTY)
        with self.assertRaises(AuthorizationError):
            self.workspace.write_subject_file("../escape.py", "x")
        self.assertIs(self.workspace.state(), WorkspaceState.INTEGRITY_VIOLATION)

    def test_policy_is_published(self) -> None:
        policy = self.workspace.to_dict()["policy"]
        self.assertEqual(policy["subject_may_write"], list(SUBJECT_CODE_DIRECTORIES))
        self.assertIn("privilege-escalation", policy["excluded_capabilities"])
        self.assertIn("laboratory-self-modification", policy["excluded_capabilities"])
        self.assertIn("control-plane-access", policy["excluded_capabilities"])

    def test_workspace_root_is_outside_every_forbidden_area(self) -> None:
        text = self.workspace.repository_relative("x.py")
        self.assertTrue(text.startswith("baby_workspace/code"), text)
        for forbidden in LAB_CODE_DIRECTORIES + HUMAN_OWNED_DIRECTORIES:
            with self.subTest(forbidden=forbidden):
                self.assertFalse(text.startswith(forbidden))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
