"""M075 -- preflight-doc structure tests. Read-only; no operational impact."""

from __future__ import annotations

from pathlib import Path

DOC = Path("docs/evidence/m075-tier3-preflight.md")


def test_preflight_exists_with_required_sections():
    assert DOC.exists()
    text = DOC.read_text(encoding="utf-8")
    for section in (
        "## 1. Implementation surface",
        "## 2. Account and privilege preflight",
        "## 3. Token-verification design",
        "## 4. Disposable verification procedure",
        "## 5. Recovery and rollback plan",
        "## 6. Proposed authorization manifest",
        "## 7. Implementation readiness",
        "## 8. Authority statement",
    ):
        assert section in text, section


def test_human_choices_marked_unresolved_not_invented():
    text = DOC.read_text(encoding="utf-8")
    assert "UNRESOLVED" in text
    assert "HUMAN CHOICE REQUIRED" in text
    for claim in ("Gate 1 OPEN", "Gate 2 OPEN", "launch authorized",
                  "birth authorized", "hereby authorize", "PROV-000019",
                  "password is ", "SeImpersonatePrivilege granted"):
        assert claim not in text, claim
