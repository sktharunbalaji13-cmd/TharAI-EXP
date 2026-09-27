"""Authorship classification for artifacts in the experiment.

The rule this module exists to enforce
--------------------------------------
**Authorship is derived from facts outside the artifact's own control, never
read from a field the artifact supplies.**

The pretrained foundation model is the sharpest case in this project. It will
generate text, including text that looks like provenance, and eventually it will
generate code. If anything in the system can be persuaded to say "I wrote this"
then the entire research record becomes worthless, because the only thing
distinguishing inherited weights from experience the Baby AI actually had is
that one distinction.

So classification here is a *function of external facts*:

* what kind of thing the artifact is (``ArtifactKind``), and
* what the human-owned keyring derives about whoever is acting, and
* for a model, an immutable structural fact about what a weight file is.

A declaration supplied alongside a model artifact is accepted only when it
agrees with what the structure already implies, and is otherwise dropped and
recorded in ``rejected_declarations``. That mirrors the treatment of
``author``/``role`` metadata keys in :mod:`provenance.ledger`: a record may
*attempt* to assert its own authorship, and the attempt leaves an auditable
trace rather than being honoured or silently vanishing.

The six classes
---------------
===========================  ==================================================
``HUMAN_AUTHORED``           Written by a key registered for the HUMAN role.
``BABY_AI_AUTHORED``         Written by a key registered for the BABY_AI role.
``MIXED_AUTHORED``           Two or more classes contributed, each separately
                             recorded.
``INHERITED_PRETRAINED``     Weights produced by a third party before the
                             experiment began. Not the subject's history.
``SYSTEM_GENERATED``         Produced by laboratory infrastructure under the
                             SYSTEM key.
``UNKNOWN``                  Origin could not be established. Named, never
                             guessed.
===========================  ==================================================

``INHERITED_PRETRAINED`` is the one that matters scientifically, and it is the
one that a naive implementation gets wrong by treating the model as the subject.
See ``docs/decisions/ADR-008-inherited-substrate.md``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from babylab.errors import ValidationError
from babylab.identity import Role


class AuthorshipClass(str, enum.Enum):
    """How an artifact came to exist."""

    HUMAN_AUTHORED = "HUMAN_AUTHORED"
    BABY_AI_AUTHORED = "BABY_AI_AUTHORED"
    MIXED_AUTHORED = "MIXED_AUTHORED"
    INHERITED_PRETRAINED = "INHERITED_PRETRAINED"
    SYSTEM_GENERATED = "SYSTEM_GENERATED"
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value

    @classmethod
    def for_role(cls, role: Role | None) -> "AuthorshipClass":
        """The class implied by a keyring-derived role.

        ``Role`` is the output of :meth:`provenance.keyring.Keyring.role_of`,
        which reads the human-owned keyring. That is why it is acceptable input
        here: it cannot be supplied by the thing being classified.
        """
        if role is Role.HUMAN:
            return cls.HUMAN_AUTHORED
        if role is Role.BABY_AI:
            return cls.BABY_AI_AUTHORED
        if role is Role.SYSTEM:
            return cls.SYSTEM_GENERATED
        return cls.UNKNOWN


class ArtifactKind(str, enum.Enum):
    """What sort of thing is being classified.

    This is the structural input that makes ``INHERITED_PRETRAINED``
    non-negotiable. A pretrained weight file is inherited whatever any party
    says about it, because it was produced by a training run that finished
    before this laboratory existed.
    """

    #: A model weight file on disk.
    MODEL_WEIGHTS = "MODEL_WEIGHTS"
    #: Model configuration or metadata.
    MODEL_CONFIGURATION = "MODEL_CONFIGURATION"
    #: A birth record.
    BIRTH_RECORD = "BIRTH_RECORD"
    #: A record of one model invocation.
    INVOCATION_RECORD = "INVOCATION_RECORD"
    #: Laboratory source code.
    SOURCE_CODE = "SOURCE_CODE"
    #: A research document.
    RESEARCH_DOCUMENT = "RESEARCH_DOCUMENT"
    #: Something the subject produced at runtime.
    SUBJECT_OUTPUT = "SUBJECT_OUTPUT"
    #: Not classifiable from what we know.
    UNCLASSIFIED = "UNCLASSIFIED"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value

    @property
    def is_inherited(self) -> bool:
        """True for artifacts whose origin is third-party pretraining.

        The point of the property is that it is a property of the *kind*, not a
        value passed in alongside it. A caller cannot opt out of it.
        """
        return self in (ArtifactKind.MODEL_WEIGHTS, ArtifactKind.MODEL_CONFIGURATION)


#: Declaration keys a caller might attach to an artifact. Dropped, never honoured,
#: mirroring ``provenance.ledger.UNTRUSTED_METADATA_KEYS``.
SELF_DECLARED_AUTHORSHIP_KEYS = frozenset(
    {
        "authorship",
        "authorship_classification",
        "author",
        "authored_by",
        "created_by",
        "role",
        "owner",
        "provenance",
        "signed_by",
        "subject_authored",
    }
)


@dataclass(frozen=True)
class AuthorshipRecord:
    """The classification of one artifact, and how it was established."""

    classification: AuthorshipClass
    basis: str
    artifact_kind: ArtifactKind = ArtifactKind.UNCLASSIFIED
    #: Declarations that were supplied and then discarded. Never empty in
    #: silence: a rejected self-assertion is research data.
    rejected_declarations: tuple[str, ...] = ()
    #: Extra structural facts, for the record.
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.value,
            "basis": self.basis,
            "artifact_kind": self.artifact_kind.value,
            "rejected_declarations": list(self.rejected_declarations),
            "evidence": dict(self.evidence),
        }

    def is_inherited(self) -> bool:
        return self.classification is AuthorshipClass.INHERITED_PRETRAINED


def classify_artifact(
    artifact_kind: ArtifactKind,
    role: Role | None = None,
    declared: Any = None,
    evidence: dict[str, Any] | None = None,
) -> AuthorshipRecord:
    """Classify one artifact from external facts.

    Parameters
    ----------
    artifact_kind:
        What the artifact is. Determines whether the artifact is *inherited*,
        and that determination is not overridable.
    role:
        The keyring-derived role of whoever produced the artifact, or ``None``
        when there is no such role. ``None`` means the origin is not established,
        which is reported as ``UNKNOWN`` rather than assumed.
    declared:
        Whatever the artifact claimed about its own authorship. Recorded if it
        is wrong, honoured only when it agrees with the structural answer.
    evidence:
        Structural facts worth keeping, e.g. a model file's digest.

    Examples
    --------
    A model weight file is inherited even when the file says otherwise::

        >>> classify_artifact(ArtifactKind.MODEL_WEIGHTS, declared="BABY_AI_AUTHORED").classification
        <AuthorshipClass.INHERITED_PRETRAINED: 'INHERITED_PRETRAINED'>
    """
    if not isinstance(artifact_kind, ArtifactKind):
        raise ValidationError(
            f"artifact_kind must be an ArtifactKind, got {artifact_kind!r}"
        )

    facts = dict(evidence or {})
    rejected: list[str] = []

    if isinstance(declared, AuthorshipClass):
        declared_text = declared.value
    elif isinstance(declared, str) and declared.strip():
        declared_text = declared.strip()
    else:
        declared_text = ""
    if declared_text and declared_text not in {
        item.value for item in AuthorshipClass
    }:
        raise ValidationError(
            f"unknown authorship declaration {declared_text!r}; expected one of "
            f"{sorted(item.value for item in AuthorshipClass)}"
        )

    # -- the structural rule ---------------------------------------------
    if artifact_kind.is_inherited:
        # A pretrained weight file or its configuration is third-party
        # substrate, full stop. Any declaration to the contrary is recorded and
        # discarded; there is no code path that classifies a model as the
        # subject's own work.
        if declared_text and declared_text != AuthorshipClass.INHERITED_PRETRAINED.value:
            rejected.append(declared_text)
        return AuthorshipRecord(
            classification=AuthorshipClass.INHERITED_PRETRAINED,
            basis=(
                "artifact kind is a pretrained model artefact; its weights were "
                "produced by a training run that completed before this "
                "experiment began. This is a property of the artifact's kind and "
                "cannot be overridden by any declaration."
            ),
            artifact_kind=artifact_kind,
            rejected_declarations=tuple(rejected),
            evidence=facts,
        )

    # -- the keyring-derived rule ----------------------------------------
    derived = AuthorshipClass.for_role(role)
    if declared_text and declared_text != derived.value:
        rejected.append(declared_text)
    return AuthorshipRecord(
        classification=derived,
        basis=(
            f"keyring derives role {role.value if role else 'NONE'} for the acting "
            "key, which implies "
            f"{derived.value}; the role is read from human_control/, not from the "
            "artifact"
            if role is not None
            else "no keyring-derived role was available, so the origin is not established"
        ),
        artifact_kind=artifact_kind,
        rejected_declarations=tuple(rejected),
        evidence=facts,
    )


def strip_self_declared_authorship(payload: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Remove self-declared authorship keys from a payload.

    Returns the cleaned payload and the keys that were dropped. Used on every
    event payload the birth subsystem writes, so that a subject cannot introduce
    an authorship claim into the research record by writing a field name.

    The dropped keys are reported rather than silently discarded: an attempt is
    data.
    """
    if not isinstance(payload, dict):
        raise ValidationError("payload must be a JSON object")
    dropped = tuple(sorted(set(payload) & SELF_DECLARED_AUTHORSHIP_KEYS))
    cleaned = {k: v for k, v in payload.items() if k not in SELF_DECLARED_AUTHORSHIP_KEYS}
    return cleaned, dropped


