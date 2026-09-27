# Experiment log

Dated record of what was actually done, what was observed, and what was decided.
This is a research journal, not a changelog: it records reasoning and
observations, including the inconvenient ones.

---

## 2026-09-26 — Milestone 001: laboratory instrumentation

### Scope

Build the observation infrastructure for a future experiment on a self-hosted AI
system. No AI, no agent, no subject, no curriculum. The instrumentation and
nothing else.

### What was built

- Append-only, hash-chained event log at `var/events/events.jsonl`.
- HMAC-signed provenance ledger at `var/provenance/ledger.jsonl`, with
  key-derived authorship and sealed heads.
- Read-only terminal observer.
- Separate, authenticated control process with a lifecycle state machine.
- 189 tests, all passing.
- Windows scripts, eight documents, six ADRs, this journal.

### Decisions recorded

| ADR | Decision |
| --- | --- |
| 001 | Record decisions, not just code. |
| 002 | Standard library only at runtime. |
| 003 | HMAC now, Ed25519 **open** — depends on whether anyone outside this machine verifies the ledger. |
| 004 | No event taxonomy. A schema would be a curriculum, and a curriculum is an intervention on the observed system. |
| 005 | Runtime data under `var/`; secrets and data out of Git. |
| 006 | A seal is not a witness. |

### Design choices worth recording

**The first layout was wrong.** `events/` and `provenance/` were both package
and data directories, so `events/events.jsonl` sat beside `events/model.py`.
Importing a package could have mutated data, and a careless `rm events/*` would
have destroyed the source. Moved runtime data to `var/`. See `ADR-005`.

**Authorship is derived, never declared.** The obvious design — caller passes
`author="HUMAN"` — is worthless, because any code that can record an entry can
claim to be the human, and the ledger would faithfully record lies *with a valid
signature*. Authorship comes from a key ID resolved through the keyring. A
declared author that conflicts with the key is discarded and the conflict is
recorded as evidence.

**The observer deliberately cannot write anything.** The human's view of the
experiment should not be able to influence the experiment. There is no code path
in `observer/` that opens a file for writing or touches `provenance/`.

**`PAUSE` and `RESUME` do nothing, and say so.** They act on the control
process's own state and return a note explaining that no subject is attached
and no simulated behaviour was produced. A mock subject would have made the
first real observation of the real experiment untrustworthy.

**No `BABY_AI` key was provisioned.** There is no subject to own one.
Provisioning it would create a signing identity for a system that does not yet
exist.

### Problems found and fixed

| Found | Impact if unfixed | Fix |
| --- | --- | --- |
| `EventStore.append_many` was O(n²) | 20 000 events took 110 s | Head-entry cache keyed on file size. Now 16 s. |
| Namespaces over 11 characters broke column alignment | Ragged, hard to scan | `fit_category()` right-truncates to a fixed width |
| `latest_for_path` rescanned the whole ledger | Every version link was O(n) | Index cache; verification still reads from disk |
| A control snapshot label could contain `..` or a path separator | A write could escape `human_control/snapshots/` | Sanitise to `[A-Za-z0-9_-]`, cap at 48, plus a containment check |
| `…` rendered as `\ufffd` under PowerShell redirection | Corrupted research output | Force UTF-8 with `errors="replace"` |
| Control test client hit a TCP RST | Test could not read the error response it triggered | Half-close the write side before reading |
| Test fixture gained a step and broke absolute counts | False provenance failures | Assert on deltas against `baseline_entries` |

The encoding bug is the one worth dwelling on. The observer's job is to display
the record faithfully, and PowerShell 5.1's default code page silently corrupted
a character in that display whenever output was piped. A research instrument
that mangles its own output is worse than one that crashes, because the damage is
invisible.

### Security posture, stated plainly

| Tier | Status |
| --- | --- |
| 1. Application policy (`PathPolicy`) | **Active and tested** |
| 2. OS file permissions (NTFS ACLs) | **Scripted, NOT applied, NOT verified** |
| 3. OS account isolation / container | **Not implemented** |

