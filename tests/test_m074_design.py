"""M074 -- design-doc structure tests. Read-only; no operational impact."""

from __future__ import annotations

from pathlib import Path

DOC = Path("docs/evidence/m074-tier3-isolation-design.md")


def test_design_exists_with_required_sections():
    assert DOC.exists()
    text = DOC.read_text(encoding="utf-8")
    for section in (
        "## 1. Execution-pathway inventory",
        "## 2. Tier-3 security contract",
        "## 3. Implementation options",
        "## 4. Verification plan",
        "## 5. Dependency and authorization map",
        "## 6. Residual risks",
        "## 7. Human decisions required",
        "## 8. Authority statement",
    ):
        assert section in text, section


def test_design_claims_no_implementation_or_authority():
    text = DOC.read_text(encoding="utf-8")
    assert "authorizes nothing" in text
    for claim in ("Tier 3 IMPLEMENTED", "has been provisioned",
                  "probe was executed", "Gate 1 is OPEN", "Gate 2 is OPEN",
                  "launch is authorized", "birth is authorized",
                  "hereby authorize", "PROV-000019"):
        assert claim not in text, claim
    assert "no fallback" in text.lower() or "no implicit" in text.lower()
