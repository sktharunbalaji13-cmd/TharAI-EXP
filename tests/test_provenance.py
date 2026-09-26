"""Provenance tests.

The specification requires: creation record, modification record, integrity
verification, and tampering detection. The centre of gravity is the last of
the specification's provenance requirements - authorship must be derived from
something outside the subject's control, not from a field the subject writes.

Test tiers used throughout this file
------------------------------------
``APPLICATION SECURITY TEST``
    Exercised here. Proves the Python code behaves as specified.

``OPERATING SYSTEM SECURITY TEST``
    NOT exercised here. Requires a second OS principal, which Milestone 001
    does not have. See tests/test_trust_boundaries.py and docs/security-model.md.
"""

from __future__ import annotations

import json
import unittest

from tests import support  # noqa: F401
from tests.support import LabTestCase

from babylab.errors import IntegrityError, TrustBoundaryViolation, ValidationError
from babylab.hashing import canonical_json
from babylab.identity import Actor, Role
from provenance.keyring import Keyring
from provenance.ledger import Action, UNTRUSTED_METADATA_KEYS, LedgerEntry
from provenance.recorder import ABSENT_SHA256, FileState

MILESTONE = "MILESTONE-001"


class KeyringTests(LabTestCase):
    def test_roles_are_derived_from_the_key_not_the_record(self):
        baby = self.provision_baby_ai()
        self.assertIs(self.keyring.role_of(self.human_key.key_id), Role.HUMAN)
        self.assertIs(self.keyring.role_of(self.system_key.key_id), Role.SYSTEM)
        self.assertIs(self.keyring.role_of(baby.key_id), Role.BABY_AI)

    def test_unregistered_key_has_no_derivable_role(self):
        with self.assertRaises(IntegrityError) as caught:
            self.keyring.role_of("HK-does-not-exist")
        self.assertIn("cannot", str(caught.exception))

    def test_secret_material_never_appears_in_the_public_keyring(self):
        text = self.paths.keyring.read_text(encoding="utf-8")
        secret = self.keyring.secret(self.human_key.key_id)
        import base64

        self.assertNotIn(base64.b64encode(secret).decode("ascii"), text)
        self.assertNotIn(secret.hex(), text)

    def test_fingerprint_detects_replaced_key_material(self):
        key_id = self.human_key.key_id
        self.assertTrue(self.keyring.check_fingerprint(key_id))
        self.paths.private_key_dir.joinpath(f"{key_id}.key").write_text(
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=", encoding="ascii"
        )
        self.assertFalse(self.keyring.check_fingerprint(key_id))
        self.assertTrue(any("fingerprint" in problem for problem in self.keyring.audit()))

    def test_sign_and_verify_round_trip(self):
        key_id = self.human_key.key_id
        signature = self.keyring.sign(key_id, b"message")
        self.assertTrue(self.keyring.verify(key_id, b"message", signature))
        self.assertFalse(self.keyring.verify(key_id, b"other", signature))

    def test_wrong_key_does_not_verify(self):
        signature = self.keyring.sign(self.human_key.key_id, b"message")
        self.assertFalse(
            self.keyring.verify(self.system_key.key_id, b"message", signature)
        )

    def test_key_ids_cannot_escape_the_private_directory(self):
        for bad in ("../escape", "sub/dir", "..", ".hidden", ""):
            with self.subTest(bad=bad), self.assertRaises(Exception):
                self.keyring._secret_path(bad)

    def test_no_baby_ai_key_exists_until_a_human_provisions_one(self):
        """The laboratory must not pre-authorise the subject.

        A key minted at bootstrap would be a decision about the future
        experiment made by the infrastructure rather than by the researcher.
        """
        fresh = Keyring(
            self.root / "fresh" / "keyring.json", self.root / "fresh" / "private"
        )
        fresh._entries = {}
        fresh._loaded = True
        self.assertFalse(fresh.has_role(Role.BABY_AI))
        with self.assertRaises(Exception):
            fresh.key_for_role(Role.BABY_AI)


