# M012 — Human-selected foundation model & runtime deployment / verification

**Status:** COMPLETE. `M012 = BLOCKED / NOT_CONFIGURED` — no human wrote a
deployment declaration, so there is no foundation to verify.

```
HUMAN MODEL SELECTION     NOT_DECLARED
HUMAN RUNTIME SELECTION   NOT_DECLARED
MODEL_NOT_CONFIGURED
REAL_RUNTIME              NOT_TESTABLE
REAL_INFERENCE            NOT_TESTABLE
SUBJECT_ACCOUNT_RUNTIME   NOT_TESTABLE
SUBJECT                   NONE
BIRTH                     NOT_PERFORMED
```

The milestone specification calls this a valid endpoint, and it is the only
honest one: it requires a human to have chosen a model and a runtime, and no
human has. **Nothing was downloaded, chosen, recommended, or ranked.** The
machinery is built, the gates are proven, and the laboratory is clean.

---

## 1. The decision belongs to a person

M012's whole subject is a boundary, and the specification names seven things
that are *not* model selection — verifying a configured artifact, hashing a
supplied one, testing a configured runtime, reporting compatibility, reporting
resource usage, reporting that an artifact cannot run. Every one of those is
verification, and every one is implemented here. None of them selects anything.

What M012 refuses to do: choose a model, recommend one, rank them, search a
repository, compare benchmarks, choose a quantization, choose a context size,
choose a runtime build, pick the first `.gguf`, or pick the first executable.

**The one runtime binary on this machine.** M011 found
`C:\Users\k.tharun balaji\.docker\bin\inference\llama-server.exe` (8.03 MB,
sha256 `8bb68042…`) and left it unselected. M012 preserves that, and adds a
demonstration that the report will surface it when a human names the directory
while refusing to use it:

```
runtimes reported : 1  (llama-server.exe)
promotable        : False
trying to use it  : refused — "a discovered candidate and no deployment
                    declaration exists, so nothing is selected"
```

## 2. Discovery cannot promote, structurally

> Filesystem discovery may be used ONLY to report candidates to the human.

That rule is easy to honour by accident and easy to lose the first time someone
adds a convenience. So the separation is structural, not disciplinary:

| Mechanism | Where |
| --- | --- |
| `Candidate` has **no field** that could hold a decision | `discovery.py` — no `selected`, `approved`, `chosen`, or `usable` |
| `CandidateReport.promotable` is a hard-coded `False` property with no branch | a future code path cannot make it `True` |
| `load_declaration` is the only producer of a `Deployment`, and takes a path a human wrote | no parameter a candidate could arrive through |
| `assert_not_selected` raises on any candidate the declaration does not name | the runtime guard, so a future shortcut hits a wall rather than running a binary |

Tests exercise this adversarially rather than on the happy path: a real `.gguf`
sits in the weights directory, the declaration is absent, and the answer is still
`NOT_CONFIGURED`. Then a declaration names a *different* file, and the decoy is
still refused — naming one artifact does not silently authorise another sitting
beside it. And the positive case is tested too, so the guard is a check rather
than a wall.

Candidates are also not hashed or executed during a scan. Hashing a
multi-gigabyte file would perform the verification the human's declaration is
supposed to authorise, against a file the human has not yet chosen; executing an
unselected binary to read its version is running a program nobody chose to run.

## 3. One declaration, two identities

M010 and M011 read a runtime config and a separate manifest. M012 asks a paired
question — *did this human choose this model to run on this runtime?* — which
needs both decisions in one place, from one person, at one moment. So
`model_deployment.json` carries the model, the runtime, the digest provenance,
and the human's stated reason, and the two identities stay distinct all the way
through.

`selection.declared_by` and `selection.rationale` are **both required**. A
foundation chosen without a named human and a stated reason is not a selection
this project can attribute, and the provenance record would be unusable. Also
refused: relative paths (they would make the selection depend on the cwd) and
non-64-hex digests.

