"""M067 -- Baby AI project status dashboard: data, progress rules, renderer.

READ-ONLY by construction. This module only reads repository state (ledger
verification reads, descriptor/content hashing, gate-state reads, file
existence checks) and renders a static HTML string. It contains no writer:
no ledger appends, no seals, no ACL/file mutation, no subprocess, no gate or
capability minting. A source-scan test pins that property.

PROGRESS-CALCULATION RULES (binding on every metric this module emits):
R1. Milestone status is categorical (COMPLETE / HOLD-ACTIVE / BLOCKED / OPEN /
    EVIDENCED). No milestone ever carries a percentage.
R2. Track progress is an exact integer fraction completed/total over an
    explicitly listed milestone set, shown as "n/m" with the set named. HOLD
    milestones count as complete because establishing the hold fulfilled their
    purpose; BLOCKED/OPEN do not count.
R3. A specification is never counted as implementation (M063/M065 are SPEC rows,
    excluded from every implementation numerator).
R4. A test is never counted as authorization; readiness is never counted as
    operation. Gates/authorizations live in panels independent of progress.
R5. NO blended overall percentage is asserted anywhere. Tile sizes in the map
    carry no weight; bars render exact labeled fractions only.
R6. Anything not freshly re-verified is marked EVIDENCED (status per its own
    evidence doc, not re-checked in M067) or UNKNOWN, with the evidence date shown.
"""

from __future__ import annotations

import html as _html

EVIDENCE_DATE = "2026-10-09"
GIT_HEAD = "6766c5b1b4e67d7dfbc21d6e87b75ce019a7c555"
LEDGER_HEAD = "PROV-000018"
LEDGER_ENTRIES = 18

