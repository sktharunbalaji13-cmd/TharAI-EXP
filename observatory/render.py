"""Rendering a snapshot to text.

Two rules govern everything in this file.

**Rule one: an absence is never drawn as a value.** Unavailable domains print
``UNAVAILABLE``. A domain the subject has not reported is not ``{}`` and not
``-`` and not a blank line. The renderer has no way to print an unreported
domain as though it were data, because
:meth:`observatory.model.CognitiveState.get` hands it a marked
:class:`~observatory.model.StateValue` rather than a raw value.

**Rule two: the no-subject state is stated, not implied.** There is a banner
line, and when there is no subject it is the only thing the state section
attempts to say. A screen full of infrastructure statistics could otherwise
read as a working instrument observing something, and the reader's eye would
slide past the one line that matters.

Colour is optional throughout. ``NO_COLOR`` and non-TTY output both degrade to
plain text, so a piped log is not full of escape codes.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from observer.format import DIM, RESET, supports_colour
from observatory.graph import EdgeKind
from observatory.model import EpistemicStatus
from observatory.snapshot import ObservatorySnapshot

#: Hues borrowed from the terminal observer so a session is visually
#: consistent, plus one amber used only for the no-subject banner.
FG_GREEN = "38;5;108"
FG_YELLOW = "38;5;180"
FG_RED = "38;5;203"

WIDTH = 78


@dataclass(frozen=True)
class RenderOptions:
    """Display options. ``detail`` adds traceability, which is off by default."""

    color: bool = False
    detail: bool = False
    width: int = WIDTH
    show_ingest: bool = True
    show_events: bool = True


class ObservatoryRenderer:
    """Turns an :class:`ObservatorySnapshot` into text.

    No state of its own beyond the options, so the same snapshot always renders
    the same way. That is what makes the output testable.
    """

    def __init__(self, options: RenderOptions | None = None):
        self.options = options or RenderOptions()

    # -- helpers ----------------------------------------------------------
    def _c(self, text: str, *codes: str) -> str:
        if not self.options.color or not codes:
            return text
        return "\033[" + ";".join(codes) + "m" + text + RESET

    def _rule(self, title: str = "") -> str:
        if not title:
            return "-" * self.options.width
        return f"-- {title} " + "-" * max(0, self.options.width - len(title) - 4)

    def _kv(self, key: str, value: str, pad: int = 18) -> str:
        return f"  {key.ljust(pad)}{value}"

    # -- sections ---------------------------------------------------------
    def header(self, snapshot: ObservatorySnapshot) -> list[str]:
        lines = ["=" * self.options.width, "  BABY LAB :: COGNITIVE STATE OBSERVATORY", "=" * self.options.width]
        no_subject = snapshot.subject_banner.startswith("NO EXPERIMENTAL")
        if no_subject:
            lines.append("")
            lines.append("  " + self._c(snapshot.subject_banner, FG_YELLOW, "1"))
            if snapshot.subject_detail:
                lines.append("  " + self._c(snapshot.subject_detail, DIM))
        else:
            lines.append("")
            lines.append("  " + self._c(snapshot.subject_banner, FG_GREEN, "1"))
        if snapshot.generated_at:
            lines.append(self._kv("observed at", snapshot.generated_at))
        return lines

    def state_section(self, snapshot: ObservatorySnapshot) -> list[str]:
        lines = [self._rule("STATE")]
        if snapshot.subject_banner.startswith("NO EXPERIMENTAL"):
            lines.append("  " + self._c("No subject attached: no cognitive state to display.", DIM))
            lines.append("  " + self._c("This is the expected result for this milestone.", DIM))
            return lines

        state = snapshot.state
        if state.version == 0:
            lines.append("  " + self._c("Subject attached but has not reported any state yet.", DIM))
            return lines

        lines.append(self._kv("state version", f"v{state.version}"))
        if state.last_event_id:
            lines.append(self._kv("last report", state.last_event_id))
        lines.append("")

        for domain in state.ordered_domains():
            value = state.get(domain)
            status = value.status
            if status is EpistemicStatus.OBSERVED:
                colour = FG_GREEN
            elif status is EpistemicStatus.DERIVED:
                colour = FG_YELLOW
            else:
                colour = DIM
            lines.append(
                f"  {domain.ljust(20)}{self._c(value.display(), colour)}"
                f"  {self._c(f'[{status.value}]', DIM)}"
            )
            if self.options.detail and value.note:
                lines.append("  " + " " * 20 + self._c(f"note: {value.note}", DIM))
            if self.options.detail and value.source_event_ids:
                for event_id in value.source_event_ids:
                    lines.append("  " + " " * 20 + self._c(f"source: {event_id}", DIM))
        return lines

    def graph_section(self, snapshot: ObservatorySnapshot) -> list[str]:
        lines = [self._rule("RELATIONSHIPS")]
        graph = snapshot.graph
        if graph.is_empty:
            lines.append("  " + self._c("No relationships have been reported.", DIM))
            if snapshot.subject_banner.startswith("NO EXPERIMENTAL"):
                lines.append("  " + self._c("Telemetry unavailable: nothing to relate.", DIM))
            return lines
        for line in graph.to_ascii(self.options.width).splitlines():
            lines.append("  " + line)
        if self.options.detail:
            for edge in graph.edges:
                if edge.kind is EdgeKind.REPORTED:
                    lines.append(
                        "  " + self._c(f"  {edge.source} -> {edge.target} (reported by subject)", DIM)
                    )
        return lines

    def events_section(self, snapshot: ObservatorySnapshot) -> list[str]:
        if not self.options.show_events or not snapshot.recent_events:
            return []
        lines = [self._rule("RECORD EVENTS")]
        for attribution in snapshot.recent_events[-10:]:
            colour = DIM if attribution.kind.value == "INFRASTRUCTURE" else FG_GREEN
            lines.append(
                f"  {attribution.event_id.ljust(24)}"
                f"{self._c(attribution.kind.value.ljust(18), colour)}"
                f"{self._c(attribution.label, DIM)}"
            )
            if self.options.detail:
                lines.append("  " + " " * 24 + self._c(f"basis: {attribution.basis}", DIM))
        return lines

    def ingest_section(self, snapshot: ObservatorySnapshot) -> list[str]:
        if not self.options.show_ingest:
            return []
        lines = [self._rule("RECORD INTEGRITY")]
        reader = snapshot.reader_state
        lines.append(self._kv("events ingested", str(reader.get("ingested", 0))))
        lines.append(self._kv("highest seq", str(reader.get("highest_seq", 0))))
        if reader.get("malformed_lines"):
            lines.append(
                self._kv("malformed lines", self._c(str(reader["malformed_lines"]), FG_RED))
            )
        if reader.get("out_of_order"):
            lines.append(
                self._kv("out-of-order events", self._c(str(reader["out_of_order"]), FG_YELLOW))
            )
        if reader.get("resets"):
            lines.append(self._kv("log resets", self._c(str(reader["resets"]), FG_YELLOW)))
        if snapshot.faults:
            for fault in snapshot.faults:
                lines.append("  " + self._c(f"fault: {fault}", FG_RED))
        return lines

    def footer(self) -> list[str]:
        return [
            self._rule(),
            "  " + self._c(
                "Observations are traceable to the canonical event log.", DIM
            ),
            "=" * self.options.width,
        ]

    # -- composition ------------------------------------------------------
    def render(self, snapshot: ObservatorySnapshot) -> str:
        sections: list[list[str]] = [self.header(snapshot)]
        sections.append(self.state_section(snapshot))
        sections.append(self.graph_section(snapshot))
        sections.append(self.events_section(snapshot))
        sections.append(self.ingest_section(snapshot))
        sections.append(self.footer())
        return "\n".join("\n".join(section) for section in sections if section)


def default_options(color: bool | None = None, detail: bool = False) -> RenderOptions:
    """Options honouring ``NO_COLOR`` and TTY detection."""
    if color is None:
        color = supports_colour(sys.stdout) and not os.environ.get("NO_COLOR")
    return RenderOptions(color=color, detail=detail)
