"""Disabled, provider-free R6 Claude adapter candidate."""
from .contracts import (
    ContractError,
    HistoricalIdentityLedger,
    TrustedArtifactRef,
    TrustedExternalGrant,
    TrustedExternalGrantRegistry,
    held_binding_digest,
    stage_a_template,
    validate_stage_a_evidence,
    validate_stage_a_template,
    validate_stage_b_seal,
)
from .adapter import FakeClaudeBoundary, StageAResult, execute_stage_a

__all__ = [
    "ContractError",
    "HistoricalIdentityLedger",
    "TrustedArtifactRef",
    "TrustedExternalGrant",
    "TrustedExternalGrantRegistry",
    "held_binding_digest",
    "FakeClaudeBoundary",
    "StageAResult",
    "execute_stage_a",
    "stage_a_template",
    "validate_stage_a_evidence",
    "validate_stage_a_template",
    "validate_stage_b_seal",
]
