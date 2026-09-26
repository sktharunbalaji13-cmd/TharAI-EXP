"""Attribution: deciding who an event came from, without believing the event.

The trap this module exists to avoid
-----------------------------------
An event carries a ``source`` field. It is tempting to read it and conclude
"this event came from the subject". That would be a serious error, and
``events/model.py`` already says why in its own docstring: ``source`` is *a
component name, not an authorship claim*.

Concretely, a future subject will be able to append events, and it will be able
to set ``source`` to anything at all. So:

* ``event.source = "subject.runtime"`` proves nothing. Anyone can write it.
* ``payload["author"] = "BABY_AI"`` proves nothing. Anyone can write it.

The only attribution the Observatory will make is one backed by the
human-owned keyring, or one that is explicitly labelled as an *infrastructure
namespace* observation rather than an identity claim.

Two kinds of attribution, kept apart
------------------------------------
======================  ==============================================
:attr:`AttributionKind` Meaning
======================  ==============================================
``INFRASTRUCTURE``      The event came from a laboratory component.
                        Observed from the event's namespace, which the
                        laboratory controls. This says *what produced
                        the record*, not *who is accountable for it*.
``SUBJECT``             The event is attributable to a real, key-backed
                        subject. Only possible once a subject exists.
``UNATTRIBUTED``        The event's origin cannot be established. Named
                        as unknown rather than assumed.
======================  ==============================================

§18 asks the Observatory to distinguish ``SYSTEM EVENT``, ``HUMAN EVENT`` and
``SUBJECT EVENT``. This module can honestly produce ``SUBJECT EVENT`` only for a
registered subject. For everything else it reports the component that emitted
the record and labels the distinction, rather than inventing an identity from a
string the producer chose.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any

from events.model import INFRASTRUCTURE_NAMESPACES, Event


class AttributionKind(str, enum.Enum):
    """How confidently an event's origin was established."""

    INFRASTRUCTURE = "INFRASTRUCTURE"
    SUBJECT = "SUBJECT"
    UNATTRIBUTED = "UNATTRIBUTED"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass(frozen=True)
class Attribution:
    """What the Observatory believes about who produced an event."""

    kind: AttributionKind
    label: str
    basis: str
    event_id: str

    @property
    def is_subject(self) -> bool:
        return self.kind is AttributionKind.SUBJECT

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "label": self.label,
            "basis": self.basis,
            "event_id": self.event_id,
        }


class Attributor:
    """Assigns :class:`Attribution` to events.

    ``subject_namespace`` is the set of event namespaces a real subject is
    permitted to write under. It is empty in Milestone 002 because no subject
    exists. It is *configuration*, not a schema: when a subject does exist, its
    namespaces are declared by the human alongside its key, and any namespace
    the subject invents beyond those is reported as UNATTRIBUTED rather than
    quietly accepted. See docs/observability-principles.md.
    """

    def __init__(
        self,
        subject_namespace: frozenset[str] | None = None,
        subject_label: str | None = None,
    ):
        self._namespaces = subject_namespace or frozenset()
        self._label = subject_label

    # -- properties -------------------------------------------------------
    @property
    def expects_subject_events(self) -> bool:
        return bool(self._namespaces)

    def subject_namespaces(self) -> frozenset[str]:
        return self._namespaces

    # -- the decision -----------------------------------------------------
    def attribute(self, event: Event) -> Attribution:
        namespace = event.namespace()

        if self._namespaces and namespace in self._namespaces:
            return Attribution(
                kind=AttributionKind.SUBJECT,
                label=self._label or "SUBJECT",
                basis=(
                    "namespace declared by the human for a key-backed subject; "
                    "the event itself asserted nothing"
                ),
                event_id=event.event_id,
            )

        if not self._namespaces:
            return Attribution(
                kind=AttributionKind.INFRASTRUCTURE,
                label=namespace.upper(),
                basis=(
                    "laboratory infrastructure namespace; no subject is "
                    "attached, so this cannot be subject activity"
                ),
                event_id=event.event_id,
            )

        if namespace in INFRASTRUCTURE_NAMESPACES:
            # A known laboratory namespace stays infrastructure even once a
            # subject exists. The control plane did not become the subject.
            return Attribution(
                kind=AttributionKind.INFRASTRUCTURE,
                label=namespace.upper(),
                basis="known laboratory infrastructure namespace",
                event_id=event.event_id,
            )

        return Attribution(
            kind=AttributionKind.UNATTRIBUTED,
            label=namespace.upper(),
            basis=(
                "namespace is neither laboratory infrastructure nor one the "
                "human declared for the subject, so its origin is unknown"
            ),
            event_id=event.event_id,
        )

    def partition(self, events: list[Event]) -> dict[AttributionKind, list[Event]]:
        """Split events by attribution kind. Used by the state deriver."""
        buckets: dict[AttributionKind, list[Event]] = {
            kind: [] for kind in AttributionKind
        }
        for event in events:
            buckets[self.attribute(event).kind].append(event)
        return buckets

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        if not self._namespaces:
            return "Attributor(no subject attached)"
        return f"Attributor({self._label!r}, {sorted(self._namespaces)})"