# --------------------------------------------------------------------------
# Milestones: (id, title, status, basis, re_verified_in_m067)
# --------------------------------------------------------------------------
MILESTONES: tuple[tuple[str, str, str, str, bool], ...] = (
    ("M001", "Laboratory instrumentation", "EVIDENCED", "ledger MILESTONE-001 entries (5) + experiment log", False),
    ("M002", "Cognitive State Observatory", "EVIDENCED", "ledger MILESTONE-002 entries (4) + observatory code", False),
    ("M003", "Birth ceremony / model identity / truthful display", "EVIDENCED", "ledger MILESTONE-003 entries (3)", False),
    ("M004", "Trust boundary architecture", "EVIDENCED", "docs/m004-trust-boundary.md", False),
    ("M005", "OS isolation (Tier 2 verified by human probes)", "EVIDENCED", "m005-final-verification.json (2/11 probed; residuals noted)", False),
    ("M006", "Foundation-model and runtime layer", "EVIDENCED", "docs/evidence/m006 doc era", False),
    ("M007", "Environment and interaction substrate", "EVIDENCED", "docs/m007-environment.md", False),
    ("M008", "Subject architecture boundary", "EVIDENCED", "docs/m008-subject.md", False),
    ("M009", "Birth ceremony + controlled experience", "EVIDENCED", "birth/ceremony.py gate BLOCKED absent model", False),
    ("M010", "Foundation acquisition/verification", "EVIDENCED", "docs evidence era", False),
    ("M011", "Real runtime + subject-account execution", "EVIDENCED", "docs evidence era", False),
    ("M012", "Foundation deployment verification", "EVIDENCED", "m012-deployment-verification.json BLOCKED/NOT_CONFIGURED", False),
    ("M013", "Real birth ceremony / first experience", "EVIDENCED", "birth gate13/ceremony13 machinery, no birth", False),
    ("M014", "First real birth", "BLOCKED", "no model_deployment.json; M014 real result BLOCKED (verified absent 2026-10-09)", True),
    ("M015", "Subject-runtime staging boundary", "EVIDENCED", "staging design; nothing staged (verified 2026-10-09)", True),
    ("M016", "Subject-account runtime launch feasibility", "EVIDENCED", "BABY_AI_TEST verified; launch NOT_TESTABLE", False),
    ("M017", "Security objective decision", "EVIDENCED", "docs/evidence/m017 doc", False),
    ("M018", "Canonical state reconstruction", "EVIDENCED", "docs/evidence/m018 doc", False),
    ("M019", "Intended production boundary", "EVIDENCED", "docs/evidence/m019 doc", False),
    ("M020", "Security boundary verifier", "EVIDENCED", "docs/evidence/m020 doc", False),
    ("M021", "Boundary implementation design (T/MASK unselected)", "EVIDENCED", "docs/evidence/m021 doc", False),
    ("M022", "Repository state reconciliation", "EVIDENCED", "docs/evidence/m022 doc", False),
    ("M023", "Harness mutation-surface closure", "EVIDENCED", "docs/evidence/m023 doc", False),
    ("M024", "Complete mutation-surface closure", "EVIDENCED", "docs/evidence/m024 doc", False),
    ("M025", "Subject test-fixture resolution", "EVIDENCED", "docs/evidence/m025 doc", False),
    ("M026", "Disposable deployment readiness (INCOMPLETE: unmeasured)", "EVIDENCED", "docs/evidence/m026 doc", False),
    ("M027", "Interactive enforcement measurement (NOT_ATTEMPTED)", "EVIDENCED", "docs/evidence/m027 doc", False),
    ("M028", "Adjudicator + measurement readiness", "EVIDENCED", "docs/evidence/m028 doc", False),
    ("M029", "Human-gated measurement decision", "EVIDENCED", "docs/evidence/m029 doc", False),
    ("M030", "Interactive subject measurement", "EVIDENCED", "docs/evidence/m030 doc", False),
    ("M031", "Experimental hold / human-session handoff", "HOLD-ACTIVE", "hold doc; AUTOMATED_SUBJECT_LAUNCH NOT_AVAILABLE", False),
    ("M032", "Disposable session target reconciliation", "EVIDENCED", "docs/evidence/m032 doc", False),
    ("M033", "Baby-AI test session path investigation", "EVIDENCED", "docs/evidence/m033 doc", False),
    ("M034", "Cached subject-credential disposition", "EVIDENCED", "docs/evidence/m034 doc", False),
    ("M035", "Cached credential removal", "EVIDENCED", "docs/evidence/m035 doc", False),
    ("M036", "Cached credential deletion root cause", "EVIDENCED", "docs/evidence/m036 doc", False),
    ("M037", "Interactive session readiness", "EVIDENCED", "docs/evidence/m037 doc", False),
    ("M038", "First interactive launch analysis", "EVIDENCED", "docs/evidence/m038 doc", False),
    ("M039", "Instrument launcher contract remediation", "EVIDENCED", "docs/evidence/m039 doc", False),
    ("M040A", "Launch selection reconciliation", "EVIDENCED", "docs/evidence/m040a doc", False),
    ("M040B", "Launcher privilege capture", "EVIDENCED", "docs/evidence/m040b doc", False),
    ("M040C", "Two-launch-attempt reconciliation", "EVIDENCED", "docs/evidence/m040c doc", False),
    ("M041", "Handoff access-contract decision", "EVIDENCED", "docs/evidence/m041 doc", False),
    ("M042", "Trusted writer handoff design", "EVIDENCED", "docs/evidence/m042 doc", False),
    ("M043", "Live trusted-writer connection gate", "EVIDENCED", "docs/evidence/m043 doc", False),
    ("M044", "Live trusted-writer attempt", "EVIDENCED", "docs/evidence/m044 doc", False),
    ("M045", "Human live trusted-writer attempt", "EVIDENCED", "docs/evidence/m045 doc", False),
    ("M046", "Live experiment (+result)", "EVIDENCED", "docs/evidence/m046 docs", False),
    ("M047", "Live trusted-writer adjudication", "EVIDENCED", "docs/evidence/m047 doc", False),
    ("M048", "External token observation strategy", "EVIDENCED", "docs/evidence/m048 doc", False),
    ("M049", "Strategy-A authorization gate", "EVIDENCED", "docs/evidence/m049 doc", False),
    ("M050", "Live token observation gate (+result)", "EVIDENCED", "docs/evidence/m050 docs", False),
    ("M051", "Subject-side enforcement measurement design", "EVIDENCED", "docs/evidence/m051 doc", False),
    ("M052", "Live launcher freeze + read-only measurement gate", "EVIDENCED", "m052 freeze docs; auths spent", False),
    ("M052A", "Read-only instrument build + rehearsal", "EVIDENCED", "docs/evidence/m052a doc", False),
    ("M052B", "Live adjudication + production target mapping", "EVIDENCED", "docs/evidence/m052b docs", False),
    ("M052C", "M019 property adjudication", "EVIDENCED", "docs/evidence/m052c doc", False),
    ("M052D", "Canonical topology decision gate", "EVIDENCED", "docs/evidence/m052d doc", False),
    ("M052E", "D6 topology contract decision", "EVIDENCED", "docs/evidence/m052e doc", False),
    ("M052F", "M019 D6B amendment", "EVIDENCED", "docs/evidence/m052f doc", False),
    ("M052G", "Observation namespace implementation", "EVIDENCED", "docs/evidence/m052g doc", False),
    ("M052H", "T-BABY-1 preflight + live adjudication", "EVIDENCED", "docs/evidence/m052h docs", False),
    ("M052I", "Post-M052H governance reconciliation", "EVIDENCED", "docs/evidence/m052i doc", False),
    ("M052J", "D3 deny-mask decision (0x000D0156)", "EVIDENCED", "docs/evidence/m052j doc", False),
    ("M052K", "D3 implementation (frozen mechanism, gates closed)", "EVIDENCED", "m052k module; no production write path", False),
    ("M052L", "Interlock governance (Gate 2 mechanism, unopened)", "EVIDENCED", "m052l module; evaluate() never permits write", False),
    ("M052M", "Accidental production ACE incident (governance readiness)", "EVIDENCED", "incident docs; ACE removed by M057", False),
    ("M052N", "Incident exactness proof (disposable)", "EVIDENCED", "m052n module + tests", False),
    ("M052O", "Recovery authorisation architecture + disposable proof", "EVIDENCED", "m052o module; 21-case matrix", False),
    ("M052P", "Recovery governance gate (40-case matrix, decision NONE)", "EVIDENCED", "m052p module + matrix", False),
    ("M052Q–Y", "Recovery-governance decision iterations", "EVIDENCED", "docs/evidence/m052q–y docs", False),
    ("M052Z", "Director decision hold", "HOLD-ACTIVE", "hold module; launch/recovery/D3 BLOCKED", False),
    ("M053", "Governance hold finalization", "HOLD-ACTIVE", "hold module; holds active", False),
    ("M054", "R1 governance frozen (HUMAN seal PROV-000015)", "COMPLETE", "canonical digest 0b7148e0… verified live 2026-10-09; ledger+seal", True),
    ("M054B", "Provenance discrepancy adjudication (pre-existing)", "COMPLETE", "evidence doc; drift confirmed pre-M054", True),
    ("M055", "Recovery authorisation design (unsigned draft)", "COMPLETE", "session report; gaps documented, none repaired", True),
    ("M056", "Recovery authorisation issued (HUMAN seal PROV-000016)", "COMPLETE", "canonical 4d5c64e5… verified live 2026-10-09; ledger+seal", True),
    ("M057", "Recovery executed + verified (one exact ACE removal)", "COMPLETE", "poststate d63ff646… verified live 2026-10-09; PROV-000017", True),
    ("M058", "Post-recovery security review (module CLASS A)", "COMPLETE", "session report; read-only", True),
    ("M059", "Developmental readiness review", "COMPLETE", "session report; read-only", True),
    ("M060", "Reconciliation versioned (incident vs post-recovery)", "COMPLETE", "m060 module+tests; live PASS verified 2026-10-09", True),
    ("M061", "Experiment-log drift disposition (Option A accepted)", "COMPLETE", "session report + human disposition; file untouched", True),
    ("M062", "Gate-1 preparation package (D3-scoped finding)", "COMPLETE", "session report; no files changed", True),
    ("M063", "Developmental gate architecture (no implementation)", "COMPLETE", "session report; SPECIFICATION row, not implementation", True),
    ("M064", "Developmental boundary decided (Option C, sealed)", "COMPLETE", "canonical e2a3939e… verified live 2026-10-09; PROV-000018", True),
    ("M065", "Implementation-preparation contract (F1 BLOCKING found)", "COMPLETE", "session report; SPECIFICATION row", True),
    ("M066", "F1 staging/recovery remediation (verified)", "COMPLETE", "staging.py guards + 10/10 tests; production unchanged", True),
    ("M067", "Status dashboard (this milestone)", "COMPLETE", "report accepted; page+tests delivered", True),
    ("M068", "Graphical treemap dashboard", "OPEN", "in progress; completes on accepted report", True),
)

COMPLETE_LIKE = ("COMPLETE", "HOLD-ACTIVE", "EVIDENCED")

