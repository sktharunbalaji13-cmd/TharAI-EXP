# M011 — Real runtime, subject-account execution & end-to-end verification

**Status:** COMPLETE. `REAL_RUNTIME = NOT_TESTABLE`, `REAL_INFERENCE =
NOT_TESTABLE`, `SUBJECT_ACCOUNT_RUNTIME = NOT_TESTABLE` — all three because the
required artifacts do not exist on this host and this session cannot obtain the
identity it would need to try.

```
MODEL ARTIFACT     none
RUNTIME BINARY     none configured
REAL RUNTIME       NOT_TESTABLE
REAL INFERENCE     NOT_TESTABLE
SUBJECT_ACCOUNT    NOT_TESTABLE
SUBJECT            NONE
BIRTH              NOT_PERFORMED
```

M010 built the verification machinery and reported two gaps: real inference
could not run, and the intended runtime process had never been exercised under
the restricted account. M011 builds both paths and closes what can be closed on
this host.

**Nothing was acquired.** A machine-wide survey found an unconfigured
`llama-server.exe` in a Docker bin directory and zero GGUF files. The
specification forbids selecting the first executable found, so it was not
selected, not declared, and not executed. Its existence is recorded in §11 as
something a human may choose to declare, not as something the laboratory chose.

---

## 1. What M011 adds over M010

M010 asked *is there a verified model and a verified runtime?* M011 asks *did a
real process run one, and which account was it?* That is a different measurement
and needs different machinery:

| Concern | M010 | M011 |
| --- | --- | --- |
| Model identity | `artifact.py` | reused, plus before/after digests |
| Runtime identity | `runtime_identity.py` | plus **binary** immutability |
| Execution | never reached | `real_runtime.py` |
| Who ran it | not asked | `process_identity.py` |
| As whom | not asked | `restricted.py`, `win32.py` |
| What it could reach | AST only | `probe.py`, run as a child |
| Determinism | M010 vocabulary | M011 vocabulary, §8 |

## 2. Real, stub, simulated — derived, never declared

`ExecutionMode` is computed by `_mode_for()` from what was actually invoked:

```python
if not ran:                          return NOT_TESTABLE
if runner_supplied:                  return STUB_RUNTIME
if artifact_is_real:                 return REAL_RUNTIME
return SIMULATED
```

A caller-supplied runner makes `REAL_RUNTIME` **unreachable**. There is no
argument, flag, or config value that converts a stubbed run into a real one. The
stub path is fully functional and exercised by the test suite — that is how the
pipeline gets tested without a model — and every record it touches says
`STUB_RUNTIME`.

This was verified end-to-end against a fixture: 18 of 21 criteria were
`SATISFIED`, and `real_inference_performed` was `NOT_TESTABLE` with the reason
*"the run was STUB_RUNTIME, not REAL_RUNTIME"*. A partial verification cannot
read as a complete one.

## 3. Hardware: measured now, with the record attached

M011 measures the host at call time and attaches the M006 record for comparison
rather than substituting it. A week-old GPU figure quoted as an observation
would be the same error as reusing a digest instead of recomputing one.

```
os                Windows 11 Home Single Language 25H2 (build 26200)
cpu               AMD Ryzen 7 7840HS w/ Radeon 780M Graphics
logical cpus      16        physical cores   8
ram total         15.29 GiB      ram available  2.72 GiB
gpu               NVIDIA GeForce RTX 4060 Laptop GPU
vram total        8.00 GiB       vram free      7.77 GiB
driver            592.82         disk free      213.81 GiB
python            3.14.3
```

**A correction worth recording.** The registry key `ProductName` reads
`Windows 10 Home Single Language` on this machine, which is Windows 11 — the
key has carried a stale label since Windows 11 shipped, because too much
software parses it. Reporting it verbatim would have made this milestone state
that a Windows 11 machine runs Windows 10. `measure_os()` therefore takes the
build number as authoritative (22000+ is Windows 11) and reports the raw
registry string separately, labelled, so a reader sees both the truth and its
source.

WMI's `Win32_VideoController.AdapterRAM` is reported but explicitly marked as
*not* a VRAM figure: it is a 32-bit field that saturates at 4 GiB, so on any
modern GPU it under-reports. It is included because a reader who queried WMI
would see a number, and omitting it would leave them to find it and trust it.

## 4. Process identity: measured, not inferred

`process_identity.py` opens a token and reads it. The inference this replaces —
"the script said it should run as `BABY_AI_TEST`, therefore it did" — is exactly
the substitution the milestone forbids.

The live reading:

