"""M016/M017 follow-up - the corrected native probe's boundary-test interface.

This module exists to make the M015 subject-boundary test *runnable* without
weakening anything to run it. It does two things:

1. Records the human-verified identity evidence from the interactive ``runas``
   launch, so the fact survives in the repository rather than only in a chat log.
2. Builds the exact argv the probe needs, from disposable paths, and classifies
   the probe's output strictly.

The classification matters more than the launching. A probe line is only turned
into a finding when the probe also reported that it *reached* the path; a denial
for an unreachable path is discarded rather than recorded.

**No filesystem boundary test has occurred yet.** This module prepares one and
classifies results. It does not produce a subject-side ACL finding by itself, and
it contains no test that mocks the Windows security APIs while claiming real
enforcement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
STAGING = REPO / "subject_runtime"

#: The subject account and its SID, as verified interactively.
SUBJECT_ACCOUNT = "THARUNBALAJI-LA\\BABY_AI_TEST"
SUBJECT_SID = "S-1-5-21-2406520953-1060965512-844951592-1022"

#: The operator's SID, recorded so a probe run can be shown to differ. A probe that
#: printed this SID while launched via runas would mean runas had not switched
#: identity at all.
OPERATOR_SID = "S-1-5-21-2406520953-1060965512-844951592-1001"


class Outcome(str, Enum):
    """The five outcomes the probe is allowed to report.

    ``OS_DENIED`` means winerror 5 and nothing else. A missing or unreachable
    target is never a denial -- conflating the two would let a misconfigured
    harness read as a working security boundary.
    """

    OS_ALLOWED = "OS_ALLOWED"
    OS_DENIED = "OS_DENIED"
    PATH_ERROR = "PATH_ERROR"
    NOT_TESTABLE = "NOT_TESTABLE"
    ERROR = "ERROR"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


#: A mandatory label SID is S-1-16-<RID>. The header is 8 bytes:
#: Revision(1) + SubAuthorityCount(1) + IdentifierAuthority(6), then the
#: SubAuthority DWORDs. Reading the RID from offset 2 lands inside the identifier
#: authority, whose low DWORD is 0 -- so a Medium token reads as UNPROTECTED.
#: This offset is the bug the M016 probe carried and is asserted by a test.
INTEGRITY_RID_OFFSET = 8

INTEGRITY_RIDS = {
    0x0000: "UNPROTECTED",
    0x1000: "LOW",
    0x2000: "MEDIUM",
    0x3000: "HIGH",
    0x4000: "SYSTEM",
}


def integrity_label_from_sid(sid: str) -> str:
    """The integrity name for an ``S-1-16-<RID>`` SID.

    Returns ``UNKNOWN`` rather than a guess for a SID that is not a mandatory
    label, so an unrelated SID cannot be reported as an integrity level.
    """
    parts = sid.split("-")
    # S-1-16-<RID> splits to ['S', '1', '16', '<RID>']: the authority is at
    # index 2, not index 1. Index 1 is the revision ("1") and happens to be a
    # plausible-looking value, so the wrong index silently yields UNKNOWN for
    # every real integrity SID rather than raising.
    if len(parts) < 4 or parts[0] != "S" or parts[1] != "1" or parts[2] != "16":
        return "UNKNOWN"
    try:
        rid = int(parts[-1])
    except ValueError:
        return "UNKNOWN"
    return INTEGRITY_RIDS.get(rid, f"UNKNOWN({rid:X})")


@dataclass(frozen=True)
class ProbeFinding:
    """One operation's outcome, plus whether the probe reached its target."""

    operation: str
    outcome: str
    detail: str = ""

    @property
    def reached_target(self) -> bool:
        """Whether the probe actually attempted the operation.

        A finding whose target was never reached is not evidence about an ACL,
        whatever outcome it carries. ``no_staged_executable_supplied`` counts as
        not-reached: the operations behind that summary never ran, because the
        file they target does not exist.
        """
        return not self.detail.startswith((
            "no_path_supplied",
            "path_not_reached",
            "no_staged_executable_supplied",
        ))

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "outcome": self.outcome,
            "detail": self.detail,
            "reached_target": self.reached_target,
        }


_LINE = re.compile(
    r"^probe=(?P<operation>\S+)\s+result=(?P<outcome>\S+)"
    r"(?:\s+(?:reason=)?(?P<detail>.*))?$"
)
_KEY = re.compile(r"^(?P<key>[a-z_]+)=(?P<value>.*)$")


