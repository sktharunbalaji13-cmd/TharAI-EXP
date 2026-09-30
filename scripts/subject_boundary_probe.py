"""The identity and boundary probe the HUMAN runs as ``BABY_AI_TEST``.

This file is not run by the laboratory. The human runs it, from their own
Windows prompt, supplying ``BABY_AI_TEST``'s password at a Windows credential
prompt. The password is never typed into a tool, never written to a file, and
never passed to this process as an argument.

Why the human and not the harness
----------------------------------
The automated harness holds neither ``SeImpersonatePrivilege`` nor
``SeAssignPrimaryTokenPrivilege`` -- not merely disabled, but *absent* from its
token, so they cannot be enabled (M005 observed ``ERROR_NOT_ALL_ASSIGNED``,
1300). The only ways for a non-elevated process to obtain another account's
token are all credential-based. So a human performing the launch is not a
workaround; it is the only mechanism on this host that produces a genuine
``BABY_AI_TEST`` token without the laboratory storing a password.

What this probe does
--------------------
Two things, in this order:

1. Report its own identity, and its PID.
2. Attempt a controlled write to each protected path and a
   write/read/delete round trip in the permitted workspace, recording the OS
   answer for each.

What it deliberately does not do
--------------------------------
* It does not read protected evidence. It attempts a *create* and records
  whether the OS refused. A refusal is the evidence; a successful read would be
  the failure.
* It does not import any laboratory module. It is stdlib-only so that the
  boundary result cannot be coloured by what the laboratory's own code does
  first.
* It does not write anywhere except the permitted workspace.
* It cannot birth anything. There is no birth code on this path.

Its self-report is **not** the evidence. The operator verifies the PID's token
independently, afterwards, with
:func:`foundation.token_observation.observe_process`. This file's own account
claim is recorded beside the token reading and never merged with it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

#: Where this probe writes its report. The one directory ``BABY_AI_TEST`` is
#: meant to be able to write.
WORKSPACE = Path("baby_workspace")

#: Paths whose *write* must be refused. Derived from the M005 deny ACEs, not
#: from a wish list. Attempting a create here is how the boundary is observed;
#: reading these paths is never attempted.
PROTECTED_TARGETS: tuple[tuple[str, str], ...] = (
    ("var/events", "canonical event log"),
    ("var/provenance", "provenance evidence"),
    ("human_control/security", "human-control security"),
    ("human_control/security/keys/private", "private key material"),
    ("human_control/provenance", "protected research evidence"),
    ("docs/evidence", "protected research evidence"),
)

#: Written and removed, to show the boundary is not simply "deny everything".
WORKSPACE_PROBE_FILE = WORKSPACE / "subject_boundary_probe.txt"
PROBE_CONTENT = b"BABY_AI_TEST boundary probe: create, read, delete.\n"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _command(argv: list[str]) -> dict[str, object]:
    try:
        completed = subprocess.run(argv, capture_output=True, text=True,
                                   timeout=60)
        return {"argv": argv, "exit": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip()}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"argv": argv, "error": str(exc)}


def self_identity() -> dict[str, object]:
    """What this process says about itself.

    Recorded for comparison against the token reading. Never authoritative: a
    program can print anything, and the whole reason the operator reads the
    token separately is that this section is not evidence.
    """
    return {
        "whoami": _command(["whoami"]),
        "whoami_user": _command(["whoami", "/user"]),
        "whoami_groups": _command(["whoami", "/groups"]),
        "whoami_privileges": _command(["whoami", "/priv"]),
        "environment_username": os.environ.get("USERNAME", ""),
        "environment_userdomain": os.environ.get("USERDOMAIN", ""),
        "pid": os.getpid(),
        "integrity": "read from the token by the operator, not by this probe",
    }


def probe_protected() -> list[dict[str, object]]:
    """Attempt one create per protected path and record the OS answer.

    The attempt is the test. ``Access is denied`` is the expected outcome and is
    recorded with the system's own wording, so a reader can tell an OS refusal
    from a Python exception from a file that simply was not there.
    """
    results: list[dict[str, object]] = []
    for relative, purpose in PROTECTED_TARGETS:
        target = Path(relative) / "subject_boundary_probe.txt"
        entry: dict[str, object] = {
            "target": relative,
            "purpose": purpose,
            "attempted_operation": "create file",
            "expected": "OS_DENIED",
        }
        if not target.parent.is_dir():
            entry.update(result="NOT_ATTEMPTED",
                         detail="the parent directory does not exist")
            results.append(entry)
            continue
        try:
            with target.open("xb") as handle:
                handle.write(PROBE_CONTENT)
            entry["result"] = "ALLOWED"
            entry["detail"] = (
                "THE BOUNDARY FAILED: the subject account could create a file "
                "here. This is a security finding, not a probe success."
            )
            try:
                target.unlink()
                entry["cleaned_up"] = True
            except OSError as exc:
                entry["cleaned_up"] = False
                entry["cleanup_error"] = str(exc)
        except PermissionError as exc:
            entry.update(result="OS_DENIED", detail=str(exc),
                         evidence=f"file exists after: {target.exists()}")
        except FileExistsError:
            entry.update(result="UNEXPECTED_PREEXISTING",
                         detail=f"a file already existed at {target}")
        except OSError as exc:
            entry.update(result="OS_ERROR", detail=str(exc))
        results.append(entry)
    return results


def probe_workspace() -> dict[str, object]:
    """Create, read back exact bytes, and delete, inside the workspace.

    The read-back compares the bytes rather than checking that the file exists,
    because a file that exists with the wrong contents is a different failure
    from one that was never written.
    """
    result: dict[str, object] = {
        "target": str(WORKSPACE_PROBE_FILE),
        "attempted_operation": "create, read, delete",
        "expected": "ALLOWED",
    }
    try:
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        with WORKSPACE_PROBE_FILE.open("xb") as handle:
            handle.write(PROBE_CONTENT)
        result["created"] = True

        read_back = WORKSPACE_PROBE_FILE.read_bytes()
        result["read_back_matches"] = read_back == PROBE_CONTENT
        result["bytes"] = len(read_back)

        WORKSPACE_PROBE_FILE.unlink()
        result["deleted"] = True
        result["result"] = "ALLOWED"
    except PermissionError as exc:
        result.update(result="OS_DENIED", detail=str(exc))
    except FileExistsError:
        result.update(result="UNEXPECTED_PREEXISTING")
    except OSError as exc:
        result.update(result="OS_ERROR", detail=str(exc))
    return result


def main() -> int:
    """Run the probe and write the report to the workspace.

    Prints the PID to stdout so the operator can observe that exact process's
    token from their own session. Printing a PID is not a request to trust it --
    it is a handle for the operator to check.
    """
    identity = self_identity()
    protected = probe_protected()
    workspace = probe_workspace()

    denials = sum(1 for entry in protected if entry.get("result") == "OS_DENIED")
    breaches = [entry for entry in protected
                if entry.get("result") == "ALLOWED"]

    report = {
        "schema": "babylab/subject-boundary-probe/v1",
        "generated_at": _now(),
        "executed_by": "the human operator, via their own credential prompt",
        "subject_account_expected": r"THARUNBALAJI-LA\BABY_AI_TEST",
        "subject_sid_expected": "S-1-5-21-2406520953-1060965512-844951592-1022",
        "self_identity": identity,
        "pid": os.getpid(),
        "protected_attempts": protected,
        "protected_denied": denials,
        "protected_allowed": len(breaches),
        "workspace": workspace,
        "boundary_meaningful": None,
        "boundary_meaningful_note": (
            "the operator sets this to true ONLY after reading this process's "
            "token and confirming the SID. This probe cannot establish it: a "
            "process cannot prove its own identity."
        ),
        "boundary_holds": denials == len(PROTECTED_TARGETS) and not breaches,
        "read_only_outside_workspace": True,
        "birth_performed": False,
        "note": (
            "this probe wrote nothing outside baby_workspace and read no "
            "protected evidence. The protected entries record whether a CREATE "
            "was refused, which is the boundary test."
        ),
    }

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    out = WORKSPACE / "subject_boundary_probe.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"probe pid            : {os.getpid()}")
    print(f"self-reported account: {identity['whoami'].get('stdout', 'UNAVAILABLE')}")
    print(f"protected denied     : {denials}/{len(PROTECTED_TARGETS)}")
    print(f"protected ALLOWED    : {len(breaches)}")
    print(f"workspace result     : {workspace.get('result')}")
    print(f"report written to    : {out}")
    print()
    print("Now verify the identity independently, from your own session:")
    print(f"  py -3 -c \"from foundation.token_observation import observe_process;"
          f" print(observe_process({os.getpid()},"
          r" expected_sid='S-1-5-21-2406520953-1060965512-844951592-1022').to_dict())\"")
    return 0 if not breaches else 2


if __name__ == "__main__":
    raise SystemExit(main())
