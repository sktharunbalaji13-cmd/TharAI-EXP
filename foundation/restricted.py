"""M011 restricted execution: launch the runtime as ``BABY_AI_TEST``.

The requirement M011 exists to satisfy
--------------------------------------
M010 reported ``filesystem restriction = NOT_ESTABLISHED`` because the intended
runtime process had never been exercised under the restricted account. Closing
that gap means *actually launching* a process as that account and observing what
it can reach. Inspecting the ACLs is not the same measurement, and neither is
running the runtime as the operator and reasoning about what the account would
have found.

Three ways to launch as another account, and why two of them are refusals
-----------------------------------------------------------------------

1. ``CreateProcessWithTokenW`` from a logon token -- needs a password.
   **Refused by design.** The password would have to be typed, stored, or passed
   on a command line, and every one of those leaks it. This module never asks
   for a password and never accepts one.
2. ``CreateProcessAsUser`` with a duplicated token from an existing process --
   needs ``SeImpersonatePrivilege`` (or ``SeAssignPrimaryTokenPrivilege``).
   **This is the correct mechanism**, and it is attempted first. When the
   privilege is absent the attempt is reported as ``NOT_TESTABLE`` with the real
   Win32 error.
3. ``runas`` -- prompts interactively for a credential and cannot be
   automated. **Refused**: an unattended harness must not block on a console
   prompt, and a harness that waits for one is indistinguishable from a hung
   one.

When none of those is available the answer is ``NOT_TESTABLE`` with the reason.
It is *not* a fallback to running as the operator. That fallback is the exact
failure this milestone forbids: a run under the administrator token would look
successful and would prove nothing about the restricted identity.

What the child is asked to do
-----------------------------
The child runs :mod:`foundation.probe`, which is the code that touches protected
paths and the workspace. Passing the *probe* rather than the whole runtime keeps
the identity measurement honest: the thing interrogated is the process that
actually attempted the access, not a helper that merely describes it.
"""

from __future__ import annotations

import enum
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The account M005 established. Named here, resolved from the M005 evidence, and
#: never inferred from "whatever restricted user exists on this machine".
SUBJECT_ACCOUNT = "BABY_AI_TEST"
SUBJECT_DOMAIN = "THARUNBALAJI-LA"
SUBJECT_SID = "S-1-5-21-2406520953-1060965512-844951592-1022"

#: Privileges that would permit launching as another identity.
REQUIRED_PRIVILEGES = (
    "SeImpersonatePrivilege",
    "SeAssignPrimaryTokenPrivilege",
)


class LaunchState(str, enum.Enum):
    """What a launch attempt achieved. Never includes a silent fallback."""

    VERIFIED = "VERIFIED"
    #: The mechanism is available and the launch happened.
    LAUNCHED = "LAUNCHED"
    #: The mechanism is unavailable on this host. The reason is recorded.
    NOT_TESTABLE = "NOT_TESTABLE"
    #: The launch was attempted and failed. The Win32 error is recorded.
    FAILED = "FAILED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass
class LaunchResult:
    """The outcome of attempting to run something as the restricted account."""

    state: LaunchState
    account: str = f"{SUBJECT_DOMAIN}\\{SUBJECT_ACCOUNT}"
    expected_sid: str = SUBJECT_SID
    observed: Any = None
    detail: str = ""
    mechanism: str = ""
    privileges_held: list[str] = field(default_factory=list)
    privileges_missing: list[str] = field(default_factory=list)
    error_code: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def ran_as_subject(self) -> bool:
        """True only when the child's own token says it is the subject account.

        Not "the launch was requested" and not "the account exists" -- the
        child's own interrogation, relayed.
        """
        return bool(
            self.state in {LaunchState.VERIFIED, LaunchState.LAUNCHED}
            and isinstance(self.observed, dict)
            and str(self.observed.get("sid", "")).upper() == SUBJECT_SID.upper()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "account": self.account,
            "expected_sid": self.expected_sid,
            "ran_as_subject": self.ran_as_subject,
            "mechanism": self.mechanism,
            "privileges_held": list(self.privileges_held),
            "privileges_missing": list(self.privileges_missing),
            "error_code": self.error_code,
            "observed": self.observed,
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }


