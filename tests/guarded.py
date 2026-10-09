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

import re
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
    "icacls_guarded",
    "icacls_reported_failures",
    "icacls_succeeded",
    "attrib_guarded",
    "attrib_succeeded",
    "attrib_reported_failures",
    "AttributeMutationRefused",
    "ATTRIB_MUTATING_OPERATIONS",
    "ATTRIB_SCOPE_MODIFIERS",
    "ATTRIB_PATH_EXPANDING",
    "RecursiveMutationRefused",
    "ICACLS_MUTATING_SWITCHES",
    "ICACLS_PATH_EXPANDING_SWITCHES",
    "apply_boundary_guarded",
    "apply_subject_deny_guarded",
]

#: icacls switches that change a descriptor, an owner, or the filesystem. A bare
#: ``icacls <path>`` is a listing and is not in this set; anything here is.
ICACLS_MUTATING_SWITCHES = frozenset({
    "/grant", "/grant:r", "/deny", "/deny:r", "/remove", "/remove:g", "/remove:d",
    "/remove:u", "/inheritance", "/inheritance:r", "/inheritance:d", "/inheritance:e",
    "/setowner", "/setintegritylevel", "/reset", "/save", "/restore", "/delete",
})

#: Switches that widen the affected-path set beyond the literal path argument.
#:
#: M023 measured what ``/T`` does on a disposable tree carrying one reparse point of
#: each kind. All three escape the validated root::
#:
#:     none            -> does NOT escape
#:     symlink (dir)   -> mutates the link TARGET and its contents
#:     symlink (file)  -> mutates the link TARGET file
#:     junction        -> mutates the target's CONTENTS (the target directory itself
#:                        was unchanged in this measurement; its children were not)
#:
#: So ``/T`` cannot be made safe by validating the path it was handed: the affected set
#: is computed by Windows' own reparse resolution, which the harness can neither
#: enumerate nor predict. Enumerating the subtree first would only be sound if the
#: enumeration's traversal matched ``icacls``' exactly, and nothing here establishes
#: that it does.
#:
#: Hence **rejected by policy**, fail-closed, before any process launches. That is the
#: outcome the measurement produced, not an assumption made in advance.
#:
#: ``/C`` and ``/Q`` are refused for the return-code rule rather than for recursion:
#: ``/C`` converts per-path failures into a successful return code, and ``/Q``
#: suppresses the output :func:`icacls_reported_failures` reads to detect them.
ICACLS_PATH_EXPANDING_SWITCHES = frozenset({
    "/t",
    "/c",
    "/q",
})


class RecursiveMutationRefused(ValueError):
    """A path-expanding mutation was requested and refused before launch.

    Distinct from the plain :class:`ValueError` a non-mutating switch set raises, so a
    caller can tell "this harness will not recurse" from "your switch set contained
    nothing mutating". Both are refusals; they call for different corrections.
    """


def icacls_reported_failures(completed) -> int:
    """The per-path failure count icacls reported; ``0`` means it claims success.

    ``icacls`` can return ``0`` while reporting ``Failed processing N files``. M022
    measured exactly that, so a caller checking only the return code can report a
    mutation that never happened. Reading the reported number removes the dependency on
    the return code alone.

    With ``/C`` refused by :func:`icacls_guarded`, one run cannot both succeed and
    hide its own failures -- which is why that switch is refused rather than only
    documented.
    """
    text = (completed.stdout or "") + (completed.stderr or "")
    # The count must be the one that FOLLOWS the phrase, not merely the first integer on
    # the line. icacls puts both numbers on one line --
    #   "Successfully processed 1 files; Failed processing 0 files"
    # -- so taking the first digit on that line returns the SUCCESS count and reports a
    # clean run as a failure. Found by running it: a legitimate grant returned rc 0 and
    # icacls_succeeded() reported False. The phrase-anchored match is the fix.
    for match in re.finditer(r"Failed\s+processing\s+(\d+)\s+files", text):
        return int(match.group(1))
    return 0


def icacls_succeeded(completed) -> bool:
    """True only when icacls returned 0 **and** reported no per-path failure."""
    return completed.returncode == 0 and icacls_reported_failures(completed) == 0


