"""Tests for the M016/M017 follow-up: integrity parsing and the boundary harness.

The integrity tests here are arithmetic, not mocked. They assert the *structure*
of a mandatory-label SID against known-good vectors, so a regression to the
offset-2 bug is caught without needing a Windows token at all.

What is NOT claimed: that any filesystem boundary has been enforced for the
subject. No test in this file mocks a Windows security API and then asserts a
denial. The operator positive control below runs the real probe for real; the
subject-side boundary test has not yet been run and is asserted only as
*prepared*, not as *passed*.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from foundation.boundary_test import (
    HUMAN_VERIFIED_IDENTITY,
    INTEGRITY_RIDS,
    OPERATOR_SID,
    SUBJECT_SID,
    Outcome,
    ProbeFinding,
    build_probe_argv,
    integrity_label_from_sid,
    parse_probe_output,
    runas_command,
)

REPO = Path(__file__).resolve().parents[1]
PROBE_SOURCE = REPO / "foundation" / "subject_probe.cs"
PROBE_EXE = REPO / "baby_workspace" / "m016_probe.exe"


# ---------------------------------------------------------------------------
# Integrity: the SID layout, as arithmetic
# ---------------------------------------------------------------------------

def test_mandatory_label_sid_header_is_eight_bytes():
    """Revision(1) + SubAuthorityCount(1) + IdentifierAuthority(6) = 8.

    This is the constant the probe got wrong. It is asserted here as a fact about
    the SID format, independently of any token.
    """
    # S-1-16-8192: revision 1, subauth count 1, authority 6, one sub-authority.
    sid = bytes([1, 1, 0, 0, 0, 0, 0, 0x10]) + (8192).to_bytes(4, "little")
    assert len(sid) == 12
    assert sid[0] == 1          # Revision
    assert sid[1] == 1          # SubAuthorityCount
    assert sid[2:8] == bytes([0, 0, 0, 0, 0, 0x10])   # IdentifierAuthority
    assert int.from_bytes(sid[8:12], "little") == 8192


def test_reading_the_rid_from_offset_two_would_report_unprotected():
    """The exact defect, demonstrated.

    Offset 2 lands inside the identifier authority. Its low DWORD is zero, which
    maps to UNPROTECTED -- which is what the probe printed for a Medium token.
    """
    sid = bytes([1, 1, 0, 0, 0, 0, 0, 0x10]) + (8192).to_bytes(4, "little")
    wrong = int.from_bytes(sid[2:6], "little")
    right = int.from_bytes(sid[8:12], "little")
    assert wrong == 0
    assert INTEGRITY_RIDS[wrong] == "UNPROTECTED"
    assert right == 0x2000
    assert INTEGRITY_RIDS[right] == "MEDIUM"


@pytest.mark.parametrize("rid,name", sorted(INTEGRITY_RIDS.items()))
def test_every_integrity_rid_maps_to_its_name(rid: int, name: str):
    assert integrity_label_from_sid(f"S-1-16-{rid}") == name


def test_unknown_rid_is_not_guessed():
    assert integrity_label_from_sid("S-1-16-9999").startswith("UNKNOWN")
    assert integrity_label_from_sid("S-1-5-21-1-2-3-1001") == "UNKNOWN"
    assert integrity_label_from_sid("not-a-sid") == "UNKNOWN"
    assert integrity_label_from_sid("") == "UNKNOWN"


def test_probe_source_uses_the_eight_byte_offset():
    """Guards the fix at the source, not just in the Python model."""
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    assert "8 + (count - 1) * 4" in source
    assert "2 + (count - 1) * 4" not in source


def test_probe_source_does_not_report_unprotected_on_parse_failure():
    """A parse failure must be distinguishable from a zero RID."""
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    assert "<no-label>" in source
    assert "<unreadable-sid>" in source
    assert "PARSE_FAILED" in source


def test_probe_source_reads_integrity_twice():
    """Two independent paths must agree; a single path can silently return 0."""
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    assert "integrity_level_independent=" in source
    assert "integrity_paths_agree=" in source
    assert "ConvertSidToStringSid" in source


# ---------------------------------------------------------------------------
# Identity stays token-derived
# ---------------------------------------------------------------------------

def test_identity_is_never_derived_from_arguments():
    source = PROBE_SOURCE.read_text(encoding="utf-8")
    assert "OpenProcessToken" in source
    assert "GetTokenInformation" in source
    # The account name is printed from the token, not from argv.
    assert 'Console.WriteLine("account_name="' in source


def test_verified_human_identity_is_recorded_and_flagged_correctly():
    record = HUMAN_VERIFIED_IDENTITY
    assert record["verified"] is True
    assert record["user_sid"] == SUBJECT_SID
    assert record["credentials_stored"] is False
    assert record["savecred_used"] is False
    # The reported integrity must stay on the record as a bug, not as a finding.
    assert record["integrity_level_as_reported"] == "UNPROTECTED"
    assert record["integrity_level_status"] == "RESOLVED_AS_PROBE_BUG"


def test_subject_and_operator_sids_differ():
    """A runas launch that printed the operator SID would mean no identity switch."""
    assert SUBJECT_SID != OPERATOR_SID
    assert SUBJECT_SID.endswith("-1022")
    assert OPERATOR_SID.endswith("-1001")


# ---------------------------------------------------------------------------
# The runas command
# ---------------------------------------------------------------------------

def test_runas_command_contains_no_password():
    command = runas_command(PROBE_EXE, "out.txt", ["-", "-", "-", "-"])
    assert "password" not in command.lower()
    assert "/savecred" not in command.lower()
    assert "BABY_AI_TEST" in command


def test_runas_command_redirects_stdout():
    """runas closes the child's console on exit; without redirection evidence is lost."""
    command = runas_command(PROBE_EXE, "out.txt", ["-", "-", "-", "-"])
    assert "cmd.exe /c" in command
    assert "> " in command and "2>&1" in command


