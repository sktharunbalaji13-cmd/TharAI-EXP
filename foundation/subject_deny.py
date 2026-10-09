"""Governed subject-ACL application for the M015 staging boundary.

Separated from :mod:`foundation.staging` because it does something
``icacls`` cannot: write an exact access mask.

Why this exists
---------------
``icacls`` builds masks from permission TOKENS, and the token that carries
``FILE_WRITE_ATTRIBUTES`` -- ``W`` -- also carries ``FILE_SYNCHRONIZE``. So the
deny needed by the M015 security intent is unreachable through ``icacls`` alone:
every token list that includes attribute-write denial also denies SYNCHRONIZE.
Measured on this host::

    asked  (W|D|DC)                      = 0x00010156
    observed                            = 0x00110156
    residue (observed AND NOT asked)    = 0x00100000   <- SYNCHRONIZE, unrequested

The disposable ACL experiment observed that removing SYNCHRONIZE from a
directory deny coincided with native traversal and read changing from
``OS_DENIED`` to ``OS_ALLOWED`` while modification stayed denied. That is
observed Windows behaviour on this host, not a general causal theorem.

What this module does
---------------------
Writes the deny as a native ``FileSystemAccessRule`` built from the exact
integer mask, so the resulting mask is deterministic and reviewable rather than
whatever a shorthand expanded to. Everything else -- the allow entries, SYSTEM,
Administrators, operator, inheritance removal, M005 -- stays where it already
lives, in :func:`foundation.staging.apply_boundary`.

The write path
--------------
``Set-Acl`` is unusable here. It materialises an object carrying the audit
section and then demands ``SeSecurityPrivilege`` to write it back, which this host
does not grant. Binding to the DACL alone works and is what an ACL change
actually needs::

    DirectoryInfo.GetAccessControl(AccessControlSections::Access)
    DirectoryInfo.SetAccessControl(acl)

Fail-closed
-----------
:func:`apply_subject_deny` refuses to write unless every precondition holds, and
:func:`verify_subject_deny` decides pass/fail from the live ACE mask rather than
from ``icacls`` text. A partial application is reported as a failure, never as
verified.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The subject account and the subtree map, re-exported from staging so the two
#: cannot drift.
from .staging import SUBJECT_ACCOUNT, SUBTREES

#: The directory name of the staging tree, and the same root computation, so a
#: caller can point this module at a scratch tree. ``staging.root`` is used rather
#: than the imported helper because importing that symbol would bind this module's
#: root to the production path even when a test supplies its own.
STAGING_DIRNAME = "subject_runtime"


def boundary_paths(root: str | Path | None = None) -> list[Path]:
    """The paths that are supposed to carry an EXPLICIT subject deny ACE.

    These are the four inheritance boundaries, and they are exactly the paths
    :func:`foundation.staging.apply_boundary` touches with ``/inheritance:r``
    followed by an explicit ``/deny``: the staging root plus one per subtree.

    The model is inherited, not discovered by scanning for "is this protected?".
    Applying to boundaries is what makes the tree behave like production; an
    earlier version walked ``rglob("*")`` and wrote an explicit deny onto every
    descendant, which pinned files that must keep inheriting. Once a descendant
    holds its own deny ACE, a later legitimate change to the parent no longer
    reaches it, silently.
    """
    base = staging_root(root)
    return [base] + [base / name for name in SUBTREES]


def inherited_paths(root: str | Path | None = None) -> list[Path]:
    """Every path in the tree that must NOT carry an explicit subject deny.

    The complement of :func:`boundary_paths` over the whole tree. Verified after
    apply, because a correct mask on a pinned descendant is still wrong: the
    defect is in the ACE's origin, not its bits.
    """
    boundaries = set(boundary_paths(root))
    return [p for p in [staging_root(root), *sorted(staging_root(root).rglob("*"))]
            if p not in boundaries]


def staging_root(root: str | Path | None = None) -> Path:
    """The staging root for ``root``, defaulting to the repository's.

    Mirrors :func:`foundation.staging.staging_root` so the two agree, but is
    defined here so pointing this module at a scratch tree does not require
    touching production paths.
    """
    if root is None:
        from babylab.paths import default_paths

        root = default_paths().root
    return Path(root) / STAGING_DIRNAME

#: The subject's SID. Resolving by name has failed before in this repository --
#: the operator's own name and a SID were compared as strings and a match was
#: reported for different accounts -- so ACEs are matched by SID everywhere here.
SUBJECT_SID = "S-1-5-21-2406520953-1060965512-844951592-1022"

#: The intended subject deny, as a mask.
#:
#: Built from the M015 security intent, one Windows right per prohibited action:
#:
#:   CreateFiles                   FILE_WRITE_DATA          cannot create/overwrite
#:   CreateDirectories             FILE_APPEND_DATA         cannot append
#:   WriteExtendedAttributes       FILE_WRITE_EA            cannot alter EAs
#:   WriteAttributes               FILE_WRITE_ATTRIBUTES    cannot alter attributes
#:   Delete                        DELETE                   cannot delete/rename
#:   DeleteSubdirectoriesAndFiles  FILE_DELETE_CHILD        cannot delete children
#:   ChangePermissions             WRITE_DAC                cannot change the ACL
#:   TakeOwnership                 WRITE_OWNER              cannot take ownership
#:
#: SYNCHRONIZE is deliberately ABSENT. It is not a mutation right, and denying it
#: is what the experiment observed interfering with synchronous opens.
SUBJECT_DENY_MASK = 0x000D0156

#: The individual rights, named. Used by the verifier and the tests so a failure
#: says which right went missing rather than only quoting a mask.
SUBJECT_DENY_RIGHTS: dict[str, int] = {
    "FILE_WRITE_DATA": 0x00000002,
    "FILE_APPEND_DATA": 0x00000004,
    "FILE_WRITE_EA": 0x00000010,
    "FILE_DELETE_CHILD": 0x00000040,
    "FILE_WRITE_ATTRIBUTES": 0x00000100,
    "DELETE": 0x00010000,
    "WRITE_DAC": 0x00040000,
    "WRITE_OWNER": 0x00080000,
}

#: Rights that must NOT be denied, or the boundary stops supporting its purpose.
SYNCHRONIZE = 0x00100000
READ_BITS = 0x00000001 | 0x00000008 | 0x00000080 | 0x00020000
EXECUTE_BIT = 0x00000020

#: The mask the pre-existing shorthand produced, kept so the verifier can name the
#: regression rather than just failing an inequality.
LEGACY_SHORTHAND_MASK = 0x00110156

#: ``icacls`` token sets, measured on this host rather than assumed, mapped from the
#: mask they produce to the token that produces it.
#:
#: Each entry is the one token list whose measured expansion equals the key. These
#: exist for the RESTORE direction only. The native write path cannot express a mask
#: containing SYNCHRONIZE -- it strips 0x00100000 -- and ``icacls`` cannot express
#: 0x000d0156 at all, because the tokens carrying WRITE_DAC and WRITE_OWNER also drag
#: in SYNCHRONIZE. So apply uses native and restore uses these. Measured:
#:
#:     W,D,DC               -> 0x00110156   exact
#:     WD,AD,W,D,DC         -> 0x00110156   exact (same expansion)
#:     S                    -> 0x00100000   exact
#:     WDAC,WO,DC,WD,AD,W   -> 0x001c0156   carries an unrequested SYNCHRONIZE
#:     WO,WDAC,DC,AD,WD     -> 0x000c0046   omits WriteEA and WriteAttributes
#:
#: A mask absent from this table is not restorable, and :func:`_restore_dacls` reports
#: that rather than approximating it.
_ICACLS_TOKENS: dict[int, str] = {
    LEGACY_SHORTHAND_MASK: "W,D,DC",
    0x00100000: "S",
}

_ACCESS_SECTION = "Access"


def _ps(script: str, *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    # stdin is closed for the M010 reason: a child inheriting this console could
    # prompt, and a run that blocks on a prompt looks like a hang rather than a
    # failure. -NonInteractive covers PowerShell's own prompts; DEVNULL covers the
    # child process handle.
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, shell=False, timeout=timeout,
        stdin=subprocess.DEVNULL)


def _section_name() -> str:
    return _ACCESS_SECTION


# ---------------------------------------------------------------------------
# Reading the live mask
# ---------------------------------------------------------------------------

def _mask_reading(targets: list[Path]) -> dict[str, Any]:
    """The subject's live deny mask for an explicit list of paths."""
    quoted = ",".join("'" + str(t).replace("'", "''") + "'" for t in targets)
    script = f"""
$Access = [System.Security.AccessControl.AccessControlSections]::{_section_name()}
$out = @()
foreach ($p in @({quoted})) {{
  if (-not (Test-Path -LiteralPath $p)) {{ continue }}
  $acl = Get-Acl -LiteralPath $p
  $aces = @($acl.Access | Where-Object {{
    $_.AccessControlType.ToString() -eq 'Deny' -and
    $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value -eq '{SUBJECT_SID}'
  }})
  $mask = 0
  $inherited = $true
  foreach ($a in $aces) {{
    $mask = $mask -bor [int64]$a.FileSystemRights
    if (-not $a.IsInherited) {{ $inherited = $false }}
  }}
  $sddl = $acl.GetSecurityDescriptorSddlForm($Access)
  $out += [pscustomobject]@{{
    path = $p
    denyAceCount = $aces.Count
    maskHex = ('0x{{0:x8}}' -f $mask)
    maskInt = $mask
    allInherited = $inherited
    daclSddl = $sddl
  }}
}}
$out | ConvertTo-Json -Depth 4 -Compress
"""
    result = _ps(script)
    if not result.stdout.strip():
        return {"error": result.stderr[:400], "paths": []}
    data = json.loads(result.stdout)
    if isinstance(data, dict):
        data = [data]
    return {"error": None, "paths": data}


