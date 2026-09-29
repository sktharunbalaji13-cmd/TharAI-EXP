"""Subject state: minimal, versioned, and honest about what is not there.

What is in the state
--------------------
Identity reference, lifecycle, counters, hashes. Everything a laboratory needs
to keep track of one subject record, and nothing it does not yet have.

What is not in the state, on purpose
-------------------------------------
There is no ``memories`` list, no ``skills``, no ``knowledge``, no
``personality``, no ``goals``, no ``emotions``, no curiosity counter. An empty
list would imply a system that exists and is merely empty; a missing field
would imply one that was forgotten. Instead, unimplemented capabilities are
represented as **structurally unavailable** in :data:`UNIMPLEMENTED_CAPABILITIES`
-- a named absence that a future milestone must deliberately remove, rather
than an accidental one that could be filled in by habit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from babylab.hashing import canonical_bytes, sha256_hex
from subject.lifecycle import LifecycleState

#: Schema version for every state this module builds.
SUBJECT_STATE_SCHEMA = "babylab/subject-state/v1"

#: Capabilities that do not exist yet. Named explicitly so that using one is a
#: deliberate, reviewable act, and so that no caller can mistake an absence for
#: an empty store.
UNIMPLEMENTED_CAPABILITIES: dict[str, str] = {
    "semantic_memory": "UNAVAILABLE - no memory system exists",
    "episodic_recall": "UNAVAILABLE - no memory system exists",
    "skill_store": "UNAVAILABLE - no learning system exists",
    "goal_state": "UNAVAILABLE - no goal mechanism exists",
    "motivation": "UNAVAILABLE - no motivation mechanism exists",
    "curiosity": "UNAVAILABLE - no curiosity mechanism exists",
    "personality": "UNAVAILABLE - no personality mechanism exists",
    "emotional_state": "UNAVAILABLE - no emotional mechanism exists",
    "self_modification": "UNAVAILABLE - no self-modification capability exists",
    "tool_registry": "UNAVAILABLE - no tool system exists",
}


@dataclass(frozen=True)
class SubjectState:
    """The laboratory's record of one subject, at one version."""

    subject_id: str
    schema_version: str = SUBJECT_STATE_SCHEMA
    state_version: int = 0
    lifecycle: LifecycleState = LifecycleState.UNCREATED
    experience_count: int = 0
    #: Hash of the most recent experience, or 64 zeros when there is none.
    experience_head_hash: str = "0" * 64
    identity_hash: str = ""
    creation_record_hash: str = ""
    capabilities: dict[str, str] = field(
        default_factory=lambda: dict(UNIMPLEMENTED_CAPABILITIES))

    def __post_init__(self) -> None:
        if not self.subject_id:
            raise ValueError("subject_id must be non-empty")
        if self.schema_version != SUBJECT_STATE_SCHEMA:
            raise ValueError(
                f"expected schema {SUBJECT_STATE_SCHEMA}, got {self.schema_version!r}")
        if self.state_version < 0:
            raise ValueError("state_version must be >= 0")
        if self.experience_count < 0:
            raise ValueError("experience_count must be >= 0")
        object.__setattr__(self, "capabilities", dict(self.capabilities))

    @property
    def state_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.to_dict()))

    def advanced(self, *, experience_hash: str,
                 lifecycle: LifecycleState | None = None) -> "SubjectState":
        """A new state with one experience recorded. Never mutates in place."""
        from dataclasses import replace

        return replace(
            self,
            state_version=self.state_version + 1,
            experience_count=self.experience_count + 1,
            experience_head_hash=experience_hash,
            lifecycle=(lifecycle if lifecycle is not None else self.lifecycle),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "schema_version": self.schema_version,
            "state_version": self.state_version,
            "lifecycle": self.lifecycle.value,
            "experience_count": self.experience_count,
            "experience_head_hash": self.experience_head_hash,
            "identity_hash": self.identity_hash,
            "creation_record_hash": self.creation_record_hash,
            "capabilities": dict(sorted(self.capabilities.items())),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SubjectState":
        return cls(
            subject_id=payload["subject_id"],
            schema_version=payload.get("schema_version", SUBJECT_STATE_SCHEMA),
            state_version=payload.get("state_version", 0),
            lifecycle=LifecycleState(payload.get("lifecycle", "UNCREATED")),
            experience_count=payload.get("experience_count", 0),
            experience_head_hash=payload.get("experience_head_hash", "0" * 64),
            identity_hash=payload.get("identity_hash", ""),
            creation_record_hash=payload.get("creation_record_hash", ""),
            capabilities=dict(payload.get("capabilities", UNIMPLEMENTED_CAPABILITIES)),
        )


__all__ = [
    "SUBJECT_STATE_SCHEMA",
    "UNIMPLEMENTED_CAPABILITIES",
    "SubjectState",
]
