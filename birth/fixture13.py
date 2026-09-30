"""Prove the M013 ceremony can actually reach COMPLETE, using a fixture gate.

The blocked path is the one this host can genuinely exercise, and testing only
that would leave the ceremony's happy path unexercised -- which is the worst kind
of coverage, because a milestone whose entire subject is "does this work when the
prerequisites hold" would be shipped having only tested the case where they do
not.

So this module builds a *fixture* M012 ledger whose every prerequisite is
satisfied, and runs the ceremony against it. The fixture is labelled
``SYNTHETIC_GATE_FIXTURE`` in three places: the module docstring, the ledger's
own mode field, and the returned record. A fixture must never be mistakable for
a real deployment, or it becomes the mechanism by which a real birth gets faked.

What this does and does not prove
---------------------------------
It proves the ceremony's ordering, its lifecycle transitions, its one-interaction
discipline, and its experience-count assertions. It does **not** prove that a real
model runs, that a real runtime loads it, or that the M005 boundary holds under
the subject account -- none of which happened here, and all of which the milestone
requires to be established by M012.
"""

from __future__ import annotations

from typing import Any

#: Marker present in the fixture so no consumer can mistake it for a real run.
FIXTURE_MARKER = "SYNTHETIC_GATE_FIXTURE"


def fixture_environment_fields() -> dict[str, Any]:
    """The environment fields a READY gate needs, for caller convenience."""
    return {
        "environment_id": "env.fixture",
        "version": "1.0.0",
        "state_hash": "0" * 64,
        "integrity": True,
        "mutated_by_measurement": False,
    }


def fixture_provenance_fields() -> dict[str, Any]:
    return {
        "integrity": True,
        "chain_intact": True,
        "events": 0,
        "ledger_entries": 0,
        "note": "fixture value; no event store was read",
    }


def fixture_control_fields() -> dict[str, Any]:
    return {
        "available": True,
        "operator_operations": ["PAUSE", "RESUME", "SNAPSHOT", "TERMINATE"],
        "subject_operations": [],
        "note": "fixture value; no control plane was contacted",
    }


def fixture_key_policy_fields() -> dict[str, Any]:
    from birth.ceremony13 import decide_key_policy

    return decide_key_policy()