Tier 2 could not be enabled in this environment:

```
IsAdmin(role): False
net user babylab_probe_xyz /add
  -> Access is denied.
```

So the honest summary is that only the weakest boundary is in force, and it is
bypassable by any process running as the same Windows user — which is currently
everything. This is recorded in `docs/security-model.md`, in the trust-boundary
script's own output, and in the completion report. It is not reported as
passing anywhere.

HMAC signing is symmetric, so the operator can forge entries for any role they
hold a key for. `ADR-003` is left **open** pending the answer to one question:
will anyone outside this machine ever verify this ledger?

### Verified

- 189 tests pass in ~48 s.
- `python -m provenance.cli verify` exits `0` on the live laboratory.
- Control process started, answered `status`, `inspect`, `pause`, `resume`,
  took a snapshot recorded in the ledger under the `SYSTEM` key, and shut down
  cleanly through `SHUTTING_DOWN`.
- Observer replays and follows; malformed lines are rendered, not swallowed.

### Not verified

- OS-level denial of writes to `human_control/`. Requires a second account.
- Any claim about a subject's behaviour. There is no subject.
- Behaviour under genuine multi-process contention. Thread concurrency is
  tested; process-level contention only via the manual run.

### Open questions for the human researcher

1. **Will anyone outside this machine verify the provenance ledger?** If yes,
   Milestone 002 should start by adopting Ed25519 (`ADR-003`).
2. **`LICENSE` copyright holder is a placeholder.** It needs a real name
   before anything is published.
3. **Is the seal worth an external witness?** (`ADR-006`) It requires a second
   party or an offline copy, so it cannot be set up alone.
4. **What service account name for tier 2?** `BABYAI` is a placeholder in the
   script.

---

## 2026-09-26 - Milestone 002: Cognitive State Observatory

### Scope

Build the instrument that observes a subject's reported cognitive state. No AI,
no subject, no credentials, no model, no memory, no curriculum, no autonomy.
The instrument and nothing else.

### What was built

- `observatory/` package: model, subject registry, attributor, incremental
  reader, state deriver, relationship graph, snapshot, renderer, live session,
  CLI. Ten modules, flat, following the convention of the existing packages.
- `status`, `state`, `live`, `history` subcommands, plus `--json`, `--detail`,
  `--no-color`, `--subject-namespace`, `--subject-label`.
- 181 new tests, 397 in total, all passing.
- Four documents, one ADR, this entry.
- One change outside `observatory/`: `provenance.cli record` learned to record
  modifications, deletions, and explicit overrides, because appending this
  section to a protected file is exactly the situation the audit exists to
  catch, and there was no supported way to answer it.

### The state of the instrument

```
  subject                 NO EXPERIMENTAL SUBJECT ATTACHED
                          Cognitive telemetry unavailable
  events ingested         18
  state versions          0
  reported domains        0
```

That is the whole of it, and it is the correct output. The Observatory renders
nothing, because there is nothing to render. `NO SUBJECT` is a result, not an
error state.

### Decisions recorded

| ADR | Decision |
| --- | --- |
| 007 | The Observatory is a read-only projection. Absence is a first-class value. Provenance is not identity. No decorative rendering. |

`ADR-003` was reopened and closed as **deferred**, recorded below.

### The four refusals

Worth recording because each was a point where the easy thing was to build
something that looked like a result.

**An unreported domain is not an empty one.** The specification's own example
settled it: `memory_activity: unavailable` is correct, `memory_activity: []` is a
lie. Rendering the second would let a reader conclude *the subject checked its
memory and found nothing*, when the truth is *the subject never said anything
about its memory*. The enforcement is in the type - `StateValue` cannot be
constructed in a state that would display an absence as a claim - so the
guarantee does not depend on a caller remembering to check.