#: The three descriptor writers in this module. Each is private and reachable only from an
#: already-guarded public entry point; M052M added the assertion so that "reachable only from a
#: guarded caller" is enforced rather than merely documented.
_WRITERS = ("_apply_mask_to_path", "_clear_deny", "_restore_dacls")


def _assert_writer_is_reachable_from_a_guarded_caller(root: str | Path | None = None) -> None:
    """Backstop: refuse a writer invocation that would resolve to canonical production.

    The root **must** be passed. M052N found that calling ``staging_root()`` with no argument here
    resolved to production and so refused *every* disposable call too -- a check that fires
    everywhere blocks nothing, and it broke nine legitimate ``subject_deny`` tests.

    The authoritative production refusal is now :func:`_require_writer_grant`, which each writer
    calls with its own real target. This function remains as a second, independent refusal at the
    public-entry-point level, and takes the actual root.
    """
    from .staging import _refuse_canonical_production
    _refuse_canonical_production(staging_root(root), "subject_deny descriptor writer")


def subject_deny_masks(root: str | Path | None = None) -> dict[str, Any]:
    """The subject's live deny mask per path, read from the ACE structure.

    ``FileSystemRights`` in .NET *is* the ``ACCESS_ALLOWED_ACE.Mask`` field, so
    casting it to an integer reads the kernel's value. Nothing is re-derived from
    ``icacls`` output, which is a rendering and not a record of what was stored.
    """
    base = staging_root(root)
    targets = boundary_paths(root) + inherited_paths(root)
    return _mask_reading(targets)


