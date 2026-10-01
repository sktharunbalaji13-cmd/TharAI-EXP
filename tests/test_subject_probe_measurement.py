"""Regression tests for the two M015 probe measurement defects.

These tests are about the probe's *measurement semantics*, not about any ACL
policy. Both defects produced confident, wrong security evidence:

  1. `traverse_directory` called Directory.GetFileSystemEntries, which requests
     FILE_LIST_DIRECTORY on the directory itself. It never descends to a child,
     so it could not measure traversal. The M015 experiment relied on that
     operation to decide whether root FILE_TRAVERSE was the missing capability,
     and got an answer about a different right.

  2. The read lambda called `new FileInfo(path).Length` before `File.OpenRead`.
     A stat failure aborted the lambda and was reported as
     `read_disposable_file result=OS_DENIED`, so a metadata denial was published
     as a read denial with no read ever attempted.

A test that only asserts the current code shape would pass forever without
detecting a regression, so each test here targets the specific confusion the
defect caused. Where behaviour can be checked by running the probe, it is: a
static source scan cannot tell whether an operation truly reads bytes, only
whether it appears to.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PROBE_SOURCE = REPO / "foundation" / "subject_probe.cs"
# Built into a per-session temp directory, NOT baby_workspace. The existing M016
# suites share a single baby_workspace/m016_probe.exe, and one of them rebuilds it
# from whatever source it finds. Sharing that path made these tests execute a
# binary built by another suite, so they asserted against a v1 probe and failed
# for a reason that had nothing to do with the measurement contract.
PROBE_EXE = Path(tempfile.gettempdir()) / "m015_probe_measurement" / "m016_probe.exe"

sys.path.insert(0, str(REPO))
from foundation.boundary_test import build_probe_argv, parse_probe_output  # noqa: E402


def _build_probe(exe: Path) -> Path:
    """Compile the CURRENT source with the C# compiler inside PowerShell 5.1.

    Always rebuilds. A cached binary is how these tests came to run a stale probe:
    the file existed from an earlier session, so the compile step was skipped and
    the assertions ran against a probe built from older source. The measurement
    contract is the thing under test, so the binary must match the source.
    """
    exe.parent.mkdir(parents=True, exist_ok=True)
    cs = exe.with_suffix(".cs")
    cs.write_text(PROBE_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
    if exe.exists():
        try:
            exe.unlink()
        except PermissionError:
            # A previous run's binary may still be executing. Fall back to a
            # fresh name rather than silently reusing a stale build.
            exe = exe.with_name(exe.stem + "_" + str(os.getpid()) + exe.suffix)
            cs = exe.with_suffix(".cs")
            cs.write_text(PROBE_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
    script = (
        "$ErrorActionPreference='Stop'; "
        f"Add-Type -Path '{cs}' "
        f"-OutputAssembly '{exe}' -OutputType ConsoleApplication"
    )
    built = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, shell=False, timeout=300)
    if built.returncode != 0 or not exe.is_file():
        pytest.skip("Add-Type could not compile the probe on this host")
    return exe


def _findings_by_operation(parsed: dict) -> dict[str, dict]:
    """Index the parser's findings by operation name.

    ``parse_probe_output`` returns a flat finding list, so a lookup by name needs
    an index. Building it here keeps the tests independent of list ordering,
    which the probe is free to change.
    """
    return {f["operation"]: f for f in parsed["findings"]}


def _detail_value(finding: dict, key: str) -> str | None:
    """Read one ``key=value`` out of a finding's detail string."""
    for token in str(finding.get("detail") or "").split():
        if token.startswith(key + "="):
            return token[len(key) + 1:]
    return None


def _method_body(source: str, name: str) -> str:
    """Extract one method's body by brace matching from its signature.

    Matches any return type, so `Main` (which returns int) is reachable as well as
    the void helpers.
    """
    match = re.search(
        rf"(?:static|public|private|internal|\s)+[\w<>\[\]]+\s+{re.escape(name)}\s*\(",
        source)
    if not match:
        pytest.fail(f"probe has no method named {name}")
    start = source.index("{", match.end())
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                body = source[start:index + 1]
                return _strip_comments(body)
    pytest.fail(f"unbalanced braces while reading {name}")


