"""Strict inert contracts for the provider-free next-phase composition candidate."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Optional, Protocol, runtime_checkable


class IntegrationContractError(ValueError):
    """Stable, value-free contract failure."""


_SHA = frozenset("0123456789abcdef")
_SUMMARY_TOKEN = object()


def _sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _SHA


def _fail(code: str) -> None:
    raise IntegrationContractError(code)


def _deep_freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_deep_freeze(item) for item in value)
    if value is None or type(value) in (str, int, bool):
        return value
    _fail("SUMMARY_VALUE_INVALID")


@dataclass(frozen=True)
class O1IdentityBindingV1:
    """Typed operation/prompt identity inherited from the CLEAN O1 contract."""
    operation_id: str
    prompt_id: str
    operation_binding_sha256: str
    prompt_binding_sha256: str

    def __post_init__(self) -> None:
        if (type(self.operation_id) is not str or not self.operation_id
                or type(self.prompt_id) is not str or not self.prompt_id
                or not _sha(self.operation_binding_sha256)
                or not _sha(self.prompt_binding_sha256)):
            _fail("O1_IDENTITY_BINDING_INVALID")


class GatewayAuthenticatedSummary:
    """Recursively immutable summary issued only by one integration verifier."""
    __slots__ = ("_value", "_verifier_identity", "_generation_id", "_anchor_id", "_owner_token",
                 "_identity_commitment", "_o1_commitment", "_evidence_commitment")

    def __init__(self, token: object, value: Mapping[str, Any], *, verifier_identity: str,
                 generation_id: str, anchor_id: str, owner_token: object,
                 identity_commitment: str, o1_commitment: str, evidence_commitment: str) -> None:
        if token is not _SUMMARY_TOKEN:
            raise TypeError("authenticated summary requires integration verifier")
        object.__setattr__(self, "_value", _deep_freeze(dict(value)))
        object.__setattr__(self, "_verifier_identity", verifier_identity)
        object.__setattr__(self, "_generation_id", generation_id)
        object.__setattr__(self, "_anchor_id", anchor_id)
        object.__setattr__(self, "_owner_token", owner_token)
        for name, commitment in (("_identity_commitment", identity_commitment),
                                 ("_o1_commitment", o1_commitment),
                                 ("_evidence_commitment", evidence_commitment)):
            if not _sha(commitment): _fail("SUMMARY_COMMITMENT_INVALID")
            object.__setattr__(self, name, commitment)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("authenticated summary is immutable")

    def __copy__(self) -> object:
        raise TypeError("authenticated summary cannot be copied")

    def __deepcopy__(self, memo: object) -> object:
        raise TypeError("authenticated summary cannot be copied")

    @property
    def value(self) -> Mapping[str, Any]: return self._value
    @property
    def verifier_identity(self) -> str: return self._verifier_identity
    @property
    def generation_id(self) -> str: return self._generation_id
    @property
    def anchor_id(self) -> str: return self._anchor_id


@runtime_checkable
class IntegrationOwnedVerifier(Protocol):
    @property
    def verifier_identity(self) -> str: ...
    @property
    def generation_id(self) -> str: ...
    @property
    def anchor_id(self) -> str: ...
    @property
    def active(self) -> bool: ...
    def consume_summary(self, summary: GatewayAuthenticatedSummary, *, identity: Any,
                        o1_binding: O1IdentityBindingV1) -> Any: ...
    def seal_initial_state(self, state_body: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def verify_state(self, state_body: Mapping[str, Any], state_attestation: Mapping[str, Any]) -> None: ...
    def verify_state_and_seal_next(self, current_body: Mapping[str, Any],
                                   current_attestation: Mapping[str, Any],
                                   next_body: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def verify_and_consume(self, proof_mapping: Any, expected_bindings: Mapping[str, Any],
                           current_body: Mapping[str, Any], current_attestation: Mapping[str, Any],
                           next_state_builder: Any) -> Any: ...


@dataclass(frozen=True)
class IntegrationResultV1:
    route: str
    status: str
    action: str
    request_count: int
    upstream_forward_count: int
    replay_permitted: bool
    unknown_fenced: bool
    retry_after_seconds: Optional[int]
    state: Any
    evidence: Any

    def __post_init__(self) -> None:
        head = (self.route, self.status, self.action, self.request_count,
                self.upstream_forward_count, self.replay_permitted, self.unknown_fenced)
        allowed = {
            ("R6", "succeeded", "none", 1, 1, False, False),
            ("R6", "succeeded", "none", 2, 1, False, False),
            ("R7", "retry_wait", "restart", 1, 0, True, False),
            ("R8", "unknown", "reconcile_only", 1, 1, False, True),
        }
        if head not in allowed:
            _fail("RESULT_TUPLE_INVALID")
        if self.route == "R7":
            if type(self.retry_after_seconds) is not int or self.retry_after_seconds <= 0:
                _fail("RESULT_RETRY_INVALID")
        elif self.retry_after_seconds is not None:
            _fail("RESULT_RETRY_FORBIDDEN")


PREREQUISITES = MappingProxyType({
    "R9": MappingProxyType({"name": "visible-session-evidence", "candidate": "claude_visible_session_v1",
        "enabled": False, "capability_open": False, "live_authority": False,
        "intended_runtime": False, "materialized": False}),
    "R10": MappingProxyType({"name": "visible-cli-grammar", "candidate": "claude_visible_cli_v1",
        "producer_review": "PENDING_SEPARATE_REVIEW", "enabled": False, "capability_open": False,
        "live_authority": False, "intended_runtime": False, "materialized": False}),
})

CAPABILITIES = MappingProxyType({
    "enabled": False, "capability_open": False, "live_authority": False, "intended_runtime": False,
    "provider_access": False, "network_access": False, "process_access": False,
    "host_access": False, "email_access": False, "cli_enabled": False, "cli_materialized": False,
    "promotion_blocked": True,
    "promotion_block_reason": "gateway authority is same-process candidate-only",
    "promotion_requires": ("separate authority process or OS-protected key custody", "new security review"),
})
