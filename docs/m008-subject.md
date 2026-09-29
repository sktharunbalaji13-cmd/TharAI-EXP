# M008 — Subject architecture and first-experience boundary

**Status:** COMPLETE and tested. **No birth was performed. No subject is attached.**

```
FOUNDATION MODEL
    !=
SUBJECT
    !=
ENVIRONMENT
    !=
LABORATORY
```

M008 establishes the *boundary* a subject would live inside. It does not establish
consciousness, sentience, learning, memory, or autonomy — and it says so in the
telemetry, where `UNAVAILABLE` is printed beside every one of those words.

---

## 1. What a subject is, at this layer

An externally governed identity plus subject-owned state and a provenance-linked
history of experiences. It is not a model instance, not a process, not a response,
not an environment, not a key, not an account, and not a workspace.

| Component | Module | Property |
| --- | --- | --- |
| Identity | `subject/identity.py` | derived by the laboratory, immutable |
| Creation record | `subject/creation.py` | written once, frozen |
| Lifecycle | `subject/lifecycle.py` | explicit state machine, no auto-ACTIVE |
| State | `subject/state.py` | versioned, hashed, no memory fields |
| Experience | `subject/experience.py` | references, never copies |
| Provenance | `subject/provenance.py` | source by channel, origin by arrival |
| Interface | `subject/interface.py` | observe / propose / apply, nothing else |
| Harness | `subject/harness.py` | explicit single interactions, never a loop |
| Telemetry | `subject/telemetry.py` | infrastructure state, never mental state |

## 2. Identity is externally governed

`derive_identity` accepts exactly one issuer: `"LABORATORY"`. Model output,
subject output, environment output and every reserved actor name are refused with
`UNAUTHORIZED_ISSUER` — there is no special case for any of them, because a
special case is how a forged identity gets in.

The issuer string is the schema-level guard. The substantive enforcement is where
records may live: identity records are created by harness code, never written to
a subject-reachable path, and the M005 OS boundary plus key custody is what makes
"the subject rewrote its identity" a filesystem impossibility. Both layers are
documented as necessary; neither is presented as sufficient alone.

## 3. Foundation reference is a pointer, never an identity

`FoundationReference` carries the digest and describing facts of an associated
pretrained artifact, with an explicit `state`: `VERIFIED` (digest checked against
held bytes), `DECLARED` (supplied, not checked), `UNVERIFIED` (supplied by
something untrusted), or `NONE` (no associated artifact). A `VERIFIED` reference
without a 64-character digest is refused.

The subject's digest never equals the artifact's. A reference to an absent
foundation is recorded as `NONE`, never assumed. The artifact classification is
always `INHERITED_PRETRAINED` — structurally, not by declaration.

`S` references `F`. `S != F`. Pretrained knowledge never becomes experience by
being attached.

## 4. Lifecycle is process state

`UNCREATED → CREATED → ATTACHED → ACTIVE → PAUSED ↔ ACTIVE → TERMINATED`, with
`TERMINATED` terminal. Creating a subject ends in `CREATED`, not `ACTIVE`:
if existence implied activity, there would be no way to hold a subject still
while examining it, and a subject that cannot be held still cannot be studied
safely. `ACTIVE` requires an explicit laboratory operation after attachment.

`ACTIVE` means the laboratory attached this record to an interaction harness.
It says nothing about awareness, experience, intelligence, aliveness, or
consciousness. A transition requested by anything but `"LABORATORY"` is refused,
and a subject has no method and no path to request its own — there is no
`subject.request_activation` because the concept does not exist at this layer.

## 5. State contains no memory

`SubjectState` holds identity reference, lifecycle, counters, hashes. It holds
no `memories`, `skills`, `knowledge`, `personality`, `goals`, `emotions`,
`episodes`, or `beliefs` — and the absence is asserted structurally: any list,
dict, or store other than the `capabilities` map fails a test.

Unimplemented capabilities are **named absences**, not empty stores:
`semantic_memory: UNAVAILABLE — no memory system exists`. An empty list would
imply a system that exists and is merely empty; a missing field would imply one
that was forgotten. A named `UNAVAILABLE` is the only form that is honest, and
a future milestone must deliberately remove it.

## 6. Experience is a record, not a memory

An experience is one interaction that crossed the subject/environment boundary,
named entirely by references: observation id and hash, action id, consequence
digest, environment state hash and version, prior and resulting subject-state
hashes, provenance reference. References, not copies — if the experience embedded
the full observation, two copies could disagree with no structural answer about
which is authoritative.

A sequence of experiences is a history. **Reading a history is not remembering.**
M008 builds the history; retrieval, consolidation and everything that would make
it memory are separate milestones with separate reviews.

## 7. T_birth: the first-experience boundary

Before creation there is no subject and no experience count to speak of. At
creation the count is zero — asserted in the creation path itself, so a subject
that appeared with history would fail immediately. Attachment is not experience:
an attached-but-untouched subject still has zero. The first experience is produced
by the first controlled interaction, and after exactly one interaction the count
is exactly one, naming the right subject, environment, observation, action,
consequence, prior state and resulting state.

No historical experiences may exist. The pretrained model's prior knowledge does
not become experience by being attached. No backfilled childhood, no invented
memories, no synthesized history.

