"""Provider-neutral, source-only outcome and replay contracts.

These types classify evidence.  A ``retryable`` result is only a scheduling
candidate; it never grants authority to repeat an external effect.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping, Protocol, runtime_checkable


class ContractError(ValueError):
    """A stable contract validation error (never provider error text)."""


class Provider(str, Enum):
    CODEX_CLI = "codex_cli"
    CLAUDE_HOST = "claude_host"


class Phase(str, Enum):
    NOT_STARTED = "not_started"
    CONNECTING = "connecting"
    SUBMITTED = "submitted"
    STREAMING = "streaming"
    TERMINAL = "terminal"


class Submission(str, Enum):
    NOT_SUBMITTED = "not_submitted"
    DEFINITELY_SUBMITTED = "definitely_submitted"
    POSSIBLY_SUBMITTED = "possibly_submitted"


class TerminalProof(str, Enum):
    VERIFIED = "verified"
    ABSENT = "absent"
    CONTRADICTORY = "contradictory"


class ResultStatus(str, Enum):
    SUCCEEDED = "succeeded"
    RETRYABLE = "retryable"
    FAILED = "failed"
    UNKNOWN = "unknown"


class FailureKind(str, Enum):
    NONE = "none"
    TIMEOUT = "timeout"
    CONNECTION_RESET = "connection_reset"
    CONNECTION = "connection"
    PARTIAL_RESPONSE = "partial_response"
    MISSING_TERMINAL = "missing_terminal"
    HTTP = "http"
    QUOTA_EXHAUSTED = "quota_exhausted"
    AUTH = "auth"
    CONFIG = "config"
    MODEL = "model"
    POLICY = "policy"
    LOCAL_CONFIG = "local_config"
    PROVIDER = "provider"
    UNKNOWN = "unknown"


class ReplayEffect(str, Enum):
    NONE = "none"
    IDEMPOTENT = "idempotent"
    RECONCILE_BEFORE_REPLAY = "reconcile_before_replay"


_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_OPERATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_SLOT_SCOPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_EVIDENCE_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SECRET_KEY = re.compile(
    r"(?:^|[_-])(authorization|cookie|credential|password|passwd|secret|token|api[_-]?key|private[_-]?key)(?:$|[_-])",
    re.IGNORECASE,
)
_UNSAFE_TEXT_KEY = re.compile(
    r"(?:^|[_-])(body|content|error|exception|message|prompt|raw|stderr|stdout|text|trace)(?:$|[_-])",
    re.IGNORECASE,
)
_MAX_RECEIPT_BYTES = 16 * 1024
_MAX_RECEIPT_DEPTH = 6
_MAX_RECEIPT_ITEMS = 256
_MAX_STRING = 2048


def _fail(code: str) -> None:
    raise ContractError(code)


def _enum(enum_type: type[Enum], value: Any, code: str) -> Any:
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        _fail(code)


def _aware(value: datetime | None, code: str) -> datetime | None:
    if value is not None and (not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None):
        _fail(code)
    return value


def _freeze_receipt(value: Any, depth: int = 0, count: list[int] | None = None,
                    active: set[int] | None = None) -> Any:
    if count is None:
        count = [0]
    if active is None:
        active = set()
    count[0] += 1
    if count[0] > _MAX_RECEIPT_ITEMS or depth > _MAX_RECEIPT_DEPTH:
        _fail("PROVIDER_RECEIPT_BOUNDS")
    if value is None or type(value) is bool or type(value) is int:
        return value
    if type(value) is float:
        if value != value or value in (float("inf"), float("-inf")):
            _fail("PROVIDER_RECEIPT_VALUE_INVALID")
        return value
    if type(value) is str:
        if len(value) > _MAX_STRING:
            _fail("PROVIDER_RECEIPT_BOUNDS")
        return value
    if type(value) in (list, tuple) or isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            _fail("PROVIDER_RECEIPT_CYCLE")
        active.add(identity)
        try:
            if type(value) in (list, tuple):
                return tuple(_freeze_receipt(item, depth + 1, count, active) for item in value)
            copied: dict[str, Any] = {}
            for key, item in value.items():
                if type(key) is not str or not key or len(key) > 128:
                    _fail("PROVIDER_RECEIPT_KEY_INVALID")
                if _SECRET_KEY.search(key):
                    _fail("PROVIDER_RECEIPT_SECRET_KEY")
                if _UNSAFE_TEXT_KEY.search(key):
                    _fail("PROVIDER_RECEIPT_UNSAFE_TEXT_KEY")
                copied[key] = _freeze_receipt(item, depth + 1, count, active)
            return MappingProxyType(copied)
        finally:
            active.remove(identity)
    _fail("PROVIDER_RECEIPT_VALUE_INVALID")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True)
class ProviderResultV1:
    provider: Provider | str
    operation_id: str
    phase: Phase | str
    submission: Submission | str
    terminal_proof: TerminalProof | str
    status: ResultStatus | str
    code: str
    failure_kind: FailureKind | str = FailureKind.NONE
    http_status: int | None = None
    provider_should_retry: bool | None = None
    retry_after_at: datetime | None = None
    retry_after_source: str | None = None
    receipt: Mapping[str, Any] | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != 1:
            _fail("PROVIDER_RESULT_VERSION_INVALID")
        provider = _enum(Provider, self.provider, "PROVIDER_INVALID")
        phase = _enum(Phase, self.phase, "PROVIDER_PHASE_INVALID")
        submission = _enum(Submission, self.submission, "PROVIDER_SUBMISSION_INVALID")
        proof = _enum(TerminalProof, self.terminal_proof, "PROVIDER_TERMINAL_PROOF_INVALID")
        status = _enum(ResultStatus, self.status, "PROVIDER_STATUS_INVALID")
        failure = _enum(FailureKind, self.failure_kind, "PROVIDER_FAILURE_KIND_INVALID")
        if type(self.operation_id) is not str or not _OPERATION.fullmatch(self.operation_id):
            _fail("PROVIDER_OPERATION_ID_INVALID")
        if type(self.code) is not str or not _CODE.fullmatch(self.code):
            _fail("PROVIDER_CODE_INVALID")
        if self.http_status is not None and (type(self.http_status) is not int or not 100 <= self.http_status <= 599):
            _fail("PROVIDER_HTTP_STATUS_INVALID")
        if self.provider_should_retry is not None and type(self.provider_should_retry) is not bool:
            _fail("PROVIDER_SHOULD_RETRY_INVALID")
        _aware(self.retry_after_at, "PROVIDER_RETRY_AFTER_INVALID")
        if (self.retry_after_at is None) != (self.retry_after_source is None):
            _fail("PROVIDER_RETRY_AFTER_SOURCE_INVALID")
        if self.retry_after_source not in (None, "retry-after-ms", "retry-after-seconds", "http-date", "typed-timestamp"):
            _fail("PROVIDER_RETRY_AFTER_SOURCE_INVALID")
        frozen = MappingProxyType({}) if self.receipt is None else _freeze_receipt(self.receipt)
        if not isinstance(frozen, Mapping):
            _fail("PROVIDER_RECEIPT_INVALID")
        try:
            size = len(json.dumps(_plain(frozen), sort_keys=True, separators=(",", ":")).encode())
        except (TypeError, ValueError):
            _fail("PROVIDER_RECEIPT_VALUE_INVALID")
        if size > _MAX_RECEIPT_BYTES:
            _fail("PROVIDER_RECEIPT_BOUNDS")

        permanent = {FailureKind.QUOTA_EXHAUSTED, FailureKind.AUTH, FailureKind.CONFIG,
                     FailureKind.MODEL, FailureKind.POLICY, FailureKind.LOCAL_CONFIG}
        unsafe_after_submit = {FailureKind.TIMEOUT, FailureKind.CONNECTION_RESET, FailureKind.PARTIAL_RESPONSE,
                               FailureKind.MISSING_TERMINAL}
        if phase in (Phase.NOT_STARTED, Phase.CONNECTING) and submission is not Submission.NOT_SUBMITTED:
            _fail("PROVIDER_PHASE_SUBMISSION_CONFLICT")
        if phase in (Phase.SUBMITTED, Phase.STREAMING) and submission is Submission.NOT_SUBMITTED:
            _fail("PROVIDER_PHASE_SUBMISSION_CONFLICT")
        if proof is TerminalProof.VERIFIED and phase is not Phase.TERMINAL:
            _fail("PROVIDER_TERMINAL_PROOF_CONFLICT")
        if phase is not Phase.TERMINAL and proof is not TerminalProof.ABSENT:
            _fail("PROVIDER_TERMINAL_PROOF_CONFLICT")
        if status is ResultStatus.SUCCEEDED and not (phase is Phase.TERMINAL and proof is TerminalProof.VERIFIED
                                                     and failure is FailureKind.NONE):
            _fail("PROVIDER_SUCCESS_UNVERIFIED")
        if status is not ResultStatus.SUCCEEDED and failure is FailureKind.NONE:
            _fail("PROVIDER_FAILURE_KIND_REQUIRED")
        if status is ResultStatus.RETRYABLE:
            if submission is not Submission.NOT_SUBMITTED or phase not in (Phase.NOT_STARTED, Phase.CONNECTING):
                _fail("PROVIDER_RETRY_UNSAFE")
            if failure in permanent or self.provider_should_retry is False:
                _fail("PROVIDER_RETRY_CONTRADICTED")
        if failure in permanent and status is not ResultStatus.FAILED:
            _fail("PROVIDER_PERMANENT_FAILURE_STATUS")
        if (submission is not Submission.NOT_SUBMITTED or phase in (Phase.SUBMITTED, Phase.STREAMING)) and failure in unsafe_after_submit:
            if status is not ResultStatus.UNKNOWN:
                _fail("PROVIDER_OUTCOME_MUST_BE_UNKNOWN")
        if proof is TerminalProof.CONTRADICTORY and status is not ResultStatus.UNKNOWN:
            _fail("PROVIDER_CONTRADICTORY_PROOF")
        if failure is FailureKind.MISSING_TERMINAL and status is not ResultStatus.UNKNOWN:
            _fail("PROVIDER_OUTCOME_MUST_BE_UNKNOWN")
        if self.http_status is not None and failure is not FailureKind.HTTP:
            _fail("PROVIDER_HTTP_KIND_REQUIRED")

        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "submission", submission)
        object.__setattr__(self, "terminal_proof", proof)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "failure_kind", failure)
        object.__setattr__(self, "receipt", frozen)

    def to_mapping(self) -> Mapping[str, Any]:
        """Return a detached immutable mapping used by durable proof hashing."""
        retry_after = (self.retry_after_at.astimezone(timezone.utc).isoformat()
                       if self.retry_after_at is not None else None)
        return MappingProxyType({
            "version": self.version,
            "provider": self.provider.value,
            "operation_id": self.operation_id,
            "phase": self.phase.value,
            "submission": self.submission.value,
            "terminal_proof": self.terminal_proof.value,
            "status": self.status.value,
            "code": self.code,
            "failure_kind": self.failure_kind.value,
            "http_status": self.http_status,
            "provider_should_retry": self.provider_should_retry,
            "retry_after_at": retry_after,
            "retry_after_source": self.retry_after_source,
            "receipt": self.receipt,
        })

    @property
    def canonical_sha256(self) -> str:
        payload = json.dumps(_plain(self.to_mapping()), sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()
        return hashlib.sha256(payload).hexdigest()

    @property
    def typed_http_retry_candidate(self) -> bool:
        return self.http_status in ({408, 409, 429, 529} | set(range(500, 600)))

    @property
    def safe_retry_candidate(self) -> bool:
        return self.status is ResultStatus.RETRYABLE and self.submission is Submission.NOT_SUBMITTED


@dataclass(frozen=True)
class ReplayContractV1:
    effect: ReplayEffect | str
    automatic_phases: tuple[Phase | str, ...]
    slot_operation_scope: str
    reconciliation_adapter: str | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != 1:
            _fail("REPLAY_VERSION_INVALID")
        effect = _enum(ReplayEffect, self.effect, "REPLAY_EFFECT_INVALID")
        if type(self.automatic_phases) is not tuple or not self.automatic_phases:
            _fail("REPLAY_PHASES_INVALID")
        phases = tuple(_enum(Phase, phase, "REPLAY_PHASES_INVALID") for phase in self.automatic_phases)
        if len(set(phases)) != len(phases) or any(phase in (Phase.SUBMITTED, Phase.STREAMING, Phase.TERMINAL) for phase in phases):
            _fail("REPLAY_PHASES_INVALID")
        if type(self.slot_operation_scope) is not str or not _SLOT_SCOPE.fullmatch(self.slot_operation_scope):
            _fail("REPLAY_SCOPE_INVALID")
        if self.reconciliation_adapter is not None and (type(self.reconciliation_adapter) is not str or
                                                         not _OPERATION.fullmatch(self.reconciliation_adapter)):
            _fail("REPLAY_ADAPTER_INVALID")
        if effect is ReplayEffect.RECONCILE_BEFORE_REPLAY and self.reconciliation_adapter is None:
            _fail("REPLAY_ADAPTER_REQUIRED")
        if effect is not ReplayEffect.RECONCILE_BEFORE_REPLAY and self.reconciliation_adapter is not None:
            _fail("REPLAY_ADAPTER_UNEXPECTED")
        object.__setattr__(self, "effect", effect)
        object.__setattr__(self, "automatic_phases", phases)


@dataclass(frozen=True)
class ReconciliationProofV1:
    attempt_id: str
    operation_id: str
    slot_operation_scope: str
    provider_result_sha256: str
    outcome: str
    evidence_sha256: str
    recorded_at: datetime
    version: int = 1

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != 1:
            _fail("RECONCILIATION_PROOF_VERSION_INVALID")
        if type(self.attempt_id) is not str or not _OPERATION.fullmatch(self.attempt_id):
            _fail("RECONCILIATION_PROOF_ATTEMPT_INVALID")
        if type(self.operation_id) is not str or not _OPERATION.fullmatch(self.operation_id):
            _fail("RECONCILIATION_PROOF_OPERATION_INVALID")
        if type(self.slot_operation_scope) is not str or not _SLOT_SCOPE.fullmatch(self.slot_operation_scope):
            _fail("RECONCILIATION_PROOF_SCOPE_INVALID")
        if type(self.provider_result_sha256) is not str or not _EVIDENCE_SHA256.fullmatch(self.provider_result_sha256):
            _fail("RECONCILIATION_PROOF_RESULT_INVALID")
        if type(self.outcome) is not str or self.outcome != "absent":
            _fail("RECONCILIATION_PROOF_OUTCOME_INVALID")
        if type(self.evidence_sha256) is not str or not _EVIDENCE_SHA256.fullmatch(self.evidence_sha256):
            _fail("RECONCILIATION_PROOF_EVIDENCE_INVALID")
        _aware(self.recorded_at, "RECONCILIATION_PROOF_RECORDED_AT_INVALID")

    def to_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType({
            "version": self.version,
            "attempt_id": self.attempt_id,
            "operation_id": self.operation_id,
            "slot_operation_scope": self.slot_operation_scope,
            "provider_result_sha256": self.provider_result_sha256,
            "outcome": self.outcome,
            "evidence_sha256": self.evidence_sha256,
            "recorded_at": self.recorded_at.astimezone(timezone.utc).isoformat(),
        })

    @property
    def canonical_sha256(self) -> str:
        payload = json.dumps(dict(self.to_mapping()), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()


@runtime_checkable
class ReconciliationAdapter(Protocol):
    """An owning component can prove whether an operation already took effect."""

    def reconcile(self, *, attempt_id: str, operation_id: str,
                  slot_operation_scope: str) -> ReconciliationProofV1:
        ...


def validate_replay(contract: ReplayContractV1, result: ProviderResultV1, *,
                    reconciliation_proof: ReconciliationProofV1 | None = None,
                    expected_attempt_id: str | None = None,
                    expected_provider_result_sha256: str | None = None,
                    expected_evidence_sha256: str | None = None,
                    expected_proof_sha256: str | None = None) -> bool:
    """Pure semantic validation, never replay authority by itself.

    A future Engine durable-store method must load the immutable proof and all four
    expected bindings from its database before calling this helper.  Values supplied
    ad hoc by a caller do not establish storage provenance or authority.
    """
    if not isinstance(contract, ReplayContractV1) or not isinstance(result, ProviderResultV1):
        _fail("REPLAY_INPUT_INVALID")
    if contract.effect in (ReplayEffect.NONE, ReplayEffect.IDEMPOTENT):
        return result.safe_retry_candidate and result.phase in contract.automatic_phases
    if not isinstance(reconciliation_proof, ReconciliationProofV1):
        return False
    expected = (expected_attempt_id, expected_provider_result_sha256,
                expected_evidence_sha256, expected_proof_sha256)
    if any(type(value) is not str for value in expected):
        return False
    post_submit_unknown = (result.status is ResultStatus.UNKNOWN
                           and result.submission in (Submission.DEFINITELY_SUBMITTED,
                                                     Submission.POSSIBLY_SUBMITTED)
                           and result.phase in (Phase.SUBMITTED, Phase.STREAMING, Phase.TERMINAL))
    return (post_submit_unknown
            and reconciliation_proof.attempt_id == expected_attempt_id
            and reconciliation_proof.operation_id == result.operation_id
            and reconciliation_proof.slot_operation_scope == contract.slot_operation_scope
            and reconciliation_proof.provider_result_sha256 == result.canonical_sha256
            and reconciliation_proof.provider_result_sha256 == expected_provider_result_sha256
            and reconciliation_proof.evidence_sha256 == expected_evidence_sha256
            and reconciliation_proof.canonical_sha256 == expected_proof_sha256)


def from_legacy_result(value: Mapping[str, Any], *, provider: Provider | str, operation_id: str) -> ProviderResultV1:
    """Conservatively detach legacy ``{status, code, receipt}`` dictionaries."""
    if type(value) is not dict or set(value) - {"status", "code", "receipt"}:
        _fail("LEGACY_PROVIDER_RESULT_INVALID")
    status = value.get("status")
    code = value.get("code")
    receipt = value.get("receipt", {})
    if status == "succeeded":
        return ProviderResultV1(provider, operation_id, Phase.TERMINAL, Submission.DEFINITELY_SUBMITTED,
                                TerminalProof.VERIFIED, ResultStatus.SUCCEEDED, code, receipt=receipt)
    if status == "failed":
        return ProviderResultV1(provider, operation_id, Phase.TERMINAL, Submission.POSSIBLY_SUBMITTED,
                                TerminalProof.VERIFIED, ResultStatus.FAILED, code,
                                failure_kind=FailureKind.PROVIDER, receipt=receipt)
    # Legacy retryable/unknown values carry no trustworthy pre-submission proof.
    if status in ("retryable", "unknown"):
        return ProviderResultV1(provider, operation_id, Phase.TERMINAL, Submission.POSSIBLY_SUBMITTED,
                                TerminalProof.ABSENT, ResultStatus.UNKNOWN, code,
                                failure_kind=FailureKind.UNKNOWN, receipt=receipt)
    _fail("LEGACY_PROVIDER_STATUS_INVALID")