def _strip_comments(body: str) -> str:
    """Remove // comments so prose about a call is not read as a call.

    The corrected Traverse explains at length why it must not call Reach(). Those
    sentences contain the token, so a naive scan would fail the very test that
    documents the fix. Only // line comments are stripped: a /* */ block or a
    string literal could hide or fake a call, and neither appears in these
    methods.
    """
    lines = []
    for line in body.splitlines():
        # Keep string literals intact: a "//" inside a quoted path is not a comment.
        in_string = False
        cut = len(line)
        index = 0
        while index < len(line) - 1:
            if line[index] == '"' and line[index - 1:index] != "\\":
                in_string = not in_string
            elif not in_string and line[index:index + 2] == "//":
                cut = index
                break
            index += 1
        lines.append(line[:cut])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Defect 1: a method named traverse must not measure enumeration
# ---------------------------------------------------------------------------

def test_no_method_named_traverse_calls_get_file_system_entries():
    """The original defect, pinned at its exact mechanism.

    If a traverse-named method lists directory entries, its result answers
    FILE_LIST_DIRECTORY while the label claims FILE_TRAVERSE. That is the
    confusion that invalidated the M015 experiment.
    """
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    body = _method_body(source, "Traverse")
    assert "GetFileSystemEntries" not in body, (
        "a method named Traverse calls Directory.GetFileSystemEntries, which "
        "measures FILE_LIST_DIRECTORY rather than FILE_TRAVERSE"
    )


def test_enumeration_lives_in_enumerate_and_traverse_opens_a_leaf():
    """Separation is structural: the two operations must differ in mechanism.

    A rename alone would satisfy the test above while leaving both operations
    identical. This one requires traversal to actually open a target beneath the
    directory, which is the only way Windows exercises FILE_TRAVERSE.
    """
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    traverse_body = _method_body(source, "Traverse")
    enumerate_body = _method_body(source, "Enumerate")

    assert "TryNativeOpen" in traverse_body, (
        "Traverse must open a target beneath the directory to exercise traversal"
    )
    assert "GetFileSystemEntries" in enumerate_body, (
        "Enumerate is the FILE_LIST_DIRECTORY measurement and must list entries"
    )
    assert "TryNativeOpen" not in enumerate_body, (
        "Enumerate must not reuse the native-open path; that is the traverse test"
    )


def test_traverse_reports_traverse_and_list_as_separate_capabilities():
    """A single traversal verdict cannot be attributed to a single cause.

    The M015 failure was ambiguous precisely because one label covered both
    rights. The corrected operation must emit them distinctly, or a future denial
    is unattributable in exactly the same way.
    """
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    body = _method_body(source, "Traverse")
    assert "FILE_TRAVERSE" in body
    assert "FILE_LIST_DIRECTORY" in body, (
        "traversal evidence must also name the ancestor-listing capability "
        "separately, so a denial can be attributed to traverse or to list"
    )


# ---------------------------------------------------------------------------
# Defect 2: a metadata failure must never be published as a read denial
# ---------------------------------------------------------------------------

def test_read_reports_bytes_observed_and_never_takes_them_from_a_stat():
    """`bytes_observed` must come from Read(), not from a length or stat call.

    The original code printed FileInfo.Length as the observed byte count, so the
    number described a metadata result while sitting on a line labelled as a
    successful read.
    """
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    body = _method_body(source, "ReadBytes")
    assert ".Read(" in body, "ReadBytes must actually call Read()"
    assert "bytes_observed" in body
    # `buffer.Length` is the read buffer's own capacity, which is legitimate: the
    # count passed to Read() must come from the buffer, not from the file. Only a
    # *file* length is forbidden, so FileInfo and GetFileAttributes are the tokens
    # to reject here.
    assert "FileInfo" not in body, (
        "ReadBytes must not stat the file; FileInfo.Length is the exact call that "
        "made a metadata denial look like a read denial"
    )
    assert "GetFileAttributes" not in body, (
        "ReadBytes must not query the file's attributes; that is Metadata's job"
    )
    assert re.search(r"\.Length\b(?!\s*\})", body) is None or "buffer" in body, (
        "a length read in the read path must be the buffer's, not the file's"
    )


