# M015 Incident — Harness Write Isolation

**PRODUCTION_ACL_MUTATED_BY_THIS_TASK = NO**

The production staging boundary was destroyed by an M015/M016 test run. This
document records the corrected diagnosis, the structural fix, and what remains
open. Production is currently damaged and **has not been repaired** by this task.

## 1. Corrected diagnosis

An earlier statement in this investigation claimed that "an M015/M016 test calls
`apply_boundary()` against real production as part of test setup". **That was
wrong.** The audit establishes:

| function | call sites | argument | safe? |
|---|---|---|---|
| `apply_boundary()` | `test_staging_boundary.py:65` only | `tmp_path` | yes |
| `apply_subject_deny()` | `test_subject_deny.py` only | `scratch_root` (tmp) | yes |
| `_restore_dacls()` | `test_subject_deny.py` only | scratch snapshot | yes |

**`apply_boundary()` was not the production-writing mechanism.**

The real cause was three call sites that used production paths as test fixtures:

1. **`tests/test_boundary_harness.py:314`** — `harness_fixture` created and deleted
   `subject_runtime/runtime/m016_harness_fixture_<token>.exe`.
2. **`tests/test_boundary_harness.py:333`** — `_run_probe` created and `rmtree`'d
   `subject_runtime/config/m016_harness_delete_target`, including in a `finally`.
3. **`tests/test_m016_launch.py:354`** — wrote `subject_runtime/runtime/m016_control.exe`
   and invoked the **full subject probe** with `scratch=subject_runtime/config`.

Site 3 was the severe one. The probe runs as the operator and creates, appends,
renames, creates child directories and deletes objects in its scratch. The mutation
therefore happened inside a **child process**, which is why the usual reasoning —
"the Python test did not mutate production" — was true and irrelevant.

The original justification was *"a fixture this test invocation owns"* — ownership
by convention, with no enforcement. That is what produced the incident.

## 2. The fix: a central write-scoped mutation boundary

Two new modules:

- **`tests/path_policy.py`** — the canonical path policy. Derives the repository
  root from the environment (`BABYAI_REPO_ROOT`) or the package location, never a
  hardcoded user path. Canonicalises via `Path.resolve()`, which on Windows is
  non-strict, so a **nonexistent** future path inside production is still
  classified. Comparison is **component-wise and case-folded**, not string prefix.
- **`tests/guarded.py`** — every mutation-capable surface, each routing through the
  policy before any filesystem, ACL or subprocess operation:
  `make_fixture_file`, `make_fixture_dir`, `remove_tree`, `guarded_probe_argv`,
  `run_probe_guarded`, `apply_boundary_guarded`, `apply_subject_deny_guarded`,
  `restore_dacls_guarded`.

### Why a policy and not a wrapped global API

Monkeypatching `Path.mkdir` or `shutil.rmtree` process-wide would catch more call
sites, but it would also intercept pytest's own tmp_path handling and every
read-only inspection — producing confusing errors far from their cause. The
mutation surfaces are few and known, so guarding them explicitly is auditable, and
the audit test then asserts that **no other test helper mutates a repository path
unguarded**.

### Read versus write

Production **reads stay permitted**, and deliberately:

| helper | purpose |
|---|---|
| `read_production_for_verification(path)` | read-only; grants reading only |
| `assert_test_write_path(path)` | mutation; refuses the repository |

Read-only checks were kept because they are what **detected** the incident:
`test_m015_boundary_is_untouched`, `test_m015_boundary_still_verifies_after_m016_work`,
`test_principal_names_containing_spaces_survive`, `test_no_runtime_or_model_was_staged`.
Migrating them to a recorded snapshot was considered and **deferred**: if they go,
the next clobber is silent.

### The probe guard

`guarded_probe_argv` validates every mutation-capable path argument **before**
`build_probe_argv` produces an argv and **before** any process is launched. The
"the subprocess would do it instead" argument is exactly what caused the incident,
so the guard does not rely on the probe to protect itself.

