"""Terminal observer tests.

Covers what the specification requires: the observer receives events, displays
them, handles malformed events, and stays useful at high event volume.

The high-volume tests assert behaviour that matters to a human reader - the
right number of lines, no lost events, bounded memory - rather than a
wall-clock performance figure, which would be a flaky assertion on shared
hardware.
"""

from __future__ import annotations

import io
import threading
import time
import unittest

from tests import support  # noqa: F401
from tests.support import LabTestCase

from observer.format import RenderOptions, Renderer, category_of, short_time, strip_ansi
from observer.terminal import RING_SIZE, TerminalObserver


def make_observer(case: LabTestCase, **kwargs) -> tuple[TerminalObserver, io.StringIO]:
    stream = io.StringIO()
    kwargs.setdefault("follow", False)
    observer = TerminalObserver(
        paths=case.paths,
        store=case.store,
        stream=stream,
        options=RenderOptions(colour=False),
        **kwargs,
    )
    return observer, stream


class RenderingTests(LabTestCase):
    def setUp(self):
        super().setUp()
        self.stream = io.StringIO()
        self.renderer = Renderer(RenderOptions(colour=False), self.stream)

    def test_output_matches_the_specified_shape(self):
        event = self.store.append(
            "system.observer.started", "test", {"headline": "Observer started"}
        )
        lines = strip_ansi("\n".join(self.renderer.event_lines(event)))
        self.assertRegex(lines, r"^\[\d{2}:\d{2}:\d{2}\] SYSTEM\s+Observer started$")

    def test_category_comes_from_the_event_namespace(self):
        self.assertEqual(category_of("system.observer.started"), "SYSTEM")
        self.assertEqual(category_of("security.human_control.verified"), "SECURITY")
        self.assertEqual(category_of("provenance.baseline.recorded"), "PROVENANCE")
        self.assertEqual(category_of("control.snapshot.taken"), "CONTROL")

    def test_every_category_puts_the_headline_in_the_same_column(self):
        """Column alignment is what makes a long session scannable."""
        columns = []
        for event_type in (
            "system.a",
            "security.b",
            "provenance.c",
            "control.d",
            "observer.e",
            "baby_ai_something_long.f",
        ):
            event = self.store.append(event_type, "test", {"headline": "HEADLINE"})
            line = strip_ansi(self.renderer.event_lines(event)[0])
            columns.append(line.index("HEADLINE"))
        self.assertEqual(len(set(columns)), 1, f"ragged columns: {columns}")

    def test_short_time_drops_the_date_but_keeps_the_clock(self):
        self.assertEqual(short_time("2026-09-26T19:00:01.123Z"), "19:00:01")
        self.assertEqual(short_time("2026-09-26T19:00:01Z"), "19:00:01")

    def test_an_event_without_a_headline_falls_back_to_its_type(self):
        event = self.store.append("system.no.headline", "test")
        line = strip_ansi(self.renderer.event_lines(event)[0])
        self.assertIn("system.no.headline", line)

    def test_a_very_long_headline_is_truncated(self):
        event = self.store.append("system.long", "test", {"headline": "x" * 500})
        line = strip_ansi(self.renderer.event_lines(event)[0])
        self.assertLess(len(line), 260)
        self.assertTrue(line.endswith("…"))

    def test_detail_mode_prints_the_payload(self):
        event = self.store.append("system.d", "test", {"headline": "h", "count": 7})
        self.renderer.options.detail = True
        text = strip_ansi("\n".join(self.renderer.event_lines(event)))
        self.assertIn('"count": 7', text)

    def test_colour_is_never_the_only_carrier_of_meaning(self):
        coloured = Renderer(RenderOptions(colour=True), io.StringIO())
        event = self.store.append("security.alert", "test", {"headline": "Something"})
        self.assertIn("Something", strip_ansi("\n".join(coloured.event_lines(event))))