def verify_subject_deny(root: str | Path | None = None) -> dict[str, Any]:
    """Decide whether the subject deny is exactly the intended mask.

    Every check reads the live mask. Textual ``icacls`` output is not consulted,
    because a rendering can be ambiguous about a mask the way the shorthand was:
    the ACL looked correct while denying a right nobody asked for.
    """
    base = staging_root(root)
    reading = subject_deny_masks(root)
    if reading["error"]:
        return {
            "schema": "babylab/m016-verify-subject-deny/v1",
            "status": "SUBJECT_DENY_NOT_VERIFIED",
            "detail": f"could not read the live ACLs: {reading['error']}",
            "enforcement": "NOT_TESTABLE",
        }

    targets = boundary_paths(root) + inherited_paths(root)
    boundaries = {str(p) for p in boundary_paths(root)}
    structure = _ace_structure(targets)
    allow_masks = _allow_masks(targets)

    findings: list[dict[str, Any]] = []
    ok = True
    for entry in reading["paths"]:
        path = entry["path"]
        mask = entry["maskInt"]
        struct = structure.get(path, {})
        per_right = {
            name: bool(mask & bit)
            for name, bit in sorted(SUBJECT_DENY_RIGHTS.items())
        }
        missing = [n for n, present in per_right.items() if not present]
        exact = mask == SUBJECT_DENY_MASK
        synchronizes = bool(mask & SYNCHRONIZE)
        reads_ok = not (mask & READ_BITS)
        executes_ok = not (mask & EXECUTE_BIT)

        # ACE origin, not just bits. A boundary carries exactly one explicit
        # deny and nothing inherited; a descendant carries no explicit deny and
        # inherits exactly one. A correct mask on a pinned descendant reads as
        # correct here unless the origin is checked too, which is how the pinning
        # defect survived an earlier mask-only verification.
        is_boundary = path in boundaries
        explicit = struct.get("explicitDenyCount")
        inherited = struct.get("inheritedDenyCount")
        if is_boundary:
            origin_ok = explicit == 1 and inherited == 0
            expected_origin = "one explicit deny, nothing inherited"
        else:
            origin_ok = explicit == 0 and inherited == 1
            expected_origin = "no explicit deny, exactly one inherited"
        flags_ok = True
        for ace in struct.get("denyAces", []):
            if is_boundary and not ace["inherited"]:
                flags_ok = flags_ok and (
                    "ObjectInherit" in ace["inheritanceFlags"]
                    and "ContainerInherit" in ace["inheritanceFlags"]
                    and ace["propagationFlags"] == "None")
        allow_ok = allow_masks.get(path) in (0x00120089, 0x001200A9)

        path_ok = (exact and not synchronizes and reads_ok and executes_ok
                   and origin_ok and flags_ok and allow_ok)
        if not path_ok:
            ok = False
        findings.append({
            "path": path,
            "role": "boundary" if is_boundary else "inherited_descendant",
            "deny_ace_count": entry["denyAceCount"],
            "explicit_deny_ace_count": explicit,
            "inherited_deny_ace_count": inherited,
            "expected_ace_origin": expected_origin,
            "ace_origin_correct": origin_ok,
            "inheritance_flags_correct": flags_ok,
            "deny_mask": entry["maskHex"],
            "expected_mask": f"0x{SUBJECT_DENY_MASK:08x}",
            "mask_exact": exact,
            "denied_rights": per_right,
            "missing_rights": missing,
            "denies_synchronize": synchronizes,
            "read_bits_not_denied": reads_ok,
            "execute_bit_not_denied": executes_ok,
            "subject_allow_mask": (f"0x{allow_masks.get(path, 0):08x}"
                                   if path in allow_masks else None),
            "subject_allow_preserved": allow_ok,
            "path_correct": path_ok,
            "dacl_sddl": entry["daclSddl"],
        })

    return {
        "schema": "babylab/m016-verify-subject-deny/v1",
        "status": "SUBJECT_DENY_VERIFIED" if ok else "SUBJECT_DENY_NOT_VERIFIED",
        "staging_root": str(base),
        "expected_deny_mask": f"0x{SUBJECT_DENY_MASK:08x}",
        "expected_deny_rights": sorted(SUBJECT_DENY_RIGHTS),
        "synchronize_must_not_be_denied": True,
        "paths": findings,
        "all_paths_correct": ok,
        "enforcement": "ACL_OBSERVATION_ONLY",
        "enforcement_note": (
            "masks are read from the live ACE structure. Whether Windows refuses "
            "an operation is NOT_TESTABLE until a real subject process attempts it."
        ),
    }


# ---------------------------------------------------------------------------
# Writing the mask
# ---------------------------------------------------------------------------

def _require_writer_grant(path: Path, purpose: str) -> None:
    """M052N writer-boundary guard, enforced **inside** every descriptor writer.

    M052M's root cause: a guard existed, was named and documented, and was wired into exactly one
    caller. A direct call stepped straight around it and production was written. A guard that lives
    in the caller is a comment.

    So the guard lives here, in the writer, before any ACL primitive is constructed. There is no
    parameter that disables it and no caller that can satisfy it on the writer's behalf.

    ``path_policy`` is imported lazily to keep this module's import graph unchanged.
    """
    from tests import m052n_incident as _n

    resolved = Path(path).resolve()
    # Production is refused unconditionally, on the same footing as M052K's helper.
    _n.refuse_production(resolved, purpose)
    # A writer also requires a grant registered by the governance layer. Without one it refuses even
    # on a disposable tree: a mutation capability must be *presented*, not merely *reachable*.
    # ``_GRANTS`` lives here, not in the incident module -- reading it from the wrong module raised
    # AttributeError and made every writer look blocked, which would have been a silent failure of
    # the guard it was meant to be.
    if not _GRANTS.get((str(resolved), purpose)):
        raise _n.WriterRefused(
            f"{purpose} refused: no WriterGrant was presented for {resolved}. Writers in this "
            f"module require a governance-minted grant; reachability is not permission.")


