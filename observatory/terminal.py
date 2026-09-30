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
        self._foundation = self._read_foundation()
        self._runtime_verification = self._read_runtime_verification()
        self._deployment = self._read_deployment()
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

    def _read_foundation(self) -> dict[str, Any]:
        """Ask the M010 foundation layer what it reports, tolerating failure.

        Read with ``with_runtime_probe=False`` on purpose. Probing means
        executing the configured binary, and a view that can trigger the
        execution it is reporting on is not a view -- it would also make polling
        this display far more expensive than reading a file. The panel therefore
        reports the runtime as unprobed and leaves the probe to the validation
        command, which records it properly.
        """
        from babylab.errors import BabyLabError

        try:
            from foundation.status import foundation_status

            return foundation_status(
                self.paths.root, with_runtime_probe=False
            ).to_dict()
        except (BabyLabError, OSError, ValueError) as exc:
            return {
                "model_configured": None,
                "artifact": {"status": "UNAVAILABLE", "verified": False},
                "runtime": {"state": "UNAVAILABLE"},
                "detail": f"the foundation layer could not be read: {exc}",
                "explicitly_not": {
                    "subject": "no subject exists",
                    "birth": "birth was not performed",
                },
            }

    def _read_runtime_verification(self) -> dict[str, Any]:
        """The M011 runtime-verification panel, without executing anything.

        Uses :func:`foundation.m011_status.capability_only`, which reads the
        privilege state and the account and stops there. It deliberately does
        **not** call ``verification.verify()``: that would launch a process and
        hash a multi-gigabyte artifact every time the display was polled, and a
        view whose refresh rate depends on how much work the thing it observes
        does is not a view.

        The full verification is a command, and the panel reports the host's
        capability to run it.
        """
        from babylab.errors import BabyLabError

        try:
            from foundation.m011_status import capability_only

            return capability_only(self.paths.root)
        except (BabyLabError, OSError, ValueError) as exc:
            return {
                "inference_mode": "NOT_TESTABLE",
                "inference_outcome": "NOT_RUN",
                "restricted_account_runtime": "NOT_TESTABLE",
                "restricted_account_reason": (
                    f"the runtime-verification panel could not be read: {exc}"
                ),
                "subject": "NONE",
                "birth": "NOT_PERFORMED",
            }

    def _read_deployment(self) -> dict[str, Any]:
        """The declared foundation selection, read without verifying anything.

        :func:`foundation.m012_status.deployment_only` reads the declaration and
        the candidate report. It does not hash the artifact, probe the runtime,
        load a model, or run an inference -- any of which on every poll would make
        this display the most expensive process in the laboratory, and a panel
        that performs the verification it reports is not a panel.
        """
        from babylab.errors import BabyLabError

        try:
            from foundation.m012_status import deployment_only

            return deployment_only(self.paths.root)
        except (BabyLabError, OSError, ValueError) as exc:
            return {
                "human_model_selection": "UNAVAILABLE",
                "human_runtime_selection": "UNAVAILABLE",
                "model_path": "UNAVAILABLE",
                "runtime_path": "UNAVAILABLE",
                "real_runtime": "NOT_TESTABLE",
                "compatibility": "UNKNOWN",
                "subject": "NONE",
                "birth": "NOT_PERFORMED",
                "note": f"the deployment panel could not be read: {exc}",
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
            foundation=self._foundation,
            runtime_verification=self._runtime_verification,
            deployment=self._deployment,
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
