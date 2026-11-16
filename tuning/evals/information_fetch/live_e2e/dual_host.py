"""Provider-free sealing of one case for isolated Codex and Claude hosts.

This module validates references and emits private-runtime packet *descriptions*.
It never resolves credentials, creates runtime roots, invokes a provider, or enables
MCP. Callers own private persistence and must keep the returned packets out of
source control.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from shared.research_sources.host_adapter_contracts import (
    AdapterId,
    HostBudget,
    HostContractError,
    HostExecutionBinding,
    validate_execution_pair,
)


VERSION = "dual-host-live-e2e-1"
_SHA256 = re.compile(r"[a-f0-9]{64}")
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~-]+"),
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----"),
    re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|client[_-]?secret)\s*[=:]"),
)
_FORBIDDEN_INPUT_KEYS = frozenset({
    "apikey", "accesstoken", "refreshtoken", "password", "clientsecret",
    "credentialvalue", "tokenvalue", "secretvalue",
})
_EXPECTED_SEQUENCE = ("search", "open_pdf", "open_sealed_html_alternate")

PUBLIC_CASE_TEMPLATE: dict[str, Any] = {
    "schema_version": "dual-host-public-case-1",
    "case_id": "now-q1-2025-financial-results-positive-control-v1",
    "issuer_id": "NOW",
    "canonical_disclosure_id": "servicenow-q1-2025-financial-results",
    "title": "ServiceNow Reports First Quarter 2025 Financial Results",
    "publication_date": "2025-04-23",
    "question": "What does the official Q1 2025 release establish, and what remains unestablished?",
    "search_query": "site:newsroom.servicenow.com \"ServiceNow Reports First Quarter 2025 Financial Results\"",
    "primary_pdf_url": "https://s205.q4cdn.com/537566246/files/doc_news/ServiceNow-Reports-First-Quarter-2025-Financial-Results-2025.pdf",
    "alternate_html_url": "https://newsroom.servicenow.com/press-releases/details/2025/ServiceNow-Reports-First-Quarter-2025-Financial-Results/default.aspx",
    "equivalence_status": "approved",
    "equivalence_reviewer_id": "independent-live-browser-review",
    "equivalence_rationale": "The ServiceNow Newsroom HTML page explicitly labels and links the 244 KB PDF as the PDF-format download of the same titled and dated release.",
    "equivalence_caveat": "Q4 CDN is the hosting intermediary; approval establishes publisher-authorized representation, not byte identity or complete textual parity.",
    "quote_preselected": False,
    "selection_bias": "ServiceNow is repeatedly inspected development evidence and is only a positive control.",
}

PUBLIC_PROTOCOL: dict[str, Any] = {
    "schema_version": "dual-host-protocol-1",
    "dispatch_sequence": list(_EXPECTED_SEQUENCE),
    "budgets": {
        "search_items": 1,
        "open_items": 2,
        "provider_items": 3,
        "concurrency": 1,
        "call_timeout_seconds": 60,
        "run_timeout_seconds": 300,
    },
    "cache_enabled": False,
    "fallback": {
        "allowed": "sealed_html_after_eligible_pdf_representation_failure",
        "cross_host": False,
        "provider_switch": False,
        "unchanged_retry": False,
    },
    "mcp": "not_used",
}


class DualHostError(ValueError):
    """Stable, non-secret error raised before any provider action."""


class HostName(str, Enum):
    CODEX = "codex"
    CLAUDE = "claude"


@dataclass(frozen=True)
class HostRuntimeInput:
    """Host-owned references and an isolated unknown-outcome fence."""

    binding: HostExecutionBinding
    unknown_outcome_fence: str


@dataclass(frozen=True)
class DualHostBundle:
    sealed_case: dict[str, Any]
    sealed_protocol: dict[str, Any]
    codex_envelope: dict[str, Any]
    claude_envelope: dict[str, Any]

    def packets(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return generated packet descriptions; no files or credentials are read."""
        return self.codex_envelope["packet"], self.claude_envelope["packet"]


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise DualHostError(code)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise DualHostError("DUAL_HOST_JSON_INVALID") from error


