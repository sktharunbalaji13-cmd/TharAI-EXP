"""M070 -- planning-artifact structure tests. Read-only; no operational impact."""

from __future__ import annotations

import re
from pathlib import Path

DOC = Path("docs/evidence/m070-security-prerequisite-plan.md")


def test_plan_exists_with_required_sections():
    assert DOC.exists()
    text = DOC.read_text(encoding="utf-8")
    for section in (
        "## 1. M066 residual gap",
        "## 2. Workstream A",
        "## 3. Workstream B",
        "## 4. Workstream C",
        "## 5. Workstream D",
        "## 6. Workstream E",
        "## 7. Birth and launch preconditions",
        "## 8. Phased milestone sequence",
        "## 9. Human-decision checklist",
        "## 10. Authority statement",
    ):
        assert section in text, section


def test_plan_claims_no_authority():
    text = DOC.read_text(encoding="utf-8")
    assert "grants NO operational authority" in text
    for claim in ("Gate 1 OPEN", "Gate 2 OPEN", "launch authorized",
                  "birth authorized", "hereby authorize", "PROV-000019",
                  "PROV-000020"):
        assert claim not in text, claim


def test_plan_contains_no_invented_digests():
    text = DOC.read_text(encoding="utf-8")
    found = set(re.findall(r"\b[0-9a-f]{64}\b", text))
    assert not found, found
    for prefix in ("d63ff646", "55250a71"):
        assert prefix in text, prefix
