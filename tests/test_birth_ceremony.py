"""Tests for the birth record and the birth ceremony.

The ceremony is the one function that creates a subject, so these tests lean
hard on the negative cases: what must *not* exist afterwards when a precondition
fails. A milestone that quietly produced a subject from a missing model would be
worse than a milestone that produced nothing.
"""

from __future__ import annotations

import dataclasses
import json
import unittest

from babylab.errors import IntegrityError, ValidationError
from tests.birth_fixtures import (
    configure_installed_model,
    usable_probe,
    weights_config,
)
from tests.support import LabTestCase
from birth.birth_record import (
    BirthRecord,
    build_record,
    load_record,
    record_path,
    verify_record,
    write_record,
)
from birth.cognitive import CapabilityRegistry
from birth.config import FoundationConfig, RuntimeKind, load_config, save_config
from birth.environment import unattached_environment
from birth.fake import fake_config
from birth.identity import ModelStatus, resolve_model_identity
from birth.service import (
    BIRTH_EVENT_SOURCE,
    BIRTH_EVENT_TYPE,
    birth_ceremony,
    birth_status,
    inspect,
)
from birth.workspace import CodeWorkspace


def read_events(case: LabTestCase) -> list[dict]:
    return [json.loads(line) for line in case.read_event_lines()]


class TestUnconfiguredLaboratoryBearsNoSubject(LabTestCase):
    def test_ceremony_without_config_reports_not_configured(self) -> None:
        result = birth_ceremony(paths=self.paths, recorder=self.recorder)
        self.assertIs(result.status, ModelStatus.NOT_CONFIGURED)
        self.assertFalse(result.born)

    def test_no_record_and_no_event_are_created(self) -> None:
        birth_ceremony(
            paths=self.paths, recorder=self.recorder, runtime_probe=usable_probe
        )
        self.assertIsNone(load_record(self.paths))
        self.assertFalse(record_path(self.paths).exists())
        self.assertEqual(self.read_event_lines(), [], "no event may exist either")

    def test_no_provenance_entry_is_created(self) -> None:
        before = self.ledger.count()
        birth_ceremony(
            paths=self.paths, recorder=self.recorder, runtime_probe=usable_probe
        )
        self.assertEqual(self.ledger.count(), before)

    def test_ceremony_is_repeatable_and_still_bears_nothing(self) -> None:
        for _ in range(3):
            result = birth_ceremony(paths=self.paths, recorder=self.recorder)
            self.assertFalse(result.born)
        self.assertIsNone(load_record(self.paths))


class TestUninstalledModelBearsNoSubject(LabTestCase):
    def test_ceremony_with_config_but_no_weights(self) -> None:
        save_config(weights_config(), self.paths)
        result = birth_ceremony(
            paths=self.paths, recorder=self.recorder, runtime_probe=usable_probe
        )
        self.assertIs(result.status, ModelStatus.MODEL_NOT_INSTALLED)
        self.assertFalse(result.born)
        self.assertIn("nothing will be fetched automatically", result.detail)

    def test_no_record_event_or_provenance(self) -> None:
        save_config(weights_config(), self.paths)
        before = self.ledger.count()
        birth_ceremony(
            paths=self.paths, recorder=self.recorder, runtime_probe=usable_probe
        )
        self.assertIsNone(load_record(self.paths))
        self.assertEqual(self.read_event_lines(), [])
        self.assertEqual(self.ledger.count(), before)

    def test_wrong_weights_bear_no_subject(self) -> None:
        config = weights_config()
        target = config.resolve_model_path(self.paths)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"different bytes than configured")
        save_config(config, self.paths)
        result = birth_ceremony(
            paths=self.paths, recorder=self.recorder, runtime_probe=usable_probe
        )
        self.assertIs(result.status, ModelStatus.MODEL_INTEGRITY_MISMATCH)
        self.assertFalse(result.born)
        self.assertIsNone(load_record(self.paths))

    def test_unusable_runtime_bears_no_subject(self) -> None:
        configure_installed_model(self)
        result = birth_ceremony(
            paths=self.paths,
            recorder=self.recorder,
            runtime_probe=lambda cfg: (False, "no such binary", "cpu"),
        )
        self.assertIs(result.status, ModelStatus.RUNTIME_UNAVAILABLE)
        self.assertFalse(result.born)
        self.assertIsNone(load_record(self.paths))
        self.assertEqual(self.read_event_lines(), [])


