"""Keyring: the root of authorship attribution.

The central problem this solves
-------------------------------
The specification requires distinguishing ``HUMAN``, ``BABY_AI`` and
``SYSTEM``, and forbids determining that from a value the Baby AI itself can
write. So authorship is derived from **which key signed a record**::

    ledger entry --(key_id)--> keyring (in human_control/) --> Role

The keyring lives in ``human_control/security/keys/keyring.json``. The secret
key material lives beside it in ``private/`` and is excluded from version
control. A process without read access to ``human_control/`` cannot register a
key, therefore cannot mint authorship for a role it does not hold.

Deliberate design choices
-------------------------
**HMAC-SHA256, not asymmetric signatures.** The specification asks for
established primitives from standard libraries, and the Python standard
library ships ``hmac`` but no signature algorithm. The cost of that choice is
stated rather than hidden: with a symmetric MAC, *key possession implies the
ability to forge any role's records*. The mitigation is that key material is
protected by the ``human_control/`` ACL, not by the cryptography. An
asymmetric scheme (``Ed25519`` via the third-party ``cryptography`` package)
would let the human verify a Baby AI signature without ever being able to
produce one, which is a strictly better property. This is recorded as an open
architectural decision for the human researcher: see
docs/decisions/ADR-003-authorship-attribution.md.

**Fingerprints, not public keys.** Because HMAC has no public key, the
keyring publishes a *verification tag*: the MAC of a fixed, published
challenge string. It lets a later party confirm "this is the same key" without
learning the key. It does not let them verify a record without the key.
"""

from __future__ import annotations

import base64
import hmac
import secrets
import uuid
from dataclasses import dataclass
from pathlib import Path

from babylab.clock import Clock, format_timestamp
from babylab.errors import ConfigurationError, IntegrityError
from babylab.hashing import MAC_ALGORITHM, canonical_bytes, sha256_hex
from babylab.identity import Actor, Role
from babylab.storage import atomic_write_text

#: Published challenge used to derive a key's non-secret fingerprint.
FINGERPRINT_CHALLENGE = b"babylab/keyring/fingerprint/v1"

KEY_LENGTH_BYTES = 32

_KEY_ID_PREFIX = {
    Role.HUMAN: "HK",
    Role.SYSTEM: "SK",
    Role.BABY_AI: "BAK",
}


@dataclass(frozen=True)
class KeyEntry:
    """Non-secret metadata about one signing key."""

    key_id: str
    role: Role
    actor_id: str
    algorithm: str
    fingerprint: str
    created: str
    state: str = "active"
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "key_id": self.key_id,
            "role": self.role.value,
            "actor_id": self.actor_id,
            "algorithm": self.algorithm,
            "fingerprint": self.fingerprint,
            "created": self.created,
            "state": self.state,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KeyEntry":
        try:
            return cls(
                key_id=data["key_id"],
                role=Role(data["role"]),
                actor_id=data["actor_id"],
                algorithm=data["algorithm"],
                fingerprint=data["fingerprint"],
                created=data["created"],
                state=data.get("state", "active"),
                note=data.get("note", ""),
            )
        except (KeyError, ValueError) as exc:
            raise ConfigurationError(f"malformed keyring entry: {exc}") from exc


