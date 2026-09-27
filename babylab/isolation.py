"""Measured OS isolation posture (Milestone 004).

Why this module exists
----------------------
Milestone 003 stated: "OS-level isolation is not implemented. Tier 1 discipline
only." That claim was an *assertion*. This module turns it into a **measurement**
that any investigator can re-run, and it is deliberately capable of reporting a
different answer on a different machine.

The central distinction this laboratory must not blur
---------------------------------------------------
A software architecture that is *intended* to be isolated is not equivalent to an
OS-enforced isolation boundary. :mod:`babylab.trust` refuses a write in Python
code. That refusal is real, tested, and worth having -- but it is executed by a
process running with the operator's own OS permissions. Unless a *second*,
lower-privilege OS identity exists and the kernel denies that identity write
access, the refusal is advisory.

This module therefore reports three distinct statuses, never collapsed:

``VERIFIED``
    A lower-privilege identity exists AND an actual write from it was attempted
    AND the kernel denied it. Only real evidence of denial earns this.

``UNVERIFIED``
    A mechanism exists and is configured, but no write from a lower-privilege
    identity has actually been attempted and denied yet.

``NOT_IMPLEMENTED``
    No such mechanism is active on this host. The concrete prerequisites for
    reaching ``VERIFIED`` are reported alongside it.

Nothing in this module ever reports ``VERIFIED`` on the basis of reading an ACL
and assuming it works. Configuration is not enforcement.
"""

from __future__ import annotations

import enum
import os
import subprocess
from dataclasses import dataclass, field


class IsolationStatus(str, enum.Enum):
    """How much OS-level isolation is actually in force on this host."""

    #: A real write from a lower-privilege identity was denied by the kernel.
    VERIFIED = "VERIFIED"
    #: A mechanism is configured but has not been proven by an attempted write.
    UNVERIFIED = "UNVERIFIED"
    #: No lower-privilege OS identity / enforced boundary exists here.
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class EnforcementLayer(str, enum.Enum):
    """Which mechanism would actually stop a misbehaving subject."""

    APPLICATION_POLICY = "application policy"
    OS_FILE_PERMISSIONS = "OS policy (NTFS ACL)"
    OS_ACCOUNT = "OS policy (separate account)"
    OS_CONTAINER = "OS policy (container)"
    OS_VIRTUAL_MACHINE = "OS policy (virtual machine)"
    NONE = "none"


@dataclass(frozen=True)
class HostMeasurement:
    """A single observed fact about this host.

    ``value`` is what was actually observed. ``source`` records how, so a later
    reader can tell an observation from a guess.
    """

    name: str
    value: object
    source: str

    def as_row(self) -> dict:
        return {"name": self.name, "value": self.value, "source": self.source}


@dataclass(frozen=True)
class IsolationReport:
    """The full measured answer for one host."""

    status: IsolationStatus
    layer: EnforcementLayer
    measurements: tuple[HostMeasurement, ...] = ()
    #: Concrete, checkable prerequisites required before VERIFIED is reachable.
    prerequisites: tuple[str, ...] = ()
    #: Why the current status was reached, in plain language.
    reasons: tuple[str, ...] = ()
    #: True only when a write was actually attempted from a lower identity.
    write_attempt_performed: bool = False
    write_attempt_denied: bool = False
    metadata: dict = field(default_factory=dict)

    def measurement(self, name: str) -> HostMeasurement | None:
        for m in self.measurements:
            if m.name == name:
                return m
        return None

    def as_rows(self) -> list[dict]:
        return [m.as_row() for m in self.measurements]


# ---------------------------------------------------------------------------
# Probes. Each returns a HostMeasurement and never raises: a measurement tool
# that crashes tells the investigator nothing.
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception as exc:  # noqa: BLE001
        return -1, "", repr(exc)


def measure_account() -> HostMeasurement:
    """Identity of the account running the laboratory."""
    user = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    code, out, _ = _run(["whoami"])
    return HostMeasurement(
        name="current_account",
        value={"username": user, "domain": domain, "whoami": out} if code == 0 else user,
        source="os.environ + whoami",
    )