def icacls_guarded(path, switches, *, timeout: int = 120):
    """Run a **mutating, non-recursive** ``icacls`` against a disposable path only.

    Three checks run before the process is launched, all here rather than at the call
    site:

    1. the path must be outside the repository, via :func:`assert_test_write_path`;
    2. no path-expanding switch may be present
       (:data:`ICACLS_PATH_EXPANDING_SWITCHES`);
    3. at least one mutating switch must be present.

    The third is not pedantry. ``icacls <path>`` with no switch is a *listing*, so a
    helper that accepted an empty switch list would be a mutation surface whose refusal
    depended on the caller passing the right thing -- the assumption that eventually
    does not hold.

    The second is M023's finding. A command is not safe merely because its literal path
    argument is safe: ``/T`` was measured to mutate descendants and to follow symlinks,
    file symlinks and junctions straight out of the validated tree. Validating one path
    then permitting a recursion over a set the harness cannot enumerate has the same
    shape as the M015 incident, so recursion is refused rather than permitted
    optimistically.

    Ordering is deliberate and fail-closed: path, then recursion, then mutating-switch
    requirement. A caller cannot use a weaker error to discover whether its path was
    acceptable.

    The returned ``CompletedProcess`` is **not** proof the mutation occurred; callers
    must consult :func:`icacls_succeeded`.

    ``/inheritance:d`` is deliberately still available: M019 forbids *assuming* it
    preserves same-SID ACE semantics, not running it on disposable state. No M020
    fixture uses it, because a fixture built that way would be testing the M016 defect
    rather than the verifier.
    """
    safe = assert_test_write_path(path, what="icacls mutation")
    supplied = tuple(str(s) for s in switches)

    expanding = sorted({s.lower() for s in supplied} & ICACLS_PATH_EXPANDING_SWITCHES)
    if expanding:
        raise RecursiveMutationRefused(
            f"icacls_guarded refuses path-expanding switches {expanding}: M023 measured "
            "/T mutating descendants and following symlinks, file symlinks and junctions "
            "out of the validated tree, so the affected-path set cannot be enumerated or "
            "validated before launch. /C additionally hides per-path failures behind a "
            "zero return code. Apply the mutation to each path explicitly.")

    mutating = [s for s in supplied
                if s.lower().startswith(tuple(ICACLS_MUTATING_SWITCHES))]
    if not mutating:
        raise ValueError(
            "icacls_guarded refuses a switch set with no mutating switch: "
            f"{supplied!r}. Use a plain `icacls <path>` subprocess for a listing.")
    return subprocess.run(["icacls", str(safe), *supplied], capture_output=True,
                          text=True, timeout=timeout, shell=False,
                          stdin=subprocess.DEVNULL, encoding="utf-8",
                          errors="replace")


# ---------------------------------------------------------------------------
# attrib -- the surface a DACL-centred audit cannot see
# ---------------------------------------------------------------------------
#
# ``attrib`` changes no DACL, so every audit built around security descriptors misses it.
# That is M023's finding generalised: a harness must define its mutation surface, not
# search for the command most commonly used to mutate one.
#
# Attribute writes are not beside this project's threat model, they are inside it.
# ``FILE_WRITE_ATTRIBUTES`` is a DACL right -- it is right **E** of the milestone corpus,
# the "accidentally granted" case -- and ``attrib`` is the tool that spends it.

#: Attribute operations, from ``attrib /?``. Everything here mutates; ``/L`` is a modifier
#: and ``/D``/``/S`` are handled below.
ATTRIB_MUTATING_OPERATIONS = frozenset({
    "+r", "-r", "+a", "-a", "+s", "-s", "+h", "-h", "+i", "-i",
    "+c", "-c", "+o", "-o", "+p", "-p", "+x", "-x", "+t", "-t", "+u", "-u",
})

#: Modifiers that do not themselves widen the affected-path set.
ATTRIB_SCOPE_MODIFIERS = frozenset({"/l", "/d"})

#: Refused, and the measured reason is stronger than M023's was for ``icacls /T``.
#:
#: ``attrib /s`` does not recurse from the path it was given. It recurses from the
#: **process working directory**, treating its path argument as a filename *pattern*:::
#:
#:     attrib root +r /s          -> processes nothing (root is a directory, not a match)
#:     cwd=root; attrib +r *.txt /s -> sets +r on every .txt under root
#:
#: So the affected-path set is a function of the CWD -- a parameter no argv element
#: controls. Measured with one reparse kind at a time:
#:
#:     none          -> does NOT escape
#:     symlink (dir) -> ESCAPES
#:     symlink (file)-> does NOT escape
#:     junction      -> ESCAPES
#:
#: Wildcard patterns are refused for the same reason: ``*.txt`` is a set the harness
#: cannot enumerate or validate.
#:
#: The repository used no recursive ``attrib`` and no wildcards at all, so refusing costs
#: no existing capability.
ATTRIB_PATH_EXPANDING = frozenset({"/s"})
ATTRIB_WILDCARD_CHARS = ("*", "?", "<", ">", "|")


