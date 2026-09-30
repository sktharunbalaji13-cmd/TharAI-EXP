# M014 â€” Human-selected foundation deployment and the first real birth

## What this milestone is

M012 verified a deployment a human declared. M013 built a birth ceremony and
declined to run it. M014 is the execution boundary: the one place in the system
where the chain

```
HUMAN DECLARATION â†’ ARTIFACT â†’ RUNTIME â†’ RESTRICTED ACCOUNT â†’ SECURITY PROBE
â†’ BIRTH GATE â†’ REAL BIRTH â†’ EXACTLY ONE FIRST EXPERIENCE â†’ STOP
```

is walked end to end, with a refusal available at every step.

It adds no developmental architecture. Every piece of machinery it uses already
exists: `foundation.artifact` for artifact identity, `foundation.runtime_identity`
for the binary, `foundation.restricted` for the subject account,
`foundation.m012.verify` for deployment verification, `birth.gate13` for the gate,
`birth.ceremony13` for the ceremony, `birth.replay13` for replay. M014's own
code is the ordering and the refusals.

## The laboratory never chooses

The human picks the model, the artifact, the quantization, the runtime, and the
version. M014 verifies those choices and then either births or explains why it did
not. There is no code path in `birth/m014.py` that searches for, ranks,
recommends, downloads, or substitutes an artifact â€” and `test_the_laboratory_never_chooses`
asserts that by walking the module's AST, so the claim is checked rather than
asserted in prose.

A malformed declaration is `FAILED` and is **never repaired**. A repaired
declaration reads as a human decision and is not one, which is worse than no
declaration at all.

## Result on this host: BLOCKED

Two independent reasons, and both are reported:

1. **No declaration.** `human_control/experiment_config/model_deployment.json`
   does not exist. M014 does not create it.
2. **The restricted-account boundary is NOT_TESTABLE.** This session holds
   neither `SeImpersonatePrivilege` nor `SeAssignPrimaryTokenPrivilege`, so the
   harness cannot run a process as `THARUNBALAJI-LA\BABY_AI_TEST`.

The second is reported even though the run stopped at the first, because it is a
property of the host rather than of the declaration, and it is the condition most
likely to block a birth even after a human deploys everything.

The milestone allows three legitimate paths to that condition â€” a verified real
launch, a mechanism the human establishes outside the laboratory, or it remains
NOT_TESTABLE. This host takes the third. M014 does not grant privileges to satisfy
a test, weaken ACLs, remove M005 deny ACEs, store a password, or ask for one, and
`assess_subject_account` reports `operator_execution_accepted_as_subject: False`
unconditionally so that claim cannot be quietly dropped later.

## What is verified, and how

| Stage | Evidence | Refuses |
|---|---|---|
| Declaration | file read | absent â†’ BLOCKED, malformed â†’ FAILED |
| Artifact | real SHA-256 over real bytes, GGUF magic and version from the header | missing â†’ BLOCKED, too small â†’ BLOCKED, not GGUF â†’ FAILED |
| Runtime | real digest of the binary, version read *from the executable* | missing â†’ BLOCKED, version unavailable or mismatched â†’ FAILED |
| Immutability | both digests captured before and after, required equal | any change â†’ FAILED |
| M012 | `foundation.m012.verify`, unmodified | any unmet criterion |
| Security | subject-account assessment and probe verdict | operator identity as subject â†’ BLOCKED |
| Gate | `birth.gate13`, unmodified | not READY |
| Ceremony | `birth.ceremony13`, unmodified | any incomplete step |

The GGUF header's architecture and quantization are **declared by the file**, not
verified by the laboratory, and the record says so in `identity_source`. A file
named `qwen3-8b.gguf` is not a Qwen and not 8B until something other than its
name says so.

Runtime version matching normalises formatting but not build numbers: `build 4100`
matches `4100`, and `1.0.0` does not match `1.0.1`. Requiring byte-identical
strings would make a correct declaration fail on punctuation, which would train
people to paste whatever the binary prints and stop reading it.

## Why a stubbed load can never produce a real birth

This is worth stating because it is the mechanism that makes the rest of the
guarantee hold.

`foundation.compatibility.assess_compatibility` marks any substituted process call
as `STUB_LOAD` with `established_by_load=False`, and the M013 gate refuses that
method. So a test harness cannot drive a stubbed load to a READY gate, no matter
how it is configured.

The consequence for this milestone's own testing is honest and worth stating:
**M014's real path cannot be completed in a test, and that is the guarantee
working.** What the tests do exercise is

