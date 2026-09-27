"""Milestone 004 -- rendering-level verification.

The lesson carried over from Milestone 003: an honest data model can still be
rendered into a misleading picture, so these tests assert on the **text a human
would actually read**, not on the model behind it.

Every test renders the complete output through the real ``ObservatoryRenderer``
and then inspects the resulting string. A test that only asserted
``model.state == expected`` would pass even if the renderer lied.
"""

from __future__ import annotations

import unittest

from observatory.graph import StateGraph
from observatory.model import (
    CONVENTIONAL_DOMAINS,
    CognitiveState,
    EpistemicStatus,
    StateValue,
)
from observatory.render import ObservatoryRenderer, RenderOptions
from observatory.snapshot import ObservatorySnapshot
from observatory.subject import (
    NO_SUBJECT_BANNER,
    RECORDED_BANNER,
    RECORDED_DETAIL,
    UNRECORDED_DETAIL,
    SubjectStatus,
)


def render(snapshot: ObservatorySnapshot, **options) -> str:
    """Render through the real path, colour off so assertions see plain text."""
    opts = {"color": False}
    opts.update(options)
    return ObservatoryRenderer(RenderOptions(**opts)).render(snapshot)


def make_snapshot(
    *,
    subject_status: str = SubjectStatus.NO_SUBJECT.value,
    banner: str = NO_SUBJECT_BANNER,
    detail: str | None = "Cognitive telemetry unavailable",
    birth: dict | None = None,
    state: CognitiveState | None = None,
    faults: list[str] | None = None,
    trust: dict | None = None,
    os_boundary: dict | None = None,
) -> ObservatorySnapshot:
    return ObservatorySnapshot(
        subject_status=subject_status,
        subject_banner=banner,
        subject_detail=detail,
        state=state if state is not None else CognitiveState.empty(),
        graph=StateGraph(),
        reader_state={"ingested": 0, "highest_seq": 0},
        faults=list(faults or []),
        generated_at="2026-01-01T00:00:00Z",
        birth=dict(birth or {}),
        trust=dict(trust or {}),
        os_boundary=dict(os_boundary or {}),
    )


def birth_payload(**overrides) -> dict:
    base = {
        "model_status": "NOT_CONFIGURED",
        "model_usable": False,
        "model": None,
        "model_installed": False,
        "subject_exists": False,
        "subject_id": "",
        "born_at": "",
        "birth_id": "",
        "birth_event_id": "",
        "birth_record_hash": "",
        "environment_id": "none",
        "environment_connected": False,
        "workspace_state": "EMPTY",
        "capability_statuses": {},
        "capability_registry_hash": "",
        "model_detail": "",
    }
    base.update(overrides)
    return base


class Invariant1NoSubjectImpliesNothing(unittest.TestCase):
    """Invariant 1: with no subject, the display must not imply one exists."""

    def test_banner_states_no_subject(self):
        text = render(make_snapshot())
        self.assertIn("NO EXPERIMENTAL SUBJECT ATTACHED", text)

    def test_telemetry_unavailability_is_stated(self):
        self.assertIn("Cognitive telemetry unavailable", render(make_snapshot()))

    def test_no_subject_id_is_displayed(self):
        text = render(make_snapshot(birth=birth_payload()))
        self.assertNotIn("SUBJECT:", text)

    def test_state_section_says_there_is_no_state(self):
        text = render(make_snapshot())
        state = text.split("-- STATE")[1].split("-- RELATIONSHIPS")[0]
        self.assertIn("no cognitive state to display", state)

    def test_no_epistemic_claim_is_presented(self):
        text = render(make_snapshot())
        state = text.split("-- STATE")[1].split("-- RELATIONSHIPS")[0]
        for claim in ("[OBSERVED]", "[DERIVED]"):
            self.assertNotIn(claim, state)


class Invariant2RecordedIsNotAttached(unittest.TestCase):
    """Invariant 2: a record without a key must read RECORDED, never ATTACHED."""

    SNAP = make_snapshot(
        subject_status=SubjectStatus.RECORDED.value,
        banner=f"{RECORDED_BANNER}: baby-ai:subject-001",
        detail=RECORDED_DETAIL,
        birth=birth_payload(
            model_status="READY",
            model_installed=True,
            subject_exists=True,
            subject_id="baby-ai:subject-001",
            born_at="2026-01-01T00:00:00Z",
            birth_id="BIRTH-000001",
        ),
    )

    def test_display_says_recorded(self):
        self.assertIn("RECORDED", render(self.SNAP))

    def test_display_never_says_attached(self):
        text = render(self.SNAP)
        self.assertNotIn("ATTACHED,", text)
        self.assertNotIn("KEY-ATTACHED,", text.replace("NOT KEY-ATTACHED", ""))

    def test_recorded_detail_is_visible(self):
        self.assertIn(RECORDED_DETAIL, render(self.SNAP))

    def test_no_active_agency_is_implied(self):
        text = render(self.SNAP)
        # A recorded subject cannot author anything, so the display must not
        # suggest it is operating.
        self.assertIn("no signing key", text)
        self.assertNotIn("AGENT ONLINE", text)

    def test_state_section_declines_to_show_state(self):
        state = render(self.SNAP).split("-- STATE")[1].split("-- RELATIONSHIPS")[0]
        self.assertIn("no signing key", state)
        self.assertIn("No cognitive state is shown", state)


