"""Property-level security-boundary verifier. READ-ONLY. TEST-ONLY.

Why this exists
---------------
M019 established that the existing ``foundation.staging.verify_boundary`` cannot
verify the properties the laboratory actually cares about. It compares *expanded
icacls permission letters* (``R``, ``RX``, ``M``, ``F``, ...), and the rights M019
requires evidence for have **no letter at all**:

    FILE_TRAVERSE (0x20), WRITE_DAC (0x40000), WRITE_OWNER (0x80000),
    FILE_WRITE_EA (0x10), FILE_WRITE_ATTRIBUTES (0x100)

So a tree that grants the subject ``WRITE_DAC`` and ``WRITE_OWNER`` passes the old
verifier's "deny present and grants nothing" test, because those rights cannot be
*written* in the representation it compares. Worse, ``icacls`` cannot even render
``0x000d0156`` -- M016 measured that every token list expressing attribute writes
also carries ``SYNCHRONIZE``. The limitation is in the representation, not in the
verifier's logic.

A second, independent defect: a letter comparison cannot distinguish **effective
access** from **raw ACE representation**. M019 refuted G5 on exactly this point --
``SeChangeNotifyPrivilege`` lets the subject traverse a tree whose root allow mask
lacks ``FILE_TRAVERSE``. Reading the mask would have concluded the opposite of what
Windows does.

What this module does instead
-----------------------------
It reads the security descriptor directly (principal, SID, allow/deny, **numeric
access mask**, inheritance and propagation flags, explicit vs inherited, owner,
owner SID) and evaluates **security properties** against a target profile.

It is deliberately **neutral about implementation**: it does not select, recommend
or encode an ACL mask. Masks are read and reported; what is asserted is which
properties hold.

Every conclusion carries an ``evidence`` string naming the layer it came from:

    raw_ace | descriptor | effective_access | observed_behavior | NOT_VERIFIABLE

so a conclusion drawn from a descriptor is never mistaken for a measurement of what
Windows actually did.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "FILE_READ_DATA", "FILE_WRITE_DATA", "FILE_APPEND_DATA", "FILE_READ_EA",
    "FILE_WRITE_EA", "FILE_TRAVERSE", "FILE_EXECUTE", "FILE_DELETE_CHILD",
    "FILE_READ_ATTRIBUTES", "FILE_WRITE_ATTRIBUTES", "READ_CONTROL", "DELETE",
    "SYNCHRONIZE", "WRITE_DAC", "WRITE_OWNER", "GENERIC_ALL", "GENERIC_READ",
    "GENERIC_WRITE", "GENERIC_EXECUTE", "MASK32",
    "BIT_NAMES", "expand_generic", "rights_from_tokens",
    "AceRecord", "DescriptorRecord", "PropertyCheck", "VerificationReport",
    "read_descriptor", "effective_access", "verify_properties", "verify_topology",
    "TargetObject", "TopologyReport", "M019_TARGET_PATHS", "ADMIN_RIGHTS",
    "FIXTURE_ARTIFACT_MARKERS",
    "current_token", "TokenObservation",
    "SE_CHANGE_NOTIFY", "SUBJECT_SID", "OPERATOR_SID", "ADMIN_SID", "SYSTEM_SID",
    "AU_SID", "USERS_SID", "EVERYONE_SID",
]

#: An NT access mask is 32 bits and **unsigned**. .NET returns
#: ``System.Security.AccessControl.FileSystemRights`` as a signed ``Int64``, so a
#: descriptor carrying GENERIC_READ comes back as a negative number
#: (``-0x1fff0000``). Taken raw, that mask compares as if every bit above 0x20 were
#: set and ``0x80000000`` as if it were absent -- so the reader would report a
#: GENERIC_READ grant as neither generic nor read. Found by the real-filesystem
#: layer against the live ``subject_runtime`` descriptor; every mask is normalised
#: through this constant and a test asserts the round trip.
MASK32 = 0xFFFFFFFF

# --- Windows filesystem rights (numeric; no letters) -----------------------

FILE_READ_DATA = 0x0001        # FILE_LIST_DIRECTORY on a directory
FILE_WRITE_DATA = 0x0002       # FILE_ADD_FILE on a directory
FILE_APPEND_DATA = 0x0004      # FILE_ADD_SUBDIRECTORY on a directory
FILE_READ_EA = 0x0008
FILE_WRITE_EA = 0x0010
FILE_TRAVERSE = 0x0020         # FILE_TRAVERSE on a directory
#: The same bit, a different right, on a file. Windows reuses 0x20 rather than
#: spending a second bit, and the two are **not** interchangeable: SeChangeNotify
#: bypasses the traverse check and not the execute check. Collapsing them is the
#: same category of defect as probe v1's ``traverse_directory`` -- an operation
#: name that merges two capabilities -- reproduced in the mask instead of the
#: probe, so the distinction is made by object kind rather than by bit.
FILE_EXECUTE = 0x0020           # FILE_EXECUTE on a file
FILE_DELETE_CHILD = 0x0040
FILE_READ_ATTRIBUTES = 0x0080
FILE_WRITE_ATTRIBUTES = 0x0100
READ_CONTROL = 0x00020000
DELETE = 0x00010000
WRITE_DAC = 0x00040000
WRITE_OWNER = 0x00080000
SYNCHRONIZE = 0x00100000
GENERIC_READ = 0x80000000
GENERIC_EXECUTE = 0x20000000
GENERIC_WRITE = 0x40000000
GENERIC_ALL = 0x10000000

BIT_NAMES: dict[int, str] = {
    FILE_READ_DATA: "FILE_READ_DATA", FILE_WRITE_DATA: "FILE_WRITE_DATA",
    FILE_APPEND_DATA: "FILE_APPEND_DATA", FILE_READ_EA: "FILE_READ_EA",
    FILE_TRAVERSE: "FILE_TRAVERSE", FILE_DELETE_CHILD: "FILE_DELETE_CHILD",
    FILE_READ_ATTRIBUTES: "FILE_READ_ATTRIBUTES",
    FILE_WRITE_ATTRIBUTES: "FILE_WRITE_ATTRIBUTES",
    FILE_WRITE_EA: "FILE_WRITE_EA",
    READ_CONTROL: "READ_CONTROL", DELETE: "DELETE", WRITE_DAC: "WRITE_DAC",
    WRITE_OWNER: "WRITE_OWNER", SYNCHRONIZE: "SYNCHRONIZE",
}

#: Privileges that change what a mask means. Present in an ordinary user token.
SE_CHANGE_NOTIFY = "SeChangeNotifyPrivilege"

SUBJECT_SID = "S-1-5-21-2406520953-1060965512-844951592-1022"
OPERATOR_SID = "S-1-5-21-2406520953-1060965512-844951592-1001"
SYSTEM_SID = "S-1-5-18"
ADMIN_SID = "S-1-5-32-544"
AU_SID = "S-1-5-11"
USERS_SID = "S-1-5-32-545"
EVERYONE_SID = "S-1-1-0"

#: What "administrative access" means here, as a property and not as a label.
#: M019 T-ADM-1 requires an administrator to be able to change content, remove
#: objects, rewrite the descriptor and take ownership. ``icacls (F)`` is not the
#: test; these four rights are, because a mask can carry them or omit them.
ADMIN_RIGHTS = FILE_WRITE_DATA | DELETE | WRITE_DAC | WRITE_OWNER

_GENERIC_MAP = {
    GENERIC_READ: FILE_READ_DATA | FILE_READ_EA | FILE_READ_ATTRIBUTES | READ_CONTROL,
    GENERIC_WRITE: FILE_WRITE_DATA | FILE_APPEND_DATA | FILE_WRITE_EA
    | FILE_READ_ATTRIBUTES | FILE_WRITE_ATTRIBUTES | READ_CONTROL | SYNCHRONIZE,
    GENERIC_EXECUTE: FILE_READ_ATTRIBUTES | FILE_TRAVERSE | READ_CONTROL | SYNCHRONIZE,
    GENERIC_ALL: (FILE_READ_DATA | FILE_WRITE_DATA | FILE_APPEND_DATA | FILE_READ_EA
                  | FILE_TRAVERSE | FILE_DELETE_CHILD | FILE_READ_ATTRIBUTES
                  | FILE_WRITE_ATTRIBUTES | DELETE | READ_CONTROL | WRITE_DAC
                  | WRITE_OWNER | SYNCHRONIZE),
}


def expand_generic(mask: int) -> int:
    """Fold GENERIC_* bits into their file-specific equivalents.

    Required because Windows stores ``GENERIC_ALL`` for a FullControl ACE while
    the M019 properties are expressed as individual bits. Comparing a GENERIC_ALL
    ACE against ``WRITE_DAC`` without this fold would report a false violation on
    every full-control grant.

    The mask is normalised to 32 unsigned bits first, so a descriptor that arrived
    from .NET as a negative ``Int64`` folds the same way as the same mask arriving
    as a positive one.
    """
    mask &= MASK32
    out = mask & ~sum(_GENERIC_MAP) & MASK32
    for generic, concrete in _GENERIC_MAP.items():
        if mask & generic:
            out |= concrete
    return out & MASK32


#: icacls letter -> the rights it carries, reconstructed from M016's **measured**
#: rows rather than invented.
#:
#: M016 measured ``W,D,DC -> 0x00110156`` and separately ``S -> 0x00100000``
#: (exact). The SYNCHRONIZE bit is present in the former and absent from the latter,
#: which measures exactly the bundling defect this module exists to demonstrate:
#:
#:     W, D, DC  ->  DELETE | WRITE_ATTRIBUTES | WRITE_EA | DELETE_CHILD
#:                | APPEND_DATA | WRITE_DATA | SYNCHRONIZE
#:     S         ->  SYNCHRONIZE            (so W/D/DC must be carrying it)
#:
#: The per-letter split *within* that bundle was not measured independently, so it is
#: assigned by the documented icacls semantics and asserted only at the level M016
#: measured: the union must reproduce 0x00110156 exactly, and no subset of these
#: letters may reach WRITE_DAC or WRITE_OWNER.
_ICACLS_LETTER_RIGHTS: dict[str, int] = {
    "R": FILE_READ_DATA | FILE_READ_EA | FILE_READ_ATTRIBUTES | READ_CONTROL,
    "X": FILE_TRAVERSE,
    "W": FILE_WRITE_DATA | FILE_APPEND_DATA | FILE_WRITE_ATTRIBUTES | SYNCHRONIZE,
    "D": DELETE | FILE_WRITE_EA,
    "DC": FILE_DELETE_CHILD,
    # icacls prints a directory's inheritable ACEs with the ``IO`` (inherit-only)
    # flag, so a token measured on a directory lands in the mask. M016's
    # 0x00110156 row was measured that way and carries this bit; M015's deny
    # ``W,D,DC`` includes ``DC`` precisely to cover DELETE_CHILD.
    "IO": FILE_DELETE_CHILD,
    "S": SYNCHRONIZE,
    "F": expand_generic(GENERIC_ALL),
    "M": expand_generic(GENERIC_ALL),
}

#: Propagation flags. Not permissions: ``staging._expand`` skips them for exactly
#: this reason, and a traversal flag treated as a right would make every inheritable
#: ACE look broader than it is.
_ICACLS_FLAGS = frozenset({"OI", "CI", "IO", "I", "N", "DENY"})

#: The measured fact this module exists to demonstrate. A deny backstop expressed
#: in icacls letters carries SYNCHRONIZE and **never** WRITE_DAC or WRITE_OWNER,
#: because no letter selects either. Verified as a test rather than asserted in a
#: comment, so a change to the table cannot quietly invalidate it.
ICACLS_DENY_CANNOT_EXPRESS = (WRITE_DAC, WRITE_OWNER)


def rights_from_tokens(tokens: Iterable[str]) -> int:
    """Map icacls permission *letters* to numeric rights.

    Present only so this module can state, as a testable fact, that the letter
    vocabulary **cannot express** several M019 rights. It is used by the
    negative-control tests to demonstrate the old verifier's blindness, and is
    never used to evaluate a property.

    Letters are **bundles**: ``W`` carries WRITE_ATTRIBUTES and SYNCHRONIZE, and
    ``D`` carries WRITE_EA -- which is precisely why a bundle cannot select a single
    right. ``WD``, ``AD``, ``GW`` and ``GA`` are absent on purpose: they are
    multi-letter compounds whose contents M016 did not measure separately, and
    guessing would blur the very distinction these tests depend on.

    Accepts the token forms icacls actually prints -- individual letters,
    comma-joined bundles (``W,D,DC``), and a whole flag string
    (``(OI)(CI)(DENY)(W,D,DC)``). Propagation flags are skipped, matching
    ``staging._expand``: they describe propagation, not permission.
    """
    out = 0
    for token in tokens:
        for part in re.split(r"[(),\s]+", str(token).upper()):
            if not part or part in _ICACLS_FLAGS:
                continue
            out |= _ICACLS_LETTER_RIGHTS.get(part, 0)
    return out


# --- descriptor model -------------------------------------------------------

@dataclass(frozen=True)
class AceRecord:
    """One access-control entry, read from the descriptor. Never letter-reduced."""
    principal: str
    sid: str
    is_allow: bool
    mask: int
    inheritance_flags: str = "None"
    propagation_flags: str = "None"
    is_inherited: bool = False

    def __post_init__(self) -> None:
        # Frozen dataclass, so normalise through object.__setattr__. A mask that
        # arrived negative (see MASK32) would otherwise render as "0x-1fff0000" and
        # compare as the wrong number everywhere downstream.
        normalised = int(self.mask) & MASK32
        if normalised != self.mask:
            object.__setattr__(self, "mask", normalised)

    @property
    def kind(self) -> str:
        return "Allow" if self.is_allow else "Deny"

    @property
    def effective_mask(self) -> int:
        return expand_generic(self.mask)

    def has(self, right: int) -> bool:
        return bool(self.effective_mask & right)

    def as_dict(self) -> dict[str, Any]:
        return {"principal": self.principal, "sid": self.sid, "type": self.kind,
                "mask": f"0x{self.mask:08x}", "inheritance": self.inheritance_flags,
                "propagation": self.propagation_flags, "inherited": self.is_inherited}


@dataclass(frozen=True)
class DescriptorRecord:
    """A path's security state, as read. Contains no conclusions."""
    path: str
    path_type: str
    exists: bool
    owner: str
    owner_sid: str
    access_sddl: str
    access_rules_protected: bool
    aces: tuple[AceRecord, ...] = ()

    @property
    def object_kind(self) -> str:
        """``"dir"``, ``"file"`` or ``"unknown"``.

        Load-bearing, not cosmetic. Windows gives 0x20 two meanings depending on
        the object: traverse on a directory, execute on a file. A verifier that
        ignores the kind either demands a traverse bit where execute is meant, or
        accepts an execute grant on data, and in both cases it reaches a
        conclusion about a capability the object does not have.
        """
        return {"dir": "dir", "directory": "dir", "file": "file"}.get(
            str(self.path_type).lower(), "unknown")

    def aces_for(self, *sids: str) -> list[AceRecord]:
        wanted = set(sids)
        return [a for a in self.aces if a.sid in wanted]

    def explicit_aces(self) -> list[AceRecord]:
        return [a for a in self.aces if not a.is_inherited]

    def inherited_aces(self) -> list[AceRecord]:
        return [a for a in self.aces if a.is_inherited]

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "path_type": self.path_type,
                "object_kind": self.object_kind, "exists": self.exists,
                "owner": self.owner, "owner_sid": self.owner_sid,
                "access_rules_protected": self.access_rules_protected,
                "access_sddl": self.access_sddl,
                "aces": [a.as_dict() for a in self.aces]}


