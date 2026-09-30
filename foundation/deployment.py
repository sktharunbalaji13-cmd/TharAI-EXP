"""M012 deployment: one explicit human declaration naming both artifacts.

Why a joint declaration
-----------------------
M010 and M011 each read a *runtime* configuration and a separate *manifest*.
That is enough to verify a model in isolation, but M012 asks a paired question:
"did this human choose *this* model to run on *this* runtime?" Answering that
needs both decisions in one place, attributed to one person, at one moment. So
M012 introduces a single declaration carrying the model, the runtime, the digest
provenance, and the human's stated reason -- and the two identities are kept
distinct all the way through, because a paired declaration does not make them one
thing.

The selection boundary
----------------------
This module reads a file the human wrote. It does not enumerate a directory, walk
a PATH, or ask the filesystem what looks plausible. A file merely existing is not
a selection; :mod:`foundation.discovery` reports candidates for a human to
consider and has no way to promote one, and this module has no parameter that
accepts a discovered path as a decision.

What the human must supply
--------------------------
* an absolute path to the model artifact;
* its SHA-256, or a reference to an externally published digest;
* an absolute path to the runtime executable;
* an expected version string, which is checked against the executable rather
  than believed;
* their own name and a reason.

The reason is not decoration. "Which foundation did you pick, and why" is
research provenance, and a declaration without one cannot answer the question
this project exists to ask. It is recorded verbatim and never interpreted.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Accepted schema.
DEPLOYMENT_SCHEMA = "babylab/foundation-deployment/v1"

#: Where the human writes the declaration. Reported, never searched for.
DEPLOYMENT_RELPATH = "human_control/experiment_config/model_deployment.json"


class DeploymentState(str, enum.Enum):
    #: No human declaration exists. The correct state of a laboratory that has
    #: not been told which foundation to use.
    NOT_CONFIGURED = "NOT_CONFIGURED"
    #: A declaration exists and is well formed.
    LOADED = "LOADED"
    #: A declaration exists and is wrong. Detail is carried; nothing is repaired.
    INVALID = "INVALID"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class Deployment:
    """One human's selection of a model and a runtime, kept as two identities."""

    #: --- the model ---
    model_path: str = ""
    model_sha256: str = ""
    model_external_digest: str = ""
    model_external_source: str = ""
    model_external_reference: str = ""
    model_family: str = ""
    model_name: str = ""
    model_quantization: str = ""
    model_context_length: int | None = None
    model_license: str = ""
    model_source_url: str = ""
    model_acquisition_reference: str = ""

    #: --- the runtime, a separate subject with separate provenance ---
    runtime_path: str = ""
    runtime_expected_version: str = ""
    runtime_implementation: str = "llama.cpp"
    runtime_acquisition_reference: str = ""

    #: --- who chose, and why ---
    declared_by: str = ""
    declared_at: str = ""
    selection_rationale: str = ""
    source_path: str = ""
    state: DeploymentState = DeploymentState.NOT_CONFIGURED
    detail: str = ""

    @property
    def has_model(self) -> bool:
        return bool(self.model_path)

    @property
    def has_runtime(self) -> bool:
        return bool(self.runtime_path)

    @property
    def has_external_model_digest(self) -> bool:
        return bool(self.model_external_digest) and bool(self.model_external_source)

    @property
    def selection_is_attributed(self) -> bool:
        """A selection a human cannot be named for is not a selection.

        Required rather than optional. An unattributed declaration would let a
        later commit claim the foundation was chosen deliberately when nobody can
        say by whom or why.
        """
        return bool(self.declared_by.strip()) and bool(self.selection_rationale.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DEPLOYMENT_SCHEMA,
            "state": self.state.value,
            "detail": self.detail,
            "source_path": self.source_path,
            "model": {
                "path": self.model_path,
                "sha256": self.model_sha256,
                "external_digest": self.model_external_digest,
                "external_digest_source": self.model_external_source,
                "external_digest_reference": self.model_external_reference,
                "has_external_digest": self.has_external_model_digest,
                "family": self.model_family,
                "name": self.model_name,
                "quantization": self.model_quantization,
                "context_length": self.model_context_length,
                "license": self.model_license,
                "source_url": self.model_source_url,
                "acquisition_reference": self.model_acquisition_reference,
            },
            "runtime": {
                "path": self.runtime_path,
                "expected_version": self.runtime_expected_version,
                "implementation": self.runtime_implementation,
                "acquisition_reference": self.runtime_acquisition_reference,
            },
            "identity_separation": (
                "the model is an artifact identified by its bytes; the runtime is "
                "an executable identified by its own path, digest, and version. "
                "They are verified independently and neither implies the other."
            ),
            "selection": {
                "declared_by": self.declared_by,
                "declared_at": self.declared_at,
                "rationale": self.selection_rationale,
                "attributed": self.selection_is_attributed,
            },
        }


