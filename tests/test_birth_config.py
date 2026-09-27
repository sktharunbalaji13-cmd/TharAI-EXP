"""Tests for the explicit foundation configuration and model identity.

Two properties matter most here and are checked hardest:

* an absent configuration produces a named status, never a default model;
* a weight file whose digest disagrees with the configuration is refused, even
  though it exists and has the right name.
"""

from __future__ import annotations

import dataclasses
import inspect
import tempfile
import unittest
from pathlib import Path

from babylab.errors import ConfigurationError, ValidationError
from babylab.hashing import file_sha256
from babylab.paths import ProjectPaths
from birth.config import (
    FoundationConfig,
    GenerationConfig,
    HardwareBackend,
    HardwareConfig,
    RuntimeKind,
    SamplingConfig,
    config_path,
    load_config,
    save_config,
)
from birth.fake import fake_config
from birth.identity import (
    DigestCache,
    InstallationReport,
    ModelIdentity,
    ModelStatus,
    require_usable,
    resolve_model_identity,
)


def replace(config: FoundationConfig, **overrides) -> FoundationConfig:
    """A modified copy of a frozen config, for exercising one field at a time."""
    return dataclasses.replace(config, **overrides)


class ConfigTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.paths = ProjectPaths(self.root)
        self.paths.ensure_directories()

    def install_weights(self, config: FoundationConfig, content: bytes = b"weights") -> str:
        """Put a real file where the configuration says, return its digest."""
        target = config.resolve_model_path(self.paths)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return file_sha256(target)


class TestNoImplicitModel(unittest.TestCase):
    def test_missing_config_raises_rather_than_defaulting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ProjectPaths(Path(tmp).resolve())
            paths.ensure_directories()
            with self.assertRaises(ConfigurationError) as caught:
                load_config(paths)
            self.assertIn("never chooses a model", str(caught.exception))

    def test_no_locator_or_download_in_config_source(self) -> None:
        """The absence of a default is a property of the code, so check the code."""
        import birth.config as config_module

        source = inspect.getsource(config_module)
        for forbidden in ("shutil", "urllib", "requests", "httpx", "urlopen"):
            self.assertNotIn(
                forbidden,
                source,
                f"birth.config must not contain {forbidden!r}; the laboratory "
                "never locates or fetches a model on its own",
            )

    def test_report_for_missing_config_is_not_configured(self) -> None:
        report = resolve_model_identity(None)
        self.assertIs(report.status, ModelStatus.NOT_CONFIGURED)
        self.assertIsNone(report.identity)
        self.assertFalse(report.status.is_usable)


class TestConfigValidation(ConfigTestCase):
    def test_round_trips_through_disk(self) -> None:
        config = fake_config()
        save_config(config, self.paths)
        loaded = load_config(self.paths)
        self.assertEqual(loaded.to_dict(), config.to_dict())
        self.assertEqual(loaded.configuration_hash(), config.configuration_hash())

    def test_configuration_hash_is_stable_across_equal_configs(self) -> None:
        self.assertEqual(
            fake_config().configuration_hash(), fake_config().configuration_hash()
        )

    def test_configuration_hash_changes_with_revision(self) -> None:
        base = fake_config()
        self.assertNotEqual(
            base.configuration_hash(),
            replace(base, model_revision="fake-v2").configuration_hash(),
        )

    def test_configuration_hash_changes_with_hardware(self) -> None:
        base = fake_config()
        self.assertNotEqual(
            base.configuration_hash(),
            replace(
                base, hardware=HardwareConfig(backend=HardwareBackend.CUDA, gpu_layers=99)
            ).configuration_hash(),
            "a different GPU offload setting is a different experiment",
        )

    def test_digest_must_be_64_hex(self) -> None:
        with self.assertRaises(ValidationError):
            replace(fake_config(), model_sha256="abc")

    def test_real_runtime_must_record_a_version(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            replace(fake_config(), runtime=RuntimeKind.LLAMA_CPP, runtime_version="")
        self.assertIn("reproducible", str(caught.exception))

    def test_unknown_field_is_rejected_not_ignored(self) -> None:
        payload = fake_config().to_dict()
        payload["temperature_override"] = 0.9
        with self.assertRaises(ValidationError) as caught:
            FoundationConfig.from_dict(payload)
        self.assertIn("temperature_override", str(caught.exception))

    def test_wrong_schema_is_rejected(self) -> None:
        payload = fake_config().to_dict()
        payload["schema"] = "something/else/v1"
        with self.assertRaises(ValidationError):
            FoundationConfig.from_dict(payload)

    def test_invalid_json_is_a_configuration_error(self) -> None:
        target = config_path(self.paths)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ConfigurationError):
            load_config(self.paths)

    def test_relative_model_path_resolves_under_var_models(self) -> None:
        resolved = fake_config().resolve_model_path(self.paths)
        self.assertTrue(str(resolved).startswith(str(self.paths.model_dir)))

    def test_absolute_model_path_is_used_as_given(self) -> None:
        config = replace(fake_config(), model_file="D:/elsewhere/model.gguf")
        self.assertEqual(
            config.resolve_model_path(self.paths).as_posix(), "D:/elsewhere/model.gguf"
        )


