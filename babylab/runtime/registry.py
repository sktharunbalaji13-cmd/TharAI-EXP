"""Adapter registry: how a model is replaced without touching the laboratory.

Milestone 006's replaceability requirement is structural, not aspirational. The
subject-facing interface, the Observatory and the provenance layer are all
written against :class:`~babylab.runtime.contract.ModelAdapter`. Selecting a
different runtime is a matter of registering a different adapter and changing
one configuration file. No laboratory code is edited.

Two properties are enforced here rather than documented and hoped for:

**No fallback.** If the configured adapter is not registered, the registry says
so and stops. It does not try another adapter, and it does not "pick the best
available" one. A laboratory that silently runs a different runtime than the one
recorded in provenance is worse than one that runs nothing.

**No discovery.** Adapters are registered explicitly by import path. The
registry never scans, never imports anything the laboratory did not name, and
never touches the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from babylab.runtime.contract import (
    ADAPTER_CONTRACT_VERSION,
    ModelAdapter,
    RuntimeErrorKind,
    RuntimeFailure,
)


@dataclass(frozen=True)
class AdapterRegistration:
    """One known way to run a model."""

    adapter_id: str
    factory: Callable[[], ModelAdapter]
    description: str
    contract_version: str = ADAPTER_CONTRACT_VERSION

    def create(self) -> ModelAdapter:
        adapter = self.factory()
        version = getattr(adapter, "contract_version", ADAPTER_CONTRACT_VERSION)
        if version != ADAPTER_CONTRACT_VERSION:
            raise RuntimeFailure(
                RuntimeErrorKind.RUNTIME_MISSING,
                f"adapter {self.adapter_id!r} declares contract version "
                f"{version!r} but this laboratory implements "
                f"{ADAPTER_CONTRACT_VERSION!r}",
                adapter_id=self.adapter_id,
            )
        return adapter


class AdapterRegistry:
    """Explicit, closed set of runtimes this laboratory knows how to drive."""

    def __init__(self) -> None:
        self._registrations: dict[str, AdapterRegistration] = {}

    def register(self, registration: AdapterRegistration) -> None:
        self._registrations[registration.adapter_id] = registration

    def known(self) -> tuple[str, ...]:
        return tuple(sorted(self._registrations))

    def describe(self, adapter_id: str) -> dict[str, Any]:
        try:
            registration = self._registrations[adapter_id]
        except KeyError:
            raise RuntimeFailure(
                RuntimeErrorKind.RUNTIME_MISSING,
                f"no adapter registered for {adapter_id!r}. "
                f"Known adapters: {', '.join(self.known()) or '(none)'}. "
                "The laboratory does not search for alternatives and does not "
                "substitute one.",
                adapter_id=adapter_id,
            ) from None
        return {
            "adapter_id": registration.adapter_id,
            "description": registration.description,
            "contract_version": registration.contract_version,
        }

    def create(self, adapter_id: str) -> ModelAdapter:
        """Instantiate the named adapter, or fail. Never falls back."""
        try:
            registration = self._registrations[adapter_id]
        except KeyError:
            raise RuntimeFailure(
                RuntimeErrorKind.RUNTIME_MISSING,
                f"adapter {adapter_id!r} is not registered. The laboratory "
                f"will not substitute another runtime. Known: "
                f"{', '.join(self.known()) or '(none)'}",
                adapter_id=adapter_id,
                known=list(self.known()),
            ) from None
        return registration.create()


#: The laboratory's default registry. Adapters are added by explicit
#: registration, so importing this module alone gives an honest empty registry
#: rather than a surprise binding.
DEFAULT_REGISTRY = AdapterRegistry()


def register_llamacpp(registry: AdapterRegistry = DEFAULT_REGISTRY) -> AdapterRegistry:
    """Register the llama.cpp adapter.

    Imported lazily and by explicit call. There is no import-time side effect
    that could make a test pass or fail depending on what happens to be
    installed.
    """
    from babylab.runtime.llamacpp_adapter import LlamaCppAdapter

    registry.register(
        AdapterRegistration(
            adapter_id="llamacpp",
            factory=LlamaCppAdapter,
            description=(
                "llama.cpp via the llama-cli subprocess. Local, no network "
                "listener, weights identified by SHA-256."
            ),
        )
    )
    return registry


__all__ = [
    "AdapterRegistration",
    "AdapterRegistry",
    "DEFAULT_REGISTRY",
    "register_llamacpp",
]