def _reject_secrets(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            _require(normalized not in _FORBIDDEN_INPUT_KEYS,
                     "DUAL_HOST_SECRET_INPUT_REJECTED")
            _reject_secrets(str(key))
            _reject_secrets(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _reject_secrets(item)
    elif isinstance(value, str):
        _require(not any(pattern.search(value) for pattern in _SECRET_PATTERNS),
                 "DUAL_HOST_SECRET_INPUT_REJECTED")


def _seal(packet: dict[str, Any]) -> dict[str, Any]:
    _reject_secrets(packet)
    return {
        "packet": packet,
        "seal": {
            "algorithm": "sha256",
            "packet_sha256": hashlib.sha256(canonical_bytes(packet)).hexdigest(),
        },
    }


def _validate_seal(envelope: Mapping[str, Any], code: str) -> None:
    _require(set(envelope) == {"packet", "seal"}, code)
    seal = envelope["seal"]
    _require(isinstance(seal, Mapping) and seal.get("algorithm") == "sha256"
             and _SHA256.fullmatch(str(seal.get("packet_sha256"))) is not None
             and seal["packet_sha256"] == hashlib.sha256(
                 canonical_bytes(envelope["packet"])).hexdigest(), code)


def seal_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and seal a quote-free public case."""
    _require(isinstance(case, Mapping), "DUAL_HOST_CASE_INVALID")
    packet = dict(case)
    required = set(PUBLIC_CASE_TEMPLATE)
    _require(set(packet) == required, "DUAL_HOST_CASE_FIELDS")
    _require(packet.get("schema_version") == "dual-host-public-case-1"
             and packet.get("quote_preselected") is False,
             "DUAL_HOST_CASE_INVALID")
    for key in required - {"quote_preselected"}:
        _require(isinstance(packet[key], str) and bool(packet[key].strip()),
                 "DUAL_HOST_CASE_INVALID")
    normalized_keys = {re.sub(r"[^a-z0-9]", "", key.lower()) for key in packet}
    _require("quote" not in normalized_keys and "selectedquote" not in normalized_keys,
             "DUAL_HOST_QUOTE_REJECTED")
    urls = [urlsplit(packet[key]) for key in ("primary_pdf_url", "alternate_html_url")]
    hosts = [url.hostname for url in urls]
    same_publisher = (hosts[0] == hosts[1] or
                      all(host == "servicenow.com" or host.endswith(".servicenow.com")
                          for host in hosts if host is not None))
    approved_intermediary = (
        packet.get("equivalence_status") == "approved"
        and hosts == ["s205.q4cdn.com", "newsroom.servicenow.com"]
        and packet.get("canonical_disclosure_id")
            == "servicenow-q1-2025-financial-results"
        and packet.get("title")
            == "ServiceNow Reports First Quarter 2025 Financial Results"
        and packet.get("publication_date") == "2025-04-23"
        and "Q4 CDN" in packet.get("equivalence_caveat", "")
    )
    _require(all(url.scheme == "https" and url.hostname and not url.username
                 and not url.password and not url.fragment for url in urls)
             and (same_publisher or approved_intermediary)
             and urls[0].path.lower().endswith(".pdf"),
             "DUAL_HOST_CASE_URL_INVALID")
    return _seal(packet)


def seal_protocol(protocol: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the common bounded protocol and seal it once for both hosts."""
    _require(isinstance(protocol, Mapping), "DUAL_HOST_PROTOCOL_INVALID")
    packet = json.loads(canonical_bytes(protocol))
    _require(packet.get("schema_version") == "dual-host-protocol-1"
             and tuple(packet.get("dispatch_sequence", ())) == _EXPECTED_SEQUENCE
             and packet.get("cache_enabled") is False
             and packet.get("mcp") == "not_used",
             "DUAL_HOST_PROTOCOL_INVALID")
    fallback = packet.get("fallback")
    _require(isinstance(fallback, dict) and fallback.get("cross_host") is False
             and fallback.get("provider_switch") is False
             and fallback.get("unchanged_retry") is False,
             "DUAL_HOST_CROSS_HOST_FALLBACK_REJECTED")
    try:
        budget = HostBudget(**packet["budgets"])
    except (KeyError, TypeError, HostContractError) as error:
        raise DualHostError("DUAL_HOST_BUDGET_INVALID") from error
    _require(asdict(budget) == packet["budgets"], "DUAL_HOST_BUDGET_INVALID")
    return _seal(packet)


def _relative_fence(root: Path, value: str) -> Path:
    _require(isinstance(value, str) and value and not Path(value).is_absolute(),
             "DUAL_HOST_FENCE_INVALID")
    relative = Path(value)
    _require(relative.parts and ".." not in relative.parts,
             "DUAL_HOST_FENCE_INVALID")
    current = root
    for part in relative.parts:
        current = current / part
        _require(not current.is_symlink(), "DUAL_HOST_FENCE_INVALID")
    try:
        resolved = current.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        raise DualHostError("DUAL_HOST_FENCE_INVALID") from None
    if current.exists():
        _require(current.is_dir(), "DUAL_HOST_FENCE_INVALID")
    return resolved


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _host_packet(host: HostName, runtime: HostRuntimeInput,
                 case: Mapping[str, Any], protocol: Mapping[str, Any]) -> dict[str, Any]:
    binding = runtime.binding.to_public_dict()
    expected = (AdapterId.CODEX_NATIVE_WEB if host is HostName.CODEX
                else AdapterId.CLAUDE_CODE_WEB)
    _require(runtime.binding.profile.adapter_id is expected,
             "DUAL_HOST_ADAPTER_MISMATCH")
    _require(runtime.binding.profile.mcp is None, "DUAL_HOST_MCP_NOT_USED")
    packet = {
        "schema_version": VERSION,
        "host": host.value,
        "case_ref": {"packet_sha256": case["seal"]["packet_sha256"]},
        "protocol_ref": {"packet_sha256": protocol["seal"]["packet_sha256"]},
        "binding": binding,
        "unknown_outcome_fence": runtime.unknown_outcome_fence,
        "fallback": {
            "host": host.value,
            "cross_host": False,
            "provider_switch": False,
        },
        "mcp": "not_used",
        "credential_value_present": False,
    }
    return packet


def build_dual_host_bundle(*, case: Mapping[str, Any], protocol: Mapping[str, Any],
                           codex: HostRuntimeInput, claude: HostRuntimeInput,
                           workspace_root: Path) -> DualHostBundle:
    """Build two sealed, isolated packets from one sealed case and protocol.

    Verification reads only the workspace files named by immutable runtime/profile
    references. It neither reads a credential store nor touches mutable roots.
    """
    sealed_case = seal_case(case)
    sealed_protocol = seal_protocol(protocol)
    root = Path(workspace_root).resolve(strict=True)
    try:
        codex_binding, claude_binding = validate_execution_pair(
            codex.binding, claude.binding, workspace_root=root)
    except HostContractError as error:
        raise DualHostError(str(error)) from error
    _require(codex_binding.budget == claude_binding.budget,
             "DUAL_HOST_BUDGET_MISMATCH")
    _require(asdict(codex_binding.budget) == sealed_protocol["packet"]["budgets"],
             "DUAL_HOST_PROTOCOL_BUDGET_MISMATCH")

    codex_fence = _relative_fence(root, codex.unknown_outcome_fence)
    claude_fence = _relative_fence(root, claude.unknown_outcome_fence)
    codex_artifact, codex_cache = codex_binding.verify(root)
    claude_artifact, claude_cache = claude_binding.verify(root)
    mutable = [
        codex_artifact, codex_cache, claude_artifact, claude_cache,
        codex_fence, claude_fence,
    ]
    for index, left in enumerate(mutable):
        for right in mutable[index + 1:]:
            _require(not _overlap(left, right), "DUAL_HOST_FENCE_SHARED")

    codex_envelope = _seal(_host_packet(
        HostName.CODEX, codex, sealed_case, sealed_protocol))
    claude_envelope = _seal(_host_packet(
        HostName.CLAUDE, claude, sealed_case, sealed_protocol))
    _validate_seal(codex_envelope, "DUAL_HOST_CODEX_SEAL_INVALID")
    _validate_seal(claude_envelope, "DUAL_HOST_CLAUDE_SEAL_INVALID")
    _require(codex_envelope["seal"]["packet_sha256"]
             != claude_envelope["seal"]["packet_sha256"],
             "DUAL_HOST_ENVELOPE_COLLISION")
    return DualHostBundle(sealed_case, sealed_protocol,
                          codex_envelope, claude_envelope)
