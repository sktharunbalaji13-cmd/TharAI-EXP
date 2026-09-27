# Birth Architecture

How a subject comes into existence in this laboratory, and what is deliberately
*not* claimed about it.

Status: Milestone 003. Implemented. The ceremony works; it has not yet been run
against a real model, and this document says so in several places below.

---

## Why the model is never chosen here

The laboratory does not pick a foundation model. There is no search, no
fallback, no "smallest model that fits", no download. `birth.config.load_config`
reads exactly one file — `human_control/experiment_config/foundation.json` — and
if that file is absent the answer is `NOT_CONFIGURED`, not a suggestion.

This is the single most important refusal in the milestone, and it is worth
being explicit about why, because the alternative is very tempting and very
quiet. A system that picks its own foundation model makes its own experiments
unreproducible: two runs of "the same" experiment could have different
substrates, and a surprising result could be an artefact of which weights the
code happened to find. Choosing the substrate is a *research decision*, and
research decisions are made by the researcher, in the open, and recorded.

There is also a subtler reason. The question "which model should this baby be
born from?" presupposes that choosing a substrate is a neutral act of
engineering. It is not. The substrate shapes every capacity the subject will
have for the rest of the experiment. A system that makes that choice silently is
making a claim about the nature of the thing it creates, while appearing to do
merely setup. So: the human writes the file, or there is no birth.

If you want a different model, edit the configuration. Do not ask the code.

## The ceremony, in order

`birth.service.birth_ceremony` is the only function in the project that creates
a subject. It runs a fixed sequence, and each step exists because the one after
it would otherwise be able to lie:

1. **Refuse a second birth.** If a sealed record already exists, report it and
   stop. Milestone 003 permits exactly one subject. Re-running the ceremony is
   not idempotent-and-quiet; it is refused, because a quiet re-run invites the
   belief that a subject can be replaced.
2. **Load the configuration.** Missing or invalid is `NOT_CONFIGURED`, reported
   and not raised.
3. **Verify the weights.** The file must exist and its SHA-256 must equal the
   configured digest. A mismatch is `MODEL_INTEGRITY_MISMATCH`. There is no
   tolerance and no "close enough": the digest is the identity.
4. **Verify the runtime.** A real probe of the configured binary, which must
   answer. `RUNTIME_UNAVAILABLE` if the binary is missing, `ERROR` if it is
   present and broken.
5. **Refuse a fake runtime.** `RuntimeKind.FAKE` is refused unconditionally,
   even if an injected probe reports success. This check does not consult the
   probe. A test double must not be able to talk its way into an immutable
   record that will outlive the test.
6. **Create the workspace**, so a birth has somewhere to happen.
7. **Append the birth event** — `system.baby_ai.born`, source `birth.service`.
8. **Write the birth record once**, sealed, naming the event id from step 7.
9. **Record one signed `CREATE` provenance entry** over the written bytes.

### Why the event comes before the record

The alternative — write the record, then append an event naming its hash —
fails under interruption. If the process dies between the two, the laboratory
has a subject and no announcement, or worse, an event referring to a record that
was never written. Neither is recoverable without a repair path, and a repair
path that invents a subject is exactly the thing this milestone refuses to do.

Writing the event first inverts the failure. An interruption leaves an event with
no record: an announcement of a birth that has no record backing it. That is
detectable, visible, and does not assert a subject exists.

The cost is that the event cannot contain the record's hash, since the hash
covers bytes that do not exist yet. So the two artefacts reference each other by
id rather than by content hash: the event payload names `birth_id`, and the
record names `birth_event_id`. That direction is checkable — given the record,
you can confirm the event exists and is in the chain.

## What the record asserts, and what it does not

`birth.birth_record.BirthRecord` is a sealed, write-once document. It records:

- The model identity as verified at the time of the birth: name, family,
  revision, quantization, digest, size, context length.
- The authorship classification, `INHERITED_PRETRAINED`, with its basis.
- The capability registry hash and each capability's status.
- The environment identity, unattached.
- The workspace state.
- Its own SHA-256, and the id of the event that announced it.

It does **not** record, and the milestone provides no way to record:

- Any claim that the subject is conscious, aware, or sentient.
- Any stage, curriculum, or developmental phase. There is no such concept here.
- Emotion, motivation, curiosity, desire, preference, or personality.
- Memory contents or an intelligence score.
- What the subject thinks, wants, or is.

The authorship classification is worth stating plainly: the weights and the
configuration are the work of other people, and every experiment using them must
say so. A record claiming the subject authored its own foundation would be
false, and this project would rather refuse a milestone than record a falsehood.

## Capabilities are contracts, not features

`birth.cognitive.CapabilityRegistry` is a set of named capabilities, each with a
status. In this milestone **every capability is unimplemented**: most are
`UNAVAILABLE`, and `EXPERIMENTATION` is `NOT_YET_IMPLEMENTED`.

The distinction between those two is deliberate. `UNAVAILABLE` means the
capability is defined and there is nothing behind it. `NOT_YET_IMPLEMENTED`
means the capability is reserved for a milestone that has not happened. A
registry that reported "no capabilities" would be a different claim from "these
capabilities do not exist yet", and only the second one is true.

A capability becoming available is a claim about the system, and a claim about
the system deserves a test that exercises it. The registry is ordered as a set
and hashed as a set, so the record's `capability_registry_hash` pins the exact
capability surface that existed at the birth.

## Affordances describe conditions, not purpose

