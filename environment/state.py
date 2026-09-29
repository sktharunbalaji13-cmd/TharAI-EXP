"""Environment state: versioned, serializable, hashable, replayable.

The decision that makes replay work
-----------------------------------
**Timestamps are not part of the state.**

A wall-clock reading differs between the original run and a replay by
microseconds, so if the timestamp entered the hashed state, every replay would
diverge and divergence would mean nothing. Time therefore lives in the *event
stream* and in *transitions*, which record when something happened, while the
*state* records only what is true. The same rule applies to float-valued
quantities: every physical quantity below is an integer in a stated base unit, so
a hash computed today equals a hash computed next year on a different machine.
Floats are rejected rather than rounded, because rounding hides a real
imprecision behind a stable-looking digest.

What the state deliberately does not contain
--------------------------------------------
No object names, no purposes, no difficulty amounts, no task list, no progress
marker. A state is a set of entities with measurable physical properties and a
set of resource values. What those properties *mean* is not recorded here, and
recording it is the failure this module exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from babylab.hashing import canonical_bytes, sha256_hex
from babylab.measure import Measurement

#: Base units for every physical quantity. Stating them here means a value of
#: ``250`` is never ambiguous about whether it is millilitres or bytes.
UNIT_ML = "ml"
UNIT_GRAMS = "g"
UNIT_MM = "mm"
UNIT_TICKS = "ticks"
UNIT_COUNT = "count"

#: Property names an observable entity may expose. A fixed vocabulary is what
#: keeps a future subject from being handed labels the environment invented:
#: these are measurements, and a property outside this set is not observable.
OBSERVABLE_PROPERTIES = frozenset({
    "shape",          # geometry descriptor, e.g. "sphere" -- not a purpose
    "mass",           # int, UNIT_GRAMS
    "capacity",       # int, UNIT_ML; 0 means it cannot receive
    "movable",        # bool
    "height",         # int, UNIT_MM
    "width",          # int, UNIT_MM
    "contents",       # list of entity ids currently held
    "occluded",       # bool, whether currently out of view
})


def _assert_integral(value: Any, name: str) -> Any:
    """Reject floats in anything that will be hashed.

    ``1.0`` and ``1`` hash differently, and ``0.1 + 0.2 != 0.3``, so a float in
    state would make a state hash depend on arithmetic history rather than on
    the state itself.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        raise ValueError(
            f"{name}={value!r} is a float; state must use integers in a stated "
            "base unit so that a hash depends on the value, not on how it was "
            "computed"
        )
    return value