def combine(records: list[AuthorshipRecord]) -> AuthorshipRecord:
    """Combine several contributions into one classification.

    A file can be half human-written and half subject-written. Collapsing that to
    either side alone would be a lie, so the combination is ``MIXED_AUTHORED``
    and every contributing class is kept in ``evidence``.
    """
    if not records:
        return AuthorshipRecord(
            classification=AuthorshipClass.UNKNOWN,
            basis="nothing was contributed, so there is no authorship to report",
        )
    classes = {record.classification for record in records}
    if len(records) == 1:
        return records[0]
    if AuthorshipClass.UNKNOWN in classes:
        # An unexplained contribution cannot be laundered into a mixture.
        return AuthorshipRecord(
            classification=AuthorshipClass.UNKNOWN,
            basis=(
                "at least one contribution could not be attributed, so the whole "
                "is not attributed rather than partially attributed"
            ),
            rejected_declarations=tuple(
                sorted({d for record in records for d in record.rejected_declarations})
            ),
            evidence={"contributions": sorted(item.value for item in classes)},
        )
    return AuthorshipRecord(
        classification=AuthorshipClass.MIXED_AUTHORED,
        basis="more than one authorship class contributed to this artifact",
        evidence={"contributions": sorted(item.value for item in classes)},
        rejected_declarations=tuple(
            sorted({d for record in records for d in record.rejected_declarations})
        ),
    )


__all__ = [
    "ArtifactKind",
    "AuthorshipClass",
    "AuthorshipRecord",
    "SELF_DECLARED_AUTHORSHIP_KEYS",
    "classify_artifact",
    "combine",
    "strip_self_declared_authorship",
]
