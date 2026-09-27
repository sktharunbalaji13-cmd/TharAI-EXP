# Baby AI Laboratory

Research instrumentation for observing a self-hosted AI system.

**Milestones 001 and 002 delivered the laboratory and its instruments only.**
**Milestone 003 adds the birth ceremony and the subject it can create.**

There is still no AI here. Milestone 003 does not create a mind, and says so in
the code, the schema, and the display. What it adds is the ability for a
*human-configured* model to be born as a single, immutable, signed subject, and
for that fact to be reported truthfully. No model, agent, memory, goals, or
self-modification exists; no stage, curriculum, or emotional state is claimed;
and no capability is implemented. The absence is deliberate: an instrument that
contains the thing it measures cannot be trusted to report on it. See
[docs/architecture.md](docs/architecture.md),
[docs/birth-architecture.md](docs/birth-architecture.md), and
[docs/decisions/ADR-004-no-event-taxonomy.md](docs/decisions/ADR-004-no-event-taxonomy.md).

**No model has been installed and no ceremony has been run against a real
model.** `python -m birth.real_model_test` reports `NOT_CONFIGURED` and exits
non-zero, which is the correct result on a fresh installation. The laboratory
never chooses a foundation model for you.

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
| `babylab/` | Shared foundations: paths, hashing, storage and locks, clock, identity, trust policy |
| `events/` | Append-only, hash-chained event log |
| `provenance/` | HMAC-signed ledger of who changed what, with sealed heads |
| `observer/` | Read-only terminal view of the event stream |
| `observatory/` | Read-only view of what a subject has reported about itself |
| `control/` | Separate privileged process: lifecycle, snapshots, HMAC-authenticated loopback control |
| `human_control/` | Operator area: config, baseline, records, snapshots, seals, keys |
| `birth/` | The birth ceremony, model identity verification, and read-only birth status |
| `baby_workspace/` | Reserved for the subject |
| `var/` | Runtime data: `var/events/`, `var/provenance/`, `var/models/` |

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
| 2 | OS file permissions (NTFS ACLs) | **Scripted, not applied, not verified** |
| 3 | OS account isolation / container | **Not implemented** |

Only tier 1 is in force, and it is the weakest of the three: it catches
accidents and attributes privileged writes, but a subject sharing the Windows
user can bypass it entirely. Tier 2 needs an elevated session and a second
account, neither of which was available during development
(`IsAdmin` → `False`, `net user` → `Access is denied`).

Provenance signing uses HMAC-SHA256, which is symmetric: the operator who can
verify the ledger can also forge entries. Ed25519 is deferred by decision, to be
adopted before anyone outside this machine verifies anything. See
[ADR-003](docs/decisions/ADR-003-provenance-signing.md).

Details and the full threat table: [docs/security-model.md](docs/security-model.md).

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

## License

MIT — see [LICENSE](LICENSE). The copyright holder is a placeholder pending
confirmation.
