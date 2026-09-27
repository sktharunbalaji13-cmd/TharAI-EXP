"""How the suite manufactures a *real* birth, in one place.

Milestone 003's central constraint is that a fake may never be laundered into a
real record. That makes the birth fixture unusually delicate, and it is shared by
several test modules, so it lives here rather than being copied.

The three parts, and what each one honestly can and cannot do:

``weights_config``
    A :class:`~birth.config.FoundationConfig` naming the ``llama.cpp`` runtime.
    Derived from :func:`birth.fake.fake_config` only to inherit its deliberately
    unmistakable file path and digest — the switch to a real runtime kind is the
    point, because the ceremony *refuses* a fake runtime. A ceremony test that
    configured a fake would be testing the refusal, not the birth.

``configure_installed_model``
    Writes real bytes to that path and replaces the declared digest with the
    file's actual SHA-256. Every digest, size, and integrity check in the
    resulting record is therefore genuinely exercised rather than stubbed.

``usable_probe``
    The one thing a test cannot honestly provide is a running llama.cpp
    inference binary, so availability is *injected* — as an explicit argument to
    :func:`~birth.service.birth_ceremony`, never by pointing the configuration at
    a test double. The difference matters: an injected probe leaves the sealed
    record describing a real runtime, whereas a configured fake would write a
    lie into an immutable artefact. A test that needed a fake in the record would
    be testing a different system, and should say so in its own name.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from babylab.hashing import file_sha256
from birth.config import FoundationConfig, RuntimeKind, save_config
from birth.fake import fake_config

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance for type checkers
    from tests.support import LabTestCase


def weights_config(name: str = "test-substrate") -> FoundationConfig:
    """A configuration naming a real runtime, for ceremony tests."""
    return dataclasses.replace(
        fake_config(model_name=name),
        runtime=RuntimeKind.LLAMA_CPP,
        runtime_version="b0-test",
    )


def configure_installed_model(
    case: "LabTestCase",
    content: bytes = b"weights",
    name: str = "test-substrate",
) -> FoundationConfig:
    """Configure a model and put a real file with a matching digest on disk."""
    config = weights_config(name)
    target = config.resolve_model_path(case.paths)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    config = dataclasses.replace(config, model_sha256=file_sha256(target))
    save_config(config, case.paths)
    return config


def usable_probe(config: FoundationConfig) -> tuple[bool, str, str]:
    """A runtime probe that succeeds, so the ceremony can be tested for real.

    Returns the same shape the real probe does — available, detail, backend — so
    the code under test cannot tell the difference and the test is measuring the
    ceremony rather than the plumbing.
    """
    return True, f"injected probe for {config.runtime.value}", "injected"


__all__ = ["configure_installed_model", "usable_probe", "weights_config"]
