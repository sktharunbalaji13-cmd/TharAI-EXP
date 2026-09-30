# M013 â€” Real birth ceremony and the first real experience

## What this milestone was for

M012 ended with the laboratory having no foundation: no model, no runtime, no
verification. M013 asks the question that follows â€” **what happens when someone
tries to make a subject anyway?**

The answer this milestone builds is *nothing happens*, and the whole design
exists to make that answer difficult to route around. A birth is the point in the
system where a subject acquires an identity, a history, and a point in time. Once
that exists, every later claim about the subject rests on it. A subject born on
fabricated evidence is not a subject with a shaky history; it is a subject whose
existence is a fiction, and no later work can correct that.

So M013 implements a real ceremony, and then declines to run one.

## The two halves

**`birth/gate13.py` â€” the gate.** Sixteen prerequisites, three states.

`READY` means all sixteen carry actual evidence. `BLOCKED` means the laboratory
has not established them. `FAILED` means the laboratory established that they are
violated. The distinction is load-bearing: "we have not looked" and "we looked and
it is wrong" call for different responses, and a gate that collapses them either
lies about having checked or hides a real problem.

Four of the sixteen are about *this moment* rather than about M012's deployment â€”
the environment must be intact now, the key policy decided now, the control plane
available now, the provenance chain readable now. They are passed in rather than
measured inside the gate, which keeps `evaluate_birth_gate` a pure function of its
inputs. That is what makes a verdict auditable, and it is also why the gate
cannot act: it has no parameter through which a caller could ask it to perform
anything.

**`birth/ceremony13.py` â€” the ceremony.** Identity issuance, a creation record,
three separate lifecycle transitions, `T_birth`, one observation, one proposal, one
validated action, one experience, then a stop.

## The invariant that shapes the tests

> A real birth is the only outcome that creates a subject, and every other outcome
> leaves nothing behind.

This is tested from both directions, and both directions are needed. The failure
matrix proves each prerequisite can independently prevent a birth. The invariant
sweep then proves no failure path leaves a partial subject, a stray `T_birth`, or
an orphaned experience.

The sweep is the part that catches the bug the matrix cannot see. A gate that
refuses *correctly* is not sufficient on its own â€” a gate that refuses *after*
mutating state has still created a subject. Three real defects were found this way
during implementation, each of which is now a named regression test:

- **Compatibility judged on the wrong field.** The gate checked
  `established_by_load` and ignored `compatibility.compatibility`. A load that ran
  and *rejected* the artifact sets that flag too, so an INCOMPATIBLE deployment
  read as READY and a real birth proceeded on a model the runtime cannot load.
- **Context screening after activation.** A model context claiming to be the
  subject was refused *after* the lifecycle reached ACTIVE, leaving a record with a
  `T_birth` and no completed birth. Screening now runs before anything is created.
- **A stop that was only asserted.** `second_interaction = "REFUSED"` was a claim
  with nothing behind it. The environment is now wrapped in `SingleInteractionEnvironment`,
  which permits one action and raises `SecondInteractionRefused` on the second â€”
  and the ceremony requests that second action, so the record's `REFUSED` is backed
  by a real exception.

## Key policy: `NOT_REQUIRED`

M009 decided no subject key was needed. M013 revisits that decision rather than
inheriting it, because a subject now exists and the architecture is different.

The answer is unchanged, and the reasoning is recorded so it is not mistaken for an
unexamined default: the environment interface does not require a subject signature.
Provisioning a key would create one for appearance, and creating one would make the
subject appear `ATTACHED` before it had ever acted. Nothing is provisioned. The
subject is still refused the laboratory's control credentials, the control token,
the provenance signing authority, human-control credentials, private research keys,
and any ACL-manipulation capability.

## Replay is two questions, not one

`birth/replay13.py` separates `MODEL_OUTPUT_REPLAY` from `ENVIRONMENT_REPLAY`
because they answer different things. Does the same input yield the same proposal?
Does the same proposal against the same initial state yield the same event?

Conflating them would hide the failure that matters for a birth: a proposal that
reproduces while the event that supposedly taught the subject does not. If the
event is not reproducible, the subject's biography rests on an outcome that cannot
be re-derived.

Both report `UNVERIFIABLE` rather than `CONFIRMED` when they cannot check. A replay
that finds nothing to contradict has not established anything, and reporting
`CONFIRMED` there would manufacture assurance. The environment replay also checks
environment *identity*, not just state hash â€” two fresh deterministic environments
share an initial state hash, so the state alone cannot distinguish "the same world"
from "a different world that happens to start the same way".

## The Observatory cannot cause a birth

The Observatory shows the gate. It cannot cause one, and this is structural rather
than conventional.

The first version of the panel called `foundation.m012.verify` to obtain a ledger.
M011's import-graph test â€” which walks the AST rather than grepping, precisely so
that a module documenting the ban cannot pass by documenting it â€” caught the
regression. The fix was a read-only surface, not a suppression:
`birth/m013_status.py` reads the deployment declaration and imports nothing that can
execute.

A consequence is stated rather than worked around: **the panel can never report
READY.** The evidence READY requires is produced by the verification command, not
by a file read. Naming a model in a declaration establishes the human's choice, not
the artifact's identity â€” the latter needs the bytes hashed. So on this host the
panel reads 16 BLOCKED, and a valid declaration would lift only
`human_declaration`.

That is the safe direction to be wrong in.

## State on this host

M012 is not configured, so the gate is BLOCKED and the ceremony did not run:

| | |
|---|---|
| Gate (ceremony) | `BLOCKED` â€” 11 BLOCKED, 5 READY |
| Gate (Observatory) | `BLOCKED` â€” 16 BLOCKED |
| Outcome | `BLOCKED` |
| `birth_occurred` | `False` |
| `T_birth` | `UNAVAILABLE` |
| Subject | `NONE` |
| First experience | `NOT_PERFORMED` |
| Experience count | unchanged |

Nothing was written. Event store 20 events, chain intact, 0 appended. Provenance
ledger 14 entries, 0 appended. No `BIRTH.json`. No `model/` directory. No subject
key. The environment's state hash is unchanged.

## Tests

`tests/test_m013_birth.py` (94) â€” the gate, the failure matrix, the invariant
sweep, modes, the happy path against a synthetic gate, the interaction guard, and
adversarial cases including model identity claims and neutral-context screening.

`tests/test_m013_replay.py` (15) â€” replay separation, `UNVERIFIABLE` honesty,
environment identity vs. state hash.

`tests/test_m013_observatory.py` (25) â€” including AST tests that the Observatory
never names the verifier and the read surface never reaches the ceremony.

Portable suite: **1575 passed, 749 subtests passed.**

`tests/host_security`: 15 failed, 10 passed, 13 subtests. All failures are
`NOT_TESTABLE` â€” this session holds neither `SeImpersonatePrivilege` nor
`SeAssignPrimaryTokenPrivilege`, so the harness cannot impersonate
`BABY_AI_TEST`. Unchanged from M009 through M012.

## What a real birth would require

A human writes `human_control/experiment_config/model_deployment.json` naming a
model and a runtime with a reason. The verification command establishes digests,
compatibility by actual load, a real inference, immutability, and the
restricted-account probe. Only then would the gate read READY, and only then would
`run_ceremony` perform a birth.

The ceremony is implemented and exercised. What has not happened is a birth, and
that remains the correct state of the laboratory.

M014 is not started.
