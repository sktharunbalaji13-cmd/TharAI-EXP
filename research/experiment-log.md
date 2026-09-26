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
