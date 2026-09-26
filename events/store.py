"""JSON Lines event store: append-only, hash-chained, concurrently readable.

Architecture position
---------------------
The event store sits between producers and every consumer::

    Event Producers -> Event Store -> Terminal Observer
                                      -> Future Web Observatory (not built)

The store is the single source of truth. Consumers hold no state that is not
derivable from it. That is what will let a future web Observatory be added
without it becoming authoritative, and what lets the human reconstruct what
happened from the log alone (docs/architecture.md).

Durability and concurrency
--------------------------
* Appends are a single ``write`` + ``flush`` + ``fsync`` of one line, taken
  under an exclusive advisory lock, so a reader never sees a partial line and
  two writers never interleave.
* The file is never rewritten or truncated by this module. There is no
  ``update`` or ``delete`` API, by design.
* Readers track a byte offset. If the file shrinks, the reader assumes it was
  rotated or replaced and re-opens, reporting a ``log_reset`` condition rather
  than silently continuing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from babylab.clock import Clock
from babylab.errors import ValidationError
from babylab.storage import append_line, exclusive_lock
from events.model import Event, format_event_id, parse_event_id

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class StoredEvent:
    """A line read back from the store, valid or not.

    Malformed lines are returned rather than raised so that one corrupt line
    cannot blind an observer to the rest of the history. ``error`` is populated
    for such lines and the raw text is preserved for diagnosis.
    """

    line_number: int
    raw: str
    event: Event | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict:
        return {
            "line_number": self.line_number,
            "ok": self.ok,
            "error": self.error,
            "event": self.event.to_dict() if self.event else None,
        }


@dataclass(frozen=True)
class ChainReport:
    """Outcome of :meth:`EventStore.verify_chain`."""

    total_lines: int
    valid_events: int
    malformed_lines: int
    head_hash: str
    problems: list[str]

    @property
    def intact(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict:
        return {
            "intact": self.intact,
            "total_lines": self.total_lines,
            "valid_events": self.valid_events,
            "malformed_lines": self.malformed_lines,
            "head_hash": self.head_hash,
            "problems": list(self.problems),
        }

    def render(self) -> str:
        from babylab.hashing import canonical_json

        return canonical_json(self.to_dict())


class EventStore:
    """Append-only, hash-chained event log stored as JSON Lines.

    Head caching
    ------------
    Finding the head means knowing the last line. Re-reading the whole file on
    every append is O(n^2) over a session and becomes the dominant cost once
    the log reaches tens of thousands of events - which it will, because the
    log is the primary research record.

    So the head is cached in memory together with the file size it was derived
    from. Under the append lock, an unchanged size means no other writer has
    appended since, so the cache is still correct. Any size mismatch forces a
    rescan, which also handles an external writer correctly.
    """

    def __init__(self, path: Path, clock: Clock | None = None):
        self.path = Path(path)
        self.clock = clock or Clock()
        self._cached_head: Event | None = None
        self._cached_size: int | None = None
        self._cache_valid = False

    # -- writing ----------------------------------------------------------
    def append(self, event_type: str, source: str, payload: dict | None = None) -> Event:
        """Append one event and return the sealed record.

        Sequence number, timestamp, ``prev_hash`` and ``hash`` are all assigned
        here, under the same lock, so callers cannot accidentally create a fork
        in the chain by racing.
        """
        with exclusive_lock(self.path):
            head = self._head_unlocked()
            seq = (head.seq + 1) if head is not None else 1
            event = Event.create(
                seq=seq,
                event_type=event_type,
                source=source,
                payload=payload,
                moment=self.clock.now(),
                prev_hash=head.hash if head is not None else GENESIS_HASH,
            )
            append_line(self.path, event.to_json())
            self._remember_head(event)
            return event

    def append_many(self, records: list[tuple[str, str, dict]]) -> list[Event]:
        """Append several events under a single lock acquisition.

        Used by bootstrap so that a group of infrastructure events cannot be
        split by an interleaved writer.
        """
        created: list[Event] = []
        with exclusive_lock(self.path):
            head = self._head_unlocked()
            seq = head.seq if head is not None else 0
            for event_type, source, payload in records:
                seq += 1
                event = Event.create(
                    seq=seq,
                    event_type=event_type,
                    source=source,
                    payload=payload,
                    moment=self.clock.now(),
                    prev_hash=head.hash if head is not None else GENESIS_HASH,
                )
                append_line(self.path, event.to_json())
                created.append(event)
                head = event
            self._remember_head(head)
        return created

    # -- reading ----------------------------------------------------------
    def head(self) -> Event | None:
        """Most recent event, or ``None`` for an empty store."""
        with exclusive_lock(self.path):
            return self._head_unlocked()

    def _current_size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def _remember_head(self, head: Event | None) -> None:
        self._cached_head = head
        self._cached_size = self._current_size()
        self._cache_valid = True

    def _head_unlocked(self) -> Event | None:
        if self._cache_valid and self._cached_size == self._current_size():
            return self._cached_head
        last: Event | None = None
        for stored in self._iter_lines(0, None):
            if stored.ok and stored.event is not None:
                last = stored.event
        self._remember_head(last)
        return last

    def read_all(self) -> list[StoredEvent]:
        return list(self._iter_lines(0, None))

    def iter_events(self) -> Iterator[Event]:
        """Yield only well-formed events, skipping malformed lines."""
        for stored in self._iter_lines(0, None):
            if stored.ok and stored.event is not None:
                yield stored.event

    def count(self) -> int:
        return sum(1 for _ in self.iter_events())

    def _iter_lines(self, start_line: int, limit: int | None) -> Iterator[StoredEvent]:
        if not self.path.exists():
            return
        emitted = 0
        with open(self.path, "r", encoding="utf-8", errors="replace") as handle:
            for index, raw in enumerate(handle, start=1):
                if index <= start_line:
                    continue
                yield self._parse_line(index, raw.rstrip("\n"))
                emitted += 1
                if limit is not None and emitted >= limit:
                    return

    @staticmethod
    def parse_line(line_number: int, raw: str) -> StoredEvent:
        """Parse one log line into a :class:`StoredEvent`.

        Public so that incremental consumers (see :mod:`observatory.reader`)
        reuse exactly the same parsing and fault-reporting rules as a full
        replay. Two parsers would be two sets of error messages for the same
        corruption, and they would eventually disagree.
        """
        text = raw.strip()
        if not text:
            return StoredEvent(line_number, raw, None, "blank line")
        try:
            event = Event.from_json(text)
        except ValidationError as exc:
            return StoredEvent(line_number, raw, None, str(exc))
        return StoredEvent(line_number, raw, event, None)

    #: Retained so existing callers inside this module keep working.
    _parse_line = parse_line

    # -- integrity --------------------------------------------------------
    def verify_chain(self) -> ChainReport:
        """Recompute every hash and every ``prev_hash`` link.

        Detects modification of a payload, reordering, deletion from the
        middle, and corruption. It cannot detect truncation of the *tail*
        unless the expected head is known from outside the file; the
        provenance seal in ``human_control/provenance/`` is what provides that
        external anchor for research records.
        """
        expected_prev = GENESIS_HASH
        expected_seq = 1
        problems: list[str] = []
        valid = 0
        malformed = 0

        for stored in self._iter_lines(0, None):
            if not stored.ok or stored.event is None:
                malformed += 1
                problems.append(f"line {stored.line_number}: malformed ({stored.error})")
                continue
            event = stored.event
            if event.prev_hash != expected_prev:
                problems.append(
                    f"line {stored.line_number} ({event.event_id}): prev_hash "
                    f"{event.prev_hash[:12]}... expected {expected_prev[:12]}... "
                    f"(record removed, reordered, or rewritten)"
                )
            if event.seq != expected_seq:
                problems.append(
                    f"line {stored.line_number} ({event.event_id}): sequence "
                    f"{event.seq} breaks monotonic ordering (expected {expected_seq})"
                )
            recomputed = event.compute_hash()
            if recomputed != event.hash:
                problems.append(
                    f"line {stored.line_number} ({event.event_id}): hash mismatch, "
                    f"content was modified after it was written"
                )
            expected_prev = event.hash
            expected_seq = event.seq + 1
            valid += 1

        return ChainReport(
            total_lines=valid + malformed,
            valid_events=valid,
            malformed_lines=malformed,
            head_hash=expected_prev,
            problems=problems,
        )

    # -- tailing ----------------------------------------------------------
    def follow(
        self,
        from_offset: int = 0,
        poll_interval: float = 0.25,
        on_reset: Callable[[str], None] | None = None,
        stop: Callable[[], bool] | None = None,
    ) -> Iterator[StoredEvent]:
        """Yield events as they are appended.

        Yields :class:`StoredEvent` values, including malformed ones, so the
        consumer can display the fault instead of silently dropping it.
        """
        offset = max(0, from_offset)
        line_number = 0
        buffer = ""
        while stop is None or not stop():
            if not self.path.exists():
                _sleep(poll_interval)
                continue
            size = self.path.stat().st_size
            if size < offset:
                # The log was rotated or replaced. Do not guess: report it.
                if on_reset is not None:
                    on_reset(
                        f"event log shrank from {offset} to {size} bytes; "
                        f"tailing restarted from the beginning"
                    )
                offset = 0
                line_number = 0
                buffer = ""
            if size == offset:
                _sleep(poll_interval)
                continue

            with open(self.path, "r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                chunk = handle.read()
                offset = handle.tell()
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line_number += 1
                yield self._parse_line(line_number, line)

    def current_offset(self) -> int:
        if not self.path.exists():
            return 0
        return self.path.stat().st_size

    def summary(self) -> dict:
        """Counts by namespace, for the ``inspect`` control operation."""
        counts: dict[str, int] = {}
        for event in self.iter_events():
            counts[event.namespace()] = counts.get(event.namespace(), 0) + 1
        return {
            "path": str(self.path),
            "exists": self.path.exists(),
            "total_events": sum(counts.values()),
            "by_namespace": dict(sorted(counts.items())),
        }

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"EventStore({self.path})"


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)
