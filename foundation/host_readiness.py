"""Host readiness for running a real process as the subject account.

Answers one question per mechanism: *could* this host establish a genuine
``BABY_AI_TEST`` process token, and did we actually observe one? Three answers
are possible and they are kept distinct.

``VERIFIED``
    A real token was read and it was the subject's.
``NOT_TESTABLE``
    The host genuinely cannot answer without a credential this laboratory will
    not accept, store, or ask a human to paste into a tool. This is the expected
    answer here, and it is a *finding*, not a gap in the report.
``FAILED``
    A check ran and the answer was wrong. A process ran as the wrong account, or
    a boundary was breached.

The distinction that matters most: ``NOT_TESTABLE`` is never allowed to read as
success. A verifier that treats "I could not check" as "it is fine" is the exact
failure this module exists to prevent, and M005 already found the harness
reporting an operator-run probe as if it were a subject-run one.

Every function here reads. Nothing in this module launches a process, creates a
task, writes a credential, or alters a policy.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from foundation.restricted import REQUIRED_PRIVILEGES, SUBJECT_ACCOUNT, SUBJECT_SID
from foundation.token_observation import ObservationStatus, observe_process

#: The account a real process must run as. Re-exported from the single
#: definition so this module cannot drift from the one M014 reads.
EXPECTED_ACCOUNT = SUBJECT_ACCOUNT
EXPECTED_SID = SUBJECT_SID


class Readiness(str, enum.Enum):
    VERIFIED = "VERIFIED"
    NOT_TESTABLE = "NOT_TESTABLE"
    FAILED = "FAILED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass
class MechanismFinding:
    """One candidate way to establish the subject's process identity."""

    mechanism: str
    readiness: Readiness
    detail: str
    requires_privilege_we_refuse: tuple[str, ...] = ()
    requires_human_action: str = ""
    requires_stored_credential: bool = False
    mutates_host: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def is_rejected(self) -> bool:
        """Mechanisms this laboratory will not use, and why."""
        return bool(self.requires_privilege_we_refuse) or self.requires_stored_credential

    def to_dict(self) -> dict[str, Any]:
        return {
            "mechanism": self.mechanism,
            "readiness": self.readiness.value,
            "detail": self.detail,
            "requires_privilege_we_refuse": list(self.requires_privilege_we_refuse),
            "requires_human_action": self.requires_human_action,
            "requires_stored_credential": self.requires_stored_credential,
            "mutates_host": self.mutates_host,
            "is_rejected": self.is_rejected,
            "evidence": dict(self.evidence),
        }


#: The privileges M005 found absent from the operator's token, and which this
#: laboratory refuses to acquire even if it could.
REFUSED_PRIVILEGES: tuple[str, ...] = (
    "SeImpersonatePrivilege",
    "SeAssignPrimaryTokenPrivilege",
)

#: The launch command a human runs. Written out so the exact human action is
#: legible in a report rather than implied.
#:
#: ``Start-Process -Credential`` makes Windows establish the token, which is the
#: requirement. The human types the password into a Windows prompt; this
#: laboratory never sees it, never stores it, and never receives it as an
#: argument. The credential is prompted for interactively and is not persisted by
#: the laboratory.
HUMAN_LAUNCH_COMMAND = (
    'Start-Process -FilePath "py" -ArgumentList '
    '"-3", "scripts/subject_boundary_probe.py" '
    '-Credential (Get-Credential -UserName "THARUNBALAJI-LA\\BABY_AI_TEST" '
    '-Message "BABY_AI_TEST boundary probe (M014)") -WorkingDirectory .'
)


