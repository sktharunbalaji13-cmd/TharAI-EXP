"""Environment affordances: what can be observed and what follows, without purpose.

The vocabulary problem
----------------------
"Affordance" is usually defined as what an object is *for* — Gibson's
"action possibilities", a spoon affords eating. That framing is fine for
ergonomics and wrong here. If this module recorded that a spoon affords eating,
the experiment would have written down a claim about purpose that nobody
observed, in a file whose whole purpose is to record what *was* observed.

So the vocabulary is
:mod:`birth.boundary` and not Gibson. An :class:`Affordance` records:

* a **modality** — how it can be perceived at all;
* a **trigger** — a condition under which something happens;
* an **observable consequence** — what a probe or interaction can show;
* a **resource effect** — what it consumes or changes, where that is known.

Purpose is absent, and its absence is checked:
:data:`FORBIDDEN_SEMANTIC_FIELDS` names the fields that would reintroduce it
("purpose", "for", "affordance_purpose", "function", "use", "meaning",
"semantic_role", "educational_value", "label", "category"), and
:class:`Affordance` refuses to be constructed if any of them appear. A spoon can
be described by its shape, its mass, its temperature, and what happens when
something is put in it. What it is *for* is not a measurement, so there is no
field for it.

Restricted environment
----------------------
:class:`RestrictedEnvironment` describes what the subject could be given access
to, and refuses to invent a richer one. In Milestone 003 nothing is attached:
:meth:`RestrictedEnvironment.connected` is ``False`` and every query against it
reports unavailability. A simulated kitchen or a simulated room would be
indistinguishable, six months later, from a real one in the logs, so the
simulation does not exist.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from babylab.errors import ValidationError
from babylab.hashing import canonical_bytes, sha256_hex

AFFORDANCE_SCHEMA = "babylab/affordance/v1"
ENVIRONMENT_SCHEMA = "babylab/environment/v1"

#: Field names that would smuggle purpose or pedagogy into a physical record.
#: Checked at construction; see the module docstring for why.
FORBIDDEN_SEMANTIC_FIELDS = frozenset(
    {
        "affordance_purpose",
        "category",
        "educational_value",
        "for",
        "function",
        "intended_use",
        "label",
        "meaning",
        "purpose",
        "semantic_role",
        "should_do",
        "teaches",
        "use",
    }
)


class Modality(str, enum.Enum):
    """How something can be perceived. Not what it is for."""

    VISUAL = "VISUAL"
    TACTILE = "TACTILE"
    AUDITORY = "AUDITORY"
    THERMAL = "THERMAL"
    PROXIMITY = "PROXIMITY"
    FORCE = "FORCE"
    NONE = "NONE"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


class Availability(str, enum.Enum):
    """Whether a described affordance can actually be exercised.

    ``DESCRIBED`` is the Milestone 003 state for everything: the description
    exists, nothing is connected. Distinct from ``AVAILABLE`` so that a
    description can never be mistaken for a capability.
    """

    DESCRIBED = "DESCRIBED"
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass(frozen=True)
class Affordance:
    """One physically observable property-and-consequence pairing.

    No purpose. See :data:`FORBIDDEN_SEMANTIC_FIELDS`.
    """

    affordance_id: str
    #: Neutral handle for the thing described, e.g. ``"object.a"``. Not a name
    #: for it: naming a thing "spoon" imports its purpose.
    handle: str
    modality: Modality
    trigger: str
    observable_consequence: str
    resource_effect: str = ""
    availability: Availability = Availability.DESCRIBED
    measurements: dict[str, Any] = field(default_factory=dict)
    schema: str = AFFORDANCE_SCHEMA

    def __post_init__(self) -> None:
        if not self.affordance_id:
            raise ValidationError("affordance_id must be a non-empty string")
        if not self.handle.strip():
            raise ValidationError("handle must be a non-empty string")
        if not self.trigger.strip():
            raise ValidationError("trigger must describe a condition, not a purpose")
        if not self.observable_consequence.strip():
            raise ValidationError(
                "observable_consequence must say what can be observed; an "
                "affordance whose consequence is unobservable is a claim"
            )
        for name, value in self.measurements.items():
            if str(name).lower() in FORBIDDEN_SEMANTIC_FIELDS:
                raise ValidationError(
                    f"measurement field {name!r} is a semantic label, not a "
                    "measurement. Record the quantity and its units instead "
                    "(e.g. 'length_cm': 14.2)."
                )

    def describe(self) -> str:
        return (
            f"{self.handle} [{self.modality.value}] when {self.trigger}, then "
            f"{self.observable_consequence}"
            + (f" (changes {self.resource_effect})" if self.resource_effect else "")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "affordance_id": self.affordance_id,
            "handle": self.handle,
            "modality": self.modality.value,
            "trigger": self.trigger,
            "observable_consequence": self.observable_consequence,
            "resource_effect": self.resource_effect,
            "availability": self.availability.value,
            "measurements": dict(self.measurements),
        }

    def content_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.to_dict()))


def spoon_like_affordance() -> Affordance:
    """A worked example: a bowl-shaped object described without purpose.

    This is the example the specification uses, so it is worth encoding precisely
    what the correct description contains and, more importantly, what it does
    not. Note there is no "for eating", no "utensil", no "function" field, and
    no confidence that it is a bowl at all — "concave" is a shape, "bowl" is a
    category.
    """
    return Affordance(
        affordance_id="AFF-EXAMPLE-0001",
        handle="object.a",
        modality=Modality.VISUAL,
        trigger="a probe or liquid is brought into the concave region",
        observable_consequence=(
            "liquid collects in the concavity and is retained; the object does "
            "not tip while supported from below"
        ),
        resource_effect="retains up to 400 ml before overflowing",
        availability=Availability.DESCRIBED,
        measurements={
            "outer_diameter_cm": 12.4,
            "wall_thickness_cm": 0.4,
            "mass_g": 310.0,
            "surface_temperature_c": 19.8,
        },
    )


class RestrictedEnvironment:
    """The boundary of what a subject could be connected to.

    Milestone 003 attaches nothing. The class exists so that the *ceiling* is
    written down: filesystem writes, network egress, process execution, and
    privileged control are outside the environment and cannot be added to it by
    configuration. A subject's environment is a set of observations and
    consequences, not an interface to the host.
    """

    schema = ENVIRONMENT_SCHEMA

    #: Declared out of scope, permanently, for a subject's environment.
    EXCLUDED = (
        "network-egress",
        "process-execution-outside-workspace",
        "privileged-control",
        "human-control-credentials",
        "filesystem-outside-workspace",
    )

    def __init__(
        self,
        environment_id: str = "env.unattached",
        affordances: list[Affordance] | None = None,
        sensors: list[str] | None = None,
        connected: bool = False,
        reason: str = "no environment is attached in Milestone 003",
    ):
        self.environment_id = environment_id
        self._affordances = list(affordances or [])
        self._sensors = list(sensors or [])
        self._connected = bool(connected)
        self._reason = reason
        for affordance in self._affordances:
            if affordance.availability is Availability.AVAILABLE and not self._connected:
                raise ValidationError(
                    f"affordance {affordance.affordance_id} claims to be AVAILABLE "
                    "while the environment is not connected. A description cannot "
                    "be exercised without a connection; one of the two is wrong."
                )

    @property
    def connected(self) -> bool:
        return self._connected

    def reason(self) -> str:
        return self._reason

    def sensors(self) -> list[str]:
        return list(self._sensors)

    def affordances(self) -> list[Affordance]:
        return list(self._affordances)

    def describe(self, affordance_id: str) -> dict[str, Any]:
        """Describe one affordance, or report honestly that it cannot be."""
        for affordance in self._affordances:
            if affordance.affordance_id == affordance_id:
                if not self._connected:
                    return {
                        "affordance_id": affordance_id,
                        "status": "UNAVAILABLE",
                        "detail": (
                            f"described but not exercisable: {self._reason}. The "
                            "description is a record of what a sensor would see, "
                            "not an interaction that occurred."
                        ),
                        "affordance": affordance.to_dict(),
                    }
                return {
                    "affordance_id": affordance_id,
                    "status": "AVAILABLE",
                    "detail": affordance.describe(),
                    "affordance": affordance.to_dict(),
                }
        return {
            "affordance_id": affordance_id,
            "status": "UNKNOWN",
            "detail": f"no affordance {affordance_id!r} is described",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "environment_id": self.environment_id,
            "connected": self._connected,
            "reason": self._reason,
            "sensors": list(self._sensors),
            "excluded": list(self.EXCLUDED),
            "affordances": [item.to_dict() for item in self._affordances],
        }

    def content_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.to_dict()))


def unattached_environment() -> RestrictedEnvironment:
    """The environment as it honestly stands: described, connected to nothing."""
    return RestrictedEnvironment(
        affordances=[spoon_like_affordance()],
        sensors=[],
        connected=False,
    )


__all__ = [
    "AFFORDANCE_SCHEMA",
    "ENVIRONMENT_SCHEMA",
    "FORBIDDEN_SEMANTIC_FIELDS",
    "Affordance",
    "Availability",
    "Modality",
    "RestrictedEnvironment",
    "spoon_like_affordance",
    "unattached_environment",
]
