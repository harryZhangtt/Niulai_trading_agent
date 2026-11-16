"""Single-writer, single-admission observer; it has no transport capability."""
from __future__ import annotations
from typing import Any, Dict, Mapping
from .contracts import R6ContractError, sha256_bytes, validate_identity

class DuplicateAdmissionCriticalStop(R6ContractError):
    pass

class GatewayObserver:
    def __init__(self) -> None:
        self._admission_count = 0
        self._fingerprint = None
    @property
    def admission_count(self) -> int: return self._admission_count
    def admit(self, request: bytes, identity: Mapping[str, Any]) -> Dict[str, Any]:
        normalized = validate_identity(dict(identity))
        fingerprint = sha256_bytes(request)
        if fingerprint != normalized["request_fingerprint"]: raise R6ContractError("R6_REQUEST_IDENTITY_MISMATCH")
        if self._admission_count:
            raise DuplicateAdmissionCriticalStop("R6_SECOND_ADMISSION_CRITICAL_STOP")
        self._admission_count = 1; self._fingerprint = fingerprint
        return {"schema_version":"gateway-observer-receipt-v1", "identity":dict(normalized), "request_sha256":fingerprint,
                "request_fingerprint":fingerprint, "admission_count":1, "upstream_attempt_count":1,
                "second_admission_rejected":True, "gateway_retries":0, "countable_observation":False}
