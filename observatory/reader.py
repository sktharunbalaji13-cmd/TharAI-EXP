"""Incremental event consumption for the Observatory.

Why this exists rather than reusing ``TerminalObserver`` directly
----------------------------------------------------------------
The terminal observer is a *renderer* that happens to tail. The Observatory
needs the consumption half on its own, because it must be able to:

* ingest a bounded batch and return, for a web API or a test;
* know exactly which events it has already seen, so re-reading is harmless;
* notice a log that was rotated or truncated underneath it;
* be linear in the number of events, not quadratic.

Design notes
------------
**Byte offsets, not line numbers.** :meth:`observatory.reader.ObservatoryReader.poll`
resumes from a byte offset, so a process restart costs one seek rather than a
full re-read. This mirrors ``EventStore.follow`` rather than inventing a second
tailing scheme, so there is one behaviour to reason about.

**Idempotent ingest.** Every event ID already seen is skipped. Replaying the
whole log therefore produces the same state, which is what makes the derived
state a pure function of the event store — a property the provenance story
depends on.

**Faults are values.** A malformed line increments a counter and is retained for
display. It never raises, because one corrupt line must not blind the
Observatory to the rest of the record, and it must never be silently dropped,
because a gap in a research log looks exactly like an absence of events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from babylab.clock import Clock
from babylab.paths import ProjectPaths, default_paths
from events.model import Event, parse_event_id
from events.store import EventStore, StoredEvent


@dataclass
class IngestReport:
    """What one ingest pass did."""

    accepted: int = 0
    duplicates: int = 0
    malformed: int = 0
    out_of_order: int = 0
    resets: int = 0

    def merge(self, other: "IngestReport") -> "IngestReport":
        return IngestReport(
            accepted=self.accepted + other.accepted,
            duplicates=self.duplicates + other.duplicates,
            malformed=self.malformed + other.malformed,
            out_of_order=self.out_of_order + other.out_of_order,
            resets=self.resets + other.resets,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "duplicates": self.duplicates,
            "malformed": self.malformed,
            "out_of_order": self.out_of_order,
            "resets": self.resets,
        }


@dataclass
class ObservatoryReader:
    """Consumes the canonical event log without ever writing to it.

    Attributes
    ----------
    store:
        The canonical :class:`events.store.EventStore`. Held for reading only.
    seen_ids:
        Event IDs already ingested. Bounded by the log, so memory is O(events)
        in the worst case; that is the price of exact idempotence and it is
        accepted, because a duplicate silently applied twice would corrupt the
        derived state.
    highest_seq:
        Highest sequence number accepted so far, used to detect an event that
        arrives out of order. An out-of-order event is *accepted and flagged*,
        never dropped, because a laboratory should record what it saw even when
        the ordering is wrong.
    """

    store: EventStore
    clock: Clock = field(default_factory=Clock)
    seen_ids: set[str] = field(default_factory=set)
    highest_seq: int = 0
    offset: int = 0
    generation: int = 0
    malformed_lines: list[tuple[int, str]] = field(default_factory=list)
    out_of_order_ids: list[str] = field(default_factory=list)
    total_ingested: int = 0
    _started: bool = False
    _buffer: str = ""
    _line_number: int = 0
    _accepted: list[Event] = field(default_factory=list)
    _identity: tuple[int, int] | None = None

    # -- construction -----------------------------------------------------
    @classmethod
    def for_paths(
        cls, paths: ProjectPaths | None = None, clock: Clock | None = None
    ) -> "ObservatoryReader":
        resolved = paths or default_paths()
        return cls(
            store=EventStore(resolved.event_store, clock=clock or Clock()),
            clock=clock or Clock(),
        )

    # -- ingest -----------------------------------------------------------
    def ingest_event(self, event: Event) -> bool:
        """Accept one event. Returns False if it was a duplicate.

        The single funnel every other ingest path goes through, so duplicate
        suppression cannot be bypassed by adding a new entry point later.
        """
        if event.event_id in self.seen_ids:
            return False
        self.seen_ids.add(event.event_id)
        self.total_ingested += 1
        if event.seq < self.highest_seq:
            self.out_of_order_ids.append(event.event_id)
        else:
            self.highest_seq = event.seq
        return True

    def _ingest_stored(self, stored: StoredEvent, report: IngestReport) -> bool:
        if not stored.ok or stored.event is None:
            self.malformed_lines.append((stored.line_number, stored.error or "unknown"))
            report.malformed += 1
            return False
        if not self.ingest_event(stored.event):
            report.duplicates += 1
            return False
        if stored.event.event_id in self.out_of_order_ids:
            report.out_of_order += 1
        report.accepted += 1
        self._accepted.append(stored.event)
        return True

    def drain_accepted(self) -> list[Event]:
        """Return and clear the events accepted since the last drain.

        Lets a downstream consumer (the state deriver) see exactly the new
        events without re-reading the log. Keeping this buffer is what makes
        ``update()`` O(new events) instead of O(log size) per refresh.
        """
        accepted = self._accepted
        self._accepted = []
        return accepted

    def replay(self) -> IngestReport:
        """Ingest the whole log from the beginning.

        Linear in the number of lines. Used for initial state and by tests.
        """
        report = IngestReport()
        for stored in self.store.read_all():
            self._ingest_stored(stored, report)
        path = Path(self.store.path)
        if path.exists():
            self._record_identity(path)
        self.offset = self.store.current_offset()
        self._line_number = self.store.count() + len(self.malformed_lines)
        self._buffer = ""
        self._started = True
        return report

    def poll(self) -> IngestReport:
        """Ingest whatever has been appended since the last poll.

        Resumes from the stored byte offset, so a long-lived Observatory does
        not re-read the log for every new event. Cost is proportional to the
        bytes newly appended, so ingesting N events is O(N) overall rather than
        O(N^2).

        A partially written trailing line is held in a buffer and not parsed
        until its newline arrives. The event store writes each line with a
        single ``write`` + ``fsync`` under a lock, so this is belt-and-braces,
        but reading a torn line would surface a spurious "malformed" fault for
        a record that is merely still in flight.
        """
        report = IngestReport()
        if not self._started:
            return self.replay()

        path = Path(self.store.path)
        if not path.exists():
            return report

        size = path.stat().st_size
        if self._reset_needed(path, size):
            report.resets += 1
            self.offset = 0
            self._buffer = ""
            self._line_number = 0
            self._record_identity(path)

        if size == self.offset:
            return report

        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            handle.seek(self.offset)
            chunk = handle.read()
            self.offset = handle.tell()

        self._buffer += chunk
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._line_number += 1
            stored = self.store.parse_line(self._line_number, line)
            self._ingest_stored(stored, report)
        return report

    def _record_identity(self, path: Path) -> None:
        """Remember which file we were reading, to notice it being replaced.

        On Windows and POSIX a replaced file gets a new identity even when it is
        larger than the old one, so this catches a swap that a size comparison
        cannot. Identity is ``None`` where the platform does not report one, and
        a ``None`` identity simply disables the check rather than guessing.
        """
        try:
            info = path.stat()
            identity = (info.st_dev, info.st_ino) if info.st_ino else None
        except OSError:  # pragma: no cover - exotic filesystems
            identity = None
        self._identity = identity

    def _reset_needed(self, path: Path, size: int) -> bool:
        """True when the log was rotated or replaced under us.

        Either signal counts, because they catch different real failures:
        a truncated file (size shrank) and a swapped file (identity changed).
        Neither is silently absorbed, because resuming at a stale offset would
        splice two different logs together and present the result as one history.
        """
        if size < self.offset:
            self.generation += 1
            return True
        if self._identity is not None:
            try:
                info = path.stat()
                identity = (info.st_dev, info.st_ino) if info.st_ino else None
            except OSError:  # pragma: no cover - exotic filesystems
                identity = None
            if identity is not None and identity != self._identity:
                self.generation += 1
                return True
        return False

    def _on_reset(self, message: str, report: IngestReport) -> None:
        self.generation += 1
        report.resets += 1
        self.malformed_lines.append((0, f"log reset: {message}"))

    def drain(self, max_passes: int = 1) -> IngestReport:
        """Ingest available events. Exists for readability at call sites."""
        report = IngestReport()
        for _ in range(max_passes):
            step = self.poll()
            report = report.merge(step)
            if step.accepted == 0 and step.malformed == 0:
                break
        return report

    # -- queries ----------------------------------------------------------
    def ingested_count(self) -> int:
        return self.total_ingested

    def last_seq(self) -> int:
        return self.highest_seq

    def state(self) -> dict[str, Any]:
        """Serialisable cursor, for a future resumable session."""
        return {
            "offset": self.offset,
            "generation": self.generation,
            "ingested": self.total_ingested,
            "highest_seq": self.highest_seq,
            "malformed_lines": len(self.malformed_lines),
            "out_of_order": len(self.out_of_order_ids),
        }

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"ObservatoryReader({self.store.path}, ingested={self.total_ingested}, "
            f"gen={self.generation})"
        )


def event_by_id(store: EventStore, event_id: str) -> Event | None:
    """Look one event up by ID. Linear; only for diagnostics and tests.

    The Observatory never calls this on a hot path — that would be O(n) per
    lookup and quietly reintroduce the quadratic behaviour the reader exists to
    avoid.
    """
    try:
        target = parse_event_id(event_id)
    except Exception:
        return None
    for event in store.iter_events():
        if event.seq == target:
            return event
    return None


def sort_by_seq(events: Iterable[Event]) -> list[Event]:
    """Canonical ordering. Timestamps can collide at millisecond precision."""
    return sorted(events, key=lambda item: item.seq)
