# M006 — Foundation model and runtime

**Status:** runtime layer COMPLETE and tested. **No model is installed or configured.**
**The foundation model is not the subject.** A foundation model is a pretrained
artifact; a cognitive architecture is a design; the Baby AI subject is an
experimental developmental subject. M006 builds the first of these and explicitly
does not build the third.

---

## 1. What M006 answers

| Question | Answer |
| --- | --- |
| What model runtime is being used? | llama.cpp via the `llamacpp` adapter, behind a versioned contract. Not installed on this machine yet. |
| How is the model loaded? | `FoundationRuntime.load()` → adapter probes the binary, then verifies the artifact's SHA-256, then admits on observed resources. |
| What model artifact is loaded? | None. `NOT_CONFIGURED`. The required artifact is named in §3. |
| What exact configuration? | One explicit file. No defaults, no search, no discovery. |
| What resources does it consume? | Measured, never estimated. `OBSERVED` / `DERIVED` / `UNAVAILABLE` on every number. |
| How are inputs passed? | `InferenceRequest` — complete on its own. No conversation, no history. |
| How are outputs returned? | `InferenceResponse` with text, identity, timing, token counts and their epistemic status. |
| How are failures represented? | `RuntimeFailure` with a `RuntimeErrorKind`. Never a bare string. |
| How are events observed? | Existing `EventStore`, dotted `babylab.runtime.*` types. Observatory renders them. |
| How is output attributed? | Laboratory-generated record classified `INHERITED_PRETRAINED`. The model cannot claim authorship. |
| How is the M005 boundary enforced? | The subject interface has no filesystem, key, subprocess, or network method at all. |
| How is the model replaced? | Register a different adapter and change one config file. No laboratory code is edited. |

## 2. Architecture

```
model artifact              the weights, identified by SHA-256
      |
      v
model adapter               babylab/runtime/contract.py  (ModelAdapter protocol)
      |                     babylab/runtime/llamacpp_adapter.py
      v
inference runtime           babylab/runtime/runtime.py  (policy, limits, events)
      |                     babylab/runtime/governor.py  (admission)
      v
constrained interface       babylab/runtime/interface.py  (SubjectInterface)
```

Privilege lives **above** the adapter, never inside it. A new runtime cannot
arrive already holding access, because access is not the adapter's to hold.

| Module | Responsibility |
| --- | --- |
| `contract.py` | Versioned `ModelAdapter` protocol, request/response, `Measurement`, failure kinds |
| `hardware.py` | Observed host capability; epistemic status on every value |
| `registry.py` | Explicit adapter registration. No discovery, **no fallback** |
| `governor.py` | Admission control and resource ceilings |
| `llamacpp_adapter.py` | The llama.cpp binding (wraps the M003 invocation builder) |
| `runtime.py` | Lifecycle, policy, event emission |
| `interface.py` | The only surface a subject may call |
| `provenance.py` | Runtime output recorded as `INHERITED_PRETRAINED` |
| `telemetry.py` | Observatory runtime telemetry |
| `config.py` | One explicit configuration source |

## 3. Required model artifact

**Nothing is downloaded. The human acquires and declares the model.**

Required now:

| Field | Value |
| --- | --- |
| Runtime | llama.cpp (`llama-cli.exe`), built for Windows x64 with CUDA support |
| Runtime binary path | *not yet present on this machine* |
| Weights location | `human_control/experiment_config/weights/` |
| Format | GGUF |
| Size | must fit the admission policy (§5) |

**Observed on this machine (M006, 2026-09-27):**

```text
gpu            NVIDIA GeForce RTX 4060 Laptop GPU          [OBSERVED]
vram           8.00 GiB                                     [OBSERVED]
cpu            AMD Ryzen 7 7840HS w/ Radeon 780M Graphics  [OBSERVED]
cores          16 logical                                   [OBSERVED]
system_ram     15.29 GiB                                    [OBSERVED]
disk_free      239.02 GiB                                   [OBSERVED]
os             Windows 11 Home Single Language
driver         592.82                                       [OBSERVED]
```

### 3.1 Why a small quantized model, and how to choose one

The constraint is 8 GiB VRAM. A Q4_K_M quantization of a 7–8B class model is
roughly 4.5–5.5 GiB of weights, which leaves headroom for KV cache and context
inside 8 GiB. Selection criteria, in priority order — deliberately **not**
benchmark scores:

1. **Inspectability** — an open license permitting local use, with published
   tokenizer and architecture.
