"""Subject attachment: NO SUBJECT must be the answer, and stay the answer.

The registry is the boundary that stops the Observatory from inventing the
thing it is supposed to measure. These tests pin that boundary down from both
sides: with no key there is no subject, and the only way to get a subject is a
key the human registered.
"""

from __future__ import annotations

import unittest

from babylab.identity import Role
from observatory.subject import (
    NO_SUBJECT_BANNER,
    NO_SUBJECT_DETAIL,
    SubjectRegistry,
    SubjectStatus,
)
from tests.support import LabTestCase


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