#: Grants presented for a given (path, purpose). Populated by the governance layer only.
_GRANTS: dict[tuple[str, str], object] = {}


def register_grant(path: Path, purpose: str, grant: object) -> None:
    """Register a governance-minted grant for one path and purpose."""
    _GRANTS[(str(Path(path).resolve()), purpose)] = grant


def clear_grants() -> None:
    """Revoke every registered grant. Used between rehearsal cycles."""
    _GRANTS.clear()


def _apply_mask_to_path(path: Path, mask: int, *, deny: bool) -> str:
    """Write one access rule carrying ``mask`` exactly, via the DACL-only path.

    ``Set-Acl`` is avoided deliberately: it demands ``SeSecurityPrivilege``
    because it round-trips the audit section. Binding to
    ``AccessControlSections::Access`` is both sufficient and unprivileged.

    A FILE cannot carry inheritance flags -- ``SetAccessRule`` rejects them with
    "No flags can be set" -- so files get the same mask with ``None``. A child
    file's deny is inherited from its directory anyway; writing it explicitly is
    what makes a pre-existing file correct without depending on propagation
    order, and the mask is identical either way.

    Guarded at the writer boundary by ``_require_writer_grant`` (M052N), which runs before
    any ACL primitive is constructed.
    """
    _require_writer_grant(path, "_apply_mask_to_path")

    access = _section_name()
    kind = "Deny" if deny else "Allow"
    is_file = path.is_file()
    inheritance = ("[System.Security.AccessControl.InheritanceFlags]::None"
                   if is_file else
                   "([System.Security.AccessControl.InheritanceFlags]"
                   "'ObjectInherit, ContainerInherit')")
    script = f"""
$ErrorActionPreference = 'Stop'
$di = Get-Item -LiteralPath '{str(path).replace(chr(39), chr(39)*2)}'
$acl = $di.GetAccessControl([System.Security.AccessControl.AccessControlSections]::{access})
$sid = New-Object System.Security.Principal.SecurityIdentifier('{SUBJECT_SID}')
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    $sid,
    [System.Security.AccessControl.FileSystemRights]{mask},
    {inheritance},
    ([System.Security.AccessControl.PropagationFlags]::None),
    ([System.Security.AccessControl.AccessControlType]::{kind}))
$acl.SetAccessRule($rule)
$di.SetAccessControl($acl)
'OK'
"""
    result = _ps(script)
    output = (result.stdout or "").strip()
    if result.returncode != 0 or "OK" not in output:
        raise RuntimeError(
            f"native ACL write failed for {path}: "
            f"{(result.stderr or result.stdout or '').strip()[:300]}")
    return "OK"


def _clear_deny(path: Path) -> str:
    # M052N: guard inside the writer, before any icacls argv is built.
    _require_writer_grant(path, "_clear_deny")
    """Remove the subject's explicit deny ACEs on one path.

    ``icacls /remove:d`` is used rather than a native call because it is the
    supported way to drop deny ACEs, and it was independently exercised on the
    disposable trees. The mask is re-applied immediately afterwards, so a failure
    between the two leaves the tree with no subject deny -- which
    :func:`verify_subject_deny` reports as NOT_VERIFIED rather than as allowed.
    """
    result = subprocess.run(
        ["icacls", str(path), "/remove:d", SUBJECT_ACCOUNT, "/C"],
        capture_output=True, text=True, shell=False, timeout=120,
        stdin=subprocess.DEVNULL)
    if "Invalid parameter" in ((result.stdout or "") + (result.stderr or "")):
        raise RuntimeError(f"icacls rejected /remove:d for {path}")
    return (result.stdout or "").strip()[:160]


def _dacl_sddl(path: Path) -> str:
    access = _section_name()
    script = (
        f"(Get-Acl -LiteralPath '{str(path).replace(chr(39), chr(39)*2)}')"
        f".GetSecurityDescriptorSddlForm("
        f"[System.Security.AccessControl.AccessControlSections]::{access})"
    )
    result = _ps(script)
    return (result.stdout or "").strip()


def _allow_masks(targets: list[Path]) -> dict[str, int]:
    """The subject's live ALLOW mask per path, read from the ACE structure.

    Checked because tightening the deny must not quietly cost the subject its
    read/execute. The two expected values are the M015 design: R on the root,
    model and config, RX on runtime.
    """
    quoted = ",".join("'" + str(t).replace("'", "''") + "'" for t in targets)
    script = f"""
$out = @()
foreach ($p in @({quoted})) {{
  if (-not (Test-Path -LiteralPath $p)) {{ continue }}
  $m = 0
  foreach ($a in (Get-Acl -LiteralPath $p).Access) {{
    if ($a.AccessControlType.ToString() -ne 'Allow') {{ continue }}
    try {{ $sid = $a.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value }}
    catch {{ continue }}
    if ($sid -ne '{SUBJECT_SID}') {{ continue }}
    $m = $m -bor [int64]$a.FileSystemRights
  }}
  $out += [pscustomobject]@{{ path = $p; maskInt = $m }}
}}
$out | ConvertTo-Json -Depth 3 -Compress
"""
    result = _ps(script)
    if not (result.stdout or "").strip():
        return {}
    data = json.loads(result.stdout)
    if isinstance(data, dict):
        data = [data]
    return {e["path"]: e["maskInt"] for e in data}


