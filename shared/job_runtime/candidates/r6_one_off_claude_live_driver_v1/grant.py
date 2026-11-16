"""Grant boundary: Stage A is non-authorizing; Stage B only validates pinned successor contracts."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Mapping
from shared.job_runtime.candidates.r6_one_off_claude_adapter_v1 import (
    HistoricalIdentityLedger, TrustedExternalGrantRegistry, stage_a_template,
    validate_stage_a_template, validate_stage_b_seal,
)

def provider_free_template() -> Mapping[str, Any]:
    value = stage_a_template("a" * 64, "opaque-ref://claude/current")
    validate_stage_a_template(value); return value

def validate_future_stage_b(seal: Mapping[str, Any], registry: TrustedExternalGrantRegistry,
                            ledger: HistoricalIdentityLedger, now: datetime) -> Mapping[str, Any]:
    """Validation only. This function cannot construct a grant, registry, or authority."""
    return validate_stage_b_seal(seal, registry, ledger, now)
