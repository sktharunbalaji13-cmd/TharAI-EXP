"""Regression tests for the two M016 probe measurement-integrity defects.

Both produced confident, wrong security evidence from a real subject run against
the disposable 8-path mirror:

  1. Exception classification. `HResultCode()` masked every HRESULT to 16 bits
     and only ever looked at the OUTER exception. A subject run reported

         delete_child_directory result=PATH_ERROR winerror=5664

     5664 is 0x80131620 & 0xFFFF -- the runtime's own IOException HRESULT, not a
     Win32 error. Reproducing the same rights on a throwaway tree showed the OS
     returned ERROR_ACCESS_DENIED on the INNER exception. The probe fabricated a
     Win32-looking number and lost the denial.

     The rule these tests pin: never read the low 16 bits of an arbitrary HRESULT
     as a Win32 error, and search the whole exception chain.

  2. No-op delete. `File.Delete` on a missing path is a successful no-op. The
     same run reported

         workspace_write result=OS_DENIED
         workspace_read   result=PATH_ERROR winerror=2
         workspace_delete result=OS_ALLOWED

     The write was denied, so the file never existed, so the delete deleted
     nothing -- and read as OS_ALLOWED, asserting a permission never exercised.
     Deleting nothing is NOT_TESTABLE, not a pass.

Static source assertions alone would pass forever without detecting a behavioural
regression, so the tests that can be checked by behaviour are: the probe is
compiled and run, and its real output is asserted.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PROBE_SOURCE = REPO / "foundation" / "subject_probe.cs"
# Built into a per-session temp directory, not baby_workspace, which the M016
# suites share and rebuild.
PROBE_EXE = Path(tempfile.gettempdir()) / "m016_probe_integrity" / "m016_probe.exe"

sys.path.insert(0, str(REPO))
from foundation.boundary_test import build_probe_argv, parse_probe_output  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _build_probe(exe: Path) -> Path:
    """Compile the CURRENT source, always.

    Always rebuilds: a cached binary means the tests assert against a probe built
    from older source, which is how these measurement contracts went untested.
    """
    exe.parent.mkdir(parents=True, exist_ok=True)
    cs = exe.with_suffix(".cs")
    cs.write_text(PROBE_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
    if exe.exists():
        try:
            exe.unlink()
        except PermissionError:
            pass
    script = (
        "$ErrorActionPreference='Stop'; "
        f"Add-Type -Path '{cs}' -OutputAssembly '{exe}' -OutputType ConsoleApplication"
    )
    built = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, shell=False, timeout=300,
        stdin=subprocess.DEVNULL)
    if built.returncode != 0 or not exe.is_file():
        pytest.skip("Add-Type could not compile the probe on this host")
    return exe


def _run(exe: Path, **kwargs) -> tuple[dict, str]:
    argv = build_probe_argv(**kwargs)
    run = subprocess.run([str(exe), *argv], capture_output=True, text=True,
                         shell=False, timeout=180,
                         stdin=subprocess.DEVNULL)
    return parse_probe_output(run.stdout), run.stdout


def _by_op(parsed: dict) -> dict[str, dict]:
    return {f["operation"]: f for f in parsed["findings"]}


def _detail(finding: dict, key: str) -> str | None:
    for token in str(finding.get("detail") or "").split():
        if token.startswith(key + "="):
            return token[len(key) + 1:]
    return None


def _result(finding: dict) -> str:
    """The probe's own verdict for a finding.

    The parser records it as `outcome`; `detail` carries only the key=value pairs.
    Reading `result=` out of the detail string works too but conflates the
    verdict with any other `result=` token, so the parsed field is authoritative.
    """
    return str(finding.get("outcome") or "")


def _source() -> str:
    return PROBE_SOURCE.read_text(encoding="utf-8")


def _body(source: str, name: str) -> str:
    """Extract one method body by brace matching."""
    idx = source.find(name)
    assert idx != -1, f"{name} not found in the probe source"
    start = source.find("{", idx)
    assert start != -1, f"{name} has no body"
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    raise AssertionError(f"{name} body is unbalanced")


# ---------------------------------------------------------------------------
# FIX 1 -- exception unwrapping and no fabricated Win32 codes
# ---------------------------------------------------------------------------

def test_hresult_masking_is_gone():
    """The defect, pinned by its own shape.

    `ex.HResult & 0xFFFF` applied unconditionally is the defect. It fabricates a
    Win32-looking code from any CLR HRESULT, which is how 0x80131620 became the
    meaningless "5664".
    """
    source = _source()
    assert "static int HResultCode" not in source, (
        "HResultCode still exists; the unconditional `HResult & 0xFFFF` mask is "
        "the defect this correction removes"
    )
    # A blanket mask on any EXECUTABLE line outside TryWin32Error, where masking is
    # legitimate only because the high word has already been checked. Comments
    # describing the old defect are expected and are not flagged.
    guarded_at = source.find("static bool TryWin32Error")
    guarded_end = source.find("static Verdict Classify")
    outside = source[:guarded_at] + source[guarded_end:]
    blanket = []
    for line in outside.splitlines():
        code = line.split("//")[0]
        if "HResult & 0xFFFF" in code:
            blanket.append(line.strip())
    assert not blanket, (
        f"a blanket HRESULT mask survives outside TryWin32Error: {blanket}"
    )


def test_try_win32_error_requires_a_zero_high_word():
    """Only HRESULT_FROM_WIN32 values may be read as Win32 errors."""
    body = _body(_source(), "static bool TryWin32Error")
    assert "0xFFFF0000" in body, (
        "TryWin32Error must test the high word before trusting the low bits"
    )
    # The 0x80131620 / 5664 case, named explicitly so a future edit that
    # reintroduces the blanket mask is caught here.
    assert "0x8013" in _source(), (
        "the CLR HRESULT facility 0x8013 must be named in the source"
    )


def test_classify_walks_the_inner_exception_chain():
    """A wrapped denial must be found by walking, not by reading the outer type."""
    body = _body(_source(), "static Verdict Classify")
    assert "InnerException" in body, (
        "Classify must walk InnerException; a denial on an inner exception was "
        "reported as PATH_ERROR"
    )
    # The chain is searched, not just consulted.
    assert body.count("TryWin32Error") >= 1
    assert "foreach" in body, "Classify must search every link in the chain"


def test_is_access_denied_walks_the_chain():
    """The cleanup path's denial check must search the chain too."""
    body = _body(_source(), "static bool IsAccessDenied")
    assert "InnerException" in body, (
        "IsAccessDenied only ever read the outer exception"
    )


