"""A deterministic environment for validating the substrate.

What this is
------------
A **laboratory fixture**. It exists to make replay and fault behaviour testable,
and it is not a model of the world the subject will eventually inhabit. Its
entities are abstract placeholders with measured properties, chosen so the
substrate can be exercised -- not so a subject could learn anything from them.

Why it is not a developmental environment
------------------------------------------
A fixture that behaved differently depending on a caller's apparent skill amount
would be a curriculum, and a fixture that named objects by purpose would be a
hint. So this environment has:

* entities with **opaque identifiers** and **physical** properties only --
  geometry descriptors, integer masses, integer capacities, positions;
* operations named for what physically happens (``GRASP``, ``INSERT``),
  never for what it is for;
* **no difficulty, no amount, no progress, no task list, and no ordering** of any
  kind -- the operations available depend only on the entity's current measured
  properties, never on how many actions have been taken or who is acting.

That last point is enforced by a test, because it is the easiest thing to break
by accident later: applying the same action twice from the same state must
produce the same result regardless of history length.
"""

from __future__ import annotations

from typing import Any

from environment.state import (
    UNIT_COUNT,
    UNIT_GRAMS,
    UNIT_ML,
    UNIT_TICKS,
    Entity,
    EnvironmentState,
    ResourceAmount,
    ResourceState,
)

#: Bumped when the fixture's initial conditions change. An environment created
#: with a different version refuses to restore a snapshot taken by another, so
#: changing the fixture cannot silently invalidate historical results.
FIXTURE_VERSION = "1.0.0"

FIXTURE_TYPE = "deterministic_laboratory"

#: The fixture's starting conditions. Integers only, so a hash computed today
#: equals a hash computed next year.
FIXTURE_CONFIG: dict[str, Any] = {
    "type": FIXTURE_TYPE,
    "implementation_version": FIXTURE_VERSION,
    "grid": {"width": 4, "height": 4},
    "resources": {
        # ``count`` is a hard capacity: an actor can hold one entity at a time.
        "capacity": {"value": 1, "unit": UNIT_COUNT, "exhaustible": False},
        "energy": {"value": 40, "unit": UNIT_GRAMS, "exhaustible": True},
        "time": {"value": 40, "unit": UNIT_TICKS, "exhaustible": True},
    },
    "entities": [
        # Two placeholders with different MEASURED geometry and mass. Nothing
        # here says what either is for, and the difference between them is a
        # physical difference, not a semantic one.
        {
            "entity_id": "ent-a1",
            "location": [0, 0],
            "observable": {
                "shape": "prism", "mass": 20, "capacity": 0,
                "movable": True, "height": 40, "width": 20, "contents": [],
            },
            "implementation_type": "fixture.solid",
        },
        {
            "entity_id": "ent-b2",
            "location": [3, 3],
            "observable": {
                "shape": "cylinder", "mass": 8, "capacity": 0,
                "movable": True, "height": 10, "width": 10, "contents": [],
            },
            "implementation_type": "fixture.solid",
        },
        # One placeholder that is hollow: ``capacity`` is a measurement of
        # interior volume, and that is the only reason INSERT is offered on it.
        {
            "entity_id": "ent-c3",
            "location": [1, 2],
            "observable": {
                "shape": "shell", "mass": 30, "capacity": 2,
                "movable": False, "height": 60, "width": 60, "contents": [],
            },
            "implementation_type": "fixture.hollow",
        },
    ],
}


def fixture_configuration() -> dict[str, Any]:
    """A copy of the fixture configuration, safe for the caller to modify."""
    import copy

    return copy.deepcopy(FIXTURE_CONFIG)


def initial_state(config: dict[str, Any] | None = None) -> EnvironmentState:
    """Build the fixture's initial state. Pure function of the configuration."""
    settings = config or FIXTURE_CONFIG
    grid = settings.get("grid", {"width": 4, "height": 4})
    resources = ResourceState(amounts={
        key: ResourceAmount(
            resource_id=key,
            value=spec["value"],
            unit=spec["unit"],
            exhaustible=spec.get("exhaustible", True),
        )
        for key, spec in sorted(settings.get("resources", {}).items())
    })
    entities = {
        spec["entity_id"]: Entity(
            entity_id=spec["entity_id"],
            observable=dict(spec.get("observable", {})),
            location=tuple(spec.get("location", (0, 0))),
            held_by=spec.get("held_by"),
            implementation_type=spec.get("implementation_type", ""),
        )
        for spec in settings.get("entities", [])
    }
    return EnvironmentState(
        state_version=0,
        entities=entities,
        resources=resources,
        grid_width=grid.get("width", 4),
        grid_height=grid.get("height", 4),
    )


def create_deterministic_environment(created_at: str = "1970-01-01T00:00:00.000Z",
                                     declared_by: str = "LABORATORY",
                                     clock=None,
                                     environment_id: str | None = None):
    """Build a ready-to-use deterministic environment."""
    from environment.environment import Environment

    return Environment.create(
        config=fixture_configuration(),
        state=initial_state(),
        created_at=created_at,
        declared_by=declared_by,
        environment_id=environment_id,
        clock=clock,
    )


__all__ = [
    "FIXTURE_CONFIG",
    "FIXTURE_TYPE",
    "FIXTURE_VERSION",
    "create_deterministic_environment",
    "fixture_configuration",
    "initial_state",
]