The generated template writes `FILL IN: …` into every decision-bearing field, so
submitting it unfilled is `INVALID` rather than accepted with invented
provenance.

## 4. Three digest claims, and what a filename is not

```
LOCAL_COMPUTED_DIGEST   these bytes hash to X
EXTERNAL_DIGEST         a publisher said X
VERIFIED_MATCH          the two agree
```

A locally computed SHA-256 proves the first and nothing else. With no external
digest, the status is `NO_EXTERNAL_DIGEST_SUPPLIED` and the artifact is *not*
verified.

**Quantization is never read from a filename.** A filename that encodes a
different quantization than the declaration is reported as
`filename_disagreement` — a possible human error, surfaced and not resolved. A
renamed copy is still the same bytes, so a name mismatch is evidence of
something, and resolving it silently would hide a real mistake.

## 5. Compatibility: a load, and only a load

```
COMPATIBLE      the runtime loaded the artifact and said so
INCOMPATIBLE    the runtime refused it, and the refusal is quoted
UNKNOWN         the question could not be settled
```

The specification warns specifically against `file extension = compatibility`,
which is worth being blunt about: it is an easy mistake to write, because the
format check and the compatibility check look like neighbours.

* A `.gguf` extension is a naming convention and nothing more.
* A GGUF magic-number check narrows the *format* and narrows nothing about
  *compatibility*.
* Only an actual load settles it.

A load that exits 0 and prints nothing is `UNKNOWN` — silence is not an answer.
A refusal reports the runtime's own message and exit code verbatim, and is never
retried with a smaller context, a lower layer count, or a substitute file.

**`established_by_load` is the predicate that matters.** A caller-supplied process
stand-in sets `method = STUB_LOAD` and leaves the flag `False`, so a fixture that
answers every probe positively **cannot** walk the sequence into an inference.
This is verified: with a stub that returns `COMPATIBLE`, the ledger still reports
`NOT_RUN` and `real_inference` as `NOT_REACHED`. A milestone whose acceptance
criterion is "a real load" must not be satisfiable from a test.

## 6. The two identities stay separate

`model_runtime_separation` is a recorded criterion, not a comment:

```
model_sha256      c9f03f66…   (the artifact's bytes)
runtime_sha256    4a1b…        (the executable's bytes)
distinct_digests  True
```

A verified model does not verify a runtime, and a verified runtime does not
verify a model. The runtime's version is read from its own `--version` output;
when the declaration's expected version disagrees, the detail says so and the
binary's own answer is authoritative.

## 7. Freeze before, verify after

Both identities are captured *before* anything executes — `artifact_freeze` is
its own criterion. Capturing afterwards would prove only that nothing changed
after the measurement, which is the same mistake as trusting a digest from a
sidecar file. Then both are recomputed:

```
model    : ARTIFACT MUTATED  → M012 FAIL, sequence stops
runtime  : RUNTIME MUTATED   → M012 FAIL, sequence stops
```

Both are tested by appending actual bytes and watching the check fail.

## 8. What is unblocked even here

A blocked deployment is not a silent one. Eight criteria are answerable with no
model at all, and all eight are recorded:

| Criterion | State | What it establishes |
| --- | --- | --- |
| `hardware_measured` | SATISFIED | this host, measured now |
| `no_candidate_automatically_selected` | SATISFIED | discovery is inert |
| `process_identity` | SATISFIED | a live token, not a config file |
| `workspace_probe` | SATISFIED | write + readback + cleanup, no residue |
| `no_tools_no_memory_no_learning` | SATISFIED | no tools, no memory, no learning |
| `network_absent` | SATISFIED | nothing was fetched |
| `no_subject_no_birth` | SATISFIED | unconditional, holds whether blocked or not |
| `audit_complete` | SATISFIED | 16 questions, re-derivable |

Two of these were added because the tests found them missing. `network_absent`
and `no_subject_no_birth` were absent from the blocked path, and both are
guarantees that do not weaken when nothing runs — a reader who sees
`NOT_REACHED` on everything else needs to be able to see that "nothing was
fetched" and "no subject exists" are still being asserted. Omitting them would
have made a blocked milestone look like a milestone that stopped trying.

