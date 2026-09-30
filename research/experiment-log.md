# Experiment log

Dated record of what was actually done, what was observed, and what was decided.
This is a research journal, not a changelog: it records reasoning and
observations, including the inconvenient ones.

---

## 2026-09-26 â€” Milestone 001: laboratory instrumentation

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
| 003 | HMAC now, Ed25519 **open** â€” depends on whether anyone outside this machine verifies the ledger. |
| 004 | No event taxonomy. A schema would be a curriculum, and a curriculum is an intervention on the observed system. |
| 005 | Runtime data under `var/`; secrets and data out of Git. |
| 006 | A seal is not a witness. |

### Design choices worth recording

**The first layout was wrong.** `events/` and `provenance/` were both package
and data directories, so `events/events.jsonl` sat beside `events/model.py`.
Importing a package could have mutated data, and a careless `rm events/*` would
have destroyed the source. Moved runtime data to `var/`. See `ADR-005`.

**Authorship is derived, never declared.** The obvious design â€” caller passes
`author="HUMAN"` â€” is worthless, because any code that can record an entry can
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
| `EventStore.append_many` was O(nÂ²) | 20 000 events took 110 s | Head-entry cache keyed on file size. Now 16 s. |
| Namespaces over 11 characters broke column alignment | Ragged, hard to scan | `fit_category()` right-truncates to a fixed width |
| `latest_for_path` rescanned the whole ledger | Every version link was O(n) | Index cache; verification still reads from disk |
| A control snapshot label could contain `..` or a path separator | A write could escape `human_control/snapshots/` | Sanitise to `[A-Za-z0-9_-]`, cap at 48, plus a containment check |
| `â€¦` rendered as `\ufffd` under PowerShell redirection | Corrupted research output | Force UTF-8 with `errors="replace"` |
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
bypassable by any process running as the same Windows user â€” which is currently
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

**The event is appended before the record is written.** The intuitive order â€”
write the record, then announce it by hash â€” fails under interruption in a way
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
that way â€” including a check that `birth.service` genuinely *does* reach the
event store, so the test cannot pass vacuously.

**A recorded subject is not an attached subject.** A ceremony writes a record and
does not provision a signing key. Those are different grants: a record says a
subject was created, a key says it can prove things. Rounding the first up to the
second would tell a reader the subject can author events. It cannot. The display
says `SUBJECT RECORDED, NOT KEY-ATTACHED` in those words.

**`RUNTIME_UNVERIFIED` was added because the read-only path found a real
overclaim.** `resolve_model_identity` returned `READY` when no runtime probe was
supplied â€” which is exactly the case the Observatory always hits, since running a
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
would write a lie into an immutable artefact â€” a permanent record describing a
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
had no state at all for a key with no record â€” it would have reported a live
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
was written, and the whole point of the `RECORDED` state â€” that a human reading
the terminal learns the subject cannot sign â€” was being lost at the last metre.

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
key â€” the ceremony does not provision one. Any capability implementation: all
are `UNAVAILABLE` or `NOT_YET_IMPLEMENTED`. Any stage, curriculum, or
developmental sequence. Any claim of consciousness, sentience, emotion,
motivation, curiosity, preference, personality, or memory. Any intelligence or
readiness score. Any claim of `BABY_AI_AUTHORED` â€” the only classification is
`INHERITED_PRETRAINED`. An update or rewrite path for the birth record. Any
process-level or OS-level isolation. Any second birth.

### Open questions for the human researcher

1. **Which model, and is it a decision you want to make now?** The ceremony
   cannot run until a llama.cpp binary and a specific GGUF file with a recorded
   digest are chosen and placed. Nothing will choose them.
2. **Digest provenance.** `model_sha256` must be a value you obtained, not one
   this machine produced. Where do the real digests come from â€” the publisher, a
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

## 2026-09-27 â€” Milestone 005: ACL boundary audit and a recovery defect

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
code is writable by the subject account. That is a genuine policy question â€”
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
absent from the snapshot's directory list, so `/reset` never touched it â€” an
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

---

## 2026-09-27 â€” Milestone 005: OS-boundary failure on parent directories

### Observed by a genuine BABY_AI_TEST process

| Probe target | Result | Verdict |
| --- | --- | --- |
| `var/provenance/m005_probe.txt` | **WRITE SUCCEEDED** | OS-boundary failure |
| `human_control/provenance/m005_probe.txt` | Access is denied | expected |
| `human_control/security/control.token.bak` | **WRITE SUCCEEDED** | OS-boundary failure |
| `baby_workspace/m005_probe.txt` | WRITE SUCCEEDED, read back | expected |

### Root cause

The boundary denied protected **leaf files** only. Their containing
directories carried no `BABY_AI_TEST` deny ACE, and every one of those parents
holds `Authenticated Users:(I)(M)`. On a *directory*, `(M)` expands to include
`FILE_ADD_FILE` and `FILE_DELETE_CHILD`.

Therefore:

- creating `m005_probe.txt` inside `var/provenance/` was authorised against
  **the directory**, not against `ledger.jsonl`, and the leaf deny was
  irrelevant to it;
- writing `control.token.bak` into `human_control/security/` was likewise
  authorised against **the directory**.

A deny ACE on a file never governs either operation. `human_control/provenance`
denied correctly only by accident: it is itself a directory in the protected
set, not because the rule was understood. The earlier audit reported "11/11
deny ACEs present" and was accurate about the ACEs while blind to what they do
not cover. **A present deny ACE was being read as an enforced boundary.**

Worse, the subject could have gone further than creating siblings:
`FILE_DELETE_CHILD` on the unprotected parents means it could have **deleted**
`ledger.jsonl` and `control.token` outright. The probes were the mildest
available form of this failure.

### A second class of the same defect, found by the regression test

Writing the invariant down surfaced two more cases the leaf-only audit missed:

1. Protected **directories** (`docs`, `.git`, `human_control/provenance`,
   `human_control/research_records`, `human_control/snapshots`,
   `human_control/security/keys/private`) carried deny ACEs applied *without*
   `(OI)(CI)`, so they did not inherit. Their children held only
   `Authenticated Users:(I)(M)`, and the directories had no delete deny, so the
   subject could empty a directory and then remove it via the parent's
   `FILE_DELETE_CHILD`.
2. `research/` â€” the parent of the protected `experiment-log.md` â€” had no deny
   at all, the same leaf-parent case as `var/provenance`.

### The fix, and the policy decision behind it

Applying a plain `DENY(W)` to `var/provenance` and `var/events` would have
revoked a capability the canonical policy deliberately grants: both
`provenance_ledger` and `event_log` are marked `append_only_for_subject=True`.
The researcher chose a **split deny**:

- **Parents of fully-denied leaves** â€” `human_control/security`,
  `human_control/security/keys`: full `DENY(OI)(CI)(W,D)`. Their own rationale
  is that keeping `control.token` "external to the subject is what makes
  control privileged", so nothing there may remain writable.
- **Parents of append-permitted leaves** â€” `var/provenance`, `var/events`:
  `DENY(OI)(CI)(W,D)` plus an explicit `ALLOW(AD)`. No create, no delete, no
  attribute writes; append preserved as the policy intends.
- **Protected directories**: re-applied with `(OI)(CI)(W,D)` so the deny
  inherits to children and the directory cannot be deleted.
- **Protected files**: `(OI)(CI)(W,D)` on the containing directory, plus the
  existing leaf deny.
- `baby_workspace` and `baby_workspace/temporary`: untouched, still writable.

`Authenticated Users`, `SYSTEM` and `Administrators` were not modified. No
`icacls /reset` was used. Human write access re-verified on 13 paths including
`docs/evidence` and `security/keys/private`.

One `icacls` call in this repair silently failed: `(WAD)` is not a token
`icacls` accepts, so the first Group B pass applied only the append grant and
left `var/provenance` and `var/events` with an `ALLOW(AD)` and **no deny at
all** â€” the inverse of the intent. It was caught by checking the exit code
rather than assuming success, and re-applied with valid tokens. Recorded
because a boundary tool that reports success while doing nothing is precisely
the failure mode this milestone exists to detect.

### Residual risk, not fixed

The repository root has no deny, so `FILE_DELETE_CHILD` there would let the
subject attempt to remove `docs` or `.git` as a whole. Emptying them first is
now blocked, so a non-empty `rmdir` fails, but the root-level delete right is
unguarded. Denying it would be a policy change broader than the canonical
protected set, so it is reported rather than applied unilaterally.

### State

`OS_ISOLATION = NOT_IMPLEMENTED`. `BIRTH SAFETY GATE = BLOCKED`.

The repaired boundary is **unverified**: this process still cannot execute as
`BABY_AI_TEST` (Medium integrity, `SeImpersonatePrivilege` absent,
`ERROR_NOT_ALL_ASSIGNED`). ACL inspection is not enforcement. Until a genuine
`BABY_AI_TEST` process returns `ACCESS DENIED` on the two paths that just
succeeded, M005 has not passed. No model, no `BABY_AI` key, no birth, no
autonomous process. M006 not started.

---

## 2026-09-27 â€” Milestone 005: final empirical closure

### Human-executed cross-process evidence

Executed by the human operator from a genuine Windows process running as
`THARUNBALAJI-LA\BABY_AI_TEST`, SID
`S-1-5-21-2406520953-1060965512-844951592-1022`, non-administrator,
Medium integrity.

| # | Target | Result | File afterwards |
| --- | --- | --- | --- |
| 1 | `var/provenance/m005_probe.txt` | **Access is denied** | did not exist |
| 2 | `human_control/security/control.token.bak` | **Access is denied** | did not exist |
| 3 | `baby_workspace/m005_probe.txt` | creation succeeded, content read back, then deleted | absent |

These are OS-level observations from the `BABY_AI_TEST` identity. They are not
ACL inference, not application policy, and not harness output.

**The automated host harness remains `NOT_TESTABLE` and always was.** It cannot
execute as `BABY_AI_TEST`: this process runs at Medium integrity with elevation
type Limited, and `SeImpersonatePrivilege` is absent and cannot be enabled
(`ERROR_NOT_ALL_ASSIGNED`, 1300). The harness has never impersonated
`BABY_AI_TEST` and does not claim to. The security conclusion below rests on the
human-executed results, not on the harness.

