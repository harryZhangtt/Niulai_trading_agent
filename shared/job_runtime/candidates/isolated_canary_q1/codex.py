"""Pure Codex 0.167 invocation planning and fail-closed JSONL translation."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from typing import Any, Mapping

from .canonical import canonical_json_bytes, sha256_bytes, strict_json_loads
from .codex_contracts import CapabilityGateV1, CaptureEnvelopeV1, CodexCandidateError, InvocationPlanV1, PromptBytesV1, TranslationReceiptV1


def _sha(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def load_authority_manifest(path: Path | None = None) -> Mapping[str, Any]:
    target = path or Path(__file__).with_name("authority-manifest-v1.json")
    try:
        raw = target.read_bytes()
        if sha256_bytes(raw) != "1cf1d9000e282eebe0ac067f156876ffd1db3e113eab66aef0bacf7ee035eb34":
            raise CodexCandidateError("CODEX_Q1_AUTHORITY_INVALID")
        value = strict_json_loads(raw, maximum=65_536)
    except Exception:
        raise CodexCandidateError("CODEX_Q1_AUTHORITY_INVALID") from None
    keys = {"schema_version", "candidate_id", "repository", "tag", "commit", "tree_sha", "archive_sha256", "binary", "source_blocks", "grammar_inventory_sha256", "retry", "source_authority_complete"}
    if type(value) is not dict or set(value) != keys or value["schema_version"] != 1 or value["candidate_id"] != "codex-rust-0.167-isolated-canary-q1" or value["repository"] != "openai/codex" or value["tag"] != "rust-v0.167.0" or value["commit"] != "086ccc833bc9cf01024ad2dd6af7dbd421b6bf9a" or not all(_sha(value[field]) for field in ("archive_sha256", "grammar_inventory_sha256")) or value["source_authority_complete"] is not False:
        raise CodexCandidateError("CODEX_Q1_AUTHORITY_INVALID")
    if not re.fullmatch(r"[0-9a-f]{40}", value["tree_sha"]):
        raise CodexCandidateError("CODEX_Q1_AUTHORITY_INVALID")
    binary = value["binary"]
    if type(binary) is not dict or set(binary) != {"asset_binding_verified", "sha256", "size", "version"} or type(binary["asset_binding_verified"]) is not bool or not _sha(binary["sha256"]) or type(binary["size"]) is not int or binary["size"] < 1 or binary["version"] != "0.167.0":
        raise CodexCandidateError("CODEX_Q1_AUTHORITY_INVALID")
    blocks = value["source_blocks"]
    if type(blocks) is not dict or set(blocks) != {"thread_event_sha256", "thread_item_details_sha256"} or not all(_sha(item) for item in blocks.values()):
        raise CodexCandidateError("CODEX_Q1_AUTHORITY_INVALID")
    retry = value["retry"]
    expected = {"request_default": 4, "stream_default": 5, "request_key": "request_max_retries", "stream_key": "stream_max_retries", "request_target": 0, "stream_target": 0}
    if retry != expected:
        raise CodexCandidateError("CODEX_Q1_AUTHORITY_INVALID")
    return value


def capability_gate() -> CapabilityGateV1:
    try:
        manifest = load_authority_manifest()
        source = manifest["source_authority_complete"] is True
    except CodexCandidateError:
        source = False
    return CapabilityGateV1(source, source, False, False, False, False, False, False)


def build_invocation_plan(*, prompt: PromptBytesV1, configured_model: str, effort: str, final_output_token: str) -> InvocationPlanV1:
    if type(prompt) is not PromptBytesV1:
        raise CodexCandidateError("CODEX_Q1_PROMPT_TYPE_INVALID")
    if type(configured_model) is not str or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", configured_model) is None or effort not in {"low", "medium", "high"} or type(final_output_token) is not str or re.fullmatch(r"@[A-Za-z0-9._-]{1,64}", final_output_token) is None:
        raise CodexCandidateError("CODEX_Q1_AUTHORITY_INVALID")
    if prompt.sha256 != sha256_bytes(prompt.raw) or prompt.length != len(prompt.raw):
        raise CodexCandidateError("CODEX_Q1_PROMPT_BINDING_MISMATCH")
    argv = ("codex", "exec", "--ignore-user-config", "--ephemeral", "--strict-config", "--json", "--sandbox", "read-only", "--model", configured_model, "-c", "request_max_retries=0", "-c", "stream_max_retries=0", "-c", f'model_reasoning_effort="{effort}"', "--output-last-message", final_output_token, "-")
    if argv.count("request_max_retries=0") != 1 or argv.count("stream_max_retries=0") != 1:
        raise CodexCandidateError("CODEX_Q1_RETRY_ZERO_UNPROVEN")
    return InvocationPlanV1(argv, (prompt.raw,), prompt.sha256, prompt.length, configured_model, effort, final_output_token, sha256_bytes(canonical_json_bytes(list(argv))))


def _lines(raw: bytes) -> list[dict[str, Any]]:
    if type(raw) is not bytes or not 1 <= len(raw) <= 1_048_576:
        raise CodexCandidateError("CODEX_Q1_CAPTURE_SIZE_INVALID")
    if not raw.endswith(b"\n"):
        raise CodexCandidateError("CODEX_Q1_CAPTURE_TRUNCATED")
    values = []
    for line in raw.splitlines():
        if not line:
            raise CodexCandidateError("CODEX_Q1_EVENT_MALFORMED")
        try:
            value = strict_json_loads(line, maximum=131_072)
        except Exception as exc:
            code = getattr(exc, "code", "CODEX_Q1_EVENT_MALFORMED")
            if code == "CANARY_JSON_DUPLICATE_KEY":
                code = "CODEX_Q1_EVENT_DUPLICATE_KEY"
            raise CodexCandidateError(code if code.startswith("CODEX_Q1_") else "CODEX_Q1_EVENT_MALFORMED") from None
        if type(value) is not dict:
            raise CodexCandidateError("CODEX_Q1_EVENT_MALFORMED")
        values.append(value)
    return values


def _unknown(code: str, events: list[object], counts: Counter, tool: bool, capture: CaptureEnvelopeV1) -> TranslationReceiptV1:
    return TranslationReceiptV1(1, "unknown", code, "streaming", "possibly_submitted", "missing", len(events), dict(counts), tool, False, False, False, "configured_cli_argument", False, None, False, False)


def _item_valid(item: dict[str, Any]) -> bool:
    schemas = {
        "agent_message": ({"id", "type", "text"}, {"text": str}),
        "reasoning": ({"id", "type", "text"}, {"text": str}),
        "command_execution": ({"id", "type", "command", "status"}, {"command": str, "status": str}),
        "file_change": ({"id", "type", "changes", "status"}, {"changes": list, "status": str}),
        "mcp_tool_call": ({"id", "type", "server", "tool", "status"}, {"server": str, "tool": str, "status": str}),
        "collab_tool_call": ({"id", "type", "tool", "status"}, {"tool": str, "status": str}),
        "web_search": ({"id", "type", "query", "status"}, {"query": str, "status": str}),
        "todo_list": ({"id", "type", "items"}, {"items": list}),
        "error": ({"id", "type", "message"}, {"message": str}),
    }
    kind = item.get("type")
    if kind not in schemas or set(item) != schemas[kind][0] or type(item.get("id")) is not str or not item["id"] or "model" in item:
        return False
    if not all(type(item[key]) is expected for key, expected in schemas[kind][1].items()):
        return False
    if kind in {"agent_message", "reasoning", "error"}:
        try:
            item[next(iter(schemas[kind][1]))].encode("utf-8")
        except UnicodeEncodeError:
            return False
    return True


def _usage_valid(value: object) -> bool:
    if value is None:
        return True
    if type(value) is not dict or not set(value) <= {"input_tokens", "output_tokens", "cached_input_tokens"}:
        return False
    return all(type(number) is int and number >= 0 for number in value.values())


def translate(capture: CaptureEnvelopeV1, plan: InvocationPlanV1 | None = None) -> TranslationReceiptV1:
    if type(capture) is not CaptureEnvelopeV1 or type(plan) is not InvocationPlanV1:
        return _unknown("CODEX_Q1_PROCESS_CONTRADICTORY", [], Counter(), False, capture)
    try:
        plan.__post_init__()
    except CodexCandidateError:
        return _unknown("CODEX_Q1_RETRY_ZERO_UNPROVEN", [], Counter(), False, capture)
    prompt_ok = capture.prompt_delivery_complete and capture.prompt_sent_length == plan.stdin_length and capture.prompt_length == plan.stdin_length and capture.prompt_sha256 == plan.stdin_sha256
    launch_ok = capture.launch_binding_sha256 == plan.argv_sha256 and capture.retry_zero_observed
    output_self_ok = bool(capture.final_output and capture.final_output.custody_verified and capture.final_output.size > 0 and capture.final_output.sha256 == sha256_bytes(capture.final_output.raw))
    try:
        events = _lines(capture.stdout_jsonl)
    except CodexCandidateError as error:
        return _unknown(error.code, [], Counter(), False, capture)
    started = False; turn = False; terminal = None; items: dict[str, tuple[str, str]] = {}; counts = Counter(); tool = False; agent_messages: list[str] = []
    allowed_tools = {"command_execution", "file_change", "mcp_tool_call", "web_search", "collab_tool_call"}
    for index, event in enumerate(events):
        etype = event.get("type")
        if terminal is not None:
            return _unknown("CODEX_Q1_EVENT_AFTER_TERMINAL", events, counts, tool, capture)
        if etype == "thread.started":
            if index != 0 or started or set(event) != {"type", "thread_id"} or type(event["thread_id"]) is not str:
                return _unknown("CODEX_Q1_EVENT_ORDER_INVALID", events, counts, tool, capture)
            started = True
        elif etype == "turn.started":
            if index != 1 or not started or turn or set(event) != {"type"}:
                return _unknown("CODEX_Q1_EVENT_ORDER_INVALID", events, counts, tool, capture)
            turn = True
        elif etype in {"item.started", "item.updated", "item.completed"}:
            if not turn or set(event) != {"type", "item"} or type(event["item"]) is not dict or not _item_valid(event["item"]):
                return _unknown("CODEX_Q1_EVENT_FIELDS_INVALID", events, counts, tool, capture)
            item = event["item"]; ident = item["id"]; kind = item["type"]; state = items.get(ident)
            if kind in allowed_tools:
                tool = True
            if etype == "item.started":
                if state is not None:
                    return _unknown("CODEX_Q1_ITEM_ORDER_INVALID", events, counts, tool, capture)
                items[ident] = (kind, "started")
            elif etype == "item.updated":
                if state != (kind, "started"):
                    return _unknown("CODEX_Q1_ITEM_ORDER_INVALID", events, counts, tool, capture)
            else:
                if state is not None and state != (kind, "started"):
                    return _unknown("CODEX_Q1_ITEM_ORDER_INVALID", events, counts, tool, capture)
                items[ident] = (kind, "completed"); counts[kind] += 1
                if kind == "agent_message":
                    agent_messages.append(item["text"])
        elif etype == "turn.completed":
            if "model" in event:
                return _unknown("CODEX_Q1_EVENT_UNSUPPORTED", events, counts, tool, capture)
            if not turn or not set(event) <= {"type", "usage"} or not _usage_valid(event.get("usage")) or any(state != "completed" for _kind, state in items.values()):
                return _unknown("CODEX_Q1_EVENT_ORDER_INVALID", events, counts, tool, capture)
            terminal = etype
        elif etype == "turn.failed":
            if not turn or set(event) != {"type", "error"} or capture.process_phase != "terminal":
                return _unknown("CODEX_Q1_PROCESS_CONTRADICTORY", events, counts, tool, capture)
            terminal = etype
        elif etype == "error":
            if not turn or set(event) != {"type", "message"} or capture.process_phase != "terminal":
                return _unknown("CODEX_Q1_PROCESS_CONTRADICTORY", events, counts, tool, capture)
            terminal = etype
        else:
            return _unknown("CODEX_Q1_EVENT_UNSUPPORTED", events, counts, tool, capture)
    if terminal is None:
        return _unknown("CODEX_Q1_TERMINAL_MISSING", events, counts, tool, capture)
    if capture.process_phase != "terminal":
        return _unknown("CODEX_Q1_PROCESS_CONTRADICTORY", events, counts, tool, capture)
    output_ok = bool(output_self_ok and len(agent_messages) >= 1 and capture.final_output and capture.final_output.raw == agent_messages[-1].encode("utf-8"))
    if terminal == "turn.failed": status, code = "failed", "CODEX_Q1_TURN_FAILED"
    elif terminal == "error": status, code = "failed", "CODEX_Q1_RUNNER_ERROR"
    elif tool: status, code = "failed", "CODEX_Q1_TOOL_POLICY_VIOLATION"
    elif capture.exit_code == 0 and capture.signal is None and prompt_ok and launch_ok and output_ok: status, code = "succeeded", "CODEX_Q1_COMPLETED"
    else: status, code = "unknown", "CODEX_Q1_PROCESS_CONTRADICTORY"
    return TranslationReceiptV1(1, status, code, "terminal", "definitely_submitted", terminal, len(events), dict(counts), tool, launch_ok, prompt_ok, output_ok, "configured_cli_argument", False, None, False, False)
