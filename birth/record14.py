"""The birth record's location and its stable hash.

Extracted from :mod:`birth.m014` so that two very different callers can share
them without one having to import the other. The Observatory's read surface needs
both -- to find a record and to re-derive its hash -- and importing
:mod:`birth.m014` to get them would hand a read-only panel a module that can
execute a ceremony. Splitting the pure functions out keeps that boundary
structural instead of a matter of discipline.

Nothing here executes, mutates, or decides. These are a path and a function over
a dictionary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Where a birth record is written, relative to the repository root. Reported and
#: created on a real birth only; never searched for.
BIRTH_RECORD_RELPATH = "human_control/birth_records/BIRTH.json"


def birth_record_path(root: Any = None) -> Path:
    """The path a birth record occupies. Computed, never searched for."""
    if root is None:
        from babylab.paths import default_paths

        root = default_paths().root
    return Path(root) / BIRTH_RECORD_RELPATH


def compute_birth_record_hash(record: dict[str, Any]) -> str:
    """The stable digest of a birth record, over content and nothing else.

    Sorted keys and no values derived from the moment of hashing, so the same
    birth always hashes the same. A hash that moved because a field was
    reordered, or because the clock ticked during serialisation, would make the
    immutability check meaningless -- it would report drift where none exists and
    a reader would learn to ignore it.
    """
    from babylab.hashing import sha256_hex

    return sha256_hex(
        json.dumps(record, sort_keys=True, default=str).encode("utf-8")
    )


def verify_birth_record_unchanged(
    record: dict[str, Any], expected_hash: str,
) -> dict[str, Any]:
    """Check that a record still hashes to what it did when it was written.

    Covers both directions the milestone asks for: a subject attempting to edit
    the record must be caught, and an accidental operator-side mutation must also
    be caught. They are the same check, and that is the point -- the record
    carries no author-of-last-edit field, because a record that trusted such a
    field would be forgeable by whoever wrote the field.
    """
    observed = compute_birth_record_hash(record)
    return {
        "expected_hash": expected_hash,
        "observed_hash": observed,
        "unchanged": observed == expected_hash,
        "note": (
            "the record carries no author-of-last-edit field, so any change is "
            "detected regardless of who made it"
        ),
    }


__all__ = [
    "BIRTH_RECORD_RELPATH",
    "birth_record_path",
    "compute_birth_record_hash",
    "verify_birth_record_unchanged",
]