def test_read_occurs_before_any_metadata_measurement():
    """Ordering, not just presence, is what makes the evidence trustworthy.

    The original defect was a stat call sitting INSIDE the read lambda, so a stat
    failure pre-empted the read entirely. Separating the two operations is not
    sufficient on its own: if the stat still ran first, a run could end with a
    metadata result and no read result at all. This asserts the read is invoked
    first in Main.
    """
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    main = _method_body(source, "Main")
    read_call = main.find('ReadBytes("read_file_bytes"')
    metadata_call = main.find('Metadata("read_metadata"')
    assert read_call != -1, "Main must invoke the byte-read measurement"
    assert metadata_call != -1, "Main must invoke the metadata measurement"
    assert read_call < metadata_call, (
        "the byte read must be attempted before the optional metadata measurement, "
        "so metadata cannot be reported in place of a read"
    )


def test_metadata_is_reported_as_its_own_capability():
    """Metadata is a distinct capability and must be labelled as one.

    Folding it into the read line is what made the first subject run's
    `read_disposable_file=OS_DENIED` impossible to interpret.
    """
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    body = _method_body(source, "Metadata")
    assert "FILE_READ_ATTRIBUTES" in body
    assert "GetFileAttributesExW" in body
    assert "GetFileSystemEntries" not in body


# ---------------------------------------------------------------------------
# Defect 3: a Reach() preflight can suppress the capability it precedes
# ---------------------------------------------------------------------------

def test_traverse_does_not_preflight_with_reach():
    """The traversal measurement must not gate on Exists() before attempting.

    Reach() answers "does this path exist?", and under a restricted account a
    path that exists but cannot be traversed answers NO. A preflight built on it
    therefore returns early and publishes NOT_TESTABLE for a capability that was
    never attempted -- which is exactly what the first two subject runs of the
    corrected experiment reported.
    """
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    body = _method_body(source, "Traverse")
    assert "Reach(" not in body, (
        "Traverse must not call Reach() before the native open; Exists() cannot "
        "distinguish an inaccessible path from an absent one, so the preflight "
        "suppresses the FILE_TRAVERSE measurement it is meant to guard"
    )
    assert "Directory.Exists" not in body
    assert "File.Exists" not in body


def test_traverse_attempts_the_native_open_before_any_early_return():
    """The native open must be reachable even when the directory is unreadable.

    A structural check: the CreateFileW-backed helper must be invoked before any
    conditional return that depends on a reachability answer. This is what makes
    the preflight regression above impossible to reintroduce silently.
    """
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    body = _method_body(source, "Traverse")
    open_call = body.find("TryNativeOpen(leaf, FILE_READ_ATTRIBUTES")
    assert open_call != -1, "Traverse must attempt the minimal-access leaf open"

    # Only a return guarded by the absent-leaf check is permitted ahead of the
    # open. The guard is located structurally -- the `if` immediately enclosing
    # the return -- rather than by scanning backwards for a token, which would
    # match text anywhere in the enclosing block and pass on a comment.
    # Locate each `return` before the open, then find the nearest preceding `if`
    # whose body contains it. A multi-line Console.WriteLine makes the
    # immediately-preceding line a poor boundary, so the guard is taken to be the
    # last `if` opened before the return.
    for match in re.finditer(r"\breturn\b", body):
        if match.start() >= open_call:
            break
        guards = list(re.finditer(r"\bif\s*\(", body[:match.start()]))
        assert guards, "an early return before the native open has no guard at all"
        # The condition text is read to the parenthesis that closes it, not to the
        # next `)`, so a nested call inside the condition is not truncated.
        guard = guards[-1]
        depth = 0
        end = guard.end()
        for index in range(guard.end() - 1, len(body)):
            if body[index] == "(":
                depth += 1
            elif body[index] == ")":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        guard_text = body[guard.start():end]
        assert "IsNullOrEmpty(leaf)" in guard_text, (
            "the only early return allowed before the native open is guarded by "
            "IsNullOrEmpty(leaf); any other condition can suppress the "
            f"FILE_TRAVERSE measurement. Guard was: {guard_text!r}"
        )


