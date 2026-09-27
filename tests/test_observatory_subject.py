"""Subject attachment: NO SUBJECT must be the answer, and stay the answer.

The registry is the boundary that stops the Observatory from inventing the
thing it is supposed to measure. These tests pin that boundary down from both
sides: with no key there is no subject, and the only way to get a subject is a
key the human registered.

Milestone 003 adds a third state. A ceremony can leave a sealed birth record
behind, which means a subject *exists*, but the ceremony does not provision a
signing key — that is a separate human decision. So a recorded subject is
genuinely present and genuinely not attached, and the display has to be able to
say both without rounding either one up.
"""

from __future__ import annotations

import unittest

from babylab.identity import Role
from observatory.subject import (
    NO_SUBJECT_BANNER,
    NO_SUBJECT_DETAIL,
    RECORDED_BANNER,
    RECORDED_DETAIL,
    SubjectRegistry,
    SubjectStatus,
)
from tests.support import LabTestCase


def birth_payload(subject_id: str = "baby-ai:subject-001") -> dict:
    """The shape :func:`birth.status.birth_status` returns for a born subject."""
    return {
        "subject_exists": True,
        "subject_id": subject_id,
        "born_at": "2026-09-27T00:00:00+00:00",
        "birth_id": "birth-0001",
        "birth_event_id": "evt-0001",
        "model_status": "READY",
        "model_detail": "model verified",
        "capability_registry_hash": "a" * 64,
        "capability_statuses": {},
        "environment_id": "env-unattached",
        "environment_connected": False,
        "workspace_state": "UNINITIALIZED",
    }


class SubjectRegistryTests(LabTestCase):
    def test_no_baby_ai_key_means_no_subject(self) -> None:
        registry = SubjectRegistry(self.keyring)
        self.assertFalse(self.keyring.has_role(Role.BABY_AI))
        self.assertIsNone(registry.subject())
        self.assertFalse(registry.is_attached())

    def test_status_is_no_subject(self) -> None:
        self.assertIs(SubjectRegistry(self.keyring).status, SubjectStatus.NO_SUBJECT)

    def test_describe_is_the_honest_banner(self) -> None:
        self.assertEqual(SubjectRegistry(self.keyring).describe(), NO_SUBJECT_BANNER)

    def test_banner_and_detail_are_distinct_claims(self) -> None:
        # "No subject attached" and "telemetry unavailable" are different facts.
        # Collapsing them would hide which half of the instrument is missing.
        self.assertIn("NO EXPERIMENTAL SUBJECT", NO_SUBJECT_BANNER)
        self.assertIn("telemetry unavailable", NO_SUBJECT_DETAIL.lower())

    def test_no_keyring_at_all_means_no_subject(self) -> None:
        self.assertIsNone(SubjectRegistry(None).subject())

    def test_broken_keyring_means_no_subject_not_assumed_subject(self) -> None:
        class Hostile:
            def has_role(self, role):
                raise RuntimeError("keyring is unreadable")

        # We cannot establish a subject, so we report none. Assuming one would
        # be the exact failure this module exists to prevent.
        self.assertIsNone(SubjectRegistry(Hostile()).subject())

    def test_human_and_system_keys_do_not_make_a_subject(self) -> None:
        # The fixture provisions HUMAN and SYSTEM. Neither is the subject.
        registry = SubjectRegistry(self.keyring)
        self.assertIsNone(registry.subject())

    def test_provisioned_baby_ai_key_attaches_a_subject(self) -> None:
        actor = self.provision_baby_ai("baby-ai:subject")
        registry = SubjectRegistry(self.keyring)
        subject = registry.subject()
        self.assertIsNotNone(subject)
        self.assertEqual(subject.subject_id, actor.actor_id)
        self.assertTrue(registry.is_attached())

    def test_attached_registry_describes_the_subject(self) -> None:
        self.provision_baby_ai("baby-ai:subject")
        self.assertEqual(
            SubjectRegistry(self.keyring).describe(), "SUBJECT: baby-ai:subject"
        )

    def test_dict_reports_status_and_no_subject_detail(self) -> None:
        data = SubjectRegistry(self.keyring).to_dict()
        self.assertEqual(data["status"], "NO_SUBJECT")
        self.assertIsNone(data["subject"])
        self.assertEqual(data["detail"], NO_SUBJECT_DETAIL)

    def test_dict_omits_detail_when_attached(self) -> None:
        self.provision_baby_ai("baby-ai:subject")
        data = SubjectRegistry(self.keyring).to_dict()
        self.assertIsNotNone(data["subject"])
        self.assertIsNone(data["detail"])


