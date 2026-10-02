"""Regression tests for the first real BABY_AI_TEST boundary run.

The first subject run produced 21 results and then crashed. Four defects were
found in the harness by reading that output against the source, and each is now
locked in by a test:

1. ``read_disposable_file=OS_ALLOWED`` while every staging operation was denied.
   The read target was ``baby_workspace\\m016_probe.exe`` -- the writable
   experimentation area -- not anything inside ``subject_runtime``. The result
   was true but proved nothing about the boundary, and nothing in the output said
   which file it referred to.
2. ``delete_child_directory=OS_ALLOWED`` was a no-op reported as success. The
   directory had never been created (creation was denied), and the delete was
   guarded by ``if (Directory.Exists(...))`` *inside* the lambda that counted
   success.
3. ``restore_acl_target_attributes=ERROR`` was correct behaviour reported as a
   fault: the subject holds no FILE_WRITE_ATTRIBUTES, which is the point.
4. The probe crashed in ``Directory.GetFiles(runtime)`` during cleanup, because
   ``Directory.GetFiles`` reports access-denied as a plain ``IOException`` and the
   probe only caught ``UnauthorizedAccessException``.

None of these tests runs anything as BABY_AI_TEST, and none weakens an ACL to
manufacture a denial. Where a test needs a real refusal it uses a path that
genuinely does not exist, and asserts the *classification* rather than faking a
permission result.
"""

from __future__ import annotations

import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from foundation.boundary_test import Outcome, build_probe_argv, parse_probe_output

REPO = Path(__file__).resolve().parents[1]
PROBE_SOURCE = REPO / "foundation" / "subject_probe.cs"
PROBE_EXE = REPO / "baby_workspace" / "m016_probe.exe"
STAGING = REPO / "subject_runtime"


@pytest.fixture
def probe() -> Path:
    """Build the probe by path; skip if Add-Type is unavailable."""
    if not PROBE_EXE.is_file():
        PROBE_EXE.parent.mkdir(parents=True, exist_ok=True)
        cs = PROBE_EXE.with_suffix(".cs")
        cs.write_text(PROBE_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
        script = (
            "$ErrorActionPreference='Stop'; "
            f"Add-Type -Path '{cs}' "
            f"-OutputAssembly '{PROBE_EXE}' -OutputType ConsoleApplication"
        )
        built = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, shell=False, timeout=300)
        if built.returncode != 0 or not PROBE_EXE.is_file():
            pytest.skip("Add-Type could not compile the probe")
    return PROBE_EXE


@pytest.fixture
def owned_fixture():
    runtime = STAGING / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    path = runtime / f"m016_subjecttest_{uuid.uuid4().hex[:12]}.exe"
    path.write_bytes(b"")
    yield path
    if path.exists():
        path.chmod(0o666)
        subprocess.run(["attrib", "-R", str(path)], capture_output=True)
        path.unlink(missing_ok=True)


def run_probe(probe: Path, **kw) -> tuple[dict, str]:
    argv = build_probe_argv(**kw)
    result = subprocess.run([str(probe), *argv], capture_output=True, text=True,
                            shell=False, timeout=180)
    return parse_probe_output(result.stdout), result.stdout


