"""Same-process integration-owned verifier; candidate-only and not promotable."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
import threading
from typing import Any, Mapping

from shared.job_runtime.candidates.claude_loopback_gateway_v1 import ExpectedPreForwardBinding
from shared.job_runtime.candidates.claude_campaign_v1 import CampaignIdentityV1
from . import contracts as _contracts
from .contracts import GatewayAuthenticatedSummary, IntegrationContractError, O1IdentityBindingV1

_FIELDS = frozenset({"gateway_disposition", "terminal_disposition", "http_status",
    "upstream_forward_count", "submission", "typed_transient", "retry_after_seconds",
    "request_ordinal", "proof"})


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping): return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple): return [_plain(item) for item in value]
    return value


def _encoded(value: Mapping[str, Any]) -> bytes:
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


class _CampaignProof:
    __slots__ = ("summary_id", "owner_token", "value")
    def __init__(self, summary_id: int, owner_token: object, value: Mapping[str, Any]) -> None:
        self.summary_id = summary_id; self.owner_token = owner_token; self.value = value


class SameProcessIntegrationVerifier:
    """Owns summary authentication/consumption and campaign state seals."""

    def __init__(self, *, gateway_verifier: Any, expected_binding: ExpectedPreForwardBinding,
                 token_factory: Any = secrets.token_hex) -> None:
        if not callable(token_factory): raise TypeError("token factory must be callable")
        tokens = tuple(token_factory(24) for _ in range(3))
        if any(type(token) is not str or len(token) < 16 for token in tokens) or len(set(tokens)) != 3:
            raise ValueError("token factory returned invalid or duplicate tokens")
        self.verifier_identity = "claude_next_phase_v1.verifier.%s" % tokens[0]
        self.generation_id = "generation-%s" % tokens[1]; self.anchor_id = "anchor-%s" % tokens[2]
        self.active = True; self.verification_calls = 0; self.summary_consumption_calls = 0
        self._gateway_verifier = gateway_verifier; self._expected_binding = expected_binding
        self._owner_token = object(); self._key = secrets.token_bytes(32); self._lock = threading.Lock()
        self._state_nonce = 0; self._consumed_states: set[str] = set()
        self._issued_summaries: dict[int, GatewayAuthenticatedSummary] = {}
        self._consumed_summaries: set[int] = set(); self._issued_campaign_proofs: dict[int, _CampaignProof] = {}
        self._consumed_campaign_proofs: set[int] = set()

    def close(self) -> None:
        with self._lock: self.active = False; self._key = b""; self._issued_summaries.clear()

    def _mac(self, domain: bytes, value: Mapping[str, Any]) -> str:
        return hmac.new(self._key, domain+b"\0"+_encoded(value), hashlib.sha256).hexdigest()

    @staticmethod
    def _identity_value(identity: Any) -> Mapping[str, Any]:
        if type(identity) is not CampaignIdentityV1: raise IntegrationContractError("SUMMARY_IDENTITY_INVALID")
        fields = ("campaign_id", "run_id", "job_id", "slot_id", "attempt_id", "operation_id",
                  "request_id", "prompt_id", "gateway_id", "process_id", "prompt_sha256",
                  "source_sha256", "config_sha256", "version")
        try: return {name: getattr(identity, name) for name in fields}
        except AttributeError as exc: raise IntegrationContractError("SUMMARY_IDENTITY_INVALID") from exc

    @staticmethod
    def _o1_value(o1: O1IdentityBindingV1) -> Mapping[str, Any]:
        if type(o1) is not O1IdentityBindingV1: raise IntegrationContractError("O1_IDENTITY_BINDING_INVALID")
        return {name: getattr(o1, name) for name in o1.__dataclass_fields__}

    @staticmethod
    def _evidence_value(value: Mapping[str, Any]) -> Mapping[str, Any]:
        return {key: _plain(item) for key, item in value.items() if key != "proof"}

    @staticmethod
    def _commit(value: Mapping[str, Any]) -> str:
        return hashlib.sha256(_encoded(value)).hexdigest()

    @staticmethod
    def _validate_identity(identity: Any, o1: O1IdentityBindingV1,
                           expected: ExpectedPreForwardBinding) -> None:
        if (identity.operation_id != o1.operation_id or identity.prompt_id != o1.prompt_id
                or expected.operation_binding_hash != o1.operation_binding_sha256
                or expected.prompt_binding_hash != o1.prompt_binding_sha256):
            raise IntegrationContractError("O1_GATEWAY_BINDING_MISMATCH")

    def _issue_authenticated_summary(self, raw_summary: Mapping[str, Any], *, identity: Any,
                                     o1_binding: O1IdentityBindingV1) -> GatewayAuthenticatedSummary:
        """Private candidate issuance API after gateway/integration authentication."""
        if type(raw_summary) is not dict or set(raw_summary) != _FIELDS or not self.active:
            raise IntegrationContractError("GATEWAY_SUMMARY_INVALID")
        self._validate_identity(identity, o1_binding, self._expected_binding)
        value = dict(raw_summary); disposition = value["gateway_disposition"]
        forwarded = value["upstream_forward_count"]; ordinal = value["request_ordinal"]
        if type(ordinal) is not int or ordinal < 1 or type(forwarded) is not int:
            raise IntegrationContractError("GATEWAY_SUMMARY_SCALAR_INVALID")
        if disposition == "rejected_before_forward":
            if (forwarded != 0 or value["http_status"] != 502 or value["submission"] != "not_submitted"
                    or type(value["retry_after_seconds"]) is not int or value["retry_after_seconds"] <= 0):
                raise IntegrationContractError("GATEWAY_PRE_FORWARD_INVALID")
            try:
                verified = self._gateway_verifier.verify_and_consume(value["proof"],
                    expected_binding=self._expected_binding, request_ordinal=ordinal)
            except Exception as exc:
                raise IntegrationContractError("GATEWAY_AUTHENTICATION_FAILED") from exc
            if (verified.binding is not self._expected_binding or verified.status != 502
                    or verified.upstream_attempts != 0 or verified.submission != "not_submitted"):
                raise IntegrationContractError("GATEWAY_AUTHENTICATION_RESULT_INVALID")
        elif disposition == "pass_through":
            if forwarded != 1 or value["proof"] is not None:
                raise IntegrationContractError("GATEWAY_PASS_THROUGH_INVALID")
        elif disposition == "cut":
            if forwarded != 1 or value["proof"] is not None:
                raise IntegrationContractError("GATEWAY_CUT_INVALID")
        else: raise IntegrationContractError("GATEWAY_DISPOSITION_INVALID")
        summary = GatewayAuthenticatedSummary(_contracts._SUMMARY_TOKEN, value,
            verifier_identity=self.verifier_identity, generation_id=self.generation_id,
            anchor_id=self.anchor_id, owner_token=self._owner_token,
            identity_commitment=self._commit(self._identity_value(identity)),
            o1_commitment=self._commit(self._o1_value(o1_binding)),
            evidence_commitment=self._commit(self._evidence_value(value)))
        with self._lock:
            if not self.active: raise IntegrationContractError("VERIFIER_REVOKED")
            self.verification_calls += 1; self._issued_summaries[id(summary)] = summary
        return summary

    def consume_summary(self, summary: GatewayAuthenticatedSummary, *, identity: Any,
                        o1_binding: O1IdentityBindingV1) -> _CampaignProof:
        """Atomically verify exact owner, commitments, generation, and consume once."""
        with self._lock:
            sid=id(summary)
            if (not self.active or type(summary) is not GatewayAuthenticatedSummary
                    or self._issued_summaries.get(sid) is not summary or sid in self._consumed_summaries
                    or summary._owner_token is not self._owner_token
                    or summary.verifier_identity != self.verifier_identity
                    or summary.generation_id != self.generation_id or summary.anchor_id != self.anchor_id
                    or summary._identity_commitment != self._commit(self._identity_value(identity))
                    or summary._o1_commitment != self._commit(self._o1_value(o1_binding))
                    or summary._evidence_commitment != self._commit(self._evidence_value(summary.value))):
                raise IntegrationContractError("SUMMARY_NOT_ISSUED_OR_CONSUMED")
            value=summary.value
            proof=_CampaignProof(sid, self._owner_token, value)
            self._consumed_summaries.add(sid); self._issued_campaign_proofs[id(proof)]=proof
            self.summary_consumption_calls += 1
            return proof

    def _seal_locked(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        self._state_nonce += 1
        envelope={"state_id":"state-%d"%self._state_nonce,"generation_id":self.generation_id,
            "anchor_id":self.anchor_id,"body_sha256":hashlib.sha256(_encoded(body)).hexdigest()}
        return {**envelope,"hmac_sha256":self._mac(b"state",envelope)}

    def _verify_state_locked(self, body: Mapping[str, Any], proof: Mapping[str, Any]) -> None:
        if (not self.active or type(proof) is not dict or set(proof)!={"state_id","generation_id","anchor_id","body_sha256","hmac_sha256"}):
            raise IntegrationContractError("STATE_PROOF_INVALID")
        envelope={key:proof[key] for key in ("state_id","generation_id","anchor_id","body_sha256")}
        if (proof["state_id"] in self._consumed_states or envelope["generation_id"]!=self.generation_id
                or envelope["anchor_id"]!=self.anchor_id or envelope["body_sha256"]!=hashlib.sha256(_encoded(body)).hexdigest()
                or not hmac.compare_digest(proof["hmac_sha256"],self._mac(b"state",envelope))):
            raise IntegrationContractError("STATE_PROOF_INVALID")

    def seal_initial_state(self, state_body: Mapping[str, Any]) -> Mapping[str, Any]:
        with self._lock:
            if not self.active: raise IntegrationContractError("VERIFIER_REVOKED")
            return self._seal_locked(dict(state_body))

    def verify_state(self, state_body: Mapping[str, Any], state_attestation: Mapping[str, Any]) -> None:
        with self._lock: self._verify_state_locked(dict(state_body),state_attestation)

    def verify_state_and_seal_next(self,current_body:Mapping[str,Any],current_attestation:Mapping[str,Any],next_body:Mapping[str,Any])->Mapping[str,Any]:
        with self._lock:
            self._verify_state_locked(dict(current_body),current_attestation)
            result=self._seal_locked(dict(next_body)); self._consumed_states.add(current_attestation["state_id"]); return result

    def verify_and_consume(self,proof_mapping:Any,expected_bindings:Mapping[str,Any],current_body:Mapping[str,Any],current_attestation:Mapping[str,Any],next_state_builder:Any)->Any:
        with self._lock:
            self._verify_state_locked(dict(current_body),current_attestation); pid=id(proof_mapping)
            if (type(proof_mapping) is not _CampaignProof or self._issued_campaign_proofs.get(pid) is not proof_mapping
                    or pid in self._consumed_campaign_proofs or proof_mapping.owner_token is not self._owner_token):
                raise IntegrationContractError("CAMPAIGN_PROOF_INVALID")
            value=proof_mapping.value; expected=dict(expected_bindings)
            if not all(expected[key]==value[key] for key in ("gateway_disposition","terminal_disposition","http_status","upstream_forward_count","submission","retry_after_seconds")):
                raise IntegrationContractError("SUMMARY_CAMPAIGN_BINDING_MISMATCH")
            body=dict(next_state_builder(datetime.now(timezone.utc))); result=self._seal_locked(body)
            self._consumed_campaign_proofs.add(pid); self._consumed_states.add(current_attestation["state_id"])
            return body,result
