"""Rendering events for a human reader.

Target output shape, from the specification::

    [19:00:01] SYSTEM
    Observer started

A timestamp, a category, and one sentence. The restraint is intentional: this
is a research instrument that will be read for hours at a time, often while
something else is happening. Anything decorative costs attention that should go
to the content.

Category derivation
-------------------
The category is the first segment of ``event_type``, uppercased. It is derived
from data the laboratory produced, not supplied by a producer, so two
components cannot disagree about how the same event is labelled.

Colour
------
ANSI colour is used only when the output stream is a TTY, ``NO_COLOR`` is unset,
and ``--no-color`` was not passed. Piped output stays plain so that logs and
diffs stay readable.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import TextIO

from events.model import Event

#: Distinct, deliberately colour-blind-safe hues. No colour is ever the sole
#: carrier of meaning; every line is legible in plain text.
CATEGORY_COLOURS = {
    "SYSTEM": "38;5;245",
    "SECURITY": "38;5;203",
    "PROVENANCE": "38;5;108",
    "CONTROL": "38;5;180",
    "OBSERVER": "38;5;245",
    "TRUST": "38;5;179",
}
DEFAULT_COLOUR = "38;5;250"
DIM = "38;5;240"
BOLD = "1"

RESET = "\033[0m"

#: Long payloads are truncated in the single-line view so that one enormous
#: event cannot scroll everything else off the screen.
MAX_HEADLINE_CHARS = 200

#: Width of the category column. Fixed so that every event in a session
#: aligns, which is what makes a long stream scannable by eye.
CATEGORY_WIDTH = 11

ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def supports_colour(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("BABYLAB_FORCE_COLOR"):
        return True
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def category_of(event_type: str) -> str:
    return event_type.split(".", 1)[0].upper()


def fit_category(category: str, width: int = CATEGORY_WIDTH) -> str:
    """Right-truncate an over-long category so the column never shifts.

    A namespace longer than the column is truncated rather than allowed to
    push the headline out of alignment. The full ``event_type`` remains
    available via ``--source`` and ``--detail``, so nothing is lost - only the
    one-line view is abbreviated.
    """
    if len(category) <= width:
        return category.ljust(width)
    return category[: width - 1] + "…"


def short_time(timestamp: str) -> str:
    """``2026-09-26T19:00:01.123Z`` -> ``19:00:01``.

    The date is dropped because the observer is for watching a session live.
    It remains available in ``--detail`` mode and in the raw event log, so
    nothing is lost.
    """
    if "T" not in timestamp:
        return timestamp
    time_part = timestamp.split("T", 1)[1]
    return time_part.rstrip("Z").split(".", 1)[0]


@dataclass
class RenderOptions:
    colour: bool = False
    detail: bool = False
    show_source: bool = False
    show_hash: bool = False
    max_headline: int = MAX_HEADLINE_CHARS


class Renderer:
    """Turns events into terminal lines."""

    def __init__(self, options: RenderOptions | None = None, stream: TextIO | None = None):
        self.options = options or RenderOptions()
        self.stream = stream or sys.stdout
        if stream is not None:
            self.options.colour = False

    # -- colouring --------------------------------------------------------
    def _paint(self, text: str, code: str) -> str:
        if not self.options.colour:
            return text
        return f"\033[{code}m{text}{RESET}"

    # -- rendering --------------------------------------------------------
    def header(self, title: str, subtitle: str = "") -> list[str]:
        lines = [self._paint(title, BOLD)]
        if subtitle:
            lines.append(self._paint(subtitle, DIM))
        lines.append(self._paint("─" * 60, DIM))
        return lines

    def event_lines(self, event: Event) -> list[str]:
        """Two or more lines describing one event."""
        category = category_of(event.event_type)
        colour = CATEGORY_COLOURS.get(category, DEFAULT_COLOUR)
        stamp = self._paint(f"[{short_time(event.timestamp)}]", DIM)
        label = self._paint(fit_category(category), colour)
        headline = _ellipsise(event.headline(), self.options.max_headline)

        lines = [f"{stamp} {label} {headline}"]

        if self.options.show_source:
            lines.append(self._paint(f"{'':<14}{event.source}  {event.event_type}", DIM))
        if self.options.show_hash:
            lines.append(self._paint(f"{'':<14}{event.event_id}  {event.hash[:16]}", DIM))
        if self.options.detail:
            lines.extend(self._detail_lines(event))
        return lines

    def _detail_lines(self, event: Event) -> list[str]:
        import json

        from babylab.hashing import canonical_json

        body = canonical_json(event.payload)
        try:
            pretty = json.dumps(json.loads(body), indent=2, sort_keys=True)
        except ValueError:  # pragma: no cover - canonical_json always emits JSON
            pretty = body
        rendered = [self._paint(f"{'':<14}{line}", DIM) for line in pretty.splitlines()]
        return rendered

    def malformed_lines(self, line_number: int, raw: str, error: str) -> list[str]:
        """A fault must be visible, not swallowed."""
        label = self._paint(fit_category("MALFORMED"), "38;5;203")
        excerpt = _ellipsise(raw.strip(), 80) or "<empty line>"
        return [
            f"{self._paint('[line]', DIM)} {label} {excerpt}",
            self._paint(f"{'':<14}reason: {error}", DIM),
        ]

    def notice(self, text: str) -> list[str]:
        return [self._paint(f"  {text}", DIM)]

    def error(self, text: str) -> list[str]:
        return [self._paint(f"  error: {text}", "38;5;203")]


def _ellipsise(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def strip_ansi(text: str) -> str:
    """Remove ANSI sequences. Used by the tests and by ``--plain`` output."""
    return ANSI_RE.sub("", text)
