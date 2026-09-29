"""Snapshots, restore, and branch lineage.

Restoring does not rewind
-------------------------
A restore starts a **new branch**. The original event stream is neither
truncated nor edited: the events that led to the snapshot stay exactly where
they were, and restoring appends a ``snapshot_restored`` event that begins a new
lineage. This is the only design in which "replay diverged, go back and try
something else" does not destroy the evidence that the first attempt happened --
which, in a developmental experiment, is exactly the evidence that matters.

Integrity
---------
A snapshot carries the state it was taken from *and* the hash of that state. A
snapshot whose recorded state does not hash to its recorded value is corrupt and
:meth:`Snapshot.verify` says so. Because a corrupt snapshot could otherwise be
restored into a state that never existed, :meth:`Environment.restore` refuses
one rather than loading it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from babylab.hashing import canonical_bytes, sha256_hex
from environment.identity import EnvironmentIdentity
from environment.state import EnvironmentState


@dataclass(frozen=True)
class Snapshot:
    """A verifiable point-in-time capture of an environment."""

    snapshot_id: str
    environment_id: str
    implementation_version: str
    configuration_hash: str
    state_version: int
    state_hash: str
    state: dict[str, Any]
    created_at: str
    parent_snapshot_id: str | None = None
    branch_id: str = "main"
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "environment_id": self.environment_id,
            "implementation_version": self.implementation_version,
            "configuration_hash": self.configuration_hash,
            "state_version": self.state_version,
            "state_hash": self.state_hash,
            "state": self.state,
            "created_at": self.created_at,
            "parent_snapshot_id": self.parent_snapshot_id,
            "branch_id": self.branch_id,
            "label": self.label,
        }

    def verify(self) -> tuple[bool, str]:
        """Whether the embedded state still hashes to the recorded value."""
        rebuilt = EnvironmentState.from_dict(self.state)
        actual = rebuilt.state_hash
        if actual != self.state_hash:
            return False, (
                f"snapshot {self.snapshot_id} is corrupt: its state hashes to "
                f"{actual}, but the snapshot records {self.state_hash}"
            )
        if rebuilt.state_version != self.state_version:
            return False, (
                f"snapshot {self.snapshot_id} records state_version "
                f"{self.state_version} but its state says {rebuilt.state_version}"
            )
        return True, "intact"

    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.to_dict()))


def take_snapshot(
    identity: EnvironmentIdentity,
    state: EnvironmentState,
    created_at: str,
    parent_snapshot_id: str | None = None,
    branch_id: str = "main",
    label: str = "",
    snapshot_id: str | None = None,
) -> Snapshot:
    """Capture a state, verifying it as it is captured."""
    snapshot = Snapshot(
        snapshot_id=snapshot_id or f"snap-{uuid.uuid4().hex[:16]}",
        environment_id=identity.environment_id,
        implementation_version=identity.implementation_version,
        configuration_hash=identity.configuration_hash,
        state_version=state.state_version,
        state_hash=state.state_hash,
        state=state.to_dict(),
        created_at=created_at,
        parent_snapshot_id=parent_snapshot_id,
        branch_id=branch_id,
        label=label,
    )
    intact, detail = snapshot.verify()
    if not intact:  # pragma: no cover - would mean a bug in to_dict/from_dict
        raise ValueError(f"a freshly captured snapshot failed its own check: {detail}")
    return snapshot


@dataclass(frozen=True)
class Branch:
    """One line of execution, with its lineage back to the root."""

    branch_id: str
    parent_branch_id: str | None
    root_snapshot_id: str | None
    created_at: str
    state_version: int = 0

    def lineage(self, registry: dict[str, "Branch"]) -> tuple[str, ...]:
        """Walk back to the root, oldest first."""
        chain: list[str] = []
        current: Branch | None = self
        while current is not None:
            chain.append(current.branch_id)
            current = (registry.get(current.parent_branch_id)
                       if current.parent_branch_id else None)
        return tuple(reversed(chain))

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "parent_branch_id": self.parent_branch_id,
            "root_snapshot_id": self.root_snapshot_id,
            "created_at": self.created_at,
            "state_version": self.state_version,
        }


__all__ = ["Branch", "Snapshot", "take_snapshot"]
