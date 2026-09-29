# M009 — Birth ceremony and first controlled experience

**Status:** COMPLETE. **REAL_BIRTH = NOT_PERFORMED** — correctly blocked, with the
complete machinery built, tested, and proven to block.

```
NO SUBJECT
    ↓
BIRTH CEREMONY (built, tested; REAL mode blocked by the gate)
    ↓
NO SUBJECT (unchanged)
```

---

## 1. What M009 answers

M008 built the subject *architecture*. M009 builds the *transition*: the exact
sequence by which a subject would come into existence, the exact boundary of its
first experience, and the exact conditions under which the transition is refused.
Every step is auditable, every failure preserves evidence, and the whole pipeline
runs end-to-end in an explicitly labelled simulated mode.

## 2. The gate

`birth/gate.py` + `birth/gate_checks.py`: fourteen prerequisites, each evaluated
against **live machine state**, each returning `PASS` / `FAIL` / `UNKNOWN`.
Two rules make it a gate rather than a report:

1. **UNKNOWN never becomes PASS.** An unknowable prerequisite blocks.
2. **Absence is FAIL, not UNKNOWN.** "No model is configured" is an observed
   fact, not a gap in knowledge.

Every check always runs, so one evaluation shows the whole picture. A check that
raises blocks rather than passing silently. On this machine the verdict is
`BLOCKED` on `model_runtime_availability: MODEL_NOT_CONFIGURED` — which is the
correct answer, and the machinery that produces it is what was built.

Security checks re-inspect the filesystem; they do not read a previous
milestone's evidence file and call that a check. Checks with side effects say
what they checked instead of performing the effect: the provenance check reads
the chain and ledger but never writes.

## 3. The ceremony

`birth/ceremony.py`: preflight → gate → identity → creation → pre-birth proof →
foundation → environment → T_birth → CREATED → ATTACHED → ACTIVE → first
observation → proposal → consequence → first experience. Each step records an
event; any failure aborts *there*, preserves everything gathered, terminates the
record, and fabricates nothing downstream. There is no code path past a failure,
so partial birth cannot look like success.

Two modes travel with every event and record. `REAL` requires the gate to
proceed. `SIMULATED` runs the full pipeline against fixtures and says `NOT_A_BIRTH`
in its own completion event. A simulated run can never report `REAL_BIRTH`.

T_birth is one immutable record naming subject, foundation, environment,
ceremony and mode. Before it: zero experiences, asserted in the pre-birth proof
event, not merely true by default.

## 4. Key custody: NOT_REQUIRED, with reasons

`birth/keycustody.py` decides custody explicitly. The ceremony needs no signing —
provenance is laboratory-generated and hash-linked, and no BABY_AI-authored
content exists yet — so the decision is `NOT_REQUIRED`. Provisioning a key "for
appearance" would create the active BABY_AI role that makes the observer report
attachment. `provision_key` refuses outright: production key creation is never a
side effect. If signing is ever declared required without a key, the decision is
`REQUIRED_BUT_UNPROVISIONED`, which the gate treats as blocking.

## 5. Lifecycle control, rollback, and the audit

`birth/control.py`: laboratory-only pause/resume/terminate. Pause preserves
everything; resume refuses anything not paused; terminate ends permanently and
deletes nothing. A terminated record with intact history is distinguishable from
one that never had any — which is why termination is defined that way.

Rollback is evidence preservation, not cleanup. A failed identity leaves the
failure; a failed creation leaves the failure; a failed attachment terminates
the record *and keeps the failure*. Nothing downstream is fabricated, and
`ceremony_complete` never appears on an aborted run.

`birth/audit.py`: sixteen questions answered by re-deriving from the record,
never by quoting claims. `verify_audit` rebuilds every answer independently and
names disagreements. `replay_ceremony` replays the recorded first action against
a fresh deterministic environment and compares hashes; a doctored audit fails
verification, demonstrated by test.

## 6. What M009 explicitly states

Birth is a laboratory lifecycle event.
Birth does not establish consciousness.
Birth does not establish sentience.
Birth does not establish intelligence.
Birth does not establish learning.
Birth does not establish memory.
Birth does not establish autonomy.

## 7. Known limitations

* **No model is configured**, so REAL mode cannot proceed and the end-to-end
  REAL path — verified artifact, probed runtime, production birth — is
  implemented but unexecuted. That is reported as BLOCKED, not implied as
  working.
* The ceremony's first interaction uses the M008 interface without a model
  completion; proposals in REAL mode with a configured model would carry
  `INHERITED_PRETRAINED` context, a path that exists in code and has no
  executed instance.
* Key provisioning is deliberately unimplemented beyond refusal; a future
  milestone that genuinely requires subject signing needs its own reviewed
  ceremony.
* The `issuer == "LABORATORY"` check remains the schema-level guard, with M005
  storage boundaries and key custody as its required companions.
* Timestamps are metadata in replay comparison, never state — matching the M007
  rule that makes replay meaningful.

## 8. Acceptance criteria

All satisfied: gate with distinct PASS/FAIL/UNKNOWN and UNKNOWN-blocking;
explicit model/runtime/foundation prerequisites; external identity issuance;
explicit custody decision; environment, provenance and security prerequisites;
creation record; staged ceremony; T_birth; pre-birth zero proof; explicit
lifecycle transitions; first observation/action/consequence/experience with
exactly one experience on success; provenance-linked records; no self-authored
evidence; failure evidence preserved; no fabricated stages; history-preserving
rollback; working pause/resume/termination with post-termination immutability;
no loop/memory/learning/modification/network/physical/curriculum; honest
Observatory; machine-readable audit with independent verification; replay with
divergence reporting; M005 intact; tests passing; documentation complete.