Mutation-capable probe arguments: positional `scratch` (index 0), `staging_root`,
`acl_target`, `delete_fixture`. Pure-read arguments (`traverse`,
`traverse-leaf`, `enumerate_*`, `read_file`) are permitted against production.

## 3. A real bug in the guard, caught before it shipped

The first version of `MUTATING_PROBE_OPTIONS` used the **CLI flag spelling**
(`--delete-fixture`) while the guard looked values up by **builder keyword**
(`delete_fixture`). Every lookup missed, so the guard skipped **every** probe
option while still appearing to check them. A silent-passing guard is worse than
no guard, because it is mistaken for a control.

Caught by `test_mutating_probe_option_names_match_the_builder_keywords`, which
asserts the tuple against `inspect.signature(build_probe_argv)`.

## 4. Negative regression evidence

`tests/test_harness_write_isolation.py` — **33 passed**.

- Repository root, `subject_runtime`, `runtime`, `model`, `config`, and
  **nonexistent** descendants all refused.
- `C:\dev\TharAI-EXP-evil` (shares a string prefix) **accepted** by the policy layer.
- Relative paths, `.` / `..`, and mixed-case Windows paths covered.
- All nine mutation surfaces refused.
- **30 deliberate production-mutation attempts** across five targets, each
  refused before any work, with production fingerprints **identical afterwards** and
  path count unchanged. The test performs **no cleanup**, because a cleanup step
  would be indistinguishable from the repair that must not happen.

## 5. Second defect found: a BOM I introduced

The regex patch that threaded the tree fixture through the callers used
`Set-Content -Encoding utf8`, which wrote a UTF-8 BOM into
`test_boundary_harness.py`. `test_no_source_file_carries_a_utf8_bom` caught it.
Rewritten without a BOM; `test_host_readiness.py` now 48 passed.

## 6. Test results

| suite | result |
|---|---|
| `test_harness_write_isolation.py` | **33 passed** |
| `test_boundary_harness.py` + `test_m016_launch.py` + `test_probe_integrity.py` + `test_subject_deny.py` | 149 passed, 8 failed |
| full portable | **2017 passed, 16 failed**, 2 warnings, 749 subtests |

Failures outside the pre-existing 11-item baseline — **all read-only checks
correctly reporting the damaged production**:

```
test_boundary_harness.py::test_m015_boundary_is_untouched
test_m016_launch.py::test_m015_boundary_still_verifies_after_m016_work
test_staging_boundary.py::test_principal_names_containing_spaces_survive
test_subject_boundary_run.py::test_m015_boundary_untouched
test_subject_boundary_run.py::test_no_runtime_or_model_staged
test_subject_deny.py::test_verifier_reports_production_state_honestly
```

These are the alarm working. They are not harness regressions, and they must not be
"fixed" by repairing production from a test.

## 7. Production state

Unchanged by this task. Read-only fingerprint taken before and after the refusal
attempts and **identical**:

```
subject_runtime AU write ACEs : 1 (inherited from C:\dev\TharAI-EXP)
model\                        : absent
BABY_AI_TEST explicit ACEs    : 0
operator explicit ACEs        : 0
```

`PRODUCTION_RECOVERY_VERIFIED = NO` — unchanged, as expected.

## 8. Open items, in order

1. **Multi-level containment rehearsal** on a disposable tree mirroring the real
   `subject_runtime` shape (nested `config` descendant, three files under `runtime`).
   Containment and rollback are proven only for a single-level tree.
