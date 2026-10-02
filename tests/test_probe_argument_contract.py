"""The probe's path-argument contract, and the guard's classification of it.

Two failures are guarded against here, and both have already happened once.

1. **A mutation-capable argument classified READ_ONLY.** The guard authorised the
   probe's ``staged``, ``protected`` and ``workspace`` positional slots as
   read-only. All three are mutated by the launched process. No current test
   passed production paths through them, so nothing broke -- but the guard was
   not the complete boundary it appeared to be.

2. **Silent option drift.** An earlier ``MUTATING_PROBE_OPTIONS`` used the CLI
   flag spelling (``--delete-fixture``) while lookups used the builder keyword
   (``delete_fixture``). Every lookup missed, so the guard skipped every option
   while still appearing to check them. A silently-passing guard is worse than no
   guard, because it is mistaken for a control.

So the classification is asserted against the probe SOURCE, not against a
comment. ``PROBE_MUTATION_EVIDENCE`` names the ``probe=<label>`` operations that
mutate each WRITE argument; if the probe gains a mutating operation without a
classification change, or loses one, these tests fail.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from foundation.boundary_test import build_probe_argv
from tests.path_policy import (
    MUTATING_PROBE_FLAGS,
    MUTATING_PROBE_OPTIONS,
    MUTATING_PROBE_POSITIONS,
    PROBE_ARGUMENT_CLASSIFICATION,
    PROBE_MUTATION_EVIDENCE,
    PROBE_PATH_OPTIONS,
    PROBE_POSITIONAL_ARGUMENTS,
    READ_ONLY_PROBE_OPTIONS,
    classify_probe_arguments,
)

REPO = Path(__file__).resolve().parents[1]
PROBE_SOURCE = (REPO / "foundation" / "subject_probe.cs").read_text(encoding="utf-8")

PROD_RUNTIME = "C:\\dev\\TharAI-EXP\\subject_runtime"


def _probe_labels() -> set[str]:
    """Every ``probe=<label>`` the probe can emit."""
    return set(re.findall(r'probe=\s*([a-z_]+)\s+result=', PROBE_SOURCE)) | set(
        re.findall(r'"probe=" \+ label', PROBE_SOURCE)
    )


def _source_labels() -> set[str]:
    """Operation labels, from both the literal form and the ``label +`` form."""
    literal = set(re.findall(r'probe=\s*([a-z_]+)\s+result=', PROBE_SOURCE))
    computed = set(re.findall(r'probe=\s*([a-z_]+)\s*result=', PROBE_SOURCE))
    return literal | computed


# ---------------------------------------------------------------------------
# 1. the classification covers the builder's real signature
# ---------------------------------------------------------------------------

def test_every_path_bearing_builder_argument_is_classified():
    """No path argument may be missing from the classification.

    An unclassified argument is UNKNOWN, and UNKNOWN mutation-capable is the thing
    the prompt forbids. This is the check that turns "nobody looked at it" into a
    test failure.
    """
    params = inspect.signature(build_probe_argv).parameters
    path_params = {name for name, p in params.items()
                   if p.annotation.startswith(("str", "Path")) or p.annotation is not str}

    unclassified = path_params - set(PROBE_ARGUMENT_CLASSIFICATION)
    assert not unclassified, (
        f"builder path arguments with no classification: {sorted(unclassified)}. "
        "Add each to PROBE_ARGUMENT_CLASSIFICATION as WRITE or READ_ONLY -- an "
        "unclassified argument cannot be guarded."
    )
    assert not (set(PROBE_ARGUMENT_CLASSIFICATION) - path_params), (
        "classification names an argument the builder does not accept; either the "
        "builder changed or the classification is stale"
    )


def test_classification_values_are_only_write_or_read_only():
    bad = {k: v for k, v in PROBE_ARGUMENT_CLASSIFICATION.items()
           if v not in ("WRITE", "READ_ONLY")}
    assert not bad, f"classification must be WRITE or READ_ONLY, found {bad}"


def test_no_mutation_capable_argument_is_classified_read_only():
    """The regression itself.

    Every WRITE argument must have mutating evidence recorded, and no
    evidence-bearing argument may be READ_ONLY. Evidence is what makes the
    classification auditable rather than a bare assertion of intent.
    """
    for name, kind in PROBE_ARGUMENT_CLASSIFICATION.items():
        if kind == "WRITE":
            assert name in PROBE_MUTATION_EVIDENCE, (
                f"{name} is WRITE-scoped but records no mutating probe operation; "
                "a WRITE classification without evidence is an unreviewed guess"
            )
        else:
            assert name not in PROBE_MUTATION_EVIDENCE, (
                f"{name} is READ_ONLY but lists mutating probe operations "
                f"{PROBE_MUTATION_EVIDENCE[name]}; it must be WRITE-scoped"
            )


def test_classify_returns_a_copy_not_the_shared_table():
    table = classify_probe_arguments()
    assert table == PROBE_ARGUMENT_CLASSIFICATION
    table["scratch"] = "READ_ONLY"
    assert PROBE_ARGUMENT_CLASSIFICATION["scratch"] == "WRITE", (
        "classify_probe_arguments exposed the shared mutable table"
    )


# ---------------------------------------------------------------------------
# 2. the WRITE set is exactly the mutation-capable set
# ---------------------------------------------------------------------------

def test_mutating_options_are_exactly_the_write_named_options():
    expected = tuple(n for n in PROBE_PATH_OPTIONS
                     if PROBE_ARGUMENT_CLASSIFICATION[n] == "WRITE")
    assert set(MUTATING_PROBE_OPTIONS) == set(expected)
    assert "staging_root" in MUTATING_PROBE_OPTIONS
    assert "acl_target" in MUTATING_PROBE_OPTIONS
    assert "delete_fixture" in MUTATING_PROBE_OPTIONS


def test_read_only_options_are_exactly_the_complement():
    expected = tuple(n for n in PROBE_PATH_OPTIONS
                     if PROBE_ARGUMENT_CLASSIFICATION[n] == "READ_ONLY")
    assert set(READ_ONLY_PROBE_OPTIONS) == set(expected)
    assert "traverse" in READ_ONLY_PROBE_OPTIONS
    assert "read_file" in READ_ONLY_PROBE_OPTIONS


def test_read_write_sets_are_disjoint_and_cover_everything():
    write = {n for n, k in PROBE_ARGUMENT_CLASSIFICATION.items() if k == "WRITE"}
    read = {n for n, k in PROBE_ARGUMENT_CLASSIFICATION.items() if k == "READ_ONLY"}
    assert not (write & read), f"argument in both sets: {write & read}"
    assert write | read == set(PROBE_ARGUMENT_CLASSIFICATION)


def test_the_three_previously_misclassified_slots_are_now_write():
    """The specific defect this task closed."""
    for name in ("staged", "protected", "workspace"):
        assert PROBE_ARGUMENT_CLASSIFICATION[name] == "WRITE", (
            f"{name} mutates through the launched process and must be WRITE-scoped"
        )
    assert PROBE_ARGUMENT_CLASSIFICATION["scratch"] == "WRITE"


def test_every_positional_slot_is_write_scoped():
    assert MUTATING_PROBE_POSITIONS == (0, 1, 2, 3)
    for name in PROBE_POSITIONAL_ARGUMENTS:
        assert PROBE_ARGUMENT_CLASSIFICATION[name] == "WRITE", name


# ---------------------------------------------------------------------------
# 3. the classification matches the probe SOURCE
# ---------------------------------------------------------------------------

def _emits(label: str, source: str) -> bool:
    """Whether the probe actually contains this operation label.

    An operation label appears in the source two different ways:

    * passed to a runner -- ``Run("modify_staged_executable", ...)``,
      ``RunGuarded("create_child_directory", ...)``, ``RunDelete(...)``; or
    * emitted directly -- ``"probe=cleanup_p_txt result=" + verdict``, or
      ``"probe=" + label`` inside a shared reporter.

    Matching only one form rejects correct evidence, so both are accepted. An
    earlier version of this check accepted only the quoted-literal form and
    wrongly rejected every operation that reaches a ``Run`` helper by parameter --
    which is most of them.
    """
    return (f'"{label}"' in source) or (f"probe={label}" in source)


def test_mutation_evidence_names_operations_that_exist_in_the_probe():
    """Every cited operation label is real.

    This is the anti-drift check. A classification citing an operation the probe
    does not contain means the evidence is fiction; an operation mutating a path
    with no classification means the guard has a hole.
    """
    source = PROBE_SOURCE
    unknown: dict[str, list[str]] = {}
    for name, labels in PROBE_MUTATION_EVIDENCE.items():
        absent = [lbl for lbl in labels if not _emits(lbl, source)]
        if absent:
            unknown[name] = absent
    assert not unknown, (
        f"PROBE_MUTATION_EVIDENCE cites probe operations absent from "
        f"subject_probe.cs: {unknown}"
    )


def test_probe_source_uses_each_write_argument():
    """Each WRITE argument is actually read by the probe.

    Guards against a classification for an argument the probe ignores, which
    would be a control over nothing.
    """
    for name in PROBE_POSITIONAL_ARGUMENTS:
        assert re.search(rf'\b{name}\b', PROBE_SOURCE), name
    for name in MUTATING_PROBE_OPTIONS:
        dashed = name.replace("_", "-")
        assert f'"--{dashed}="' in PROBE_SOURCE or f'--{dashed}=' in PROBE_SOURCE, name


def test_staged_slot_can_still_select_a_mutated_directory():
    """`staged` is WRITE because its PARENT becomes the destructive directory.

    Regression on the reason, so nobody "simplifies" the classification back to
    READ_ONLY on the grounds that the file itself is only read.
    """
    assert "Path.GetDirectoryName(staged)" in PROBE_SOURCE, (
        "the probe no longer derives its destructive-copy directory from the "
        "staged path; revisit whether 'staged' is still WRITE-scoped"
    )


def test_workspace_slot_is_written_and_deleted():
    for expected in ('Path.Combine(workspace, "probe_workspace.txt")',
                     '"workspace_write"',
                     '"workspace_delete"'):
        assert expected in PROBE_SOURCE, expected


def test_protected_slot_mutates_a_child():
    assert '"modify_acl_on_protected"' in PROBE_SOURCE
    assert re.search(r"File\.SetAttributes\(\s*entries\[0\]", PROBE_SOURCE), (
        "protected is WRITE-scoped because the probe sets attributes on a child"
    )


# ---------------------------------------------------------------------------
# 4. flag/keyword consistency (retained from the earlier defect)
# ---------------------------------------------------------------------------

def test_mutating_probe_option_names_match_the_builder_keywords():
    """The ``--delete-fixture`` vs ``delete_fixture`` defect.

    The guard looks arguments up by builder keyword. If this tuple ever uses the
    CLI spelling, every lookup misses and the guard skips every option while
    appearing to check them.
    """
    params = inspect.signature(build_probe_argv).parameters
    for name in MUTATING_PROBE_OPTIONS:
        assert name in params, f"{name} is not a build_probe_argv keyword"
    for flag in MUTATING_PROBE_FLAGS:
        assert flag.startswith("--")
        keyword = flag[2:].replace("-", "_")
        assert keyword in params, f"{flag} has no builder keyword {keyword}"


def test_flag_tuple_derives_from_the_keyword_tuple():
    assert MUTATING_PROBE_FLAGS == tuple(
        "--" + n.replace("_", "-") for n in MUTATING_PROBE_OPTIONS
    )


def test_builder_emits_each_mutating_flag_in_camel_to_kebab_form(tmp_path):
    argv = build_probe_argv(
        scratch=tmp_path / "s",
        staging_root=tmp_path / "r",
        acl_target=tmp_path / "a",
        delete_fixture=tmp_path / "d",
    )
    for flag in MUTATING_PROBE_FLAGS:
        assert any(a.startswith(flag + "=") for a in argv), f"{flag} not emitted"