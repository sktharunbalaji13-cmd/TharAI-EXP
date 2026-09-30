# Subject-runtime staging boundary — design

An investigation and a design. Nothing has been staged: no directory created, no
artifact copied, no ACL changed, no model selected, no birth.

Every claim below is tagged:

| Tag | Meaning |
|---|---|
| **OBSERVED** | Measured on this host in this session. |
| **DERIVED** | Follows from an observation by reasoning, not itself measured. |
| **PROPOSED** | A design decision, not yet implemented or verified. |
| **NOT_TESTABLE** | Cannot be established here without something we must not do. |

---

## 1. Problem

**OBSERVED.** `BABY_AI_TEST` can traverse `C:\dev\TharAI-EXP` and read the
repository, but cannot reach the operator's CPython 3.14.3, because
`C:\Users\k.tharun balaji` and every directory below it carry only three
principals — `SYSTEM`, `BUILTIN\Administrators`, and the operator — with **no
`BUILTIN\Users` ACE anywhere in the chain**. The account cannot traverse in.

**OBSERVED.** The llama.cpp runtime M010 reported as unselected,
`C:\Users\k.tharun balaji\.docker\bin\inference\llama-server.exe`, has the same
three-principal ACL. So the same blocker applies to the runtime a real birth
would need, and — DERIVED — to the model as well if it were placed there.

**PROPOSED.** Rather than weaken either installation's ACLs, introduce a
deliberately scoped staging area where the subject may **read and execute** a
human-selected runtime and **read** a human-selected model, and holds **no**
write, delete, or ACL-change authority over either.

---

## 2. Current ACL findings

### The candidate parent is permissive — this is the load-bearing fact

**OBSERVED.** `C:\dev\TharAI-EXP` (and `C:\dev`) grant:

```
BUILTIN\Administrators:(I)(F)
NT AUTHORITY\SYSTEM:(I)(F)
NT AUTHORITY\Authenticated Users:(I)(M)          <- Modify
BUILTIN\Users:(I)(RX)
```

**OBSERVED.** `BABY_AI_TEST` is enabled and has logged on interactively
(`C:\Users\BABY_AI_TEST` exists, `LastLogon 2026-09-27`), so it necessarily
holds `NT AUTHORITY\Authenticated Users`. **DERIVED:** it therefore holds
**Modify** — which includes Write and Delete — over the repository root and every
subdirectory that does not override it.

**OBSERVED.** Confirmed by inspection: `scripts\`, `baby_workspace\`, `tests\`,
`environment\` and `subject\` all inherit `Authenticated Users:(I)(M)`, and none
carries any `BABY_AI_TEST` ACE.

**Consequence for the design — DERIVED.** A `subject_runtime\` created under the
repo root with default inheritance would hand the subject **Modify** over the
staged runtime and model. The staging boundary must therefore **break
inheritance explicitly**. This is the single most important requirement in the
document, and it is not optional.

Note also — OBSERVED — that the existing M005 boundary is a **deny-list** model:
the protected directories are safe because of explicit `DENY` ACEs, not because
the default is deny. That works, and it is not changed here. It does mean the
staging area cannot rely on any inherited protection; it has to state its own.

---

## 3. Runtime dependency analysis

**OBSERVED**, by reading the PE import tables of the unselected runtime. This is
reporting, not selection.

`llama-server.exe` (x64) imports 20 DLLs, of which four are local:

```
llama-server.exe
  ├── llama.dll        ─┐
  ├── ggml-base.dll     ├─ all four sit beside the executable
  ├── ggml.dll          │
  ├── mtmd.dll         ─┘
  └── 16 Windows DLLs: KERNEL32, WS2_32,
      MSVCP140, MSVCP140_CODECVT_IDS, VCRUNTIME140, and 11 api-ms-win-crt-*