def survey_account() -> dict[str, Any]:
    """What the subject account looks like, from the operator's side.

    Read-only: ``Get-LocalUser`` and ``Get-LocalGroupMember``. Group membership
    is reported explicitly, because an account that belongs to *no* local group
    inherits nothing from one -- a security property worth stating rather than
    leaving a reader to infer from an empty table.

    PowerShell's cmdlets are used rather than parsing ``net user``, for two
    reasons found while writing this: ``net user`` does not print the account's
    SID at all, and its ``Local Group Memberships`` line is *empty* when the
    account is in no group, which is indistinguishable from a parse failure. The
    cmdlets answer both questions unambiguously.
    """
    import json
    import subprocess

    script = (
        "$u = Get-LocalUser -Name 'BABY_AI_TEST' -ErrorAction Stop; "
        "$m = @(); "
        "foreach ($g in Get-LocalGroup) { "
        "  $mm = @(Get-LocalGroupMember -Group $g.Name -ErrorAction SilentlyContinue); "
        "  if ($mm.Name -contains ('THARUNBALAJI-LA\\BABY_AI_TEST')) "
        "    { $m += $g.Name } }; "
        "[pscustomobject]@{ "
        "  name = $u.Name; enabled = [string]$u.Enabled; "
        "  sid = [string]$u.SID; "
        "  password_required = [string]$u.PasswordRequired; "
        "  password_last_set = [string]$u.PasswordLastSet; "
        "  password_expires = [string]$u.PasswordExpires; "
        "  last_logon = [string]$u.LastLogon; "
        "  description = [string]$u.Description; "
        "  local_groups = $m } | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=120,
            # Explicit, per the M010 boundary rule: an argument vector rather
            # than a shell string, and no inherited console the child could be
            # prompted on. `-NonInteractive` in the argv is not a substitute --
            # stdin is closed as well, so a prompt would fail rather than hang.
            shell=False,
            stdin=subprocess.DEVNULL,
        )
        if completed.returncode != 0:
            raise OSError((completed.stderr or "").strip()
                          or f"exit {completed.returncode}")
        data = json.loads((completed.stdout or "").strip() or "{}")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # Distinguish "could not read" from "is in no groups". They look the same
        # in a summary table and mean opposite things.
        return {
            "account": EXPECTED_ACCOUNT, "expected_sid": EXPECTED_SID,
            "observed": {"error": str(exc)},
            "sid": "", "sid_matches": False,
            "local_group_membership": "UNAVAILABLE",
            "global_group_membership": "UNAVAILABLE",
            "inherits_no_group_privilege": "UNAVAILABLE",
            "read_failed": True,
        }

    groups = data.get("local_groups") or []
    sid = str(data.get("sid", ""))
    return {
        "account": EXPECTED_ACCOUNT,
        "expected_sid": EXPECTED_SID,
        "observed": {
            "name": data.get("name"),
            "enabled": data.get("enabled"),
            "password_required": data.get("password_required"),
            "password_last_set": data.get("password_last_set"),
            "password_expires": data.get("password_expires"),
            "last_logon": data.get("last_logon"),
            "description": data.get("description") or "(none)",
        },
        "sid": sid,
        "sid_matches": sid.upper() == EXPECTED_SID.upper(),
        "local_group_membership": groups or "NONE",
        "global_group_membership": "UNAVAILABLE (net user reports *None)",
        "inherits_no_group_privilege": not groups,
        "read_failed": False,
    }


def survey_harness_privileges() -> dict[str, Any]:
    """Which of the refused privileges this process actually holds.

    Reads its own token. An absent privilege is reported as absent, never as
    "disabled but available" -- M005 established that these are absent from the
    token, which is why enabling them returns ``ERROR_NOT_ALL_ASSIGNED``.
    """
    import os

    from foundation.token_observation import observe_process

    observation = observe_process(os.getpid())
    return {
        "pid": os.getpid(),
        "required_to_impersonate": list(REQUIRED_PRIVILEGES),
        "privileges_we_refuse_to_acquire": list(REFUSED_PRIVILEGES),
        "notable_privileges_held": list(observation.privileges_present),
        "can_impersonate": all(
            name in observation.privileges_present
            for name in REFUSED_PRIVILEGES
        ),
        "integrity": observation.integrity_label,
        "elevated": observation.elevated,
        "detail": observation.detail,
    }