TRACKS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Recovery governance & execution",
     "M052J–M057 + M054B (decision iterations counted once as M052Q–Y)",
     ("M052J", "M052K", "M052L", "M052M", "M052N", "M052O", "M052P",
      "M052Q–Y", "M052Z", "M053", "M054", "M054B", "M055", "M056", "M057")),
    ("Post-recovery review & reconciliation",
     "M058–M061",
     ("M058", "M059", "M060", "M061")),
    ("Developmental governance & safety",
     "M062–M068",
     ("M062", "M063", "M064", "M065", "M066", "M067", "M068")),
    ("Laboratory foundation, instruments & holds",
     "M001–M052I (machinery, instruments, sessions, holds; statuses per own evidence)",
     ("M001", "M002", "M003", "M004", "M005", "M006", "M007", "M008", "M009",
      "M010", "M011", "M012", "M013", "M014", "M015", "M016", "M017", "M018",
      "M019", "M020", "M021", "M022", "M023", "M024", "M025", "M026", "M027",
      "M028", "M029", "M030", "M031", "M032", "M033", "M034", "M035", "M036",
      "M037", "M038", "M039", "M040A", "M040B", "M040C", "M041", "M042",
      "M043", "M044", "M045", "M046", "M047", "M048", "M049", "M050", "M051",
      "M052", "M052A", "M052B", "M052C", "M052D", "M052E", "M052F", "M052G",
      "M052H", "M052I")),
)

WORKSTREAMS: tuple[tuple[str, str, str, str], ...] = (
    ("Recovery governance & execution", "COMPLETE", "M057 poststate exact; incident closed with audit items",
     "2026-10-09"),
    ("Post-recovery reconciliation", "COMPLETE", "M060 dual-mode; live post-recovery PASS",
     "2026-10-09"),
    ("Provenance & seals", "HEALTHY (known drift)", "17 entries intact, head PROV-000018 sealed; exp-log drift accepted (Option A)",
     "2026-10-09"),
    ("Isolation & boundaries", "PARTIAL", "Tier 1/2 partial; Tier 3 absent; F1 fixed M066; FILE_DELETE_CHILD open",
     "2026-10-09"),
    ("Foundation / model / runtime", "PARTIAL", "machinery real; no artifacts selected, nothing staged",
     "2026-10-09"),
    ("Birth & lifecycle", "PARTIAL", "machinery complete; BLOCKED (no declaration); no birth",
     "2026-10-09"),
    ("Launch & sessions", "BLOCKED", "holds active; no auth; no session; NOT_TESTABLE unattended",
     "2026-10-09"),
    ("Observatory & telemetry", "PARTIAL", "read-only pipeline; bans enforced; no INTERPRETATION/HYPOTHESIS split",
     "2026-10-09"),
    ("Developmental governance", "COMPLETE", "M064 sealed; implementation deferred; F1 remediated",
     "2026-10-09"),
    ("Human control & security posture", "PARTIAL", "separation by design; HMAC/Tier-3/contract caveats carried",
     "2026-10-09"),
)

GATES: tuple[tuple[str, str, str], ...] = (
    ("D3 Gate 1 (production mutation)", "CLOSED", "no valid ProductionAuthorisation exists"),
    ("Gate 2 (production capability)", "CLOSED", "no GovernanceDecision; in-memory, fresh-process closed"),
    ("Birth gates (M009/M013)", "BLOCKED", "no declaration; MODEL_NOT_CONFIGURED"),
    ("Launch interlocks", "BLOCKED", "no selection; holds; no session"),
    ("Lifecycle", "UNCREATED", "no BIRTH.json"),
    ("A/B/C policy", "NONE", "no decision"),
    ("Network", "NO NETWORK (loopback pending final policy)", "D7 open"),
)

AUTHORIZATIONS: tuple[tuple[str, str, str], ...] = (
    ("M054 R1 governance", "FROZEN (PROV-000015)", "classification only; authorises no recovery"),
    ("M056 recovery auth 990c6e6f…", "SPENT (PROV-000016)", "consumed by M057; module self-neutralized"),
    ("M057 execution", "CONSUMED (PROV-000017)", "one verified ACE removal; poststate exact"),
    ("M064 boundary decision", "RECORDED (PROV-000018)", "architecture only; grants nothing"),
    ("M031/M052Z/M053 holds", "ACTIVE", "launch/recovery/D3 BLOCKED by design"),
    ("Launch authorization", "NONE", "prior auths spent; fresh verbatim words required"),
    ("Birth authorization", "NONE", "no declaration; M014 BLOCKED"),
    ("A/B/C decision", "NONE", "ordinary-mutation Gate-2 track untouched"),
)

DECISIONS_OPEN: tuple[tuple[str, str], ...] = (
    ("Tier 3 mandate vs accepted risk", "before launch"),
    ("Tier-2 credit vs fresh full-coverage proof", "before birth-execution/launch per human call"),
    ("FILE_DELETE_CHILD close vs accept", "before launch"),
    ("Staging immutability demonstration timing", "human call"),
    ("Final network policy", "before any launch"),
    ("Model + runtime selection", "separate human milestone"),
    ("Birth authorization", "after implementation + evidence"),
    ("Launch authorization", "after birth + fresh verbatim words"),
)

RISKS: tuple[tuple[str, str, str], ...] = (
    ("F1 staging defaults", "CLOSED (M066)", "guards + 10/10 tests; production unchanged"),
    ("Misconfigured launch as operator", "OPEN", "Tier 3 absent; privilege/session path undecided"),
    ("Reconcile 02/05/09 misread as failure", "MITIGATED", "M060 dual-mode + this dashboard's legend"),
    ("Single-operator HMAC provenance limits", "ACCEPTED (documented)", "ADR-003; third-party verification blocked"),
    ("Undiscovered writer outside scan patterns", "UNKNOWN (bounded)", "M062/M066 scans; novel primitives uncovered"),
)

NEXT_MILESTONE = ("M068", "Human review: accept M066 F1 remediation; scope D6/D7/model-runtime "
                          "decisions for birth-boundary implementation (recommendation only; no authorization)")


def track_fraction(track_ids: tuple[str, ...]) -> tuple[int, int]:
    """Completed-like milestones over the track set, per rules R1/R2."""
    by_id = {m[0]: m[1] for m in ((mid, status) for mid, _, status, _, _ in MILESTONES)}
    done = sum(1 for i in track_ids if by_id.get(i) in COMPLETE_LIKE)
    return done, len(track_ids)