# ---------------------------------------------------------------------------
# 1. The read test must name its target
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_read_target_can_be_the_writable_workspace(probe: Path,
                                                   owned_fixture: Path):
    """The harness permits the workspace target, but labels it as outside.

    The point is not to forbid it -- an operator may legitimately want to check the
    workspace -- but to make the output say which regime the result belongs to, so
    a workspace read is never read as staging evidence.
    """
    parsed, raw = run_probe(
        probe,
        scratch=STAGING / "config",
        staged=owned_fixture,
        workspace=REPO / "baby_workspace",
        read_file=REPO / "baby_workspace" / "m016_probe.exe",
        staging_root=STAGING / "runtime",
    )
    assert "read_file_in_staging=False" in raw, (
        "a read outside the staging root must be reported as such")
    echo = [l for l in raw.splitlines() if l.startswith("read_file_target=")]
    assert echo and "baby_workspace" in echo[0], echo


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_read_target_inside_subject_runtime_is_flagged(probe: Path,
                                                       owned_fixture: Path):
    """The boundary read, with the staging root supplied explicitly."""
    read_fixture = STAGING / "runtime" / "m016_read_fixture_check.exe"
    read_fixture.write_bytes(b"payload\n")
    try:
        parsed, raw = run_probe(
            probe,
            scratch=STAGING / "config",
            staged=owned_fixture,
            workspace=REPO / "baby_workspace",
            read_file=read_fixture,
            staging_root=STAGING / "runtime",
        )
        assert "read_file_in_staging=True" in raw, raw[-600:]
        findings = {f["operation"]: f for f in parsed["findings"]}
        assert findings["read_disposable_file"]["outcome"] == \
            Outcome.OS_ALLOWED.value
    finally:
        read_fixture.unlink(missing_ok=True)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_missing_read_target_is_not_testable(probe: Path, owned_fixture: Path):
    """A read that cannot reach its target must not claim success."""
    parsed, raw = run_probe(
        probe,
        scratch=STAGING / "config",
        staged=owned_fixture,
        workspace=REPO / "baby_workspace",
        read_file=STAGING / "runtime" / "m016_no_such_read_file.exe",
        staging_root=STAGING / "runtime",
    )
    findings = {f["operation"]: f for f in parsed["findings"]}
    read = findings["read_disposable_file"]
    assert read["outcome"] != Outcome.OS_ALLOWED.value, read
    assert read["outcome"] in {
        Outcome.NOT_TESTABLE.value, Outcome.PATH_ERROR.value}, read


def test_read_inside_staging_helper_is_not_a_prefix_match():
    """A sibling directory sharing a name prefix must not count as inside."""
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    assert "static bool IsUnder(string path, string root)" in source
    # The separator check is what distinguishes a real subdirectory from
    # "subject_runtime_evil", which a plain StartsWith would accept.
    assert "a[b.Length] == '\\\\'" in source or 'a[b.Length]' in source, (
        "IsUnder must require a separator after the root, not merely a prefix match")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_probe_reports_the_bytes_it_actually_read(probe: Path, owned_fixture: Path):
    """The observed size proves the read reached the file rather than a guess."""
    target = REPO / "baby_workspace" / "m016_probe.exe"
    parsed, raw = run_probe(
        probe,
        scratch=STAGING / "config",
        staged=owned_fixture,
        workspace=REPO / "baby_workspace",
        read_file=target,
    )
    observed = [l for l in raw.splitlines() if l.startswith("read_file_bytes_observed=")]
    assert observed, "no byte count reported"
    reported = int(observed[0].split("=", 1)[1])
    assert reported == target.stat().st_size, (reported, target.stat().st_size)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_read_inside_staging_is_reachable_for_the_operator(probe: Path,
                                                           owned_fixture: Path):
    """The boundary read we actually care about: a file inside subject_runtime.

    The subject holds R there, so the expected result is OS_ALLOWED for the
    operator and the operation is meaningful for a subject run -- unlike a read
    against the writable workspace.
    """
    parsed, _raw = run_probe(
        probe,
        scratch=STAGING / "config",
        staged=owned_fixture,
        workspace=REPO / "baby_workspace",
        read_file=owned_fixture,
    )
    findings = {f["operation"]: f for f in parsed["findings"]}
    assert findings["read_disposable_file"]["outcome"] == Outcome.OS_ALLOWED.value
    assert findings["read_disposable_file"]["reached_target"] is True