**A subject cannot vouch for itself.** The temptation was to read
`Event.source` or a payload `author` field and call it the subject. Both are
written by whoever produced the event, and a future subject can write both, so
neither is evidence. Subject identity comes from the keyring or it does not
exist. There are tests in which an event's `source` is literally `baby_ai` and
its payload says `{"author": "BABY_AI"}`, and the Observatory still declines to
call them the subject's. This is the decision most likely to be quietly relaxed
later, so it is written into `ADR-007` rather than left implicit.

**There is no fixed pipeline.** No `perception -> memory -> context -> action`
chain. A subject reporting one domain produces exactly one node, and a domain
name the Observatory has never heard of is displayed rather than filtered.

**No brain picture.** A plain-text adjacency listing, because a listing cannot
be misread as an anatomical diagram. No psychological vocabulary appears
anywhere in the package, and a test fails the build if `readiness`, `confidence`,
`mood`, `curiosity`, `engagement` or `happiness` appears. The test looks
strange. It is there because the most likely future addition to this package is
a well-meant helpfulness field, and that would be an invention wearing a UI.

### The architecture questions, answered by the human researcher

Asked at the start of this milestone and recorded now:

1. **Will anyone outside this machine verify the ledger?** **Yes, eventually.**
   `ADR-003` is therefore **deferred, not open**: HMAC-SHA256 stays for now,
   Ed25519 is adopted before any external verification. The reopen condition is
   concrete - an independent party asked to verify, a second operator, or
   publication. No migration was performed in this milestone, because with no
   subject and no third party there is no ledger to re-sign and no assurance
   claim it would change.
2. **`LICENSE` holder.** Unresolved placeholder. Not published.
3. **External witness for the seal?** Not required for a first experimental
   run. `ADR-006` unchanged.
4. **Service account name.** Not created until a real subject exists. The target
   topology is recorded: human and control identities own the protected
   research data; the subject will eventually run under a separate OS account
   with a restricted workspace.
5. **How should a future subject be registered?** Deliberately left open. A
   registration mechanism is a future decision, and `SubjectRegistry` has no
   mutation method, so nothing can attach a subject by accident in the meantime.

### Problems found and fixed

| Found | Impact if unfixed | Fix |
| --- | --- | --- |
| `EventStore._parse_line` was private | The reader either reached into a private method or duplicated parsing, and two parsers would eventually disagree on the error message for the same corruption | Promoted to a public `parse_line`, with the old name kept as an alias |
| Liveness was `DERIVED` with no source events | Crashed on construction, or would have been fixed by citing a fabricated event | `UNAVAILABLE` with a note, which is the honest status for "attached but silent" |
| `display()` let a note override the placeholder | Prose in the value column, one refactor away from being read as data | Notes moved to the detail column only |
| `follow()` is an infinite generator | A `break` condition can never be satisfied; `poll()` would have spun forever | `poll()` does its own bounded read from the offset, which also handles torn writes properly |
| Reader re-walked the whole log on every refresh | Quadratic in a live session | Reader hands back the events it accepted via `drain_accepted()` |
| The CLI never loaded the keyring | A real subject could never be observed, only the absence of one | The CLI consults the keyring, as it must |
| A longer replacement log was invisible | A rotation would splice two logs and present them as one history | Detection uses file identity as well as size |
| Performance test timed appends as if they were reads | Concluded the reader was quadratic when it was measuring `fsync` | Writes pre-built and flushed outside the measured span |
| `provenance.cli record` could only record creations | Editing a protected file in an editor is normal, and the audit correctly reported it - but the only supported repair was to weaken the audit or leave verification failing | The command now derives the action per file from what the audit reports, with `--action` to override |
| `cmd_record` raised `NameError` on `--path` | A pre-existing bug: `Path` was never imported, and no test covered the branch, so the flag had never worked | Imported, and covered by CLI tests through the real `main` |
| The repair path matched on audit message wording | Rephrasing a human-readable message would silently break the thing that fixes the audit | `classify_problem` lives beside the messages that produce them, and is the only thing that reads the wording |
| Appending this entry left the journal with mixed line endings | The recorded digest was of CRLF bytes that `.gitattributes` (`eol=lf`) would never store, so a fresh clone would fail its own audit | Normalised to LF, then re-recorded. The committed blob is now byte-identical to the recorded file |

