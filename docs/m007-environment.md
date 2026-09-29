# M007 — Environment and interaction substrate

**Status:** COMPLETE and tested. **No subject. No birth. No autonomy. No curriculum.**

```
FOUNDATION MODEL RUNTIME   (M006)
          +
ENVIRONMENT SUBSTRATE     (M007)
          =
NOT:  SUBJECT
```

---

## 1. Three distinctions this milestone holds

| | |
| --- | --- |
| **Environment ≠ Baby AI** | The environment is infrastructure. It belongs to no one, is created for no one, and acts for no one. |
| **Observation ≠ interpretation** | An observation reports measurements. What a measurement *means* is discovered, never supplied. |
| **Action capability ≠ intended purpose** | An entity admits `GRASP` because it is movable. That is not a statement about what it is for. |

## 2. Why the semantic line is enforced in code, not prose

The experimental premise is that useful behaviour emerges from interaction. That
premise is destroyed by an environment that supplies meaning, so the absence of
meaning is treated as a correctness property rather than a writing style.

* `Entity` has **no `name`, `purpose`, `usefulness` or `recommended_action` field** — and `__post_init__` rejects any observable property outside a fixed vocabulary.
* Operations are named for **mechanics**: `GRASP`, `RELEASE`, `MOVE`, `INSERT`, `REMOVE`, `OBSERVE`, `WAIT`.
* The operations an entity admits are **derived from its measured properties**, not declared. `ent-c3` admits `INSERT` because it has `capacity: 2`, not because it is "a container".
* `implementation_type` exists in state as laboratory bookkeeping and is **deliberately absent from observations** — how the world was built is not a property of the world.
* A test scans every **emitted string literal** in the package (docstrings excluded) for 24 banned semantic tokens, so adding a hint later takes a deliberate edit.

The same test asserts the *affordances* are a function of physics, not of history:
the same action from a restored state produces the same consequence as from a
fresh one. A world that treated a caller as more experienced would fail there.

## 3. The decision that makes replay work

**Timestamps are not in the state.**

A wall-clock reading differs between an original run and a replay by microseconds,
so a timestamp in the hashed state would make every replay diverge and divergence
would mean nothing. Time lives in events and results; state records only what is
true.

The same reasoning excludes floats. Every physical quantity is an integer in a
stated base unit (`g`, `ml`, `mm`, `ticks`, `count`), and `Entity.__post_init__`
**rejects a float** rather than rounding it — rounding hides a real imprecision
behind a stable-looking digest.

## 4. Architecture

```
environment/
  state.py          versioned state, entities, resources, canonical hashing
  identity.py       externally generated identity + configuration hash
  events.py         append-only hash-chained event stream
  action.py         action contract + four validation outcomes
  consequence.py    results, state deltas, resource changes
  observation.py    observation contract, epistemic status
  snapshot.py       integrity-verified snapshots, branches, lineage
  environment.py    the facade: create / observe / submit / snapshot / restore / replay
  deterministic.py  the laboratory fixture
  telemetry.py      Observatory integration
```

## 5. State model

`EnvironmentState` is immutable and carries `state_version`, entities, resources
and grid dimensions. Every transition produces a **new** state object; nothing is
mutated in place, so there is no code path on which a rejected action can change
anything. `state_hash` is SHA-256 over the canonical encoding, and covers
`state_version`, so two different points in history can never collide.

## 6. Observation model

Observations report: entity id, location, holder, measured properties, and the
operations those properties currently admit. Every value is a `Measurement` with
`OBSERVED` / `DERIVED` / `UNAVAILABLE`. An environment that does not measure
something reports `UNAVAILABLE` — it does not omit it silently, because "not
measured" and "does not exist" are different claims.

## 7. Action model and validation

Validation returns four **distinct** outcomes, and collapsing them is how an
environment ends up quietly coercing nonsense:

| Outcome | Meaning |
| --- | --- |
| `ACCEPTED` | Well formed and currently possible |
| `REJECTED` | Well formed; the world says no (no such target, cannot afford it, out of grid) |
| `INVALID` | Not well formed (unknown operation, missing or wrong-typed parameter) |
| `UNAVAILABLE` | Cannot be decided — a cost depends on an unmodelled resource |

