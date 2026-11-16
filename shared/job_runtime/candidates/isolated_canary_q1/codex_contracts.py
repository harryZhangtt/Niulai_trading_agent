"""Frozen, redacted Codex 0.167 candidate contracts."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping

from .canonical import canonical_json_bytes, sha256_bytes
from .frozen import freeze


class CodexCandidateError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _sha(value: str) -> bool:
    return type(value) is str and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


@dataclass(frozen=True, slots=True, repr=False)
class PromptBytesV1:
    sha256: str
    length: int
    raw: bytes

    def __post_init__(self) -> None:
        if type(self.raw) is not bytes or type(self.length) is not int or not 1 <= len(self.raw) <= 524_288 or self.length != len(self.raw) or type(self.sha256) is not str or self.sha256 != sha256_bytes(self.raw):
            raise CodexCandidateError("CODEX_Q1_PROMPT_BINDING_MISMATCH")

    @classmethod
    def bind(cls, raw: bytes) -> "PromptBytesV1":
        if type(raw) is not bytes:
            raise CodexCandidateError("CODEX_Q1_PROMPT_TYPE_INVALID")
        if not 1 <= len(raw) <= 524_288:
            raise CodexCandidateError("CODEX_Q1_PROMPT_SIZE_INVALID")
        return cls(sha256_bytes(raw), len(raw), raw)

    def __repr__(self) -> str:
        return "PromptBytesV1(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class InvocationPlanV1:
    argv: tuple[str, ...]
    stdin_chunks: tuple[bytes, ...]
    stdin_sha256: str
    stdin_length: int
    configured_model: str
    effort: str
    final_output_token: str
    argv_sha256: str

    def __post_init__(self) -> None:
        if type(self.argv) is not tuple or not self.argv or any(type(token) is not str for token in self.argv) or type(self.stdin_chunks) is not tuple or any(type(chunk) is not bytes for chunk in self.stdin_chunks):
            raise CodexCandidateError("CODEX_Q1_AUTHORITY_INVALID")
        raw = b"".join(self.stdin_chunks)
        expected_effort = f'model_reasoning_effort="{self.effort}"'
        expected_tuple = ("codex", "exec", "--ignore-user-config", "--ephemeral", "--strict-config", "--json", "--sandbox", "read-only", "--model", self.configured_model, "-c", "request_max_retries=0", "-c", "stream_max_retries=0", "-c", expected_effort, "--output-last-message", self.final_output_token, "-")
        expected_argv = sha256_bytes(canonical_json_bytes(list(expected_tuple)))
        if not 1 <= len(raw) <= 524_288 or type(self.stdin_length) is not int or type(self.stdin_sha256) is not str or self.stdin_sha256 != sha256_bytes(raw) or self.stdin_length != len(raw) or type(self.configured_model) is not str or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", self.configured_model) is None or type(self.effort) is not str or self.effort not in {"low", "medium", "high"} or type(self.final_output_token) is not str or re.fullmatch(r"@[A-Za-z0-9._-]{1,64}", self.final_output_token) is None or type(self.argv_sha256) is not str or self.argv != expected_tuple or self.argv_sha256 != expected_argv:
            raise CodexCandidateError("CODEX_Q1_PROMPT_BINDING_MISMATCH")

    def __repr__(self) -> str:
        return "InvocationPlanV1(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class FinalOutputBindingV1:
    sha256: str
    size: int
    custody_verified: bool
    raw: bytes

    def __post_init__(self) -> None:
        if type(self.raw) is not bytes or type(self.size) is not int or self.size != len(self.raw) or type(self.sha256) is not str or self.sha256 != sha256_bytes(self.raw) or type(self.custody_verified) is not bool:
            raise CodexCandidateError("CODEX_Q1_FINAL_OUTPUT_UNBOUND")

    def __repr__(self) -> str:
        return "FinalOutputBindingV1(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class CaptureEnvelopeV1:
    stdout_jsonl: bytes
    process_phase: str
    exit_code: int | None
    signal: int | None
    prompt_delivery_complete: bool
    prompt_sha256: str
    prompt_length: int
    prompt_sent_length: int
    launch_binding_sha256: str
    retry_zero_observed: bool
    final_output: FinalOutputBindingV1 | None

    def __post_init__(self) -> None:
        exact_int_or_none = lambda value: value is None or type(value) is int
        if type(self.stdout_jsonl) is not bytes or type(self.process_phase) is not str or self.process_phase not in {"not_started", "connecting", "submitted", "terminal"} or not exact_int_or_none(self.exit_code) or not exact_int_or_none(self.signal) or (self.exit_code is not None and self.signal is not None) or type(self.prompt_delivery_complete) is not bool or type(self.prompt_length) is not int or type(self.prompt_sent_length) is not int or self.prompt_length < 0 or self.prompt_sent_length < 0 or not _sha(self.prompt_sha256) or not _sha(self.launch_binding_sha256) or type(self.retry_zero_observed) is not bool:
            raise CodexCandidateError("CODEX_Q1_PROCESS_CONTRADICTORY")
        if self.final_output is not None and type(self.final_output) is not FinalOutputBindingV1:
            raise CodexCandidateError("CODEX_Q1_PROCESS_CONTRADICTORY")
        if self.process_phase == "terminal" and self.exit_code is None and self.signal is None:
            raise CodexCandidateError("CODEX_Q1_PROCESS_CONTRADICTORY")

    def __repr__(self) -> str:
        return "CaptureEnvelopeV1(<redacted>)"


@dataclass(frozen=True, slots=True)
class TranslationReceiptV1:
    schema_version: int
    status: str
    code: str
    phase: str
    submission: str
    terminal_kind: str
    event_count: int
    item_counts: Mapping[str, int]
    tool_activity: bool
    retry_zero_verified: bool
    prompt_delivery_verified: bool
    final_output_verified: bool
    model_binding_source: str
    provider_reported_model: bool
    observed_model: None
    model_identity_verified: bool
    capability_open: bool

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1 or type(self.status) is not str or self.status not in {"succeeded", "failed", "unknown"} or type(self.code) is not str or not self.code.startswith("CODEX_Q1_") or type(self.phase) is not str or self.phase not in {"streaming", "terminal"} or type(self.submission) is not str or self.submission not in {"possibly_submitted", "definitely_submitted"} or type(self.terminal_kind) is not str or self.terminal_kind not in {"missing", "turn.completed", "turn.failed", "error"} or type(self.event_count) is not int or self.event_count < 0 or type(self.item_counts) is not dict or any(type(key) is not str or type(value) is not int or value < 0 for key, value in self.item_counts.items()) or any(type(value) is not bool for value in (self.tool_activity, self.retry_zero_verified, self.prompt_delivery_verified, self.final_output_verified, self.provider_reported_model, self.model_identity_verified, self.capability_open)) or type(self.model_binding_source) is not str or self.model_binding_source != "configured_cli_argument" or self.provider_reported_model or self.observed_model is not None or self.model_identity_verified or self.capability_open:
            raise CodexCandidateError("CODEX_Q1_EVENT_FIELDS_INVALID")
        if self.status == "succeeded" and not (self.code == "CODEX_Q1_COMPLETED" and self.phase == "terminal" and self.submission == "definitely_submitted" and self.terminal_kind == "turn.completed" and self.retry_zero_verified and self.prompt_delivery_verified and self.final_output_verified and not self.tool_activity):
            raise CodexCandidateError("CODEX_Q1_EVENT_FIELDS_INVALID")
        if self.status != "succeeded" and self.code == "CODEX_Q1_COMPLETED":
            raise CodexCandidateError("CODEX_Q1_EVENT_FIELDS_INVALID")
        failed_variants = {"CODEX_Q1_TURN_FAILED": "turn.failed", "CODEX_Q1_RUNNER_ERROR": "error", "CODEX_Q1_TOOL_POLICY_VIOLATION": "turn.completed"}
        streaming_unknown_codes = {"CODEX_Q1_RETRY_ZERO_UNPROVEN", "CODEX_Q1_PROCESS_CONTRADICTORY", "CODEX_Q1_CAPTURE_SIZE_INVALID", "CODEX_Q1_CAPTURE_TRUNCATED", "CODEX_Q1_EVENT_MALFORMED", "CODEX_Q1_EVENT_DUPLICATE_KEY", "CODEX_Q1_EVENT_ORDER_INVALID", "CODEX_Q1_EVENT_FIELDS_INVALID", "CODEX_Q1_EVENT_UNSUPPORTED", "CODEX_Q1_ITEM_ORDER_INVALID", "CODEX_Q1_TERMINAL_MISSING", "CODEX_Q1_EVENT_AFTER_TERMINAL"}
        terminal_unknown_codes = {"CODEX_Q1_PROCESS_CONTRADICTORY"}
        if self.status == "failed" and not (self.phase == "terminal" and self.submission == "definitely_submitted" and failed_variants.get(self.code) == self.terminal_kind):
            raise CodexCandidateError("CODEX_Q1_EVENT_FIELDS_INVALID")
        if self.status == "failed" and self.code == "CODEX_Q1_TOOL_POLICY_VIOLATION" and not self.tool_activity:
            raise CodexCandidateError("CODEX_Q1_EVENT_FIELDS_INVALID")
        if self.status == "unknown":
            streaming_valid = self.phase == "streaming" and self.code in streaming_unknown_codes and self.submission == "possibly_submitted" and self.terminal_kind == "missing" and not self.retry_zero_verified and not self.prompt_delivery_verified and not self.final_output_verified
            terminal_valid = self.phase == "terminal" and self.code in terminal_unknown_codes and self.submission == "definitely_submitted" and self.terminal_kind != "missing"
            if not (streaming_valid or terminal_valid):
                raise CodexCandidateError("CODEX_Q1_EVENT_FIELDS_INVALID")
        object.__setattr__(self, "item_counts", freeze(self.item_counts))


@dataclass(frozen=True, slots=True)
class CapabilityGateV1:
    source_authority_verified: bool
    source_grammar_verified: bool
    binary_asset_verified: bool
    retry_zero_live_verified: bool
    sanitized_live_capture_verified: bool
    asset_capture_binding_verified: bool
    canonical_integration_reviewed: bool
    capability_open: bool

    def __post_init__(self) -> None:
        values = (self.source_authority_verified, self.source_grammar_verified, self.binary_asset_verified, self.retry_zero_live_verified, self.sanitized_live_capture_verified, self.asset_capture_binding_verified, self.canonical_integration_reviewed, self.capability_open)
        if any(type(value) is not bool for value in values) or any(values):
            raise CodexCandidateError("CODEX_Q1_CAPABILITY_CLOSED")