class TestAFakeRuntimeIsNotASubject(LabTestCase):
    """A test double must never be able to produce a birth record.

    The file is a real file with a real digest, so nothing but the runtime kind
    stands between this configuration and a subject. If the ceremony accepted it,
    a ``BIRTH.json`` describing a test double would sit in ``human_control/``
    looking exactly like a real one.
    """

    def setUp(self) -> None:
        super().setUp()
        configure_installed_model(self)

    def test_a_fake_runtime_is_refused(self) -> None:
        save_config(fake_config(), self.paths)
        result = birth_ceremony(
            paths=self.paths, recorder=self.recorder, runtime_probe=usable_probe
        )
        self.assertFalse(result.born)
        self.assertIs(result.status, ModelStatus.RUNTIME_UNAVAILABLE)
        self.assertIn("test double", result.detail)

    def test_no_record_event_or_provenance_is_produced(self) -> None:
        save_config(fake_config(), self.paths)
        before = self.ledger.count()
        birth_ceremony(
            paths=self.paths, recorder=self.recorder, runtime_probe=usable_probe
        )
        self.assertIsNone(load_record(self.paths))
        self.assertEqual(self.read_event_lines(), [])
        self.assertEqual(self.ledger.count(), before)

    def test_a_probe_that_says_fake_still_cannot_help(self) -> None:
        """Injecting a probe cannot bypass the refusal, because the refusal is
        about what the configuration names rather than about the probe's answer."""
        save_config(fake_config(), self.paths)
        result = birth_ceremony(
            paths=self.paths,
            recorder=self.recorder,
            runtime_probe=lambda cfg: (True, "fake runtime is always available", "fake"),
        )
        self.assertFalse(result.born)
        self.assertIsNone(load_record(self.paths))


