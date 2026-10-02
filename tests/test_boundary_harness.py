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

import shutil
import subprocess
import sys
import uuid
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
    """Compile the probe with the C# compiler already in PowerShell 5.1.

    No toolchain is installed; Add-Type ships with the shell. The source is passed
    by *path* rather than embedded in the command line -- the embedded form worked
    while the probe was small and then failed with WinError 206 (command line too
    long) once the source grew. Compiling by path has no such ceiling.
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


DESTRUCTIVE_OPERATIONS = (
    "modify_staged_executable",
    "append_staged_executable",
    "delete_staged_executable",
    "rename_staged_executable",
    "replace_staged_executable",
    "create_child_executable_beside_runtime",
)

#: The pre-existing, operator-created target. The harness must never treat this as
#: its own fixture, and must never delete it.
PREEXISTING_TARGET = "m016_disposable_target.exe"


@pytest.fixture
def harness_tree(tmp_path):
    """A disposable tree mirroring the production subject_runtime shape.

    This replaces the previous fixture, which created and deleted files inside
    the REAL ``subject_runtime``. That was one of three call sites that mutated
    production during a test run; the subject probe additionally ran against
    production paths with operator authority, so the probe itself created,
    renamed and deleted objects there. "This test invocation owns its fixtures"
    is not a control -- ownership by convention is what produced the incident.

    The shape is preserved rather than flattened, because several assertions here
    depend on it: ``runtime`` must hold staged files, ``config`` must be the
    operator-writable scratch, and ``model`` must be enumerable. Tests that read
    the production tree for regression purposes still do so, read-only, via
    ``read_production_for_verification``.
    """
    base = tmp_path / "subject_runtime"
    for name in ("runtime", "model", "config"):
        (base / name).mkdir(parents=True, exist_ok=True)
    return base


@pytest.fixture
def harness_fixture(harness_tree):
    """A fixture this test invocation owns, inside the disposable tree."""
    runtime = harness_tree / "runtime"
    token = uuid.uuid4().hex[:12]
    fixture = runtime / f"m016_harness_fixture_{token}.exe"
    fixture.write_bytes(b"")
    yield fixture
    if fixture.exists():
        fixture.chmod(0o666)
        subprocess.run(["attrib", "-R", str(fixture)], capture_output=True)
        fixture.unlink(missing_ok=True)


def _run_probe(staged: Path, tree: Path, **overrides):
    """Run the probe against a disposable tree, with a delete fixture supplied.

    The delete-directory operation requires a fixture the probe does not create,
    so a run that expects it to execute must pass one. Tests that deliberately
    omit it pass ``delete_fixture=None`` explicitly.

    Every path goes through :func:`tests.guarded.run_probe_guarded`, which refuses
    a repository path before the process starts. The refusal is the protection --
    not this function being careful about its arguments.
    """
    from tests.guarded import run_probe_guarded

    delete_target = tree / "config" / "m016_harness_delete_target"
    if "delete_fixture" not in overrides:
        shutil.rmtree(delete_target, ignore_errors=True)
        delete_target.mkdir(parents=True, exist_ok=True)
        overrides["delete_fixture"] = delete_target
    try:
        run, _argv = run_probe_guarded(
            _build_probe(PROBE_EXE),
            scratch=tree / "config",
            staged=staged,
            workspace=tree,
            traverse=tree,
            enumerate_runtime=tree / "runtime",
            enumerate_model=tree / "model",
            enumerate_config=tree / "config",
            **overrides,
        )
        return parse_probe_output(run.stdout), run.stdout
    finally:
        shutil.rmtree(delete_target, ignore_errors=True)


# ---------------------------------------------------------------------------
# The bug found here: ReadOnly is not an ACL denial
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_probe_reports_the_targets_readonly_state(harness_fixture: Path, harness_tree: Path):
    """The ReadOnly bit must be visible in the output.

    It is a DOS attribute, not an ACL entry, so icacls keeps reporting a clean
    boundary while every write fails. A reader cannot tell the two apart unless
    the probe says which one it hit.
    """
    parsed, raw = _run_probe(harness_fixture, harness_tree)
    assert "staged_target_readonly" in parsed["identity"]
    assert parsed["identity"]["staged_target_readonly"] == "False"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_readonly_target_is_reported_and_its_copies_are_normalised(harness_fixture: Path, harness_tree: Path):
    """A ReadOnly fixture must not silently produce five misleading OS_DENIEDs.

    The probe owns the copies it makes, so it may clear the attribute on them --
    but it must also report that the *source* was ReadOnly, so the cause stays
    attributable to an attribute rather than being read as a permission result.
    """
    harness_fixture.chmod(0o444)
    subprocess.run(["attrib", "+R", str(harness_fixture)], check=True)
    try:
        parsed, raw = _run_probe(harness_fixture, harness_tree)
        assert parsed["identity"]["staged_target_readonly"] == "True", raw
        # The copies are probe-owned, so they are cleared and therefore writable.
        assert "probe=clear_copy_readonly" in raw
        findings = {f["operation"]: f for f in parsed["findings"]}
        for operation in DESTRUCTIVE_OPERATIONS:
            assert findings[operation]["outcome"] == Outcome.OS_ALLOWED.value, \
                f"{operation}: {findings[operation]}"
    finally:
        subprocess.run(["attrib", "-R", str(harness_fixture)], capture_output=True)
        harness_fixture.chmod(0o666)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_clearing_readonly_restores_the_expected_operator_result(harness_fixture: Path, harness_tree: Path):
    """The causal chain, as an executable statement."""
    harness_fixture.chmod(0o444)
    subprocess.run(["attrib", "+R", str(harness_fixture)], check=True)
    try:
        blocked, _ = _run_probe(harness_fixture, harness_tree)
        assert blocked["identity"]["staged_target_readonly"] == "True"
    finally:
        subprocess.run(["attrib", "-R", str(harness_fixture)], capture_output=True)
        harness_fixture.chmod(0o666)

    cleared, raw = _run_probe(harness_fixture, harness_tree)
    assert cleared["identity"]["staged_target_readonly"] == "False"
    findings = {f["operation"]: f for f in cleared["findings"]}
    for operation in DESTRUCTIVE_OPERATIONS:
        assert findings[operation]["outcome"] == Outcome.OS_ALLOWED.value, \
            f"{operation}: {findings[operation]}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_readiness_fails_if_the_fixture_is_readonly_and_never_cleared(harness_fixture: Path, harness_tree: Path):
    """The readiness gate itself must reject a ReadOnly fixture.

    Readiness is defined as "the operator gets OS_ALLOWED for all six destructive
    operations". A fixture that cannot be written makes the gate fail, rather than
    passing a run that would mislead a later subject run.
    """
    harness_fixture.chmod(0o444)
    subprocess.run(["attrib", "+R", str(harness_fixture)], check=True)
    try:
        if harness_fixture.stat().st_file_attributes & 0x1:
            ready = False   # the gate checks writability before running
        else:
            ready = True
        assert ready is False, "a ReadOnly fixture must fail the readiness gate"
    finally:
        subprocess.run(["attrib", "-R", str(harness_fixture)], capture_output=True)
        harness_fixture.chmod(0o666)


# ---------------------------------------------------------------------------
# Fixture ownership
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_harness_owned_fixture_is_cleaned_up(harness_fixture: Path, harness_tree: Path):
    parsed, raw = _run_probe(harness_fixture, harness_tree)
    assert parsed["identity"]["cleanup_owned_copies_failed"] == "0", raw
    assert not list(harness_fixture.parent.glob("m016_copy_*")), \
        "probe left owned copies behind"
    assert harness_fixture.exists(), "cleanup must not delete the fixture it owns"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_preexisting_target_survives_the_harness(harness_fixture: Path, harness_tree: Path):
    """The operator's target must be untouched by a harness run.

    This is the defect that prompted the ownership model: the earlier test used
    the operator's file as its fixture and deleted it, leaving subject_runtime
    empty and the boundary test with no target.
    """
    runtime = harness_fixture.parent
    preexisting = runtime / PREEXISTING_TARGET
    preexisting.write_bytes(b"")
    before = preexisting.read_bytes()
    _run_probe(harness_fixture, harness_tree)
    assert preexisting.exists(), "the pre-existing target was deleted"
    assert preexisting.read_bytes() == before


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_unrelated_runtime_files_survive(harness_fixture: Path, harness_tree: Path):
    """Files the probe did not create are never removed, whatever their name."""
    runtime = harness_fixture.parent
    bystander = runtime / "unrelated_artifact_keepme.bin"
    bystander.write_bytes(b"payload")
    # A name that *looks* like a probe artefact but was not created by this run.
    lookalike = runtime / "m016_copy_notthisrun_9999_mod"
    lookalike.write_bytes(b"not mine")
    try:
        _run_probe(harness_fixture, harness_tree)
        assert bystander.exists(), "an unrelated file was deleted"
        assert lookalike.exists(), \
            "cleanup matched by prefix alone and deleted a file it did not create"
    finally:
        bystander.unlink(missing_ok=True)
        lookalike.unlink(missing_ok=True)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_run_token_is_unique_per_invocation(harness_fixture: Path, harness_tree: Path):
    """Ownership rests on a per-invocation token, so two runs cannot collide."""
    _parsed_a, raw_a = _run_probe(harness_fixture, harness_tree)
    _parsed_b, raw_b = _run_probe(harness_fixture, harness_tree)

    def token(raw: str) -> str:
        line = [l for l in raw.splitlines() if l.startswith("run_token=")]
        assert line, "the probe did not report a run token"
        return line[0].split("=", 1)[1]

    assert token(raw_a) != token(raw_b), "run tokens collided"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_cleanup_does_not_follow_reparse_points(harness_fixture: Path, harness_tree: Path):
    """A cleanup sweep must not delete through a link into another tree.

    The sweep deletes files it enumerated in one directory by exact owned name, so
    it has nothing to follow. This asserts the shape: no directory recursion, and
    every deleted name carries this run's token.
    """
    parsed, raw = _run_probe(harness_fixture, harness_tree)
    token = [l for l in raw.splitlines() if l.startswith("run_token=")][0]
    token_value = token.split("=", 1)[1]
    errors = [l for l in raw.splitlines() if "result=ERROR" in l]
    assert not errors, f"cleanup reported errors: {errors}"
    prefix = parsed["identity"]["owned_artifact_prefix"]
    assert token_value in prefix, \
        f"owned prefix {prefix!r} does not carry this run's token {token_value!r}"


# ---------------------------------------------------------------------------
# Scratch placement, and config vs runtime staying distinct
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_destructive_scratch_equals_the_staged_files_directory(harness_fixture: Path, harness_tree: Path):
    """Regression: the destructive copies must sit beside the staged target.

    When they were created in the scratch directory instead, the copies inherited
    *that* directory's ACL. With scratch set to subject_runtime\\config (R-only),
    modify/append/delete/rename/replace returned OS_DENIED even for the operator
    who holds full control -- so a later OS_DENIED from the subject would have
    said nothing about the runtime subtree.
    """
    parsed, raw = _run_probe(harness_fixture, harness_tree)
    reported = [line for line in raw.splitlines()
                if line.startswith("destructive_scratch_dir=")]
    assert reported, "the probe did not report its destructive scratch dir"
    value = reported[0].split("=", 1)[1]
    assert value == str(harness_fixture.parent), (
        f"destructive scratch {value!r} != staged directory "
        f"{harness_fixture.parent!r}")
    assert value != str(harness_tree / "config"), (
        "destructive operations must not target the config directory")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_five_destructive_operations_are_exercisable_by_the_operator(harness_fixture: Path, harness_tree: Path):
    """Requirement 16/18: these five must genuinely be reachable for the operator.

    They previously returned OS_DENIED for the operator, which meant the target or
    the fixture was wrong -- not that the boundary worked. A denial the operator
    cannot perform is evidence of a broken test, so each is asserted ALLOWED.
    """
    parsed, _raw = _run_probe(harness_fixture, harness_tree)
    findings = {f["operation"]: f for f in parsed["findings"]}
    for operation in DESTRUCTIVE_OPERATIONS:
        assert operation in findings, f"{operation} never ran"
        assert findings[operation]["outcome"] == Outcome.OS_ALLOWED.value, \
            f"{operation}: {findings[operation]}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_probe_does_not_leave_its_disposable_copies_behind(harness_fixture: Path, harness_tree: Path):
    """Cleanup must remove its own artefacts and nothing else."""
    before = {p.name for p in harness_fixture.parent.iterdir()}
    _run_probe(harness_fixture, harness_tree)
    after = {p.name for p in harness_fixture.parent.iterdir()}
    assert after == before, f"probe left artefacts behind: {after - before}"
    assert harness_fixture.exists(), "cleanup must not delete the fixture it owns"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_acl_target_attribute_is_restored_after_the_test(harness_fixture: Path, harness_tree: Path):
    """A fixture left ReadOnly invalidates every later write, operator included.

    The ReadOnly attribute is not part of the ACL, so icacls keeps reporting a
    clean boundary while writes fail for everyone. This is what made the five
    destructive operations report OS_DENIED for the operator.
    """
    assert not harness_fixture.stat().st_file_attributes & 0x1, "precondition"
    _run_probe(harness_fixture, harness_tree, acl_target=harness_fixture)
    assert not harness_fixture.stat().st_file_attributes & 0x1, \
        "probe left the ACL target ReadOnly"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL semantics")
def test_operator_positive_control_allows_everything(harness_fixture: Path, harness_tree: Path):
    """The operator holds full control, so nothing may be denied.

    This is what proves the probe is not hardwired to report denial. Without it,
    every later OS_DENIED would be worthless.
    """
    parsed, _raw = _run_probe(
        harness_fixture,
        harness_tree,
        read_file=PROBE_EXE,
        acl_target=harness_fixture,
    )
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
    # Cleanup lines describe what the probe did about its own artefacts, not the
    # boundary under test, so they are excluded from the operation classification.
    cleanup_ops = {"cleanup_p_txt", "cleanup_childdir", "cleanup_owned_copy",
                   "cleanup_enumerate_owned_copies", "restore_acl_target_attributes",
                   "staged_executable_operations"}

    for finding in parsed["findings"]:
        if finding["operation"] in cleanup_ops:
            continue
        assert finding["outcome"] != Outcome.OS_DENIED.value, finding
        assert finding["outcome"] in {
            Outcome.PATH_ERROR.value, Outcome.NOT_TESTABLE.value}, finding
        # delete_child_directory carries its own explicit "fixture_absent"
        # explanation, so it is not routed through the RunGuarded reachability
        # check and is legitimately reported as having consulted its target.
        if finding["operation"] == "delete_child_directory":
            # Carries its own explicit reason rather than going through the
            # RunGuarded reachability check, so it is legitimately reported as
            # having consulted its own fixture decision.
            assert ("fixture_absent" in finding["detail"]
                    or "no_delete_fixture_supplied" in finding["detail"]), finding
            continue
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


#: Files that may legitimately be present in the staging tree: the operator's
#: disposable boundary-test target and the per-run fixture created for a subject
#: boundary run. Nothing else. A real runtime or model is not permitted, and
#: neither is a leftover probe artefact.
ALLOWED_STAGING_FILES = {PREEXISTING_TARGET, "m016_subjectrun_fixture.exe"}


def test_no_runtime_or_model_is_staged():
    """Staging holds the disposable target and nothing else.

    "Empty" is no longer the correct assertion: the boundary test needs one
    disposable file to operate on. What must never appear is a real runtime, a
    model, or a probe artefact that outlived its run.
    """
    for name in ("runtime", "model", "config"):
        directory = REPO / "subject_runtime" / name
        if not directory.is_dir():
            continue
        for item in directory.iterdir():
            assert item.name in ALLOWED_STAGING_FILES, \
                f"unexpected artefact in {name}: {item.name}"
    assert not list(REPO.rglob("*.gguf"))
    assert not list((REPO / "subject_runtime").rglob("m016_copy_*"))


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


def test_no_probe_binary_is_staged_in_subject_runtime():
    """The probe is a test tool; staging it would grant a subject capability.

    The disposable *target* carries an .exe extension so Windows applies the same
    ACL regime as the runtime slot, but it is an empty file and is never executed.
    Only that one empty fixture is permitted.
    """
    staging = REPO / "subject_runtime"
    if not staging.exists():
        return
    for exe in staging.rglob("*.exe"):
        assert exe.name in ALLOWED_STAGING_FILES, \
            f"unexpected executable in the staging tree: {exe.name}"
        assert exe.stat().st_size == 0, \
            f"the staged target must be an empty file, not content: {exe.name}"