"""Deriving cognitive state from events.

The derivation rule
-------------------
A subject's cognitive state is whatever the subject has *said*. An event
payload may carry a ``state`` object, mapping domain names to reported values.
The deriver copies those through as :attr:`~observatory.model.EpistemicStatus.OBSERVED`.

Nothing else is observed. That is the whole rule, and it is worth stating
plainly because the temptation in this project is always to add a little more
inference:

* An event type does not imply a state. ``tool.use`` does not mean the subject
  was thinking about tools. It means a tool was used.
* A missing domain is not an empty domain. See :mod:`observatory.model`.
* Lab infrastructure events describe *the laboratory*, not a subject. When no
  subject is attached, they contribute nothing to cognitive state — they are
  still counted, still shown, and still available in history, but they are not
  dressed up as somebody's mind.
* No value is inferred from aggregates. Event counts, timestamps and sources are
  metadata about the record, not cognitive content.

The one thing the deriver does compute is
:attr:`~observatory.model.EpistemicStatus.DERIVED` *liveness*: whether the
subject has reported anything recently, computed purely from event timestamps.
That is genuinely derivable, is labelled ``DERIVED``, and cites its events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from babylab.clock import Clock
from events.model import Event, parse_timestamp
from observatory.attribution import Attributor, AttributionKind
from observatory.model import (
    CognitiveState,
    EpistemicStatus,
    StateTransition,
    StateValue,
)

#: Key in an event payload under which a subject may report cognitive state.
#: A single reserved key rather than a new event taxonomy, so that adding a
#: domain does not require a code change or an ADR (see ADR-004).
STATE_KEY = "state"

#: How long without a report before liveness is reported as false. Long
#: compared to the observer's refresh, short enough to be meaningful in a
#: session. Deliberately a constant rather than a tunable, because a tunable
#: threshold invites tuning it until the answer looks good.
LIVENESS_WINDOW = timedelta(seconds=60)


@dataclass
class StateDeriver:
    """Folds subject events into :class:`CognitiveState` versions.

    Maintains a transition log so that ``observatory.cli history`` can show what
    changed and why, with the causing event IDs attached (§13).
    """

    attributor: Attributor = field(default_factory=Attributor)
    subject_id: str | None = None
    clock: Clock = field(default_factory=Clock)
    _domains: dict[str, StateValue] = field(default_factory=dict)
    _version: int = 0
    _transitions: list[StateTransition] = field(default_factory=list)
    _processed: set[str] = field(default_factory=set)
    _last_report_at: datetime | None = None
    _last_seq: int = 0

    # -- ingestion --------------------------------------------------------
    def apply(self, event: Event) -> StateTransition | None:
        """Fold one event in. Returns a transition, or ``None`` if nothing changed."""
        if event.event_id in self._processed:
            return None
        self._processed.add(event.event_id)

        attribution = self.attributor.attribute(event)
        if attribution.kind is not AttributionKind.SUBJECT:
            # Infrastructure or unattributable. Recorded in the stream, visible
            # in the UI, but it is not a statement about a mind.
            self._last_seq = max(self._last_seq, event.seq)
            return None

        reported = _extract_state(event)
        if reported is None:
            self._last_seq = max(self._last_seq, event.seq)
            return None

        self._last_seq = max(self._last_seq, event.seq)
        self.note_report_time(_event_time(event, self.clock.now()))
        changed: list[str] = []
        for domain, value in reported.items():
            incoming = StateValue.observed(domain, value, (event.event_id,))
            existing = self._domains.get(domain)
            if existing is not None and existing.value == value:
                # Re-reported identically. Not a state change, but the newest
                # source event is the one that a reader would want to cite.
                self._domains[domain] = incoming
                continue
            self._domains[domain] = incoming
            changed.append(domain)

        if not changed:
            return None

        self._version += 1
        transition = StateTransition(
            version=self._version,
            cause_event_ids=(event.event_id,),
            reason=f"subject reported {', '.join(sorted(changed))}",
            changed_domains=tuple(sorted(changed)),
            timestamp=event.timestamp,
        )
        self._transitions.append(transition)
        return transition

    def apply_all(self, events: Iterable[Event]) -> list[StateTransition]:
        out: list[StateTransition] = []
        for event in events:
            transition = self.apply(event)
            if transition is not None:
                out.append(transition)
        return out

    # -- derived state ----------------------------------------------------
    def liveness(self, now: datetime) -> StateValue:
        """Whether the subject reported recently. Labelled ``DERIVED``.

        With no subject there is no liveness, so this is ``UNAVAILABLE``. A
        system reporting "the subject is not currently active" when no subject
        exists would be inventing an entity to then describe.
        """
        if self.subject_id is None:
            return StateValue.unavailable(
                "liveness", note="no subject is attached, so it cannot be active"
            )
        last = self._last_report_at
        if last is None:
            return StateValue.unavailable(
                "liveness", note="the subject has never reported"
            )
        active = (now - last) <= LIVENESS_WINDOW
        source = self._transitions[-1].cause_event_ids if self._transitions else ()
        return StateValue.derived("liveness", active, source, note="time since last report")

    def snapshot(self, now: datetime, timestamp: str = "") -> CognitiveState:
        """The current state, plus derived liveness."""
        domains = dict(self._domains)
        domains["liveness"] = self.liveness(now)
        state = CognitiveState(
            subject_id=self.subject_id,
            version=self._version,
            timestamp=timestamp,
            domains=domains,
            last_event_id=self._transitions[-1].cause_event_ids[0] if self._transitions else None,
            last_event_seq=self._last_seq,
        )
        return state

    def history(self) -> list[StateTransition]:
        return list(self._transitions)

    def version(self) -> int:
        return self._version

    def note_report_time(self, when: datetime) -> None:
        """Record when the subject last reported, for liveness."""
        if self._last_report_at is None or when > self._last_report_at:
            self._last_report_at = when

    def stats(self) -> dict[str, int]:
        return {
            "processed_events": len(self._processed),
            "state_versions": self._version,
            "reported_domains": len(self._domains),
        }


def _event_time(event: Event, fallback: datetime) -> datetime:
    """Timestamp for an event, used only for the liveness window.

    A timestamp that will not parse degrades to ``fallback`` rather than
    raising: an unparseable timestamp is a formatting oddity, and losing the
    ability to observe the rest of the log over it would be a bad trade.
    """
    try:
        return parse_timestamp(event.timestamp)
    except (ValueError, TypeError):
        return fallback


def _extract_state(event: Event) -> dict[str, Any] | None:
    """Pull the reported ``state`` object out of an event payload.

    Returns ``None`` when the event carries no state report. A ``state`` key
    that is present but empty yields ``{}``, which counts as "reported nothing"
    rather than "did not report" — a distinction the subject's own tooling
    controls and which we pass through rather than second-guess.
    """
    payload = event.payload
    if not isinstance(payload, dict):
        return None
    reported = payload.get(STATE_KEY)
    if reported is None:
        return None
    if not isinstance(reported, dict):
        # A subject reported something that is not a domain map. Do not guess at
        # the intent; record nothing and let the malformed-domain case surface.
        return None
    return reported


__all__ = ["StateDeriver", "STATE_KEY", "LIVENESS_WINDOW", "EpistemicStatus"]