# ---------------------------------------------------------------------------
# 2. A skipped delete must never be reported as a successful delete
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_delete_child_directory_never_reports_allowed_for_a_missing_fixture(
        probe: Path):
    """A delete that never happened must not read OS_ALLOWED.

    The first subject run produced exactly this: creation was denied, the delete
    was guarded by Directory.Exists, the guard skipped the work, and the lambda
    still counted it as a success. The subject appeared able to delete directories
    when it had not tried.

    Exercised with a scratch path that does not exist, so the probe's own fixture
    creation genuinely fails and the delete fixture is genuinely absent.
    """
    missing = STAGING / "config" / "m016_no_such_dir"
    if missing.exists():
        missing.rmdir()          # left by an earlier failed run
    assert not missing.exists(), "precondition: the scratch path must be absent"
    parsed, raw = run_probe(
        probe,
        scratch=missing,
        staged=None,
        workspace=None,
    )
    findings = {f["operation"]: f for f in parsed["findings"]}
    delete = findings.get("delete_child_directory")
    assert delete is not None, "delete_child_directory was not reported at all"
    assert delete["outcome"] != Outcome.OS_ALLOWED.value, (
        f"a delete that could not have happened reported success: {delete}")
    assert delete["outcome"] in {
        Outcome.NOT_TESTABLE.value, Outcome.PATH_ERROR.value}, delete
    # The create must also have failed to prepare the fixture.
    create = findings["create_child_directory"]
    assert create["outcome"] != Outcome.OS_ALLOWED.value, create
    if missing.exists():
        missing.rmdir()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_probe_source_has_no_silent_exists_guard_in_the_delete(probe: Path):
    """A static guard, so the defect cannot come back unnoticed."""
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    match = re.search(
        r'RunGuarded\("delete_child_directory".*?\}\);', source, re.S)
    if match:
        assert "if (Directory.Exists" not in match.group(0), (
            "the delete body hides a skip behind Directory.Exists, which makes a "
            "no-op indistinguishable from a successful deletion")
    assert "fixture_absent" in source, (
        "the absent-fixture path must be reported explicitly")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_child_create_and_delete_use_distinct_fixtures(probe: Path,
                                                       owned_fixture: Path):
    """Two fixtures, and the delete fixture is the OPERATOR's, not the probe's."""
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    assert "m016_child_create_dir" in source
    assert "--delete-fixture=" in source, (
        "the delete target must be supplied by the operator")
    assert 'delete_child_directory_target_preexisted=' in source, (
        "the probe must state whether the delete fixture existed beforehand")
    assert 'create_child_directory_target=' in source
    assert 'delete_child_directory_target=' in source


