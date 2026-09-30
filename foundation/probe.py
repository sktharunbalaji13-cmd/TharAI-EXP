"""M011 probe: the access test, written to be run as the restricted account.

Run as a child, print one JSON object on stdout, exit.

Why the probe runs in the child
------------------------------
The measurement is "what can this process reach", and the only honest way to
answer that is for the process in question to try. A parent that attempts the
access is measuring the parent's rights, not the subject account's -- which is
the substitution M011 exists to eliminate. So the same module serves both roles:
the parent launches it with a restricted token, the child interrogates its own
identity and attempts its own access, and the parent relays the child's report
rather than interpreting anything.

What is attempted, and what each result means
---------------------------------------------
Six protected targets, each attempted for **write**. Write is the stricter test:
an account that can read a key can usually also read it in a way that matters
less than an account that can overwrite the ledger, so a read denial alone
would understate the exposure. Each attempt reports the OS's own answer.

Two workspace operations, in the order the M005 policy implies: write, read back
the content that was written, then delete. Readback matters because a create
that appears to succeed but silently writes nothing is a different result from a
real write, and only reading it back distinguishes them.

A network attempt
-----------------
``RUNTIME_NETWORK_PROBE.md`` is written into the temporary workspace and read
back. It does not open a socket -- the point is to establish that a write and a
read both succeed inside the permitted workspace, so that a *denial* elsewhere is
about the boundary rather than about a broken filesystem. A genuine outbound
connection is never attempted: making one to prove a policy is not observing the
policy, and the absence of network use is established structurally in
:mod:`foundation.isolation` instead.

The probe never weakens anything
--------------------------------
It does not modify an ACL, does not take ownership, does not change a
permission, and does not write outside the temporary workspace. Every write
attempt against a protected target is expected to fail; if one unexpectedly
succeeds, that is recorded as a finding and the file it created is removed
immediately, because a probe that left a file behind would itself be the
violation it was looking for.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The file the workspace probe writes. Named so a leftover is identifiable.
PROBE_FILENAME = "M011_PROBE.txt"

#: Content written and read back. A fixed string, so a readback proves the write
#: reached the same bytes rather than an empty file.
PROBE_CONTENT = "m011-restricted-identity-probe"

#: Anything other than these two counts as a violation of the workspace policy.
WORKSPACE_ANSWERS = ("OK", "DENIED")


@dataclass
class AccessAttempt:
    """One attempted operation and the OS's answer to it."""

    target: str
    category: str
    operation: str
    permitted: bool
    detail: str
    cleanup_performed: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "category": self.category,
            "operation": self.operation,
            "permitted": self.permitted,
            "detail": self.detail,
            "cleanup_performed": self.cleanup_performed,
            "evidence": dict(self.evidence),
        }


def _attempt_write(
    target: Path, label: str, category: str, *, remove_on_success: bool = True
) -> AccessAttempt:
    """Try to create a file inside ``target``.

    ``remove_on_success`` is ``True`` for protected paths -- a creation there is
    a violation, so the file is deleted immediately rather than left behind. It
    is ``False`` for the workspace cycle, where the file has to survive until the
    readback step has confirmed what was written; the workspace has its own
    explicit delete step for that.
    """
    probe = target / PROBE_FILENAME
    if not target.is_dir():
        # A protected *file* cannot be written without replacing it, which would
        # destroy a research record. Reading it is the non-destructive test.
        return AccessAttempt(
            target=str(target), category=category, operation="write",
            permitted=False,
            detail=(
                "this target is a file, not a directory; the probe does not "
                "attempt to replace a protected research record"
            ),
            evidence={"target_kind": "file", "destructive_if_written": True},
        )
    try:
        probe.write_text(PROBE_CONTENT, encoding="utf-8")
    except PermissionError as exc:
        return AccessAttempt(
            target=str(target), category=category, operation="write",
            permitted=False,
            detail=f"the OS refused the write: {exc.strerror or exc}",
            evidence={"errno": getattr(exc, "errno", None)},
        )
    except OSError as exc:
        return AccessAttempt(
            target=str(target), category=category, operation="write",
            permitted=False, detail=f"the write failed: {type(exc).__name__}: {exc}",
        )

    if not remove_on_success:
        return AccessAttempt(
            target=str(target), category=category, operation="write",
            permitted=True,
            detail="the write succeeded; the file is retained for readback",
        )

    removed = False
    try:
        probe.unlink()
        removed = True
    except OSError:  # pragma: no cover - a failed removal is itself the finding
        pass
    return AccessAttempt(
        target=str(target), category=category, operation="write",
        permitted=True,
        detail=(
            "the write SUCCEEDED on a protected path, which is a boundary "
            "violation. The file was removed immediately so the probe left no "
            "artefact behind."
        ),
        cleanup_performed=removed,
        evidence={"violation": True},
    )


