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
from pathlib import Path

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


def _wrap(text: str, width: int) -> list[str]:
    """Greedy word wrap. Used for reasons that must be readable in full.

    A refusal reason is the most useful thing this section can print, and
    truncating it would leave the reader unable to act on it. Width is floored
    so a narrow terminal cannot produce a zero-length loop.
    """
    usable = max(20, width)
    words = str(text).split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= usable:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


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

    def foundation_section(self, snapshot: ObservatorySnapshot) -> list[str]:
        """Milestone 010: the foundation-model runtime, as measurements.

        Placed directly beneath the birth section because the two are the same
        story told in order: this is the substrate, that is what the substrate
        would be attached to. Keeping them adjacent is what stops a reader from
        treating "the model works" as "the subject exists".

        Three rules govern this section.

        First, it displays only what was measured. Every absent value renders
        ``UNAVAILABLE``, and no field here can render a psychological
        characteristic, because there is no field for one. The M003 vocabulary
        ban applies to this section as strictly as to the cognitive panel: a
        trait with no measurement behind it must not be spelled here even to say
        that it is absent, because the word itself would be the only place the
        concept appeared.

        Second, it never rounds a claim up. A model whose bytes hash but has no
        external digest is shown as locally computed and *not* verified. A
        runtime that was asked to use the GPU but never confirmed it is shown as
        requested, not confirmed.

        Third, it says what a model running is not. The closing line is not
        decoration; it is the distinction the entire milestone turns on, placed
        where a reader who has just seen a verified model will encounter it.
        """
        foundation = snapshot.foundation or {}
        if not foundation:
            return []
        lines = [self._rule("FOUNDATION RUNTIME")]

        configured = foundation.get("model_configured")
        if configured is None:
            lines.append(self._kv("model configured", self._c("UNAVAILABLE", DIM)))
        else:
            lines.append(
                self._kv(
                    "model configured",
                    self._c("YES", FG_GREEN) if configured
                    else self._c("NO  (no model declaration)", FG_YELLOW),
                )
            )

        artifact = foundation.get("artifact") or {}
        status = str(artifact.get("status") or "UNAVAILABLE")
        # A locally computed digest with no external source is deliberately not
        # coloured as a success. It is a weaker claim and must look weaker.
        if status in {"VERIFIED_MATCH"}:
            colour = FG_GREEN
        elif status in {"COMPUTED_LOCAL_DIGEST", "NO_EXTERNAL_DIGEST_SUPPLIED"}:
            colour = FG_YELLOW
        elif status in {"EXTERNAL_DIGEST_MISMATCH", "UNSUPPORTED_FORMAT",
                        "ARTIFACT_MISSING", "ARTIFACT_TOO_SMALL"}:
            colour = FG_RED
        else:
            colour = DIM
        lines.append(self._kv("artifact", self._c(status, colour)))

        verified = artifact.get("verified")
        lines.append(
            self._kv(
                "artifact verified",
                self._c("YES (external digest matched)", FG_GREEN)
                if verified is True
                else self._c("NO", FG_YELLOW) if verified is False
                else self._c("UNAVAILABLE", DIM),
            )
        )

        external = artifact.get("external_sha256")
        basis = artifact.get("external_digest_source") or "none"
        lines.append(
            self._kv(
                "external digest",
                f"{(external[:16] + '...') if external else 'NOT SUPPLIED'}  ({basis})",
            )
        )
        computed = artifact.get("computed_sha256")
        lines.append(
            self._kv(
                "computed digest",
                (computed[:16] + "...") if computed else self._c("UNAVAILABLE", DIM),
            )
        )

        runtime = foundation.get("runtime") or {}
        rstate = str(runtime.get("state") or "UNAVAILABLE")
        rcolour = FG_GREEN if rstate == "VERIFIED" else (FG_RED if rstate in {
            "BINARY_MISSING", "PROBE_FAILED", "NOT_EXECUTABLE"} else DIM)
        lines.append(self._kv("runtime", self._c(rstate, rcolour)))
        lines.append(
            self._kv(
                "runtime version",
                str(runtime.get("version") or self._c("UNAVAILABLE", DIM)),
            )
        )

        gpu = str(runtime.get("gpu_usage") or "UNAVAILABLE")
        # CONFIRMED is the only state that may be shown as a success. A
        # requested-but-unconfirmed offload is shown as exactly that.
        gpu_colour = FG_GREEN if gpu == "CONFIRMED" else (
            FG_YELLOW if gpu in {"REQUESTED_NOT_CONFIRMED", "UNAVAILABLE"} else DIM)
        lines.append(self._kv("gpu usage", self._c(gpu, gpu_colour)))

        vram = foundation.get("vram") or {}
        if not vram:
            lines.append(self._kv("vram", self._c("UNAVAILABLE", DIM)))
        else:
            total = vram.get("total_bytes")
            free = vram.get("free_bytes")
            total_text = (
                f"{total / (1024 ** 3):.1f} GiB total" if isinstance(total, int)
                else self._c("UNAVAILABLE", DIM)
            )
            free_text = (
                f"  {free / (1024 ** 3):.1f} GiB free" if isinstance(free, int) else ""
            )
            lines.append(self._kv("vram", f"{total_text}{free_text}"))

        inference = foundation.get("inference") or {}
        if inference:
            outcome = str(inference.get("outcome") or "NOT_RUN")
            icolour = FG_GREEN if outcome == "COMPLETED" else FG_YELLOW
            lines.append(self._kv("inference", self._c(outcome, icolour)))
            prompt_d = inference.get("prompt_sha256")
            output_d = inference.get("output_sha256")
            lines.append(
                self._kv(
                    "prompt digest",
                    (prompt_d[:16] + "...") if prompt_d else self._c("UNAVAILABLE", DIM),
                )
            )
            lines.append(
                self._kv(
                    "output digest",
                    (output_d[:16] + "...") if output_d else self._c("UNAVAILABLE", DIM),
                )
            )
            accounting = inference.get("token_accounting") or {}
            if accounting:
                def _count(block: Any) -> str:
                    if not isinstance(block, dict) or not block.get("value"):
                        return "UNAVAILABLE"
                    return f"{block['value']} {block.get('status', '?').lower()}"

                lines.append(
                    self._kv(
                        "tokens (p/gen/total)",
                        f"{_count(accounting.get('prompt_tokens'))}"
                        f" / {_count(accounting.get('completion_tokens'))}"
                        f" / {_count(accounting.get('total_tokens'))}",
                    )
                )

        isolation = foundation.get("isolation") or {}
        if isolation:
            lines.append(
                self._kv(
                    "runtime boundary",
                    f"{isolation.get('enforced', 0)} enforced"
                    f" / {isolation.get('structural', 0)} structural"
                    f" / {len(isolation.get('not_established') or [])} not established",
                )
            )

        not_clause = foundation.get("explicitly_not") or {}
        if not_clause:
            lines.append(
                self._kv(
                    "this is not",
                    self._c("a subject, an experience, or learning", FG_YELLOW),
                )
            )
            if not_clause.get("birth"):
                lines.append(
                    self._kv(
                        "birth",
                        self._c("NOT_PERFORMED (a separate gated event)", FG_YELLOW),
                    )
                )

        return lines

    def runtime_verification_section(self, snapshot: ObservatorySnapshot) -> list[str]:
        """Milestone 011: real-runtime verification and execution identity.

        Sits inside the foundation area because it extends the same claim rather
        than starting a new one. M010 asked "is there a verified model and
        runtime"; M011 asks "did a real process actually run one, and which
        account was it".

        The section is built so that a partial verification cannot read as a
        complete one. ``REAL_RUNTIME`` is the only mode coloured as a success,
        ``STUB_RUNTIME`` and ``SIMULATED`` are amber because they exist and are
        not what acceptance requires, and ``NOT_TESTABLE`` is plain and
        unexplained-looking until its reason is printed underneath it -- which is
        exactly the point, since a bare code would invite the reader to assume a
        problem with the laboratory rather than with the host.
        """
        block = snapshot.runtime_verification or {}
        if not block:
            return []
        lines = [self._rule("RUNTIME VERIFICATION")]

        mode = str(block.get("inference_mode", "NOT_TESTABLE"))
        if mode == "REAL_RUNTIME":
            mode_colour = FG_GREEN
        elif mode in {"STUB_RUNTIME", "SIMULATED"}:
            mode_colour = FG_YELLOW
        else:
            mode_colour = DIM
        lines.append(self._kv("runtime mode", self._c(mode, mode_colour)))

        outcome = str(block.get("inference_outcome", "NOT_RUN"))
        outcome_colour = FG_GREEN if outcome == "COMPLETED" else FG_YELLOW
        lines.append(self._kv("inference", self._c(outcome, outcome_colour)))

        prompt_d = block.get("prompt_sha256")
        output_d = block.get("output_sha256")
        lines.append(
            self._kv("prompt digest",
                     (prompt_d[:16] + "...") if prompt_d else self._c("UNAVAILABLE", DIM))
        )
        lines.append(
            self._kv("output digest",
                     (output_d[:16] + "...") if output_d else self._c("UNAVAILABLE", DIM))
        )

        accounting = block.get("token_accounting") or {}
        if accounting:
            def _count(part: Any) -> str:
                if not isinstance(part, dict) or part.get("value") is None:
                    return "UNAVAILABLE"
                return f"{part['value']} {str(part.get('status', '?')).lower()}"

            lines.append(
                self._kv("tokens (p/gen/total)",
                         f"{_count(accounting.get('prompt_tokens'))}"
                         f" / {_count(accounting.get('completion_tokens'))}"
                         f" / {_count(accounting.get('total_tokens'))}")
            )

        verdict = block.get("determinism")
        if verdict:
            det_colour = FG_GREEN if verdict == "DETERMINISTIC_FOR_TEST_CONFIGURATION" else FG_YELLOW
            lines.append(self._kv("determinism", self._c(str(verdict), det_colour)))

        model_imm = block.get("model_immutable")
        runtime_imm = block.get("runtime_immutable")
        if model_imm is not None:
            lines.append(
                self._kv("model unchanged",
                         self._c("YES" if model_imm is True else
                                 ("NO" if model_imm is False else "UNAVAILABLE"),
                                 FG_GREEN if model_imm is True
                                 else (FG_RED if model_imm is False else DIM)))
            )
        if runtime_imm is not None:
            lines.append(
                self._kv("runtime unchanged",
                         self._c("YES" if runtime_imm is True else
                                 ("NO" if runtime_imm is False else "UNAVAILABLE"),
                                 FG_GREEN if runtime_imm is True
                                 else (FG_RED if runtime_imm is False else DIM)))
            )

        identity = block.get("process_identity") or {}
        if identity:
            account = identity.get("account", "UNAVAILABLE")
            domain = identity.get("domain", "")
            lines.append(
                self._kv("process identity",
                         f"{domain}\\{account}" if account != "UNAVAILABLE"
                         else self._c("UNAVAILABLE", DIM))
            )
            lines.append(
                self._kv("process sid",
                         str(identity.get("sid", "UNAVAILABLE")))
            )
            lines.append(
                self._kv("integrity", str(identity.get("integrity_level", "UNAVAILABLE")))
            )
            lines.append(
                self._kv("elevated", str(identity.get("is_elevated", "UNAVAILABLE")))
            )
        restricted = block.get("restricted_account_runtime")
        if restricted:
            colour = {
                "VERIFIED": FG_GREEN, "FAILED": FG_RED,
            }.get(str(restricted), FG_YELLOW)
            lines.append(
                self._kv("subject account", self._c(str(restricted), colour))
            )
            reason = str(block.get("restricted_account_reason", "")).strip()
            if reason:
                for chunk in _wrap(reason, self.options.width - 24):
                    lines.append("  " + self._c(chunk, DIM))

        probe = block.get("protected_probe")
        if probe:
            lines.append(
                self._kv("protected probe",
                         f"{probe.get('protected_denied', 0)} of "
                         f"{probe.get('protected_attempts', 0)} denied")
            )
            runner = probe.get("runner_account", "UNAVAILABLE")
            lines.append(
                self._kv("probe ran as", str(runner))
            )

        network = block.get("network")
        if network:
            lines.append(
                self._kv("network", self._c(str(network), FG_GREEN))
            )

        gpu = block.get("gpu_usage")
        if gpu:
            lines.append(self._kv("gpu", str(gpu)))

        lines.append(
            self._kv("subject", self._c("NONE - a runtime is not a subject", FG_YELLOW))
        )
        lines.append(
            self._kv("birth", self._c("NOT_PERFORMED", FG_YELLOW))
        )
        return lines

    def deployment_section(self, snapshot: ObservatorySnapshot) -> list[str]:
        """Milestone 012: the human's declared foundation selection.

        Placed first inside the foundation area, because it is the *decision*
        and everything below it is the verification of that decision. A reader
        who sees "runtime mode: REAL_RUNTIME" without having seen who chose the
        substrate would be reading the result of a choice they never saw made.

        Two states are deliberately distinguished and never merged:

        * ``NOT_DECLARED`` -- no human wrote a deployment declaration. The
          laboratory has no foundation, which is the correct state until told.
        * ``DECLARED`` -- a human named a model and a runtime, with a reason. The
          reason is displayed, because "which foundation, and why" is research
          provenance and not a footnote.

        A candidate count is shown with its "none selected" note, so the display
        makes visible that things exist on the machine which are *not* in use.
        That is the M012 discovery rule rendered honestly.
        """
        block = snapshot.deployment or {}
        if not block:
            return []
        lines = [self._rule("FOUNDATION SELECTION")]

        for label, key in (
            ("model selection", "human_model_selection"),
            ("runtime selection", "human_runtime_selection"),
        ):
            value = str(block.get(key, "UNAVAILABLE"))
            colour = FG_GREEN if value == "DECLARED" else FG_YELLOW
            lines.append(self._kv(label, self._c(value, colour)))

        model_path = str(block.get("model_path", "UNAVAILABLE"))
        if model_path != "UNAVAILABLE":
            lines.append(self._kv("model", self._c(Path(model_path).name, DIM)))
        digest = block.get("model_sha256")
        lines.append(
            self._kv("model sha256",
                     (str(digest)[:16] + "...") if digest and
                     digest != "UNAVAILABLE" else self._c("UNAVAILABLE", DIM))
        )

        external = str(block.get("model_external_digest") or "NOT SUPPLIED")
        source = str(block.get("model_external_source") or "none")
        if block.get("digest_verified"):
            colour = FG_GREEN
        elif block.get("digest_status") == "NO_EXTERNAL_DIGEST_SUPPLIED":
            colour = FG_YELLOW
        else:
            colour = DIM
        lines.append(
            self._kv("external digest", self._c(f"{external}  ({source})", colour))
        )

        runtime_path = str(block.get("runtime_path", "UNAVAILABLE"))
        if runtime_path != "UNAVAILABLE":
            lines.append(self._kv("runtime", self._c(Path(runtime_path).name, DIM)))
        lines.append(
            self._kv("runtime version",
                     str(block.get("runtime_version")
                         or block.get("runtime_expected_version")
                         or "UNAVAILABLE"))
        )

        if block.get("selection_attributed"):
            lines.append(
                self._kv("selected by", str(block.get("declared_by", "UNAVAILABLE")))
            )
        else:
            lines.append(
                self._kv("selected by",
                         self._c("UNATTRIBUTED - not a selection this project "
                                 "can attribute", FG_YELLOW))
            )

        disagreement = block.get("filename_disagreement")
        if disagreement:
            for chunk in _wrap(str(disagreement), self.options.width - 24):
                lines.append("  " + self._c(chunk, FG_YELLOW))

        candidates = block.get("candidates_reported") or {}
        if candidates:
            lines.append(self._kv("candidates found", self._c(
                f"{candidates.get('models', 0)} model, "
                f"{candidates.get('runtimes', 0)} runtime on this machine; "
                "none selected", DIM,
            )))

        lines.append(self._kv("real runtime", str(block.get("real_runtime", "NOT_TESTABLE"))))
        lines.append(
            self._kv("compatibility", str(block.get("compatibility", "UNKNOWN")))
        )
        return lines

    def birth_ceremony_section(self, snapshot: ObservatorySnapshot) -> list[str]:
        """Milestone 013: the birth gate, and the fact that no birth occurred.

        Placed after the foundation selection because it consumes it: the gate is
        the first thing in the system that asks "may a subject exist", and the
        answer is mostly a restatement of the sixteen prerequisites below.

        ``READY``, ``BLOCKED``, and ``FAILED`` are rendered in three different
        colours and never merged. The distinction is the whole point of the gate:
        BLOCKED means the laboratory has not established the prerequisites, and
        FAILED means it established that they are violated. A display that
        collapsed both into "not ready" would erase the difference between "we
        have not looked" and "we looked and it is wrong".

        The blocking prerequisites are counted rather than listed, because
        sixteen lines would bury the single line a reader needs: no subject
        exists, and this is correct.
        """
        block = snapshot.birth_ceremony or {}
        if not block:
            return []
        lines = [self._rule("BIRTH GATE")]

        state = str(block.get("state", "UNAVAILABLE"))
        colour = {
            "READY": FG_GREEN,
            "FAILED": FG_RED,
            "BLOCKED": FG_YELLOW,
        }.get(state, DIM)
        lines.append(self._kv("gate", self._c(state, colour)))

        prerequisites = block.get("prerequisites") or []
        if prerequisites:
            tally: dict[str, int] = {}
            for prerequisite in prerequisites:
                key = str(prerequisite.get("state", "UNAVAILABLE"))
                tally[key] = tally.get(key, 0) + 1
            summary = "  ".join(
                f"{count} {name}" for name, count in sorted(tally.items())
            )
            lines.append(self._kv("prerequisites", summary))

        lines.append(
            self._kv("real birth", self._c(
                str(block.get("real_birth", "NOT_PERFORMED")), FG_YELLOW))
        )
        lines.append(
            self._kv("subject", self._c(str(block.get("subject", "NONE")), FG_YELLOW))
        )
        lines.append(
            self._kv("T_birth", self._c(str(block.get("t_birth", "UNAVAILABLE")), DIM))
        )
        lines.append(
            self._kv("first experience", self._c(
                str(block.get("first_experience", "NOT_PERFORMED")), FG_YELLOW))
        )

        note = block.get("note")
        if note and self.options.detail:
            for row in _wrap(str(note), self.options.width - 4):
                lines.append("  " + self._c(row, DIM))
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
        sections.append(self.foundation_section(snapshot))
        sections.append(self.deployment_section(snapshot))
        sections.append(self.birth_ceremony_section(snapshot))
        sections.append(self.runtime_verification_section(snapshot))
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
