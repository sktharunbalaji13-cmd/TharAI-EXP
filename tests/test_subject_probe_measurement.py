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
        exe.unlink()
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
                return source[start:index + 1]
    pytest.fail(f"unbalanced braces while reading {name}")


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

    for label in ("traverse", "read_file_bytes", "read_metadata"):
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
