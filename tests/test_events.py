"""Event system tests.

Covers the five areas the specification requires: creation, event IDs,
timestamps, persistence, and malformed events. Plus the hash chain, because a
tamper-evident log that does not actually detect tampering is worse than no
integrity claim at all.

All tests are APPLICATION-LEVEL tests. None of them proves anything about
operating-system enforcement; see tests/test_trust_boundaries.py for the
distinction, which is stated explicitly there.
"""

from __future__ import annotations

import json
import threading
import unittest

from tests import support  # noqa: F401  (puts the project root on sys.path)
from tests.support import LabTestCase

from babylab.clock import FixedClock, format_timestamp, parse_timestamp
from babylab.errors import ValidationError
from events.model import Event, format_event_id, parse_event_id
from events.store import GENESIS_HASH, EventStore


class EventCreationTests(LabTestCase):
    def test_create_produces_a_complete_sealed_event(self):
        event = Event.create(
            seq=1, event_type="system.started", source="test", payload={"headline": "Up"}
        )
        self.assertEqual(event.event_id, "EVENT-000001")
        self.assertEqual(event.seq, 1)
        self.assertEqual(event.event_type, "system.started")
        self.assertEqual(event.source, "test")
        self.assertEqual(event.payload, {"headline": "Up"})
        self.assertEqual(event.prev_hash, GENESIS_HASH)
        self.assertEqual(len(event.hash), 64)
        event.validate_sealed()

    def test_payload_defaults_to_empty_object_not_none(self):
        event = Event.create(seq=1, event_type="system.tick", source="test")
        self.assertEqual(event.payload, {})

    def test_hash_is_deterministic_for_identical_fields(self):
        """Same fields in, same digest out - including the timestamp.

        The timestamp is part of the hashed body, so determinism means "given
        the same instant", not "given the same call".
        """
        from datetime import datetime, timezone

        moment = datetime(2026, 9, 26, 19, 0, 0, tzinfo=timezone.utc)
        first = Event.create(seq=1, event_type="system.tick", source="test", moment=moment)
        second = Event.create(seq=1, event_type="system.tick", source="test", moment=moment)
        self.assertEqual(first.hash, second.hash)
        self.assertEqual(first.timestamp, "2026-09-26T19:00:00.000Z")

    def test_hash_changes_when_any_field_changes(self):
        from datetime import datetime, timezone

        moment = datetime(2026, 9, 26, 19, 0, 0, tzinfo=timezone.utc)
        base = Event.create(
            seq=1, event_type="system.tick", source="test", payload={"a": 1}, moment=moment
        )
        later = datetime(2026, 9, 26, 19, 0, 1, tzinfo=timezone.utc)
        variants = [
            Event.create(seq=1, event_type="system.tock", source="test", payload={"a": 1}, moment=moment),
            Event.create(seq=1, event_type="system.tick", source="other", payload={"a": 1}, moment=moment),
            Event.create(seq=1, event_type="system.tick", source="test", payload={"a": 2}, moment=moment),
            Event.create(seq=1, event_type="system.tick", source="test", payload={"a": 1}, moment=later),
            Event.create(seq=2, event_type="system.tick", source="test", payload={"a": 1}, moment=moment),
        ]
        for variant in variants:
            with self.subTest(variant=variant.event_type):
                self.assertNotEqual(base.hash, variant.hash)

    def test_sealing_is_idempotent(self):
        event = Event.create(seq=1, event_type="system.tick", source="test")
        self.assertEqual(event.seal().hash, event.hash)

    def test_seq_must_be_positive(self):
        with self.assertRaises(ValidationError):
            Event.create(seq=0, event_type="system.tick", source="test")

    def test_event_type_must_be_dotted_lowercase(self):
        for bad in ("system", "System.Started", "system started", "system..started", ""):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                Event.create(seq=1, event_type=bad, source="test")

    def test_source_must_not_be_empty(self):
        with self.assertRaises(ValidationError):
            Event.create(seq=1, event_type="system.tick", source="   ")

    def test_arbitrary_namespaces_are_accepted(self):
        """The laboratory must not pre-register what the subject may do.

        A whitelist of event types would be a curriculum in disguise. Any
        syntactically valid type is accepted.
        """
        for event_type in (
            "system.started",
            "security.thing.happened",
            "totally.unexpected.namespace",
        ):
            with self.subTest(event_type=event_type):
                event = Event.create(seq=1, event_type=event_type, source="test")
                event.validate_sealed()