`REJECTED` and `INVALID` are kept apart deliberately: one is the world refusing,
the other is a caller bug. Merging them hides bugs behind a plausible refusal.

An action that changes nothing reports `NO_EFFECT` rather than an invented
consequence.

## 8. Resource model

Resources are **environmental facts, not scores**. There is no total, no
comparison, and no notion of "more is better". `energy`, `time` and a
concurrent-holding `capacity` are tracked; a resource that is not modelled is
reported as unmodelled rather than assumed unlimited.

`ResourceAmount`, deliberately not "level" — a level implies a rank, and rank is
curriculum vocabulary. Renaming it was not cosmetic; a test bans the word.

Resources cannot go negative: validation checks affordability *before* anything
is applied. A resource the fixture does not model yields `UNAVAILABLE` rather
than a guess.

## 9. Event stream and provenance

Eleven event types: `environment_created`, `observation_generated`,
`action_requested`, `action_validated`, `action_rejected`, `action_applied`,
`state_transitioned`, `resource_changed`, `snapshot_created`, `snapshot_restored`,
`environment_fault`.

The chain is hash-linked; altering any past event breaks every event after it, and
`verify()` says so. There is no `truncate`, `delete` or `update` — asserted by a
test that the class exposes no such method.

**The actor cannot narrate itself.** An `action_requested` event records the
operation, actor, target, a parameter *count* and a parameter *digest* — never
the caller's values, and never even the caller's parameter *names*, which are
also caller-supplied text. Only the parameters the environment actually
interpreted are recorded, in `state_transitioned`. A caller submitting
`{"author": "BABY_AI", "i_wrote_this": true}` leaves no trace of it in the log.

Events carry state **hashes**, not bulk state, so the log stays a log rather than
becoming a data store. Environment facts are `SYSTEM_GENERATED`; an actor's
claim is not a category it can enter.

## 10. Snapshot, restore and branching

Restoring does **not** rewind. It starts a new branch and appends a
`snapshot_restored` event; the original events stay byte-identical. In a
developmental experiment, "replay diverged, go back and try something else" must
not destroy the evidence that the first attempt happened.

```
main ──●──●──●── S1
              ├── branch-2
              └── branch-3
```

Snapshots are integrity-verified: a snapshot whose recorded state no longer
hashes to its recorded value is corrupt, and restore refuses it rather than
loading a state that never existed. Configuration and implementation-version
mismatches are refused the same way, and every refusal is recorded as an
`environment_fault`.

## 11. Replay

`replay(actions, expected=...)` applies a recorded sequence and compares each
resulting state hash. Divergence is **reported, not hidden**: the outcome names
the first divergent action and carries both hashes.

A replay check that can only ever succeed proves nothing, so the suite contains
both a matching replay and a deliberately divergent one — the same action replayed
from a different base state — and asserts that the second is detected.

## 12. Security boundary

* The environment package imports **nothing** credential-bearing: no `provenance`, no `control`, no `babylab.identity`, no `babylab.trust`.
* No attribute named like a secret is ever read — asserted over the AST.
* No `icacls`, no `SetAcl`, no `chmod`, no `Win32Security` anywhere in the package.
* No network client is imported.
* **No coupling to the model runtime.** `Measurement` was moved from
  `babylab.runtime.contract` into a neutral `babylab/measure.py` precisely so the
  environment would not have to import the runtime package to speak about
  epistemic status. The M006 surface re-exports it unchanged.
* Mutable environment state would belong in `baby_workspace/` (the subject-facing
  sandbox), never in protected research evidence. A test exercises a full
  lifecycle and asserts protected artifacts are byte-identical afterwards.

## 13. Observatory integration

Telemetry shows environment identity, implementation version, configuration hash,
state version and hash, event count, chain integrity, active branch, latest
action and result, resources with status, and branch lineage.

It never shows that the environment thinks, wants, is curious, or is learning.
Those are claims about a mind, and no measurement here produces one. Enforced by
a test over rendered output and over the telemetry key allowlist.