def test_delete_fixture_is_never_created_by_the_probe(probe: Path,
                                                       owned_fixture: Path):
    """A probe that creates the directory it is about to delete proves nothing."""
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    # The only Directory.CreateDirectory for the delete path must be absent: the
    # delete target arrives via --delete-fixture and is only ever inspected.
    assert "prepare_delete_child_fixture" not in source, (
        "the probe must not create the fixture it intends to delete")
    delete_block = source[source.find("delete_child_directory_target="):]
    assert "Directory.CreateDirectory" not in delete_block.split(
        "create_child_directory_target=")[0], (
        "the delete branch must not create its own target")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_absent_delete_fixture_is_not_testable(probe: Path, owned_fixture: Path):
    """No fixture means no test, and it must say so."""
    parsed, raw = run_probe(
        probe,
        scratch=STAGING / "config",
        staged=owned_fixture,
        workspace=REPO / "baby_workspace",
        delete_fixture=STAGING / "config" / "m016_absent_delete_target",
    )
    findings = {f["operation"]: f for f in parsed["findings"]}
    delete = findings.get("delete_child_directory")
    assert delete is not None, "delete_child_directory was not reported at all"
    assert delete["outcome"] == Outcome.NOT_TESTABLE.value
    assert "delete_fixture_absent" in delete["detail"], delete
    assert "delete_child_directory_target_preexisted=False" in raw


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_no_delete_fixture_supplied_is_not_testable(probe: Path,
                                                    owned_fixture: Path):
    """Omitting the option must be reported, not silently treated as a pass."""
    parsed, raw = run_probe(
        probe,
        scratch=STAGING / "config",
        staged=owned_fixture,
        workspace=REPO / "baby_workspace",
    )
    findings = {f["operation"]: f for f in parsed["findings"]}
    delete = findings["delete_child_directory"]
    assert delete["outcome"] == Outcome.NOT_TESTABLE.value
    assert "no_delete_fixture_supplied" in delete["detail"], delete
    assert "delete_child_directory_target=<none>" in raw


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_preexisting_delete_fixture_is_deleted(probe: Path, owned_fixture: Path):
    """The positive control: a real directory really goes away."""
    import shutil
    target = STAGING / "config" / "m016_delete_fixture_control"
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    (target / "sentinel.txt").write_bytes(b"x")
    assert target.is_dir(), "precondition"
    try:
        parsed, raw = run_probe(
            probe,
            scratch=STAGING / "config",
            staged=owned_fixture,
            workspace=REPO / "baby_workspace",
            delete_fixture=target,
        )
        findings = {f["operation"]: f for f in parsed["findings"]}
        assert "delete_child_directory_target_preexisted=True" in raw
        assert findings["delete_child_directory"]["outcome"] == \
            Outcome.OS_ALLOWED.value, findings["delete_child_directory"]
        assert not target.exists(), "the fixture should have been removed"
    finally:
        shutil.rmtree(target, ignore_errors=True)


def test_delete_uses_a_recursive_delete(probe: Path):
    """A non-recursive delete of a non-empty fixture returns winerror 145.

    That is a PATH_ERROR about the fixture's contents and says nothing about
    whether the account may delete the directory -- it was the first thing the
    operator control caught.
    """
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    # The delete moved into RunDelete when the no-op classification was corrected:
    # it now asserts the fixture exists, then deletes recursively. The recursion
    # requirement is unchanged, so the assertion follows the call.
    assert "RunDelete(\"delete_child_directory\"" in source, (
        "the delete must go through RunDelete so a missing fixture cannot be "
        "reported as OS_ALLOWED")
    assert 'if (expectDirectory) Directory.Delete(path, true);' in source, (
        "the delete must be recursive so a fixture holding a sentinel file can be "
        "removed, and the result reflects the delete right rather than the "
        "fixture's emptiness")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_delete_child_directory_is_allowed_when_its_fixture_exists(
        probe: Path, owned_fixture: Path):
    """The positive control for the fixed operation."""
    import shutil
    target = STAGING / "config" / "m016_delete_positive_control"
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    try:
        parsed, raw = run_probe(
            probe,
            scratch=STAGING / "config",
            staged=owned_fixture,
            workspace=REPO / "baby_workspace",
            delete_fixture=target,
        )
        findings = {f["operation"]: f for f in parsed["findings"]}
        assert findings["create_child_directory"]["outcome"] == \
            Outcome.OS_ALLOWED.value
        assert findings["delete_child_directory"]["outcome"] == \
            Outcome.OS_ALLOWED.value, findings["delete_child_directory"]
    finally:
        shutil.rmtree(target, ignore_errors=True)


# ---------------------------------------------------------------------------
# 3. Attribute restoration: a subject refusal is correct behaviour
# ---------------------------------------------------------------------------

def test_probe_source_labels_attribute_restore_refusal_as_expected():
    """The subject cannot restore attributes, and that is the boundary working."""
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    assert "EXPECTED_OS_DENIED" in source
    assert "lacks FILE_WRITE_ATTRIBUTES" in source, (
        "the probe must explain that the refusal is the intended boundary, not a "
        "harness fault")