def deployment_path(root: str | Path) -> Path:
    return Path(root) / DEPLOYMENT_RELPATH


def _invalid(target: Path, detail: str) -> Deployment:
    return Deployment(state=DeploymentState.INVALID, detail=detail,
                      source_path=str(target))


def load_declaration(path: str | Path | None) -> Deployment:
    """Read the human's declaration, or explain its absence.

    ``None`` and a missing file both yield ``NOT_CONFIGURED``, which is the
    state a laboratory is supposed to be in until a person tells it what
    foundation to use. Nothing is created, and no other location is consulted.
    """
    if path is None:
        return Deployment(
            state=DeploymentState.NOT_CONFIGURED,
            detail=(
                "no deployment declaration was supplied. The laboratory does not "
                "choose a foundation model, does not choose a runtime, and does "
                "not search the filesystem for either. A human writes this file "
                "naming both, with a reason."
            ),
        )

    target = Path(path)
    if not target.is_file():
        return Deployment(
            state=DeploymentState.NOT_CONFIGURED,
            detail=(
                f"no deployment declaration at {target}. A file merely existing on "
                "this machine is not a selection: M011 recorded an unconfigured "
                "llama.cpp binary that was correctly left unselected, and it stays "
                "unselected until a human names it here."
            ),
            source_path=str(target),
        )

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _invalid(target, f"the declaration could not be read: {exc}")

    schema = payload.get("schema")
    if schema != DEPLOYMENT_SCHEMA:
        return _invalid(
            target,
            f"the declaration declares schema {schema!r}; this laboratory "
            f"implements {DEPLOYMENT_SCHEMA!r}. Refusing to partially interpret it.",
        )

    model = payload.get("model")
    if not isinstance(model, dict):
        return _invalid(target, "the declaration has no 'model' object")

    runtime = payload.get("runtime")
    if not isinstance(runtime, dict):
        return _invalid(
            target,
            "the declaration has no 'runtime' object. M012 verifies a paired "
            "choice -- a model AND a runtime -- so both must be named.",
        )

    model_path = str(model.get("path", "")).strip()
    if not model_path:
        return _invalid(
            target,
            "model.path must name the artifact explicitly. The laboratory does "
            "not select a model, does not rank models, and does not pick the "
            "first .gguf it finds.",
        )
    if not Path(model_path).is_absolute():
        return _invalid(
            target,
            f"model.path must be absolute; {model_path!r} is relative, and a "
            "relative path would make the selection depend on where the process "
            "happened to start.",
        )

    sha = str(model.get("sha256", "")).strip().lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        return _invalid(
            target,
            "model.sha256 must be 64 hex characters. The laboratory will not "
            "derive it from the file, because a digest derived from the artifact "
            "proves only that the artifact hashes to itself.",
        )

    runtime_path = str(runtime.get("path", "")).strip()
    if not runtime_path:
        return _invalid(
            target,
            "runtime.path must name the executable explicitly. The laboratory "
            "does not search PATH, does not pick the first llama.cpp binary it "
            "finds, and does not download one.",
        )
    if not Path(runtime_path).is_absolute():
        return _invalid(
            target,
            f"runtime.path must be absolute; {runtime_path!r} is relative.",
        )

    selection = payload.get("selection") or {}
    if not isinstance(selection, dict):
        selection = {}
    declared_by = str(selection.get("declared_by", "")).strip()
    rationale = str(selection.get("rationale", "")).strip()
    if not declared_by or not rationale:
        return _invalid(
            target,
            "selection.declared_by and selection.rationale are both required. A "
            "foundation chosen without a named human and a stated reason is not "
            "a selection this project can attribute, and the provenance record "
            "would be unusable.",
        )

    external = model.get("external_digest") or {}
    if not isinstance(external, dict):
        external = {}

    return Deployment(
        state=DeploymentState.LOADED,
        source_path=str(target),
        model_path=model_path,
        model_sha256=sha,
        model_external_digest=str(external.get("sha256", "")).strip().lower(),
        model_external_source=str(external.get("source", "")).strip(),
        model_external_reference=str(external.get("reference", "")).strip(),
        model_family=str(model.get("family", "")),
        model_name=str(model.get("name", "")),
        model_quantization=str(model.get("quantization", "")),
        model_context_length=(
            int(model["context_length"])
            if model.get("context_length") is not None else None
        ),
        model_license=str(model.get("license", "")),
        model_source_url=str(model.get("source_url", "")),
        model_acquisition_reference=str(model.get("acquisition_reference", "")),
        runtime_path=runtime_path,
        runtime_expected_version=str(runtime.get("expected_version", "")),
        runtime_implementation=str(runtime.get("implementation", "llama.cpp")),
        runtime_acquisition_reference=str(runtime.get("acquisition_reference", "")),
        declared_by=declared_by,
        declared_at=str(selection.get("declared_at", "")),
        selection_rationale=rationale,
        detail=(
            f"a human selected {Path(model_path).name} on "
            f"{Path(runtime_path).name}. The selection is attributed and "
            "rationaled; verification of the two artifacts proceeds independently."
        ),
    )


