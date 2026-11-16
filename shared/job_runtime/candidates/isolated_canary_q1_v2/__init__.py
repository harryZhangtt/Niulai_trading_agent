"""Reviewed source-authority v2 candidate. No invocation capability."""
from .authority import capability_gate, load_authority_manifest
from .contracts import AuthorityV2Error, CapabilityGateV2
__all__ = ["AuthorityV2Error", "CapabilityGateV2", "capability_gate", "load_authority_manifest"]
