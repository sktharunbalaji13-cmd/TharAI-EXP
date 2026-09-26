"""The terminal observer.

What it is
----------
A read-only process that displays the event stream. It holds no authoritative
state, writes nothing into the event log, and has no privileged operations. If
it were deleted, no research record would be lost. That is the property that
keeps it an *observer* rather than part of the experiment.

Remaining useful at high volume
-------------------------------
A naive ``print`` per event cannot keep up once thousands of events arrive, and
a terminal that scrolls past unreadably is not an instrument. Three mechanisms
address this:

* **Batched writes.** Lines accumulate in a buffer and are flushed on a size or
  time threshold, so a burst costs a few writes rather than thousands.
* **A bounded ring buffer.** Recent lines are retained for ``--detail`` context
  and diagnostics without unbounded memory growth.
* **Aggregate mode.** ``--summary`` replaces the stream with running counts per
  category and event type, updated in place. At very high volume this is the
  readable view, because the question changes from "what did each event say" to
  "what is happening".

Malformed input
---------------
A corrupt line is displayed as a ``MALFORMED`` entry with its reason, and the
observer continues. Refusing to display a log because one line is broken would
make the observer useless exactly when it is needed.
"""

from __future__ import annotations

import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterable, TextIO

from babylab.clock import Clock
from babylab.paths import ProjectPaths, default_paths
from events.model import Event
from events.store import EventStore, StoredEvent
from observer.format import RenderOptions, Renderer, category_of, supports_colour

#: Flush the output buffer after this many lines.
FLUSH_LINES = 64

#: ...or after this many seconds, so a slow trickle still appears promptly.
FLUSH_SECONDS = 0.25

#: Retained lines for diagnostics. Bounded on purpose.
RING_SIZE = 512


@dataclass
class ObserverStats:
    displayed: int = 0
    malformed: int = 0
    filtered_out: int = 0
    batches: int = 0
    started_at: float = field(default_factory=time.monotonic)

    @property
    def elapsed(self) -> float:
        return max(1e-9, time.monotonic() - self.started_at)

    @property
    def rate(self) -> float:
        return self.displayed / self.elapsed

    def to_dict(self) -> dict:
        return {
            "displayed": self.displayed,
            "malformed": self.malformed,
            "filtered_out": self.filtered_out,
            "batches": self.batches,
            "elapsed_seconds": round(self.elapsed, 3),
            "events_per_second": round(self.rate, 1),
        }