class TestSuccessfulBirth(LabTestCase):
    def setUp(self) -> None:
        super().setUp()
        configure_installed_model(self)
        self.result = birth_ceremony(
            paths=self.paths,
            recorder=self.recorder,
            runtime_probe=usable_probe,
            experiment_id="EXP-BIRTH-001",
        )

    def test_a_subject_is_born(self) -> None:
        self.assertTrue(self.result.born)
        self.assertEqual(self.result.record.subject_id, "baby-ai:subject-001")

    def test_record_is_written_and_sealed(self) -> None:
        record = load_record(self.paths)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertTrue(record.verify_hash())
        self.assertTrue(record.birth_event_id)

    def test_verify_passes(self) -> None:
        ok, problems = verify_record(self.paths)
        self.assertTrue(ok, problems)

    def test_exactly_one_birth_event_is_emitted(self) -> None:
        events = read_events(self)
        births = [e for e in events if e["event_type"] == BIRTH_EVENT_TYPE]
        self.assertEqual(len(births), 1)
        event = births[0]
        self.assertEqual(event["source"], BIRTH_EVENT_SOURCE)
        self.assertEqual(event["event_id"], self.result.event_id)

    def test_event_is_laboratory_generated_not_self_announced(self) -> None:
        """The subject is named in the payload; it did not emit the event."""
        birth = [e for e in read_events(self) if e["event_type"] == BIRTH_EVENT_TYPE][0]
        self.assertEqual(birth["source"], BIRTH_EVENT_SOURCE)
        self.assertNotIn("baby-ai", birth["source"])
        self.assertEqual(birth["payload"]["subject_id"], "baby-ai:subject-001")

    def test_payload_records_the_model_as_inherited(self) -> None:
        birth = [e for e in read_events(self) if e["event_type"] == BIRTH_EVENT_TYPE][0]
        self.assertEqual(birth["payload"]["authored_by"], "INHERITED_PRETRAINED")
        self.assertEqual(
            birth["payload"]["model"]["model_sha256"],
            self.result.record.model.model_sha256,
        )

    def test_payload_says_capability_order_is_meaningless(self) -> None:
        birth = [e for e in read_events(self) if e["event_type"] == BIRTH_EVENT_TYPE][0]
        self.assertTrue(birth["payload"]["capability_order_is_meaningless"])

    def test_payload_reports_no_capability_implemented(self) -> None:
        birth = [e for e in read_events(self) if e["event_type"] == BIRTH_EVENT_TYPE][0]
        self.assertNotIn("IMPLEMENTED", birth["payload"]["capabilities"].values())

    def test_payload_reports_nothing_connected(self) -> None:
        birth = [e for e in read_events(self) if e["event_type"] == BIRTH_EVENT_TYPE][0]
        self.assertFalse(birth["payload"]["environment"]["connected"])
        self.assertEqual(birth["payload"]["workspace"]["subject_written_file_count"], 0)

    def test_event_and_record_name_each_other(self) -> None:
        """The two-way link, in the only direction that can exist.

        The event cannot carry the record's hash — the record does not exist yet
        when the event is appended — and the record must carry the event's id. So
        the link is by stable id, and a verifier checks the record, which hashes
        itself.
        """
        birth = [e for e in read_events(self) if e["event_type"] == BIRTH_EVENT_TYPE][0]
        record = load_record(self.paths)
        assert record is not None
        self.assertEqual(birth["payload"]["birth_id"], record.birth_id)
        self.assertEqual(record.birth_event_id, birth["event_id"])

    def test_event_cites_no_record_hash(self) -> None:
        """A hash in the event would be the pre-write hash, and would be wrong."""
        birth = [e for e in read_events(self) if e["event_type"] == BIRTH_EVENT_TYPE][0]
        self.assertNotIn("birth_record_hash", birth["payload"])
        self.assertTrue(birth["payload"]["birth_record_written_after_this_event"])

    def test_record_hash_describes_the_bytes_on_disk(self) -> None:
        record = load_record(self.paths)
        assert record is not None
        on_disk = json.loads(record_path(self.paths).read_text(encoding="utf-8"))
        self.assertEqual(on_disk["hash"], record.compute_hash())

    def test_record_stores_project_relative_paths(self) -> None:
        """A record naming one machine's absolute paths would not verify elsewhere."""
        record = load_record(self.paths)
        assert record is not None
        self.assertEqual(record.model_path, "var/models/fake/does-not-exist.gguf")
        self.assertEqual(record.workspace_root, "baby_workspace/code")
        for value in (record.model_path, record.workspace_root):
            self.assertNotIn(":", value)

    def test_record_carries_no_provenance_field(self) -> None:
        """A file cannot contain the digest of a ledger entry describing itself.

        The entry exists in the ledger and is found by path; the record has no
        always-empty field that could be mistaken for one.
        """
        record = load_record(self.paths)
        assert record is not None
        self.assertNotIn("provenance_entries", record.to_dict())

    def test_provenance_covers_the_creation(self) -> None:
        self.assertEqual(len(self.result.provenance_entries), 1)
        history = self.ledger.history_for_path(
            str(record_path(self.paths).relative_to(self.paths.root).as_posix())
        )
        self.assertEqual([entry.action.value for entry in history], ["CREATE"])
        for entry in history:
            self.assertEqual(entry.author.value, "SYSTEM")

    def test_provenance_chain_is_intact(self) -> None:
        report = self.ledger.verify()
        self.assertTrue(report.intact, report.problems)

    def test_ceremony_does_not_seal_the_ledger(self) -> None:
        """Sealing is a human act. The ceremony records and stops there."""
        self.assertIsNone(
            self.ledger.verify_seal(),
            "the ceremony must not write a human-signed head seal",
        )

    def test_provenance_entry_metadata_names_the_model(self) -> None:
        history = self.ledger.history_for_path(
            str(record_path(self.paths).relative_to(self.paths.root).as_posix())
        )
        self.assertEqual(
            history[0].metadata["model_sha256"], self.result.record.model.model_sha256
        )


class TestOneSubjectOnly(LabTestCase):
    def setUp(self) -> None:
        super().setUp()
        configure_installed_model(self)

    def test_second_ceremony_is_refused(self) -> None:
        first = self._ceremony()
        second = self._ceremony()
        self.assertTrue(first.born)
        self.assertFalse(second.born)
        self.assertIn("exactly one birth", second.detail)

    def test_second_ceremony_adds_no_second_event(self) -> None:
        self._ceremony()
        self._ceremony()
        births = [e for e in read_events(self) if e["event_type"] == BIRTH_EVENT_TYPE]
        self.assertEqual(len(births), 1)

    def test_write_record_refuses_to_overwrite(self) -> None:
        record = self._ceremony().record
        with self.assertRaises(IntegrityError) as caught:
            write_record(record, self.paths)
        self.assertIn("exactly one subject", str(caught.exception))

    def test_the_record_file_is_never_written_twice(self) -> None:
        """A single CREATE entry, because the bytes are written once.

        The earlier two-write order left a MODIFY entry for the event-id
        backfill, which meant the sealed document's bytes changed after they had
        been hashed and recorded.
        """
        self._ceremony()
        history = self.ledger.history_for_path(
            str(record_path(self.paths).relative_to(self.paths.root).as_posix())
        )
        self.assertEqual([entry.action.value for entry in history], ["CREATE"])

    def test_ceremony_is_idempotent_in_what_it_reports(self) -> None:
        first = self._ceremony()
        second = self._ceremony()
        self.assertEqual(first.record.birth_id, second.record.birth_id)
        self.assertEqual(first.event_id, second.event_id)

    def _ceremony(self):
        return birth_ceremony(
            paths=self.paths, recorder=self.recorder, runtime_probe=usable_probe
        )