The last one is the most instructive. The first run of the performance test
showed 401 polls taking 102 s against a 0.5 s replay, which looked exactly like
the quadratic behaviour the test exists to catch. It was not. `EventStore.append`
fsyncs every line, so the test was measuring the disk. The fix was to time polls
separately from writes, and the same test then passed comfortably.

### Measured performance

| Workload | Result |
| --- | --- |
| Full ingest, 100,000 events | Passes a 120 s budget; whole performance module runs in ~14 s |
| 200 incremental polls over a 20,000-event log | Far under the cost of one full replay, confirming no per-poll re-read |
| 100 snapshot constructions | Under 5 s; a snapshot never scans the log |
| Full suite, 397 tests | ~91 s |

These are guards against a change in complexity class, not benchmarks to
optimise against. The thresholds are deliberately loose so a loaded machine does
not turn the suite red.

### Verified

- 397 tests pass; 216 pre-existing, 181 new.
- `python -m observatory.cli status`, `state`, `history`, and `live
  --iterations N` all exit `0` against the live laboratory.
- The live log holds 18 real infrastructure events. The Observatory reports them
  as `INFRASTRUCTURE` with their basis, and reports zero cognitive state.
- Structural read-only guarantee: the package contains no mutating call, no
  filesystem mutation, no `open()` for writing, and no network import.
- Behavioural read-only guarantee: a full ingest leaves the event log and the
  provenance ledger byte-identical and adds no ledger entries.
- Malformed lines, duplicate records, out-of-order events, a torn trailing
  line, and a rotated log are each handled and counted.
- `python -m provenance.cli verify` exits `0` against the live ledger: chain and
  MACs intact, seal valid, keyring valid, protected files matching. This entry
  was recorded as a `MODIFY` under the human key, not as a fresh `CREATE`, which
  is the point: the audit caught the edit and the supported repair path answered
  it without the audit being relaxed.
- The committed blob for this file is byte-identical to the bytes the ledger
  records, so a fresh clone on any platform passes its own audit.

### Not verified

- **OS-level denial of writes to `human_control/`.** Still Tier 1 only. Tier 2
  ACLs and a separate subject account remain unimplemented and require an
  elevated environment. Unchanged from Milestone 001.
- **Anything about a subject's cognition.** There is no subject. The state
  deriver's subject path is exercised only by tests that mint a key through the
  test fixture, never by the running system.
- **Multi-process contention on a live tail.** Thread-level behaviour is tested;
  two processes genuinely tailing one log is not.
- **The future web client.** The snapshot contract is defined and versioned; no
  client has been built against it, so the contract has not been validated by a
  second implementation.

### Deliberately not built

A model. An agent. A subject, a subject ID, a subject key, or a service account.
A `BABY_AI` role in the live keyring. A readiness score, a confidence value, a
mood, an engagement metric. A brain image, a neural animation, a pulse. Memory
or learning. A curriculum or developmental sequence. A web server or browser
client. A persistent derived-state store. An event taxonomy. Any write path
whatsoever.

Each of these was a place where a plausible-looking artefact would have been
easy to add and would have made the first real observation of a real subject
untrustworthy.

### Open questions for the human researcher

1. **Subject registration.** When a real subject exists, how is it registered,
   and which namespaces may it write under? `SubjectRegistry` is read-only and
   `--subject-namespace` is configuration, so nothing is decided yet. See
   `ADR-007`. **Partly answered in Milestone 003:** a `BABY_AI` signing key is a
   separate, deliberate act and the ceremony does not create one, so the registry
   reports `RECORDED` rather than `ATTACHED`. Which namespaces such a key may
   write under is still undecided.