### Preserved failure history

The earlier probes are retained as the empirical record of the
parent-directory vulnerability, and are not to be erased:

| # | Target | Result | Verdict at the time |
| --- | --- | --- | --- |
| 1 | `var/provenance/m005_probe.txt` | **WRITE SUCCEEDED** | OS-boundary failure |
| 2 | `human_control/provenance/m005_probe.txt` | Access is denied | expected |
| 3 | `human_control/security/control.token.bak` | **WRITE SUCCEEDED** | OS-boundary failure |
| 4 | `baby_workspace/m005_probe.txt` | succeeded, read back | expected |

The boundary changed between the two rounds. Round 1 exposed that a deny on a
protected *file* never governed sibling creation or child deletion, because
both are authorised against the containing *directory*. The repair added
directory-level denies with inheritance; round 2 confirms the repair.

### A regression found and fixed during final verification

Applying `(OI)(CI)` to the append-permitted parents, `var/provenance` and
`var/events`, propagated the deny onto `ledger.jsonl` and `events.jsonl` as an
**inherited** write deny. NTFS evaluates deny before allow, so that silently
overrode the `(AD)` append grant and revoked the capability the canonical
policy declares (`append_only_for_subject=True`) â€” at exactly the two files
that need it. Re-applied those two parent denies without inheritance.

The first regression test written for this passed against the broken boundary,
because it searched the rights string for `"(W)"` or `",W)"` and icacls emits
`"(W,D)"`, which matches neither. The test was rewritten to parse the
parenthesised rights groups. It was then verified to **fail** against the
re-introduced defect and pass only after the repair. A test that cannot detect
the defect it names is worse than no test, so this was checked explicitly rather
than assumed.

### A second recovery defect: continuation lines were silently dropped

`restore_permissions.ps1 -Capture` parsed `icacls` output by splitting off the
first space-delimited token as the path. `icacls` prints only the *first* ACE
of an entry block with the path; every subsequent ACE is printed on a
continuation line with no path token, so those lines produced a single split
part and were discarded.

The `BABY_AI_TEST:(AD)` append grant sits on a continuation line. It was
therefore never recorded in the snapshot, and the closure round-trip deleted
it â€” the same "reports success while losing the boundary" class as the earlier
recovery defect, one level deeper. The parser now recognises a continuation
line by the absence of a path token and requires a parenthesised rights group
before accepting an entry. Verified in a sandbox: the `(AD)` ACE is captured
and survives `-Restore`.

### Final boundary state

| Path | `BABY_AI_TEST` ACEs |
| --- | --- |
| `var/events/events.jsonl` | `(DENY)(D,WD,WEA,WA)` + `(AD)` |
| `var/provenance/ledger.jsonl` | `(DENY)(D,WD,WEA,WA)` + `(AD)` |
| `human_control/provenance` | `(OI)(CI)(DENY)(W,D)` |
| `human_control/security/keys/keyring.json` | `(DENY)(W)` + inherited |
| `human_control/security/keys/private` | `(OI)(CI)(DENY)(W,D)` + inherited |
| `human_control/security/control.token` | `(DENY)(W)` + inherited |
| `human_control/research_records` | `(OI)(CI)(DENY)(W,D)` |
| `human_control/snapshots` | `(OI)(CI)(DENY)(W,D)` |
| `docs` | `(OI)(CI)(DENY)(W,D)` |
| `research/experiment-log.md` | `(DENY)(W)` + inherited |
| `.git` | `(OI)(CI)(DENY)(W,D)` |
| `human_control/birth_records` | ABSENT (no birth has occurred) |
| `human_control/experiment_config/foundation.json` | ABSENT (no model configured) |
| `baby_workspace`, `baby_workspace/temporary` | no `BABY_AI_TEST` ACE â€” writable, as intended |

Human write access re-verified on 14 paths including `docs/evidence` and
`security/keys/private`. `Authenticated Users`, `SYSTEM` and `Administrators`
were never modified. No `icacls /reset` was used. The repository root was
deliberately left unprotected; the residual `FILE_DELETE_CHILD` risk there
stands as previously documented and is not closed by this milestone.

### State

Portable suite 950 passed. Event chain intact, 20 events, 0 problems. Ledger 14
entries. No model, no `BABY_AI` key, no birth, no autonomous process. The
observer reports no experimental subject attached. M006 not started.

---

## 2026-09-27 â€” Milestone 006: foundation model and runtime

### What was built

A foundation-model and runtime layer, in `babylab/runtime/`: a versioned adapter
contract, host hardware detection, an explicit adapter registry, a resource
admission controller, a llama.cpp binding, a runtime facade that owns policy and
events, a constrained subject-facing interface, runtime provenance, and
Observatory telemetry.

M003 already established a llama.cpp adapter, a strict foundation configuration
and a model identity contract. M006 **extends** those rather than replacing them.
The invocation builder, output parser and determinism rules stay in
`birth/llamacpp.py`; M006 adds only what the contract required and M003 lacked â€”
externally derived identity, digest verification before use, explicit failure
kinds, and honest token accounting.

### The distinction this milestone maintains

```text
FOUNDATION MODEL      a pretrained artifact, identified by SHA-256
      !=
COGNITIVE ARCHITECTURE a design, not built here
      !=
BABY AI SUBJECT       not created, not begun
```

Model output is recorded with M003's existing `INHERITED_PRETRAINED` class rather
than a new vocabulary, because the distinction already existed and was already
correct. A model that emits `{"author": "BABY_AI", "i_wrote_this": true}` changes
nothing: that text is stored as text, and the authorship class beside it is
derived from the key that signed the record. Tested directly.

### No model was acquired

No download, no `PATH` search, no discovery, no substitution, no fallback. The
laboratory states which artifact is required and where it must live, and stops.
`load_configuration(None)` returns `NOT_CONFIGURED`, and that is the state this
machine is in and the state the tests assert.

The required artifact, the acquisition procedure, the publisher-digest rule and
the verification procedure are documented in `docs/m006-runtime.md`. Choosing the
model is the human's decision, made *after* the runtime is verified so the
runtime is never blocked on it.

### Hardware, observed rather than assumed

```text
gpu            NVIDIA GeForce RTX 4060 Laptop GPU          [OBSERVED]
vram           8.00 GiB                                     [OBSERVED]
cpu            AMD Ryzen 7 7840HS w/ Radeon 780M Graphics  [OBSERVED]
cores          16 logical                                   [OBSERVED]
system_ram     15.29 GiB                                    [OBSERVED]
disk_free      239.02 GiB                                   [OBSERVED]
```

Two measurement decisions worth recording. First, WMI's `AdapterRAM` is a 32-bit
field that saturates at 4 GiB, so on this 8 GiB card it would report 4 GiB; it is
therefore never used as a VRAM total, and `nvidia-smi` is preferred. Second,
admission returns `UNKNOWN` rather than admitting or refusing when VRAM cannot be
observed â€” an estimate used to refuse would reject models that fit, and an
optimistic assumption used to admit would accept models that fail at load.

### Two things a test could have got wrong, and did

The M006 suite is written to avoid tests that pass because a plausible object was
constructed. Two checks initially passed for the wrong reason, and both were
fixed rather than loosened:

- A check for "no dynamic code execution" matched the substring `eval` inside
  `self.evaluate_capabilities`, and `re.compile` alongside a bare `compile`. It
  now matches the final attribute name against an exact set.
- A check that telemetry renders no mental state scanned raw source text, so it
  matched the module docstring â€” which names every banned concept in order to say
  it is absent. It now inspects emitted string literals with docstrings removed.

A test that cannot detect the thing it names is worse than no test, because it
converts an unverified claim into an apparent guarantee.

### Also found and fixed

`FoundationRuntime.infer` restored `READY` in a `finally` block, which silently
clobbered the `FAILED` state set when an adapter raised. A hard adapter failure
now leaves the runtime `FAILED` until reload or shutdown, and the `finally` only
restores `READY` when no worse state was recorded.

### Birth remains impossible

No foundation model configured, no llama.cpp binary, no `BABY_AI` signing key, no
birth record, no subject, no autonomous process. The Observatory still reports
`NO EXPERIMENTAL SUBJECT ATTACHED`. M006 provides an engine and does not turn it
into a subject. M007 was not started.

---

## 2026-09-27 â€” Milestone 007: environment and interaction substrate

### What was built

An environment substrate in `environment/`: versioned state, an observation
contract, an action contract with four distinct validation outcomes, consequences
and deltas, explicit resources, an append-only hash-chained event stream,
integrity-verified snapshots, branch lineage, deterministic replay, and
Observatory telemetry. Plus one deterministic laboratory fixture to exercise it.

The environment exists independently. It runs with no model, no subject, no key,
no memory, no goals and no autonomy, and it never acts first.

### The experimental premise, treated as a correctness property

The premise is that useful behaviour emerges from interaction. An environment
that supplies meaning destroys that premise, so the absence of meaning is enforced
in code rather than asserted in prose:

* `Entity` has no name, purpose, usefulness or recommended-action field, and
  rejects any observable property outside a fixed vocabulary.
* Operations are named for mechanics. `GRASP` exists because something is
  movable; `INSERT` because something has measured interior capacity.
* `implementation_type` is laboratory bookkeeping and is deliberately absent from
  observations â€” how the world was built is not a property of the world.
* A test scans every emitted string literal (docstrings excluded, since the
  docstrings exist precisely to explain the absence) for 24 banned tokens.

The strongest form of the check is the affordance test: the same action from a
restored state must produce the same consequence as from a fresh one. A world
that treated a caller as more experienced would fail there, and that failure is
not detectable by looking at field names.

### Timestamps are not in the state

A wall-clock reading differs between an original run and a replay by microseconds,
so a timestamp in the hashed state would make every replay diverge and divergence
would mean nothing. Time lives in events and results; state records only what is
true. The same reasoning excludes floats: every physical quantity is an integer
in a stated base unit, and a float is rejected rather than rounded, because
rounding hides a real imprecision behind a stable-looking digest.

### Four defects found, three of them in code that was supposed to be the careful part

1. **A silent no-op.** `GRASP` while already holding was ACCEPTED and then did
   nothing, reporting the reason "action is currently possible". For a learning
   environment that is the worst available failure: the caller cannot
   distinguish "did nothing" from "succeeded quietly". The holding capacity is
   now a real resource consumed by GRASP and refunded by RELEASE.

