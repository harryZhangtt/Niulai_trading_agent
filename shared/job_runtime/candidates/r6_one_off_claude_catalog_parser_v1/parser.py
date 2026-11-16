"""Provider-free parser for one frozen Claude ``/model`` JSONL capture.

This module performs local file reads only.  It has no provider, network,
account, subprocess, retry, replay, or live-action surface.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

STATUS = "PASS_FROZEN_CATALOG_MEMBERSHIP_EVIDENCE"
DISPLAY_TOKEN = "Opus 5.5"
EXPECTED_MODEL = "claude-opus-5-5"
EXECUTION_RECEIPT_REF = {
    "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-claude-catalog-preflight-r6-execution-receipt.json",
    "bytes": 2603,
    "sha256": "b0b7312fe4bb6e451835f3c97288b560f53836f92cb69a1784f00ed324d44dc1",
}
STDOUT_REF = {
    "path": "/Users/bytedance/Desktop/Trading Agent/.job-runtime/live-provider-evidence/r6-one-off/claude-catalog-r6-32489c6235ba413a99eaf4fe8d89c7a1/stdout",
    "bytes": 5288,
    "sha256": "162c2ffbc043b84b6396168fde4fea592f6e77b0e9a3e3eba976db5ef36966dc",
    "mode": "0600",
}

_SYSTEM_KEYS = frozenset({
    "type", "subtype", "cwd", "session_id", "tools", "mcp_servers", "model",
    "permissionMode", "slash_commands", "terminal_slash_commands", "apiKeySource",
    "claude_code_version", "output_style", "agents", "skills", "plugins",
    "capabilities", "analytics_disabled", "product_feedback_disabled", "uuid",
    "original_cwd", "additional_directories", "messaging_socket_path",
    "fast_mode_state", "fast_mode_disabled_reason", "per_turn_effort_active",
    "ultrathink_available", "ultrathink_typed_raises", "view_mode",
})
_ASSISTANT_KEYS = frozenset({
    "type", "message", "parent_tool_use_id", "local_command_source", "session_id",
    "uuid", "timestamp", "local_command_run",
})
_MESSAGE_KEYS = frozenset({
    "model", "id", "type", "role", "content", "stop_reason", "stop_sequence",
    "usage", "context_management", "stop_details", "container", "diagnostics",
})
_RESULT_KEYS = frozenset({
    "is_error", "duration_ms", "duration_api_ms", "num_turns", "stop_reason",
    "session_id", "total_cost_usd", "usage", "modelUsage", "permission_denials",
    "fast_mode_state", "fast_mode_disabled_reason", "subagent_stats", "safety_stops",
    "subtype", "result", "local_command", "type", "uuid", "queued_turn_count",
    "result_index", "model_usage_since_last_result",
})
_USAGE_KEYS = frozenset({
    "output_tokens_details", "input_tokens", "cache_creation_input_tokens",
    "cache_read_input_tokens", "output_tokens", "server_tool_use", "service_tier",
    "cache_creation", "inference_geo", "iterations", "speed", "fallback_credit",
})
_SECRET_KEYS = frozenset({
    "api_key", "apikey", "authorization", "password", "passwd", "secret",
    "access_token", "refresh_token", "credential", "credentials", "cookie",
    "private_key",
})


class CatalogParseError(ValueError):
    """A stable fail-closed error from the frozen parser contract."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise CatalogParseError(code)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pairs(values: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    keys = [key for key, _ in values]
    _require(len(keys) == len(set(keys)), "DUPLICATE_JSON_KEY")
    return dict(values)