class TestIdentityResolution(ConfigTestCase):
    def test_present_weights_without_a_probe_are_unverified_not_ready(self) -> None:
        """Verified weights are not the same claim as a working runtime.

        The digest is proven here, but no process has run the model. Reporting
        READY would tell a reader the model is usable, which is precisely the
        inference this status exists to block.
        """
        config = fake_config()
        digest = self.install_weights(config)
        config = replace(config, model_sha256=digest)
        report = resolve_model_identity(config, self.paths)
        self.assertIs(report.status, ModelStatus.RUNTIME_UNVERIFIED)
        self.assertFalse(report.status.is_usable)
        self.assertEqual(report.observed_sha256, digest)
        self.assertIn("NOT checked", report.detail)

    def test_a_successful_probe_upgrades_unverified_to_ready(self) -> None:
        config = fake_config()
        digest = self.install_weights(config)
        config = replace(config, model_sha256=digest)
        report = resolve_model_identity(
            config, self.paths, runtime_probe=lambda _c: (True, "loaded", "cpu")
        )
        self.assertIs(report.status, ModelStatus.READY)
        self.assertTrue(report.status.is_usable)

    def test_absent_file_is_model_not_installed(self) -> None:
        report = resolve_model_identity(fake_config(), self.paths)
        self.assertIs(report.status, ModelStatus.MODEL_NOT_INSTALLED)
        self.assertIn("nothing will be fetched automatically", report.detail)

    def test_wrong_digest_is_integrity_mismatch(self) -> None:
        config = fake_config()
        self.install_weights(config, content=b"not the configured weights")
        report = resolve_model_identity(config, self.paths)
        self.assertIs(report.status, ModelStatus.MODEL_INTEGRITY_MISMATCH)
        self.assertFalse(report.status.is_usable)
        self.assertIn("is not the file configured", report.detail)

    def test_same_name_and_size_but_different_bytes_is_still_refused(self) -> None:
        """The case a name-and-length check would pass and a digest check does not."""
        config = fake_config()
        self.install_weights(config, content=b"aaaaaaaa")
        report = resolve_model_identity(replace(config, model_sha256="b" * 64), self.paths)
        self.assertIs(report.status, ModelStatus.MODEL_INTEGRITY_MISMATCH)

    def test_identity_authorship_is_inherited(self) -> None:
        identity = ModelIdentity.from_config(fake_config())
        self.assertEqual(identity.authorship.value, "INHERITED_PRETRAINED")

    def test_identity_round_trips_and_recomputes_authorship(self) -> None:
        identity = ModelIdentity.from_config(fake_config())
        restored = ModelIdentity.from_dict(identity.to_dict())
        self.assertEqual(restored.model_sha256, identity.model_sha256)
        self.assertEqual(restored.configuration_hash, identity.configuration_hash)

    def test_edited_authorship_field_is_caught(self) -> None:
        payload = ModelIdentity.from_config(fake_config()).to_dict()
        payload["authorship_classification"] = "BABY_AI_AUTHORED"
        with self.assertRaises(ValidationError) as caught:
            ModelIdentity.from_dict(payload)
        self.assertIn("has been edited", str(caught.exception))

    def test_stale_size_is_a_note_not_a_failure(self) -> None:
        config = fake_config()
        digest = self.install_weights(config, content=b"0123456789")
        report = resolve_model_identity(
            replace(config, model_sha256=digest, model_size_bytes=999), self.paths
        )
        self.assertIs(report.status, ModelStatus.RUNTIME_UNVERIFIED)
        self.assertTrue(any("stale" in note for note in report.notes))

    def test_runtime_probe_can_downgrade_ready(self) -> None:
        config = fake_config()
        digest = self.install_weights(config)
        config = replace(config, model_sha256=digest)
        report = resolve_model_identity(
            config,
            self.paths,
            runtime_probe=lambda _c: (False, "binary missing", "UNAVAILABLE"),
        )
        self.assertIs(report.status, ModelStatus.RUNTIME_UNAVAILABLE)
        self.assertTrue(
            report.is_installed,
            "the weights are installed even though the runtime is absent; the two "
            "facts are reported separately",
        )
        self.assertFalse(report.status.is_usable)

    def test_require_usable_raises_for_unusable(self) -> None:
        with self.assertRaises(ValidationError):
            require_usable(
                InstallationReport(status=ModelStatus.MODEL_NOT_INSTALLED, detail="absent")
            )


class TestDigestCache(ConfigTestCase):
    def test_cache_returns_the_same_answer(self) -> None:
        cache = DigestCache()
        target = self.paths.model_dir / "x.bin"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"hello")
        first = cache.digest(target)
        self.assertEqual(cache.digest(target), first)
        self.assertEqual(first, file_sha256(target))

    def test_changed_file_is_rehashed(self) -> None:
        """A cache must never turn a changed file into a stale pass."""
        cache = DigestCache()
        target = self.paths.model_dir / "x.bin"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"hello")
        before = cache.digest(target)
        target.write_bytes(b"goodbye!")
        after = cache.digest(target)
        self.assertNotEqual(before, after)
        self.assertEqual(after, file_sha256(target))


class TestSubConfigValidation(unittest.TestCase):
    def test_generation_bounds(self) -> None:
        with self.assertRaises(ValidationError):
            GenerationConfig(temperature=5.0)
        with self.assertRaises(ValidationError):
            GenerationConfig(max_tokens=0)
        with self.assertRaises(ValidationError):
            GenerationConfig(seed=-1)

    def test_sampling_bounds(self) -> None:
        with self.assertRaises(ValidationError):
            SamplingConfig(repeat_penalty=0.0)

    def test_hardware_bounds_and_backend(self) -> None:
        with self.assertRaises(ValidationError):
            HardwareConfig(gpu_memory_bytes=-1)
        with self.assertRaises(ValidationError):
            HardwareConfig.from_dict({"backend": "quantum"})
        self.assertIs(
            HardwareConfig.from_dict({"backend": "cuda"}).backend, HardwareBackend.CUDA
        )

    def test_unknown_generation_field_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            GenerationConfig.from_dict({"max_tokens": 10, "mystery": 1})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