2. **Faithful restoration** from `prod_fingerprint_before.json`, fingerprint
   `02c5e4c473c2deacbbb8dd6636fb5ab7adfbc735f816fb1b9c2ede5da0bae54d`. Still
   blocked: no DACL-only write mechanism on this host avoids `SeSecurityPrivilege`.
   `apply_boundary()` is **not** an acceptable substitute — it would reconstruct
   rather than restore, and the recorded state includes `model\`.
3. ~~**Containment at production.**~~ **REJECTED — see
   `docs/evidence/m016-containment-rejected.md`.** The sequence previously recorded
   here as "mechanically available" is **unsafe and permanently rejected**:
   `/inheritance:d` collapses distinct Allow ACEs for the same principal, so the
   temporary operator FullControl ACE replaces the pre-existing inherited
   `0x00120089` operator ACE. Operator read access is destroyed at the freeze step,
   before AU removal. Do not apply this sequence. Replaced by a decision milestone
   between minimum blast radius and minimum deviation from the intended ACL model.

## 9. Post-audit: the guard's classification of probe arguments

The isolation work passed its own tests, but a later read of the **probe source**
found the guard was not the complete boundary it appeared to be.

`guarded_probe_argv` authorised the probe's positional slots 1–3 (`staged`,
`protected`, `workspace`) as read-only, on the reasoning that "the probe does not
write to them". The probe mutates all three:

| slot | probe behaviour | why it is WRITE |
|---|---|---|
| `staged` | `File.Copy` source, but with no `--staging-root` the destructive directory is `Path.GetDirectoryName(staged)`, then create / append / delete / rename / replace / child-create inside it | the argument selects a directory the probe mutates |
| `protected` | `File.SetAttributes(entries[0], FileAttributes.ReadOnly)` on the first child it enumerates | a mutation of an arbitrary child, not a read |
| `workspace` | `Touch`, read back, delete, then deleted again by the cleanup sweep | create + delete |

No current test passed production paths through these arguments, so this was **not**
the incident mechanism. But a guard that looks complete while having a hole is worse
than one that is visibly narrow, because it is mistaken for a control.

### The fix

Classification moved into `tests/path_policy.py` as
`PROBE_ARGUMENT_CLASSIFICATION`, keyed by `build_probe_argv` keyword, valued
`WRITE` or `READ_ONLY`, with `PROBE_MUTATION_EVIDENCE` naming the
`probe=<label>` operations that mutate each WRITE argument. The guard derives its
checks from that table rather than hardcoding slot indices, so a slot added or
reordered in the builder cannot fall out of the guard silently.

Two further changes make the classification auditable instead of asserted:

- **The classification is checked against the probe SOURCE.** Every label in
  `PROBE_MUTATION_EVIDENCE` must exist in `subject_probe.cs`, and each WRITE
  argument must have evidence recorded — a WRITE classification without evidence
  is an unreviewed guess. A new mutating operation added to the probe without a
  classification change therefore fails a test.
- **The three specific reasons are regression-tested.** `staged` must still be
  WRITE because `Path.GetDirectoryName(staged)` is still the destructive
  directory; `protected` must still match `File.SetAttributes(entries[0]`;
  `workspace` must still contain its write and delete. Otherwise somebody could
  "simplify" a classification back to READ_ONLY on the grounds that the file
  itself is only read.

Result: **63 passed** (`test_probe_argument_contract.py` 17,
`test_harness_write_isolation.py` 46). Every mutation-capable probe argument is
refused before launch, proven with a tripwire on `subprocess.run` rather than by
demonstrating the refusal with the real probe.

The four requirements the post-audit raised are covered: nonexistent, relative,
case-variant and prefix-similar-external paths each behave correctly, and
production is byte-identical before and after the negative tests.

## 10. Containment and rollback evidence

Rehearsals on disposable trees only; production never referenced.

- `/inheritance:r` **removes** inherited ACEs. Only the explicit operator ACE
  survived; SYSTEM and Administrators were lost. Invalid as a containment step.
- `/inheritance:d` **copies** inherited ACEs to explicit. AU, SYSTEM, Administrators
  and operator all became explicit; AU was then removable in isolation; the parent
  stayed byte-identical.
- Rollback `/inheritance:e` alone **leaves** the frozen explicit copies alongside
  newly inherited ones. Duplicates. Correctly gated as FAIL.
- Rollback `/inheritance:e` then removing SYSTEM, Administrators and operator
  explicit ACEs returns the child to a **byte-identical** fingerprint
  (`60be3c3a…`), repeated on a fresh tree. `ROLLBACK_FIDELITY = PASS`.