def _attempt_read(target: Path, label: str, category: str) -> AccessAttempt:
    """Try to read a target. Used for protected files and for readback."""
    try:
        if target.is_dir():
            entries = sorted(p.name for p in target.iterdir())
            return AccessAttempt(
                target=str(target), category=category, operation="read",
                permitted=True,
                detail=f"the directory was listed ({len(entries)} entries)",
                evidence={"entry_count": len(entries)},
            )
        content = target.read_bytes()
        return AccessAttempt(
            target=str(target), category=category, operation="read",
            permitted=True,
            detail=f"the file was read ({len(content)} bytes)",
            evidence={"byte_count": len(content)},
        )
    except PermissionError as exc:
        return AccessAttempt(
            target=str(target), category=category, operation="read",
            permitted=False,
            detail=f"the OS refused the read: {exc.strerror or exc}",
            evidence={"errno": getattr(exc, "errno", None)},
        )
    except OSError as exc:
        return AccessAttempt(
            target=str(target), category=category, operation="read",
            permitted=False, detail=f"the read failed: {type(exc).__name__}: {exc}",
        )


def _workspace_cycle(workspace: Path) -> dict[str, Any]:
    """Write, read back, delete -- inside the permitted workspace.

    The write does *not* delete on success: the readback step is the only way to
    distinguish a real write from a create that appears to succeed and leaves
    nothing, and deleting first would make that distinction impossible.
    """
    probe = workspace / PROBE_FILENAME
    steps: list[AccessAttempt] = []

    steps.append(
        _attempt_write(workspace, "workspace", "workspace_write",
                       remove_on_success=False)
    )

    readback = AccessAttempt(
        target=str(probe), category="workspace_read", operation="read",
        permitted=False, detail="no readback was possible",
    )
    try:
        content = probe.read_text(encoding="utf-8")
        readback = AccessAttempt(
            target=str(probe), category="workspace_read", operation="read",
            permitted=True,
            detail=(
                "the workspace write was read back and the content matched"
                if content == PROBE_CONTENT
                else "the workspace read returned different content"
            ),
            evidence={"content_matched": content == PROBE_CONTENT},
        )
    except OSError as exc:
        readback = AccessAttempt(
            target=str(probe), category="workspace_read", operation="read",
            permitted=False,
            detail=f"the workspace readback failed: {type(exc).__name__}: {exc}",
        )
    steps.append(readback)

    cleanup = AccessAttempt(
        target=str(probe), category="workspace_cleanup", operation="delete",
        permitted=False, detail="no cleanup was attempted",
    )
    try:
        probe.unlink()
        cleanup = AccessAttempt(
            target=str(probe), category="workspace_cleanup", operation="delete",
            permitted=True, detail="the probe file was deleted",
        )
    except FileNotFoundError:
        cleanup = AccessAttempt(
            target=str(probe), category="workspace_cleanup", operation="delete",
            permitted=False,
            detail="the probe file was already absent, so nothing was left behind",
        )
    except OSError as exc:
        cleanup = AccessAttempt(
            target=str(probe), category="workspace_cleanup", operation="delete",
            permitted=False,
            detail=f"the probe file could not be deleted: {type(exc).__name__}: {exc}",
        )
    steps.append(cleanup)

    return {
        "workspace": str(workspace),
        "steps": [s.to_dict() for s in steps],
        "write_allowed": steps[0].permitted,
        "readback_ok": steps[1].permitted
        and bool(steps[1].evidence.get("content_matched")),
        "cleanup_ok": steps[2].permitted or "already absent" in steps[2].detail,
    }


def _protected_targets() -> list[tuple[Path, str, str]]:
    """The six protected targets the milestone names, from the M005 boundary.

    Taken from :mod:`babylab.osboundary` rather than restated, so the probe
    cannot drift from the policy it is testing. The entry names are the M005
    ones; the category is the milestone's grouping. ``human_control`` is
    represented by the seals directory, which is a directory inside it and so
    can be probed for write without touching a research record.
    """
    from babylab.osboundary import protected_paths

    wanted = {
        "provenance_ledger": "provenance",
        "event_log": "event",
        "provenance_seals": "human_control",
        "provenance_private_keys": "private_key",
        "research_documentation": "research",
        "control_token": "control_token",
    }
    by_name = {entry.name: Path(entry.path) for entry in protected_paths()}
    return [
        (by_name[entry_name], category, entry_name)
        for entry_name, category in wanted.items()
        if entry_name in by_name
    ]