## 14. Deterministic laboratory fixture

`deterministic_laboratory` v1.0.0: a 4×4 grid, three placeholder entities with
integer masses, capacities and geometry descriptors, and three resources. It is
labelled a **laboratory fixture** in its own type name and docstring, and it
exists to make replay and fault behaviour testable — not to be a world the
subject could learn from.

## 15. Fault injection

Deterministic faults covering: invalid action, missing target, malformed action,
impossible operation (out of grid), resource exhaustion, corrupted state,
corrupted snapshot, configuration mismatch, implementation-version mismatch, and
unknown snapshot. **Failures remain visible** — every fault becomes an
`environment_fault` event, and no code path recovers by inventing state.

## 16. Three defects found and fixed during this milestone

1. **A silent no-op.** `GRASP` while already holding was `ACCEPTED` and then did
   nothing, reporting the "action is currently possible" reason. That is the
   worst possible failure for a learning environment: the caller cannot
   distinguish "did nothing" from "succeeded quietly". The holding capacity is
   now a real resource consumed by `GRASP` and refunded by `RELEASE`, so the
   second grasp is `REJECTED` with a reason.
2. **`WAIT` bypassed the cost check.** It short-circuited validation before
   affordability was examined, so an exhausted clock drained to **-390**. Cost
   is now checked before any operation-specific shortcut.
3. **`replay`'s divergence detection was dead code.** It computed the action id
   from the raw request, before `submit` attaches `environment_id`, so the
   expectation lookup could never match and replay always reported success. It
   now looks the expectation up by the id `submit` actually produced.

A fourth fix is structural rather than a bug: the actor-supplied parameters were
being copied verbatim into the immutable event log, which let a caller write its
own authorship claim into an append-only record. Only a count and a digest are
recorded now.

## 17. Known limitations

* The fixture is a grid of placeholders. It is a substrate test, not a world.
* `WAIT` exists only so a caller can hold still; it has no other purpose.
* Streaming, partial observability and observation latency are **not** modelled —
  `observation_latency` is reported `UNAVAILABLE` rather than invented.
* No physical interface abstraction beyond "an entity has measurable properties
  and admits operations". Real sensors and actuators need their own safety
  boundary and their own milestone.
* Branch lineage is recorded but there is no merge operation, deliberately:
  merging histories silently is exactly what must not happen.
* Replay is deterministic because state carries no time and no floats. A future
  environment with genuine stochastic dynamics would need a seeded generator
  whose state is part of the hashed state.

## 18. Acceptance criteria

| Criterion | Status |
| --- | --- |
| Environment substrate exists | yes |
| Runs without a model | yes — no runtime import |
| Runs without a subject | yes |
| Environment identity exists | yes — derived externally |
| State / observation / action / consequence / resource / entity models | yes |
| Tool/interface model | yes — operations derived from measured properties |
| Event stream exists | yes — 11 types, hash-chained |
| Snapshot/restore exists | yes — integrity-verified |
| Branch lineage exists | yes |
| Deterministic replay exists | yes, and can detect divergence |
| Environment provenance exists | yes — externally generated |
| Security boundary verified | yes — structural absence asserted |
| Protected evidence inaccessible | yes — byte-identical after a full lifecycle |
| Protected credentials inaccessible | yes — no import, no attribute |
| Workspace boundary intact | yes — M005 unchanged |
| No network / model / subject dependency | yes |
| No memory, learning, curriculum, autonomous loop, self-modification | yes |
| No physical interfaces | yes |
| Observatory honest | yes — telemetry only |
| Fault injection works | yes |
| Tests pass | yes — 82 M007, 1103 total |
| Documentation complete | yes — this file |
| Working tree clean | yes |

## 19. Final state

```
NO BABY AI SUBJECT
NO BIRTH
NO BABY_AI KEY
NO AUTONOMOUS PROCESS
NO MEMORY
NO LEARNING LOOP
NO CURRICULUM
NO PHYSICAL ACTUATORS
```

The laboratory now has a **foundation model runtime** and an **environment
substrate**. It does not have a subject. M008 must be separately designed and
separately reviewed.