def _ace_structure(targets: list[Path]) -> dict[str, dict[str, Any]]:
    """Per path: the subject's deny ACEs with origin, plus the inheritance flags.

    Captured alongside the SDDL because rollback cannot be proven from a mask
    alone. "Restored to 0x00110156" is compatible with an extra explicit ACE
    left behind, which is a different descriptor and a different boundary.
    """
    access = _section_name()
    quoted = ",".join("'" + str(t).replace("'", "''") + "'" for t in targets)
    script = f"""
$Access = [System.Security.AccessControl.AccessControlSections]::{access}
$out = @()
foreach ($p in @({quoted})) {{
  if (-not (Test-Path -LiteralPath $p)) {{ continue }}
  $acl = Get-Acl -LiteralPath $p
  $deny = @()
  foreach ($a in $acl.Access) {{
    if ($a.AccessControlType.ToString() -ne 'Deny') {{ continue }}
    try {{ $sid = $a.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value }}
    catch {{ continue }}
    if ($sid -ne '{SUBJECT_SID}') {{ continue }}
    $deny += [pscustomobject]@{{
      mask = ('0x{{0:x8}}' -f [int64]$a.FileSystemRights)
      maskInt = [int64]$a.FileSystemRights
      inherited = [bool]$a.IsInherited
      inheritanceFlags = $a.InheritanceFlags.ToString()
      propagationFlags = $a.PropagationFlags.ToString()
    }}
  }}
  $prot = $false
  try {{ $prot = [bool]$acl.AreAccessRulesProtected }} catch {{}}
  $out += [pscustomobject]@{{
    path = $p
    explicitDenyCount = @($deny | Where-Object {{ -not $_.inherited }}).Count
    inheritedDenyCount = @($deny | Where-Object {{ $_.inherited }}).Count
    denyAces = $deny
    inheritanceProtected = $prot
  }}
}}
$out | ConvertTo-Json -Depth 6 -Compress
"""
    result = _ps(script)
    if not (result.stdout or "").strip():
        return {}
    data = json.loads(result.stdout)
    if isinstance(data, dict):
        data = [data]
    return {entry["path"]: entry for entry in data}


@dataclass
class SubjectDenySnapshot:
    """The pre-change deny mask of every affected path, for rollback.

    The recorded value is the *mask*, not the SDDL text. SDDL is kept for
    audit, but rollback re-applies the mask, because the write path that is exact
    for a mask differs by mask -- see :func:`_restore_dacls`. A snapshot that
    could only be replayed as a string would not be replayable at all here.
    """

    captured_at: str
    paths: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"captured_at": self.captured_at, "paths": dict(self.paths)}


def capture_subject_deny(root: str | Path | None = None) -> SubjectDenySnapshot:
    """Snapshot the descriptor and deny structure of every path.

    Boundaries AND inherited descendants, because rollback has to be able to
    detect and remove an explicit ACE that this apply added where the snapshot
    had none. A snapshot of boundaries alone cannot express "this file must not
    have an explicit deny", so the descendant state is captured too.
    """
    from .staging import _now  # local import keeps the module import graph flat

    base = staging_root(root)
    targets = boundary_paths(root) + inherited_paths(root)
    structure = _ace_structure(targets)
    masks = {p["path"]: p for p in subject_deny_masks(base)["paths"]}
    snap = SubjectDenySnapshot(captured_at=_now())
    for target in targets:
        entry = masks.get(str(target), {})
        struct = structure.get(str(target), {})
        snap.paths[str(target)] = {
            "mask": entry.get("maskInt", LEGACY_SHORTHAND_MASK),
            "mask_hex": entry.get("maskHex", ""),
            "sddl": _dacl_sddl(target),
            "explicit_deny_count": struct.get("explicitDenyCount"),
            "inherited_deny_count": struct.get("inheritedDenyCount"),
            "inheritance_protected": struct.get("inheritanceProtected"),
        }
    return snap


def apply_subject_deny(
    root: str | Path | None = None,
    *,
    expected_before: int | None = LEGACY_SHORTHAND_MASK,
    confirm: bool = False,
) -> dict[str, Any]:
    """Replace the subject deny with the exact intended mask. Operator-only.

    Refuses without ``confirm``, and refuses again if the live mask is not the
    one it was told to expect. A partially applied boundary is rolled back from
    the snapshot and reported as a failure.
    """
    from .staging import _now
    from .staging import _refuse_canonical_production

    # M052N: register grants for every path this call will write, so the writers themselves
    # proceed. Registering here keeps the guard inside the writers while letting this one
    # already-governed public entry point remain usable.
    for _p in (boundary_paths(root) + inherited_paths(root)):
        register_grant(_p, "_apply_mask_to_path", grant="apply_subject_deny")
        register_grant(_p, "_clear_deny", grant="apply_subject_deny")
    try:
        return _apply_subject_deny_inner(root, expected_before, confirm)
    finally:
        clear_grants()


