# M010 — Foundation model acquisition, verification & runtime validation

**Status:** COMPLETE. **MODEL_NOT_CONFIGURED** — the verification machinery is
built, tested, and correctly refuses to proceed without a human-supplied model.

```
FOUNDATION MODEL     none configured
ARTIFACT             none
RUNTIME             none
REAL INFERENCE      NOT_TESTABLE
SUBJECT             NONE
BIRTH               NOT_PERFORMED
```

M001–M009 built the laboratory and, in M009, the complete birth ceremony. M009
stopped at a gate that reported `MODEL_NOT_CONFIGURED`. M010 builds the other
side of that gate: the artifact identity, runtime identity, and resource
admission the gate will eventually consume.

**Nothing was acquired.** No model was downloaded, searched for, selected, or
substituted. The milestone specification calls this an acceptable outcome and it
is the only honest one on a machine with no model on it.

---

## 1. The acquisition policy is code, not prose

The rule "the laboratory never chooses its own substrate" is the load-bearing
constraint of this entire repository, and prose decays the first time a
milestone is blocked on it. So it is code.

`foundation/acquisition.py` reports exactly three terminal states —
`MODEL_NOT_CONFIGURED`, `RUNTIME_UNAVAILABLE`, `DECLARATION_INVALID` — and there
is no fourth state in which the laboratory goes and finds a model. It exports a
twelve-entry inventory of the acquisition routes it refuses
(`FORBIDDEN_ACQUISITION_ROUTES`) and a `refuse()` that raises, so a caller
cannot discard the refusal by ignoring a return value.

Three tests close the loop. The weights boundary is filled with three real GGUF
files and the correct answer is still `MODEL_NOT_CONFIGURED`, because discovery
is not a question this package asks. A declaration naming a missing artifact
yields `ARTIFACT_MISSING` and the file does not exist afterwards. And no module
defines a function named after any forbidden route.

## 2. Three digest claims, kept apart

This is the distinction the milestone turns on:

| Claim | Who establishes it | Meaning |
| --- | --- | --- |
| `COMPUTED_LOCAL_DIGEST` | the laboratory, from the bytes | the file is still this file |
| `EXTERNALLY_SUPPLIED_DIGEST` | a human, attributed to an outside source | a publisher said so |
| `VERIFIED_MATCH` | the two agreeing | genuine external verification |

`DigestStatus` has no value that lets a self-consistent local hash be called
verified. When no external digest exists the status is
`NO_EXTERNAL_DIGEST_SUPPLIED`, and the Observatory colours it amber rather than
green because it is a weaker claim and must look weaker.

The manifest is a **separate file** from the declaration, on purpose. If they
were one file, a human who mistyped a digest would satisfy his own mistake, and
"externally verified" would mean "consistent with a value written five minutes
ago by the same person."

A defect worth recording: the manifest template writes `FILL IN: 64 hex
characters published by an external source` where the digest belongs. Accepted
naively, that makes the generated template a working forgery — submit it
unfilled and the laboratory records an "externally supplied" digest made of the
words FILL IN. The loader now rejects any value that is not 64 hex characters,
reports the rejection *and* the text as written so the human can see what was
wrong, and distinguishes an unfilled placeholder from a well-formed digest with
no source (unattributed, therefore not external provenance).

## 3. Model identity ≠ runtime identity

```
MODEL     M    a file, identified by its bytes
RUNTIME   R    an executable, identified by its path, digest, and version
```

`M ≠ R`. A verified model implies nothing about the runtime that will load it;
a working runtime implies nothing about which model it was given. The most
common way a laboratory overstates itself is reporting "the model works" when
what was demonstrated was "a binary ran a file."

`RuntimeIdentity` records implementation, version *read from the binary's own
`--version` output*, binary path, binary SHA-256, and the basis for that digest
(`UNAVAILABLE` with an explanation beats a digest obtained by hashing something
else). `FoundationStatus.real_inference_available` requires artifact verified
**and** runtime verified **and** a human declaration — the `M ≠ R` rule as a
single predicate.

## 4. Admission has three answers, and UNKNOWN is not a soft yes

`ADMIT`, `REFUSE`, `UNKNOWN`. The temptation is to read `UNKNOWN` as permission
because a load might well succeed. It is not permission: if VRAM cannot be
observed the laboratory does not estimate it, and
`AdmissionDecision.may_attempt` is `True` only for `ADMIT`.

