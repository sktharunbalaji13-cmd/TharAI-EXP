"""Milestone 006: the foundation-model and runtime layer.

What lives here
---------------
``contract``     versioned adapter interface, request/response, failure kinds
``hardware``     observed host capability with epistemic status on every number
``registry``     explicit adapter registration; no discovery, no fallback
``governor``     admission control and resource limits
``llamacpp_adapter``  the llama.cpp binding
``runtime``      the runtime facade: policy, lifecycle, events
``interface``    the constrained surface a subject may call
``provenance``   runtime output recorded as INHERITED_PRETRAINED
``config``       one explicit configuration source, and nothing else

The distinction this package maintains
--------------------------------------
A foundation model is a pretrained artifact. It is not a cognitive architecture
and it is not the subject. M006 builds the engine and stops there: no curriculum,
no memory, no goals, no autonomy, no tools, no self-modification, and no subject.
"""

from babylab.runtime.contract import (
    ADAPTER_CONTRACT_VERSION,
    EpistemicStatus,
    FinishReason,
    InferenceRequest,
    InferenceResponse,
    Measurement,
    ModelAdapter,
    RuntimeErrorKind,
    RuntimeFailure,
    RuntimeIdentity,
    RuntimeState,
)
from babylab.runtime.governor import Admission, AdmissionDecision, ResourcePolicy
from babylab.runtime.hardware import HardwareReport, detect_hardware
from babylab.runtime.interface import SubjectInterface
from babylab.runtime.registry import AdapterRegistration, AdapterRegistry
from babylab.runtime.runtime import FoundationRuntime, ModelDeclaration

__all__ = [
    "ADAPTER_CONTRACT_VERSION",
    "AdapterRegistration",
    "AdapterRegistry",
    "Admission",
    "AdmissionDecision",
    "EpistemicStatus",
    "FinishReason",
    "FoundationRuntime",
    "HardwareReport",
    "InferenceRequest",
    "InferenceResponse",
    "Measurement",
    "ModelAdapter",
    "ModelDeclaration",
    "ResourcePolicy",
    "RuntimeErrorKind",
    "RuntimeFailure",
    "RuntimeIdentity",
    "RuntimeState",
    "SubjectInterface",
    "detect_hardware",
]