def held_privileges() -> dict[str, bool]:
    """Which of the launch-enabling privileges this process actually holds.

    Read from the live token with ``whoami /priv``, which reports *state*, not
    mere presence. A privilege listed as Disabled cannot be used to launch a
    process, and treating it as held would turn a genuine ``NOT_TESTABLE`` into
    a false claim that the mechanism was available.
    """
    try:
        completed = subprocess.run(
            ["whoami", "/priv"],
            capture_output=True,
            text=True,
            timeout=25,
            stdin=subprocess.DEVNULL,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {name: False for name in REQUIRED_PRIVILEGES}

    state: dict[str, bool] = {}
    for line in completed.stdout.splitlines():
        for name in REQUIRED_PRIVILEGES:
            if name in line:
                state[name] = "Enabled" in line
    for name in REQUIRED_PRIVILEGES:
        state.setdefault(name, False)
    return state


def can_launch_as_subject() -> tuple[bool, list[str], list[str]]:
    """``(possible, held, missing)`` for launching as the subject account."""
    states = held_privileges()
    held = [name for name, enabled in states.items() if enabled]
    missing = [name for name, enabled in states.items() if not enabled]
    return bool(held), held, missing


def launch_as_subject(
    command: list[str],
    *,
    timeout_seconds: float = 180.0,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> LaunchResult:
    """Run ``command`` as ``BABY_AI_TEST``, or report why it cannot be run.

    ``command`` is a vector, never a string. There is no shell, so nothing in the
    command can be reinterpreted as syntax, and the argv is exactly what the
    caller specified.

    The child is launched with :mod:`foundation.probe`, which captures its own
    identity and the access it managed, and prints the result as JSON on stdout.
    That JSON is the only evidence accepted -- a launch is never reported as
    successful because the process was created.
    """
    possible, held, missing = can_launch_as_subject()

    if not possible:
        return LaunchResult(
            state=LaunchState.NOT_TESTABLE,
            mechanism="CreateProcessAsUserW",
            privileges_held=held,
            privileges_missing=missing,
            detail=(
                "this session holds neither SeImpersonatePrivilege nor "
                "SeAssignPrimaryTokenPrivilege, so it cannot start a process "
                "under another account's token. Creating one with a password is "
                "refused by design: the credential would have to be stored, "
                "typed, or passed on a command line, and each of those leaks it. "
                "Running the runtime as the operator instead would produce a "
                "successful-looking result that proves nothing about the "
                "restricted identity, so no fallback is taken."
            ),
            evidence={
                "mechanism_refused": "CreateProcessWithTokenW",
                "refusal_reason": "requires a stored password; never accepted",
                "mechanism_refused_too": "runas",
                "second_refusal_reason": (
                    "interactive credential prompt; an unattended harness that "
                    "waits for one cannot be distinguished from a hung one"
                ),
                "fallback_taken": False,
                "fallback_would_have_proven": "nothing about the subject account",
            },
        )

    # The privilege exists. Duplicate a token from an existing process owned by
    # the subject account and use CreateProcessAsUserW.
    from foundation.win32 import create_process_as_user

    return create_process_as_user(
        command,
        account=SUBJECT_ACCOUNT,
        domain=SUBJECT_DOMAIN,
        timeout_seconds=timeout_seconds,
        cwd=cwd,
        env=env,
        privileges_held=held,
        privileges_missing=missing,
    )


def run_probe_as_subject(
    *,
    python: str | None = None,
    timeout_seconds: float = 180.0,
) -> LaunchResult:
    """The M011 probe, run as the subject account.

    Wraps :func:`launch_as_subject` with the probe argv, so the caller does not
    assemble a command line and cannot accidentally pass a shell.
    """
    interpreter = python or sys.executable
    return launch_as_subject(
        [interpreter, "-m", "foundation.probe", "--identity-and-access"],
        timeout_seconds=timeout_seconds,
    )


def describe(root: str | Path | None = None) -> dict[str, Any]:
    """What this host can and cannot do, for the final report.

    Called even when nothing is launched, so the report can state the
    capability position rather than only the outcome. ``root`` is accepted and
    ignored: the capability question is about the session's privileges, not
    about where the code happens to be pointing.
    """
    possible, held, missing = can_launch_as_subject()
    from foundation.process_identity import capture_own_identity

    caller = capture_own_identity()
    return {
        "intended_account": f"{SUBJECT_DOMAIN}\\{SUBJECT_ACCOUNT}",
        "intended_sid": SUBJECT_SID,
        "can_launch_as_subject": possible,
        "privileges_held": held,
        "privileges_missing": missing,
        "mechanisms_refused": {
            "CreateProcessWithTokenW": "requires a stored password; never accepted",
            "runas": "interactive prompt; not automatable",
        },
        "caller_identity": caller.to_dict(),
        "policy": (
            "no fallback to the operator's identity. A run under the "
            "administrator token would look successful and would establish "
            "nothing about the restricted account."
        ),
    }


__all__ = [
    "REQUIRED_PRIVILEGES",
    "SUBJECT_ACCOUNT",
    "SUBJECT_DOMAIN",
    "SUBJECT_SID",
    "LaunchResult",
    "LaunchState",
    "can_launch_as_subject",
    "describe",
    "held_privileges",
    "launch_as_subject",
    "run_probe_as_subject",
]
