"""The explicit foundation-model configuration.

Why configuration and not discovery
-----------------------------------
The specification is emphatic: do not download a model, do not silently select
one, do not silently change versions. Every one of those is a way for the
experiment to become unreproducible without anyone deciding to make it so.

So this module has no search path, no default, and no fallback. There is exactly
one configured model, named by the human in
``human_control/experiment_config/foundation.json``, and the file records enough
about it that a reader in ten years can tell whether the same weights are on
disk.

Reproducibility
---------------
:class:`FoundationConfig` has a ``configuration_hash``: a digest over the
canonical encoding of every field that affects what the model *is*. Two
laboratories with the same configuration hash were running the same model. That
hash goes into the birth record, so a birth can be reconstructed exactly.

What is deliberately *not* recorded here
-----------------------------------------
The model file's own digest is recorded (:attr:`FoundationConfig.model_sha256`),
but the weights are not placed under version control. A multi-gigabyte binary in
Git is in every clone forever; the digest is what makes the installation
checkable, and it is far smaller than the thing it describes.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from babylab.errors import ConfigurationError, ValidationError
from babylab.hashing import canonical_bytes, content_hash, sha256_hex
from babylab.paths import ProjectPaths, default_paths
from babylab.storage import atomic_write_text

FOUNDATION_CONFIG_SCHEMA = "babylab/foundation-config/v1"

#: Bumped when the meaning of a field changes, so an old file is not silently
#: reinterpreted under new semantics.
FOUNDATION_CONFIG_VERSION = 1

#: Fields covered by :meth:`FoundationConfig.configuration_hash`. Anything that
#: changes what the model *is* belongs here; anything that changes how a
#: particular run is configured (seed, per-request options) does not.
IDENTITY_FIELDS = (
    "schema",
    "model_family",
    "model_name",
    "model_revision",
    "quantization",
    "model_file",
    "model_sha256",
    "model_size_bytes",
    "runtime",
    "runtime_version",
    "context_length",
    "generation",
    "sampling",
    "hardware",
    "source_url",
    "license",
)


class RuntimeKind(str, enum.Enum):
    """Which local runtime serves the model.

    Named, not discovered, for the same reason the model is named: a research
    record that says "some runtime" cannot be reproduced.
    """

    LLAMA_CPP = "llama.cpp"
    #: Deterministic in-process stand-in. Never a substitute for a real model;
    #: it exists so the plumbing can be tested without weights.
    FAKE = "fake"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


class HardwareBackend(str, enum.Enum):
    """Compute backend. Recorded as declared intent and as observed fact."""

    CUDA = "cuda"
    VULKAN = "vulkan"
    CPU = "cpu"
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass(frozen=True)
class GenerationConfig:
    """Deterministic settings for reproducible generation."""

    max_tokens: int = 512
    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = 0
    repeat_penalty: float = 1.0
    stop: tuple[str, ...] = ()
    seed: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "stop", tuple(self.stop))
        if self.max_tokens < 1:
            raise ValidationError(f"max_tokens must be >= 1, got {self.max_tokens}")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValidationError(
                f"temperature must be within [0, 2], got {self.temperature}"
            )
        if not 0.0 <= self.top_p <= 1.0:
            raise ValidationError(f"top_p must be within [0, 1], got {self.top_p}")
        if self.top_k < 0:
            raise ValidationError(f"top_k must be >= 0, got {self.top_k}")
        if self.repeat_penalty <= 0.0:
            raise ValidationError(
                f"repeat_penalty must be > 0, got {self.repeat_penalty}"
            )
        if self.seed < 0:
            raise ValidationError(f"seed must be >= 0, got {self.seed}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repeat_penalty": self.repeat_penalty,
            "stop": list(self.stop),
            "seed": self.seed,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "GenerationConfig":
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise ValidationError("generation config must be an object")
        known = {f for f in cls.__dataclass_fields__}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValidationError(
                f"unknown generation config field(s): {unknown}. Refusing to "
                "ignore a field that may change what the model produces."
            )
        return cls(**data)


@dataclass(frozen=True)
class SamplingConfig:
    """Repetition and stop conditions, separated from token limits.

    Kept apart from :class:`GenerationConfig` because they answer different
    questions: "how many tokens" versus "when to stop and what to avoid
    repeating". Both affect reproducibility, so both are hashed.
    """

    repeat_penalty: float = 1.0
    stop: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stop", tuple(self.stop))
        if self.repeat_penalty <= 0.0:
            raise ValidationError(
                f"repeat_penalty must be > 0, got {self.repeat_penalty}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {"repeat_penalty": self.repeat_penalty, "stop": list(self.stop)}

    @classmethod
    def from_dict(cls, data: Any) -> "SamplingConfig":
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise ValidationError("sampling config must be an object")
        return cls(repeat_penalty=data.get("repeat_penalty", 1.0), stop=tuple(data.get("stop", ())))


@dataclass(frozen=True)
class HardwareConfig:
    """What the model is expected to run on, and what it actually ran on.

    Two separate fields on purpose. ``backend`` is what the human configured;
    ``observed_backend`` is what the runtime reported. Recording only the
    intent would let a silent fallback to CPU pass as a CUDA run, which is
    exactly the kind of discrepancy that invalidates a timing measurement.
    """

    backend: HardwareBackend = HardwareBackend.UNKNOWN
    gpu_name: str = ""
    gpu_memory_bytes: int | None = None
    gpu_layers: int | None = None
    cpu_threads: int | None = None
    cpu_threads_reported: str = ""

    def __post_init__(self) -> None:
        if self.gpu_memory_bytes is not None and self.gpu_memory_bytes < 0:
            raise ValidationError(
                f"gpu_memory_bytes must be >= 0, got {self.gpu_memory_bytes}"
            )
        if self.gpu_layers is not None and self.gpu_layers < 0:
            raise ValidationError(f"gpu_layers must be >= 0, got {self.gpu_layers}")
        if self.cpu_threads is not None and self.cpu_threads < 1:
            raise ValidationError(f"cpu_threads must be >= 1, got {self.cpu_threads}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend.value,
            "gpu_name": self.gpu_name,
            "gpu_memory_bytes": self.gpu_memory_bytes,
            "gpu_layers": self.gpu_layers,
            "cpu_threads": self.cpu_threads,
            "cpu_threads_reported": self.cpu_threads_reported,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "HardwareConfig":
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise ValidationError("hardware config must be an object")
        raw_backend = data.get("backend", HardwareBackend.UNKNOWN.value)
        try:
            backend = HardwareBackend(raw_backend)
        except ValueError as exc:
            raise ValidationError(
                f"unknown hardware backend {raw_backend!r}; expected one of "
                f"{sorted(item.value for item in HardwareBackend)}"
            ) from exc
        return cls(
            backend=backend,
            gpu_name=data.get("gpu_name", "") or "",
            gpu_memory_bytes=data.get("gpu_memory_bytes"),
            gpu_layers=data.get("gpu_layers"),
            cpu_threads=data.get("cpu_threads"),
            cpu_threads_reported=data.get("cpu_threads_reported", "") or "",
        )


@dataclass(frozen=True)
class FoundationConfig:
    """One explicitly configured pretrained foundation model.

    This is a *declaration by the human* of what the experiment intends to use.
    It is not evidence that the weights are present or correct; that is
    :mod:`birth.identity`'s job, and the two are deliberately separate so that
    "configured" and "installed" can never be confused.
    """

    model_family: str
    model_name: str
    model_revision: str
    quantization: str
    model_file: str
    model_sha256: str
    runtime: RuntimeKind
    runtime_version: str
    context_length: int
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    model_size_bytes: int | None = None
    runtime_binary: str = ""
    runtime_binary_sha256: str = ""
    installed_at: str = ""
    source_url: str = ""
    license: str = ""
    license_url: str = ""
    notes: str = ""
    declared_by: str = ""
    schema: str = FOUNDATION_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        for name in (
            "model_family",
            "model_name",
            "model_revision",
            "quantization",
            "model_file",
            "model_sha256",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"{name} must be a non-empty string, got {value!r}")
        if not isinstance(self.runtime_version, str) or not self.runtime_version.strip():
            raise ValidationError(
                "runtime_version must be a non-empty string. A runtime identified "
                "only as 'some version' is not reproducible, and a result that "
                "cannot be reproduced is not a result."
            )
        if len(self.model_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.model_sha256
        ):
            raise ValidationError(
                f"model_sha256 must be 64 lowercase hex characters, got "
                f"{self.model_sha256!r}"
            )
        if self.context_length < 1:
            raise ValidationError(
                f"context_length must be >= 1, got {self.context_length}"
            )
        if self.model_size_bytes is not None and self.model_size_bytes < 0:
            raise ValidationError(
                f"model_size_bytes must be >= 0, got {self.model_size_bytes}"
            )

    # -- identity ---------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "model_family": self.model_family,
            "model_name": self.model_name,
            "model_revision": self.model_revision,
            "quantization": self.quantization,
            "model_file": self.model_file,
            "model_sha256": self.model_sha256,
            "model_size_bytes": self.model_size_bytes,
            "runtime": self.runtime.value,
            "runtime_binary": self.runtime_binary,
            "runtime_binary_sha256": self.runtime_binary_sha256,
            "runtime_version": self.runtime_version,
            "context_length": self.context_length,
            "generation": self.generation.to_dict(),
            "sampling": self.sampling.to_dict(),
            "hardware": self.hardware.to_dict(),
            "installed_at": self.installed_at,
            "source_url": self.source_url,
            "license": self.license,
            "license_url": self.license_url,
            "notes": self.notes,
            "declared_by": self.declared_by,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "FoundationConfig":
        if not isinstance(data, dict):
            raise ValidationError("foundation config must be a JSON object")
        schema = data.get("schema")
        if schema != FOUNDATION_CONFIG_SCHEMA:
            raise ValidationError(
                f"unsupported foundation config schema {schema!r}; expected "
                f"{FOUNDATION_CONFIG_SCHEMA!r}"
            )
        known = set(cls.__dataclass_fields__)
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValidationError(
                f"unknown foundation config field(s): {unknown}. Refusing to "
                "ignore a field that may affect reproducibility."
            )
        raw_runtime = data.get("runtime")
        try:
            runtime = RuntimeKind(raw_runtime)
        except ValueError as exc:
            raise ValidationError(
                f"unknown runtime {raw_runtime!r}; expected one of "
                f"{sorted(item.value for item in RuntimeKind)}"
            ) from exc
        return cls(
            model_family=data["model_family"],
            model_name=data["model_name"],
            model_revision=data["model_revision"],
            quantization=data["quantization"],
            model_file=data["model_file"],
            model_sha256=data["model_sha256"],
            model_size_bytes=data.get("model_size_bytes"),
            runtime=runtime,
            runtime_binary=data.get("runtime_binary", "") or "",
            runtime_binary_sha256=data.get("runtime_binary_sha256", "") or "",
            runtime_version=data["runtime_version"],
            context_length=data["context_length"],
            generation=GenerationConfig.from_dict(data.get("generation")),
            sampling=SamplingConfig.from_dict(data.get("sampling")),
            hardware=HardwareConfig.from_dict(data.get("hardware")),
            installed_at=data.get("installed_at", "") or "",
            source_url=data.get("source_url", "") or "",
            license=data.get("license", "") or "",
            license_url=data.get("license_url", "") or "",
            notes=data.get("notes", "") or "",
            declared_by=data.get("declared_by", "") or "",
            schema=schema,
        )

    def identity_fields(self) -> dict[str, Any]:
        """The subset that defines *what model this is*."""
        body = self.to_dict()
        return {name: body[name] for name in IDENTITY_FIELDS}

    def configuration_hash(self) -> str:
        """Digest over :meth:`identity_fields`.

        Two configurations with the same hash describe the same model and the
        same way of running it. Recorded in the birth record so a birth is
        reproducible.
        """
        return content_hash(self.identity_fields())

    def resolve_model_path(self, paths: ProjectPaths | None = None) -> Path:
        """Absolute path of the weight file.

        An absolute ``model_file`` is used as-is; a relative one is resolved
        against ``var/models/``. Weights live outside version control, so
        relative paths are the normal case.
        """
        candidate = Path(self.model_file)
        if candidate.is_absolute():
            return candidate
        root = (paths or default_paths()).model_dir
        return root / candidate

    def runtime_identity(self) -> str:
        """A short, hashable identity for the runtime itself."""
        return f"{self.runtime.value}@{self.runtime_version}"


def config_path(paths: ProjectPaths | None = None) -> Path:
    return (paths or default_paths()).foundation_config


def load_config(paths: ProjectPaths | None = None) -> FoundationConfig:
    """Read the configured foundation model.

    Raises :class:`ConfigurationError` when no configuration exists. It does not
    return a default, and it does not go looking for a model: an unconfigured
    laboratory has no foundation model, and saying so is the correct answer.
    """
    target = config_path(paths)
    if not target.exists():
        raise ConfigurationError(
            f"no foundation model is configured. Expected a configuration at "
            f"{target}. The laboratory never chooses a model on its own; see "
            "docs/birth-architecture.md, 'Why the model is never chosen here'."
        )
    import json

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"foundation config at {target} is not valid JSON: {exc}") from exc
    try:
        return FoundationConfig.from_dict(data)
    except ValidationError as exc:
        raise ConfigurationError(f"foundation config at {target} is unusable: {exc}") from exc


def save_config(config: FoundationConfig, paths: ProjectPaths | None = None) -> Path:
    """Write the configuration. Caller is responsible for provenance.

    This does *not* touch the provenance ledger. Recording the configuration as
    a human-authored artifact is a separate, explicit step performed by
    :mod:`birth.service`, so that writing a file and signing a record about it
    cannot be confused.
    """
    from babylab.hashing import canonical_json

    target = config_path(paths)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, canonical_json(config.to_dict()) + "\n")
    return target


def digest_of_file(path: Path) -> str:
    """Streaming SHA-256 of a file. Used to verify an installation."""
    from babylab.hashing import file_sha256

    return file_sha256(path)


def canonical_config_digest(config: FoundationConfig) -> str:
    """Alias kept explicit so call sites read as intent rather than mechanics."""
    return sha256_hex(canonical_bytes(config.identity_fields()))


__all__ = [
    "FOUNDATION_CONFIG_SCHEMA",
    "FOUNDATION_CONFIG_VERSION",
    "FoundationConfig",
    "GenerationConfig",
    "HardwareBackend",
    "HardwareConfig",
    "RuntimeKind",
    "SamplingConfig",
    "config_path",
    "digest_of_file",
    "load_config",
    "save_config",
]
