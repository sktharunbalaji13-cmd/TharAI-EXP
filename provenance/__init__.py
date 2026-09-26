"""Provenance: tamper-evident, externally-attributed research history.

Milestone 001 delivers the data model and the integrity mechanism only. No
self-modifying agent exists, and none is simulated.

The load-bearing idea: **authorship is derived from key material held in
``human_control/``, never from a field inside the record.**
"""

from provenance.keyring import KeyEntry, Keyring
from provenance.ledger import (
    GENESIS_HASH,
    SIGNED_FIELDS,
    UNTRUSTED_METADATA_KEYS,
    Action,
    LedgerEntry,
    LedgerReport,
    ProvenanceLedger,
    StoredEntry,
)
from provenance.recorder import ABSENT_SHA256, FileState, ProvenanceRecorder

__all__ = [
    "Action",
    "Keyring",
    "KeyEntry",
    "LedgerEntry",
    "LedgerReport",
    "ProvenanceLedger",
    "ProvenanceRecorder",
    "StoredEntry",
    "FileState",
    "ABSENT_SHA256",
    "GENESIS_HASH",
    "SIGNED_FIELDS",
    "UNTRUSTED_METADATA_KEYS",
]