# --- reading ----------------------------------------------------------------

_PS = r"""
$ErrorActionPreference = 'Stop'
$acl = Get-Acl -LiteralPath {lit}
$aces = @($acl.Access | ForEach-Object {{
  $sid = ''
  try {{ $sid = $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value }} catch {{ $sid = 'UNRESOLVED' }}
  [pscustomobject]@{{
    principal = [string]$_.IdentityReference
    sid = $sid
    allow   = ([string]$_.AccessControlType -eq 'Allow')
    mask    = [int64]$_.FileSystemRights
    inherit = [string]$_.InheritanceFlags
    prop    = [string]$_.PropagationFlags
    inherited = [bool]$_.IsInherited
  }}
}})
$ownerSid = ''
try {{ $ownerSid = (New-Object System.Security.Principal.NTAccount($acl.Owner)).Translate([System.Security.Principal.SecurityIdentifier]).Value }} catch {{ $ownerSid = 'UNRESOLVED' }}
[pscustomobject]@{{
  path = {lit}
  exists = [bool](Test-Path -LiteralPath {lit})
  is_dir = [bool](Test-Path -LiteralPath {lit} -PathType Container)
  owner = [string]$acl.Owner
  owner_sid = $ownerSid
  protected = [bool]$acl.AreAccessRulesProtected
  sddl = $acl.GetSecurityDescriptorSddlForm([System.Security.AccessControl.AccessControlSections]::Access)
  aces = $aces
}} | ConvertTo-Json -Depth 5 -Compress
"""