def collect_live_state() -> dict[str, str]:
    """Read-only live verification of the headline facts. Reads only."""
    from babylab.hashing import file_sha256
    from babylab.paths import default_paths
    from provenance.keyring import Keyring
    from provenance.ledger import ProvenanceLedger
    from tests import m052l_interlock as L
    import os as _os
    paths = default_paths()
    keyring = Keyring(paths.keyring, paths.private_key_dir)
    ledger = ProvenanceLedger(
        paths.provenance_ledger, keyring, seal_dir=paths.protected_provenance)
    report = ledger.verify(deep=True)
    seal = ledger.verify_seal()
    head = ledger.head()
    from tests import m052p_governance as P
    from tests import m052o_recovery as O
    from tests import path_policy as pp
    import hashlib as _hl
    _t = pp.read_production_for_verification(P.AFFECTED)
    _st = O.incident_state(_t)
    return {
        "evidence_date": EVIDENCE_DATE,
        "git_head": GIT_HEAD,
        "ledger_entries": str(report.valid_entries),
        "ledger_head": head.entry_id if head else "NONE",
        "chain_intact": str(report.intact),
        "seal_intact": str(seal.intact if seal else False),
        "gate_1": L.evaluate(None)["gate_1"]["state"],
        "gate_2_open": str(L.interlock_state()["gate_2_open"]),
        "explog_drift": file_sha256(paths.root / "research" / "experiment-log.md")[:16],
        "m064_sha": file_sha256(
            paths.root / "docs" / "evidence" / "m064-developmental-boundary-decision.json")[:16],
        "runtime_selection": str(_os.path.exists(
            paths.root / "human_control" / "experiment_config" / "runtime_selection.json")),
        "model_deployment": str(_os.path.exists(
            paths.root / "human_control" / "experiment_config" / "model_deployment.json")),
        "birth_record": str(_os.path.exists(
            paths.root / "human_control" / "birth_records" / "BIRTH.json")),
        "production_descriptor": O._descriptor_hash(_st),
        "production_content": _hl.sha256(_t.read_bytes()).hexdigest(),
    }


_CSS = """
body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:2em;max-width:1100px;color:#1a1a1a}
h1{font-size:1.6em} h2{margin-top:2em;border-bottom:2px solid #333;padding-bottom:.2em}
table{border-collapse:collapse;width:100%;font-size:.85em;margin:.5em 0}
th,td{border:1px solid #bbb;padding:.35em .5em;text-align:left;vertical-align:top}
th{background:#eee}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:.6em;margin:.5em 0}
.tile{border:2px solid #666;border-radius:6px;padding:.6em}
.st-COMPLETE,.st-HEALTHY,.st-CLOSED,.st-FROZEN,.st-PASS{background:#dff0d8;border-color:#3c763d}
.st-PARTIAL,.st-HOLD-ACTIVE,.st-BLOCKED,.st-MITIGATED{background:#fcf8e3;border-color:#8a6d3b}
.st-MISSING,.st-OPEN,.st-NONE,.st-FAIL{background:#f2dede;border-color:#a94442}
.st-EVIDENCED,.st-UNKNOWN,.st-SPECIFICATION{background:#e8e8e8;border-color:#666}
.bar{background:#ddd;height:1em;border-radius:3px}.bar>i{display:block;background:#3c763d;height:1em;border-radius:3px}
.small{font-size:.8em;color:#555}.legend{font-size:.85em}
code{font-size:.85em}
"""


def _esc(text: object) -> str:
    return _html.escape(str(text), quote=True)


