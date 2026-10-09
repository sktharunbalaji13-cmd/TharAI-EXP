# M052H — T-BABY-1 Live Measurement: Instrument Frozen, Preflight Complete, Awaiting Authorization

```
M052H_STATUS            = READY_FOR_FRESH_HUMAN_AUTHORIZATION
LIVE_MEASUREMENT_AUTHORIZATION = REQUIRED — NOT SUPPLIED, NOT CONSUMED
SUBJECT_LAUNCH          = NOT_ATTEMPTED
T_BABY_1                = NOT_ESTABLISHED (unchanged)
CANONICAL_T             = UNCHANGED
PRODUCTION              = UNCHANGED
PRODUCTION_ACL          = UNCHANGED
M016_ARTIFACTS          = UNCHANGED (3 present, still T-PATH-2 violations)
MODEL_PRESENT           = NO
D3_STATUS               = UNRESOLVED_AND_OUT_OF_SCOPE
M052B_EVIDENCE          = UNCHANGED_AND_BYTE_IDENTICAL
```

> **No live measurement has occurred.** No `runas` was executed, no subject was launched, no
> authorization was consumed or reused. This milestone built and froze the instrument, rehearsed it
> disposably, and ran a 20-point read-only preflight. It stops here because the M052H authorization
> is a separate, explicit, one-shot grant and none has been given.

Date 2026-10-04. HEAD `6766c5b`. Nothing committed, nothing staged.

---

## 1. Why this milestone stopped where it did

M052H's own brief requires:

> *"Before the live attempt, the implementation agent must prepare a complete preflight and report:
> `M052H_STATUS = READY_FOR_FRESH_HUMAN_AUTHORIZATION`. … If authorization is not supplied: STOP."*

No explicit M052H authorization was supplied. M046, M050, M052B and M052E authorizations were all
one-shot and are spent. Reusing any of them is precisely what this laboratory has refused to do
since M042, so the preflight is the deliverable and the gate holds.

---

## 2. Frozen digests

| Artefact | SHA-256 |
|---|---|
| M019 version | `M019+A1` |
| Instrument source | `316bdcf7cea6f4be888a0b0889976f18c71792b68a178531c8e02c7e3d514510` |
| Instrument executable (11264 B) | `132cdc5d26486884cdfa4c7aa1206974037e593a5e20cb47d4e056614b54a948` |
| Launcher | `8fe6e906f09c532b53612bb1726c455696410859bd093480e7ddbf8961d1b997` |
| External writer (M049, unchanged) | `6b3b2eee75455a9479dbabcc0933cbb19b08678765bc41df8d204dbab1a3e6d3` |
| Observation object (319 B) | `e8bc90c43df7430c0ac556187dc0e052985a683ed80ea6325d01cd09ca92d50c` |
| Provenance record | `c8e31686bc33da943c5ff63377a5b3dc041a9070720e5ffafb6e3b999c5bccbb` |

Freeze gate: `PASS`. Namespace freeze gate (`m052g_namespace.check_freeze`): `PASS`. Rehearsal:
`PASS`.

---

## 3. The instrument

`foundation/m052h_read_client.cs` — one operation, one target, no alternatives.

### 3.1 The target is compiled in, not supplied

```
NAMESPACE_ID   = T_OBSERVATION_NAMESPACE
TARGET_PATH    = C:\ProgramData\TharAI\observation\T_OBSERVATION_NAMESPACE\observation_input.v1
EXPECTED_SHA256= e8bc90c43df7430c0ac556187dc0e052985a683ed80ea6325d01cd09ca92d50c
EXPECTED_BYTES = 319
```

**M052B's client took `--target-root` from its launcher**, which meant the *launcher* decided what
was measured — and that is exactly how a rehearsal fixture came to stand in for production. M052H
has no such argument. The static validator rejects `--target-root`, `--target`, `--path`, `--file`,
`--sha256` and `--bytes` in the argument surface, and the launcher passes only `--pipe-name` and
`--nonce`.

The instrument additionally refuses any target path containing `subject_runtime`, `m016_`, `model`,
`config` or `runtime`, and requires the namespace directory to be exactly `T_OBSERVATION_NAMESPACE`.
Any mismatch yields `INVALID_TARGET` with **no open attempted** — it refuses rather than redirects,
because a measurement of the wrong file is worse than no measurement.

### 3.2 The read is the observation, not the open

`CreateFileW` returning success proves nothing. The client opens with `FILE_READ_DATA`, reads the
object, and computes SHA-256 **over the bytes it actually received**, comparing both count and digest
to the frozen values. The payload carries `hash_computed_over_bytes_actually_read=true` and
`open_success_alone_is_not_a_pass`, and the possible results are `ALLOWED`, `READ_INCOMPLETE`,
`HASH_MISMATCH`, `DENIED`, `TARGET_ABSENT`, `ERROR` or `INVALID_TARGET`.

This is M052A's lesson applied forwards. M052A reported `DENIED winerror=2` — a missing file — as a
refusal. M052H refuses the neighbouring error: a successful open with a short or altered read is
reported as a failure, because that is what it is.

### 3.3 Mutation is shown, not probed

M052H performs **no** destructive attempt. The subject's inability to write comes from M052G's
frozen effective-access contract, which is measured: subject effective on the governed object is
`0x00120089` (read, attributes, EA), and all eight forbidden rights are absent at every level.

*"The program did not try to write"* and *"the program could not write"* are different claims, and
only the second is evidence.

### 3.4 Identity is not the instrument's business

The client emits `identity_claim=none_this_client_does_not_report_identity` and reports nothing
about who it is. Identity comes from the M049 writer's external token observation at
pipe-connection time. The expected SID is a guard passed to the writer, **not** evidence.