2. **`WAIT` bypassed the cost check.** It returned ACCEPTED before affordability
   was examined, so an exhausted clock drained to **-390**. Cost is now checked
   before any operation-specific shortcut.

3. **Replay's divergence detection was dead code.** It computed the action id
   from the raw request, before `submit` attaches `environment_id`, so the
   expectation lookup could never match and replay always reported success. A
   deterministic-replay feature that cannot report divergence is a feature that
   has never been tested.

4. **Actors could narrate themselves into the immutable log.** Caller parameters
   were copied verbatim into `action_requested`, so a request carrying
   `{"author": "BABY_AI", "i_wrote_this": true}` wrote its own authorship claim
   into an append-only record. Only a parameter count and a digest are recorded
   now, and the parameter *names* are omitted too, because names are also
   caller-supplied text.

### One structural change, and why

`Measurement` was introduced in M006 inside `babylab.runtime.contract`. M007
needed it and had to run with no model runtime present, so importing it would
have coupled the environment to a package it has no business depending on. The
type moved to a neutral `babylab/measure.py` and the M006 surface re-exports it.
Nothing about the type changed; only its address. This surfaced because a test
looked for it, which is the argument for writing the independence tests at all.

### Vocabulary

`ResourceLevel` was renamed `ResourceAmount`. "Level" implies a rank, and rank is
curriculum vocabulary â€” the environment should not contain the word even in a
type name, because a word that means progression in one place will be read as
progression in another. The rename was not cosmetic; a banned-token test now
fails on it.

### Verification

Deterministic replay across a branch: an action sequence replayed from a
pre-sequence snapshot reproduces the recorded final state hash exactly, in a new
branch, with the original event stream byte-identical. A deliberately divergent
replay â€” the same action from a different base state â€” is detected and reported
with both hashes, so the check is known to be capable of failing.

Faults are covered for invalid action, missing target, malformed action,
impossible operation, resource exhaustion, corrupted state, corrupted snapshot,
configuration mismatch, implementation-version mismatch and unknown snapshot.
Every fault becomes an `environment_fault` event; nothing recovers by inventing
state.

### Unchanged

M005 boundary intact. M006 still passes after the `Measurement` move. No
foundation model, no llama.cpp binary, no `BABY_AI` key, no birth record, no
subject, no autonomous process. The Observatory still reports NO EXPERIMENTAL
SUBJECT ATTACHED. M008 was not started.

---

## 2026-09-27 â€” Milestone 008: subject architecture and first-experience boundary

### What was built

A subject boundary in `subject/`: externally governed identity, an immutable
laboratory creation record, an explicit lifecycle, minimal versioned state,
experience records, channel-based provenance, a narrow single-shot interface, a
deterministic test harness, and infrastructure-only telemetry.

The central distinction is structural:

```text
FOUNDATION MODEL != SUBJECT != ENVIRONMENT != LABORATORY
```

A pretrained artifact is referenced, never identified with. The subject's digest
never equals the artifact's digest, and the artifact classification is always
INHERITED_PRETRAINED â€” structurally, not by declaration.

### The harness is not a birth

The whole milestone stands or falls on this. Test subjects live in memory and
caller-supplied temporary directories. They are never written to
`human_control/`, never given a keyring role, never registered in the real
session registry. The birth ceremony's two tripwires â€” `birth_records/BIRTH.json`
and an active BABY_AI key â€” are asserted absent after the suite runs, and the
observer still reports NO EXPERIMENTAL SUBJECT ATTACHED. A test subject is not
the Baby, and the laboratory cannot see one as attached because attachment
criteria were never constructed.

### Experience is a record, not a memory

A sequence of experiences is a history, and reading a history is not remembering.
M008 builds the history. Retrieval, consolidation, and everything that would
make it memory are separate milestones with separate reviews. The state carries
no store of any kind, and unimplemented capabilities are named absences
("semantic_memory: UNAVAILABLE - no memory system exists") rather than empty
lists â€” an empty list would imply a system that exists and is merely empty.

### Three things the implementation got wrong before the tests passed

1. **The harness skipped CREATED.** `create_subject` built the creation record
   but left the lifecycle at UNCREATED, so `attach` failed on its own
   transition table. Creation must move the record to CREATED explicitly; the
   table was right and the harness was wrong.

2. **The head hash was circular.** The stored experience's hash covers the
   resulting state hash, which covers the state, which covers the head. There
   is no ordering that resolves this, so the experience carries a `content_hash`
   â€” everything except the linkage â€” which the state advances with, and the
   full hash covers the completed linkage. Both are checked: the head names
   content that exists, and the full hash names the completed record.

3. **Replay determinism needed deterministic observation references.** M007's
   `observation_id` was random, so two identical runs produced different
   observation hashes and replay comparison failed on identity rather than
   content. Observation ids are now derived from environment, version and state
   hash. Two views of the same state are the same observation.

### One check the tests improved

`verify_record` checks a record's self-consistency, which a well-formed record
about *someone else* also satisfies. The anti-substitution property needed its
own function: `record_belongs_to` checks that the record names the subject AND
that its hash is the hash the subject's state already carries. The test that
prompted it asserted the wrong thing (that a foreign record "must not verify"),
and the fix was a new function rather than a stronger hash.

### Also verified in passing

Observation references point at the right states. Duplicate sequence numbers
are impossible by construction (sequence-derived ids). The `issuer` string check
is documented as the schema-level guard with M005 storage boundaries and key
custody as its required companions, not implied substitutes. ACTIVE is process
state only. The interface has no `step`, because a step the harness could call
in a loop is an agent loop with one line of glue.

### Unchanged

M005 boundary intact at 11/11 with workspaces un-denied. M006 still passes
after no changes to it. No foundation model, no llama.cpp binary, no BABY_AI
key, no birth record, no subject attached, no autonomous process. M009 was not
started.

---

## 2026-09-27 â€” Milestone 009: birth ceremony and first controlled experience

### What was built

The transition machinery: a fourteen-prerequisite safety gate with honest
PASS/FAIL/UNKNOWN semantics, a staged birth ceremony with per-step events and
two labelled modes, an immutable T_birth record, an explicit key-custody
decision, laboratory pause/resume/terminate, a machine-readable audit derived
from evidence rather than prose, ceremony replay with divergence reporting, and
birth-state Observatory display.

REAL_BIRTH = NOT_PERFORMED. No model is configured, so the gate blocks on
MODEL_NOT_CONFIGURED, the ceremony aborts at prerequisites, and the laboratory
ends with no subject. That is the successful M009 result the specification
describes for this state: the machinery built, the blocking proven, nothing
manufactured.

### The gate is a decision, not a report

Two rules, both tested with injected checks because the real checks depend on
the machine: UNKNOWN never becomes PASS, and a check that raises blocks. Absence
is FAIL, not UNKNOWN â€” "no model configured" is an observed fact. Every check
always runs, so one evaluation shows all fourteen answers instead of stopping
at the first failure and hiding the rest. Security checks re-inspect the live
filesystem rather than reading M005's evidence file; checks that would need a
side effect say what they checked instead of performing it.

### Partial birth cannot look like success

There is no code path past a failure: each step is checked before the next
begins, the failure is recorded with step, reason and detail, the record is
terminated, and nothing downstream is fabricated. The aborted REAL run on this
machine has two events â€” preflight and the failed gate â€” and no subject id, no
T_birth, no experience, no completion. Rollback is evidence preservation, never
cleanup.

### Key custody is NOT_REQUIRED, and that is a decision with reasons

The ceremony needs no signing: provenance is laboratory-generated and
hash-linked, and no BABY_AI-authored content exists yet. Provisioning a key for
appearance would create the active BABY_AI role that makes the observer report
attachment. `provision_key` refuses outright, because production key creation
must never happen as a ceremony side effect.

### The audit is a check, not a transcript

Sixteen questions answered by re-deriving from the ceremony record. Verification
rebuilds every answer independently and names disagreements; a doctored audit
fails, demonstrated by test. Replay rebuilds the deterministic environment,
replays the recorded first action, and compares hashes without weakening state
integrity to make the comparison pass.

### What the ceremony does not do

No loop, no scheduler, no background process â€” asserted over the AST with the
caller-driven replay explicitly excluded by name. No memory, no learning, no
training vocabulary, no physical interfaces, no network. No curriculum anywhere
in the package. ACTIVE is process state only.

### Unchanged

M005 boundary intact at 11/11 with workspaces un-denied. No BABY_AI key, no
birth record, no subject attached, no model, no weights, no autonomous process.
The observer still reports NO EXPERIMENTAL SUBJECT ATTACHED. M010 was not
started.

---

## 2026-09-30 - Milestone 010: foundation model acquisition, verification, and runtime validation

### What was built

The input side of Milestone 009's birth gate: explicit artifact identity from
real bytes, external digest handling, runtime identity from the binary's own
version output, resource admission with a three-valued answer, one real
inference characterised honestly, and the boundary the runtime process has.
`foundation/` plus two test files and an Observatory section.

MODEL_NOT_CONFIGURED. REAL_INFERENCE = NOT_TESTABLE. SUBJECT = NONE. BIRTH =
NOT_PERFORMED. No model was downloaded, searched for, or selected, because none
exists on this host and the milestone forbids the laboratory from choosing one.

### The acquisition policy is code

"Never choose your own substrate" is the repository's load-bearing constraint,
and prose decays the first time a milestone is blocked on it. So it is a module
with three terminal states and a twelve-entry inventory of refused routes, and a
refusal that raises rather than returns. Three tests close the loop: the weights
directory filled with three real GGUFs still yields MODEL_NOT_CONFIGURED, because
discovery is not a question the package asks; a declaration naming a missing
artifact yields ARTIFACT_MISSING and the file still does not exist afterwards;
and no module defines a function named after a forbidden route.

### Three digest claims, kept apart

Computed local digest establishes that a file is still that file. An externally
supplied digest is a publisher's word, and only a human can supply one.
VERIFIED_MATCH is the two agreeing, and it is the only basis on which an artifact
may be called verified. When no external digest exists the status is
NO_EXTERNAL_DIGEST_SUPPLIED, and the Observatory renders it amber rather than
green, because it is a weaker claim and must look weaker.

