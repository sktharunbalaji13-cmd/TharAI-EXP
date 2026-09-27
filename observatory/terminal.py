"""The live Observatory session.

Wires the three collaborators together and owns the update loop:

* :class:`~observatory.subject.SubjectRegistry` — is there a subject?
* :class:`~observatory.reader.ObservatoryReader` — what has been recorded?
* :class:`~observatory.derive.StateDeriver` — what has the subject reported?

The session holds an :class:`~observatory.attribution.Attributor` so that every
event displayed is labelled with how its origin was established, and a renderer
so that a view can be produced from any snapshot.

Read-only by construction: the session is handed an
:class:`events.store.EventStore` and calls only reading methods on it. It has
no reference to any writer, no append path, and no provenance mutation. That is
asserted in ``tests/test_observatory_security.py``.

The birth state is read through :mod:`birth.status` rather than
:mod:`birth.service`, and that is not a stylistic choice. ``birth.service`` holds
the ceremony and therefore imports the event store's append path; importing it
here would put a writer into a read-only component's dependency graph and make
the security assertion above true only by convention. :mod:`birth.status` is the
half of the birth subsystem that cannot write anything.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from babylab.clock import Clock
from babylab.paths import ProjectPaths, default_paths
from birth.status import birth_status
from events.store import EventStore
from observatory.attribution import Attributor
from observatory.derive import StateDeriver
from observatory.reader import ObservatoryReader
from observatory.render import ObservatoryRenderer, RenderOptions
from observatory.snapshot import ObservatorySnapshot, compose_snapshot
from observatory.subject import SubjectRegistry

#: Refuse to render a snapshot more often than this in live mode, so a fast
#: event producer cannot spin the terminal. The event log is still fully
#: consumed; only the redraw is coalesced.
MIN_REDRAW_SECONDS = 0.05


@dataclass
class ObservatorySession:
    """A read-only observer of the canonical event store."""

    paths: ProjectPaths = field(default_factory=default_paths)
    clock: Clock = field(default_factory=Clock)
    refresh: float = 0.2
    keyring: Any | None = None
    subject_namespace: frozenset[str] | None = None
    subject_label: str | None = None

    def __post_init__(self) -> None:
        self.store = EventStore(self.paths.event_store, clock=self.clock)
        self._birth = self._read_birth()
        self.registry = SubjectRegistry(self.keyring, self._birth)
        self.reader = ObservatoryReader(store=self.store, clock=self.clock)
        self.attributor = Attributor(
            subject_namespace=self.subject_namespace, subject_label=self.subject_label
        )
        subject = self.registry.subject()
        self.deriver = StateDeriver(
            attributor=self.attributor,
            subject_id=subject.subject_id if subject else None,
        )
        self._recent: list = []
        self._started = False

    def _read_birth(self) -> dict[str, Any]:
        """Ask the birth subsystem what it reports, tolerating any failure.

        The Observatory must keep working in a laboratory where the birth
        subsystem cannot answer — a corrupt record, a half-written config, a
        permissions problem. A read-only observer that crashes because an
        unrelated subsystem is unhappy is not read-only, it is useless, so the
        failure is reported as a fact in the payload rather than raised.
        """
        from babylab.errors import BabyLabError

        try:
            return birth_status(self.paths)
        except (BabyLabError, OSError, ValueError) as exc:
            return {
                "subject_exists": False,
                "subject_id": "",
                "model_status": "UNAVAILABLE",
                "model_detail": f"the birth subsystem could not be read: {exc}",
                "read_error": str(exc),
            }

    # -- updating ---------------------------------------------------------
    def update(self) -> ObservatorySnapshot:
        """Consume new events and return the resulting snapshot.

        Cost is proportional to the events appended since the last call, not to
        the size of the log, so a long session stays responsive.
        """
        if self._started:
            self.reader.poll()
        else:
            self.reader.replay()
            self._started = True

        for event in self.reader.drain_accepted():
            self._recent.append(self.attributor.attribute(event))
            self.deriver.apply(event)
        if len(self._recent) > 10:
            self._recent = self._recent[-10:]

        return self.snapshot()

    def snapshot(self) -> ObservatorySnapshot:
        return compose_snapshot(
            self.registry,
            self.reader,
            self.deriver,
            now=self.clock.now(),
            timestamp=self.clock.timestamp(),
            recent_attributions=self._recent[-10:],
            birth=self._birth,
        )

    def render(self, options: RenderOptions | None = None) -> str:
        return ObservatoryRenderer(options or RenderOptions()).render(self.snapshot())

    def follow(self, render_options: RenderOptions | None = None, iterations: int | None = None) -> int:
        """Redraw until interrupted. Returns an exit code.

        ``iterations`` bounds the loop for tests; ``None`` runs until Ctrl-C,
        matching ``observer.cli``'s established behaviour.
        """
        renderer = ObservatoryRenderer(render_options or RenderOptions())
        count = 0
        try:
            while iterations is None or count < iterations:
                snapshot = self.update()
                if renderer.options.color:
                    print("\033[H\033[2J", end="")
                print(renderer.render(snapshot))
                count += 1
                if iterations is not None and count >= iterations:
                    break
                time.sleep(max(self.refresh, MIN_REDRAW_SECONDS))
        except KeyboardInterrupt:
            return 130
        return 0