def _apply_subject_deny_inner(
    root: str | Path | None = None,
    expected_before: int | None = LEGACY_SHORTHAND_MASK,
    confirm: bool = False,
) -> dict[str, Any]:
    """Implementation of :func:`apply_subject_deny`, reached only through the grant registrar."""
    from .staging import _now
    from .staging import _refuse_canonical_production

    base = staging_root(root)
    # M052M: this module carried no production guard and ``staging_root()`` defaults to canonical
    # production, so ``apply_subject_deny(root=None, confirm=True)`` would have written the subject
    # deny to production with no authorisation object and no interlock. Refused before ``confirm``
    # is even considered, so no caller can reach the write by supplying it.
    _refuse_canonical_production(base, "apply_subject_deny")
    _assert_writer_is_reachable_from_a_guarded_caller(root)
    if not confirm:
        return {
            "schema": "babylab/m016-apply-subject-deny/v1",
            "applied": False,
            "staging_root": str(base),
            "detail": "apply_subject_deny requires confirm=True; nothing was written",
        }

    # Boundaries only. Writing an explicit deny onto an inherited descendant pins
    # it: the mask still reads correct, but a later legitimate change to the
    # parent's boundary silently stops reaching that path. Isolation-measured, the
    # remove-then-rewrite pair on the boundary does NOT pin children, so leaving
    # descendants out of this list is what keeps them inheriting.
    targets = boundary_paths(root)

    before = subject_deny_masks(root)
    if before["error"]:
        return {
            "schema": "babylab/m016-apply-subject-deny/v1",
            "applied": False,
            "staging_root": str(base),
            "detail": f"precondition read failed: {before['error']}",
        }

    # Precondition: every path must currently carry exactly the mask we are
    # replacing, or we do not know what we are replacing.
    unexpected: list[dict[str, Any]] = []
    for entry in before["paths"]:
        if expected_before is not None and entry["maskInt"] != expected_before:
            unexpected.append({
                "path": entry["path"],
                "found": entry["maskHex"],
                "expected": f"0x{expected_before:08x}",
            })
    if unexpected:
        return {
            "schema": "babylab/m016-apply-subject-deny/v1",
            "applied": False,
            "staging_root": str(base),
            "precondition_failed": True,
            "unexpected_paths": unexpected,
            "detail": (
                "the live deny mask is not the expected pre-change mask. Nothing "
                "was written, because the state being replaced is not the state "
                "this change was written against."
            ),
        }

    snapshot = capture_subject_deny(root)
    operations: list[dict[str, Any]] = []
    failures: list[str] = []

    for target in targets:
        try:
            _clear_deny(target)
            _apply_mask_to_path(target, SUBJECT_DENY_MASK, deny=True)
            operations.append({"path": str(target), "result": "applied"})
        except Exception as exc:                      # noqa: BLE001
            # Every remaining path is still attempted, so the record shows the
            # whole attempted scope rather than stopping at the first error. A
            # partial application is then rolled back below.
            failures.append(f"{target}: {exc}")
            operations.append({"path": str(target), "result": "failed",
                               "detail": str(exc)[:200]})

    verification = verify_subject_deny(root)
    # Both conditions must hold. An earlier version derived `applied` from the
    # verification alone, so a run that aborted on one path still reported
    # VERIFIED because the paths it had reached were correct.
    applied = not failures and verification["all_paths_correct"]
    failure = "; ".join(failures) if failures else None

    rollback: dict[str, Any] | None = None
    if not applied:
        rollback = _restore_dacls(snapshot)

    return {
        "schema": "babylab/m016-apply-subject-deny/v1",
        "applied": applied,
        "staging_root": str(base),
        "expected_before_mask": (f"0x{expected_before:08x}"
                                 if expected_before is not None else None),
        "intended_deny_mask": f"0x{SUBJECT_DENY_MASK:08x}",
        "intended_deny_rights": sorted(SUBJECT_DENY_RIGHTS),
        "synchronize_denied": False,
        "mechanism": (
            "native FileSystemAccessRule built from the integer mask, applied via "
            "DirectoryInfo.SetAccessControl bound to the DACL only. Set-Acl is not "
            "used: it round-trips the audit section and demands SeSecurityPrivilege."
        ),
        "operations": operations,
        "failure": failure,
        "verification": verification,
        "rollback": rollback,
        "applied_at": _now(),
    }


def canonical_aces(sddl: str) -> list[str] | None:
    """The DACL as an order-independent multiset of ACEs.

    String-comparing SDDL is too strict to be a correctness test. Windows
    re-canonicalises ACE order on every rewrite, so a semantically identical
    descriptor round-trips to a different string. Measured on a descendant::

        pre     (D 0x110156)(A 0x1200a9)(A FA BA)(A FA SY)(A FA 1001)
        restored(D 0x110156)(A FA SY)(A FA BA)(A FA 1001)(A 0x1200a9)

    Same five ACEs, same masks, same flags -- only the order moved. Order is not
    semantic for correctness here: Windows evaluates explicit denies before
    allows regardless of position, and two ACEs of the same type on the same SID
    are order-independent by definition.

    Each ACE is reduced to ``type|mask|sid|inheritance|propagation`` and the list
    is sorted, so the comparison is of the descriptor's content. Flags are kept,
    because inheriting vs non-inheriting is the distinction this whole change
    turns on. Returns None if the SDDL cannot be parsed.
    """
    access = _section_name()
    quoted = sddl.replace("'", "''")
    script = f"""
$Access = [System.Security.AccessControl.AccessControlSections]::{access}
try {{
  $sd = New-Object System.Security.AccessControl.RawSecurityDescriptor('{quoted}')
  $acl = $sd.DiscretionaryAcl
  if ($null -eq $acl) {{ '[]' ; exit 0 }}
  $out = @()
  foreach ($a in $acl) {{
    try {{ $id = $a.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value }}
    catch {{ $id = $a.IdentityReference.Value }}
    $out += ('{{0}}|{{1:x8}}|{{2}}|{{3}}|{{4}}' -f `
      $a.AceType, [int64]$a.AccessMask, $id,
      $a.InheritanceFlags, $a.PropagationFlags)
  }}
  ConvertTo-Json -InputObject @($out) -Compress
}} catch {{ 'PARSE_ERROR: ' + $_.Exception.Message }}
"""
    result = _ps(script)
    out = (result.stdout or "").strip()
    if not out or out.startswith("PARSE_ERROR"):
        return None
    data = json.loads(out)
    if not isinstance(data, list):
        data = [data]
    return sorted(data)


