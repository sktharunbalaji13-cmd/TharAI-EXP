"""M014 read surface for the Observatory.

Extends :mod:`birth.m013_status` with what M014 established, and executes
nothing. It reads a declaration and reports a birth record if one exists; it
cannot verify an artifact, invoke a runtime, launch a process under the subject
account, or run a ceremony.

That boundary is inherited rather than restated: :mod:`birth.m013_status` already
refuses to import anything that can execute, and this module defers to it for the
gate verdict instead of computing one. A second gate evaluation here would be a
second thing to keep correct, and it would be evaluated from different evidence
than the ceremony's, which is exactly how a display and a decision come to
disagree.

Consequence, stated rather than worked around: this surface cannot report a
READY gate. The evidence READY requires is produced by the verification command,
and M014 must not hand that to a display.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: The M014 modules that can execute something.
M014_EXECUTION_MODULES: tuple[str, ...] = (
    "m014.py",
)

#: Vocabulary this surface must never report. M011 forbade it for runtime
#: telemetry and M012 forbade it for deployment status; a birth record is the
#: most tempting place to reach for it, because a record of a subject's first
#: experience is exactly the kind of document that invites an inference.
FORBIDDEN_DISPLAY_TERMS: tuple[str, ...] = (
    "intelligence",
    "consciousness",
    "conscious",
    "sentience",
    "sentient",
    "awareness",
    "personality",
    "curiosity",
    "emotion",
    "motivation",
    "developmental score",
    "learning score",
    "readiness",
)


def birth_record_only(root: str | Path | None = None) -> dict[str, Any]:
    """Report M014's outcome from files alone. Performs no birth and no check."""
    from birth.m013_status import ceremony_only
    from birth.record14 import birth_record_path, compute_birth_record_hash

    if root is None:
        from babylab.paths import default_paths

        root = default_paths().root

    path = birth_record_path(root)
    record_present = path.is_file()

    gate = ceremony_only(root)

    payload: dict[str, Any] = {
        "schema": "babylab/m014-status/v1",
        "source": "declaration_and_record_only",
        "state": gate.get("state"),
        "may_proceed": gate.get("may_proceed", False),
        "real_birth": "PERFORMED" if record_present else "NOT_PERFORMED",
        "subject": "UNKNOWN" if record_present else "NONE",
        "first_experience": "UNKNOWN" if record_present else "NOT_PERFORMED",
        "t_birth": "UNAVAILABLE",
        "lifecycle": "UNKNOWN" if record_present else "UNCREATED",
        "experience_count": "UNAVAILABLE",
        "birth_record_present": record_present,
        "birth_record_path": str(path),
        "prerequisites": gate.get("prerequisites", []),
        "note": (
            "read from the deployment declaration and, if one exists, the birth "
            "record. This panel runs no verification, invokes no runtime, launches "
            "no process, and performs no ceremony; it also cannot report a READY "
            "gate, because the evidence READY requires comes from the "
            "verification command. No field here is inferred from a subject's "
            "output."
        ),
        "forbidden_display_terms": list(FORBIDDEN_DISPLAY_TERMS),
    }

    if record_present:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            payload["record_error"] = f"the birth record could not be read: {exc}"
        else:
            ceremony = record.get("ceremony") or record
            payload.update({
                "subject": ceremony.get("subject_id") or "NONE",
                "t_birth": ceremony.get("t_birth", "UNAVAILABLE"),
                "lifecycle": ceremony.get("lifecycle", "UNCREATED"),
                "birth_record_hash": compute_birth_record_hash(record),
                "first_experience": (
                    "RECORDED" if ceremony.get("first_experience")
                    else "NOT_PERFORMED"
                ),
                "experience_count": ceremony.get("experience_count_final")
                if ceremony.get("experience_count_final") is not None
                else "UNAVAILABLE",
                "second_interaction": ceremony.get(
                    "second_interaction", "UNAVAILABLE"),
                "identity_issuer": ceremony.get("identity_issuer")
                or "UNAVAILABLE",
            })

    return payload


__all__ = ["FORBIDDEN_DISPLAY_TERMS", "M014_EXECUTION_MODULES",
           "birth_record_only"]
