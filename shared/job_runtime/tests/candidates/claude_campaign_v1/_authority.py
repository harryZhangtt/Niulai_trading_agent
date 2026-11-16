"""Test-only locked HMAC owner for gateway observations and campaign states."""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import threading
from collections.abc import Mapping


class _ObservedGatewayRecord:
    __slots__ = ("bindings", "observed_at")
    def __init__(self, bindings, observed_at):
        self.bindings = dict(bindings); self.observed_at = observed_at


class _Proof(Mapping):
    __slots__ = ("_value",)
    def __init__(self, value): self._value = value
    def __getitem__(self, key): return self._value[key]
    def __iter__(self): return iter(self._value)
    def __len__(self): return len(self._value)


class HMACObservationAuthority:
    verifier_identity = "test.hmac_gateway_observer.v1"
    _generation_counter = 0

    def __init__(self):
        type(self)._generation_counter += 1
        number = type(self)._generation_counter
        self.generation_id = "generation-%d" % number
        self.anchor_id = "anchor-%d" % number
        self.active = True
        self.verification_calls = 0; self.last_proof = None
        self.__key = ("synthetic-test-owner-key-%d" % number).encode()
        self.__lock = threading.Lock()
        self.__observed = set(); self.__issued = {}; self.__consumed = set()
        self.__gateway_nonce = 0; self.__state_nonce = 0; self.__consumed_states = set()

    @property
    def gateway_consumed_count(self):
        with self.__lock: return len(self.__consumed)

    @property
    def state_consumed_count(self):
        with self.__lock: return len(self.__consumed_states)

    def close(self):
        with self.__lock: self.active = False

    @staticmethod
    def _encoded(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

    def _mac(self, domain, value):
        return hmac.new(self.__key, domain + b"\0" + self._encoded(value), hashlib.sha256).hexdigest()

    def observe_gateway(self, bindings, observed_at):
        if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
            raise ValueError("OBSERVED_AT_INVALID")
        record = _ObservedGatewayRecord(bindings, observed_at.astimezone(timezone.utc))
        with self.__lock:
            if not self.active: raise ValueError("VERIFIER_REVOKED")
            self.__observed.add(id(record))
        return record

    def issue(self, record):
        with self.__lock:
            if not self.active or type(record) is not _ObservedGatewayRecord or id(record) not in self.__observed:
                raise ValueError("OBSERVATION_NOT_OWNED")
            self.__observed.remove(id(record)); self.__gateway_nonce += 1
            payload = {"bindings": record.bindings, "observed_at": record.observed_at.isoformat(),
                       "nonce": "gateway-%d" % self.__gateway_nonce,
                       "generation_id": self.generation_id, "anchor_id": self.anchor_id}
            proof = _Proof({"payload": payload, "hmac_sha256": self._mac(b"gateway", payload)})
            self.__issued[id(proof)] = proof
            return proof

    def _seal_state_locked(self, body):
        self.__state_nonce += 1
        state_id = "state-%d" % self.__state_nonce
        envelope = {"state_id": state_id, "generation_id": self.generation_id,
                    "anchor_id": self.anchor_id, "body_sha256": hashlib.sha256(
                        self._encoded(body)).hexdigest()}
        return {**envelope, "hmac_sha256": self._mac(b"state", envelope)}

    def _verify_state_locked(self, body, proof, require_unconsumed=True):
        if not self.active or type(proof) is not dict or set(proof) != {
                "state_id", "generation_id", "anchor_id", "body_sha256", "hmac_sha256"}:
            raise ValueError("STATE_PROOF_INVALID")
        envelope = {key: proof[key] for key in (
            "state_id", "generation_id", "anchor_id", "body_sha256")}
        if (envelope["generation_id"] != self.generation_id
                or envelope["anchor_id"] != self.anchor_id
                or envelope["body_sha256"] != hashlib.sha256(self._encoded(body)).hexdigest()
                or not hmac.compare_digest(proof["hmac_sha256"], self._mac(b"state", envelope))
                or (require_unconsumed and proof["state_id"] in self.__consumed_states)):
            raise ValueError("STATE_PROOF_INVALID")

    def seal_initial_state(self, state_body):
        with self.__lock:
            if not self.active: raise ValueError("VERIFIER_REVOKED")
            return self._seal_state_locked(dict(state_body))

    def verify_state(self, state_body, state_attestation):
        with self.__lock:
            self._verify_state_locked(dict(state_body), state_attestation)

    def verify_state_and_seal_next(self, current_body, current_attestation, next_body):
        with self.__lock:
            self._verify_state_locked(dict(current_body), current_attestation)
            proof = self._seal_state_locked(dict(next_body))
            self.__consumed_states.add(current_attestation["state_id"])
            return proof

    def _verify_gateway_locked(self, proof_mapping, expected_bindings):
        self.verification_calls += 1; self.last_proof = proof_mapping
        if (not self.active or type(proof_mapping) is not _Proof
                or self.__issued.get(id(proof_mapping)) is not proof_mapping
                or id(proof_mapping) in self.__consumed):
            raise ValueError("PROOF_NOT_ISSUED_OR_CONSUMED")
        value = dict(proof_mapping)
        payload = value.get("payload")
        if (type(payload) is not dict or value.get("hmac_sha256") != self._mac(b"gateway", payload)
                or payload.get("bindings") != dict(expected_bindings)
                or payload.get("generation_id") != self.generation_id
                or payload.get("anchor_id") != self.anchor_id):
            raise ValueError("PROOF_INVALID")
        return datetime.fromisoformat(payload["observed_at"])

    def verify_and_consume(self, proof_mapping, expected_bindings, current_body,
                           current_attestation, next_state_builder):
        with self.__lock:
            self._verify_state_locked(dict(current_body), current_attestation)
            observed = self._verify_gateway_locked(proof_mapping, expected_bindings)
            next_body = dict(next_state_builder(observed))
            next_proof = self._seal_state_locked(next_body)
            self.__consumed.add(id(proof_mapping))
            self.__consumed_states.add(current_attestation["state_id"])
            return next_body, next_proof


def expected_bindings_for(item):
    identity=item.identity
    return {"campaign_id":identity.campaign_id,"run_id":identity.run_id,"job_id":identity.job_id,
            "slot_id":identity.slot_id,"attempt_id":identity.attempt_id,"operation_id":identity.operation_id,
            "request_id":identity.request_id,"prompt_id":identity.prompt_id,"gateway_id":identity.gateway_id,
            "process_id":identity.process_id,"prompt_sha256":identity.prompt_sha256,
            "source_sha256":identity.source_sha256,"config_sha256":identity.config_sha256,
            "evidence_sha256":item.evidence_sha256,"gateway_disposition":item.gateway_disposition.value,
            "terminal_disposition":item.terminal_disposition.value,"http_status":item.http_status,
            "upstream_forward_count":item.upstream_forward_count,"submission":item.submission.value,
            "retry_after_seconds":item.retry_after_seconds}


def proof_for(authority,item,observed_at):
    return authority.issue(authority.observe_gateway(expected_bindings_for(item),observed_at))
