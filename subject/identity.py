"""Subject identity: externally established, never self-authorized.

The rule
--------
**A subject does not get to say who it is.** The identity record is produced by
laboratory-controlled code from laboratory-held facts, and the derivation
function refuses any request that did not arrive through the laboratory. Model
output that says ``{"author": "BABY_AI"}`` is text; it is not evidence, and it
is rejected as an identity source rather than interpreted.

How the guard works, and where it actually lives
------------------------------------------------
The schema-level guard here is the ``issuer`` parameter: identity can only be
derived with ``issuer="LABORATORY"``. That check is real but small, and a reader
should not mistake it for the whole boundary. The substantive enforcement is
*where identity records may live*: they are created by harness/laboratory code,
never written to a subject-reachable path, and the production guard -- the M005
OS boundary plus key custody -- is what makes "the subject rewrote its identity"
a filesystem impossibility rather than a string comparison. Both layers are
needed; neither alone is the boundary.

Foundation reference
--------------------
The identity carries a foundation reference: the digest and describing facts of
whatever pretrained artifact this subject is associated with, if any. The
reference is a *pointer*, not an identity. The subject's digest never equals the
artifact's digest, and the reference says nothing about what the artifact
"knows". A reference to an unverified or absent foundation is recorded as
exactly that -- ``UNVERIFIED`` / ``NONE`` -- never as an assumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from babylab.hashing import canonical_bytes, sha256_hex

#: Schema version for every identity this module derives.
SUBJECT_IDENTITY_SCHEMA = "babylab/subject-identity/v1"

#: The only issuer that may derive a subject identity.
LABORATORY_ISSUER = "LABORATORY"

#: Reserved actor names that may never appear as an issuer.
NON_LABORATORY_ISSUERS = frozenset({"SUBJECT", "BABY_AI", "MODEL", "ENVIRONMENT"})


class IdentityError(RuntimeError):
    """Refused identity derivation or use."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class FoundationReference:
    """A pointer to a pretrained artifact. A reference, never an identity.

    ``state`` says what the laboratory actually knows about the artifact:
    ``VERIFIED`` means the digest was checked against bytes the laboratory
    holds; ``DECLARED`` means the facts were supplied but not checked;
    ``UNVERIFIED`` means they were supplied by something the laboratory does
    not trust; ``NONE`` means there is no associated artifact at all.
    """

    state: str
    artifact_digest: str = ""
    artifact_name: str = ""
    runtime_implementation: str = ""
    runtime_version: str = ""
    classification: str = "INHERITED_PRETRAINED"

    VALID_STATES = frozenset({"VERIFIED", "DECLARED", "UNVERIFIED", "NONE"})

    def __post_init__(self) -> None:
        if self.state not in self.VALID_STATES:
            raise IdentityError("INVALID_FOUNDATION_STATE", self.state)
        if self.state == "VERIFIED" and (
            not self.artifact_digest or len(self.artifact_digest) != 64
        ):
            raise IdentityError(
                "UNVERIFIABLE_FOUNDATION",
                "a VERIFIED reference requires a 64-character digest",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "artifact_digest": self.artifact_digest,
            "artifact_name": self.artifact_name,
            "runtime_implementation": self.runtime_implementation,
            "runtime_version": self.runtime_version,
            "classification": self.classification,
        }

    @classmethod
    def none(cls) -> "FoundationReference":
        return cls(state="NONE")

    @classmethod
    def declared(cls, **facts: Any) -> "FoundationReference":
        return cls(state="DECLARED", **facts)

    @classmethod
    def unverified(cls, **facts: Any) -> "FoundationReference":
        return cls(state="UNVERIFIED", **facts)


@dataclass(frozen=True)
class SubjectIdentity:
    """Who a subject is, as determined from outside it."""

    subject_id: str
    schema_version: str = SUBJECT_IDENTITY_SCHEMA
    foundation: FoundationReference = field(default_factory=FoundationReference.none)
    environment_interface_version: str = ""
    issuer: str = LABORATORY_ISSUER
    derived_at: str = ""
    derivation_basis: str = ""

    def __post_init__(self) -> None:
        if not self.subject_id or not isinstance(self.subject_id, str):
            raise IdentityError("MALFORMED_IDENTITY", "subject_id must be non-empty")
        if self.schema_version != SUBJECT_IDENTITY_SCHEMA:
            raise IdentityError(
                "SCHEMA_MISMATCH",
                f"expected {SUBJECT_IDENTITY_SCHEMA}, got {self.schema_version!r}",
            )

    @property
    def identity_hash(self) -> str:
        """Digest of the identity record. What the subject state anchors to."""
        return sha256_hex(canonical_bytes(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "schema_version": self.schema_version,
            "foundation": self.foundation.to_dict(),
            "environment_interface_version": self.environment_interface_version,
            "issuer": self.issuer,
            "derived_at": self.derived_at,
            "derivation_basis": self.derivation_basis,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SubjectIdentity":
        foundation = payload.get("foundation", {})
        return cls(
            subject_id=payload["subject_id"],
            schema_version=payload.get("schema_version", SUBJECT_IDENTITY_SCHEMA),
            foundation=FoundationReference(
                state=foundation.get("state", "NONE"),
                artifact_digest=foundation.get("artifact_digest", ""),
                artifact_name=foundation.get("artifact_name", ""),
                runtime_implementation=foundation.get("runtime_implementation", ""),
                runtime_version=foundation.get("runtime_version", ""),
                classification=foundation.get("classification", "INHERITED_PRETRAINED"),
            ),
            environment_interface_version=payload.get(
                "environment_interface_version", ""),
            issuer=payload.get("issuer", ""),
            derived_at=payload.get("derived_at", ""),
            derivation_basis=payload.get("derivation_basis", ""),
        )


def derive_identity(
    *,
    subject_id: str,
    issuer: str,
    foundation: FoundationReference | None = None,
    environment_interface_version: str = "",
    derived_at: str = "",
    derivation_basis: str = "",
) -> SubjectIdentity:
    """Derive a subject identity, from the laboratory only.

    ``issuer`` must be ``"LABORATORY"``. Model output, subject output, and
    environment output are uniformly refused -- there is no special case for any
    of them, because a special case is how a forged identity gets in.
    """
    if issuer != LABORATORY_ISSUER:
        raise IdentityError(
            "UNAUTHORIZED_ISSUER",
            f"identity may only be derived by {LABORATORY_ISSUER!r}; "
            f"got {issuer!r}. Model output, subject output and environment "
            "output are never identity evidence.",
        )
    return SubjectIdentity(
        subject_id=subject_id,
        foundation=foundation or FoundationReference.none(),
        environment_interface_version=environment_interface_version,
        issuer=issuer,
        derived_at=derived_at,
        derivation_basis=derivation_basis or "laboratory-controlled derivation",
    )


def verify_identity_record(payload: dict[str, Any]) -> tuple[bool, str]:
    """Check a stored identity record without constructing trust from it."""
    try:
        SubjectIdentity.from_dict(payload)
    except (IdentityError, KeyError, TypeError, AttributeError) as exc:
        return False, f"malformed identity record: {exc}"
    if payload.get("issuer") != LABORATORY_ISSUER:
        return False, "identity record was not issued by the laboratory"
    return True, "intact"


__all__ = [
    "FoundationReference",
    "IdentityError",
    "LABORATORY_ISSUER",
    "NON_LABORATORY_ISSUERS",
    "SUBJECT_IDENTITY_SCHEMA",
    "SubjectIdentity",
    "derive_identity",
    "verify_identity_record",
]