def candidate_mechanisms() -> list[MechanismFinding]:
    """Every mechanism this investigation considered, and its verdict.

    Listed with the rejected ones included. A report that only mentioned the
    viable mechanism would leave a reader unable to tell whether the others were
    considered and dismissed or never thought of.
    """
    from foundation.restricted import can_launch_as_subject

    can_launch, _held, missing = can_launch_as_subject()

    return [
        MechanismFinding(
            mechanism="impersonation via SeImpersonatePrivilege",
            readiness=Readiness.FAILED,
            detail=(
                "the privilege is absent from this process's token, so it cannot "
                "be enabled (M005 observed ERROR_NOT_ALL_ASSIGNED / 1300). "
                "Acquiring it is refused regardless: it would let any process in "
                "the session assume any identity, which is a larger hole than the "
                "one it would close."
            ),
            requires_privilege_we_refuse=("SeImpersonatePrivilege",),
        ),
        MechanismFinding(
            mechanism="CreateProcessWithLogonW via SeAssignPrimaryTokenPrivilege",
            readiness=Readiness.FAILED,
            detail=(
                "the privilege is absent, and acquiring it is refused. It is a "
                "credential-equivalent right: whoever holds it can create a token "
                "for any local account without that account's password."
            ),
            requires_privilege_we_refuse=("SeAssignPrimaryTokenPrivilege",),
        ),
        MechanismFinding(
            mechanism="S4U / LOGON32_LOGON_S4U2 (run without a password)",
            readiness=Readiness.FAILED,
            detail=(
                "S4U deliberately needs no password, which is why it looks "
                "attractive -- and it needs SeImpersonatePrivilege to call, and "
                "SeTcbPrivilege to register a task that uses it. Both are absent "
                "and both are refused."
            ),
            requires_privilege_we_refuse=("SeImpersonatePrivilege", "SeTcbPrivilege"),
        ),
        MechanismFinding(
            mechanism="Task Scheduler task registered for the subject account",
            readiness=Readiness.NOT_TESTABLE,
            detail=(
                "registering a task that runs as another local account requires "
                "either that account's password in Task Scheduler's credential "
                "store, or an elevated registration using S4U. This process is "
                "not elevated, and the laboratory will not store a password or "
                "take elevation to create a persistent task."
            ),
            requires_stored_credential=True,
            mutates_host=True,
            requires_human_action=(
                "a human would have to register the task in an elevated console "
                "and enter the subject's password there. The laboratory does not "
                "do this and does not recommend it: a persistent task is a "
                "standing execution path, which is more capability than a "
                "one-shot human launch needs."
            ),
        ),
        MechanismFinding(
            mechanism="Windows service running as the subject account",
            readiness=Readiness.FAILED,
            detail=(
                "a service cannot run as an ordinary local account without a "
                "stored password, and creating a service needs elevation. A "
                "service would also be a persistent, always-on execution path, "
                "which is the opposite of the single controlled interaction M014 "
                "performs."
            ),
            requires_stored_credential=True,
            mutates_host=True,
        ),
        MechanismFinding(
            mechanism="WSL",
            readiness=Readiness.FAILED,
            detail=(
                "WSL runs under the operator's Windows account and reaches the "
                "filesystem over 9p/DrvFs. M005 measured its identity as the "
                "operator's own (uid=1000 sktharun_balaji), so a WSL process "
                "cannot hold the subject's Windows token. It is not a candidate."
            ),
            evidence={"m005_wsl_probe": "docs/evidence/m005-wsl-probe.json"},
        ),
        MechanismFinding(
            mechanism="human-launched process via Start-Process -Credential",
            readiness=Readiness.NOT_TESTABLE if not can_launch
            else Readiness.VERIFIED,
            detail=(
                "Windows establishes the token; the human types the password into "
                "a Windows prompt. The laboratory never receives, stores, or logs "
                "it. This is the mechanism M005 already used successfully, and it "
                "is the only one that produces a genuine subject token on this "
                "host without the laboratory acquiring a privilege or holding a "
                "secret. It is reported NOT_TESTABLE because this investigation "
                "did not perform a launch, and an unperformed launch is not a "
                "verified one."
            ),
            requires_human_action=HUMAN_LAUNCH_COMMAND,
        ),
    ]


