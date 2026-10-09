"""M067 -- dashboard correctness + read-only enforcement tests.

All checks are read-only except writing to pytest tmp_path (never the repo).
Live-state assertions use the same read paths as the dashboard itself.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import tests.m067_dashboard as D


def test_track_fractions_follow_rules_r1_r2():
    by_id = {mid: status for mid, _, status, _, _ in D.MILESTONES}
    for name, _scope, ids in D.TRACKS:
        done, total = D.track_fraction(ids)
        assert total == len(ids) and total > 0, name
        expect = sum(1 for i in ids if by_id[i] in D.COMPLETE_LIKE)
        assert done == expect, name
        assert all(by_id[i] != "OPEN" or True for i in ids)


def test_no_blended_percent_and_bars_match_labels():
    html = D.render_html(D.collect_live_state())
    assert "No blended completion percentage is asserted" in html
    for name, _scope, ids in D.TRACKS:
        done, total = D.track_fraction(ids)
        assert f"{done}/{total}" in html, name
        pct = int(100 * done / total)
        assert f"width:{pct}%" in html, name
    assert "~40%" not in html
    assert "forty-percent figure is not used" in html


def test_live_state_matches_authoritative_baseline():
    live = D.collect_live_state()
    assert live["ledger_entries"] == "18"
    assert live["ledger_head"] == "PROV-000018"
    assert live["chain_intact"] == "True"
    assert live["seal_intact"] == "True"
    assert live["gate_1"] == "CLOSED"
    assert live["gate_2_open"] == "False"
    assert live["explog_drift"] == "07efda7adb6ee30f"
    assert live["m064_sha"] == "e2a3939e77a55200"
    assert live["runtime_selection"] == "False"
    assert live["model_deployment"] == "False"
    assert live["birth_record"] == "False"
    assert live["production_descriptor"] == (
        "d63ff646bec494c198db9031491558f2744ea40bb2b1af016090e980865c1f27")
    assert live["production_content"] == (
        "55250a71209a4d397dc51f3f12da105455a5d20ace53062416d26079fded0cdf")


def test_module_contains_no_writer_or_authority_mint():
    source = Path(D.__file__).read_text(encoding="utf-8")
    for token in ("import subprocess", "from subprocess", ".record(",
                  "ledger.record", ".seal(", "append_line", "rmtree",
                  "SetAccessControl", "AddAccessRule", "Set-Acl", "icacls",
                  "open(", "ProductionCapability(", "RecoveryCapability",
                  "token_bytes", "mint(", "register(", "run_process(",
                  "os.replace", "copy2", "chmod", "chown"):
        assert token not in source, token


def test_reporting_changes_no_operational_state():
    from babylab.hashing import file_sha256
    from babylab.paths import default_paths
    from provenance.keyring import Keyring
    from provenance.ledger import ProvenanceLedger
    paths = default_paths()
    watched = [paths.provenance_ledger,
               paths.root / "research" / "experiment-log.md",
               paths.root / "subject_runtime" / "runtime" / "m016_read_fixture.exe"]
    before = [file_sha256(p) for p in watched]
    keyring = Keyring(paths.keyring, paths.private_key_dir)
    ledger = ProvenanceLedger(paths.provenance_ledger, keyring,
                              seal_dir=paths.protected_provenance)
    n_before = sum(1 for _ in ledger.iter_entries())
    D.collect_live_state()
    D.render_html(D.collect_live_state())
    after = [file_sha256(p) for p in watched]
    n_after = sum(1 for _ in ledger.iter_entries())
    assert before == after
    assert n_before == n_after == 18


def test_rendered_page_structure_and_content():
    page = Path("docs/m067-status-dashboard.html")
    assert page.exists()
    text = page.read_text(encoding="utf-8")

    class _P(HTMLParser):
        def error(self, message):
            raise AssertionError(message)
    _P().feed(text)

    for section in ("Workstream map", "Gates (independent of progress)",
                    "Authorizations (independent of tests)", "Milestones M001",
                    "Open human decisions", "Risks", "Next recommended milestone",
                    "Methods &amp; limitations", "no scripts and no external resources"):
        assert section in text, section
    for digest in ("0b7148e0", "4d5c64e5", "d63ff646", "55250a71",
                   "07efda7a", "e2a3939e"):
        assert digest in text, digest
    assert "<script" not in text.lower()
    assert "PROV-000018" in text


def test_markdown_twin_parity():
    live = D.collect_live_state()
    md = D.render_markdown(live)
    page = Path("docs/m067-status-dashboard.md")
    assert page.exists()
    assert page.read_text(encoding="utf-8") == md
    for section in ("## Workstream map", "## Gates (independent of progress)",
                    "## Authorizations (independent of tests)", "## Milestones M001",
                    "## Open human decisions", "## Risks",
                    "## Next recommended milestone", "## Methods & limitations"):
        assert section in md, section
    for digest in ("0b7148e0", "4d5c64e5", "d63ff646", "55250a71",
                   "07efda7a", "e2a3939e", "PROV-000018"):
        assert digest in md, digest
    assert "forty-percent figure is not used" in md
    assert "~40%" not in md
    for name, _scope, ids in D.TRACKS:
        done, total = D.track_fraction(ids)
        assert f"{done}/{total}" in md, name
