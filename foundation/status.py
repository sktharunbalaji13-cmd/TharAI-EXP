"""M010 status: one read-only function the Observatory can call.

Why this module is separate
---------------------------
The Observatory displays foundation-runtime state. It must not be able to
*change* it, and it must not be able to load a model, spawn a runtime, or run an
inference -- a view that could execute the thing it observes is not a view.

So :func:`foundation_status` is the entire read surface. It reads a declaration,
a manifest, an artifact's bytes, a binary's bytes, and the machine's VRAM. It
starts no subprocess, opens no socket, and imports neither ``subject`` nor the
birth ceremony.

What it will never display
--------------------------
Intelligence, consciousness, awareness, reasoning quality, personality,
curiosity, learning progress, readiness. Runtime telemetry cannot establish any
of those, and a field for one would have to be invented to be filled. The
rendered section is a measurement panel, not a profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from foundation.acquisition import AcquisitionState, assess
from foundation.admission import evaluate_admission, observe_vram
from foundation.artifact import DigestStatus, identify
from foundation.manifest import load_manifest
from foundation.runtime_identity import identify_runtime

#: Vocabulary this milestone refuses to display. Enforced structurally: the
#: renderer has no field that could carry any of it.
FORBIDDEN_DISPLAY_TERMS: tuple[str, ...] = (
    "intelligence",
    "consciousness",
    "conscious",
    "sentience",
    "sentient",
    "awareness",
    "reasoning quality",
    "personality",
    "curiosity",
    "learning progress",
    "readiness",
    "emotion",
    "mood",
    "stage",
    "curriculum",
)


@dataclass
class FoundationStatus:
    """Everything the Observatory needs, assembled read-only."""

    acquisition: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    artifact: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    admission: dict[str, Any] = field(default_factory=dict)
    vram: dict[str, Any] = field(default_factory=dict)
    inference: dict[str, Any] = field(default_factory=dict)
    isolation: dict[str, Any] = field(default_factory=dict)
    detail: str = ""

    @property
    def model_configured(self) -> bool:
        return self.acquisition.get("state") == AcquisitionState.DECLARED.value

    @property
    def artifact_verified(self) -> bool:
        return bool(self.artifact.get("verified"))

    @property
    def runtime_verified(self) -> bool:
        return bool(self.runtime.get("verified"))

    @property
    def real_inference_available(self) -> bool:
        """True only when everything needed for a real run is established.

        A verified model with an unverified runtime, or vice versa, is not
        sufficient. This is the ``M != R`` rule expressed as a single predicate.
        """
        return bool(
            self.acquisition.get("model_available")
            and self.artifact_verified
            and self.runtime_verified
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "babylab/foundation-status/v1",
            "model_configured": self.model_configured,
            "artifact_verified": self.artifact_verified,
            "runtime_verified": self.runtime_verified,
            "real_inference_available": self.real_inference_available,
            "acquisition": dict(self.acquisition),
            "manifest": dict(self.manifest),
            "artifact": dict(self.artifact),
            "runtime": dict(self.runtime),
            "admission": dict(self.admission),
            "vram": dict(self.vram),
            "inference": dict(self.inference),
            "isolation": dict(self.isolation),
            "forbidden_display_terms": list(FORBIDDEN_DISPLAY_TERMS),
            "detail": self.detail,
            "explicitly_not": {
                "subject": "no subject exists; a model running is not a subject",
                "birth": "birth is a separate, gated laboratory event and was not performed",
                "memory": "no memory system exists",
                "learning": "no learning or weight update occurs",
                "experience": "inference output is not an experience",
            },
        }


def foundation_status(
    root: str | Path | None = None,
    *,
    with_runtime_probe: bool = False,
    with_admission: bool = False,
    with_isolation: bool = False,
) -> FoundationStatus:
    """Assemble the read-only foundation panel.

    The expensive sub-probes are opt-in. A default call hashes nothing beyond
    what is needed to answer "is a model configured", so the Observatory can poll
    this cheaply. Passing ``with_runtime_probe=True`` will *execute* the
    configured binary with ``--version``; that is a subprocess, so the
    Observatory leaves it off and reports the runtime as unprobed instead.
    """
    if root is None:
        from babylab.paths import default_paths

        root = default_paths().root
    root = Path(root)

    acquisition = assess(root)
    status = FoundationStatus(acquisition=acquisition.to_dict())

    manifest = load_manifest(acquisition.manifest_path)
    status.manifest = manifest.to_dict()

    artifact: dict[str, Any] = {}
    runtime: dict[str, Any] = {"state": "NOT_PROBED", "detail": (
        "the runtime binary was not probed; the Observatory does not execute "
        "binaries. Use the validation command for that."
    )}

    if acquisition.state is AcquisitionState.DECLARED:
        from babylab.runtime.config import load_configuration

        loaded = load_configuration(acquisition.declaration_path)
        if loaded.configured:
            declaration = loaded.configuration.declaration
            identity = identify(
                declaration.model_path,
                expected_sha256=declaration.sha256,
                external_sha256=manifest.externally_supplied_sha256,
                external_source=manifest.external_digest_source,
                family=declaration.model_family or manifest.declared_family,
                name=declaration.model_name or manifest.declared_name,
                quantization=declaration.quantization or manifest.declared_quantization,
                context_length=declaration.context_length,
                source_url=manifest.source_url or declaration.source_url,
                license_=manifest.license or declaration.license,
            )
            artifact = identity.to_dict()
            status.artifact = artifact

            if with_runtime_probe and declaration.runtime_binary:
                runtime = identify_runtime(declaration.runtime_binary).to_dict()

            if with_admission and artifact.get("size_bytes"):
                context = (
                    manifest.declared_context_length
                    or declaration.context_length
                    or 2048
                )
                decision = evaluate_admission(
                    artifact_bytes=int(artifact["size_bytes"]),
                    context_length=int(context),
                )
                status.admission = decision.to_dict()
                status.vram = observe_vram()
    else:
        artifact = {
            "status": DigestStatus.NOT_CONFIGURED.value,
            "detail": (
                "no artifact is identified because no human wrote a model "
                "declaration. The laboratory does not search for one."
            ),
            "verified": False,
        }
        status.artifact = artifact

    status.runtime = runtime

    if with_isolation:
        from foundation.isolation import verify_isolation

        status.isolation = verify_isolation(root).to_dict()

    status.detail = (
        "Read-only foundation state. A verified model with no runtime is not an "
        "executable configuration, and a runtime with no model is not a "
        "subject: model identity and runtime identity are separate claims."
    )
    return status


def render_lines(status: FoundationStatus) -> list[str]:
    """Plain text for the CLI, in the same key/value style as the rest.

    Every absent value prints as ``UNAVAILABLE`` rather than being omitted, so a
    blank line can never be read as a passing check.
    """
    acq = status.acquisition
    art = status.artifact
    rt = status.runtime
    lines: list[str] = [
        f"model configured   {acq.get('state', 'UNAVAILABLE')}",
        f"  declaration      {acq.get('declaration_path', 'UNAVAILABLE')}",
        f"  manifest         {acq.get('manifest_path', 'UNAVAILABLE')}",
        f"  weights boundary {acq.get('weights_directory', 'UNAVAILABLE')}",
        f"artifact status    {art.get('status', 'UNAVAILABLE')}",
        f"  filename         {art.get('filename') or 'UNAVAILABLE'}",
        f"  size bytes       {art.get('size_bytes') or 'UNAVAILABLE'}",
        f"  computed sha256  {art.get('computed_sha256') or 'UNAVAILABLE'}",
        f"  external digest  {art.get('external_sha256') or 'NOT SUPPLIED'}",
        f"  digest basis     {art.get('external_digest_source') or 'none'}",
        f"  verified         {art.get('verified', False)}",
        f"runtime state      {rt.get('state', 'UNAVAILABLE')}",
        f"  implementation   {rt.get('implementation', 'UNAVAILABLE')}",
        f"  version          {rt.get('version', 'UNAVAILABLE')}",
        f"  binary sha256    {rt.get('binary_sha256', 'UNAVAILABLE')}",
        f"  gpu usage        {rt.get('gpu_usage', 'UNAVAILABLE')}",
        f"real inference     {'AVAILABLE' if status.real_inference_available else 'NOT AVAILABLE'}",
        f"subject            none (a model running is not a subject)",
        f"birth              NOT_PERFORMED",
    ]
    return lines


__all__ = [
    "FORBIDDEN_DISPLAY_TERMS",
    "FoundationStatus",
    "foundation_status",
    "render_lines",
]
