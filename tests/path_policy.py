"""Canonical path policy for the test harness. TEST-ONLY. Mutation boundary.

Why this exists
---------------
An M015/M016 test run destroyed the production staging boundary. The mechanism was
NOT ``apply_boundary()`` -- audit showed it is called exactly once, from
``test_staging_boundary.py``, and it receives ``tmp_path``. The real mechanism was
that test fixtures and the subject probe were pointed at production paths:

- ``tests/test_boundary_harness.py`` created and deleted fixture files inside
  ``subject_runtime/runtime`` and ``subject_runtime/config``.
- ``tests/test_m016_launch.py`` invoked the full probe against
  ``subject_runtime/config`` with operator authority, so the probe itself created,
  renamed and deleted objects in production.

A docstring saying "this test owns its fixtures" is not a control. Ownership by
convention is what produced the incident. This module makes the boundary
structural instead: every mutation-capable surface validates its paths here,
before any filesystem, ACL or subprocess operation runs.

Read versus write
-----------------
Production READS stay permitted, and deliberately so. The read-only checks
(``test_m015_boundary_still_verifies_after_m016_work``,
``test_principal_names_containing_spaces_survive``,
``test_no_runtime_or_model_was_staged``) are what DETECTED the incident. Removing
them would remove the alarm. Only MUTATION is refused.

Canonicalisation
----------------
Comparison is on resolved, normalised, case-folded path *parts* -- never on raw
string prefixes. ``C:\\dev\\TharAI-EXP-evil`` shares a string prefix with the
repository root and must not be classified as inside it. A path that does not
exist yet is still classified, because ``Path.resolve()`` is non-strict on
Windows: it walks and normalises the missing tail rather than failing.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ProductionPathViolation",
    "repo_root",
    "canonical",
    "is_inside_repo",
    "assert_test_write_path",
    "assert_test_write_paths",
    "read_production_for_verification",
    "PROBE_POSITIONAL_ARGUMENTS",
    "PROBE_PATH_OPTIONS",
    "MUTATING_PROBE_OPTIONS",
    "MUTATING_PROBE_FLAGS",
    "MUTATING_PROBE_POSITIONS",
    "READ_ONLY_PROBE_OPTIONS",
    "PROBE_MUTATION_EVIDENCE",
    "classify_probe_arguments",
]


#: Environment override, so the policy can be pointed at a repository other than
#: the one this file lives in (a checkout copy, a CI workspace). Falls back to
#: the parent of ``tests/``.
ENV_REPO_ROOT = "BABYAI_REPO_ROOT"


def repo_root() -> Path:
    """The canonical repository root, from the environment when set.

    Deliberately derived rather than hardcoded: a user-specific literal is both a
    portability bug and a policy that silently stops applying on another machine.
    """
    override = os.environ.get(ENV_REPO_ROOT)
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def canonical(path: str | Path) -> Path:
    """Absolute, normalised, ``.``/``..``-free, symlink-resolved path.

    Non-strict on purpose. ``resolve()`` on a path whose tail does not exist yet
    still normalises the missing components, which is required here: the policy
    must reject a FUTURE production path, not only one that already exists.
    Resolving only what happens to be present would let a test create a new
    directory inside production after validation.
    """
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return Path(os.path.normpath(str(candidate.resolve())))


def _parts(path: Path) -> tuple[str, ...]:
    """Drive-letter-normalised, case-folded components, for comparison."""
    out: list[str] = []
    for part in path.parts:
        if part.endswith(":") and len(part) == 2:      # "C:" -> "c"
            out.append(part.lower())
            continue
        if part in ("\\", "/"):
            continue
        out.append(part.casefold())
    return tuple(out)


def is_inside_repo(path: str | Path, root: str | Path | None = None) -> bool:
    """True when ``path`` is the repository root or any descendant of it.

    Component-wise, so a string-prefix sibling is NOT inside.
    """
    base = canonical(root) if root is not None else repo_root()
    parts = _parts(canonical(path))
    base_parts = _parts(base)
    if len(parts) < len(base_parts):
        return False
    return parts[: len(base_parts)] == base_parts


class ProductionPathViolation(RuntimeError):
    """A mutation-capable test helper was handed a path inside the repository.

    Carries the evidence needed to diagnose it: what was supplied, what it
    canonicalises to, and which repository root it collided with.
    """

    def __init__(self, supplied: str | Path, resolved: Path, root: Path,
                 reason: str) -> None:
        self.supplied = str(supplied)
        self.resolved = str(resolved)
        self.repository_root = str(root)
        self.reason = reason
        super().__init__(
            f"refusing to mutate a repository path from a test: {reason}\n"
            f"  supplied        : {self.supplied}\n"
            f"  canonical       : {self.resolved}\n"
            f"  repository root : {self.repository_root}\n"
            f"A test must mutate only disposable state under tmp_path. Read-only "
            f"production access goes through read_production_for_verification()."
        )


def assert_test_write_path(path: str | Path, *, root: str | Path | None = None,
                           what: str = "mutation") -> Path:
    """Authorise ONE path for a mutation-capable operation.

    Returns the canonical path on success so a caller can use the value it just
    validated rather than re-resolving. Raises :class:`ProductionPathViolation`
    otherwise -- before any filesystem, ACL or subprocess work happens.

    This is the single mutation authorisation point. Mutation-capable helpers call
    it; tests do not need to remember to.
    """
    base = canonical(root) if root is not None else repo_root()
    resolved = canonical(path)
    if is_inside_repo(resolved, base):
        reason = ("the path is the repository root itself"
                  if _parts(resolved) == _parts(base)
                  else f"the path is inside the repository ({what})")
        raise ProductionPathViolation(path, resolved, base, reason)
    return resolved


def assert_test_write_paths(paths: dict[str, str | Path | None], *,
                            root: str | Path | None = None,
                            what: str = "mutation") -> dict[str, Path]:
    """Authorise a named mapping of paths, skipping ``None`` values.

    The named form is for helpers taking several paths at once (a probe argv,
    a fixture set), so the refusal message says WHICH argument was the problem
    rather than leaving the caller to work out which of six paths it was.
    """
    out: dict[str, Path] = {}
    for name, value in paths.items():
        if value is None:
            continue
        out[name] = assert_test_write_path(value, root=root,
                                           what=f"{what}: {name}")
    return out


def read_production_for_verification(path: str | Path) -> Path:
    """Authorise a READ-ONLY production access and return the canonical path.

    Named separately from :func:`assert_test_write_path` so the distinction is
    visible at every call site, and so a future reader cannot mistake a permitted
    production read for a permitted mutation. It grants reading only: the caller
    is responsible for not writing, and every mutation surface still refuses.
    """
    return canonical(path)


# ---------------------------------------------------------------------------
# The probe's path-bearing argument contract.
#
# Classified by WHAT THE LAUNCHED PROCESS CAN DO to each path, not by argument
# name and not by whether the Python harness itself writes there. The probe is a
# child process running under the operator: it creates, appends, renames,
# replaces and deletes objects in paths the harness never touches itself. A
# classification of READ_ONLY on such an argument is a hole in the guard, and a
# guard that looks complete while having a hole is worse than one that is
# visibly narrow -- it is mistaken for a control.
#
# Every entry is derived from ``foundation/subject_probe.cs``; the operation names
# in PROBE_MUTATION_EVIDENCE are the ``probe=<label>`` operations that touch that
# path, and ``test_probe_argument_contract.py`` asserts each of those labels
# actually exists in the probe source. A new mutating operation added to the probe
# without a corresponding classification change therefore fails a test rather than
# silently widening the attack surface.
# ---------------------------------------------------------------------------

#: Positional slots of ``build_probe_argv``, in order. Positional 0 is scratch.
PROBE_POSITIONAL_ARGUMENTS = ("scratch", "staged", "protected", "workspace")

#: Named path-bearing options, in ``build_probe_argv`` keyword form. KEYWORD FORM,
#: never the CLI flag spelling: an earlier version of the guard tuple used the
#: dashed spelling, so every lookup missed and the guard skipped every option
#: while still appearing to check them. That is why
#: ``test_mutating_probe_option_names_match_the_builder_keywords`` exists.
PROBE_PATH_OPTIONS = (
    "traverse", "traverse_leaf",
    "enumerate_runtime", "enumerate_model", "enumerate_config",
    "read_file", "acl_target", "staging_root", "delete_fixture",
)

#: Every path-bearing argument the probe accepts, keyed by builder keyword.
#: Value is WRITE or READ_ONLY.
PROBE_ARGUMENT_CLASSIFICATION = {
    # Positional 0. The probe creates p.txt, creates m016_child_create_dir, then
    # deletes both -- and the cleanup sweep deletes them again by exact name.
    "scratch": "WRITE",
    # Positional 1. The staged file itself is only read (GetAttributes) and is the
    # SOURCE of File.Copy. But when --staging-root is not supplied the probe
    # derives the destructive-copy directory from this path's PARENT
    # (Path.GetDirectoryName(staged)) and then creates, appends, renames,
    # replaces and deletes inside it. So this argument determines a directory the
    # probe mutates, even though the file it names is never modified.
    "staged": "WRITE",
    # Positional 2. Directory.GetFileSystemEntries, then File.SetAttributes on the
    # FIRST entry it finds -- a real mutation of an arbitrary child, not a read.
    "protected": "WRITE",
    # Positional 3. Touch(probe_workspace.txt), read it back, delete it, then the
    # cleanup sweep deletes it again.
    "workspace": "WRITE",

    # --staging-root. The destructive-copy directory. Touch, append, delete,
    # rename, replace, create a child, and a cleanup enumeration + delete sweep.
    "staging_root": "WRITE",
    # --acl-target. File.SetAttributes(ReadOnly) then restore. A write to file
    # attributes, which the ACL does not contain and icacls does not report.
    "acl_target": "WRITE",
    # --delete-fixture. Directory.Delete(path, recursive: true).
    "delete_fixture": "WRITE",

    # --traverse / --traverse-leaf. The native directory open IS the measurement;
    # there is no separate existence preflight precisely because Exists() cannot
    # distinguish "absent" from "present but not traversable".
    "traverse": "READ_ONLY",
    "traverse_leaf": "READ_ONLY",
    # --enumerate-*. Reach() then a listing.
    "enumerate_runtime": "READ_ONLY",
    "enumerate_model": "READ_ONLY",
    "enumerate_config": "READ_ONLY",
    # --read-file. FileStream(Open, Read) plus a length read. FileAccess.Read.
    "read_file": "READ_ONLY",
}

#: The ``probe=<label>`` operations that mutate each WRITE argument, as they appear
#: in ``foundation/subject_probe.cs``. Kept next to the classification so the two
#: cannot drift apart silently, and asserted against the probe source by
#: ``test_probe_argument_contract.py``.
PROBE_MUTATION_EVIDENCE = {
    "scratch": ("create_file_in_staging_scratch", "create_child_directory",
                "cleanup_p_txt", "cleanup_childdir"),
    "staged": ("modify_staged_executable", "append_staged_executable",
               "delete_staged_executable", "rename_staged_executable",
               "replace_staged_executable", "create_child_executable_beside_runtime",
               "cleanup_owned_copy", "clear_copy_readonly"),
    "protected": ("modify_acl_on_protected",),
    "workspace": ("workspace_write", "workspace_delete"),
    "staging_root": ("modify_staged_executable", "append_staged_executable",
                     "delete_staged_executable", "rename_staged_executable",
                     "replace_staged_executable", "create_child_executable_beside_runtime",
                     "cleanup_owned_copy"),
    "acl_target": ("modify_acl", "restore_acl_target_attributes"),
    "delete_fixture": ("delete_child_directory",),
}

MUTATING_PROBE_OPTIONS = tuple(
    name for name, kind in PROBE_ARGUMENT_CLASSIFICATION.items()
    if kind == "WRITE" and name in PROBE_PATH_OPTIONS
)
MUTATING_PROBE_FLAGS = tuple("--" + name.replace("_", "-") for name in MUTATING_PROBE_OPTIONS)
MUTATING_PROBE_POSITIONS = tuple(
    index for index, name in enumerate(PROBE_POSITIONAL_ARGUMENTS)
    if PROBE_ARGUMENT_CLASSIFICATION[name] == "WRITE"
)
READ_ONLY_PROBE_OPTIONS = tuple(
    name for name, kind in PROBE_ARGUMENT_CLASSIFICATION.items() if kind == "READ_ONLY"
)


def classify_probe_arguments() -> dict[str, str]:
    """The full path-argument classification, as a copy.

    Returned rather than exposed as a bare module constant so a caller cannot
    mutate the shared table, and so the audit has one obvious thing to read.
    """
    return dict(PROBE_ARGUMENT_CLASSIFICATION)