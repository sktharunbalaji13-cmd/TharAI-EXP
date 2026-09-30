# Baby AI Laboratory

Research instrumentation for observing a self-hosted AI system.

**Milestones 001–009 are delivered. There is still no AI here, and the laboratory
refuses to pretend otherwise.**

```
M009 STATUS           COMPLETE — machinery built, blocking proven
BIRTH SAFETY GATE     BLOCKED (MODEL_NOT_CONFIGURED)
REAL BIRTH STATUS     NOT_PERFORMED
SUBJECT               none attached
BABY_AI KEY           not created
FOUNDATION MODEL      none configured
AUTONOMOUS PROCESS    none running
```

What exists is the complete transition machinery: a gated birth ceremony, a
deterministic environment, a subject architecture, and a runtime contract layer
for a model that has not been installed. What does not exist is a mind.

The absence is deliberate. Everything in this project is an *observation
instrument*, and an instrument that also contains the thing it measures cannot be
trusted to report on it. So there is no simulated subject presented as real, no
placeholder agent, and no capability quietly reported as available. When the
Milestone-009 birth ceremony was run, its gate **blocked** on the missing model
and the laboratory ended with no subject — which was the successful outcome, and
the only honest one available.

## Milestones

| Milestone | Delivers | State |
| --- | --- | --- |
| [001](docs/architecture.md) | Instrumentation: event log, provenance ledger, read-only observer, separated control process | complete |
| [002](docs/observatory.md) | The read-only Cognitive State Observatory | complete |
| [003](docs/birth-architecture.md) | The birth ceremony, model identity verification, truthful display | complete |
| [004](docs/m004-trust-boundary.md) | The trust boundary, measured instead of asserted | complete |
| [005](docs/m005-os-isolation.md) | The OS boundary, applied and verified by human cross-process execution | complete |
| [006](docs/m006-runtime.md) | The runtime layer: contracts, hardware probe, governor, llama.cpp adapter | complete, no model |
| [007](docs/m007-environment.md) | The environment and interaction substrate, deterministic and replayable | complete, inert |
| [008](docs/m008-subject.md) | The subject architecture and the first-experience boundary | complete, no subject |
| [009](docs/m009-birth.md) | The gated birth ceremony and first controlled experience | complete, `REAL_BIRTH = NOT_PERFORMED` |

**No model has been installed and no ceremony has been run against real
weights.** `python -m birth.real_model_test` reports `NOT_CONFIGURED` and exits
non-zero, which is the correct result on a fresh installation. The laboratory
never chooses a foundation model for you: no search, no fallback, no download.

## Requirements

Windows 11 and Python 3.14+. No third-party packages are required; `pytest` is
an optional convenience only.

## Quick start

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
python -m unittest discover -s tests -t .
python -m observer.cli
python -m observatory.cli status
python -m birth.cli status
```

## What is here

| Component | Purpose |
| --- | --- |
| `babylab/` | Shared foundations: paths, hashing, storage and locks, clock, identity, trust policy, OS boundary |
| `babylab/runtime/` | Runtime contracts, hardware probe, resource governor, llama.cpp adapter (Milestone 006) |
| `events/` | Append-only, hash-chained event log |
| `provenance/` | HMAC-signed ledger of who changed what, with sealed heads |
| `observer/` | Read-only terminal view of the event stream |
| `observatory/` | Read-only view of what a subject has reported about itself |
| `environment/` | Typed actions, validated consequences, deterministic replayable state (Milestone 007) |
| `subject/` | Subject identity, lifecycle, hash-chained state, first-experience boundary, in-memory harness (Milestone 008) |
| `control/` | Separate privileged process: lifecycle, snapshots, HMAC-authenticated loopback control |
| `human_control/` | Operator area: config, baseline, records, snapshots, seals, keys |
| `birth/` | The birth ceremony, its safety gate, key custody, audit and replay, and read-only status |
| `baby_workspace/` | Reserved for the subject |
| `var/` | Runtime data: `var/events/`, `var/provenance/`, `var/models/`, `var/measurements/` |

Data, secrets, and model weights are not in Git; code and documentation are. See
[docs/git-integration.md](docs/git-integration.md).

## Common commands

```powershell
# Watch the stream (read-only)
python -m observer.cli
python -m observer.cli --summary
python -m observer.cli --namespace security --detail

# Birth: inspect first, act second
python -m birth.cli status           # what the ceremony would find; writes nothing
python -m birth.cli model            # configured model and its verified digest
python -m birth.cli capabilities      # the capability contracts
python -m birth.cli ceremony          # the one command that creates a subject
python -m birth.cli verify            # re-verify the sealed birth record
python -m birth.real_model_test       # explicit real-model check; nonzero if unconfigured

# Cognitive State Observatory (read-only)
python -m observatory.cli status          # summary; with no subject: NO SUBJECT
python -m observatory.cli state           # reported cognitive state
python -m observatory.cli live            # follow, redrawing
python -m observatory.cli history         # state transitions and their causes
python -m observatory.cli --json state    # the versioned snapshot contract
python -m observatory.cli --detail state  # with source event IDs

