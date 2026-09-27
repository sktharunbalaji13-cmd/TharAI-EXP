"""``birth``: the subject's origin, made explicit and auditable.

What this package is for
------------------------
Milestone 003. It answers one question in a way that can be checked later: *what
exactly was this subject, and what did it already know before it knew anything?*

The four commitments in the code
-------------------------------
1. **The model is inherited, not earned.** :mod:`birth.authorship` classifies
   pretrained weights as ``INHERITED_PRETRAINED`` from their kind alone, and
   recomputes that rather than trusting a stored field.
2. **The model is chosen by a human, or not at all.** :mod:`birth.config` has no
   default and no search path. :mod:`birth.identity` reports ``NOT_CONFIGURED``
   and ``MODEL_NOT_INSTALLED`` as facts.
3. **The birth is one event, written once.** :mod:`birth.birth_record` refuses a
   second subject. :mod:`birth.service` emits ``system.baby_ai.born`` from the
   laboratory, never from the subject.
4. **The capability set is an unordered set of empty contracts.**
   :mod:`birth.cognitive` defines the interface for what the subject will
   eventually do and implements none of it, because implementing it is the
   experiment.

Quick start
-----------
::

    from babylab.paths import default_paths
    from birth.service import inspect, birth_ceremony

    result = inspect()                    # writes nothing, always
    print(result.describe())              # e.g. MODEL_NOT_INSTALLED: ...
    ceremony = birth_ceremony()           # creates a subject, or explains why not

See docs/birth-architecture.md.
"""

from __future__ import annotations

from birth.authorship import (
    ArtifactKind,
    AuthorshipClass,
    AuthorshipRecord,
    classify_artifact,
)
from birth.birth_record import (
    BIRTH_RECORD_SCHEMA,
    BirthRecord,
    load_record,
    verify_record,
)
from birth.boundary import (
    ActionBoundary,
    ActionDecision,
    ActionIntent,
    ActionKind,
    DecisionOutcome,
    RefusalReason,
)
from birth.cognitive import (
    CapabilityContract,
    CapabilityKind,
    CapabilityRegistry,
    CapabilityStatus,
    capability_names,
)
from birth.environment import Affordance, RestrictedEnvironment, unattached_environment
from birth.identity import (
    InstallationReport,
    ModelIdentity,
    ModelStatus,
    resolve_model_identity,
)
from birth.perception import (
    EvidenceKind,
    FoundationEvidence,
    Interpretation,
    interpret,
    record_evidence,
)
from birth.runtime import (
    FoundationModel,
    InvocationRecord,
    ModelResponse,
    ObservationStatus,
    OutputKind,
    PromptRequest,
    build_invocation_record,
)
from birth.service import (
    BIRTH_EVENT_SOURCE,
    BIRTH_EVENT_TYPE,
    CeremonyResult,
    birth_ceremony,
    birth_status,
    inspect,
)
from birth.workspace import CodeWorkspace, WorkspaceState

__all__ = [
    "BIRTH_EVENT_SOURCE",
    "BIRTH_EVENT_TYPE",
    "BIRTH_RECORD_SCHEMA",
    "ActionBoundary",
    "ActionDecision",
    "ActionIntent",
    "ActionKind",
    "Affordance",
    "ArtifactKind",
    "AuthorshipClass",
    "AuthorshipRecord",
    "BirthRecord",
    "CapabilityContract",
    "CapabilityKind",
    "CapabilityRegistry",
    "CapabilityStatus",
    "CeremonyResult",
    "CodeWorkspace",
    "DecisionOutcome",
    "EvidenceKind",
    "FoundationEvidence",
    "FoundationModel",
    "InstallationReport",
    "Interpretation",
    "InvocationRecord",
    "ModelIdentity",
    "ModelResponse",
    "ModelStatus",
    "ObservationStatus",
    "OutputKind",
    "PromptRequest",
    "RefusalReason",
    "RestrictedEnvironment",
    "WorkspaceState",
    "birth_ceremony",
    "birth_status",
    "build_invocation_record",
    "capability_names",
    "classify_artifact",
    "inspect",
    "interpret",
    "load_record",
    "record_evidence",
    "resolve_model_identity",
    "unattached_environment",
    "verify_record",
]
