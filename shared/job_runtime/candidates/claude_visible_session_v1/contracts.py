"""Strict, provider-free validators for frozen visible-session evidence.

There is deliberately no provider SDK, process, network, CLI, or activation
adapter in this module. Import constructs constants only and performs no I/O.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Iterable, Mapping, Sequence


def _freeze(value: Any) -> Any:
    """Recursively freeze validation authority at module construction."""
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """Create a disposable JSON-shaped comparison value from frozen authority."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


_MODEL_ID = "claude-opus-5-5"
_MODEL_DISPLAY_NAME = "Claude Opus 5.5"
_EFFORT = "low"
_TERMINAL_STATES = frozenset(("succeeded", "failed", "cancelled", "timed_out"))
_POLL_STATES = frozenset(("queued", "running")) | _TERMINAL_STATES
_FORBIDDEN_PRIVACY_MARKERS = (
    "ixic", "niulai-private", "private_state", "private-state", "/private/",
)
_FROZEN_BUDGETS = _freeze({
    "R9": {"max_wall_seconds": 60, "max_output_tokens": 512, "max_tool_calls": 1},
    "R10": {"max_wall_seconds": 120, "max_output_tokens": 2048, "max_tool_calls": 4},
})
_FROZEN_OBSERVED_BUDGETS = _freeze({
    "R9": {"wall_seconds": 2, "output_tokens": 128, "tool_calls": 1},
    "R10": {"wall_seconds": 3, "output_tokens": 512, "tool_calls": 4},
})
_FROZEN_REQUEST_EVENTS = _freeze({
    "R9": [{"logical_request_id": "r9-parent", "attempt": 1, "actor": "parent", "kind": "gateway_request"}],
    "R10": [
        {"logical_request_id": "r10-parent", "attempt": 1, "actor": "parent", "kind": "gateway_request"},
        {"logical_request_id": "r10-child-1", "attempt": 1, "actor": "child-1", "kind": "gateway_request"},
    ],
})
_FROZEN_TOOL_EVENTS = _freeze({
    "R9": [
        {"ordinal": 1, "actor": "parent", "tool": "Read", "target": "r9/abc.bin", "status": "succeeded"},
    ],
    "R10": [
        {"ordinal": 1, "actor": "parent", "tool": "Agent", "target": "child-1", "status": "succeeded"},
        {"ordinal": 2, "actor": "child-1", "tool": "Glob", "target": "r10/*.json", "status": "succeeded"},
        {"ordinal": 3, "actor": "child-1", "tool": "Grep", "target": "S1|S2|S3", "status": "succeeded"},
        {"ordinal": 4, "actor": "child-1", "tool": "Read", "target": "r10/skills-input.json", "status": "succeeded"},
    ],
})
_FROZEN_POLLS = _freeze({
    "R9": [
        {"ordinal": 1, "status": "running", "observed_at": "2099-01-01T00:00:01Z"},
        {"ordinal": 2, "status": "succeeded", "observed_at": "2099-01-01T00:00:02Z"},
    ],
    "R10": [
        {"ordinal": 1, "status": "queued", "observed_at": "2099-01-01T00:00:01Z"},
        {"ordinal": 2, "status": "running", "observed_at": "2099-01-01T00:00:02Z"},
        {"ordinal": 3, "status": "succeeded", "observed_at": "2099-01-01T00:00:03Z"},
    ],
})
_R10_INPUT_SHA256 = "c084f6a3d0f3ad095ab9508535f923af137545d8f4d55af5aeea9a8ba725fbae"
_R10_AGENT_SHA256 = "a593f09aba8317d9505f66393c07ec1f9e71d932132b034921be0c2b72432cad"
_R10_OUTPUT_SHA256 = "62f2f92246cf4392b11628d7dfb1a106cbcb8a1921f9ce4a3f08699e5615cae6"
_FROZEN_TERMINALS = _freeze({
    "R9": {
        "status": "succeeded", "completed_at": "2099-01-01T00:00:02Z",
        "output": {"sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "bytes": 3},
        "children": [],
    },
    "R10": {
        "status": "succeeded", "completed_at": "2099-01-01T00:00:03Z",
        "output": {"skill_ids": ["S1", "S2", "S3"], "input_sha256": _R10_INPUT_SHA256, "agent_definition_sha256": _R10_AGENT_SHA256, "output_sha256": _R10_OUTPUT_SHA256},
        "children": [{"id": "child-1", "agent_definition": "r10/agent-definition.json", "agent_definition_sha256": _R10_AGENT_SHA256, "status": "succeeded", "output_path": "r10/mining-output.json"}],
    },
})
_FROZEN_CLEANUPS = _freeze({
    "R9": {"status": "complete", "completed_at": "2099-01-01T00:00:03Z", "active_children": 0, "session_retained_visible": True, "stopped_resources": []},
    "R10": {"status": "complete", "completed_at": "2099-01-01T00:00:04Z", "active_children": 0, "session_retained_visible": True, "stopped_resources": ["child-1"]},
})

# Path construction only. Unlike resolve/stat/open, this performs no filesystem I/O.
_FROZEN_CASES_PATH = Path(__file__).parent / "frozen_cases.json"

_R10_INPUT_DOCUMENT = _freeze({
    "skills": [
        {"id": "S1", "name": "Amber Index", "files": ["amber.md"]},
        {"id": "S2", "name": "Birch Ledger", "files": ["birch.md", "birch.json"]},
        {"id": "S3", "name": "Cobalt Lens", "files": ["cobalt.txt"]},
    ]
})
_R10_AGENT_DOCUMENT = _freeze({
    "schema_version": "static-readonly-agent-v1", "name": "synthetic-skill-miner",
    "description": "Mine only the supplied invented S1-S3 fixture",
    "model_id": _MODEL_ID, "effort": _EFFORT,
    "tools": {"allow": ["Glob", "Grep", "Read"], "deny": ["Agent", "Bash", "Edit", "WebFetch", "WebSearch", "Write"]},
    "max_depth": 0, "max_concurrency": 1, "retries": 0,
})
_R10_OUTPUT_DOCUMENT = _freeze({
    "schema_version": "synthetic-skill-mining-v1",
    "skills": [
        {"id": "S1", "name": "Amber Index", "file_count": 1, "capability": "index synthetic amber records"},
        {"id": "S2", "name": "Birch Ledger", "file_count": 2, "capability": "reconcile synthetic birch entries"},
        {"id": "S3", "name": "Cobalt Lens", "file_count": 1, "capability": "inspect synthetic cobalt samples"},
    ],
})


class ContractError(ValueError):
    """Raised when a frozen contract or evidence bundle is not exact."""


def _fail(path: str, message: str) -> None:
    raise ContractError("{0}: {1}".format(path, message))


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    return value


def _sequence(value: Any, path: str) -> Sequence[Any]:
    if not isinstance(value, list):
        _fail(path, "must be an array")
    return value


def _exact_keys(value: Mapping[str, Any], expected: Iterable[str], path: str) -> None:
    expected_set = set(expected)
    actual = set(value)
    if actual != expected_set:
        _fail(path, "keys differ; missing={0}, extra={1}".format(
            sorted(expected_set - actual), sorted(actual - expected_set)
        ))


def _strict_equal(value: Any, expected: Any) -> bool:
    """Equality that never treats booleans as integers."""
    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(value) == set(expected) and all(
            _strict_equal(value[key], expected[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(value) == len(expected) and all(
            _strict_equal(left, right) for left, right in zip(value, expected)
        )
    return bool(value == expected)


def _equal(value: Any, expected: Any, path: str) -> None:
    if not _strict_equal(value, expected):
        _fail(path, "expected {0!r}, got {1!r}".format(expected, value))


def _positive_int(value: Any, path: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(path, "must be an integer >= {0}".format(minimum))
    return value


def _nonempty(value: Any, path: str) -> str:
    if type(value) is not str or not value:
        _fail(path, "must be a non-empty string")
    return value


def _timestamp(value: Any, path: str) -> datetime:
    _nonempty(value, path)
    if len(value) != 20 or value[4] != "-" or value[7] != "-" or value[10] != "T" or value[13] != ":" or value[16] != ":" or value[19] != "Z":
        _fail(path, "must be canonical UTC RFC3339 YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        _fail(path, "must be a valid canonical UTC RFC3339 timestamp")
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        _fail(path, "must use canonical UTC RFC3339 formatting")
    return parsed


def _scan_privacy(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _scan_privacy(key, path + ".<key>")
            _scan_privacy(item, path + "." + str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_privacy(item, "{0}[{1}]".format(path, index))
    elif isinstance(value, str):
        lowered = value.lower()
        for marker in _FORBIDDEN_PRIVACY_MARKERS:
            if marker in lowered:
                _fail(path, "contains forbidden privacy marker")


def _json_payload(payload: bytes, path: str) -> Any:
    if type(payload) is not bytes:
        _fail(path, "must be bytes")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail(path, "must be UTF-8 JSON")


def load_frozen_cases() -> Dict[str, Any]:
    """Explicitly load candidate data; import itself remains I/O-free."""
    with _FROZEN_CASES_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_case(case: Any) -> None:
    case = _mapping(case, "$case")
    _scan_privacy(case)
    _exact_keys(case, (
        "schema_version", "case_id", "purpose", "session", "budget", "retries",
        "persistence", "tools", "topology", "gateway_requests",
        "future_slot_binding", "fixture",
    ), "$case")
    _equal(case["schema_version"], "claude-visible-session-case-v1", "$case.schema_version")
    case_id = case["case_id"]
    if type(case_id) is not str or case_id not in ("R9", "R10"):
        _fail("$case.case_id", "must be R9 or R10")
    expected_purpose = {
        "R9": "Read-only digest of the three-byte abc fixture",
        "R10": "Exactly one read-only child mines three synthetic skills",
    }[case_id]
    _equal(case["purpose"], expected_purpose, "$case.purpose")

    _equal(case["session"], {
        "name": "claude-visible-{0}-v1".format(case_id.lower()),
        "model_id": _MODEL_ID, "model_display_name": _MODEL_DISPLAY_NAME, "effort": _EFFORT,
    }, "$case.session")
    _equal(case["budget"], _thaw(_FROZEN_BUDGETS[case_id]), "$case.budget")
    _equal(case["retries"], {"provider": 0, "transport": 0, "task": 0}, "$case.retries")
    _equal(case["persistence"], {"visible": True, "persist": True, "resume": False}, "$case.persistence")

    expected_tools = {
        "R9": {
            "parent_allow": ["Read"],
            "parent_deny": ["Agent", "Bash", "Edit", "Glob", "Grep", "WebFetch", "WebSearch", "Write"],
            "child_allow": [],
            "child_deny": ["Agent", "Bash", "Edit", "Glob", "Grep", "Read", "WebFetch", "WebSearch", "Write"],
        },
        "R10": {
            "parent_allow": ["Agent"],
            "parent_deny": ["Bash", "Edit", "Glob", "Grep", "Read", "WebFetch", "WebSearch", "Write"],
            "child_allow": ["Glob", "Grep", "Read"],
            "child_deny": ["Agent", "Bash", "Edit", "WebFetch", "WebSearch", "Write"],
        },
    }
    _equal(case["tools"], expected_tools[case_id], "$case.tools")
    _equal(case["topology"], {
        "max_depth": 0 if case_id == "R9" else 1,
        "max_concurrency": 1,
        "exact_child_count": 0 if case_id == "R9" else 1,
    }, "$case.topology")
    expected_requests = 1 if case_id == "R9" else 2
    _equal(case["gateway_requests"], {
        "exact_logical": expected_requests, "max_attempts_total": expected_requests,
    }, "$case.gateway_requests")
    _equal(case["future_slot_binding"], {
        "slot_id": "slot-2099-01-01T00:00:00Z-" + case_id.lower(),
        "scheduled_for": "2099-01-01T00:00:00Z",
        "request_id": "request-" + case_id.lower() + "-v1",
    }, "$case.future_slot_binding")
    _timestamp(case["future_slot_binding"]["scheduled_for"], "$case.future_slot_binding.scheduled_for")

    expected_fixture = {
        "R9": {
            "relative_path": "r9/abc.bin", "bytes": 3,
            "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        },
        "R10": {
            "input_path": "r10/skills-input.json", "input_sha256": _R10_INPUT_SHA256,
            "agent_definition_path": "r10/agent-definition.json", "agent_definition_sha256": _R10_AGENT_SHA256,
            "output_path": "r10/mining-output.json", "output_sha256": _R10_OUTPUT_SHA256,
            "skill_ids": ["S1", "S2", "S3"],
        },
    }
    _equal(case["fixture"], expected_fixture[case_id], "$case.fixture")


def validate_fixture_payloads(case: Any, payloads: Any) -> None:
    """Bind exact fixture bytes to their frozen hashes and JSON semantics."""
    validate_case(case)
    case = _mapping(case, "$case")
    payloads = _mapping(payloads, "$payloads")
    case_id = case["case_id"]
    if case_id == "R9":
        _exact_keys(payloads, ("r9/abc.bin",), "$payloads")
        payload = payloads["r9/abc.bin"]
        if type(payload) is not bytes:
            _fail("$payloads.r9/abc.bin", "must be bytes")
        _equal(payload, b"abc", "$payloads.r9/abc.bin")
        _equal(hashlib.sha256(payload).hexdigest(), case["fixture"]["sha256"], "$payloads.r9/abc.bin.sha256")
        return

    expected = {
        "r10/skills-input.json": ("input_sha256", _R10_INPUT_DOCUMENT),
        "r10/agent-definition.json": ("agent_definition_sha256", _R10_AGENT_DOCUMENT),
        "r10/mining-output.json": ("output_sha256", _R10_OUTPUT_DOCUMENT),
    }
    _exact_keys(payloads, expected, "$payloads")
    for relative_path, (hash_key, semantic_document) in expected.items():
        payload = payloads[relative_path]
        if type(payload) is not bytes:
            _fail("$payloads." + relative_path, "must be bytes")
        _equal(hashlib.sha256(payload).hexdigest(), case["fixture"][hash_key], "$payloads." + relative_path + ".sha256")
        parsed = _json_payload(payload, "$payloads." + relative_path)
        _scan_privacy(parsed, "$payloads." + relative_path)
        _equal(parsed, _thaw(semantic_document), "$payloads." + relative_path + ".semantics")


def validate_cli_placeholder(value: Any) -> None:
    value = _mapping(value, "$cli")
    _equal(value, {
        "schema_version": "claude-visible-cli-placeholder-v1",
        "semantic_contract_id": "claude-visible-cli-semantics-v1",
        "enabled": False, "invocation_prohibited": True,
        "cli_executable": None, "cli_version": None, "grammar": None,
        "required_operations": ["background", "list", "log", "attach", "stop"],
        "conformance_status": "missing",
        "activation_requirement": "Supply and test exact version-pinned grammar for every required operation before enabling",
    }, "$cli")


def validate_evidence_bundle(case: Any, evidence: Any) -> None:
    validate_case(case)
    case = _mapping(case, "$case")
    evidence = _mapping(evidence, "$evidence")
    _scan_privacy(evidence)
    _exact_keys(evidence, (
        "schema_version", "case_id", "session_name", "future_slot_binding",
        "request_events", "tool_events", "budget_observed", "polls", "terminal", "cleanup",
    ), "$evidence")
    case_id = case["case_id"]
    _equal(evidence["schema_version"], "claude-visible-session-evidence-v1", "$evidence.schema_version")
    _equal(evidence["case_id"], case_id, "$evidence.case_id")
    _equal(evidence["session_name"], case["session"]["name"], "$evidence.session_name")
    _equal(evidence["future_slot_binding"], case["future_slot_binding"], "$evidence.future_slot_binding")

    _equal(evidence["request_events"], _thaw(_FROZEN_REQUEST_EVENTS[case_id]), "$evidence.request_events")
    _equal(evidence["tool_events"], _thaw(_FROZEN_TOOL_EVENTS[case_id]), "$evidence.tool_events")
    _equal(evidence["budget_observed"], _thaw(_FROZEN_OBSERVED_BUDGETS[case_id]), "$evidence.budget_observed")
    observed = evidence["budget_observed"]
    if observed["wall_seconds"] > case["budget"]["max_wall_seconds"] or observed["output_tokens"] > case["budget"]["max_output_tokens"] or observed["tool_calls"] > case["budget"]["max_tool_calls"]:
        _fail("$evidence.budget_observed", "exceeds frozen budget")
    _equal(observed["tool_calls"], len(evidence["tool_events"]), "$evidence.budget_observed.tool_calls")

    polls = _sequence(evidence["polls"], "$evidence.polls")
    _equal(polls, _thaw(_FROZEN_POLLS[case_id]), "$evidence.polls")
    if len(polls) < 2:
        _fail("$evidence.polls", "must contain progress and terminal polls")
    prior_time = _timestamp(case["future_slot_binding"]["scheduled_for"], "$case.future_slot_binding.scheduled_for")
    terminal_count = 0
    previous_status = None
    allowed_transitions = {
        None: ("queued", "running"), "queued": ("running",), "running": ("running", "succeeded"),
    }
    for index, raw_poll in enumerate(polls):
        path = "$evidence.polls[{0}]".format(index)
        poll = _mapping(raw_poll, path)
        _exact_keys(poll, ("ordinal", "status", "observed_at"), path)
        _equal(poll["ordinal"], index + 1, path + ".ordinal")
        if type(poll["status"]) is not str or poll["status"] not in _POLL_STATES:
            _fail(path + ".status", "unknown status")
        if poll["status"] not in allowed_transitions.get(previous_status, ()):
            _fail(path + ".status", "illegal status transition")
        observed_at = _timestamp(poll["observed_at"], path + ".observed_at")
        if observed_at <= prior_time:
            _fail(path + ".observed_at", "must be strictly later than the prior timestamp")
        prior_time = observed_at
        previous_status = poll["status"]
        if poll["status"] in _TERMINAL_STATES:
            terminal_count += 1
            if index != len(polls) - 1:
                _fail(path + ".status", "terminal poll must be last")
    _equal(terminal_count, 1, "$evidence.polls.terminal_count")

    terminal = _mapping(evidence["terminal"], "$evidence.terminal")
    _equal(terminal, _thaw(_FROZEN_TERMINALS[case_id]), "$evidence.terminal")
    _exact_keys(terminal, ("status", "completed_at", "output", "children"), "$evidence.terminal")
    _equal(terminal["status"], "succeeded", "$evidence.terminal.status")
    _equal(terminal["status"], polls[-1]["status"], "$evidence.terminal.status")
    terminal_time = _timestamp(terminal["completed_at"], "$evidence.terminal.completed_at")
    _equal(terminal["completed_at"], polls[-1]["observed_at"], "$evidence.terminal.completed_at")
    children = _sequence(terminal["children"], "$evidence.terminal.children")
    if case_id == "R9":
        _equal(children, [], "$evidence.terminal.children")
        _equal(terminal["output"], {"sha256": case["fixture"]["sha256"], "bytes": 3}, "$evidence.terminal.output")
    else:
        _equal(children, [{
            "id": "child-1", "agent_definition": case["fixture"]["agent_definition_path"],
            "agent_definition_sha256": case["fixture"]["agent_definition_sha256"],
            "status": "succeeded", "output_path": case["fixture"]["output_path"],
        }], "$evidence.terminal.children")
        _equal(terminal["output"], {
            "skill_ids": ["S1", "S2", "S3"],
            "input_sha256": case["fixture"]["input_sha256"],
            "agent_definition_sha256": case["fixture"]["agent_definition_sha256"],
            "output_sha256": case["fixture"]["output_sha256"],
        }, "$evidence.terminal.output")

    cleanup = _mapping(evidence["cleanup"], "$evidence.cleanup")
    _equal(cleanup, _thaw(_FROZEN_CLEANUPS[case_id]), "$evidence.cleanup")
    _equal(cleanup, {
        "status": "complete", "completed_at": cleanup.get("completed_at"),
        "active_children": 0, "session_retained_visible": True,
        "stopped_resources": ["child-1"] if case_id == "R10" else [],
    }, "$evidence.cleanup")
    cleanup_time = _timestamp(cleanup["completed_at"], "$evidence.cleanup.completed_at")
    if cleanup_time <= terminal_time:
        _fail("$evidence.cleanup.completed_at", "must be strictly later than terminal completion")