def test_argv_uses_a_placeholder_rather_than_empty_strings():
    """PowerShell drops empty-string arguments and shifts every later value."""
    argv = build_probe_argv()
    assert argv == ["-", "-", "-", "-"]
    assert "" not in argv


def test_argv_carries_absolute_paths_when_given():
    argv = build_probe_argv(
        scratch=REPO / "subject_runtime" / "config",
        enumerate_runtime=REPO / "subject_runtime" / "runtime",
    )
    assert argv[0] == str(REPO / "subject_runtime" / "config")
    assert "--enumerate-runtime=" in " ".join(argv)


# ---------------------------------------------------------------------------
# Outcome classification
# ---------------------------------------------------------------------------

def test_five_outcomes_are_defined():
    assert {o.value for o in Outcome} == {
        "OS_ALLOWED", "OS_DENIED", "PATH_ERROR", "NOT_TESTABLE", "ERROR"}


def test_unreachable_target_is_not_a_denial():
    finding = ProbeFinding("modify", "OS_DENIED", "path_not_reached(NOT_REACHABLE)")
    assert finding.reached_target is False


def test_missing_path_is_not_a_denial():
    finding = ProbeFinding("modify", "NOT_TESTABLE", "no_path_supplied")
    assert finding.reached_target is False


def test_real_denial_reached_its_target():
    finding = ProbeFinding("modify", "OS_DENIED", "winerror=5")
    assert finding.reached_target is True


def test_parser_classifies_and_separates_findings():
    output = "\n".join([
        "schema=probe/v1",
        "user_sid=" + SUBJECT_SID,
        "integrity_level=MEDIUM",
        "integrity_level_independent=MEDIUM",
        "integrity_paths_agree=true",
        "probe=traverse_directory result=OS_ALLOWED",
        "probe=modify_staged_executable result=OS_DENIED winerror=5",
        "probe=create_file_in_staging_scratch result=NOT_TESTABLE "
        "reason=path_not_reached(NOT_REACHABLE)",
    ])
    parsed = parse_probe_output(output)
    assert parsed["identity"]["user_sid"] == SUBJECT_SID
    assert parsed["integrity_level"] == "MEDIUM"
    assert parsed["integrity_paths_agree"] is True
    assert len(parsed["findings"]) == 3
    reached = {f["operation"] for f in parsed["findings_reaching_target"]}
    assert reached == {"traverse_directory", "modify_staged_executable"}


def test_parser_does_not_silently_drop_unknown_lines():
    parsed = parse_probe_output("probe=x result=OS_ALLOWED\nsomething_unparseable")
    assert parsed["unparsed_lines"] == ["something_unparseable"]


def test_parser_reports_disagreement_between_integrity_paths():
    parsed = parse_probe_output(
        "integrity_level=UNPROTECTED\nintegrity_level_independent=MEDIUM\n"
        "integrity_paths_agree=false")
    assert parsed["integrity_paths_agree"] is False
    assert parsed["integrity_level"] != parsed["integrity_level_independent"]


# ---------------------------------------------------------------------------
# Real probe, operator side
# ---------------------------------------------------------------------------

def _build_probe(exe: Path) -> Path:
    if not exe.is_file():
        source = PROBE_SOURCE.read_text(encoding="utf-8")
        script = (
            "$ErrorActionPreference='Stop'; "
            "Add-Type -TypeDefinition @'\n" + source + "\n'@ "
            f"-OutputAssembly '{exe}' -OutputType ConsoleApplication"
        )
        built = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, shell=False, timeout=300)
        if built.returncode != 0 or not exe.is_file():
            pytest.skip("Add-Type could not compile the probe on this host")
    return exe


@pytest.mark.skipif(sys.platform != "win32", reason="Windows token APIs")
def test_probe_reports_medium_integrity_and_the_two_paths_agree():
    """This is the corrected result, checked against a real token.

    A Medium operator token that still reads UNPROTECTED would mean the fix did not
    hold; agreement between the two paths guards against a coincidental match.
    """
    exe = _build_probe(PROBE_EXE)
    run = subprocess.run([str(exe)], capture_output=True, text=True,
                         shell=False, timeout=120)
    parsed = parse_probe_output(run.stdout)
    assert parsed["integrity_level"] == "MEDIUM"
    assert parsed["integrity_level_independent"] == "MEDIUM"
    assert parsed["integrity_paths_agree"] is True
    assert parsed["integrity_level"] not in ("", "UNPROTECTED")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows token APIs")
