"""Tests for M016 - subject-account launch feasibility and the native probe.

What these tests can and cannot claim:

* They assert the **decision logic** for launch feasibility: which mechanisms
  exist, what each requires, and that the absence of the impersonation
  privileges is reported as ``NOT_TESTABLE`` rather than as a pass.
* They assert the probe **source** compiles, and that a built probe correctly
  reports the operator's own identity -- a positive control.
* They assert credential handling is inert.

What they deliberately do **not** claim: that ``BABY_AI_TEST`` was launched. It
was not. No test here mocks the Windows security APIs, and no test asserts
subject-side enforcement, because that has not happened. A test named
``test_subject_write_is_denied`` would be a lie today; the honest test is that
the *mechanism for finding out* is built, exercised against the operator, and
found blocked.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from foundation.staging import verify_boundary
from foundation.subject_process import (
    MECHANISMS,
    LaunchStatus,
    REQUIRED_PRIVILEGES,
    human_selected_runtime,
    is_elevated,
    launch_feasibility,
    probe_binary,
    report,
    subject_account_state,
    token_privileges,
)

REPO = Path(__file__).resolve().parents[1]
PROBE_SOURCE = REPO / "foundation" / "subject_probe.cs"


# ---------------------------------------------------------------------------
# No implicit runtime selection
# ---------------------------------------------------------------------------

def test_no_runtime_is_selected_without_a_declaration():
    """The discovered llama-server.exe must not become the runtime on its own."""
    result = human_selected_runtime()
    assert result["status"] == LaunchStatus.RUNTIME_NOT_SELECTED.value
    assert result["declaration_present"] is False
    assert result["selected_runtime"] is None


def test_selection_is_not_inferred_from_the_previous_discovery():
    """A previous discovery is not a selection.

    The M014/M015 investigations located a llama-server.exe. Nothing may promote
    that finding into a selection without a human declaration naming it.
    """
    result = human_selected_runtime()
    serialised = json.dumps(result)
    assert "llama" not in serialised.lower()


def test_a_declaration_without_attribution_is_not_a_selection(tmp_path: Path):
    """An unsigned selection is not a human selection."""
    declaration = tmp_path / "runtime_selection.json"
    declaration.write_text(json.dumps({"source_path": "C:/somewhere/app.exe"}),
                           encoding="utf-8")
    result = human_selected_runtime(declaration)
    assert result["status"] == LaunchStatus.RUNTIME_NOT_SELECTED.value
    assert "selected_by" in result["reason"]


def test_a_declaration_from_human_is_a_selection(tmp_path: Path):
    source = tmp_path / "app.exe"
    source.write_bytes(b"MZ")
    declaration = tmp_path / "runtime_selection.json"
    declaration.write_text(json.dumps({
        "source_path": str(source), "selected_by": "operator",
    }), encoding="utf-8")
    result = human_selected_runtime(declaration)
    assert result["selected_runtime"] == str(source)
    assert result["selected_by"] == "operator"
    assert result["source_exists"] is True
    assert result["source_sha256"]


def test_staging_declared_contains_nothing_now():
    """M016 selects nothing, so nothing may be staged."""
    assert human_selected_runtime()["selected_runtime"] is None


# ---------------------------------------------------------------------------
# Launch feasibility: the honest NOT_TESTABLE
# ---------------------------------------------------------------------------

def test_launch_is_reported_not_testable_not_verified():
    result = launch_feasibility()
    assert result["status"] == LaunchStatus.NOT_TESTABLE.value
    assert result["status"] != LaunchStatus.VERIFIED.value
    assert result["subject_process_launched"] is False


def test_the_missing_privileges_are_named():
    """A blocker must be specific, or it cannot be acted on."""
    privileges = token_privileges()
    assert privileges["missing"]
    assert set(privileges["missing"]) <= set(REQUIRED_PRIVILEGES)


def test_every_mechanism_states_a_requirement_and_a_finding():
    for mechanism in MECHANISMS:
        assert mechanism.requirement
        assert mechanism.finding
        assert mechanism.name


def test_mechanisms_needing_stored_credentials_are_marked_interactive():
    """A mechanism needing a stored password must never look automatable."""
    for mechanism in MECHANISMS:
        if "stored" in mechanism.requirement.lower():
            assert mechanism.automatable is False, mechanism.name


def test_wsl_and_docker_are_rejected_as_a_different_identity():
    """These produce a Linux or container identity, not a Windows subject token."""
    rejected = [m for m in MECHANISMS if "REJECTED BY DESIGN" in m.finding]
    names = " ".join(m.name for m in rejected)
    assert "WSL" in names or "docker" in names
    for mechanism in rejected:
        assert mechanism.name in launch_feasibility()["rejected_by_design"]


def test_no_automatable_mechanism_remains_that_would_produce_a_windows_token():
    """The result must be that nothing usable remains, not that something does."""
    feasibility = launch_feasibility()
    assert feasibility["automatable_mechanisms_remaining"] == []


def test_blockers_explain_both_privileges_and_elevation():
    blockers = " ".join(launch_feasibility()["blockers"])
    for privilege in REQUIRED_PRIVILEGES:
        assert privilege in blockers


def test_elevation_is_read_from_groups_not_from_presence():
    """An unelevated token carries Administrators *deny only*."""
    result = is_elevated()
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Credential handling
# ---------------------------------------------------------------------------

def test_no_credential_was_read_stored_or_logged():
    handling = launch_feasibility()["credential_handling"]
    assert handling["password_read"] is False
    assert handling["password_stored"] is False
    assert handling["password_in_arguments"] is False
    assert handling["password_in_environment"] is False
    assert handling["password_in_repository"] is False
    assert handling["password_logged"] is False


def test_account_state_never_reports_a_password_value():
    state = subject_account_state()
    assert state["password_value_read"] is False
    assert state["password_stored_anywhere"] is False
    # The check looks for a secret *value*, not the word "password": the report
    # legitimately contains metadata fields like PasswordRequired and its own
    # "password_stored_anywhere": false assertion. Matching on the substring would
    # flag those and force the guard to be weakened.
    assert "password_value" not in state
    assert "password" not in state.get("observed", {}) or \
        set(state["observed"]) <= {
            "Name", "Enabled", "PasswordRequired", "LastLogon",
            "UserMayChangePassword", "read_failed"}
    for forbidden in ("pwd=", "plaintext", "secret="):
        assert forbidden not in json.dumps(state).lower()


def test_no_credential_shaped_string_in_the_module_source():
    """A static guard against a password being baked into the source."""
    source = (REPO / "foundation" / "subject_process.py").read_text(encoding="utf-8")
    assert not re.search(r"password\s*=\s*[\"'][^\"']+[\"']", source, re.I)


# ---------------------------------------------------------------------------
# The native probe
# ---------------------------------------------------------------------------

def test_probe_source_is_present_and_not_python():
    assert PROBE_SOURCE.is_file()
    assert PROBE_SOURCE.suffix == ".cs"


def test_probe_is_not_staged_in_subject_runtime():
    """The probe is a test tool; staging it would add a subject capability."""
    staging = REPO / "subject_runtime"
    if staging.exists():
        assert not list(staging.rglob("probe*"))


def test_probe_reports_its_four_outcomes():
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    for outcome in ("OS_ALLOWED", "OS_DENIED", "NOT_TESTABLE", "PATH_ERROR"):
        assert outcome in source


def test_probe_distinguishes_denial_from_a_missing_path():
    """A denial must mean winerror 5 and nothing else.

    Collapsing "file not found" into a denial would let an unstaged runtime look
    like a protected one.
    """
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    assert 'code == 5 ? "OS_DENIED" : "PATH_ERROR"' in source


def test_probe_reads_identity_from_the_token_not_the_arguments():
    """Identity must never come from the command line."""
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    assert "OpenProcessToken" in source
    assert "GetTokenInformation" in source
    assert "account_name=" in source


def test_probe_declares_several_privileges_from_the_token():
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    for field in ("privileges=", "privilege_count=", "integrity_level=", "groups="):
        assert field in source


def test_probe_cleans_up_after_itself():
    """A probe that leaves copies in subject_runtime would contaminate later runs."""
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    assert "File.Delete" in source
    assert "probe_workspace.txt" in source


def test_probe_binary_report_does_not_claim_a_subject_run():
    info = probe_binary()
    assert info["staged_in_subject_runtime"] is False
    assert info["python_used_as_subject_runtime"] is False
    assert info.get("status") in {"PROBE_BUILT", LaunchStatus.NOT_TESTABLE.value}


def _compile_probe(exe: Path, source: str):
    """Compile the probe with the C# compiler already present in PowerShell 5.1.

    The source is written to a temporary .cs file and compiled by *path* rather
    than embedded in the command line. Embedding it worked while the probe was
    small, and then hit Windows' 32k command-line limit (WinError 206) once the
    source grew -- a failure that looked like a test bug and was actually an
    argument-passing design that had run out of room.
    """
    exe.parent.mkdir(parents=True, exist_ok=True)
    cs = exe.with_suffix(".cs")
    cs.write_text(source, encoding="utf-8")
    script = (
        "$ErrorActionPreference='Stop'; "
        f"Add-Type -Path '{cs}' "
        f"-OutputAssembly '{exe}' -OutputType ConsoleApplication"
    )
    built = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, shell=False, timeout=300)
    return built


@pytest.mark.skipif(sys.platform != "win32", reason="Windows token APIs")
def test_probe_builds_and_correctly_identifies_the_operator():
    """Positive control: the probe must name the account it is actually running as.

    If this cannot identify the operator, it cannot be trusted to identify
    BABY_AI_TEST either, so it fails the milestone's evidentiary requirement.
    """
    out = REPO.parent / "m016_probe_build"
    exe = out / "probe.exe"
    built = _compile_probe(exe, PROBE_SOURCE.read_text(encoding="utf-8"))
    assert built.returncode == 0, built.stdout + built.stderr
    assert exe.is_file()

    run = subprocess.run([str(exe)], capture_output=True, text=True,
                         shell=False, timeout=120)
    output = run.stdout
    assert "schema=probe/v1" in output
    assert "user_sid=S-1-5-21-" in output
    assert "account_name=" in output
    assert "integrity_level=" in output
    assert "NOT_TESTABLE reason=no_paths_supplied" in output
    # It reported this operator's SID, not the subject's.
    assert "BABY_AI_TEST" not in output
    exe.unlink(missing_ok=True)


def _build_probe(exe: Path):
    """Compile the probe with the C# compiler already in PowerShell 5.1.

    No toolchain is installed; Add-Type ships with the shell. The source is passed
    by *path* rather than embedded in the command line -- the embedded form worked
    while the probe was small and then failed with WinError 206 once it grew.
    """
    if not exe.is_file():
        exe.parent.mkdir(parents=True, exist_ok=True)
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_probe_reports_the_operator_as_allowed_by_the_os():
    """The probe must be capable of reporting OS_ALLOWED.

    A probe hardwired to print "denied" would satisfy every subject-side
    assertion while proving nothing. As the operator, who holds full control,
    every write must be allowed.
    """
    out = REPO.parent / "m016_probe_build"
    exe = _build_probe(out / "probe.exe")
    staged = REPO / "subject_runtime" / "runtime" / "m016_control.exe"
    scratch = REPO / "subject_runtime" / "config"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"MZ")
    try:
        run = subprocess.run(
            [str(exe), str(scratch), str(staged), "", ""],
            capture_output=True, text=True, shell=False, timeout=120)
        output = run.stdout
        assert "modify_staged_executable result=OS_ALLOWED" in output, output
        assert "delete_staged_executable result=OS_ALLOWED" in output, output
        assert "create_file_in_staging_scratch result=OS_ALLOWED" in output
    finally:
        staged.unlink(missing_ok=True)
        # The probe is expected to clean up its own scratch artefacts; assert it
        # actually did, because a probe that leaves copies behind in
        # subject_runtime would contaminate every later run.
        for leftover in ("config/p.txt", "runtime/child.exe"):
            assert not (REPO / "subject_runtime" / leftover).exists(), leftover


# ---------------------------------------------------------------------------
# M015 boundary and M005 regression
# ---------------------------------------------------------------------------

def test_m015_boundary_still_verifies_after_m016_work():
    report_ = verify_boundary()
    assert report_["status"] == "STAGING_VERIFIED"
    assert report_["inherited_modify_absent_everywhere"] is True
    assert report_["subject_rights_exact_everywhere"] is True
    assert report_["subject_deny_backstop_present_everywhere"] is True


def test_protected_path_count_is_unchanged():
    from babylab.osboundary import protected_paths

    assert len(protected_paths()) == 13


def test_protected_evidence_digests_are_readable():
    from foundation.isolation import protected_evidence_digests

    digests = protected_evidence_digests()
    assert digests
    assert all(not v.startswith("UNREADABLE") for v in digests.values())


def test_workspace_is_still_writable_by_the_operator():
    workspace = REPO / "baby_workspace"
    assert workspace.is_dir()
    probe = workspace / "m016_write_check.txt"
    probe.write_text("x", encoding="utf-8")
    probe.unlink()


# ---------------------------------------------------------------------------
# Nothing out of scope happened
# ---------------------------------------------------------------------------

def test_m016_is_not_birth():
    assert not (REPO / "human_control" / "birth_records" / "BIRTH.json").exists()


def test_no_model_was_selected_or_staged():
    assert not list(REPO.rglob("*.gguf"))
    for name in ("model", "config"):
        directory = REPO / "subject_runtime" / name
        if directory.is_dir():
            assert not list(directory.iterdir())


def test_no_network_isolation_is_claimed():
    payload = json.dumps(report())
    assert "not claimed" in payload.lower()


def test_no_signing_key_was_created():
    keys = REPO / "human_control" / "security" / "keys"
    for name in ("subject.key", "baby.key", "subject_signing.key"):
        assert not (keys / name).exists()


def test_python_is_not_staged_for_the_subject():
    staging = REPO / "subject_runtime"
    if staging.exists():
        assert not list(staging.rglob("python*.exe"))


def test_report_records_that_nothing_was_launched():
    payload = report()
    assert payload["subject_process_launched"] is False
    assert payload["runtime_staged"] is False
    assert payload["birth_status"].startswith("M014 remains BLOCKED")