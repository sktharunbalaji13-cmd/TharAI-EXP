"""M012 audit: sixteen questions, answered from evidence.

The milestone's requirement is not that the audit *says* the right thing. It is
that each answer **derives from evidence** rather than from a narrative. So every
question here is answered by reading a specific field of the verification record,
and :attr:`AuditAnswer.source` names that field. An answer whose source is missing
becomes ``UNKNOWN`` with the reason, not a confident default -- which is the whole
difference between an audit and a summary.

Re-verification
---------------
:func:`reverify` recomputes every answer from the stored record and compares. A
hand-edited audit therefore fails verification the same way a hand-edited birth
record does in M009: the record is not trusted because it exists, it is trusted
because it can be re-derived.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

AUDIT_SCHEMA = "babylab/m012-audit/v1"


@dataclass(frozen=True)
class AuditAnswer:
    """One question, one answer, and the evidence field it came from."""

    question: str
    answer: Any
    #: The exact path in the verification record this was read from. Empty when
    #: the answer is UNKNOWN, which is itself informative.
    source: str = ""
    state: str = "DERIVED"
    note: str = ""

    @property
    def derived(self) -> bool:
        return self.state == "DERIVED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "source": self.source,
            "state": self.state,
            "derived_from_evidence": self.derived,
            "note": self.note,
        }


def _dig(record: dict[str, Any], path: str) -> tuple[Any, bool]:
    """Read a dotted path out of a record. Returns ``(value, found)``."""
    cursor: Any = record
    for part in path.split("."):
        if isinstance(cursor, dict) and part in cursor:
            cursor = cursor[part]
        else:
            return None, False
    return cursor, True


def _answer(
    record: dict[str, Any],
    question: str,
    path: str,
    *,
    expected: type | tuple[type, ...] | None = None,
    note: str = "",
) -> AuditAnswer:
    """Answer one question by reading one field, or say it could not be read."""
    value, found = _dig(record, path)
    if not found or value is None:
        return AuditAnswer(
            question=question, answer="UNKNOWN", source="", state="UNKNOWN",
            note=note or f"no field {path!r} in the verification record",
        )
    if expected is not None and not isinstance(value, expected):
        return AuditAnswer(
            question=question,
            answer=f"UNEXPECTED_TYPE({type(value).__name__})",
            source=path,
            state="UNKNOWN",
            note=note or (
                f"{path} is {type(value).__name__}, which the audit does not "
                "interpret; an unexpected shape is reported rather than coerced"
            ),
        )
    return AuditAnswer(question=question, answer=value, source=path,
                       state="DERIVED", note=note)


def build_audit(record: dict[str, Any]) -> dict[str, Any]:
    """Answer the milestone's sixteen questions from a verification record."""
    answers: list[AuditAnswer] = [
        _answer(record, "Was the model explicitly selected by the human?",
                "deployment.state",
                note="LOADED means a human wrote the declaration; NOT_CONFIGURED "
                     "means nobody did"),
        _answer(record, "Was the selection attributed to a named human with a reason?",
                "deployment.selection.attributed"),
        _answer(record, "What exact bytes were selected?",
                "artifact.model_path"),
        _answer(record, "What digest identifies them?",
                "artifact.sha256"),
        _answer(record, "Was an external digest supplied?",
                "artifact.external_supplied"),
        _answer(record, "Did the external digest match the computed one?",
                "artifact.verified"),
        _answer(record, "What exact runtime was selected?",
                "deployment.runtime.path"),
        _answer(record, "What runtime identity was observed?",
                "runtime.sha256"),
        _answer(record, "Did the runtime load the model?",
                "compatibility.established_by_load"),
        _answer(record, "Did real inference execute?",
                "inference.is_real_runtime"),
        _answer(record, "Under which process identity?",
                "process_identity.sid"),
        _answer(record, "Were protected writes denied?",
                "probe.protected_denied",
                note="meaningful only when the probe ran as the subject account; "
                     "boundary_meaningful states whether it did"),
        _answer(record, "Was workspace access permitted?",
                "probe.workspace_write_allowed"),
        _answer(record, "Was network absent?",
                "network.policy"),
        _answer(record, "Did model and runtime bytes remain unchanged?",
                "immutability.model_and_runtime_unchanged"),
        _answer(record, "Was determinism characterised?",
                "determinism.verdict"),
    ]

    derived = sum(1 for a in answers if a.derived)
    return {
        "schema": AUDIT_SCHEMA,
        "answers": [a.to_dict() for a in answers],
        "derived_count": derived,
        "unknown_count": sum(1 for a in answers if a.state == "UNKNOWN"),
        "summary": {
            "all_questions_derived": derived == len(answers),
            "unanswered_questions": [
                a.question for a in answers if not a.derived
            ],
        },
        "method": (
            "every answer is read from a named field of the verification record. "
            "A field that is absent or of an unexpected type yields UNKNOWN with "
            "the reason, never a confident default."
        ),
    }


def reverify(audit: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Recompute every answer and report the disagreements.

    A doctored answer does not survive this: the rebuilt value is compared field
    by field, and any difference is named. A passing audit is therefore a
    statement about the record, not about the file containing the audit.
    """
    rebuilt = build_audit(record)
    original = {
        item.get("question"): item.get("answer")
        for item in audit.get("answers", []) if isinstance(item, dict)
    }
    disagreements: list[dict[str, Any]] = []

    for item in rebuilt["answers"]:
        question = item["question"]
        if question not in original:
            disagreements.append({
                "question": question, "in_audit": None,
                "recomputed": item["answer"], "issue": "question missing from the audit",
            })
        elif original[question] != item["answer"]:
            disagreements.append({
                "question": question, "in_audit": original[question],
                "recomputed": item["answer"], "issue": "answer disagrees with the record",
            })

    for question in original:
        if question not in {i["question"] for i in rebuilt["answers"]}:
            disagreements.append({
                "question": question, "in_audit": original[question],
                "recomputed": None, "issue": "question is not one the audit asks",
            })

    return {
        "verified": not disagreements,
        "disagreements": disagreements,
        "checked": len(rebuilt["answers"]),
        "detail": (
            "every answer was re-derived from the verification record and matched"
            if not disagreements
            else f"{len(disagreements)} answer(s) could not be re-derived from the "
                 "record; see the disagreements"
        ),
    }


def write_audit(audit: dict[str, Any], path: str | Path) -> Path:
    """Write the audit. The only writer, and it writes a finished product."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    return target


__all__ = [
    "AUDIT_SCHEMA",
    "AuditAnswer",
    "build_audit",
    "reverify",
    "write_audit",
]