def run_probe(root: str | Path | None = None) -> dict[str, Any]:
    """Run the whole probe and return one JSON-serialisable record.

    Captures its own identity first, so the record is self-describing: a reader
    can confirm which account produced the access results without consulting the
    parent that launched it.
    """
    if root is None:
        from babylab.paths import default_paths

        root = default_paths().root
    root = Path(root)

    from foundation.process_identity import capture_own_identity

    identity = capture_own_identity()

    protected: list[dict[str, Any]] = []
    for path, key, entry_name in _protected_targets():
        result = _attempt_write(path, entry_name, key)
        protected.append(result.to_dict())
        if not result.permitted and path.is_file():
            protected.append(_attempt_read(path, entry_name, key).to_dict())

    from babylab.osboundary import subject_workspace_paths

    workspaces = {w.name: Path(w.path) for w in subject_workspace_paths()}
    experimental = workspaces.get("experimental_workspace")
    cycle = (
        _workspace_cycle(experimental)
        if experimental is not None and experimental.is_dir()
        else {
            "workspace": str(experimental) if experimental else "UNAVAILABLE",
            "steps": [],
            "write_allowed": False,
            "readback_ok": False,
            "cleanup_ok": False,
            "detail": "the subject workspace directory does not exist",
        }
    )

    return {
        "schema": "babylab/m011-probe/v1",
        "identity": identity.to_dict(),
        "protected": protected,
        "workspace": cycle,
        "network": {
            "policy": "LOCAL_ONLY_NO_FETCH",
            "outbound_attempted": False,
            "detail": (
                "no socket was opened. Establishing that a connection is refused "
                "would require making one, and making a connection to test a "
                "policy is not observing the policy. The runtime path's imports "
                "are checked structurally instead."
            ),
        },
        "modification_policy": {
            "acl_changed": False,
            "permission_changed": False,
            "ownership_taken": False,
            "detail": (
                "the probe writes only inside the subject workspace and only "
                "attempts writes elsewhere; it never changes a permission"
            ),
        },
        "verdict": _verdict(protected, cycle, identity),
    }


def _verdict(
    protected: list[dict[str, Any]],
    cycle: dict[str, Any],
    identity: Any,
) -> dict[str, Any]:
    """Summarise the probe.

    The verdict depends entirely on *who ran it*, and the distinction is not
    cosmetic:

    * Run as the **subject account**, a permitted protected access is a boundary
      violation. That is the measurement M011 exists to make.
    * Run as the **operator**, a permitted protected access is the expected and
      documented state -- the operator owns the keyring, the token, and the
      ledger, and M005's boundary is explicitly a boundary against the *subject*
      account, not against the human. Reporting the operator's access as a
      violation would invent a failure and imply the M005 boundary is broken
      when it is working as designed.

    Either way the raw attempts are reported, so a reader can judge for
    themselves rather than trusting a summary.
    """
    from foundation.restricted import SUBJECT_SID

    ran_as_subject = str(identity.sid).upper() == SUBJECT_SID.upper()
    permitted = [p for p in protected if p["permitted"]]
    denied = [p for p in protected if not p["permitted"]]

    if ran_as_subject:
        conclusion = (
            "run as the subject account: every protected target denied the "
            "access, and the workspace permitted write, readback, and delete"
            if not permitted and cycle.get("write_allowed")
            else "run as the subject account: the boundary did NOT behave as the "
                 "M005 policy describes; see the individual attempts"
        )
        boundary = not permitted
    else:
        conclusion = (
            f"run as {identity.domain}\\{identity.account}, NOT the subject "
            "account. Protected access is expected to succeed for the operator, "
            "who owns these files; M005's boundary is a boundary against the "
            "subject account. This run establishes that the probe works, and "
            "establishes nothing about the restricted identity."
        )
        boundary = None

    return {
        "ran_as_subject_account": ran_as_subject,
        "runner_account": f"{identity.domain}\\{identity.account}",
        "runner_sid": identity.sid,
        "protected_attempts": len(protected),
        "protected_denied": len(denied),
        "protected_permitted": len(permitted),
        "boundary_holds": boundary,
        "boundary_meaningful": ran_as_subject,
        "workspace_write_allowed": bool(cycle.get("write_allowed")),
        "workspace_readback_ok": bool(cycle.get("readback_ok")),
        "workspace_cleanup_ok": bool(cycle.get("cleanup_ok")),
        "permitted_attempts": permitted,
        "conclusion": conclusion,
    }


def main(argv: list[str] | None = None) -> int:
    """Child entry point. Emits one JSON object on stdout."""
    parser = argparse.ArgumentParser(
        prog="python -m foundation.probe",
        description=(
            "Attempt the M011 access probe and report the result as JSON. "
            "Read-only with respect to policy: no ACL is changed."
        ),
    )
    parser.add_argument(
        "--identity-and-access", action="store_true",
        help="run the identity, protected-path, workspace, and network probes",
    )
    parser.add_argument(
        "--root", default=None,
        help="laboratory root; defaults to the configured project root",
    )
    args = parser.parse_args(argv)

    # A Windows child launched with CREATE_NO_WINDOW may have no console, so
    # stdout is written through the binary stream to avoid the cp1252 that
    # sys.stdout can default to on this host.
    payload = run_probe(args.root)
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except UnicodeEncodeError:  # pragma: no cover - console encoding fallback
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
