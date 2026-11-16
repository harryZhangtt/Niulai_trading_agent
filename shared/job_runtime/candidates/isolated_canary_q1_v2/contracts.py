"""Fail-closed partial capability contract for reviewed Codex authority v2."""
from dataclasses import dataclass

class AuthorityV2Error(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

@dataclass(frozen=True)
class CapabilityGateV2:
    source_authority_verified: bool
    source_grammar_verified: bool
    binary_asset_verified: bool
    source_to_binary_reproducible_build_verified: bool
    retry_zero_live_verified: bool
    sanitized_live_capture_verified: bool
    gateway_observer_reconciliation_verified: bool
    capability_open: bool

    def __post_init__(self) -> None:
        values = tuple(getattr(self, name) for name in self.__dataclass_fields__)
        if any(type(value) is not bool for value in values):
            raise AuthorityV2Error("CODEX_Q1_V2_CAPABILITY_INVALID")
        prerequisites = values[:-1]
        if self.capability_open and not all(prerequisites):
            raise AuthorityV2Error("CODEX_Q1_V2_CAPABILITY_OPEN_INVALID")
