"""Regression tests for the ACL comparison gates themselves.

Every rehearsal in this investigation used a gate of the form: "compare the final
descriptor to the baseline and fail if they differ". Two of those gates were
defective, and in both cases the defect made the gate weaker than it appeared:

1. **A comparison that could not fail.** The multi-level rehearsal's per-path diff
   computed ``Compare-Object -ReferenceObject (Canon $p) -DifferenceObject (Canon $p)``
   -- the same live value on both sides. It printed "paths differing: 0" while the
   whole-tree fingerprint visibly disagreed. It compared nothing to its baseline
   because no baseline had been captured.

2. **A protected-state comparison that was vacuous.** The exact-topology rehearsal
   declared ``$protA`` and ``$protE`` and then never assigned either, so the
   inheritance-protection state contributed nothing to the verdict.

Both defects share a cause: a gate whose correctness is asserted by reading it,
rather than by deliberately breaking the thing it claims to detect. These tests
supply that break deliberately. Each constructs a comparison, corrupts exactly one
field of the final state, and requires the comparison to notice.

The ACL state itself is pure data here, so the gate logic is exercised with no
filesystem access and no privilege requirement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# A minimal, testable restatement of the comparison the rehearsals performed.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Ace:
    type: str
    sid: str
    mask: int
    inheritance: str
    propagation: str
    inherited: bool

    def canonical(self) -> str:
        # Order-independent: Windows re-canonicalises ACE order on every rewrite,
        # so a comparison on raw order would flag a correct result as a difference.
        return (f"{self.type}|{self.sid}|0x{self.mask:08x}|inh={self.inheritance}"
                f"|prop={self.propagation}|inherited={self.inherited}")


@dataclass(frozen=True)
class AclSnapshot:
    """One path's descriptor, captured at a point in time."""
    path: str
    protected: bool
    aces: tuple[Ace, ...] = field(default_factory=tuple)

    def canonical(self) -> tuple[str, ...]:
        return tuple(sorted(a.canonical() for a in self.aces))


@dataclass
class ComparisonResult:
    matches: bool
    ace_differences: list[str]
    protected_mismatch: bool


def compare(baseline: AclSnapshot, final: AclSnapshot) -> ComparisonResult:
    """Decide whether ``final`` reproduces ``baseline`` exactly.

    Three independent conditions, all required:

    * the canonical ACE multisets must be equal -- SID, type, mask, inheritance
      flags, propagation flags and inherited-vs-explicit status;
    * the ACE counts must be equal, so a duplicate that happens to sort adjacently
      cannot hide inside a multiset comparison;
    * the inheritance-protection flag must be equal.

    ``protected`` is compared as its own term rather than folded into the ACE
    multiset, because it is a property of the descriptor and not of any ACE. An
    earlier version declared the two protected-state variables and never assigned
    them, so this term silently evaluated as always-equal.
    """
    base = baseline.canonical()
    got = final.canonical()
    diffs: list[str] = []
    for line in base:
        if line not in got:
            diffs.append(f"missing: {line}")
    for line in got:
        if line not in base:
            diffs.append(f"added:   {line}")
    if len(base) != len(got):
        diffs.append(f"ace count {len(base)} -> {len(got)}")
    protected_mismatch = baseline.protected != final.protected
    return ComparisonResult(
        matches=not diffs and not protected_mismatch,
        ace_differences=diffs,
        protected_mismatch=protected_mismatch,
    )


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

SID_AU = "S-1-5-11"
SID_SYS = "S-1-5-18"
SID_BA = "S-1-5-32-544"
SID_OP = "S-1-5-21-2406520953-1060965512-844951592-1001"

OI_CI = "ContainerInherit, ObjectInherit"