#: A blank declaration for a human to fill in. Every field that matters is a
#: placeholder, so submitting it unfilled is rejected rather than accepted with
#: invented provenance.
TEMPLATE = """{
  "schema": "babylab/foundation-deployment/v1",

  "model": {
    "path": "FILL IN: absolute path to the .gguf you selected",
    "sha256": "FILL IN: 64 hex characters of the artifact you selected",
    "family": "FILL IN: model family, as the publisher names it",
    "name": "FILL IN: specific model name",
    "quantization": "FILL IN: e.g. Q4_K_M, as published",
    "context_length": null,
    "license": "FILL IN",
    "source_url": "",

    "external_digest": {
      "sha256": "FILL IN: a digest published by an external source, or empty",
      "source": "FILL IN: where that digest came from",
      "reference": "FILL IN: URL or document for that digest"
    },

    "acquisition_reference": "FILL IN: how and when you obtained the artifact"
  },

  "runtime": {
    "path": "FILL IN: absolute path to the llama.cpp executable you built or chose",
    "implementation": "llama.cpp",
    "expected_version": "FILL IN: the version string you expect it to report",
    "acquisition_reference": "FILL IN: how and when you obtained the binary"
  },

  "selection": {
    "declared_by": "FILL IN: your name",
    "declared_at": "FILL IN: ISO-8601",
    "rationale": "FILL IN: why you chose this model and this runtime"
  }
}
"""


def write_template(path: str | Path) -> Path:
    """Write an unverified template for a human to complete.

    The one place this package writes a declaration-shaped file, and it writes a
    blank: every decision-bearing field is a placeholder, so an unfilled template
    is refused by :func:`load_declaration` rather than accepted.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(TEMPLATE, encoding="utf-8")
    return target


__all__ = [
    "DEPLOYMENT_RELPATH",
    "DEPLOYMENT_SCHEMA",
    "TEMPLATE",
    "Deployment",
    "DeploymentState",
    "deployment_path",
    "load_declaration",
    "write_template",
]
