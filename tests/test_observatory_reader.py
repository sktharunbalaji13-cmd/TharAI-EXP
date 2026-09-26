"""Incremental consumption: correctness under growth, damage, and repetition.

A research log is append-only in principle and unreliable in practice. These
tests cover the ways it actually misbehaves: torn lines, corruption, rotation,
duplicated records, and a process that restarts. Each one is a way a naive
observer would silently display a wrong picture.
"""

from __future__ import annotations

import unittest

from observatory.reader import ObservatoryReader
from tests.support import LabTestCase


class ReaderTests(LabTestCase):
    def reader(self) -> ObservatoryReader:
        return ObservatoryReader(store=self.store, clock=self.clock)

    # -- basics -----------------------------------------------------------
    def test_empty_log_ingests_nothing(self) -> None:
        report = self.reader().replay()
        self.assertEqual(report.accepted, 0)
        self.assertEqual(self.reader().ingested_count(), 0)

    def test_first_poll_replays_from_the_beginning(self) -> None:
        for index in range(3):
            self.store.append("system.test", "test", {"n": index})
        reader = self.reader()
        self.assertEqual(reader.poll().accepted, 3)

    def test_poll_only_returns_new_events(self) -> None:
        self.store.append("system.test", "test", {"n": 1})
        reader = self.reader()
        self.assertEqual(reader.replay().accepted, 1)

        self.store.append("system.test", "test", {"n": 2})
        self.assertEqual(reader.poll().accepted, 1)
        self.assertEqual(reader.ingested_count(), 2)

    def test_poll_on_unchanged_log_accepts_nothing(self) -> None:
        self.store.append("system.test", "test", {"n": 1})
        reader = self.reader()
        reader.replay()
        self.assertEqual(reader.poll().accepted, 0)
        self.assertEqual(reader.poll().accepted, 0)

    def test_offset_advances_only_over_whole_lines(self) -> None:
        for index in range(3):
            self.store.append("system.test", "test", {"n": index})
        reader = self.reader()
        reader.replay()
        self.assertEqual(reader.offset, self.store.current_offset())

    # -- duplicates -------------------------------------------------------
    def test_replaying_twice_accepts_nothing_new(self) -> None:
        for index in range(4):
            self.store.append("system.test", "test", {"n": index})
        reader = self.reader()
        self.assertEqual(reader.replay().accepted, 4)
        self.assertEqual(reader.replay().accepted, 0)
        self.assertEqual(reader.replay().duplicates, 4)
        self.assertEqual(reader.ingested_count(), 4)

    def test_duplicate_records_in_the_log_are_counted_not_applied(self) -> None:
        for index in range(2):
            self.store.append("system.test", "test", {"n": index})
        first = self.read_event_lines()[0]
        # A party with write access duplicating a line is a corruption we must
        # notice, not a second observation of the same thing.
        self.store.path.write_text(first + "\n" + "\n".join(self.read_event_lines()) + "\n", encoding="utf-8")
        report = self.reader().replay()
        self.assertEqual(report.accepted, 2)
        self.assertEqual(report.duplicates, 1)

    def test_ingest_event_is_idempotent(self) -> None:
        self.store.append("system.test", "test", {"n": 1})
        event = next(self.store.iter_events())
        reader = self.reader()
        self.assertTrue(reader.ingest_event(event))
        self.assertFalse(reader.ingest_event(event))

    # -- malformed and torn lines ----------------------------------------
    def test_malformed_line_is_counted_and_survives_good_events(self) -> None:
        self.store.append("system.test", "test", {"n": 1})
        self.rewrite_events(lambda text: text + "{not json at all}\n")
        self.store.append("system.test", "test", {"n": 2})

        reader = self.reader()
        report = reader.replay()
        self.assertEqual(report.accepted, 2)
        self.assertEqual(report.malformed, 1)
        self.assertEqual(len(reader.malformed_lines), 1)

    def test_a_gap_does_not_stop_later_events_being_seen(self) -> None:
        self.store.append("system.test", "test", {"n": 1})
        self.rewrite_events(lambda text: text + "garbage\n")
        self.store.append("system.test", "test", {"n": 3})
        reader = self.reader()
        reader.replay()
        self.assertEqual(reader.ingested_count(), 2)

    def test_truncated_log_yields_what_is_intact(self) -> None:
        for index in range(5):
            self.store.append("system.test", "test", {"n": index})
        # Chop the final line in half, as a crash mid-write would.
        lines = self.read_event_lines()
        self.store.path.write_text("\n".join(lines[:-1]) + "\n" + lines[-1][:20], encoding="utf-8")
        report = self.reader().replay()
        self.assertEqual(report.accepted, 4)
        self.assertEqual(report.malformed, 1)

    def test_partial_trailing_line_is_not_parsed_until_complete(self) -> None:
        self.store.append("system.test", "test", {"n": 1})
        self.store.append("system.test", "test", {"n": 2})
        lines = self.read_event_lines()
        # Start again from only the first event, so event 2 can arrive in pieces.
        self.store.path.write_text(lines[0] + "\n", encoding="utf-8")

        reader = self.reader()
        reader.replay()
        self.assertEqual(reader.ingested_count(), 1)

        # Simulate a write caught in the middle: append without a newline.
        with open(self.store.path, "a", encoding="utf-8") as handle:
            handle.write(lines[1][:30])
        # A torn line is not a fault: the record is merely still in flight.
        self.assertEqual(reader.poll().malformed, 0)
        self.assertEqual(reader.poll().accepted, 0)

        with open(self.store.path, "a", encoding="utf-8") as handle:
            handle.write(lines[1][30:] + "\n")
        self.assertEqual(reader.poll().accepted, 1)
        self.assertEqual(reader.poll().malformed, 0)

    def test_blank_line_is_a_fault(self) -> None:
        self.store.append("system.test", "test", {"n": 1})
        self.rewrite_events(lambda text: text + "\n\n")
        self.assertEqual(self.reader().replay().malformed, 2)

    # -- ordering ---------------------------------------------------------
    def test_out_of_order_event_is_accepted_and_flagged(self) -> None:
        for index in range(3):
            self.store.append("system.test", "test", {"n": index})
        reader = self.reader()
        for event in sorted(self.store.iter_events(), key=lambda e: e.seq, reverse=True):
            reader.ingest_event(event)
        # Recorded, not dropped: a laboratory should remember what it saw even
        # when the ordering is wrong.
        self.assertEqual(reader.ingested_count(), 3)
        self.assertEqual(len(reader.out_of_order_ids), 2)

    def test_highest_seq_tracks_the_maximum(self) -> None:
        for index in range(3):
            self.store.append("system.test", "test", {"n": index})
        reader = self.reader()
        reader.replay()
        self.assertEqual(reader.last_seq(), 3)

    # -- rotation and replacement ----------------------------------------
    def test_truncated_file_reports_a_reset(self) -> None:
        for index in range(3):
            self.store.append("system.test", "test", {"n": index})
        reader = self.reader()
        reader.replay()
        self.assertEqual(reader.poll().resets, 0)

        # Rotated out from under us.
        self.store.path.write_text("", encoding="utf-8")
        report = reader.poll()
        self.assertEqual(report.resets, 1)
        self.assertEqual(reader.generation, 1)

    def test_replaced_file_is_detected_even_when_longer(self) -> None:
        for index in range(2):
            self.store.append("system.test", "test", {"n": index})
        reader = self.reader()
        reader.replay()
        original = self.store.path.read_text(encoding="utf-8")

        # A rotation tool that swaps in a *longer* file. Size alone cannot see
        # this; only the file identity can.
        self.store.path.unlink()
        self.store.path.write_text(original + original, encoding="utf-8")
        report = reader.poll()
        self.assertEqual(report.resets, 1)
        # The new file holds four lines: the two known events and two copies.
        # Every one is a duplicate, so nothing is double-applied.
        self.assertEqual(report.duplicates, 4)
        self.assertEqual(report.accepted, 0)
        self.assertEqual(reader.ingested_count(), 2)

    def test_appended_duplicate_tail_is_not_treated_as_a_reset(self) -> None:
        for index in range(2):
            self.store.append("system.test", "test", {"n": index})
        reader = self.reader()
        reader.replay()
        original = self.store.path.read_text(encoding="utf-8")
        # Appending a copy of the log is an append, not a replacement.
        with open(self.store.path, "a", encoding="utf-8") as handle:
            handle.write(original)
        report = reader.poll()
        self.assertEqual(report.resets, 0)
        self.assertEqual(report.duplicates, 2)

    # -- restart ----------------------------------------------------------
    def test_fresh_reader_over_the_same_log_agrees(self) -> None:
        for index in range(5):
            self.store.append("system.test", "test", {"n": index})
        first = self.reader()
        first.replay()
        # A restart is just a new reader over the same canonical log.
        second = self.reader()
        second.replay()
        self.assertEqual(first.ingested_count(), second.ingested_count())
        self.assertEqual(first.last_seq(), second.last_seq())

    def test_drain_accepted_returns_new_events_once(self) -> None:
        for index in range(3):
            self.store.append("system.test", "test", {"n": index})
        reader = self.reader()
        reader.replay()
        drained = reader.drain_accepted()
        self.assertEqual(len(drained), 3)
        self.assertEqual(reader.drain_accepted(), [])

    def test_state_is_serialisable(self) -> None:
        for index in range(2):
            self.store.append("system.test", "test", {"n": index})
        reader = self.reader()
        reader.replay()
        state = reader.state()
        for key in ("offset", "generation", "ingested", "highest_seq"):
            self.assertIn(key, state)

    def test_from_paths_builds_a_working_reader(self) -> None:
        self.store.append("system.test", "test", {"n": 1})
        reader = ObservatoryReader.for_paths(self.paths, self.clock)
        self.assertEqual(reader.replay().accepted, 1)


if __name__ == "__main__":
    unittest.main()
