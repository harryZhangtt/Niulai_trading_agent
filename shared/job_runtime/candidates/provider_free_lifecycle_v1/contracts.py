"""Strict inert contracts for the additive provider-free lifecycle candidate."""
from dataclasses import dataclass
from collections import namedtuple
from types import MappingProxyType
from typing import Any, Mapping
import hashlib, json, re

SHA = re.compile(r"[0-9a-f]{64}")
SCHEMA = "provider-free-lifecycle-v1"
SCENARIOS = ("nominal", "post_admission_ambiguity")
EXPECTED_GRANT = MappingProxyType({
    "source_sha256": "e1cfe354991e0680ed7202b20734cce2bead0b5aaeaba65f24d584a0259a89c1",
    "config_sha256": "069cad0e76c5596017ca4a1b9152ee4938b2bbaa1c16d0a47d9f5777012b4d21",
    "allocation_sha256": "5c24da1b1ed99810dedd9ed94332057cfefe0854e3fc088f2e71e919d963bbe9",
    "prompt_sha256": "20398230cd739e266f4659743b9d9d7428193848ae67bd20e2ddb9603dae046e",
    "predecessor_r5_sha256": "d199fd079b7f94ca17d9fd1d6bb9e5b2339178403948d8173dabebd948b33d78",
    "predecessor_r4_slot_sha256": "66ca95b8a8cd1b6471b893a13169249d8a36713e5475665e42352a13dbec2186",
    "predecessor_r4_attempt_sha256": "f8ddc6225b89f25cff3a39ae0cc310ef7348d7fd507783eb597d61ed9c35ae08",
})

class LifecycleContractError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")

def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()

def _sha(value: Any) -> bool:
    return type(value) is str and SHA.fullmatch(value) is not None

def _strict(mapping: Mapping[str, Any], keys: set) -> None:
    if type(mapping) is not dict or set(mapping) != keys:
        raise LifecycleContractError("PFL_SHAPE_INVALID")

BINDING_FIELDS = ("schema_version","scenario","source_sha256","config_sha256","allocation_sha256","prompt_sha256","predecessor_r5_sha256","predecessor_r4_slot_sha256","predecessor_r4_attempt_sha256","old_replay_authorized","new_logical_job_authorized","enabled","capability_open")
_BindingBase = namedtuple("BindingV1Base", BINDING_FIELDS)
class BindingV1(_BindingBase):
    __slots__ = ()
    def __new__(cls, schema_version, scenario, source_sha256, config_sha256, allocation_sha256,
                prompt_sha256, predecessor_r5_sha256, predecessor_r4_slot_sha256,
                predecessor_r4_attempt_sha256, old_replay_authorized,
                new_logical_job_authorized, enabled, capability_open):
        self = super().__new__(cls, schema_version, scenario, source_sha256, config_sha256,
            allocation_sha256, prompt_sha256, predecessor_r5_sha256, predecessor_r4_slot_sha256,
            predecessor_r4_attempt_sha256, old_replay_authorized, new_logical_job_authorized,
            enabled, capability_open)
        if self.schema_version != SCHEMA or self.scenario not in SCENARIOS:
            raise LifecycleContractError("PFL_BINDING_INVALID")
        if not all(_sha(x) for x in (self.source_sha256,self.config_sha256,self.allocation_sha256,
            self.prompt_sha256,self.predecessor_r5_sha256,self.predecessor_r4_slot_sha256,
            self.predecessor_r4_attempt_sha256)):
            raise LifecycleContractError("PFL_BINDING_INVALID")
        if any(type(x) is not bool for x in (self.old_replay_authorized,self.new_logical_job_authorized,self.enabled,self.capability_open)):
            raise LifecycleContractError("PFL_BINDING_INVALID")
        if self.old_replay_authorized or not self.new_logical_job_authorized or self.enabled or self.capability_open:
            raise LifecycleContractError("PFL_BINDING_INVALID")
        for key, expected in EXPECTED_GRANT.items():
            if getattr(self,key) != expected: raise LifecycleContractError("PFL_GRANT_MISMATCH")
        return self

@dataclass(frozen=True)
class EvidenceV1:
    schema_version: str
    scenario: str
    binding_sha256: str
    engine_binding_sha256: str
    operation_binding_sha256: str
    prompt_binding_sha256: str
    effect_evidence_kind: str
    dispatch_count: int
    dispatch_before_reconstruction: int
    slot_count: int
    attempt_count: int
    slot_status: str
    attempt_status: str
    reconstructed_dispatch_count: int
    replay_authorized: bool
    provider_calls: int
    network_calls: int
    process_calls: int
    host_calls: int
    email_calls: int
    business_effects: int
    enabled: bool
    capability_open: bool
    evidence_sha256: str

    def body(self) -> dict:
        return {key: getattr(self, key) for key in self.__dataclass_fields__ if key != "evidence_sha256"}

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA or self.scenario not in SCENARIOS or not all(_sha(x) for x in (self.binding_sha256, self.engine_binding_sha256, self.operation_binding_sha256, self.prompt_binding_sha256)) or self.engine_binding_sha256 != self.binding_sha256 or self.effect_evidence_kind != "deny_by_default_recorder":
            raise LifecycleContractError("PFL_EVIDENCE_INVALID")
        ints = (self.dispatch_count, self.dispatch_before_reconstruction, self.slot_count, self.attempt_count, self.reconstructed_dispatch_count,
                self.provider_calls, self.network_calls, self.process_calls, self.host_calls,
                self.email_calls, self.business_effects)
        if any(type(x) is not int or x < 0 for x in ints):
            raise LifecycleContractError("PFL_EVIDENCE_INVALID")
        if any(type(x) is not bool for x in (self.replay_authorized, self.enabled, self.capability_open)):
            raise LifecycleContractError("PFL_EVIDENCE_INVALID")
        if self.slot_count != 1 or self.attempt_count != 1 or self.dispatch_count != 1 or self.dispatch_before_reconstruction != 1 or self.reconstructed_dispatch_count != 1:
            raise LifecycleContractError("PFL_COUNT_INVALID")
        expected = ("succeeded", "succeeded") if self.scenario == "nominal" else ("unknown", "unknown")
        if (self.slot_status, self.attempt_status) != expected or self.replay_authorized or self.enabled or self.capability_open:
            raise LifecycleContractError("PFL_STATE_INVALID")
        if any((self.provider_calls, self.network_calls, self.process_calls, self.host_calls,
                self.email_calls, self.business_effects)):
            raise LifecycleContractError("PFL_EFFECT_INVALID")
        if self.evidence_sha256 != digest(self.body()):
            raise LifecycleContractError("PFL_DIGEST_INVALID")

def binding_from_mapping(value: Mapping[str, Any]) -> BindingV1:
    keys = set(BINDING_FIELDS)
    _strict(value, keys)
    try:
        return BindingV1(**value)
    except (TypeError, LifecycleContractError):
        raise LifecycleContractError("PFL_BINDING_INVALID") from None

def evidence_from_mapping(value: Mapping[str, Any]) -> EvidenceV1:
    keys = set(EvidenceV1.__dataclass_fields__)
    _strict(value, keys)
    try:
        return EvidenceV1(**value)
    except (TypeError, LifecycleContractError):
        raise LifecycleContractError("PFL_EVIDENCE_INVALID") from None

def public_projection(evidence: EvidenceV1) -> Mapping[str, Any]:
    return MappingProxyType(dict(evidence.body(), evidence_sha256=evidence.evidence_sha256))
