"""Strict cooperative adapter for Claude Code WebSearch/WebFetch.

The adapter maps one sealed acquisition operation to one exact Claude Code tool
call.  It does not invoke a tool, choose a provider, persist runtime state, or
establish source quality.  Durable dispatch fencing remains owned by
``HostedAcquisitionRunner`` and the live-session coordinator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import base64
import hashlib
import json
from typing import Any, Mapping

from investment.research.acquisition_runner import HostedProviderResponse
from shared.research_sources.acquisition_contracts import AcquisitionIdentity, ExactArguments
from shared.research_sources.acquisition_validation import public_https_url
from shared.research_sources.artifacts import SourceError


VERSION = "claude-code-web-adapter-1"
CLAUDE_CODE_SEARCH = "claude_code.WebSearch"
CLAUDE_CODE_FETCH = "claude_code.WebFetch"
CODEX_NATIVE_WEB = "codex.native_tools.web__run"
DEFAULT_RAW_LIMIT = 65536
FETCH_PROMPT = (
    "Return a bounded rendered extract of the requested public document. Preserve "
    "literal wording needed for source verification, state when content is unavailable, "
    "and do not infer facts absent from the fetched page."
)


class ClaudeCodeAdapterError(ValueError):
    """A stable, secret-safe adapter error code."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ClaudeCodeAdapterError(code)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise ClaudeCodeAdapterError("ACQ_CLAUDE_TOOL_INPUT_INVALID") from error


def _aware_timestamp(value: str) -> str:
    _require(isinstance(value, str), "ACQ_CLAUDE_CAPTURE_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ClaudeCodeAdapterError("ACQ_CLAUDE_CAPTURE_TIME_INVALID") from None
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None,
             "ACQ_CLAUDE_CAPTURE_TIME_INVALID")
    return value