def parse_probe_output(output: str) -> dict[str, Any]:
    """Parse the probe's stdout into identity fields and classified findings.

    Parsing is strict on purpose. A line the parser does not recognise is recorded
    in ``unparsed`` rather than dropped, because a silently ignored line could be
    the one carrying the evidence.
    """
    identity: dict[str, str] = {}
    findings: list[ProbeFinding] = []
    unparsed: list[str] = []

    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _LINE.match(line)
        if match:
            findings.append(ProbeFinding(
                operation=match.group("operation"),
                outcome=match.group("outcome"),
                detail=(match.group("detail") or "").strip(),
            ))
            continue
        key = _KEY.match(line)
        if key:
            identity[key.group("key")] = key.group("value").strip()
        else:
            unparsed.append(line)

    direct = identity.get("integrity_level", "")
    independent = identity.get("integrity_level_independent", "")
    return {
        "identity": identity,
        "findings": [f.as_dict() for f in findings],
        "findings_reaching_target": [f.as_dict() for f in findings if f.reached_target],
        "integrity_paths_agree": identity.get("integrity_paths_agree") == "true",
        "integrity_level": direct,
        "integrity_level_independent": independent,
        "integrity_from_sid": integrity_label_from_sid(
            identity.get("integrity_sid", "")),
        "unparsed_lines": unparsed,
    }


def build_probe_argv(
    scratch: str | Path | None = None,
    staged: str | Path | None = None,
    protected: str | Path | None = None,
    workspace: str | Path | None = None,
    *,
    traverse: str | Path | None = None,
    enumerate_runtime: str | Path | None = None,
    enumerate_model: str | Path | None = None,
    enumerate_config: str | Path | None = None,
    read_file: str | Path | None = None,
    acl_target: str | Path | None = None,
) -> list[str]:
    """The exact argv for one probe run, using absolute paths.

    Positional slots use ``-`` for "not supplied" because Windows PowerShell
    *drops* an empty-string argument: passing ``""`` shifts every later
    positional value by one, which previously made the workspace test run against
    an option string and report a spurious format error.
    """
    def slot(value: str | Path | None) -> str:
        return "-" if value is None else str(value)

    argv = [slot(scratch), slot(staged), slot(protected), slot(workspace)]
    for name, value in (
        ("--traverse", traverse),
        ("--enumerate-runtime", enumerate_runtime),
        ("--enumerate-model", enumerate_model),
        ("--enumerate-config", enumerate_config),
        ("--read-file", read_file),
        ("--acl-target", acl_target),
    ):
        if value is not None:
            argv.append(f"{name}={value}")
    return argv


def runas_command(probe: str | Path, output: str | Path, argv: list[str]) -> str:
    """The interactive ``runas.exe`` command line for a human to run.

    Two properties are deliberate and load-bearing:

    * **No password anywhere.** ``runas`` prompts at a Windows dialog.
      ``/savecred`` is omitted on purpose: it would cache the credential.
    * **``cmd.exe /c`` wraps the probe.** ``runas`` starts the program in a new
      console window that closes when the process exits, and the probe writes to
      stdout. Without redirection its evidence would be gone before it could be
      read.

    The command is returned as text and never executed here: it requires an
    interactive credential entry.
    """
    inner = "cmd.exe /c \"\"" + str(probe) + "\""
    if argv:
        inner += " " + " ".join(f'"{a}"' if " " in a else a for a in argv)
    inner += f' > "{output}" 2>&1"'
    return f'& "$env:SystemRoot\\System32\\runas.exe" /user:{SUBJECT_ACCOUNT} "{inner}"'


#: The identity evidence a human obtained interactively, recorded so the verified
#: fact lives in the repository. ``integrity_level`` is deliberately absent: the
#: probe reported UNPROTECTED for that run, which the follow-up proved to be a
#: parsing bug rather than a property of the token.
HUMAN_VERIFIED_IDENTITY = {
    "source": "interactive runas.exe launch, human-observed output",
    "verified": True,
    "account_name": "THARUNBALAJI-LA\\BABY_AI_TEST",
    "user_sid": SUBJECT_SID,
    "identity_read_from": "live process token (OpenProcessToken)",
    "integrity_level_as_reported": "UNPROTECTED",
    "integrity_level_status": "RESOLVED_AS_PROBE_BUG",
    "integrity_note": (
        "the probe read the mandatory-label RID from SID offset 2 instead of 8, "
        "landing inside the 6-byte identifier authority whose low DWORD is 0. "
        "Corrected and re-verified against whoami /groups."
    ),
    "credentials_stored": False,
    "savecred_used": False,
}