def measure_elevation() -> HostMeasurement:
    """Whether this session is actually elevated.

    Being a member of the Administrators group is NOT elevation. A medium
    integrity token cannot change file ownership or install deny ACEs, so this
    distinction decides whether OS enforcement is even attemptable.
    """
    code, out, _ = _run(["whoami", "/groups"])
    if code != 0:
        return HostMeasurement("elevated", None, "whoami /groups failed")
    # S-1-16-* are integrity levels; 12288=medium, 16384=high/system.
    high = any(s in out for s in ("S-1-16-16384", "S-1-16-12288"))
    in_admin_group = "S-1-5-32-544" in out
    return HostMeasurement(
        name="elevated",
        value={"elevated": high, "administrators_group_member": in_admin_group},
        source="whoami /groups integrity SIDs",
    )


def measure_broad_write_grant(path: str) -> HostMeasurement:
    """Does a broad trustee (e.g. ``Authenticated Users``) hold write rights?

    If it does, then *any* second local account -- including a future Baby AI
    service account -- can write there, and no OS boundary exists on that path
    regardless of what the laboratory's own policy says.
    """
    code, out, _ = _run(["icacls", path])
    if code != 0:
        return HostMeasurement("broad_write_grant", {"error": "icacls failed"}, f"icacls {path}")
    broad_write = []
    for raw in out.splitlines():
        s = raw.strip()
        if not s or s.lower().startswith("successfully"):
            continue
        parts = s.split(" ", 1)
        if len(parts) != 2 or ":" not in parts[1]:
            continue
        trustee, rights = parts[1].rsplit(":", 1)
        trustee, rights = trustee.strip(), rights.strip()
        leaf = trustee.split("\\")[-1].lower()
        if leaf in ("authenticated users", "everyone", "users"):
            if any(tok in rights for tok in ("(F)", "(M)", "(W)", "(D)", "(C)")):
                broad_write.append({"trustee": trustee, "rights": rights})
    return HostMeasurement(
        name="broad_write_grant",
        value={"path": str(path), "broad_write_entries": broad_write, "broad_write_present": bool(broad_write)},
        source=f"icacls {path}",
    )


def measure_second_identity() -> HostMeasurement:
    """Is there a local account that could act as the Baby AI execution identity?

    OS and agent-infrastructure accounts (Administrator, Guest, WDAGUtilityAccount,
    the harness sandbox accounts) are deliberately NOT counted: borrowing another
    product's accounts would not be a research boundary.
    """
    code, out, _ = _run(
        ["powershell", "-NoProfile", "-Command", "(Get-LocalUser | Select-Object -ExpandProperty Name) -join ','"]
    )
    names = [n.strip() for n in out.split(",") if n.strip()] if code == 0 else []
    reserved = {
        "administrator", "guest", "defaultaccount", "wdagutilityaccount",
        "codexsandboxoffline", "codexsandboxonline",
    }
    candidates = [n for n in names if n.lower() not in reserved]
    return HostMeasurement(
        name="second_identity_available",
        value={
            "all_local_users": names,
            "non_reserved_candidates": candidates,
            "provisioned_baby_ai_account": None,
        },
        source="Get-LocalUser",
    )


def measure_container_runtime() -> HostMeasurement:
    """Container/VM isolation availability.

    A client binary is not an isolation boundary. The engine must actually
    answer before this can count as available.
    """
    client, out, _ = _run(["docker", "--version"])
    engine_code, engine_out, engine_err = _run(
        ["docker", "info", "--format", "{{.ServerVersion}}"], timeout=90
    )
    return HostMeasurement(
        name="container_runtime",
        value={
            "client_present": client == 0,
            "client_version": out if client == 0 else None,
            "engine_running": engine_code == 0,
            "engine_detail": (engine_out or engine_err)[:200],
        },
        source="docker --version + docker info",
    )


