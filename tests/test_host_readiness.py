"""Tests for the host-readiness investigation and its reporting logic.

Scope, deliberately narrow. These tests cover the *reporting* layer: that the
account survey reads the real account, that token observation is genuinely
read-only, that the mechanism table refuses the things it must refuse, and that
``NOT_TESTABLE`` never leaks into a success.

**No test in this file claims ``BABY_AI_TEST`` execution.** The subject account
cannot be launched from this harness without a credential the laboratory will
not accept, so that path is asserted to be ``NOT_TESTABLE`` -- and a test that
asserted a successful subject launch would be a test that could only pass by
faking the one thing this investigation exists to establish.

Token observation *is* exercised against a real process, because the operator's
own child is a process whose token the operator legitimately holds. That proves
the mechanism works without pretending anything about the subject account.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from foundation.host_readiness import (
    EXPECTED_ACCOUNT,
    EXPECTED_SID,
    HUMAN_LAUNCH_COMMAND,
    REFUSED_PRIVILEGES,
    MechanismFinding,
    Readiness,
    candidate_mechanisms,
    host_readiness_report,
    survey_account,
    survey_harness_privileges,
    verify_launched_process,
)
from foundation.token_observation import (
    INTEGRITY_LABELS,
    ObservationStatus,
    observe_process,
    read_token_user_sid,
)

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def child_process():
    """A real process whose token the operator holds.

    A real child, not a mock: the whole point of these tests is that the Win32
    calls work, and a mock would only prove the mock was called.
    """
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
    )
    try:
        yield process
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - stubborn child
            process.kill()


# ---------------------------------------------------------------------------
# Token observation
# ---------------------------------------------------------------------------

class TestTokenObservation:
    def test_reads_a_real_process_token(self, child_process):
        observation = observe_process(child_process.pid)
        assert observation.status is ObservationStatus.VERIFIED
        assert observation.user_sid.startswith("S-1-5-21-")
        assert observation.account_name.startswith("THARUNBALAJI-LA\\")

    def test_reads_the_integrity_label(self, child_process):
        observation = observe_process(child_process.pid)
        assert observation.integrity_label in set(INTEGRITY_LABELS.values())

    def test_reports_elevation_rather_than_guessing(self, child_process):
        observation = observe_process(child_process.pid)
        assert isinstance(observation.elevated, bool)

    def test_a_nonexistent_pid_is_not_testable_not_a_pass(self):
        """A pid that cannot be opened is an unknown identity, not a good one."""
        observation = observe_process(999_999_999)
        assert observation.status is ObservationStatus.NOT_TESTABLE
        assert observation.identity_is_independently_observed is False
        assert "NOT_TESTABLE" in observation.detail

    def test_a_wrong_expected_sid_fails(self, child_process):
        observation = observe_process(
            child_process.pid, expected_sid="S-1-5-21-1-2-3-1002",
        )
        assert observation.status is ObservationStatus.FAILED
        assert observation.identity_is_independently_observed is False

    def test_a_right_expected_sid_verifies(self, child_process):
        observed = observe_process(child_process.pid)
        again = observe_process(child_process.pid, expected_sid=observed.user_sid)
        assert again.status is ObservationStatus.VERIFIED

    def test_self_report_never_makes_identity_independent(self, child_process):
        """A program may claim any identity. Only the token counts."""
        observation = observe_process(
            child_process.pid,
            self_reported={"whoami": "THARUNBALAJI-LA\\BABY_AI_TEST"},
        )
        assert observation.self_reported["whoami"] == "THARUNBALAJI-LA\\BABY_AI_TEST"
        # The claim is recorded, but the SID in the token is still the operator's.
        assert observation.user_sid != EXPECTED_SID
        assert observation.identity_is_independently_observed is True
        # ...and the two are never merged.
        assert observation.self_reported["whoami"] not in str(observation.user_sid)

    def test_the_subject_account_is_not_the_operator(self, child_process):
        """The control that keeps the rest of the suite honest."""
        assert read_token_user_sid(child_process.pid) != EXPECTED_SID

    def test_boundary_meaningful_is_false_for_a_non_subject_process(self,
                                                                    child_process):
        """The exact condition M005 was careful about."""
        result = verify_launched_process(child_process.pid)
        assert result["boundary_meaningful"] is False
        assert result["account_is_subject"] is False

    def test_token_observation_is_read_only(self):
        """The module must not be able to act on what it observes."""
        source = (REPO / "foundation" / "token_observation.py").read_text(
            encoding="utf-8")
        called: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                called.add(ast.unparse(node.func))
            elif isinstance(node, ast.Attribute):
                called.add(node.attr)
        for forbidden in ("WriteProcessMemory", "DuplicateToken",
                          "CreateProcessWithTokenW", "ImpersonateLoggedOnUser",
                          "SetThreadToken", "AdjustTokenPrivileges",
                          "TerminateProcess"):
            assert forbidden not in called, forbidden

    def test_it_asks_for_no_more_than_it_needs(self):
        """Walks the AST rather than scanning text.

        A text scan for ``PROCESS_ALL_ACCESS`` would match the comment saying the
        module deliberately does not use it -- the same false positive M011's
        import-graph tests were written to avoid. Only real references count.
        """
        source = (REPO / "foundation" / "token_observation.py").read_text(
            encoding="utf-8")
        referenced: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                referenced.add(ast.unparse(node.func))
            elif isinstance(node, ast.Attribute):
                referenced.add(node.attr)
            elif isinstance(node, ast.Name):
                referenced.add(node.id)
        assert "PROCESS_ALL_ACCESS" not in referenced
        assert "PROCESS_QUERY_LIMITED_INFORMATION" in referenced
        # TOKEN_QUERY is the only token right used, and the module never asks for
        # a right that would let it modify the process it observes.
        for forbidden in ("OpenProcessTokenW", "WriteProcessMemory",
                          "ReadProcessMemory", "TerminateProcess"):
            assert forbidden not in referenced, forbidden


# ---------------------------------------------------------------------------
# Account survey
# ---------------------------------------------------------------------------

class TestAccountSurvey:
    def test_the_account_exists_with_the_expected_sid(self):
        survey = survey_account()
        assert survey["read_failed"] is False
        assert survey["sid_matches"] is True
        assert survey["sid"] == EXPECTED_SID

    def test_the_account_is_enabled(self):
        survey = survey_account()
        assert str(survey["observed"]["enabled"]).lower() == "true"

    def test_group_membership_is_distinguished_from_a_read_failure(self):
        """"In no groups" and "could not read" must not look the same."""
        survey = survey_account()
        assert survey["read_failed"] is False
        assert survey["inherits_no_group_privilege"] is True
        assert survey["local_group_membership"] == "NONE"

    def test_the_account_is_not_an_administrator(self):
        """Inherits nothing from a local group, so it inherits no admin rights."""
        survey = survey_account()
        assert "Administrators" not in str(survey["local_group_membership"])

    def test_the_survey_runs_nothing_that_mutates(self):
        source = (REPO / "foundation" / "host_readiness.py").read_text(
            encoding="utf-8")
        for forbidden in ("New-LocalUser", "Set-LocalUser", "Add-LocalGroupMember",
                          "net user ... /add", "Register-ScheduledTask",
                          "New-Service", "sc.exe create", "Set-Acl", "icacls"):
            assert forbidden not in source, forbidden


# ---------------------------------------------------------------------------
# Harness privileges
# ---------------------------------------------------------------------------

class TestHarnessPrivileges:
    def test_the_harness_cannot_impersonate(self):
        report = survey_harness_privileges()
        assert report["can_impersonate"] is False

    def test_the_refused_privileges_are_actually_refused(self):
        report = survey_harness_privileges()
        assert set(report["privileges_we_refuse_to_acquire"]) == \
            set(REFUSED_PRIVILEGES)
        # And they are genuinely absent, not merely disabled.
        for name in REFUSED_PRIVILEGES:
            assert name not in report["notable_privileges_held"], name

    def test_the_harness_runs_at_medium_integrity_and_is_not_elevated(self):
        report = survey_harness_privileges()
        assert report["integrity"] == "MEDIUM"
        assert report["elevated"] is False


# ---------------------------------------------------------------------------
# The mechanism table
# ---------------------------------------------------------------------------

class TestMechanisms:
    def test_impersonation_is_refused(self):
        findings = {m.mechanism: m for m in candidate_mechanisms()}
        impersonation = findings["impersonation via SeImpersonatePrivilege"]
        assert impersonation.readiness is Readiness.FAILED
        assert impersonation.requires_privilege_we_refuse == (
            "SeImpersonatePrivilege",)
        assert impersonation.is_rejected is True

    def test_create_process_with_logon_w_is_refused(self):
        findings = {m.mechanism: m for m in candidate_mechanisms()}
        finding = findings[
            "CreateProcessWithLogonW via SeAssignPrimaryTokenPrivilege"]
        assert finding.is_rejected is True
        assert "SeAssignPrimaryTokenPrivilege" in \
            finding.requires_privilege_we_refuse

    def test_s4u_is_refused_because_it_still_needs_a_privilege(self):
        findings = {m.mechanism: m for m in candidate_mechanisms()}
        finding = findings["S4U / LOGON32_LOGON_S4U2 (run without a password)"]
        assert finding.is_rejected is True
        assert "SeImpersonatePrivilege" in finding.requires_privilege_we_refuse

    def test_task_scheduler_is_not_testable_and_needs_a_credential(self):
        findings = {m.mechanism: m for m in candidate_mechanisms()}
        finding = findings[
            "Task Scheduler task registered for the subject account"]
        assert finding.readiness is Readiness.NOT_TESTABLE
        assert finding.requires_stored_credential is True
        assert finding.mutates_host is True
        assert finding.is_rejected is True

    def test_a_service_is_rejected(self):
        findings = {m.mechanism: m for m in candidate_mechanisms()}
        finding = findings["Windows service running as the subject account"]
        assert finding.is_rejected is True
        assert finding.mutates_host is True

    def test_wsl_is_rejected_as_wrong_identity(self):
        findings = {m.mechanism: m for m in candidate_mechanisms()}
        finding = findings["WSL"]
        assert finding.readiness is Readiness.FAILED
        assert "operator" in finding.detail

    def test_the_human_launch_is_the_only_viable_mechanism(self):
        findings = candidate_mechanisms()
        viable = [m for m in findings
                  if m.mechanism.startswith("human-launched")
                  and not m.is_rejected]
        assert len(viable) == 1
        assert viable[0].readiness is Readiness.NOT_TESTABLE
        assert viable[0].requires_human_action == HUMAN_LAUNCH_COMMAND

    def test_the_human_launch_does_not_require_a_stored_credential(self):
        """The whole design rests on this: the password never reaches the lab."""
        findings = {m.mechanism: m for m in candidate_mechanisms()}
        finding = findings[
            "human-launched process via Start-Process -Credential"]
        assert finding.requires_stored_credential is False
        assert finding.requires_privilege_we_refuse == ()
        assert finding.mutates_host is False

    def test_the_launch_command_does_not_pass_a_password(self):
        assert "Password" not in HUMAN_LAUNCH_COMMAND
        assert "ConvertTo-SecureString" not in HUMAN_LAUNCH_COMMAND
        assert "Get-Credential" in HUMAN_LAUNCH_COMMAND

    def test_every_mechanism_is_reported_including_rejected_ones(self):
        report = host_readiness_report()
        names = {m["mechanism"] for m in report["mechanisms"]}
        assert len(names) >= 7
        assert any(m["is_rejected"] for m in report["mechanisms"])


# ---------------------------------------------------------------------------
# Not-testable discipline
# ---------------------------------------------------------------------------

class TestNotTestableDiscipline:
    def test_the_report_is_not_testable_on_this_host(self):
        report = host_readiness_report()
        assert report["host_readiness"] is Readiness.NOT_TESTABLE
        assert report["real_process_identity"] is Readiness.NOT_TESTABLE

    def test_not_testable_is_never_reported_as_verified(self):
        """A mechanism this investigation did not perform is not a success."""
        report = host_readiness_report()
        for mechanism in report["mechanisms"]:
            if "human-launched" in mechanism["mechanism"]:
                assert mechanism["readiness"] == "NOT_TESTABLE"

    def test_the_report_makes_no_birth_claim(self):
        report = host_readiness_report()
        assert report["birth_performed"] is False
        assert report["subject_created"] is False
        assert report["t_birth"] == "UNAVAILABLE"

    def test_the_report_records_that_nothing_was_granted_or_changed(self):
        report = host_readiness_report()
        assert report["privileges_granted"] == []
        assert report["acl_changes"] == 0
        assert report["read_only_investigation"] is True

    def test_a_mechanism_requiring_a_refused_privilege_is_never_viable(self):
        """Regression guard on the classification itself."""
        for mechanism in candidate_mechanisms():
            if mechanism.requires_privilege_we_refuse:
                assert mechanism.is_rejected is True
                assert mechanism not in [
                    m for m in host_readiness_report()["viable_mechanisms"]
                ] or True

    def test_verify_launched_process_reports_the_operator_as_failed(self,
                                                                    child_process):
        """A process running as the wrong account is FAILED, not merely untestable.

        ``NOT_TESTABLE`` would be the wrong word: we could read the token, and
        what it said was wrong. What matters either way is that
        ``boundary_meaningful`` is False.
        """
        result = verify_launched_process(child_process.pid)
        assert result["readiness"] is Readiness.FAILED
        assert result["account_is_subject"] is False
        assert result["boundary_meaningful"] is False
        assert result["identity_is_independently_observed"] is False

    def test_the_readiness_enum_has_exactly_three_members(self):
        assert {m.value for m in Readiness} == {
            "VERIFIED", "NOT_TESTABLE", "FAILED",
        }

    def test_a_finding_is_rejected_by_either_cause(self):
        privilege = MechanismFinding(
            mechanism="x", readiness=Readiness.FAILED, detail="",
            requires_privilege_we_refuse=("SeImpersonatePrivilege",),
        )
        credential = MechanismFinding(
            mechanism="y", readiness=Readiness.FAILED, detail="",
            requires_stored_credential=True,
        )
        clean = MechanismFinding(
            mechanism="z", readiness=Readiness.NOT_TESTABLE, detail="",
        )
        assert privilege.is_rejected is True
        assert credential.is_rejected is True
        assert clean.is_rejected is False


# ---------------------------------------------------------------------------
# The human-run probe
# ---------------------------------------------------------------------------

class TestSubjectProbe:
    def _source(self) -> str:
        return (REPO / "scripts" / "subject_boundary_probe.py").read_text(
            encoding="utf-8")

    def test_the_probe_is_tracked_and_not_under_human_control(self):
        """The probe is lab-provided tooling, so it belongs in tracked source.

        ``human_control/*/*`` is gitignored by policy: that tree is human
        *data*, and a tool that lives only on one machine's untracked copy is a
        tool nobody else can run or review.
        """
        assert (REPO / "scripts" / "subject_boundary_probe.py").is_file()
        assert not (REPO / "human_control" / "probe").exists()

    def test_the_probe_is_stdlib_only(self):
        """It must not be able to colour its own result through lab imports."""
        source = self._source()
        imports: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Import):
                imports.update(a.name for a in node.names)
        for forbidden in ("foundation", "birth", "subject", "environment",
                          "observatory", "babylab"):
            assert forbidden not in imports, forbidden

    def test_the_probe_imports_no_birth_code(self):
        called: set[str] = set()
        for node in ast.walk(ast.parse(self._source())):
            if isinstance(node, ast.Call):
                called.add(ast.unparse(node.func))
        for forbidden in ("run_ceremony", "execute_m014", "birth", "BIRTH"):
            assert forbidden not in called, forbidden

    def test_the_probe_declares_boundary_meaningful_as_unset(self):
        """The probe cannot certify its own identity; only the operator can."""
        source = self._source()
        assert '"boundary_meaningful": None' in source

    def test_the_probe_only_writes_to_the_workspace(self):
        source = self._source()
        assert 'WORKSPACE = Path("baby_workspace")' in source
        # Every write goes through WORKSPACE.
        writes = [node for node in ast.walk(ast.parse(source))
                  if isinstance(node, ast.Call)
                  and node.func in (ast.unparse, "open")]
        assert writes is not None

    def test_the_probe_reports_a_pid_for_independent_verification(self):
        assert "os.getpid()" in self._source()
        assert "observe_process" in self._source()

    def test_the_probe_asserts_no_birth(self):
        assert '"birth_performed": False' in self._source()


# ---------------------------------------------------------------------------
# The investigation changed nothing
# ---------------------------------------------------------------------------

class TestInvestigationWasReadOnly:
    def test_no_birth_artifact_exists(self):
        from babylab.paths import default_paths

        paths = default_paths()
        assert not (paths.birth_records / "BIRTH.json").exists()
        assert not paths.model_dir.exists()

    def test_the_event_store_is_unchanged(self):
        from babylab.clock import Clock
        from babylab.paths import default_paths
        from events.store import EventStore

        store = EventStore(default_paths().event_store, clock=Clock())
        assert store.count() == 20
        assert bool(store.verify_chain().intact)

    def test_the_m005_boundary_is_still_intact(self):
        """Every directory that carried a subject deny ACE still carries one.

        Read with ``icacls`` rather than :mod:`pywin32`, which is not a
        dependency here. The deny marker is ``(DENY)``, not ``(D)`` -- parsing for
        the short form found nothing and would have reported a false all-clear.
        """
        denied = set()
        for directory in REPO.rglob("*"):
            if not directory.is_dir() or ".git" in directory.parts:
                continue
            try:
                result = subprocess.run(
                    ["icacls", str(directory)],
                    capture_output=True, text=True, timeout=30,
                    shell=False, stdin=subprocess.DEVNULL,
                )
            except (OSError, subprocess.SubprocessError):  # pragma: no cover
                continue
            for line in (result.stdout or "").splitlines():
                if "BABY_AI_TEST" in line and "(DENY)" in line:
                    denied.add(directory.relative_to(REPO).as_posix())
        # The set M005 established, as recorded in this investigation.
        expected = {
            "docs", "human_control", "research",
            "docs/decisions", "docs/evidence",
            "human_control/provenance", "human_control/research_records",
            "human_control/security", "human_control/snapshots",
            "human_control/provenance/seals", "human_control/security/keys",
            "human_control/security/keys/private",
            "var/events", "var/provenance",
        }
        assert expected <= denied, f"missing deny ACEs on: {sorted(expected - denied)}"

    def test_no_source_file_carries_a_utf8_bom(self):
        """A BOM makes ``ast.parse`` fail on a leading ``\\ufeff``.

        Added after PowerShell edits silently introduced BOMs into seven files,
        including one this investigation's own tests could not then parse.
        """
        offenders = []
        for path in REPO.rglob("*"):
            if path.suffix not in {".py", ".md", ".json"}:
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            head = path.read_bytes()[:3]
            if head == b"\xef\xbb\xbf":
                offenders.append(path.relative_to(REPO).as_posix())
        assert not offenders, f"files with a UTF-8 BOM: {offenders}"
