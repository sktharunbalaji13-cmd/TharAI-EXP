"""Milestone 007: the environment and interaction substrate.

The environment exists independently of any subject. It provides a world that
can be observed and acted upon, and nothing else. It has no goals, no memory, no
autonomy, no curriculum, and it never acts first.

    ENVIRONMENT      state, observations, actions, consequences, resources, events
        |
        |   (not yet, and not in this milestone)
        v
    BABY AI SUBJECT

Three distinctions this package is built to hold:

``Environment != Baby AI``
    The environment is infrastructure. It belongs to no one.
``Observation != interpretation``
    An observation reports measurements. The meaning of a measurement is
    discovered, not supplied.
``Action capability != intended purpose``
    An entity admits GRASP because it is movable. That is not a statement about
    what it is for.
"""

from environment.action import Action, Operation, Validation, ValidationOutcome
from environment.consequence import (
    ActionResult,
    ConsequenceKind,
    ResourceChange,
    StateDelta,
    compute_delta,
)
from environment.environment import Environment, EnvironmentFault
from environment.events import (
    ChainVerification,
    EnvironmentEvent,
    EventStream,
    EventType,
)
from environment.identity import (
    EnvironmentIdentity,
    configuration_hash,
    derive_identity,
    verify_configuration,
)
from environment.observation import EntityObservation, Observation, build_observation
from environment.snapshot import Branch, Snapshot, take_snapshot
from environment.state import (
    Entity,
    EnvironmentState,
    ResourceAmount,
    ResourceState,
)

__all__ = [
    "Action",
    "ActionResult",
    "Branch",
    "ChainVerification",
    "ConsequenceKind",
    "Entity",
    "EntityObservation",
    "Environment",
    "EnvironmentEvent",
    "EnvironmentFault",
    "EnvironmentIdentity",
    "EnvironmentState",
    "EventStream",
    "EventType",
    "Observation",
    "Operation",
    "ResourceChange",
    "ResourceAmount",
    "ResourceState",
    "Snapshot",
    "StateDelta",
    "Validation",
    "ValidationOutcome",
    "build_observation",
    "configuration_hash",
    "compute_delta",
    "derive_identity",
    "take_snapshot",
    "verify_configuration",
]
