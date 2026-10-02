"""Guarded mutation surfaces for the test harness. TEST-ONLY.

Every helper here routes its paths through :mod:`tests.path_policy` BEFORE any
filesystem, ACL or subprocess operation runs. A test that uses these helpers
cannot mutate the repository even if it deliberately passes production paths --
the refusal happens first, and the operation never executes.

Why helpers rather than a wrapped global API
---------------------------------------------
Monkeypatching ``pathlib.Path.mkdir`` or ``shutil.rmtree`` process-wide would
catch more call sites, but it would also intercept the test runner, pytest's own
tmp_path handling, and every read-only inspection. That failure mode is subtle
and produces confusing errors far from their cause. The mutation surfaces are few
and known, so guarding them explicitly is auditable: a reader can list them and
check each one. The repository-wide audit in ``test_harness_write_isolation.py``
then asserts that no OTHER test helper mutates a repository path unguarded.
"""
from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

from tests.path_policy import (
    MUTATING_PROBE_POSITIONS,
    PROBE_ARGUMENT_CLASSIFICATION,
    PROBE_POSITIONAL_ARGUMENTS,
    assert_test_write_path,
    assert_test_write_paths,
)

__all__ = [
    "guarded_probe_argv",
    "run_probe_guarded",
    "make_fixture_file",
    "make_fixture_dir",
    "remove_tree",
    "apply_boundary_guarded",
    "apply_subject_deny_guarded",
]


def apply_boundary_guarded(root, **kwargs):
    """``apply_boundary`` against a disposable root only."""
    from foundation.staging import apply_boundary

    safe = assert_test_write_path(root, what="apply_boundary")
    return apply_boundary(safe, **kwargs)


def apply_subject_deny_guarded(root, **kwargs):
    """``apply_subject_deny`` against a disposable root only."""
    from foundation.subject_deny import apply_subject_deny

    safe = assert_test_write_path(root, what="apply_subject_deny")
    return apply_subject_deny(safe, **kwargs)


def restore_dacls_guarded(snapshot, *, root):
    """``_restore_dacls`` guarded: the snapshot's own paths are validated."""
    from foundation.subject_deny import _restore_dacls

    for path in snapshot.paths:
        assert_test_write_path(path, what="_restore_dacls")
    assert_test_write_path(root, what="_restore_dacls root")
    return _restore_dacls(snapshot)


def make_fixture_file(directory, name: str | None = None,
                      content: bytes = b"") -> Path:
    """Create a file the test invocation owns. Disposable directory required."""
    safe_dir = assert_test_write_path(directory, what="fixture directory")
    safe_dir.mkdir(parents=True, exist_ok=True)
    token = name or f"m016_fixture_{uuid.uuid4().hex[:12]}.exe"
    path = safe_dir / token
    path.write_bytes(content)
    return path


def make_fixture_dir(directory, name: str | None = None) -> Path:
    """Create a directory the test invocation owns. Disposable parent required."""
    safe_dir = assert_test_write_path(directory, what="fixture directory")
    token = name or f"m016_fixture_{uuid.uuid4().hex[:12]}"
    path = safe_dir / token
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def remove_tree(path) -> bool:
    """Remove a tree. Disposable path required.

    Returns whether the path is gone afterwards, so a caller can assert on it
    rather than assuming ``ignore_errors=True`` succeeded -- which is how a
    locked directory goes unnoticed.
    """
    safe = assert_test_write_path(path, what="cleanup")
    shutil.rmtree(safe, ignore_errors=True)
    return not safe.exists()


def guarded_probe_argv(**kwargs) -> list[str]:
    """Validate every mutation-capable probe path, then build the argv.

    Refuses BEFORE ``build_probe_argv`` produces an argv and before any process is
    launched. The "the probe subprocess would do it instead" argument is exactly
    the one that caused the incident: the probe ran as operator against
    production paths, so the mutation happened in a child process the test never
    directly called ``mkdir`` on.

    All four positional slots and all three mutating options are WRITE-scoped.
    The earlier version authorised positional slots 1-3 (``staged``, ``protected``,
    ``workspace``) as read-only on the reasoning that the probe "does not write to
    them". The probe source says otherwise:

    * ``staged`` -- the file is read and copied, but with no ``--staging-root`` the
      probe derives the destructive-copy directory from ``Path.GetDirectoryName(staged)``
      and then creates, appends, renames, replaces and deletes inside that
      directory. The argument therefore names a directory the probe mutates.
    * ``protected`` -- ``File.SetAttributes(entries[0], FileAttributes.ReadOnly)``
      on the first child it enumerates. A mutation of an arbitrary child.
    * ``workspace`` -- ``Touch``, read back, delete, then deleted again by cleanup.

    Classification lives in ``path_policy.PROBE_ARGUMENT_CLASSIFICATION`` and is
    asserted against the probe source by ``test_probe_argument_contract.py``.
    """
    from foundation.boundary_test import build_probe_argv

    write_scoped: dict[str, object] = {}

    # Positional slots. Indexed from PROBE_POSITIONAL_ARGUMENTS rather than
    # hardcoded, so a slot added or reordered in the builder cannot silently fall
    # out of the guard.
    for index, name in enumerate(PROBE_POSITIONAL_ARGUMENTS):
        if PROBE_ARGUMENT_CLASSIFICATION[name] != "WRITE":
            continue
        value = kwargs.get(name)
        if value is not None:
            write_scoped[f"{name} (positional {index})"] = value

    # Named options, both positional-or-keyword and keyword-only.
    for name, kind in PROBE_ARGUMENT_CLASSIFICATION.items():
        if kind != "WRITE" or name in PROBE_POSITIONAL_ARGUMENTS:
            continue
        value = kwargs.get(name)
        if value is not None:
            write_scoped[name] = value

    assert_test_write_paths(write_scoped, what="probe argument")

    # READ_ONLY arguments are deliberately NOT authorised here. A production read
    # is permitted, and it is permitted by being absent from this check -- there
    # is no allow-list, so an argument cannot be added to the read side by
    # forgetting to classify it.
    return build_probe_argv(**kwargs)


def run_probe_guarded(exe: Path, *, timeout: int = 180, **kwargs):
    """Launch the probe with mutation-capable paths already validated.

    Returns ``(completed_process, argv)``. The argv is returned because several
    tests assert on the exact command line, and rebuilding it to inspect it would
    be a second, unguarded construction.
    """
    argv = guarded_probe_argv(**kwargs)
    run = subprocess.run([str(exe), *argv], capture_output=True, text=True,
                         shell=False, timeout=timeout)
    return run, argv


# Every positional slot is now WRITE-scoped. Kept as an explicit assertion rather
# than a silent consequence so that widening the guard and narrowing it are both
# visible in the diff: if a future probe contract change makes a slot read-only
# again, this fails and the change has to be justified in the source.
assert MUTATING_PROBE_POSITIONS == (0, 1, 2, 3), (
    "every probe positional slot is mutation-capable; see "
    "PROBE_ARGUMENT_CLASSIFICATION in tests/path_policy.py"
)