2. **`LICENSE` copyright holder.** Still a placeholder. Blocks publication.
3. **Ed25519 timing.** Deferred per the decision above; the reopen condition is
   recorded, so this only needs revisiting when an independent party is involved.
4. **Tier 2 and the subject account.** Both need an elevated environment, and
   the subject account is not needed until there is a subject.

---

## 2026-09-27 - Milestone 003: birth, model identity, and a truthful display

### Scope

Allow a subject to be born, exactly once, from a model the human explicitly
configured and whose bytes were verified. Report that birth honestly in the
Observatory. Nothing else.

### What was built

- `birth/` package: configuration, model identity resolution, the runtime
  protocol, the llama.cpp subprocess adapter, the capability registry, the
  environment and workspace descriptions, the action boundary, the sealed birth
  record, the ceremony, and a read-only status module.
- `python -m birth.cli` with `status`, `model`, `capabilities`, `ceremony`, and
  `verify`, plus `python -m birth.real_model_test` for an explicit real-model
  check.
- 306 new tests, 703 in total, all passing.
- One new document and one new ADR: `docs/birth-architecture.md`,
  `docs/decisions/ADR-008-inherited-substrate.md`, and updates to
  `docs/architecture.md`, `docs/observatory.md`, `docs/observatory-api.md`, and
  this file.

### The decisions that mattered

**The laboratory never chooses a model.** `load_config` reads exactly one file.
No search, no fallback, no download. This was the milestone's most important
refusal and the one most likely to be quietly abandoned later, because a
self-selecting substrate is very convenient and the failure is invisible: two
runs of "the same" experiment quietly get different weights.

**The event is appended before the record is written.** The intuitive order —
write the record, then announce it by hash — fails under interruption in a way
that is hard to recover from. Writing the event first means a crash leaves an
event with no record: an announcement of a birth that did not happen. That is
detectable. The cost is that the event cannot carry the record's hash, so the two
artefacts reference each other by id instead, in the one direction that is
checkable.

**The record is written exactly once.** There is no `update_record`. The
provenance entry is a `CREATE` over the final bytes. Both were chosen so that no
code path exists which could rewrite a sealed birth.

**`birth.status` was split out of `birth.service`.** The Observatory has to
display whether a subject exists, and the function that knows is the ceremony,
which holds the event-append path. Importing it for a read would have handed a
read-only component the ability to write. The split makes the guarantee
structural, and `ObservatoryImportClosureTests` walks the import graph to keep it
that way — including a check that `birth.service` genuinely *does* reach the
event store, so the test cannot pass vacuously.

**A recorded subject is not an attached subject.** A ceremony writes a record and
does not provision a signing key. Those are different grants: a record says a
subject was created, a key says it can prove things. Rounding the first up to the
second would tell a reader the subject can author events. It cannot. The display
says `SUBJECT RECORDED, NOT KEY-ATTACHED` in those words.

**`RUNTIME_UNVERIFIED` was added because the read-only path found a real
overclaim.** `resolve_model_identity` returned `READY` when no runtime probe was
supplied — which is exactly the case the Observatory always hits, since running a
binary is not a read-only act. A display showing `READY` would be telling a
reader the model is usable when no process had run it. There is now a status for
"weights verified, runtime unchecked", and `birth_status` reports
`model_installed` and `model_usable` separately. A related incoherence was fixed
at the same time: with a record present, the detail line was still quoting the
unprobed inspection, so the display could print `READY` and "the runtime was NOT
checked" in adjacent lines.

### A note on testing without lying

The suite must be able to produce a successful birth, and must not be able to
produce a fake one that looks real. Weights are real bytes with their real
SHA-256, so every digest and integrity check runs for real. The runtime is
**injected as a call argument**, never configured.