def _md_esc(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


_STATUS_DOT = {
    "COMPLETE": "\U0001F7E9", "HEALTHY": "\U0001F7E9", "CLOSED": "\U0001F7E9",
    "FROZEN": "\U0001F7E9", "PASS": "\U0001F7E9",
    "PARTIAL": "\U0001F7E8", "HOLD-ACTIVE": "\U0001F7E8", "BLOCKED": "\U0001F7E8",
    "MITIGATED": "\U0001F7E8",
    "MISSING": "\U0001F7E5", "OPEN": "\U0001F7E5", "NONE": "\U0001F7E5",
    "FAIL": "\U0001F7E5",
}


def _dot(status: str) -> str:
    return _STATUS_DOT.get(status.split(" ")[0].upper(), "\u2B1C")


def render_markdown(live: dict[str, str] | None = None) -> str:
    """Render the dashboard as GitHub-flavored Markdown. Pure; no I/O, no mutation.

    Same data and rules as render_html (fractions only, no blended percent,
    gates/authorizations independent of progress). Tile map becomes a status-dot
    table since Markdown has no colored tiles.
    """
    live = live or {}
    out: list[str] = []
    out.append("# Baby AI Project Status Dashboard")
    out.append("")
    out.append(f"Evidence date: **{EVIDENCE_DATE}** · GIT_HEAD: `{GIT_HEAD}` · "
               f"Ledger: **{LEDGER_ENTRIES} entries, head {LEDGER_HEAD}, sealed**.")
    out.append("")
    out.append("> Read-only status artifact: this page asserts nothing, authorizes "
               "nothing, and changes nothing. Full-color local version: "
               "`docs/m067-status-dashboard.html` (open in a browser).")
    out.append("")
    if live:
        out.append("## Live-verified headline state")
        out.append("")
        out.append("| Fact | Live value |")
        out.append("| --- | --- |")
        for key in ("ledger_entries", "ledger_head", "chain_intact", "seal_intact",
                    "gate_1", "gate_2_open", "explog_drift", "m064_sha",
                    "runtime_selection", "model_deployment", "birth_record",
                    "production_descriptor", "production_content"):
            out.append(f"| `{key}` | `{live.get(key, '?')}` |")
        out.append("")
    out.append("## Progress by track (exact fractions; no blended percent asserted)")
    out.append("")
    out.append("Rules: categorical milestones only; HOLD counts as complete (hold "
               "fulfilled its purpose); specifications excluded from implementation "
               "counts; tests never count as authorization; readiness never counts "
               "as operation.")
    out.append("")
    out.append("| Track | Scope | Progress |")
    out.append("| --- | --- | --- |")
    for name, scope, ids in TRACKS:
        done, total = track_fraction(ids)
        filled = int(round(10 * done / total)) if total else 0
        bar = "\u2588" * filled + "\u2591" * (10 - filled)
        out.append(f"| {_md_esc(name)} | {_md_esc(scope)} | `{bar}` {done}/{total} |")
    out.append("")
    out.append("## Workstream map (dot color only; no weighting)")
    out.append("")
    out.append("| Workstream | Status | Note | As of |")
    out.append("| --- | --- | --- | --- |")
    for name, status, note, date in WORKSTREAMS:
        out.append(f"| {_md_esc(name)} | {_dot(status)} {status} "
                   f"| {_md_esc(note)} | {date} |")
    out.append("")
    out.append("Legend: 🟩 complete/healthy/closed/frozen/pass; "
               "🟨 partial/hold-active/blocked/mitigated (attention, not failure); "
               "🟥 missing/open/fail; ⬜ evidenced-not-reverified / unknown / specification. "
               "FAIL on incident-state checks after recovery means 'incident absent', not failure.")
    out.append("")
    out.append("## Gates (independent of progress)")
    out.append("")
    out.append("| Gate | State | Basis |")
    out.append("| --- | --- | --- |")
    for name, state, basis in GATES:
        out.append(f"| {_md_esc(name)} | {_dot(state)} {state} | {_md_esc(basis)} |")
    out.append("")
    out.append("## Authorizations (independent of tests)")
    out.append("")
    out.append("| Authorization | State | Note |")
    out.append("| --- | --- | --- |")
    for name, state, note in AUTHORIZATIONS:
        out.append(f"| {_md_esc(name)} | {_md_esc(state)} | {_md_esc(note)} |")
    out.append("")
    out.append("## Milestones M001–M067")
    out.append("")
    out.append("| ID | Title | Status | Basis | Re-verified M067 |")
    out.append("| --- | --- | --- | --- | --- |")
    for mid, title, status, basis, rever in MILESTONES:
        out.append(f"| {_md_esc(mid)} | {_md_esc(title)} | {_dot(status)} {status} "
                   f"| {_md_esc(basis)} | {'YES' if rever else 'basis only'} |")
    out.append("")
    out.append("## Open human decisions")
    out.append("")
    out.append("| Decision | Needed before |")
    out.append("| --- | --- |")
    for name, timing in DECISIONS_OPEN:
        out.append(f"| {_md_esc(name)} | {_md_esc(timing)} |")
    out.append("")
    out.append("## Risks")
    out.append("")
    out.append("| Risk | State | Note |")
    out.append("| --- | --- | --- |")
    for name, state, note in RISKS:
        out.append(f"| {_md_esc(name)} | {_md_esc(state)} | {_md_esc(note)} |")
    out.append("")
    out.append("## Next recommended milestone")
    out.append("")
    out.append(f"**{NEXT_MILESTONE[0]}** — {NEXT_MILESTONE[1]}")
    out.append("")
    out.append("## Methods & limitations")
    out.append("")
    out.append("Headline facts re-verified live via ledger verify + seal check, gate reads, "
               "file hashing, and existence checks on 2026-10-09. Earlier milestones marked "
               "EVIDENCED carry their own evidence docs' claims, not fresh M067 verification. "
               "No blended completion percentage is asserted; the prior informal forty-percent "
               "figure is not used.")
    out.append("")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# M068 -- graphical treemap. Same canonical data; genuine squarified layout.
# --------------------------------------------------------------------------
#
# SIZING RULE (binding): every milestone tile has weight 1, i.e. tile area is
# proportional to exactly one defined milestone unit. Track area is therefore
# proportional to milestone count. No other weights exist; tile size means
# "how many defined milestones", nothing about importance or effort.
#
# COLOR RULE (binding): COMPLETE->green, except kind SPEC->blue (specification
# delivered, implementation not performed); HOLD-ACTIVE/BLOCKED/OPEN->amber
# (attention: active stop, awaiting input, or in progress -- never failure);
# EVIDENCED->gray (documented basis, not freshly verified); red is reserved for
# a confirmed blocking defect/failed criterion (none present; legend says so).

KIND: dict[str, str] = {}
for _mid, _kind in (
    ("M054", "IMPL"), ("M056", "IMPL"), ("M057", "IMPL"), ("M060", "IMPL"),
    ("M064", "IMPL"), ("M066", "IMPL"), ("M067", "IMPL"), ("M068", "IMPL"),
    ("M063", "SPEC"), ("M065", "SPEC"),
    ("M031", "HOLD"), ("M052Z", "HOLD"), ("M053", "HOLD"),
    ("M054B", "REVIEW"), ("M055", "REVIEW"), ("M058", "REVIEW"),
    ("M059", "REVIEW"), ("M061", "REVIEW"), ("M062", "REVIEW"),
):
    KIND[_mid] = _kind


def _kind_of(mid: str) -> str:
    return KIND.get(mid, "EVIDENCE")


REMAINING: dict[str, str] = {
    "M014": "Human model/runtime declaration required; birth BLOCKED until then.",
    "M031": "Hold active: awaits human interactive session + decisions.",
    "M052Z": "Hold active: awaits director decision.",
    "M053": "Hold active: awaits human recovery-governance decision.",
    "M067": "None (report accepted).",
    "M068": "Acceptance of this graphical dashboard.",
}
_REMAINING_DEFAULT_CLOSED = "None (closed per its success criteria)."
_REMAINING_DEFAULT_OPEN = ("No outstanding work recorded in the M067 basis; "
                           "underlying claims not re-verified.")


def _remaining_of(mid: str, status: str) -> str:
    if mid in REMAINING:
        return REMAINING[mid]
    return (_REMAINING_DEFAULT_CLOSED if status in ("COMPLETE", "HOLD-ACTIVE")
            else _REMAINING_DEFAULT_OPEN)


COLORS = {
    "green": "#2e7d32",
    "amber": "#b7791f",
    "gray": "#616161",
    "red": "#c62828",
    "blue": "#1565c0",
}


def tile_color(status: str, kind: str) -> str:
    """Status color per the binding rule above. Never green for stale/unknown."""
    if kind == "SPEC":
        return "blue"
    if status == "COMPLETE":
        return "green"
    if status in ("HOLD-ACTIVE", "BLOCKED", "OPEN"):
        return "amber"
    return "gray"


def _squarify(items: list[tuple[str, float]],
              x: float, y: float, w: float, h: float) -> dict[str, tuple[float, float, float, float]]:
    """Squarified treemap layout. Deterministic: sorts by (-weight, key).

    Returns {key: (x, y, w, h)} in the same coordinate space. Rectangles are
    non-overlapping, contained in [x,x+w]x[y,y+h], and areas are proportional
    to weights (up to floating-point rounding).
    """
    ordered = sorted(items, key=lambda kv: (-kv[1], kv[0]))
    total = sum(weight for _, weight in ordered)
    if total <= 0 or w <= 0 or h <= 0 or not ordered:
        return {}
    scale = (w * h) / total
    rects: dict[str, tuple[float, float, float, float]] = {}
    remaining = list(ordered)
    cx, cy, cw, ch = x, y, w, h
    while remaining:
        row: list[tuple[str, float]] = []
        row_sum = 0.0
        best = float("inf")
        while remaining:
            candidate = remaining[0]
            trial = row_sum + candidate[1]
            worst = _worst(row + [candidate], trial, cw, ch, scale)
            if worst <= best:
                best = worst
                row.append(candidate)
                row_sum = trial
                remaining.pop(0)
            else:
                break
        if not row:
            row.append(remaining.pop(0))
            row_sum = row[0][1]
        _layout_row(row, row_sum, scale, rects, cx, cy, cw, ch)
        used = (row_sum * scale) / (ch if cw >= ch else cw)
        if cw >= ch:
            cx += used
            cw -= used
        else:
            cy += used
            ch -= used
    return rects


def _worst(row: list[tuple[str, float]], row_sum: float,
           cw: float, ch: float, scale: float) -> float:
    side = min(cw, ch)
    if side <= 0 or row_sum <= 0:
        return float("inf")
    areas = [weight * scale for _, weight in row]
    worst = 0.0
    for area in areas:
        ratio = (side * side * max(area, 1e-12)) / ((row_sum * scale) ** 2)
        worst = max(worst, ratio, 1 / ratio if ratio else float("inf"))
    return worst


def _layout_row(row: list[tuple[str, float]], row_sum: float, scale: float,
                rects: dict[str, tuple[float, float, float, float]],
                cx: float, cy: float, cw: float, ch: float) -> None:
    if row_sum <= 0:
        return
    offset = 0.0
    if cw >= ch:
        thickness = (row_sum * scale) / ch if ch > 0 else 0.0
        for key, weight in row:
            length = (weight * scale) / thickness if thickness > 0 else 0.0
            rects[key] = (cx, cy + offset, thickness, length)
            offset += length
    else:
        thickness = (row_sum * scale) / cw if cw > 0 else 0.0
        for key, weight in row:
            length = (weight * scale) / thickness if thickness > 0 else 0.0
            rects[key] = (cx + offset, cy, length, thickness)
            offset += length


def build_treemap(width: float = 1000.0, height: float = 620.0) -> dict[str, Any]:
    """Two-level treemap: tracks, then one unit-weight tile per milestone.

    Returns track rects, tile rects keyed by milestone id, and tile metadata
    (label, status, kind, color, basis, evidence date, remaining work).
    """
    by_id = {mid: (title, status, basis, rever)
             for mid, title, status, basis, rever in MILESTONES}
    track_items = [(_track_key(name), float(len(ids))) for name, _, ids in TRACKS]
    track_rects = _squarify(track_items, 0.0, 0.0, width, height)
    tiles: dict[str, dict[str, Any]] = {}
    tile_rects: dict[str, tuple[float, float, float, float]] = {}
    for (name, _scope, ids), tkey in zip(
            [t for t in TRACKS], [_track_key(n) for n, _, _ in TRACKS]):
        rect = track_rects.get(tkey)
        if rect is None:
            continue
        tx, ty, tw, th = rect
        pad = 0.0
        inner = _squarify([(mid, 1.0) for mid in ids],
                           tx + pad, ty + pad, max(tw - 2 * pad, 1.0),
                           max(th - 2 * pad, 1.0))
        for mid, r in inner.items():
            title, status, basis, rever = by_id[mid]
            kind = _kind_of(mid)
            tiles[mid] = {
                "track": name, "rect": r, "title": title, "status": status,
                "kind": kind, "color": tile_color(status, kind), "basis": basis,
                "evidence": ("live " + EVIDENCE_DATE if rever
                             else "basis only; not re-verified"),
                "remaining": _remaining_of(mid, status),
            }
            tile_rects[mid] = r
    tracks = [{"name": name, "scope": scope, "ids": list(ids),
               "rect": track_rects.get(_track_key(name))}
              for name, scope, ids in TRACKS]
    return {"width": width, "height": height, "tracks": tracks, "tiles": tiles}


def _track_key(name: str) -> str:
    return "track:" + name


_GRAPH_CSS = """
body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0;background:#141414;color:#f0f0f0}
header{padding:1em 1.5em;background:#0a0a0a;border-bottom:1px solid #333}
h1{font-size:1.4em;margin:.2em 0}
.strip{display:flex;flex-wrap:wrap;gap:.5em;padding:.8em 1.5em;background:#1d1d1d}
.strip div{background:#222;border:1px solid #444;border-radius:4px;padding:.3em .6em;font-size:.85em}
#map{position:relative;width:96%;max-width:1000px;aspect-ratio:1000/620;margin:1em auto;background:#0a0a0a;border:1px solid #333}
.track{position:absolute;border:2px solid #555;box-sizing:border-box}
.track>span{position:absolute;top:2px;left:4px;font-size:11px;color:#bbb;z-index:1}
.tile{position:absolute;box-sizing:border-box;border:1px solid #0a0a0a;overflow:hidden;
font-size:11px;line-height:1.2;padding:2px;cursor:pointer;color:#fff;text-shadow:0 1px 2px #000}
.tile:focus{outline:2px solid #fff;outline-offset:-2px}
.tile.hidden{display:none}
#detail{max-width:1000px;margin:1em auto;padding:1em;background:#1d1d1d;border:1px solid #444;min-height:6em}
#detail h3{margin:.2em 0}
.filters{padding:.5em 1.5em}
.filters button{margin:.2em;padding:.3em .7em;cursor:pointer}
.legend{padding:.5em 1.5em;font-size:.85em;color:#ccc}
.access{max-width:1000px;margin:1em auto;padding:0 1.5em}
table{border-collapse:collapse;width:100%;font-size:.8em}
th,td{border:1px solid #555;padding:.3em .5em;text-align:left}
th{background:#222}
"""


_GRAPH_JS = """
const detail=document.getElementById('detailbody');
function show(el){detail.innerHTML='<h3>'+el.dataset.mid+' — '+el.dataset.title+'</h3>'
+'<p><b>Status:</b> '+el.dataset.status+' ('+el.dataset.kind+') · '
+'<b>Track:</b> '+el.dataset.track+'</p>'
+'<p><b>Basis:</b> '+el.dataset.basis+'</p>'
+'<p><b>Evidence:</b> '+el.dataset.evidence+'</p>'
+'<p><b>Remaining work:</b> '+el.dataset.remaining+'</p>';}
document.querySelectorAll('.tile').forEach(function(el){
el.addEventListener('click',function(){show(el);});
el.addEventListener('keydown',function(ev){if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();show(el);}});});
function filterStatus(s){document.querySelectorAll('.tile').forEach(function(el){
el.classList.toggle('hidden',s!=='all'&&el.dataset.color!==s);});}
"""


def render_graphical_html(live: dict[str, str] | None = None) -> str:
    """Full graphical treemap page. Static + inline vanilla JS/CSS only.

    No external scripts, stylesheets, images, fonts, or network requests.
    Gates/authorizations render in a panel separate from the treemap so gate
    state is never confused with progress. Snapshot date is displayed; nothing
    here implies live updating.
    """
    live = live or {}
    tree = build_treemap()
    width, height = tree["width"], tree["height"]
    parts = ["<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
             "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
             "<title>Baby AI — Project Progress (M068 treemap)</title>"
             f"<style>{_GRAPH_CSS}</style></head><body>"]
    parts.append("<header><h1>Baby AI — Project Progress</h1>"
                 f"<p>Snapshot/evidence date: <b>{EVIDENCE_DATE}</b> · "
                 f"Ledger: <b>{LEDGER_ENTRIES} entries, head {LEDGER_HEAD}</b> · "
                 "Point-in-time render from canonical dashboard data; not live-updating. "
                 "This page asserts nothing, authorizes nothing, changes nothing.</p></header>")
    parts.append("<div class=\"strip\" aria-label=\"Workstream summary\">")
    for name, _scope, ids in TRACKS:
        done, total = track_fraction(ids)
        parts.append(f"<div><b>{_html.escape(name)}</b> — {done}/{total} milestones</div>")
    parts.append("</div>")
    parts.append("<div class=\"filters\" role=\"toolbar\" aria-label=\"Filter by status\">"
                 "Filter: <button onclick=\"filterStatus('all')\">all</button> "
                 "<button onclick=\"filterStatus('green')\">verified complete</button> "
                 "<button onclick=\"filterStatus('amber')\">attention</button> "
                 "<button onclick=\"filterStatus('gray')\">basis only</button> "
                 "<button onclick=\"filterStatus('blue')\">specification</button></div>")
    parts.append(f"<div id=\"map\" role=\"group\" aria-label=\"Milestone treemap\">")
    for track in tree["tracks"]:
        rect = track["rect"]
        if rect is None:
            continue
        x, y, w, h = (100 * v / (width if i % 2 == 0 else height)
                       for i, v in enumerate(rect))
        parts.append(
            f"<div class=\"track\" style=\"left:{x:.2f}%;top:{y:.2f}%;"
            f"width:{w:.2f}%;height:{h:.2f}%;\">"
            f"<span>{_html.escape(track['name'])}</span>")
        for mid in track["ids"]:
            tile = tree["tiles"].get(mid)
            if tile is None:
                continue
            tx, ty, tw, th = tile["rect"]
            lx, ly, lw, lh = (100 * tx / width, 100 * ty / height,
                              100 * tw / width, 100 * th / height)
            color = COLORS[tile["color"]]
            label = mid if lw > 4.5 and lh > 6 else ""
            parts.append(
                f"<div class=\"tile\" tabindex=\"0\" role=\"button\" "
                f"aria-label=\"{_html.escape(mid)}: {_html.escape(tile['title'])} "
                f"({_html.escape(tile['status'])})\" "
                f"style=\"left:{lx:.2f}%;top:{ly:.2f}%;width:{lw:.2f}%;height:{lh:.2f}%;"
                f"background:{color};\" "
                f"data-mid=\"{_html.escape(mid)}\" "
                f"data-title=\"{_html.escape(tile['title'])}\" "
                f"data-status=\"{_html.escape(tile['status'])}\" "
                f"data-kind=\"{_html.escape(tile['kind'])}\" "
                f"data-color=\"{_html.escape(tile['color'])}\" "
                f"data-track=\"{_html.escape(tile['track'])}\" "
                f"data-basis=\"{_html.escape(tile['basis'])}\" "
                f"data-evidence=\"{_html.escape(tile['evidence'])}\" "
                f"data-remaining=\"{_html.escape(tile['remaining'])}\">"
                f"{_html.escape(label)}</div>")
        parts.append("</div>")
    parts.append("</div>")
    parts.append("<div id=\"detail\" aria-live=\"polite\"><h3>Tile detail</h3>"
                 "<div id=\"detailbody\">Click or Tab to a tile and press Enter "
                 "for its tasks, evidence, and remaining work. Small tiles without "
                 "visible labels are listed in full below.</div></div>")
    parts.append("<div class=\"legend\">Legend — tile area = exactly one defined "
                 "milestone unit (all tiles equal area; track area = milestone count; "
                 "size means count, not importance). "
                 "Colors: <b style=\"color:#7fd67f\">green</b>=verified complete · "
                 "<b style=\"color:#e0a83c\">amber</b>=attention (hold / awaiting input / "
                 "in progress — never failure) · "
                 "<b style=\"color:#bdbdbd\">gray</b>=documented basis only, not freshly "
                 "verified · <b style=\"color:#7fa8e0\">blue</b>=specification delivered, "
                 "implementation not performed · red=confirmed blocking defect "
                 "(none present). A specification is not implementation; a test is not "
                 "authorization; readiness is not operation.</div>")
    parts.append("<div class=\"access\"><h2>Gates &amp; authorizations (separate from progress)</h2>"
                 "<table><tr><th>Gate / authorization</th><th>State</th></tr>")
    for name, state, _basis in GATES:
        parts.append(f"<tr><td>{_html.escape(name)}</td><td>{_html.escape(state)}</td></tr>")
    for name, state, _note in AUTHORIZATIONS:
        parts.append(f"<tr><td>{_html.escape(name)}</td><td>{_html.escape(state)}</td></tr>")
    parts.append("</table>")
    parts.append("<h2>Accessible tile list (every tile, regardless of label space)</h2>"
                 "<details><summary>Show all milestone tiles</summary>"
                 "<table><tr><th>ID</th><th>Title</th><th>Status</th><th>Kind</th>"
                 "<th>Evidence</th><th>Remaining work</th></tr>")
    for mid, _t, _s, _b, _r in MILESTONES:
        tile = tree["tiles"].get(mid)
        if tile is None:
            continue
        parts.append(f"<tr><td>{_html.escape(mid)}</td><td>{_html.escape(tile['title'])}</td>"
                     f"<td>{_html.escape(tile['status'])}</td>"
                     f"<td>{_html.escape(tile['kind'])}</td>"
                     f"<td>{_html.escape(tile['evidence'])}</td>"
                     f"<td>{_html.escape(tile['remaining'])}</td></tr>")
    parts.append("</table></details></div>")
    parts.append(f"<script>{_GRAPH_JS}</script></body></html>")
    return "\n".join(parts)


def render_preview_svg() -> str:
    """Compact static workstream preview for README embedding.

    Generated deterministically from WORKSTREAMS (same canonical data).
    Grayscale-friendly status dots + labels; ~600px wide. Labeled preview,
    not a live view: caption carries the evidence date.
    """
    width, height = 620.0, 260.0
    items = [(name, 1.0) for name, _, _, _ in WORKSTREAMS]
    rects = _squarify(items, 0.0, 24.0, width, height - 24.0)
    dots = {"COMPLETE": "#2e7d32", "HEALTHY": "#2e7d32", "PARTIAL": "#b7791f",
            "BLOCKED": "#b7791f", "EVIDENCED": "#616161"}
    svg = [f"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{int(width)}\" "
           f"height=\"{int(height)}\" role=\"img\" "
           f"aria-label=\"Workstream status preview, evidence {EVIDENCE_DATE}\">",
           f"<text x=\"4\" y=\"16\" font-size=\"14\" font-family=\"sans-serif\" "
           f"fill=\"#111\">Baby AI workstreams ({EVIDENCE_DATE})</text>"]
    for (name, status, _note, _date), rect in zip(WORKSTREAMS, [rects[k] for k, _ in items]):
        x, y, w, h = rect
        color = dots.get(status.split(" ")[0], "#616161")
        short = name if len(name) < 22 else name[:21] + "…"
        svg.append(f"<rect x=\"{x:.1f}\" y=\"{y:.1f}\" width=\"{w:.1f}\" height=\"{h:.1f}\" "
                   f"fill=\"{color}\" stroke=\"#fff\" stroke-width=\"1.5\"/>")
        if w > 90 and h > 28:
            svg.append(f"<text x=\"{x + 4:.1f}\" y=\"{y + 16:.1f}\" font-size=\"11\" "
                       f"font-family=\"sans-serif\" fill=\"#fff\">{_html.escape(short)}</text>")
            svg.append(f"<text x=\"{x + 4:.1f}\" y=\"{y + 30:.1f}\" font-size=\"10\" "
                       f"font-family=\"sans-serif\" fill=\"#fff\">{_html.escape(status)}</text>")
    svg.append("</svg>")
    return "\n".join(svg) + "\n"
    """Render the static dashboard. Pure string building; no I/O, no mutation."""
def render_html(live: dict[str, str] | None = None) -> str:
    """Render the static dashboard. Pure string building; no I/O, no mutation."""
    live = live or {}
    parts: list[str] = []
    parts.append("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
                 "<title>Baby AI Project Status Dashboard (M067)</title>"
                 f"<style>{_CSS}</style></head><body>")
    parts.append("<h1>Baby AI Project Status Dashboard</h1>")
    parts.append(f"<p>Evidence date: <b>{EVIDENCE_DATE}</b> · GIT_HEAD: <code>{GIT_HEAD}</code> · "
                 f"Ledger: <b>{LEDGER_ENTRIES} entries, head {LEDGER_HEAD}, sealed</b> · "
                 "Read-only status artifact: this page asserts nothing, authorizes nothing, "
                 "and changes nothing.</p>")
    if live:
        parts.append("<h2>Live-verified headline state</h2><table><tr><th>Fact</th><th>Live value</th></tr>")
        for key in ("ledger_entries", "ledger_head", "chain_intact", "seal_intact",
                    "gate_1", "gate_2_open", "explog_drift", "m064_sha",
                    "runtime_selection", "model_deployment", "birth_record",
                    "production_descriptor", "production_content"):
            parts.append(f"<tr><td>{_esc(key)}</td><td><code>{_esc(live.get(key, '?'))}</code></td></tr>")
        parts.append("</table>")
    parts.append("<h2>Progress by track (exact fractions; no blended percent asserted)</h2>")
    parts.append("<p class=\"small\">Rules: categorical milestones only; HOLD counts as complete "
                 "(hold fulfilled its purpose); specifications excluded from implementation counts; "
                 "tests never count as authorization; readiness never counts as operation.</p>")
    parts.append("<table><tr><th>Track</th><th>Scope</th><th>Progress</th></tr>")
    for name, scope, ids in TRACKS:
        done, total = track_fraction(ids)
        pct = int(100 * done / total) if total else 0
        parts.append(f"<tr><td>{_esc(name)}</td><td class=\"small\">{_esc(scope)}</td>"
                     f"<td><div class=\"bar\"><i style=\"width:{pct}%\"></i></div>"
                     f"{done}/{total}</td></tr>")
    parts.append("</table>")
    parts.append("<h2>Workstream map (tile size carries no weight)</h2><div class=\"tiles\">")
    for name, status, note, date in WORKSTREAMS:
        cls = status.split(" ")[0].replace("(", "").upper()
        parts.append(f"<div class=\"tile st-{cls}\"><b>{_esc(name)}</b><br>{_esc(status)}"
                     f"<br><span class=\"small\">{_esc(note)} · as of {date}</span></div>")
    parts.append("</div>")
    parts.append("<p class=\"legend small\">Legend: green = complete/healthy/closed/frozen/pass; "
                 "amber = partial/hold-active/blocked/mitigated (attention, not failure); "
                 "red = missing/open/fail; gray = evidenced-not-reverified / unknown / specification. "
                 "FAIL on incident-state checks after recovery means 'incident absent', not failure.</p>")
    parts.append("<h2>Gates (independent of progress)</h2><table>"
                 "<tr><th>Gate</th><th>State</th><th>Basis</th></tr>")
    for name, state, basis in GATES:
        first = state.split(" ")[0].upper()
        cls = first if first in ("CLOSED", "UNCREATED", "NONE", "BLOCKED", "OPEN",
                                 "PARTIAL", "COMPLETE", "FAIL", "PASS") else "UNKNOWN"
        parts.append(f"<tr><td>{_esc(name)}</td><td class=\"st-{cls}\">{_esc(state)}</td>"
                     f"<td class=\"small\">{_esc(basis)}</td></tr>")
    parts.append("</table><h2>Authorizations (independent of tests)</h2><table>"
                 "<tr><th>Authorization</th><th>State</th><th>Note</th></tr>")
    for name, state, note in AUTHORIZATIONS:
        parts.append(f"<tr><td>{_esc(name)}</td><td>{_esc(state)}</td>"
                     f"<td class=\"small\">{_esc(note)}</td></tr>")
    parts.append("</table><h2>Milestones M001–M067</h2><table><tr><th>ID</th><th>Title</th>"
                 "<th>Status</th><th>Basis</th><th>Re-verified M067</th></tr>")
    for mid, title, status, basis, rever in MILESTONES:
        parts.append(f"<tr><td>{_esc(mid)}</td><td>{_esc(title)}</td>"
                     f"<td class=\"st-{status}\">{_esc(status)}</td>"
                     f"<td class=\"small\">{_esc(basis)}</td>"
                     f"<td>{'YES' if rever else 'basis only'}</td></tr>")
    parts.append("</table><h2>Open human decisions</h2><table>"
                 "<tr><th>Decision</th><th>Needed before</th></tr>")
    for name, timing in DECISIONS_OPEN:
        parts.append(f"<tr><td>{_esc(name)}</td><td>{_esc(timing)}</td></tr>")
    parts.append("</table><h2>Risks</h2><table><tr><th>Risk</th><th>State</th><th>Note</th></tr>")
    for name, state, note in RISKS:
        parts.append(f"<tr><td>{_esc(name)}</td><td>{_esc(state)}</td>"
                     f"<td class=\"small\">{_esc(note)}</td></tr>")
    parts.append("</table><h2>Next recommended milestone</h2>")
    parts.append(f"<p><b>{_esc(NEXT_MILESTONE[0])}</b> — {_esc(NEXT_MILESTONE[1])}</p>")
    parts.append("<h2>Methods &amp; limitations</h2><p class=\"small\">Headline facts re-verified "
                 "live via ledger verify + seal check, gate reads, file hashing, and existence "
                 "checks on 2026-10-09. Earlier milestones marked EVIDENCED carry their own "
                 "evidence docs' claims, not fresh M067 verification. No blended completion "
                 "percentage is asserted; the prior informal forty-percent figure is not used. This page "
                 "is static HTML with no scripts and no external resources; it cannot authorize, "
                 "launch, mutate, or seal anything.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
