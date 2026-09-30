"""M010 foundation-model acquisition, verification, and runtime validation.

Foundation model output is not subject output. Foundation model output is not
experience. Foundation model output is not learning. Foundation model execution
does not create a subject. Foundation model execution does not perform birth.

What this package does
----------------------
It turns "a model file" into "a verified artifact plus a verified runtime", and
nothing beyond that. It is the input side of Milestone 009's birth gate, built
so the gate can later have something real to consume.

What it deliberately does not do
--------------------------------
* It does not acquire a model. :mod:`foundation.acquisition` is a refusal with
  a machine-readable inventory of the routes it turns away.
* It does not create a subject, perform a birth, build a memory, train
  anything, or grant a tool. No module here imports ``subject`` or the birth
  ceremony, and the test suite walks the import graph to prove it.
* It does not claim GPU use from a configuration value, token counts from an
  estimate, or provenance from a file that sits next to the artifact.
"""

from foundation.acquisition import (
    AcquisitionRefused,
    AcquisitionState,
    AcquisitionStatus,
    assess,
    refuse,
)
from foundation.admission import AdmissionDecision, AdmissionState, evaluate_admission
from foundation.artifact import (
    ArtifactIdentity,
    DigestStatus,
    compute_digest,
    identify,
    verify_immutable,
)
from foundation.inference import (
    InferenceKind,
    InferenceOutcome,
    InferenceRecord,
    assert_neutral_prompt,
    baseline_sampling,
    compare_repeat,
    run_inference,
)
from foundation.isolation import IsolationReport, verify_isolation
from foundation.manifest import ModelManifest, load_manifest, write_template
from foundation.runtime_identity import (
    GpuUsage,
    RuntimeIdentity,
    RuntimeState,
    identify_runtime,
)
from foundation.status import FoundationStatus, foundation_status
from foundation.validation import ValidationLedger, validate

__all__ = [
    "AcquisitionRefused",
    "AcquisitionState",
    "AcquisitionStatus",
    "AdmissionDecision",
    "AdmissionState",
    "ArtifactIdentity",
    "DigestStatus",
    "FoundationStatus",
    "GpuUsage",
    "InferenceKind",
    "InferenceOutcome",
    "InferenceRecord",
    "IsolationReport",
    "ModelManifest",
    "RuntimeIdentity",
    "RuntimeState",
    "ValidationLedger",
    "assess",
    "assert_neutral_prompt",
    "baseline_sampling",
    "compare_repeat",
    "compute_digest",
    "evaluate_admission",
    "foundation_status",
    "identify",
    "identify_runtime",
    "load_manifest",
    "refuse",
    "run_inference",
    "validate",
    "verify_immutable",
    "verify_isolation",
    "write_template",
]