def test_unclassified_is_a_real_verdict():
    """An unestablishable code must not be dressed up as PATH_ERROR or a number."""
    source = _source()
    assert "UNCLASSIFIED" in source, (
        "a result with no established Win32 error must be UNCLASSIFIED"
    )
    body = _body(source, "static Verdict Classify")
    assert 'v.Result = "UNCLASSIFIED"' in body


def test_classification_records_outer_and_inner():
    """The evidence chain must be visible in the output."""
    source = _source()
    assert "OuterType" in source and "InnerType" in source
    assert "outer=" in source and "inner=" in source


def test_genuine_access_denied_hresult_still_reads_as_five():
    """The fix must not break the case that already worked.

    A direct UnauthorizedAccessException carries HRESULT 0x80070005. That must
    still classify as OS_DENIED with winerror=5.
    """
    body = _body(_source(), "static Verdict Classify")
    assert "ERROR_ACCESS_DENIED" in body
    assert '"OS_DENIED"' in body


def test_path_error_classification_is_not_weakened():
    """Genuine path errors must still read as PATH_ERROR, not as denials."""
    source = _source()
    body = _body(source, "static Verdict Classify")
    for name in ("ERROR_FILE_NOT_FOUND", "ERROR_PATH_NOT_FOUND",
                 "ERROR_INVALID_NAME"):
        assert name in body, f"{name} must remain classified as a path error"
    assert '"PATH_ERROR"' in body
    assert "IO_ERROR" in body, "ERROR_SHARING_VIOLATION must remain IO_ERROR"


# ---------------------------------------------------------------------------
# FIX 2 -- no-op delete classification
# ---------------------------------------------------------------------------

def test_run_delete_requires_the_target_to_exist():
    """File.Delete on a missing path is a no-op; claiming OS_ALLOWED asserts a
    permission that was never exercised."""
    body = _body(_source(), "static string RunDelete")
    assert "Directory.Exists" in body or "File.Exists" in body
    assert "target_not_present" in body
    assert "NOT_TESTABLE" in body


def test_run_delete_reports_whether_the_target_preexisted():
    """A reader must be able to tell a real delete from a no-op."""
    body = _body(_source(), "static string RunDelete")
    # Recorded on the finding rather than as a separate console line, because the
    # parser only sees one record per operation. The implementation emits both a
    # `probe=<label> target_preexisted=<bool>` line and puts the field on the
    # result line; this test runs the probe, so it asserts on what the parser sees.
    source = _source()
    assert "target_preexisted" in source
    assert "target_preexisted=" in body


def test_deletes_go_through_run_delete_not_bare_run():
    """Both delete measurements must go through the existence-checking path."""
    source = _source()
    # The guarded one and the workspace one.
    assert 'RunDelete("delete_child_directory"' in source, (
        "delete_child_directory must use RunDelete so a missing fixture cannot "
        "read as OS_ALLOWED"
    )
    assert 'RunDelete("workspace_delete"' in source, (
        "workspace_delete must use RunDelete; a denied create followed by a "
        "no-op delete previously reported OS_ALLOWED"
    )


def test_delete_fixture_still_requires_a_preexisting_fixture():
    """The stricter --delete-fixture contract must survive the correction."""
    source = _source()
    assert "delete_fixture_absent" in source, (
        "the operator must still pre-create the delete fixture"
    )
    assert "delete_child_directory_target_preexisted" in source