class CreationRecordTests(LabTestCase):
    def test_creation_is_recorded_with_content_hash_and_author(self):
        target = self.write("human_control/research_records/notes.md", "first")
        entry = self.recorder.record_creation(
            target, self.human, MILESTONE, "initial note"
        )
        self.assertEqual(entry.action, Action.CREATE)
        self.assertEqual(entry.path, "human_control/research_records/notes.md")
        self.assertIsNotNone(entry.author)
        self.assertEqual(entry.author, Role.HUMAN)
        self.assertEqual(entry.size_bytes, len("first"))
        self.assertEqual(entry.content_sha256, FileState.of(str(target)).sha256)
        self.assertIsNone(entry.prev_version_id)

    def test_creation_is_persisted(self):
        before = self.ledger.count()
        target = self.write("human_control/research_records/a.txt", "a")
        self.recorder.record_creation(target, self.human, MILESTONE, "create a")
        self.assertEqual(self.ledger.count(), before + 1)
        entries = self.ledger.history_for_path("human_control/research_records/a.txt")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].path, "human_control/research_records/a.txt")

    def test_system_and_human_authorship_are_distinguishable(self):
        """The specification requires distinguishing HUMAN from SYSTEM."""
        human_file = self.write("human_control/research_records/h.txt", "h")
        system_file = self.write("human_control/snapshots/s.json", "{}")
        self.recorder.record_creation(human_file, self.human, MILESTONE, "human")
        self.recorder.record_creation(system_file, self.system, MILESTONE, "system")
        summary = self.ledger.summary()
        self.assertEqual(summary["by_author"]["SYSTEM"], 1)
        self.assertEqual(
            summary["by_author"]["HUMAN"], self.baseline_entries + 1
        )
        system_entry = self.ledger.latest_for_path("human_control/snapshots/s.json")
        self.assertEqual(system_entry.author, Role.SYSTEM)

    def test_experiment_id_and_reason_are_recorded(self):
        target = self.write("human_control/research_records/e.txt", "e")
        entry = self.recorder.record_creation(
            target, self.human, "EXP-0007", "because of a specific reason"
        )
        self.assertEqual(entry.experiment_id, "EXP-0007")
        self.assertEqual(entry.reason, "because of a specific reason")


class ModificationRecordTests(LabTestCase):
    def setUp(self):
        super().setUp()
        self.target = self.write("human_control/research_records/doc.md", "v1")
        self.first = self.recorder.record_creation(
            self.target, self.human, MILESTONE, "create"
        )

    def test_modification_links_to_the_previous_version(self):
        self.target.write_text("v2", encoding="utf-8")
        second = self.recorder.record_modification(
            self.target, self.human, MILESTONE, "revise"
        )
        self.assertEqual(second.action, Action.MODIFY)
        self.assertEqual(second.prev_version_id, self.first.entry_id)
        self.assertNotEqual(second.content_sha256, self.first.content_sha256)

    def test_a_long_history_forms_an_unbroken_chain(self):
        previous = self.first
        for index in range(2, 6):
            self.target.write_text(f"v{index}", encoding="utf-8")
            previous = self.recorder.record_modification(
                self.target, self.human, MILESTONE, f"revision {index}"
            )
        history = self.ledger.history_for_path("human_control/research_records/doc.md")
        self.assertEqual(len(history), 5)
        self.assertIsNone(history[0].prev_version_id)
        for earlier, later in zip(history, history[1:]):
            self.assertEqual(later.prev_version_id, earlier.entry_id)

    def test_history_can_be_walked_backwards_to_the_first_version(self):
        self.target.write_text("v2", encoding="utf-8")
        self.recorder.record_modification(self.target, self.human, MILESTONE, "revise")
        entries = list(self.ledger.iter_entries())
        walked: list[str] = []
        current: LedgerEntry | None = entries[-1]
        while current is not None and current.prev_version_id is not None:
            current = next(
                e for e in entries if e.entry_id == current.prev_version_id
            )
            walked.append(current.content_sha256)
        self.assertEqual(walked[0], self.first.content_sha256)

    def test_recording_a_modification_of_a_deleted_file_is_refused(self):
        self.target.unlink()
        with self.assertRaises(ValueError) as caught:
            self.recorder.record_modification(self.target, self.human, MILESTONE, "revise")
        self.assertIn("deletion", str(caught.exception))

    def test_deletion_is_recordable(self):
        self.target.unlink()
        entry = self.recorder.record_deletion(self.target, self.human, MILESTONE, "removed")
        self.assertEqual(entry.action, Action.DELETE)
        self.assertEqual(entry.content_sha256, ABSENT_SHA256)