def _powershell(script: str) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=180, shell=False,
        stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    return result.stdout or ""


def _ps_literal(value: str) -> str:
    """A PowerShell single-quoted string literal.

    ``subprocess.list2cmdline`` is wrong here: it only quotes arguments that
    contain spaces, so ``C:\\dev\\...`` arrives unquoted and PowerShell parses it
    as a *command name* -- "not recognized as the name of a cmdlet". PowerShell
    string literals are single-quoted with an embedded quote doubled.
    """
    return "'" + str(value).replace("'", "''") + "'"


def read_descriptor(path: str | Path) -> DescriptorRecord:
    """Read one path's security descriptor. READ-ONLY; launches nothing mutating."""
    target = str(path)
    literal = _ps_literal(target)
    raw = _powershell(_PS.format(lit=literal)).strip()
    if not raw:
        return DescriptorRecord(target, "unknown", False, "UNREADABLE", "UNREADABLE",
                               "", False, ())
    data = json.loads(raw)
    aces = tuple(AceRecord(
        principal=a.get("principal", ""), sid=a.get("sid", "UNRESOLVED"),
        is_allow=bool(a.get("allow")), mask=int(a.get("mask", 0)),
        inheritance_flags=str(a.get("inherit", "None")),
        propagation_flags=str(a.get("prop", "None")),
        is_inherited=bool(a.get("inherited")),
    ) for a in data.get("aces") or ())
    return DescriptorRecord(
        path=target, path_type="dir" if data.get("is_dir") else "file",
        exists=bool(data.get("exists")), owner=str(data.get("owner", "")),
        owner_sid=str(data.get("owner_sid", "")),
        access_sddl=str(data.get("sddl", "")),
        access_rules_protected=bool(data.get("protected")), aces=aces)


