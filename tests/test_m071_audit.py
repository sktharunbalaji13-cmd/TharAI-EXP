"""M071 -- audit-artifact structure tests. Read-only; no operational impact."""

from __future__ import annotations

from pathlib import Path

DOC = Path("docs/evidence/m071-security-evidence-audit.md")


def test_audit_exists_with_required_sections():
    assert DOC.exists()
    text = DOC.read_text(encoding="utf-8")
    for section in (
        "## 1. Tier-2 11-path evidence matrix",
        "## 2. Tier-3 identity and token separation",
        "## 3. FILE_DELETE_CHILD",
        "## 4. Staging immutability",
        "## 5. Network",
        "## 6. Model/runtime, birth, launch preconditions",
        "## 7. Dependency register",
        "## 8. Unknowns and contradictions",
        "## 9. Authority statement",
    ):
        assert section in text, section


def test_audit_claims_no_authority_and_no_invention():
    text = DOC.read_text(encoding="utf-8")
    assert "grants NO operational authority" in text
    for claim in ("Gate 1 OPEN", "Gate 2 OPEN", "launch authorized",
                  "birth authorized", "hereby authorize", "PROV-000019",
                  "TIER_3_IMPLEMENTED", "enforcement verified by this audit"):
        assert claim not in text, claim
    assert "NOT implemented" in text or "unimplemented" in text or "NO " in text