def measure_wsl() -> HostMeasurement:
    """WSL availability -- the one kernel-isolation path observed working here."""
    code, out, _ = _run(["wsl", "-e", "uname", "-a"], timeout=120)
    return HostMeasurement(
        name="wsl",
        value={"executable": code == 0, "kernel": out[:200] if code == 0 else None},
        source="wsl -e uname -a",
    )


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def assess_isolation(
    protected_paths: list[Path],
    *,
    write_attempt_performed: bool = False,
    write_attempt_denied: bool = False,
) -> IsolationReport:
    """Measure this host and return a graded, non-overclaiming verdict.

    The only route to :attr:`IsolationStatus.VERIFIED` is a write that was
    actually attempted from a lower-privilege identity and actually denied by
    the kernel. Passing configuration, or an ACL that merely *looks* right, can
    never produce VERIFIED.
    """
    account = measure_account()
    elevation = measure_elevation()
    second_identity = measure_second_identity()
    container = measure_container_runtime()
    wsl = measure_wsl()
    grants = tuple(measure_broad_write_grant(p) for p in protected_paths)

    measurements = (account, elevation, second_identity, container, wsl) + grants

    elev_value = elevation.value if isinstance(elevation.value, dict) else {}
    is_elevated = bool(elev_value.get("elevated"))
    ident_value = second_identity.value if isinstance(second_identity.value, dict) else {}
    provisioned = bool(ident_value.get("provisioned_baby_ai_account"))
    cont_value = container.value if isinstance(container.value, dict) else {}
    engine_running = bool(cont_value.get("engine_running"))

    broad_write_paths = [
        g.value.get("path")
        for g in grants
        if isinstance(g.value, dict) and g.value.get("broad_write_present")
    ]

    reasons: list[str] = []
    prerequisites: list[str] = []

    if broad_write_paths:
        reasons.append(
            "NTFS ACLs grant write access to a broad trustee (Authenticated Users / "
            "Everyone) on protected paths: " + ", ".join(str(p) for p in broad_write_paths)
        )
        prerequisites.append(
            "An elevated session able to install explicit deny ACEs for the Baby AI "
            "identity on human_control/, var/provenance/, var/events/, docs/ and .git/"
        )
    if not is_elevated:
        reasons.append(
            "The current session is a medium-integrity token, not an elevated one; "
            "it cannot change file ownership or install deny ACEs."
        )
        prerequisites.append("An elevated (administrator) session")
    if not provisioned:
        reasons.append(
            "No dedicated low-privilege Baby AI execution account is provisioned. "
            "The other local accounts are OS or agent-harness accounts and reusing "
            "them would not constitute a research boundary."
        )
        prerequisites.append("A dedicated Baby AI service account created by an administrator")
    if not engine_running:
        reasons.append(
            "A container client is present but its engine is not running, so no "
            "container isolation boundary exists right now."
        )
        prerequisites.append("Start the container engine, or enable Windows Sandbox / a VM")

    if write_attempt_performed and write_attempt_denied:
        return IsolationReport(
            status=IsolationStatus.VERIFIED,
            layer=EnforcementLayer.OS_FILE_PERMISSIONS,
            measurements=measurements,
            prerequisites=(),
            reasons=("A write from a lower-privilege identity was attempted and denied.",),
            write_attempt_performed=True,
            write_attempt_denied=True,
            metadata={"broad_write_paths": broad_write_paths},
        )

    if write_attempt_performed and not write_attempt_denied:
        # The write was actually allowed. That is a real, damning observation.
        reasons.insert(
            0,
            "A write from the lower-privilege identity SUCCEEDED, so no OS-level "
            "write boundary is in force on this host.",
        )
        status = IsolationStatus.NOT_IMPLEMENTED
    elif is_elevated and provisioned and not broad_write_paths:
        # Everything needed is present but nobody has proven a denial yet.
        status = IsolationStatus.UNVERIFIED
        reasons.insert(
            0,
            "The required mechanisms appear available but no write from a "
            "lower-privilege identity has been attempted and denied yet.",
        )
    else:
        status = IsolationStatus.NOT_IMPLEMENTED

    return IsolationReport(
        status=status,
        layer=EnforcementLayer.APPLICATION_POLICY,
        measurements=measurements,
        prerequisites=tuple(prerequisites),
        reasons=tuple(reasons),
        write_attempt_performed=write_attempt_performed,
        write_attempt_denied=write_attempt_denied,
        metadata={"broad_write_paths": broad_write_paths},
    )