2. **Reproducibility** — a stable, version-pinned artifact with a publisher digest
   *you* obtain, not one this machine computes and calls authoritative.
3. **Memory footprint** — must clear §5 admission.
4. **Runtime stability** — must run under llama.cpp CUDA on Windows.
5. **Observability** — must report token counts so telemetry is measured, not guessed.
6. **Replaceability** — the architecture is a contract, so the model is a
   configuration, not a rewrite.

Candidate families that fit: Llama 3.1 8B, Qwen2.5 7B, Mistral 7B, Phi-3.5-mini.
**The choice is the human's** and is made *after* the runtime is verified, so the
runtime is never blocked on a model decision.

### 3.2 Acquisition procedure (human-controlled)

1. Build or obtain `llama-cli.exe` with CUDA support. Place it at an explicit path.
2. Download the chosen GGUF from its publisher, by hand, to
   `human_control/experiment_config/weights/`.
3. **Obtain the publisher's SHA-256** from the release page. This is the value
   that goes in the configuration. The laboratory will not compute a digest and
   then declare it trustworthy — that would be self-attestation.
4. Write `human_control/experiment_config/runtime.json`:

```json
{
  "schema": "babylab/runtime-config/v1",
  "declared_by": "HUMAN",
  "model": {
    "adapter_id": "llamacpp",
    "path": "human_control/experiment_config/weights/<file>.gguf",
    "sha256": "<publisher digest, 64 hex>",
    "size_bytes": 0,
    "family": "",
    "name": "",
    "quantization": "Q4_K_M",
    "context_length": 4096,
    "runtime_binary": "<absolute path to llama-cli.exe>",
    "license": "",
    "license_url": ""
  }
}
```

5. Start the runtime. It refuses if the digest does not match.

### 3.3 Verification procedure

`load()` refuses, in order, and never proceeds past a failure: runtime binary
missing → `RUNTIME_MISSING`; artifact absent → `ARTIFACT_MISSING`; format not GGUF
→ `UNSUPPORTED_FORMAT`; digest absent or malformed → `NOT_CONFIGURED`; digest
mismatch → `DIGEST_MISMATCH`. Weights are only read after the digest matches, so
a substituted artifact is never executed on the strength of its own metadata.

## 4. Reproducibility and determinism

`seed` and `temperature` are always passed explicitly, including when zero. A
default the runtime happens to apply can change between builds; an explicit zero
cannot. The invocation is a fixed argument vector with `shell=False`, asserted in
tests, so an unrecognised option is a startup error rather than a silent
behaviour change.

## 5. Resource governance

| Limit | Default | Effect |
| --- | --- | --- |
| `max_vram_fraction` | 0.85 | Load refused above this share of **observed** VRAM |
| `max_model_bytes` | unset | Optional hard ceiling |
| `max_context_length` | 32768 | Longer refused |
| `max_inference_seconds` | 600 | Wall-clock ceiling |
| `require_gpu` | False | When true, no CPU fallback |

Admission returns `ADMIT`, `REFUSE`, or **`UNKNOWN`**. It refuses only on observed
facts. When VRAM cannot be observed it returns `UNKNOWN` and defers — it does not
estimate. A VRAM estimate used to refuse would reject models that fit; an
optimistic assumption used to admit would accept models that fail at load.

WMI's `AdapterRAM` saturates at 4 GiB, so it is never used as a VRAM total. On
this machine `nvidia-smi` reports the real 8.00 GiB, which is what the governor
uses.

## 6. Observability

Emitted to the existing `EventStore`, all sourced `babylab.runtime`:

`runtime.configure.requested` · `.accepted` · `.refused` ·
`runtime.admission.evaluated` · `.uncertain` ·
`runtime.model.load.requested` · `.succeeded` · `.failed` ·
`runtime.inference.requested` · `.started` · `.completed` · `.cancelled` · `.failed` ·
`runtime.cancel.requested` · `runtime.shutdown`

Each carries instance id, runtime identity, model identity, request id, resource
metrics and result.

**No prompt text and no completion text is ever written to the event log.** Prompt
and output *lengths* and digests are recorded instead, so the event is useful for
debugging without becoming a transcript store.

## 7. Provenance

Model output is classified **`INHERITED_PRETRAINED`** — M003's existing class, used
rather than a new vocabulary. The classification is derived from external facts
(which adapter ran, which verified digest, which runtime emitted the text), never
read from the artifact.