class EventIdTests(LabTestCase):
    def test_ids_are_zero_padded_and_sequential(self):
        ids = [self.store.append("system.tick", "test").event_id for _ in range(3)]
        self.assertEqual(ids, ["EVENT-000001", "EVENT-000002", "EVENT-000003"])

    def test_ids_keep_growing_past_six_digits(self):
        self.assertEqual(format_event_id(999999), "EVENT-999999")
        self.assertEqual(format_event_id(1000000), "EVENT-1000000")

    def test_ids_round_trip(self):
        for seq in (1, 42, 999999, 1234567):
            self.assertEqual(parse_event_id(format_event_id(seq)), seq)

    def test_malformed_ids_are_rejected(self):
        for bad in ("EVENT-abc", "event-000001", "EVENT-", "1", "EVENT-000001x"):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                parse_event_id(bad)

    def test_id_must_agree_with_seq(self):
        data = Event.create(seq=1, event_type="system.tick", source="test").to_dict()
        data["seq"] = 7
        with self.assertRaises(ValidationError) as caught:
            Event.from_dict(data)
        self.assertIn("disagrees with seq", str(caught.exception))


class TimestampTests(LabTestCase):
    def test_timestamps_are_utc_with_millisecond_precision(self):
        event = self.store.append("system.tick", "test")
        self.assertRegex(event.timestamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

    def test_timestamps_parse_back_to_the_same_instant(self):
        event = self.store.append("system.tick", "test")
        parsed = parse_timestamp(event.timestamp)
        self.assertEqual(format_timestamp(parsed), event.timestamp)

    def test_second_precision_input_is_accepted(self):
        """The specification's example uses second precision; accept it."""
        event = Event.create(seq=1, event_type="system.tick", source="test")
        data = event.to_dict()
        data["timestamp"] = "2026-09-26T19:00:00Z"
        parsed = Event.from_dict(data)
        self.assertEqual(parsed.timestamp, "2026-09-26T19:00:00Z")

    def test_offset_timestamps_are_normalised_to_utc(self):
        parsed = parse_timestamp("2026-09-26T21:00:00+02:00")
        self.assertEqual(format_timestamp(parsed), "2026-09-26T19:00:00.000Z")

    def test_malformed_timestamps_are_rejected(self):
        for bad in ("2026-09-26", "not a date", "2026-09-26T19:00:00", "", "20260926T190000Z"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    Event.from_dict(
                        {
                            **Event.create(seq=1, event_type="a.b", source="s").to_dict(),
                            "timestamp": bad,
                        }
                    )

    def test_naive_datetimes_are_refused(self):
        from datetime import datetime

        with self.assertRaises(ValueError):
            format_timestamp(datetime(2026, 9, 26, 19, 0, 0))

    def test_events_are_strictly_ordered_in_time(self):
        events = [self.store.append("system.tick", "test") for _ in range(5)]
        stamps = [event.timestamp for event in events]
        self.assertEqual(stamps, sorted(stamps))
        self.assertEqual(len(set(stamps)), 5, "FixedClock must yield distinct timestamps")


class PersistenceTests(LabTestCase):
    def test_events_survive_a_reopen(self):
        self.store.append("system.first", "test", {"headline": "First"})
        self.store.append("system.second", "test", {"headline": "Second"})

        reopened = EventStore(self.paths.event_store)
        events = list(reopened.iter_events())
        self.assertEqual([event.event_type for event in events], ["system.first", "system.second"])
        self.assertEqual(events[0].payload["headline"], "First")

    def test_file_is_json_lines_one_object_per_line(self):
        self.store.append("system.one", "test")
        self.store.append("system.two", "test")
        lines = self.read_event_lines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertNotIn("\n", line)
            self.assertIsInstance(json.loads(line), dict)

    def test_empty_store_reads_as_empty(self):
        self.assertIsNone(self.store.head())
        self.assertEqual(self.store.read_all(), [])
        self.assertEqual(self.store.count(), 0)

    def test_head_is_the_last_event(self):
        self.store.append("system.one", "test")
        last = self.store.append("system.two", "test")
        self.assertEqual(self.store.head().event_id, last.event_id)

    def test_concurrent_appends_produce_an_intact_chain(self):
        errors: list[BaseException] = []

        def writer(worker: int) -> None:
            try:
                for index in range(10):
                    self.store.append(
                        "system.worker_tick", f"worker-{worker}", {"worker": worker, "i": index}
                    )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(self.store.count(), 40)
        report = self.store.verify_chain()
        self.assertTrue(report.intact, msg=f"chain broken: {report.problems}")

    def test_chain_links_events_in_order(self):
        events = [self.store.append("system.tick", "test") for _ in range(4)]
        self.assertEqual(events[0].prev_hash, GENESIS_HASH)
        for previous, current in zip(events, events[1:]):
            self.assertEqual(current.prev_hash, previous.hash)


class MalformedEventTests(LabTestCase):
    def test_non_json_line_is_reported_not_raised(self):
        self.store.append("system.good", "test")
        with open(self.paths.event_store, "a", encoding="utf-8") as handle:
            handle.write("this is not json\n")
        stored = self.store.read_all()
        self.assertEqual(len(stored), 2)
        self.assertTrue(stored[0].ok)
        self.assertFalse(stored[1].ok)
        self.assertIn("not valid JSON", stored[1].error)

    def test_missing_required_field_is_reported(self):
        self.store.append("system.good", "test")
        partial = {"event_id": "EVENT-000002", "seq": 2}
        with open(self.paths.event_store, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(partial) + "\n")
        stored = self.store.read_all()
        self.assertFalse(stored[1].ok)
        self.assertIn("must be a string", stored[1].error)

    def test_blank_lines_are_reported(self):
        self.store.append("system.good", "test")
        with open(self.paths.event_store, "a", encoding="utf-8") as handle:
            handle.write("\n   \n")
        stored = self.store.read_all()
        self.assertEqual(len(stored), 3)
        self.assertEqual(stored[1].error, "blank line")

    def test_wrong_payload_type_is_reported(self):
        self.store.append("system.good", "test")
        bad = Event.create(seq=2, event_type="system.bad", source="test").to_dict()
        bad["payload"] = ["not", "an", "object"]
        with open(self.paths.event_store, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(bad) + "\n")
        stored = self.store.read_all()
        self.assertFalse(stored[1].ok)
        self.assertIn("'payload' must be an object", stored[1].error)

    def test_unsealed_event_is_rejected(self):
        event = Event.create(seq=1, event_type="system.tick", source="test")
        data = event.to_dict()
        data["hash"] = ""
        with self.assertRaises(ValidationError) as caught:
            Event.from_dict(data)
        self.assertIn("never sealed", str(caught.exception))

    def test_one_bad_line_does_not_hide_the_others(self):
        self.store.append("system.one", "test")
        with open(self.paths.event_store, "a", encoding="utf-8") as handle:
            handle.write("garbage\n")
        self.store.append("system.two", "test")
        events = list(self.store.iter_events())
        self.assertEqual([event.event_type for event in events], ["system.one", "system.two"])

    def test_raw_text_is_preserved_for_diagnosis(self):
        with open(self.paths.event_store, "w", encoding="utf-8") as handle:
            handle.write("{oops\n")
        stored = self.store.read_all()
        self.assertEqual(stored[0].raw, "{oops")


class ChainVerificationTests(LabTestCase):
    def setUp(self):
        super().setUp()
        for index in range(5):
            self.store.append("system.tick", "test", {"index": index})

    def test_intact_chain_verifies(self):
        report = self.store.verify_chain()
        self.assertTrue(report.intact, msg=report.problems)
        self.assertEqual(report.valid_events, 5)
        self.assertEqual(report.malformed_lines, 0)

    def test_payload_tampering_is_detected(self):
        def tamper(text: str) -> str:
            return text.replace('"index":2', '"index":99')

        self.rewrite_events(tamper)
        report = self.store.verify_chain()
        self.assertFalse(report.intact)
        self.assertTrue(any("hash mismatch" in problem for problem in report.problems))

    def test_deleting_a_middle_event_is_detected(self):
        def delete_middle(text: str) -> str:
            lines = text.splitlines(keepends=True)
            return "".join(lines[:2] + lines[3:])

        self.rewrite_events(delete_middle)
        report = self.store.verify_chain()
        self.assertFalse(report.intact)
        self.assertTrue(any("prev_hash" in problem for problem in report.problems))

    def test_reordering_events_is_detected(self):
        def swap(text: str) -> str:
            lines = text.splitlines(keepends=True)
            lines[1], lines[2] = lines[2], lines[1]
            return "".join(lines)

        self.rewrite_events(swap)
        report = self.store.verify_chain()
        self.assertFalse(report.intact)

    def test_truncating_the_tail_is_reported_as_intact_by_the_chain_alone(self):
        """Documents a real limitation rather than hiding it.

        The chain alone cannot detect tail truncation, because the last
        remaining entry is a perfectly valid head. External anchoring is the
        job of the provenance seal. Asserting the limitation here means a
        future change cannot quietly make the docs wrong.
        """
        def truncate(text: str) -> str:
            lines = text.splitlines(keepends=True)
            return "".join(lines[:3])

        self.rewrite_events(truncate)
        report = self.store.verify_chain()
        self.assertTrue(report.intact, "chain alone cannot see tail truncation")
        self.assertEqual(report.valid_events, 3)


class TailingTests(LabTestCase):
    def test_follow_yields_appended_events(self):
        self.store.append("system.one", "test")
        seen: list[Event] = []
        stop = threading.Event()

        def consume() -> None:
            for stored in self.store.follow(from_offset=0, poll_interval=0.01, stop=stop.is_set):
                if stored.event:
                    seen.append(stored.event)
                if len(seen) >= 2:
                    stop.set()

        worker = threading.Thread(target=consume, daemon=True)
        worker.start()
        self.store.append("system.two", "test")
        worker.join(timeout=5.0)
        self.assertEqual([event.event_type for event in seen], ["system.one", "system.two"])

    def test_follow_reports_a_shrinking_log_instead_of_guessing(self):
        self.store.append("system.one", "test")
        offset = self.store.current_offset()
        messages: list[str] = []
        stop = threading.Event()

        def consume() -> None:
            generator = self.store.follow(
                from_offset=offset,
                poll_interval=0.01,
                on_reset=messages.append,
                stop=stop.is_set,
            )
            try:
                next(generator)
            except StopIteration:
                pass
            stop.set()

        worker = threading.Thread(target=consume, daemon=True)
        worker.start()
        self.paths.event_store.write_text("", encoding="utf-8")
        worker.join(timeout=5.0)
        self.assertTrue(any("shrank" in message for message in messages))

    def test_summary_counts_by_namespace(self):
        self.store.append("system.one", "test")
        self.store.append("security.two", "test")
        self.store.append("security.three", "test")
        summary = self.store.summary()
        self.assertEqual(summary["total_events"], 3)
        self.assertEqual(summary["by_namespace"], {"security": 2, "system": 1})


if __name__ == "__main__":
    unittest.main()