class ReceivingTests(LabTestCase):
    def test_observer_displays_existing_events(self):
        self.store.append("system.one", "test", {"headline": "First"})
        self.store.append("system.two", "test", {"headline": "Second"})
        observer, stream = make_observer(self)
        shown = observer.show_history()
        self.assertEqual(shown, 2)
        output = stream.getvalue()
        self.assertIn("First", output)
        self.assertIn("Second", output)
        self.assertEqual(output.count("\n"), 2)

    def test_observer_displays_nothing_for_an_empty_log(self):
        observer, stream = make_observer(self)
        self.assertEqual(observer.show_history(), 0)
        self.assertEqual(stream.getvalue(), "")

    def test_observer_writes_nothing_back_to_the_event_log(self):
        """A read-only observer. Asserted, not assumed."""
        self.store.append("system.one", "test", {"headline": "First"})
        before = self.read_event_lines()
        observer, _ = make_observer(self)
        observer.show_history()
        self.assertEqual(self.read_event_lines(), before)

    def test_max_history_limits_the_replay(self):
        for index in range(20):
            self.store.append("system.tick", "test", {"headline": f"E{index}", "i": index})
        observer, stream = make_observer(self, max_history=5)
        shown = observer.show_history()
        self.assertEqual(shown, 5)
        output = stream.getvalue()
        self.assertIn("15 earlier events omitted", output)
        self.assertIn("E19", output)
        self.assertNotIn("E0\n", output)


class FilteringTests(LabTestCase):
    def setUp(self):
        super().setUp()
        self.store.append("system.one", "test", {"headline": "SysOne"})
        self.store.append("security.two", "test", {"headline": "SecTwo"})
        self.store.append("system.three", "test", {"headline": "SysThree"})

    def test_namespace_filter(self):
        observer, stream = make_observer(self, namespaces=["security"])
        self.assertEqual(observer.show_history(), 1)
        output = stream.getvalue()
        self.assertIn("SecTwo", output)
        self.assertNotIn("SysOne", output)
        self.assertEqual(observer.stats.filtered_out, 2)

    def test_type_filter(self):
        observer, stream = make_observer(
            self, types=["system.one", "system.three"]
        )
        self.assertEqual(observer.show_history(), 2)
        self.assertNotIn("SecTwo", stream.getvalue())

    def test_filters_combine(self):
        observer, _ = make_observer(self, namespaces=["system"], types=["system.one"])
        self.assertEqual(observer.show_history(), 1)

    def test_an_unmatched_filter_shows_nothing_rather_than_everything(self):
        observer, stream = make_observer(self, namespaces=["does-not-exist"])
        self.assertEqual(observer.show_history(), 0)
        self.assertEqual(stream.getvalue(), "")


class MalformedHandlingTests(LabTestCase):
    def test_a_corrupt_line_is_shown_not_swallowed(self):
        self.store.append("system.good", "test", {"headline": "Good"})
        with open(self.paths.event_store, "a", encoding="utf-8") as handle:
            handle.write("}}} not json {{{\n")
        observer, stream = make_observer(self)
        observer.show_history()
        output = stream.getvalue()
        self.assertIn("MALFORMED", output)
        self.assertIn("Good", output)
        self.assertEqual(observer.stats.malformed, 1)
        self.assertEqual(observer.stats.displayed, 1)

    def test_the_reason_for_a_malformed_line_is_shown(self):
        with open(self.paths.event_store, "w", encoding="utf-8") as handle:
            handle.write("garbage\n")
        observer, stream = make_observer(self)
        observer.show_history()
        self.assertIn("reason:", stream.getvalue())

    def test_one_corrupt_line_does_not_stop_the_ones_after_it(self):
        self.store.append("system.before", "test", {"headline": "Before"})
        with open(self.paths.event_store, "a", encoding="utf-8") as handle:
            handle.write("corrupt\n")
        self.store.append("system.after", "test", {"headline": "After"})
        observer, stream = make_observer(self)
        observer.show_history()
        output = stream.getvalue()
        self.assertIn("Before", output)
        self.assertIn("After", output)
        self.assertIn("MALFORMED", output)

    def test_a_completely_empty_line_is_reported_not_crashed_on(self):
        with open(self.paths.event_store, "w", encoding="utf-8") as handle:
            handle.write("\n\n\n")
        observer, stream = make_observer(self)
        observer.show_history()
        self.assertEqual(observer.stats.malformed, 3)
        self.assertIn("MALFORMED", stream.getvalue())


