"""Tests for the llama.cpp adapter.

The adapter is the only place in the project that runs a subprocess, so its
tests are about the two things that go wrong with subprocess adapters: reporting
a measurement that was never taken, and running a command that is not the command
the record claims was run.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from babylab.errors import ValidationError
from birth.config import HardwareBackend, HardwareConfig, RuntimeKind
from birth.llamacpp import (
    LlamaCppModel,
    build_command,
    extract_completion_text,
    gpu_availability,
    parse_llama_output,
    resolve_paths,
)
from birth.runtime import PromptRequest

#: The binary path as the configuration names it, and as pathlib renders it back.
BINARY = "C:/tools/llama.cpp/build/bin/llama-cli.exe"


def config(**overrides):
    from birth.fake import fake_config

    base = fake_config()
    for key, value in overrides.items():
        base = base.__class__(**{**base.__dict__, key: value})
    return base


def llama_config(**overrides):
    settings = {
        "model_family": "qwen",
        "model_name": "qwen2.5-0.5b-instruct",
        "model_revision": "main",
        "quantization": "Q4_K_M",
        "model_file": "qwen/qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "model_sha256": "a" * 64,
        "runtime": RuntimeKind.LLAMA_CPP,
        "runtime_version": "b4501",
        "runtime_binary": "C:/tools/llama.cpp/build/bin/llama-cli.exe",
        "context_length": 4096,
    }
    settings.update(overrides)
    return config(**settings)


class FakeCompleted:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class TestCommandIsDeterministic(unittest.TestCase):
    def _command(self, **overrides) -> list[str]:
        settings = llama_config()
        for key, value in overrides.items():
            settings = settings.__class__(**{**settings.__dict__, key: value})
        return build_command(
            settings,
            resolve_paths(settings),
            prompt="hello",
            max_tokens=64,
            temperature=0.0,
            top_p=1.0,
            top_k=40,
            repeat_penalty=1.1,
            seed=0,
            stop=("</s>",),
            n_gpu_layers=99,
            threads=8,
        )

    def test_binary_and_model_come_first_and_are_explicit(self) -> None:
        command = self._command()
        self.assertEqual(command[0], str(Path(BINARY)))
        self.assertEqual(command[1], "--model")
        self.assertIn("qwen2.5-0.5b-instruct-q4_k_m.gguf", command[2])

    def test_same_inputs_give_the_same_command(self) -> None:
        self.assertEqual(self._command(), self._command())

    def test_seed_and_temperature_are_always_explicit(self) -> None:
        """A zero passed explicitly is reproducible; a zero defaulted is not."""
        command = self._command()
        self.assertEqual(command[command.index("--temp") + 1], "0.000000")
        self.assertEqual(command[command.index("--seed") + 1], "0")
        self.assertEqual(command[command.index("--top-p") + 1], "1.000000")

    def test_prompt_is_not_echoed_back(self) -> None:
        """The text extractor relies on this, so the flag is asserted here."""
        self.assertIn("--no-display-prompt", self._command())
        self.assertIn("--no-conversation", self._command())

    def test_stop_markers_are_repeated(self) -> None:
        command = self._command()
        self.assertEqual(command.count("--stop"), 1)
        self.assertEqual(command[command.index("--stop") + 1], "</s>")

    def test_no_shell_metacharacters_are_interpreted(self) -> None:
        command = self._command()
        self.assertIn("hello", command)
        self.assertNotIn("&&", " ".join(command))


class TestPathResolutionIsExplicit(unittest.TestCase):
    def test_a_missing_binary_name_is_refused(self) -> None:
        settings = llama_config(runtime_binary="")
        with self.assertRaises(ValidationError) as caught:
            resolve_paths(settings)
        self.assertIn("runtime_binary", str(caught.exception))
        self.assertIn("will not search PATH", str(caught.exception))

    def test_model_path_comes_from_the_configuration(self) -> None:
        resolved = resolve_paths(llama_config())
        self.assertTrue(resolved.model.as_posix().endswith(
            "qwen/qwen2.5-0.5b-instruct-q4_k_m.gguf"
        ))


class TestTokenCountsAreOnlyReportedWhenPrinted(unittest.TestCase):
    def test_json_line_yields_prompt_and_completion(self) -> None:
        """Both shapes appear in one line, so both must be read.

        A parser that stops at the first match reports the prompt count and
        silently loses the completion count, which then reports a total that is
        half the real one rather than reporting nothing.
        """
        line = '{"n_prompt_tokens": 31, "tokens_predicted": 12, "content": "hi"}'
        response = parse_llama_output(line)
        self.assertEqual(response.prompt_tokens, 31)
        self.assertEqual(response.completion_tokens, 12)
        self.assertEqual(response.total_tokens, 43)

    def test_timings_line_yields_prompt_tokens(self) -> None:
        stderr = "prompt eval time = 120.50 ms / 31 tokens"
        response = parse_llama_output("hello", stderr)
        self.assertEqual(response.prompt_tokens, 31)
        self.assertIsNone(response.completion_tokens)
        self.assertEqual(response.total_tokens, 31)

    def test_predicted_timings_line_yields_completion_tokens(self) -> None:
        stderr = "predicted timings = 88.10 ms / 12 tokens"
        response = parse_llama_output("hello", stderr)
        self.assertEqual(response.completion_tokens, 12)
        self.assertIsNone(response.prompt_tokens)

    def test_no_count_printed_means_unavailable_not_zero(self) -> None:
        response = parse_llama_output("just some text")
        self.assertIsNone(response.total_tokens)
        self.assertEqual(
            response.diagnostics["token_counts_source"], "UNAVAILABLE"
        )

    def test_the_last_count_wins(self) -> None:
        stderr = "prompt eval time = 1.0 ms / 10 tokens\nprompt eval time = 1.0 ms / 20 tokens"
        self.assertEqual(parse_llama_output("x", stderr).prompt_tokens, 20)

    def test_source_is_runtime_reported_when_counted(self) -> None:
        response = parse_llama_output('{"n_prompt_tokens": 3, "tokens_predicted": 4}')
        self.assertEqual(
            response.diagnostics["token_counts_source"], "runtime-reported"
        )


class TestCompletionExtraction(unittest.TestCase):
    def test_json_content_field_wins(self) -> None:
        self.assertEqual(
            extract_completion_text('{"content": "  the answer  "}'), "the answer"
        )

    def test_alternate_json_keys(self) -> None:
        self.assertEqual(extract_completion_text('{"text": "abc"}'), "abc")

    def test_plain_multiline_output_keeps_every_line(self) -> None:
        """No prompt echo is requested, so the first line is not a prompt.

        Dropping the first line here would truncate the first line of every real
        completion, quietly, with no error anywhere.
        """
        self.assertEqual(extract_completion_text("first\nsecond\n"), "first\nsecond")

    def test_empty_output_is_empty(self) -> None:
        self.assertEqual(extract_completion_text(""), "")
        self.assertEqual(extract_completion_text("   \n "), "")

    def test_unparseable_json_falls_back_to_the_text(self) -> None:
        self.assertEqual(extract_completion_text('{"content": '), '{"content":')

    def test_blank_json_field_falls_through(self) -> None:
        self.assertEqual(extract_completion_text('{"content": "  "}'), '{"content": "  "}')


class TestBackendAndFinishAreReadNotGuessed(unittest.TestCase):
    def test_cuda_is_observed_from_output(self) -> None:
        self.assertEqual(parse_llama_output("x", "using CUDA backend").backend, "cuda")

    def test_absent_backend_defaults_to_cpu_and_says_nothing_else(self) -> None:
        self.assertEqual(parse_llama_output("x").backend, "cpu")

    def test_finish_reason_is_read_from_stderr(self) -> None:
        self.assertEqual(parse_llama_output("x", "stop").finish_reason, "stop")

    def test_no_finish_reason_is_empty_not_guessed(self) -> None:
        self.assertEqual(parse_llama_output("x").finish_reason, "")

    def test_diagnostics_are_bounded(self) -> None:
        stderr = "\n".join(f"line {i}" for i in range(500))
        response = parse_llama_output("x", stderr)
        self.assertLessEqual(len(response.diagnostics["stderr_tail"]), 40)


class TestModelLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.commands: list[list[str]] = []

    def _runner(self, command, timeout):
        self.commands.append(list(command))
        if "--version" in command:
            return FakeCompleted(stdout="version: 4501 (abcdef)")
        return FakeCompleted(
            stdout='{"n_prompt_tokens": 5, "tokens_predicted": 7, "content": "hello"}',
            stderr="llama_print_timings: done\nstop",
        )

    def _model(self, **overrides) -> LlamaCppModel:
        settings = llama_config(**overrides)
        resolved = resolve_paths(settings)
        return LlamaCppModel(
            settings, timeout_seconds=5.0, runner=self._runner
        ), resolved

    def test_load_requires_the_binary_to_exist(self) -> None:
        model, _ = self._model()
        with self.assertRaises(ValidationError) as caught:
            model.load()
        self.assertIn("does not search PATH", str(caught.exception))

    def test_probe_reports_a_missing_binary_without_raising(self) -> None:
        model, _ = self._model()

        def runner(command, timeout):
            raise OSError("no such file")

        model._runner = runner
        available, detail, backend = model.probe()
        self.assertFalse(available)
        self.assertIn("OSError", detail)
        self.assertEqual(backend, "unknown")

    def test_declared_backend_is_the_configured_one_not_a_guess(self) -> None:
        """An unconfigured backend reports ``unknown``, not ``cpu``.

        Defaulting to ``cpu`` would make a failed GPU configuration look like a
        deliberate CPU run.
        """
        model, _ = self._model()
        self.assertEqual(model.probe()[2], "unknown")
        cuda, _ = self._model(
            hardware=HardwareConfig(backend=HardwareBackend.CUDA)
        )
        self.assertEqual(cuda.probe()[2], "cuda")

    def test_probe_reports_the_binary_version_when_present(self) -> None:
        model, _ = self._model()
        available, detail, _ = model.probe()
        self.assertTrue(available)
        self.assertIn("4501", detail)

    def test_probe_never_loads_weights(self) -> None:
        """A status display must not put gigabytes into VRAM."""
        model, _ = self._model()
        model.probe()
        self.assertEqual(self.commands, [[str(Path(BINARY)), "--version"]])

    def test_generate_before_load_is_an_error(self) -> None:
        model, _ = self._model()
        with self.assertRaises(RuntimeError):
            model.generate(PromptRequest(prompt="hi"))


class TestGpuAvailabilityIsObserved(unittest.TestCase):
    def test_result_is_a_fact_or_unavailable_never_a_guess(self) -> None:
        result = gpu_availability()
        self.assertIn("available", result)
        self.assertIn("backend_observed", result)
        self.assertIn(result["backend_observed"], {"cuda", "UNAVAILABLE"})
        if not result["available"]:
            self.assertIsNone(result["gpu_memory_bytes"])
        else:
            self.assertIsInstance(result["gpu_memory_bytes"], int)

    def test_detail_always_says_where_the_answer_came_from(self) -> None:
        self.assertIn("source", gpu_availability())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