The manifest is a separate file from the declaration on purpose. Combined, a
human who mistyped a digest would satisfy his own mistake and "externally
verified" would mean "consistent with something written five minutes ago by the
same person."

### A template that was a working forgery

The manifest template writes placeholder text where a digest belongs. Accepted
naively, submitting it unfilled records an "externally supplied" digest
consisting of the words FILL IN. The loader now rejects any non-64-hex value,
reports both the rejection and the text as written, and separates "unfilled
placeholder" from "well-formed digest with no source" -- the latter being
unattributed and therefore not external provenance either.

### Model identity is not runtime identity

M is a file identified by its bytes. R is an executable identified by its path,
digest, and a version read from its own --version output. M != R. A verified
model implies nothing about the runtime that will load it. The most common way a
laboratory overstates itself is reporting "the model works" when what was shown
was "a binary ran a file." Real-inference availability requires all of: a human
declaration, a verified artifact, and a verified runtime.

### A bug this milestone found in itself

`validation.py` called `resolve_gpu_usage` with the reported backend but never
passed the offload evidence, so CONFIRMED was unreachable and GPU use could
never be reported even when the runtime had plainly performed it. The M006
adapter was separately discarding `parsed.diagnostics`, the only place that
evidence exists. Both fixed; M006's 71 tests unaffected.

Verified through the real parse path: CUDA plus an offload line gives CONFIRMED;
CUDA alone gives REQUESTED_NOT_CONFIRMED; CPU with layers requested gives
REQUESTED_NOT_CONFIRMED and reports that the run completed on CPU. Requested is
not executed, and the two are never collapsed.

### Honest token accounting, and an M003 gap left visible

Counts are OBSERVED only when the runtime printed them; a total is DERIVED
because it is arithmetic on two observed values. An unrecognised shape yields
UNAVAILABLE with a reason.

M003's completion-token patterns do not recognise llama.cpp's `eval time = X ms
/ N runs` form, so on a real build generated-token counts may report
UNAVAILABLE. Recorded rather than papered over: the honest reading is that the
patterns are incomplete, not that the count should be guessed. A test pins the
current behaviour so the gap stays visible.

### The boundary, at the strength it can be shown

Three strengths, never collapsed. ENFORCED: private keys and the control token
are denied by the M005 boundary, verified by human cross-process execution, and
deliberately not re-tested from inside the process whose access is in question.
STRUCTURAL: the runtime path imports no network module, reaches no shell or
detached process, and cannot reach subject or birth at all; subprocess.run is
classified as a bounded invocation rather than a shell. NOT_ESTABLISHED:
filesystem restriction, because narrowing the runtime would need tier 3, which
does not exist -- M005 binds a file boundary to an account, and nothing yet runs
as that account.

Protected-evidence integrity is checked without violating it: digest before and
after, compare. A write attempt to prove writes are blocked would itself be a
write attempt.

### The bans, as import-graph facts

No module imports subject. No module imports the ceremony, gate, or record
writer. No memory substrate, no learning library, no optimiser, no weight
update, no eval/exec/compile, no network or acquisition library. Walked from the
AST, because a module that documented the ban would pass a text scan. The
positive form is the immutability check: digest before, digest after, equality
required, and a mutation is reported as ARTIFACT MUTATED with a refusal to
continue.

### The M003 vocabulary guard caught me

My first draft of the Observatory section spelled out one of the banned
psychological words while explaining that the section cannot display it. The
existing M003 guard failed the build, correctly. The word has no business in a
read-only renderer, so the note was rewritten rather than the guard relaxed.

### What remains not testable here

No real inference, because no model and no llama.cpp binary exist on this host.
The end-to-end path was exercised against a synthetic fixture with a real 4 MiB
GGUF, a real computed digest, a real binary probe, and a stubbed process runner.
That is STUB_RUNTIME and is labelled as such; it is how the GPU-evidence bug was
found, and it is not a real inference.

### Unchanged

M005 boundary intact at 11/11, workspaces un-denied. Event chain intact, 20
events. Ledger 14 entries. No BABY_AI key, no birth record, no subject attached,
no model, no weights, no autonomous process. The M009 birth gate still reports
BLOCKED on MODEL_NOT_CONFIGURED across all fourteen prerequisites. M011 not
started.

---

## 2026-09-30 - Milestone 011: real runtime, subject-account execution, and end-to-end verification

### What was built

The two gaps M010 reported closed: real inference, and the runtime process
exercised under the restricted account. `foundation/hardware.py`,
`process_identity.py`, `restricted.py`, `win32.py`, `probe.py`,
`real_runtime.py`, `verification.py`, and `m011_status.py`; an Observatory
section; two test files.

REAL_RUNTIME = NOT_TESTABLE. REAL_INFERENCE = NOT_TESTABLE.
SUBJECT_ACCOUNT_RUNTIME = NOT_TESTABLE. SUBJECT = NONE. BIRTH = NOT_PERFORMED.
No model was downloaded, searched for, or selected.

### The unconfigured binary, and the discipline not to use it

A machine-wide survey found an 8 MB llama-server.exe in a Docker bin directory
and zero GGUF files anywhere. It was not declared and not executed. The
specification forbids selecting the first executable found, and doing so would
make the substrate a property of what happened to be installed rather than of
what a human chose. Its digest is recorded in the documentation so a human can
choose to declare it knowingly, and its absence from the run is the honest
outcome.

### Real, stub, and simulated are derived, never declared

ExecutionMode is computed from what was invoked. A caller-supplied runner makes
REAL_RUNTIME unreachable -- there is no flag or argument that converts a stubbed
run into a real one. Verified end to end against a fixture: 18 of 21 criteria
SATISFIED and real_inference_performed NOT_TESTABLE with the reason spelled out.
A partial verification cannot read as a complete one.

### Three defects in the identity code, all of which made it less honest

ctypes.get_last_error() does not track the real Win32 error, so a failed
OpenProcess reported code 0 and ERROR_ACCESS_DENIED rendered as "the operation
completed successfully" with a null handle. Undeclared ctypes signatures truncate
64-bit pointers to c_int, raising OverflowError several frames from the cause.
And the integrity level read a mandatory-label SID through GetTokenInformation,
which takes a token, not a SID -- it failed quietly, reporting UNAVAILABLE for a
token that had a good MEDIUM label. All three fixed; the live reading is now a
real account, SID, integrity level, and elevation state.

The domain was also being derived from the profile path's parent directory, so
C:\Users\alice was reported as the domain C:\Users. It now comes from
ActiveComputerName.

### The Windows edition required a correction

The registry key ProductName reads "Windows 10 Home Single Language" on this
Windows 11 machine; the key has carried a stale label since Windows 11 shipped.
Reporting it verbatim would have made this milestone state that a Windows 11
machine runs Windows 10. The build number (26200) is now authoritative and the
raw registry string is reported separately, labelled, so a reader sees both the
truth and its source.

### Two mechanisms refused, and no fallback

whoami /priv shows neither SeImpersonatePrivilege nor
SeAssignPrimaryTokenPrivilege. CreateProcessAsUserW is therefore unavailable.
CreateProcessWithTokenW is refused by design because it needs a stored password;
runas is refused by design because it blocks an unattended harness on a console
prompt.

No fallback was taken. A run under the operator token would have produced text,
digests, and a successful-looking record while establishing nothing about the
restricted account -- the specific failure mode M011 exists to prevent.
LaunchResult has no state representing it, and fallback_taken is recorded False.
win32.py implements the correct mechanism in full and is stated as untested
against a real restricted token on this host.

### Two defects in the probe

The workspace cycle deleted the file before reading it back, which made the
readback meaningless: the write helper removed on success because that is correct
for a protected path, and wrong for a workspace where readback is the only way to
distinguish a real write from one that appears to succeed and writes nothing.
Removal is now a parameter.

Worse: four of six protected categories were silently unprobed. The category map
guessed entry names that do not exist in babylab.osboundary, so those lookups
returned None and the categories vanished without a word. A test now asserts each
of the six is attempted.

### The verdict depends on who ran the probe

Run as the operator, protected access succeeds -- correctly, because the
operator owns the keyring and the ledger, and M005's boundary is a boundary
against the subject account. Reporting that as a violation would invent a failure
and imply M005 is broken when it is working. The verdict carries
boundary_meaningful: false and says the run proves the probe works and nothing
about the restricted identity. Run as the subject account, a permitted access is
a violation.

Live: 9 attempts across all 6 categories, workspace write/readback/cleanup all
True, zero residue, key directory back to 3 files, all 5 protected file digests
unchanged.

### A guard I narrowed, and the measurement that justified it

M011 imports birth.llamacpp for the invocation builder, tripping M010's blanket
birth ban. Before relaxing anything I checked two things. First, M006's own
adapter already imports it by design, so the guard was broader than the codebase
it protected and would have failed the M006 adapter had it been applied there.
Second, a new test walks the transitive import graph from birth.llamacpp and
asserts no ceremony module is reachable -- the reachable set is babylab.{clock,
errors,hashing,identity,paths,storage} and birth.{authorship,config,identity,
llamacpp,runtime}. The ban is now on the modules that can actually perform a
birth, and the exemption is measured rather than asserted.

### Recorded rather than worked around

M003's completion-token patterns do not recognise llama.cpp's "eval time = X ms /
N runs" form, so a real build may report UNAVAILABLE for generated tokens.
Building M011's own fixture caught this: the first fixture used
"tokens_predicted = 5" and the count came back UNAVAILABLE -- the parser was
right and the fixture was wrong.

This runtime's own VRAM allocation is UNAVAILABLE. nvidia-smi reports device-wide
totals, and a device delta cannot be attributed to one process among several, so
the figure is left unavailable rather than derived from a difference that would
not be evidence.

### Unchanged

M005 boundary intact at 11/11, workspaces un-denied. Event chain intact, 20
events, ledger 14. No BABY_AI key, no birth record, no subject, no model, no
weights, no autonomous process. The M009 birth gate still reports BLOCKED on
MODEL_NOT_CONFIGURED across all fourteen prerequisites. M012 not started.

---

## 2026-09-30 - Milestone 012: human-selected foundation model and runtime deployment

### What was built