class HighVolumeTests(LabTestCase):
    def test_a_thousand_events_are_all_displayed(self):
        for index in range(1000):
            self.store.append(
                "system.bulk", "test", {"headline": f"Event {index}", "index": index}
            )
        observer, stream = make_observer(self)
        shown = observer.show_history()
        self.assertEqual(shown, 1000)
        self.assertEqual(observer.stats.malformed, 0)
        output = stream.getvalue()
        self.assertIn("Event 0", output)
        self.assertIn("Event 999", output)
        self.assertEqual(output.count("\n"), 1000)

    def test_output_is_batched_rather_than_written_per_event(self):
        """One write per event cannot keep up with a burst."""
        for index in range(500):
            self.store.append("system.bulk", "test", {"headline": f"E{index}"})
        observer, stream = make_observer(self)
        observer.show_history()
        self.assertEqual(observer.stats.displayed, 500)
        # 500 events at FLUSH_LINES=64 is roughly 8 writes, not 500.
        self.assertLess(observer.stats.batches, 50)
        self.assertGreaterEqual(observer.stats.batches, 5)

    def test_recent_line_buffer_is_bounded(self):
        """Unbounded retention would be a memory leak in a long session."""
        for index in range(2000):
            self.store.append("system.bulk", "test", {"headline": f"E{index}"})
        observer, _ = make_observer(self)
        observer.show_history()
        self.assertLessEqual(len(observer.recent), RING_SIZE)

    def test_summary_mode_aggregates_instead_of_streaming(self):
        for index in range(300):
            namespace = "system" if index % 2 == 0 else "security"
            self.store.append(f"{namespace}.bulk", "test")
        observer, stream = make_observer(self, summary_mode=True)
        observer.show_history()
        output = stream.getvalue()
        self.assertIn("Event summary by category", output)
        self.assertIn("system", output)
        self.assertIn("security", output)
        self.assertIn("By event type", output)
        # Aggregated, so far fewer lines than events.
        self.assertLess(output.count("\n"), 40)

    def test_progress_notes_appear_at_the_requested_interval(self):
        for index in range(100):
            self.store.append("system.bulk", "test", {"headline": f"E{index}"})
        observer, stream = make_observer(self, progress_every=25)
        observer.show_history()
        self.assertIn("/s)", stream.getvalue())

    def test_throughput_is_reported(self):
        for index in range(100):
            self.store.append("system.bulk", "test", {"headline": f"E{index}"})
        observer, _ = make_observer(self)
        observer.show_history()
        stats = observer.stats.to_dict()
        self.assertEqual(stats["displayed"], 100)
        self.assertGreater(stats["events_per_second"], 0)
        self.assertGreater(stats["elapsed_seconds"], 0)


class FollowTests(LabTestCase):
    def test_follow_displays_events_appended_after_it_starts(self):
        self.store.append("system.initial", "test", {"headline": "Initial"})
        observer, stream = make_observer(self, follow=True, poll_interval=0.01)
        done = threading.Event()

        def run() -> None:
            observer.run()
            done.set()

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        time.sleep(0.2)
        self.store.append("system.live", "test", {"headline": "LiveEvent"})
        time.sleep(0.4)
        observer.stop()
        done.wait(timeout=5.0)

        output = stream.getvalue()
        self.assertIn("Initial", output)
        self.assertIn("LiveEvent", output)

    def test_a_shrinking_log_is_reported_to_the_operator(self):
        self.store.append("system.initial", "test", {"headline": "Initial"})
        observer, stream = make_observer(self, follow=True, poll_interval=0.01)
        done = threading.Event()

        def run() -> None:
            observer.run()
            done.set()

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        time.sleep(0.2)
        self.paths.event_store.write_text("", encoding="utf-8")
        time.sleep(0.3)
        observer.stop()
        done.wait(timeout=5.0)
        self.assertIn("shrank", stream.getvalue())


class ReadOnlyIndependenceTests(LabTestCase):
    def test_the_observer_works_from_the_log_alone(self):
        """The log is the source of truth, not the observer's memory.

        A fresh observer over the same log must reach the same conclusion,
        which is what makes a future web Observatory safe to add.
        """
        self.store.append("system.one", "test", {"headline": "One"})
        first, first_stream = make_observer(self)
        first.show_history()
        second, second_stream = make_observer(self)
        second.show_history()
        self.assertEqual(first_stream.getvalue(), second_stream.getvalue())

    def test_deleting_the_observer_module_would_lose_no_data(self):
        """Structural property: the observer holds no authoritative state."""
        from pathlib import Path

        observer_dir = support.ROOT / "observer"
        self.assertTrue((observer_dir / "terminal.py").exists())
        # The observer writes only to the stream it is given.
        stream = io.StringIO()
        observer = TerminalObserver(
            paths=self.paths,
            store=self.store,
            stream=stream,
            options=RenderOptions(colour=False),
            follow=False,
        )
        before = sorted(p.name for p in Path(self.paths.event_store).parent.iterdir())
        observer.show_history()
        after = sorted(p.name for p in Path(self.paths.event_store).parent.iterdir())
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
