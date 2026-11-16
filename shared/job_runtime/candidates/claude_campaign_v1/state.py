"""Verifier-authenticated, linear campaign state transitions."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import copy
import re
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple

from .contracts import (Authority, CampaignContractError, CampaignIdentityV1, EvidenceV1,
                        GatewayDisposition, PreForwardProofVerifier, Submission,
                        TerminalDisposition, classify_authority)

_RECONCILIATION = "claude_campaign_v1.named_unknown_reconciliation"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_SLOTS = frozenset(("slot-1", "slot-2"))
_MAX_ATTEMPTS = {"R6": 1, "R7": 2, "R8": 1}
_BODY_KEYS = {"version", "campaign_id", "expected_identity", "expected_evidence_sha256",
              "verifier_identity", "verifier_generation", "verifier_anchor_id", "slot_scope",
              "status", "attempts", "max_attempts", "next_retry_at", "retry_observed_at",
              "retry_after_seconds", "unknown_slot_id", "blocked_slots", "reconciliation_adapter"}


def _fail(code: str) -> None:
    raise CampaignContractError(code)


def _aware(value: datetime, code: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _fail(code)
    return value.astimezone(timezone.utc)


def _timestamp(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if type(value) is not str:
        _fail("STATE_RETRY_AT_INVALID")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        _fail("STATE_RETRY_AT_INVALID")


def _expected_bindings(evidence: EvidenceV1) -> Mapping[str, Any]:
    identity = evidence.identity
    return MappingProxyType({
        "campaign_id": identity.campaign_id, "run_id": identity.run_id,
        "job_id": identity.job_id, "slot_id": identity.slot_id,
        "attempt_id": identity.attempt_id, "operation_id": identity.operation_id,
        "request_id": identity.request_id, "prompt_id": identity.prompt_id,
        "gateway_id": identity.gateway_id, "process_id": identity.process_id,
        "prompt_sha256": identity.prompt_sha256, "source_sha256": identity.source_sha256,
        "config_sha256": identity.config_sha256, "evidence_sha256": evidence.evidence_sha256,
        "gateway_disposition": evidence.gateway_disposition.value,
        "terminal_disposition": evidence.terminal_disposition.value,
        "http_status": evidence.http_status,
        "upstream_forward_count": evidence.upstream_forward_count,
        "submission": evidence.submission.value,
        "retry_after_seconds": evidence.retry_after_seconds,
    })


def _pre_forward_candidate(evidence: EvidenceV1) -> bool:
    return (evidence.identity.campaign_id == "R7"
            and evidence.gateway_disposition is GatewayDisposition.REJECTED_BEFORE_FORWARD
            and evidence.terminal_disposition is TerminalDisposition.ABSENT
            and evidence.http_status == 502 and evidence.upstream_forward_count == 0
            and evidence.submission is Submission.NOT_SUBMITTED
            and evidence.typed_transient is True and evidence.retry_after_seconds is not None)


@dataclass(frozen=True)
class CampaignStateV1:
    campaign_id: str
    expected_identity: CampaignIdentityV1
    expected_evidence_sha256: str
    verifier_identity: str
    verifier_generation: str
    verifier_anchor_id: str
    state_attestation: Mapping[str, Any]
    _verifier: PreForwardProofVerifier
    _verifier_anchor: PreForwardProofVerifier
    slot_scope: Tuple[str, str] = ("slot-1", "slot-2")
    status: str = "ready"
    attempts: int = 0
    max_attempts: int = 1
    next_retry_at: Optional[datetime] = None
    retry_observed_at: Optional[datetime] = None
    retry_after_seconds: Optional[float] = None
    unknown_slot_id: Optional[str] = None
    blocked_slots: Tuple[str, ...] = ()
    reconciliation_adapter: str = _RECONCILIATION
    version: int = 1

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != 1:
            _fail("STATE_VERSION_INVALID")
        if not isinstance(self.expected_identity, CampaignIdentityV1):
            _fail("STATE_EXPECTED_IDENTITY_INVALID")
        if self.campaign_id != self.expected_identity.campaign_id:
            _fail("STATE_CAMPAIGN_BINDING_MISMATCH")
        if type(self.expected_evidence_sha256) is not str or _SHA256.fullmatch(self.expected_evidence_sha256) is None:
            _fail("STATE_EVIDENCE_SHA256_INVALID")
        if (any(type(value) is not str or _ID.fullmatch(value) is None for value in (
                self.verifier_identity, self.verifier_generation, self.verifier_anchor_id))
                or self._verifier is not self._verifier_anchor
                or not isinstance(self._verifier, PreForwardProofVerifier)
                or self._verifier.verifier_identity != self.verifier_identity
                or self._verifier.generation_id != self.verifier_generation
                or self._verifier.anchor_id != self.verifier_anchor_id
                or self._verifier.active is not True):
            _fail("STATE_VERIFIER_BINDING_INVALID")
        if type(self.state_attestation) is not dict:
            _fail("STATE_ATTESTATION_INVALID")
        if (type(self.slot_scope) is not tuple or len(self.slot_scope) != 2
                or set(self.slot_scope) != _SLOTS or self.slot_scope[0] == self.slot_scope[1]
                or self.expected_identity.slot_id not in self.slot_scope):
            _fail("STATE_SLOT_SCOPE_INVALID")
        if self.reconciliation_adapter != _RECONCILIATION:
            _fail("STATE_RECONCILIATION_ADAPTER_INVALID")
        if self.status not in ("ready", "retry_wait", "succeeded", "terminal_failed", "unknown", "reconciled"):
            _fail("STATE_STATUS_INVALID")
        if (type(self.attempts) is not int or type(self.max_attempts) is not int
                or not 0 <= self.attempts <= self.max_attempts
                or self.max_attempts != _MAX_ATTEMPTS[self.campaign_id]):
            _fail("STATE_ATTEMPTS_INVALID")
        if self.status == "ready" and not (self.attempts == 0 or (self.campaign_id == "R7" and self.attempts == 1)):
            _fail("STATE_STATUS_ATTEMPT_CONFLICT")
        if self.status == "retry_wait" and not (self.campaign_id == "R7" and self.attempts == 1 < self.max_attempts):
            _fail("STATE_STATUS_ATTEMPT_CONFLICT")
        if self.status in ("succeeded", "terminal_failed", "unknown", "reconciled") and self.attempts < 1:
            _fail("STATE_STATUS_ATTEMPT_CONFLICT")
        retry_values = (self.next_retry_at, self.retry_observed_at, self.retry_after_seconds)
        if self.status == "retry_wait":
            if any(value is None for value in retry_values):
                _fail("STATE_RETRY_PROOF_REQUIRED")
            observed = _aware(self.retry_observed_at, "STATE_RETRY_AT_INVALID")
            next_at = _aware(self.next_retry_at, "STATE_RETRY_AT_INVALID")
            if (type(self.retry_after_seconds) is not int
                    or not 1 <= self.retry_after_seconds <= 30 * 86400
                    or next_at != observed + timedelta(seconds=self.retry_after_seconds)):
                _fail("STATE_RETRY_PROOF_INVALID")
        elif any(value is not None for value in retry_values):
            _fail("STATE_RETRY_PROOF_FORBIDDEN")
        if self.status == "unknown":
            if self.unknown_slot_id != self.expected_identity.slot_id or self.blocked_slots != self.slot_scope:
                _fail("STATE_UNKNOWN_FENCE_INVALID")
        elif self.unknown_slot_id is not None or self.blocked_slots:
            _fail("STATE_UNKNOWN_FENCE_FORBIDDEN")
        try:
            self._verifier.verify_state(self.body_mapping(), self.state_attestation)
        except Exception:
            _fail("STATE_ATTESTATION_INVALID")

    def body_mapping(self) -> Mapping[str, Any]:
        identity = {field: getattr(self.expected_identity, field)
                    for field in self.expected_identity.__dataclass_fields__}
        return {
            "version": self.version, "campaign_id": self.campaign_id,
            "expected_identity": identity, "expected_evidence_sha256": self.expected_evidence_sha256,
            "verifier_identity": self.verifier_identity,
            "verifier_generation": self.verifier_generation,
            "verifier_anchor_id": self.verifier_anchor_id,
            "slot_scope": list(self.slot_scope), "status": self.status,
            "attempts": self.attempts, "max_attempts": self.max_attempts,
            "next_retry_at": _timestamp(self.next_retry_at),
            "retry_observed_at": _timestamp(self.retry_observed_at),
            "retry_after_seconds": self.retry_after_seconds,
            "unknown_slot_id": self.unknown_slot_id, "blocked_slots": list(self.blocked_slots),
            "reconciliation_adapter": self.reconciliation_adapter,
        }

    def to_mapping(self) -> Mapping[str, Any]:
        return {**self.body_mapping(), "state_attestation": copy.deepcopy(dict(self.state_attestation))}


def _from_body(body: Mapping[str, Any], attestation: Mapping[str, Any],
               verifier: PreForwardProofVerifier, anchor: PreForwardProofVerifier) -> CampaignStateV1:
    if type(body) is not dict or set(body) != _BODY_KEYS:
        _fail("STATE_KEYS_INVALID")
    identity = body["expected_identity"]
    if type(identity) is not dict or set(identity) != set(CampaignIdentityV1.__dataclass_fields__):
        _fail("STATE_EXPECTED_IDENTITY_INVALID")
    if type(body["slot_scope"]) is not list or type(body["blocked_slots"]) is not list:
        _fail("STATE_SLOT_LIST_INVALID")
    return CampaignStateV1(
        campaign_id=body["campaign_id"], expected_identity=CampaignIdentityV1(**identity),
        expected_evidence_sha256=body["expected_evidence_sha256"],
        verifier_identity=body["verifier_identity"], verifier_generation=body["verifier_generation"],
        verifier_anchor_id=body["verifier_anchor_id"], state_attestation=dict(attestation),
        _verifier=verifier, _verifier_anchor=anchor, slot_scope=tuple(body["slot_scope"]),
        status=body["status"], attempts=body["attempts"], max_attempts=body["max_attempts"],
        next_retry_at=_parse_timestamp(body["next_retry_at"]),
        retry_observed_at=_parse_timestamp(body["retry_observed_at"]),
        retry_after_seconds=body["retry_after_seconds"], unknown_slot_id=body["unknown_slot_id"],
        blocked_slots=tuple(body["blocked_slots"]),
        reconciliation_adapter=body["reconciliation_adapter"], version=body["version"])


def create_initial_state(identity: CampaignIdentityV1, evidence_sha256: str,
                         verifier: PreForwardProofVerifier,
                         pinned_verifier: PreForwardProofVerifier) -> CampaignStateV1:
    if verifier is not pinned_verifier:
        _fail("STATE_VERIFIER_BINDING_INVALID")
    body = {
        "version": 1, "campaign_id": identity.campaign_id,
        "expected_identity": {field: getattr(identity, field) for field in identity.__dataclass_fields__},
        "expected_evidence_sha256": evidence_sha256,
        "verifier_identity": verifier.verifier_identity,
        "verifier_generation": verifier.generation_id, "verifier_anchor_id": verifier.anchor_id,
        "slot_scope": ["slot-1", "slot-2"], "status": "ready", "attempts": 0,
        "max_attempts": _MAX_ATTEMPTS[identity.campaign_id], "next_retry_at": None,
        "retry_observed_at": None, "retry_after_seconds": None,
        "unknown_slot_id": None, "blocked_slots": [],
        "reconciliation_adapter": _RECONCILIATION,
    }
    try:
        attestation = verifier.seal_initial_state(body)
    except Exception:
        _fail("STATE_INITIAL_SEAL_FAILED")
    return _from_body(body, attestation, verifier, pinned_verifier)


def restore_state(value: Mapping[str, Any], *, verifier: PreForwardProofVerifier,
                  pinned_verifier: PreForwardProofVerifier) -> CampaignStateV1:
    if type(value) is not dict or set(value) != _BODY_KEYS | {"state_attestation"}:
        _fail("STATE_KEYS_INVALID")
    body = {key: copy.deepcopy(value[key]) for key in _BODY_KEYS}
    return _from_body(body, value["state_attestation"], verifier, pinned_verifier)


def _verify_current(state: CampaignStateV1) -> None:
    if not isinstance(state, CampaignStateV1):
        _fail("STATE_TRANSITION_INPUT_INVALID")
    if (state._verifier is not state._verifier_anchor
            or state._verifier.verifier_identity != state.verifier_identity
            or state._verifier.generation_id != state.verifier_generation
            or state._verifier.anchor_id != state.verifier_anchor_id
            or state._verifier.active is not True):
        _fail("STATE_VERIFIER_BINDING_INVALID")
    try:
        state._verifier.verify_state(state.body_mapping(), state.state_attestation)
    except Exception:
        _fail("STATE_ATTESTATION_INVALID")


def _seal_next(state: CampaignStateV1, body: Mapping[str, Any]) -> CampaignStateV1:
    try:
        proof = state._verifier.verify_state_and_seal_next(
            state.body_mapping(), state.state_attestation, body)
    except Exception:
        _fail("STATE_TRANSITION_SEAL_FAILED")
    return _from_body(body, proof, state._verifier, state._verifier_anchor)


def _next_body(state: CampaignStateV1, **changes: Any) -> Mapping[str, Any]:
    body = copy.deepcopy(dict(state.body_mapping()))
    body.update(changes)
    return body


def apply_evidence(state: CampaignStateV1, evidence: EvidenceV1, *, proof_mapping: Any = None) -> CampaignStateV1:
    if not isinstance(evidence, EvidenceV1) or state.status != "ready":
        _fail("STATE_TRANSITION_INVALID")
    if evidence.retry_after_seconds is not None and (type(evidence.retry_after_seconds) is not int
            or not 1 <= evidence.retry_after_seconds <= 30 * 86400):
        _fail("STATE_RETRY_AFTER_INVALID")
    _verify_current(state)
    evidence.validate_binding(state.expected_identity)
    if evidence.evidence_sha256 != state.expected_evidence_sha256:
        _fail("STATE_EVIDENCE_SHA256_MISMATCH")
    authority = classify_authority(evidence)
    attempts = state.attempts + 1
    base = {"attempts": attempts}
    if _pre_forward_candidate(evidence):
        def build(observed_at: Any) -> Mapping[str, Any]:
            observed = _aware(observed_at, "STATE_VERIFIED_OBSERVED_AT_INVALID")
            delay = evidence.retry_after_seconds
            status = "retry_wait" if attempts < state.max_attempts else "terminal_failed"
            return _next_body(
                state, attempts=attempts, status=status,
                retry_observed_at=_timestamp(observed) if status == "retry_wait" else None,
                retry_after_seconds=delay if status == "retry_wait" else None,
                next_retry_at=_timestamp(observed + timedelta(seconds=delay)) if status == "retry_wait" else None)
        try:
            body, attestation = state._verifier.verify_and_consume(
                proof_mapping, _expected_bindings(evidence), state.body_mapping(),
                state.state_attestation, build)
            return _from_body(body, attestation, state._verifier, state._verifier_anchor)
        except Exception:
            # Invalid gateway proof consumes neither gateway nor state proof; seal unknown linearly.
            return _seal_next(state, _next_body(
                state, status="unknown", attempts=attempts,
                unknown_slot_id=evidence.identity.slot_id, blocked_slots=list(state.slot_scope)))
    if authority is Authority.SUCCEEDED:
        return _seal_next(state, _next_body(state, status="succeeded", **base))
    if authority is Authority.TERMINAL_FAILED:
        return _seal_next(state, _next_body(state, status="terminal_failed", **base))
    return _seal_next(state, _next_body(
        state, status="unknown", attempts=attempts,
        unknown_slot_id=evidence.identity.slot_id, blocked_slots=list(state.slot_scope)))


def retry_ready(state: CampaignStateV1, now: datetime, *, next_identity: CampaignIdentityV1,
                next_evidence_sha256: str) -> CampaignStateV1:
    _verify_current(state)
    if state.status != "retry_wait" or state.attempts >= state.max_attempts:
        _fail("STATE_NOT_WAITING")
    if _aware(now, "STATE_NOW_INVALID") < state.next_retry_at:
        _fail("STATE_COOLDOWN_ACTIVE")
    previous = state.expected_identity
    stable = ("campaign_id", "run_id", "job_id", "slot_id", "prompt_id",
              "prompt_sha256", "source_sha256", "config_sha256")
    fresh = ("attempt_id", "operation_id", "request_id", "gateway_id", "process_id")
    if (not isinstance(next_identity, CampaignIdentityV1)
            or any(getattr(previous, field) != getattr(next_identity, field) for field in stable)):
        _fail("STATE_NEXT_IDENTITY_BINDING_MISMATCH")
    if any(getattr(previous, field) == getattr(next_identity, field) for field in fresh):
        _fail("STATE_NEXT_IDENTITY_NOT_FRESH")
    if type(next_evidence_sha256) is not str or _SHA256.fullmatch(next_evidence_sha256) is None:
        _fail("STATE_EVIDENCE_SHA256_INVALID")
    body = _next_body(
        state, status="ready",
        expected_identity={field: getattr(next_identity, field) for field in next_identity.__dataclass_fields__},
        expected_evidence_sha256=next_evidence_sha256,
        next_retry_at=None, retry_observed_at=None, retry_after_seconds=None)
    return _seal_next(state, body)


def named_unknown_reconciliation(state: CampaignStateV1, *, adapter: str, resolved: bool) -> CampaignStateV1:
    _verify_current(state)
    if state.status != "unknown" or adapter != state.reconciliation_adapter or type(resolved) is not bool:
        _fail("RECONCILIATION_AUTHORITY_INVALID")
    if not resolved:
        return state
    return _seal_next(state, _next_body(
        state, status="reconciled", unknown_slot_id=None, blocked_slots=[]))