## 9. The sixteen-question audit

Every answer is read from a named field, and `AuditAnswer.source` records which.
A field that is absent or the wrong type yields `UNKNOWN` with the reason — never
a confident default. On this host: **11 derived, 5 unknown**, which is the honest
split, because five questions genuinely have no evidence to read.

`reverify` recomputes every answer and names disagreements, so a hand-edited
audit fails. Tested: doctoring one answer produces exactly one disagreement.

```
Was the model explicitly selected by the human?    NOT_CONFIGURED
Was the selection attributed to a named human?     False
What exact bytes were selected?                    UNKNOWN
Did real inference execute?                        False
Under which process identity?                      S-1-5-21-…-1001
Was network absent?                                LOCAL_ONLY_NO_FETCH
Was a subject created?                             (not asked; the summary denies it)
```

The last line matters: the summary block carries
`subject_created: false` and `birth_performed: false` as hard values, so a
reader can check the claim without inferring it from the absence of evidence.

## 10. The probe, and who ran it

The M011 probe is reused unchanged, including its `boundary_meaningful` flag.
Run as the operator, protected access succeeds — correctly, because the operator
owns the keyring and the ledger — and the verdict says so rather than implying
M005 is broken. Run as `BABY_AI_TEST`, a permitted access would be a violation.

```
protected attempted : 9    across all 6 categories
workspace           : write / readback / cleanup all True, no residue
boundary_meaningful : false (ran as the operator)
SUBJECT_ACCOUNT_RUNTIME : NOT_TESTABLE
```

All six categories are asserted present by test. M011 found that four of six had
been silently unprobed because the category map guessed entry names that do not
exist; that fix is now pinned so it cannot regress.

`SUBJECT_ACCOUNT_RUNTIME` is `NOT_TESTABLE` for the M011 reason, unchanged: this
session holds neither `SeImpersonatePrivilege` nor
`SeAssignPrimaryTokenPrivilege`; `CreateProcessWithTokenW` is refused because it
needs a stored password; `runas` is refused because it blocks an unattended
harness. No fallback to the operator token, and the account is not weakened.

## 11. Observatory

A `FOUNDATION SELECTION` section sits at the top of the foundation area,
*before* the runtime panel — because it is the decision, and everything below it
is the verification of that decision. A reader who saw "real runtime" without
having seen who chose the substrate would be reading the result of a choice they
never saw made.

```
-- FOUNDATION SELECTION ---
  model selection   NOT_DECLARED
  runtime selection NOT_DECLARED
  model sha256      UNAVAILABLE
  external digest   NOT SUPPLIED  (none)
  runtime version   NOT STATED
  selected by       UNATTRIBUTED - not a selection this project can attribute
  candidates found  0 model, 0 runtime on this machine; none selected
  real runtime      NOT_TESTABLE
  compatibility     UNKNOWN
```

The candidate line is deliberate. "Things exist on this machine which are *not*
in use" is the M012 discovery rule rendered honestly rather than hidden.

The session reads `deployment_only()` — the declaration and the candidate report,
nothing more. It does not hash the artifact, probe the runtime, load a model, or
run an inference, because a panel that performs the verification it reports is
not a panel, and a display whose refresh cost depends on hashing a
multi-gigabyte file would be the most expensive process in the laboratory. A
test walks the session's AST to confirm it reaches no execution entry point.

No psychological field exists: a test injects `intelligence`, `consciousness`,
`curiosity`, `learning_progress`, `personality`, and `readiness` into the payload
and asserts the rendered text contains none.

## 12. Failure behaviour

Every refusal ends the sequence with a recorded reason and a named criterion, and
nothing downstream is fabricated:

| Failure | Result |
| --- | --- |
| no declaration | `BLOCKED` — a correct outcome, distinct from `FAILED` |
| invalid declaration | `FAILED` with the specific field named |
| relative path, bad digest, unfilled template | `INVALID` |
| digest mismatch | `model_artifact_usable = FAILED`, nothing executed |
| missing runtime | stops after the artifact, nothing executed |
| load refusal | `INCOMPATIBLE`, the runtime's own message quoted |
| unestablished compatibility | stops; a stub cannot authorise execution |
| `UNKNOWN` admission | stops; never converted to `ADMIT` |
| artifact or runtime mutation | `FAILED`, sequence stops |

`BLOCKED` is a distinct state from `FAILED` on purpose, and a test asserts they
are not equal: a refusal is correct behaviour, not an error.

## 13. The prohibitions, as import-graph facts

Not promises — walked from the AST across every module in `foundation/`:

* no acquisition library (no `urllib`, `http`, `requests`, `socket`,
  `huggingface_hub`, `transformers`, `boto3`, `gdown`)
* no `subject` import
* no ceremony module (`birth.ceremony`, `birth.gate`, `birth.service`,
  `birth.keycustody`, `birth.birth_record`, `birth.readiness`, `birth.status`)
* no memory substrate, no learning library, no threading/scheduling/autonomy
* no `eval`/`exec`/`compile`/`__import__`

## 14. What M012 explicitly does not establish

```
M012 verifies a human-selected foundation.
M012 does not choose the foundation.
M012 does not create a subject.
M012 does not perform birth.
Foundation-model output is not subject experience.
Foundation-model execution is not learning.
```

## 15. Known limitations

* **No real deployment exists.** The criterion is `BLOCKED`, not passed.
* **Compatibility has never been established by a real load.** The mechanism is
  implemented and tested against every refusal shape, but no real
  runtime-and-GGUF pair has been put through it, because the human has not
  supplied one.
* **Restricted-account execution remains unproven end-to-end**, for the M011
  reason. Nothing runs as `BABY_AI_TEST`, because tier 3 does not exist.
* **M005's boundary is a file boundary**, verified by human cross-process
  execution. M012 did not change that, and cannot demonstrate the runtime
  process being subject to it while nothing executes as that account.
* **Admission uses file size as a memory proxy.** Coarse; a real decision would
  want the runtime's per-layer requirement, unavailable before a load.
* **M003's completion-token patterns remain incomplete** (M010, §10): the
  `eval time = X ms / N runs` form is not recognised.
* **Runtime-specific VRAM allocation is unobservable**, and left `UNAVAILABLE`
  rather than derived from a device-wide delta.

## 16. Acceptance criteria

Satisfied: human selection explicit and required; no discovered artifact
automatically selected, proven adversarially; artifact identity and SHA-256
verified; external digest status explicit; runtime identity and executable-sourced
version; model/runtime identities separate; both immutability checks; workspace
write/readback/cleanup; network absent; no acquisition; no subject; no birth; no
memory; no learning; no autonomy; provenance complete; Observatory complete;
sixteen-question audit complete and re-verifiable; failure paths tested;
documentation complete; tests pass; working tree clean.

**`NOT_TESTABLE`, not claimed:** real GGUF loaded; real inference; prompt and
output digests from a real run; token accounting from a real run; GPU and VRAM
evidence from a real run; determinism of a real run; immutability across a real
run; runtime execution under `BABY_AI_TEST`; protected-file denial to the actual
runtime process; compatibility established by a real load.

**Criterion count on this host:** 8 `SATISFIED`, 2 `BLOCKED`, 17 `NOT_REACHED`,
2 `NOT_TESTABLE`.

## 17. What a human needs to do

Write `human_control/experiment_config/model_deployment.json`:

1. the absolute path to the `.gguf` you selected
2. its SHA-256, plus a publisher digest and its source if you have one
3. the absolute path to the llama.cpp executable you built or chose
4. the version you expect it to report
5. your name and why you chose this pair

`python -c "from foundation.m012_status import deployment_only; print(deployment_only())"`
shows what the laboratory currently believes. Nothing else needs to change: the
verification machinery is already in place and will run the moment that file
exists. The laboratory will not create it for you.