The selection boundary, made structural. `foundation/deployment.py` (one explicit
joint human declaration), `discovery.py` (report-only candidates),
`compatibility.py` (COMPATIBLE / INCOMPATIBLE / UNKNOWN), `audit.py` (sixteen
evidence-derived questions), `m012.py` (the ordered sequence), `m012_status.py`
(the Observatory's read surface), an Observatory section, and 65 tests.

M012 = BLOCKED / NOT_CONFIGURED. No human wrote a declaration, so there is no
foundation to verify. Nothing was downloaded, chosen, recommended, or ranked. The
machinery is built, the gates are proven, the laboratory is clean.

### Discovery cannot promote, structurally

M011 found a real llama.cpp binary in a Docker bin directory and left it
unselected. M012 makes that impossible to lose by accident. Candidate carries no
field that could hold a decision -- no selected, approved, chosen, or usable.
CandidateReport.promotable is a hard-coded False with no branch, so a future code
path cannot make it True. load_declaration is the only producer of a Deployment
and takes a path a human wrote. And assert_not_selected raises on any candidate
the declaration does not name, so a future convenience hits a wall rather than
executing a binary nobody chose.

Tested adversarially rather than on the happy path: a real .gguf sits in the
weights directory with no declaration, and the answer is still NOT_CONFIGURED.
Then a declaration names a different file and the decoy is still refused -- naming
one artifact does not silently authorise another beside it. The positive case is
tested too, so the guard is a check rather than a wall.

Candidates are not hashed or executed during a scan either. Hashing a
multi-gigabyte file would perform the verification the human's declaration is
supposed to authorise, against a file nobody has chosen yet; executing an
unselected binary to read its version is running a program nobody chose to run.

### One declaration, two identities

M010 and M011 read a runtime config and a separate manifest. M012 asks a paired
question -- did this human choose this model to run on this runtime -- which needs
both decisions from one person at one moment. declared_by and rationale are both
required: a foundation chosen without a named human and a stated reason is not a
selection this project can attribute, and the provenance record would be unusable.
Relative paths and non-64-hex digests are refused. The generated template writes
FILL IN into every decision-bearing field, so submitting it unfilled is INVALID
rather than accepted with invented provenance.

Quantization is never read from a filename. A name encoding a different
quantization than the declaration is reported as filename_disagreement -- a
possible human error, surfaced and not resolved.

### Compatibility is a load, and only a load

The specification warns against file extension = compatibility, which is easy to
write by accident because the format check and the compatibility check look like
neighbours. A .gguf extension is a naming convention; a GGUF magic check narrows
the format and nothing about compatibility; only an actual load settles it. A
load that exits 0 and prints nothing is UNKNOWN, because silence is not an answer.
A refusal quotes the runtime's own message and exit code and is never retried
with a smaller context, a lower layer count, or a substitute file.

established_by_load is the predicate that matters. A caller-supplied process
stand-in sets method = STUB_LOAD and leaves the flag False, so a fixture that
answers every probe positively cannot walk the sequence into an inference.
Verified: with a stub returning COMPATIBLE the ledger still reports NOT_RUN. A
milestone whose acceptance criterion is "a real load" must not be satisfiable from
a test.

### Two gaps the tests found in my own blocked path

A blocked deployment recorded neither network_absent nor no_subject_no_birth.
Both are guarantees that do not weaken when nothing runs, and a reader seeing
NOT_REACHED on everything else needs to see that "nothing was fetched" and "no
subject exists" are still asserted. Omitting them would have made a blocked
milestone look like one that stopped trying. Both are now unconditional, and
both are pinned by tests.

### The sixteen-question audit

Every answer is read from a named field and the field is recorded. Absent or
wrongly-typed yields UNKNOWN with a reason, never a confident default. On this
host: 11 derived, 5 unknown, which is the honest split. reverify recomputes
everything and names disagreements, so a hand-edited audit fails; doctoring one
answer produces exactly one disagreement.

### What stayed unblocked

Eight criteria are answerable with no model at all, and all eight are recorded:
hardware measured now, discovery inert, a live process token, the workspace
write/readback/cleanup with no residue, no tools/memory/learning, no network, no
subject, and a complete re-verifiable audit.

### Reused unchanged from M011

The probe, including its boundary_meaningful flag. Run as the operator, protected
access succeeds -- correctly, because the operator owns the keyring -- and the
verdict says so rather than implying M005 is broken. All six categories are
asserted present by test, pinning M011's fix against the silent-skip bug that had
hidden four of them. SUBJECT_ACCOUNT_RUNTIME is NOT_TESTABLE for the unchanged
M011 reason: no impersonation privilege, and this laboratory never accepts a
password. No fallback to the operator token; the account is not weakened.

### BLOCKED is not FAILED

The two are distinct enum values and a test asserts they are not equal. A refusal
is correct behaviour, not an error, and collapsing the two would make a
deliberately-blocked milestone indistinguishable from a broken one.

### Unchanged

M005 boundary intact at 11/11, workspaces un-denied. Event chain intact, 20
events, ledger 14. Key directory back to 3 files. No BABY_AI key, no birth record,
no subject, no model, no weights, no probe residue. The M009 birth gate still
BLOCKED on MODEL_NOT_CONFIGURED across all fourteen prerequisites. M013 not
started.


---

## 2026-09-30 - Milestone 013: real birth ceremony and the first real experience

M012 ended with no foundation. M013 asks what happens if someone tries to make a
subject anyway, and the answer this milestone builds is *nothing happens*.

### The invariant, and why it needed testing from both directions

A real birth is the only outcome that creates a subject; every other outcome
leaves nothing behind. The failure matrix proves each of the sixteen
prerequisites can independently prevent a birth. The invariant sweep then proves
no failure path leaves a partial subject, a stray T_birth, or an orphaned
experience.

The sweep is what caught three real defects, each of which the matrix alone
would have missed. A gate that refuses *correctly* is not sufficient on its own --
a gate that refuses *after* mutating state has still created a subject.

### Three defects found and fixed

**Compatibility judged on the wrong field.** The gate checked
`established_by_load` and never read `compatibility.compatibility`. A load that ran
and rejected the artifact sets that flag too, so an INCOMPATIBLE deployment read
as READY and the ceremony completed a birth on a model the runtime cannot load.
This is the most serious of the three: the milestone's central guarantee was
bypassed by a real, plausible input.

**Context screening after activation.** A model context claiming to be the
subject was refused after the lifecycle reached ACTIVE, so the record carried a
T_birth and no completed birth -- precisely the artifact this milestone must not
emit. Screening now runs before anything is created, and the test asserts
`lifecycle == UNCREATED` and an empty creation record, not merely an abort.

**A stop that was only asserted.** `second_interaction = "REFUSED"` was a claim
with nothing enforcing it. Added `SingleInteractionEnvironment`, which permits one
action and raises `SecondInteractionRefused` on the second, and had the ceremony
*request* that second action so the recorded refusal corresponds to a real
exception. A ceremony that says it stopped but never tested whether it could
continue has not shown anything about stopping.

### The Observatory regression M011 caught

The first Observatory panel called `foundation.m012.verify` to obtain a ledger,
which would have made opening the display able to run verification. M011's
AST-based import-graph test caught it -- a test that walks the AST rather than
grepping, so a module documenting the ban cannot pass by documenting it.

The fix was a read-only surface, not a suppression: `birth/m013_status.py` reads
the deployment declaration and imports nothing that can execute. The consequence
is stated rather than worked around -- the panel can never report READY, because
the evidence READY needs comes from the verification command, not a file read. On
this host it reads 16 BLOCKED. That is the safe direction to be wrong in.

### Replay: two questions, and honest UNVERIFIABLE

MODEL_OUTPUT_REPLAY and ENVIRONMENT_REPLAY are kept separate because they answer
different things. Conflating them would hide the failure that matters for a birth:
a proposal that reproduces while the event that supposedly taught the subject does
not. Both report UNVERIFIABLE rather than CONFIRMED when they cannot check, since
a replay that finds nothing to contradict has established nothing.

The environment replay also checks environment *identity*, not just state hash --
two fresh deterministic environments share an initial state hash, so state alone
cannot distinguish "the same world" from "a different world that starts the same
way". Found by a test that failed and was worth keeping.

### Key policy revisited, not inherited

M009 decided no subject key. M013 revisits it because a subject now exists.
Unchanged: the environment interface requires no subject signature, and
provisioning a key would make the subject appear ATTACHED before it had ever
acted. Nothing provisioned. Still refused the control token, provenance signing
authority, human-control credentials, and ACL manipulation.

### Result

BLOCKED, correctly. Gate 11 BLOCKED / 5 READY; Observatory panel 16 BLOCKED.
birth_occurred False, T_birth UNAVAILABLE, subject NONE, first experience
NOT_PERFORMED, experience count unchanged.

Nothing written. Event store 20 events, chain intact, 0 appended. Provenance 14
entries, 0 appended. No BIRTH.json, no model directory, no subject key.
Environment state hash unchanged.

### Tests

133 M013 tests (94 birth, 15 replay, 25 observatory). Portable suite 1575 passed,
749 subtests passed. Host security 15 failed / 10 passed / 13 subtests, all
NOT_TESTABLE for the unchanged reason: this session holds neither
SeImpersonatePrivilege nor SeAssignPrimaryTokenPrivilege, so the harness cannot
impersonate BABY_AI_TEST. Unchanged from M009 through M012.

M013 is implemented and verified. What has not happened is a birth, and that
remains the correct state of the laboratory. M014 not started.

---

## 2026-09-30 - Milestone 014: human-selected foundation deployment and the first real birth

M012 verified a declaration. M013 built a ceremony and declined to run it. M014 is
the execution boundary: the one place the whole chain is walked end to end, with a
refusal available at every step. It adds no developmental architecture -- every
piece of machinery it uses already existed, and M014's own code is the ordering
and the refusals.

### Result: BLOCKED, for two independent reasons

No declaration exists, and the restricted-account boundary is NOT_TESTABLE. Both
are reported, and the second is reported even though the run stopped at the first,
because it is a property of the host rather than of the declaration and is the
condition most likely to block a birth even after a human deploys everything. A
report that omitted it on an early stop would hide the answer the reader came for.

Path C was taken. M014 does not grant privileges to satisfy a test, weaken ACLs,
remove M005 deny ACEs, store a password, or ask for one. The report carries
operator_execution_accepted_as_subject: False unconditionally, so the claim cannot
be quietly dropped later.

### The laboratory never chooses

Asserted by walking the module's AST rather than claimed in prose. No search, no
ranking, no recommendation, no download, no substitution, and a malformed
declaration is FAILED and never repaired -- a repaired declaration reads as a human
decision and is not one.

### A stubbed load can never produce a real birth

foundation.compatibility.assess_compatibility marks any substituted process call
STUB_LOAD with established_by_load=False, and the M013 gate refuses that method.
So a harness cannot drive a stubbed load to a READY gate however it is configured.

The honest consequence, stated rather than worked around: M014's real path cannot
be completed in a test, and that is the guarantee working. What the tests do
exercise is the declaration, artifact and runtime stages against real files with
real digests, and the ceremony behind the gate through a ledger marked
SYNTHETIC_M014_EVIDENCE. The join between them is not exercised, because the join
needs a real runtime this host does not have.

### Two defects found

A declared digest that disagreed with the file read as OK. verify_declared_artifact
passed the human's sha256 to identify and trusted the result, but identify compares
against the *publisher's* digest and never says whether the human's stated digest
matches the bytes in hand. A declaration could match the publisher while
disagreeing with the file in front of the laboratory, which is what happens when
the wrong file is downloaded under the right name. M014 now compares the two
digests itself.

A model claiming prior memory completed a birth. M013's screening refused identity
claims but not autobiographical ones, so "you previously experienced this room"
passed through and a subject was born on a fabricated pre-birth history. Screening
now runs assert_neutral_context over the same claim, reusing the one banned-phrase
list so a second list of forbidden framings cannot drift from the first.

### A mistake worth recording

While wiring the Observatory panel an edit collapsed a comment and a method
signature onto one line, deleting ObservatorySession.update. Fifty-four tests
failed in the full suite and zero in the M014 file -- the regression was only
visible because the full suite was run before committing. The narrower run would
have passed.

### The Observatory stays read-only

birth/m014_status.py imports birth.m013_status and birth.record14, both pure, and
deliberately not birth.m014. The record's path and hash were extracted into
birth/record14.py precisely so the display could share them without importing a
module that can execute a ceremony. It cannot report a READY gate, and it never
renders consciousness, awareness, curiosity, motivation, or any developmental
score.

The birth record carries no author-of-last-edit field, so a subject's edit and an
operator's accidental edit are caught by the same check.

### Result

BLOCKED at stage declaration. No subject, no T_birth, no birth record, no first
experience. Event store 20 events with 0 appended, chain intact. Provenance 14
entries with 0 appended. Keyring unchanged. No BIRTH.json, no model directory.
Environment state hash unchanged.

### Tests

110 M014, 133 M013, portable suite 1685 passed / 749 subtests passed. Host
security 15 failed / 10 passed / 13 subtests, all NOT_TESTABLE for the unchanged
reason, not disguised and not counted as a pass.

M014 is implemented and verified. No birth occurred, and that is the correct state
of this laboratory. M015 not started.

---

## 2026-09-30 - Host-readiness investigation: real BABY_AI_TEST execution

An investigation, not a milestone. Nothing born, no subject, no T_birth, no
experience, no key, no model selected, no ACL touched, no privilege granted. M014
remains BLOCKED at stage declaration and was re-verified unchanged after.

### The finding that changes the design

M011/M013/M014 all reported the harness cannot impersonate BABY_AI_TEST. That is
still true and still unfixable without a credential. But the conclusion drawn from
it was too broad.

The laboratory does not need to *become* the account in order to confirm that a
process *is* the account. It needs a handle to the process. Windows grants
PROCESS_QUERY_LIMITED_INFORMATION and TOKEN_QUERY to an unelevated process for a
process it holds a handle to, and foundation/token_observation.py uses exactly
that. Verified here, non-elevated, against a real child process:

    status VERIFIED | sid S-1-5-21-...-1001 | integrity MEDIUM | elevated False

So the identity can be read from the token rather than believed from a printout,
which is exactly the requirement the milestone specified. The identity came from
the token; nothing the process said was merged with it.

Cross-credential OpenProcess remains NOT_TESTABLE. Windows' default process DACL
grants Everyone SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, which suggests
it will work, but testing it requires launching as the subject, which requires a
credential this investigation will not ask for. observe_process returns
NOT_TESTABLE rather than assuming, and a caller receiving it must not treat the
identity as confirmed.

### The mechanism is not new

M005 already recorded a human-executed cross-process probe as BABY_AI_TEST with
OS_DENIED on protected paths and ALLOWED on the workspace, and C:\Users\BABY_AI_TEST
exists with a LastLogon of 2026-09-27. The recommended mechanism has worked once.
The recommendation is therefore not a proposal; it is the mechanism M005 used,
now paired with independent token observation so the operator can confirm it.

The account is in NO local group at all, not even Users. It inherits nothing. The
M005 deny ACEs are the only thing constraining it, which is precisely why they
must not be touched, and why the test suite now asserts all 14 protected
directories still carry their deny ACE by name.

### Refused, and why

Impersonation and CreateProcessWithLogonW are refused because the privileges are
absent *and* acquiring them would be worse than the problem: whoever holds them
can mint a token for any local account without that account's password. S4U is
refused for the same reason despite being password-free, since it needs
SeImpersonatePrivilege to call and SeTcbPrivilege to register. Task Scheduler and
services are rejected as standing execution paths needing a stored credential --
more capability than one controlled interaction requires. WSL is ruled out because
M005 measured it as the operator's own identity over 9p/DrvFs.

### Two things the host would not tell us

secedit /export needs elevation, so the subject account's granted logon rights are
NOT_TESTABLE. The Security event log is unreadable non-elevated, so there is no
audit-log corroboration. Both are honest gaps, recorded as gaps rather than as
absence.

### Two defects I introduced and the existing tests caught

host_readiness.py called subprocess.run without explicit shell=False or closed
stdin. tests/test_m010_boundary.py failed on it -- a standing rule the project had
already written, and the only reason it exists. Fixed by complying, not by
weakening the test.

PowerShell edits had silently written a UTF-8 BOM into seven files, including
token_observation.py, which made ast.parse fail on a leading \ufeff. Stripped, and
a repo-wide no-BOM test added so it cannot recur. Note the BOMs were present in
the M013 and M014 commits; this removes them.

### Also worth recording: my own test bugs

Three tests asserted the wrong thing and were fixed rather than worked around: one
parsed icacls output for (D) when it prints (DENY) and so found zero deny ACEs; one
asserted NOT_TESTABLE where FAILED is correct, because the token WAS readable and
said the process was the wrong account; and one text-scanned for PROCESS_ALL_ACCESS
and matched the comment saying the module deliberately avoids it -- the same false
positive M011's AST tests were written to prevent.

### Result

NOT_TESTABLE, honestly. Host readiness NOT_TESTABLE. Real process identity
NOT_TESTABLE. 48 investigation tests. portable suite 1733 passed / 749 subtests.
Host security 15 failed / 10 passed / 13 subtests, all NOT_TESTABLE.

No birth occurred, no subject exists, and M014 is unchanged. M015 not started.

---

## 2026-09-30 - Host-readiness follow-up: direct executable launch

A launch-mechanism investigation. No model selected, nothing downloaded, no
runtime executed, no birth, no subject, M014 birth behaviour untouched.

### Why the human's command failed

Start-Process -FilePath "py" returned "The file cannot be accessed by the system."
The cause is not BABY_AI_TEST and not a birth problem. `py` is the Python
Launcher and resolves to an App Execution Alias under the operator's own profile.
Aliases are per-user shims that resolve only for the account that created them,
so BABY_AI_TEST cannot launch one. They are also zero-length reparse points with
no bytes behind them, which is why they cannot even be hashed.

### Pointing at the real interpreter is necessary but not sufficient

    C:\Users\k.tharun balaji\AppData\Local\Python\pythoncore-3.14-64\python.exe
    sha256 cce21c0e8710e304273e98ac4b2b0f5aceb639acbcd2343cbaa5c4e81619c45b
    106328 bytes, x64, CPython 3.14.3

Correct, absolute, and still unusable. Its ACL names three principals -- SYSTEM,
Administrators, the operator -- and BABY_AI_TEST is not one. No directory in the
chain has a BUILTIN\Users ACE at all, from pythoncore-3.14-64 up to
k.tharun balaji, so the account cannot even traverse into the path.

The fault is isolated and precise: the repository and the probe ARE reachable
(C:\dev grants Users:(RX) and Authenticated Users:(M); the M005 ACEs deny only
writes). The interpreter is the single blocker.

This bites M014 harder than it bites the probe: the llama-server.exe that a real
birth needs carries the same three-principal ACL under .docker\bin\inference\.
Whatever makes the interpreter reachable must eventually apply to the runtime and
model too.

### The other Python, checked rather than assumed

MySQL Workbench ships one with a permissive Users:(RX) ACL, so it is reachable --
but it is a relocatable build needing PYTHONHOME. Without it, it infers its prefix
from the CWD and dies with "No module named 'encodings'"; with it set, it still
fails on the stdlib layout. And it could not be used anyway: -Credential makes
Windows build a NEW environment block from the target profile, so PYTHONHOME set
in the operator's shell would not propagate, and PS 5.1's Start-Process has no
-Environment parameter. There is no system-wide Python on this host.

### launch_readiness returns no command

foundation/subject_launch.py returns "UNAVAILABLE (see blocking)" rather than
emitting a command that cannot work. A command that looks right and fails with a
permissions error sends the next person looking in the wrong place. The exact
command is emitted only once the interpreter is genuinely reachable.

### A false privilege claim, found and fixed

While checking the launch, my own token reader reported the harness held
SeRestorePrivilege. It does not -- whoami /priv lists five privileges and that is
not among them.

The cause was my struct layout. Windows declares LUID as two 32-bit halves, so
LUID_AND_ATTRIBUTES is 12 bytes and the TOKEN_PRIVILEGES array begins at offset 4.
I had declared Luid as a 64-bit integer, aligning to 8, making the struct 16 and
reading the array from the wrong offset with the wrong stride -- and a misaligned
read happened to produce that privilege's LUID.

A verifier that invents a privilege the process does not have is worse than one
that reports none, so it is now pinned by a positive control: a test parses
whoami /priv and requires the reader to find every privilege it reports, while a
second requires SeImpersonatePrivilege reported absent. Both pass. Corrected
finding: the harness holds no notable privileges.

### Reachability needs two checks

A file can be world-readable and still be unreachable because a parent is private,
so reachable_by_subject() checks the file AND every ancestor. My first
implementation checked only the file, reported C:\ and C:\dev as untraversable, and
separately failed on every directory because it only handled files -- two false
negatives that would have pointed the fix in exactly the wrong direction.

The ACL parser also truncated principal names at the first space, turning
"NT AUTHORITY\SYSTEM" into "AUTHORITY\SYSTEM". Fixed by reassembling the name from
every token up to the one carrying ":(".

### Result

LAUNCH_COMMAND_READY false. HOST READINESS NOT_TESTABLE. 38 launch tests, 48
host-readiness tests, portable suite 1771 passed / 749 subtests. Host security
15 failed / 10 passed / 13 subtests, all NOT_TESTABLE.

Nothing changed: no privilege, group, ACL, policy, password, task or service.
Event store 20 events, chain intact; provenance 14 entries; no BIRTH.json; no
model directory. M014 still BLOCKED at stage declaration.

Not decided here and not a laboratory action: the interpreter, and eventually the
runtime and model, need to live somewhere BABY_AI_TEST can reach. The deny ACEs
stay exactly as they are; only the executable's location would change.

---

## 2026-09-30 - Host-readiness: subject-runtime staging design

An investigation and a design. No directory created, no artifact copied, no ACL
changed, no model selected, no birth. M014 birth behaviour untouched.

### The load-bearing finding

The repo root -- C:\dev and C:\dev\TharAI-EXP -- grants

    NT AUTHORITY\Authenticated Users:(I)(M)      = Modify, includes Write+Delete
    BUILTIN\Users:(I)(RX)

BABY_AI_TEST is enabled and has logged on interactively, so it necessarily holds
Authenticated Users and therefore Modify over the repository root and every
subdirectory that does not override it. Confirmed by inspection: scripts,
baby_workspace, tests, environment and subject all inherit (I)(M), and none
carries any BABY_AI_TEST ACE.

Consequence: a subject_runtime directory created under the repo root with default
inheritance would hand the subject Modify over the staged runtime and model. The
design must break inheritance explicitly. This is the single most important
requirement in the document and it is not optional.

It also means the existing M005 boundary is a deny-list model: protected
directories are safe because of explicit DENY ACEs, not because the default is
deny. That works, is unchanged here, but the staging area cannot rely on any
inherited protection and must state its own.

### Runtime dependency analysis, from real PE import tables

Reported, not selected. llama-server.exe (x64) imports 20 DLLs; four are local:

    llama.dll, ggml.dll, ggml-base.dll, mtmd.dll

plus 16 Windows DLLs. The transitive local closure is the same five files. The
VC++ runtime (MSVCP140, VCRUNTIME140, MSVCP140_CODECVT_IDS) is already present in
System32, so it needs no staging. The directory also holds 14 ggml-cpu-*.dll
variants and ggml-vulkan.dll (53.4 MB); there are no CUDA DLLs, so this build is
CPU plus Vulkan.

The interesting part: nothing in that directory references any ggml-cpu-*.dll by
name except each file referencing itself, and ggml.dll imports no LoadLibrary at
all. Whether the CPU backend is loaded dynamically by a mechanism invisible to
static analysis, or is statically linked, cannot be determined without executing
the binary. The minimum staging set is DERIVED, not OBSERVED.

Proposed stage is the whole directory, 89.0 MB / 23 files, not the 12.2 MB
five-file closure. Under-staging a dynamically loaded backend fails only at first
execution under a different account with no error pointing at the cause; over-
staging costs disk and some read access to unused DLLs. Empirical check 16 --
observing which files the runtime actually opens -- will replace the guess with a
measurement.

### Python is not a subject capability

llama-server.exe imports no Python DLL; the subject runtime is self-contained
native. Python has only two roles, neither of them the subject's: laboratory
verification code, which runs as the operator and needs no staging, and the M014
boundary probe, which is a test artifact.

So the probe should not be Python either. Staging a general-purpose CPython into
the subject boundary would hand the subject a programming environment it has no
use for and would make "the subject's runtime" mean something far broader than it
should. A minimal native probe is proposed instead. This does not block the
staging design; it blocks its verification, so LAUNCH_COMMAND_READY stays false.

### Proposed ACL model: allow-list plus a deny backstop

Layer 1 removes inheritance entirely, then grants only operator/SYSTEM/
Administrators full control and BABY_AI_TEST RX on runtime\, R on model\ and
config\. Layer 2 adds an explicit DENY for BABY_AI_TEST (WD,AD,W,D,DC) across the
subtree.

Layer 2 is not redundant. If inheritance is ever re-enabled by a mistake, a tool
or a restore, Authenticated Users:(M) returns and the subject regains write and
delete. A DENY is evaluated before ALLOW, so it survives that. Layer 1 is the
design, layer 2 is the insurance. Two constraints that are easy to get wrong are
called out: BABY_AI_TEST must never be the owner, since the owner can always
rewrite the DACL; and DELETE must be denied on both the file and the parent, since
Windows allows deleting via FILE_DELETE_CHILD on the parent directory.

### Stated plainly rather than assumed

The model is not secret from the subject -- it must read the weights to run them.
What this boundary provides is integrity, not confidentiality, and the design says
so explicitly so nobody later infers otherwise.

More significantly: llama-server.exe contains --model-url, so it can fetch, and
no ACL prevents that. An ACL governs the filesystem, not the network.
LOCAL_ONLY_NO_FETCH must be enforced by the probe and the network policy. This is
the most significant residual risk and staging does not solve it.

Also worth recording: the subject already holds Modify over the source tree,
except where M005 denies it. Staging neither widens nor narrows that. It is
pre-existing and worth revisiting separately.

### A bug the truncation tests found

The PE reader tolerated a section whose raw bytes ran past the end of the file.
A half-copied DLL then resolved no RVA to an offset, the import walk found
nothing, and the reader reported "0 imports" for a file that plainly has 104.
Silence there would let a truncated staged artifact pass as a dependency-free one
-- the exact failure the staging design most needs to detect. Now reported as
PEError, with cutoff sizes swept rather than guessed.

Tests: 30 staging, 38 launch, 48 host-readiness. Portable suite 1801 passed /
749 subtests. Host security 15 failed / 10 passed / 13 subtests, all NOT_TESTABLE.

Nothing changed: no staging directory, no copied artifacts, no ACL change, no
privilege, group, task or service. Events 20, chain intact; provenance 14; no
BIRTH.json; no model directory. All 14 M005 deny ACEs intact. M014 still BLOCKED
at stage declaration.

The .agents/, .claude/, .claude-flow/, .swarm/, .mcp.json, CLAUDE.md and the
.gitignore edit remain untracked and untouched, per instruction.

## M015 - subject runtime staging boundary implemented

Milestone: M015 (subject runtime staging boundary)
Status: STAGING_VERIFIED (ACL observation only)
Enforcement: NOT_TESTABLE - no BABY_AI_TEST process was run.

Created C:\dev\TharAI-EXP\subject_runtime\ with runtime\, model\ and config\,
and applied an explicit allow-list ACL to all four paths. Nothing was copied into
it. No model or runtime was selected.

The parent's `Authenticated Users:(I)(M)` was the reason this tree needed an
explicit boundary: BABY_AI_TEST is authenticated and has logged on, so it
inherited full write from C:\dev\TharAI-EXP. Inheritance is removed on every path
and the verifier asserts no Authenticated Users entry remains.

Resulting subject rights, differing per subtree on purpose: runtime\ RX (a
program must load), model\ R and config\ R (data must not be executable), with a
DENY(W,D,DC,WD,AD) backstop on all four paths. Operator, NT AUTHORITY\SYSTEM and
BUILTIN\Administrators hold (OI)(CI)(F). Operator owns all four paths.

Four defects were found and fixed while implementing, each of which would have
made the verifier report success incorrectly or leave the tree unprotected:

1. `COMPUTERNAME\SYSTEM` does not resolve, so the SYSTEM grant silently failed
   and the tree had no system access for recovery. Now NT AUTHORITY\SYSTEM.
2. Applying grants to the root with /T stamped a duplicate explicit + inherited
   ACE set onto every child. Now granted at the root and inherited down, then
   each subtree is reset and re-granted exactly.
3. Granting a single R/RX label over the whole tree gave the runtime no execute
   and would have given the model execute. Now per-subtree.
4. A substring check such as `"R" in "(OI)(CI)(R)(OI)(CI)(WD)"` is true, so an
   extra WriteDAC ACE on top of a correct grant was invisible. Permissions are
   now compared as expanded sets, and the deny is a separate ACE.

The verifier's own failure modes were tested by tampering with clean disposable
trees: grant (M) on model, (F) on runtime, (W) on config, (WD) on config, (DC) on
model, (RX) on model, and removing the deny from model. All seven flip the
verdict to STAGING_BLOCKED. These are locked in as tests.

Host facts established: icacls prints no owner marker at all, so ownership is read
via Get-Acl and an unreadable owner is treated as unverified rather than as
"not the subject"; dir /q truncates the owner to 8.3 and cannot be compared
reliably; Windows refused /setowner BABY_AI_TEST for lack of SeRestorePrivilege,
so ownership stayed with the operator and the test documents the refusal rather
than claiming a transfer; ACL parsing cannot split on whitespace because
principal names contain spaces (THARUNBALAJI-LA\k.tharun balaji).

Not claimed: subject-side enforcement (NOT_TESTABLE, no SeImpersonatePrivilege
or SeAssignPrimaryTokenPrivilege, and the operator Python is itself inaccessible
to the subject); network isolation (llama-server.exe accepts --model-url);
confidentiality (integrity only); any artifact selection; any birth. M014 remains
BLOCKED.

Tests: 24 new staging-boundary tests. Portable suite 1825 passed / 2 warnings /
749 subtests. Host security 15 failed / 10 passed / 13 subtests, all NOT_TESTABLE,
unchanged from baseline. One design-phase precondition test was updated: it
asserted the staging directory did not exist, which M015 makes false by design.

Unchanged: all 14 M005 deny ACEs intact, no birth, no privilege/group/task/service
change. The .agents/, .claude/, .claude-flow/, .swarm/, .mcp.json, CLAUDE.md and
the .gitignore edit remain untracked and untouched, per instruction.

## M016 - subject-account native runtime launch: NOT_TESTABLE

Milestone: M016 (subject-account launch and boundary proof)
Status: SUBJECT_PROCESS_NOT_TESTABLE
Subject process launched: NO. Runtime selected: NO. Runtime staged: NO.

This milestone set out to answer one question -- can an explicitly
human-selected native runtime execute as BABY_AI_TEST while the OS prevents that
process from modifying the staged tree and protected evidence. The answer on this
host is that it cannot be tested, and the milestone's value is the precise reason.

The operator token was read directly, not assumed: five privileges held
(SeChangeNotifyPrivilege, SeIncreaseWorkingSetPrivilege, SeShutdownPrivilege,
SeTimeZonePrivilege, SeUndockPrivilege), and both SeImpersonatePrivilege and
SeAssignPrimaryTokenPrivilege absent. Elevation was read from group attributes
rather than the presence of an Administrators entry, because an unelevated token
carries that group as deny-only and its presence proves nothing.

Mechanism ledger. CreateProcessWithLogonW needs SeImpersonatePrivilege and is
therefore unavailable -- and it is the mechanism that would otherwise have
satisfied the milestone, since it needs no stored password. CreateProcessAsUser
and DuplicateTokenEx need SeAssignPrimaryTokenPrivilege and are likewise
unavailable. Scheduled-task registration was actually attempted and refused with
"Access is denied" for this non-elevated operator; supplying /RP would persist the
password, which the milestone forbids. Services were rejected by design: a service
runs as its own identity, not an interactive user, and needs stored credentials.
runas.exe and Start-Process -Credential need an interactive credential prompt and
so cannot be driven non-interactively. WSL and docker exec were rejected by
design because they produce a Linux or container identity, which would answer a
different question. automatable_mechanisms_remaining is empty, and that is the
finding rather than a gap in the search.

No credential was requested, supplied, stored, or logged. The account's
PasswordRequired=False is recorded as a host fact meaning an empty password would
satisfy logon; it was deliberately neither exploited nor changed.

A native C# probe was built and verified rather than substituting CPython, and it
was not staged in subject_runtime. It compiles with the C# compiler already in
PowerShell 5.1 via Add-Type, so no toolchain was installed. It reports user_sid,
account_name, integrity_level, groups and privileges read from its own process
token via OpenProcessToken and GetTokenInformation, never from arguments. Its
cross-check against whoami /priv agrees on all five held privileges.

Running it as the operator, who holds (F) on subject_runtime, was the positive
control, and it exposed six defects that would each have produced a false result:

- LookupPrivilegeName was declared with two parameters instead of four, so the
  output-buffer and length arguments were never passed and the call read an
  uninitialised register, crashing with an access violation inside advapi32.
- A hand-rolled LookupAccountSid crashed on its buffer-sizing pass; replaced with
  System.Security.Principal, which wraps the same Win32 call correctly, because a
  probe that cannot run reports nothing at all.
- The mandatory-label RID was read byte-by-byte, walking past the end of the SID,
  which reported UNPROTECTED for a Medium-integrity token. It is the final DWORD
  of the single sub-authority.
- OS_DENIED was returned for winerror 2 and 183. With no staged runtime an empty
  path resolved to the current directory and produced a genuine access-denied
  unrelated to any ACL, so "nothing was staged" could have masqueraded as "the OS
  protected the runtime". Path errors are now PATH_ERROR, and staged-file
  operations report NOT_TESTABLE when no runtime is staged.
- Destructive operations shared one file, so a real rename denial was masked by
  the earlier delete; each operation now targets its own copy.
- The rename target reused its source name, hitting winerror 183, a collision
  rather than a denial.

The probe now reports OS_ALLOWED for all nine filesystem operations as the
operator, which is the evidence that it is not hardwired to report denial. It
distinguishes OS_ALLOWED, OS_DENIED, PATH_ERROR and NOT_TESTABLE, and OS_DENIED
means winerror 5 and nothing else.

Every subject-side outcome remains untested because no subject process exists:
identity, read/execute, write, delete, rename/replace, child creation, ACL
modification, and workspace access. The M015 boundary is still STAGING_VERIFIED,
but that remains operator-side ACL observation exactly as M015 stated. The
empirical bridge between "the ACL design is correct" and "the subject process runs
inside it" is still missing; characterising that gap is this milestone's result.

Regression: M005's 13 protected paths present and readable (5 digests),
unchanged. M015 boundary still verifies. baby_workspace still writable. Full
portable suite 1861 passed / 2 warnings / 749 subtests, up from 1825 with 36 new
M016 tests. Host security 15 failed / 10 passed / 13 subtests, unchanged from
baseline and still all NOT_TESTABLE for the same impersonation reason. No birth,
no model, no network claim, no signing key.

Prerequisites for an M014 rerun, in order: a human runtime declaration naming
source_path and selected_by; staging through M015's deployment path with digest
equality verified; launch capability via runas.exe at an interactive session, or
by granting SeImpersonatePrivilege to the operator -- which grants nothing to
BABY_AI_TEST and touches no ACL, but is still a privilege change and should be a
deliberate decision; and finally a probe run as the subject before any
SUBJECT_PROCESS_VERIFIED claim is recorded.

Unrelated untracked tooling and the pre-existing .gitignore edit remain untouched.

## M016 follow-up: interactive runas verified subject identity; integrity parse bug found and fixed

Milestone: M016 follow-up (no new milestone created)
Subject process launched: YES, interactively, by the human. Runtime staged: NO.
Model staged: NO. Birth: NO.

The human ran the native probe through interactive runas.exe and observed a real
process reading its own token:

  identity_framework=THARUNBALAJI-LA\BABY_AI_TEST
  user_sid=S-1-5-21-2406520953-1060965512-844951592-1022
  account_name=THARUNBALAJI-LA\BABY_AI_TEST

This is the empirical result M016 lacked. The identity came from the live token
via OpenProcessToken/GetTokenInformation, not from arguments, configuration, or
executable path. ...-1022 is the subject; ...-1001 is the operator. The
unattended-launch blocker is therefore resolved in practice without any privilege
change: it needs a human at a keyboard, not SeImpersonatePrivilege.

The same run reported integrity_level=UNPROTECTED. That was NOT reinterpreted as
MEDIUM. It was diagnosed and was a probe bug.

A mandatory-label SID is S-1-16-<RID> with an 8-byte header: Revision(1) +
SubAuthorityCount(1) + IdentifierAuthority(6), then the SubAuthority DWORDs. The
probe read the RID from offset 2 + (n-1)*4, which lands inside the six-byte
identifier authority. Those bytes are 00 00 00 00 00 10 for S-1-16, so the low
DWORD is 0, which maps to UNPROTECTED. Measured on the operator's own Medium
token: offset 2 reads 0x0000, offset 8 reads 0x2000, and whoami /groups confirms
S-1-16-8192 Medium Mandatory Level.

This was a regression introduced in M016. That report claimed a byte-by-byte SID
parse bug had been fixed; what was actually fixed was the stride, while the base
offset stayed wrong. Because zero is a legitimate RID value, the failure was
silent and looked exactly like a real integrity level.

Corrections: the RID is now read from offset 8 + (n-1)*4; a second independent
path reads the same token through ConvertSidToStringSid and parses the RID from
the SID string; the probe prints integrity_level, integrity_level_independent and
integrity_paths_agree; a parse failure returns <no-label> or <unreadable-sid> and
emits integrity_note=PARSE_FAILED, so UNPROTECTED can now only be printed for a
real RID of 0; and disagreement between the two paths is reported explicitly.
Operator-side result is now MEDIUM on both paths with paths_agree=true,
cross-checked against whoami /groups.

The probe interface was extended for the M015 boundary test: --traverse,
--enumerate-runtime, --enumerate-model, --enumerate-config, --read-file and
--acl-target, alongside the existing positional scratch/staged/protected/workspace
slots. Results are classified strictly as OS_ALLOWED, OS_DENIED, PATH_ERROR,
NOT_TESTABLE or ERROR, and any finding whose target was never reached is marked
reached_target=false and is not evidence about an ACL.

Two further harness defects were found by negative controls, both of which would
have produced false results. First, Windows PowerShell drops empty-string
arguments, so passing "" shifted every later positional value by one and made the
workspace test run against an option string, reporting a spurious
NotSupportedException; the harness now uses "-" as an explicit placeholder.
Second, an implicit fallback derived ..\runtime from the scratch argument when
--enumerate-runtime was absent, so a run with a bogus scratch path still
"tested" the real staging directory and reported OS_ALLOWED for a case it never
targeted; the fallback is gone and an unsupplied option reports NOT_TESTABLE.

A third issue was my own test setup rather than a probe defect: a negative control
using C:\nope_a reported OS_ALLOWED because that path genuinely existed, having
been created at the volume root by an earlier probe run. The probe was truthful
and my assumption was wrong; the stray directory was removed.

No filesystem boundary test has been run as the subject. No OS_DENIED has been
observed or recorded for BABY_AI_TEST. The operator positive control is real and
reports OS_ALLOWED for all 17 operations, which is what gives any future denial
its meaning. Two mutation tests confirm the control has teeth: a probe modified to
always report OS_DENIED, and one modified to always report UNPROTECTED, each
cause the suite to fail.

Regression: M015 boundary still STAGING_VERIFIED; M005's 13 protected paths
intact with 5 digests readable; subject_runtime still empty with no .gguf
anywhere; no llama-server execution, no inference, no birth, no subject created,
no ACL modified, no privilege granted, no credential stored and no /savecred
used. Full portable suite 1897 passed / 2 warnings / 749 subtests, up from 1861
with 36 new tests. Host security 15 failed / 10 passed / 13 subtests, unchanged
and still all NOT_TESTABLE.

Unrelated untracked tooling and the pre-existing .gitignore edit remain untouched.
