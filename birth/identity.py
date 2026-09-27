"""Model identity: what is configured versus what is actually on disk.

The distinction this module enforces
------------------------------------
``CONFIGURED`` and ``INSTALLED`` are different facts, and a system that blurs
them will eventually report a model that is not there.

* **Configured** — a human wrote down what they intend to use
  (:mod:`birth.config`).
* **Installed** — the weight file exists at the configured path *and* its
  SHA-256 matches the configured digest.
* **Healthy** — the runtime binary is present and answers a version query.

Each is reported separately. A configuration with no weights is
``MODEL_NOT_INSTALLED``, never a silent download and never a substitute.

The digest check is the reproducibility anchor
----------------------------------------------
If the bytes on disk do not hash to the configured value, the answer is
``MODEL_INTEGRITY_MISMATCH`` and the model is not usable, even though a file is
present and a runtime could probably load it. Same size and same name are not
evidence; the digest is.

Hashing cost
------------
Weight files are gigabytes. Verification streams the file in chunks rather than
reading it whole, and the result is memoised per (path, size, mtime) so a status
display does not re-hash 4 GB on every redraw. The memo is a cache of a pure
function, so it cannot weaken the check: a changed file changes its size or
mtime and forces a re-hash.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from babylab.errors import ValidationError
from babylab.paths import ProjectPaths, default_paths
from birth.authorship import ArtifactKind, AuthorshipClass, classify_artifact
from birth.config import FoundationConfig


class ModelStatus(str, enum.Enum):
    """Installation and runtime state of the configured model."""

    #: No configuration exists at all. The laboratory has no foundation model.
    NOT_CONFIGURED = "NOT_CONFIGURED"
    #: Configured, but the weight file is not on disk.
    MODEL_NOT_INSTALLED = "MODEL_NOT_INSTALLED"
    #: The weight file exists but its digest differs from the configured one.
    MODEL_INTEGRITY_MISMATCH = "MODEL_INTEGRITY_MISMATCH"
    #: Weights are present and correct, but the runtime binary is missing.
    RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"
    #: Weights are present and correct, but nobody has checked the runtime.
    #:
    #: This exists because "we did not look" and "we looked and it is fine" are
    #: different facts, and collapsing them is how a display ends up promising a
    #: model is ready when nothing has run it. The read-only inspection path
    #: (``birth.status.inspect`` with no probe) reports this, and the Observatory
    #: shows it. The ceremony never reports it: it always installs a real probe,
    #: so by the time it writes a record the runtime genuinely has been checked.
    RUNTIME_UNVERIFIED = "RUNTIME_UNVERIFIED"
    #: Weights and runtime are both present and correct.
    READY = "READY"
    #: The runtime is present but failed a health query.
    ERROR = "ERROR"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value

    @property
    def is_usable(self) -> bool:
        """True only when a real load could plausibly succeed.

        Deliberately narrow. ``ERROR`` is not usable even though the files are
        present, because a runtime that answers its version query with an error
        is not a runtime you can generate with. ``RUNTIME_UNVERIFIED`` is not
        usable either: an unrun runtime is an unknown runtime, and reporting it
        as usable would let a read-only observer imply the model has been
        exercised when it has not.
        """
        return self is ModelStatus.READY

    @property
    def is_inherited(self) -> bool:
        """Every status here describes third-party substrate, never subject work."""
        return True


@dataclass(frozen=True)
class ModelIdentity:
    """Everything needed to name one specific model installation."""

    model_family: str
    model_name: str
    model_revision: str
    quantization: str
    model_sha256: str
    model_size_bytes: int | None
    runtime: str
    runtime_version: str
    context_length: int
    configuration_hash: str
    source_url: str = ""
    license: str = ""
    license_url: str = ""
    installed_at: str = ""
    #: Digest of the runtime binary, when one was configured. Lets a reader tell
    #: "llama.cpp b4521" from a different build that also calls itself b4521.
    runtime_binary_sha256: str = ""
    authorship: AuthorshipClass = AuthorshipClass.INHERITED_PRETRAINED
    authorship_basis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_family": self.model_family,
            "model_name": self.model_name,
            "model_revision": self.model_revision,
            "quantization": self.quantization,
            "model_sha256": self.model_sha256,
            "model_size_bytes": self.model_size_bytes,
            "runtime": self.runtime,
            "runtime_version": self.runtime_version,
            "context_length": self.context_length,
            "configuration_hash": self.configuration_hash,
            "source_url": self.source_url,
            "license": self.license,
            "license_url": self.license_url,
            "installed_at": self.installed_at,
            "runtime_binary_sha256": self.runtime_binary_sha256,
            "authorship_classification": self.authorship.value,
            "authorship_basis": self.authorship_basis,
        }

    @classmethod
    def from_config(cls, config: FoundationConfig) -> "ModelIdentity":
        record = classify_artifact(
            ArtifactKind.MODEL_WEIGHTS,
            declared=None,
            evidence={"model_sha256": config.model_sha256},
        )
        return cls(
            model_family=config.model_family,
            model_name=config.model_name,
            model_revision=config.model_revision,
            quantization=config.quantization,
            model_sha256=config.model_sha256,
            model_size_bytes=config.model_size_bytes,
            runtime=config.runtime.value,
            runtime_version=config.runtime_version,
            context_length=config.context_length,
            configuration_hash=config.configuration_hash(),
            source_url=config.source_url,
            license=config.license,
            license_url=config.license_url,
            installed_at=config.installed_at,
            runtime_binary_sha256=config.runtime_binary_sha256,
            authorship=record.classification,
            authorship_basis=record.basis,
        )

    @classmethod
    def from_dict(cls, data: Any) -> "ModelIdentity":
        """Rebuild an identity from its recorded form.

        Authorship is recomputed rather than read back, for the same reason it is
        never read from a payload when creating one: a stored classification that
        disagreed with the artifact's kind would mean the record had been edited,
        and recomputing makes that visible. The recorded basis is kept for
        comparison by :func:`authorship_matches`.
        """
        if not isinstance(data, dict):
            raise ValidationError("model identity must be a JSON object")
        recorded_class = data.get("authorship_classification")
        identity = cls(
            model_family=data["model_family"],
            model_name=data["model_name"],
            model_revision=data["model_revision"],
            quantization=data["quantization"],
            model_sha256=data["model_sha256"],
            model_size_bytes=data.get("model_size_bytes"),
            runtime=data["runtime"],
            runtime_version=data["runtime_version"],
            context_length=data["context_length"],
            configuration_hash=data["configuration_hash"],
            source_url=data.get("source_url", "") or "",
            license=data.get("license", "") or "",
            license_url=data.get("license_url", "") or "",
            installed_at=data.get("installed_at", "") or "",
            runtime_binary_sha256=data.get("runtime_binary_sha256", "") or "",
            authorship=classify_artifact(ArtifactKind.MODEL_WEIGHTS).classification,
            authorship_basis=classify_artifact(ArtifactKind.MODEL_WEIGHTS).basis,
        )
        if recorded_class and recorded_class != identity.authorship.value:
            raise ValidationError(
                f"record claims authorship {recorded_class!r} for a pretrained "
                f"weight file; the only correct classification is "
                f"{identity.authorship.value}. The record has been edited."
            )
        return identity

    def short_hash(self) -> str:
        return self.model_sha256[:12]


@dataclass
class InstallationReport:
    """The outcome of checking a configuration against the disk."""

    status: ModelStatus
    detail: str
    identity: ModelIdentity | None = None
    model_path: Path | None = None
    observed_sha256: str = ""
    observed_size_bytes: int | None = None
    runtime_available: bool = False
    runtime_detail: str = ""
    observed_backend: str = ""
    checked_at: str = ""
    notes: tuple[str, ...] = ()

    @property
    def is_installed(self) -> bool:
        """True when the configured weights are present and match the digest."""
        return self.status in (
            ModelStatus.READY,
            ModelStatus.RUNTIME_UNAVAILABLE,
            ModelStatus.ERROR,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "detail": self.detail,
            "identity": self.identity.to_dict() if self.identity else None,
            "model_path": str(self.model_path) if self.model_path else None,
            "observed_sha256": self.observed_sha256,
            "observed_size_bytes": self.observed_size_bytes,
            "runtime_available": self.runtime_available,
            "runtime_detail": self.runtime_detail,
            "observed_backend": self.observed_backend,
            "checked_at": self.checked_at,
            "notes": list(self.notes),
        }

    def describe(self) -> str:
        return f"{self.status.value}: {self.detail}"


class DigestCache:
    """Memoises file digests keyed by identity-and-size-and-mtime.

    A pure-function cache, so it cannot turn a mismatch into a pass: any change
    to the file changes the key and forces a fresh hash.
    """

    def __init__(self) -> None:
        self._entries: dict[str, tuple[tuple[int, int], str]] = {}

    def digest(self, path: Path) -> str:
        from babylab.hashing import file_sha256

        key = str(path)
        try:
            info = path.stat()
            stamp = (info.st_size, info.st_mtime_ns)
        except OSError:
            self._entries.pop(key, None)
            return ""
        cached = self._entries.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        digest = file_sha256(path)
        self._entries[key] = (stamp, digest)
        return digest

    def clear(self) -> None:
        self._entries.clear()


def resolve_model_identity(
    config: FoundationConfig | None,
    paths: ProjectPaths | None = None,
    runtime_probe=None,
    cache: DigestCache | None = None,
    now: str = "",
) -> InstallationReport:
    """Check a configuration against reality and report what is true.

    ``runtime_probe`` is a callable taking the config and returning
    ``(available: bool, detail: str, observed_backend: str)``. It is injected
    rather than imported so that identity resolution stays a pure check with no
    subprocess and no side effects, and so tests can supply a probe without
    pretending a runtime exists.
    """
    paths = paths or default_paths()

    if config is None:
        return InstallationReport(
            status=ModelStatus.NOT_CONFIGURED,
            detail=(
                "no foundation model has been configured. The laboratory does "
                "not choose, download, or substitute a model on its own."
            ),
            checked_at=now,
        )

    identity = ModelIdentity.from_config(config)
    model_path = config.resolve_model_path(paths)

    if not model_path.is_file():
        return InstallationReport(
            status=ModelStatus.MODEL_NOT_INSTALLED,
            detail=(
                f"configured model {config.model_name!r} is not present at "
                f"{model_path}. Install the exact weights named by the "
                "configuration; nothing will be fetched automatically."
            ),
            identity=identity,
            model_path=model_path,
            checked_at=now,
        )

    observed_size = model_path.stat().st_size
    observed = (cache.digest(model_path) if cache else _digest(model_path))
    notes: list[str] = []
    if observed != config.model_sha256:
        return InstallationReport(
            status=ModelStatus.MODEL_INTEGRITY_MISMATCH,
            detail=(
                f"weights at {model_path} hash to {observed[:12]}..., but the "
                f"configuration declares {config.model_sha256[:12]}.... The file "
                "present is not the file configured, so it will not be used."
            ),
            identity=identity,
            model_path=model_path,
            observed_sha256=observed,
            observed_size_bytes=observed_size,
            checked_at=now,
            notes=tuple(notes),
        )

    if config.model_size_bytes is not None and config.model_size_bytes != observed_size:
        # Not fatal: the digest already proves identity. Recorded because a size
        # disagreement means the configuration was edited by hand at some point.
        notes.append(
            f"configuration records {config.model_size_bytes} bytes but the file "
            f"is {observed_size}; the digest matches, so the configuration's size "
            "field is stale rather than the file being wrong"
        )

    if runtime_probe is None:
        # The weights are verified; the runtime is not. Reporting READY here
        # would tell a reader the model is ready to use when no process has run
        # it, so the status says exactly what was and was not established.
        return InstallationReport(
            status=ModelStatus.RUNTIME_UNVERIFIED,
            detail=(
                "weights present and matching; the runtime was NOT checked, so "
                "this is not a claim that the model can be run"
            ),
            identity=identity,
            model_path=model_path,
            observed_sha256=observed,
            observed_size_bytes=observed_size,
            checked_at=now,
            notes=tuple(notes),
        )

    available, detail, observed_backend = runtime_probe(config)
    if not available:
        return InstallationReport(
            status=ModelStatus.RUNTIME_UNAVAILABLE,
            detail=(
                f"weights are present and verified, but the configured runtime "
                f"{config.runtime.value} is not usable: {detail}"
            ),
            identity=identity,
            model_path=model_path,
            observed_sha256=observed,
            observed_size_bytes=observed_size,
            runtime_available=False,
            runtime_detail=detail,
            observed_backend=observed_backend,
            checked_at=now,
            notes=tuple(notes),
        )

    return InstallationReport(
        status=ModelStatus.READY,
        detail=f"weights verified and runtime {config.runtime.value} is available",
        identity=identity,
        model_path=model_path,
        observed_sha256=observed,
        observed_size_bytes=observed_size,
        runtime_available=True,
        runtime_detail=detail,
        observed_backend=observed_backend,
        checked_at=now,
        notes=tuple(notes),
    )


def _digest(path: Path) -> str:
    from babylab.hashing import file_sha256

    return file_sha256(path)


def status_for_terminal(report: InstallationReport) -> str:
    """One word for the status line, as the specification's sketch shows."""
    if report.status is ModelStatus.READY:
        return "READY"
    return report.status.value


def require_usable(report: InstallationReport) -> ModelIdentity:
    """Return the identity, or refuse because the model cannot be used.

    Raising rather than returning ``None`` is deliberate: every caller that
    needs a model needs a *usable* one, and a caller that ignores the return
    value cannot accidentally proceed against an unusable installation.
    """
    if not report.status.is_usable or report.identity is None:
        raise ValidationError(
            f"the configured foundation model is not usable: {report.describe()}"
        )
    return report.identity


__all__ = [
    "DigestCache",
    "InstallationReport",
    "ModelIdentity",
    "ModelStatus",
    "require_usable",
    "resolve_model_identity",
    "status_for_terminal",
]
