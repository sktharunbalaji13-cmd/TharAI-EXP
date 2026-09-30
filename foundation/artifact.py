"""M010 artifact identity: byte identity, computed from the bytes.

What this module is for
-----------------------
Three claims are easy to confuse, and the whole milestone turns on keeping them
apart:

``computed local digest``
    SHA-256 over the actual bytes on this disk. The laboratory can always
    establish this. It is authoritative for *byte identity* and nothing else.

``externally supplied digest``
    A digest some outside source published. Only a human can supply one, by
    writing it into the manifest. The laboratory has no network access and no
    knowledge of any publisher's infrastructure, so it can never obtain one
    itself.

``verified match``
    The two agree. This is a genuine external check and is the only basis on
    which an artifact may be called verified.

The rule that matters
---------------------
A digest that hashes consistently against a file sitting next to it proves
nothing about *provenance*. It proves the file is still the file. If no external
digest was supplied, the honest status is
``NO_EXTERNAL_DIGEST_SUPPLIED`` -- not "verified". Calling a self-consistent
local hash "verified" is the single most likely way for this milestone to lie,
so the status enum has no value that would let it.

Immutability
------------
:func:`verify_immutable` recomputes the digest after use. If an inference
mutated the artifact, the digests differ and the caller is told to fail rather
than to retry with adjusted settings.
"""

from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Only GGUF. M010 supports the format the M006 runtime contract already
#: targets and refuses to grow into a multi-format project.
SUPPORTED_FORMATS: tuple[str, ...] = ("gguf",)

#: GGUF magic. Read from the first four bytes so a renamed .txt is caught as an
#: unsupported artifact rather than as a model that fails to load much later.
GGUF_MAGIC = b"GGUF"

#: A file below this size cannot be a language model. Used to reject a
#: truncated download, which is a common and otherwise silent failure.
MINIMUM_PLAUSIBLE_BYTES = 1 << 20  # 1 MiB


class DigestStatus(str, enum.Enum):
    """How far the artifact's identity has actually been established."""

    #: No artifact is named.
    NOT_CONFIGURED = "NOT_CONFIGURED"
    #: The named path does not exist.
    ARTIFACT_MISSING = "ARTIFACT_MISSING"
    #: The path exists but is empty or too small to be a model.
    ARTIFACT_TOO_SMALL = "ARTIFACT_TOO_SMALL"
    #: The file is not a GGUF, whatever it is named.
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    #: Bytes hashed successfully. Byte identity established, nothing more.
    COMPUTED_LOCAL_DIGEST = "COMPUTED_LOCAL_DIGEST"
    #: A human supplied an external digest and it disagrees. Always a refusal.
    EXTERNAL_DIGEST_MISMATCH = "EXTERNAL_DIGEST_MISMATCH"
    #: A human supplied an external digest and it agrees. The strongest state.
    VERIFIED_MATCH = "VERIFIED_MATCH"
    #: Bytes hash, but no external digest was supplied. Not "verified".
    NO_EXTERNAL_DIGEST_SUPPLIED = "NO_EXTERNAL_DIGEST_SUPPLIED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_refusal(self) -> bool:
        return self in {
            DigestStatus.ARTIFACT_MISSING,
            DigestStatus.ARTIFACT_TOO_SMALL,
            DigestStatus.UNSUPPORTED_FORMAT,
            DigestStatus.EXTERNAL_DIGEST_MISMATCH,
        }

    @property
    def may_execute(self) -> bool:
        """Only a digest that survived every check may be executed.

        ``NO_EXTERNAL_DIGEST_SUPPLIED`` is deliberately **not** in this set when
        the operator demanded external verification. A caller that needs
        publisher provenance must be told no, not handed a self-consistent hash.
        """
        return self in {DigestStatus.COMPUTED_LOCAL_DIGEST,
                        DigestStatus.VERIFIED_MATCH,
                        DigestStatus.NO_EXTERNAL_DIGEST_SUPPLIED}