def test_probe_integrity_matches_whoami():
    """Independent cross-check against a different tool entirely."""
    exe = _build_probe(PROBE_EXE)
    probe = parse_probe_output(subprocess.run(
        [str(exe)], capture_output=True, text=True, shell=False,
        timeout=120).stdout)
    groups = subprocess.run(["whoami", "/groups"], capture_output=True, text=True,
                            shell=False, timeout=60).stdout
    assert "S-1-16-8192" in groups, "expected a Medium Mandatory Level label"
    assert probe["integrity_level"] == "MEDIUM"
    assert probe["integrity_level"] == integrity_label_from_sid("S-1-16-8192")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_operator_positive_control_allows_everything():
    """The operator holds full control, so nothing may be denied.

    This is what proves the probe is not hardwired to report denial. Without it,
    every later OS_DENIED would be worthless.
    """
    exe = _build_probe(PROBE_EXE)
    staging = REPO / "subject_runtime"
    staged = staging / "runtime" / "m016_control.exe"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"MZ")
    try:
        argv = build_probe_argv(
            scratch=staging / "config",
            staged=staged,
            workspace=REPO / "baby_workspace",
            traverse=staging,
            enumerate_runtime=staging / "runtime",
            enumerate_model=staging / "model",
            enumerate_config=staging / "config",
            read_file=REPO / "baby_workspace" / "m016_probe.exe",
        )
        run = subprocess.run([str(exe), *argv], capture_output=True, text=True,
                             shell=False, timeout=180)
        parsed = parse_probe_output(run.stdout)
        findings = {f["operation"]: f for f in parsed["findings_reaching_target"]}
        expected_allowed = [
            "traverse_directory", "enumerate_runtime", "enumerate_model",
            "enumerate_config", "read_disposable_file",
            "create_file_in_staging_scratch", "modify_staged_executable",
            "append_staged_executable", "delete_staged_executable",
            "rename_staged_executable", "replace_staged_executable",
            "create_child_executable_beside_runtime", "create_child_directory",
            "delete_child_directory", "workspace_write", "workspace_read",
            "workspace_delete",
        ]
        for operation in expected_allowed:
            assert operation in findings, f"{operation} never ran"
            assert findings[operation]["outcome"] == Outcome.OS_ALLOWED.value, \
                f"{operation}: {findings[operation]}"
    finally:
        staged.unlink(missing_ok=True)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_missing_paths_never_produce_a_denial():
    """A negative control on classification itself."""
    exe = _build_probe(PROBE_EXE)
    argv = build_probe_argv(
        scratch=r"C:\m016_missing_dir", staged=r"C:\m016_missing.exe",
        protected=None, workspace=None,
        traverse=r"C:\m016_missing_dir",
        enumerate_runtime=r"C:\m016_missing_dir",
        read_file=r"C:\m016_missing.txt",
    )
    run = subprocess.run([str(exe), *argv], capture_output=True, text=True,
                         shell=False, timeout=120)
    parsed = parse_probe_output(run.stdout)
    for finding in parsed["findings"]:
        assert finding["outcome"] != Outcome.OS_DENIED.value, finding
        assert finding["outcome"] in {
            Outcome.PATH_ERROR.value, Outcome.NOT_TESTABLE.value}, finding
        assert finding["reached_target"] is False, finding


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_absent_options_are_not_tested_rather_than_assumed():
    """No implicit fallback may substitute a path the harness never supplied."""
    exe = _build_probe(PROBE_EXE)
    run = subprocess.run([str(exe), "-", "-", "-", "-"], capture_output=True,
                         text=True, shell=False, timeout=120)
    parsed = parse_probe_output(run.stdout)
    findings = {f["operation"]: f for f in parsed["findings"]}
    for operation in ("traverse_directory", "enumerate_runtime",
                      "enumerate_model", "enumerate_config",
                      "read_disposable_file", "modify_acl"):
        assert findings[operation]["outcome"] == Outcome.NOT_TESTABLE.value
        assert findings[operation]["detail"] == "no_path_supplied"


# ---------------------------------------------------------------------------
# Scope: nothing out of bounds happened
# ---------------------------------------------------------------------------

def test_no_boundary_test_has_been_recorded_as_passed():
    """The subject-side ACL boundary is prepared, not proven."""
    # No evidence file may claim a subject-side denial.
    evidence = REPO / "docs" / "evidence"
    for path in evidence.glob("m016*.json"):
        text = path.read_text(encoding="utf-8").lower()
        assert "subject_write_denied" not in text
        assert "boundary_enforced" not in text


def test_no_runtime_or_model_is_staged():
    for name in ("runtime", "model", "config"):
        directory = REPO / "subject_runtime" / name
        if directory.is_dir():
            assert not list(directory.iterdir()), f"{name} is not empty"
    assert not list(REPO.rglob("*.gguf"))


def test_no_birth_occurred():
    assert not (REPO / "human_control" / "birth_records" / "BIRTH.json").exists()


def test_m015_boundary_is_untouched():
    from foundation.staging import verify_boundary

    report = verify_boundary()
    assert report["status"] == "STAGING_VERIFIED"
    assert report["subject_rights_exact_everywhere"] is True
    assert report["inherited_modify_absent_everywhere"] is True


def test_m005_protected_evidence_is_intact():
    from foundation.isolation import protected_evidence_digests

    digests = protected_evidence_digests()
    assert digests
    assert all(not v.startswith("UNREADABLE") for v in digests.values())


def test_probe_is_not_staged_in_subject_runtime():
    staging = REPO / "subject_runtime"
    if staging.exists():
        assert not list(staging.rglob("*.exe"))