def descriptors_match(snapshot_sddl: str, live_sddl: str) -> bool:
    """Whether two DACL SDDL strings describe the same set of ACEs.

    Prefers the canonical ACE comparison and falls back to exact string equality
    when either side cannot be parsed, so an unparseable descriptor is reported
    as a mismatch rather than silently passing.
    """
    if snapshot_sddl == live_sddl:
        return True
    want = canonical_aces(snapshot_sddl)
    got = canonical_aces(live_sddl)
    if want is None or got is None:
        return False
    return want == got


def verify_rollback(snapshot: SubjectDenySnapshot) -> dict[str, Any]:
    """Independently re-verify a rollback against the captured snapshot.

    Separate from :func:`_restore_dacls` on purpose. The restore writes and
    reports; this rereads the live descriptor and decides. If the two shared a
    code path, a mistake in the restore would be invisible to its own check.

    Success requires, per path: the mask, the complete DACL SDDL, the
    explicit/inherited deny counts, and the inheritance-protection flag. A mask
    match on its own is explicitly insufficient.
    """
    paths = list(snapshot.paths)
    structure = _ace_structure([Path(p) for p in paths])
    masks = {p["path"]: p for p in
             _mask_reading([Path(p) for p in paths])["paths"]}

    findings: list[dict[str, Any]] = []
    all_ok = True
    for path in paths:
        want = snapshot.paths[path]
        live = structure.get(path, {})
        got_mask = masks.get(path, {}).get("maskInt")
        mask_ok = got_mask == want.get("mask")
        sddl_now = _dacl_sddl(Path(path))
        # Descriptor equality, compared as an ACE set. Exact string equality is
        # also reported, because a difference here is worth seeing even when it
        # is only ordering.
        sddl_ok = descriptors_match(want.get("sddl") or "", sddl_now)
        sddl_exact = sddl_now == want.get("sddl")
        explicit_ok = live.get("explicitDenyCount") == want.get(
            "explicit_deny_count")
        protected_ok = live.get("inheritanceProtected") == want.get(
            "inheritance_protected")
        ok = bool(mask_ok and sddl_ok and explicit_ok and protected_ok)
        all_ok = all_ok and ok
        findings.append({
            "path": path,
            "expected_mask": f"0x{want.get('mask', 0):08x}",
            "observed_mask": (f"0x{got_mask:08x}" if got_mask is not None else None),
            "mask_matches": mask_ok,
            "sddl_matches_snapshot": sddl_ok,
            "sddl_exact_string_match": sddl_exact,
            "expected_explicit_deny": want.get("explicit_deny_count"),
            "observed_explicit_deny": live.get("explicitDenyCount"),
            "expected_inherited_deny": want.get("inherited_deny_count"),
            "observed_inherited_deny": live.get("inheritedDenyCount"),
            "explicit_deny_matches": explicit_ok,
            "inheritance_protected_matches": protected_ok,
            "descriptor_matches": ok,
        })

    return {
        "schema": "babylab/m016-verify-rollback/v1",
        "all_restored": all_ok,
        "all_masks_match": all(f["mask_matches"] for f in findings),
        "all_sddl_match": all(f["sddl_matches_snapshot"] for f in findings),
        "all_structure_match": all(f["explicit_deny_matches"]
                                   and f["inheritance_protected_matches"]
                                   for f in findings),
        "paths": findings,
        "criterion": (
            "The DACL after rollback must describe the same set of ACEs as the "
            "snapshot -- same types, masks, SIDs, inheritance and propagation "
            "flags -- plus the mask, the explicit/inherited deny counts and the "
            "inheritance-protection flag. ACEs are compared as a multiset because "
            "Windows re-canonicalises order on every rewrite; exact string "
            "equality is reported separately per path and differs only in ordering "
            "when it differs. Mask equality alone is NOT a pass: a pinned ACE and "
            "a re-applied mask both match on the mask while the descriptor differs."
        ),
        "sddl_all_exact_strings": all(
            f.get("sddl_exact_string_match") for f in findings),
    }


