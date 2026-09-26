"""Cognitive State Observatory.

A read-only consumer of the canonical event log. It reports what a subject has
said about itself, marks the difference between a reported value and an absent
one, and cites the events behind every number it shows.

Milestone 002 ships with no subject. ``observatory.cli status`` says so, and
that is the correct output, not a failure state.
"""

from observatory.model import (
    CognitiveState,
    EpistemicStatus,
    StateTransition,
    StateValue,
)
from observatory.subject import (
    NO_SUBJECT_BANNER,
    NO_SUBJECT_DETAIL,
    SubjectRegistry,
    SubjectStatus,
)

__all__ = [
    "CognitiveState",
    "EpistemicStatus",
    "StateTransition",
    "StateValue",
    "SubjectRegistry",
    "SubjectStatus",
    "NO_SUBJECT_BANNER",
    "NO_SUBJECT_DETAIL",
]
