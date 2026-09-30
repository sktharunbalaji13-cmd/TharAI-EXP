"""M011 process identity: who actually ran this.

Why a module for it
-------------------
M011's central requirement is that the foundation runtime be exercised as a
*restricted identity*, not as the human operator. Verifying that means reading
the identity of a running process -- its token, its SID, its integrity level,
its elevation state, its PID, and the digest of the image it is running.

The temptation is to infer all of that from configuration: the script says it
should run as ``BABY_AI_TEST``, therefore it did. That inference is exactly what
this module exists to refuse. A launch that silently fell back to the operator's
token would look identical from the outside unless the resulting process is
actually interrogated.

What is measured, and what cannot be
------------------------------------
* **Own process** -- fully measurable. Token, SID, integrity, elevation, PID,
  image digest.
* **Another process by PID** -- measurable for token and image, provided the
  caller can open it. Opening a process owned by another account requires
  rights this session does not hold, so a failure is reported as
  ``NOT_ESTABLISHED`` with the Win32 error rather than guessed.
* **A process that has exited** -- not measurable at all. If the caller wants the
  identity of a process that already terminated, the honest answer is that the
  evidence must be captured while it runs, which is why
  :func:`capture_own_identity` is designed to be called from inside the
  restricted child.
"""

from __future__ import annotations

import ctypes
import enum
import getpass
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Win32 error codes worth naming rather than printing as integers. The list is
#: partial on purpose -- an unnamed code is still reported with its number, and
#: an entry is added here when a code is actually encountered.
_ERROR_NAMES = {
    5: "ERROR_ACCESS_DENIED",
    6: "ERROR_INVALID_HANDLE",
    87: "ERROR_INVALID_PARAMETER",
    1314: "ERROR_PRIVILEGE_NOT_HELD",
    1326: "ERROR_LOGON_FAILURE",
    1327: "ERROR_ACCOUNT_RESTRICTION",
    1909: "ERROR_ACCOUNT_DISABLED",
    220: "ERROR_INVALID_ACCOUNT",
}


def _last_error() -> int:
    """The real Win32 error code.

    ``_last_error()`` reads a *copy* Windows makes for ctypes and does
    not track the real thread error, so after a failed ``OpenProcess`` it can
    report 0 while the OS reported 5. That turned
    ``ERROR_ACCESS_DENIED`` into ``Win32 error 0`` and made an access refusal
    look like a success with a null handle. ``kernel32.GetLastError()`` is the
    authoritative source, so it is what every diagnostic here uses.
    """
    try:
        return int(ctypes.windll.kernel32.GetLastError())
    except Exception:  # noqa: BLE001 - non-Windows or a stubbed ctypes
        return int(_last_error())  # fallback only


def _error_text(code: int) -> str:
    """Name a Win32 error, and look it up when the table has no entry."""
    if code in _ERROR_NAMES:
        return f"{_ERROR_NAMES[code]} ({code})"
    message = ""
    try:
        buffer = ctypes.create_unicode_buffer(512)
        length = ctypes.c_ulong(len(buffer))
        if ctypes.windll.kernel32.FormatMessageW(
            0x00001000, None, ctypes.c_ulong(code), 0, buffer, length, None
        ):
            message = buffer.value.strip()
    except Exception:  # noqa: BLE001 - the message table is best effort
        message = ""
    if message:
        return f"{message} ({code})"
    return f"Win32 error {code}"


class IdentityStatus(str, enum.Enum):
    VERIFIED = "VERIFIED"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass
class ProcessIdentity:
    """Who a process actually is, as read from the OS."""

    status: IdentityStatus = IdentityStatus.NOT_ESTABLISHED
    pid: int | None = None
    account: str = "UNAVAILABLE"
    domain: str = "UNAVAILABLE"
    sid: str = "UNAVAILABLE"
    integrity_level: str = "UNAVAILABLE"
    is_elevated: bool | None = None
    is_admin_token: bool | None = None
    executable_path: str = "UNAVAILABLE"
    executable_sha256: str = "UNAVAILABLE"
    executable_digest_basis: str = "unavailable"
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def verified(self) -> bool:
        return self.status is IdentityStatus.VERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "pid": self.pid,
            "account": self.account,
            "domain": self.domain,
            "sid": self.sid,
            "integrity_level": self.integrity_level,
            "is_elevated": self.is_elevated,
            "is_admin_token": self.is_admin_token,
            "executable_path": self.executable_path,
            "executable_sha256": self.executable_sha256,
            "executable_digest_basis": self.executable_digest_basis,
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }


# ---------------------------------------------------------------------------
# token interrogation
# ---------------------------------------------------------------------------
def _open_process_token(process_handle: int, access: int = 0x0008 | 0x0020):
    """Open a process token. Returns ``(handle, None)`` or ``(None, error_text)``.

    The handle is returned as a plain ``int`` rather than a ``c_void_p`` so that
    every call site can wrap it exactly once. Returning the ctypes object and
    re-wrapping it downstream is how a token handle turns into a
    ``TypeError: cannot be converted to pointer`` several frames from the cause.
    """
    advapi = ctypes.windll.advapi32
    handle = ctypes.c_void_p()
    if not advapi.OpenProcessToken(
        ctypes.c_void_p(process_handle), access, ctypes.byref(handle)
    ):
        return None, _error_text(_last_error())
    return handle.value, None


#: TOKEN_INFORMATION_CLASS values used here.
TOKEN_USER_CLASS = 1
TOKEN_GROUPS_CLASS = 2
TOKEN_ELEVATION_CLASS = 20
TOKEN_MANDATORY_LABEL_CLASS = 25

_API_DECLARED = False


def _declare_token_apis(advapi: Any, kernel: Any) -> None:
    """Declare the Win32 signatures once.

    Without explicit ``argtypes``/``restype``, ctypes marshals pointers as
    ``c_int`` and truncates them on a 64-bit host. That produces an
    ``OverflowError`` that points at the wrong line entirely, so the
    declarations are made up front and idempotently.
    """
    global _API_DECLARED
    if _API_DECLARED:
        return

    advapi.GetTokenInformation.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    advapi.GetTokenInformation.restype = ctypes.c_int

    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                              ctypes.POINTER(ctypes.c_wchar_p)]
    advapi.ConvertSidToStringSidW.restype = ctypes.c_int

    advapi.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                        ctypes.POINTER(ctypes.c_void_p)]
    advapi.OpenProcessToken.restype = ctypes.c_int

    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int

    kernel.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    kernel.QueryFullProcessImageNameW.restype = ctypes.c_int

    _API_DECLARED = True


#: Domains reported by the machine itself, so the label is observed rather than
#: inferred from a profile path.
_MACHINE_DOMAIN_KEY = r"SYSTEM\CurrentControlSet\Control\ComputerName\ActiveComputerName"


def _account_from_profile_list(sid_text: str) -> tuple[str, str]:
    """Resolve ``(account, domain)`` for a SID.

    The account name is the last component of the profile path. The *domain* is
    not the parent directory of that path -- ``C:\\Users\\alice`` has no domain
    in it, and reporting one would be reading a filesystem location as a
    network identity. The machine's own ComputerName key is used instead, with
    the profile path reported separately so the derivation is inspectable.
    """
    account = "UNAVAILABLE"
    domain = "UNAVAILABLE"

    import winreg  # type: ignore[import-not-found]

    key = winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList",
    )
    index = 0
    while True:
        try:
            sid_key = winreg.EnumKey(key, index)
        except OSError:
            break
        index += 1
        if sid_key != sid_text:
            continue
        try:
            sub = winreg.OpenKey(key, sid_key)
            with sub:
                profile = str(winreg.QueryValueEx(sub, "ProfileImagePath")[0])
            account = Path(profile).name
        except OSError:
            pass
        break

    try:
        name_key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, _MACHINE_DOMAIN_KEY
        )
        with name_key:
            domain = str(winreg.QueryValueEx(name_key, "ComputerName")[0])
    except OSError:
        domain = "UNAVAILABLE"

    return account, domain


