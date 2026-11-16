"""Provider-free immutable contracts for retry/unknown campaign review.

This module classifies already-sanitized evidence.  It performs no I/O and grants
no authority to invoke a provider, process, gateway, or runtime.
"""
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping, Optional, Protocol, Tuple, runtime_checkable


class CampaignContractError(ValueError):
    """Stable validation error containing no supplied value."""


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_CAMPAIGNS = frozenset(("R6", "R7", "R8"))
_SLOTS = frozenset(("slot-1", "slot-2"))


def _fail(code: str) -> None:
    raise CampaignContractError(code)


def _identifier(value: Any, code: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _fail(code)
    return value


def _sha(value: Any, code: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(code)
    return value


@dataclass(frozen=True)
class CampaignIdentityV1:
    campaign_id: str
    run_id: str
    job_id: str
    slot_id: str
    attempt_id: str
    operation_id: str
    request_id: str
    prompt_id: str
    gateway_id: str
    process_id: str
    prompt_sha256: str
    source_sha256: str
    config_sha256: str
    version: int = 1

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != 1:
            _fail("IDENTITY_VERSION_INVALID")
        for field in ("campaign_id", "run_id", "job_id", "slot_id", "attempt_id", "operation_id",
                      "request_id", "prompt_id", "gateway_id", "process_id"):
            _identifier(getattr(self, field), "IDENTITY_%s_INVALID" % field.upper())
        if self.campaign_id not in _CAMPAIGNS:
            _fail("IDENTITY_CAMPAIGN_ID_INVALID")
        if self.slot_id not in _SLOTS:
            _fail("IDENTITY_SLOT_ID_INVALID")
        expected_job = "claude-campaign-v1.%s.%s" % (self.campaign_id.lower(), self.slot_id)
        if self.job_id != expected_job:
            _fail("IDENTITY_JOB_ID_MISMATCH")
        for field in ("prompt_sha256", "source_sha256", "config_sha256"):
            _sha(getattr(self, field), "IDENTITY_%s_INVALID" % field.upper())

    def binding(self) -> Tuple[Any, ...]:
        return tuple(getattr(self, field) for field in self.__dataclass_fields__)


class GatewayDisposition(str, Enum):
    PASS_THROUGH = "pass_through"
    REJECTED_BEFORE_FORWARD = "rejected_before_forward"
    CUT = "cut"


class TerminalDisposition(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    ABSENT = "absent"
    CONTRADICTORY = "contradictory"


class Submission(str, Enum):
    NOT_SUBMITTED = "not_submitted"
    POSSIBLY_SUBMITTED = "possibly_submitted"
    DEFINITELY_SUBMITTED = "definitely_submitted"


class Authority(str, Enum):
    SUCCEEDED = "succeeded"
    RETRYABLE = "retryable"
    TERMINAL_FAILED = "terminal_failed"
    UNKNOWN = "unknown"


def compute_evidence_sha256(identity: CampaignIdentityV1, gateway_disposition: Any,
                            terminal_disposition: Any, upstream_forward_count: Any,
                            submission: Any, typed_transient: Any, http_status: Any,
                            retry_after_seconds: Any, code: Any, version: Any = 1) -> str:
    if not isinstance(identity, CampaignIdentityV1):
        _fail("EVIDENCE_IDENTITY_INVALID")
    try:
        gateway = GatewayDisposition(gateway_disposition).value
        terminal = TerminalDisposition(terminal_disposition).value
        submitted = Submission(submission).value
    except (TypeError, ValueError):
        _fail("EVIDENCE_DISPOSITION_INVALID")
    identity_value = {field: getattr(identity, field) for field in identity.__dataclass_fields__}
    value = {"version": version, "identity": identity_value,
             "gateway_disposition": gateway, "terminal_disposition": terminal,
             "upstream_forward_count": upstream_forward_count, "submission": submitted,
             "typed_transient": typed_transient, "http_status": http_status,
             "retry_after_seconds": retry_after_seconds, "code": code}
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()
    except (TypeError, ValueError):
        _fail("EVIDENCE_CANONICALIZATION_INVALID")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class EvidenceV1:
    identity: CampaignIdentityV1
    gateway_disposition: GatewayDisposition
    terminal_disposition: TerminalDisposition
    upstream_forward_count: int
    submission: Submission
    typed_transient: bool
    http_status: Optional[int]
    retry_after_seconds: Optional[float]
    code: str
    evidence_sha256: str
    version: int = 1

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != 1:
            _fail("EVIDENCE_VERSION_INVALID")
        if not isinstance(self.identity, CampaignIdentityV1):
            _fail("EVIDENCE_IDENTITY_INVALID")
        try:
            gateway = GatewayDisposition(self.gateway_disposition)
            terminal = TerminalDisposition(self.terminal_disposition)
            submission = Submission(self.submission)
        except (TypeError, ValueError):
            _fail("EVIDENCE_DISPOSITION_INVALID")
        if type(self.upstream_forward_count) is not int or self.upstream_forward_count not in (0, 1):
            _fail("EVIDENCE_FORWARD_COUNT_INVALID")
        if type(self.typed_transient) is not bool:
            _fail("EVIDENCE_TRANSIENT_INVALID")
        if self.http_status is not None and (type(self.http_status) is not int or not 100 <= self.http_status <= 599):
            _fail("EVIDENCE_HTTP_STATUS_INVALID")
        if self.retry_after_seconds is not None and (type(self.retry_after_seconds) is not int
                or not 1 <= self.retry_after_seconds <= 30 * 86400):
            _fail("EVIDENCE_RETRY_AFTER_INVALID")
        if self.retry_after_seconds is not None and self.http_status is None:
            _fail("EVIDENCE_RETRY_AFTER_WITHOUT_HTTP")
        if type(self.code) is not str or _CODE.fullmatch(self.code) is None:
            _fail("EVIDENCE_CODE_INVALID")
        _sha(self.evidence_sha256, "EVIDENCE_SHA256_INVALID")
        expected_sha256 = compute_evidence_sha256(
            self.identity, gateway, terminal, self.upstream_forward_count,
            submission, self.typed_transient, self.http_status,
            self.retry_after_seconds, self.code, self.version)
        if self.evidence_sha256 != expected_sha256:
            _fail("EVIDENCE_SHA256_MISMATCH")
        object.__setattr__(self, "gateway_disposition", gateway)
        object.__setattr__(self, "terminal_disposition", terminal)
        object.__setattr__(self, "submission", submission)

    def validate_binding(self, expected: CampaignIdentityV1) -> None:
        if not isinstance(expected, CampaignIdentityV1) or self.identity.binding() != expected.binding():
            _fail("EVIDENCE_IDENTITY_BINDING_MISMATCH")


@runtime_checkable
class PreForwardProofVerifier(Protocol):
    @property
    def verifier_identity(self) -> str:
        ...

    @property
    def generation_id(self) -> str:
        ...

    @property
    def anchor_id(self) -> str:
        ...

    @property
    def active(self) -> bool:
        ...

    def seal_initial_state(self, state_body: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def verify_state(self, state_body: Mapping[str, Any],
                     state_attestation: Mapping[str, Any]) -> None:
        ...

    def verify_state_and_seal_next(self, current_body: Mapping[str, Any],
                                   current_attestation: Mapping[str, Any],
                                   next_body: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def verify_and_consume(self, proof_mapping: Any,
                           expected_bindings: Mapping[str, Any],
                           current_body: Mapping[str, Any],
                           current_attestation: Mapping[str, Any],
                           next_state_builder: Any) -> Any:
        ...


def classify_authority(evidence: EvidenceV1) -> Authority:
    """Apply the closed authority table; every contradiction fails to unknown."""
    if not isinstance(evidence, EvidenceV1):
        _fail("EVIDENCE_INVALID")
    gateway = evidence.gateway_disposition
    terminal = evidence.terminal_disposition
    forwarded = evidence.upstream_forward_count
    submission = evidence.submission
    transient = evidence.typed_transient

    if (gateway is GatewayDisposition.PASS_THROUGH and forwarded == 1
            and submission is Submission.DEFINITELY_SUBMITTED
            and terminal is TerminalDisposition.SUCCESS and not transient):
        return Authority.SUCCEEDED
    if gateway is GatewayDisposition.CUT and forwarded == 1:
        return Authority.UNKNOWN
    if terminal is TerminalDisposition.CONTRADICTORY:
        return Authority.UNKNOWN
    # Explicit terminal failure is authoritative only when the gateway evidence
    # is coherent and the operation was either rejected or passed through.
    if terminal is TerminalDisposition.FAILURE and not transient and (
            (gateway is GatewayDisposition.REJECTED_BEFORE_FORWARD and forwarded == 0)
            or (gateway is GatewayDisposition.PASS_THROUGH and forwarded == 1)):
        return Authority.TERMINAL_FAILED
    return Authority.UNKNOWN


def evidence_from_mapping(value: Mapping[str, Any]) -> EvidenceV1:
    """Parse one closed mapping; unknown, missing, or duplicate-decoded keys fail."""
    if type(value) is not dict or set(value) != {
            "version", "identity", "gateway_disposition", "terminal_disposition",
            "upstream_forward_count", "submission", "typed_transient", "http_status",
            "retry_after_seconds", "code", "evidence_sha256"}:
        _fail("EVIDENCE_KEYS_INVALID")
    identity = value["identity"]
    identity_keys = {
        "version", "campaign_id", "run_id", "job_id", "slot_id", "attempt_id", "operation_id",
        "request_id", "prompt_id", "gateway_id", "process_id", "prompt_sha256", "source_sha256",
        "config_sha256"}
    if type(identity) is not dict or set(identity) != identity_keys:
        _fail("IDENTITY_KEYS_INVALID")
    return EvidenceV1(identity=CampaignIdentityV1(**identity),
                      gateway_disposition=value["gateway_disposition"],
                      terminal_disposition=value["terminal_disposition"],
                      upstream_forward_count=value["upstream_forward_count"],
                      submission=value["submission"], typed_transient=value["typed_transient"],
                      http_status=value["http_status"], retry_after_seconds=value["retry_after_seconds"],
                      code=value["code"],
                      evidence_sha256=value["evidence_sha256"], version=value["version"])


def evidence_from_json_bytes(data: bytes) -> EvidenceV1:
    """Canonical lexical ingestion before runtime contract construction.

    JSON Schema numeric equality remains standards-compliant; this boundary
    deliberately preserves JSON number spelling as Python int/float and then
    applies the stricter runtime field types.
    """
    if type(data) is not bytes or not data or len(data) > 64 * 1024:
        _fail("EVIDENCE_JSON_INVALID")
    def pairs(items: Any) -> Mapping[str, Any]:
        value = {}
        for key, item in items:
            if key in value:
                _fail("EVIDENCE_JSON_DUPLICATE_KEY")
            value[key] = item
        return value
    try:
        value = json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except CampaignContractError:
        raise
    except Exception:
        _fail("EVIDENCE_JSON_INVALID")
    return evidence_from_mapping(value)