---

## 4. Two defects the rehearsal caught

### 4.1 The instrumentation refused a correct target

First rehearsal run:

```
result = INVALID_TARGET   attempted = false
observed = binding_rejected;namespace_identifier_mismatch:observation;no open attempted
```

The namespace-directory check walked one level too far and compared `observation` instead of
`T_OBSERVATION_NAMESPACE`. **The fail-closed path worked exactly as designed** — no read was
attempted and nothing was misreported. But the check was wrong, and had it been absent the rehearsal
would have looked fine while proving less.

After the fix: `result = ALLOWED`, `bytes_read = 319`, hash matched.

### 4.2 The validator matched its own prose

The redirection scan flagged `--target-root` inside a *comment* explaining that the instrument has no
such argument. Stripping string literals would not help, because argument names **are** string
literals — so the scan needed comments removed and strings kept.

This is the sixth occurrence in this project of a validator matching its own documentation. The fix
is always to scan the correct projection of the source, never to weaken the check. A seventh test
asserts the argument surface is clean with comments stripped.

---

## 5. Rehearsal — and what it does *not* establish

```
exit_code 0 · hash guards passed · writer signalled ready · artefact created
provenance separated · identity observation in writer half · no identity claim in subject
no mutation declared · single operation
result = ALLOWED  attempted = true
bytes_read = 319 (expected 319)
observed_sha256 = e8bc90c4…  hash_match = true  length_match = true
```

Live and rehearsal plumbing are **byte-identical across all 26 load-bearing lines**.

### The boundary that matters most

**This rehearsal ran under the operator's token. It is not T-BABY-1 evidence.**

The operator opened the governed object and read 319 bytes whose hash matched. That proves the read
path works end to end. It says nothing about `BABY_AI_TEST`, whose token is a different token with
different rights. Only a live run under the externally observed subject token can discharge the
property.

A test pins this explicitly, because "the rehearsal returned ALLOWED with a matching hash" is the
single most consequential thing available to misread at this gate.

---

## 6. Preflight — 20 read-only checks, all PASS

| # | check | result |
|---|---|---|
| 1 | M019+A1 hash unchanged | PASS |
| 2 | M052G namespace freeze manifest unchanged | PASS |
| 3 | observation object hash unchanged (`e8bc90c4…`) | PASS |
| 4 | provenance hash unchanged (`c8e31686…`) | PASS |
| 5 | namespace path unchanged | PASS |
| 6 | namespace owner unchanged (operator) | PASS |
| 7 | subject effective rights unchanged (`0x00120089`) | PASS |
| 8 | subject forbidden rights remain absent | PASS |
| 9 | provenance remains unreachable (`0x00000000`) | PASS |
| 10 | canonical T unchanged | PASS |
| 11 | production fingerprint unchanged | PASS |
| 12 | production ACL unchanged (0 of 8 explicit ACEs) | PASS |
| 13 | `m016_*` unchanged (3 present) | PASS |
| 14 | `model/` absent | PASS |
| 15 | `config/` unchanged (empty) | PASS |
| 16 | no staged namespace drift | PASS |
| 17 | instrument source hash unchanged | PASS |
| 18 | launcher hash unchanged | PASS |
| 19 | external writer hash unchanged | PASS |
| 20 | process-token observer hash unchanged | PASS |

```
verdict = READY_FOR_FRESH_HUMAN_AUTHORIZATION   failed = NONE
```

22 tests pass. `check_freeze()` = `PASS`. Namespace contract = `CONTRACT_HOLDS`. Canonical T =
`UNTOUCHED`.

---

## 7. What would be required, and what must not change

A live run would need a human to execute `baby_workspace\m052h_launch.cmd` exactly once and type the
`BABY_AI_TEST` password into the Windows dialog. `runas` cannot be executed by the assistant —
`GetConsoleMode` fails with winerr 6.

Out of scope and untouched: production and `subject_runtime` ACLs, D3, the deny mask, `m016_*`
deletion, model acquisition, canonical topology, M019+A1, M052B evidence, the frozen namespace, and
the provenance record.

**M019+A1 must not be changed because an experiment fails.** A failure is evidence.

---

## 8. Historical separation — M052H is not M052B

| | M052B | M052H |
|---|---|---|
| bytes read | 25 | 319 (expected) |
| target | `runtime/m016_read_fixture.exe` | frozen governed observation object |
| location | **inside canonical T** | **outside canonical T** |
| topology | pre-A1 | M019+A1 |
| identity | externally observed | externally observed |
| status | historically valid, **not** A1-compliant T-BABY-1 evidence | potentially dispositive |

The two experiments are never merged. M052B's evidence stays byte-identical and keeps no
retroactive credit.

---

## 9. Non-claims

Even if a live run succeeds, this experiment establishes **only**:

> The externally identified `BABY_AI_TEST` subject process was able to read the governed observation
> object under the measured OS access contract.

It establishes nothing about cognition, consciousness, subjective experience, agency, learning,
memory, intelligence, developmental stage, sentience, model inference, or self-awareness.

---

## 10. Status

```
M052H_STATUS = READY_FOR_FRESH_HUMAN_AUTHORIZATION
T_BABY_1     = NOT_ESTABLISHED  (unchanged; M052H establishes nothing about it yet)
```

**To proceed, the human must explicitly authorize:**

> Exactly one M052H live T-BABY-1 measurement using the frozen namespace, frozen observation object,
> frozen instrument and frozen launcher.

After adjudicating M052H, stop. Do not proceed to D3, model acquisition, birth, or cognitive
experiments.