class Invariant3KeyWithoutRecordExposesDiscrepancy(unittest.TestCase):
    """Invariant 3: a key with no record must not read as NO_SUBJECT."""

    SNAP = make_snapshot(
        subject_status=SubjectStatus.ATTACHED.value,
        banner="SUBJECT: baby-ai:subject-001",
        detail=UNRECORDED_DETAIL,
        birth=birth_payload(model_status="READY", model_installed=True),
    )

    def test_does_not_say_no_subject(self):
        self.assertNotIn("NO EXPERIMENTAL SUBJECT ATTACHED", render(self.SNAP))

    def test_exposes_the_authority_discrepancy(self):
        text = render(self.SNAP)
        self.assertIn(UNRECORDED_DETAIL, text)
        self.assertIn("No birth record exists", text)

    def test_names_the_key_as_the_only_evidence(self):
        self.assertIn("key is the only evidence", render(self.SNAP))


class Invariant4RuntimeUnverifiedIsNotReady(unittest.TestCase):
    """Invariant 4: an unexecuted runtime must never read READY."""

    def test_runtime_unverified_is_shown(self):
        text = render(make_snapshot(birth=birth_payload(model_status="RUNTIME_UNVERIFIED")))
        self.assertIn("RUNTIME_UNVERIFIED", text)

    def test_runtime_unverified_never_coexists_with_ready(self):
        text = render(make_snapshot(birth=birth_payload(model_status="RUNTIME_UNVERIFIED")))
        self.assertNotIn("model status    READY", text)
        self.assertNotIn("READY", text.replace("RUNTIME_UNVERIFIED", ""))

    def test_runtime_unavailable_never_coexists_with_ready(self):
        text = render(make_snapshot(birth=birth_payload(model_status="RUNTIME_UNAVAILABLE")))
        self.assertNotIn("READY", text)

    def test_unusable_model_is_marked_not_usable(self):
        text = render(make_snapshot(birth=birth_payload(model_status="MODEL_INTEGRITY_MISMATCH")))
        self.assertIn("not usable", text)


class Invariant5NoModelNoInference(unittest.TestCase):
    """Invariant 5: an uninstalled model must not imply inference is available."""

    def test_not_configured_is_shown(self):
        self.assertIn(
            "NOT_CONFIGURED", render(make_snapshot(birth=birth_payload(model_status="NOT_CONFIGURED")))
        )

    def test_model_not_installed_is_shown(self):
        self.assertIn(
            "MODEL_NOT_INSTALLED",
            render(make_snapshot(birth=birth_payload(model_status="MODEL_NOT_INSTALLED"))),
        )

    def test_weights_are_unavailable_not_present(self):
        text = render(make_snapshot(birth=birth_payload(model_status="MODEL_NOT_INSTALLED")))
        self.assertIn("UNAVAILABLE", text)
        self.assertNotIn("present and matching", text)

    def test_no_ready_claim_without_a_model(self):
        for status in ("NOT_CONFIGURED", "MODEL_NOT_INSTALLED", "MODEL_INTEGRITY_MISMATCH"):
            with self.subTest(status=status):
                text = render(make_snapshot(birth=birth_payload(model_status=status)))
                self.assertNotIn("READY", text)


class Invariant6InterfaceIsNotImplementation(unittest.TestCase):
    """Invariant 6: a component that is only an interface must not read implemented."""

    def test_capabilities_read_none_implemented(self):
        payload = birth_payload(
            model_status="READY",
            model_installed=True,
            capability_statuses={"memory": "UNIMPLEMENTED", "tool_use": "UNIMPLEMENTED"},
        )
        self.assertIn("none implemented", render(make_snapshot(birth=payload)))

    def test_registry_hash_alone_does_not_claim_implementation(self):
        payload = birth_payload(
            model_status="READY", model_installed=True, capability_registry_hash="abc123"
        )
        self.assertIn("none implemented", render(make_snapshot(birth=payload)))