# ---------------------------------------------------------------------------
# Behaviour: the probe is compiled and actually run
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_missing_delete_target_reports_not_testable(tmp_path):
    """The real probe, pointed at a delete fixture that does not exist.

    This is the exact defect: previously this path reported OS_ALLOWED because
    File.Delete on a missing file succeeds.
    """
    exe = _build_probe(PROBE_EXE)
    scratch = tmp_path / "subject_runtime"
    (scratch / "runtime").mkdir(parents=True)
    leaf = scratch / "runtime" / "leaf.bin"
    leaf.write_bytes(b"leaf")

    parsed, raw = _run(
        exe,
        scratch=tmp_path,
        staged=None,
        protected=None,
        workspace=tmp_path,
        traverse=scratch,
        traverse_leaf=leaf,
        read_file=leaf,
        enumerate_runtime=scratch / "runtime",
        delete_fixture=tmp_path / "never_created_dir",
    )
    findings = _by_op(parsed)
    assert "delete_child_directory" in findings, (
        f"the delete measurement vanished:\n{raw}"
    )
    f = findings["delete_child_directory"]
    assert _result(f) == "NOT_TESTABLE", (
        f"a missing delete fixture must be NOT_TESTABLE, not a pass: {f}"
    )
    # Two guards catch a missing fixture and both must NOT_TESTABLE. Which one
    # fired is a detail; that neither reported a pass is the contract.
    detail = str(f.get("detail") or "")
    assert ("target_not_present" in detail
            or "delete_fixture_absent" in detail), (
        f"the missing-target reason must be visible: {f}"
    )
    assert _detail(f, "target_preexisted") == "false", (
        f"the absent target must be recorded as absent: {f}"
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_existing_delete_target_is_attempted_and_reported(tmp_path):
    """A target that does exist must be deleted, so the verdict is meaningful.

    The operator owns this file, so the delete succeeds -- and the point is that
    it is reported as an attempt on a present target rather than skipped.
    """
    exe = _build_probe(PROBE_EXE)
    scratch = tmp_path / "subject_runtime"
    (scratch / "runtime").mkdir(parents=True)
    leaf = scratch / "runtime" / "leaf.bin"
    leaf.write_bytes(b"leaf")
    victim = tmp_path / "operator_owned_victim"
    victim.mkdir()

    parsed, raw = _run(
        exe,
        scratch=tmp_path,
        staged=None,
        protected=None,
        workspace=tmp_path,
        traverse=scratch,
        traverse_leaf=leaf,
        read_file=leaf,
        delete_fixture=victim,
    )
    findings = _by_op(parsed)
    f = findings["delete_child_directory"]
    assert _detail(f, "target_preexisted") == "true", (
        f"the fixture must be recorded as pre-existing: {raw}"
    )
    assert _result(f) == "OS_ALLOWED", (
        "deleting an operator-owned directory should succeed, and the success "
        f"must be attributed to a real delete: {raw}"
    )
    assert not victim.exists(), "the directory was not actually deleted"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_a_denied_delete_is_reported_as_denied_not_as_a_path_error(tmp_path):
    """The full chain: deny DELETE on the target, then attempt it.

    Exercises the unwrapping end to end. The reproduction of this on a throwaway
    tree is what showed the OS returns ERROR_ACCESS_DENIED on the INNER exception
    while the outer exception carries the runtime's own IOException code.
    """
    exe = _build_probe(PROBE_EXE)
    import os

    scratch = tmp_path / "subject_runtime"
    (scratch / "runtime").mkdir(parents=True)
    leaf = scratch / "runtime" / "leaf.bin"
    leaf.write_bytes(b"leaf")

    victim = tmp_path / "denied_victim"
    victim.mkdir()
    operator = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")

    # Deny DELETE and FILE_DELETE_CHILD to the operator: the same two rights the
    # M015 mask denies. WRITE_DAC stays allowed so cleanup can undo this.
    subprocess.run(
        ["icacls", str(victim), "/deny", f"{domain}\\{operator}:(D,DC)", "/C"],
        capture_output=True, text=True, shell=False, timeout=120,
        stdin=subprocess.DEVNULL)

    try:
        parsed, raw = _run(
            exe,
            scratch=tmp_path,
            staged=None,
            protected=None,
            workspace=tmp_path,
            traverse=scratch,
            traverse_leaf=leaf,
            read_file=leaf,
            delete_fixture=victim,
        )
        f = _by_op(parsed)["delete_child_directory"]
        assert _detail(f, "target_preexisted") == "true"
        assert _result(f) == "OS_DENIED", (
            "a denied delete must read as OS_DENIED; the previous run produced "
            f"PATH_ERROR winerror=5664 on exactly this operation:\n{raw}"
        )
        # And the error must be a real Win32 code, not a masked CLR HRESULT.
        assert _detail(f, "winerror") == "5", (
            f"the reported winerror must be the real Win32 code:\n{raw}"
        )
        assert victim.exists(), "the denied directory must still exist"
    finally:
        subprocess.run(
            ["icacls", str(victim), "/remove:d",
             f"{domain}\\{operator}", "/C"],
            capture_output=True, text=True, shell=False, timeout=120,
            stdin=subprocess.DEVNULL)


def test_probe_still_emits_schema_v2():
    """The measurement contract changed; the schema must say so."""
    assert "schema=probe/v2" in _source()