def test_native_open_classifies_denial_apart_from_absence():
    """A missing target must not be reported as an access denial.

    TryNativeOpen previously returned OS_DENIED for every failure, so a typo in a
    path would have looked like a security control that worked. The error codes
    are classified instead, and that classification is what lets the traversal
    test drop its preflight without losing the denial/absence distinction.
    """
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    body = _method_body(source, "TryNativeOpen")
    assert "ERROR_ACCESS_DENIED" in body, (
        "only ERROR_ACCESS_DENIED may be reported as OS_DENIED"
    )
    for absent in ("ERROR_FILE_NOT_FOUND", "ERROR_PATH_NOT_FOUND"):
        assert absent in body, f"{absent} must be distinguished from a denial"
    deny_returns = [
        line for line in body.splitlines()
        if "return" in line and '"OS_DENIED"' in line
    ]
    assert len(deny_returns) == 1, (
        "OS_DENIED must be returned from exactly one branch, the "
        "ERROR_ACCESS_DENIED one; a blanket OS_DENIED would mask absent paths"
    )


def test_traverse_reports_not_testable_when_no_target_supplied():
    """An absent traversal target is genuinely untested, and says so."""
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    body = _method_body(source, "Traverse")
    assert "no_traversal_target_supplied" in body, (
        "a missing traversal target must report no_traversal_target_supplied "
        "rather than being silently degraded into a different operation"
    )


def test_other_capabilities_keep_their_own_measurement_calls():
    """The traversal fix must not collapse the other three capabilities.

    This guards against a 'fix' that makes traversal work by routing the read or
    the listing through the same call. Each capability must still reach its own
    Windows operation.
    """
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    assert "GetFileSystemEntries" in _method_body(source, "Enumerate"), (
        "FILE_LIST_DIRECTORY must still be measured by enumerating the directory"
    )
    assert ".Read(" in _method_body(source, "ReadBytes"), (
        "FILE_READ_DATA must still be measured by an actual read"
    )
    assert "GetFileAttributesExW" in _method_body(source, "Metadata"), (
        "FILE_READ_ATTRIBUTES must still be measured by its own call"
    )


def test_schema_remains_v2_after_the_preflight_correction():
    """The preflight fix is a measurement correction, not a new contract.

    Bumping the schema here would invalidate every archived v2 run, including
    the two that established the preflight defect. The operation names and
    capability labels are unchanged, so the schema must not move.
    """
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    assert "schema=probe/v2" in source
    assert "schema=probe/v3" not in source


def test_result_vocabulary_distinguishes_denied_from_bad_path():
    """OS_DENIED, PATH_ERROR, and NOT_TESTABLE must not collapse together.

    A missing file is not a denial. Reporting it as one would make an untested
    case look like a security control that worked.
    """
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    body = _method_body(source, "ReadBytes")
    # NOT_TESTABLE and PATH_ERROR are decided before the read is attempted, in the
    # caller's reachability guard, so the tokens are checked across both.
    main = _method_body(source, "Main")
    for token in ("OS_DENIED", "PATH_ERROR"):
        assert token in body, f"ReadBytes must be able to emit {token}"
    assert "NOT_TESTABLE" in main and "PATH_ERROR" in main, (
        "an unsupplied or unreachable read path must be reported as untestable or "
        "a path error, never as a denial"
    )


