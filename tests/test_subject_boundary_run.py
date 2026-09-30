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
def test_probe_echoes_the_read_target(probe: Path, owned_fixture: Path):
    """A read result is meaningless without the path that produced it.

    The first subject run reported read_disposable_file=OS_ALLOWED against a file
    in the writable workspace while every staging operation was denied. Nothing in
    the output said so, and the result was easy to read as evidence that the
    subject could read inside the boundary.
    """
    parsed, raw = run_probe(
        probe,
        scratch=STAGING / "config",
        staged=owned_fixture,
        workspace=REPO / "baby_workspace",
        read_file=REPO / "baby_workspace" / "m016_probe.exe",
    )
    echo = [l for l in raw.splitlines() if l.startswith("read_file_target=")]
    assert echo, "the probe did not echo its read target"
    assert "baby_workspace" in echo[0], echo[0]


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
    """Two names, so the create cannot consume the delete's target."""
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    assert "m016_child_create_dir" in source
    assert "m016_child_delete_dir" in source
    assert 'delete_child_fixture_present=' in source, (
        "the probe must state whether its delete fixture was created")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_delete_child_directory_is_allowed_when_its_fixture_exists(
        probe: Path, owned_fixture: Path):
    """The positive control for the fixed operation."""
    parsed, _raw = run_probe(
        probe,
        scratch=STAGING / "config",
        staged=owned_fixture,
        workspace=REPO / "baby_workspace",
    )
    findings = {f["operation"]: f for f in parsed["findings"]}
    assert findings["create_child_directory"]["outcome"] == Outcome.OS_ALLOWED.value
    assert findings["delete_child_directory"]["outcome"] == Outcome.OS_ALLOWED.value


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
    """Directory.GetFiles reports a denial as IOException, not UnauthorizedAccessException."""
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    body = source[source.find("static string Run(string label"):]
    body = body[: body.find("\n    }")]
    assert "UnauthorizedAccessException" in body
    assert "OS_DENIED" in body
    assert "HResultCode" in body, (
        "the IOException branch must inspect the Win32 code, since that is how a "
        "denied enumeration arrives")


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
    assert not list(REPO.rglob("*.gguf"))
    for item in (STAGING / "runtime").iterdir():
        assert item.stat().st_size == 0 or item.name.startswith("m016_"), item


def test_no_birth():
    assert not (REPO / "human_control" / "birth_records" / "BIRTH.json").exists()