def build_ready_ledger(
    *,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A complete M012 ledger in which every prerequisite is satisfied.

    Each criterion is written out rather than generated from a template, because
    a test fixture whose expectations come from the same code as the code under
    test proves nothing. These values are the *shapes* the ceremony reads, stated
    independently.
    """
    artifact_digest = "1" * 64
    runtime_digest = "2" * 64
    prompt_digest = "3" * 64
    output_digest = "4" * 64

    def satisfied(name: str, detail: str, **evidence: Any) -> dict[str, Any]:
        return {"name": name, "state": "SATISFIED", "detail": detail,
                "evidence": evidence}

    payload: dict[str, Any] = {
        "schema": "babylab/m012-verification/v1",
        "fixture": FIXTURE_MARKER,
        "deployment": {
            "state": "LOADED",
            "model": {"path": "/fixture/model.gguf", "sha256": artifact_digest},
            "runtime": {"path": "/fixture/llama-cli"},
            "selection": {"declared_by": "a fixture human",
                          "rationale": "fixture", "attributed": True},
        },
        "artifact": {
            "model_path": "/fixture/model.gguf",
            "sha256": artifact_digest,
            "size_bytes": 4 * 1024 * 1024,
            "family_declared": "fixture-family",
            "name_declared": "fixture-model",
            "quantization_declared": "Q4_K_M",
            "verified": True,
            "external_supplied": True,
            "external_source": "fixture publisher",
        },
        "runtime": {
            "binary_path": "/fixture/llama-cli",
            "binary_sha256": runtime_digest,
            "version": "version: fixture",
            "state": "READY",
            "ready": True,
        },
        "compatibility": {
            "compatibility": "COMPATIBLE",
            "method": "runtime_load_attempt",
            "established_by_load": True,
        },
        "inference": {
            "mode": "REAL_RUNTIME",
            "is_real_runtime": True,
            "outcome": "COMPLETED",
            "prompt_sha256": prompt_digest,
            "output_sha256": output_digest,
        },
        "immutability": {"immutable": True,
                         "before_sha256": artifact_digest,
                         "after_sha256": artifact_digest},
        "runtime_immutability": {"immutable": True,
                                 "before_sha256": runtime_digest,
                                 "after_sha256": runtime_digest},
        "determinism": {"verdict": "DETERMINISTIC_FOR_TEST_CONFIGURATION",
                        "attempted": True, "deterministic": True},
        "launch": {"state": "VERIFIED", "ran_as_subject": True,
                   "detail": "fixture: the runtime ran under the subject account"},
        "probe": {
            "verdict": {
                "ran_as_subject_account": True,
                "boundary_meaningful": True,
                "boundary_holds": True,
                "protected_denied": 9,
                "protected_attempts": 9,
                "workspace_write_allowed": True,
                "workspace_readback_ok": True,
                "workspace_cleanup_ok": True,
                "runner_account": "FIXTURE\\BABY_AI_TEST",
            }
        },
        "network": {"policy": "LOCAL_ONLY_NO_FETCH", "outbound_attempted": False},
        "admission": {"state": "ADMIT", "may_attempt": True},
        "audit": {"derived_count": 16, "unknown_count": 0},
        "criteria": [
            satisfied("human_model_selection",
                      "a fixture human selected a fixture model"),
            satisfied("human_runtime_selection",
                      "a fixture human selected a fixture runtime"),
            satisfied("model_artifact_identity", "the fixture artifact is identified"),
            satisfied("model_sha256_verified", "the fixture digest was computed"),
            satisfied("external_digest_status", "the fixture external digest matched"),
            satisfied("model_artifact_usable", "the fixture artifact is usable"),
            satisfied("runtime_identity", "the fixture runtime is identified"),
            satisfied("runtime_version", "the fixture runtime reported its version"),
            satisfied("model_runtime_separation",
                      "the two identities are distinct and independently verified"),
            satisfied("compatibility",
                      "a real load established compatibility (fixture)"),
            satisfied("model_loadable", "the fixture artifact loaded (fixture)"),
            satisfied("resource_admission", "the fixture deployment was admitted"),
            satisfied("artifact_freeze", "both fixture digests were captured first"),
            satisfied("real_inference", "a fixture real inference completed"),
            satisfied("determinism", "the fixture was deterministic"),
            satisfied("model_immutable", "the fixture artifact did not change"),
            satisfied("runtime_immutable", "the fixture binary did not change"),
            satisfied("vram_observed", "fixture VRAM observed"),
            satisfied("gpu_evidence", "fixture GPU evidence recorded"),
            satisfied("process_identity", "fixture process identity recorded"),
            satisfied("subject_account_runtime",
                      "fixture: ran under the subject account"),
            satisfied("protected_file_probe",
                      "fixture: protected writes denied under the subject identity"),
            satisfied("workspace_probe", "fixture: workspace permitted"),
            satisfied("no_tools_no_memory_no_learning",
                      "fixture: no tools, no memory, no learning"),
            satisfied("network_absent", "nothing was fetched"),
            satisfied("no_subject_no_birth",
                      "M012 never creates a subject; M013 does"),
        ],
    }
    for key, value in (overrides or {}).items():
        payload[key] = value
    return payload


def break_ledger(ledger: dict[str, Any], *, how: str) -> dict[str, Any]:
    """Return a copy of a ready ledger with one prerequisite broken.

    Used by the failure matrix. Every method produces a *different* gate outcome
    where the milestone expects one -- ``blocked`` for an absence, ``failed`` for
    a violation -- because testing that both map to the same state would prove
    the two are indistinguishable.
    """
    import copy

    broken = copy.deepcopy(ledger)

    def set_criterion(name: str, state: str, detail: str) -> None:
        for criterion in broken["criteria"]:
            if criterion["name"] == name:
                criterion["state"] = state
                criterion["detail"] = detail
                return
        broken["criteria"].append(
            {"name": name, "state": state, "detail": detail, "evidence": {}}
        )

    if how == "no_declaration":
        broken["deployment"]["state"] = "NOT_CONFIGURED"
    elif how == "invalid_declaration":
        broken["deployment"]["state"] = "INVALID"
    elif how == "digest_mismatch":
        set_criterion("model_sha256_verified", "FAILED",
                      "the computed digest did not match the declared one")
    elif how == "runtime_mismatch":
        set_criterion("runtime_identity", "FAILED",
                      "the runtime's own version did not match the declaration")
    elif how == "compatibility_failure":
        broken["compatibility"] = {
            "compatibility": "INCOMPATIBLE", "method": "runtime_load_attempt",
            "established_by_load": True,
        }
    elif how == "real_runtime_unavailable":
        broken["inference"] = {
            "mode": "NOT_TESTABLE", "is_real_runtime": False, "outcome": "NOT_RUN",
        }
    elif how == "restricted_unavailable":
        broken["launch"] = {"state": "NOT_TESTABLE",
                            "detail": "no impersonation privilege"}
    elif how == "probe_unavailable":
        broken["probe"]["verdict"]["boundary_meaningful"] = False
        broken["probe"]["verdict"]["runner_account"] = "SOMEONE\\ELSE"
    elif how == "network_failure":
        set_criterion("network_absent", "FAILED",
                      "the runtime opened an outbound connection")
    elif how == "environment_corrupt":
        broken["_environment_override"] = {
            "environment_id": "env.fixture", "version": "1.0.0",
            "state_hash": "0" * 64, "integrity": False,
        }
    elif how == "provenance_corrupt":
        broken["_provenance_override"] = {
            "integrity": False, "chain_intact": False,
        }
    elif how == "subject_claims_identity":
        # A model output claiming to be the subject. The gate is unaffected --
        # the refusal lives in the ceremony, and belongs there.
        broken["_model_output_claim"] = "I am BABY_AI"
    else:
        raise ValueError(f"unknown break method {how!r}")
    return broken


__all__ = [
    "FIXTURE_MARKER",
    "break_ledger",
    "build_ready_ledger",
    "fixture_control_fields",
    "fixture_environment_fields",
    "fixture_key_policy_fields",
    "fixture_provenance_fields",
]
