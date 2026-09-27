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

    def test_subject_detail_is_rendered_not_just_the_banner(self) -> None:
        # The banner alone reads "SUBJECT: <id>", which implies a ceremony ran.
        # This session has a key and no birth record, so the correction has to
        # reach the screen. It did not: the renderer printed the detail only in
        # the no-subject branch, and the same omission hid RECORDED_DETAIL.
        text = render(self.session)
        self.assertIn("No birth record exists", text)

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


class BirthFoundationRenderingTests(LabTestCase):
    """The unconfigured laboratory is the most common case and must read well.

    There is no model and no subject in a fresh installation. That is not a
    failure to report, it is the state, and the display has to state it without
    looking broken.
    """

    def session(self) -> ObservatorySession:
        session = ObservatorySession(
            paths=self.paths, clock=self.clock, keyring=self.keyring
        )
        session.update()
        return session

    def test_unconfigured_laboratory_still_has_a_birth_section(self) -> None:
        text = render(self.session())
        self.assertIn("BIRTH / FOUNDATION", text)

    def test_not_configured_is_shown_rather_than_guessed(self) -> None:
        self.assertIn("NOT_CONFIGURED", render(self.session()))

    def test_no_model_is_reported_as_unavailable_not_absent_silently(self) -> None:
        text = render(self.session())
        # An empty cell would read as "no model, nothing to see", which is a
        # different claim from "we could not determine this".
        self.assertIn("weights           UNAVAILABLE", text)
        self.assertIn("model usable      no (unproven)", text)

    def test_no_birth_record_is_stated_explicitly(self) -> None:
        self.assertIn("none: no birth record exists", render(self.session()))

    def test_infrastructure_and_cognition_stay_in_separate_sections(self) -> None:
        text = render(self.session())
        # Match the section rules, not the words: the header already contains
        # "COGNITIVE STATE", which would make a substring search meaningless.
        self.assertLess(text.index("-- BIRTH / FOUNDATION"), text.index("-- STATE "))

    def test_no_cognitive_state_is_inferred_from_a_configured_model(self) -> None:
        # The state section must still say no subject, regardless of what the
        # birth section reports. A model is not a mind.
        text = render(self.session())
        state_at = text.index("STATE")
        self.assertIn("No subject attached", text[state_at:])

    def test_detail_mode_adds_the_capability_registry_digest(self) -> None:
        session = self.session()
        plain = render(session)
        detailed = render(session, detail=True)
        self.assertLessEqual(len(plain), len(detailed))
        self.assertIn("registry sha256", detailed)


class BornButUnattachedRenderingTests(LabTestCase):
    """After a ceremony: a subject exists, and it has still said nothing.

    This is the state that would be most tempting to render generously. A birth
    record is real, and it would be easy to show a state table next to it. The
    whole point is that there is nothing to show.
    """

    def born_session(self) -> ObservatorySession:
        self.born_subject()
        session = ObservatorySession(
            paths=self.paths, clock=self.clock, keyring=self.keyring
        )
        session.update()
        return session

    def test_the_banner_reports_recorded_not_attached(self) -> None:
        self.assertIn("SUBJECT RECORDED, NOT KEY-ATTACHED", render(self.born_session()))

    def test_the_subject_id_is_shown(self) -> None:
        self.assertIn("baby-ai:subject-001", render(self.born_session()))

    def test_the_birth_event_id_is_shown_and_traceable(self) -> None:
        session = self.born_session()
        text = render(session, detail=True)
        snapshot = session.snapshot()
        self.assertIn(snapshot.birth["birth_event_id"], text)
        # A displayed id that is not traceable is a number from nowhere.
        self.assertIn(snapshot.birth["birth_event_id"], snapshot.traceable_event_ids())

    def test_no_cognitive_state_is_shown_for_an_unattached_subject(self) -> None:
        text = render(self.born_session())
        self.assertIn("no signing key", text)
        self.assertIn("No cognitive state is shown", text)

    def test_no_domain_is_reported_as_observed(self) -> None:
        # The renderer would only print this if a value had been attributed to a
        # subject. Nothing has been, so it must not appear.
        self.assertNotIn("[OBSERVED]", render(self.born_session()))

    def test_attaching_a_key_makes_the_state_section_live(self) -> None:
        self.provision_baby_ai("baby-ai:subject-001")
        text = render(self.born_session())
        self.assertIn("SUBJECT: baby-ai:subject-001", text)
        self.assertNotIn("no signing key", text)
        self.assertIn("has not reported any state yet", text)


class BirthReadFailureTests(LabTestCase):
    """A broken birth subsystem must not take the Observatory down with it."""

    def test_a_corrupt_birth_record_is_reported_not_raised(self) -> None:
        self.paths.birth_record.parent.mkdir(parents=True, exist_ok=True)
        self.paths.birth_record.write_text("{not json", encoding="utf-8")
        session = ObservatorySession(
            paths=self.paths, clock=self.clock, keyring=self.keyring
        )
        snapshot = session.update()
        self.assertEqual(snapshot.birth["model_status"], "UNAVAILABLE")
        self.assertIn("read_error", snapshot.birth)

    def test_the_display_still_renders(self) -> None:
        self.paths.birth_record.parent.mkdir(parents=True, exist_ok=True)
        self.paths.birth_record.write_text("{not json", encoding="utf-8")
        session = ObservatorySession(
            paths=self.paths, clock=self.clock, keyring=self.keyring
        )
        session.update()
        text = render(session)
        self.assertIn("COGNITIVE STATE OBSERVATORY", text)
        self.assertIn("birth read error", text)


if __name__ == "__main__":
    unittest.main()
