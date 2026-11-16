"""Disabled provider-free R6 live successor. Importing performs no I/O."""
from .contracts import ContractError, LiveAuthorization
from .grant import TrustedAuthorizationVerifier, stage_a_template
__all__=["ContractError","LiveAuthorization","TrustedAuthorizationVerifier","stage_a_template"]