class Keyring:
    """Registry of signing keys and the authority to attribute authorship."""

    def __init__(self, public_path: Path, private_dir: Path, clock: Clock | None = None):
        self.public_path = Path(public_path)
        self.private_dir = Path(private_dir)
        self.clock = clock or Clock()
        self._entries: dict[str, KeyEntry] = {}
        self._loaded = False

    # -- persistence ------------------------------------------------------
    def load(self) -> "Keyring":
        if not self.public_path.exists():
            raise ConfigurationError(
                f"keyring not found at {self.public_path}. "
                f"Run scripts/bootstrap.ps1 or 'python -m babylab.bootstrap' first."
            )
        import json

        try:
            data = json.loads(self.public_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"keyring is not valid JSON: {exc}") from exc
        entries = data.get("keys", [])
        self._entries = {entry["key_id"]: KeyEntry.from_dict(entry) for entry in entries}
        self._loaded = True
        return self

    def save(self) -> None:
        from babylab.hashing import canonical_json

        payload = {
            "schema": "babylab/keyring/v1",
            "algorithm": MAC_ALGORITHM,
            "note": (
                "Public keyring metadata only. Secret key material is stored in "
                "private/ and is excluded from version control. The presence of "
                "this file inside human_control/ is what makes role attribution "
                "meaningful."
            ),
            "keys": [entry.to_dict() for entry in self._entries.values()],
        }
        atomic_write_text(self.public_path, canonical_json(payload) + "\n")

    def _require_loaded(self) -> None:
        if not self._loaded:
            self.load()

    # -- registration -----------------------------------------------------
    def register(
        self,
        role: Role,
        actor_id: str,
        note: str = "",
        key_id: str | None = None,
    ) -> KeyEntry:
        """Create a new key for ``role`` and persist key material.

        Only the human operator performs registration. There is no code path
        that lets a caller self-register a role at signing time.
        """
        self._require_loaded()
        identifier = key_id or self._mint_key_id(role)
        if identifier in self._entries:
            raise ConfigurationError(f"key {identifier!r} already registered")
        secret = secrets.token_bytes(KEY_LENGTH_BYTES)
        self._write_secret(identifier, secret)
        entry = KeyEntry(
            key_id=identifier,
            role=role,
            actor_id=actor_id,
            algorithm=MAC_ALGORITHM,
            fingerprint=self.fingerprint_for(secret),
            created=format_timestamp(self.clock.now()),
            note=note,
        )
        self._entries[identifier] = entry
        self.save()
        return entry

    def _mint_key_id(self, role: Role) -> str:
        prefix = _KEY_ID_PREFIX[role]
        while True:
            candidate = f"{prefix}-{uuid.uuid4().hex[:12]}"
            if candidate not in self._entries:
                return candidate

    def _secret_path(self, key_id: str) -> Path:
        # Reject any key id that could escape the private directory.
        if not key_id or "/" in key_id or "\\" in key_id or key_id.startswith("."):
            raise ConfigurationError(f"illegal key id {key_id!r}")
        return self.private_dir / f"{key_id}.key"

    def _write_secret(self, key_id: str, secret: bytes) -> None:
        path = self._secret_path(key_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, base64.b64encode(secret).decode("ascii"))

    # -- secret access ----------------------------------------------------
    def secret(self, key_id: str) -> bytes:
        self._require_loaded()
        path = self._secret_path(key_id)
        if not path.exists():
            raise ConfigurationError(f"no secret material for key {key_id!r}")
        return base64.b64decode(path.read_text(encoding="ascii").strip())

    @staticmethod
    def fingerprint_for(secret: bytes) -> str:
        return hmac.new(secret, FINGERPRINT_CHALLENGE, "sha256").hexdigest()

    # -- the attribution rule --------------------------------------------
    def role_of(self, key_id: str) -> Role:
        """The authoritative authorship role for a key.

        This is the only function in the project permitted to answer "who wrote
        this". It reads the human-owned keyring, never the record.
        """
        self._require_loaded()
        entry = self._entries.get(key_id)
        if entry is None:
            raise IntegrityError(
                f"key {key_id!r} is not in the keyring; authorship cannot be "
                f"attributed. A record signed by an unregistered key is not "
                f"trustworthy evidence of anything."
            )
        if entry.state != "active":
            raise IntegrityError(
                f"key {key_id!r} is in state {entry.state!r} and may not sign"
            )
        return entry.role

    def actor_of(self, key_id: str) -> Actor:
        self._require_loaded()
        entry = self._entries[key_id]
        return Actor(
            role=entry.role,
            actor_id=entry.actor_id,
            key_id=key_id,
            basis="keyring-key",
        )

    def key_for_role(self, role: Role) -> KeyEntry:
        self._require_loaded()
        for entry in self._entries.values():
            if entry.role is role and entry.state == "active":
                return entry
        raise ConfigurationError(f"no active key registered for role {role.value}")

    def has_role(self, role: Role) -> bool:
        self._require_loaded()
        return any(
            entry.role is role and entry.state == "active"
            for entry in self._entries.values()
        )

    def entries(self) -> list[KeyEntry]:
        self._require_loaded()
        return sorted(self._entries.values(), key=lambda item: item.key_id)

    # -- signing ----------------------------------------------------------
    def sign(self, key_id: str, message: bytes) -> str:
        return hmac.new(self.secret(key_id), message, "sha256").hexdigest()

    def verify(self, key_id: str, message: bytes, signature: str) -> bool:
        """Constant-time verification. Never raises on a wrong signature."""
        try:
            expected = self.sign(key_id, message)
        except ConfigurationError:
            return False
        return hmac.compare_digest(expected, signature)

    def check_fingerprint(self, key_id: str) -> bool:
        """Confirm stored key material still matches the published fingerprint.

        Guards against a silent swap of the secret file: an attacker who
        replaced the key would otherwise produce records that verify against
        the keyring while not being signed by the original key.
        """
        self._require_loaded()
        entry = self._entries[key_id]
        return hmac.compare_digest(
            self.fingerprint_for(self.secret(key_id)), entry.fingerprint
        )

    def audit(self) -> list[str]:
        """Problems found in the keyring. Empty list means healthy."""
        self._require_loaded()
        problems: list[str] = []
        for entry in self.entries():
            path = self._secret_path(entry.key_id)
            if not path.exists():
                problems.append(f"{entry.key_id}: secret material missing at {path}")
                continue
            try:
                if not self.check_fingerprint(entry.key_id):
                    problems.append(
                        f"{entry.key_id}: secret material does not match the "
                        f"published fingerprint (key material was replaced)"
                    )
            except Exception as exc:  # noqa: BLE001 - audit must not crash
                problems.append(f"{entry.key_id}: unreadable ({exc})")
        for role in (Role.HUMAN, Role.SYSTEM):
            if not self.has_role(role):
                problems.append(f"no active key for required role {role.value}")
        return problems

    def commitment(self) -> str:
        """Digest of all public keyring metadata, for the baseline record."""
        from babylab.hashing import canonical_json

        return sha256_hex(
            canonical_bytes({"keys": [entry.to_dict() for entry in self.entries()]})
        )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Keyring({self.public_path}, keys={len(self._entries)})"