def test_probe_never_asks_for_elevated_rights():
    """Restoration must never be escalated to make cleanup succeed."""
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    for forbidden in ("AdjustTokenPrivileges", "SetSecurityDescriptorDacl",
                      "TakeOwnership", "runas"):
        assert forbidden not in source, (
            f"the probe must not attempt {forbidden}")


# ---------------------------------------------------------------------------
# 4. A denial must never become an unhandled exception
# ---------------------------------------------------------------------------

def test_probe_source_uses_no_csharp6_exception_filters():
    """Add-Type compiles with the C# 5 compiler inside PowerShell 5.1.

    `catch (...) when (...)` does not compile there, and the failure looks like a
    syntax error rather than a language-version problem.
    """
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    assert not re.search(r"catch \([^)]*\) when ", source), (
        "exception filters require C# 6; Add-Type here uses C# 5")


def test_run_helper_handles_both_denial_shapes():
    """Directory.GetFiles reports a denial as IOException, not UnauthorizedAccessException.

    Run() no longer catches by exception TYPE. A subject run reported
    `delete_child_directory result=PATH_ERROR winerror=5664`, and 5664 was
    0x80131620 & 0xFFFF -- the runtime's own IOException code, masked into a
    number shaped like a Win32 error. The denial was real; only the classification
    lost it. Classification now goes through Classify(), which walks the whole
    exception chain and accepts a Win32 code only from a genuine
    HRESULT_FROM_WIN32 value.
    """
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    body = source[source.find("static string Run(string label"):]
    body = body[: body.find("\n    }")]
    # The verdict strings live in Classify() now; Run() prints whatever it returns.
    # What Run must still do is delegate rather than classify by type.
    assert "Classify" in body, (
        "Run must classify through Classify so a wrapped or runtime-raised "
        "exception cannot hide a denial")
    assert "catch (UnauthorizedAccessException)" not in body, (
        "catching by exception type is what missed the wrapped denial; the chain "
        "must be inspected instead")
    assert "static bool TryWin32Error" in source
    assert "0x80070000" in source, (
        "only HRESULT_FROM_WIN32 values (high word 0x8007) may be read as Win32 "
        "errors; masking an arbitrary HRESULT is the original defect")

    classify = source[source.find("static Verdict Classify"):]
    classify = classify[: classify.find("\n    }")]
    for verdict in ("OS_DENIED", "PATH_ERROR", "IO_ERROR", "UNCLASSIFIED"):
        assert verdict in classify, f"{verdict} must be reachable from Classify()"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_probe_never_exits_with_an_unhandled_exception(probe: Path,
                                                       owned_fixture: Path):
    """The operator run must complete cleanly.

    The subject run recorded all 21 results and then died in cleanup. The results
    survived in the output file, but the process exit and the missing cleanup
    report are both evidence gaps.
    """
    result = subprocess.run(
        [str(probe), *build_probe_argv(
            scratch=STAGING / "config",
            staged=owned_fixture,
            workspace=REPO / "baby_workspace",
        )],
        capture_output=True, text=True, shell=False, timeout=180)
    assert "Unhandled Exception" not in result.stdout
    assert "Unhandled Exception" not in result.stderr
    # The exit code is the count of allowed operations, a positive-capable value by
    # design, so it is NOT an error signal. What matters is that the process
    # completed its report rather than dying partway through.
    assert "exit_code=" in result.stdout, result.stdout[-400:]
    assert "cleanup_state=" in result.stdout, result.stdout[-400:]


# ---------------------------------------------------------------------------
# 5. Cleanup must not require enumerating a directory the account cannot list
# ---------------------------------------------------------------------------

def test_probe_source_guards_the_cleanup_enumeration():
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    index = source.find("cleanup_enumerate_owned_copies")
    assert index > 0, "the cleanup enumeration is not reported"
    window = source[max(0, index - 1000): index + 600]
    assert "CLEANUP_NOT_PERMITTED" in window
    assert "IsAccessDenied" in window
    assert "operator-side cleanup required" in window, (
        "the probe must state that an operator has to finish the cleanup")


