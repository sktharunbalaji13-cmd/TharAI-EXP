"""M011 Win32 helpers: token duplication and restricted process creation.

Isolated in one module because the ctypes surface is where the sharp edges are,
and a milestone that is about proving an identity should not bury that code
inside a business-logic function.

The one operation performed here is :func:`create_process_as_user`:
``CreateProcessAsUserW`` with a token duplicated from an existing process that
already runs as the intended account. No password is read, requested, or stored.
No shell is involved. The child's stdout is captured so the parent can relay the
identity the child reported *about itself*.
"""

from __future__ import annotations

import ctypes
import enum
import json
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

#: Win32 constants used here.
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_DUPLICATE = 0x0002
TOKEN_ASSIGN_PRIMARY = 0x0008
TOKEN_QUERY = 0x0008
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_ALL_ACCESS = 0xF01FF
SE_PRIVILEGE_ENABLED = 0x00000002
CREATE_NEW_CONSOLE = 0x00000010
CREATE_NO_WINDOW = 0x08000000
STARTF_USESTDHANDLES = 0x00000100
LOGON_WITH_PROFILE = 0x00000001
LOGON32_LOGON_INTERACTIVE = 3

_ERROR_NAMES = {
    5: "ERROR_ACCESS_DENIED",
    87: "ERROR_INVALID_PARAMETER",
    1314: "ERROR_PRIVILEGE_NOT_HELD",
    1326: "ERROR_LOGON_FAILURE",
    1327: "ERROR_ACCOUNT_RESTRICTION",
    1909: "ERROR_ACCOUNT_DISABLED",
    220: "ERROR_INVALID_ACCOUNT",
    87: "ERROR_INVALID_PARAMETER",
}


def last_error() -> int:
    try:
        return int(ctypes.windll.kernel32.GetLastError())
    except Exception:  # noqa: BLE001
        return int(ctypes.get_last_error())


def error_text(code: int) -> str:
    if code in _ERROR_NAMES:
        return f"{_ERROR_NAMES[code]} ({code})"
    try:
        buffer = ctypes.create_unicode_buffer(512)
        length = ctypes.c_ulong(len(buffer))
        if ctypes.windll.kernel32.FormatMessageW(
            0x00001000, None, ctypes.c_ulong(code), 0, buffer, length, None
        ):
            return f"{buffer.value.strip()} ({code})"
    except Exception:  # noqa: BLE001
        pass
    return f"Win32 error {code}"


class Win32Stage(str, enum.Enum):
    """Which step of the sequence failed. A bare "it failed" is not a diagnosis."""

    PRIVILEGE_CHECK = "PRIVILEGE_CHECK"
    FIND_SUBJECT_PROCESS = "FIND_SUBJECT_PROCESS"
    OPEN_PROCESS = "OPEN_PROCESS"
    OPEN_TOKEN = "OPEN_TOKEN"
    DUPLICATE_TOKEN = "DUPLICATE_TOKEN"
    CREATE_PROCESS = "CREATE_PROCESS"
    WAIT = "WAIT"
    READ_OUTPUT = "READ_OUTPUT"
    NO_SUBJECT_PROCESS = "NO_SUBJECT_PROCESS"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


def _declare(advapi: Any, kernel: Any) -> None:
    """Declare the Win32 signatures.

    Undeclared ctypes signatures truncate 64-bit pointers to ``c_int`` and
    produce failures that point at the wrong line entirely.
    """
    advapi.OpenProcessToken.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p)
    ]
    advapi.OpenProcessToken.restype = ctypes.c_int

    advapi.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    advapi.OpenProcess.restype = ctypes.c_void_p

    advapi.DuplicateTokenEx.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
        ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi.DuplicateTokenEx.restype = ctypes.c_int

    advapi.CreateProcessAsUserW.restype = ctypes.c_int


