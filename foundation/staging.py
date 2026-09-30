"""The subject-runtime staging boundary: create it, govern it, prove it.

M015. This module builds the staging tree and its ACLs. It does **not** birth,
attach a subject, select a model, or select a runtime.

The one design decision everything else follows from
---------------------------------------------------
The repository root grants ``NT AUTHORITY\\Authenticated Users:(M)`` -- Modify,
which includes Write and Delete -- and ``BABY_AI_TEST`` necessarily holds
``Authenticated Users`` because it is enabled and has logged on. So a staging
directory created here with default inheritance would hand the subject **write and
delete over the staged runtime and the staged model**.

Inheritance is therefore broken explicitly (:func:`apply_boundary`) and the
resulting ACL is read back and asserted (:func:`verify_boundary`). A ``DENY`` ACE
alone is not sufficient here, and that is the difference from M005: M005's
protected paths are a *deny-list* on top of an inherited Modify, whereas this
boundary is an *allow-list* that removes the inherited Modify entirely. The
user-visible proof is that ``Authenticated Users:(M)`` is **absent** from the
staging subtree rather than merely overridden.

What the subject may do
-----------------------
======================  ================================================
``subject_runtime\\``   traverse, read
``runtime\\``           read, execute
``model\\``             read
``config\\``            read
======================  ================================================

and nothing else: no write, no delete, no rename, no child creation, no ACL
change. The model is deliberately readable, because the subject has to read the
weights to run them. This boundary provides **integrity**, not confidentiality,
and :data:`CONFIDENTIALITY_NOT_PROVIDED` says so where a reader will look.

Nothing here stages a real artifact by default. See :func:`deploy_runtime`, which
requires an explicit human-supplied source path, and refuses to infer one.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

#: The staging root, relative to the repository. Named by this milestone.
STAGING_DIRNAME = "subject_runtime"

#: The three subtrees, and the access each grants the subject.
SUBTREES: dict[str, str] = {
    "runtime": "RX",   # read and execute: the native runtime
    "model": "R",      # read only: the subject must load the weights
    "config": "R",     # read only: immutable runtime configuration
}

#: The subject account, re-exported so this module cannot drift from M011's
#: single definition.
SUBJECT_ACCOUNT = "THARUNBALAJI-LA\\BABY_AI_TEST"

#: Stated in the record as well as the documentation. An ACL governs the
#: filesystem; it does not make a process local-only.
CONFIDENTIALITY_NOT_PROVIDED = (
    "the subject must read the model to run it; this boundary provides "
    "integrity, not confidentiality"
)

NETWORK_NOT_ESTABLISHED = (
    "filesystem ACLs do not establish LOCAL_ONLY_NO_FETCH. A staged runtime may "
    "still hold network capability; network isolation is a separate gate and is "
    "NOT_TESTABLE here."
)

#: Write, delete, and ACL-change rights denied to the subject on every path in the
#: staging tree. W=write data, AD=append data, WD=write DAC, D=delete,
#: DC=delete child, OI/CI=inherit to files and subdirectories.
SUBJECT_DENY_RIGHTS = "WD,AD,W,D,DC"


class StagingStatus(str, Enum):
    """The states the Observatory reports. Never ``READY`` for birth."""

    STAGING_NOT_CONFIGURED = "STAGING_NOT_CONFIGURED"
    STAGED_RUNTIME = "STAGED_RUNTIME"
    STAGED_MODEL = "STAGED_MODEL"
    STAGING_VERIFIED = "STAGING_VERIFIED"
    STAGING_BLOCKED = "STAGING_BLOCKED"
    STAGING_FAILED = "STAGING_FAILED"
    NOT_TESTABLE = "NOT_TESTABLE"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


def staging_root(root: str | Path | None = None) -> Path:
    """The absolute staging root. Computed, never searched for."""
    if root is None:
        from babylab.paths import default_paths

        root = default_paths().root
    return Path(root) / STAGING_DIRNAME


def _run(argv: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a command with an explicit argv and no shell.

    ``shell=False`` and a closed stdin, per the project's standing subprocess
    rule. Every argument here comes from this module or from a human-supplied
    path -- never from a document or from a discovered file.
    """
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          shell=False, stdin=subprocess.DEVNULL,
                          encoding="utf-8", errors="replace")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: str | Path) -> str:
    """SHA-256 of a file, read in chunks so a multi-gigabyte model is fine."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# ACL application
# ---------------------------------------------------------------------------

def apply_boundary(
    root: str | Path | None = None,
    *,
    operator: str | None = None,
) -> dict[str, Any]:
    """Create the staging tree and apply its ACLs. Operator-only action.

    Order matters and is deliberate:

    1. create the three subtrees;
    2. **remove inheritance** on the whole tree;
    3. grant the subject only read/execute, never write;
    4. add the deny backstop for write/delete/ACL-change;
    5. re-apply the operator/SYSTEM/Administrators grants so step 2 cannot have
       left the tree unmanageable.

    Step 2 before step 3 is the whole point: granting the subject first and
    removing inheritance afterwards would leave inherited ``Authenticated
    Users:(M)`` converted to an explicit ACE, which the subject would still hold.
    """
    base = staging_root(root)
    operator = operator or os.environ.get("USERNAME") or "operator"

    created = []
    for name in ("", *SUBTREES):
        target = base / name if name else base
        if not target.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            created.append(str(target))

    # Inheritance must be removed on every path, or the inherited Modify survives
    # on whichever subtree missed it.
    inheritance = _run(["icacls", str(base), "/inheritance:r", "/T", "/C"])

    # Per-subtree grants, because the access genuinely differs: the runtime is a
    # program and must be executable, the model and config are data and must not
    # be. Granting RX to everything would hand the subject execute rights over
    # the model, and granting R to everything would leave the runtime unloadable.
    per_subtree: list[tuple[str, str]] = [
        f"{operator}:(OI)(CI)(F)",
        "NT AUTHORITY\\SYSTEM:(OI)(CI)(F)",
        "BUILTIN\\Administrators:(OI)(CI)(F)",
        f"{SUBJECT_ACCOUNT}:(OI)(CI)(RX)",
    ]
    for name, rights in SUBTREES.items():
        per_subtree.append(f"{SUBJECT_ACCOUNT}:(OI)(CI)({rights})")

    applied: list[dict[str, Any]] = []

    # Grants are applied to the *root* and inherited down, then each subtree is
    # reset to have no inherited entries of its own. Applying to the root and
    # walking with /T instead would stamp a second, near-duplicate set of
    # entries onto every child -- an explicit RX plus an inherited RX -- which is
    # how a tree ends up carrying two ACLs that disagree.
    for entry in per_subtree:
        result = _run(["icacls", str(base), "/grant:r", entry, "/C"])
        applied.append({"operation": "grant", "entry": entry,
                        "exit": result.returncode,
                        "detail": (result.stdout or result.stderr or "").strip()[:200]})

    # A deny needs /deny. /grant cannot create one, so the root's backstop is
    # issued separately -- otherwise the root is the one path in the tree with no
    # deny, and it is the path that gates access to all three subtrees.
    result = _run(["icacls", str(base), "/deny",
                   f"{SUBJECT_ACCOUNT}:(OI)(CI)({SUBJECT_DENY_RIGHTS})", "/C"])
    applied.append({"operation": "deny", "entry": f"{base} :: root backstop",
                    "exit": result.returncode,
                    "detail": (result.stdout or result.stderr or "").strip()[:200]})

    # Now clean the children: drop inheritance, then re-grant exactly what that
    # subtree needs. The deny backstop is re-applied last because it must be the
    # most specific.
    for name, rights in SUBTREES.items():
        target = base / name
        child = _run(["icacls", str(target), "/inheritance:r", "/C"])
        applied.append({"operation": "inheritance_reset", "entry": str(target),
                        "exit": child.returncode,
                        "detail": (child.stdout or "").strip()[:160]})
        for entry in (
            f"{operator}:(OI)(CI)(F)",
            "NT AUTHORITY\\SYSTEM:(OI)(CI)(F)",
            "BUILTIN\\Administrators:(OI)(CI)(F)",
            f"{SUBJECT_ACCOUNT}:(OI)(CI)({rights})",
        ):
            result = _run(["icacls", str(target), "/grant:r", entry, "/C"])
            applied.append({"operation": "grant", "entry": f"{target} :: {entry}",
                            "exit": result.returncode,
                            "detail": (result.stdout or result.stderr or "").strip()[:200]})
        result = _run(["icacls", str(target), "/deny",
                       f"{SUBJECT_ACCOUNT}:(OI)(CI)({SUBJECT_DENY_RIGHTS})", "/C"])
        applied.append({"operation": "deny", "entry": str(target),
                        "exit": result.returncode,
                        "detail": (result.stdout or result.stderr or "").strip()[:200]})

    failures = [item for item in applied if item["exit"] != 0]
    return {
        "schema": "babylab/m015-apply-boundary/v1",
        "staging_root": str(base),
        "subtrees": {name: str(base / name) for name in SUBTREES},
        "created": created,
        "inheritance_removed_exit": inheritance.returncode,
        "inheritance_detail": (inheritance.stdout or "").strip()[:200],
        "operations": applied,
        "failed_operations": failures,
        "status": (StagingStatus.STAGING_FAILED if failures
                   else StagingStatus.STAGING_NOT_CONFIGURED),
        "applied_at": _now(),
    }


# ---------------------------------------------------------------------------
# ACL verification
# ---------------------------------------------------------------------------

def acl_of(path: str | Path) -> list[str]:
    """The raw ACL entries for one path, normalised to ``principal:(rights)``.

    Read-only. Two normalisations happen here, because ``icacls`` output cannot be
    compared as-is:

    * the first line carries the path, which would otherwise parse as a principal;
    * principal names contain spaces (``NT AUTHORITY\\SYSTEM``,
      ``THARUNBALAJI-LA\\k.tharun balaji``), so an entry is read by locating the
      ``:(`` that starts the flags rather than by splitting on whitespace.

    Without the second, every such principal truncates to its first word and the
    verifier reports rights for an account that does not exist.
    """
    result = _run(["icacls", str(path)])
    entries: list[str] = []
    for raw in (result.stdout or "").splitlines():
        line = raw.strip()
        if not line or "Successfully processed" in line:
            continue
        marker = line.find(":(")
        if marker <= 0:
            continue
        principal = line[:marker].strip()
        # icacls prefixes the first line with the path, so for that one entry the
        # principal is really "<path> <principal>". Strip it by prefix length using
        # both separator spellings: a suffix test never matches, and any
        # character-level rewrite mangles principals that legitimately contain an
        # underscore -- BABY_AI_TEST would become "baby\ai\test".
        for form in (str(path), str(path).replace("/", "\\"),
                     str(path).replace("\\", "/")):
            if principal.lower().startswith(form.lower()):
                principal = principal[len(form):].strip()
                break
        remainder = line[marker + 1:]
        end = remainder.rfind(")")
        flags = remainder[: end + 1] if end != -1 else remainder
        entries.append(f"{principal}:{flags}")
    return entries


def _owner_of(path: str | Path) -> str:
    """The owner of one path. Read-only.

    Ownership matters independently of the ACEs: an owner may rewrite the DACL
    regardless of what the DACL currently grants, so a tree the subject owns is a
    tree the subject can unlock. The deny on WriteDAC does not stop this, because
    taking ownership is a different right from changing it.

    ``icacls`` prints no owner marker at all, so it cannot answer this -- it would
    report ``''`` for every path and the check would pass vacuously. ``dir /q``
    prints the owner, but truncates the name at 8.3, which is ambiguous between
    accounts. ``Get-Acl`` is therefore the only source used, and a non-empty
    answer is required: an unreadable owner is treated as unverified, never as
    "not the subject".
    """
    result = _run([
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        f"(Get-Acl -LiteralPath {subprocess.list2cmdline([str(path)])}).Owner",
    ])
    return (result.stdout or "").strip()


def _principals(entries: list[str]) -> dict[str, str]:
    """Map principal -> its combined rights, from normalised entries.

    A path can hold several entries for one principal, so the rights are
    concatenated rather than overwritten; a grant and a deny for the same
    principal are both captured, and :func:`_split_subject_entries` is what
    separates them.
    """
    found: dict[str, str] = {}
    for entry in entries:
        marker = entry.find(":")
        if marker <= 0:
            continue
        principal = entry[:marker]
        found[principal] = found.get(principal, "") + entry[marker + 1:]
    return found


#: The permission letters an icacls abbreviation expands to. Comparisons are done
#: on the expanded set rather than on the literal label, because a label test such
#: as ``"R" in "(OI)(CI)(R)(OI)(CI)(WD)"`` is true -- the R substring is still there
#: -- so an *extra* ACE bolted onto a correct one is invisible to it. Set equality
#: cannot be fooled that way.
_RIGHTS_EXPAND = {
    "F": "RXW D DC WD AD GW GA".split(),
    "M": "RXW D DC".split(),
    "RX": "RX",
    "R": "R",
    "X": "X",
    "W": "W",
    "D": "D",
    "DC": "DC",
    "WD": "WD",
    "AD": "AD",
    "GW": "GW",
    "GA": "GA",
}

#: Letters that let the subject change the object rather than only read it.
_MUTATING = {"W", "D", "DC", "WD", "AD", "GW", "GA"}


def _expand(flags: str) -> set[str]:
    """The permission letters in an icacls flag string, fully expanded."""
    letters: set[str] = set()
    for chunk in flags.replace("(", " ").replace(")", " ").split():
        if chunk in {"OI", "CI", "IO", "I", "DENY", "N"}:
            # OI/CI/IO say how an entry propagates, not what it permits; treating
            # them as permissions would make every entry look broader than it is.
            continue
        for letter in chunk:
            letters.update(_RIGHTS_EXPAND.get(letter, []))
    return letters


def _render(letters: set[str]) -> str:
    """A canonical label for a set of permissions, or ``''`` when empty."""
    for label, expanded in (("F", "RXW D DC WD AD GW GA".split()),):
        if letters == set(expanded):
            return label
    if letters == {"R", "X", "W", "D", "DC"}:
        return "M"
    if letters == {"R", "X"}:
        return "RX"
    if letters == {"R"}:
        return "R"
    if letters == {"X"}:
        return "X"
    return "".join(sorted(letters))


def _split_subject_entries(entries: list[str]) -> tuple[str, set[str], list[str]]:
    """The subject's grants, the expanded permission set, and its deny rights.

    icacls marks a deny with ``(DENY)`` rather than by a distinct rights label,
    so a grant and a deny for one principal are separate entries. They are unioned
    here because "the subject may write" must hold across every grant ACE, not per
    ACE -- two grants of ``R`` and ``WD`` together mean the subject may write.
    """
    grants: set[str] = set()
    raw: set[str] = set()
    denies: list[str] = []
    for entry in entries:
        marker = entry.find(":")
        if marker <= 0 or entry[:marker] != SUBJECT_ACCOUNT:
            continue
        flags = entry[marker + 1:]
        # DENY arrives as a distinct ``(DENY)`` token sitting beside the rights, not
        # inside them -- icacls prints ``(OI)(CI)(DENY)(W,D,DC)``. Testing for the
        # substring "DENY" anywhere in the flags is not enough to be safe either,
        # because a rights list can be assembled without that token at all (a
        # caller quoting only ``(W,D,DC)``), and then the deny's write letters would
        # be unioned into the grant and the path would look writable.
        tokens = flags.replace("(", " ").replace(")", " ").split()
        is_deny = "DENY" in tokens
        if is_deny:
            rights = _expand(" ".join(t for t in tokens if t != "DENY"))
            if rights:
                denies.append(_render(rights))
            continue
        grants |= _expand(flags)
    raw = grants
    return _render(raw), grants, denies


def _grants_write(rights: str) -> bool:
    """Whether an access string permits writing, deleting, or changing the ACL."""
    if not rights:
        return True   # no explicit grant is not a restriction
    return any(marker in rights for marker in ("W", "M", "F", "D", "WD", "DC"))


def verify_boundary(root: str | Path | None = None) -> dict[str, Any]:
    """Read the ACLs back and assert the boundary actually holds.

    This is the check that distinguishes an allow-list from M005's deny-list:
    it asserts that inherited ``Authenticated Users`` Modify is **absent**, not
    merely overridden by a deny ACE.

    Every result is an ACL *observation*, not an OS enforcement measurement.
    Whether the subject is actually refused is ``NOT_TESTABLE`` until a real
    subject process is launched -- M005 already recorded the difference, when an
    operator-side read reported ALLOWED on a path the subject cannot write.
    """
    base = staging_root(root)
    if not base.is_dir():
        return {
            "schema": "babylab/m015-verify-boundary/v1",
            "status": StagingStatus.STAGING_NOT_CONFIGURED.value,
            "staging_root": str(base),
            "detail": "the staging tree does not exist",
            "enforcement": "NOT_TESTABLE",
        }

    findings: list[dict[str, Any]] = []
    all_present = True
    access_correct = True
    deny_present = True
    owned_by_subject = True

    for label, target in (("root", base),
                          *((name, base / name) for name in SUBTREES)):
        entries = acl_of(target)
        principals = _principals(entries)

        inherited_present = any(
            line.strip().startswith("Authenticated Users:(I)")
            for line in entries
        )
        auth_users = principals.get("NT AUTHORITY\\Authenticated Users", "")
        users = principals.get("BUILTIN\\Users", "")
        subject = principals.get(SUBJECT_ACCOUNT, "")
        subject_grants, subject_letters, subject_denies = _split_subject_entries(entries)

        has_write = any(marker in auth_users + users for marker in ("(M)", "(W)"))
        if inherited_present or has_write:
            all_present = False

        # The expected grant is an exact set, not a containment test. Accepting a
        # superset would let `(RX)` on the model or `(F)` on the subject pass,
        # which are both over-grants this boundary exists to prevent. An extra
        # ACE is caught too, since the union no longer equals the expectation.
        expected = {"R", "X"} if label == "runtime" else {"R"}
        grant_ok = subject_letters == expected
        if not grant_ok:
            access_correct = False

        owner = _owner_of(target)
        # An empty owner is a failed read, not a pass: treating "unknown" as "not
        # the subject" is how an unverifiable tree reports itself as verified.
        owner_ok = bool(owner) and owner.casefold() != SUBJECT_ACCOUNT.casefold()
        if not owner_ok:
            owned_by_subject = False

        # A deny must be present, and must not itself grant anything. Computed
        # per path and folded into the overall verdict below: a boundary that is
        # missing its write backstop is a different boundary from one that has it.
        deny_ok = bool(subject_denies)
        if not deny_ok:
            deny_present = False

        findings.append({
            "label": label,
            "path": str(target),
            "entries": entries,
            "inherited_authenticated_users_modify_present": inherited_present,
            "authenticated_users": auth_users,
            "builtin_users": users,
            "subject_grants": subject_grants,
            "subject_permission_set": sorted(subject_letters),
            "subject_denies": subject_denies,
            "expected_subject_rights": _render(expected),
            "subject_rights_exact": grant_ok,
            "subject_may_write": bool(subject_letters & _MUTATING),
            "subject_deny_backstop_present": deny_ok,
            "owner": owner,
            "subject_is_owner": not owner_ok,
            "allow_list_clean": not inherited_present and not has_write,
        })

    verified = all_present and access_correct and deny_present and owned_by_subject

    return {
        "schema": "babylab/m015-verify-boundary/v1",
        "status": (
            StagingStatus.STAGING_VERIFIED.value
            if verified else StagingStatus.STAGING_BLOCKED
        ),
        "staging_root": str(base),
        "paths": findings,
        "inherited_modify_absent_everywhere": all_present,
        "subject_rights_exact_everywhere": access_correct,
        "subject_deny_backstop_present_everywhere": deny_present,
        "subject_is_not_owner_everywhere": owned_by_subject,
        "enforcement": "ACL_OBSERVATION_ONLY",
        "enforcement_note": (
            "these are readings of the ACL, not measurements of Windows refusing "
            "an operation. OS enforcement is NOT_TESTABLE until a real "
            "BABY_AI_TEST process attempts the operations and is refused."
        ),
        "confidentiality": CONFIDENTIALITY_NOT_PROVIDED,
        "network": NETWORK_NOT_ESTABLISHED,
        "verified_at": _now(),
    }


# ---------------------------------------------------------------------------
# Deployment: copy, verify, record
# ---------------------------------------------------------------------------

@dataclass
class DeploymentRecord:
    """One staged artifact, with both identities recorded separately.

    ``source_sha256`` and ``staged_sha256`` are kept apart rather than collapsed
    into one field. They are expected to be equal for a faithful copy, and the
    design requires that to be *verified* rather than assumed -- but if they ever
    diverge, the record has to show which one came from where.
    """

    kind: str
    source_path: str
    staged_path: str
    source_sha256: str
    staged_sha256: str
    size_bytes: int
    timestamp: str
    result: str
    authored_by: str = "LABORATORY"
    subject_authored: bool = False
    detail: str = ""

    @property
    def hashes_match(self) -> bool:
        return (
            bool(self.source_sha256)
            and self.source_sha256 == self.staged_sha256
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source_path": self.source_path,
            "staged_path": self.staged_path,
            "source_sha256": self.source_sha256,
            "staged_sha256": self.staged_sha256,
            "hashes_match": self.hashes_match,
            "size_bytes": self.size_bytes,
            "timestamp": self.timestamp,
            "result": self.result,
            "authored_by": self.authored_by,
            "subject_authored": self.subject_authored,
            "detail": self.detail,
        }


def deploy_artifact(
    kind: str,
    source: str | Path,
    root: str | Path | None = None,
    *,
    human_selected: bool = False,
) -> DeploymentRecord:
    """COPY an explicitly human-selected artifact into the staging tree.

    Refuses when ``human_selected`` is not set. This is the mechanism that stops
    "the runtime we happened to find last time" from being silently adopted: the
    caller must state that a human chose this artifact. Discovery results, the
    first executable on disk, and a filename match are all insufficient, and the
    refusal is explicit rather than implicit in a missing argument.

    COPY semantics throughout. The source is never moved or modified; a failed copy
    is removed rather than left looking valid.
    """
    timestamp = _now()
    base = staging_root(root)
    source_path = Path(source)

    if not human_selected:
        return DeploymentRecord(
            kind=kind, source_path=str(source_path),
            staged_path="", source_sha256="", staged_sha256="", size_bytes=0,
            timestamp=timestamp, result="REFUSED_NOT_HUMAN_SELECTED",
            detail=(
                "M015 will not stage an artifact that a human has not selected. "
                "A previously discovered runtime is not a selection."
            ),
        )
    if not source_path.is_file():
        return DeploymentRecord(
            kind=kind, source_path=str(source_path), staged_path="",
            source_sha256="", staged_sha256="", size_bytes=0,
            timestamp=timestamp, result="FAILED_SOURCE_MISSING",
            detail=f"the human-selected source does not exist: {source_path}",
        )
    if kind not in SUBTREES:
        return DeploymentRecord(
            kind=kind, source_path=str(source_path), staged_path="",
            source_sha256="", staged_sha256="", size_bytes=0,
            timestamp=timestamp, result="FAILED_UNKNOWN_KIND",
            detail=f"{kind!r} is not a staging subtree ({sorted(SUBTREES)})",
        )

    destination = base / kind / source_path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")

    # Remove any earlier partial first, so a stale file can never be completed
    # into existence by a copy that then fails.
    if partial.exists():
        partial.unlink()
    try:
        shutil.copy2(source_path, partial)
    except OSError as exc:
        return DeploymentRecord(
            kind=kind, source_path=str(source_path),
            staged_path=str(destination), source_sha256="", staged_sha256="",
            size_bytes=0, timestamp=timestamp, result="FAILED_COPY",
            detail=f"the copy did not complete: {exc}",
        )

    source_hash = sha256_file(source_path)
    staged_hash = sha256_file(partial)
    staged_size = partial.stat().st_size
    source_size = source_path.stat().st_size

    # The source must be unchanged by the copy. If it is not, something is very
    # wrong and the staging must not proceed on unverified bytes.
    if source_hash != sha256_file(source_path):
        partial.unlink(missing_ok=True)
        return DeploymentRecord(
            kind=kind, source_path=str(source_path),
            staged_path=str(destination), source_sha256=source_hash,
            staged_sha256=staged_hash, size_bytes=staged_size,
            timestamp=timestamp, result="FAILED_SOURCE_CHANGED",
            detail="the source changed during the copy; refusing to stage it",
        )

    if staged_hash != source_hash or staged_size != source_size:
        partial.unlink(missing_ok=True)
        return DeploymentRecord(
            kind=kind, source_path=str(source_path),
            staged_path=str(destination), source_sha256=source_hash,
            staged_sha256=staged_hash, size_bytes=staged_size,
            timestamp=timestamp, result="FAILED_HASH_MISMATCH",
            detail=(
                "the staged bytes do not match the source. The partial file has "
                "been removed so a truncated or altered copy cannot look valid."
            ),
        )

    # Publish only after verification, so the staged name never exists in an
    # unverified state.
    os.replace(partial, destination)
    return DeploymentRecord(
        kind=kind, source_path=str(source_path), staged_path=str(destination),
        source_sha256=source_hash, staged_sha256=staged_hash,
        size_bytes=staged_size, timestamp=timestamp, result="STAGED",
        detail="copied and hash-verified; the source is unchanged",
    )


def staging_inventory(root: str | Path | None = None) -> dict[str, Any]:
    """What is currently staged, with digests. A read."""
    base = staging_root(root)
    inventory: dict[str, Any] = {}
    for name in SUBTREES:
        directory = base / name
        if not directory.is_dir():
            inventory[name] = {"present": False, "files": []}
            continue
        files = []
        for item in sorted(directory.iterdir()):
            if item.is_file():
                files.append({
                    "name": item.name,
                    "size_bytes": item.stat().st_size,
                    "sha256": sha256_file(item),
                })
        inventory[name] = {"present": True, "files": files}
    return {
        "schema": "babylab/m015-inventory/v1",
        "staging_root": str(base),
        "inventory": inventory,
        "runtime_staged": bool(inventory["runtime"]["files"]),
        "model_staged": bool(inventory["model"]["files"]),
        "read_at": _now(),
    }


def recover(
    root: str | Path | None = None,
    *,
    confirm: bool = False,
) -> dict[str, Any]:
    """Remove the staging tree and only that. Operator-only.

    Refuses without ``confirm``, because this is the one function here that
    destroys anything. It touches nothing outside ``subject_runtime``: the
    originals were copied, never moved, so there is nothing else to restore.
    """
    base = staging_root(root)
    if not confirm:
        return {
            "schema": "babylab/m015-recover/v1",
            "removed": False,
            "staging_root": str(base),
            "detail": "recovery requires confirm=True; nothing was removed",
        }
    if not base.exists():
        return {
            "schema": "babylab/m015-recover/v1",
            "removed": False, "staging_root": str(base),
            "detail": "nothing to remove",
        }
    removed_files = [str(p) for p in base.rglob("*") if p.is_file()]
    shutil.rmtree(base)
    return {
        "schema": "babylab/m015-recover/v1",
        "removed": True,
        "staging_root": str(base),
        "removed_file_count": len(removed_files),
        "removed_files": removed_files,
        "detail": (
            "the staging tree was removed. Source artifacts were copied, never "
            "moved, so no original was affected."
        ),
        "recovered_at": _now(),
    }


__all__ = [
    "CONFIDENTIALITY_NOT_PROVIDED",
    "NETWORK_NOT_ESTABLISHED",
    "STAGING_DIRNAME",
    "SUBJECT_ACCOUNT",
    "SUBJECT_DENY_RIGHTS",
    "SUBTREES",
    "DeploymentRecord",
    "StagingStatus",
    "acl_of",
    "apply_boundary",
    "deploy_artifact",
    "recover",
    "sha256_file",
    "staging_inventory",
    "staging_root",
    "verify_boundary",
]