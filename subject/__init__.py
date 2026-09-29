"""Milestone 008: the subject architecture and first-experience boundary.

A subject is an externally governed identity plus subject-owned state and a
provenance-linked history of experiences. It is not a model, not a process, not
a response, not an environment, not a key, not an account, and not a workspace.

    FOUNDATION MODEL
        !=
    SUBJECT
        !=
    ENVIRONMENT
        !=
    LABORATORY

M008 builds the boundary. It does not build a mind: no curriculum, no goals,
no motivation, no personality, no emotions, no memory, no learning, no autonomy.
"""

from subject.creation import (
    CREATION_RECORD_SCHEMA,
    CreationRecord,
    create_record,
    record_belongs_to,
    verify_record,
)
from subject.experience import Experience, experience_id_for, verify_experience
from subject.harness import HarnessSubject, SubjectHarness
from subject.identity import (
    FoundationReference,
    IdentityError,
    SubjectIdentity,
    derive_identity,
    verify_identity_record,
)
from subject.interface import INTERFACE_VERSION, Proposal, SubjectInterface
from subject.lifecycle import (
    ALLOWED_TRANSITIONS,
    LifecycleError,
    LifecycleState,
    SubjectLifecycle,
)
from subject.provenance import (
    Origin,
    ProvenanceAttribution,
    Source,
    attribute_record,
)
from subject.state import (
    SUBJECT_STATE_SCHEMA,
    UNIMPLEMENTED_CAPABILITIES,
    SubjectState,
)
from subject.telemetry import SubjectTelemetry, build_telemetry

__all__ = [
    "ALLOWED_TRANSITIONS",
    "CREATION_RECORD_SCHEMA",
    "CreationRecord",
    "Experience",
    "FoundationReference",
    "HarnessSubject",
    "IdentityError",
    "LifecycleError",
    "LifecycleState",
    "Origin",
    "Proposal",
    "ProvenanceAttribution",
    "Source",
    "SubjectHarness",
    "SubjectIdentity",
    "SubjectInterface",
    "SubjectLifecycle",
    "SubjectState",
    "SubjectTelemetry",
    "INTERFACE_VERSION",
    "SUBJECT_STATE_SCHEMA",
    "UNIMPLEMENTED_CAPABILITIES",
    "attribute_record",
    "build_telemetry",
    "create_record",
    "derive_identity",
    "experience_id_for",
    "record_belongs_to",
    "verify_experience",
    "verify_identity_record",
    "verify_record",
]