def find_process_for_account(account: str, domain: str) -> tuple[int, str] | None:
    """Find a live process already running as ``domain\\account``.

    A token must be duplicated from an existing process; Windows provides no way
    to mint one for a logged-out account without a password. So the honest
    precondition is "the account has a process", and when it does not the answer
    is ``NO_SUBJECT_PROCESS`` rather than a login attempt.

    Returns ``(pid, detail)`` or ``None``.
    """
    target = f"{domain}\\{account}".lower()
    try:
        completed = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=30,
            stdin=subprocess.DEVNULL, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"tasklist could not be run: {exc}"

    for line in completed.stdout.splitlines():
        if target not in line.lower():
            continue
        parts = [p.strip('" ') for p in line.split('","')]
        if len(parts) < 2:
            continue
        try:
            return int(parts[1]), f"found {parts[0]} running as {target}"
        except ValueError:
            continue
    return None, (
        f"no live process is running as {target}. A token can only be "
        "duplicated from an existing process, and minting one for a logged-out "
        "account requires a password, which this laboratory never accepts."
    )


def create_process_as_user(
    command: list[str],
    *,
    account: str,
    domain: str,
    timeout_seconds: float = 180.0,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    privileges_held: list[str] | None = None,
    privileges_missing: list[str] | None = None,
) -> Any:
    """Create a process as ``domain\\account`` from a duplicated token.

    Returns the ``LaunchResult`` built in :mod:`foundation.restricted`, so the
    import stays one-directional: this module does the Win32 work, and the
    caller owns the policy vocabulary.
    """
    from foundation.restricted import LaunchResult, LaunchState

    advapi = ctypes.windll.advapi32
    kernel = ctypes.windll.kernel32
    _declare(advapi, kernel)

    result = LaunchResult(
        state=LaunchState.NOT_TESTABLE,
        mechanism="CreateProcessAsUserW",
        privileges_held=list(privileges_held or []),
        privileges_missing=list(privileges_missing or []),
    )

    found = find_process_for_account(account, domain)
    if found is None:
        result.state = LaunchState.NOT_TESTABLE
        result.detail = (
            "no process is running as the intended account, so no token can be "
            "duplicated and no restricted process can be created."
        )
        result.evidence["stage"] = Win32Stage.NO_SUBJECT_PROCESS.value
        result.evidence["detail"] = found[1] if isinstance(found, tuple) else ""
        return result

    pid, found_detail = found
    result.evidence["subject_process"] = {"pid": pid, "detail": found_detail}

    handle = advapi.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        result.state = LaunchState.FAILED
        result.error_code = last_error()
        result.evidence["stage"] = Win32Stage.OPEN_PROCESS.value
        result.detail = f"the subject process could not be opened: {error_text(result.error_code)}"
        return result

    token = ctypes.c_void_p()
    try:
        if not advapi.OpenProcessToken(handle, TOKEN_DUPLICATE | TOKEN_QUERY,
                                       ctypes.byref(token)):
            result.state = LaunchState.FAILED
            result.error_code = last_error()
            result.evidence["stage"] = Win32Stage.OPEN_TOKEN.value
            result.detail = (
                "the subject process's token could not be opened for duplication: "
                f"{error_text(result.error_code)}"
            )
            return result

        duplicate = ctypes.c_void_p()
        if not advapi.DuplicateTokenEx(
            token, TOKEN_ALL_ACCESS, None, 0, SecurityImpersonation,
            TokenPrimary, ctypes.byref(duplicate),
        ):
            result.state = LaunchState.FAILED
            result.error_code = last_error()
            result.evidence["stage"] = Win32Stage.DUPLICATE_TOKEN.value
            result.detail = (
                "the token could not be duplicated: "
                f"{error_text(result.error_code)}"
            )
            return result
    finally:
        kernel.CloseHandle(handle)
        if token:
            kernel.CloseHandle(token)

    result = _spawn_with_token(duplicate, command, result, cwd, env,
                               timeout_seconds)
    kernel.CloseHandle(duplicate)
    return result


#: SECURITY_ATTRIBUTES-ish constants for DuplicateTokenEx.
SecurityImpersonation = 2
TokenPrimary = 1


class STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]