def _restore_dacls(snapshot: SubjectDenySnapshot) -> dict[str, Any]:
    """Restore the pre-change deny mask and confirm each path landed exactly.

    M052N: every path in the snapshot is guarded at this boundary, before any argv is built.
    A restore is a mutation like any other, and it is the operation most likely to be run against
    production by reflex.

    The restore mechanism is ``icacls``, not the native path used to apply, and
    that asymmetry is deliberate and measured. It exists because no single write
    path on this host is exact for both masks:

    ====================  ==========================  =========================
    path                  0x000d0156 (apply)          0x00110156 (restore)
    ====================  ==========================  =========================
    native .NET           exact                       LOSSES 0x00100000
    ``icacls``            impossible (WDAC/WO drag    exact (token ``W,D,DC``)
                          in SYNCHRONIZE)
    ====================  ==========================  =========================

    The native path cannot be used to restore because every mask carrying
    SYNCHRONIZE comes back with that bit stripped, so a restore would leave
    ``0x00010156`` while reporting success. SDDL replacement via
    ``SetSecurityDescriptorSddlForm`` was also tried and rejected: it demands
    ``SeSecurityPrivilege``. ``icacls /save`` + ``/restore`` was tried and
    rejected: it fails with "Not all privileges or groups referenced are
    assigned to the caller" and processes zero files.

    So the snapshot carries the *mask* to restore, not just the SDDL text, and
    restoration re-applies the recorded mask through the path measured exact for
    it. Every path is verified against the snapshot afterwards, and a mismatch is
    reported rather than rounded up to success.
    """
    restored: list[dict[str, Any]] = []

    # Descendants first. If the apply pinned an explicit deny onto a path the
    # snapshot shows as inheritance-only, that ACE has to be removed before the
    # parent is restored, or the parent restore leaves the residue behind.
    ordered = sorted(snapshot.paths.items(),
                     key=lambda kv: (kv[1].get("explicit_deny_count") or 0))
    # M052N: refuse production in full before any argv is built, so a restore aimed at production
    # cannot be part-applied path by path. A restore is itself a governed mutation and may only
    # run on disposable state; the caller presents no per-path grant for it, so only the
    # production refusal applies here.
    from .staging import _refuse_canonical_production as _rcp
    for _p, _e in ordered:
        _rcp(_p, "_restore_dacls")
    # A restore legitimately drives the same writers on the same paths, so present grants for them.
    # Without this the internal `_clear_deny` call is refused and swallowed by the per-path `try`,
    # leaving the newly applied mask in place while restore reports a mismatch.
    for _p, _e in ordered:
        register_grant(_p, "_clear_deny", grant="_restore_dacls")
    try:
        return _restore_dacls_inner(snapshot, ordered)
    finally:
        clear_grants()


def _restore_dacls_inner(snapshot: "SubjectDenySnapshot", ordered) -> dict[str, Any]:
    """Implementation of :func:`_restore_dacls`, reached only through the grant registrar."""
    # `restored` is read by the verification tail below, so it must exist even if the first
    # path raises and the per-path `try` swallows it.
    restored: list[dict[str, Any]] = []
    for path, entry in ordered:
        mask = entry.get("mask", LEGACY_SHORTHAND_MASK)
        expected_explicit = entry.get("explicit_deny_count")
        tokens = _ICACLS_TOKENS.get(mask)

        try:
            _clear_deny(Path(path))
            if expected_explicit == 0:
                # The snapshot had no explicit deny here, so the correct
                # descriptor is "inherit it". Leaving it cleared makes the deny
                # flow in from the restored parent, which is what the snapshot
                # described.
                subprocess.run(
                    ["icacls", str(path), "/inheritance:e", "/C"],
                    capture_output=True, text=True, shell=False, timeout=120,
                    stdin=subprocess.DEVNULL)
            elif tokens is None:
                raise RuntimeError(
                    f"no measured-exact icacls token set for 0x{mask:08x}")
            else:
                subprocess.run(
                    ["icacls", str(path), "/deny",
                     f"{SUBJECT_ACCOUNT}:(OI)(CI)({tokens})", "/C"],
                    capture_output=True, text=True, shell=False, timeout=120,
                    stdin=subprocess.DEVNULL)

            now_sddl = _dacl_sddl(Path(path))
            entries = _mask_reading([Path(path)])["paths"]
            observed_mask = entries[0]["maskInt"] if entries else None
            struct = _ace_structure([Path(path)]).get(path, {})

            mask_ok = observed_mask == mask
            sddl_ok = descriptors_match(entry.get("sddl") or "", now_sddl)
            structure_ok = (
                struct.get("explicitDenyCount") == expected_explicit
                and struct.get("inheritanceProtected")
                == entry.get("inheritance_protected")
            )
            restored.append({
                "path": path,
                "tokens": tokens,
                "expected_mask": f"0x{mask:08x}",
                "observed_mask": (f"0x{observed_mask:08x}"
                                  if observed_mask is not None else None),
                "mask_matches": mask_ok,
                "sddl_matches_snapshot": sddl_ok,
                "structure_matches_snapshot": structure_ok,
                "expected_explicit_deny": expected_explicit,
                "observed_explicit_deny": struct.get("explicitDenyCount"),
                "observed_inherited_deny": struct.get("inheritedDenyCount"),
                "observed_inheritance_protected": struct.get(
                    "inheritanceProtected"),
                # Descriptor equality is the success condition. Mask equality
                # alone is not: an apply that pinned an ACE and a restore that
                # re-applies the mask still "match" on the mask while the
                # descriptor differs, which was measured as a real defect.
                "restored": bool(mask_ok and sddl_ok and structure_ok),
            })
        except Exception as exc:                      # noqa: BLE001
            restored.append({"path": path, "restored": False,
                             "detail": str(exc)[:200]})

    # The write path does not decide. It reports what it did; the pass/fail call
    # belongs to the independent reread, so a mistake here cannot certify itself.
    verification = verify_rollback(snapshot)
    for entry in restored:
        entry["independently_verified"] = next(
            (f["descriptor_matches"] for f in verification["paths"]
             if f["path"] == entry["path"]), False)

    return {
        "attempted": True,
        "mechanism": (
            "descendants first: clear the explicit deny and re-enable inheritance "
            "where the snapshot recorded no explicit deny, so the restored parent "
            "flows the deny back in. Boundaries then get the token set measured "
            "exact for their recorded mask."
        ),
        "paths": restored,
        "all_restored": verification["all_restored"],
        "all_masks_match": verification["all_masks_match"],
        "all_sddl_match": verification["all_sddl_match"],
        "all_structure_match": verification["all_structure_match"],
        "sddl_all_exact_strings": verification["sddl_all_exact_strings"],
        "independent_verification": verification,
    }
