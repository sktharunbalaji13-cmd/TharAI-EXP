"""Observations: what the environment exposes, and how it came to be known.

The line this module holds
--------------------------
**An observation is a measurement, not an interpretation.**

An observation reports what is physically observable about an entity: its
geometry, its mass, whether it is currently held, what operations its measured
properties admit. It does not report what any of that is *for*. There is no
``name``, no ``purpose``, no ``usefulness``, and no ``recommended_action``
field, and the vocabulary of observable properties is closed in
:mod:`environment.state` precisely so that inventing one is a deliberate act
rather than something that happens by writing a new key.

``implementation_type`` is laboratory bookkeeping and is deliberately *absent*
from observations, even though it exists in state. Exposing it would hand the
future subject a hint about how the environment was built, which is a different
thing from a property of the world.

Every value carries an epistemic status. A property the environment does not
expose is reported ``UNAVAILABLE`` rather than omitted silently or guessed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from babylab.hashing import canonical_bytes, sha256_hex
from babylab.measure import Measurement
from environment.state import EnvironmentState, Entity


@dataclass(frozen=True)
class EntityObservation:
    """One entity as the environment exposes it.

    Only :data:`environment.state.OBSERVABLE_PROPERTIES` may appear. An
    implementation type, if present in state, is not copied here.
    """

    entity_id: str
    location: tuple[int, int]
    held_by: str | None
    properties: dict[str, Measurement] = field(default_factory=dict)
    available_operations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "location": list(self.location),
            "held_by": self.held_by,
            "properties": {k: v.to_dict() for k, v in sorted(self.properties.items())},
            "available_operations": list(self.available_operations),
        }


def observe_entity(entity: Entity) -> EntityObservation:
    """Expose one entity's measured properties, and nothing else."""
    properties: dict[str, Measurement] = {}
    for key, value in sorted(entity.observable.items()):
        if key == "contents":
            # Reported as a measurement of occupancy, and always available.
            properties[key] = Measurement.observed(
                list(value), "entity_id", "environment state")
            continue
        if isinstance(value, bool):
            properties[key] = Measurement.observed(value, "boolean", "environment state")
        elif isinstance(value, int):
            unit = {
                "mass": "g", "capacity": "ml", "height": "mm", "width": "mm",
            }.get(key, "")
            properties[key] = Measurement.observed(value, unit, "environment state")
        else:
            # A geometry descriptor such as "sphere": observable, and a
            # measurement of shape, not a statement of purpose.
            properties[key] = Measurement.observed(value, "descriptor",
                                                    "environment state")
    return EntityObservation(
        entity_id=entity.entity_id,
        location=entity.location,
        held_by=entity.held_by,
        properties=properties,
        available_operations=entity.supported_operations(),
    )


@dataclass(frozen=True)
class Observation:
    """A complete view of the environment at one state version."""

    observation_id: str
    environment_id: str
    state_version: int
    state_hash: str
    timestamp: str
    entities: tuple[EntityObservation, ...] = ()
    resources: dict[str, Measurement] = field(default_factory=dict)
    grid: dict[str, int] = field(default_factory=dict)
    visible_events: tuple[str, ...] = ()

    @property
    def observation_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.to_dict()))

    def entity(self, entity_id: str) -> EntityObservation | None:
        for candidate in self.entities:
            if candidate.entity_id == entity_id:
                return candidate
        return None

    def operations_for(self, entity_id: str) -> tuple[str, ...]:
        found = self.entity(entity_id)
        return found.available_operations if found else ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "environment_id": self.environment_id,
            "state_version": self.state_version,
            "state_hash": self.state_hash,
            "timestamp": self.timestamp,
            "entities": [e.to_dict() for e in self.entities],
            "resources": {k: v.to_dict() for k, v in sorted(self.resources.items())},
            "grid": dict(sorted(self.grid.items())),
            "visible_events": list(self.visible_events),
        }


def build_observation(
    environment_id: str,
    state: EnvironmentState,
    timestamp: str,
    visible_events: tuple[str, ...] = (),
) -> Observation:
    """Assemble an observation of ``state``.

    Properties an environment chooses not to measure are reported
    ``UNAVAILABLE`` rather than left out, so a caller can tell "not measured"
    from "does not exist".
    """
    entities = tuple(
        observe_entity(state.entities[entity_id])
        for entity_id in sorted(state.entities)
    )
    resources = dict(state.resource_observations())
    return Observation(
        observation_id=f"obs-{uuid.uuid4().hex[:16]}",
        environment_id=environment_id,
        state_version=state.state_version,
        state_hash=state.state_hash,
        timestamp=timestamp,
        entities=entities,
        resources=resources,
        grid={"width": state.grid_width, "height": state.grid_height},
        visible_events=visible_events,
    )


__all__ = ["EntityObservation", "Observation", "build_observation", "observe_entity"]
