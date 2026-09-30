"""M010 runtime identity, kept separate from model identity.

Two independent subjects
------------------------
::

    MODEL     M    the artifact: a file, identified by its bytes
    RUNTIME   R    the executor: a binary, identified by its path and version

``M != R``. A verified model implies nothing about the runtime that will load
it, and a working runtime implies nothing about which model it was given. The
most common way a laboratory overstates itself is to report "the model works"
when what was actually demonstrated was "a binary ran a file".

So this module records runtime identity on its own terms, and
:mod:`foundation.inference` refuses to produce a result unless *both* are
established. ``M`` alone is not a runtime, and ``R`` alone is not a model.

GPU claims
----------
Requested GPU layers and executed GPU work are different facts.
``n_gpu_layers > 0`` is what the *caller asked for*; it is evidence of a
configuration value and of nothing else. This module records both
separately, and reports GPU usage as ``UNAVAILABLE`` whenever the runtime did
not independently establish it. Guessing from the presence of an NVIDIA card,
or from a successful run, is exactly the inference the milestone forbids.
"""

from __future__ import annotations

import enum
import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Probe ceiling for ``--version``. Loads no weights, touches no VRAM.
VERSION_PROBE_TIMEOUT_SECONDS = 20.0


class RuntimeState(str, enum.Enum):
    """What is known about the executor."""

    NOT_CONFIGURED = "NOT_CONFIGURED"
    BINARY_MISSING = "BINARY_MISSING"
    NOT_EXECUTABLE = "NOT_EXECUTABLE"
    PROBE_FAILED = "PROBE_FAILED"
    VERIFIED = "VERIFIED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class GpuUsage(str, enum.Enum):
    """GPU usage, reported at the strength it was actually established."""

    #: No GPU backend was requested.
    NOT_REQUESTED = "NOT_REQUESTED"
    #: Layers were requested but the runtime never confirmed execution.
    REQUESTED_NOT_CONFIRMED = "REQUESTED_NOT_CONFIRMED"
    #: The runtime's own output established GPU execution.
    CONFIRMED = "CONFIRMED"
    #: GPU execution could not be established either way.
    UNAVAILABLE = "UNAVAILABLE"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class RuntimeIdentity:
    """Identity of the executor, independent of the artifact it may load."""

    implementation: str = "llama.cpp"
    adapter_id: str = "llamacpp"
    state: RuntimeState = RuntimeState.NOT_CONFIGURED
    version: str = "UNAVAILABLE"
    version_source: str = "none"
    binary_path: str = ""
    binary_sha256: str = "UNAVAILABLE"
    binary_size_bytes: int = 0
    #: A binary is a file whose identity is its digest. A Windows PE that cannot
    #: be hashed is a weaker claim and is reported as such.
    binary_digest_basis: str = "none"
    invocation_configuration: dict[str, Any] = field(default_factory=dict)
    gpu_requested_layers: int | None = None
    gpu_usage: GpuUsage = GpuUsage.UNAVAILABLE
    gpu_backend: str = "UNAVAILABLE"
    build_information: str = "UNAVAILABLE"
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def verified(self) -> bool:
        return self.state is RuntimeState.VERIFIED

    @property
    def gpu_claimed(self) -> bool:
        """True only when the runtime itself established GPU work.

        A caller asking for layers is not evidence, so this property never
        reports ``REQUESTED_NOT_CONFIRMED`` as usage.
        """
        return self.gpu_usage is GpuUsage.CONFIRMED

    def to_dict(self) -> dict[str, Any]:
        return {
            "implementation": self.implementation,
            "adapter_id": self.adapter_id,
            "state": self.state.value,
            "verified": self.verified,
            "version": self.version,
            "version_source": self.version_source,
            "binary_path": self.binary_path,
            "binary_sha256": self.binary_sha256,
            "binary_size_bytes": self.binary_size_bytes,
            "binary_digest_basis": self.binary_digest_basis,
            "invocation_configuration": dict(self.invocation_configuration),
            "gpu_requested_layers": self.gpu_requested_layers,
            "gpu_usage": self.gpu_usage.value,
            "gpu_claimed": self.gpu_claimed,
            "gpu_backend": self.gpu_backend,
            "build_information": self.build_information,
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }


def _absent(state: RuntimeState, detail: str, binary: str = "") -> RuntimeIdentity:
    return RuntimeIdentity(state=state, detail=detail, binary_path=binary)