# --- effective access -------------------------------------------------------

@dataclass(frozen=True)
class EffectiveAccess:
    """What Windows would permit a token, as far as a DACL reading can say.

    ``privilege_bypasses`` names the privileges that change the answer. This is the
    mechanism behind M019's T-TRAV-3: ``SeChangeNotifyPrivilege`` bypasses
    ``FILE_TRAVERSE`` checking, so absence of the bit is not absence of traversal.
    """
    granted: int
    denied: int
    privilege_bypasses: tuple[str, ...] = ()

    @property
    def effective(self) -> int:
        return self.granted & ~self.denied

    def permits(self, right: int) -> bool:
        return bool(self.effective & right)

    def denies(self, right: int) -> bool:
        return bool(self.denied & right)

    def can_traverse(self) -> bool:
        """Traversal as Windows decides it, not as the mask implies.

        Directory-only. On a file the same bit is execute and no privilege
        bypasses it, which is why :meth:`can_execute` exists separately rather
        than as a flag on this one.
        """
        if self.permits(FILE_TRAVERSE):
            return True
        return SE_CHANGE_NOTIFY in self.privilege_bypasses

    def can_execute(self) -> bool:
        """Execute as Windows decides it: the ACE, and only the ACE.

        ``SeChangeNotifyPrivilege`` bypasses traverse *checking*, so it buys
        descent. It does not bypass execute checking -- that needs SeTcbPrivilege
        (or ownership, which is a different right). Treating the two as one is
        how a model file ends up quietly executable.
        """
        return self.permits(FILE_EXECUTE)

    def traversal_bypass_privilege(self) -> str | None:
        """The privilege carrying traversal when the ACE does not, else ``None``."""
        if self.permits(FILE_TRAVERSE):
            return None
        return SE_CHANGE_NOTIFY if SE_CHANGE_NOTIFY in self.privilege_bypasses else None

    def as_dict(self) -> dict[str, Any]:
        return {"granted": f"0x{self.granted:08x}", "denied": f"0x{self.denied:08x}",
                "effective": f"0x{self.effective:08x}",
                "privilege_bypasses": list(self.privilege_bypasses),
                "traversal_permitted": self.can_traverse(),
                "traversal_bypass_privilege": self.traversal_bypass_privilege(),
                "execute_permitted": self.can_execute()}


def effective_access(descriptor: DescriptorRecord, token_sids: Iterable[str],
                     privileges: Iterable[str] = ()) -> EffectiveAccess:
    """Apply the Windows DACL model to a token's SIDs.

    Deny ACEs override allow ACEs. Explicit ACEs are applied before inherited ones,
    matching the canonical order. Generic bits are folded first.

    A property that depends on kernel behaviour this cannot model is returned as a
    denial only where the DACL actually denies it; anything else is reported as
    granted with the bypassing privilege named. Nothing is silently assumed.
    """
    sids = set(token_sids)
    granted = 0
    denied = 0
    for ace in descriptor.aces:
        if ace.sid not in sids:
            continue
        mask = ace.effective_mask
        if ace.is_allow:
            granted |= mask
        else:
            denied |= mask
    return EffectiveAccess(granted=granted & MASK32, denied=denied & MASK32,
                           privilege_bypasses=tuple(privileges))


# --- property evaluation ----------------------------------------------------

@dataclass
class PropertyCheck:
    """One property, its verdict, and the evidence layer the verdict came from."""
    name: str
    verdict: str                    # PASS | FAIL | NOT_VERIFIABLE | NOT_APPLICABLE
    detail: str
    evidence: str                   # raw_ace | descriptor | effective_access | ...
    observed: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.verdict == "PASS"

    def as_dict(self) -> dict[str, Any]:
        return {"property": self.name, "verdict": self.verdict, "detail": self.detail,
                "evidence": self.evidence, "observed": self.observed}