## 8. The subject does not write its own evidence

Outputs the subject interface emits are recorded as `SUBJECT_GENERATED` content
— and "recorded as subject-generated" is not authorship, it is classification.
Provenance is derived externally: the environment event, the interface event,
and the laboratory record together constitute evidence of what happened. A
subject saying "I did X" establishes nothing; the three records agreeing is
what establishes it.

Attribution is by **channel**, never by payload fields. A proposal carrying
`{"author": "LABORATORY"}` is still `SUBJECT_GENERATED`; a foundation completion
carrying `{"author": "BABY_AI"}` is still `INHERITED_PRETRAINED`. The function
genuinely never inspects `author` or `role` — tested with liar payloads, not
claimed in prose.

Authenticity levels are kept distinct: `OBSERVED`, `DERIVED`,
`SUBJECT_GENERATED`, `INHERITED_PRETRAINED`, `UNAVAILABLE`. Unknown information
is never zero, empty, false, or absent unless absence itself was observed.

## 9. The interface is narrow and single-shot

`observe` → `propose` → `apply`. Three separate, explicit calls. There is no
`step` that chains them, because a `step` the harness could call in a loop is an
agent loop with one line of glue — asserted by a test that the method does not
exist.

The interface exposes no filesystem, no subprocess, no keys, no network, no
environment internals. A proposal for a different environment is refused with
`BOUNDARY_VIOLATION`.

The model slot holds an optional completion function. When present, its output
is classified `INHERITED_PRETRAINED` and changes nothing about the action:
context is not memory, and a completion is not a decision. When absent — the
state of this laboratory — the interface reports `NOT_CONFIGURED` rather than
substituting anything.

## 10. Persistence without memory

Defined, not implemented. What would survive: subject identity, schema state,
experience provenance references, state hashes, lifecycle state. What the
subject would "know": nothing yet, because knowing requires a retrieval system
that does not exist. Persistence and memory are different questions, and the
persistence boundary is a schema for the first that implies nothing about the
second.

## 11. The harness is not a birth

`SubjectHarness` creates test subjects in memory and caller-supplied temporary
directories. Never in `human_control/`. Never the real keyring. Never the real
session registry. The observer therefore cannot see a harness subject as
attached — which is the entire point, because a test subject is not the Baby.

Verified after this whole suite runs: no `birth_records/BIRTH.json`, no
`BABY_AI` keyring role, observer reports `NO EXPERIMENTAL SUBJECT ATTACHED`.

The harness drives **exactly one interaction per call**. It has no `run`, `loop`,
`drive`, `step`, `daemon`, or `schedule` method — asserted. `replay_interactions`
iterates a caller-supplied plan and is excluded by name with a reason: replaying
what the caller passed is the opposite of autonomy.

## 12. Observatory: infrastructure, never mind

Shows existence, id, lifecycle, foundation and environment references, creation
record, state version and hash, experience count, latest experience, provenance
integrity, capability state. Mental vocabulary — consciousness, awareness,
intelligence, sentience, feelings, curiosity, readiness — appears only beside
`UNAVAILABLE`, because the honest behaviour is to name what is missing and say
why. Runtime telemetry (token counts, latency, CPU/GPU) is never presented as
evidence of cognition.

## 13. Security

M005 is authoritative and was re-verified intact at 11/11 after M008, with
workspaces un-denied. The subject package imports no credential material, no
network clients, and no model-runtime code; no secret-shaped attribute is ever
read; the interface holds no reference to any key. A full subject lifecycle
leaves protected evidence byte-identical — tested, not asserted.

## 14. Known limitations

* Test subjects are in-memory records. There is no persistent subject store yet;
  the persistence boundary is a schema, not an implementation.
* Replay determinism requires deterministic ids: `create_subject` accepts explicit
  `subject_id`/`environment_id` for tests. Random ids remain the default, because
  two identically configured subjects must stay distinguishable instances.
* The `issuer == "LABORATORY"` check is the schema-level guard; production
  enforcement rests on M005 storage boundaries and key custody, documented as
  required companions rather than implied.
* Experience `content_hash` excludes `resulting_subject_state_hash` (unknowable
  before the state exists) and `observation_id` (a random uniqueifier; the
  deterministic `observation_hash` is the comparison key). The full
  `experience_hash` covers everything.
* Observation ids became deterministic in M007 (`obs-{env}-{version}-{hash}`)
  because random ids poisoned cross-run replay comparison. Two views of the
  same state are the same observation.

## 15. What M008 explicitly states

M008 establishes subject architecture.
M008 does not establish consciousness.
M008 does not establish sentience.
M008 does not establish learning.
M008 does not establish memory.
M008 does not establish autonomy.
M008 does not establish developmental progress.

## 16. Acceptance criteria

All satisfied: subject entity, externally governed immutable identity, separate
foundation/environment/laboratory identities, integrity-protected creation
record, explicit lifecycle, versioned hashable state with no fake memory,
experience records with a first-experience boundary, zero at creation, exactly
one after one interaction, provenance with no self-authorship, inherited
knowledge separate, capability-limited interface, no loop/training/modification/
network/physical/curriculum/goals/motivation/personality, M005 intact,
deterministic harness, working replay with detectable divergence, corruption
detection, honest Observatory, tests passing, documentation complete.
