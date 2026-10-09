"""M068 -- graphical treemap verification.

Read-only except pytest tmp_path. Live reads mirror the dashboard collector.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import tests.m067_dashboard as D


def _tree():
    return D.build_treemap()


def test_geometry_deterministic():
    first = D.build_treemap()
    second = D.build_treemap()
    assert first["tiles"].keys() == second["tiles"].keys()
    for mid in first["tiles"]:
        assert first["tiles"][mid]["rect"] == second["tiles"][mid]["rect"], mid


def _overlap(a, b) -> bool:
    eps = 1e-9
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return (ax + eps < bx + bw - eps and bx + eps < ax + aw - eps
            and ay + eps < by + bh - eps and by + eps < ay + ah - eps)


def test_no_overlap_and_contained():
    tree = _tree()
    rects = list(tree["tiles"].values())
    rects = [t["rect"] for t in rects]
    for i in range(len(rects)):
        x, y, w, h = rects[i]
        assert x >= 0 and y >= 0 and x + w <= 1000.0 + 1e-6 and y + h <= 620.0 + 1e-6
        assert w > 0 and h > 0
        for j in range(i + 1, len(rects)):
            assert not _overlap(rects[i], rects[j]), (i, j)


def test_tiles_match_real_task_sets():
    tree = _tree()
    milestone_ids = {mid for mid, _, _, _, _ in D.MILESTONES}
    assert set(tree["tiles"].keys()) == milestone_ids
    track_ids = {i for _, _, ids in D.TRACKS for i in ids}
    assert track_ids == milestone_ids
    for mid, tile in tree["tiles"].items():
        assert tile["track"]
        assert tile["title"] and tile["status"] and tile["basis"]
        assert tile["evidence"] and tile["remaining"]


def test_areas_follow_sizing_rule():
    tree = _tree()
    areas = {mid: t["rect"][2] * t["rect"][3] for mid, t in tree["tiles"].items()}
    expect = (1000.0 * 620.0) / len(areas)
    for mid, area in areas.items():
        assert abs(area - expect) / expect < 0.05, (mid, area)
    track_area: dict[str, float] = {}
    for track in tree["tracks"]:
        track_area[track["name"]] = sum(
            areas[mid] for mid in track["ids"] if mid in areas)
    totals = {name: len(ids) for name, _, ids in D.TRACKS}
    for name in track_area:
        assert abs(track_area[name] / totals[name] - expect) / expect < 0.05, name


def test_colors_match_verified_states():
    tree = _tree()
    by_id = {mid: status for mid, _, status, _, _ in D.MILESTONES}
    for mid, tile in tree["tiles"].items():
        status, kind = tile["status"], tile["kind"]
        assert tile["color"] == D.tile_color(status, kind), mid
        if status == "EVIDENCED" or "not re-verified" in tile["evidence"]:
            assert tile["color"] != "green", mid
        if kind == "SPEC":
            assert tile["color"] == "blue", mid
        if status == "OPEN":
            assert tile["color"] != "green", mid
    reds = [m for m, t in tree["tiles"].items() if t["color"] == "red"]
    assert reds == []


def test_gates_separate_and_birth_launch_unexecuted():
    html = D.render_graphical_html(D.collect_live_state())
    assert "separate from progress" in html
    for gate, _, _ in D.GATES:
        assert gate in html
    live = D.collect_live_state()
    assert live["birth_record"] == "False"
    assert live["gate_1"] == "CLOSED" and live["gate_2_open"] == "False"


def test_consistent_canonical_data_across_renders():
    live = D.collect_live_state()
    md = D.render_markdown(live)
    html = D.render_html(live)
    graph = D.render_graphical_html(live)
    for digest in ("0b7148e0", "4d5c64e5", "d63ff646", "55250a71",
                   "07efda7a", "e2a3939e", "PROV-000018"):
        assert digest in md, digest
        assert digest in html, digest
    assert "PROV-000018" in graph
    assert "0b7148e0" in graph and "4d5c64e5" in graph
    for name, _scope, ids in D.TRACKS:
        done, total = D.track_fraction(ids)
        assert f"{done}/{total}" in md and f"{done}/{total}" in html
        assert f"{done}/{total}" in graph


def test_readme_links_resolve_and_pages_status():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "m068-treemap.html" in readme
    assert "m068-treemap-preview.svg" in readme
    assert Path("docs/m068-treemap.html").exists()
    assert Path("docs/m068-treemap-preview.svg").exists()
    assert Path("docs/m067-status-dashboard.md").exists()
    assert "GitHub Pages" in readme


def test_no_external_scripts_or_resources():
    for name in ("docs/m068-treemap.html", "docs/m068-treemap-preview.svg",
                 "docs/m067-status-dashboard.html"):
        text = Path(name).read_text(encoding="utf-8")
        lowered = text.lower().replace('xmlns="http://www.w3.org/2000/svg"', "")
        assert "<script src" not in lowered, name
        assert "http://" not in lowered and "https://" not in lowered, name
        assert "analytics" not in lowered, name

    class _P(HTMLParser):
        def error(self, message):
            raise AssertionError(message)
    _P().feed(Path("docs/m068-treemap.html").read_text(encoding="utf-8"))


def test_rendering_mutates_nothing():
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
    live = D.collect_live_state()
    D.render_graphical_html(live)
    D.render_preview_svg()
    D.render_html(live)
    D.render_markdown(live)
    after = [file_sha256(p) for p in watched]
    n_after = sum(1 for _ in ledger.iter_entries())
    assert before == after
    assert n_before == n_after == 18
