"""Tests for authorship classification.

The property under test throughout: authorship is a function of external facts,
and a self-declaration cannot change it.
"""

from __future__ import annotations

import unittest

from babylab.errors import ValidationError
from babylab.identity import Role
from birth.authorship import (
    ArtifactKind,
    AuthorshipClass,
    classify_artifact,
    combine,
    strip_self_declared_authorship,
)


class TestInheritedPretrained(unittest.TestCase):
    def test_weights_are_inherited_regardless_of_role(self) -> None:
        for role in (Role.HUMAN, Role.BABY_AI, Role.SYSTEM, None):
            with self.subTest(role=role):
                record = classify_artifact(ArtifactKind.MODEL_WEIGHTS, role=role)
                self.assertIs(record.classification, AuthorshipClass.INHERITED_PRETRAINED)

    def test_weights_are_inherited_despite_self_declaration(self) -> None:
        record = classify_artifact(
            ArtifactKind.MODEL_WEIGHTS, declared=AuthorshipClass.BABY_AI_AUTHORED
        )
        self.assertIs(record.classification, AuthorshipClass.INHERITED_PRETRAINED)
        self.assertIn(
            "BABY_AI_AUTHORED", record.rejected_declarations,
            "the rejected declaration must be recorded, not silently dropped",
        )

    def test_correct_declaration_is_not_rejected(self) -> None:
        record = classify_artifact(
            ArtifactKind.MODEL_WEIGHTS, declared="INHERITED_PRETRAINED"
        )
        self.assertIs(record.classification, AuthorshipClass.INHERITED_PRETRAINED)
        self.assertEqual(record.rejected_declarations, ())

    def test_model_configuration_is_also_inherited(self) -> None:
        record = classify_artifact(ArtifactKind.MODEL_CONFIGURATION)
        self.assertIs(record.classification, AuthorshipClass.INHERITED_PRETRAINED)

    def test_no_code_path_classifies_a_model_as_subject_work(self) -> None:
        """The strongest statement of the rule, checked exhaustively."""
        for kind in ArtifactKind:
            for role in Role:
                for declared in AuthorshipClass:
                    record = classify_artifact(kind, role=role, declared=declared)
                    if kind.is_inherited:
                        self.assertIs(
                            record.classification,
                            AuthorshipClass.INHERITED_PRETRAINED,
                            f"{kind} classified as {record.classification}",
                        )

    def test_basis_mentions_pre_existing_training(self) -> None:
        record = classify_artifact(ArtifactKind.MODEL_WEIGHTS)
        self.assertIn("before this experiment began", record.basis)


class TestRoleDerivation(unittest.TestCase):
    def test_human_key_implies_human_authored(self) -> None:
        record = classify_artifact(ArtifactKind.RESEARCH_DOCUMENT, role=Role.HUMAN)
        self.assertIs(record.classification, AuthorshipClass.HUMAN_AUTHORED)

    def test_baby_key_implies_baby_authored(self) -> None:
        record = classify_artifact(ArtifactKind.SUBJECT_OUTPUT, role=Role.BABY_AI)
        self.assertIs(record.classification, AuthorshipClass.BABY_AI_AUTHORED)

    def test_system_key_imimplies_system_generated(self) -> None:
        record = classify_artifact(ArtifactKind.SOURCE_CODE, role=Role.SYSTEM)
        self.assertIs(record.classification, AuthorshipClass.SYSTEM_GENERATED)

    def test_no_role_is_unknown_not_guessed(self) -> None:
        record = classify_artifact(ArtifactKind.SUBJECT_OUTPUT, role=None)
        self.assertIs(record.classification, AuthorshipClass.UNKNOWN)
        self.assertIn("not established", record.basis)

    def test_mismatched_declaration_is_rejected(self) -> None:
        record = classify_artifact(
            ArtifactKind.SUBJECT_OUTPUT, role=Role.BABY_AI, declared="HUMAN_AUTHORED"
        )
        self.assertIs(record.classification, AuthorshipClass.BABY_AI_AUTHORED)
        self.assertIn("HUMAN_AUTHORED", record.rejected_declarations)

    def test_unknown_declaration_is_an_error(self) -> None:
        with self.assertRaises(ValidationError):
            classify_artifact(ArtifactKind.SOURCE_CODE, declared="TRUSTED_ME")

    def test_empty_declaration_is_ignored(self) -> None:
        record = classify_artifact(ArtifactKind.SOURCE_CODE, role=Role.HUMAN, declared="  ")
        self.assertIs(record.classification, AuthorshipClass.HUMAN_AUTHORED)
        self.assertEqual(record.rejected_declarations, ())


class TestStripSelfDeclared(unittest.TestCase):
    def test_author_keys_are_removed(self) -> None:
        cleaned, dropped = strip_self_declared_authorship(
            {"sensor_id": "cam", "author": "BABY_AI", "role": "HUMAN", "provenance": "x"}
        )
        self.assertEqual(cleaned, {"sensor_id": "cam"})
        self.assertEqual(dropped, ("author", "provenance", "role"))

    def test_clean_payload_is_unchanged(self) -> None:
        payload = {"sensor_id": "cam", "readings": {"lux": 400}}
        cleaned, dropped = strip_self_declared_authorship(payload)
        self.assertEqual(cleaned, payload)
        self.assertEqual(dropped, ())

    def test_non_object_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            strip_self_declared_authorship(["not", "a", "dict"])


class TestCombine(unittest.TestCase):
    def test_single_record_passes_through(self) -> None:
        record = classify_artifact(ArtifactKind.SOURCE_CODE, role=Role.HUMAN)
        self.assertIs(combine([record]), record)

    def test_mixed_roles_produce_mixed(self) -> None:
        combined = combine(
            [
                classify_artifact(ArtifactKind.SOURCE_CODE, role=Role.HUMAN),
                classify_artifact(ArtifactKind.SUBJECT_OUTPUT, role=Role.BABY_AI),
            ]
        )
        self.assertIs(combined.classification, AuthorshipClass.MIXED_AUTHORED)
        self.assertEqual(
            combined.evidence["contributions"], ["BABY_AI_AUTHORED", "HUMAN_AUTHORED"]
        )

    def test_unknown_contribution_blocks_the_whole(self) -> None:
        combined = combine(
            [
                classify_artifact(ArtifactKind.SOURCE_CODE, role=Role.HUMAN),
                classify_artifact(ArtifactKind.SUBJECT_OUTPUT, role=None),
            ]
        )
        self.assertIs(
            combined.classification,
            AuthorshipClass.UNKNOWN,
            "an unattributable contribution must not be laundered into a mixture",
        )

    def test_empty_is_unknown(self) -> None:
        self.assertIs(combine([]).classification, AuthorshipClass.UNKNOWN)

    def test_mixed_never_calls_a_pretrained_model_the_subject(self) -> None:
        combined = combine(
            [
                classify_artifact(ArtifactKind.SOURCE_CODE, role=Role.HUMAN),
                classify_artifact(ArtifactKind.MODEL_WEIGHTS),
            ]
        )
        self.assertIs(combined.classification, AuthorshipClass.MIXED_AUTHORED)
        self.assertNotIn(
            "BABY_AI_AUTHORED", combined.evidence["contributions"]
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
