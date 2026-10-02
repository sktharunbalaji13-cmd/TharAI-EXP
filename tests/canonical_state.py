"""Canonical production-state fingerprint recipe. READ-ONLY.

Why this module exists
----------------------
M017 finding **G6**: a fingerprint value recorded only in prose, with no stored
artifact and no recorded *recipe*, is not reproducible. During M017's own
close-out an ad-hoc fingerprint omitted one field and produced
``0fb72590...`` against a recorded ``70055d54...`` -- which reads as "production
changed" when it had not. The mismatch was a recipe difference, not a state
change.

So the recipe is now **code**, versioned, with its field list and serialisation
stated, and a test asserting the version and field list. A fingerprint produced
elsewhere is comparable only if it carries the same ``RECIPE_ID`` **and** the same
field list. Comparing across recipe versions is a category error and this module
refuses to pretend otherwise by always reporting which recipe produced a value.

Read-only by construction
-------------------------
The only external commands used are an ``icacls`` **listing** and a
``Get-Acl`` read. Every argv is built here from a fixed template and then
checked: any icacls flag that can mutate a descriptor is rejected before the
process is launched, so this module cannot become a mutation path by accident or
by a future edit. ``test_canonical_state.py`` asserts both properties.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from tests.path_policy import read_production_for_verification

__all__ = [
    "CANONICAL_RECIPE_ID",
    "CANONICAL_RECIPE_FIELDS",
    "CANONICAL_RECIPE_V2_ID",
    "CANONICAL_RECIPE_V2_FIELDS",
    "RECIPES",
    "ICACLS_MUTATING_FLAGS",
    "production_state",
    "fingerprint_of",
]

#: Bump when the field list or serialisation changes. A fingerprint from a
#: different id is NOT comparable, full stop.
CANONICAL_RECIPE_ID = "babylab/production-acl-fingerprint/v1"

#: The complete per-path record, in serialisation order. Changing this list
#: changes the fingerprint and requires a new RECIPE_ID.
CANONICAL_RECIPE_FIELDS = (
    "relative_path",     # posix, relative to subject_runtime; "." for the root
    "path_type",         # "dir" | "file"
    "exists",
    "access_sddl",       # AccessControlSections::Access only, NOT owner/audit
    "access_rules_protected",
)

#: v2 adds ownership. Added by M019 because T carries an ownership invariant and
#: v1 cannot express it -- the recorded restoration candidate R has no owner field
#: at all, so C5 was unverifiable from R by construction.
#:
#: v1 is NOT modified and NOT deprecated. Its default and its values are unchanged;
#: a golden-value test asserts a fixed v1 input still hashes to the value it
#: produced before v2 existed, which is the only way to prove the addition was not
#: silent.
CANONICAL_RECIPE_V2_ID = "babylab/production-acl-fingerprint/v2"
CANONICAL_RECIPE_V2_FIELDS = CANONICAL_RECIPE_FIELDS + ("owner", "owner_sid")

RECIPES = {
    CANONICAL_RECIPE_ID: CANONICAL_RECIPE_FIELDS,
    CANONICAL_RECIPE_V2_ID: CANONICAL_RECIPE_V2_FIELDS,
}

#: icacls switches that can change a descriptor, an owner, or the filesystem.
#: Asserted absent from every argv this module builds. A listing is ``icacls
#: <path>`` with no switch at all.
ICACLS_MUTATING_FLAGS = frozenset({
    "/grant", "/grant:r", "/deny", "/deny:r", "/remove", "/remove:g", "/remove:d",
    "/remove:u", "/inheritance", "/inheritance:r", "/inheritance:d", "/inheritance:e",
    "/setowner", "/setintegritylevel", "/reset", "/save", "/restore", "/delete",
    "/c", "/t", "/f", "/q",
})

_ACCESS = "[System.Security.AccessControl.AccessControlSections]::Access"


def _run(argv: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a read-only command. Refuses any argv that could mutate.

    The check is here rather than at the call sites because a call site that
    "obviously" cannot mutate is exactly the assumption that eventually does not
    hold. ``shell=False`` and a closed stdin per the project's standing rule.
    """
    if argv and Path(argv[0]).name.lower().startswith("icacls"):
        for flag in ICACLS_MUTATING_FLAGS:
            assert flag not in argv, f"refusing a mutating icacls switch: {flag}"
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          shell=False, stdin=subprocess.DEVNULL,
                          encoding="utf-8", errors="replace")


def _access_sddl(path: Path) -> str:
    """The DACL, in SDDL form. Read-only, Access section only."""
    result = _run([
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        f"(Get-Acl -LiteralPath {subprocess.list2cmdline([str(path)])})."
        f"GetSecurityDescriptorSddlForm({_ACCESS})",
    ])
    return (result.stdout or "").strip()