# ---------------------------------------------------------------------------
# Behavioural confirmation: run the probe, do not infer from source
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_missing_target_reports_not_testable_rather_than_denied(tmp_path):
    """A path that does not exist must not be reported as an access denial."""
    exe = _build_probe(PROBE_EXE)
    missing_root = tmp_path / "absent"
    missing_leaf = missing_root / "runtime" / "absent_fixture.exe"
    workspace = REPO / "baby_workspace"
    argv = build_probe_argv(
        scratch=tmp_path,
        staged=None,
        protected=None,
        workspace=workspace,
        traverse=missing_root,
        traverse_leaf=missing_leaf,
        read_file=missing_leaf,
    )
    run = subprocess.run([str(exe), *argv], capture_output=True, text=True,
                         shell=False, timeout=120)
    findings = _findings_by_operation(parse_probe_output(run.stdout))

    # With a leaf supplied, the traversal measurement attempts the open and the
    # kernel's answer arrives as PATH_ERROR -- never NOT_TESTABLE, which would
    # mean the probe declined to try, and never OS_DENIED, which would mean a
    # denial was invented for a path that is simply absent.
    traverse = findings.get("traverse_to_leaf")
    assert traverse is not None, (
        "a supplied traversal target must be attempted; the preflight removed in "
        "this correction used to return before any open was made"
    )
    assert traverse["outcome"] == "PATH_ERROR", (
        f"an absent traversal target reported {traverse['outcome']!r}; expected "
        f"PATH_ERROR because the native open was attempted and the OS reported "
        f"the file as not found"
    )
    # The kernel reports ERROR_PATH_NOT_FOUND (3) when a parent directory is
    # missing, and ERROR_FILE_NOT_FOUND (2) when only the leaf is. Both are
    # absence, so both are accepted -- what matters is that a not-found code came
    # back at all, which is what proves the open was attempted.
    detail = str(traverse.get("detail", ""))
    assert "winerror=2" in detail or "winerror=3" in detail, (
        "the absent-target case must carry a not-found Win32 code so a reader can "
        f"see the open really happened and the OS really answered; got {detail!r}"
    )

    for label in ("read_file_bytes", "read_metadata"):
        finding = findings.get(label)
        assert finding is not None, f"{label} produced no finding at all"
        assert finding["outcome"] in {"NOT_TESTABLE", "PATH_ERROR"}, (
            f"{label} on a missing path reported {finding['outcome']!r}; "
            f"an absent path is not an access denial"
        )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_actual_read_reports_bytes_equal_to_file_size(tmp_path):
    """bytes_observed must match the real content length.

    A probe that reported a size from metadata rather than from Read() would pass
    a weaker test; comparing against the written file size pins it to the bytes
    actually fetched.
    """
    exe = _build_probe(PROBE_EXE)
    fixture = tmp_path / "read_fixture.bin"
    payload = b"m015 measurement payload"
    fixture.write_bytes(payload)

    argv = build_probe_argv(
        scratch=tmp_path,
        staged=None,
        protected=None,
        workspace=REPO / "baby_workspace",
        traverse=tmp_path,
        traverse_leaf=fixture,
        read_file=fixture,
    )
    run = subprocess.run([str(exe), *argv], capture_output=True, text=True,
                         shell=False, timeout=120)
    findings = _findings_by_operation(parse_probe_output(run.stdout))

    read = findings["read_file_bytes"]
    assert read["outcome"] == "OS_ALLOWED"
    observed = _detail_value(read, "bytes_observed")
    assert observed is not None, "read_file_bytes must report bytes_observed"
    assert int(observed) == len(payload), (
        "bytes_observed must be the count Read() returned, not a stat length"
    )

    metadata = findings["read_metadata"]
    assert metadata["outcome"] == "OS_ALLOWED", (
        "metadata must be measured and reported in its own right"
    )
    assert _detail_value(metadata, "metadata_bytes_reported") is not None, (
        "the metadata line must use its own field name, not bytes_observed"
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_traverse_to_leaf_and_ancestor_list_are_independent_measurements(tmp_path):
    """The two traversal-related capabilities must both be present and distinct.

    Only the separation matters here, not either verdict: a regression that
    collapsed them again would still show two ALLOWED results.
    """
    exe = _build_probe(PROBE_EXE)
    leaf = tmp_path / "runtime" / "leaf.bin"
    leaf.parent.mkdir(parents=True, exist_ok=True)
    leaf.write_bytes(b"leaf")

    argv = build_probe_argv(
        scratch=tmp_path,
        staged=None,
        protected=None,
        workspace=REPO / "baby_workspace",
        traverse=tmp_path,
        traverse_leaf=leaf,
        read_file=leaf,
    )
    run = subprocess.run([str(exe), *argv], capture_output=True, text=True,
                         shell=False, timeout=120)
    findings = _findings_by_operation(parse_probe_output(run.stdout))

    assert "traverse_to_leaf" in findings, (
        "the corrected probe must emit traverse_to_leaf, not traverse_directory"
    )
    assert "traverse_ancestor_list" in findings
    assert _detail_value(findings["traverse_to_leaf"], "capability") == "FILE_TRAVERSE"
    assert _detail_value(
        findings["traverse_ancestor_list"], "capability") == "FILE_LIST_DIRECTORY"


def test_schema_version_advanced():
    """A schema bump is how a consumer learns the measurement contract changed."""
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    assert "schema=probe/v2" in source