That distinction is the whole point. Pointing a configuration at a fake runtime
would write a lie into an immutable artefact — a permanent record describing a
test double as a real substrate. Injecting availability instead leaves the sealed
record describing a real runtime and puts the falsification in the test's own
call site. The ceremony's refusal of `RuntimeKind.FAKE` is unconditional and does
not consult the probe, so no fixture can route around it. This lives in
`tests/birth_fixtures.py` so there is one definition of it.

### A bug found by looking at the output

The `RUNTIME_UNVERIFIED` problem was not found by a test. A passing test asserted
`inspect()` returned `READY`, and that assertion was itself the bug: it encoded
the overclaim as expected behaviour. It was found by printing the display and
reading it. Tests confirm that a value is what the code produces; only reading
the output reveals whether that value is the right claim to be making.

A second, smaller one came from the same exercise: the label `environment
attached` overran the renderer's 18-character column and printed as
`environment attachedno`.

A third was found after the milestone was committed, by reviewing the commit
against the documentation rather than against the tests. The `ATTACHED` subject
state keyed off the keyring alone, while three documents claimed it required a
birth record *and* a key. Both could not be true, and the documentation's rule
had no state at all for a key with no record — it would have reported a live
signing key as `NO_SUBJECT`.

The code was right and the prose was wrong, for a reason worth stating: a signing
key that exists must never be hidden, because hiding it would understate the
system's authority. So `ATTACHED` still keys off the keyring, and the missing
record is now reported rather than assumed. `observatory.subject.UNRECORDED_DETAIL`
covers it, symmetric with `RECORDED_DETAIL` for the opposite mismatch. `detail`
is `null` only when a subject is both recorded and attached.

Two tests had encoded the wrong behaviour rather than the right one.
`test_dict_omits_detail_when_attached` asserted that a key-attached subject
reports no detail, which is precisely the overclaim; and
`test_a_key_without_a_record_is_still_attached_not_recorded` passed a *populated*
birth payload, so it never tested the case in its own name. The first was the
same failure mode as the `READY` bug: a green test asserting something that
should not have been true. Both are now fixed, and the second has two
companions covering the recorded, unrecorded, and fully-attached cases.

The lesson generalises past this milestone. A test suite verifies that the code
does what the code does. It cannot verify that the code is claiming the right
thing, and a test written to match observed behaviour will happily lock in an
overclaim. The only reliable check found so far is to read the output and ask
what a human would conclude, and to compare the documentation against the
implementation rather than assuming the two were written from the same
understanding.

Applying that check to the fix found a fourth defect, immediately. The new
`UNRECORDED_DETAIL` existed in the data model and was asserted by unit tests, and
never reached the screen. `ObservatoryRenderer.header` printed `subject_detail`
only inside its `no_subject` branch; every other state got the banner alone. So
`RECORDED_DETAIL` had been silently dropped from the display since the day it
was written, and the whole point of the `RECORDED` state — that a human reading
the terminal learns the subject cannot sign — was being lost at the last metre.

Nothing caught it because every test that mattered checked the model rather than
the rendered text, and the one test that checked rendering
(`test_telemetry_unavailability_is_stated`) was in the `no_subject` branch, the
single place the code worked. The new test asserts the detail reaches the
rendered output, and was confirmed to fail when the fix is reverted.

All four defects share a shape: an honest value that existed, was correct, and was
never actually seen by a reader. The model was right and the screen was wrong;
the test was green and the prose was wrong. Recording them here because the
pattern is more likely to recur than any individual bug, and the only thing that
has caught them so far is deliberately reading the output rather than the code.

### Verified

- 703 tests pass; 397 pre-existing, 306 new. The 397 baseline was re-measured
  against commit `2d5ea3d` in a detached worktree rather than assumed.
- `python -m birth.cli status` exits `0` and reports `NOT_CONFIGURED` against the
  live laboratory, creating nothing.
- `python -m birth.cli ceremony` exits `1`, reports `NOT_CONFIGURED`, and creates
  no event, no birth record, and no provenance entry. The live log still holds
  its 18 events.
