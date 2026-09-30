"""Resolve an interpreter the subject account can actually execute, and build
the launch command. Executes nothing.

Why this module exists
----------------------
``Start-Process -FilePath "py"`` failed for the human with *"The file cannot be
accessed by the system."* The cause is not ``BABY_AI_TEST`` and not a birth
problem. ``py`` resolves to an **App Execution Alias** under the operator's own
profile::

    C:\\Users\\k.tharun balaji\\AppData\\Local\\Microsoft\\WindowsApps\\py.exe

App Execution Aliases are per-user, so ``BABY_AI_TEST`` cannot reach that path at
all. Pointing at the *real* interpreter is necessary but not sufficient, which is
the part this module is for: the lab's CPython 3.14.3 also lives inside the
operator's profile, and that entire directory chain grants ``SYSTEM``,
``Administrators`` and the operator **only** -- there is no ``BUILTIN\\Users`` ACE
anywhere from ``C:\\Users\\k.tharun balaji`` downwards, so the account cannot even
traverse into it. A correct absolute path is still the wrong answer.

The same fact bites harder later: M010 found the unselected
``llama-server.exe`` under ``.docker\\bin\\inference\\`` with the same three-entry
ACL. So a real M014 birth will be blocked for the same reason as this probe.

What it does
------------
* resolves the operator's ``py`` shim, the ``python`` shim, and the real
  interpreter, and records the difference
* records each candidate's size, SHA-256 and PE architecture
* reads the ACL principals on the candidate and on every ancestor directory, and
  reports whether the subject account could *traverse* to it
* builds the ``Start-Process`` command from absolute paths, and refuses to build
  one for a candidate the subject account cannot reach

What it does not do
-------------------
It never launches anything, never asks for or stores a credential, never modifies
an ACL, a group, a policy or a password, and never creates a task or a service.
``LAUNCH_COMMAND_READY`` is ``False`` on this host, and that is the finding.
"""

from __future__ import annotations

import hashlib
import os
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The App Execution Alias directory. Anything resolved out of here is a per-user
#: shim and is unusable by a different account.
APP_EXECUTION_ALIAS_DIR = "WindowsApps"

#: Principals that could grant the subject account access. A path is only
#: reachable if one of these appears on it *and* on every ancestor.
#: ``BABY_AI_TEST`` is not listed: it is in no group at all, which is exactly why
#: it must be named explicitly wherever it is granted anything.
REACHABLE_PRINCIPALS: tuple[str, ...] = (
    "BABY_AI_TEST",
    "BUILTIN\\Users",
    "NT AUTHORITY\\Authenticated Users",
    "NT AUTHORITY\\Everyone",
    "Everyone",
)

#: Machine-readable PE machine types.
_PE_MACHINES: dict[int, str] = {0x014C: "x86", 0x8664: "x64", 0xAA64: "arm64"}


@dataclass
class ExecutableFacts:
    """One candidate executable, described without running it."""

    path: str
    exists: bool = False
    is_file: bool = False
    size_bytes: int | None = None
    sha256: str = "UNAVAILABLE"
    pe_machine: str = "UNAVAILABLE"
    is_app_execution_alias: bool = False
    reachable_by_subject: bool = False
    blocking_principals: list[str] = field(default_factory=list)
    ancestor_principals: dict[str, list[str]] = field(default_factory=dict)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "is_regular_file": self.is_file,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "pe_machine": self.pe_machine,
            "is_app_execution_alias": self.is_app_execution_alias,
            "reachable_by_subject": self.reachable_by_subject,
            "blocking_principals": list(self.blocking_principals),
            "detail": self.detail,
        }


