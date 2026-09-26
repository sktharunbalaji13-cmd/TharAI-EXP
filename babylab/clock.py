"""Time handling.

All timestamps produced by this project are UTC and are formatted as RFC 3339
/ ISO 8601 with a trailing ``Z``.

Milestone 001 note
------------------
The specification's example event uses second precision::

    "2026-09-26T19:00:00Z"

This project emits **millisecond** precision instead::

    "2026-09-26T19:00:00.123Z"

Rationale: the event store is expected to receive bursts of events, and at
second precision many events legitimately share a timestamp, which makes
human-facing observer output ambiguous about ordering. This is a documented
deviation (docs/event-model.md, "Timestamp Precision"). The parser accepts
both precisions, so a second-precision event is still valid input.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

#: Strict RFC 3339 UTC timestamp. Fractional seconds are optional on input.
TIMESTAMP_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})"
    r"T(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?P<fraction>\.\d{1,6})?"
    r"(?P<offset>Z|[+-]\d{2}:\d{2})$"
)


class Clock:
    """A monotonic-enough wall clock that can be replaced in tests.

    Injecting the clock is what lets the test suite assert on exact
    timestamps without sleeping and without introducing flakiness.
    """

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def timestamp(self) -> str:
        return format_timestamp(self.now())


class FixedClock(Clock):
    """A clock that advances by a fixed step on every read.

    Used by tests to produce deterministic, strictly ordered timestamps.
    """

    def __init__(self, start: datetime | None = None, step_seconds: float = 1.0):
        self._current = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self._step = step_seconds

    def now(self) -> datetime:
        from datetime import timedelta

        value = self._current
        self._current = self._current + timedelta(seconds=self._step)
        return value


def format_timestamp(moment: datetime) -> str:
    """Format an aware datetime as ``YYYY-MM-DDTHH:MM:SS.mmmZ``.

    Naive datetimes are rejected rather than silently assumed to be UTC: an
    implicit timezone assumption inside a provenance system is exactly the
    kind of quiet, hard-to-debug error this project tries to avoid.
    """
    if moment.tzinfo is None:
        raise ValueError("refusing to format a naive datetime; supply tzinfo")
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def parse_timestamp(text: str) -> datetime:
    """Parse an RFC 3339 timestamp into an aware UTC datetime.

    Raises :class:`ValueError` on anything malformed, which callers surface
    as a validation error rather than a crash.
    """
    if not isinstance(text, str):
        raise ValueError(f"timestamp must be a string, got {type(text).__name__}")
    match = TIMESTAMP_RE.match(text)
    if match is None:
        raise ValueError(f"malformed timestamp: {text!r}")
    normalised = text[:-1] + "+00:00" if text.endswith("Z") else text
    return datetime.fromisoformat(normalised).astimezone(timezone.utc)