def _token_user_and_groups(token: Any) -> dict[str, Any]:
    advapi = ctypes.windll.advapi32
    kernel = ctypes.windll.kernel32
    # ctypes defaults every unspecified argument to c_int, which silently
    # truncates a 64-bit pointer on x64. Declaring the signatures is not
    # optional here: without it, ConvertSidToStringSidW receives a truncated
    # SID and raises OverflowError several frames from the real fault.
    _declare_token_apis(advapi, kernel)

    # TOKEN_USER
    size = ctypes.c_ulong()
    advapi.GetTokenInformation(
        token, 1, None, 0, ctypes.byref(size)
    )
    buffer = ctypes.create_string_buffer(size.value)
    if not advapi.GetTokenInformation(
        token, 1, buffer, size, ctypes.byref(size)
    ):
        return {"error": _error_text(_last_error())}

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p),
                    ("Attributes", ctypes.c_ulong)]

    class TOKEN_USER(ctypes.Structure):
        _fields_ = [("User", SID_AND_ATTRIBUTES)]

    token_user = ctypes.cast(buffer, ctypes.POINTER(TOKEN_USER)).contents
    sid_pointer = token_user.User.Sid

    wchar = ctypes.c_wchar_p()
    if not advapi.ConvertSidToStringSidW(
        ctypes.c_void_p(sid_pointer), ctypes.byref(wchar)
    ):
        return {"error": _error_text(_last_error())}
    sid_text = wchar.value if wchar.value else "UNAVAILABLE"
    kernel.LocalFree(ctypes.c_void_p(ctypes.cast(wchar, ctypes.c_void_p).value))

    # TOKEN_ELEVATION
    elevation = ctypes.c_ulong()
    e_size = ctypes.c_ulong(ctypes.sizeof(elevation))
    elevated: bool | None = None
    if advapi.GetTokenInformation(
        token, 20, ctypes.byref(elevation), e_size,
        ctypes.byref(e_size),
    ):
        elevated = elevation.value != 0

    # TOKEN_MANDATORY_LABEL -> integrity level, read from the same token.
    integrity = _integrity_of_token(token)

    account = "UNAVAILABLE"
    domain = "UNAVAILABLE"
    try:
        account, domain = _account_from_profile_list(sid_text)
    except Exception:  # noqa: BLE001
        pass

    return {
        "sid": sid_text,
        "is_elevated": elevated,
        "account": account,
        "domain": domain,
    }


#: Mandatory-label RIDs and their names.
_INTEGRITY_RIDS = {
    0x0000: "UNTRUSTED",
    0x1000: "LOW",
    0x2000: "MEDIUM",
    0x3000: "HIGH",
    0x4000: "SYSTEM",
}


def _integrity_of_token(token: int) -> str:
    """Integrity level from a token's mandatory label.

    Read from the label's RID rather than from the user's group membership,
    because a UAC-split token keeps the Administrators SID as deny-only and a
    membership check would report a misleading answer.
    """
    advapi = ctypes.windll.advapi32
    _declare_token_apis(advapi, ctypes.windll.kernel32)

    size = ctypes.c_ulong()
    advapi.GetTokenInformation(
        ctypes.c_void_p(token), TOKEN_MANDATORY_LABEL_CLASS, None, 0,
        ctypes.byref(size),
    )
    if not size.value:
        return "UNAVAILABLE"
    buffer = ctypes.create_string_buffer(size.value)
    if not advapi.GetTokenInformation(
        ctypes.c_void_p(token), TOKEN_MANDATORY_LABEL_CLASS, buffer, size,
        ctypes.byref(size),
    ):
        return f"UNAVAILABLE ({_error_text(_last_error())})"

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_ulong)]

    class TOKEN_MANDATORY_LABEL(ctypes.Structure):
        _fields_ = [("Label", SID_AND_ATTRIBUTES)]

    label = ctypes.cast(buffer, ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents
    return _integrity_from_sid(label.Label.Sid)


def _integrity_from_sid(sid_pointer: int) -> str:
    """Map a mandatory-label SID to its integrity name.

    A SID's layout is fixed and public: one revision byte, one sub-authority
    count byte, a six-byte identifier authority, then the sub-authorities as
    DWORDs. The RID is the last of them, so the count byte is what indexes it.

    The count is read straight out of the structure rather than through
    ``GetTokenInformation``, which takes a *token* and not a SID pointer. Passing
    a SID there fails quietly -- it reports an empty result rather than an
    error -- and the integrity level then reads UNAVAILABLE for a token that
    has one. Reading the byte is both correct and one syscall fewer.
    """
    if not sid_pointer:
        return "UNAVAILABLE (no label SID)"
    header = ctypes.cast(
        ctypes.c_void_p(sid_pointer), ctypes.POINTER(ctypes.c_ubyte)
    )
    sub_count = int(header[1])
    if sub_count < 1:
        return "UNAVAILABLE (label SID carries no sub-authority)"
    rid_address = ctypes.c_void_p(sid_pointer + 8 + 4 * (sub_count - 1))
    rid = ctypes.cast(rid_address, ctypes.POINTER(ctypes.c_ulong)).contents.value
    return _INTEGRITY_RIDS.get(
        rid, f"UNRECOGNISED_RID_0x{rid:04X}"
    )


def _is_admin(elevated: bool | None) -> bool | None:
    """Whether the token carries the Administrators group.

    Read from the token's group list rather than from the current process's
    well-known SID, so the answer describes *this* token.
    """
    if elevated is None:
        return None
    if elevated:
        return True
    # A non-elevated token on a UAC machine usually still has the Administrators
    # SID as deny-only, so a negative elevation does not prove non-membership.
    # Reported as False-with-a-caveat rather than a confident boolean.
    return False


def image_digest(path: str | Path) -> tuple[str, str]:
    """SHA-256 of an executable, with the basis stated.

    The basis is reported because a hash is only as good as its source: a digest
    of the *script* that launched a process says nothing about the image.
    """
    from foundation.runtime_identity import sha256_binary

    return sha256_binary(path)


def capture_own_identity(
    executable: str | Path | None = None,
) -> ProcessIdentity:
    """Interrogate the calling process.

    This is the function the restricted child calls on itself. It is the only
    way to get a trustworthy answer about which account actually executed the
    runtime, because the parent cannot always open a process owned by another
    account -- and a parent that inferred identity from its own configuration
    would be reporting its intention rather than the outcome.
    """
    kernel = ctypes.windll.kernel32
    process_handle = kernel.GetCurrentProcess()

    identity = ProcessIdentity(pid=int(os.getpid()))

    target = str(executable) if executable else sys.executable
    digest, basis = image_digest(target)
    identity.executable_path = target
    identity.executable_sha256 = digest
    identity.executable_digest_basis = basis

    token, error = _open_process_token(process_handle)
    if token is None:
        identity.detail = f"the process token could not be opened: {error}"
        identity.evidence["open_token_error"] = error
        return identity

    try:
        details = _token_user_and_groups(token)
    finally:
        kernel.CloseHandle(token)

    if "error" in details:
        identity.detail = f"token information could not be read: {details['error']}"
        identity.evidence["token_error"] = details["error"]
        return identity

    identity.sid = str(details.get("sid", "UNAVAILABLE"))
    identity.account = str(details.get("account", "UNAVAILABLE"))
    identity.domain = str(details.get("domain", "UNAVAILABLE"))
    identity.is_elevated = details.get("is_elevated")
    identity.is_admin_token = _is_admin(details.get("is_elevated"))
    identity.integrity_level = _integrity_from_sid_of_current()

    if identity.account == "UNAVAILABLE":
        # Fall back to the OS's own answer rather than leaving the field blank.
        try:
            identity.account = getpass.getuser()
        except Exception:  # noqa: BLE001
            pass
        identity.evidence["account_source"] = "getpass.getuser fallback"

    identity.status = IdentityStatus.VERIFIED
    identity.detail = (
        f"the running process reports {identity.domain}\\{identity.account} "
        f"(SID {identity.sid}, {identity.integrity_level} integrity, "
        f"elevated={identity.is_elevated})"
    )
    return identity


def _integrity_from_sid_of_current() -> str:
    """Integrity level of the current process, read from its own token."""
    kernel = ctypes.windll.kernel32
    advapi = ctypes.windll.advapi32

    process_handle = kernel.GetCurrentProcess()
    token, error = _open_process_token(process_handle)
    if token is None:
        return f"UNAVAILABLE ({error})"

    try:
        size = ctypes.c_ulong()
        advapi.GetTokenInformation(
            token, 25, None, 0, ctypes.byref(size)
        )
        if not size.value:
            return "UNAVAILABLE"
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(
            token, 25, buffer, size, ctypes.byref(size)
        ):
            return f"UNAVAILABLE ({_error_text(_last_error())})"

        class SID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_ulong)]

        class TOKEN_MANDATORY_LABEL(ctypes.Structure):
            _fields_ = [("Label", SID_AND_ATTRIBUTES)]

        label = ctypes.cast(
            buffer, ctypes.POINTER(TOKEN_MANDATORY_LABEL)
        ).contents
        return _integrity_from_sid(label.Label.Sid)
    finally:
        kernel.CloseHandle(token)


def capture_by_pid(pid: int) -> ProcessIdentity:
    """Interrogate another process by PID.

    Requires the right to open it. When that right is absent the result is
    ``NOT_ESTABLISHED`` with the Win32 error -- not an assumption that the
    process runs as whoever launched it.
    """
    kernel = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    PROCESS_QUERY_INFORMATION = 0x0400

    handle = kernel.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_QUERY_INFORMATION,
        False, pid,
    )
    if not handle:
        # Read the error immediately: any intervening call clears it, and an
        # unrelated call between OpenProcess and the read is what turned
        # ERROR_ACCESS_DENIED into a bare 0.
        code = _last_error()
        return ProcessIdentity(
            status=IdentityStatus.NOT_ESTABLISHED,
            pid=pid,
            detail=(
                f"process {pid} could not be opened: {_error_text(code)}. Opening "
                "a process owned by another account requires rights this session "
                "does not hold, so its identity is not established here."
            ),
            evidence={"open_process_error": _error_text(code)},
        )

    try:
        identity = ProcessIdentity(pid=pid)
        identity.detail = f"process {pid} was opened for interrogation"

        size = ctypes.c_ulong(0)
        kernel.QueryFullProcessImageNameW(
            ctypes.c_void_p(handle), 0, None, ctypes.byref(size)
        )
        if size.value:
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel.QueryFullProcessImageNameW(
                ctypes.c_void_p(handle), 0, buffer, ctypes.byref(size)
            ):
                identity.executable_path = buffer.value
                digest, basis = image_digest(buffer.value)
                identity.executable_sha256 = digest
                identity.executable_digest_basis = basis

        token, error = _open_process_token(handle)
        if token is None:
            identity.status = IdentityStatus.NOT_ESTABLISHED
            identity.detail = (
                f"the token of process {pid} could not be opened: {error}"
            )
            identity.evidence["open_token_error"] = error
            return identity

        try:
            details = _token_user_and_groups(token)
        finally:
            kernel.CloseHandle(token)

        if "error" in details:
            identity.detail = (
                f"token information for process {pid} could not be read: "
                f"{details['error']}"
            )
            return identity

        identity.sid = str(details.get("sid", "UNAVAILABLE"))
        identity.account = str(details.get("account", "UNAVAILABLE"))
        identity.domain = str(details.get("domain", "UNAVAILABLE"))
        identity.is_elevated = details.get("is_elevated")
        identity.status = IdentityStatus.VERIFIED
        identity.detail = (
            f"process {pid} reports {identity.domain}\\{identity.account}"
        )
        return identity
    finally:
        kernel.CloseHandle(handle)


__all__ = [
    "IdentityStatus",
    "ProcessIdentity",
    "capture_by_pid",
    "capture_own_identity",
    "image_digest",
]
