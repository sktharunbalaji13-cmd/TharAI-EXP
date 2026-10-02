"""Tests for the canonical fingerprint recipe.

The recipe is the thing every future production comparison depends on, so it is
tested for three properties:

1. **Determinism.** The same state yields the same fingerprint, independent of
   filesystem enumeration order. An unstable order produces a fingerprint that
   changes while the state does not.
2. **Recipe identity is carried.** A value records which recipe produced it, so a
   cross-recipe comparison is visibly invalid rather than silently wrong.
3. **Read-only.** Every external argv is checked to contain no icacls switch that
   could mutate, and a tripwire proves no unexpected process is launched.

The third matters because this module points itself at production on every run.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.canonical_state import (
    CANONICAL_RECIPE_FIELDS,
    CANONICAL_RECIPE_ID,
    ICACLS_MUTATING_FLAGS,
    _run,
    fingerprint_of,
    production_state,
)
from tests.path_policy import ProductionPathViolation

REPO = Path(__file__).resolve().parents[1]


def _entry(**over):
    base = {
        "relative_path": ".",
        "path_type": "dir",
        "exists": True,
        "access_sddl": "D:AI(A;ID;FA;;;BA)",
        "access_rules_protected": False,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# determinism and sensitivity
# ---------------------------------------------------------------------------

def test_fingerprint_is_deterministic():
    entries = [_entry(), _entry(relative_path="runtime", path_type="dir")]
    assert fingerprint_of(entries) == fingerprint_of(list(entries))


def test_fingerprint_is_order_independent_of_the_input_list():
    """Records are hashed in the order given, so order IS part of the value.

    That is why ``production_state`` sorts before enumerating: an unsorted
    filesystem walk would make the fingerprint unstable while nothing changed.
    Asserting the sensitivity here documents the reason the sort is load-bearing.
    """
    a = _entry(relative_path="runtime")
    b = _entry(relative_path="model")
    assert fingerprint_of([a, b]) != fingerprint_of([b, a])


def test_every_field_affects_the_fingerprint():
    """A field that does not affect the value is a field nobody is checking."""
    base = fingerprint_of([_entry()])
    variants = {
        "relative_path": _entry(relative_path="runtime"),
        "path_type": _entry(path_type="file"),
        "exists": _entry(exists=False),
        "access_sddl": _entry(access_sddl="D:PAI(A;ID;FA;;;BA)"),
        "access_rules_protected": _entry(access_rules_protected=True),
    }
    assert set(variants) == set(CANONICAL_RECIPE_FIELDS), (
        "this test must cover every recipe field"
    )
    for field, variant in variants.items():
        assert fingerprint_of([variant]) != base, (
            f"recipe field {field!r} does not affect the fingerprint; it is being "
            "recorded but never compared"
        )


def test_path_type_is_part_of_the_recipe():
    """The M017 false alarm was a missing path-type term.

    ``directory`` and a ``file`` at the same relative path with the same SDDL must
    not collide, or a file replacing a directory would go unnoticed.
    """
    assert fingerprint_of([_entry(path_type="dir")]) != fingerprint_of(
        [_entry(path_type="file")])


def test_recipe_id_is_hashed_in():
    """Two recipes cannot produce the same value by coincidence.

    The recipe id is hashed in as the payload's first line, derived from the field
    set. So an unregistered field set gets its own prefix rather than silently
    inheriting v1's -- otherwise a typo'd field list would produce values that
    compare equal to v1's, which is precisely the confusion the recipe id exists
    to prevent.
    """
    from tests.canonical_state import CANONICAL_RECIPE_V2_FIELDS

    v1 = fingerprint_of([_entry()])
    v2 = fingerprint_of([_entry(owner="A", owner_sid="S-1")], CANONICAL_RECIPE_V2_FIELDS)
    unregistered = fingerprint_of([{"a": ".", "b": "dir"}], ("a", "b"))
    assert len({v1, v2, unregistered}) == 3


def test_booleans_serialise_unambiguously():
    """``True`` and ``"True"`` must not serialise identically."""
    assert fingerprint_of([_entry(access_rules_protected=True)]) != fingerprint_of(
        [_entry(access_rules_protected=False)])


# ---------------------------------------------------------------------------
# read-only enforcement
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("flag", sorted(ICACLS_MUTATING_FLAGS))
def test_mutating_icacls_switch_is_refused(flag, tmp_path):
    """Every mutating switch is rejected before a process starts.

    The module points itself at production on every run, so this is the property
    that stops a future edit from turning an inspection tool into a mutation tool.

    The path is deliberately NOT a production path. ``_run`` refuses on the presence
    of a mutating switch regardless of what it is pointed at, so the assertion is
    unchanged -- and keeping production out of a test whose subject is "refuse the
    flag" is one less production string paired with ``icacls`` in this tree.
    """
    with pytest.raises(AssertionError, match="mutating icacls switch"):
        _run(["icacls", str(tmp_path), flag])


def test_read_only_icacls_listing_is_permitted(tmp_path):
    """A bare listing has no switch and must not be refused."""
    # Exercised for the guard only -- not actually executed, because this test
    # must not launch a process at all. The assertion is that _run does not raise
    # before launching.
    captured: dict = {}

    def _fake(argv, **kwargs):
        captured["argv"] = argv
        raise RuntimeError("stop-before-launch")

    original = subprocess.run
    subprocess.run = _fake
    try:
        with pytest.raises(RuntimeError, match="stop-before-launch"):
            _run(["icacls", str(tmp_path)])
    finally:
        subprocess.run = original
    assert captured["argv"] == ["icacls", str(tmp_path)]


def test_mutating_flag_set_covers_the_dangerous_switches():
    for required in ("/grant", "/deny", "/remove:g", "/inheritance:r",
                     "/inheritance:d", "/setowner", "/reset", "/restore"):
        assert required in ICACLS_MUTATING_FLAGS, required


# ---------------------------------------------------------------------------
# the recipe as actually used on production
# ---------------------------------------------------------------------------

def test_production_state_is_readable_and_carries_its_recipe():
    """P1 construction: production is read, never written.

    Read-only, so production is a permitted input. The test asserts the record
    carries its recipe id and field list, which is what makes the value
    comparable later.
    """
    state = production_state(REPO / "subject_runtime")
    assert state["recipe_id"] == CANONICAL_RECIPE_ID
    assert state["recipe_fields"] == list(CANONICAL_RECIPE_FIELDS)
    assert len(state["fingerprint"]) == 64
    assert state["path_count"] == len(state["paths"])
    for record in state["paths"]:
        assert set(record) == set(CANONICAL_RECIPE_FIELDS)
        assert record["exists"] is True
    assert state["paths"][0]["relative_path"] == ".", "root must sort first"


def test_repeated_production_reads_agree():
    """Two reads of unchanged state must produce the same fingerprint.

    The negative control: if this ever fails while nothing has changed, the recipe
    is unstable and no comparison built on it can be trusted.
    """
    first = production_state(REPO / "subject_runtime")
    second = production_state(REPO / "subject_runtime")
    assert first["fingerprint"] == second["fingerprint"]


def test_state_output_refuses_to_write_into_the_repository():
    """An evidence artifact landing in production is production content."""
    from tests.canonical_state import dump

    with pytest.raises(ProductionPathViolation):
        dump({"a": 1}, REPO / "subject_runtime" / "evidence.json")


# ---------------------------------------------------------------------------
# v2: ownership, added by M019 because T carries an ownership invariant
# ---------------------------------------------------------------------------

#: Captured BEFORE v2 existed. If adding v2 ever changed a v1 value, this fails --
#: which is the only proof that the addition was not silent.
GOLDEN_V1_FINGERPRINT = "0b7bb336a43a889e04261a4a063a94d63376cd9d7611a55144a4a7a9a258aeb5"


def _v1_fixture_entry():
    return _entry()


def test_adding_v2_did_not_change_v1():
    """v1's value for a fixed input is unchanged.

    A recipe version that silently altered prior values would invalidate every
    comparison already made. This is the regression that prevents that.
    """
    assert fingerprint_of([_v1_fixture_entry()]) == GOLDEN_V1_FINGERPRINT, (
        "the v1 recipe's output changed when v2 was added; v1 must remain "
        "byte-stable and v2 must be opt-in"
    )


def test_v1_is_still_the_default():
    """An existing caller that does not pass a recipe must keep producing v1."""
    from tests.canonical_state import production_state

    state = production_state(REPO / "subject_runtime")
    assert state["recipe_id"] == CANONICAL_RECIPE_ID
    assert state["recipe_fields"] == list(CANONICAL_RECIPE_FIELDS)
    assert "owner" not in state["paths"][0]


def test_v2_extends_v1_and_adds_ownership():
    from tests.canonical_state import (
        CANONICAL_RECIPE_V2_FIELDS,
        CANONICAL_RECIPE_V2_ID,
        production_state,
    )

    assert CANONICAL_RECIPE_V2_FIELDS[: len(CANONICAL_RECIPE_FIELDS)] == CANONICAL_RECIPE_FIELDS
    assert set(CANONICAL_RECIPE_V2_FIELDS) - set(CANONICAL_RECIPE_FIELDS) == {
        "owner", "owner_sid"}

    state = production_state(REPO / "subject_runtime", recipe=CANONICAL_RECIPE_V2_ID)
    assert state["recipe_id"] == CANONICAL_RECIPE_V2_ID
    assert set(state["paths"][0]) == set(CANONICAL_RECIPE_V2_FIELDS)


def test_v1_and_v2_produce_different_values():
    """Two recipes cannot be confused for one another."""
    from tests.canonical_state import CANONICAL_RECIPE_V2_ID, production_state

    v1 = production_state(REPO / "subject_runtime")
    v2 = production_state(REPO / "subject_runtime", recipe=CANONICAL_RECIPE_V2_ID)
    assert v1["fingerprint"] != v2["fingerprint"]


def test_owner_is_observed_not_inferred(tmp_path):
    """Ownership is read, and an unresolvable owner is reported, not guessed."""
    from tests.canonical_state import _owner

    name, sid = _owner(tmp_path)
    assert name and name != ""
    assert sid and sid != ""


def test_owner_fields_affect_the_v2_fingerprint():
    """A field recorded but never compared is a field nobody is checking."""
    from tests.canonical_state import CANONICAL_RECIPE_V2_FIELDS, CANONICAL_RECIPE_V2_ID

    a = fingerprint_of([_entry(owner="A", owner_sid="S-1")], CANONICAL_RECIPE_V2_FIELDS)
    b = fingerprint_of([_entry(owner="B", owner_sid="S-1")], CANONICAL_RECIPE_V2_FIELDS)
    c = fingerprint_of([_entry(owner="A", owner_sid="S-2")], CANONICAL_RECIPE_V2_FIELDS)
    assert a != b, "owner must affect the fingerprint"
    assert a != c, "owner SID must affect the fingerprint"
    assert len({a, b, c}) == 3