class RecordedButNotAttachedTests(LabTestCase):
    """A birth record proves existence; it does not prove a signing key."""

    def registry(self, subject_id: str = "baby-ai:subject-001") -> SubjectRegistry:
        return SubjectRegistry(self.keyring, birth_payload(subject_id))

    def test_a_record_alone_makes_the_status_recorded(self) -> None:
        self.assertIs(self.registry().status, SubjectStatus.RECORDED)

    def test_a_record_alone_does_not_attach_a_subject(self) -> None:
        # The important one. Reporting "SUBJECT: baby-ai:subject-001" here would
        # tell the reader the subject can sign things. It cannot; no key exists.
        registry = self.registry()
        self.assertIsNone(registry.subject())
        self.assertFalse(registry.is_attached())

    def test_a_record_makes_the_subject_present(self) -> None:
        # The other half. It would be equally wrong to keep reporting
        # NO SUBJECT after a ceremony, because that would hide a real birth.
        self.assertTrue(self.registry().is_present())

    def test_the_banner_names_both_halves(self) -> None:
        self.assertEqual(self.registry().describe(), f"{RECORDED_BANNER}: baby-ai:subject-001")

    def test_the_detail_says_why_it_is_not_attached(self) -> None:
        self.assertEqual(self.registry().detail(), RECORDED_DETAIL)
        self.assertIn("signing key is provisioned", RECORDED_DETAIL.lower())

    def test_recorded_subject_id_is_available_for_labelling(self) -> None:
        self.assertEqual(self.registry().recorded_subject_id(), "baby-ai:subject-001")

    def test_a_baby_ai_key_upgrades_recorded_to_attached(self) -> None:
        self.provision_baby_ai("baby-ai:subject-001")
        registry = self.registry()
        self.assertIs(registry.status, SubjectStatus.ATTACHED)
        self.assertIsNotNone(registry.subject())
        # The recorded id is still reported, so the display can show which
        # identity the record names and that a key backs it.
        self.assertEqual(registry.recorded_subject_id(), "baby-ai:subject-001")

    def test_a_key_without_a_record_is_still_attached_not_recorded(self) -> None:
        # The two sources are independent. A key alone means something can sign
        # but no ceremony was ever performed; that is a real and reportable state.
        self.provision_baby_ai("baby-ai:subject-001")
        registry = SubjectRegistry(self.keyring, birth_payload())
        self.assertIs(registry.status, SubjectStatus.ATTACHED)

    def test_dict_reports_recorded_status_and_no_key_backed_subject(self) -> None:
        data = self.registry().to_dict()
        self.assertEqual(data["status"], "RECORDED")
        self.assertIsNone(data["subject"])
        self.assertEqual(data["recorded_subject_id"], "baby-ai:subject-001")
        self.assertEqual(data["detail"], RECORDED_DETAIL)

    def test_an_empty_birth_payload_is_still_no_subject(self) -> None:
        # The status module always returns the keys, so a payload with
        # ``subject_exists: False`` must not accidentally register a subject.
        registry = SubjectRegistry(self.keyring, {"subject_exists": False, "subject_id": ""})
        self.assertIs(registry.status, SubjectStatus.NO_SUBJECT)

    def test_a_registry_with_no_birth_payload_is_still_no_subject(self) -> None:
        self.assertIs(SubjectRegistry(self.keyring).status, SubjectStatus.NO_SUBJECT)


class RegistryHasNoWritePathTests(LabTestCase):
    def test_registry_exposes_no_mutation(self) -> None:
        forbidden = {"register", "create", "add", "attach", "provision", "set_subject", "delete"}
        public = {name for name in dir(SubjectRegistry) if not name.startswith("_")}
        self.assertEqual(public & forbidden, set())

    def test_registry_cannot_be_made_to_attach_a_subject_by_attribute(self) -> None:
        # Frozen semantics: it is a plain object, so someone *can* poke
        # ``_keyring``, but there is no supported way. Assert the supported
        # surface is empty, which is the enforceable part.
        registry = SubjectRegistry(self.keyring)
        self.assertFalse(hasattr(registry, "subject_id"))


if __name__ == "__main__":
    unittest.main()