# Integrity
python -m provenance.cli verify
python -m provenance.cli seal --reason "pre-run baseline"
python -m provenance.cli record --reason "wrote the run notes"   # file created outside the recorder

# Control process
python -m control.cli serve
python -m control.cli status
python -m control.cli snapshot --label before-run
python -m control.cli shutdown

# Tests
python -m unittest discover -s tests -t .
```

Full walkthrough: [docs/operations.md](docs/operations.md).

## The Cognitive State Observatory

The Observatory answers one question: *what has the subject said about itself?*

It is a read-only projection over the canonical event log. It holds derived state
in memory and writes nothing, anywhere, ever. Everything it displays is
traceable to event IDs the reader can open independently.

**With no subject attached it displays nothing, and says so:**

```text
  subject                 NO EXPERIMENTAL SUBJECT ATTACHED
                          Cognitive telemetry unavailable
  events ingested         18
  state versions          0
  reported domains        0
```

That is the correct output, not a failure state. A domain the subject has not
reported renders as `UNAVAILABLE`, never as `[]` or `0`, because *the subject
checked its memory and found nothing* and *the subject never mentioned its
memory* are different claims about a mind.

Event provenance is not identity. An event's `source` field and its payload are
written by whoever produced the event, so neither establishes authorship; a
future subject can write both. Subject identity comes from the human-owned
keyring or it does not exist.

There is no brain picture, no animation, and no psychological vocabulary
anywhere in the package. A test fails the build if terms like `readiness`,
`confidence`, or `mood` appear, because the most likely future addition to this
package would be a well-meant helpfulness field, and that would be an invention
wearing a UI.

See [docs/observatory.md](docs/observatory.md) and
[docs/decisions/ADR-007-cognitive-observatory.md](docs/decisions/ADR-007-cognitive-observatory.md).

## Birth

`python -m birth.cli ceremony` is the only command in this project that creates
a subject. It verifies the configured weights by SHA-256, probes the configured
runtime, appends one `system.baby_ai.born` event, writes one sealed birth
record, and records one signed provenance entry. It refuses to run twice, and it
refuses a fake runtime even when a test asks it to.

**The model is never chosen by the laboratory.** It reads exactly one file,
`human_control/experiment_config/foundation.json`, and if that file is absent the
answer is `NOT_CONFIGURED`. There is no search, no fallback, and no download,
because a system that picks its own substrate makes its own experiments
irreproducible.

The Observatory displays birth state in a `BIRTH / FOUNDATION` section kept
separate from cognitive state, and distinguishes three subject states:

| Status | Means |
| --- | --- |
| `NO_SUBJECT` | No record, no key. |
| `RECORDED` | A birth record exists, but no `BABY_AI` signing key. |
| `ATTACHED` | A human-registered `BABY_AI` key is active. |

`RECORDED` is the honest outcome of running a ceremony, and the display does not
round it up to `ATTACHED`: a birth record says a subject was created, a signing
key says it can prove things, and only a human can grant the second. The two are
independent, and the reverse mismatch is reported too — a key with no birth
record is attached but unrecorded, and says so. The observatory reads this
through `birth.status`, which is structurally incapable of
reaching the ceremony's event-append path — a test walks the import graph to
confirm it.

See [docs/birth-architecture.md](docs/birth-architecture.md) and
[docs/decisions/ADR-008-inherited-substrate.md](docs/decisions/ADR-008-inherited-substrate.md).

## Security posture

Read this before trusting any data this repository produces.

| Tier | Boundary | Status |
| --- | --- | --- |
| 1 | Application policy (`PathPolicy`) | **Active and tested** |
| 2 | OS file permissions (NTFS ACLs) | **Applied and verified** — 11/11 denials, human cross-process |
| 3 | OS account isolation / container | **Not implemented** |

Tier 2 was established and empirically verified in Milestone 005. A
non-administrator account, `THARUNBALAJI-LA\BABY_AI_TEST` (Medium integrity), is
denied 11 protected paths and holds no ACE on either subject workspace. Because
the development process cannot hold `SeImpersonatePrivilege`, the denials were
proven by a human operator running probes in a separate process, with raw output
recorded in
[docs/evidence/m005-final-verification.json](docs/evidence/m005-final-verification.json):

| Probe run as `BABY_AI_TEST` | Result |
| --- | --- |
| read `var/provenance/m005_probe.txt` | `Access is denied.` |
| read `human_control/security/control.token.bak` | `Access is denied.` |
| create/read/delete `baby_workspace/m005_probe.txt` | succeeded |

The third probe matters as much as the two denials: a boundary that refused
everything would prove nothing.

Building that boundary surfaced two real defects, both fixed and both retained in
the evidence file: a leaf deny that left parent directories writable, and an ACL
recovery path that failed *open* rather than closed. Details in
[docs/m005-os-isolation.md](docs/m005-os-isolation.md).

**Two limitations are recorded rather than papered over.** Tier 2 binds a file
boundary to an *account*, not to a running process — nothing executes as
`BABY_AI_TEST` yet, because tier 3 does not exist — and a root-level
`FILE_DELETE_CHILD` capability on the private key directory's parent is not
denied by an explicit ACE. The full threat table is in
[docs/security-model.md](docs/security-model.md).

Provenance signing uses HMAC-SHA256, which is symmetric: the operator who can
verify the ledger can also forge entries. Ed25519 is deferred by decision, to be
adopted before anyone outside this machine verifies anything. See
[ADR-003](docs/decisions/ADR-003-provenance-signing.md).

## Documentation

| Document | Contents |
| --- | --- |
| [architecture.md](docs/architecture.md) | Components, trust boundaries, data placement, extension points |
| [provenance-model.md](docs/provenance-model.md) | Chain construction, signing, seals, threat model |
| [security-model.md](docs/security-model.md) | The three tiers, control-plane auth, key custody, residual risks |
| [observer-interface.md](docs/observer-interface.md) | CLI reference, line format, following, performance |
| [observatory.md](docs/observatory.md) | The Cognitive State Observatory: architecture, commands, guarantees |
| [birth-architecture.md](docs/birth-architecture.md) | The birth ceremony, what a record asserts, and what it refuses to claim |
| [observability-principles.md](docs/observability-principles.md) | The normative rules, each with the test that enforces it |
| [cognitive-state-model.md](docs/cognitive-state-model.md) | State schema, epistemic status, how a subject reports |
| [observatory-api.md](docs/observatory-api.md) | The versioned snapshot contract for a future web client |
| [control-protocol.md](docs/control-protocol.md) | Wire format, authentication, operations, state machine |
| [testing.md](docs/testing.md) | Test tiers, isolation, what the suite caught |
| [windows-integration.md](docs/windows-integration.md) | Locking, encoding, filenames, restricted accounts |
| [git-integration.md](docs/git-integration.md) | What is tracked, and why commits are not identity |
| [operations.md](docs/operations.md) | Day-to-day use, research workflow, troubleshooting |
| [m004-trust-boundary.md](docs/m004-trust-boundary.md) | Measuring the trust boundary instead of asserting it |
| [m005-os-isolation.md](docs/m005-os-isolation.md) | Building and proving the OS boundary, and the two defects it found |
| [m006-runtime.md](docs/m006-runtime.md) | The runtime layer: what a substrate must declare before it can be used |
| [m007-environment.md](docs/m007-environment.md) | Actions, consequences, validation, and why timestamps are not state |
| [m008-subject.md](docs/m008-subject.md) | Subject identity, lifecycle, and the first-experience boundary |
| [m009-birth.md](docs/m009-birth.md) | The gated birth ceremony, T_birth, custody, audit and replay |
| [experiment-log.md](research/experiment-log.md) | Dated research journal |
| [decisions/](docs/decisions/) | ADRs, including the ones still open |

## Design commitments

1. **No simulated subject.** The control plane reports honestly that nothing is
   attached to it. A fake subject would contaminate the first real observation.
2. **Authorship is derived from keys, never declared by the caller.** A declared
   author that conflicts with the key is discarded and the conflict recorded.
   Event `source` fields and payload claims are likewise not evidence of
   authorship.
3. **The observer and the observatory cannot write.** The human's view cannot
   influence the experiment, and the Observatory writes nothing at all - not
   even a derived-state cache. This is structural, not disciplinary: a test walks
   the Observatory's import graph and fails if the ceremony or the provenance
   recorder is reachable from it.
4. **Absence is not a value.** A domain the subject did not report is
   `UNAVAILABLE`, never `[]` or `0`. The type system refuses to construct the
   alternative.
5. **Faults are visible.** A malformed log line is rendered and flagged, never
   silently skipped; a gap in a research log would look like an absence of
   events.
6. **No decoration.** No brain images, no animation, no psychological
   vocabulary. A test fails the build if one appears.
7. **Limitations are written down.** Where a guarantee is not verified, the
   documentation says `NOT VERIFIED` rather than implying otherwise.
8. **The laboratory never chooses the substrate.** No model search, no fallback,
   no download, and no test double in a permanent record. A fake may exist in a
   test; it may never end up in a sealed artefact that outlives it.
9. **Installed is not usable, and existence is not authority.** Verified weights
   do not imply a working runtime, and a birth record does not imply a signing
   key. The status payload and the display keep those apart.
10. **`UNKNOWN` is not `PASS`.** The birth gate blocks whenever it cannot
    establish a prerequisite, and a check that raises blocks rather than passing
    by omission. Absence of a model is a `FAIL`, not a gap in knowledge.
11. **Partial birth cannot look like success.** Every ceremony step is checked
    before the next begins, a failure preserves the evidence gathered so far, and
    there is no code path past a failure. A birth record that exists is a record
    of a completed ceremony.

## License

MIT — see [LICENSE](LICENSE). The copyright holder is a placeholder pending
confirmation.