def _run(argv: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a read-only inspection command.

    ``shell=False`` and a closed stdin, per the project's standing subprocess
    rule (``tests/test_m010_boundary.py``). The arguments come from this module
    and from the operator's own path resolution, never from a document.
    """
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          shell=False, stdin=subprocess.DEVNULL,
                          encoding="utf-8", errors="replace")


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pe_machine(path: Path) -> str:
    """The PE machine type, read from the header. ``x86_64`` here, for example.

    Read rather than trusted from the filename, which is the same discipline the
    laboratory applies to a model artifact: a name is a claim, bytes are a fact.
    """
    try:
        with path.open("rb") as handle:
            if handle.read(2) != b"MZ":
                return "not a PE image"
            handle.seek(0x3C)
            offset = struct.unpack("<I", handle.read(4))[0]
            handle.seek(offset)
            if handle.read(4) != b"PE\0\0":
                return "not a PE image"
            handle.seek(offset + 4)
            machine = struct.unpack("<H", handle.read(2))[0]
        return _PE_MACHINES.get(machine, f"unknown (0x{machine:04X})")
    except (OSError, struct.error):
        return "UNAVAILABLE"


def _acl_principals(path: Path) -> list[str]:
    """The principals named in a path's ACL, read-only.

    ``icacls`` is used rather than :mod:`pywin32`, which is not a dependency.
    Entries come back as ``PRINCIPAL:(FLAGS)(RIGHTS)`` and a principal may contain
    spaces -- ``NT AUTHORITY\\SYSTEM`` -- so the name is reassembled from every
    whitespace-separated token up to the one carrying the ``:(``.

    Deny entries are recorded as such, because a directory can grant ``Users``
    read and deny it write -- which is exactly the M005 design, and collapsing
    the two would make the boundary look breached when it is intact.
    """
    try:
        result = _run(["icacls", str(path)])
    except (OSError, subprocess.SubprocessError):
        return []
    principals: set[str] = set()
    for line in (result.stdout or "").splitlines():
        name_parts: list[str] = []
        for token in line.split():
            if ":(" in token:
                name_parts.append(token.split(":(")[0])
                name = " ".join(part for part in name_parts if part).strip()
                if name and name.lower() != "successfully":
                    principals.add(
                        f"{name}:{'DENY' if '(DENY)' in token else 'ALLOW'}"
                    )
                break
            name_parts.append(token)
    return sorted(principals)


def _ancestors(path: Path) -> list[Path]:
    """Every directory from the file's parent up to the drive root."""
    chain: list[Path] = []
    current = path.parent
    while True:
        chain.append(current)
        if current.parent == current:
            break
        current = current.parent
    return chain


def reachable_by_subject(path: str | Path) -> dict[str, Any]:
    """Whether ``BABY_AI_TEST`` could execute a file at this path.

    Checks two things, and both are required:

    1. the file itself is readable/executable by a principal the account belongs
       to (or ``Users`` / ``Authenticated Users`` / ``Everyone``); and
    2. *every* ancestor directory is traversable by one of those principals.

    The second is the one that is easy to miss. A file can be world-executable
    and still be unreachable because a parent directory above it is private --
    which is precisely the situation on this host, and precisely why pointing at
    the correct absolute interpreter path does not fix the launch.

    Works for a file or a directory: for a directory its own ACL is the access
    check, since traversing *into* it is what matters.
    """
    target = Path(path)
    is_directory = target.is_dir()
    own_principals = _acl_principals(target) if target.exists() else []
    own_ok = any(
        principal.rsplit(":", 1)[0] in REACHABLE_PRINCIPALS
        and principal.endswith("ALLOW") for principal in own_principals
    ) and not any(
        principal.rsplit(":", 1)[0] in REACHABLE_PRINCIPALS
        and principal.endswith("DENY") for principal in own_principals
    )

    ancestors: dict[str, list[str]] = {}
    blocked: list[str] = []
    start = target if is_directory else target.parent
    for directory in _ancestors(target):
        if is_directory and directory == target:
            continue
        principals = _acl_principals(directory)
        ancestors[str(directory)] = principals
        ok = any(
            principal.rsplit(":", 1)[0] in REACHABLE_PRINCIPALS
            and principal.endswith("ALLOW") for principal in principals
        )
        if not ok:
            blocked.append(str(directory))

    reachable = bool(own_ok and not blocked)
    return {
        "file_principals": own_principals,
        "file_accessible": own_ok,
        "is_directory": is_directory,
        "ancestor_principals": ancestors,
        "blocked_ancestors": blocked,
        "reachable": reachable,
        "detail": (
            f"{target} is reachable by the subject account"
            if reachable else
            "not reachable by the subject account. "
            + (f"the target itself does not grant it. " if not own_ok else "")
            + (f"Untraversable ancestors: {', '.join(blocked)}." if blocked else "")
        ),
    }


def describe_executable(path: str | Path) -> ExecutableFacts:
    """Facts about one candidate executable. Reads; never runs it."""
    target = Path(path)
    facts = ExecutableFacts(path=str(target))
    facts.is_app_execution_alias = APP_EXECUTION_ALIAS_DIR in target.parts
    facts.exists = target.exists()
    if not facts.exists:
        facts.detail = f"{target} does not exist"
        return facts
    facts.is_file = target.is_file()
    if not facts.is_file:
        facts.detail = f"{target} is not a regular file"
        return facts

    if facts.is_app_execution_alias:
        # An App Execution Alias is a zero-length reparse point, so it has no
        # bytes to hash. Recorded explicitly rather than as an opaque read error,
        # because *this* is the reason the human's launch failed: the alias is a
        # per-user shim that resolves only for the operator, and Windows reports it
        # as "the file cannot be accessed by the system" for anyone else.
        try:
            facts.size_bytes = target.stat().st_size
        except OSError:
            facts.size_bytes = 0
        facts.sha256 = "UNAVAILABLE (App Execution Alias: a per-user shim with no bytes)"
        facts.pe_machine = "UNAVAILABLE (reparse point)"
        reach = reachable_by_subject(target)
        facts.reachable_by_subject = bool(reach["reachable"])
        facts.detail = (
            "this is an App Execution Alias, a per-user shim with no bytes behind "
            "it. It resolves only for the account that created it, so no other "
            "account can launch it, and Windows reports that as 'the file cannot "
            "be accessed by the system'. Use the real interpreter instead."
        )
        return facts

    try:
        facts.size_bytes = target.stat().st_size
        facts.sha256 = _digest(target)
    except OSError as exc:
        facts.detail = f"could not be read: {exc}"
        return facts
    facts.pe_machine = _pe_machine(target)

    reach = reachable_by_subject(target)
    facts.reachable_by_subject = bool(reach["reachable"])
    if not facts.reachable_by_subject:
        facts.blocking_principals = reach["blocked_ancestors"]
    facts.detail = str(reach["detail"])
    return facts


def operator_interpreter() -> ExecutableFacts:
    """The real interpreter behind the operator's ``py``.

    ``sys.executable`` is preferred over a filesystem search: it is the
    interpreter actually running this laboratory, resolved by Python itself
    rather than guessed from ``PATH``.
    """
    import sys

    return describe_executable(os.path.realpath(sys.executable))


def shim_paths() -> list[ExecutableFacts]:
    """What ``py`` and ``python`` resolve to, as shims.

    Resolved with ``where.exe`` so the report shows what Windows would hand to
    ``Start-Process``, not what this process happens to prefer.
    """
    found: list[ExecutableFacts] = []
    for name in ("py", "python"):
        try:
            result = _run(["where.exe", name])
        except (OSError, subprocess.SubprocessError):
            continue
        for line in (result.stdout or "").splitlines():
            candidate = line.strip()
            if candidate:
                found.append(describe_executable(candidate))
    return found


def probe_path(root: str | Path | None = None) -> Path:
    """The absolute path of the subject boundary probe.

    Resolved from the repository root, never from the current working directory
    and never from the operator's home directory -- a launch under another
    account must not depend on where the operator happened to be standing.
    """
    if root is None:
        from babylab.paths import default_paths

        root = default_paths().root
    return (Path(root) / "scripts" / "subject_boundary_probe.py").resolve()


def build_launch_command(
    python_exe: str,
    probe: str,
    working_directory: str,
) -> str:
    """The exact ``Start-Process`` command. Built, never executed.

    Refuses non-absolute inputs rather than emitting a command that would
    resolve differently under the subject account. A command that is *mostly*
    correct is the dangerous kind here, because it fails with an error that looks
    like a permissions problem instead of a path problem.
    """
    for label, value in (("python_exe", python_exe),
                         ("probe", probe),
                         ("working_directory", working_directory)):
        if not os.path.isabs(value):
            raise ValueError(
                f"{label} must be an absolute path; got {value!r}. A relative "
                "path would resolve differently under BABY_AI_TEST than it does "
                "for the operator."
            )
    return (
        f'Start-Process -FilePath "{python_exe}" '
        f'-ArgumentList "{probe}" '
        f'-Credential (Get-Credential -UserName "THARUNBALAJI-LA\\BABY_AI_TEST" '
        f'-Message "BABY_AI_TEST boundary probe (M014)") '
        f'-WorkingDirectory "{working_directory}"'
    )


def launch_readiness(root: str | Path | None = None) -> dict[str, Any]:
    """Everything needed to decide whether the launch can work, and why.

    Returns ``ready: False`` whenever the interpreter is not reachable by the
    subject account, whatever else is true. A ready-looking command pointed at an
    interpreter the account cannot execute is the failure this exists to prevent.
    """
    if root is None:
        from babylab.paths import default_paths

        root = default_paths().root

    shims = shim_paths()
    interpreter = operator_interpreter()
    probe = probe_path(root)
    repository = Path(root).resolve()

    probe_facts = describe_executable(probe)
    repo_reach = reachable_by_subject(repository)

    ready = interpreter.reachable_by_subject and probe.exists and \
        repo_reach["reachable"]

    blocking: list[str] = []
    if not interpreter.reachable_by_subject:
        blocking.append(
            f"the interpreter at {interpreter.path} is not executable by "
            f"BABY_AI_TEST: {'; '.join(interpreter.blocking_principals) or 'the file itself is not granted to a reachable principal'}"
        )
    if shims and all(f.is_app_execution_alias for f in shims):
        blocking.append(
            "every py/python on PATH is an App Execution Alias, which is a "
            "per-user shim that resolves only for the operator"
        )
    if not probe.exists:
        blocking.append(f"the probe is missing at {probe}")
    if not repo_reach["reachable"]:
        blocking.append(
            f"the repository at {repository} is not traversable by the subject "
            f"account: {'; '.join(repo_reach['blocked_ancestors'])}"
        )

    command = ""
    if ready:
        command = build_launch_command(
            interpreter.path, str(probe), str(repository),
        )

    return {
        "schema": "babylab/subject-launch-readiness/v1",
        "ready": ready,
        "python_shims": [f.to_dict() for f in shims],
        "python_interpreter": interpreter.to_dict(),
        "probe": probe_facts.to_dict(),
        "repository": str(repository),
        "repository_reachability": {
            "reachable": repo_reach["reachable"],
            "blocked_ancestors": repo_reach["blocked_ancestors"],
        },
        "launch_command": command or "UNAVAILABLE (see blocking)",
        "blocking": blocking,
        "read_only": True,
        "executed": False,
        "credentials_handled": False,
    }


__all__ = [
    "APP_EXECUTION_ALIAS_DIR",
    "REACHABLE_PRINCIPALS",
    "ExecutableFacts",
    "build_launch_command",
    "describe_executable",
    "launch_readiness",
    "operator_interpreter",
    "probe_path",
    "reachable_by_subject",
    "shim_paths",
]