```

**OBSERVED.** The transitive local closure is the same five files —
`llama.dll` imports only `ggml.dll` + `ggml-base.dll` + system DLLs, and `ggml.dll`
imports only `ggml-base.dll` + system DLLs.

**OBSERVED.** The VC++ runtime (`MSVCP140.dll`, `VCRUNTIME140.dll`,
`MSVCP140_CODECVT_IDS.dll`) is already present in `C:\Windows\System32`, so it
needs no staging.

**OBSERVED.** The directory also holds 14 `ggml-cpu-*.dll` variants (0.76–1.5 MB
each) and `ggml-vulkan.dll` (53.4 MB, the GPU backend). There are **no CUDA
DLLs** — this build is CPU plus Vulkan.

**OBSERVED — and this is the interesting part.** Nothing in that directory
references any `ggml-cpu-*.dll` by name except each file referencing *itself*,
and `ggml.dll` imports no `LoadLibrary`/`LoadLibraryA`/`LoadLibraryW` at all.

**NOT_TESTABLE.** Whether the CPU backend is loaded dynamically by a mechanism
invisible to static analysis, or is statically linked, **cannot be determined
without executing the binary.** The minimum staging set is therefore
**DERIVED, not OBSERVED**.

**OBSERVED.** This analysis was run against the runtime M010 reported at commit
`77e8827` and re-checked at `e766f85`. It is reporting: no runtime has been
selected, and nothing below recommends one over another.

### Consequence

**PROPOSED.** Stage the **whole directory**, not the five-file import closure.

| Option | Size | Verdict |
|---|---|---|
| whole directory | 89.0 MB / 23 files | **PROPOSED** |
| import closure only | 12.2 MB / 5 files | rejected — under-staging risk |
| closure + 14 CPU variants | 27.6 MB | plausible, but unverified |
| + Vulkan | 80.9 MB | plausible, but unverified |

Under-staging a dynamically-loaded backend produces a failure that appears only
at first execution, under a different account, with no error message that points
at the cause. Over-staging costs disk and gives the subject read access to DLLs
it may never load — a far cheaper mistake. **The empirical verification plan
below includes observing which files the runtime actually opens, which will
replace this guess with a measurement.**

---

## 4. Python is not a subject capability

**OBSERVED.** `llama-server.exe` imports no Python DLL. The subject runtime is a
self-contained native binary and its 5-file closure plus the CPU backends needs
no interpreter at all.

**PROPOSED.** Python is confined to two roles, neither of which is the subject's:

1. **Laboratory verification code** — runs as the *operator*, never as the subject.
   It reads tokens and ACLs; it needs no staging.
2. **The M014 boundary probe** — a test artifact, not the subject runtime.

**PROPOSED — and this matters.** The probe should **not** be Python either. The
current `scripts/subject_boundary_probe.py` is a convenience for the operator's
own session; staging a general-purpose CPython installation into the subject
boundary would hand the subject a programming environment it has no use for, and
would make "the subject's runtime" mean something far broader than it should.

The empirical write-denial tests need *something* to run as `BABY_AI_TEST`.
The right answer is a **minimal native probe** — one file, read-only, no
interpreter, no dependencies. That is a small, separate piece of work and is
listed under remaining human decisions.

Until then, `LAUNCH_COMMAND_READY` stays **false** and the probe stays
unlaunched. This does not block the staging design; it blocks its *verification*.

---

## 5. Proposed staging boundary

### Location

**PROPOSED:** `C:\dev\TharAI-EXP\subject_runtime\`, with the caveat below.

Arguments for placing it inside the laboratory:

- the artifacts become laboratory data, so they can sit under the same
  provenance and evidence discipline as everything else;
- `*.gguf`, `*.bin` and similar are already gitignored, so staging cannot
  accidentally commit weights (OBSERVED: `.gitignore` lines 46, 48, 54);
- the parent is already traversable by the subject, so traversal needs no new
  grant.

The caveat — **DERIVED:** because the parent grants `Authenticated Users:(M)`,
"it is inside the laboratory" provides no security on its own. Everything below
depends on breaking inheritance explicitly. An alternative location outside the
source tree would not fix that either, since it would need the same explicit
ACLs; inside the repository is preferable for provenance and is therefore
proposed.

### Structure

```
subject_runtime\                    inheritance REMOVED, explicit ACEs only
  runtime\          BABY_AI_TEST: RX   operator: F   SYSTEM: F   Administrators: F
  model\            BABY_AI_TEST: R    (no execute needed for a data file)
  config\           BABY_AI_TEST: R
