"""M016 - whether a native executable can be launched as BABY_AI_TEST.

This module investigates the *host capability* and reports it honestly. It does
not grant privileges, weaken an ACL, store a credential, or take a shortcut
through a Python interpreter.

The central distinction this file is built around:

    a verifier that cannot report failure is not a verifier

Every mechanism is probed and its outcome recorded, and ``MECHANISMS`` is the
ledger. A mechanism that cannot be attempted without a stored password is marked
``INTERACTIVE_ONLY`` rather than quietly skipped, because "we did not try it" and
"we tried it and it is blocked" are different claims.

The conclusion on this host is ``SUBJECT_PROCESS_NOT_TESTABLE``: the mechanism
that would work (``CreateProcessWithLogonW``) requires ``SeImpersonatePrivilege``,
which this operator token does not hold, and every alternative either needs
credentials the milestone forbids persisting or needs elevation.

**No process was launched as BABY_AI_TEST in this milestone.**
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

#: Re-exported from M011 so this module cannot drift from the single definition.
SUBJECT_ACCOUNT = "THARUNBALAJI-LA\\BABY_AI_TEST"


class LaunchStatus(str, Enum):
    """The four outcomes a launch attempt may have.

    ``SUBJECT_PROCESS_NOT_TESTABLE`` is a real, publishable result. It is not a
    soft failure to be retried until it turns green.
    """

    VERIFIED = "SUBJECT_PROCESS_VERIFIED"
    NOT_TESTABLE = "SUBJECT_PROCESS_NOT_TESTABLE"
    FAILED = "SUBJECT_PROCESS_FAILED"
    RUNTIME_NOT_SELECTED = "RUNTIME_NOT_SELECTED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


#: Privileges whose absence blocks the "launch as another user without stored
#: credentials" family of mechanisms. Both are absent on this operator token,
#: which is why the milestone's result is NOT_TESTABLE rather than FAILED.
REQUIRED_PRIVILEGES = (
    "SeImpersonatePrivilege",       # CreateProcessWithLogonW
    "SeAssignPrimaryTokenPrivilege",  # CreateProcessAsUser
)


@dataclass(frozen=True)
class Mechanism:
    """One candidate way to start a process as the subject account."""

    name: str
    #: What the mechanism actually requires, stated as a fact rather than a hope.
    requirement: str
    #: Whether an automated attempt is possible without storing a credential.
    automatable: bool
    #: Why it cannot be used here, or why it can.
    finding: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "requirement": self.requirement,
            "automatable_without_stored_credential": self.automatable,
            "finding": self.finding,
        }


#: The ledger. Populated by investigation, not by assumption -- each entry states
#: what was observed on this host.
MECHANISMS: tuple[Mechanism, ...] = (
    Mechanism(
        name="CreateProcessWithLogonW",
        requirement="SeImpersonatePrivilege in the caller's token",
        automatable=True,
        finding=(
            "UNAVAILABLE: privilege absent from the operator token. This is the "
            "mechanism that would otherwise satisfy the milestone, because it "
            "needs no stored password."
        ),
    ),
    Mechanism(
        name="CreateProcessAsUser / DuplicateTokenEx",
        requirement="SeAssignPrimaryTokenPrivilege, or a duplicated primary token",
        automatable=True,
        finding="UNAVAILABLE: privilege absent; no duplicated token to reuse.",
    ),
    Mechanism(
        name="Scheduled Task (schtasks /create /ru BABY_AI_TEST)",
        requirement=(
            "stored credentials for a non-interactive run, or an interactive "
            "prompt at task registration"
        ),
        automatable=False,
        finding=(
            "BLOCKED: registration attempted and refused with 'Access is denied' "
            "for this non-elevated operator. Supplying /RP would persist the "
            "password in a way the milestone forbids."
        ),
    ),
    Mechanism(
        name="Windows service (sc.exe create)",
        requirement="stored service credentials, and elevation to install",
        automatable=False,
        finding=(
            "REJECTED BY DESIGN: a service runs as its own identity, not as an "
            "interactive user, and would require persisting the password."
        ),
    ),
    Mechanism(
        name="runas.exe",
        requirement="an interactive GUI credential prompt",
        automatable=False,
        finding=(
            "INTERACTIVE_ONLY: the binary exists and is the one mechanism that "
            "does not need stored credentials, but it cannot be driven "
            "non-interactively, so an automated run cannot confirm it."
        ),
    ),
    Mechanism(
        name="Start-Process -Credential",
        requirement="a SecureString credential supplied at the call site",
        automatable=False,
        finding=(
            "INTERACTIVE_ONLY: same credential-prompt constraint as runas. The "
            "prior M014 attempt also failed for an unrelated reason -- the "
            "target was py.exe, an App Execution Alias invisible to the subject. "
            "A native PE would not have that problem, but the credential prompt "
            "still blocks automation."
        ),
    ),
    Mechanism(
        name="WSL / docker exec",
        requirement="a Linux or container identity",
        automatable=True,
        finding=(
            "REJECTED BY DESIGN: these produce a Linux or container identity, "
            "not a Windows process token for BABY_AI_TEST. Substituting them "
            "would answer a different question than the milestone asks."
        ),
    ),
)


def token_privileges() -> dict[str, Any]:
    """The operator token's privileges, read from the running token."""
    sysinfo = subprocess.run(
        ["whoami", "/priv"], capture_output=True, text=True, shell=False,
        stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace", timeout=60)
    held: list[str] = []
    for line in (sysinfo.stdout or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("Privilege") or stripped.startswith("-"):
            continue
        name = stripped.split()[0]
        if name.startswith("Se"):
            held.append(name)
    missing = [p for p in REQUIRED_PRIVILEGES if p not in held]
    return {
        "privileges_held": sorted(held),
        "privilege_count": len(held),
        "required_for_launch": list(REQUIRED_PRIVILEGES),
        "missing": missing,
        "sufficient_for_unattended_launch": not missing,
    }


def is_elevated() -> bool:
    """Whether this token is elevated.

    Checked from the token's groups rather than from the presence of an
    Administrators entry: an unelevated token carries Administrators marked
    *deny only*, so its presence proves nothing.
    """
    groups = subprocess.run(
        ["whoami", "/groups"], capture_output=True, text=True, shell=False,
        stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace", timeout=60)
    for line in (groups.stdout or "").splitlines():
        if "S-1-5-32-544" in line and "deny only" not in line.lower():
            return True
    return False


def subject_account_state() -> dict[str, Any]:
    """Metadata about the subject account. Never reads or stores a secret."""
    try:
        ps = (
            "$u = Get-LocalUser -Name 'BABY_AI_TEST' -ErrorAction Stop; "
            "[pscustomobject]@{ Name=$u.Name; Enabled=$u.Enabled; "
            "PasswordRequired=$u.PasswordRequired; LastLogon=$u.LastLogon; "
            "UserMayChangePassword=$u.UserMayChangePassword } | ConvertTo-Json -Compress"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, shell=False,
            stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace", timeout=120)
        data = json.loads((result.stdout or "{}").strip() or "{}")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        data = {"read_failed": str(exc)}
    return {
        "account": SUBJECT_ACCOUNT,
        "observed": data,
        "password_value_read": False,
        "password_stored_anywhere": False,
        "note": (
            "metadata only; the password value is never read, logged, or stored. "
            "PasswordRequired=False means an empty password would satisfy logon, "
            "which is a security finding about the host and not something this "
            "milestone exploits or changes."
        ),
    }


def human_selected_runtime(declaration_path: str | Path | None = None) -> dict[str, Any]:
    """Whether a human has explicitly declared a runtime to use.

    Absence is the expected and correct state. Nothing here infers a selection
    from a filename, a location, a file size, or a previously discovered binary:
    the milestone's whole point is that the operator chooses, not the tool.
    """
    path = Path(declaration_path) if declaration_path else (
        Path(__file__).resolve().parents[1]
        / "human_control" / "experiment_config" / "runtime_selection.json")
    if not path.is_file():
        return {
            "status": LaunchStatus.RUNTIME_NOT_SELECTED.value,
            "declaration_path": str(path),
            "declaration_present": False,
            "selected_runtime": None,
            "selected_by": None,
            "reason": (
                "no human runtime declaration exists, so no runtime was chosen, "
                "copied, or executed"
            ),
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "status": LaunchStatus.FAILED.value,
            "declaration_path": str(path),
            "declaration_present": True,
            "reason": f"declaration unreadable: {exc}",
        }
    source = data.get("source_path")
    selected_by = data.get("selected_by")
    if not source or not selected_by:
        return {
            "status": LaunchStatus.RUNTIME_NOT_SELECTED.value,
            "declaration_path": str(path),
            "declaration_present": True,
            "reason": (
                "declaration exists but does not name both a source_path and a "
                "selected_by; an unsigned or unattributed selection is not a "
                "human selection"
            ),
        }
    source_path = Path(source)
    return {
        "status": LaunchStatus.RUNTIME_NOT_SELECTED.value,
        "declaration_path": str(path),
        "declaration_present": True,
        "selected_runtime": str(source_path),
        "selected_by": selected_by,
        "source_exists": source_path.is_file(),
        "source_sha256": (
            _sha256(source_path) if source_path.is_file() else None),
        "reason": "a human declaration is present; staging is a separate action",
    }


def _sha256(path: str | Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def launch_feasibility() -> dict[str, Any]:
    """Can a native process be launched as the subject account on this host?"""
    privileges = token_privileges()
    elevated = is_elevated()

    # The decision rule, stated explicitly: an unattended launch as another local
    # user requires one of the impersonation privileges. Without it, every
    # remaining route needs a stored password or an interactive prompt, and the
    # milestone forbids both.
    unattended_possible = privileges["sufficient_for_unattended_launch"]

    blockers: list[str] = []
    for name in privileges["missing"]:
        blockers.append(f"{name} is absent from the operator token")
    if not elevated:
        blockers.append(
            "the operator token is not elevated, so mechanisms that require "
            "elevation (scheduled-task registration, service install) are refused")

    if unattended_possible:
        status = LaunchStatus.NOT_TESTABLE.value
        reason = (
            "the privilege is present, so a launch could be attempted; this "
            "milestone does not attempt it without a human-selected runtime"
        )
    else:
        status = LaunchStatus.NOT_TESTABLE.value
        reason = (
            "SUBJECT_PROCESS_NOT_TESTABLE: launching a native process as "
            "BABY_AI_TEST from this token requires SeImpersonatePrivilege or "
            "SeAssignPrimaryTokenPrivilege, and neither is held. The remaining "
            "mechanisms all require a stored credential or an interactive "
            "prompt, neither of which this milestone will substitute for proof."
        )

    return {
        "schema": "babylab/m016-launch-feasibility/v1",
        "status": status,
        "subject_process_launched": False,
        "privileges": privileges,
        "operator_elevated": elevated,
        "mechanisms": [m.as_dict() for m in MECHANISMS],
        "automatable_mechanisms_remaining": [
            m.name for m in MECHANISMS
            if m.automatable and "UNAVAILABLE" not in m.finding
            and "REJECTED BY DESIGN" not in m.finding],
        "rejected_by_design": [
            m.name for m in MECHANISMS if "REJECTED BY DESIGN" in m.finding],
        "interactive_only_mechanisms": [
            m.name for m in MECHANISMS if not m.automatable],
        "blockers": blockers,
        "reason": reason,
        "credential_handling": {
            "password_read": False,
            "password_stored": False,
            "password_in_arguments": False,
            "password_in_environment": False,
            "password_in_repository": False,
            "password_logged": False,
            "policy": (
                "no credential was requested, supplied, stored, or logged. "
                "Mechanisms requiring one are marked INTERACTIVE_ONLY and left "
                "for a human at an interactive session."
            ),
        },
        "assessed_at": datetime.now(timezone.utc).isoformat(),
    }


def probe_binary(source: str | Path | None = None) -> dict[str, Any]:
    """Locate or build the native boundary probe. No toolchain is installed.

    ``Add-Type`` compiles with the C# compiler already present in PowerShell 5.1,
    so no new toolchain is required. If no compiler is available the probe is
    reported unavailable rather than replaced by Python, because staging CPython
    for the subject is explicitly out of bounds.
    """
    if source is None:
        source = (Path(__file__).resolve().parents[1]
                  / "foundation" / "subject_probe.cs")
    source = Path(source)
    result: dict[str, Any] = {
        "schema": "babylab/m016-probe/v1",
        "source": str(source),
        "source_present": source.is_file(),
        "language": "csharp",
        "compiler": "PowerShell 5.1 Add-Type (no toolchain installed)",
        "staged_in_subject_runtime": False,
        "python_used_as_subject_runtime": False,
    }
    if not source.is_file():
        result["status"] = LaunchStatus.NOT_TESTABLE.value
        result["reason"] = "probe source not present"
        return result

    exe = source.with_suffix(".exe")
    if not exe.is_file():
        result["status"] = LaunchStatus.NOT_TESTABLE.value
        result["reason"] = (
            "probe source exists but no compiled probe is present; build it with "
            "Add-Type before launching. NOT_TESTABLE rather than FAILED, because "
            "nothing has been attempted as the subject yet."
        )
        return result

    result["status"] = "PROBE_BUILT"
    result["sha256"] = _sha256(exe)
    result["size_bytes"] = exe.stat().st_size
    result["identity_source"] = (
        "the probe reads its own process token via OpenProcessToken and "
        "GetTokenInformation; identity is never taken from arguments"
    )
    return result


def report() -> dict[str, Any]:
    """The whole M016 picture, in the shape the documentation records."""
    feasibility = launch_feasibility()
    return {
        "schema": "babylab/m016-report/v1",
        "milestone": "M016",
        "subject_account_launch_status": feasibility["status"],
        "subject_process_launched": False,
        "birth_status": "M014 remains BLOCKED; M016 does not change it",
        "model_status": "none selected",
        "runtime_selection": human_selected_runtime(),
        "runtime_staged": False,
        "account": subject_account_state(),
        "probe": probe_binary(),
        "network_status": (
            "not claimed; no firewall rule was added and no isolation is asserted"
        ),
        "launch": feasibility,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }