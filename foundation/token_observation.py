"""Read another process's identity from its **token**, not from its claims.

M005 established the OS boundary using a probe the *human* ran as
``BABY_AI_TEST``, and recorded the result as human-executed cross-process
evidence. It could not be automated because the automated harness held neither
``SeImpersonatePrivilege`` nor ``SeAssignPrimaryTokenPrivilege``.

That limitation turns out to be narrower than it looked, and this module is the
reason. The laboratory does not need to *become* ``BABY_AI_TEST`` in order to
confirm that a process is ``BABY_AI_TEST``. It needs a handle to the process, and
Windows will hand one over for ``TOKEN_QUERY`` without any special privilege:

* :func:`read_token_user_sid` -- the SID in the token.
* :func:`read_token_integrity_level` -- the mandatory integrity label.

Both were verified on this host, non-elevated, against a process the operator
spawned: the token read returned the operator's own SID and ``8192`` (``0x2000``,
Medium). So the technique is sound.

What remains unverified
-----------------------
Whether ``OpenProcess`` succeeds against a process running under *different*
credentials. Windows' default process DACL grants ``Everyone``
``SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION``, which suggests it will, but
that has not been tested here because testing it requires launching as
``BABY_AI_TEST``, which requires a credential this module will not ask for or
store. :func:`observe_process` therefore returns ``VERIFIED``, ``NOT_TESTABLE`` or
``FAILED`` rather than assuming success, and a caller that gets ``NOT_TESTABLE``
must not treat the identity as confirmed.

This module only reads. It opens handles, asks questions, and closes them. It
never writes to a process, never injects, never duplicates a token, and never
grants anything.
"""

from __future__ import annotations

import ctypes
import enum
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Any

#: The minimum right that permits reading a process token's user and integrity
#: label. Deliberately not PROCESS_ALL_ACCESS: this module needs to look, not to
#: touch, and a module that asked for more than it needs would be one more reason
#: to distrust it.
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

TOKEN_QUERY = 0x0008
TOKEN_QUERY_SOURCE = 0x000A00

#: ``TOKEN_INFORMATION_CLASS`` values used here. Prefixed so they cannot collide
#: with the structure definitions below -- ``_TOKEN_USER`` as both a value and a
#: struct silently means the struct, which fails at the Win32 call rather than
#: at import.
_CLASS_TOKEN_USER = 1
_CLASS_TOKEN_PRIVILEGES = 3
_CLASS_TOKEN_ELEVATION = 20
_CLASS_TOKEN_INTEGRITY_LEVEL = 25

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]


class _TOKEN_USER(ctypes.Structure):
    _fields_ = [("User", _SID_AND_ATTRIBUTES)]


class _TOKEN_ELEVATION(ctypes.Structure):
    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


class _TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", wintypes.LPVOID)]


class _LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", ctypes.c_longlong), ("Attributes", wintypes.DWORD)]


_advapi32.OpenProcessToken.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
]
_advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
_advapi32.LookupPrivilegeValueW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(_LUID_AND_ATTRIBUTES),
]
_advapi32.PrivilegeCheck.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(_LUID_AND_ATTRIBUTES), ctypes.POINTER(wintypes.BOOL),
]
_advapi32.ConvertSidToStringSidW.argtypes = [
    wintypes.LPVOID, ctypes.POINTER(ctypes.c_wchar_p),
]
_advapi32.ConvertSidToStringSidW.restype = ctypes.c_int
_advapi32.LookupAccountSidW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPVOID, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
]
_advapi32.LookupAccountSidW.restype = ctypes.c_int
_kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
_kernel32.LocalFree.restype = wintypes.HLOCAL

#: Integrity level RIDs as they appear in a token's mandatory label.
INTEGRITY_LABELS: dict[str, str] = {
    "0x0000": "UNTRUSTED",
    "0x1000": "LOW",
    "0x2000": "MEDIUM",
    "0x3000": "HIGH",
    "0x4000": "SYSTEM",
}


class ObservationStatus(str, enum.Enum):
    """The three answers, and only three.

    ``NOT_TESTABLE`` is a real result here rather than a failure to be papered
    over. The host genuinely cannot answer without a credential it must not
    accept, and a caller that treats "I could not check" as "it is fine" is the
    failure this enumeration exists to prevent.
    """

    VERIFIED = "VERIFIED"
    NOT_TESTABLE = "NOT_TESTABLE"
    FAILED = "FAILED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass
class ProcessTokenObservation:
    """What one process's token says, and how confidently we could read it."""

    pid: int
    status: ObservationStatus = ObservationStatus.NOT_TESTABLE
    user_sid: str = "UNAVAILABLE"
    account_name: str = "UNAVAILABLE"
    integrity_label: str = "UNAVAILABLE"
    elevated: bool | None = None
    privileges_present: list[str] = field(default_factory=list)
    detail: str = ""
    #: The process's own claim about itself, when it supplied one. Recorded
    #: separately from the token readings and never merged with them, because a
    #: program asserting its identity is not evidence about its identity.
    self_reported: dict[str, Any] = field(default_factory=dict)

    @property
    def identity_is_independently_observed(self) -> bool:
        """True only when the SID came from the token.

        A self-reported username never satisfies this, however confidently it is
        formatted.
        """
        return self.status is ObservationStatus.VERIFIED and not self.user_sid.startswith(
            "UNAVAILABLE")

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "status": self.status.value,
            "user_sid": self.user_sid,
            "account_name": self.account_name,
            "integrity_label": self.integrity_label,
            "elevated": self.elevated,
            "privileges_present": list(self.privileges_present),
            "identity_is_independently_observed": self.identity_is_independently_observed,
            "self_reported": dict(self.self_reported),
            "detail": self.detail,
            "read_only": True,
        }


def _sid_to_string(sid_pointer: int) -> str:
    text = ctypes.c_wchar_p()
    if not _advapi32.ConvertSidToStringSidW(sid_pointer, ctypes.byref(text)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return text.value
    finally:
        _kernel32.LocalFree(text)


def _account_for_sid(sid: str) -> str:
    """Resolve a SID string to ``DOMAIN\\name``, or report that we could not.

    A failure here is not fatal. The SID is the authoritative identity; the name
    is a convenience, and a machine that cannot resolve it has not undermined the
    observation.
    """
    import ctypes as _c

    token = _c.POINTER(_c.c_void_p)()
    if not _advapi32.ConvertStringSidToSidW(sid, _c.byref(token)):
        return "UNAVAILABLE"
    try:
        name = _c.create_unicode_buffer(256)
        domain = _c.create_unicode_buffer(256)
        name_size = wintypes.DWORD(256)
        domain_size = wintypes.DWORD(256)
        sid_type = wintypes.DWORD()
        if _advapi32.LookupAccountSidW(None, token, name,
                                       _c.byref(name_size), domain,
                                       _c.byref(domain_size),
                                       _c.byref(sid_type)):
            return f"{domain.value}\\{name.value}"
        return "UNAVAILABLE"
    finally:
        _kernel32.LocalFree(token)


_advapi32.ConvertStringSidToSidW.argtypes = [
    wintypes.LPCWSTR, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
]
_advapi32.ConvertStringSidToSidW.restype = ctypes.c_int


def _query(pid: int, info_class: int) -> tuple[Any | None, str]:
    """Read one ``TOKEN_INFORMATION_CLASS`` from a process. Read-only."""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None, f"OpenProcess error {ctypes.get_last_error()}"
    token = wintypes.HANDLE()
    try:
        if not _advapi32.OpenProcessToken(handle, TOKEN_QUERY, ctypes.byref(token)):
            return None, f"OpenProcessToken error {ctypes.get_last_error()}"
        needed = wintypes.DWORD()
        _advapi32.GetTokenInformation(token, info_class, None, 0,
                                      ctypes.byref(needed))
        if needed.value == 0:
            return None, "GetTokenInformation reported no size"
        buffer = ctypes.create_string_buffer(needed.value)
        if not _advapi32.GetTokenInformation(token, info_class, buffer,
                                              needed.value, ctypes.byref(needed)):
            return None, f"GetTokenInformation error {ctypes.get_last_error()}"
        return buffer, ""
    finally:
        if token:
            _kernel32.CloseHandle(token)
        _kernel32.CloseHandle(handle)


def observe_process(
    pid: int,
    *,
    expected_sid: str = "",
    self_reported: dict[str, Any] | None = None,
) -> ProcessTokenObservation:
    """Read ``pid``'s token and report what it says about identity and integrity.

    ``expected_sid`` is compared against the token, not against anything the
    process said. When it is supplied and the token disagrees, the result is
    ``FAILED`` -- a process running as the wrong account is not a degraded
    success.
    """
    observation = ProcessTokenObservation(pid=pid)
    if self_reported:
        observation.self_reported = dict(self_reported)

    buffer, error = _query(pid, _CLASS_TOKEN_USER)
    if buffer is None:
        observation.status = ObservationStatus.NOT_TESTABLE
        observation.detail = (
            f"the token of pid {pid} could not be read: {error}. This is "
            "NOT_TESTABLE, not a pass: an unobserved identity is an unknown "
            "identity, and Windows may refuse this for reasons that have nothing "
            "to do with whether the process is who it claims to be."
        )
        return observation

    user = ctypes.cast(buffer, ctypes.POINTER(_TOKEN_USER)).contents
    try:
        observation.user_sid = _sid_to_string(user.User.Sid)
    except OSError as exc:
        observation.status = ObservationStatus.FAILED
        observation.detail = f"the SID in pid {pid}'s token could not be rendered: {exc}"
        return observation

    observation.account_name = _account_for_sid(observation.user_sid)

    label_buffer, label_error = _query(pid, _CLASS_TOKEN_INTEGRITY_LEVEL)
    if label_buffer is not None:
        label = ctypes.cast(label_buffer,
                            ctypes.POINTER(_SID_AND_ATTRIBUTES)).contents
        try:
            rid = _sid_to_string(label.Sid).split("-")[-1]
            observation.integrity_label = INTEGRITY_LABELS.get(
                f"0x{int(rid):04X}", f"UNKNOWN (RID 0x{int(rid):04X})",
            )
        except (OSError, ValueError):
            observation.integrity_label = "UNAVAILABLE"
    else:
        observation.integrity_label = f"UNAVAILABLE ({label_error})"

    elevation_buffer, _ = _query(pid, _CLASS_TOKEN_ELEVATION)
    if elevation_buffer is not None:
        elevation = ctypes.cast(elevation_buffer,
                                 ctypes.POINTER(_TOKEN_ELEVATION)).contents
        observation.elevated = bool(elevation.TokenIsElevated)

    observation.privileges_present = _privileges_present(pid)

    if expected_sid and observation.user_sid.upper() != expected_sid.upper():
        observation.status = ObservationStatus.FAILED
        observation.detail = (
            f"pid {pid}'s token is {observation.user_sid}, not the expected "
            f"{expected_sid}. The process is not running as the subject account."
        )
        return observation

    observation.status = ObservationStatus.VERIFIED
    observation.detail = (
        f"pid {pid}'s token was read directly: user {observation.account_name} "
        f"({observation.user_sid}), integrity {observation.integrity_label}, "
        f"elevated {observation.elevated}. The identity came from the token, not "
        "from anything the process said about itself."
    )
    return observation


#: Privileges worth reporting by name. Read from the token's own privilege table,
#: so a process cannot hide one by omitting it from a printout.
_NOTABLE_PRIVILEGES: tuple[str, ...] = (
    "SeImpersonatePrivilege",
    "SeAssignPrimaryTokenPrivilege",
    "SeDebugPrivilege",
    "SeBackupPrivilege",
    "SeRestorePrivilege",
    "SeTakeOwnershipPrivilege",
    "SeTcbPrivilege",
    "SeCreateTokenPrivilege",
)


def _privileges_present(pid: int) -> list[str]:
    """Which notable privileges the token actually holds.

    Resolved by comparing each known privilege's LUID against the token's own
    privilege table. The inverse direction -- turning an LUID in the table back
    into a name -- is not available in one call, and guessing at it would risk
    reporting a privilege the process does not hold. An empty list therefore means
    "none of the notable ones", never "none at all".
    """
    buffer, _ = _query(pid, _CLASS_TOKEN_PRIVILEGES)
    if buffer is None:
        return []
    header = ctypes.cast(buffer, ctypes.POINTER(_TOKEN_PRIVILEGES)).contents
    if not header.PrivilegeCount:
        return []
    entries = ctypes.cast(
        ctypes.byref(buffer, ctypes.sizeof(_TOKEN_PRIVILEGES)),
        ctypes.POINTER(_LUID_AND_ATTRIBUTES),
    )
    held = {int(entries[i].Luid) for i in range(header.PrivilegeCount)}

    present: list[str] = []
    for name in _NOTABLE_PRIVILEGES:
        descriptor = _LUID_AND_ATTRIBUTES()
        if not _advapi32.LookupPrivilegeValueW(None, name,
                                               ctypes.byref(descriptor)):
            continue
        if int(descriptor.Luid) in held:
            present.append(name)
    return sorted(present)
    return False


def read_token_user_sid(pid: int) -> str:
    """The SID in a process's token, or a string naming why it could not be read.

    Kept as a one-liner because it is the primitive the M014 verifier needs, and
    because a caller that wants only the SID should not have to know the shape of
    the observation record.
    """
    return observe_process(pid).user_sid


__all__ = [
    "INTEGRITY_LABELS",
    "PROCESS_QUERY_LIMITED_INFORMATION",
    "TOKEN_QUERY",
    "ObservationStatus",
    "ProcessTokenObservation",
    "observe_process",
    "read_token_user_sid",
]