VRAM comes from `nvidia-smi` (observed) and is never derived from artifact size.
A GGUF's file size is not its memory footprint, and its memory footprint is not
VRAM — KV cache scales with context length and layer count. Every decision
carries that statement explicitly so the absence of an inference is visible
rather than merely true.

## 5. GPU: requested is not executed

`n_gpu_layers > 0` is evidence of a configuration value and of nothing else.
`resolve_gpu_usage` requires **two** independent pieces of evidence before
reporting `CONFIRMED`: the runtime naming a non-CPU backend, *and* the runtime's
own output containing an affirmative offload line. One alone yields
`REQUESTED_NOT_CONFIRMED`.

This exposed a real bug in my own code. `validation.py` originally called
`resolve_gpu_usage` with the backend but never passed the offload evidence, so
`CONFIRMED` was unreachable — GPU use could never be reported even when the
runtime had plainly performed it. The M006 adapter was also discarding
`parsed.diagnostics`, which is the only place that evidence exists. Both fixed;
M006's 71 tests still pass.

Verified behaviour, all three through the real parse path:

| Runtime output | Reported |
| --- | --- |
| `llama backend = CUDA` + `offloaded 35/35 layers to GPU` | `CONFIRMED` |
| `llama backend = CUDA`, no offload line | `REQUESTED_NOT_CONFIRMED` |
| `llama backend = CPU`, 35 layers requested | `REQUESTED_NOT_CONFIRMED` (completed on CPU) |

## 6. Honest token accounting

Three counts, distinguished: prompt, generated, total. A count is `OBSERVED`
only when the runtime printed it; a total is `DERIVED` because it is arithmetic
on two observed values. When the runtime prints a shape M003's parser does not
recognise, the count is `UNAVAILABLE` with a reason. An estimate presented as an
observation is worse than a gap, because a gap can be noticed.

A related M003 limitation, recorded rather than papered over: the parser
recognises `"tokens_predicted": N` and `predicted timing = X ms / N tokens`, but
not the `eval time = 430.00 ms / 5 runs` form. On a real llama.cpp build that
form would report `UNAVAILABLE` for generated tokens. The honest reading is that
M003's completion-token patterns are incomplete — not that the count should be
guessed. A test asserts this behaviour explicitly so the gap stays visible.

## 7. A neutral prompt, and output that is only data

`VALIDATION_PROMPT` asks the model to count from one to five. It is checkable,
and it contains no identity, no developmental framing, and no claim about a
subject. A prompt saying "you are a newborn AI" would make the output
unfalsifiable, which is the opposite of validation. Nine banned substrings are
enforced by a function that *raises* rather than warns, because a contaminated
prompt makes the whole run uninterpretable.

Output is classified `FOUNDATION_MODEL_OUTPUT`, and `OUTPUT_IS_NOT` names the
five things it is not. The text is retained for the caller and hashed into the
ledger; the default serialisation omits it, so a reader is not invited to treat
generated prose as meaningful. A test feeds a prompt-injection string through
the runtime and asserts it is hashed, classified, and never executed.

## 8. Determinism is characterised, not asserted

The baseline is greedy (temperature 0, top_k 1, fixed seed, 32 max tokens),
chosen so a repeat *should* match and a mismatch is therefore informative. The
record says whether identical configuration produced identical output and stops
there. A differing repeat is reported as an observation about this runtime and
model pair — explicitly not evidence that either is broken. No repeat at all is
`attempted: False`, never a pass.

## 9. The boundary, at the strength it can actually be shown

`foundation/isolation.py` reports three strengths and never collapses them:

* **ENFORCED** — measured. Private keys and the control token are denied to the
  subject account by the M005 boundary, verified by human cross-process
  execution. Not re-tested here: this process runs as the laboratory user, and
  testing from inside the process whose access is in question proves nothing.
* **STRUCTURAL** — provable from the AST. The runtime path imports no network
  module, reaches no shell or detached process, and cannot reach `subject` or
  `birth` at all. `subprocess.run` is counted as a *bounded* invocation —
  argument vector, `shell=False`, stdin closed, wall-clock timeout — which is
  how one invokes a known binary, and is distinguished from a shell.
* **NOT_ESTABLISHED** — and this is the honest one. Filesystem restriction is
  `NOT_ESTABLISHED`, because narrowing the runtime to exactly the artifact,
  its binary, and a temporary workspace would need tier 3, which does not exist.
  M005 binds a file boundary to an *account*; nothing yet runs as that account.