class TestRecordIntegrity(LabTestCase):
    def setUp(self) -> None:
        super().setUp()
        configure_installed_model(self)
        self.result = birth_ceremony(
            paths=self.paths, recorder=self.recorder, runtime_probe=usable_probe
        )

    def test_modified_record_is_detected(self) -> None:
        path = record_path(self.paths)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["born_at"] = "1999-01-01T00:00:00.000Z"
        path.write_text(json.dumps(data), encoding="utf-8")
        ok, problems = verify_record(self.paths)
        self.assertFalse(ok)
        self.assertTrue(any("hash mismatch" in problem for problem in problems))

    def test_edited_model_digest_is_detected(self) -> None:
        path = record_path(self.paths)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["model"]["model_sha256"] = "c" * 64
        path.write_text(json.dumps(data), encoding="utf-8")
        ok, problems = verify_record(self.paths)
        self.assertFalse(ok)

    def test_record_claiming_baby_authorship_is_rejected_on_read(self) -> None:
        path = record_path(self.paths)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["model"]["authorship_classification"] = "BABY_AI_AUTHORED"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(ValidationError) as caught:
            load_record(self.paths)
        self.assertIn("has been edited", str(caught.exception))

    def test_corrupt_json_is_reported_as_corruption_not_a_partial_write(self) -> None:
        record_path(self.paths).write_text("{ truncated", encoding="utf-8")
        ok, problems = verify_record(self.paths)
        self.assertFalse(ok)
        self.assertTrue(any("not valid JSON" in problem for problem in problems))

    def test_record_without_an_event_id_fails_verification(self) -> None:
        record = self.result.record
        stripped = BirthRecord(**{**record.__dict__, "birth_event_id": ""})
        stripped = BirthRecord(
            **{**record.__dict__, "birth_event_id": "", "hash": record.hash}
        )
        target = record_path(self.paths)
        target.write_text(
            json.dumps({**stripped.to_dict(), "hash": record.hash}), encoding="utf-8"
        )
        ok, problems = verify_record(self.paths)
        self.assertFalse(ok)
        self.assertTrue(any("names no birth event" in problem for problem in problems))

    def test_event_id_cannot_be_renamed(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            self.result.record.with_birth_event("EVENT-999999")
        self.assertIn("refusing to rename", str(caught.exception))

    def test_observed_and_configured_digests_must_agree(self) -> None:
        with self.assertRaises(ValidationError):
            BirthRecord(
                **{
                    **self.result.record.__dict__,
                    "observed_model_sha256": "d" * 64,
                }
            )

    def test_schema_round_trip_is_stable(self) -> None:
        record = load_record(self.paths)
        assert record is not None
        restored = BirthRecord.from_dict(json.loads(json.dumps(record.to_dict())))
        self.assertEqual(restored.hash, record.hash)
        self.assertEqual(restored.compute_hash(), record.hash)


class TestBuildRecordRequiresAUsableModel(LabTestCase):
    def test_unusable_report_is_refused(self) -> None:
        report = resolve_model_identity(None, self.paths)
        with self.assertRaises(ValidationError) as caught:
            build_record(
                report=report,
                registry=CapabilityRegistry(),
                environment=unattached_environment(),
                workspace=CodeWorkspace.create(self.paths),
            )
        self.assertIn("refusing to write a birth record", str(caught.exception))

    def test_ready_report_produces_a_sealed_record(self) -> None:
        configure_installed_model(self)
        # Probed, because ``build_record`` rightly refuses a report whose runtime
        # was never checked: a record asserts the model could be run.
        report = resolve_model_identity(
            load_config(self.paths), self.paths, runtime_probe=usable_probe
        )
        record = build_record(
            report=report,
            registry=CapabilityRegistry(),
            environment=unattached_environment(),
            workspace=CodeWorkspace.create(self.paths),
        )
        self.assertTrue(record.hash)
        self.assertTrue(record.verify_hash())

    def test_an_unprobed_report_is_refused(self) -> None:
        """Verified weights alone are not grounds for writing an immutable record.

        A birth record is a permanent claim that a real model was really there.
        A report that never ran the runtime does not support that claim, so the
        refusal is the honest outcome.
        """
        configure_installed_model(self)
        report = resolve_model_identity(load_config(self.paths), self.paths)
        self.assertIs(report.status, ModelStatus.RUNTIME_UNVERIFIED)
        with self.assertRaises(ValidationError):
            build_record(
                report=report,
                registry=CapabilityRegistry(),
                environment=unattached_environment(),
                workspace=CodeWorkspace.create(self.paths),
            )


class TestStatusIsReadOnly(LabTestCase):
    def test_inspect_writes_nothing(self) -> None:
        configure_installed_model(self)
        before_events = self.read_event_lines()
        before_entries = self.ledger.count()
        result = inspect(self.paths)
        self.assertIs(result.status, ModelStatus.RUNTIME_UNVERIFIED)
        self.assertEqual(self.read_event_lines(), before_events)
        self.assertEqual(self.ledger.count(), before_entries)
        self.assertIsNone(load_record(self.paths))
        self.assertFalse(self.paths.birth_record.exists())

    def test_inspecting_with_a_probe_reports_ready(self) -> None:
        configure_installed_model(self)
        result = inspect(self.paths, runtime_probe=usable_probe)
        self.assertIs(result.status, ModelStatus.READY)

    def test_inspection_has_no_write_path(self) -> None:
        """The result exposes no way to create anything.

        :mod:`birth.status` exists so that a reader can depend on the birth
        subsystem without acquiring the ceremony's write path, and the ceremony
        must not have leaked back in through the result type.
        """
        result = inspect(self.paths)
        for forbidden in ("born", "record", "write_record", "birth_ceremony"):
            self.assertFalse(
                hasattr(result, forbidden), f"InspectionResult must not expose {forbidden}"
            )
        self.assertNotIn("events", result.to_dict())

    def test_status_reports_installed_weights_without_claiming_a_usable_model(self) -> None:
        """Installed and usable are different questions, and it has both keys.

        ``birth_status`` never runs the runtime, so it must not claim the model
        is usable. The weights really are installed, and saying so is not a lie.
        Reporting only one of the two would misinform in one direction or the
        other.
        """
        configure_installed_model(self)
        payload = birth_status(self.paths)
        self.assertFalse(payload["subject_exists"])
        self.assertEqual(payload["subject_id"], "")
        self.assertTrue(payload["model_installed"])
        self.assertFalse(payload["model_usable"])
        self.assertEqual(payload["model_status"], "RUNTIME_UNVERIFIED")
        self.assertEqual(payload["model"]["authorship_classification"], "INHERITED_PRETRAINED")

    def test_a_born_record_reports_the_model_as_usable(self) -> None:
        # A record only exists if a probed ceremony succeeded, so by the time one
        # is present the runtime genuinely was exercised.
        configure_installed_model(self)
        birth_ceremony(
            paths=self.paths, recorder=self.recorder, runtime_probe=usable_probe
        )
        payload = birth_status(self.paths)
        self.assertTrue(payload["model_usable"])
        self.assertEqual(payload["model_status"], "READY")

    def test_status_reports_the_subject_afterwards(self) -> None:
        configure_installed_model(self)
        birth_ceremony(
            paths=self.paths, recorder=self.recorder, runtime_probe=usable_probe
        )
        payload = birth_status(self.paths)
        self.assertTrue(payload["subject_exists"])
        self.assertEqual(payload["subject_id"], "baby-ai:subject-001")
        self.assertTrue(payload["model_installed"])
        self.assertTrue(payload["birth_event_id"])

    def test_status_detail_never_contradicts_its_own_status(self) -> None:
        """"READY" beside "the runtime was NOT checked" would be incoherent.

        The inspection on its own cannot verify a runtime, so its wording is
        careful. Once a record exists the status is READY, and the detail has to
        change with it rather than keep quoting the unprobed inspection.
        """
        # No configuration: says so, and does not claim anything about a runtime.
        unconfigured = birth_status(self.paths)
        self.assertEqual(unconfigured["model_status"], "NOT_CONFIGURED")
        self.assertIn("no foundation model is configured", unconfigured["model_detail"])

        # Weights installed but unprobed: the runtime claim is explicitly withheld.
        configure_installed_model(self)
        unprobed = birth_status(self.paths)
        self.assertEqual(unprobed["model_status"], "RUNTIME_UNVERIFIED")
        self.assertIn("NOT checked", unprobed["model_detail"])

        # A record exists, so a probed ceremony ran; the detail must follow.
        birth_ceremony(
            paths=self.paths, recorder=self.recorder, runtime_probe=usable_probe
        )
        probed = birth_status(self.paths)
        self.assertEqual(probed["model_status"], "READY")
        self.assertNotIn("NOT checked", probed["model_detail"])
        self.assertIn("verified the weights and the runtime", probed["model_detail"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