@dataclass
class VerificationReport:
    label: str
    checks: list[PropertyCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Strict: every property M019 asks about was **established**.

        A ``NOT_VERIFIABLE`` in the set makes this ``False``, deliberately. A
        report that said "passed" while one property was unread or unmeasured
        would be the same failure as M015's ``owner_ok`` treating an unread owner
        as "not the subject": unestablished reads as established. Use
        :attr:`failed` when the question is only "is anything violated".
        """
        return all(c.verdict in ("PASS", "NOT_APPLICABLE") for c in self.checks)

    @property
    def failed(self) -> bool:
        """Whether any property is violated. Ignores what could not be established."""
        return any(c.verdict == "FAIL" for c in self.checks)

    @property
    def failures(self) -> list[PropertyCheck]:
        return [c for c in self.checks if c.verdict == "FAIL"]

    @property
    def not_verifiable(self) -> list[PropertyCheck]:
        return [c for c in self.checks if c.verdict == "NOT_VERIFIABLE"]

    def verdict(self, name: str) -> str | None:
        """The verdict for one property, or ``None`` if it was never evaluated."""
        for check in self.checks:
            if check.name == name:
                return check.verdict
        return None

    def check(self, name: str) -> PropertyCheck | None:
        for check in self.checks:
            if check.name == name:
                return check
        return None

    def add(self, name: str, verdict: str, detail: str, evidence: str,
            **observed: Any) -> PropertyCheck:
        check = PropertyCheck(name, verdict, detail, evidence, observed)
        self.checks.append(check)
        return check

    def as_dict(self) -> dict[str, Any]:
        return {"label": self.label,
                "passed": self.passed,
                "failed": self.failed,
                "verdict_counts": _counts(self.checks),
                "failures": [c.name for c in self.failures],
                "not_verifiable": [c.name for c in self.not_verifiable],
                "authoritative_security_verdict": False,
                "authority_note": (
                    "descriptor and DACL-model results only. This report is not a "
                    "measurement of Windows refusing the subject, and it is not an "
                    "approval of a boundary design."),
                "checks": [c.as_dict() for c in self.checks]}


def _counts(checks: list[PropertyCheck]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in checks:
        out[c.verdict] = out.get(c.verdict, 0) + 1
    return out


def _sid_granted(aces: Iterable[AceRecord]) -> int:
    """Rights effectively granted to one SID by its own ACEs; denies win.

    Deny-last on purpose: Windows evaluates all deny ACEs before any allow ACE, so
    an allow cannot re-grant a right a deny for the same principal removed.
    """
    granted = 0
    denied = 0
    for ace in aces:
        if ace.is_allow:
            granted |= ace.effective_mask
        else:
            denied |= ace.effective_mask
    return (granted & ~denied) & MASK32


def verify_properties(
    descriptor: DescriptorRecord,
    *,
    label: str = "",
    subject_sid: str = SUBJECT_SID,
    operator_sid: str = OPERATOR_SID,
    require_traverse: bool = True,
    require_execute: bool = False,
    subject_privileges: Iterable[str] = (),
    expected_owner_sid: str = OPERATOR_SID,
    observed_subject_operations: dict[str, str] | None = None,
) -> VerificationReport:
    """Evaluate the M019 property set against one descriptor.

    The property set is fixed by M019 and is not configurable away here: this is
    the contract the verifier exists to check. No ACL mask is named or preferred.

    ``require_execute`` is M019's one per-object variation in T-BABY-5: the
    runtime's loadable file must be executable by the subject, while model and
    config data must not be. It is a **file** property -- on a directory the check
    reports ``NOT_APPLICABLE`` and says why, because 0x20 there means traverse.

    ``observed_subject_operations`` maps an operation name to the result Windows
    gave when the subject actually attempted it. Without it the report says so
    explicitly: everything above is descriptor and model, and calling that
    enforcement is the mistake M019 recorded in C7.
    """
    report = VerificationReport(label or descriptor.path)

    if not descriptor.exists:
        report.add("target_exists", "FAIL", "target path does not exist",
                   "descriptor", path=descriptor.path)
        return report
    report.add("target_exists", "PASS", "target path exists", "descriptor")
    kind = descriptor.object_kind

    # --- ownership (descriptor layer; never inferred from group membership) ---
    if descriptor.owner_sid in ("", "UNRESOLVED"):
        report.add("owner_known", "NOT_VERIFIABLE",
                   "owner could not be read; an unread owner is unverified, never "
                   "'not the subject'", "descriptor", owner=descriptor.owner)
    else:
        report.add("owner_known", "PASS", "owner resolved", "descriptor",
                   owner=descriptor.owner, owner_sid=descriptor.owner_sid)

    if descriptor.owner_sid == subject_sid:
        report.add("subject_is_not_owner", "FAIL",
                   "the subject owns the path and may rewrite the DACL regardless "
                   "of what the DACL grants", "descriptor",
                   owner=descriptor.owner, owner_sid=descriptor.owner_sid)
    else:
        report.add("subject_is_not_owner", "PASS",
                   "subject does not own the path", "descriptor",
                   owner_sid=descriptor.owner_sid)

    if expected_owner_sid and descriptor.owner_sid not in ("", "UNRESOLVED"):
        ok = descriptor.owner_sid == expected_owner_sid
        report.add("owner_is_expected_administrator", "PASS" if ok else "FAIL",
                   "owner matches the expected administrative identity" if ok
                   else "owner is not the expected administrative identity",
                   "descriptor", owner_sid=descriptor.owner_sid,
                   expected=expected_owner_sid)

    # --- inherited Modify must be absent (M019 T-WR-11) ---
    for ace in descriptor.aces:
        if ace.sid in (AU_SID, USERS_SID) and ace.is_allow:
            mutating = ace.effective_mask & (FILE_WRITE_DATA | FILE_APPEND_DATA
                                             | DELETE | FILE_DELETE_CHILD
                                             | WRITE_DAC | WRITE_OWNER)
            if mutating:
                report.add("no_inherited_modify", "FAIL",
                           f"{ace.principal} holds a write-capable Allow ACE",
                           "raw_ace", principal=ace.principal, sid=ace.sid,
                           mask=ace.as_dict()["mask"], inherited=ace.is_inherited)
                break
    else:
        report.add("no_inherited_modify", "PASS",
                   "no Authenticated Users or Users ACE grants write",
                   "raw_ace")

    # --- subject effective access (effective_access layer) ---
    access = effective_access(descriptor, [subject_sid], subject_privileges)

    must_deny = {
        "write": FILE_WRITE_DATA, "append": FILE_APPEND_DATA, "delete": DELETE,
        "delete_child": FILE_DELETE_CHILD,
        "write_dac": WRITE_DAC, "write_owner": WRITE_OWNER,
        "write_ea": FILE_WRITE_EA, "write_attributes": FILE_WRITE_ATTRIBUTES,
    }
    for name, right in must_deny.items():
        if access.denies(right):
            report.add(f"subject_denied_{name}", "PASS",
                       f"DACL denies {BIT_NAMES[right]} (0x{right:08x})",
                       "effective_access", right=BIT_NAMES[right])
        elif access.permits(right):
            report.add(f"subject_denied_{name}", "FAIL",
                       f"subject is granted {BIT_NAMES[right]} (0x{right:08x})",
                       "effective_access", right=BIT_NAMES[right])
        else:
            report.add(f"subject_denied_{name}", "PASS",
                       f"neither allowed nor denied by the DACL; no grant exists",
                       "effective_access", right=BIT_NAMES[right])

    must_allow = {
        "read": FILE_READ_DATA, "read_ea": FILE_READ_EA,
        "read_attributes": FILE_READ_ATTRIBUTES, "read_control": READ_CONTROL,
    }
    for name, right in must_allow.items():
        report.add(f"subject_allowed_{name}",
                   "PASS" if access.permits(right) else "FAIL",
                   f"subject {'may' if access.permits(right) else 'may not'} "
                   f"{BIT_NAMES[right]}", "effective_access",
                   right=BIT_NAMES[right])

    # --- execute (M019 T-BABY-5): a FILE capability, never a directory one ----
    #
    # 0x20 is FILE_EXECUTE on a file and FILE_TRAVERSE on a directory, and only
    # the second is bypassed by SeChangeNotifyPrivilege. Asking "may the subject
    # execute?" of a directory -- or answering it from the traverse bit -- is the
    # probe v1 conflation reproduced in the mask rather than the probe, so the
    # object kind decides which question is even asked.
    if kind == "file":
        allowed = access.can_execute()
        report.add("subject_execute", "PASS" if allowed is require_execute else "FAIL",
                   f"the subject {'may' if allowed else 'may not'} execute; M019 "
                   f"T-BABY-5 {'requires' if require_execute else 'withholds'} "
                   "execute on this object",
                   "effective_access", right="FILE_EXECUTE",
                   required=require_execute, granted=allowed,
                   note="execute is never granted by a bypass privilege; only "
                        "SeTcbPrivilege or ownership supplies it")
    elif kind == "dir":
        report.add("subject_execute", "NOT_APPLICABLE",
                   "execute is a file capability; on a directory 0x20 is "
                   "FILE_TRAVERSE and is evaluated as subject_traversal",
                   "effective_access", right="FILE_EXECUTE", object_kind=kind)
    else:
        report.add("subject_execute", "NOT_VERIFIABLE",
                   "object kind unknown, so 0x20 cannot be read as traverse or as "
                   "execute; answering either way would be a guess",
                   "effective_access", right="FILE_EXECUTE", object_kind=kind)

    # --- traversal (M019 T-TRAV): a DIRECTORY capability, never a file one -----
    if kind == "file":
        report.add("subject_traversal", "NOT_APPLICABLE",
                   "traversal is a directory capability; reaching this file is "
                   "traversing its parent, which is evaluated on the parent",
                   "effective_access", object_kind=kind)
        report.add("traversal_is_not_ace_load_bearing", "NOT_APPLICABLE",
                   "no directory is in scope for a file object",
                   "effective_access", object_kind=kind)
    elif kind != "dir":
        report.add("subject_traversal", "NOT_VERIFIABLE",
                   "object kind unknown; traversal cannot be decided for an object "
                   "that may not be a directory", "effective_access",
                   object_kind=kind)
        report.add("traversal_is_not_ace_load_bearing", "NOT_VERIFIABLE",
                   "object kind unknown", "effective_access", object_kind=kind)
    elif not require_traverse:
        report.add("subject_traversal", "NOT_APPLICABLE", "traversal not required",
                   "effective_access", object_kind=kind)
        report.add("traversal_is_not_ace_load_bearing", "NOT_APPLICABLE",
                   "traversal is not in scope for this object", "effective_access")
    else:
        can = access.can_traverse()
        bypass = SE_CHANGE_NOTIFY in access.privilege_bypasses
        report.add(
            "subject_traversal", "PASS" if can else "FAIL",
            "traversal permitted by the DACL" if access.permits(FILE_TRAVERSE)
            else ("traversal permitted via SeChangeNotifyPrivilege, which bypasses "
                  "FILE_TRAVERSE checking" if can
                  else "no traversal path: neither the ACE nor a bypass privilege"),
            "effective_access",
            ace_file_traverse=bool(access.granted & FILE_TRAVERSE),
            se_change_notify=bypass, traversal_permitted=can,
            bypass_privilege=access.traversal_bypass_privilege())
        # The M019 guard against reintroducing G5.
        if bypass:
            report.add("traversal_is_not_ace_load_bearing", "PASS",
                       "SeChangeNotifyPrivilege bypasses FILE_TRAVERSE, so no "
                       "security property may depend on withholding that bit",
                       "effective_access", privilege=SE_CHANGE_NOTIFY)
        else:
            report.add("traversal_is_not_ace_load_bearing", "NOT_VERIFIABLE",
                       "privilege set not supplied; cannot establish whether "
                       "traversal depends on the ACE or on a bypass privilege",
                       "effective_access")

    # --- administrative access (raw_ace layer; group membership is NOT assumed) ---
    needed = ADMIN_RIGHTS
    for name, sid in (("operator", operator_sid), ("system", SYSTEM_SID),
                      ("administrators", ADMIN_SID)):
        granted = _sid_granted(descriptor.aces_for(sid))
        ok = granted & needed == needed
        report.add(f"{name}_administrative_access", "PASS" if ok else "FAIL",
                   f"{name} retains administrative rights" if ok
                   else f"{name} is missing administrative rights "
                        f"(0x{granted:08x}, needs 0x{needed:08x})",
                   "raw_ace", granted=f"0x{granted:08x}",
                   aces=[a.as_dict() for a in descriptor.aces_for(sid)])

    # --- M019 T-ADM-4: the operator's access must not be group-derived alone ---
    #
    # In this session's context BUILTIN\Administrators is deny-only, so any
    # administrative capability the operator holds has to come from an ACE naming
    # the operator directly. This is the check that catches the failure M019
    # recorded: a principal-wide removal of an administrator can strip exactly that
    # ACE while leaving the group membership -- and the illusion of administrative
    # access -- in place. It is also why "Administrators retains control" is not
    # accepted as a substitute for it.
    operator_aces = descriptor.aces_for(operator_sid)
    operator_granted = _sid_granted(operator_aces)
    if not operator_aces:
        report.add("operator_access_not_group_derived", "FAIL",
                   "the operator holds no ACE on this object at all; in an "
                   "unelevated token (Administrators deny-only) that means no "
                   "administrative access, whatever the group membership says",
                   "raw_ace", operator_sid=operator_sid, aces=[])
    elif operator_granted & needed == needed:
        report.add("operator_access_not_group_derived", "PASS",
                   "the operator SID itself carries administrative rights, so "
                   "Administrators membership is not the only source",
                   "raw_ace", granted=f"0x{operator_granted:08x}",
                   aces=[a.as_dict() for a in operator_aces])
    else:
        report.add("operator_access_not_group_derived", "FAIL",
                   f"the operator's own ACEs carry 0x{operator_granted:08x}, short of "
                   f"the 0x{needed:08x} M019 T-ADM-1 requires; with Administrators "
                   "deny-only the operator's administrative access is not "
                   "established",
                   "raw_ace", granted=f"0x{operator_granted:08x}",
                   aces=[a.as_dict() for a in operator_aces])

    # --- same-SID multiplicity (M016: one ACE per principal is NOT assumed) ---
    counts: dict[tuple[str, str], int] = {}
    for ace in descriptor.aces:
        counts[(ace.sid, ace.kind)] = counts.get((ace.sid, ace.kind), 0) + 1
    multi = {f"{sid}:{kind}": n for (sid, kind), n in counts.items() if n > 1}
    report.add("same_sid_multiplicity", "PASS",
               "no principal holds multiple ACEs of one type" if not multi
               else "multiple ACEs for the same principal and type are present and "
                    "were evaluated individually, not collapsed",
               "raw_ace", multi=sorted(multi))

    # --- the honesty anchor: was any of this observed, or only modelled? ------
    #
    # Everything above is read from a descriptor and evaluated through the DACL
    # model. None of it is a measurement of what Windows did when the subject
    # tried. M019 C7 already recorded that an operator-side read reported ALLOWED
    # on a path the subject cannot write, so a report that omitted this line would
    # let "the descriptor permits it" be read as "the subject can do it".
    if observed_subject_operations is None:
        report.add("subject_os_enforcement_measured", "NOT_VERIFIABLE",
                   "no subject-run observations supplied; every result above is a "
                   "descriptor reading or a DACL-model conclusion, not a measurement "
                   "of Windows refusing the subject",
                   "observed_behavior", attempts=0)
    else:
        report.add("subject_os_enforcement_measured", "PASS",
                   f"{len(observed_subject_operations)} subject-run observations "
                   "supplied and folded into this report",
                   "observed_behavior",
                   attempts=len(observed_subject_operations),
                   results=dict(observed_subject_operations))

    return report


# ---------------------------------------------------------------------------
# Topology: M019's target path set, evaluated object by object
# ---------------------------------------------------------------------------

#: The four paths M019 T-PATH-1 defines, and nothing else. Named here so the set is
#: one literal that a test can pin, rather than an enumeration that quietly widens.
M019_TARGET_PATHS = ("subject_runtime", "runtime", "model", "config")

#: M016's fixture artifacts. T-PATH-2 forbids them inside the target set, and the
#: production tree currently holds three -- recorded, not removed.
FIXTURE_ARTIFACT_MARKERS = ("m016_",)


@dataclass(frozen=True)
class TargetObject:
    """One object in the target set, with the per-object M019 variation applied."""

    relative_path: str
    #: ``True`` the subject must be able to execute it (M019 T-BABY-5 runtime),
    #: ``False`` it must not be (model, config), ``None`` do not assert either --
    #: which is the correct answer for a directory, where the capability does not
    #: exist.
    require_execute: bool | None = None
    must_exist: bool = True

    @property
    def label(self) -> str:
        return self.relative_path.replace("/", ".").replace("\\", ".")


@dataclass
class TopologyReport:
    """Per-object reports plus the set-level findings."""

    root: str
    reports: list[VerificationReport] = field(default_factory=list)
    set_checks: list[PropertyCheck] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)

    @property
    def checks(self) -> list[PropertyCheck]:
        return [*self.set_checks, *[c for r in self.reports for c in r.checks]]

    @property
    def passed(self) -> bool:
        return all(c.verdict in ("PASS", "NOT_APPLICABLE") for c in self.checks)

    @property
    def failed(self) -> bool:
        return any(c.verdict == "FAIL" for c in self.checks)

    @property
    def failures(self) -> list[PropertyCheck]:
        return [c for c in self.checks if c.verdict == "FAIL"]

    @property
    def not_verifiable(self) -> list[PropertyCheck]:
        return [c for c in self.checks if c.verdict == "NOT_VERIFIABLE"]

    def as_dict(self) -> dict[str, Any]:
        return {"root": self.root, "passed": self.passed, "failed": self.failed,
                "verdict_counts": _counts(self.checks),
                "failures": [f"{c.name}@{_where(self, c)}" for c in self.failures],
                "not_verifiable": [c.name for c in self.not_verifiable],
                "unexpected_paths": list(self.extras),
                "authoritative_security_verdict": False,
                "set_checks": [c.as_dict() for c in self.set_checks],
                "objects": [r.as_dict() for r in self.reports]}


def _where(topology: TopologyReport, check: PropertyCheck) -> str:
    for report in topology.reports:
        if any(c is check for c in report.checks):
            return report.label
    return "set"


def verify_topology(
    root: str | Path,
    targets: Iterable[TargetObject],
    *,
    subject_sid: str = SUBJECT_SID,
    operator_sid: str = OPERATOR_SID,
    subject_privileges: Iterable[str] = (),
    expected_owner_sid: str = OPERATOR_SID,
    observed_subject_operations: dict[str, str] | None = None,
) -> TopologyReport:
    """Read every object in the target set and evaluate M019 against each.

    READ-ONLY. This launches one PowerShell per object to read a descriptor and
    nothing else -- no ``icacls`` switch, no ``Set-Acl``, no process launched as
    the subject. It is what a caller reaches for when the question is "is this
    tree the intended boundary", as opposed to :func:`verify_properties`, which
    asks about a single descriptor.

    Objects outside ``targets`` are *listed* and reported, never evaluated and never
    touched: M019 T-PATH-2 exists because a fixture artifact sitting inside the
    target set is itself a violation, and quietly ignoring the surplus would hide
    exactly the thing that needs reporting.
    """
    topology = TopologyReport(root=str(root))
    targets = list(targets)
    root_path = Path(root)

    for target in targets:
        descriptor = read_descriptor(root_path / target.relative_path)
        topology.reports.append(verify_properties(
            descriptor, label=target.label, subject_sid=subject_sid,
            operator_sid=operator_sid,
            require_execute=bool(target.require_execute),
            subject_privileges=subject_privileges,
            expected_owner_sid=expected_owner_sid,
            observed_subject_operations=observed_subject_operations))

    declared = {"."} | {Path(t.relative_path).as_posix().casefold() for t in targets}
    found: list[str] = []
    if root_path.exists():
        found = sorted((p.relative_to(root_path).as_posix() or ".").casefold()
                       for p in [root_path, *root_path.rglob("*")])
    topology.extras = [name for name in found if name not in declared]

    debris = [name for name in topology.extras
              if any(marker in name for marker in FIXTURE_ARTIFACT_MARKERS)]
    topology.set_checks.append(PropertyCheck(
        "target_path_set_exact", "FAIL" if topology.extras else "PASS",
        "the target set holds only the declared paths" if not topology.extras
        else f"{len(topology.extras)} path(s) inside the target set were never "
             "declared: " + ", ".join(topology.extras),
        "descriptor", unexpected=list(topology.extras)))
    topology.set_checks.append(PropertyCheck(
        "no_fixture_artifacts_in_target_set", "FAIL" if debris else "PASS",
        "no M016 fixture artifact is inside the target set" if not debris
        else "fixture artifacts present in the target set: " + ", ".join(debris),
        "descriptor", artifacts=debris))
    return topology


# ---------------------------------------------------------------------------
# Token observation (M019 T-ADM-4). Read-only.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TokenObservation:
    """What the inspecting token actually holds. Read-only; never assumed."""

    user: str = "UNKNOWN"
    user_sid: str = "UNKNOWN"
    is_admin_role: bool = False
    groups: tuple[tuple[str, str], ...] = ()      # (sid-or-name, attribute)
    privileges: tuple[tuple[str, str], ...] = ()  # (name, "Enabled"/"Disabled")
    raw: str = ""

    def group_state(self, needle: str) -> str:
        """``"enabled"``/``"deny_only"``/``"absent"`` for a named group."""
        for name, attribute in self.groups:
            if needle.casefold() in name.casefold():
                return attribute
        return "absent"

    def administrators_confers_access(self) -> bool:
        """Whether Administrators membership actually grants anything here.

        From ``IsInRole``, which is language-independent and reflects the token
        rather than the account. M019 T-ADM-4 observed ``False``: the account is
        an administrator but this token is not elevated, so the SID is present
        and deny-only. Any verifier reasoning that says "Administrators is an
        administrator, therefore the operator has access" is wrong in this
        context, and this is the check that says so.
        """
        return self.is_admin_role

    def has_privilege(self, name: str) -> bool:
        return any(priv.casefold() == name.casefold()
                   for priv, state in self.privileges)

    def as_dict(self) -> dict[str, Any]:
        return {"user": self.user, "user_sid": self.user_sid,
                "is_in_role_administrator": self.is_admin_role,
                "administrators_group_state": self.group_state("Administrators"),
                "privileges": [list(p) for p in self.privileges],
                "groups": [list(g) for g in self.groups]}


_TOKEN_SCRIPT = r"""
$id = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object System.Security.Principal.WindowsPrincipal($id)
'token_user=' + $id.Name
'token_user_sid=' + $id.User.Value
'token_is_admin=' + $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
'token_is_system=' + $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::System)
"""


def current_token() -> TokenObservation:
    """Observe the inspecting token. READ-ONLY; launches nothing mutating.

    M019 T-ADM-4 recorded that this context's ``BUILTIN\\Administrators`` is
    deny-only, so an unelevated token. Verifier conclusions about administrative
    access are only sound with that state known: a check that assumed membership
    confers access would be assuming the thing M019 measured -- and would be wrong
    in exactly the context the laboratory runs in.

    Two sources, because neither alone answers the question:

    * ``WindowsIdentity`` gives the user SID and ``IsInRole``. That is the
      language-independent answer to "does Administrators membership confer
      anything?", and it is the one the conclusions rest on.
    * ``whoami /groups`` / ``whoami /priv`` in CSV form give the per-SID token
      attribute and the held privilege set. ``$id.Privileges`` enumerates empty
      here -- a .NET behaviour on a non-elevated ``GetCurrent()`` identity -- so
      the privilege evidence comes from ``whoami`` rather than being inferred
      from an empty collection, which would have quietly reported "no
      privileges" and made the traversal conclusion unfounded.

    The group *attribute* text is localised; the language-independent signal is
    ``IsInRole``, so that is what ``administrators_confers_access`` uses and the
    text is carried only as evidence.
    """
    raw = _powershell(_TOKEN_SCRIPT)
    user = user_sid = "UNKNOWN"
    is_admin = False
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("token_user_sid="):
            user_sid = line.split("=", 1)[1]
        elif line.startswith("token_user="):
            user = line.split("=", 1)[1]
        elif line.startswith("token_is_admin="):
            is_admin = line.split("=", 1)[1].strip().lower() == "true"

    groups = tuple((name, _classify_attribute(attribute))
                   for _, name, attribute in _group_rows())
    privileges = tuple((row[0].strip('" '), row[2].strip('" '))
                       for row in _csv_rows("whoami /priv /fo csv /nh") if len(row) >= 3)
    return TokenObservation(user=user, user_sid=user_sid, is_admin_role=is_admin,
                            groups=groups, privileges=privileges,
                            raw=raw + "\n" + _powershell("whoami /groups /fo csv /nh")
                            + _powershell("whoami /priv /fo csv /nh"))


def _csv_rows(command: str) -> list[list[str]]:
    """Rows of a ``/fo csv /nh`` listing. Read-only, one launch per call."""
    import csv
    import io

    text = _powershell(command) or ""
    return [row for row in csv.reader(io.StringIO(text)) if row]


def _group_rows() -> list[tuple[str, str, str]]:
    """``(sid, name, attribute)`` per group SID. Read-only."""
    out: list[tuple[str, str, str]] = []
    for row in _csv_rows("whoami /groups /fo csv /nh"):
        if len(row) < 4:
            continue
        out.append((row[2].strip(), row[0].strip(), row[3].strip()))
    return out


def _classify_attribute(attribute: str) -> str:
    """``deny_only`` / ``enabled`` / ``unknown`` for a token group attribute.

    Localised text, so the result is reported as evidence and never used as the
    basis of a conclusion -- :meth:`TokenObservation.administrators_confers_access`
    is, because it is derived from ``IsInRole``.
    """
    low = attribute.casefold()
    if "deny" in low:
        return "deny_only"
    if "enabled" in low:
        return "enabled"
    return "unknown"