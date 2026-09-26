"""Performance: 100,000 events, and no accidental quadratic behaviour.

The specification asks for at least 100,000 events. More importantly it asks
that consumption be linear, because a live view that re-reads the log on every
refresh is fine in a demo and unusable in a session.

Two measurement notes, both learned the hard way:

*Appending is not reading.* The event store fsyncs every line, which costs
milliseconds. If a test times "append a batch, then poll" it will conclude the
reader is quadratic when it is really measuring the disk. Every test here times
the polls and the replay separately from the writes.

*The fixture is seeded in one write.* Building 100,000 chained events in memory
and writing them once produces a log identical in structure to one the real
writer would have produced, without spending several minutes on fsync.
"""

from __future__ import annotations

import time
import unittest

from events.model import Event
from events.store import GENESIS_HASH
from observatory.attribution import Attributor
from observatory.derive import StateDeriver
from observatory.reader import ObservatoryReader
from tests.support import LabTestCase

TARGET_EVENTS = 100_000

#: Generous. The point is to catch a change in complexity class, not to measure
#: the machine. A loaded CI box must not turn this suite red.
INGEST_BUDGET_SECONDS = 120.0


def seed_fast(
    store,
    count: int,
    event_type: str = "system.perf.seed",
    payload_for=None,
) -> int:
    """Append ``count`` valid chained events with a single bulk write.

    Uses the same :class:`~events.model.Event` construction the real store uses,
    so the resulting log verifies, but skips the per-line fsync that would make
    seeding 100,000 events take minutes.

    ``payload_for(index)`` builds each event's payload, so a caller can seed
    genuine state reports rather than bare events.

    The store's head cache is deliberately left alone: it is not needed by the
    reader, and pretending otherwise would be tidier than it is honest. These
    tests never append through the store after seeding.
    """
    lines = _build_chain(store, count, event_type, payload_for)
    with open(store.path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write("".join(lines))
    return count


def _build_chain(store, count: int, event_type: str, payload_for=None) -> list[str]:
    """Build ``count`` chained event lines continuing from the log's head."""
    head_seq, prev_hash = 0, GENESIS_HASH
    for last in store.iter_events():
        head_seq, prev_hash = last.seq, last.hash

    moment = store.clock.now()
    lines: list[str] = []
    for index in range(count):
        event = Event.create(
            seq=head_seq + index + 1,
            event_type=event_type,
            source="perf.harness",
            payload=payload_for(index) if payload_for else {"n": index},
            moment=moment,
            prev_hash=prev_hash,
        )
        prev_hash = event.hash
        lines.append(event.to_json() + "\n")
    return lines


def _build_batches(store, batch_count: int, per_batch: int, event_type: str) -> list[str]:
    """Build all append batches in one pass.

    Chaining the whole run in a single pass matters: re-reading the log head per
    batch would be quadratic in the *test*, which is precisely the mistake this
    module exists to detect in the reader.
    """
    head_seq, prev_hash = 0, GENESIS_HASH
    for last in store.iter_events():
        head_seq, prev_hash = last.seq, last.hash

    moment = store.clock.now()
    batches: list[str] = []
    chunk: list[str] = []
    for index in range(batch_count * per_batch):
        event = Event.create(
            seq=head_seq + index + 1,
            event_type=event_type,
            source="perf.harness",
            payload={"n": index},
            moment=moment,
            prev_hash=prev_hash,
        )
        prev_hash = event.hash
        chunk.append(event.to_json() + "\n")
        if len(chunk) == per_batch:
            batches.append("".join(chunk))
            chunk = []
    if chunk:
        batches.append("".join(chunk))
    return batches


class PerformanceTests(LabTestCase):
    def test_ingests_one_hundred_thousand_events(self) -> None:
        seed_fast(self.store, TARGET_EVENTS)
        self.assertGreaterEqual(self.store.count(), TARGET_EVENTS)
        # The seeded log is a genuine chain, not just well-formed lines.
        self.assertEqual(self.store.verify_chain().problems, [])

        reader = ObservatoryReader(store=self.store, clock=self.clock)
        started = time.perf_counter()
        report = reader.replay()
        elapsed = time.perf_counter() - started

        self.assertEqual(report.accepted, TARGET_EVENTS)
        self.assertEqual(reader.ingested_count(), TARGET_EVENTS)
        self.assertLess(
            elapsed,
            INGEST_BUDGET_SECONDS,
            f"full ingest of {TARGET_EVENTS} events took {elapsed:.1f}s",
        )

    def test_incremental_poll_is_not_quadratic(self) -> None:
        """Polling in many small batches must cost far less than repeated replay.

        If each poll re-read the log, N polls over the same log would do N times
        the work of one replay. Timing only the polls is what makes the ratio
        meaningful.
        """
        seed_count = 20_000
        seed_fast(self.store, seed_count)

        reader = ObservatoryReader(store=self.store, clock=self.clock)
        replay_started = time.perf_counter()
        reader.replay()
        replay_elapsed = time.perf_counter() - replay_started

        # Pre-build every batch so no write time lands inside the measured span.
        batches = _build_batches(self.store, batch_count=200, per_batch=100, event_type="system.perf.tick")

        poll_seconds = 0.0
        accepted = 0
        with open(self.store.path, "a", encoding="utf-8", newline="\n") as handle:
            for batch in batches:
                handle.write(batch)
                # The reader opens its own handle, so unflushed Python buffers
                # would be invisible to it. A real producer fsyncs per append;
                # flushing is the honest equivalent here.
                handle.flush()
                started = time.perf_counter()
                report = reader.poll()
                poll_seconds += time.perf_counter() - started
                accepted += report.accepted

        self.assertEqual(accepted, 200 * 100)
        # 200 polls would each cost a full replay if the reader were quadratic.
        self.assertLess(
            poll_seconds,
            replay_elapsed * 10,
            f"200 incremental polls took {poll_seconds:.2f}s vs one "
            f"{replay_elapsed:.2f}s replay, which suggests a full re-read each time",
        )

    def test_derivation_scales_with_events(self) -> None:
        count = 20_000
        # Each event is a genuine state report, so every one is a real
        # transition rather than a bare event that changes nothing.
        seed_fast(
            self.store,
            count,
            event_type="baby.report",
            payload_for=lambda index: {"state": {"memory": {"n": index}}},
        )

        deriver = StateDeriver(
            attributor=Attributor(
                subject_namespace=frozenset({"baby"}), subject_label="SUBJECT"
            ),
            subject_id="baby-ai:subject",
            clock=self.clock,
        )
        started = time.perf_counter()
        deriver.apply_all(self.store.iter_events())
        elapsed = time.perf_counter() - started

        self.assertEqual(deriver.version(), count)
        self.assertLess(elapsed, INGEST_BUDGET_SECONDS)

    def test_snapshot_construction_is_cheap(self) -> None:
        """A snapshot is built on every refresh, so it must not scan the log."""
        seed_fast(self.store, 20_000)
        deriver = StateDeriver(
            attributor=Attributor(
                subject_namespace=frozenset({"baby"}), subject_label="SUBJECT"
            ),
            subject_id="baby-ai:subject",
            clock=self.clock,
        )
        deriver.apply_all(self.store.iter_events())

        started = time.perf_counter()
        for _ in range(100):
            deriver.snapshot(self.clock.now())
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 5.0)


if __name__ == "__main__":
    unittest.main()