def sha256_binary(path: str | Path) -> tuple[str, str]:
    """Hash a binary, returning ``(digest, basis)``.

    The basis is reported alongside the digest because a hash is only as
    meaningful as its source. ``UNAVAILABLE`` with an explanation is more
    useful than a digest obtained by hashing something other than the binary.
    """
    target = Path(path)
    try:
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            while True:
                chunk = handle.read(4 * 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest(), "sha256 over the named binary"
    except OSError as exc:
        return "UNAVAILABLE", f"could not hash the binary: {exc}"


def probe_version(binary: str | Path) -> tuple[str, str, str]:
    """Ask the binary what it is. Returns ``(version, source, raw_first_line)``.

    Only the explicitly named binary is invoked. There is no ``PATH`` search and
    no fallback to a second binary, because a runtime that silently swaps its
    own executor is not the runtime that was declared.
    """
    command = [str(binary), "--version"]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=VERSION_PROBE_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "UNAVAILABLE", f"probe failed: {type(exc).__name__}: {exc}", ""

    output = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode != 0 or not output:
        return (
            "UNAVAILABLE",
            f"binary exited {completed.returncode} without a version string",
            output[:200],
        )
    first = output.splitlines()[0].strip()
    return first[:200], "binary --version output", first


def identify_runtime(
    binary: str | Path | None,
    *,
    declared_version: str = "",
    gpu_requested_layers: int | None = None,
    invoker=None,
) -> RuntimeIdentity:
    """Establish what the named runtime is, and whether it runs.

    Existence, then executability, then identity, then version. The digest is
    computed from the binary's own bytes; a version string copied into the
    declaration is reported as a declaration and never substituted for a probe.
    """
    if not binary:
        return _absent(
            RuntimeState.NOT_CONFIGURED,
            "no runtime binary was named; the laboratory does not build, "
            "download, or search for one",
        )

    path = Path(binary)
    if not path.is_file():
        return _absent(
            RuntimeState.BINARY_MISSING,
            f"runtime binary not found at {path}; the laboratory does not search "
            "PATH and does not install anything",
            str(path),
        )

    size = path.stat().st_size
    if size == 0:
        return _absent(
            RuntimeState.NOT_EXECUTABLE,
            f"runtime binary at {path} is zero bytes",
            str(path),
        )

    digest, basis = sha256_binary(path)

    if invoker is None:
        version, source, raw = probe_version(path)
        raw_output = raw
    else:
        version, source, raw = invoker(path)
        raw_output = raw

    if version == "UNAVAILABLE":
        return RuntimeIdentity(
            state=RuntimeState.PROBE_FAILED,
            version="UNAVAILABLE",
            version_source=source,
            binary_path=str(path),
            binary_sha256=digest,
            binary_size_bytes=size,
            binary_digest_basis=basis,
            gpu_requested_layers=gpu_requested_layers,
            detail=(
                f"the binary exists and hashed, but did not report a version: "
                f"{source}"
            ),
            evidence={"raw_probe_output": raw_output},
        )

    mismatch = ""
    if declared_version and declared_version not in version:
        mismatch = (
            f" the declaration states {declared_version!r}, which the binary's "
            f"own output does not contain."
        )

    return RuntimeIdentity(
        state=RuntimeState.VERIFIED,
        version=version,
        version_source=source,
        binary_path=str(path),
        binary_sha256=digest,
        binary_size_bytes=size,
        binary_digest_basis=basis,
        gpu_requested_layers=gpu_requested_layers,
        build_information=(
            "version string read from the binary itself; no separate build "
            "metadata is available from the executable"
        ),
        detail=(
            f"binary executed and identified itself as {version}.{mismatch} "
            "This establishes the runtime only. It says nothing about any model."
        ),
        evidence={"raw_probe_output": raw_output, "declared_version": declared_version},
    )


def resolve_gpu_usage(
    *,
    requested_layers: int | None,
    reported_backend: str,
    runner_evidence: str = "",
) -> tuple[GpuUsage, str]:
    """Decide what can honestly be said about GPU execution.

    Two independent pieces of evidence are required before GPU usage is
    claimed: the runtime naming a non-CPU backend, and the runtime's own output
    containing affirmative offload evidence. A configured layer count is
    configuration, not execution, and a CPU-only report after a GPU was
    requested is a finding rather than a success.
    """
    backend = (reported_backend or "").strip().lower()

    if requested_layers is not None and requested_layers <= 0:
        return GpuUsage.NOT_REQUESTED, "no GPU layers were requested"

    if backend in {"", "unavailable"}:
        return (
            GpuUsage.UNAVAILABLE,
            "the runtime reported no backend, so GPU usage cannot be "
            "established in either direction",
        )

    if backend == "cpu":
        if requested_layers:
            return (
                GpuUsage.REQUESTED_NOT_CONFIRMED,
                f"{requested_layers} GPU layers were requested but the runtime "
                "reported the CPU backend; the run completed on CPU",
            )
        return GpuUsage.NOT_REQUESTED, "the runtime reported the CPU backend"

    # A non-CPU backend is a necessary condition, not a sufficient one.
    if not runner_evidence:
        return (
            GpuUsage.REQUESTED_NOT_CONFIRMED,
            f"the runtime reported the {backend} backend, but printed no "
            "affirmative offload evidence; requested GPU layers are not "
            "evidence of executed GPU work",
        )
    return (
        GpuUsage.CONFIRMED,
        f"the runtime reported the {backend} backend and printed offload "
        f"evidence ({runner_evidence})",
    )


def default_invocation_configuration(
    *,
    n_gpu_layers: int | None,
    threads: int | None,
    context_length: int,
) -> dict[str, Any]:
    """The invocation parameters, recorded rather than implied.

    Written out even when a value is unset, so a reader can see that
    ``threads: null`` was a decision rather than an omission.
    """
    return {
        "n_gpu_layers": n_gpu_layers,
        "threads": threads,
        "context_length": context_length,
        "deterministic_because": (
            "sampling parameters are set explicitly below; nothing relies on an "
            "undocumented runtime default"
        ),
    }


__all__ = [
    "VERSION_PROBE_TIMEOUT_SECONDS",
    "GpuUsage",
    "RuntimeIdentity",
    "RuntimeState",
    "default_invocation_configuration",
    "identify_runtime",
    "probe_version",
    "resolve_gpu_usage",
    "sha256_binary",
]
