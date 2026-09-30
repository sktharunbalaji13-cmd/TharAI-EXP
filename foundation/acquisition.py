"""M010 acquisition policy: the laboratory never fetches a model.

The whole point of this module is a negative. There is no code here that
downloads, searches, scrapes, or infers a model choice, and the test suite
proves that structurally rather than by reading these docstrings.

Why the negative needs a module at all
--------------------------------------
A policy that exists only as prose in a design document decays the first time
someone needs a model to test something. "The lab never downloads" is easy to
honour until a milestone is blocked on it, and then it is very easy to add one
``urllib.request.urlopen`` and call it a convenience. Putting the rule in code
with a machine-readable refusal gives the convenience something to be refused
*by*.

The three states
----------------
``MODEL_NOT_CONFIGURED``
    No human-supplied declaration exists. This is the correct and expected
    state of a fresh laboratory, and it is not an error to work around.
``RUNTIME_UNAVAILABLE``
    A model is declared but the named runtime binary is absent. The laboratory
    does not install it.
``DECLARATION_INVALID``
    Something was supplied and it is wrong. Detail is carried; nothing is
    repaired.

All three are terminal for acquisition. There is no fourth state in which the
laboratory goes and finds a model.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from babylab.runtime.config import (
    ConfigurationResult,
    ConfigurationState,
    load_configuration,
)

#: Where the human declaration lives. Reported, never searched for.
DECLARATION_RELPATH = "human_control/experiment_config/runtime.json"

#: Where a human-supplied model manifest lives. Distinct from the declaration:
#: the manifest carries what the publisher said, the declaration carries what
#: this laboratory will execute.
MANIFEST_RELPATH = "human_control/experiment_config/model_manifest.json"

#: The approved weights boundary. Weights belong here and nowhere else.
WEIGHTS_RELPATH = "human_control/experiment_config/weights"

#: Machine-readable inventory of every acquisition route the specification
#: forbids. Exported so the test suite and the final report can cite one list
#: rather than restating the prohibitions in prose.
FORBIDDEN_ACQUISITION_ROUTES: tuple[str, ...] = (
    "huggingface_download",
    "github_release_download",
    "arbitrary_url_fetch",
    "curl_wget_acquisition",
    "package_manager_model_install",
    "model_hub_api_discovery",
    "automatic_runtime_binary_fetch",
    "automatic_dependency_install",
    "recursive_model_discovery",
    "path_based_binary_search",
    "silent_model_substitution",
    "silent_quantization_change",
    "silent_family_change",
)

#: Human-readable explanation attached to every refusal. One string, so the
#: CLI, the audit, and the tests cannot drift apart.
REFUSAL_REASON = (
    "The laboratory does not acquire foundation models. A human selects the "
    "model family, quantization, artifact and runtime, writes the declaration "
    "and manifest by hand, and the laboratory verifies only what is written "
    "there. Selecting a substrate automatically would make every experiment "
    "irreproducible, because the substrate would be a property of when the code "
    "ran rather than of what the human chose."
)


class AcquisitionState(str, enum.Enum):
    """The only three states acquisition can report. None of them is 'fetched'."""

    MODEL_NOT_CONFIGURED = "MODEL_NOT_CONFIGURED"
    RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"
    DECLARATION_INVALID = "DECLARATION_INVALID"
    DECLARED = "DECLARED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class AcquisitionStatus:
    """What the acquisition policy reports, and what it refuses to do."""

    state: AcquisitionState
    detail: str = ""
    declaration_path: str = ""
    manifest_path: str = ""
    weights_directory: str = ""
    #: True only when a human has written both a declaration and a manifest.
    #: Until then the laboratory has no model, regardless of what is on disk.
    human_supplied: bool = False
    forbidden_routes: tuple[str, ...] = FORBIDDEN_ACQUISITION_ROUTES
    network_required: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def model_available(self) -> bool:
        """A model the laboratory may execute. Never true from discovery."""
        return self.state is AcquisitionState.DECLARED

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "detail": self.detail,
            "declaration_path": self.declaration_path,
            "manifest_path": self.manifest_path,
            "weights_directory": self.weights_directory,
            "human_supplied": self.human_supplied,
            "model_available": self.model_available,
            "network_required": self.network_required,
            "forbidden_routes": list(self.forbidden_routes),
            "evidence": dict(self.evidence),
        }

    def describe(self) -> str:
        if self.state is AcquisitionState.MODEL_NOT_CONFIGURED:
            return f"MODEL_NOT_CONFIGURED: {self.detail}"
        if self.state is AcquisitionState.RUNTIME_UNAVAILABLE:
            return f"RUNTIME_UNAVAILABLE: {self.detail}"
        if self.state is AcquisitionState.DECLARATION_INVALID:
            return f"DECLARATION_INVALID: {self.detail}"
        return f"DECLARED: {self.detail}"


class AcquisitionRefused(RuntimeError):
    """Raised by anything that attempts an acquisition this module forbids.

    It exists so that a future convenience cannot quietly succeed. The message
    is the policy; the class is the enforcement.
    """

    def __init__(self, route: str) -> None:
        self.route = route
        super().__init__(f"acquisition route {route!r} is forbidden. {REFUSAL_REASON}")


def refuse(route: str) -> None:
    """The single place an acquisition attempt is turned away.

    Raises rather than returning, so the refusal cannot be discarded by a caller
    that forgets to check a return value. The only correct handling is the
    exception propagating.
    """
    raise AcquisitionRefused(route)


def declaration_path(root: str | Path) -> Path:
    return Path(root) / DECLARATION_RELPATH


def manifest_path(root: str | Path) -> Path:
    return Path(root) / MANIFEST_RELPATH


def weights_directory(root: str | Path) -> Path:
    """The approved weights boundary. Reported; never enumerated for models."""
    return Path(root) / WEIGHTS_RELPATH


def assess(root: str | Path | None = None) -> AcquisitionStatus:
    """Report what a human has supplied. Never a reason to go looking.

    The three questions asked here are all about *files a human wrote*. Whether
    any ``.gguf`` happens to exist elsewhere on the machine is deliberately not
    one of them.
    """
    if root is None:
        from babylab.paths import default_paths

        root = default_paths().root

    root = Path(root)
    decl = declaration_path(root)
    man = manifest_path(root)
    weights = weights_directory(root)
    loaded: ConfigurationResult = load_configuration(decl)

    evidence: dict[str, Any] = {
        "declaration_exists": decl.is_file(),
        "manifest_exists": man.is_file(),
        "weights_directory_exists": weights.is_dir(),
    }

    if loaded.state is ConfigurationState.NOT_CONFIGURED:
        return AcquisitionStatus(
            state=AcquisitionState.MODEL_NOT_CONFIGURED,
            detail=(
                f"no model declaration at {decl}. The laboratory does not search "
                "for weights, does not read a model hub, and does not create a "
                "declaration. A human writes this file when a model is selected."
            ),
            declaration_path=str(decl),
            manifest_path=str(man),
            weights_directory=str(weights),
            human_supplied=False,
            evidence=evidence,
        )

    if loaded.state is ConfigurationState.INVALID:
        return AcquisitionStatus(
            state=AcquisitionState.DECLARATION_INVALID,
            detail=f"declaration at {decl} is invalid: {loaded.detail}",
            declaration_path=str(decl),
            manifest_path=str(man),
            weights_directory=str(weights),
            human_supplied=False,
            evidence=evidence,
        )

    # LOADED. The declaration is well-formed, so ask whether the runtime it
    # names is actually present. Absence is RUNTIME_UNAVAILABLE and the
    # laboratory still does nothing about it.
    declaration = loaded.configuration.declaration
    binary = declaration.runtime_binary
    evidence["declared_model_path"] = declaration.model_path
    evidence["declared_adapter"] = declaration.adapter_id

    if not binary:
        return AcquisitionStatus(
            state=AcquisitionState.RUNTIME_UNAVAILABLE,
            detail=(
                "the declaration names no runtime binary. The laboratory does "
                "not build, download, or locate one on the operator's behalf."
            ),
            declaration_path=str(decl),
            manifest_path=str(man),
            weights_directory=str(weights),
            human_supplied=man.is_file(),
            evidence=evidence,
        )

    if not Path(binary).is_file():
        return AcquisitionStatus(
            state=AcquisitionState.RUNTIME_UNAVAILABLE,
            detail=(
                f"the declared runtime binary is not present at {binary}. The "
                "laboratory does not install runtimes, does not search PATH, and "
                "does not substitute a different binary."
            ),
            declaration_path=str(decl),
            manifest_path=str(man),
            weights_directory=str(weights),
            human_supplied=man.is_file(),
            evidence=evidence,
        )

    return AcquisitionStatus(
        state=AcquisitionState.DECLARED,
        detail=(
            f"model declared at {declaration.model_path} with runtime {binary}. "
            "Verification happens in the artifact layer; declaring is not the "
            "same as being verified."
        ),
        declaration_path=str(decl),
        manifest_path=str(man),
        weights_directory=str(weights),
        human_supplied=man.is_file(),
        evidence=evidence,
    )


__all__ = [
    "DECLARATION_RELPATH",
    "FORBIDDEN_ACQUISITION_ROUTES",
    "MANIFEST_RELPATH",
    "REFUSAL_REASON",
    "WEIGHTS_RELPATH",
    "AcquisitionRefused",
    "AcquisitionState",
    "AcquisitionStatus",
    "assess",
    "declaration_path",
    "manifest_path",
    "refuse",
    "weights_directory",
]