def _baseline() -> AclSnapshot:
    """The production-shaped baseline: subject_runtime inheriting, 4 ACEs."""
    return AclSnapshot(
        path="subject_runtime",
        protected=False,
        aces=(
            Ace("Allow", SID_AU, 0x001301BF, OI_CI, "None", True),
            Ace("Allow", SID_SYS, 0x001F01FF, OI_CI, "None", True),
            Ace("Allow", SID_BA, 0x001F01FF, OI_CI, "None", True),
            Ace("Allow", SID_OP, 0x00120089, OI_CI, "None", True),
        ),
    )


# ---------------------------------------------------------------------------
# 1. the gate detects inheritance-protection drift
# ---------------------------------------------------------------------------

def test_identical_state_passes():
    result = compare(_baseline(), _baseline())
    assert result.matches is True
    assert result.protected_mismatch is False
    assert result.ace_differences == []


def test_gate_detects_protected_state_change():
    """The regression the vacuous `$protA`/`$protE` comparison would have missed.

    Same ACEs in every respect, only the descriptor's protection flag flipped.
    That is exactly what `/inheritance:d` does, and it is invisible to an ACE
    multiset comparison alone.
    """
    final = _baseline()
    drifted = AclSnapshot(path=final.path, protected=True, aces=final.aces)
    result = compare(_baseline(), drifted)
    assert result.matches is False, (
        "the gate accepted a descriptor whose inheritance-protection state "
        "changed; this is the vacuous-protected-state defect"
    )
    assert result.protected_mismatch is True
    assert result.ace_differences == [], (
        "the ACEs are genuinely identical, so only the protection flag differs"
    )


def test_protected_state_is_a_separate_condition_not_folded_into_aces():
    """Changing only `protected` must flip the verdict with no ACE diff at all."""
    base = _baseline()
    same_aces_other_flag = AclSnapshot(path=base.path, protected=True, aces=base.aces)
    assert base.canonical() == same_aces_other_flag.canonical()
    assert compare(base, same_aces_other_flag).matches is False


# ---------------------------------------------------------------------------
# 2. the gate detects inherited-vs-explicit drift
# ---------------------------------------------------------------------------

def test_gate_detects_inherited_to_explicit_drift():
    """The defect the exact-topology rehearsal actually exhibited.

    An ACE changes origin from inherited to explicit while keeping its SID, type,
    mask and flags. This is precisely what `/inheritance:d` did to the operator's
    `0x00120089` ACE, and it is a semantic change even though every bit of the
    access mask is identical.
    """
    base = _baseline()
    frozen_aces = tuple(
        Ace(a.type, a.sid, a.mask, a.inheritance, a.propagation, False)
        if a.sid == SID_SYS else a
        for a in base.aces
    )
    final = AclSnapshot(path=base.path, protected=base.protected, aces=frozen_aces)
    result = compare(base, final)
    assert result.matches is False, (
        "the gate accepted an ACE whose inherited/explicit status changed"
    )
    assert result.protected_mismatch is False, (
        "the protection flag did not change here, so the ACE term must be what "
        "caught it"
    )
    assert any("inherited=False" in d and "inherited=True" not in d
               for d in result.ace_differences)


# ---------------------------------------------------------------------------
# 3. the gate detects mask, principal, type and flag changes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,mutate", [
    ("mask",
     lambda a: Ace(a.type, a.sid, a.mask ^ 0x00100000, a.inheritance, a.propagation, a.inherited)),
    ("principal",
     lambda a: Ace(a.type, SID_OP if a.sid == SID_AU else a.sid, a.mask,
                   a.inheritance, a.propagation, a.inherited)),
    ("type",
     lambda a: Ace("Deny" if a.type == "Allow" else "Allow", a.sid, a.mask,
                   a.inheritance, a.propagation, a.inherited)),
    ("inheritance flags",
     lambda a: Ace(a.type, a.sid, a.mask, "None", a.propagation, a.inherited)),
    ("propagation flags",
     lambda a: Ace(a.type, a.sid, a.mask, a.inheritance, "InheritOnly", a.inherited)),
])
def test_gate_detects_each_semantic_field(label, mutate):
    base = _baseline()
    mutated = tuple(mutate(a) for a in base.aces)
    result = compare(base, AclSnapshot(path=base.path, protected=base.protected,
                                       aces=mutated))
    assert result.matches is False, f"the gate missed a change to {label}"


