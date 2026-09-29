"""The one explicit configuration source for the M006 runtime.

M003 already established the strict properties, and this module preserves them
rather than relaxing them for convenience:

* **one explicit source** -- a single file the human points the laboratory at
* **no fallback search** -- a missing file is a state, not a reason to look around
* **no automatic download** -- nothing here fetches anything
* **no hidden model discovery** -- no scanning for ``*.gguf``
* **no silent substitution** -- a declared digest that does not match is a refusal

A configuration that names a model the laboratory cannot verify is rejected
loudly. And a configuration that does not exist produces
:attr:`ConfigurationState.NOT_CONFIGURED`, which is a legitimate, tested state --
not an error to be worked around.

Why no default file
-------------------
A default path would let a model be "present" by accident. The human supplies the
path, so the absence of a model is always an explicit human decision rather than
a consequence of where the process happened to start.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from babylab.runtime.runtime import ModelDeclaration

#: Accepted schema. A file declaring anything else is refused rather than
#: partially interpreted.
CONFIG_SCHEMA = "babylab/runtime-config/v1"

#: Where the human is told to put weights. Not searched, not scanned.
DEFAULT_WEIGHTS_DIRNAME = "human_control/experiment_config/weights"


class ConfigurationState(str, enum.Enum):
    """The result of asking "is a model configured?"."""

    #: No configuration was supplied. The correct state for a fresh laboratory.
    NOT_CONFIGURED = "NOT_CONFIGURED"
    #: A configuration was supplied and is internally consistent.
    LOADED = "LOADED"
    #: A configuration was supplied but is wrong. Detail is carried.
    INVALID = "INVALID"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class RuntimeConfiguration:
    """A parsed, validated configuration. Absent configuration is not one of these."""

    declaration: ModelDeclaration
    policy: dict[str, Any] = field(default_factory=dict)
    declared_at: str = ""
    source_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONFIG_SCHEMA,
            "declared_at": self.declared_at,
            "source_path": self.source_path,
            "model": self.declaration.to_dict(),
            "policy": self.policy,
        }


@dataclass(frozen=True)
class ConfigurationResult:
    """The honest answer to "what model is configured?"."""

    state: ConfigurationState
    configuration: RuntimeConfiguration | None = None
    detail: str = ""

    @property
    def configured(self) -> bool:
        return self.state is ConfigurationState.LOADED

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "detail": self.detail,
            "configuration": self.configuration.to_dict() if self.configuration else None,
        }


def expected_weights_location(repository_root: Path) -> Path:
    """Where the human should place weights. Reported, never scanned."""
    return Path(repository_root) / DEFAULT_WEIGHTS_DIRNAME


def load_configuration(path: str | Path | None) -> ConfigurationResult:
    """Load one configuration file, or explain why there is none.

    ``None`` and a missing file both yield :attr:`ConfigurationState.NOT_CONFIGURED`.
    That is the state a laboratory with no model is supposed to be in, and it is
    what most M006 tests exercise.
    """
    if path is None:
        return ConfigurationResult(
            state=ConfigurationState.NOT_CONFIGURED,
            detail=(
                "no runtime configuration was supplied. The laboratory does not "
                "search for one, and does not download a model. Supply an "
                "explicit configuration file to enable inference."
            ),
        )

    target = Path(path)
    if not target.is_file():
        return ConfigurationResult(
            state=ConfigurationState.NOT_CONFIGURED,
            detail=(
                f"configuration file not found at {target}. The laboratory does "
                "not search other locations and does not create one."
            ),
        )

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ConfigurationResult(
            state=ConfigurationState.INVALID,
            detail=f"configuration at {target} could not be read: {exc}",
        )

    schema = payload.get("schema")
    if schema != CONFIG_SCHEMA:
        return ConfigurationResult(
            state=ConfigurationState.INVALID,
            detail=(
                f"configuration declares schema {schema!r}; this laboratory "
                f"implements {CONFIG_SCHEMA!r}. Refusing to partially interpret it."
            ),
        )

    model = payload.get("model")
    if not isinstance(model, dict):
        return ConfigurationResult(
            state=ConfigurationState.INVALID,
            detail="configuration has no 'model' object",
        )

    sha256 = str(model.get("sha256", "")).strip().lower()
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        return ConfigurationResult(
            state=ConfigurationState.INVALID,
            detail=(
                "model.sha256 must be a 64-character hex digest. The laboratory "
                "will not load an artifact of unverified identity, and will not "
                "derive the digest from the file itself."
            ),
        )

    model_path = str(model.get("path", "")).strip()
    if not model_path:
        return ConfigurationResult(
            state=ConfigurationState.INVALID,
            detail="model.path must name the artifact explicitly; the laboratory "
                   "does not search for weights",
        )

    declaration = ModelDeclaration(
        adapter_id=str(model.get("adapter_id", "")).strip(),
        model_path=model_path,
        sha256=sha256,
        model_family=str(model.get("family", "")),
        model_name=str(model.get("name", "")),
        quantization=str(model.get("quantization", "")),
        context_length=int(model.get("context_length", 2048)),
        model_size_bytes=(
            int(model["size_bytes"]) if model.get("size_bytes") is not None else None
        ),
        runtime_binary=(str(model["runtime_binary"])
                        if model.get("runtime_binary") else None),
        runtime_version=str(model.get("runtime_version", "")),
        license=str(model.get("license", "")),
        license_url=str(model.get("license_url", "")),
        source_url=str(model.get("source_url", "")),
        declared_by=str(payload.get("declared_by", "")),
        notes=str(model.get("notes", "")),
    )

    if not declaration.adapter_id:
        return ConfigurationResult(
            state=ConfigurationState.INVALID,
            detail=(
                "model.adapter_id must name the runtime explicitly. The "
                "laboratory will not choose a runtime on the operator's behalf."
            ),
        )

    return ConfigurationResult(
        state=ConfigurationState.LOADED,
        configuration=RuntimeConfiguration(
            declaration=declaration,
            policy=payload.get("policy", {}) if isinstance(payload.get("policy"), dict) else {},
            declared_at=str(payload.get("declared_at", "")),
            source_path=str(target),
        ),
    )


__all__ = [
    "CONFIG_SCHEMA",
    "ConfigurationResult",
    "ConfigurationState",
    "DEFAULT_WEIGHTS_DIRNAME",
    "RuntimeConfiguration",
    "expected_weights_location",
    "load_configuration",
]