class AuthorshipAttributionTests(LabTestCase):
    """The load-bearing tests of the whole provenance system.

    The specification: "the author classification must NOT be determined by a
    value written by Baby AI itself."
    """

    def test_baby_ai_cannot_claim_to_be_human_by_writing_an_author_field(self):
        baby = self.provision_baby_ai()
        target = self.root / "baby_workspace" / "code" / "note.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("anything", encoding="utf-8")
        entry = self.ledger.record(
            action=Action.CREATE,
            path="baby_workspace/code/note.txt",
            content_sha256=FileState.of(str(target)).sha256,
            size_bytes=target.stat().st_size,
            experiment_id=MILESTONE,
            reason="subject wrote a file",
            actor=baby,
            metadata={"author": "HUMAN", "role": "HUMAN", "owner": "human"},
        )
        self.assertEqual(entry.author, Role.BABY_AI)
        self.assertNotIn("author", entry.metadata)
        self.assertNotIn("role", entry.metadata)
        self.assertNotIn("owner", entry.metadata)
        self.assertEqual(
            entry.metadata["dropped_untrusted_fields"],
            sorted(UNTRUSTED_METADATA_KEYS & {"author", "role", "owner"}),
        )

    def test_the_signed_body_contains_no_author_field(self):
        """Otherwise a record could restate its own authorship under signature."""
        baby = self.provision_baby_ai()
        entry = self.ledger.record(
            action=Action.CREATE,
            path="baby_workspace/code/x.txt",
            content_sha256=ABSENT_SHA256,
            size_bytes=0,
            experiment_id=MILESTONE,
            reason="r",
            actor=baby,
        )
        self.assertNotIn("author", entry.signed_body())
        self.assertEqual(entry.signed_body()["key_id"], baby.key_id)

    def test_hand_editing_the_author_field_is_detected(self):
        target = self.write("human_control/research_records/x.txt", "x")
        self.recorder.record_creation(target, self.system, MILESTONE, "system wrote")
        self.rewrite_ledger(
            lambda text: text.replace('"author":"SYSTEM"', '"author":"HUMAN"')
        )
        report = self.ledger.verify()
        self.assertFalse(report.intact)
        self.assertTrue(
            any("contradicts the keyring" in problem for problem in report.problems)
        )

    def test_a_baby_ai_actor_requires_a_key_id(self):
        with self.assertRaises(ValueError):
            Actor.baby_ai(key_id="")
        with self.assertRaises(ValueError):
            Actor.baby_ai(key_id=None)

    def test_unsigned_entries_are_refused(self):
        naked = Actor(role=Role.BABY_AI, actor_id="baby-ai:x", key_id=None)
        with self.assertRaises(ValidationError) as caught:
            self.ledger.record(
                action=Action.CREATE,
                path="p",
                content_sha256=ABSENT_SHA256,
                size_bytes=0,
                experiment_id=MILESTONE,
                reason="r",
                actor=naked,
            )
        self.assertIn("must be signed", str(caught.exception))


