"""The provenance ledger: an append-only, hash-chained, MAC-signed history.

What it records
---------------
For every protected artifact change: who, when, which path, the content hash
before and after, the previous version of that file, which experiment caused
the change, and why.

How authorship is established
-----------------------------
Each entry names a ``key_id``. The author is then *derived* by
:meth:`provenance.keyring.Keyring.role_of`, which reads the human-owned
keyring. A ``role`` or ``author`` field supplied by the caller is discarded
before the entry is hashed and the discardances are recorded. This is the
mechanism that stops a future Baby AI from writing ``{"author": "HUMAN"}`` and
being believed.

Chain structure
---------------
Two independent links protect the history:

* ``prev_entry_hash`` / ``hash`` - SHA-256 chain over entry content. Catches
  modification, reordering and mid-history deletion.
* ``mac`` - HMAC-SHA256 over the canonical entry body with the author's key.
  Catches modification *and* forgery by a party without key material.

Neither catches truncation of the tail on its own, because the last entry is
simply the last entry. That is what :meth:`ProvenanceLedger.seal` is for: it
writes the current head hash into ``human_control/provenance/`` under the human
key, which is outside the ledger's own write authority.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from babylab.clock import Clock, format_timestamp
from babylab.errors import IntegrityError, ValidationError
from babylab.hashing import canonical_bytes, canonical_json, sha256_hex
from babylab.identity import Actor, Role
from babylab.storage import append_line, atomic_write_text, exclusive_lock
from provenance.keyring import Keyring

GENESIS_HASH = "0" * 64

#: Fields covered by the entry hash and by the MAC, plus metadata. Everything
#: else in an entry line is either derived or excluded by construction.
SIGNED_FIELDS = (
    "entry_id",
    "seq",
    "timestamp",
    "action",
    "path",
    "content_sha256",
    "size_bytes",
    "experiment_id",
    "reason",
    "actor_id",
    "key_id",
    "prev_version_id",
    "prev_entry_hash",
)

#: Caller-supplied metadata keys that are dropped rather than trusted.
UNTRUSTED_METADATA_KEYS = frozenset(
    {"author", "role", "authored_by", "created_by", "user", "owner", "signed_by"}
)


class Action(str, Enum):
    """Kinds of change the ledger can record."""

    CREATE = "CREATE"
    MODIFY = "MODIFY"
    DELETE = "DELETE"
    MOVE = "MOVE"
    DENY = "DENY"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass(frozen=True)
class LedgerEntry:
    """One line of the provenance ledger."""

    entry_id: str
    seq: int
    timestamp: str
    action: Action
    path: str
    content_sha256: str
    size_bytes: int
    experiment_id: str
    reason: str
    actor_id: str
    key_id: str
    prev_version_id: str | None
    prev_entry_hash: str
    hash: str = ""
    mac: str = ""
    author: Role | None = None
    author_basis: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def signed_body(self) -> dict[str, Any]:
        """The exact bytes covered by ``hash`` and ``mac``.

        ``author`` is excluded because it is a *derived* field: including a
        derived value in the signed body would let a record restate its own
        authorship. The signed body names only ``key_id``, and the keyring
        decides what that means.
        """
        body = {name: getattr(self, name) for name in SIGNED_FIELDS}
        body["metadata"] = self.metadata
        return body

    def compute_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.signed_body()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "action": self.action.value,
            "path": self.path,
            "content_sha256": self.content_sha256,
            "size_bytes": self.size_bytes,
            "experiment_id": self.experiment_id,
            "reason": self.reason,
            "actor_id": self.actor_id,
            "key_id": self.key_id,
            "prev_version_id": self.prev_version_id,
            "prev_entry_hash": self.prev_entry_hash,
            "hash": self.hash,
            "mac": self.mac,
            "author": self.author.value if self.author else None,
            "author_basis": self.author_basis,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Any) -> "LedgerEntry":
        if not isinstance(data, dict):
            raise ValidationError("ledger entry must be a JSON object")
        try:
            return cls(
                entry_id=data["entry_id"],
                seq=data["seq"],
                timestamp=data["timestamp"],
                action=Action(data["action"]),
                path=data["path"],
                content_sha256=data["content_sha256"],
                size_bytes=data["size_bytes"],
                experiment_id=data["experiment_id"],
                reason=data["reason"],
                actor_id=data["actor_id"],
                key_id=data["key_id"],
                prev_version_id=data.get("prev_version_id"),
                prev_entry_hash=data["prev_entry_hash"],
                hash=data.get("hash", ""),
                mac=data.get("mac", ""),
                author=Role(data["author"]) if data.get("author") else None,
                author_basis=data.get("author_basis", ""),
                metadata=data.get("metadata", {}) or {},
            )
        except (KeyError, ValueError) as exc:
            raise ValidationError(f"malformed ledger entry: {exc}") from exc

    @classmethod
    def from_json(cls, text: str) -> "LedgerEntry":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"line is not valid JSON: {exc}") from exc
        return cls.from_dict(data)


@dataclass(frozen=True)
class StoredEntry:
    """A ledger line as read back, valid or not."""

    line_number: int
    raw: str
    entry: LedgerEntry | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class LedgerReport:
    """Outcome of :meth:`ProvenanceLedger.verify`."""

    total_lines: int
    valid_entries: int
    malformed_lines: int
    head_hash: str
    head_entry_id: str | None
    problems: list[str]

    @property
    def intact(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict:
        return {
            "intact": self.intact,
            "total_lines": self.total_lines,
            "valid_entries": self.valid_entries,
            "malformed_lines": self.malformed_lines,
            "head_hash": self.head_hash,
            "head_entry_id": self.head_entry_id,
            "problems": list(self.problems),
        }

    def render(self) -> str:
        return canonical_json(self.to_dict())


class ProvenanceLedger:
    """Append-only, hash-chained, MAC-signed provenance history.

    Index caching
    -------------
    Two lookups are needed on every append: the current head (to chain onto)
    and the latest entry for the path being recorded (to link the version
    history). Both are O(n) scans of the file, which makes a long research
    session quadratic.

    Both are therefore cached in memory together with the file size they were
    derived from. Under the append lock an unchanged size means no other writer
    has extended the file, so the caches are still correct; any size change
    forces a full reindex. Verification never uses these caches - it always
    reads from disk - so caching cannot mask tampering.
    """

    def __init__(
        self,
        path: Path,
        keyring: Keyring,
        clock: Clock | None = None,
        seal_dir: Path | None = None,
    ):
        self.path = Path(path)
        self.keyring = keyring
        self.clock = clock or Clock()
        self.seal_dir = (
            Path(seal_dir)
            if seal_dir
            else Path(path).resolve().parent.parent / "human_control" / "provenance"
        )
        self._head_cache: LedgerEntry | None = None
        self._index_cache: dict[str, LedgerEntry] = {}
        self._size_cache: int | None = None

    # -- caching ----------------------------------------------------------
    def _current_size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def _reindex(self) -> None:
        head: LedgerEntry | None = None
        index: dict[str, LedgerEntry] = {}
        for stored in self._iter_lines(0, None):
            if stored.ok and stored.entry is not None:
                head = stored.entry
                index[stored.entry.path] = stored.entry
        self._head_cache = head
        self._index_cache = index
        self._size_cache = self._current_size()

    def _ensure_index(self) -> None:
        if self._size_cache != self._current_size():
            self._reindex()

    def _remember(self, entry: LedgerEntry) -> None:
        self._head_cache = entry
        self._index_cache[entry.path] = entry
        self._size_cache = self._current_size()

    # -- writing ----------------------------------------------------------
    def record(
        self,
        action: Action,
        path: str,
        content_sha256: str,
        size_bytes: int,
        experiment_id: str,
        reason: str,
        actor: Actor,
        prev_version_id: str | None = None,
        metadata: dict | None = None,
    ) -> LedgerEntry:
        """Append one entry, signed by the actor's key.

        ``actor.key_id`` is mandatory. Refusing to write an unsigned entry is
        the point: an unsigned provenance record proves nothing.
        """
        if actor.key_id is None:
            raise ValidationError(
                "provenance entries must be signed; actor "
                f"{actor.actor_id!r} presented no key"
            )
        clean_metadata = {
            key: value
            for key, value in (metadata or {}).items()
            if key not in UNTRUSTED_METADATA_KEYS
        }
        dropped = sorted(set(metadata or {}) & UNTRUSTED_METADATA_KEYS)
        if dropped:
            # Recorded in the entry itself, before hashing, so that a caller
            # trying to assert its own authorship leaves an auditable trace
            # rather than failing silently.
            clean_metadata["dropped_untrusted_fields"] = dropped

        with exclusive_lock(self.path):
            self._ensure_index()
            head = self._head_cache
            seq = (head.seq + 1) if head is not None else 1
            body = LedgerEntry(
                entry_id=f"PROV-{seq:06d}",
                seq=seq,
                timestamp=format_timestamp(self.clock.now()),
                action=Action(action),
                path=path,
                content_sha256=content_sha256,
                size_bytes=int(size_bytes),
                experiment_id=experiment_id,
                reason=reason,
                actor_id=actor.actor_id,
                key_id=actor.key_id,
                prev_version_id=prev_version_id,
                prev_entry_hash=head.hash if head is not None else GENESIS_HASH,
                metadata=clean_metadata,
            )
            encoded = canonical_bytes(body.signed_body())
            hashed = sha256_hex(encoded)
            signed = LedgerEntry(**{**body.__dict__, "hash": hashed})
            mac = self.keyring.sign(actor.key_id, encoded)
            role = self.keyring.role_of(actor.key_id)
            entry = LedgerEntry(
                **{
                    **signed.__dict__,
                    "mac": mac,
                    "author": role,
                    "author_basis": f"keyring:{actor.key_id}",
                }
            )
            append_line(self.path, entry.to_json())
            self._remember(entry)
        return entry

    # -- reading ----------------------------------------------------------
    def read_all(self) -> list[StoredEntry]:
        return list(self._iter_lines(0, None))

    def iter_entries(self) -> Iterator[LedgerEntry]:
        for stored in self._iter_lines(0, None):
            if stored.ok and stored.entry is not None:
                yield stored.entry

    def latest_for_path(self, path: str) -> LedgerEntry | None:
        """Most recent entry touching ``path``. Used for version linkage.

        Served from the index cache, which is invalidated whenever the file
        size changes. Reading from disk every time would make a long session
        quadratic.
        """
        with exclusive_lock(self.path):
            self._ensure_index()
            return self._index_cache.get(path)

    def latest_for_path_uncached(self, path: str) -> LedgerEntry | None:
        """Disk-only lookup. Used by verification, which must not trust caches."""
        found: LedgerEntry | None = None
        for entry in self.iter_entries():
            if entry.path == path:
                found = entry
        return found

    def history_for_path(self, path: str) -> list[LedgerEntry]:
        return [entry for entry in self.iter_entries() if entry.path == path]

    def head(self) -> LedgerEntry | None:
        with exclusive_lock(self.path):
            self._ensure_index()
            return self._head_cache

    def count(self) -> int:
        return sum(1 for _ in self.iter_entries())

    def _iter_lines(self, start_line: int, limit: int | None) -> Iterator[StoredEntry]:
        if not self.path.exists():
            return
        emitted = 0
        with open(self.path, "r", encoding="utf-8", errors="replace") as handle:
            for index, raw in enumerate(handle, start=1):
                if index <= start_line:
                    continue
                yield self._parse_line(index, raw.rstrip("\n"))
                emitted += 1
                if limit is not None and emitted >= limit:
                    return

    @staticmethod
    def _parse_line(line_number: int, raw: str) -> StoredEntry:
        text = raw.strip()
        if not text:
            return StoredEntry(line_number, raw, None, "blank line")
        try:
            return StoredEntry(line_number, raw, LedgerEntry.from_json(text), None)
        except ValidationError as exc:
            return StoredEntry(line_number, raw, None, str(exc))

    # -- verification -----------------------------------------------------
    def verify(self, deep: bool = True) -> LedgerReport:
        """Recompute the chain, verify every MAC, and check authorship.

        Checks performed
        ----------------
        1. Structural validity of each line.
        2. ``hash`` matches the recomputed digest of the entry body
           (detects content modification).
        3. ``mac`` verifies under the named key (detects modification *and*
           forgery with a key the human never registered).
        4. The key named is present and active, and its secret still matches
           the published fingerprint (detects key substitution).
        5. The recorded ``author`` equals the role the keyring derives
           (detects a hand-edited author field).
        6. ``prev_entry_hash`` links correctly and ``seq`` increases by one
           (detects reordering and mid-history deletion).
        7. ``prev_version_id`` for each path refers to the preceding entry for
           that same path (detects a broken or fabricated version history).

        Does **not** detect tail truncation; see :meth:`verify_seal`.
        """
        problems: list[str] = []
        expected_prev = GENESIS_HASH
        expected_seq = 1
        valid = 0
        malformed = 0
        head_hash = GENESIS_HASH
        head_id: str | None = None
        last_by_path: dict[str, LedgerEntry] = {}

        for stored in self._iter_lines(0, None):
            if not stored.ok or stored.entry is None:
                malformed += 1
                problems.append(f"line {stored.line_number}: malformed ({stored.error})")
                continue
            entry = stored.entry
            where = f"line {stored.line_number} ({entry.entry_id})"

            if entry.seq != expected_seq:
                problems.append(
                    f"{where}: sequence {entry.seq} breaks monotonic ordering "
                    f"(expected {expected_seq})"
                )
            if entry.prev_entry_hash != expected_prev:
                problems.append(
                    f"{where}: prev_entry_hash does not match the preceding entry "
                    f"(record removed, reordered, or rewritten)"
                )

            body = canonical_bytes(entry.signed_body())
            recomputed = sha256_hex(body)
            if recomputed != entry.hash:
                problems.append(
                    f"{where}: hash mismatch - entry content was modified after "
                    f"it was written"
                )

            if deep:
                if not self.keyring.verify(entry.key_id, body, entry.mac):
                    problems.append(
                        f"{where}: MAC does not verify under key {entry.key_id!r} - "
                        f"the entry was forged or altered"
                    )
                try:
                    derived = self.keyring.role_of(entry.key_id)
                except IntegrityError as exc:
                    problems.append(f"{where}: {exc}")
                    derived = None
                if (
                    derived is not None
                    and entry.author is not None
                    and derived is not entry.author
                ):
                    problems.append(
                        f"{where}: recorded author {entry.author.value} contradicts "
                        f"the keyring, which derives {derived.value} from key "
                        f"{entry.key_id!r}"
                    )
                try:
                    if not self.keyring.check_fingerprint(entry.key_id):
                        problems.append(
                            f"{where}: key material for {entry.key_id!r} does not "
                            f"match its published fingerprint"
                        )
                except Exception as exc:  # noqa: BLE001 - verification must not crash
                    problems.append(f"{where}: key {entry.key_id!r} unusable ({exc})")

            previous_for_path = last_by_path.get(entry.path)
            if previous_for_path is None:
                if entry.prev_version_id not in (None, ""):
                    problems.append(
                        f"{where}: first entry for {entry.path!r} claims a previous "
                        f"version {entry.prev_version_id!r}"
                    )
            elif entry.prev_version_id != previous_for_path.entry_id:
                problems.append(
                    f"{where}: prev_version_id {entry.prev_version_id!r} does not "
                    f"point at the preceding version of {entry.path!r} "
                    f"({previous_for_path.entry_id})"
                )
            last_by_path[entry.path] = entry

            expected_prev = entry.hash
            expected_seq = entry.seq + 1
            head_hash = entry.hash
            head_id = entry.entry_id
            valid += 1

        return LedgerReport(
            total_lines=valid + malformed,
            valid_entries=valid,
            malformed_lines=malformed,
            head_hash=head_hash,
            head_entry_id=head_id,
            problems=problems,
        )

    def verify_seal(self, seal_path: Path | None = None) -> LedgerReport | None:
        """Compare the current head against the last human-signed seal.

        This is the only check that detects *truncation of the tail*. Without
        it, a party that can write the ledger could delete the final N entries
        and every remaining entry would still verify.
        """
        target = Path(seal_path) if seal_path else self.seal_dir / "HEAD.json"
        if not target.exists():
            return None
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            sealed_hash = data["head_hash"]
            sealed_entry = data.get("head_entry_id")
            sealed_key = data["signing_key_id"]
        except (json.JSONDecodeError, KeyError) as exc:
            return LedgerReport(
                total_lines=0,
                valid_entries=0,
                malformed_lines=0,
                head_hash="",
                head_entry_id=None,
                problems=[f"seal at {target} is unreadable: {exc}"],
            )

        problems: list[str] = []
        body = {
            "head_hash": sealed_hash,
            "head_entry_id": sealed_entry,
            "sealed_at": data.get("sealed_at"),
        }
        if not self.keyring.verify(
            sealed_key, canonical_bytes(body), data.get("seal_mac", "")
        ):
            problems.append(
                f"seal at {target} does not verify under key {sealed_key!r}; the "
                f"seal itself was altered"
            )

        head = self.head()
        if head is None:
            problems.append("ledger is empty but a seal exists")
        elif head.hash != sealed_hash:
            sealed_seq = data.get("head_seq") or 0
            if head.seq < sealed_seq:
                problems.append(
                    f"LEDGER TRUNCATED: sealed head was {sealed_entry} at seq "
                    f"{sealed_seq}, ledger now ends at {head.entry_id} at seq "
                    f"{head.seq}"
                )
            else:
                problems.append(
                    f"ledger head {head.entry_id} does not match sealed head "
                    f"{sealed_entry}; the ledger was altered or re-sealed without "
                    f"the human key"
                )
        return LedgerReport(
            total_lines=0,
            valid_entries=0,
            malformed_lines=0,
            head_hash=head.hash if head else "",
            head_entry_id=head.entry_id if head else None,
            problems=problems,
        )

    # -- sealing ----------------------------------------------------------
    def seal(self, actor: Actor, note: str = "") -> Path:
        """Anchor the current head under a key, in ``human_control/``.

        Run this at the end of a session, and before any maintenance that
        touches the ledger. Doing it regularly is what bounds how much history
        a party could truncate undetected.
        """
        if actor.key_id is None:
            raise ValidationError("sealing requires a signing key")
        head = self.head()
        if head is None:
            raise ValidationError("cannot seal an empty ledger")
        sealed_at = format_timestamp(self.clock.now())
        body = {
            "head_hash": head.hash,
            "head_entry_id": head.entry_id,
            "sealed_at": sealed_at,
        }
        manifest = {
            "schema": "babylab/provenance-seal/v1",
            "sealed_at": sealed_at,
            "head_hash": head.hash,
            "head_entry_id": head.entry_id,
            "head_seq": head.seq,
            "total_entries": head.seq,
            "signing_key_id": actor.key_id,
            "signing_role": self.keyring.role_of(actor.key_id).value,
            "note": note,
            "seal_mac": self.keyring.sign(actor.key_id, canonical_bytes(body)),
        }
        self.seal_dir.mkdir(parents=True, exist_ok=True)
        archive = self.seal_dir / "seals" / f"{head.entry_id}.json"
        atomic_write_text(archive, canonical_json(manifest) + "\n")
        atomic_write_text(self.seal_dir / "HEAD.json", canonical_json(manifest) + "\n")
        return self.seal_dir / "HEAD.json"

    def summary(self) -> dict:
        entries = list(self.iter_entries())
        by_role: dict[str, int] = {}
        by_action: dict[str, int] = {}
        for entry in entries:
            key = entry.author.value if entry.author else "UNATTRIBUTED"
            by_role[key] = by_role.get(key, 0) + 1
            by_action[entry.action.value] = by_action.get(entry.action.value, 0) + 1
        return {
            "path": str(self.path),
            "total_entries": len(entries),
            "by_author": dict(sorted(by_role.items())),
            "by_action": dict(sorted(by_action.items())),
            "distinct_paths": len({entry.path for entry in entries}),
        }

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"ProvenanceLedger({self.path})"