@dataclass(frozen=True)
class ClaudeCodeCallSpec:
    identity: AcquisitionIdentity
    acquisition_arguments: ExactArguments
    host_tool: str
    tool_input: Mapping[str, Any]
    representation_scope: str
    requested_url: str | None
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        _require(isinstance(self.identity, AcquisitionIdentity)
                 and isinstance(self.acquisition_arguments, ExactArguments),
                 "ACQ_CLAUDE_CALL_IDENTITY_INVALID")
        _require(self.host_tool in {CLAUDE_CODE_SEARCH, CLAUDE_CODE_FETCH},
                 "ACQ_CLAUDE_TOOL_IDENTITY_INVALID")
        expected_scope = ("current_search_metadata_only" if self.host_tool == CLAUDE_CODE_SEARCH
                          else "rendered_extracted_representation")
        _require(self.representation_scope == expected_scope,
                 "ACQ_CLAUDE_REPRESENTATION_INVALID")
        _require(isinstance(self.tool_input, Mapping) and bool(self.tool_input),
                 "ACQ_CLAUDE_TOOL_INPUT_INVALID")
        _require(type(self.limitations) is tuple and bool(self.limitations)
                 and all(isinstance(value, str) and value for value in self.limitations),
                 "ACQ_CLAUDE_LIMITATIONS_INVALID")
        if self.host_tool == CLAUDE_CODE_FETCH:
            _require(self.requested_url == self.tool_input.get("url"),
                     "ACQ_CLAUDE_URL_MISMATCH")
        else:
            _require(self.requested_url is None, "ACQ_CLAUDE_URL_MISMATCH")

    @property
    def tool_input_sha256(self) -> str:
        return hashlib.sha256(_canonical(self.tool_input)).hexdigest()

    def public_call(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "experiment_id": self.identity.run.experiment_id,
            "execution_id": self.identity.run.execution_id,
            "trace_id": self.identity.run.trace_id,
            "operation_id": self.identity.dispatch.operation_id,
            "attempt_id": self.identity.dispatch.attempt_id,
            "dispatch_id": self.identity.dispatch.dispatch_id,
            "configured_backend": self.host_tool,
            "tool_input": dict(self.tool_input),
            "tool_input_sha256": self.tool_input_sha256,
            "acquisition_arguments_sha256": self.acquisition_arguments.sha256,
            "representation_scope": self.representation_scope,
            "requested_url": self.requested_url,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class ClaudeCodeCapture:
    spec: ClaudeCodeCallSpec
    raw_result_json: bytes = field(repr=False)
    captured_at: str
    raw_byte_limit: int

    def __post_init__(self) -> None:
        _require(isinstance(self.spec, ClaudeCodeCallSpec),
                 "ACQ_CLAUDE_CAPTURE_SPEC_INVALID")
        _require(isinstance(self.raw_result_json, bytes) and bool(self.raw_result_json),
                 "ACQ_CLAUDE_CAPTURE_INVALID")
        _require(type(self.raw_byte_limit) is int and 0 < self.raw_byte_limit <= 8 * 1024 * 1024,
                 "ACQ_CLAUDE_RAW_LIMIT_INVALID")
        _require(len(self.raw_result_json) <= self.raw_byte_limit,
                 "ACQ_CLAUDE_RAW_TOO_LARGE")
        try:
            json.loads(self.raw_result_json)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ClaudeCodeAdapterError("ACQ_CLAUDE_CAPTURE_JSON_INVALID") from None
        _aware_timestamp(self.captured_at)

    @property
    def raw_result_sha256(self) -> str:
        return hashlib.sha256(self.raw_result_json).hexdigest()

    def provider_response(self) -> HostedProviderResponse:
        """Return exact bytes for the existing runner's private bounded capture."""
        return HostedProviderResponse([self.raw_result_json], observed_backend=self.spec.host_tool)

    def receipt(self) -> dict[str, Any]:
        """Return a bounded public envelope; raw tool output is hash-only."""
        call = self.spec.public_call()
        return {
            "kind": "acquisition_cooperative_host_capture",
            **call,
            "observed_backend": self.spec.host_tool,
            "captured_at": self.captured_at,
            "raw_result_sha256": self.raw_result_sha256,
            "raw_result_bytes": len(self.raw_result_json),
            "raw_result_limit_bytes": self.raw_byte_limit,
            "truncated": False,
            "raw_result_persisted_here": False,
        }


class PreparedClaudeCodeCall:
    """One-shot in-process capture guard around an immutable call specification.

    This guard catches accidental duplicate capture in one cooperative turn.  It is
    not a restart fence; callers must pass ``provider_response()`` through the
    durable hosted runner before treating the operation as captured.
    """

    def __init__(self, spec: ClaudeCodeCallSpec):
        _require(isinstance(spec, ClaudeCodeCallSpec), "ACQ_CLAUDE_CALL_SPEC_INVALID")
        self.spec = spec
        self._captured = False

    def capture(self, *, dispatch_id: str, observed_tool: str,
                actual_tool_input: Mapping[str, Any], raw_result_json: bytes,
                captured_at: str, raw_byte_limit: int = DEFAULT_RAW_LIMIT) -> ClaudeCodeCapture:
        _require(not self._captured, "ACQ_CLAUDE_CAPTURE_REPLAY")
        _require(dispatch_id == self.spec.identity.dispatch.dispatch_id,
                 "ACQ_CLAUDE_CAPTURE_ID_MISMATCH")
        _require(observed_tool == self.spec.host_tool,
                 "ACQ_CLAUDE_CAPTURE_TOOL_MISMATCH")
        _require(_canonical(actual_tool_input) == _canonical(self.spec.tool_input),
                 "ACQ_CLAUDE_CAPTURE_ARGUMENT_MISMATCH")
        capture = ClaudeCodeCapture(self.spec, raw_result_json, captured_at, raw_byte_limit)
        self._captured = True
        return capture


def prepare_claude_code_call(identity: AcquisitionIdentity,
                             arguments: Mapping[str, Any]) -> PreparedClaudeCodeCall:
    """Map one exact acquisition operation to one Claude Code host-tool call."""
    _require(isinstance(identity, AcquisitionIdentity), "ACQ_CLAUDE_CALL_IDENTITY_INVALID")
    exact = ExactArguments.from_mapping(arguments)
    decoded = exact.to_dict()
    _require(set(decoded) <= {"search_query", "open", "find", "response_length"},
             "ACQ_CLAUDE_ARGUMENTS_INVALID")
    keys = [key for key in ("search_query", "open", "find") if key in decoded]
    _require(len(keys) == 1, "ACQ_CLAUDE_ARGUMENTS_INVALID")
    key = keys[0]
    _require(key != "find", "ACQ_CLAUDE_FIND_UNSUPPORTED")
    items = decoded[key]
    _require(isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict),
             "ACQ_CLAUDE_ONE_ITEM_REQUIRED")
    response_length = decoded.get("response_length", "long")
    _require(response_length == "long", "ACQ_CLAUDE_RESPONSE_LENGTH_UNSUPPORTED")

    if key == "search_query":
        item = items[0]
        _require(set(item) == {"q"} and isinstance(item.get("q"), str)
                 and 0 < len(item["q"]) <= 1000,
                 "ACQ_CLAUDE_SEARCH_ARGUMENTS_UNSUPPORTED")
        spec = ClaudeCodeCallSpec(
            identity=identity,
            acquisition_arguments=exact,
            host_tool=CLAUDE_CODE_SEARCH,
            tool_input={"query": item["q"]},
            representation_scope="current_search_metadata_only",
            requested_url=None,
            limitations=(
                "Search results are current metadata and are not opened-document evidence.",
                "Claude Code host-tool output is not publisher-original bytes.",
            ),
        )
    else:
        item = items[0]
        _require(set(item) == {"ref_id"}, "ACQ_CLAUDE_OPEN_ARGUMENTS_UNSUPPORTED")
        try:
            url = public_https_url(item.get("ref_id"), "ACQ_CLAUDE_URL_INVALID")
        except (SourceError, TypeError, ValueError):
            raise ClaudeCodeAdapterError("ACQ_CLAUDE_URL_INVALID") from None
        spec = ClaudeCodeCallSpec(
            identity=identity,
            acquisition_arguments=exact,
            host_tool=CLAUDE_CODE_FETCH,
            tool_input={"url": url, "prompt": FETCH_PROMPT},
            representation_scope="rendered_extracted_representation",
            requested_url=url,
            limitations=(
                "WebFetch returns a rendered or model-extracted representation, not publisher-original bytes.",
                "Literal support is limited to text present in the exact captured host output.",
                "This capture does not establish historical availability or semantic admission.",
            ),
        )
    _require(spec.host_tool != CODEX_NATIVE_WEB, "ACQ_CLAUDE_CODEX_IDENTITY_CONFLICT")
    return PreparedClaudeCodeCall(spec)
