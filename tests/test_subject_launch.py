"""Tests for the subject-account launch mechanism.

The human's ``Start-Process -FilePath "py"`` failed with *"The file cannot be
accessed by the system."* The cause is a per-user App Execution Alias, not a
birth problem and not a fact about ``BABY_AI_TEST``.

These tests pin the properties of the launch command that must hold whenever it
is eventually generated:

1. it names an absolute interpreter
2. it does not route through a shell
3. it names an absolute probe path
4. it names an absolute working directory
5. it embeds no password
6. it changes no security policy
7. independent identity verification stays token-based

**No test here claims ``BABY_AI_TEST`` execution.** The account cannot be
launched from this harness without a credential the laboratory will not accept,
so ``launch_readiness()['ready']`` is asserted to be ``False`` and the reason is
asserted to be the interpreter. A test asserting a successful subject launch
could only pass by faking the one thing this work exists to establish.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from foundation.host_readiness import HUMAN_LAUNCH_COMMAND, Readiness
from foundation.subject_launch import (
    APP_EXECUTION_ALIAS_DIR,
    REACHABLE_PRINCIPALS,
    build_launch_command,
    describe_executable,
    launch_readiness,
    operator_interpreter,
    probe_path,
    reachable_by_subject,
    shim_paths,
)
from foundation.token_observation import ObservationStatus, observe_process

REPO = Path(__file__).resolve().parents[1]

PYTHON_EXE = r"C:\Python\python.exe"
PROBE = r"C:\dev\TharAI-EXP\scripts\subject_boundary_probe.py"
WORKDIR = r"C:\dev\TharAI-EXP"


@pytest.fixture(scope="module")
def command() -> str:
    return build_launch_command(PYTHON_EXE, PROBE, WORKDIR)


# ---------------------------------------------------------------------------
# 1-4: the command's shape
# ---------------------------------------------------------------------------

class TestLaunchCommandShape:
    def test_1_the_executable_is_absolute(self, command):
        assert f'-FilePath "{PYTHON_EXE}"' in command
        assert "py.exe" not in command
        assert APP_EXECUTION_ALIAS_DIR not in command

    def test_1b_a_relative_executable_is_refused(self):
        """A relative interpreter is the exact bug that was just diagnosed."""
        with pytest.raises(ValueError, match="absolute"):
            build_launch_command("py.exe", PROBE, WORKDIR)

    def test_1c_the_app_execution_alias_is_identified_on_this_host(self):
        """The shim that failed is recognised as a shim, not an interpreter."""
        shims = [s for s in shim_paths() if s.is_app_execution_alias]
        assert shims, "expected at least one App Execution Alias on PATH"
        for shim in shims:
            assert APP_EXECUTION_ALIAS_DIR in shim.path
            assert shim.reachable_by_subject is False
            assert "per-user shim" in shim.detail

    def test_2_the_command_uses_no_shell(self, command):
        lowered = command.lower()
        for forbidden in ("cmd.exe", "cmd /c", "/c ", "powershell",
                          "shell=true", "-command", "invoke-expression",
                          "start-process powershell"):
            assert forbidden not in lowered, forbidden

    def test_2b_the_command_is_executable_to_probe_directly(self, command):
        """The argv is FilePath -> ArgumentList, with nothing in between."""
        assert "-ArgumentList" in command
        # Exactly one program is named: the interpreter.
        programs = re.findall(r'"([A-Za-z]:\\[^"]+)"', command)
        assert programs[0] == PYTHON_EXE
        assert programs[1] == PROBE
        assert programs[2] == WORKDIR

    def test_3_the_probe_path_is_absolute(self, command):
        assert f'-ArgumentList "{PROBE}"' in command
        assert "\\dev\\" in PROBE

    def test_3b_a_relative_probe_is_refused(self):
        with pytest.raises(ValueError, match="absolute"):
            build_launch_command(PYTHON_EXE, "scripts/probe.py", WORKDIR)

    def test_3c_the_probe_is_not_under_human_control(self):
        """human_control/*/* is gitignored: human data, not lab source."""
        resolved = probe_path(REPO)
        assert resolved.is_file()
        assert "human_control" not in resolved.parts
        assert str(resolved) == PROBE

    def test_4_the_working_directory_is_absolute(self, command):
        assert f'-WorkingDirectory "{WORKDIR}"' in command

    def test_4b_a_relative_working_directory_is_refused(self):
        with pytest.raises(ValueError, match="absolute"):
            build_launch_command(PYTHON_EXE, PROBE, ".")

    def test_4c_the_repository_path_is_derived_not_assumed(self):
        """Not from the operator's home directory."""
        resolved = str(REPO.resolve())
        assert resolved == WORKDIR
        assert "TharAI-EXP" in resolved


# ---------------------------------------------------------------------------
# 5-6: nothing sensitive in the command
# ---------------------------------------------------------------------------

class TestLaunchCommandContainsNoSecrets:
    def test_5_no_password_is_embedded(self, command):
        lowered = command.lower()
        assert "password" not in lowered
        assert "convertto-securestring" not in lowered
        assert "plaintext" not in lowered
        # Present as a *prompt*, not as a secret.
        assert "-credential" in lowered

    def test_5b_the_credential_is_a_prompt(self, command):
        assert "Get-Credential" in command
        assert 'THARUNBALAJI-LA\\BABY_AI_TEST' in command

    def test_5c_the_recorded_human_command_has_the_same_safety(self):
        lowered = HUMAN_LAUNCH_COMMAND.lower()
        assert "password" not in lowered
        assert "convertto-securestring" not in lowered
        assert "cmd.exe" not in lowered

    def test_6_the_command_changes_no_security_policy(self, command):
        lowered = command.lower()
        for forbidden in ("icacls", "set-acl", "secedit", "net user",
                          "gpedit", "secpol", "new-localservice",
                          "register-scheduledtask", "new-service",
                          "add-localgroupmember", "ntrights", "privileges",
                          "uac", "secpol.msc", "reg add", "set-itemproperty"):
            assert forbidden not in lowered, forbidden

    def test_6b_the_module_builds_only_a_command(self):
        """The module must not be able to run the launch it constructs."""
        source = (REPO / "foundation" / "subject_launch.py").read_text(
            encoding="utf-8")
        called: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                called.add(ast.unparse(node.func))
        for forbidden in ("Start-Process", "CreateProcessWithLogonW",
                          "LogonUser", "runas", "Popen"):
            assert forbidden not in called, forbidden
        # The only subprocess use is a read-only inspection helper.
        assert "subprocess.run" in called
        assert any("subprocess.run" in name for name in called)

    def test_6c_inspection_commands_are_read_only(self):
        source = (REPO / "foundation" / "subject_launch.py").read_text(
            encoding="utf-8")
        for argv in re.findall(r'_run\(\[(.*?)\]', source, re.S):
            for forbidden in ("icacls", "/set", "/grant", "/deny", "/remove",
                              "net", "sc", "reg"):
                if forbidden in argv:
                    assert "/set" not in argv and "/grant" not in argv
        assert 'shell=False' in source
        assert "stdin=subprocess.DEVNULL" in source


# ---------------------------------------------------------------------------
# 7: identity verification stays token-based
# ---------------------------------------------------------------------------

class TestTokenObservationUnchanged:
    def test_7_the_observation_method_is_still_token_based(self):
        source = (REPO / "foundation" / "token_observation.py").read_text(
            encoding="utf-8")
        for required in ("OpenProcess", "OpenProcessToken",
                         "GetTokenInformation", "ConvertSidToStringSidW"):
            assert required in source, required
        assert "TokenUser" in source or "token_user" in source.lower()

    def test_7b_it_does_not_fall_back_to_whoami(self):
        """A self-report is not evidence, so the module must not parse one."""
        source = (REPO / "foundation" / "token_observation.py").read_text(
            encoding="utf-8")
        called: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                called.add(ast.unparse(node.func))
        for forbidden in ("subprocess.run", "subprocess.check_output", "Popen"):
            assert forbidden not in called, forbidden

    def test_7c_an_unreadable_token_is_not_testable_not_a_pass(self):
        observation = observe_process(999_999_999)
        assert observation.status is ObservationStatus.NOT_TESTABLE
        assert observation.identity_is_independently_observed is False

    def test_7d_the_privilege_reader_agrees_with_whoami(self):
        """A positive control on the privilege table layout.

        Regression. ``LUID`` was declared as a 64-bit integer, which aligns to 8
        and makes ``LUID_AND_ATTRIBUTES`` 16 bytes instead of Windows' 12, so the
        privilege array was walked with the wrong stride. That produced a *false*
        claim -- ``SeRestorePrivilege`` reported as held by a token that does not
        hold it. A verifier that invents a privilege is worse than one that
        reports none, so the layout is pinned here against ``whoami /priv``.
        """
        import ctypes
        import os
        import subprocess

        from foundation.token_observation import (
            _ADVAPI_ALIASES,
            _CLASS_TOKEN_PRIVILEGES,
            _LUID_AND_ATTRIBUTES,
            _TOKEN_PRIVILEGES,
            _query,
        )

        # Windows declares LUID as two 32-bit halves, so the struct is 12 bytes
        # and the array begins at offset 4.
        assert ctypes.sizeof(_LUID_AND_ATTRIBUTES) == 12
        assert _TOKEN_PRIVILEGES.Privileges.offset == 4

        buffer, _ = _query(os.getpid(), _CLASS_TOKEN_PRIVILEGES)
        header = ctypes.cast(buffer, ctypes.POINTER(_TOKEN_PRIVILEGES)).contents
        entries = ctypes.cast(
            ctypes.byref(buffer, _TOKEN_PRIVILEGES.Privileges.offset),
            ctypes.POINTER(_LUID_AND_ATTRIBUTES),
        )
        held = {entries[i].luid_value for i in range(header.PrivilegeCount)}
        assert held, "the harness token should hold some privileges"

        # Every privilege `whoami /priv` reports must be found by the reader.
        import re as _re

        reported = subprocess.run(
            ["whoami", "/priv"], capture_output=True, text=True, timeout=60,
            shell=False, stdin=subprocess.DEVNULL,
        ).stdout
        names = _re.findall(r"^\s*(Se\w+Privilege)\s", reported, _re.MULTILINE)
        assert names, "could not parse whoami /priv output"
        for name in names:
            descriptor = _LUID_AND_ATTRIBUTES()
            assert _ADVAPI_ALIASES.LookupPrivilegeValueW(
                None, name, ctypes.byref(descriptor))
            assert descriptor.luid_value in held, (
                f"{name} is reported by whoami but not found by the reader"
            )

    def test_7e_the_refused_privileges_are_reported_absent(self):
        """The claim the whole investigation rests on, checked against the token."""
        import os

        from foundation.token_observation import _NOTABLE_PRIVILEGES

        observation = observe_process(os.getpid())
        for name in ("SeImpersonatePrivilege", "SeAssignPrimaryTokenPrivilege"):
            if name in _NOTABLE_PRIVILEGES:
                assert name not in observation.privileges_present, name


# ---------------------------------------------------------------------------
# Readiness on this host
# ---------------------------------------------------------------------------

class TestLaunchReadiness:
    def test_the_launch_is_not_ready(self):
        """The honest answer, asserted so it cannot be quietly inverted."""
        readiness = launch_readiness(REPO)
        assert readiness["ready"] is False
        assert readiness["executed"] is False
        assert readiness["credentials_handled"] is False

    def test_the_blocker_is_the_interpreter(self):
        readiness = launch_readiness(REPO)
        assert readiness["blocking"], "expected at least one blocker"
        assert any("interpreter" in blocker for blocker in readiness["blocking"])

    def test_no_command_is_offered_while_blocked(self):
        """A command that cannot work is worse than no command."""
        readiness = launch_readiness(REPO)
        assert readiness["launch_command"].startswith("UNAVAILABLE")

    def test_the_interpreter_is_identified_precisely(self):
        interpreter = operator_interpreter()
        assert interpreter.exists is True
        assert interpreter.is_file is True
        assert interpreter.is_app_execution_alias is False
        assert len(interpreter.sha256) == 64
        assert interpreter.size_bytes and interpreter.size_bytes > 0
        assert interpreter.pe_machine in {"x64", "x86", "arm64"}

    def test_the_interpreter_is_unreachable_because_of_its_ancestors(self):
        """Not because the file denies it, but because a parent is private."""
        interpreter = operator_interpreter()
        assert interpreter.reachable_by_subject is False
        assert interpreter.blocking_principals, "expected a blocking ancestor"

    def test_the_probe_and_repository_are_reachable(self):
        """Isolates the fault: the target is fine, the interpreter is not."""
        readiness = launch_readiness(REPO)
        assert readiness["probe"]["reachable_by_subject"] is True
        assert readiness["repository_reachability"]["reachable"] is True

    def test_the_principal_set_names_the_account_explicitly(self):
        """The account is in no group, so a group-based check alone would miss it."""
        assert "BABY_AI_TEST" in REACHABLE_PRINCIPALS
        assert "BUILTIN\\Users" in REACHABLE_PRINCIPALS

    def test_a_deny_is_not_mistaken_for_a_grant(self):
        """M005 denies writes to protected paths while granting reads.

        A reachability check that treated a DENY as an ALLOW would report the
        protected directories as reachable and quietly defeat the boundary.
        """
        from foundation.subject_launch import _acl_principals

        principals = _acl_principals(REPO / "var" / "events")
        assert any("BABY_AI_TEST" in p and p.endswith("DENY") for p in principals)
        assert any("BUILTIN\\Users" in p and p.endswith("ALLOW")
                   for p in principals)

    def test_the_repository_is_reachable_despite_the_m005_denies(self):
        """Read access must still be granted, or nothing could ever be verified."""
        assert reachable_by_subject(REPO)["reachable"] is True

    def test_a_missing_executable_is_reported_not_raised(self):
        facts = describe_executable(r"C:\definitely\not\here\python.exe")
        assert facts.exists is False
        assert "does not exist" in facts.detail
        assert facts.sha256 == "UNAVAILABLE"

    def test_host_readiness_stays_not_testable(self):
        """No launch happened, so readiness is unchanged from the investigation."""
        from foundation.host_readiness import host_readiness_report

        report = host_readiness_report()
        assert report["host_readiness"] is Readiness.NOT_TESTABLE
        assert report["real_process_identity"] is Readiness.NOT_TESTABLE


# ---------------------------------------------------------------------------
# The investigation changed nothing
# ---------------------------------------------------------------------------

class TestNothingWasChanged:
    def test_the_account_is_untouched(self):
        from foundation.host_readiness import survey_account

        survey = survey_account()
        assert survey["read_failed"] is False
        assert survey["sid_matches"] is True
        assert survey["inherits_no_group_privilege"] is True

    def test_no_privilege_is_held(self):
        from foundation.host_readiness import survey_harness_privileges

        report = survey_harness_privileges()
        assert report["can_impersonate"] is False
        assert report["notable_privileges_held"] == []

    def test_no_birth_artifact_exists(self):
        from babylab.paths import default_paths

        paths = default_paths()
        assert not (paths.birth_records / "BIRTH.json").exists()
        assert not paths.model_dir.exists()

    def test_the_event_log_is_unchanged(self):
        from babylab.clock import Clock
        from babylab.paths import default_paths
        from events.store import EventStore

        store = EventStore(default_paths().event_store, clock=Clock())
        assert store.count() == 20
        assert bool(store.verify_chain().intact)

    def test_the_m005_boundary_is_still_intact(self):
        denied = set()
        for directory in REPO.rglob("*"):
            if not directory.is_dir() or ".git" in directory.parts:
                continue
            import subprocess

            result = subprocess.run(
                ["icacls", str(directory)], capture_output=True, text=True,
                timeout=30, shell=False, stdin=subprocess.DEVNULL,
            )
            for line in (result.stdout or "").splitlines():
                if "BABY_AI_TEST" in line and "(DENY)" in line:
                    denied.add(directory.relative_to(REPO).as_posix())
        expected = {
            "docs", "human_control", "research",
            "docs/decisions", "docs/evidence",
            "human_control/provenance", "human_control/research_records",
            "human_control/security", "human_control/snapshots",
            "human_control/provenance/seals", "human_control/security/keys",
            "human_control/security/keys/private",
            "var/events", "var/provenance",
        }
        assert expected <= denied, f"missing: {sorted(expected - denied)}"
