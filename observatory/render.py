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
            # Printed here too, not only in the no-subject branch. A subject can
            # be attached and still need a caveat — a key with no birth record is
            # attached, and the banner alone would imply a ceremony happened.
            if snapshot.subject_detail:
                lines.append("  " + self._c(snapshot.subject_detail, DIM))
        if snapshot.generated_at:
            lines.append(self._kv("observed at", snapshot.generated_at))
        return lines

    def birth_section(self, snapshot: ObservatorySnapshot) -> list[str]:
        """The laboratory's birth facts, above everything else.

        These are *infrastructure* facts: what was configured, what was
        installed, what the ceremony concluded. They are deliberately kept
        visually separate from the cognitive STATE section below, because a
        subject existing is not the same claim as a subject reporting something.
        A reader who conflates the two would conclude that having a model means
        having a mind, which is exactly the confusion this display exists to
        prevent.
        """
        birth = snapshot.birth
        if not birth:
            return []
        lines = [self._rule("BIRTH / FOUNDATION")]

        status = str(birth.get("model_status", "UNAVAILABLE"))
        colour = FG_GREEN if status == "READY" else FG_YELLOW
        if status == "READY":
            lines.append(self._kv("model status", self._c(status, colour)))
        else:
            # Spell out the non-ready reasons. A bare status code is easy to skim
            # past, and the difference between "not installed" and "we did not
            # check" is the whole point of reporting it at all.
            lines.append(
                self._kv("model status", self._c(f"{status}  (not usable)", colour))
            )
        if "model_usable" in birth:
            usable = bool(birth["model_usable"])
            lines.append(
                self._kv(
                    "model usable",
                    self._c("yes", FG_GREEN) if usable else self._c("no (unproven)", DIM),
                )
            )

        model = birth.get("model")
        if isinstance(model, dict):
            lines.append(self._kv("model", str(model.get("model_name", ""))))
            lines.append(self._kv("family", str(model.get("model_family", "") or "UNSPECIFIED")))
            revision = str(model.get("model_revision", "") or "")
            quant = str(model.get("quantization", "") or "")
            if revision or quant:
                lines.append(
                    self._kv("revision", " ".join(p for p in (revision, quant) if p))
                )
            lines.append(
                self._kv(
                    "sha256", self._c(str(model.get("model_sha256", "") or "UNAVAILABLE"), DIM)
                )
            )
            lines.append(
                self._kv(
                    "authorship", str(model.get("authorship_classification", "") or "UNSPECIFIED")
                )
            )
        elif birth.get("model_installed"):
            lines.append(self._kv("weights", self._c("present and matching", DIM)))
        else:
            lines.append(self._kv("weights", self._c("UNAVAILABLE", DIM)))

        if birth.get("subject_exists"):
            lines.append(self._kv("subject", str(birth.get("subject_id", ""))))
            lines.append(self._kv("born at", str(birth.get("born_at", ""))))
            lines.append(self._kv("birth id", str(birth.get("birth_id", ""))))
            if birth.get("birth_event_id"):
                lines.append(self._kv("birth event", str(birth["birth_event_id"])))
            if birth.get("birth_record_hash"):
                lines.append(
                    self._kv("record sha256", self._c(str(birth["birth_record_hash"]), DIM))
                )
        else:
            lines.append(
                self._kv("subject", self._c("none: no birth record exists", DIM))
            )

        lines.append(self._kv("environment", str(birth.get("environment_id", "") or "UNAVAILABLE")))
        lines.append(
            self._kv(
                "env attached",
                self._c("no", FG_YELLOW) if not birth.get("environment_connected") else "yes",
            )
        )
        workspace = str(birth.get("workspace_state", "") or "UNAVAILABLE")
        lines.append(self._kv("workspace", workspace))

        capabilities = birth.get("capability_statuses") or {}
        if capabilities:
            lines.append(self._kv("capabilities", "none implemented"))
            # One per line rather than a comma run: the full set is long, and a
            # wrapped blob of nine statuses invites nobody to read any of them.
            for name, state in sorted(capabilities.items()):
                lines.append("  " + " " * 18 + self._c(f"{name} = {state}", DIM))
        elif birth.get("capability_registry_hash"):
            lines.append(self._kv("capabilities", self._c("none implemented", DIM)))
        if self.options.detail and birth.get("capability_registry_hash"):
            lines.append(
                self._kv("registry sha256", self._c(str(birth["capability_registry_hash"]), DIM))
            )

        detail = str(birth.get("model_detail", "")).strip()
        if detail:
            lines.append("  " + self._c(f"model: {detail}", DIM))
        if birth.get("read_error"):
            lines.append("  " + self._c(f"birth read error: {birth['read_error']}", FG_RED))
        if self.options.detail and isinstance(model, dict):
            runtime = str(model.get("runtime", "") or "")
            runtime_version = str(model.get("runtime_version", "") or "")
            if runtime or runtime_version:
                lines.append(
                    self._kv("runtime", " ".join(p for p in (runtime, runtime_version) if p))
                )
        return lines

    def state_section(self, snapshot: ObservatorySnapshot) -> list[str]:
        lines = [self._rule("STATE")]
        if snapshot.subject_status == "NO_SUBJECT":
            lines.append("  " + self._c("No subject attached: no cognitive state to display.", DIM))
            lines.append("  " + self._c("This is the expected result for this milestone.", DIM))
            return lines
        if snapshot.subject_status == "RECORDED":
            lines.append(
                "  "
                + self._c(
                    "A subject exists but has no signing key, so it cannot be",
                    DIM,
                )
            )
            lines.append(
                "  " + self._c("the author of anything. No cognitive state is shown.", DIM)
            )
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

    def trust_boundary_section(self, snapshot: ObservatorySnapshot) -> list[str]:
        """Section 22: expose the actual trust state, never a stronger claim.

        ``snapshot.trust`` is a plain dict so that the renderer stays free of any
        dependency on the isolation or audit machinery; the Observatory is a
        view, and a view that measured the boundary itself would be a second
        source of truth. Whatever is passed in is displayed verbatim, and an
        absent key renders as UNAVAILABLE rather than as a default that reads
        like a measurement.

        Wording note: this section deliberately says "safety gate" rather than
        reusing the audit command's longer name. Milestone 003 bans a specific
        six-word vocabulary anywhere in this package, because a *psychological*
        score in that family would have to be invented in order to display it. A
        birth safety gate is the opposite kind of thing -- a measured deployment
        precondition -- so the two collided only lexically. The unambiguous
        wording is used here instead of relaxing the M003 guard. The audit
        command in the birth package keeps its own full name.
        """
        trust = snapshot.trust or {}
        if not trust:
            return []
        lines = [self._rule("TRUST BOUNDARY")]

        for title, key in (
            ("Human authority", "human_authority"),
            ("Laboratory authority", "laboratory_authority"),
            ("Baby AI authority", "baby_ai_authority"),
            ("Control access", "control_access"),
            ("Provenance access", "provenance_access"),
            ("Evidence access", "evidence_access"),
        ):
            value = trust.get(key)
            if value is None:
                lines.append(self._kv(title, self._c("UNAVAILABLE", DIM)))
            else:
                lines.append(self._kv(title, str(value)))

        os_isolation = trust.get("os_isolation")
        if os_isolation is None:
            lines.append(self._kv("OS isolation", self._c("UNAVAILABLE", DIM)))
        else:
            status = str(os_isolation)
            colour = FG_GREEN if status == "VERIFIED" else FG_YELLOW
            lines.append(self._kv("OS isolation", self._c(status, colour)))

        gate = trust.get("birth_safety_gate")
        if gate is None:
            lines.append(self._kv("Birth safety gate", self._c("UNAVAILABLE", DIM)))
        else:
            lines.append(self._kv("Birth safety gate", str(gate)))

        return lines

    def os_boundary_section(self, snapshot: ObservatorySnapshot) -> list[str]:
        """Milestone 005: the measured OS boundary, from observations only.

        Every value here must come from a real attempt. A missing key renders
        ``UNAVAILABLE`` -- never ``VERIFIED``, and never a value inferred from
        the existence of ACL code. Section 23 is explicit that the Observatory
        must never claim stronger isolation than the underlying tests establish.
        """
        boundary = snapshot.os_boundary or {}
        if not boundary:
            return []
        lines = [self._rule("OS BOUNDARY")]

        principal = boundary.get("execution_identity")
        lines.append(
            self._kv("execution identity", str(principal) if principal
                     else self._c("UNAVAILABLE", DIM))
        )
        integrity = boundary.get("integrity")
        lines.append(
            self._kv("integrity", str(integrity) if integrity
                     else self._c("UNAVAILABLE", DIM))
        )
        admin = boundary.get("administrator")
        if admin is None:
            lines.append(self._kv("administrator", self._c("UNAVAILABLE", DIM)))
        else:
            lines.append(self._kv("administrator", "NO" if admin is False else "YES"))

        state = boundary.get("os_isolation")
        if state is None:
            lines.append(self._kv("os isolation", self._c("UNAVAILABLE", DIM)))
        else:
            status = str(state)
            colour = FG_GREEN if status == "VERIFIED" else FG_YELLOW
            if status == "FAILED":
                colour = FG_RED
            lines.append(self._kv("os isolation", self._c(status, colour)))

        for title, key in (
            ("protected evidence", "protected_evidence"),
            ("control credentials", "control_credentials"),
            ("provenance keys", "provenance_keys"),
            ("experimental workspace", "experimental_workspace"),
        ):
            value = boundary.get(key)
            if value is None:
                lines.append(self._kv(title, self._c("UNAVAILABLE", DIM)))
            else:
                lines.append(self._kv(title, str(value)))

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
        sections.append(self.birth_section(snapshot))
        sections.append(self.state_section(snapshot))
        sections.append(self.graph_section(snapshot))
        sections.append(self.events_section(snapshot))
        sections.append(self.ingest_section(snapshot))
        sections.append(self.trust_boundary_section(snapshot))
        sections.append(self.os_boundary_section(snapshot))
        sections.append(self.footer())
        return "\n".join("\n".join(section) for section in sections if section)


def default_options(color: bool | None = None, detail: bool = False) -> RenderOptions:
    """Options honouring ``NO_COLOR`` and TTY detection."""
    if color is None:
        color = supports_colour(sys.stdout) and not os.environ.get("NO_COLOR")
    return RenderOptions(color=color, detail=detail)