- the declaration, artifact, and runtime stages against *real files on disk* with
  real digests, and
- the ceremony behind the gate, reached through a ledger marked
  `SYNTHETIC_M014_EVIDENCE`.

What is not exercised is the join between them, because the join requires a real
runtime that this host does not have.

## Two defects found while building this

**A declared digest that disagreed with the file read as OK.**
`verify_declared_artifact` passed the human's `sha256` to `identify` and trusted
the result. But `identify` compares the artifact against the *publisher's*
digest; it never says whether the human's stated digest matches the bytes in hand.
A declaration could therefore match the publisher while disagreeing with the file
in front of the laboratory â€” which is what happens when the wrong file is
downloaded under the right name. M014 now compares the two digests itself and
reports `declared_digest_matches`.

**A model claiming prior memory completed a birth.** M013's context screening
refused *identity* claims ("I am BABY_AI") but not *autobiographical* ones, so a
context reading "you previously experienced this room" passed straight through and
a subject was born on a fabricated pre-birth history. Screening now runs
`assert_neutral_context` over the same claim, reusing the one banned-phrase list,
so a second list of forbidden framings cannot drift away from the first.

## The birth record, and its immutability

`birth/record14.py` holds the record's path and its stable hash. It exists as a
separate module for a boundary reason: the Observatory needs both, and importing
`birth/m014` to get them would hand a read-only panel a module that can execute a
ceremony.

The hash is over sorted keys with nothing derived from the moment of hashing, so
the same birth always hashes the same. A hash that moved on reordering or on a
clock tick would report drift where none exists, and a reader would learn to
ignore it.

The record carries **no author-of-last-edit field**, so a subject's edit and an
operator's accidental edit are caught by the same check. A record that trusted such
a field would be forgeable by whoever wrote the field.

## The Observatory remains read-only

`birth/m014_status.py` reports M014 from the declaration and, if one exists, the
birth record. It imports `birth.m013_status` and `birth.record14` â€” both pure â€” and
deliberately not `birth.m014`. It verifies no artifact, invokes no runtime, launches
no process, and runs no ceremony.

Like M013's panel, it **cannot report a READY gate**, because the evidence READY
requires comes from the verification command. Naming a model in a declaration
establishes the human's choice, not the artifact's identity, so `model_identity`,
`model_digest` and `runtime_identity` read BLOCKED there even with a valid
declaration.

It also never renders `consciousness`, `awareness`, `intelligence`, `curiosity`,
`emotion`, `motivation`, or any developmental score â€” the vocabulary a birth record
is most likely to invite, precisely because it is a record of a subject's first
experience.

## What a real completion would produce

Only after a human writes the declaration **and** the restricted-account boundary
becomes verifiable:

- identity laboratory-issued; creation record laboratory-issued
- `UNCREATED â†’ CREATED â†’ ATTACHED â†’ ACTIVE`, each transition separately authorized
- `T_birth` assigned at the activation transition, never before
- personal experience count `0` before, `1` after
- one observation, one proposal, one validated action, one consequence, one
  experience causally referencing the environment event
- a second interaction requested and refused by `SingleInteractionEnvironment`
- no memory, no learning, no autonomy, no self-modification
- the birth record written once, hashed, and unchanged

## Tests

`tests/test_m014_execution.py` â€” 110 tests. All 30 required adversarial cases,
mapped to the field the laboratory actually reads, plus the declaration/artifact/
runtime stages against real files, the invariant sweep, the mode separation, and
the AST checks that the Observatory cannot execute and the laboratory cannot
choose.

Portable suite: **1685 passed, 749 subtests passed** (110 M014 + 133 M013 among
them).

`tests/host_security`: 15 failed, 10 passed, 13 subtests. All failures are
`NOT_TESTABLE` â€” this session holds neither `SeImpersonatePrivilege` nor
`SeAssignPrimaryTokenPrivilege`. Unchanged from M009 through M013. Not disguised,
and not counted as a pass.

## Explicitly

- **M014 does not choose the foundation model.**
- **M014 does not download artifacts.**
- **M014 does not establish consciousness.**
- **M014 does not infer subjective experience from language.**
- **M014 establishes personal experience only in the operational laboratory sense
  of an actual recorded environment interaction.**
- **M014 performs exactly one controlled first interaction.**
- **M014 does not implement memory.**
- **M014 does not implement learning.**
- **M014 does not implement autonomy.**
- **M014 does not implement self-modification.**

M015 is not started.