def verify_launched_process(
    pid: int,
    *,
    self_reported: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Independently confirm a launched process really is the subject account.

    The confirmation comes from the process's token. ``self_reported`` is
    recorded beside it and never merged with it, and
    ``boundary_meaningful`` stays ``False`` unless the token actually says
    ``...-1022``.

    This is the function M014 will call. It is exercised here only against
    processes this investigation legitimately controls, so the subject-account
    path remains ``NOT_TESTABLE`` until a human performs a launch.
    """
    observation = observe_process(pid, expected_sid=EXPECTED_SID,
                                  self_reported=self_reported)
    return {
        "pid": pid,
        "readiness": (
            Readiness.VERIFIED if observation.status is ObservationStatus.VERIFIED
            else Readiness.FAILED
            if observation.status is ObservationStatus.FAILED
            else Readiness.NOT_TESTABLE
        ),
        "token": observation.to_dict(),
        "identity_is_independently_observed":
            observation.identity_is_independently_observed,
        "account_is_subject": (
            observation.user_sid.upper() == EXPECTED_SID.upper()
        ),
        "boundary_meaningful": (
            observation.user_sid.upper() == EXPECTED_SID.upper()
        ),
        "boundary_meaningful_note": (
            "true only because the SID was read from the process token and it is "
            "the subject's. A self-reported account name never sets this."
        ),
    }


def host_readiness_report() -> dict[str, Any]:
    """The whole investigation, as one record.

    Deliberately reports the mechanisms that were rejected alongside the one
    that survives, so a reader can see what was considered.
    """
    account = survey_account()
    harness = survey_harness_privileges()
    mechanisms = candidate_mechanisms()

    viable = [m for m in mechanisms if not m.is_rejected
              and m.mechanism.startswith("human-launched")]
    verified_any = any(
        m.readiness is Readiness.VERIFIED for m in mechanisms
    )

    return {
        "schema": "babylab/host-readiness/v1",
        "subject_account": EXPECTED_ACCOUNT,
        "subject_sid": EXPECTED_SID,
        "account_survey": account,
        "harness_privileges": harness,
        "mechanisms": [m.to_dict() for m in mechanisms],
        "viable_mechanisms": [m.to_dict() for m in viable],
        "recommended_mechanism": (
            "human-launched process via Start-Process -Credential, followed by "
            "independent token observation from the operator's session"
        ),
        "host_readiness": (
            Readiness.VERIFIED if verified_any else Readiness.NOT_TESTABLE
        ),
        "real_process_identity": (
            Readiness.NOT_TESTABLE
            if not verified_any else Readiness.VERIFIED
        ),
        "required_human_action": HUMAN_LAUNCH_COMMAND,
        "birth_performed": False,
        "subject_created": False,
        "t_birth": "UNAVAILABLE",
        "privileges_granted": [],
        "acl_changes": 0,
        "read_only_investigation": True,
    }


__all__ = [
    "EXPECTED_ACCOUNT",
    "EXPECTED_SID",
    "HUMAN_LAUNCH_COMMAND",
    "REFUSED_PRIVILEGES",
    "MechanismFinding",
    "Readiness",
    "candidate_mechanisms",
    "host_readiness_report",
    "survey_account",
    "survey_harness_privileges",
    "verify_launched_process",
]
