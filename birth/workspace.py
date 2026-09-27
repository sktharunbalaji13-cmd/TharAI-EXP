"""The subject's code workspace, and the write isolation around it.

What exists
-----------
A directory tree under ``baby_workspace/`` and a policy that refuses writes
outside it. The policy is real, enforced by
:func:`assert_write_allowed`, and tested by
``tests/test_birth_workspace.py``.

What does not exist
-------------------
A subject with a runtime. There is no process, no scheduler, and no model that
has been asked to write anything, so the workspace is empty of subject output in
Milestone 003. :attr:`CodeWorkspace.subject_written_file_count` is the honest
answer, not a placeholder count.

The two-tier code rule
----------------------
:data:`LAB_CODE_DIRECTORIES` is code belonging to the laboratory. :data:`SUBJECT_CODE_DIRECTORIES`
is code belonging to the subject. Keeping them in separate directories is what
makes "the subject modified the laboratory" a detectable event rather than an
inferred one — a subject-side write into a laboratory directory is refused by the
policy, and the refusal is recorded rather than absorbed.

Nothing here self-modifies. "Let the subject improve its own code" is a *later*
research question with real safety implications, and quietly wiring it up inside
a milestone called "birth" would be a poor way to find out.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from babylab.errors import AuthorizationError, ValidationError
from babylab.hashing import canonical_bytes, sha256_hex
from babylab.paths import ProjectPaths, default_paths

WORKSPACE_SCHEMA = "babylab/code-workspace/v1"

#: Laboratory code. A subject may not write here. Not a suggestion.
LAB_CODE_DIRECTORIES = ("babylab", "birth", "control", "events", "observatory", "observer", "provenance", "tests", "scripts")

#: Subject code. A subject may write here and nowhere else.
SUBJECT_CODE_DIRECTORIES = ("baby_workspace/code",)

#: Human-owned. A subject may not write here.
HUMAN_OWNED_DIRECTORIES = ("human_control", "research", "docs")


class WorkspaceState(str, enum.Enum):
    """The workspace's state, as a fact about files rather than a life stage."""

    EMPTY = "EMPTY"
    HAS_SUBJECT_CODE = "HAS_SUBJECT_CODE"
    INTEGRITY_VIOLATION = "INTEGRITY_VIOLATION"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass
class CodeWorkspace:
    """One isolated tree the subject may write code into.

    Paths passed to the methods below are relative to :attr:`root`, which *is*
    the subject code area (``baby_workspace/code/``). The laboratory's forbidden
    directories are named relative to the repository root, so the checks resolve
    a candidate to an absolute path and compare repository-relative prefixes.
    Comparing raw strings would let ``../`` past a policy that looked correct.
    """

    root: Path
    repository_root: Path
    environment_id: str = "workspace.isolated"
    #: Files written by laboratory code, for contrast. Never counted as the
    #: subject's own output.
    lab_written: set[str] = field(default_factory=set)
    #: Files written by subject-side code, each with the digest at write time.
    subject_written: dict[str, str] = field(default_factory=dict)
    #: Policy refusals, each with the reason. A refusal is data.
    refusals: list[dict[str, Any]] = field(default_factory=list)
    schema: str = WORKSPACE_SCHEMA

    # -- construction -----------------------------------------------------
    @classmethod
    def create(cls, paths: ProjectPaths | None = None) -> "CodeWorkspace":
        root = (paths or default_paths()).baby_code
        root.mkdir(parents=True, exist_ok=True)
        return cls(root=root, repository_root=(paths or default_paths()).root)

    def __post_init__(self) -> None:
        if not self.root.is_dir():
            raise ValidationError(
                f"workspace root {self.root} does not exist; create it with "
                "CodeWorkspace.create() so the isolation is established by the "
                "same call that claims it"
            )

    # -- isolation --------------------------------------------------------
    def resolve_within(self, relative: str) -> Path:
        """Resolve a relative path, refusing anything that escapes the root.

        The check is on the *resolved* path, so ``../`` and absolute paths and
        symlinks all fail the same way.
        """
        candidate = (self.root / relative).resolve()
        root = self.root.resolve()
        if candidate != root and root not in candidate.parents:
            raise AuthorizationError(
                f"path {relative!r} resolves outside the subject workspace "
                f"({candidate}). The subject's writes are confined to {root}."
            )
        return candidate

    def repository_relative(self, relative: str) -> str:
        """The candidate's path relative to the repository root, POSIX style.

        For a workspace at ``baby_workspace/code``, the relative path
        ``"hello.py"`` becomes ``"baby_workspace/code/hello.py"``, which is the
        form the directory policy is written in.
        """
        resolved = self.resolve_within(relative)
        try:
            return resolved.relative_to(self.repository_root.resolve()).as_posix()
        except ValueError as exc:  # pragma: no cover - defensive
            raise AuthorizationError(
                f"{relative!r} is not inside the repository at "
                f"{self.repository_root}"
            ) from exc

    @staticmethod
    def _in_any(relative_repo_path: str, names: tuple[str, ...]) -> str | None:
        for name in names:
            if relative_repo_path == name or relative_repo_path.startswith(f"{name}/"):
                return name
        return None

    def is_lab_code(self, relative: str) -> bool:
        return self._in_any(self.repository_relative(relative), LAB_CODE_DIRECTORIES) is not None

    def is_human_owned(self, relative: str) -> bool:
        return self._in_any(self.repository_relative(relative), HUMAN_OWNED_DIRECTORIES) is not None

    def is_subject_code(self, relative: str) -> bool:
        """Inside the subject code area.

        True for anything that resolves within :attr:`root`, since the root is
        the area. The forbidden directories are checked separately, and
        :meth:`assert_write_allowed` consults them first, so a path cannot be
        both.
        """
        resolved = self.resolve_within(relative)
        root = self.root.resolve()
        return resolved == root or root in resolved.parents

    def assert_write_allowed(self, relative: str, actor_role: str) -> None:
        """Raise unless ``actor_role`` may write ``relative``.

        Recorded as a refusal rather than raised silently, because a system that
        quietly blocks everything and a system that is being correctly
        constrained look identical from outside until you read the refusals.
        """
        # Refuse escapes first, and record them. An attempt to leave the workspace
        # is not a policy question, it is an attempt, and it is exactly the event
        # a later reader would want to see.
        try:
            self.resolve_within(relative)
        except AuthorizationError as exc:
            self._refuse(
                relative,
                actor_role,
                f"path escapes the subject workspace: {exc}",
            )

        lab = self._in_any(self.repository_relative(relative), LAB_CODE_DIRECTORIES)
        if lab is not None:
            self._refuse(
                relative,
                actor_role,
                (
                    f"laboratory code directory ({lab}). Subject-side code may not "
                    "modify the laboratory; the separation is what makes the "
                    "distinction observable."
                ),
            )
        human = self._in_any(self.repository_relative(relative), HUMAN_OWNED_DIRECTORIES)
        if human is not None:
            self._refuse(
                relative,
                actor_role,
                f"human-owned area ({human}); outside the subject's authority",
            )
        if not self.is_subject_code(relative):
            self._refuse(
                relative,
                actor_role,
                (
                    "not inside the subject code area. The subject writes code "
                    "under baby_workspace/code/ and nowhere else."
                ),
            )

    def _refuse(self, relative: str, actor_role: str, reason: str) -> None:
        self.refusals.append({"path": relative, "role": actor_role, "reason": reason})
        raise AuthorizationError(f"{relative!r}: {reason}")

    # -- writing ----------------------------------------------------------
    def write_subject_file(self, relative: str, text: str, actor_role: str = "BABY_AI") -> str:
        """Write one subject file, recording the digest at write time.

        Returns the digest. The content itself is not hashed into the workspace
        record, so the workspace stays a summary and the file stays the artifact.
        """
        self.assert_write_allowed(relative, actor_role)
        target = self.resolve_within(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        from babylab.storage import atomic_write_text

        atomic_write_text(target, text)
        digest = sha256_hex(text.encode("utf-8"))
        self.subject_written[relative] = digest
        return digest

    def write_lab_file(self, relative: str, text: str) -> str:
        """Laboratory scaffolding inside the workspace, kept separate in the record."""
        target = self.resolve_within(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        from babylab.storage import atomic_write_text

        atomic_write_text(target, text)
        digest = sha256_hex(text.encode("utf-8"))
        self.lab_written.add(relative)
        return digest

    # -- reporting --------------------------------------------------------
    def subject_written_file_count(self) -> int:
        """How many files the subject has actually written. Zero, honestly."""
        return len(self.subject_written)

    def state(self) -> WorkspaceState:
        if self.refusals:
            return WorkspaceState.INTEGRITY_VIOLATION
        if self.subject_written:
            return WorkspaceState.HAS_SUBJECT_CODE
        return WorkspaceState.EMPTY

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "root": str(self.root),
            "environment_id": self.environment_id,
            "state": self.state().value,
            "subject_written": dict(sorted(self.subject_written.items())),
            "subject_written_file_count": self.subject_written_file_count(),
            "lab_written": sorted(self.lab_written),
            "refusals": list(self.refusals),
            "policy": {
                "subject_may_write": list(SUBJECT_CODE_DIRECTORIES),
                "subject_may_not_write": list(LAB_CODE_DIRECTORIES)
                + list(HUMAN_OWNED_DIRECTORIES),
                "excluded_capabilities": [
                    "privilege-escalation",
                    "laboratory-self-modification",
                    "control-plane-access",
                ],
            },
        }

    def content_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.to_dict()))


__all__ = [
    "HUMAN_OWNED_DIRECTORIES",
    "LAB_CODE_DIRECTORIES",
    "SUBJECT_CODE_DIRECTORIES",
    "WORKSPACE_SCHEMA",
    "CodeWorkspace",
    "WorkspaceState",
]
