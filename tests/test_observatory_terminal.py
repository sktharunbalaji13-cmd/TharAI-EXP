"""Rendering and the live session.

The renderer is where an honest data model can still be turned into a
misleading picture, so the tests check the text a human would actually read.
"""

from __future__ import annotations

import contextlib
import io
import unittest

from observatory.render import ObservatoryRenderer, RenderOptions
from observatory.terminal import ObservatorySession
from tests.support import LabTestCase


def render(session: ObservatorySession, **options) -> str:
    return ObservatoryRenderer(RenderOptions(**options)).render(session.snapshot())


class NoSubjectRenderingTests(LabTestCase):
    def setUp(self) -> None:
        super().setUp()
        for index in range(3):
            self.store.append("system.test", "test", {"n": index})
        self.session = ObservatorySession(
            paths=self.paths, clock=self.clock, keyring=self.keyring
        )
        self.session.update()

    def test_banner_is_the_first_thing_shown(self) -> None:
        text = render(self.session)
        self.assertIn("NO EXPERIMENTAL SUBJECT ATTACHED", text)

    def test_telemetry_unavailability_is_stated(self) -> None:
        self.assertIn("Cognitive telemetry unavailable", render(self.session))

    def test_no_cognitive_state_is_shown(self) -> None:
        self.assertIn("no cognitive state to display", render(self.session))

    def test_infrastructure_events_are_still_listed(self) -> None:
        # Showing the real record is not the same as claiming a mind exists.
        text = render(self.session)
        self.assertIn("EVENT-000001", text)
        self.assertIn("INFRASTRUCTURE", text)

    def test_no_claim_status_appears_in_the_state_section(self) -> None:
        text = render(self.session)
        state_section = text.split("-- STATE")[1].split("-- RELATIONSHIPS")[0]
        for word in ("OBSERVED", "DERIVED"):
            self.assertNotIn(word, state_section)

    def test_graph_section_says_telemetry_is_unavailable(self) -> None:
        self.assertIn("Telemetry unavailable", render(self.session))

    def test_plain_text_has_no_escape_codes(self) -> None:
        text = render(self.session, color=False)
        self.assertNotIn("\033[", text)

    def test_colour_can_be_enabled(self) -> None:
        self.assertIn("\033[", render(self.session, color=True))

    def test_render_is_deterministic(self) -> None:
        # The same snapshot always renders identically, which is what makes the
        # output testable. (The fixture clock advances between calls, so this
        # renders one captured snapshot twice rather than two fresh ones.)
        snapshot = self.session.snapshot()
        renderer = ObservatoryRenderer(RenderOptions())
        self.assertEqual(renderer.render(snapshot), renderer.render(snapshot))

    def test_no_ansi_artefacts_when_wide(self) -> None:
        # Box drawing in the rules is fine; leaking escape codes is not.
        for line in render(self.session).splitlines():
            self.assertNotIn("[0m", line)


class SubjectRenderingTests(LabTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.provision_baby_ai("baby-ai:subject")
        self.session = ObservatorySession(
            paths=self.paths,
            clock=self.clock,
            keyring=self.keyring,
            subject_namespace=frozenset({"baby"}),
            subject_label="SUBJECT",
        )
        self.session.update()
        self.session.store.append(
            "baby.report", "subject.runtime", {"state": {"memory": {"count": 2}}}
        )
        self.session.update()

    def test_banner_names_the_subject(self) -> None:
        text = render(self.session)
        self.assertIn("SUBJECT: baby-ai:subject", text)
        self.assertNotIn("NO EXPERIMENTAL SUBJECT", text)

    def test_reported_domain_is_shown_as_observed(self) -> None:
        text = render(self.session)
        self.assertIn("memory", text)
        self.assertIn('{"count": 2}', text)
        self.assertIn("OBSERVED", text)

    def test_unreported_domain_shows_unavailable_not_empty(self) -> None:
        state = self.session.deriver.snapshot(self.clock.now())
        # Only memory was reported. A renderer that filled in the rest would be
        # inventing them; check the model refuses first.
        self.assertIsNotNone(state.get("perception"))
        self.assertEqual(state.get("perception").display(), "UNAVAILABLE")

    def test_detail_mode_shows_source_event_ids(self) -> None:
        text = render(self.session, detail=True)
        self.assertIn("source: EVENT-", text)

    def test_detail_mode_shows_liveness_note(self) -> None:
        self.assertIn("note:", render(self.session, detail=True))

    def test_history_is_rendered_separately_by_the_cli(self) -> None:
        from observatory.cli import main

        # The human declares the subject's namespace on the command line; the
        # Observatory never guesses it from the events.
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            main(["--subject-namespace", "baby", "history"])
        text = buffer.getvalue()
        self.assertIn("v1", text)
        self.assertIn("caused by: EVENT-", text)


class SessionUpdateTests(LabTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.session = ObservatorySession(
            paths=self.paths, clock=self.clock, keyring=self.keyring
        )

    def test_update_is_idempotent_without_new_events(self) -> None:
        self.store.append("system.test", "test", {"n": 1})
        first = self.session.update()
        second = self.session.update()
        self.assertEqual(first.reader_state["ingested"], second.reader_state["ingested"])

    def test_new_events_appear_on_the_next_update(self) -> None:
        self.store.append("system.test", "test", {"n": 1})
        self.session.update()
        self.store.append("system.test", "test", {"n": 2})
        snapshot = self.session.update()
        self.assertEqual(snapshot.reader_state["ingested"], 2)

    def test_snapshot_lists_traceable_event_ids(self) -> None:
        self.store.append("system.test", "test", {"n": 1})
        snapshot = self.session.update()
        # Even with no subject, the real event IDs are exposed for traceability.
        self.assertIn("EVENT-000001", snapshot.traceable_event_ids())

    def test_traceable_ids_are_sorted_and_unique(self) -> None:
        for index in range(3):
            self.store.append("system.test", "test", {"n": index})
        ids = self.session.update().traceable_event_ids()
        self.assertEqual(ids, sorted(set(ids)))

    def test_faults_are_surfaced_in_the_snapshot(self) -> None:
        self.store.append("system.test", "test", {"n": 1})
        self.rewrite_events(lambda text: text + "corrupt\n")
        snapshot = self.session.update()
        self.assertGreaterEqual(snapshot.reader_state["malformed_lines"], 1)

    def test_live_loop_renders_the_requested_number_of_frames(self) -> None:
        self.store.append("system.test", "test", {"n": 1})
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = self.session.follow(iterations=3, render_options=RenderOptions())
        self.assertEqual(code, 0)
        self.assertEqual(buffer.getvalue().count("COGNITIVE STATE OBSERVATORY"), 3)

    def test_live_loop_stops_on_interrupt(self) -> None:
        def interrupt(*args, **kwargs):
            raise KeyboardInterrupt

        self.session.clock.now = interrupt
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = self.session.follow(iterations=None, render_options=RenderOptions())
        self.assertEqual(code, 130)


if __name__ == "__main__":
    unittest.main()
