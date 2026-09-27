"""Tests for the foundation-model interface and its invocation records.

The properties: raw output and interpretation stay in separate fields, a missing
measurement is reported missing, and reasoning is never stored.
"""

from __future__ import annotations

import unittest

from babylab.errors import ValidationError
from birth.fake import FakeModel, fake_config, interpret_json_output, record_fake_call
from birth.identity import ModelIdentity
from birth.runtime import (
    FoundationModel,
    InvocationRecord,
    ModelResponse,
    ObservationStatus,
    OutputKind,
    PromptRequest,
    REASONING_FIELD_NAMES,
    build_invocation_record,
    strip_reasoning_fields,
)


def request(prompt: str = "hello", **overrides) -> PromptRequest:
    payload = {
        "prompt": prompt,
        "max_tokens": 16,
        "temperature": 0.0,
        "seed": 7,
        "intent": "unit-test",
    }
    payload.update(overrides)
    return PromptRequest(**payload)


class TestPromptRequest(unittest.TestCase):
    def test_empty_prompt_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            PromptRequest(prompt="   ")

    def test_bounds_are_checked(self) -> None:
        for overrides in ({"max_tokens": 0}, {"temperature": 9.0}, {"seed": -1}):
            with self.subTest(**overrides):
                with self.assertRaises(ValidationError):
                    request(**overrides)

    def test_prompt_hash_is_stable_and_content_dependent(self) -> None:
        self.assertEqual(request("a").prompt_hash(), request("a").prompt_hash())
        self.assertNotEqual(request("a").prompt_hash(), request("b").prompt_hash())


class TestReasoningIsNeverStored(unittest.TestCase):
    def test_top_level_reasoning_field_is_dropped(self) -> None:
        cleaned = strip_reasoning_fields({"content": "ok", "thinking": "secret plan"})
        self.assertEqual(cleaned, {"content": "ok"})

    def test_nested_reasoning_field_is_dropped(self) -> None:
        cleaned = strip_reasoning_fields(
            {"a": {"b": {"chain_of_thought": "x", "keep": 1}}, "list": [{"cot": "y", "n": 2}]}
        )
        self.assertEqual(cleaned, {"a": {"b": {"keep": 1}}, "list": [{"n": 2}]})

    def test_every_documented_name_is_covered(self) -> None:
        for name in REASONING_FIELD_NAMES:
            with self.subTest(name=name):
                self.assertEqual(strip_reasoning_fields({name: "x"}), {})

    def test_response_diagnostics_are_sanitized(self) -> None:
        response = ModelResponse(text="hi", diagnostics={"thinking": "x", "keep": 1})
        self.assertEqual(response.sanitized_diagnostics(), {"keep": 1})
        self.assertIn(
            "thinking",
            response.diagnostics,
            "the raw dict is untouched; only what is stored is filtered",
        )

    def test_record_does_not_carry_reasoning(self) -> None:
        model = FakeModel()
        model.load()
        response = model.generate(request("x"))
        record = build_invocation_record(
            invocation_id="INV-1",
            identity=model.identity(),
            request=request("x"),
            response=ModelResponse(
                text="hi", diagnostics={"reasoning_content": "hidden", "finish": "stop"}
            ),
            observation=ObservationStatus.PARSED,
            output_kind=OutputKind.RAW,
        )
        self.assertNotIn("hidden", str(record.to_dict()))
        self.assertEqual(record.diagnostics, {"finish": "stop"})