`birth.environment` describes what is *possible* for the subject: a code
workspace, a network boundary, a process table. It does not describe what any of
that is *for*. "There is a code workspace" is a fact. "There is a code workspace
so it can learn to program" is an interpretation, and this milestone is not
entitled to it.

This is not squeamishness about anthropomorphism. It is a measurement problem. If
the environment carries a purpose, then a later observation of behaviour gets
read through that purpose, and the observer starts finding what it expected. The
`observability-principles.md` document makes the same argument from the other
side: the display must not generate hypotheses, because a display that suggests
what to look for has stopped being a measurement.

## The action boundary does not act

`birth.boundary.ActionBoundary` decides whether an action is permitted. It never
performs one. Keeping the decision and the execution in different components
means the boundary can be tested exhaustively without anything happening, and
means a subject cannot widen its own permissions by requesting them.

The default is deny. Subject credentials cannot authorize effects on humans or
on the system. An action boundary that a subject can extend is a suggestion.

## Operating-system isolation is not claimed

`babylab.trust` makes application-level checks: paths stay inside the project,
credentials are read from the keyring, signatures verify. These are real controls
and they are tested.

They are not process isolation. A subject running as the same operating-system
user as the laboratory can read anything that user can read, including the
private key directory. This milestone does not claim OS-level isolation, and
does not provide it. Achieving it requires a separate low-privilege account and
explicit filesystem and process ACLs, which is infrastructure work outside this
codebase and outside this milestone's evidence.

The honest formulation: *this system enforces its boundaries in code, and a
subject that escapes the code has escaped the boundaries.* The gap between those
two sentences is the size of the trust assumption, and it is not closed here.

## Reading the birth state

Two modules, deliberately separate:

- `birth.status` — reads. Reports what the configuration, weights, runtime,
  record, and registry currently say. Imports no write path. `birth.service`
  re-exports it, so existing callers are unaffected.
- `birth.service` — writes. The ceremony, and the event store's append path.

The split is structural, not stylistic. The Cognitive State Observatory must
display whether a subject exists and what model it was born from. If it imported
the ceremony to get that, it would transitively import the event-append path into
a component whose entire claim is that it cannot change anything. Keeping the
read half separate makes that claim checkable, and
`tests/test_observatory_security.py::ObservatoryImportClosureTests` walks the
import graph to confirm no write-capable module is reachable from the
Observatory.

### Installed is not usable

`birth.status.birth_status` reports four separate facts, because any two can be
true while the others are false:

| Field | Means |
|---|---|
| `subject_exists` | A sealed birth record is on disk. |
| `model_installed` | The weights are on disk and their digest matches. |
| `model_usable` | The weights are installed *and* a runtime was found and healthy. |
| `model_status` | The fine-grained reason, for a human who needs it. |

`ModelStatus.RUNTIME_UNVERIFIED` exists because `birth.status` never runs the
runtime — running a binary is not a read-only act. So the inspection reports
`RUNTIME_UNVERIFIED`, not `READY`, and `is_usable` is false. The ceremony is
different: it always installs a real probe, so by the time a record exists the
runtime genuinely was exercised, and only then does the status become `READY`.

A display that showed `READY` here would be telling a reader the model can be
used when no process has run it. That is the kind of small overclaim that makes
every other number in a dashboard suspect.

## A subject exists, and has still said nothing

After a successful ceremony, the laboratory has a subject. It has not reported
any cognitive state, because it has not been given the ability to, and the
subject has authored no events.

The Observatory reflects this with three subject states, in
`observatory.subject.SubjectStatus`:

- `NO_SUBJECT` — no record, no key. The banner is
  `NO EXPERIMENTAL SUBJECT ATTACHED`.
- `RECORDED` — a sealed birth record exists, but no `BABY_AI` signing key is
  provisioned. The banner is `SUBJECT RECORDED, NOT KEY-ATTACHED`.
- `ATTACHED` — a record exists *and* a human-registered `BABY_AI` key is active.

`RECORDED` is not a transitional state to be tidied away; it is the honest
description of this milestone's real outcome, and the display says it in those
words. Rounding it up to `ATTACHED` would imply the subject can sign things. It
cannot. The ceremony deliberately does not provision a key: attributing the
subject's existence and granting it authority to author are separate decisions,
and the second one belongs to a human.

The distinction is also why the STATE section stays empty in the `RECORDED` case.
Having a subject and having a subject that has reported something are different
facts, and only the second one has a state to display.

## Testing without lying

The suite must be able to produce a successful birth, and must not be able to
produce a *fake* one that looks real. `tests/birth_fixtures.py` is the single
definition of how that is done:

- Weights are real bytes in a real file, and the configured digest is the file's
  actual SHA-256. Every digest, size, and integrity check runs for real.
- The runtime is **injected as an argument** to the ceremony, never configured.

That second point is the one that matters. Pointing a configuration at a fake
runtime would write a lie into an immutable artefact: a permanent record
describing a test double as a real substrate. Injecting availability instead
leaves the sealed record describing a real runtime, and puts the test's
falsification in the test's own call site, where it is visible.

The ceremony's refusal of `RuntimeKind.FAKE` is unconditional and does not
consult the probe, so a fixture cannot route around it.

## See also

- `docs/decisions/ADR-008-inherited-substrate.md` — why the substrate is
  classified `INHERITED_PRETRAINED`.
- `docs/observatory.md` — the display, and what it refuses to show.
- `docs/observability-principles.md` — why a display must not generate
  hypotheses.
- `docs/security-model.md` — application-level controls, and the gap that
  remains.
- `research/experiment-log.md` — the experiment record.