class Invariant7UnavailableStaysUnavailable(unittest.TestCase):
    """Invariant 7: an unavailable value must never silently become a value."""

    def test_environment_id_is_unavailable_when_absent(self):
        payload = birth_payload(model_status="READY", model_installed=True, environment_id="")
        text = render(make_snapshot(birth=payload))
        self.assertIn("UNAVAILABLE", text)

    def test_model_hash_is_unavailable_when_absent(self):
        payload = birth_payload(
            model_status="READY",
            model_installed=True,
            model={"model_name": "m", "model_family": "", "model_sha256": ""},
        )
        self.assertIn("UNAVAILABLE", render(make_snapshot(birth=payload)))

    def test_missing_read_error_is_not_invented(self):
        text = render(make_snapshot(birth=birth_payload()))
        self.assertNotIn("read error", text)

    def test_unavailable_state_domains_render_as_unavailable(self):
        state = CognitiveState(
            subject_id="baby-ai:subject-001",
            version=1,
            timestamp="2026-01-01T00:00:00Z",
            domains={
                domain: StateValue(domain, EpistemicStatus.UNAVAILABLE)
                for domain in CONVENTIONAL_DOMAINS
            },
        )
        snap = make_snapshot(
            subject_status=SubjectStatus.ATTACHED.value,
            banner="SUBJECT: baby-ai:subject-001",
            detail=None,
            state=state,
            birth=birth_payload(model_status="READY", model_installed=True),
        )
        text = render(snap)
        self.assertIn("UNAVAILABLE", text)
        state_section = text.split("-- STATE")[1].split("-- RELATIONSHIPS")[0]
        self.assertNotIn("[OBSERVED]", state_section)


class MalformedAndFaultStates(unittest.TestCase):
    """Malformed, partial, and fault states must be visible, not smoothed over."""

    def test_read_error_is_displayed(self):
        payload = birth_payload(read_error="BIRTH.json is not valid JSON")
        self.assertIn("birth read error", render(make_snapshot(birth=payload)))

    def test_faults_are_displayed(self):
        snap = make_snapshot(faults=["event log chain broken at line 4"])
        self.assertIn("event log chain broken", render(snap))

    def test_empty_birth_payload_renders_without_crashing(self):
        text = render(make_snapshot(birth={}))
        self.assertIn("COGNITIVE STATE OBSERVATORY", text)

    def test_partial_birth_payload_does_not_invent_fields(self):
        """A payload with only a status must not fabricate identity or a hash."""
        section = render(make_snapshot(birth={"model_status": "READY"}))
        section = section.split("-- BIRTH / FOUNDATION")[1].split("-- STATE")[0]
        self.assertIn("none: no birth record exists", section)
        self.assertNotIn("baby-ai:subject", section)
        self.assertNotIn("BIRTH-", section)

    def test_malformed_model_dict_is_tolerated(self):
        payload = birth_payload(model={"unexpected": object()})
        self.assertIn("COGNITIVE STATE OBSERVATORY", render(make_snapshot(birth=payload)))


class RenderingIsDeterministic(unittest.TestCase):
    def test_same_snapshot_renders_identically(self):
        snap = make_snapshot(birth=birth_payload())
        renderer = ObservatoryRenderer(RenderOptions(color=False))
        self.assertEqual(renderer.render(snap), renderer.render(snap))

    def test_plain_text_has_no_escape_codes(self):
        self.assertNotIn("\033[", render(make_snapshot(birth=birth_payload())))


class TrustBoundarySectionRendering(unittest.TestCase):
    """Section 22: the Observatory must show the real trust state."""

    TRUST = {
        "human_authority": "lifecycle, config, model selection, provenance, snapshots, shutdown, birth authorization",
        "laboratory_authority": "event log, provenance, research records, Observatory, control interface",
        "baby_ai_authority": "own workspace only; no inherited Tier 1 authority",
        "os_isolation": "NOT_IMPLEMENTED",
        "control_access": "DENIED",
        "provenance_access": "DENIED",
        "evidence_access": "DENIED",
        "birth_safety_gate": "BLOCKED",
    }

    def _snap(self, trust=None):
        return make_snapshot(birth=birth_payload(), trust=dict(trust if trust is not None else self.TRUST))

    def test_trust_boundary_section_is_rendered(self):
        self.assertIn("TRUST BOUNDARY", render(self._snap()))

    def test_os_isolation_is_shown_as_not_implemented(self):
        text = render(self._snap())
        self.assertIn("NOT_IMPLEMENTED", text)
        self.assertNotIn("OS isolation     VERIFIED", text)

    def test_birth_safety_gate_is_shown_as_blocked(self):
        self.assertIn("BLOCKED", render(self._snap()))

    def test_denial_is_shown_for_control_provenance_and_evidence(self):
        text = render(self._snap())
        self.assertIn("DENIED", text)

    def test_missing_trust_keys_render_unavailable_not_default(self):
        text = render(self._snap(trust={"os_isolation": "NOT_IMPLEMENTED"}))
        self.assertIn("UNAVAILABLE", text)
        self.assertNotIn("VERIFIED", text)

    def test_absent_trust_block_renders_nothing_rather_than_inventing(self):
        text = render(self._snap(trust={}))
        self.assertNotIn("TRUST BOUNDARY", text)


if __name__ == "__main__":
    unittest.main()