Protected-evidence integrity is checked the only way that does not violate it:
digest every protected artefact before and after the run and compare. Attempting
a write to prove writes are blocked would itself be a write attempt.

## 10. No subject. No birth. No memory. No learning. No tools.

Not as promises in a document — as import-graph facts, checked by walking the
AST of every M010 module:

* no module imports `subject` — a successful inference has no code path to a subject
* no module imports the birth ceremony, gate, or record writer — M010 does not invoke M009
* no module imports `provenance` — the layer records its own ledger
* no memory substrate, no vector store, no retrieval, no embeddings
* no learning library, no optimiser, no adapter, no weight update
* no `eval`/`exec`/`compile`/`__import__` — output is data
* no acquisition or network library

The immutability check is the positive form: digest before, digest after, exact
equality required, and a mutation is reported as `ARTIFACT MUTATED` with a
refusal to continue.

## 11. Observatory

A `FOUNDATION RUNTIME` section sits directly beneath `BIRTH / FOUNDATION`
because the two are one story in order: this is the substrate, that is what it
would be attached to. Adjacency is what stops a reader treating "the model
works" as "the subject exists."

The section closes with `birth NOT_PERFORMED (a separate gated event)`. The
renderer has no field that could carry intelligence, consciousness, awareness,
or curiosity — a test injects all of them into the payload and asserts the
rendered text contains none.

The Observatory reads with `with_runtime_probe=False`. A view that could trigger
the execution it reports on is not a view, and polling the display would become
expensive. A test pins the call site.

The M003 vocabulary ban applies to the new section too. My first draft of the
docstring spelled out one of the banned words while explaining that the section
cannot show it; the M003 guard failed the build, correctly. The word has no
business in a read-only renderer, and the note was rewritten.

## 12. Real-versus-simulated

`InferenceKind` distinguishes `REAL_RUNTIME`, `STUB_RUNTIME`, and
`NOT_TESTABLE`. The kind is a **required argument** to `run_inference` rather
than inferred, because inferring it would mean the code guessing whether its own
runner was real. A stubbed run is labelled in the same field a real result would
use, and its detail says "must never be reported as one."

**On this machine, `REAL_RUNTIME = NOT_TESTABLE`.** No model, no binary. The
end-to-end path was exercised against a synthetic fixture with a real 4 MiB
GGUF, a real computed digest, a real binary probe, and a stubbed process
runner — which is how the GPU-evidence bug above was found — but that is
`STUB_RUNTIME` and is reported as such.

## 13. Known limitations

* **No real inference has been executed.** No model and no llama.cpp binary
  exist on this host. The path is implemented and fixture-tested; it is not
  demonstrated against a real model, and this document does not imply it is.
* **M003's completion-token patterns are incomplete** (see §6). On a real
  llama.cpp build, generated-token counts may report `UNAVAILABLE` until the
  patterns are extended.
* **Filesystem restriction is `NOT_ESTABLISHED`** pending tier 3 (§9).
* **The runtime has not been executed as the subject account.** M005 verified
  the file boundary; nothing runs under `BABY_AI_TEST`, because tier 3 does not
  exist. The denials are real, and their application to an actual runtime
  process is not yet demonstrated.
* **Admission uses file size as its memory proxy.** That is a coarse bound. A
  real admission decision would want the runtime's own per-layer requirement,
  which is unavailable before a load.
* `nvidia-smi` is the only VRAM source. Without it, admission returns `UNKNOWN`
  rather than guessing.

## 14. Acceptance criteria

Satisfied: explicit human selection; no automatic acquisition; explicit artifact
path; artifact identity and SHA-256; external digest handling with a match/mismatch
distinction; mismatch refused; manifest; runtime identity and verification;
llama.cpp execution tested; stub and real distinct; prompt and output digests;
honest token accounting; honest resource telemetry; GPU usage never falsely
claimed; VRAM status honest; determinism characterised; artifact byte-identical
across a run; no access to protected evidence, private keys, or control
credentials; no security-policy modification; no subject creation; no birth; no
network acquisition or inference; no tools; no memory; no learning; no
self-modification; honest Observatory; complete provenance; failure paths tested;
documentation complete; tests pass; working tree clean.

**Not satisfiable on this host:** real inference against a real model, and the
demonstration of the runtime executing as the subject account. Both are recorded
as `NOT_TESTABLE` with the reason.