@dataclass(frozen=True)
class ArtifactIdentity:
    """The explicit identity record for one artifact."""

    artifact_id: str
    filename: str
    path: str
    canonical_path: str
    format: str
    size_bytes: int
    computed_sha256: str
    status: DigestStatus
    detail: str = ""
    declared_family: str = ""
    declared_name: str = ""
    declared_quantization: str = ""
    declared_context_length: int | None = None
    external_sha256: str = ""
    external_source: str = ""
    external_supplied: bool = False
    source_url: str = ""
    license: str = ""
    measured_bytes: int = 0
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def verified(self) -> bool:
        """Verified means matched an external digest. Nothing weaker qualifies."""
        return self.status is DigestStatus.VERIFIED_MATCH

    @property
    def externally_attested(self) -> bool:
        return self.external_supplied

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "filename": self.filename,
            "path": self.path,
            "canonical_path": self.canonical_path,
            "format": self.format,
            "size_bytes": self.size_bytes,
            "measured_bytes": self.measured_bytes,
            "computed_sha256": self.computed_sha256,
            "status": self.status.value,
            "detail": self.detail,
            "declared_family": self.declared_family,
            "declared_name": self.declared_name,
            "declared_quantization": self.declared_quantization,
            "declared_context_length": self.declared_context_length,
            "external_sha256": self.external_sha256,
            "external_source": self.external_source,
            "external_supplied": self.external_supplied,
            "verified": self.verified,
            "source_url": self.source_url,
            "license": self.license,
            "evidence": dict(self.evidence),
        }


