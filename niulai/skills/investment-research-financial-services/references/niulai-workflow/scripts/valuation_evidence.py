"""Evidence coverage gate, not proof of economic forecast accuracy."""
from datetime import datetime
VERSION = "2026-10-20-valuation-evidence-1"
ACTIVATED = datetime.fromisoformat("2026-10-20T12:36:23+00:00")
SECTIONS = ("business_values", "forecast_validation", "probability_basis", "professional_research", "technical_confirmation")

def validate(rec, force=False):
    if rec.get("scope") not in ("company_full", "fund_full", "crypto_full"):
        return
    block = rec.get("valuation_evidence")
    receipts = rec.get("persistence", {}).get("receipts", [])
    legacy = False
    if not force and receipts:
        try:
            legacy = all(datetime.fromisoformat(x["confirmed_at"].replace("Z", "+00:00")) < ACTIVATED for x in receipts)
        except (KeyError, ValueError, TypeError):
            pass
    if block is None and legacy:
        return
    if not isinstance(block, dict) or block.get("version") != VERSION:
        raise ValueError("Required valuation_evidence policy missing or stale")
    artifacts = {x["id"] for x in rec.get("artifacts", [])}
    for name in SECTIONS:
        section = block.get(name, {})
        if section.get("status") not in ("evidenced", "limited", "not_applicable"):
            raise ValueError(name + ": evidence status missing")
        if not isinstance(section.get("finding"), str) or not section["finding"].strip():
            raise ValueError(name + ": finding missing")
        refs = section.get("artifact_refs")
        if not isinstance(refs, list) or not refs or any(x not in artifacts for x in refs):
            raise ValueError(name + ": unresolved evidence artifacts")
        if section["status"] != "evidenced" and not section.get("limitations"):
            raise ValueError(name + ": limitations required")