- `python -m birth.real_model_test` exits `1` and reports `NOT_CONFIGURED`, with
  `UNAVAILABLE` for the model, digest, configuration hash, runtime, backend,
  token counts, and timings. No number is zero and none is estimated.
- The ceremony's negative cases are covered end to end: no configuration, no
  weights, wrong digest, missing runtime, and a fake runtime. Each produces no
  record, no event, and no ledger entry.
- A full ceremony produces exactly one event, one record write, and one signed
  `CREATE` provenance entry, and the record's own hash verifies afterwards.
- The Observatory cannot reach a write path, checked by import closure from
  three entry points, with a non-vacuity check.
- `python -m provenance.cli verify` exits `0`: chain and MACs intact, seal valid,
  keyring valid, protected files matching. This entry was recorded as a `MODIFY`
  under the human key, not as a fresh `CREATE`.

### Not verified

- **The ceremony against a real model.** No llama.cpp binary and no GGUF weights
  are installed. Every successful birth in this milestone was produced by a test
  with an injected runtime probe. The adapter, the parser, and the ceremony are
  tested; the combination has never run against real weights on this machine.
  This is the largest gap in the milestone and it is a hardware-and-weights gap,
  not a code gap.
- **Any generation metric.** Prompt tokens, output tokens, backend, and timings
  are `UNAVAILABLE`, and the report says so rather than reporting zero.
- **GPU execution.** The GPU is present and is reported by name and VRAM. No
  model has been loaded onto it.
- **OS-level denial of writes to `human_control/`.** Still Tier 1 only,
  unchanged. Now more consequential: a ceremony writes to a protected area, so
  the gap between "the code enforces this" and "the operating system enforces
  this" is wider than it was.
- **Subject authorisation of its own writes.** No `BABY_AI` key exists, so the
  path from "subject exists" to "subject authors an event" is untested in the
  running system.
- **A recorded subject's own event attribution.** `RECORDED` is exercised only
  by tests. No real laboratory is in that state.

### Deliberately not built

A model choice of any kind. A model download, search, or fallback. A baby AI
key — the ceremony does not provision one. Any capability implementation: all
are `UNAVAILABLE` or `NOT_YET_IMPLEMENTED`. Any stage, curriculum, or
developmental sequence. Any claim of consciousness, sentience, emotion,
motivation, curiosity, preference, personality, or memory. Any intelligence or
readiness score. Any claim of `BABY_AI_AUTHORED` — the only classification is
`INHERITED_PRETRAINED`. An update or rewrite path for the birth record. Any
process-level or OS-level isolation. Any second birth.

### Open questions for the human researcher

1. **Which model, and is it a decision you want to make now?** The ceremony
   cannot run until a llama.cpp binary and a specific GGUF file with a recorded
   digest are chosen and placed. Nothing will choose them.
2. **Digest provenance.** `model_sha256` must be a value you obtained, not one
   this machine produced. Where do the real digests come from — the publisher, a
   known-good manifest, or your own download-time measurement?
3. **Namespace policy for a `BABY_AI` key.** Carried over from Milestone 002 and
   now slightly more urgent: a subject will exist before it can write, and the
   namespaces it may write under are still undecided.
4. **Whether `RECORDED` is the right state to ship in.** It is the honest
   description, but it does mean the default display says a subject exists and
   has said nothing. Confirm that is the presentation you want.
5. **`LICENSE` copyright holder, Ed25519 timing, and Tier 2.** All carried
   forward unchanged.

---

## 2026-09-27 — Milestone 005: ACL boundary audit and a recovery defect

### The reported discrepancy

A cross-process probe run as `BABY_AI_TEST` successfully created
`provenance/m005_os_denial_probe.txt`, and `icacls` showed no `BABY_AI_TEST`
deny ACE on `provenance/`. It was reported that this disproves the earlier
claim that 11/11 protected paths carried effective deny ACEs.

### What direct filesystem evidence actually showed

Auditing all 13 canonical protected paths with `icacls` directly:

