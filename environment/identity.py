"""Externally generated environment identity.

The rule
--------
**An environment does not get to declare who it is.** Its identity is computed by
the laboratory from the configuration that produced it, and that configuration is
supplied from outside. If an environment could name itself, a substituted
environment could pass itself off as the one the research record describes, and
every result attributed to the original would be quietly wrong.

So :class:`EnvironmentIdentity` is derived, not declared. It carries the
configuration hash, the implementation version, and the creation time, and it is
the value the event stream and provenance records are written against.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from babylab.hashing import canonical_bytes, sha256_hex


@dataclass(frozen=True)
class EnvironmentIdentity:
    """Who this environment is, as determined from outside it."""

    environment_id: str
    environment_type: str
    implementation_version: str
    configuration_hash: str
    created_at: str
    declared_by: str
    config: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "environment_id": self.environment_id,
            "environment_type": self.environment_type,
            "implementation_version": self.implementation_version,
            "configuration_hash": self.configuration_hash,
            "created_at": self.created_at,
            "declared_by": self.declared_by,
        }

    def short(self) -> str:
        return f"{self.environment_type}@{self.implementation_version}:{self.environment_id[:8]}"


def configuration_hash(config: dict[str, Any]) -> str:
    """Hash of the exact configuration that produced an environment.

    Key order does not matter (the encoding is canonical) but any value change
    does, so two environments that behave differently cannot share a hash.
    """
    return sha256_hex(canonical_bytes(config))


def derive_identity(
    config: dict[str, Any],
    created_at: str,
    declared_by: str,
    environment_id: str | None = None,
) -> EnvironmentIdentity:
    """Build an identity from outside the environment.

    ``environment_id`` is a fresh random identifier by default. It is
    *generated* rather than derived from the configuration so that two
    identically configured environments remain distinguishable instances -- the
    configuration hash says they are the same *kind* of thing, and the id says
    they are different *things*.
    """
    return EnvironmentIdentity(
        environment_id=environment_id or f"env-{uuid.uuid4().hex[:16]}",
        environment_type=str(config.get("type", "unspecified")),
        implementation_version=str(config.get("implementation_version", "0")),
        configuration_hash=configuration_hash(config),
        created_at=created_at,
        declared_by=declared_by,
        config=dict(config),
    )


def verify_configuration(identity: EnvironmentIdentity, config: dict[str, Any]) -> bool:
    """Whether a supplied configuration still matches the recorded identity."""
    return identity.configuration_hash == configuration_hash(config)


__all__ = [
    "EnvironmentIdentity",
    "configuration_hash",
    "derive_identity",
    "verify_configuration",
]
