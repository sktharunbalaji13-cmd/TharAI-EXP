"""Experience records: what crossed the subject/environment boundary.

What an experience is
---------------------
A record of one interaction that crossed the boundary between a subject and an
environment: an observation received, an action proposed, the environment's
verdict, and the consequence. Everything it names is a *reference* -- an
observation id and hash, an action id, a consequence digest -- plus the two
subject-state hashes the interaction links. References, not copies: the
environment's own records stay the authoritative source for what happened there,
and the experience links to them rather than re-stating them.

References, not copies, for a reason
-------------------------------------
If the experience embedded the full observation, two copies of the same fact
could disagree, and the question "which one is authoritative?" would have no
structural answer. With references there is exactly one place each fact lives,
and disagreement shows up as a hash mismatch rather than a quiet duplication.

What an experience is not
-------------------------
It is not a memory. It is not learning. A sequence of experiences is a history,
and reading a history is not the same thing as remembering. M008 builds the
history; retrieval, consolidation and everything that would make it *memory*
are separate milestones with separate reviews.

T_birth
-------
The first-experience boundary: before ``T_birth`` there is no subject and no
experience. Creation records the identity and the schema, and at that moment
the experience count is zero -- asserted in the creation itself, so a record
that appeared with a nonzero count would be internally inconsistent. The first
*experience* is produced by the first controlled interaction, not by creation.
No historical experiences may exist, because there was no subject for them to
belong to. The pretrained model's prior knowledge does not become experience by
being attached; it stays ``INHERITED_PRETRAINED``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from babylab.hashing import canonical_bytes, sha256_hex
from subject.provenance import Origin


@dataclass(frozen=True)
class Experience:
    """One recorded interaction across the subject/environment boundary."""

    experience_id: str
    subject_id: str
    environment_id: str
    sequence_number: int
    created_at: str
    observation_id: str
    observation_hash: str
    action_id: str
    action_operation: str
    action_validation: str
    consequence: str
    consequence_digest: str
    environment_state_hash: str
    environment_state_version: int
    prior_subject_state_hash: str
    resulting_subject_state_hash: str
    provenance_reference: str
    #: What the experience's own content is classified as.
    origin: Origin = Origin.DERIVED

    def __post_init__(self) -> None:
        if not self.experience_id:
            raise ValueError("experience_id must be non-empty")
        if self.sequence_number < 1:
            raise ValueError("sequence numbers start at 1; there is no zeroth experience")
        # Coerce a string origin so that records rebuilt from dictionaries
        # (which carry "DERIVED" rather than Origin.DERIVED) behave identically
        # to records built directly. Without this, two equal records hash
        # differently depending on how they were constructed.
        if isinstance(self.origin, str):
            object.__setattr__(self, "origin", Origin(self.origin))

    @property
    def content_hash(self) -> str:
        """Hash of the stable content.

        Excludes ``resulting_subject_state_hash`` (unknowable before the state
        exists -- see above) **and** ``observation_id``. The id is a random
        uniqueifier assigned by the environment; the ``observation_hash`` beside
        it is what the observation *was*. Two identical runs produce different
        ids but identical hashes, so including the id would make replay
        comparison fail on identity rather than on content. The hash is the
        comparison key; the id is the pointer.
        """
        payload = {k: v for k, v in self.to_dict().items()
                   if k not in ("resulting_subject_state_hash", "observation_id")}
        return sha256_hex(canonical_bytes(payload))

    @property
    def experience_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "subject_id": self.subject_id,
            "environment_id": self.environment_id,
            "sequence_number": self.sequence_number,
            "created_at": self.created_at,
            "observation_id": self.observation_id,
            "observation_hash": self.observation_hash,
            "action_id": self.action_id,
            "action_operation": self.action_operation,
            "action_validation": self.action_validation,
            "consequence": self.consequence,
            "consequence_digest": self.consequence_digest,
            "environment_state_hash": self.environment_state_hash,
            "environment_state_version": self.environment_state_version,
            "prior_subject_state_hash": self.prior_subject_state_hash,
            "resulting_subject_state_hash": self.resulting_subject_state_hash,
            "provenance_reference": self.provenance_reference,
            "origin": self.origin.value,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Experience":
        return cls(
            experience_id=payload["experience_id"],
            subject_id=payload["subject_id"],
            environment_id=payload["environment_id"],
            sequence_number=payload["sequence_number"],
            created_at=payload.get("created_at", ""),
            observation_id=payload["observation_id"],
            observation_hash=payload["observation_hash"],
            action_id=payload["action_id"],
            action_operation=payload["action_operation"],
            action_validation=payload["action_validation"],
            consequence=payload["consequence"],
            consequence_digest=payload["consequence_digest"],
            environment_state_hash=payload["environment_state_hash"],
            environment_state_version=payload["environment_state_version"],
            prior_subject_state_hash=payload["prior_subject_state_hash"],
            resulting_subject_state_hash=payload["resulting_subject_state_hash"],
            provenance_reference=payload["provenance_reference"],
            origin=Origin(payload.get("origin", "DERIVED")),
        )


def experience_id_for(subject_id: str, sequence_number: int) -> str:
    """Deterministic experience ids, so a replay derives the same record.

    Random ids would make the same interaction produce a different record on
    replay, and then replay comparison would fail on identity rather than on
    content. Sequence-derived ids compare on what actually happened.
    """
    return f"exp-{subject_id}-{sequence_number:06d}"


def verify_experience(record: Experience) -> tuple[bool, str]:
    """Check an experience record's internal consistency."""
    recomputed = Experience.from_dict(record.to_dict())
    if recomputed.experience_hash != record.experience_hash:
        return False, "experience hash does not match its contents"
    if record.experience_id != experience_id_for(record.subject_id,
                                                record.sequence_number):
        return False, "experience id does not follow the sequence scheme"
    return True, "intact"


__all__ = ["Experience", "experience_id_for", "verify_experience"]