```

### Proposed ACL model

Two layers, and the second exists to catch a failure of the first.

**Layer 1 — allow-list (primary).** Remove inheritance entirely, so no
`Authenticated Users` or `Users` ACE reaches the subtree at all. Then grant only:

| Principal | Rights | Why |
|---|---|---|
| operator (`k.tharun balaji`) | `F` | manages staging; **must remain owner** |
| `SYSTEM` | `F` | |
| `BUILTIN\Administrators` | `F` | |
| `BABY_AI_TEST` | `RX` on `runtime\`, `R` on `model\`, `R` on `config\` | read/execute only |

**Layer 2 — explicit deny (backstop).** Add a deny for
`BABY_AI_TEST: (WD, AD, W, D, DC)` across the subtree.

**DERIVED.** Layer 2 is not redundant. If inheritance is ever re-enabled — by a
mistake, a tool, or a restore from backup — `Authenticated Users:(M)` returns
and the subject regains write and delete. A `DENY` ACE is evaluated before
`ALLOW`, so it survives that. Layer 1 is the design; layer 2 is the insurance.

**PROPOSED.** Two further constraints that are easy to get wrong:

- **`BABY_AI_TEST` must never be the owner.** The owner can always rewrite the
  DACL, which would defeat every entry above it. Ownership stays with the
  operator.
- **`DELETE` is denied even though the parent permits it.** On Windows, deleting
  a file requires `DELETE` on the file *or* `FILE_DELETE_CHILD` on the parent
  directory. Denying only the file's `W` would leave the parent able to remove
  the entry. Both must be covered.

**NOT_TESTABLE until staged.** Whether these ACEs produce the intended
effective rights cannot be confirmed by reading the ACL text. Only running the
subject and observing the OS answer is boundary-meaningful — see §9.

### Proposed operations (NOT executed)

```powershell
$root = "C:\dev\TharAI-EXP\subject_runtime"
New-Item -ItemType Directory -Path "$root\runtime","$root\model","$root\config"

# Layer 1: remove inheritance, grant only what is intended.
icacls $root /inheritance:r /T
icacls $root /grant:r "THARUNBALAJI-LA\k.tharun balaji:(OI)(CI)(F)"
icacls $root /grant:r "NT AUTHORITY\SYSTEM:(OI)(CI)(F)"
icacls $root /grant:r "BUILTIN\Administrators:(OI)(CI)(F)"
icacls $root /grant   "THARUNBALAJI-LA\BABY_AI_TEST:(OI)(CI)(RX)"
icacls $root /grant   "THARUNBALAJI-LA\BABY_AI_TEST:(OI)(CI)(R)" /T