A model emitting `{"author": "BABY_AI", "i_wrote_this": true}` changes nothing:
that text is stored as text, and the authorship class beside it comes from the
key that signed the record. This is tested directly.

Records carry SHA-256 of prompt and output, never the text itself.

**MODEL OUTPUT and BABY AI AUTHORED CHANGE remain distinct categories.** M006
creates no `BABY_AI` key, so nothing can be `BABY_AI_AUTHORED` yet.

## 8. Trust boundary

The `SubjectInterface` has no method that takes a path, reads a file, runs a
process, opens a network connection, or returns key material. It is not that these
are checked at runtime — the methods do not exist. It holds no reference to the
keyring, the control token, or the provenance private keys, so it cannot hand them
out.

Capabilities may be *named* by a caller. A name is recorded as a statement of
intent, never treated as authorisation, matching the M003/M004 trust model.

The runtime is not given: the `BABY_AI` signing key, the human-control key, the
provenance signing key, protected evidence write capability, ACL modification, or
control-process credentials.

## 9. Network policy

Local-only. No network client is imported anywhere in `babylab/runtime/` — this
is asserted by a test that scans every module for network imports. `llama-server`
is deliberately unused because it opens a listener. If a future runtime needs
network access, that is a separate decision with a separate review.

## 10. What M006 does not do

No autonomous loop · no self-directed execution · no persistent goals · no
background agents · no self-modification · no self-training · no reinforcement
learning · no online learning · no persistent memory · no environment interaction
· no tool discovery · no physical interaction · no curriculum · no skill tree · no
milestone XP · no developmental stages · no reward schedule · no learning
objectives.

No curriculum is prescribed because the subject's development is the *subject of
the experiment*. Encoding a progression would replace the thing being studied with
the thing being assumed.

## 11. Replacing the model

1. Write a class satisfying `ModelAdapter`.
2. `registry.register(AdapterRegistration(adapter_id="...", factory=..., ...))`.
3. Change `adapter_id` in the configuration.

The subject-facing interface, Observatory, provenance and trust boundary are
written against the contract and are not edited. There is no vendor name in the
cognitive architecture.

## 12. Known limitations

- **No model, no llama.cpp binary on this machine.** Every runtime path is
  `NOT_CONFIGURED` / `RUNTIME_UNAVAILABLE`, and that is the tested state.
- **No real inference has run.** `InferenceResponse` is exercised through a stub
  adapter and through `birth.llamacpp`'s parser. The end-to-end path
  (binary → GGUF → completion) is **unverified** until a human supplies both.
- **Streaming is unsupported** by the llama.cpp adapter and is reported as
  unsupported rather than faked.
- **Cancellation** is cooperative: the flag is observed by the next operation.
  Killing an in-flight child would require retaining the process handle.
- **WMI-only machines** (no `nvidia-smi`) report VRAM as `UNAVAILABLE`, so
  admission returns `UNKNOWN` and defers to the human.
- The M005 residual risks remain, including unguarded root-level
  `FILE_DELETE_CHILD` and `BABY_AI_TEST` not being able to run the harness.

## 13. Acceptance criteria

| Criterion | Status |
| --- | --- |
| Runtime architecture exists | yes |
| Model adapter contract exists | yes — versioned, `1.0.0` |
| Explicit model configuration exists | yes — one source, no defaults |
| No fallback/download behaviour | yes — tested |
| Model identity externally derived | yes — SHA-256 from bytes, never from the model |
| Model artifact hash verified | yes — tested for mismatch and absence |
| Runtime telemetry observable | yes — 15 event types |
| Inference contract works | yes |
| Runtime failures explicit | yes — 12 `RuntimeErrorKind`s |
| Protected research files inaccessible | yes — no method exists |
| Protected credentials inaccessible | yes — no reference held |
| Workspace boundary intact | yes — M005 tests still pass |
| No network dependency | yes — asserted by import scan |
| No autonomous loop | yes — AST-asserted |
| No persistent memory | yes — tested |
| No self-modification | yes — AST-asserted |
| No subject identity created | yes |
| No `BABY_AI` key created | yes |
| No birth | yes |
| Observatory epistemically honest | yes — status-annotated, no mental states |
| Tests pass | yes — 71 M006 tests, 1021 total |
| Working tree clean | yes |
| M006 documented | yes — this file |
| M007+ not implemented | yes |

**Birth remains impossible.** No model configured, no `BABY_AI` key, no birth
record, no subject. The laboratory still reports `NO SUBJECT BORN`.
