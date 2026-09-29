"""The laboratory-controlled subject creation record.

What a creation record is
-------------------------
The laboratory's own account of having created a subject record: who, when,
from what foundation, under what schema, and why. It is written once, by
laboratory code, and then frozen. Every later check that asks "is this subject
record legitimate?" consults this record.

What it is not
--------------
It is not a birth ceremony, and it must never be confused with one. M003's
ceremony is the production act with its own review and its own safeguards; this
record is an M008 architectural mechanism for tests and harness use. The
difference is structural, not a matter of which fields are filled in:

* a test-harness creation record is never written to ``human_control/``;
* it never provisions a ``BABY_AI`` signing key;
* it never registers in the real session registry.

A creation record outside those constraints is a birth, and performing one is
outside M008's scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from babylab.hashing import canonical_bytes, sha256_hex
from subject.identity import LABORATORY_ISSUER, IdentityError, SubjectIdentity

#: Schema version for creation records.
CREATION_RECORD_SCHEMA = "babylab/subject-creation/v1"


@dataclass(frozen=True)
class CreationRecord:
    """The laboratory's immutable account of a subject's creation."""

    subject_id: str
    schema_version: str
    created_at: str
    foundation_identity: dict[str, Any]
    environment_interface_version: str
    subject_schema_version: str
    laboratory_implementation_version: str
    creation_reason: str
    provenance_identity: str
    issuer: str = LABORATORY_ISSUER

    def __post_init__(self) -> None:
        if self.schema_version != CREATION_RECORD_SCHEMA:
            raise IdentityError(
                "SCHEMA_MISMATCH",
                f"expected {CREATION_RECORD_SCHEMA}, got {self.schema_version!r}",
            )
        if self.issuer != LABORATORY_ISSUER:
            raise IdentityError(
                "UNAUTHORIZED_ISSUER",
                "a creation record may only be issued by the laboratory",
            )
        if not self.subject_id:
            raise IdentityError("MALFORMED_RECORD", "subject_id must be non-empty")

    @property
    def record_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "foundation_identity": self.foundation_identity,
            "environment_interface_version": self.environment_interface_version,
            "subject_schema_version": self.subject_schema_version,
            "laboratory_implementation_version": self.laboratory_implementation_version,
            "creation_reason": self.creation_reason,
            "provenance_identity": self.provenance_identity,
            "issuer": self.issuer,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CreationRecord":
        return cls(
            subject_id=payload["subject_id"],
            schema_version=payload.get("schema_version", CREATION_RECORD_SCHEMA),
            created_at=payload.get("created_at", ""),
            foundation_identity=dict(payload.get("foundation_identity", {})),
            environment_interface_version=payload.get(
                "environment_interface_version", ""),
            subject_schema_version=payload.get("subject_schema_version", ""),
            laboratory_implementation_version=payload.get(
                "laboratory_implementation_version", ""),
            creation_reason=payload.get("creation_reason", ""),
            provenance_identity=payload.get("provenance_identity", ""),
            issuer=payload.get("issuer", ""),
        )


def create_record(
    *,
    subject_id: str,
    identity: SubjectIdentity,
    identity_hash: str,
    foundation_identity: dict[str, Any],
    environment_interface_version: str,
    subject_schema_version: str,
    laboratory_implementation_version: str,
    creation_reason: str,
    provenance_identity: str,
    created_at: str,
    issuer: str = LABORATORY_ISSUER,
) -> CreationRecord:
    """Build a creation record, from the laboratory only.

    The identity and its hash must agree: a record whose ``identity_hash`` does
    not match the supplied identity is a record about the wrong subject, and is
    refused rather than repaired.
    """
    if issuer != LABORATORY_ISSUER:
        raise IdentityError(
            "UNAUTHORIZED_ISSUER",
            "only the laboratory may create a subject creation record",
        )
    if identity.subject_id != subject_id:
        raise IdentityError(
            "IDENTITY_MISMATCH",
            "the creation record names a different subject than the identity",
        )
    if identity.identity_hash != identity_hash:
        raise IdentityError(
            "IDENTITY_MISMATCH",
            "the recorded identity hash does not match the supplied identity",
        )
    return CreationRecord(
        subject_id=subject_id,
        schema_version=CREATION_RECORD_SCHEMA,
        created_at=created_at,
        foundation_identity=dict(foundation_identity),
        environment_interface_version=environment_interface_version,
        subject_schema_version=subject_schema_version,
        laboratory_implementation_version=laboratory_implementation_version,
        creation_reason=creation_reason,
        provenance_identity=provenance_identity,
        issuer=issuer,
    )


def verify_record(record: CreationRecord) -> tuple[bool, str]:
    """Check a creation record's internal consistency."""
    recomputed = CreationRecord.from_dict(record.to_dict())
    if recomputed.record_hash != record.record_hash:
        return False, "record hash does not match its contents"
    if record.issuer != LABORATORY_ISSUER:
        return False, "record was not issued by the laboratory"
    return True, "intact"


def record_belongs_to(record: CreationRecord, subject_id: str,
                      creation_record_hash: str) -> tuple[bool, str]:
    """Whether this record is the record for a given subject.

    Self-consistency is not enough: a well-formed record about *someone else*
    verifies cleanly, and nothing in the hash prevents that record from being
    presented for the wrong subject. Binding is therefore a separate, explicit
    check: the record must name the subject *and* its hash must be the hash the
    subject's state already carries. Both conditions are required, because a
    matching name with a different hash is a substitute, and a matching hash on
    a different name is impossible.
    """
    if record.subject_id != subject_id:
        return False, (
            f"record names {record.subject_id!r}, not {subject_id!r}; "
            "a record about another subject cannot stand in for this one")
    if record.record_hash != creation_record_hash:
        return False, (
            "record hash does not match the hash the subject state carries; "
            "the record was substituted after creation")
    return True, "this record belongs to this subject"


__all__ = ["CREATION_RECORD_SCHEMA", "CreationRecord", "create_record", "verify_record"]