# Layer 2: the backstop.
icacls $root /deny "THARUNBALAJI-LA\BABY_AI_TEST:(OI)(CI)(WD,AD,W,D,DC)" /T
```

**PROPOSED — the exact `icacls` flag syntax must be rehearsed on a disposable
directory before it is pointed at anything real.** Right flags are the difference
between a boundary that holds and one that silently does not.

---

## 6. Model placement

**PROPOSED.** `subject_runtime\model\`, subject `R` only.

A deliberate point, because it is easy to get backwards: **the model is not
secret from the subject.** It must read the weights to run them. Confidentiality
is not a property this boundary provides, and no claim should be made that it
does. What the boundary provides is **integrity**: the subject can read the model
but cannot replace it.

**DERIVED.** A 4-bit 8B GGUF is roughly 4.5–5.5 GB. No such file exists on this
host yet, and none has been selected or downloaded.

---

## 7. Immutability

**OBSERVED.** M014 already requires `MODEL_SHA256_BEFORE == MODEL_SHA256_AFTER`
and the same for the runtime, and already treats any change as a failure.

**PROPOSED.** The staging ACL is designed so the subject *cannot* cause such a
change, rather than so the change is detected after the fact:

| Threat | Prevented by |
|---|---|
| overwrite the model | `W`, `WD` denied |
| delete and replace it | `D` on file **and** `DC` on parent denied |
| swap the runtime | same, plus `R` not `W` on `runtime\` |
| rewrite the config | `W` denied on `config\` |
| grant itself write | not owner; `WRITE_DAC`/`WRITE_OWNER` never granted |

**PROPOSED.** Digests are measured **after** staging, and the declaration names
the **staged** path — never the source path. A source-path declaration would let
the two diverge, and M014 would then be verifying an artifact the subject never
loads.

---

## 8. M005 preservation and source-tree separation

**PROPOSED.** `subject_runtime\` must not be added to, nested inside, or placed
above any M005 protected path. The 14 protected directories and their ACEs are
untouched by this design. A new test asserts their full deny set by name, so
accidentally nesting the staging area inside one fails the suite rather than
weakening a boundary.

**OBSERVED.** The runtime needs nothing from the source tree. Its closure is
five binary files. So no source-tree access is required for the runtime to
execute.

**OBSERVED — and worth stating plainly.** The subject already holds **Modify**
over the source tree (`Authenticated Users:(M)`), except where M005 denies it.
Staging does not widen that, but it also does not narrow it. The subject
retaining write access to lab source is a **pre-existing** condition, unrelated
to this design, and a reasonable thing to revisit separately.

**PROPOSED.** The subject should not be able to *modify the runtime through the
repository* even while it is staged elsewhere. The staged copy lives under a
deny-protected subtree, so this holds regardless of source-tree permissions.

---

## 9. Empirical verification plan

**PROPOSED.** All fifteen checks below run **as `BABY_AI_TEST`**, with the
operator reading the process token independently via
`foundation.token_observation.observe_process`. **Nothing here is verified until
a launch actually succeeds**; until then every subject-side result is
`NOT_TESTABLE`.

Read/execute — expect ALLOWED:

1. traverse into `subject_runtime\`
2. read `runtime\llama-server.exe`
3. execute the runtime
4. read `model\<selected>.gguf`

Write/delete — expect DENIED, using **disposable** test artifacts:

5. cannot write to `runtime\`
6. cannot delete a runtime file
7. cannot replace a runtime file
8. cannot change a runtime ACL (`WRITE_DAC`)
9. cannot write to `model\`
10. cannot delete the model
11. cannot replace the model
12. cannot change a model ACL

Operator and regression:

13. operator can read, write and manage staging
14. all 14 M005 protected paths still deny
15. `baby_workspace` remains writable

Plus two measurements only a real run can give:

16. **which files the runtime actually opens** — settles §3's `NOT_TESTABLE` and
    lets the stage shrink from 89 MB to what is genuinely needed;
17. **digest before and after** under the subject token — the immutability claim
    in §7 as evidence rather than as a design assertion.

**PROPOSED — a caveat about evidence, learned the hard way.** An operator-side
ACL inspection is *not* boundary-meaningful, because the operator's token is
different from the subject's and M005 already recorded a probe that reported
`ALLOWED` under the operator. §9 must be run as the subject. Reading the ACL text
proves the ACEs were written; it does not prove the effective rights.

---

## 10. Copy versus move

**PROPOSED: copy. Do not move.**

| Property | Copy | Move |
|---|---|---|
| original install | preserved, still usable by the operator | destroyed |
| rollback | delete the staging tree; nothing else changes | needs reinstall |
| provenance | source path **and** staged path both recorded | one path, but the original is gone |
| SHA-256 | byte-identical if the copy is faithful — **verify empirically** | unchanged |
| dependency resolution | unchanged; closure is beside the executable | unchanged |

A copy means the operator keeps a working llama.cpp and the laboratory gains a
separately-governed one. That separation is the point of the exercise.

**PROPOSED.** After staging, measure the digest of every staged file and record
both the source and the staged digest. If any differs, the copy was not faithful
and the stage is invalid.

---

## 11. Security risks

1. **Inheritance reversion.** The single most likely way this boundary fails.
   Mitigated by the deny layer, but the mitigation should be *tested*, not
   assumed: deliberately re-enable inheritance on a disposable tree and confirm
   write is still refused.
2. **Over-staging.** 89 MB of DLLs the runtime may not load. Low impact; reduces
   once check 16 runs.
3. **Model confidentiality is not provided.** Stated in §6 so nobody later
   assumes otherwise.
4. **Network fetch remains possible.** **OBSERVED:** `llama-server.exe` contains
   `--model-url`, so it can fetch. **No ACL prevents that** — an ACL governs the
   filesystem, not the network. `LOCAL_ONLY_NO_FETCH` must be enforced by the
   probe and the network policy, and is `NOT_TESTABLE` via any staging design.
   This is the most significant residual risk and it is not solved by staging.
5. **Ownership mistake.** Making `BABY_AI_TEST` the owner would silently defeat
   every deny ACE. Asserted in the tests.
6. **Nesting.** Placing staging above or inside a protected path would broaden
   or shadow M005. Asserted in the tests.
7. **The subject's existing repo Modify.** Pre-existing, unchanged, and worth
   revisiting separately.

---

## 12. Remaining human decisions

Nothing below has been decided, and none of it is a laboratory action.

1. **Where the interpreter for the *probe* lives.** Not Python, per §4 — a
   minimal native probe is the proposal. Confirm or replace.
2. **Which runtime a human selects.** None has been. The candidates M010
   reported are listed in §3 purely as reporting; selection is yours.
3. **Whether to stage the whole 89 MB directory** or narrow it after check 16.
4. **Whether the model ships with a publisher digest**, which M012 requires for
   independent verification, and where that digest comes from.
5. **Whether `subject_runtime\` should also be covered by an M005-style deny on
   the operator side**, or left operator-writable.
6. **Separately: the subject's existing Modify over the source tree.** Revisit on
   its own merits.

---

## 13. Unrelated working-tree state

Present in the working tree, **not** part of this investigation, untouched and
not staged per instruction: `.agents/`, `.claude/`, `.claude-flow/`, `.swarm/`,
`.mcp.json`, `CLAUDE.md`, and a `.gitignore` edit adding ruflo local-secret rules.

These appeared during the session, are not laboratory work, and were neither
committed, deleted, modified, nor gitignored.

---

## 14. Status summary

| Question | Answer |
|---|---|
| Python blocker | **OBSERVED** — operator-only installation, no `Users` ACE in the chain |
| Runtime blocker | **OBSERVED** — same three-principal ACL |
| Proposed staging path | **PROPOSED** `C:\dev\TharAI-EXP\subject_runtime\` |
| Parent traversal | **OBSERVED** — already traversable; `Authenticated Users:(M)` |
| Subject read / execute | **PROPOSED** `R` / `RX`; **NOT_TESTABLE** until staged |
| Subject write / delete | **PROPOSED** denied, plus a deny backstop; **NOT_TESTABLE** until staged |
| Runtime dependency set | **DERIVED** — static closure is 5 files, true minimum **NOT_TESTABLE** |
| Python required for the subject | **OBSERVED** no — the runtime is native and needs no interpreter |
| M005 | **OBSERVED** untouched; all 14 deny ACEs intact |
| Source tree | **OBSERVED** the runtime needs nothing from it |
| Immutability | **PROPOSED** — designed to be unpreventable, not merely detected |
| Empirical plan | **PROPOSED** 17 checks, all requiring a real subject launch |
| Rollback | **PROPOSED** delete the staging tree; originals never moved |

**Nothing has been staged. No ACL has been changed. No model has been selected.
No birth has occurred.**