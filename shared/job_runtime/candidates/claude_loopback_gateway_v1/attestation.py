"""Candidate-only one-process HMAC attestation for synthetic pre-forward 502.

THREAT BOUNDARY: this module trusts gateway and integration-owner code in the same
Python process. It does not protect against arbitrary same-process code execution,
reflection, or module-private memory access. It MUST NOT be used as intended-runtime
or live-502 retry authority. Promotion requires a separate authority process or
OS-protected key custody and a new security review.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from types import MappingProxyType
from typing import Any, Mapping

PROOF_KIND = "adapter_hmac_pre_forward_502_v1"
PROOF_VERSION = "pre-forward-attestation-v1"
_PROOF_FIELDS = frozenset({
    "proof_version", "proof_kind", "authority_id", "generation",
    "run_binding_hash", "slot_binding_hash", "attempt_binding_hash",
    "operation_binding_hash", "prompt_binding_hash", "request_ordinal", "status",
    "upstream_attempts", "upstream_count_delta", "submission", "retry_after",
    "signature",
})
_SIGNED_FIELDS = _PROOF_FIELDS - {"signature"}

THREAT_MODEL = MappingProxyType({
    "schema_version": "claude-loopback-threat-model-v1",
    "classification": "candidate_only_one_process",
    "protects_against": (
        "untrusted_http_callers",
        "serialized_receipt_or_proof_forgery",
        "copied_public_mappings_or_verifier_values",
        "non_owner_integration_callers",
    ),
    "trusts": (
        "gateway_code_in_same_python_process",
        "integration_owner_code_in_same_python_process",
    ),
    "out_of_scope": (
        "arbitrary_same_process_code_execution",
        "reflection",
        "module_private_memory_access",
        "encoded_or_derived_upstream_credential_reflection",
    ),
    "upstream_trust_boundary": "trusted_beyond_exact_credential_reflection_guard",
    "upstream_credential_responsibility": "ferry_owner_entropy_strength_rotation_and_custody",
    "upstream_credential_identity": "distinct_from_high_entropy_gateway_client_bearer",
    "credential_separation": "upstream_authorization_must_not_equal_gateway_client_bearer",
    "use_prohibition": (
        "must_not_be_used_as_intended_runtime_authority",
        "must_not_be_used_as_live_502_retry_authority",
    ),
    "promotion_requires": (
        "separate_authority_process_or_os_protected_key_custody",
        "new_security_review",
    ),
    "capability_open": False,
    "live_authority": False,
    "intended_runtime_activation": False,
})


class AttestationVerificationError(ValueError):
    """Raised when an attestation is unavailable, invalid, revoked, or replayed."""


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _is_hash(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


class ExpectedPreForwardBinding:
    """Exact out-of-band one-shot binding supplied by the integration owner."""

    __slots__ = (
        "_run_binding_hash", "_slot_binding_hash", "_attempt_binding_hash",
        "_operation_binding_hash", "_prompt_binding_hash",
    )

    def __init__(
        self, *, run_binding_hash: str, slot_binding_hash: str,
        attempt_binding_hash: str, operation_binding_hash: str,
        prompt_binding_hash: str,
    ) -> None:
        values = (
            run_binding_hash, slot_binding_hash, attempt_binding_hash,
            operation_binding_hash, prompt_binding_hash,
        )
        if not all(_is_hash(value) for value in values):
            raise ValueError("expected bindings must be canonical SHA-256 strings")
        object.__setattr__(self, "_run_binding_hash", run_binding_hash)
        object.__setattr__(self, "_slot_binding_hash", slot_binding_hash)
        object.__setattr__(self, "_attempt_binding_hash", attempt_binding_hash)
        object.__setattr__(self, "_operation_binding_hash", operation_binding_hash)
        object.__setattr__(self, "_prompt_binding_hash", prompt_binding_hash)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("expected binding is immutable")

    @property
    def run_binding_hash(self) -> str:
        return self._run_binding_hash

    @property
    def slot_binding_hash(self) -> str:
        return self._slot_binding_hash

    @property
    def attempt_binding_hash(self) -> str:
        return self._attempt_binding_hash

    @property
    def operation_binding_hash(self) -> str:
        return self._operation_binding_hash

    @property
    def prompt_binding_hash(self) -> str:
        return self._prompt_binding_hash

    def as_dict(self) -> dict[str, str]:
        return {
            "run_binding_hash": self._run_binding_hash,
            "slot_binding_hash": self._slot_binding_hash,
            "attempt_binding_hash": self._attempt_binding_hash,
            "operation_binding_hash": self._operation_binding_hash,
            "prompt_binding_hash": self._prompt_binding_hash,
        }


class VerifiedPreForwardAttestation:
    """Immutable verification result; security comes from owner verification."""

    __slots__ = (
        "_authority_id", "_generation", "_binding", "_request_ordinal", "_sealed",
    )

    def __init__(
        self, token: object, *, authority_id: str, generation: int,
        binding: ExpectedPreForwardBinding, request_ordinal: int,
    ) -> None:
        if token is not _VERIFIED_RESULT_TOKEN:
            raise TypeError("verified result requires owner verification")
        object.__setattr__(self, "_authority_id", authority_id)
        object.__setattr__(self, "_generation", generation)
        object.__setattr__(self, "_binding", binding)
        object.__setattr__(self, "_request_ordinal", request_ordinal)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("verified attestation is immutable")

    @property
    def authority_id(self) -> str:
        return self._authority_id

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def binding(self) -> ExpectedPreForwardBinding:
        return self._binding

    @property
    def request_ordinal(self) -> int:
        return self._request_ordinal

    @property
    def status(self) -> int:
        return 502

    @property
    def upstream_attempts(self) -> int:
        return 0

    @property
    def upstream_count_delta(self) -> int:
        return 0

    @property
    def submission(self) -> str:
        return "not_submitted"

    @property
    def retry_after(self) -> str:
        return "1"


_VERIFIED_RESULT_TOKEN = object()
_OWNERS_LOCK = threading.Lock()
_OWNERS: dict[str, "_PreForwardAttestationOwner"] = {}


class PreForwardAttestationVerifier:
    """Ordinary-API verifier handle; not a boundary against reflection or process compromise."""

    __slots__ = ("_capability_id", "_generation")

    def __init__(self, token: object, capability_id: str, generation: int) -> None:
        if token is not _VERIFIER_CONSTRUCTOR_TOKEN:
            raise TypeError("verifier requires gateway-owned capability")
        self._capability_id = capability_id
        self._generation = generation

    def verify_and_consume(
        self,
        proof: object,
        *,
        expected_binding: ExpectedPreForwardBinding,
        request_ordinal: int,
    ) -> VerifiedPreForwardAttestation:
        if type(request_ordinal) is not int or request_ordinal < 1:
            raise AttestationVerificationError("request ordinal must be a strict positive integer")
        if type(expected_binding) is not ExpectedPreForwardBinding:
            raise AttestationVerificationError("expected binding capability is required")
        with _OWNERS_LOCK:
            owner = _OWNERS.get(self._capability_id)
        if owner is None:
            raise AttestationVerificationError("attestation authority is revoked")
        return owner.verify_and_consume(
            self._generation, proof, expected_binding, request_ordinal
        )

    def __copy__(self) -> "PreForwardAttestationVerifier":
        return self

    def __deepcopy__(self, memo: object) -> "PreForwardAttestationVerifier":
        return self

    def __reduce__(self) -> object:
        raise TypeError("attestation verifier cannot be pickled")


_VERIFIER_CONSTRUCTOR_TOKEN = object()


class _PreForwardAttestationOwner:
    """Mutable key owner and one-shot state authority for one gateway generation."""

    __slots__ = (
        "_lock", "_key", "_authority_id", "_capability_id", "_generation",
        "_expected", "_binding_consumed", "_issued", "_verified", "_active",
    )

    def __init__(self, expected: ExpectedPreForwardBinding) -> None:
        if type(expected) is not ExpectedPreForwardBinding:
            raise TypeError("exact expected pre-forward binding is required")
        self._lock = threading.Lock()
        self._key = bytearray(secrets.token_bytes(32))
        self._authority_id = secrets.token_hex(16)
        self._capability_id = secrets.token_hex(32)
        self._generation = secrets.randbits(63) + 1
        self._expected = expected
        self._binding_consumed = False
        self._issued: set[str] = set()
        self._verified: set[str] = set()
        self._active = True
        with _OWNERS_LOCK:
            _OWNERS[self._capability_id] = self

    @property
    def run_binding_hash(self) -> str:
        return self._expected.run_binding_hash

    def verifier(self) -> PreForwardAttestationVerifier:
        return PreForwardAttestationVerifier(
            _VERIFIER_CONSTRUCTOR_TOKEN, self._capability_id, self._generation
        )

    def consume_expected_binding(self) -> ExpectedPreForwardBinding | None:
        with self._lock:
            if not self._active or self._binding_consumed:
                return None
            self._binding_consumed = True
            return self._expected

    def sign_consumed(
        self, binding: ExpectedPreForwardBinding, request_ordinal: int
    ) -> Mapping[str, Any]:
        with self._lock:
            if (
                not self._active
                or not self._binding_consumed
                or binding is not self._expected
                or type(request_ordinal) is not int
                or request_ordinal < 1
            ):
                raise AttestationVerificationError("binding was not consumed by this authority")
            payload: dict[str, Any] = {
                "proof_version": PROOF_VERSION,
                "proof_kind": PROOF_KIND,
                "authority_id": self._authority_id,
                "generation": self._generation,
                **binding.as_dict(),
                "request_ordinal": request_ordinal,
                "status": 502,
                "upstream_attempts": 0,
                "upstream_count_delta": 0,
                "submission": "not_submitted",
                "retry_after": "1",
            }
            signature = hmac.new(self._key, _canonical(payload), hashlib.sha256).hexdigest()
            self._issued.add(signature)
            return MappingProxyType({**payload, "signature": signature})

    def verify_and_consume(
        self,
        generation: int,
        proof: object,
        expected: ExpectedPreForwardBinding,
        request_ordinal: int,
    ) -> VerifiedPreForwardAttestation:
        with self._lock:
            if not self._active or generation != self._generation:
                raise AttestationVerificationError("attestation authority generation is revoked")
            if type(proof) is not dict or set(proof) != _PROOF_FIELDS:
                raise AttestationVerificationError("attestation proof is missing or malformed")
            candidate = proof
            expected_values: dict[str, Any] = {
                "proof_version": PROOF_VERSION,
                "proof_kind": PROOF_KIND,
                "authority_id": self._authority_id,
                "generation": self._generation,
                **expected.as_dict(),
                "request_ordinal": request_ordinal,
                "status": 502,
                "upstream_attempts": 0,
                "upstream_count_delta": 0,
                "submission": "not_submitted",
                "retry_after": "1",
            }
            if expected is not self._expected:
                raise AttestationVerificationError("expected binding owner mismatch")
            strict_ints = ("generation", "request_ordinal", "status", "upstream_attempts", "upstream_count_delta")
            if any(type(candidate.get(name)) is not int for name in strict_ints):
                raise AttestationVerificationError("attestation scalar type invalid")
            if any(candidate.get(name) != value for name, value in expected_values.items()):
                raise AttestationVerificationError("attestation binding or outcome mismatch")
            if not all(_is_hash(candidate[name]) for name in (
                "run_binding_hash", "slot_binding_hash", "attempt_binding_hash",
                "operation_binding_hash", "prompt_binding_hash",
            )):
                raise AttestationVerificationError("attestation hash binding malformed")
            signature = candidate.get("signature")
            if not _is_hash(signature):
                raise AttestationVerificationError("attestation signature malformed")
            signed = {name: candidate[name] for name in _SIGNED_FIELDS}
            expected_signature = hmac.new(self._key, _canonical(signed), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected_signature):
                raise AttestationVerificationError("attestation signature invalid")
            if signature not in self._issued or signature in self._verified:
                raise AttestationVerificationError("attestation proof is unknown or already consumed")
            self._verified.add(signature)
            return VerifiedPreForwardAttestation(
                _VERIFIED_RESULT_TOKEN,
                authority_id=self._authority_id,
                generation=self._generation,
                binding=expected,
                request_ordinal=request_ordinal,
            )

    def revoke(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
            self._generation += 1
            for index in range(len(self._key)):
                self._key[index] = 0
            self._expected = None  # type: ignore[assignment]
            self._issued.clear()
            self._verified.clear()
        with _OWNERS_LOCK:
            _OWNERS.pop(self._capability_id, None)