def _reject_constant(_value: str) -> Any:
    raise ValueError("non-finite number")


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _reject_secrets(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_key(key)
            _require(normalized not in _SECRET_KEYS, "SECRET_FIELD_FORBIDDEN")
            _reject_secrets(child)
    elif isinstance(value, list):
        for child in value:
            _reject_secrets(child)


def _exact_keys(value: Any, keys: Iterable[str], code: str) -> Mapping[str, Any]:
    _require(type(value) is dict and set(value) == set(keys), code)
    return value


def _string_list(value: Any, code: str) -> None:
    _require(type(value) is list and all(type(item) is str for item in value), code)


def _zero_number(value: Any, code: str) -> None:
    _require(type(value) in (int, float) and not isinstance(value, bool) and value == 0, code)


def _validate_usage(value: Any, terminal: bool) -> None:
    usage = _exact_keys(value, _USAGE_KEYS, "USAGE_SCHEMA_INVALID")
    for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"):
        _zero_number(usage[key], "NONZERO_INFERENCE_USAGE")
    cache = _exact_keys(
        usage["cache_creation"],
        ("ephemeral_1h_input_tokens", "ephemeral_5m_input_tokens"),
        "USAGE_SCHEMA_INVALID",
    )
    server = _exact_keys(
        usage["server_tool_use"], ("web_search_requests", "web_fetch_requests"),
        "USAGE_SCHEMA_INVALID",
    )
    for value_ in list(cache.values()) + list(server.values()):
        _zero_number(value_, "NONZERO_INFERENCE_USAGE")
    details = usage["output_tokens_details"]
    if terminal:
        details = _exact_keys(details, ("thinking_tokens",), "USAGE_SCHEMA_INVALID")
        _zero_number(details["thinking_tokens"], "NONZERO_INFERENCE_USAGE")
        _require(usage["iterations"] == [], "NONZERO_INFERENCE_USAGE")
        _require(type(usage["inference_geo"]) is str, "USAGE_SCHEMA_INVALID")
        _require(type(usage["service_tier"]) is str and type(usage["speed"]) is str, "USAGE_SCHEMA_INVALID")
    else:
        _require(details is None and usage["iterations"] is None, "NONZERO_INFERENCE_USAGE")
        _require(usage["inference_geo"] is None and usage["service_tier"] is None and usage["speed"] is None,
                 "NONZERO_INFERENCE_USAGE")
    _require(usage["fallback_credit"] is None, "NONZERO_INFERENCE_USAGE")


def _validate_system(event: Mapping[str, Any]) -> None:
    _exact_keys(event, _SYSTEM_KEYS, "SYSTEM_SCHEMA_INVALID")
    _require(event["type"] == "system" and event["subtype"] == "init", "SYSTEM_SCHEMA_INVALID")
    _require(event["model"] == EXPECTED_MODEL, "WRONG_SELECTED_MODEL")
    _require(event["permissionMode"] == "dontAsk", "PERMISSION_SEMANTICS_INVALID")
    _require(event["tools"] == [] and event["mcp_servers"] == [], "TOOL_ACTIVITY_FORBIDDEN")
    for key in ("slash_commands", "terminal_slash_commands", "agents", "skills", "capabilities", "additional_directories"):
        _string_list(event[key], "SYSTEM_SCHEMA_INVALID")
    _require(type(event["plugins"]) is list, "SYSTEM_SCHEMA_INVALID")
    for plugin in event["plugins"]:
        plugin = _exact_keys(plugin, ("name", "path", "source"), "SYSTEM_SCHEMA_INVALID")
        _require(all(type(value) is str for value in plugin.values()), "SYSTEM_SCHEMA_INVALID")
    for key in _SYSTEM_KEYS - {"tools", "mcp_servers", "slash_commands", "terminal_slash_commands", "agents", "skills", "plugins", "capabilities", "additional_directories", "per_turn_effort_active", "ultrathink_available", "ultrathink_typed_raises", "analytics_disabled", "product_feedback_disabled"}:
        _require(type(event[key]) is str, "SYSTEM_SCHEMA_INVALID")
    for key in ("per_turn_effort_active", "ultrathink_available", "ultrathink_typed_raises", "analytics_disabled", "product_feedback_disabled"):
        _require(type(event[key]) is bool, "SYSTEM_SCHEMA_INVALID")


def _validate_assistant(event: Mapping[str, Any]) -> int:
    _exact_keys(event, _ASSISTANT_KEYS, "ASSISTANT_SCHEMA_INVALID")
    _require(event["type"] == "assistant" and event["parent_tool_use_id"] is None, "ASSISTANT_SCHEMA_INVALID")
    run = _exact_keys(event["local_command_run"], ("command", "args"), "LOCAL_COMMAND_INVALID")
    _require(run["command"] == "model" and run["args"] == "", "LOCAL_COMMAND_INVALID")
    _require(type(event["local_command_source"]) is str, "LOCAL_COMMAND_INVALID")
    message = _exact_keys(event["message"], _MESSAGE_KEYS, "ASSISTANT_SCHEMA_INVALID")
    _require(message["type"] == "message" and message["role"] == "assistant", "ASSISTANT_SCHEMA_INVALID")
    _require(message["model"] == "<synthetic>", "ASSISTANT_SCHEMA_INVALID")
    _require(message["stop_reason"] == "end_turn", "ASSISTANT_SCHEMA_INVALID")
    for key in ("stop_sequence", "context_management", "stop_details", "container", "diagnostics"):
        _require(message[key] is None, "ASSISTANT_SCHEMA_INVALID")
    _validate_usage(message["usage"], terminal=False)
    _require(type(message["content"]) is list and len(message["content"]) >= 1, "ASSISTANT_SCHEMA_INVALID")
    for block in message["content"]:
        block = _exact_keys(block, ("type", "text"), "ASSISTANT_SCHEMA_INVALID")
        _require(block["type"] == "text" and type(block["text"]) is str, "ASSISTANT_SCHEMA_INVALID")
    for key in ("session_id", "uuid", "timestamp"):
        _require(type(event[key]) is str and bool(event[key]), "ASSISTANT_SCHEMA_INVALID")
    # This count is diagnostic only and never contributes to membership authority.
    return json.dumps(event, ensure_ascii=False).count(DISPLAY_TOKEN)


def _validate_zero_tree(value: Any) -> None:
    if isinstance(value, dict):
        for child in value.values():
            _validate_zero_tree(child)
    else:
        _zero_number(value, "NONZERO_MODEL_USAGE")


def _validate_result(event: Mapping[str, Any]) -> int:
    _exact_keys(event, _RESULT_KEYS, "RESULT_SCHEMA_INVALID")
    _require(event["type"] == "result" and event["subtype"] == "success", "RESULT_ERROR")
    _require(event["is_error"] is False and event["stop_reason"] is None, "RESULT_ERROR")
    _require(event["local_command"] == "model", "LOCAL_COMMAND_INVALID")
    _require(event["permission_denials"] == [] and event["safety_stops"] == 0, "PERMISSION_OR_SAFETY_ERROR")
    for key in ("total_cost_usd", "duration_api_ms", "num_turns", "queued_turn_count", "result_index"):
        _zero_number(event[key], "NONZERO_COST_OR_INFERENCE")
    _require(type(event["duration_ms"]) is int and event["duration_ms"] >= 0, "RESULT_SCHEMA_INVALID")
    _require(event["modelUsage"] == {} and event["model_usage_since_last_result"] == {}, "NONZERO_MODEL_USAGE")
    _validate_usage(event["usage"], terminal=True)
    stats = _exact_keys(
        event["subagent_stats"],
        ("requested", "spawned", "spawned_by_subagents", "started_in_background", "completed", "failed", "killed", "refused", "max_depth", "by_type"),
        "RESULT_SCHEMA_INVALID",
    )
    _require(stats["by_type"] == {}, "NONZERO_MODEL_USAGE")
    _exact_keys(stats["requested"], ("foreground", "background", "unset"), "RESULT_SCHEMA_INVALID")
    _exact_keys(stats["killed"], ("user", "system", "parent"), "RESULT_SCHEMA_INVALID")
    _exact_keys(stats["refused"], ("concurrency_limit", "depth_limit", "budget"), "RESULT_SCHEMA_INVALID")
    _validate_zero_tree({key: value for key, value in stats.items() if key != "by_type"})
    _require(type(event["result"]) is str, "RESULT_SCHEMA_INVALID")
    lines = event["result"].splitlines()
    _require(len(lines) == 2, "LOCAL_COMMAND_OUTPUT_INVALID")
    _require(lines[1].startswith("Usage: /model <name>. Available: "), "LOCAL_COMMAND_OUTPUT_INVALID")
    occurrences = event["result"].count(DISPLAY_TOKEN)
    _require(occurrences == 1, "EXACT_MODEL_MEMBERSHIP_REQUIRED")
    _require(lines[0] == "Current model: `Opus 5.5` (effort: low)", "WRONG_SELECTED_MODEL")
    return occurrences


def parse_frozen_catalog_jsonl(raw: bytes) -> Dict[str, Any]:
    """Parse frozen bytes and return only sanitized authority facts."""
    _require(type(raw) is bytes and 0 < len(raw) <= 65536 and raw.endswith(b"\n"), "JSONL_FRAMING_INVALID")
    lines = raw.splitlines()
    _require(1 <= len(lines) <= 64 and all(0 < len(line) <= 16384 for line in lines), "JSONL_FRAMING_INVALID")
    events: List[Mapping[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_reject_constant)
        except CatalogParseError:
            raise
        except (UnicodeError, ValueError, TypeError):
            raise CatalogParseError("JSONL_MALFORMED") from None
        _require(type(value) is dict, "EVENT_SCHEMA_INVALID")
        _reject_secrets(value)
        events.append(value)
    result_indexes = [index for index, event in enumerate(events) if event.get("type") == "result"]
    _require(len(result_indexes) == 1, "EXACTLY_ONE_RESULT_REQUIRED")
    result_index = result_indexes[0]
    _require(result_index == len(events) - 1, "RESULT_NOT_TERMINAL")
    _require(events[0].get("type") == "system", "SYSTEM_EVENT_REQUIRED")
    _validate_system(events[0])
    assistant_occurrences = 0
    for event in events[1:result_index]:
        _require(event.get("type") == "assistant", "EVENT_TYPE_UNSUPPORTED")
        assistant_occurrences += _validate_assistant(event)
    _require(result_index >= 2, "ASSISTANT_EVENT_REQUIRED")
    terminal_occurrences = _validate_result(events[result_index])
    return {
        "json_lines": len(events),
        "event_type_counts": {
            "system": 1,
            "assistant": result_index - 1,
            "result": 1,
        },
        "terminal_result_index": result_index,
        "exact_display_token": DISPLAY_TOKEN,
        "terminal_occurrences": terminal_occurrences,
        "assistant_occurrences_ignored": assistant_occurrences,
        "membership_authority": "terminal_result_only",
    }


def _verify_ref(path: Path, expected: Mapping[str, Any], code: str) -> bytes:
    _require(path.is_file() and not path.is_symlink(), code)
    raw = path.read_bytes()
    _require(len(raw) == expected["bytes"] and _sha256(raw) == expected["sha256"], code)
    return raw


def interpret_frozen_catalog(workspace_root: Path) -> Dict[str, Any]:
    """Interpret the exact frozen receipt/stdout pair without any live action."""
    root = Path(workspace_root).resolve()
    receipt_path = root / EXECUTION_RECEIPT_REF["path"]
    receipt_raw = _verify_ref(receipt_path, EXECUTION_RECEIPT_REF, "EXECUTION_RECEIPT_BINDING_MISMATCH")
    try:
        receipt = json.loads(receipt_raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except (UnicodeError, ValueError, TypeError):
        raise CatalogParseError("EXECUTION_RECEIPT_MALFORMED") from None
    _require(type(receipt) is dict and receipt.get("status") == "STOP_CATALOG_PREFLIGHT", "ORIGINAL_STOP_NOT_PRESERVED")
    stdout = receipt.get("private_raw", {}).get("stdout")
    _require(type(stdout) is dict and stdout == STDOUT_REF, "STDOUT_REF_BINDING_MISMATCH")
    stdout_path = Path(STDOUT_REF["path"])
    _require(oct(os.stat(stdout_path, follow_symlinks=False).st_mode & 0o777) == "0o600", "STDOUT_MODE_MISMATCH")
    raw = _verify_ref(stdout_path, STDOUT_REF, "STDOUT_BINDING_MISMATCH")
    observed = parse_frozen_catalog_jsonl(raw)
    return {
        "version": "r6-o1-claude-catalog-membership-interpretation-receipt-1",
        "status": STATUS,
        "parser": "r6_one_off_claude_catalog_parser_v1",
        "execution_receipt": dict(EXECUTION_RECEIPT_REF),
        "owner_private_stdout_ref": dict(STDOUT_REF),
        "original_execution_status": "STOP_CATALOG_PREFLIGHT",
        "observed": observed,
        "effects": {
            "provider_requests": 0,
            "network": 0,
            "account": 0,
            "inference": 0,
            "retry": 0,
            "replay": 0,
            "business": 0,
        },
        "claim_limits": [
            "frozen catalog membership evidence only",
            "not execution PASS",
            "not inference success",
            "not countable A/B",
            "raw remains owner-private",
        ],
        "interpretation": "The prior occurrence count was overbroad because assistant streaming copies are non-authoritative; exact membership occurs once in the sole terminal result.",
    }