@dataclass(frozen=True)
class Entity:
    """One thing in the environment, described only by measurable properties.

    ``entity_id`` is environment-local and stable. There is no ``name`` and no
    ``purpose`` field, and adding one would be the semantic cheat this project is
    built to avoid. ``implementation_type`` is laboratory bookkeeping and is
    deliberately *not* exposed in observations.
    """

    entity_id: str
    observable: dict[str, Any] = field(default_factory=dict)
    location: tuple[int, int] = (0, 0)
    held_by: str | None = None
    implementation_type: str = ""

    def __post_init__(self) -> None:
        if not self.entity_id or not isinstance(self.entity_id, str):
            raise ValueError("entity_id must be a non-empty string")
        unknown = set(self.observable) - OBSERVABLE_PROPERTIES
        if unknown:
            raise ValueError(
                f"entity {self.entity_id!r} declares properties outside the "
                f"observable vocabulary: {sorted(unknown)}"
            )
        for key, value in self.observable.items():
            _assert_integral(value, f"{self.entity_id}.{key}")
        if len(self.location) != 2:
            raise ValueError("location must be a 2-tuple of integers")
        for coordinate in self.location:
            _assert_integral(coordinate, f"{self.entity_id}.location")
        object.__setattr__(self, "location", tuple(self.location))
        object.__setattr__(self, "observable", dict(self.observable))
        if "contents" in self.observable:
            object.__setattr__(self, "observable", {
                **self.observable,
                "contents": list(self.observable["contents"]),
            })

    # -- capability queries, phrased as physics -------------------------
    @property
    def is_movable(self) -> bool:
        return bool(self.observable.get("movable", False))

    @property
    def capacity(self) -> int:
        return int(self.observable.get("capacity", 0) or 0)

    @property
    def contents(self) -> list[str]:
        return list(self.observable.get("contents", []) or [])

    @property
    def volume_used(self) -> int:
        """How much capacity is occupied. A measurement, not a judgement."""
        return len(self.contents)

    def can_receive(self) -> bool:
        return self.capacity > self.volume_used

    def supported_operations(self) -> tuple[str, ...]:
        """Operations this entity physically admits.

        Derived from measured properties, never from a declared purpose. An
        entity with a mouth-shaped opening and one with a flat tray surface have
        different observable geometry, so the environment offers different
        operations -- and the subject discovers that by trying, not by being told
        what the entity is for.
        """
        operations: list[str] = ["OBSERVE"]
        if self.held_by is None and self.is_movable:
            operations += ["GRASP", "MOVE", "RELEASE"]
        if self.held_by is not None:
            operations += ["RELEASE"]
        if self.can_receive():
            operations += ["INSERT", "REMOVE"]
        if self.is_movable and not self.observable.get("occluded", False):
            operations += ["MOVE"]
        return tuple(sorted(set(operations)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "location": list(self.location),
            "held_by": self.held_by,
            "observable": {
                key: (list(value) if isinstance(value, list) else value)
                for key, value in sorted(self.observable.items())
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Entity":
        return cls(
            entity_id=payload["entity_id"],
            observable=dict(payload.get("observable", {})),
            location=tuple(payload.get("location", (0, 0))),
            held_by=payload.get("held_by"),
            implementation_type=payload.get("implementation_type", ""),
        )


@dataclass(frozen=True)
class ResourceAmount:
    """One resource, with the unit it is measured in and where it came from."""

    resource_id: str
    value: int
    unit: str
    #: Whether a shortage is a hard failure or merely a reported fact.
    exhaustible: bool = True

    def __post_init__(self) -> None:
        _assert_integral(self.value, f"resource {self.resource_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "value": self.value,
            "unit": self.unit,
            "exhaustible": self.exhaustible,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResourceAmount":
        return cls(
            resource_id=payload["resource_id"],
            value=payload["value"],
            unit=payload["unit"],
            exhaustible=payload.get("exhaustible", True),
        )


@dataclass(frozen=True)
class ResourceState:
    """All resources at one point. A set of facts, not a score.

    There is no total, no score, and no notion of "more is better". A resource
    going down is not a penalty and going up is not a reward; they are
    measurements, and the environment never sums them.
    """

    amounts: dict[str, ResourceAmount] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalised = {}
        for key, amount in self.amounts.items():
            if amount.resource_id != key:
                raise ValueError(
                    f"resource key {key!r} disagrees with its id "
                    f"{amount.resource_id!r}"
                )
            normalised[key] = amount
        object.__setattr__(self, "amounts", dict(sorted(normalised.items())))

    def get(self, resource_id: str) -> int | None:
        amount = self.amounts.get(resource_id)
        return None if amount is None else amount.value

    def with_value(self, resource_id: str, value: int) -> "ResourceState":
        """A new state with one resource changed. Never mutates in place."""
        amount = self.amounts.get(resource_id)
        if amount is None:
            raise KeyError(f"unknown resource {resource_id!r}")
        updated = dict(self.amounts)
        updated[resource_id] = replace(amount, value=value)
        return ResourceState(amounts=updated)

    def depleted(self) -> tuple[str, ...]:
        return tuple(
            key for key, amount in sorted(self.amounts.items()) if amount.value <= 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {key: amount.to_dict() for key, amount in self.amounts.items()}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResourceState":
        return cls(amounts={
            key: ResourceAmount.from_dict(value) for key, value in payload.items()
        })


@dataclass(frozen=True)
class EnvironmentState:
    """One complete, versioned environment state."""

    state_version: int
    entities: dict[str, Entity] = field(default_factory=dict)
    resources: ResourceState = field(default_factory=ResourceState)
    grid_width: int = 1
    grid_height: int = 1

    def __post_init__(self) -> None:
        if self.state_version < 0:
            raise ValueError("state_version must be >= 0")
        if self.grid_width < 1 or self.grid_height < 1:
            raise ValueError("grid dimensions must be >= 1")
        for entity_id, entity in self.entities.items():
            if entity.entity_id != entity_id:
                raise ValueError(
                    f"entity key {entity_id!r} disagrees with its id "
                    f"{entity.entity_id!r}"
                )
            if not (0 <= entity.location[0] < self.grid_width):
                raise ValueError(
                    f"entity {entity_id!r} at x={entity.location[0]} is outside "
                    f"a grid of width {self.grid_width}"
                )
            if not (0 <= entity.location[1] < self.grid_height):
                raise ValueError(
                    f"entity {entity_id!r} at y={entity.location[1]} is outside "
                    f"a grid of height {self.grid_height}"
                )
            for child in entity.contents:
                if child not in self.entities:
                    raise ValueError(
                        f"entity {entity_id!r} holds unknown entity {child!r}"
                    )
        object.__setattr__(self, "entities", dict(sorted(self.entities.items())))

    # -- access ----------------------------------------------------------
    def entity(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)

    @property
    def state_hash(self) -> str:
        """SHA-256 over the canonical encoding of everything observable.

        This is the value replay compares. It covers state_version, so two
        different points in history can never share a hash even if the entity
        sets happen to coincide.
        """
        return sha256_hex(canonical_bytes(self.to_dict()))

    def with_entity(self, entity: Entity) -> "EnvironmentState":
        updated = dict(self.entities)
        updated[entity.entity_id] = entity
        return replace(self, entities=updated, state_version=self.state_version + 1)

    def with_resources(self, resources: ResourceState) -> "EnvironmentState":
        return replace(
            self, resources=resources, state_version=self.state_version + 1
        )

    def available_operations(self) -> dict[str, tuple[str, ...]]:
        return {
            entity_id: entity.supported_operations()
            for entity_id, entity in sorted(self.entities.items())
        }

    def resource_observations(self) -> dict[str, Measurement]:
        """Resource values as measurements, so a display can label them."""
        return {
            key: Measurement.observed(amount.value, amount.unit, "environment state")
            for key, amount in sorted(self.resources.amounts.items())
        }

    # -- serialization ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "state_version": self.state_version,
            "grid": {"width": self.grid_width, "height": self.grid_height},
            "entities": {
                entity_id: entity.to_dict()
                for entity_id, entity in sorted(self.entities.items())
            },
            "resources": self.resources.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EnvironmentState":
        grid = payload.get("grid", {})
        return cls(
            state_version=payload["state_version"],
            grid_width=grid.get("width", 1),
            grid_height=grid.get("height", 1),
            entities={
                key: Entity.from_dict(value)
                for key, value in payload.get("entities", {}).items()
            },
            resources=ResourceState.from_dict(payload.get("resources", {})),
        )


__all__ = [
    "OBSERVABLE_PROPERTIES",
    "UNIT_COUNT",
    "UNIT_GRAMS",
    "UNIT_ML",
    "UNIT_MM",
    "UNIT_TICKS",
    "Entity",
    "EnvironmentState",
    "ResourceAmount",
    "ResourceState",
]