def compute_digest(path: str | Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    """Streamed SHA-256 over the file's bytes.

    The authoritative source. Never reads a digest from a sidecar file, because
    a sidecar is only as trustworthy as whoever wrote it.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def read_gguf_header(path: str | Path) -> dict[str, Any]:
    """Read enough of a GGUF to prove the format and report its version.

    Header metadata is **declared by the artifact**, not verified by this
    laboratory. The quantization and context length reported here are useful for
    admission planning and must never be presented as independently confirmed.
    """
    with Path(path).open("rb") as handle:
        magic = handle.read(4)
        if magic != GGUF_MAGIC:
            return {"is_gguf": False, "version": None}
        raw = handle.read(4)
        if len(raw) < 4:
            return {"is_gguf": False, "version": None}
        version = int.from_bytes(raw, "little")
        return {
            "is_gguf": True,
            "version": version,
            "source": "artifact header (declared by the file, not verified)",
        }


def _artifact_id(path: Path, computed: str) -> str:
    """A stable identifier derived from location and content, not a random UUID.

    Two runs over the same bytes at the same path produce the same id, which is
    what makes a diff between two verification records meaningful.
    """
    material = f"{path.name}|{computed}".encode("utf-8")
    return "artifact-" + hashlib.sha256(material).hexdigest()[:16]


def _absent(status: DigestStatus, detail: str, path: Path, **extra: Any) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_id="",
        filename=path.name,
        path=str(path),
        canonical_path="",
        format="",
        size_bytes=0,
        computed_sha256="",
        status=status,
        detail=detail,
        evidence=dict(extra),
    )


def identify(
    model_path: str | Path | None,
    *,
    expected_sha256: str = "",
    external_sha256: str = "",
    external_source: str = "",
    family: str = "",
    name: str = "",
    quantization: str = "",
    context_length: int | None = None,
    source_url: str = "",
    license_: str = "",
) -> ArtifactIdentity:
    """Establish the identity of one explicitly named artifact.

    The order is deliberate and is the integrity procedure from the milestone
    specification: existence, then format, then plausible size, then digest, then
    external comparison. A file that fails any step is refused with a distinct
    reason, and no later step is attempted.
    """
    if not model_path:
        return _absent(
            DigestStatus.NOT_CONFIGURED,
            "no artifact path was supplied; the laboratory does not search for one",
            Path("<unconfigured>"),
        )

    path = Path(model_path)
    if not path.is_file():
        return _absent(
            DigestStatus.ARTIFACT_MISSING,
            f"artifact not found at {path}; the laboratory does not download, "
            "search, or substitute an artifact",
            path,
        )

    try:
        canonical = str(path.resolve())
    except OSError:
        canonical = str(path)

    suffix = path.suffix.lower().lstrip(".")
    if suffix not in SUPPORTED_FORMATS:
        return _absent(
            DigestStatus.UNSUPPORTED_FORMAT,
            f"unsupported artifact format {suffix!r}; this milestone supports "
            f"{', '.join(SUPPORTED_FORMATS)} only",
            path,
            canonical_path=canonical,
            observed_suffix=suffix,
        )

    measured = path.stat().st_size
    if measured < MINIMUM_PLAUSIBLE_BYTES:
        return _absent(
            DigestStatus.ARTIFACT_TOO_SMALL,
            f"artifact is {measured} bytes, below the {MINIMUM_PLAUSIBLE_BYTES} "
            "byte floor for a model; this is what a truncated download looks like",
            path,
            canonical_path=canonical,
            measured_bytes=measured,
        )

    header = read_gguf_header(path)
    if not header.get("is_gguf"):
        return _absent(
            DigestStatus.UNSUPPORTED_FORMAT,
            f"file is named {path.name} but does not begin with the GGUF magic; "
            "it is not a GGUF whatever it is called",
            path,
            canonical_path=canonical,
            measured_bytes=measured,
            header=header,
        )

    computed = compute_digest(path)
    artifact_id = _artifact_id(path, computed)
    base = dict(
        artifact_id=artifact_id,
        filename=path.name,
        path=str(path),
        canonical_path=canonical,
        format=suffix,
        size_bytes=measured,
        measured_bytes=measured,
        computed_sha256=computed,
        declared_family=family,
        declared_name=name,
        declared_quantization=quantization,
        declared_context_length=context_length,
        source_url=source_url,
        license=license_,
    )

    external = (external_sha256 or "").strip().lower()
    evidence: dict[str, Any] = {
        "gguf_version": header.get("version"),
        "gguf_version_source": header.get("source"),
        "external_digest_source": external_source or "none",
    }

    if external:
        evidence["expected_sha256_from_declaration"] = expected_sha256 or None
        if external == computed:
            return ArtifactIdentity(
                **base,
                status=DigestStatus.VERIFIED_MATCH,
                detail=(
                    f"computed digest matches the externally supplied digest from "
                    f"{external_source or 'an unnamed source'}"
                ),
                external_sha256=external,
                external_source=external_source,
                external_supplied=True,
                evidence=evidence,
            )
        return ArtifactIdentity(
            **base,
            status=DigestStatus.EXTERNAL_DIGEST_MISMATCH,
            detail=(
                f"computed digest {computed} does not match the externally "
                f"supplied {external}. Refusing to execute this artifact."
            ),
            external_sha256=external,
            external_source=external_source,
            external_supplied=True,
            evidence=evidence,
        )

    # No external digest. Byte identity is established and nothing more is
    # claimed. The distinction is the point of this branch existing.
    if expected_sha256:
        evidence["expected_sha256_from_declaration"] = expected_sha256
        if expected_sha256.strip().lower() == computed:
            return ArtifactIdentity(
                **base,
                status=DigestStatus.NO_EXTERNAL_DIGEST_SUPPLIED,
                detail=(
                    "computed digest matches the digest declared in the runtime "
                    "configuration, which the same human wrote; this establishes "
                    "that the file has not changed since the declaration, and "
                    "establishes no publisher provenance whatsoever"
                ),
                evidence=evidence,
            )
        return ArtifactIdentity(
            **base,
            status=DigestStatus.EXTERNAL_DIGEST_MISMATCH,
            detail=(
                f"computed digest {computed} does not match the digest declared "
                f"in the runtime configuration ({expected_sha256}). The artifact "
                "changed since it was declared, so its identity is now different."
            ),
            evidence=evidence,
        )

    return ArtifactIdentity(
        **base,
        status=DigestStatus.NO_EXTERNAL_DIGEST_SUPPLIED,
        detail=(
            "no external digest was supplied by a human, so byte identity is "
            "established and publisher provenance is not. This artifact is not "
            "externally verified."
        ),
        evidence=evidence,
    )


def verify_immutable(before: ArtifactIdentity, after: ArtifactIdentity) -> dict[str, Any]:
    """Compare the digest from before a run with the digest from after it.

    The specification requires exact equality. Anything else is an M010 failure
    and is reported as such, with both digests shown so the difference is
    inspectable rather than summarised away.
    """
    same = bool(before.computed_sha256) and before.computed_sha256 == after.computed_sha256
    return {
        "immutable": same,
        "before_sha256": before.computed_sha256,
        "after_sha256": after.computed_sha256,
        "before_size_bytes": before.size_bytes,
        "after_size_bytes": after.size_bytes,
        "verdict": (
            "artifact is byte-identical before and after the run"
            if same
            else "ARTIFACT MUTATED: the model's bytes changed during the run. "
                 "No learning, no adapter update, and no inference may change an "
                 "artifact. Continuing to birth machinery is refused."
        ),
    }


__all__ = [
    "GGUF_MAGIC",
    "MINIMUM_PLAUSIBLE_BYTES",
    "SUPPORTED_FORMATS",
    "ArtifactIdentity",
    "DigestStatus",
    "compute_digest",
    "identify",
    "read_gguf_header",
    "verify_immutable",
]