class IntegrityVerificationTests(LabTestCase):
    def setUp(self):
        super().setUp()
        self.a = self.write("human_control/research_records/a.txt", "alpha")
        self.b = self.write("human_control/research_records/b.txt", "beta")
        self.recorder.record_creation(self.a, self.human, MILESTONE, "create a")
        self.recorder.record_creation(self.b, self.system, MILESTONE, "create b")

    def test_intact_ledger_verifies(self):
        report = self.ledger.verify()
        self.assertTrue(report.intact, msg=report.problems)
        # Delta rather than an absolute count, so that changes to the shared
        # test fixture do not silently invalidate the assertion.
        self.assertEqual(report.valid_entries, self.baseline_entries + 2)

    def test_content_tampering_is_detected(self):
        def tamper(text: str) -> str:
            return text.replace('"reason":"create a"', '"reason":"create A"')

        self.rewrite_ledger(tamper)
        report = self.ledger.verify()
        self.assertFalse(report.intact)
        self.assertTrue(any("hash mismatch" in problem for problem in report.problems))
        self.assertTrue(any("MAC does not verify" in problem for problem in report.problems))

    def test_recomputing_the_hash_after_tampering_is_still_caught(self):
        """A smarter tamperer who fixes the hash still fails the MAC.

        This is the check that makes the hash chain worth having: without the
        MAC, an attacker with write access could rewrite an entry and its
        digest, and the chain would verify perfectly.
        """
        import hashlib

        def tamper(text: str) -> str:
            lines = text.splitlines()
            entry = json.loads(lines[0])
            entry["reason"] = "forged reason"
            from babylab.hashing import canonical_bytes

            body = {name: getattr(LedgerEntry.from_dict(entry), name) for name in ()}
            del body
            signed = LedgerEntry.from_dict(entry)
            entry["hash"] = hashlib.sha256(canonical_bytes(signed.signed_body())).hexdigest()
            lines[0] = canonical_json(entry)
            return "\n".join(lines) + "\n"

        self.rewrite_ledger(tamper)
        report = self.ledger.verify()
        self.assertFalse(report.intact)
        self.assertTrue(any("MAC does not verify" in problem for problem in report.problems))

    def test_forging_an_entry_with_an_unregistered_key_is_detected(self):
        def forge(text: str) -> str:
            lines = text.splitlines()
            entry = json.loads(lines[0])
            entry["key_id"] = "HK-attacker-invented"
            lines[0] = canonical_json(entry)
            return "\n".join(lines) + "\n"

        self.rewrite_ledger(forge)
        report = self.ledger.verify()
        self.assertFalse(report.intact)
        self.assertTrue(any("not in the keyring" in problem for problem in report.problems))

    def test_deleting_a_middle_entry_is_detected(self):
        self.recorder.record_creation(
            self.write("human_control/research_records/c.txt", "gamma"),
            self.human,
            MILESTONE,
            "create c",
        )
        def delete_middle(text: str) -> str:
            lines = text.splitlines(keepends=True)
            return "".join(lines[:1] + lines[2:])

        self.rewrite_ledger(delete_middle)
        report = self.ledger.verify()
        self.assertFalse(report.intact)
        self.assertTrue(any("prev_entry_hash" in problem for problem in report.problems))

    def test_broken_version_linkage_is_detected(self):
        self.b.write_text("beta2", encoding="utf-8")
        self.recorder.record_modification(self.b, self.human, MILESTONE, "revise b")
        def break_link(text: str) -> str:
            lines = text.splitlines()
            entry = json.loads(lines[-1])
            entry["prev_version_id"] = "PROV-000001"
            lines[-1] = canonical_json(entry)
            return "\n".join(lines) + "\n"

        self.rewrite_ledger(break_link)
        report = self.ledger.verify()
        self.assertFalse(report.intact)
        self.assertTrue(any("prev_version_id" in problem for problem in report.problems))

    def test_malformed_lines_are_reported_without_hiding_the_rest(self):
        with open(self.ledger.path, "a", encoding="utf-8") as handle:
            handle.write("{not json\n")
        report = self.ledger.verify()
        self.assertFalse(report.intact)
        self.assertEqual(report.malformed_lines, 1)
        self.assertEqual(report.valid_entries, self.baseline_entries + 2)

    def test_fast_mode_still_catches_chain_breaks_but_not_forgeries(self):
        """Documents the difference between the two verification depths.

        ``deep=False`` recomputes chain hashes only. It still catches an
        in-place edit, because the hash covers the content. It does *not*
        catch an edit where the attacker also recomputes the hash - only the
        MAC check does. Both facts are asserted so the documentation cannot
        drift away from the behaviour.
        """
        self.rewrite_ledger(
            lambda text: text.replace('"reason":"create a"', '"reason":"quiet edit"')
        )
        shallow = self.ledger.verify(deep=False)
        self.assertFalse(shallow.intact)
        self.assertTrue(any("hash mismatch" in p for p in shallow.problems))
        self.assertFalse(any("MAC does not verify" in p for p in shallow.problems))

        deep = self.ledger.verify(deep=True)
        self.assertTrue(any("MAC does not verify" in p for p in deep.problems))