- **11/11 existing protected paths DID carry an explicit
  `THARUNBALAJI-LA\BABY_AI_TEST:(DENY)(W)` ACE.** The boundary was present.
- 2 paths were absent (`human_control/birth_records`,
  `human_control/experiment_config/foundation.json`), so no ACE could exist.

**The conclusion drawn from the probe was wrong; the observation about the
boundary was right.** The probe succeeded because it targeted the wrong path.
`provenance/` at the repository root is the **Python source package**
(`keyring.py`, `ledger.py`, `recorder.py`, `cli.py`) that *implements*
provenance. The canonical protected provenance *evidence* is
`var/provenance/ledger.jsonl` and `human_control/provenance/`. A successful
write into a code directory is evidence that the code directory is unprotected,
not that the evidence boundary is absent. `babylab/paths.py` already documents
this deliberate split so data and Python packages do not share a namespace.

The earlier 11/11 claim is therefore **upheld**, not disproven. Recorded
because the intermediate conclusion ("the boundary is gone") was wrong, and
re-deriving it incorrectly later would be worse.

### A real gap the probe did surface

`provenance/` holds executable code implementing the evidence system, and that
code is writable by the subject account. That is a genuine policy question —
the subject could edit the code that judges it. It is NOT part of the canonical
M005 protected set, and widening the set is a policy decision for the human
researcher, not something to change silently mid-audit. **Left unchanged and
raised here.**

### A real defect: recovery silently destroyed the boundary

`scripts/restore_permissions.ps1 -Restore` runs `icacls /reset` on every
recorded path, stripping explicit deny ACEs, then re-applies only the EXPLICIT
entries present in the snapshot. The milestone's default snapshot
(`var/acl-snapshots/protected-paths.json`) was captured **before** the boundary
was applied and contains **zero** deny entries. Restoring from it therefore
removed the security boundary while still printing "Restored N path records".

Reproduced in an isolated sandbox (never against the real boundary): the deny
ACE count went 1 -> 0 on `human_control`, and the script reported success. The
file `var/provenance/ledger.jsonl` kept its deny only because it is a file
absent from the snapshot's directory list, so `/reset` never touched it — an
accident of layout, not a safeguard.

**This is the mechanism by which a recovery operation could have destroyed the
boundary without anyone noticing.** The earlier "recovery round-trip verified"
claim used a purpose-built snapshot that already contained the deny ACE, so it
exercised the happy path and missed this entirely.

### Fixes applied

1. `-Restore` now captures live `BABY_AI_TEST` deny ACEs **before** `/reset`,
   re-applies them afterwards, and reports
   `Post-restore check: N path(s) still carry a BABY_AI_TEST deny ACE.` A
   restored path count is no longer presented as evidence of protection.
2. `-Restore` now **deduplicates** explicit ACEs. `icacls /deny` appends rather
   than replaces, so repeated application had left duplicate deny ACEs on 4
   paths, and every recovery would have compounded them. Collapsed to exactly
   one deny ACE per protected path.
3. New regression coverage in `tests/test_m005_acl_recovery.py` (portable, 7
   tests) pins the defect, the fix, and the result taxonomy, so a future
   recovery or configuration operation cannot report protection that the
   filesystem does not have.

### What remains unproven

The recovery round-trip is now verified, and the boundary is confirmed present
by direct `icacls`. **No cross-process operation was executed by this
process.** Its token is Medium integrity (S-1-16-8192), elevation type Limited,
and `SeImpersonatePrivilege` is absent and cannot be enabled
(`ERROR_NOT_ALL_ASSIGNED`, 1300). It therefore cannot obtain a `BABY_AI_TEST`
token, and it must never handle that account's password.

`OS_DENIED` and subject workspace `ALLOWED` both remain **NOT_TESTABLE** from
here. `OS_ISOLATION = NOT_IMPLEMENTED`; `BIRTH SAFETY GATE = BLOCKED`. No
model, no `BABY_AI` key, no birth, no autonomous process. M006 not started.

