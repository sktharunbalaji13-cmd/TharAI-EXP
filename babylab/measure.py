"""Epistemic status for measured values.

Why this lives here
-------------------
``Measurement`` was introduced in Milestone 006 inside ``babylab.runtime``. By
Milestone 007 it was needed by the environment, which must be able to run with
no model runtime present at all. Leaving it inside the runtime package made the
environment import a package it has no business depending on -- a coupling that
was invisible until a test looked for it.

So the type moved here, to a neutral module, and ``babylab.runtime.contract``
re-exports it. Nothing about the type changed; only its address.

The discipline it encodes
-------------------------
A value that could not be measured is ``UNAVAILABLE``, which is a real answer
and not a zero. A value computed from other measurements is ``DERIVED`` and is
never presented as ``OBSERVED``. The status is a required field rather than
optional metadata, so it cannot be dropped by a caller who finds it
inconvenient.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any


class EpistemicStatus(str, enum.Enum):
    """How a value came to be known. Never omitted."""

    #: Read directly from the host, the runtime, or the environment state.
    OBSERVED = "OBSERVED"
    #: Computed from observed values by a stated rule.
    DERIVED = "DERIVED"
    #: Could not be measured. A real answer, not a failure to paper over.
    UNAVAILABLE = "UNAVAILABLE"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True)
class Measurement:
    """A value plus how we came to know it."""

    value: Any
    status: EpistemicStatus
    unit: str = ""
    source: str = ""

    @classmethod
    def observed(cls, value: Any, unit: str = "", source: str = "") -> "Measurement":
        return cls(value, EpistemicStatus.OBSERVED, unit, source)

    @classmethod
    def derived(cls, value: Any, unit: str = "", source: str = "") -> "Measurement":
        return cls(value, EpistemicStatus.DERIVED, unit, source)

    @classmethod
    def unavailable(cls, reason: str = "not measurable here") -> "Measurement":
        return cls(None, EpistemicStatus.UNAVAILABLE, "", reason)

    @property
    def is_available(self) -> bool:
        return self.status is not EpistemicStatus.UNAVAILABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "status": self.status.value,
            "unit": self.unit,
            "source": self.source,
        }


__all__ = ["EpistemicStatus", "Measurement"]