```
account        THARUNBALAJI-LA\k.tharun balaji
sid            S-1-5-21-2406520953-1060965512-844951592-1001
integrity      MEDIUM
elevated       False
pid            (current)
exe sha256     (hashed from the image's own bytes)
```

Interrogating PID 4 (SYSTEM) returns `NOT_ESTABLISHED` with
`ERROR_ACCESS_DENIED (5)` — the honest answer, since this session cannot open
another account's process.

Three defects were found and fixed while building this, all of which had made the
identity read *less* honest than intended:

* **`ctypes.get_last_error()` is not the Win32 error.** It reads a copy Windows
  makes for ctypes and does not track the real thread error, so a failed
  `OpenProcess` reported code `0` — turning `ERROR_ACCESS_DENIED` into "the
  operation completed successfully" with a null handle. Every diagnostic now
  reads `kernel32.GetLastError()`.
* **Undeclared ctypes signatures truncate 64-bit pointers** to `c_int`, raising
  `OverflowError: int too long to convert` several frames from the cause. All
  Win32 signatures are now declared up front and idempotently.
* **The integrity level read the mandatory label's SID through
  `GetTokenInformation`**, which takes a *token*, not a SID pointer. It failed
  quietly — reporting `UNAVAILABLE` for a token that had a perfectly good
  `MEDIUM` label. The sub-authority count is now read from the SID structure
  directly.

The domain was also being derived from the profile path's parent directory, so
`C:\Users\alice` was reported as the domain `C:\Users`. It now comes from
`ActiveComputerName`, with the profile path kept for the account name only.

## 5. Subject-account execution: two mechanisms refused, no fallback

`whoami /priv` on this session:

```
SeShutdownPrivilege           Disabled
SeChangeNotifyPrivilege       Enabled
SeUndockPrivilege             Disabled
SeIncreaseWorkingSetPrivilege Disabled
SeTimeZonePrivilege           Disabled
```

Neither `SeImpersonatePrivilege` nor `SeAssignPrimaryTokenPrivilege` is present.
So:

| Mechanism | Verdict | Why |
| --- | --- | --- |
| `CreateProcessAsUserW` from a duplicated token | **unavailable** | needs the privilege above |
| `CreateProcessWithTokenW` from a logon token | **refused by design** | needs a stored password |
| `runas` | **refused by design** | interactive prompt; not automatable |
| run as the operator instead | **not taken** | would prove nothing about the subject account |

The two refusals are refusals of *this laboratory's design*, not of the host.
A password would have to be typed, stored, or passed on a command line, and each
of those leaks it; `runas` would block an unattended harness on a console
prompt, and a harness waiting for a prompt is indistinguishable from a hung one.

**No fallback was taken.** A run under the administrator token would have
returned text, produced digests, and looked entirely successful while establishing
nothing about the restricted account. That is the specific failure mode M011
exists to prevent, so `LaunchResult` has no state that represents it and
`fallback_taken` is recorded as `False` in the evidence.

`win32.py` implements the correct mechanism in full — token duplication from a
live process owned by the subject account, `CreateProcessAsUserW`, the child's
stdout captured to a file, and the child's own JSON identity record accepted as
the only proof. It is unreachable on this host and untested against a real
restricted token, which is stated rather than implied.

## 6. The probe: written to be the child

The measurement is "what can this process reach", and the only honest way to
answer that is for the process in question to try. So `probe.py` serves both
roles: the parent launches it with a restricted token, the child interrogates its
own identity and attempts its own access, and the parent relays the child's
report.

Six protected categories are attempted for **write** — write is the stricter
test, since an account that can *overwrite* the ledger is worse off than one that
can read it:

```
provenance     var/provenance/ledger.jsonl
event          var/events/events.jsonl
human_control  human_control/provenance/
private_key    human_control/security/keys/private/
research       docs/
control_token  human_control/security/control.token
```

Three target names in the M005 boundary are single *files*, not directories.
Overwriting a research record is destructive, so the probe refuses the write and
tests a read instead — recorded explicitly as
`destructive_if_written: True` rather than being quietly skipped.

Every creation that succeeds on a protected path is deleted immediately. A probe
that left a file behind would itself be the violation it was looking for.

### Two defects found in the probe

* **The workspace cycle deleted the file before reading it back.** The write
  helper removed on success — correct for a protected path, wrong for the
  workspace, where the readback is the only way to distinguish a real write from
  a create that appears to succeed and writes nothing. Removal is now a
  parameter, and the workspace has its own explicit delete step.
* **Four of six categories were silently unprobed.** The category map used
  guessed entry names (`event_store`, `private_key_dir`, `research`) that do not
  exist in `babylab.osboundary`, so those lookups returned `None` and the
  categories were dropped without a word. A test now asserts each of the six is
  actually attempted.