class AttributeMutationRefused(ValueError):
    """An attribute mutation was refused before launch.

    Distinct from :class:`ValueError`, which a switch set containing no mutating operation
    raises. ``/S``, a wildcard, a caller-supplied CWD and "nothing mutating" all fail
    closed, and each needs a different correction.
    """


def attrib_reported_failures(completed) -> int:
    """How many objects ``attrib`` reported it could not process.

    ``rc == 0`` is **not** evidence for ``attrib`` either, and the trap is worse than
    ``icacls``'s. Measured::

        attrib +r <path that does not exist>   rc=0, stdout "File not found - <path>"
        attrib +r *.txt /s (success)           rc=0, stdout EMPTY

    There is no summary line and no non-zero code, so the absence of a failure line is
    the only success signal available. :func:`attrib_succeeded` requires both.
    """
    text = (completed.stdout or "") + (completed.stderr or "")
    markers = ("File not found", "Access is denied", "Access denied",
               "The system cannot find", "Failed to process")
    return sum(1 for line in text.splitlines()
               if any(marker in line for marker in markers))


def attrib_succeeded(completed) -> bool:
    """True only when ``attrib`` returned 0 **and** reported no per-path failure."""
    return completed.returncode == 0 and attrib_reported_failures(completed) == 0


def attrib_guarded(path, arguments, *, timeout: int = 120, cwd=None):
    """Run a **mutating, non-recursive, non-wildcard** ``attrib`` on a disposable path.

    Four checks run before the process is launched, all here rather than at the call
    site:

    1. the path must be outside the repository, via :func:`assert_test_write_path`;
    2. no path-expanding modifier (:data:`ATTRIB_PATH_EXPANDING`) and no wildcard;
    3. no caller-supplied ``cwd`` -- the recursion root is not an argv element, so
       letting a caller set it would hand them an affected-path set they never named;
    4. at least one mutating operation must be present.

    Ordering is fail-closed and mirrors :func:`icacls_guarded`: path first, then
    expansion, then semantics. A caller cannot learn whether its path was acceptable by
    receiving a weaker error.

    The returned ``CompletedProcess`` is not proof the attribute changed; callers must
    consult :func:`attrib_succeeded`, because ``attrib`` returns 0 for an object it did
    not process.
    """
    safe = assert_test_write_path(path, what="attrib mutation")

    if cwd is not None:
        raise AttributeMutationRefused(
            "attrib_guarded refuses a caller-supplied cwd: attrib /s expands from the "
            "process working directory, which is not reachable through any path "
            "argument, so naming it here would reintroduce the unvalidated affected set "
            "this guard exists to prevent")

    supplied = tuple(str(a) for a in arguments)

    expanding = sorted({a.lower() for a in supplied} & ATTRIB_PATH_EXPANDING)
    if expanding:
        raise AttributeMutationRefused(
            f"attrib_guarded refuses path-expanding modifiers {expanding}: M024 measured "
            "attrib /s expanding from the process working directory rather than from the "
            "supplied path, and following directory symlinks and junctions out of the "
            "validated tree. Apply the change to each path explicitly.")

    unknown_modifiers = sorted({a.lower() for a in supplied
                                if a.startswith("/")
                                and a.lower() not in ATTRIB_SCOPE_MODIFIERS
                                and a.lower() != "/?"})
    if unknown_modifiers:
        raise AttributeMutationRefused(
            f"attrib_guarded does not recognise modifier(s) {unknown_modifiers}; an "
            "unclassified option is refused rather than assumed harmless")

    wildcards = sorted({a for a in supplied
                        if not a.startswith("/") and any(c in a for c in ATTRIB_WILDCARD_CHARS)})
    if wildcards:
        raise AttributeMutationRefused(
            f"attrib_guarded refuses pattern arguments {wildcards}: a wildcard names a "
            "set the harness cannot enumerate or validate. Enumerate the paths "
            "explicitly, or use /l for a literal name.")

    mutating = [a for a in supplied if a.lower() in ATTRIB_MUTATING_OPERATIONS]
    if not mutating:
        raise ValueError(
            "attrib_guarded refuses an argument list with no mutating operation: "
            f"{supplied!r}. Read an attribute with Path.stat().st_file_attributes "
            "instead of shelling out.")

    return subprocess.run(["attrib", str(safe), *supplied], capture_output=True,
                          text=True, timeout=timeout, shell=False,
                          stdin=subprocess.DEVNULL, encoding="utf-8",
                          errors="replace")


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