def _is_protected(path: Path) -> bool:
    result = _run([
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        f"(Get-Acl -LiteralPath {subprocess.list2cmdline([str(path)])})."
        "AreAccessRulesProtected",
    ])
    return (result.stdout or "").strip().lower() == "true"


def _owner(path: Path) -> tuple[str, str]:
    """Owner name and owner SID.

    Ownership is observed, never inferred. It is a separate capability from the
    DACL: an owner may rewrite the DACL regardless of what the DACL grants, so a
    tree the subject owns is a tree the subject can unlock, and a deny on
    ``WRITE_DAC`` does not prevent it -- taking ownership is a different right.

    An unresolvable owner is reported as ``UNRESOLVED`` rather than guessed.
    Treating "unknown" as "not the subject" is how an unverifiable tree reports
    itself as verified.
    """
    result = _run([
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        f"(Get-Acl -LiteralPath {subprocess.list2cmdline([str(path)])}).Owner",
    ])
    name = (result.stdout or "").strip() or "UNRESOLVED"
    sid = "UNRESOLVED"
    try:
        account = _run([
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            f"(New-Object System.Security.Principal.NTAccount"
            f"({subprocess.list2cmdline([name])})).Translate"
            f"([System.Security.Principal.SecurityIdentifier]).Value",
        ])
        sid = (account.stdout or "").strip() or "UNRESOLVED"
    except Exception:                                          # noqa: BLE001
        sid = "UNRESOLVED"
    return name, sid


def _enumerate(base: Path) -> list[Path]:
    """The root and every descendant, deterministically ordered.

    Sorted by the case-folded relative path so the order does not depend on
    filesystem enumeration order -- an unstable order would make the fingerprint
    unstable while the state was unchanged.
    """
    if not base.exists():
        return []
    found = [base, *base.rglob("*")]
    return sorted(found, key=lambda p: str(p.relative_to(base)).casefold())


def production_state(staging_root: str | Path, *,
                     recipe: str = CANONICAL_RECIPE_ID) -> dict[str, Any]:
    """Read-only canonical fingerprint of a staging tree.

    ``staging_root`` may be production: production **reads** are permitted by
    policy, and this function performs none other. It writes nothing, launches
    nothing that mutates, and never creates or deletes a path.

    ``recipe`` selects the field set. It defaults to v1 so that adding v2 cannot
    silently change what an existing call produces.
    """
    fields = RECIPES[recipe]
    base = read_production_for_verification(staging_root)
    entries: list[dict[str, Any]] = []
    for path in _enumerate(base):
        record: dict[str, Any] = {
            "relative_path": str(path.relative_to(base)).replace("\\", "/") or ".",
            "path_type": "dir" if path.is_dir() else "file",
            "exists": path.exists(),
            "access_sddl": _access_sddl(path),
            "access_rules_protected": _is_protected(path),
        }
        if "owner" in fields:
            owner, owner_sid = _owner(path)
            record["owner"] = owner
            record["owner_sid"] = owner_sid
        entries.append(record)

    state = {
        "recipe_id": recipe,
        "recipe_fields": list(fields),
        "staging_root": str(base),
        "path_count": len(entries),
        "paths": entries,
    }
    state["fingerprint"] = fingerprint_of(entries, fields)
    return state


def fingerprint_of(entries: list[dict[str, Any]],
                   fields: tuple[str, ...] = CANONICAL_RECIPE_FIELDS) -> str:
    """SHA-256 over the canonical serialisation of the per-path records.

    One ``|``-joined, newline-separated line per path, fields in recipe order.
    Booleans serialise as ``true``/``false`` so the encoding is unambiguous. The
    recipe id is hashed in as a prefix line, so a value produced under a different
    recipe can never collide with one produced here.

    ``fields`` defaults to the v1 field set, so an existing caller that does not
    pass it keeps producing v1 values.
    """
    from tests.canonical_state import RECIPES  # local: avoid a cycle at import

    recipe_id = next((rid for rid, flds in RECIPES.items() if flds == fields),
                     "babylab/production-acl-fingerprint/unregistered")
    lines = [recipe_id]
    for entry in entries:
        lines.append("|".join(_serialise(entry[name]) for name in fields))
    payload = "\n".join(lines).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _serialise(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def dump(state: dict[str, Any], path: str | Path) -> None:
    """Write a state record as JSON. Writes only to the given output path.

    Refuses to write inside the repository, because an evidence artifact that
    lands in production is indistinguishable from production content.
    """
    from tests.path_policy import assert_test_write_path

    target = assert_test_write_path(path, what="canonical state output")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(state, indent=2, sort_keys=False), encoding="utf-8")