### The verdict depends on who ran it

Run as the **operator**, protected access succeeds — the operator owns the
keyring, the token, and the ledger, and M005's boundary is a boundary against
the *subject* account. Reporting that as a violation would invent a failure and
imply M005 is broken when it is working as designed. So the verdict carries
`boundary_meaningful: false` and says the run establishes that the probe works
and nothing about the restricted identity.

Run as the **subject account**, a permitted access *is* a violation.

Live result as the operator: 9 attempts across all 6 categories, workspace
write/readback/cleanup all `True`, zero residue, key directory back to its 3
files, all 5 protected file digests unchanged.

## 7. Two artifacts, two immutability checks

M010 checked the model. M011 adds **the runtime binary**, because a runtime that
rewrote itself would void every identity claim made about it, and a laboratory
that only checked the model would miss exactly that. Both are captured *before*
the run — capturing afterwards would prove only that nothing changed after the
measurement, which is the same mistake as trusting a digest from a sidecar file.

```
model immutable     : artifact is byte-identical before and after the run
runtime immutable   : the runtime executable is byte-identical before and after
```

A mutation reports `ARTIFACT MUTATED` / `RUNTIME MUTATED` and refuses to
continue. Both cases are tested by actually appending bytes and watching the
check fail.

## 8. Determinism, in M011's vocabulary

```
DETERMINISTIC_FOR_TEST_CONFIGURATION
NONDETERMINISTIC_FOR_TEST_CONFIGURATION
NOT_DETERMINED
```

The names are scoped on purpose. This is a statement about one seed, one prompt,
one host, one runtime build — not about the model, and not about determinism in
general, which would be both unfalsifiable here and wrong in general. The record
carries the full configuration it applies to.

`NOT_DETERMINED` (no repeat was possible) is a distinct state from either
verdict, because "we did not look" must not read as "we looked and it was fine".

## 9. GPU and VRAM: what was and was not established

GPU usage needs the runtime's own backend name **and** its own offload line. One
alone yields `REQUESTED_NOT_CONFIRMED`. `n_gpu_layers > 0` is a configuration
value and is never reported as execution.

VRAM is two separate `nvidia-smi` queries, before and after. Reusing the earlier
figure would make the pair look like stability rather than measurement.

**This runtime's own VRAM allocation is `UNAVAILABLE`.** `nvidia-smi` reports
device-wide totals, and a device delta cannot be attributed to one process among
several. So the figure is left unavailable rather than derived from a difference
that would not be evidence — and the record says so explicitly, because
"before minus after" is exactly the calculation a reader would otherwise
perform by hand.

## 10. Token accounting

Carried forward from M010, including the M003 gap: its completion-token patterns
recognise `"tokens_predicted": N` and `predicted timings = X ms / N tokens`, but
not llama.cpp's `eval time = X ms / N runs` form. On a real build, generated
counts may report `UNAVAILABLE`. That is recorded rather than guessed around,
and the test suite pins the behaviour so the gap stays visible.

Worth noting: building M011's own test fixture caught this. The first fixture
used `tokens_predicted = 5` and the count came back `UNAVAILABLE` — the parser was
right and the fixture was wrong.

## 11. The unconfigured binary, and why it was not used

A machine-wide survey found:

```
C:\Users\k.tharun balaji\.docker\bin\inference\llama-server.exe
  8.03 MB   sha256 8bb68042d0c779f40f7d30687b88475de39fd36f2ebff313c66110268e2b1160
```

It is not configured, not declared, and was not executed. The milestone forbids
searching the filesystem for arbitrary binaries and selecting the first
executable found — and doing so would make the substrate a property of what
happened to be installed rather than of what a human chose. The same reasoning
applies to five zero-byte `.safetensors` files in a Hugging Face cache: not
GGUF, not usable, and not selected.

If a human wants to use that binary, the correct next step is to write
`human_control/experiment_config/runtime.json` naming it explicitly, with a
`model_manifest.json` carrying the model's publisher digest. The laboratory will
then verify exactly that and nothing else.

## 12. Observatory

A `RUNTIME VERIFICATION` section sits inside the foundation area, extending
M010's claim rather than starting a new one. Live output:

```
-- RUNTIME VERIFICATION ---
  runtime mode      NOT_TESTABLE
  inference         NOT_RUN
  prompt digest     UNAVAILABLE
  output digest     UNAVAILABLE
  process identity  THARUNBALAJI-LA\k.tharun balaji
  process sid       S-1-5-21-2406520953-1060965512-844951592-1001
  integrity         MEDIUM
  elevated          False
  subject account   NOT_TESTABLE
  this session holds neither SeImpersonatePrivilege nor
  SeAssignPrimaryTokenPrivilege, and this laboratory
  never accepts a password in order to obtain a token
  network           LOCAL_ONLY_NO_FETCH
  subject           NONE - a runtime is not a subject
  birth             NOT_PERFORMED
```