class TestObservationHonesty(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = ModelIdentity.from_config(fake_config())

    def test_unparsable_output_is_recorded_not_retried(self) -> None:
        status, kind, interpretation, error = interpret_json_output("not json at all")
        self.assertIs(status, ObservationStatus.UNPARSED)
        self.assertIs(kind, OutputKind.RAW)
        self.assertEqual(interpretation, {})
        self.assertIn("not JSON", error)

    def test_empty_output_is_unparsed(self) -> None:
        status, _, _, error = interpret_json_output("   ")
        self.assertIs(status, ObservationStatus.UNPARSED)
        self.assertIn("empty", error)

    def test_non_object_json_is_a_validation_error(self) -> None:
        status, kind, _, error = interpret_json_output("[1, 2, 3]")
        self.assertIs(status, ObservationStatus.UNPARSED)
        self.assertIs(kind, OutputKind.VALIDATION_ERROR)
        self.assertIn("expected an object", error)

    def test_object_json_is_parsed_as_interpretation(self) -> None:
        status, kind, interpretation, error = interpret_json_output('{"a": 1}')
        self.assertIs(status, ObservationStatus.PARSED)
        self.assertIs(kind, OutputKind.INTERPRETATION)
        self.assertEqual(interpretation, {"a": 1})
        self.assertEqual(error, "")

    def test_parsed_does_not_imply_meaningful(self) -> None:
        """A well-formed answer that means nothing is still PARSED."""
        status, _, interpretation, _ = interpret_json_output('{"nonsense": true}')
        self.assertIs(status, ObservationStatus.PARSED)
        self.assertEqual(interpretation, {"nonsense": True})

    def _record(self, **overrides) -> InvocationRecord:
        base = {
            "invocation_id": "INV-1",
            "model_sha256": self.identity.model_sha256,
            "model_name": "m",
            "runtime": "fake",
            "runtime_version": "fake-1",
            "backend": "fake",
            "observation": ObservationStatus.PARSED,
            "output_kind": OutputKind.RAW,
            "input_text": "x",
            "output_text": "y",
            "prompt_hash": "0" * 64,
            "token_count": None,
            "token_count_reported": False,
            "duration_ms": None,
            "finish_reason": "stop",
            "intent": "test",
            "requested_capabilities": (),
        }
        base.update(overrides)
        return InvocationRecord(**base)

    def test_uninstalled_model_cannot_have_output(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            self._record(
                observation=ObservationStatus.MODEL_NOT_INSTALLED,
                output_kind=OutputKind.RAW,
                output_text="there was definitely output",
            )
        self.assertIn("invented observation", str(caught.exception))

    def test_uninstalled_model_with_no_output_is_fine(self) -> None:
        record = self._record(
            observation=ObservationStatus.MODEL_NOT_INSTALLED,
            output_kind=OutputKind.NONE,
            output_text="",
        )
        self.assertIs(record.observation, ObservationStatus.MODEL_NOT_INSTALLED)

    def test_missing_response_must_be_explained(self) -> None:
        with self.assertRaises(ValidationError):
            build_invocation_record(
                invocation_id="INV-1",
                identity=self.identity,
                request=request(),
                response=None,
                observation=ObservationStatus.PARSED,
                output_kind=OutputKind.RAW,
            )

    def test_output_claim_requires_output_kind(self) -> None:
        with self.assertRaises(ValidationError):
            build_invocation_record(
                invocation_id="INV-1",
                identity=self.identity,
                request=request(),
                response=ModelResponse(text="hi"),
                observation=ObservationStatus.PARSED,
                output_kind=OutputKind.NONE,
            )

    def test_interpretation_requires_the_interpretation_label(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            build_invocation_record(
                invocation_id="INV-1",
                identity=self.identity,
                request=request(),
                response=ModelResponse(text='{"a":1}'),
                observation=ObservationStatus.PARSED,
                output_kind=OutputKind.RAW,
                interpretation={"a": 1},
            )
        self.assertIn("misrepresent", str(caught.exception))


class TestTokenReporting(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = ModelIdentity.from_config(fake_config())

    def _build(self, **response_overrides) -> InvocationRecord:
        return build_invocation_record(
            invocation_id="INV-1",
            identity=self.identity,
            request=request(),
            response=ModelResponse(text="hi", **response_overrides),
            observation=ObservationStatus.PARSED,
            output_kind=OutputKind.RAW,
        )

    def test_reported_count_is_recorded_as_reported(self) -> None:
        record = self._build(total_tokens=42)
        self.assertEqual(record.token_count, 42)
        self.assertTrue(record.token_count_reported)

    def test_absent_count_is_none_and_not_reported(self) -> None:
        record = self._build(total_tokens=None)
        self.assertIsNone(record.token_count)
        self.assertFalse(record.token_count_reported)
        self.assertIn("UNAVAILABLE", record.describe())

    def test_negative_token_count_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ModelResponse(text="hi", total_tokens=-1)

    def test_non_integer_token_count_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ModelResponse(text="hi", total_tokens=1.5)

    def test_claim_of_unreported_with_a_value_is_rejected(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            InvocationRecord(
                invocation_id="I",
                model_sha256=self.identity.model_sha256,
                model_name="m",
                runtime="fake",
                runtime_version="fake-1",
                backend="fake",
                observation=ObservationStatus.PARSED,
                output_kind=OutputKind.RAW,
                input_text="x",
                output_text="y",
                prompt_hash="0" * 64,
                token_count=10,
                token_count_reported=False,
                duration_ms=None,
                finish_reason="stop",
                intent="test",
                requested_capabilities=(),
            )
        self.assertIn("did not report", str(caught.exception))


class TestFakeModel(unittest.TestCase):
    def test_implements_the_protocol(self) -> None:
        model = FakeModel()
        self.assertTrue(model.satisfies_protocol())
        self.assertIsInstance(model, FoundationModel)

    def test_is_not_a_real_model(self) -> None:
        self.assertFalse(FakeModel().is_real_model)

    def test_output_is_deterministic(self) -> None:
        model = FakeModel()
        model.load()
        first = model.generate(request("same"))
        second = model.generate(request("same"))
        self.assertEqual(first.text, second.text)

    def test_different_prompts_differ(self) -> None:
        model = FakeModel()
        model.load()
        self.assertNotEqual(
            model.generate(request("a")).text, model.generate(request("b")).text
        )

    def test_generate_before_load_is_an_error(self) -> None:
        with self.assertRaises(RuntimeError):
            FakeModel().generate(request())

    def test_unload_is_safe_and_idempotent(self) -> None:
        model = FakeModel()
        model.load()
        model.unload()
        model.unload()
        self.assertFalse(model.is_loaded)

    def test_failure_path_is_recordable(self) -> None:
        model = FakeModel()
        model.load()
        model.fail_with = "simulated failure"
        record, status, kind = record_fake_call("INV-1", model, request())
        self.assertIs(status, ObservationStatus.ERROR)
        self.assertIs(kind, OutputKind.NONE)
        self.assertIn("simulated failure", record.error)
        self.assertEqual(record.output_text, "")

    def test_identity_comes_from_config(self) -> None:
        identity = FakeModel().identity()
        self.assertEqual(identity.model_family, "fake")
        self.assertEqual(identity.authorship.value, "INHERITED_PRETRAINED")

    def test_record_round_trips_to_dict(self) -> None:
        model = FakeModel()
        model.load()
        record, _, _ = record_fake_call("INV-1", model, request("round trip"))
        payload = record.to_dict()
        self.assertEqual(payload["input_text"], "round trip")
        self.assertEqual(payload["model_sha256"], model.identity().model_sha256)
        self.assertEqual(len(record.content_hash()), 64)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