# ---------------------------------------------------------------------------
# 4. the gate detects loss, addition and duplication
# ---------------------------------------------------------------------------

def test_gate_detects_a_lost_ace():
    base = _baseline()
    final = AclSnapshot(path=base.path, protected=base.protected,
                        aces=base.aces[:-1])
    result = compare(base, final)
    assert result.matches is False
    assert any("missing" in d for d in result.ace_differences)


def test_gate_detects_an_added_ace():
    base = _baseline()
    extra = Ace("Allow", SID_SYS, 0x001F01FF, OI_CI, "None", False)
    result = compare(base, AclSnapshot(path=base.path, protected=base.protected,
                                       aces=base.aces + (extra,)))
    assert result.matches is False
    assert any("added" in d for d in result.ace_differences)


def test_gate_detects_a_duplicate_ace():
    """A duplicate is not caught by set semantics alone.

    ``set(baseline) == set(final)`` would hold with an extra copy present, so the
    ACE COUNT is compared as its own term.
    """
    base = _baseline()
    duplicated = base.aces + (base.aces[0],)
    result = compare(base, AclSnapshot(path=base.path, protected=base.protected,
                                       aces=duplicated))
    assert result.matches is False, (
        "the gate accepted a duplicated ACE; set comparison alone would not notice"
    )
    assert any("ace count" in d for d in result.ace_differences)


# ---------------------------------------------------------------------------
# 5. order must NOT be treated as a difference
# ---------------------------------------------------------------------------

def test_ace_order_alone_is_not_a_difference():
    """Windows re-canonicalises ACE order on every rewrite.

    A gate comparing raw order would fail a correct rollback, which is how the
    first SDDL string comparison produced a false alarm.
    """
    base = _baseline()
    reversed_state = AclSnapshot(path=base.path, protected=base.protected,
                                 aces=tuple(reversed(base.aces)))
    assert list(reversed(base.aces)) != list(base.aces), "fixture must differ in order"
    assert compare(base, reversed_state).matches is True, (
        "the gate flagged an ACE reordering as a semantic change"
    )


# ---------------------------------------------------------------------------
# 6. the gate cannot be satisfied by comparing a value to itself
# ---------------------------------------------------------------------------

def test_compare_cannot_pass_by_comparing_a_live_value_to_itself():
    """Guards the defect where a diff had no captured baseline.

    The multi-level rehearsal computed
    ``Compare-Object -ReferenceObject (Canon $p) -DifferenceObject (Canon $p)``
    and reported zero differences while the tree fingerprint disagreed. This test
    asserts that a real comparison needs a snapshot taken at a different time, and
    demonstrates what the self-comparison looked like.
    """
    base = _baseline()
    live = _baseline()
    assert compare(base, live).matches is True

    # What the defective version did: both sides read live state, so the ACEs
    # necessarily agreed even after a real change was made to the tree.
    self_compare = ComparisonResult(
        matches=not list(set(c for c in live.canonical()) ^ set(live.canonical())),
        ace_differences=[],
        protected_mismatch=live.protected != live.protected,
    )
    # A tree whose ACEs changed after the "baseline" was taken still self-compares
    # clean -- which is precisely why the defect was invisible.
    changed = AclSnapshot(path=live.path, protected=False,
                          aces=live.aces + (Ace("Allow", SID_SYS, 1, "None", "None", False),))
    defective = ComparisonResult(
        matches=not list(set(changed.canonical()) ^ set(changed.canonical())),
        ace_differences=[],
        protected_mismatch=False,
    )
    assert defective.matches is True, (
        "a self-comparison cannot detect a change; this is why the defect was "
        "invisible and why a captured baseline is required"
    )
    # The real comparison does detect it.
    assert compare(live, changed).matches is False