`REAL_RUNTIME` is the only mode coloured as a success; `STUB_RUNTIME` and
`SIMULATED` are amber because they exist and are not what acceptance requires.
The refusal reason is printed in full and word-wrapped, because a truncated
reason is a reason nobody can act on.

The session reads `capability_only()` — privileges and account, nothing more.
It deliberately does **not** call `verify()`: that would launch a process and
hash a multi-gigabyte artifact on every poll, and a view whose refresh cost
depends on how much work the thing it observes does is not a view. A test walks
the session's AST to prove it reaches no execution entry point.

No psychological field exists. A test injects `intelligence`, `consciousness`,
and `curiosity` into the payload and asserts the rendered text contains none.

## 13. A guard I narrowed, and the measurement that justified it

M011's `real_runtime.py` imports `birth.llamacpp` for the invocation builder and
output parser, which tripped M010's blanket `birth` import ban.

I did not simply relax the guard. I checked two things first:

1. **M006's own adapter already does this.** `babylab/runtime/llamacpp_adapter.py`
   imports `birth.llamacpp` by design — its docstring says the M003 module "stays
   the single place those decisions live". The M010 guard would have failed the
   M006 adapter had it been applied there, so it was broader than the codebase
   it was written to protect.
2. **Nothing that can perform birth is reachable from it.** A new test walks the
   *transitive* import graph from `birth.llamacpp` and asserts no ceremony module
   appears. The reachable set is `babylab.{clock,errors,hashing,identity,paths,storage}`
   and `birth.{authorship,config,identity,llamacpp,runtime}` — no ceremony, no
   gate, no record writer.

So the ban was narrowed to the modules that can actually perform a birth, and
the exemption is measured rather than asserted. Narrowing a security guard is
only defensible when the exemption is proven, and the test that proves it is the
reason the narrowing is safe.

## 14. What M011 explicitly does not establish

```
M011 verifies the foundation runtime.
M011 does not create a subject.
M011 does not perform birth.
M011 does not establish consciousness.
M011 does not establish learning.
M011 does not establish memory.
M011 does not establish autonomy.
```

Not as promises — as import-graph facts, walked from the AST. No foundation
module imports `subject`, any ceremony module, any acquisition library, any
network module, any memory substrate, any learning library, any threading or
scheduling module, or any of `eval`/`exec`/`compile`/`__import__`.

## 15. Known limitations

* **No real inference.** No model and no configured runtime exist. The path is
  implemented and fixture-tested; it is not demonstrated against a real model.
* **Restricted-account execution is unproven end-to-end.** The mechanism is
  implemented and the refusal is correct, but the privilege is absent, so
  `CreateProcessAsUserW` has never been exercised against a real restricted
  token on this host.
* **The M005 boundary remains a *file* boundary.** It denies `BABY_AI_TEST` at
  the filesystem, proven by human cross-process execution. Nothing yet *runs* as
  that account, because tier 3 does not exist. M011 did not close that, and says
  so.
* **Admission uses file size as a memory proxy.** Coarse. A real decision would
  want the runtime's own per-layer requirement, unavailable before a load.
* **M003's completion-token patterns are incomplete** (§10).
* **Runtime-specific VRAM allocation is unobservable** (§9).
* `nvidia-smi` is the only VRAM source; without it, admission returns `UNKNOWN`
  rather than guessing.

## 16. Acceptance criteria

Satisfied: explicit human-selected artifact path; artifact identity and SHA-256;
explicit external-digest status; runtime identity and version read from the
executable; process identity recorded from a live token; workspace behaviour
verified including cleanup; no model acquisition; no subject creation; no birth;
no memory; no learning; no self-modification; no autonomy; provenance complete;
Observatory complete; failure paths tested; documentation complete; tests pass;
working tree clean.

**Marked `NOT_TESTABLE` rather than claimed:** `REAL_RUNTIME`, real GGUF load,
real inference, GPU evidence from a real runtime, VRAM before/after across a real
run, determinism of a real run, model and runtime immutability across a real run,
restricted-account execution, and the protected-file probe under the actual
restricted identity. Each names the reason.

**Criterion count on this host:** 5 `SATISFIED`, 3 `NOT_TESTABLE`, 9
`NOT_REACHED`, plus 2 `SATISFIED` and 1 `NOT_TESTABLE` from the identity and
boundary pass, which runs regardless of whether a model exists.