def _spawn_with_token(
    token: Any,
    command: list[str],
    result: Any,
    cwd: str | Path | None,
    env: dict[str, str] | None,
    timeout_seconds: float,
) -> Any:
    """Create the process with the duplicated token and collect its stdout.

    The child's stdout carries its own interrogation result as JSON. That JSON
    is the only thing accepted as proof of identity -- the parent does not decide
    that the launch succeeded because a process object came back.
    """
    from foundation.restricted import LaunchState

    advapi = ctypes.windll.advapi32
    kernel = ctypes.windll.kernel32

    startup = STARTUPINFO()
    startup.cb = ctypes.sizeof(STARTUPINFO)
    startup.dwFlags = STARTF_USESTDHANDLES

    # Redirect the child's stdout and stderr to a file so the parent can read
    # them after the child exits. A pipe would need a reader thread and a
    # deadlock-safe drain; a file cannot block the child.
    import os
    import tempfile

    handle_file = tempfile.NamedTemporaryFile(
        mode="w+b", suffix=".m011-child.json", delete=False
    )
    os_handle = _win32_fd(handle_file)

    startup.hStdInput = _null_device()
    startup.hStdOutput = os_handle
    startup.hStdError = os_handle
    startup.dwFlags |= 0x00000100  # STARTF_USESTDHANDLES

    environment_block = None
    import os as _os

    merged = {**dict(_os.environ), **(env or {}), "BABY_AI_M011_CHILD": "1"}
    environment_block = ctypes.create_unicode_buffer(
        "\x00".join(f"{k}={v}" for k, v in merged.items()) + "\x00\x00"
    )

    info = PROCESS_INFORMATION()
    working_dir = str(cwd) if cwd else None
    command_line = ctypes.create_unicode_buffer(" ".join(
        f'"{part}"' if " " in part else part for part in command
    ))

    ok = advapi.CreateProcessAsUserW(
        token, None, command_line, None, None, False,
        CREATE_NO_WINDOW, None, working_dir, ctypes.byref(startup),
        ctypes.byref(info),
    )
    if not ok:
        result.state = LaunchState.FAILED
        result.error_code = last_error()
        result.evidence["stage"] = Win32Stage.CREATE_PROCESS.value
        result.detail = (
            "CreateProcessAsUserW was refused: "
            f"{error_text(result.error_code)}"
        )
        _close(os_handle)
        return result

    kernel.WaitForSingleObject(info.hProcess, int(timeout_seconds * 1000))
    code = wintypes.DWORD()
    kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    kernel.CloseHandle(info.hThread)
    kernel.CloseHandle(info.hProcess)
    _close(os_handle)

    try:
        handle_file.seek(0)
        raw = handle_file.read().decode("utf-8", errors="replace")
    finally:
        handle_file.close()
        try:
            Path(handle_file.name).unlink(missing_ok=True)
        except OSError:  # pragma: no cover
            pass

    result.evidence["exit_code"] = int(code.value)
    result.evidence["child_stdout"] = raw[:4000]

    try:
        observed = json.loads(raw.strip() or "{}")
    except json.JSONDecodeError:
        result.state = LaunchState.FAILED
        result.evidence["stage"] = Win32Stage.READ_OUTPUT.value
        result.detail = (
            "the restricted child did not emit a JSON identity record, so the "
            "identity of the process that ran is not established. The parent "
            "will not infer it from the fact that a process was created."
        )
        return result

    result.observed = observed
    result.evidence["stage"] = "COMPLETE"
    if str(observed.get("sid", "")).upper() == result.expected_sid.upper():
        result.state = LaunchState.VERIFIED
        result.detail = (
            "the child process reports the intended restricted account, measured "
            "from its own token rather than inferred from the launch request."
        )
    else:
        result.state = LaunchState.FAILED
        result.detail = (
            "the restricted child reported a different identity than the one "
            f"intended: {observed.get('domain')}\\{observed.get('account')} "
            f"(SID {observed.get('sid')})"
        )
    return result


def _win32_fd(python_file: Any) -> int:
    """The Win32 handle behind an open file object."""
    import msvcrt

    return int(msvcrt.get_osfhandle(python_file.fileno()))


def _null_device() -> int:
    """A read handle on NUL, so the child inherits no console input."""
    import msvcrt

    return int(msvcrt.get_osfhandle(os.open(os.devnull, os.O_RDONLY)))


def _close(handle: int) -> None:
    try:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:  # noqa: BLE001
        pass


__all__ = [
    "Win32Stage",
    "create_process_as_user",
    "error_text",
    "find_process_for_account",
    "last_error",
]
