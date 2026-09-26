"""Canonical serialisation and content hashing.

Two rules, applied everywhere in this project:

1. Anything that is hashed or signed is first serialised with
   :func:`canonical_bytes`. Canonical form is deterministic: the same logical
   value always produces the same bytes, independent of dict insertion order,
   whitespace, or platform.
2. Hashes are always reported with an explicit algorithm name.

Why this matters for the experiment: provenance records must be verifiable
years later, possibly on a different machine, possibly by a different person.
A signature over a non-deterministic serialisation is not reproducible.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

#: Every digest produced by this project names one of these. SHA-256 is
#: provided by the Python standard library (``hashlib``) and is not a custom
#: construction. See docs/provenance.md, section "Primitives Used".
HASH_ALGORITHM = "sha256"

#: Authenticated encryption/signature primitive used for provenance records
#: and control-plane authentication. Standard library (``hmac``), not custom.
MAC_ALGORITHM = "hmac-sha256"


def canonical_json(value: Any) -> str:
    """Return the canonical JSON text form of ``value``.

    Canonical means: keys sorted, no insignificant whitespace, UTF-8 (not
    ``\\uXXXX`` escaping of non-ASCII), and no NaN/Infinity.
    """
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    """Return the canonical UTF-8 encoded JSON bytes of ``value``."""
    return canonical_json(value).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """SHA-256 digest of ``data`` as lowercase hex."""
    return hashlib.sha256(data).hexdigest()


def content_hash(value: Any) -> str:
    """SHA-256 of the canonical JSON encoding of ``value``.

    Used for content-addressed file fingerprints so that "the file did not
    change" reduces to "the fingerprint did not change".
    """
    return sha256_hex(canonical_bytes(value))


def file_sha256(path) -> str:
    """Streaming SHA-256 of a file's bytes, as lowercase hex.

    Streams in chunks so that recording provenance for a large file does not
    require loading it into memory.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