def test_probe_source_does_not_enumerate_outside_a_try():
    """Every enumeration site must be inside a try or a guarded helper."""
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    for match in re.finditer(
            r"Directory\.Get(FileSystemEntries|Files|Directories)\(", source):
        lineno = source[: match.start()].count("\n") + 1
        window = source[max(0, match.start() - 500): match.start()]
        guarded = any(h in window for h in ("RunGuarded(", "Run(", "try"))
        assert guarded, (
            f"line {lineno}: enumeration is not inside a try or a guarded helper")


def test_probe_reports_cleanup_outcome_separately(probe: Path, owned_fixture: Path):
    """Cleanup state is reported whether or not the account may perform it."""
    parsed, raw = run_probe(
        probe,
        scratch=STAGING / "config",
        staged=owned_fixture,
        workspace=REPO / "baby_workspace",
    )
    for key in ("cleanup_state", "cleanup_owned_copies_failed",
                "cleanup_owned_copies_removed", "cleanup_operator_followup"):
        assert key in parsed["identity"], f"{key} missing from the report"
    assert parsed["identity"]["cleanup_owned_copies_failed"] == "0"
    assert parsed["identity"]["cleanup_state"] == "CLEAN"


def test_cleanup_does_not_delete_files_it_did_not_create(owned_fixture: Path):
    """Ownership still holds after the cleanup changes."""
    bystander = owned_fixture.parent / "unrelated_keep.bin"
    bystander.write_bytes(b"keep")
    lookalike = owned_fixture.parent / "m016_copy_someothertoken_mod"
    lookalike.write_bytes(b"not mine")
    try:
        run_probe(
            PROBE_EXE if PROBE_EXE.is_file() else _build(PROBE_EXE),
            scratch=STAGING / "config",
            staged=owned_fixture,
            workspace=REPO / "baby_workspace",
        )
        assert bystander.exists(), "cleanup deleted an unrelated file"
        assert lookalike.exists(), "cleanup matched another run's token"
    finally:
        bystander.unlink(missing_ok=True)
        lookalike.unlink(missing_ok=True)


def _build(exe: Path) -> Path:
    exe.parent.mkdir(parents=True, exist_ok=True)
    cs = exe.with_suffix(".cs")
    cs.write_text(PROBE_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
    script = (
        "$ErrorActionPreference='Stop'; "
        f"Add-Type -Path '{cs}' -OutputAssembly '{exe}' -OutputType ConsoleApplication"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   capture_output=True, text=True, shell=False, timeout=300)
    return exe


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

def test_m015_boundary_untouched():
    from foundation.staging import verify_boundary

    report = verify_boundary()
    assert report["status"] == "STAGING_VERIFIED"
    assert report["inherited_modify_absent_everywhere"] is True
    assert report["subject_rights_exact_everywhere"] is True


def test_m005_evidence_intact():
    from foundation.isolation import protected_evidence_digests

    digests = protected_evidence_digests()
    assert all(not v.startswith("UNREADABLE") for v in digests.values())


def test_no_runtime_or_model_staged():
    """Empty disposable fixtures only -- no program, no model.

    A fixture may hold bytes (the read fixture carries payload so a byte count is
    observable), so size is no longer the test; the name is. Everything permitted
    here is an m016_ artefact created and removed by the harness or the operator.
    """
    assert not list(REPO.rglob("*.gguf"))
    for item in (STAGING / "runtime").iterdir():
        assert item.name.startswith("m016_"), \
            f"unexpected artefact in the staging tree: {item.name}"
    for name in ("model", "config"):
        for item in (STAGING / name).iterdir():
            assert item.name.startswith("m016_"), \
                f"unexpected artefact in {name}: {item.name}"


def test_no_birth():
    assert not (REPO / "human_control" / "birth_records" / "BIRTH.json").exists()