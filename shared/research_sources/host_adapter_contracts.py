"""Closed provider-host configuration contracts for acquisition execution.

The contracts contain references and fingerprints, never credential values. They do
not activate an MCP server, inspect an auth store, invoke a provider, or create a
runtime directory. Call ``validate_execution_pair`` before sealing a Codex/Claude
comparison so mutable state and credential ownership remain isolated.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from typing import Any, Iterable

from shared.research_sources.acquisition_contracts import FailureClass, classify_failure


VERSION = "host-adapter-contracts-1"
OPERATIONAL_RECEIPT_VERSION = "host-operational-receipts-1"
NON_CRYPTO_LIMITATION = (
    "Operational host evidence is locally retained and does not resist malicious "
    "same-user file forgery."
)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SHA256 = re.compile(r"[a-f0-9]{64}")
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~-]+"),
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----"),
    re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|client[_-]?secret)\s*[=:]"),
)


class HostContractError(ValueError):
    """A stable, non-secret host configuration error."""


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise HostContractError(code)


def _identifier(value: Any, code: str) -> str:
    _require(isinstance(value, str) and _ID.fullmatch(value) is not None, code)
    _reject_secret(value, code)
    return value


def _hash(value: Any, code: str) -> str:
    _require(isinstance(value, str) and _SHA256.fullmatch(value) is not None, code)
    return value


def _aware_time(value: Any, code: str) -> str:
    _require(isinstance(value, str), code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HostContractError(code) from None
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, code)
    return value


def _limitations(values: Any, code: str) -> tuple[str, ...]:
    _require(type(values) is tuple and bool(values)
             and all(isinstance(value, str) and value for value in values), code)
    _require(NON_CRYPTO_LIMITATION in values, code)
    _reject_secret(values, code)
    return values


def _reject_secret(value: Any, code: str = "HOST_CONFIG_SECRET_REJECTED") -> None:
    if isinstance(value, str):
        _require(not any(pattern.search(value) for pattern in _SECRET_PATTERNS), code)
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_secret(str(key), code)
            _reject_secret(item, code)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _reject_secret(item, code)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise HostContractError("HOST_CONFIG_JSON_INVALID") from error


class AdapterId(str, Enum):
    CODEX_NATIVE_WEB = "codex_native_web"
    CLAUDE_CODE_WEB = "claude_code_web"


class CredentialSource(str, Enum):
    CODEX_PROFILE = "codex_profile"
    CLAUDE_PROFILE = "claude_profile"


class Operation(str, Enum):
    SEARCH = "search"
    OPEN = "open"
    FIND = "find"


class Capability(str, Enum):
    SEARCH = "search"
    OPEN = "open"
    FIND = "find"
    RAW_BODY_FIDELITY = "raw_body_fidelity"
    RENDERED_EXTRACT = "rendered_extract"
    CITATIONS = "citations"


class MCPTransport(str, Enum):
    STDIO = "stdio"
    HTTP = "http"


@dataclass(frozen=True)
class WorkspaceFileRef:
    path: str
    sha256: str

    def __post_init__(self) -> None:
        _require(isinstance(self.path, str) and self.path and not Path(self.path).is_absolute(),
                 "HOST_FILE_REF_PATH")
        _reject_secret(self.path)
        _hash(self.sha256, "HOST_FILE_REF_HASH")

    def verify(self, workspace_root: Path, code: str = "HOST_FILE_REF_INVALID") -> Path:
        root = Path(workspace_root).resolve(strict=True)
        relative = Path(self.path)
        _require(".." not in relative.parts and relative.parts, code)
        candidate = root / relative
        current = root
        for part in relative.parts:
            current = current / part
            _require(not current.is_symlink(), code)
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError):
            raise HostContractError(code) from None
        _require(resolved.is_file(), code)
        _require(hashlib.sha256(resolved.read_bytes()).hexdigest() == self.sha256, code)
        return resolved


@dataclass(frozen=True)
class CredentialRef:
    owner_ref: str
    source: CredentialSource
    profile_ref: str
    fingerprint_sha256: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.owner_ref, "HOST_CREDENTIAL_OWNER")
        _require(isinstance(self.source, CredentialSource), "HOST_CREDENTIAL_SOURCE")
        _identifier(self.profile_ref, "HOST_CREDENTIAL_PROFILE")
        if self.fingerprint_sha256 is not None:
            _hash(self.fingerprint_sha256, "HOST_CREDENTIAL_FINGERPRINT")
        _reject_secret(asdict(self))

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.owner_ref, self.source.value, self.profile_ref

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "owner_ref": self.owner_ref,
            "source": self.source.value,
            "profile_ref": self.profile_ref,
            "fingerprint_sha256": self.fingerprint_sha256,
            "credential_value_present": False,
        }


class OperationalTrustPolicy(str, Enum):
    OPERATIONAL_HOST_EVIDENCE = "operational_host_evidence"


class OperationalEvidenceSource(str, Enum):
    HOST_RETURNED = "host_returned_operational"
    SYNTHETIC = "synthetic_fixture"


class OperationalTerminalStatus(str, Enum):
    CAPTURED = "captured"
    FAILED = "failed"
    UNKNOWN = "unknown"


class CredentialReadinessStatus(str, Enum):
    READY = "ready"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class HostInvocationReceipt:
    adapter_id: AdapterId
    configured_backend: str
    observed_tool_identity: str
    host_session_id: str
    operational_event_id: str | None
    event_id_unavailable_reason: str | None
    dispatch_id: str
    acquisition_arguments_sha256: str
    tool_input_sha256: str
    result_sha256: str
    started_at: str
    finished_at: str
    adapter_dispatch_count: int
    tool_invocation_count: int
    underlying_request_observation: str
    underlying_http_request_count: int | None
    host_retry_count: int | None
    terminal_status: OperationalTerminalStatus
    terminal_code: str | None
    source: OperationalEvidenceSource
    trust_policy: OperationalTrustPolicy
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        _require(isinstance(self.adapter_id, AdapterId), "HOST_INVOCATION_ADAPTER")
        for value, code in (
                (self.configured_backend, "HOST_INVOCATION_BACKEND"),
                (self.observed_tool_identity, "HOST_INVOCATION_TOOL"),
                (self.host_session_id, "HOST_INVOCATION_SESSION"),
                (self.dispatch_id, "HOST_INVOCATION_DISPATCH")):
            _identifier(value, code)
        if self.operational_event_id is None:
            _require(isinstance(self.event_id_unavailable_reason, str)
                     and self.event_id_unavailable_reason.strip(),
                     "HOST_INVOCATION_EVENT_ID")
            _reject_secret(self.event_id_unavailable_reason, "HOST_INVOCATION_EVENT_ID")
        else:
            _identifier(self.operational_event_id, "HOST_INVOCATION_EVENT_ID")
            _require(self.event_id_unavailable_reason is None, "HOST_INVOCATION_EVENT_ID")
        for value in (self.acquisition_arguments_sha256, self.tool_input_sha256,
                      self.result_sha256):
            _hash(value, "HOST_INVOCATION_HASH")
        _aware_time(self.started_at, "HOST_INVOCATION_TIME")
        _aware_time(self.finished_at, "HOST_INVOCATION_TIME")
        _require(datetime.fromisoformat(self.finished_at.replace("Z", "+00:00"))
                 >= datetime.fromisoformat(self.started_at.replace("Z", "+00:00")),
                 "HOST_INVOCATION_TIME")
        _require(self.adapter_dispatch_count == 1 and self.tool_invocation_count == 1,
                 "HOST_INVOCATION_CARDINALITY")
        _require(self.underlying_request_observation in {"reported", "unknown"},
                 "HOST_INVOCATION_UNDERLYING_REQUESTS")
        if self.underlying_request_observation == "reported":
            _require(type(self.underlying_http_request_count) is int
                     and self.underlying_http_request_count >= 0
                     and type(self.host_retry_count) is int
                     and self.host_retry_count >= 0,
                     "HOST_INVOCATION_UNDERLYING_REQUESTS")
        else:
            _require(self.underlying_http_request_count is None
                     and self.host_retry_count is None,
                     "HOST_INVOCATION_UNDERLYING_REQUESTS")
        if self.terminal_status is OperationalTerminalStatus.CAPTURED:
            _require(self.terminal_code is None, "HOST_INVOCATION_STATUS_CODE")
        else:
            _require(isinstance(self.terminal_code, str), "HOST_INVOCATION_STATUS_CODE")
            try:
                classification = classify_failure(self.terminal_code)
            except Exception:
                raise HostContractError("HOST_INVOCATION_STATUS_CODE") from None
            unknown_class = classification.failure_class in {
                FailureClass.UNKNOWN_OUTCOME,
                FailureClass.DEADLINE_AFTER_POSSIBLE_DISPATCH,
            }
            _require((self.terminal_status is OperationalTerminalStatus.UNKNOWN)
                     == unknown_class, "HOST_INVOCATION_STATUS_CODE")
        _require(isinstance(self.terminal_status, OperationalTerminalStatus)
                 and isinstance(self.source, OperationalEvidenceSource)
                 and self.trust_policy is OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
                 "HOST_INVOCATION_STATUS")
        _limitations(self.limitations, "HOST_INVOCATION_LIMITATIONS")

    @property
    def live_acceptance_eligible(self) -> bool:
        return self.source is OperationalEvidenceSource.HOST_RETURNED

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": OPERATIONAL_RECEIPT_VERSION,
            "adapter_id": self.adapter_id.value,
            "configured_backend": self.configured_backend,
            "observed_tool_identity": self.observed_tool_identity,
            "host_session_id": self.host_session_id,
            "operational_event_id": self.operational_event_id,
            "event_id_unavailable_reason": self.event_id_unavailable_reason,
            "dispatch_id": self.dispatch_id,
            "acquisition_arguments_sha256": self.acquisition_arguments_sha256,
            "tool_input_sha256": self.tool_input_sha256,
            "result_sha256": self.result_sha256,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "adapter_dispatch_count": self.adapter_dispatch_count,
            "tool_invocation_count": self.tool_invocation_count,
            "underlying_request_observation": self.underlying_request_observation,
            "underlying_http_request_count": self.underlying_http_request_count,
            "host_retry_count": self.host_retry_count,
            "terminal_status": self.terminal_status.value,
            "terminal_code": self.terminal_code,
            "source": self.source.value,
            "trust_policy": self.trust_policy.value,
            "limitations": list(self.limitations),
            "cryptographic_remote_attestation": False,
            "live_acceptance_eligible": self.live_acceptance_eligible,
        }

    @classmethod
    def from_public_dict(cls, value: Any) -> "HostInvocationReceipt":
        _require(isinstance(value, dict)
                 and value.get("version") == OPERATIONAL_RECEIPT_VERSION,
                 "HOST_INVOCATION_RECEIPT")
        try:
            return cls(
                adapter_id=AdapterId(value["adapter_id"]),
                configured_backend=value["configured_backend"],
                observed_tool_identity=value["observed_tool_identity"],
                host_session_id=value["host_session_id"],
                operational_event_id=value.get("operational_event_id"),
                event_id_unavailable_reason=value.get("event_id_unavailable_reason"),
                dispatch_id=value["dispatch_id"],
                acquisition_arguments_sha256=value["acquisition_arguments_sha256"],
                tool_input_sha256=value["tool_input_sha256"],
                result_sha256=value["result_sha256"],
                started_at=value["started_at"],
                finished_at=value["finished_at"],
                adapter_dispatch_count=value["adapter_dispatch_count"],
                tool_invocation_count=value["tool_invocation_count"],
                underlying_request_observation=value["underlying_request_observation"],
                underlying_http_request_count=value.get("underlying_http_request_count"),
                host_retry_count=value.get("host_retry_count"),
                terminal_status=OperationalTerminalStatus(value["terminal_status"]),
                terminal_code=value.get("terminal_code"),
                source=OperationalEvidenceSource(value["source"]),
                trust_policy=OperationalTrustPolicy(value["trust_policy"]),
                limitations=tuple(value["limitations"]),
            )
        except (KeyError, TypeError, ValueError, HostContractError) as error:
            raise HostContractError("HOST_INVOCATION_RECEIPT") from error


@dataclass(frozen=True)
class CredentialReadinessReceipt:
    adapter_id: AdapterId
    owner_ref: str
    profile_ref: str
    profile_fingerprint_sha256: str | None
    host_session_id: str
    capability_observed: str
    checked_at: str
    status: CredentialReadinessStatus
    source: OperationalEvidenceSource
    trust_policy: OperationalTrustPolicy
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        _require(isinstance(self.adapter_id, AdapterId), "HOST_CREDENTIAL_RECEIPT")
        for value in (self.owner_ref, self.profile_ref, self.host_session_id,
                      self.capability_observed):
            _identifier(value, "HOST_CREDENTIAL_RECEIPT")
        if self.profile_fingerprint_sha256 is not None:
            _hash(self.profile_fingerprint_sha256, "HOST_CREDENTIAL_RECEIPT")
        _aware_time(self.checked_at, "HOST_CREDENTIAL_RECEIPT_TIME")
        _require(isinstance(self.status, CredentialReadinessStatus)
                 and isinstance(self.source, OperationalEvidenceSource)
                 and self.trust_policy is OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
                 "HOST_CREDENTIAL_RECEIPT")
        _limitations(self.limitations, "HOST_CREDENTIAL_RECEIPT")

    @property
    def live_acceptance_eligible(self) -> bool:
        return (self.status is CredentialReadinessStatus.READY
                and self.source is OperationalEvidenceSource.HOST_RETURNED)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": OPERATIONAL_RECEIPT_VERSION,
            "adapter_id": self.adapter_id.value,
            "owner_ref": self.owner_ref,
            "profile_ref": self.profile_ref,
            "profile_fingerprint_sha256": self.profile_fingerprint_sha256,
            "host_session_id": self.host_session_id,
            "capability_observed": self.capability_observed,
            "checked_at": self.checked_at,
            "status": self.status.value,
            "source": self.source.value,
            "trust_policy": self.trust_policy.value,
            "limitations": list(self.limitations),
            "credential_values_present": False,
            "cryptographic_remote_attestation": False,
            "live_acceptance_eligible": self.live_acceptance_eligible,
        }

    @classmethod
    def from_public_dict(cls, value: Any) -> "CredentialReadinessReceipt":
        _require(isinstance(value, dict)
                 and value.get("version") == OPERATIONAL_RECEIPT_VERSION,
                 "HOST_CREDENTIAL_RECEIPT")
        try:
            return cls(
                adapter_id=AdapterId(value["adapter_id"]),
                owner_ref=value["owner_ref"], profile_ref=value["profile_ref"],
                profile_fingerprint_sha256=value.get("profile_fingerprint_sha256"),
                host_session_id=value["host_session_id"],
                capability_observed=value["capability_observed"],
                checked_at=value["checked_at"],
                status=CredentialReadinessStatus(value["status"]),
                source=OperationalEvidenceSource(value["source"]),
                trust_policy=OperationalTrustPolicy(value["trust_policy"]),
                limitations=tuple(value["limitations"]),
            )
        except (KeyError, TypeError, ValueError, HostContractError) as error:
            raise HostContractError("HOST_CREDENTIAL_RECEIPT") from error


@dataclass(frozen=True)
class ReviewerSessionReceipt:
    adapter_id: AdapterId
    host_session_id: str
    principal_ref: str
    review_artifact_sha256: str
    checked_at: str
    source: OperationalEvidenceSource
    trust_policy: OperationalTrustPolicy
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        _require(isinstance(self.adapter_id, AdapterId), "HOST_REVIEWER_RECEIPT")
        _identifier(self.host_session_id, "HOST_REVIEWER_RECEIPT")
        _identifier(self.principal_ref, "HOST_REVIEWER_RECEIPT")
        _hash(self.review_artifact_sha256, "HOST_REVIEWER_RECEIPT")
        _aware_time(self.checked_at, "HOST_REVIEWER_RECEIPT_TIME")
        _require(isinstance(self.source, OperationalEvidenceSource)
                 and self.trust_policy is OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
                 "HOST_REVIEWER_RECEIPT")
        _limitations(self.limitations, "HOST_REVIEWER_RECEIPT")

    @property
    def live_acceptance_eligible(self) -> bool:
        return self.source is OperationalEvidenceSource.HOST_RETURNED

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "version": OPERATIONAL_RECEIPT_VERSION,
            "adapter_id": self.adapter_id.value,
            "host_session_id": self.host_session_id,
            "principal_ref": self.principal_ref,
            "review_artifact_sha256": self.review_artifact_sha256,
            "checked_at": self.checked_at,
            "source": self.source.value,
            "trust_policy": self.trust_policy.value,
            "limitations": list(self.limitations),
            "cryptographic_remote_attestation": False,
            "live_acceptance_eligible": self.live_acceptance_eligible,
        }

    @classmethod
    def from_public_dict(cls, value: Any) -> "ReviewerSessionReceipt":
        _require(isinstance(value, dict)
                 and value.get("version") == OPERATIONAL_RECEIPT_VERSION,
                 "HOST_REVIEWER_RECEIPT")
        try:
            return cls(
                adapter_id=AdapterId(value["adapter_id"]),
                host_session_id=value["host_session_id"],
                principal_ref=value["principal_ref"],
                review_artifact_sha256=value["review_artifact_sha256"],
                checked_at=value["checked_at"],
                source=OperationalEvidenceSource(value["source"]),
                trust_policy=OperationalTrustPolicy(value["trust_policy"]),
                limitations=tuple(value["limitations"]),
            )
        except (KeyError, TypeError, ValueError, HostContractError) as error:
            raise HostContractError("HOST_REVIEWER_RECEIPT") from error


@dataclass(frozen=True)
class MCPProfileRef:
    server_identity: str
    transport: MCPTransport
    config_ref: WorkspaceFileRef
    startup_timeout_seconds: int
    query_timeout_seconds: int
    cleanup_evidence_ref: WorkspaceFileRef
    rollback_evidence_ref: WorkspaceFileRef
    enabled: bool = False

    def __post_init__(self) -> None:
        _identifier(self.server_identity, "HOST_MCP_SERVER_ID")
        _require(isinstance(self.transport, MCPTransport), "HOST_MCP_TRANSPORT")
        _require(type(self.startup_timeout_seconds) is int
                 and 1 <= self.startup_timeout_seconds <= 120,
                 "HOST_MCP_STARTUP_TIMEOUT")
        _require(type(self.query_timeout_seconds) is int
                 and 1 <= self.query_timeout_seconds <= 300,
                 "HOST_MCP_QUERY_TIMEOUT")
        _require(self.enabled is False, "HOST_MCP_ACTIVE_REJECTED")

    def verify(self, workspace_root: Path) -> None:
        self.config_ref.verify(workspace_root, "HOST_MCP_CONFIG_INVALID")
        self.cleanup_evidence_ref.verify(workspace_root, "HOST_MCP_CLEANUP_INVALID")
        self.rollback_evidence_ref.verify(workspace_root, "HOST_MCP_ROLLBACK_INVALID")

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "server_identity": self.server_identity,
            "transport": self.transport.value,
            "config_ref": asdict(self.config_ref),
            "startup_timeout_seconds": self.startup_timeout_seconds,
            "query_timeout_seconds": self.query_timeout_seconds,
            "cleanup_evidence_ref": asdict(self.cleanup_evidence_ref),
            "rollback_evidence_ref": asdict(self.rollback_evidence_ref),
            "enabled": False,
        }


@dataclass(frozen=True)
class RuntimeProfileRef:
    runtime_identity: str
    interpreter_ref: WorkspaceFileRef
    profile_ref: WorkspaceFileRef

    def __post_init__(self) -> None:
        _identifier(self.runtime_identity, "HOST_RUNTIME_ID")

    def verify(self, workspace_root: Path) -> None:
        self.interpreter_ref.verify(workspace_root, "HOST_RUNTIME_INTERPRETER_INVALID")
        self.profile_ref.verify(workspace_root, "HOST_RUNTIME_PROFILE_INVALID")


@dataclass(frozen=True)
class ToolBinding:
    operation: Operation
    observed_tool_identity: str

    def __post_init__(self) -> None:
        _require(isinstance(self.operation, Operation), "HOST_TOOL_OPERATION")
        _identifier(self.observed_tool_identity, "HOST_TOOL_IDENTITY")


_CODEX_BINDINGS = {
    Operation.SEARCH: "native_tools.web__run",
    Operation.OPEN: "native_tools.web__run",
    Operation.FIND: "native_tools.web__run",
}
_CLAUDE_BINDINGS = {
    Operation.SEARCH: "claude_code.WebSearch",
    Operation.OPEN: "claude_code.WebFetch",
}
_CODEX_CAPABILITIES = frozenset({
    Capability.SEARCH, Capability.OPEN, Capability.FIND,
    Capability.RAW_BODY_FIDELITY,
})
_CLAUDE_CAPABILITIES = frozenset({
    Capability.SEARCH, Capability.OPEN, Capability.RENDERED_EXTRACT,
})


@dataclass(frozen=True)
class HostAdapterProfile:
    adapter_id: AdapterId
    configured_backend: str
    tool_bindings: tuple[ToolBinding, ...]
    capabilities: frozenset[Capability]
    runtime: RuntimeProfileRef
    credential: CredentialRef
    mcp: MCPProfileRef | None = None

    def __post_init__(self) -> None:
        _require(isinstance(self.adapter_id, AdapterId), "HOST_ADAPTER_ID")
        _identifier(self.configured_backend, "HOST_CONFIGURED_BACKEND")
        _require(type(self.tool_bindings) is tuple and self.tool_bindings
                 and all(isinstance(row, ToolBinding) for row in self.tool_bindings),
                 "HOST_TOOL_BINDINGS")
        _require(len({row.operation for row in self.tool_bindings}) == len(self.tool_bindings),
                 "HOST_TOOL_BINDING_DUPLICATE")
        _require(type(self.capabilities) is frozenset and self.capabilities
                 and all(isinstance(value, Capability) for value in self.capabilities),
                 "HOST_CAPABILITIES")
        bindings = {row.operation: row.observed_tool_identity for row in self.tool_bindings}
        if self.adapter_id is AdapterId.CODEX_NATIVE_WEB:
            _require(self.configured_backend == "native_tools.web__run"
                     and bindings == _CODEX_BINDINGS
                     and self.capabilities == _CODEX_CAPABILITIES
                     and self.credential.source is CredentialSource.CODEX_PROFILE,
                     "HOST_CODEX_PROFILE_MISMATCH")
        else:
            _require(self.configured_backend == "claude_code.web"
                     and bindings == _CLAUDE_BINDINGS
                     and self.capabilities == _CLAUDE_CAPABILITIES
                     and self.credential.source is CredentialSource.CLAUDE_PROFILE,
                     "HOST_CLAUDE_PROFILE_MISMATCH")
        _require(self.mcp is None or isinstance(self.mcp, MCPProfileRef), "HOST_MCP_PROFILE")

    def tool_for(self, operation: Operation) -> str:
        for row in self.tool_bindings:
            if row.operation is operation:
                return row.observed_tool_identity
        raise HostContractError("HOST_OPERATION_UNSUPPORTED")

    def verify(self, workspace_root: Path) -> None:
        self.runtime.verify(workspace_root)
        if self.mcp is not None:
            self.mcp.verify(workspace_root)

    def to_public_dict(self) -> dict[str, Any]:
        value = {
            "version": VERSION,
            "adapter_id": self.adapter_id.value,
            "configured_backend": self.configured_backend,
            "tool_bindings": [{"operation": row.operation.value,
                               "observed_tool_identity": row.observed_tool_identity}
                              for row in self.tool_bindings],
            "capabilities": sorted(value.value for value in self.capabilities),
            "runtime": {
                "runtime_identity": self.runtime.runtime_identity,
                "interpreter_ref": asdict(self.runtime.interpreter_ref),
                "profile_ref": asdict(self.runtime.profile_ref),
            },
            "credential": self.credential.to_public_dict(),
            "mcp": self.mcp.to_public_dict() if self.mcp else None,
        }
        _reject_secret(value)
        return value


MAX_HOST_BUDGET_ITEMS = 64
MAX_HOST_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class HostBudget:
    search_items: int
    open_items: int
    provider_items: int
    concurrency: int
    call_timeout_seconds: int
    run_timeout_seconds: int

    def __post_init__(self) -> None:
        # Search/open are operation maxima and may legitimately be zero (for
        # example smoke has no opens).  The total provider budget, concurrency,
        # and deadlines remain strictly positive and bounded.
        for value in (self.search_items, self.open_items):
            _require(type(value) is int and 0 <= value <= MAX_HOST_BUDGET_ITEMS,
                     "HOST_BUDGET_INVALID")
        _require(type(self.provider_items) is int
                 and 0 < self.provider_items <= MAX_HOST_BUDGET_ITEMS,
                 "HOST_BUDGET_INVALID")
        _require(type(self.concurrency) is int and self.concurrency > 0,
                 "HOST_BUDGET_INVALID")
        for value in (self.call_timeout_seconds, self.run_timeout_seconds):
            _require(type(value) is int
                     and 0 < value <= MAX_HOST_TIMEOUT_SECONDS,
                     "HOST_BUDGET_INVALID")
        _require(self.concurrency == 1, "HOST_CONCURRENCY_UNSUPPORTED")
        _require(self.call_timeout_seconds <= self.run_timeout_seconds,
                 "HOST_DEADLINE_INVALID")


@dataclass(frozen=True)
class HostExecutionBinding:
    profile: HostAdapterProfile
    execution_id: str
    trace_id: str
    dispatch_namespace: str
    artifact_root: str
    cache_root: str
    budget: HostBudget

    def __post_init__(self) -> None:
        _require(isinstance(self.profile, HostAdapterProfile), "HOST_EXECUTION_PROFILE")
        try:
            _require(str(uuid.UUID(self.execution_id)) == self.execution_id,
                     "HOST_EXECUTION_ID")
        except (ValueError, TypeError):
            raise HostContractError("HOST_EXECUTION_ID") from None
        _identifier(self.trace_id, "HOST_TRACE_ID")
        _identifier(self.dispatch_namespace, "HOST_DISPATCH_NAMESPACE")
        for value in (self.artifact_root, self.cache_root):
            _require(isinstance(value, str) and value and not Path(value).is_absolute(),
                     "HOST_MUTABLE_ROOT")
            _reject_secret(value)
        _require(isinstance(self.budget, HostBudget), "HOST_EXECUTION_BUDGET")

    def _resolve_root(self, workspace_root: Path, value: str) -> Path:
        root = Path(workspace_root).resolve(strict=True)
        relative = Path(value)
        _require(relative.parts and ".." not in relative.parts, "HOST_MUTABLE_ROOT")
        current = root
        for part in relative.parts:
            current = current / part
            _require(not current.is_symlink(), "HOST_MUTABLE_ROOT")
        try:
            resolved = current.resolve(strict=False)
            resolved.relative_to(root)
        except (OSError, ValueError):
            raise HostContractError("HOST_MUTABLE_ROOT") from None
        if current.exists():
            _require(current.is_dir(), "HOST_MUTABLE_ROOT")
        return resolved

    def verify(self, workspace_root: Path) -> tuple[Path, Path]:
        self.profile.verify(workspace_root)
        artifact = self._resolve_root(workspace_root, self.artifact_root)
        cache = self._resolve_root(workspace_root, self.cache_root)
        _require(not _paths_overlap(artifact, cache), "HOST_ROOTS_OVERLAP")
        return artifact, cache

    def to_public_dict(self) -> dict[str, Any]:
        value = {
            "version": VERSION,
            "profile": self.profile.to_public_dict(),
            "execution_id": self.execution_id,
            "trace_id": self.trace_id,
            "dispatch_namespace": self.dispatch_namespace,
            "artifact_root": self.artifact_root,
            "cache_root": self.cache_root,
            "budget": asdict(self.budget),
        }
        _reject_secret(value)
        value["binding_sha256"] = hashlib.sha256(_canonical(value)).hexdigest()
        return value


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def validate_execution_pair(codex: HostExecutionBinding, claude: HostExecutionBinding,
                            *, workspace_root: Path) -> tuple[HostExecutionBinding, HostExecutionBinding]:
    """Verify two isolated host bindings without touching their mutable roots."""
    _require(codex.profile.adapter_id is AdapterId.CODEX_NATIVE_WEB
             and claude.profile.adapter_id is AdapterId.CLAUDE_CODE_WEB,
             "HOST_PAIR_ORDER")
    codex_artifact, codex_cache = codex.verify(workspace_root)
    claude_artifact, claude_cache = claude.verify(workspace_root)
    _require(codex.profile.credential.identity != claude.profile.credential.identity,
             "HOST_CREDENTIAL_SHARED")
    _require(codex.profile.runtime.profile_ref.path != claude.profile.runtime.profile_ref.path,
             "HOST_RUNTIME_PROFILE_SHARED")
    if codex.profile.mcp is not None and claude.profile.mcp is not None:
        _require(codex.profile.mcp.server_identity != claude.profile.mcp.server_identity
                 and codex.profile.mcp.config_ref.path != claude.profile.mcp.config_ref.path,
                 "HOST_MCP_PROFILE_SHARED")
    _require(codex.execution_id != claude.execution_id, "HOST_EXECUTION_SHARED")
    _require(codex.trace_id != claude.trace_id, "HOST_TRACE_SHARED")
    _require(codex.dispatch_namespace != claude.dispatch_namespace,
             "HOST_DISPATCH_NAMESPACE_SHARED")
    roots = (codex_artifact, codex_cache, claude_artifact, claude_cache)
    for index, left in enumerate(roots):
        for right in roots[index + 1:]:
            _require(not _paths_overlap(left, right), "HOST_MUTABLE_ROOT_SHARED")
    return codex, claude