class TerminalObserver:
    """Displays events from the store, then follows it live."""

    def __init__(
        self,
        paths: ProjectPaths | None = None,
        store: EventStore | None = None,
        stream: TextIO | None = None,
        options: RenderOptions | None = None,
        follow: bool = True,
        poll_interval: float = 0.25,
        max_history: int | None = None,
        namespaces: Iterable[str] | None = None,
        types: Iterable[str] | None = None,
        summary_mode: bool = False,
        progress_every: int = 0,
    ):
        self.paths = paths or default_paths()
        self.clock = Clock()
        self.stream = stream or sys.stdout
        self.store = store or EventStore(self.paths.event_store, clock=self.clock)
        self.renderer = Renderer(options or RenderOptions(), self.stream)
        self.follow = follow
        self.poll_interval = poll_interval
        self.max_history = max_history
        self.namespaces = set(namespaces) if namespaces else None
        self.types = set(types) if types else None
        self.summary_mode = summary_mode
        self.progress_every = progress_every

        self.stats = ObserverStats()
        self.recent: deque[str] = deque(maxlen=RING_SIZE)
        self._buffer: list[str] = []
        self._last_flush = time.monotonic()
        self._counts: dict[str, int] = {}
        self._type_counts: dict[str, int] = {}
        self._stop = threading.Event()

    # -- filtering --------------------------------------------------------
    def accepts(self, event: Event) -> bool:
        if self.namespaces is not None and event.namespace() not in self.namespaces:
            return False
        if self.types is not None and event.event_type not in self.types:
            return False
        return True

    # -- output buffering -------------------------------------------------
    def _emit_lines(self, lines: list[str]) -> None:
        self._buffer.extend(lines)
        self.recent.extend(lines)
        if len(self._buffer) >= FLUSH_LINES:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            self._last_flush = time.monotonic()
            return
        self.stream.write("\n".join(self._buffer) + "\n")
        self.stream.flush()
        self.stats.batches += 1
        self._buffer.clear()
        self._last_flush = time.monotonic()

    def _maybe_flush(self) -> None:
        if time.monotonic() - self._last_flush >= FLUSH_SECONDS:
            self.flush()

    # -- rendering entries ------------------------------------------------
    def render_stored(self, stored: StoredEvent) -> None:
        if not stored.ok or stored.event is None:
            self.stats.malformed += 1
            self._emit_lines(
                self.renderer.malformed_lines(stored.line_number, stored.raw, stored.error or "")
            )
            self._maybe_flush()
            return
        if not self.accepts(stored.event):
            self.stats.filtered_out += 1
            return

        self.stats.displayed += 1
        if self.summary_mode:
            self._count(stored.event)
        else:
            self._emit_lines(self.renderer.event_lines(stored.event))
        if self.progress_every and self.stats.displayed % self.progress_every == 0:
            self._emit_progress()
        self._maybe_flush()

    def _count(self, event: Event) -> None:
        category = category_of(event.event_type)
        self._counts[category] = self._counts.get(category, 0) + 1
        self._type_counts[event.event_type] = self._type_counts.get(event.event_type, 0) + 1

    def _emit_progress(self) -> None:
        self._emit_lines(
            self.renderer.notice(
                f"… {self.stats.displayed} events shown, "
                f"{self.stats.malformed} malformed, "
                f"{self.stats.filtered_out} filtered "
                f"({self.stats.rate:.0f}/s)"
            )
        )

    def render_all(self, stored: Iterable[StoredEvent]) -> None:
        for item in stored:
            self.render_stored(item)

    def summary_text(self) -> str:
        if not self._counts:
            return "no events matched"
        width = max(len(key) for key in self._counts)
        parts = [f"{key.ljust(width)}  {value}" for key, value in sorted(self._counts.items())]
        return "\n".join(parts)

    def render_summary(self) -> None:
        self.flush()
        if self.stream.isatty() if hasattr(self.stream, "isatty") else False:
            self.stream.write("\033[2J\033[H")
        self.stream.write("Event summary by category\n")
        self.stream.write("=" * 40 + "\n")
        self.stream.write(self.summary_text() + "\n")
        self.stream.write("\nBy event type\n")
        self.stream.write("=" * 40 + "\n")
        width = max((len(key) for key in self._type_counts), default=10)
        for key, value in sorted(self._type_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            self.stream.write(f"{key.ljust(width)}  {value}\n")
        self.stream.write(f"\n{self.stats.displayed} events matched, {self.stats.rate:.0f}/s\n")
        self.stream.flush()

    # -- sessions ---------------------------------------------------------
    def show_history(self) -> int:
        """Replay existing events. Returns how many were displayed."""
        stored = self.store.read_all()
        if self.max_history is not None and len(stored) > self.max_history:
            omitted = len(stored) - self.max_history
            self._emit_lines(
                self.renderer.notice(
                    f"… {omitted} earlier events omitted (--max-history "
                    f"{self.max_history})"
                )
            )
            stored = stored[-self.max_history :]
        self.render_all(stored)
        self.flush()
        if self.summary_mode:
            self.render_summary()
        return self.stats.displayed

    def run(self, on_ready: Callable[[], None] | None = None) -> int:
        """Replay history, then follow the log until interrupted."""
        if self.summary_mode:
            self._emit_lines(self.renderer.notice("summary mode: no per-event output"))
        self.show_history()

        if not self.follow:
            return self.stats.displayed

        if on_ready is not None:
            on_ready()

        # Start following from the current end so history is not shown twice.
        offset = self.store.current_offset()
        line_number = 0
        try:
            for stored in self.store.follow(
                from_offset=offset,
                poll_interval=self.poll_interval,
                on_reset=lambda message: self._emit_lines(self.renderer.error(message)),
                stop=self._stop.is_set,
            ):
                line_number = stored.line_number
                self.render_stored(stored)
        except KeyboardInterrupt:  # pragma: no cover - interactive
            self._emit_lines(self.renderer.notice("interrupted; stopping"))
        finally:
            self.flush()
            if self.summary_mode:
                self.render_summary()
        return self.stats.displayed

    def stop(self) -> None:
        self._stop.set()

    def __enter__(self) -> "TerminalObserver":
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()
        self.flush()

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        mode = "follow" if self.follow else "history"
        return f"TerminalObserver({self.store.path}, {mode})"
