# ADR-008: The Foundation Model Is an Inherited Substrate

Status: accepted. Milestone 003.

## Context

Every experiment in this project starts from weights somebody else trained. The
question this decision answers is what the birth record should *say* about them.

There is a tempting framing available: the model is part of the baby, the baby
was made from the model, so the baby made itself out of the model and the
authorship is circular or self-referential or — depending on how generously the
question is read — the subject's own. Each of those readings is available and
none of them is defensible.

The opposite temptation is to record nothing, on the grounds that
classifications invite overstatement. That loses information a reader genuinely
needs: given a surprising result, the first question is always about the
substrate, and a record that says nothing about provenance forces that question
to be answered by guessing.

## Decision

Every model identity carries an `authorship` classification from
`birth.authorship`. There is exactly one value in Milestone 003:

```
INHERITED_PRETRAINED
```

with a `basis` string recording the reason it was assigned.

`INHERITED_PRETRAINED` means: the weights were trained by someone else, in a
process this project did not conduct and cannot audit, and the project's only
involvement is loading them. It says nothing good or bad about the training; it
is a provenance statement, not a quality judgement.

## Rationale

`BABY_AI_AUTHORED` is not offered as a value, and that is the substance of the
decision. The subject cannot have authored its own foundation, for the plain
reason that the foundation predates the subject. Claiming otherwise would put a
falsehood into a permanent, signed, tamper-evident artefact — the worst
available place for one, because the whole point of the artefact is that it can
be trusted later.

It also matters what the classification is *not* asked to do. It does not
establish that the subject is unoriginal in general, and it does not establish
that novelty is impossible. A project that trained its own base model would
classify it differently, and that classification would be equally mechanical. The
enum is a description of where weights came from, nothing more.

Recording the basis explicitly, rather than only the label, means a reader can
audit the reasoning rather than take the label on trust — which is the standard
the rest of the provenance system is held to.

## Consequences

- The birth record always states that the substrate was inherited, and a test
  asserts it. A record cannot be written with the subject as the author.
- A reader of any experiment result is told where the substrate came from
  without needing to consult anything else.
- Adding a second classification later — for a model this project trained — is a
  data change, not a design change. The schema is not closed.
- The classification is a claim about *provenance*. It carries no implication
  about consciousness, capability, or authorship of any output the subject
  produces, and the documentation is careful not to let it drift in that
  direction.

## Related

- `docs/birth-architecture.md` — the ceremony and what the record asserts.
- `docs/provenance-model.md` — signing and the trust root.
