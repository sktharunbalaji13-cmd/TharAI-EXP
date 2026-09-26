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
   `ADR-007`.
2. **`LICENSE` copyright holder.** Still a placeholder. Blocks publication.
3. **Ed25519 timing.** Deferred per the decision above; the reopen condition is
   recorded, so this only needs revisiting when an independent party is involved.
4. **Tier 2 and the subject account.** Both need an elevated environment, and
   the subject account is not needed until there is a subject.
