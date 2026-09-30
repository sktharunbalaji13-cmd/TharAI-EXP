"""M010 model manifest: what the human says about the artifact.

The manifest and the declaration are two different files on purpose.

* The **declaration** (``runtime.json``) is what this laboratory will execute.
* The **manifest** (``model_manifest.json``) is what a human says about the
  artifact's origin: family, quantization, publisher, and the digest an
  *external* source reported.

Keeping them apart means a claim about provenance can never be satisfied by the
same file that declares what to run. If they were one file, a human who mistyped
a digest would satisfy his own mistake, and "externally verified" would mean
"consistent with a value written five minutes ago by the same person."

Manifest text is never proof
----------------------------
A manifest is metadata about a file. It can be edited, copied, or wrong. The
only authoritative statement about the artifact's bytes is
:func:`foundation.artifact.compute_digest`. This module therefore refuses to
assert verification on its own, and every claim it carries is labelled as
declared.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Accepted schema.
MANIFEST_SCHEMA = "babylab/model-manifest/v1"


class ManifestState(str, enum.Enum):
    ABSENT = "ABSENT"
    LOADED = "LOADED"
    INVALID = "INVALID"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class ModelManifest:
    """A human's declaration about an artifact's origin.

    Every field here is a *claim about a file*, not a measurement of one. The
    distinction is carried in the field name and in :meth:`to_dict`, so a
    downstream reader cannot mistake one for the other by accident.
    """

    artifact_path: str = ""
    declared_family: str = ""
    declared_name: str = ""
    declared_format: str = ""
    declared_quantization: str = ""
    declared_context_length: int | None = None
    declared_size_bytes: int | None = None
    externally_supplied_sha256: str = ""
    #: Exactly what the file said, kept for display so a rejected value is
    #: visible to the human who wrote it rather than silently discarded. It is
    #: never used for comparison.
    external_digest_text_as_written: str = ""
    external_digest_rejection: str = ""
    external_digest_source: str = ""
    external_digest_reference: str = ""
    intended_runtime: str = ""
    intended_runtime_version: str = ""
    acquisition_reference: str = ""
    license: str = ""
    license_url: str = ""
    source_url: str = ""
    declared_by: str = ""
    declared_at: str = ""
    notes: str = ""
    source_path: str = ""
    state: ManifestState = ManifestState.ABSENT
    detail: str = ""

    @property
    def has_external_digest(self) -> bool:
        """True only when a human wrote a real 64-hex digest from an outside source.

        Three things must all hold, and each of them exists to stop a specific
        false positive:

        * the value is 64 hex characters, so ``FILL IN: 64 hex characters...``
          from the template is not a digest;
        * it is not a placeholder, so a partially filled template is rejected;
        * ``external_digest_source`` is non-empty, so a digest the same human
          entered without attribution is not external provenance.
        """
        return _is_real_digest(self.externally_supplied_sha256) and bool(
            self.external_digest_source
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA,
            "state": self.state.value,
            "detail": self.detail,
            "source_path": self.source_path,
            "artifact_path_declared": self.artifact_path,
            "family_declared": self.declared_family,
            "name_declared": self.declared_name,
            "format_declared": self.declared_format,
            "quantization_declared": self.declared_quantization,
            "context_length_declared": self.declared_context_length,
            "size_bytes_declared": self.declared_size_bytes,
            "external_sha256": self.externally_supplied_sha256,
            "external_digest_text_as_written": self.external_digest_text_as_written,
            "external_digest_rejection": self.external_digest_rejection,
            "external_digest_source": self.external_digest_source,
            "external_digest_reference": self.external_digest_reference,
            "has_external_digest": self.has_external_digest,
            "intended_runtime": self.intended_runtime,
            "intended_runtime_version": self.intended_runtime_version,
            "acquisition_reference": self.acquisition_reference,
            "license": self.license,
            "license_url": self.license_url,
            "source_url": self.source_url,
            "declared_by": self.declared_by,
            "declared_at": self.declared_at,
            "notes": self.notes,
            "is_proof_of_artifact_identity": False,
            "note": (
                "manifest text is a human's claim about a file. Byte identity "
                "comes only from a digest computed over the artifact itself."
            ),
        }


#: Placeholder fragments the template writes. A value containing one of these is
#: text a human was meant to replace, not a digest they supplied.
_PLACEHOLDER_MARKERS = ("FILL IN", "FILL-IN", "YOUR-", "REPLACE", "<", "TODO",
                        "XXXX", "PLACEHOLDER")

_HEX = set("0123456789abcdef")


def _is_real_digest(value: str) -> bool:
    """True only for a 64-character lowercase hex string that is not a template.

    Applied at every place a digest is accepted. Without it, the generated
    template is a working forgery: submit it unfilled and the laboratory would
    record an "externally supplied" digest made of the words FILL IN.
    """
    candidate = (value or "").strip().lower()
    if len(candidate) != 64:
        return False
    if not set(candidate) <= _HEX:
        return False
    return not any(marker in candidate for marker in _PLACEHOLDER_MARKERS)


def _accepted_digest(digest_block: dict[str, Any]) -> str:
    """The digest to compare against, or empty if what was written is not one."""
    raw = str(digest_block.get("sha256", "")).strip()
    return raw.lower() if _is_real_digest(raw) else ""


def _digest_rejection(digest_block: dict[str, Any]) -> str:
    """Why the written value is not external provenance, or empty if it is.

    Two distinct rejections, because they are two distinct mistakes:

    * a well-formed digest with no source is unattributed -- written by the same
      human as the manifest, so it attests to nothing;
    * a value that is not 64 hex characters is a placeholder, almost always an
      unfilled template.
    """
    raw = str(digest_block.get("sha256", "")).strip()
    if _is_real_digest(raw):
        if source_is_attributed(digest_block):
            return ""
        return (
            "the digest is well-formed but no source is named, so it is not "
            "external provenance: a value without attribution was written by the "
            "same human as the manifest and attests to nothing"
        )
    if not raw:
        return ""
    return (
        "the written value is not a 64-character hex digest (it is most likely an "
        "unfilled template placeholder), so it cannot be compared against the "
        "artifact"
    )


def source_is_attributed(digest_block: dict[str, Any]) -> bool:
    """True when the manifest names where the digest came from."""
    return bool(str(digest_block.get("source", "")).strip())


_ABSENT = ModelManifest(
    state=ManifestState.ABSENT,
    detail=(
        "no model manifest was supplied. Without one there is no external digest, "
        "so the artifact cannot be externally verified even if its bytes hash."
    ),
)


def load_manifest(path: str | Path | None) -> ModelManifest:
    """Read a manifest, or explain its absence. Never create one."""
    if path is None:
        return _ABSENT
    target = Path(path)
    if not target.is_file():
        return ModelManifest(
            state=ManifestState.ABSENT,
            detail=(
                f"no model manifest at {target}. The laboratory does not create "
                "one and does not infer publisher provenance."
            ),
            source_path=str(target),
        )

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ModelManifest(
            state=ManifestState.INVALID,
            detail=f"manifest at {target} could not be read: {exc}",
            source_path=str(target),
        )

    schema = payload.get("schema")
    if schema != MANIFEST_SCHEMA:
        return ModelManifest(
            state=ManifestState.INVALID,
            detail=(
                f"manifest declares schema {schema!r}; this laboratory implements "
                f"{MANIFEST_SCHEMA!r}. Refusing to partially interpret it."
            ),
            source_path=str(target),
        )

    digest_block = payload.get("external_digest") or {}
    if not isinstance(digest_block, dict):
        digest_block = {}

    return ModelManifest(
        state=ManifestState.LOADED,
        source_path=str(target),
        artifact_path=str(payload.get("artifact_path", "")),
        declared_family=str(payload.get("family", "")),
        declared_name=str(payload.get("name", "")),
        declared_format=str(payload.get("format", "")),
        declared_quantization=str(payload.get("quantization", "")),
        declared_context_length=(
            int(payload["context_length"])
            if payload.get("context_length") is not None
            else None
        ),
        declared_size_bytes=(
            int(payload["size_bytes"])
            if payload.get("size_bytes") is not None
            else None
        ),
        externally_supplied_sha256=_accepted_digest(digest_block),
        external_digest_text_as_written=str(digest_block.get("sha256", "")).strip(),
        external_digest_rejection=_digest_rejection(digest_block),
        external_digest_source=str(digest_block.get("source", "")).strip(),
        external_digest_reference=str(digest_block.get("reference", "")).strip(),
        intended_runtime=str(payload.get("runtime", {}).get("implementation", "")),
        intended_runtime_version=str(payload.get("runtime", {}).get("version", "")),
        acquisition_reference=str(payload.get("acquisition", {}).get("reference", "")),
        license=str(payload.get("license", "")),
        license_url=str(payload.get("license_url", "")),
        source_url=str(payload.get("source_url", "")),
        declared_by=str(payload.get("declared_by", "")),
        declared_at=str(payload.get("declared_at", "")),
        notes=str(payload.get("notes", "")),
        detail=(
            "manifest loaded. Its contents are declared claims and are verified "
            "against the artifact, never in place of it."
        ),
    )


TEMPLATE = """{
  "schema": "babylab/model-manifest/v1",

  "artifact_path": "human_control/experiment_config/weights/YOUR-MODEL.gguf",
  "family": "FILL IN: model family, exactly as the publisher names it",
  "name": "FILL IN: specific model name",
  "format": "gguf",
  "quantization": "FILL IN: e.g. Q4_K_M, as published",
  "context_length": null,
  "size_bytes": null,

  "external_digest": {
    "sha256": "FILL IN: 64 hex characters published by an external source",
    "source": "FILL IN: where that digest came from",
    "reference": "FILL IN: URL or document reference for the digest"
  },

  "runtime": {
    "implementation": "llama.cpp",
    "version": "FILL IN: the version string your binary reports"
  },

  "acquisition": {
    "reference": "FILL IN: how you obtained the artifact, and when"
  },

  "license": "FILL IN",
  "license_url": "",
  "source_url": "",

  "declared_by": "FILL IN: the human who selected this model",
  "declared_at": "FILL IN: ISO-8601",
  "notes": ""
}
"""


def write_template(path: str | Path) -> Path:
    """Write an unverified template for a human to fill in.

    The one place the laboratory writes a manifest, and it writes a *blank*:
    every field that matters is a placeholder, so a template that was submitted
    unfilled is rejected rather than accepted with invented provenance.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(TEMPLATE, encoding="utf-8")
    return target


__all__ = [
    "MANIFEST_SCHEMA",
    "TEMPLATE",
    "ManifestState",
    "ModelManifest",
    "load_manifest",
    "write_template",
]