class SealTests(LabTestCase):
    def setUp(self):
        super().setUp()
        self.target = self.write("human_control/research_records/s.txt", "s")
        self.recorder.record_creation(self.target, self.human, MILESTONE, "create")

    def test_seal_lands_in_human_control(self):
        path = self.ledger.seal(self.human, note="checkpoint")
        self.assertTrue(path.exists())
        self.assertEqual(
            self.paths.relative(path), "human_control/provenance/HEAD.json"
        )

    def test_seal_verifies_against_an_unchanged_ledger(self):
        self.ledger.seal(self.human)
        report = self.ledger.verify_seal()
        self.assertIsNotNone(report)
        self.assertTrue(report.intact, msg=report.problems)

    def test_seal_detects_tail_truncation(self):
        """The one attack the chain alone cannot see."""
        self.ledger.seal(self.human, note="after one entry")
        second = self.write("human_control/research_records/t.txt", "t")
        self.recorder.record_creation(second, self.human, MILESTONE, "create t")
        self.ledger.seal(self.human, note="after two entries")

        def truncate(text: str) -> str:
            return text.splitlines(keepends=True)[0]

        self.rewrite_ledger(truncate)
        report = self.ledger.verify_seal()
        self.assertIsNotNone(report)
        self.assertFalse(report.intact)
        self.assertTrue(
            any("TRUNCATED" in problem for problem in report.problems),
            msg=report.problems,
        )

    def test_altering_the_seal_itself_is_detected(self):
        path = self.ledger.seal(self.human)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["head_hash"] = "0" * 64
        path.write_text(canonical_json(data) + "\n", encoding="utf-8")
        report = self.ledger.verify_seal()
        self.assertFalse(report.intact)
        self.assertTrue(any("seal itself was altered" in p for p in report.problems))

    def test_no_seal_means_no_verdict_rather_than_a_false_pass(self):
        self.assertIsNone(self.ledger.verify_seal())

    def test_sealing_requires_a_key(self):
        naked = Actor(role=Role.HUMAN, actor_id="human:x", key_id=None)
        with self.assertRaises(ValidationError):
            self.ledger.seal(naked)

    def test_empty_ledger_cannot_be_sealed(self):
        fresh = Keyring(self.paths.keyring, self.paths.private_key_dir)
        from provenance.ledger import ProvenanceLedger

        ledger = ProvenanceLedger(
            self.root / "empty.jsonl", fresh, seal_dir=self.paths.protected_provenance
        )
        with self.assertRaises(ValidationError):
            ledger.seal(self.human)


class ProtectedFileTests(LabTestCase):
    def test_unrecorded_creation_in_a_protected_area_is_detected(self):
        self.write("human_control/research_records/sneaky.txt", "sneaky")
        problems = self.recorder.verify_paths()
        self.assertTrue(any("unrecorded creation" in p for p in problems), problems)

    def test_unrecorded_modification_is_detected(self):
        target = self.write("human_control/research_records/tracked.txt", "v1")
        self.recorder.record_creation(target, self.human, MILESTONE, "create")
        self.assertEqual(self.recorder.verify_paths(), [])

        target.write_text("v2 without telling anyone", encoding="utf-8")
        problems = self.recorder.verify_paths()
        self.assertTrue(any("content differs" in p for p in problems), problems)

    def test_unrecorded_deletion_is_detected(self):
        target = self.write("human_control/research_records/gone.txt", "v1")
        self.recorder.record_creation(target, self.human, MILESTONE, "create")
        target.unlink()
        problems = self.recorder.verify_paths()
        self.assertTrue(any("unrecorded deletion" in p for p in problems), problems)

    def test_private_key_material_is_excluded_by_design(self):
        """Secret digests do not belong in a research record."""
        problems = self.recorder.verify_paths()
        for problem in problems:
            self.assertNotIn("private", problem)
        excluded = {path for path, _ in self.recorder.untracked_by_design()}
        self.assertIn(self.paths.private_key_dir, excluded)
        self.assertIn(self.paths.protected_provenance, excluded)

    def test_every_exclusion_states_a_reason(self):
        for _, reason in self.recorder.untracked_by_design():
            self.assertGreater(len(reason), 40, "an unexplained exclusion is a hole")


if __name__ == "__main__":
    unittest.main()
