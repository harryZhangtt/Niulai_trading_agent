"""Bounded official Claude Agent SDK bridge with sealed local custody evidence."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import inspect
import json
import math
import os
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .provider_contract import ProviderResultV1
from .providers.claude_host import (
    CLAUDE_HOST_EVIDENCE_VERSION,
    DISPATCH_JOURNAL_VERSION,
    HOST_IDENTITY_VERSION,
    TERMINAL_PROOF_VERSION,
    WorkspaceEvidenceResolver,
    normalize_invocation,
)


def _capability(*, efforts: tuple[str, ...], max_budget_usd: float) -> Mapping[str, Any]:
    return MappingProxyType({
        "efforts": frozenset(efforts),
        "max_budget_usd": max_budget_usd,
        "max_turns": 1,
        "max_retries": 0,
        "tools_enabled": False,
        "settings_enabled": False,
        "fallback_enabled": False,
        "minimum_python": (3, 10),
        "required_option_fields": frozenset({
            "model", "effort", "tools", "mcp_servers", "strict_mcp_config",
            "agents", "skills", "permission_mode", "max_turns",
            "max_budget_usd", "env", "setting_sources",
            "include_partial_messages",
        }),
    })


CLAUDE_MODEL_CAPABILITIES = MappingProxyType({
    "claude-opus-5-5": _capability(
        efforts=("low", "medium", "high"), max_budget_usd=0.02),
    "claude-fable-5-1": _capability(efforts=("low",), max_budget_usd=0.02),
})
CLAUDE_BRIDGE_CAPABILITY = MappingProxyType({
    "source_reviewed": False,
    "live_verified": False,
    "production_enabled": False,
})

_PROFILE_FIELDS = frozenset({
    "model", "effort", "timeout_seconds", "auth_home", "max_budget_usd",
})



class ClaudeBridgeError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _event_hash(value: Mapping[str, Any]) -> str:
    return _sha(_canonical({key: item for key, item in value.items() if key != "event_sha256"}))


def _write(root: Path, name: str, value: Any, binary: bool = False) -> dict[str, Any]:
    path = root / "private" / name
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    raw = value if binary else _canonical(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(path.relative_to(root)), "sha256": _sha(raw)}


def _identity(root: Path, kind: str, operation: str, dispatch: str,
              input_sha: str, identity: str) -> dict[str, Any]:
    return _write(root, kind + ".json", {
        "schema_version": HOST_IDENTITY_VERSION,
        "kind": kind,
        "operation_id": operation,
        "dispatch_id": dispatch,
        "input_sha256": input_sha,
        "identity_ref": identity,
        "identity_sha256": _sha(identity.encode()),
    })


def _journal(root: Path, operation: str, dispatch: str, input_sha: str,
             states: list[str], times: list[datetime],
             evidence: str | None = None) -> dict[str, Any]:
    rows = []
    previous = None
    for sequence, (state, recorded) in enumerate(zip(states, times)):
        row = {
            "operation_id": operation,
            "dispatch_id": dispatch,
            "input_sha256": input_sha,
            "sequence": sequence,
            "state": state,
            "evidence_sha256": evidence if state == "captured" else None,
            "recorded_at": _timestamp(recorded),
            "previous_event_sha256": previous,
            "event_sha256": "",
        }
        row["event_sha256"] = _event_hash(row)
        previous = row["event_sha256"]
        rows.append(row)
    return _write(root, "journal.json", {
        "schema_version": DISPATCH_JOURNAL_VERSION,
        "operation_id": operation,
        "dispatch_id": dispatch,
        "input_sha256": input_sha,
        "events": rows,
    })


def _closed_failure(operation: str, code: str) -> ProviderResultV1:
    return ProviderResultV1(
        provider="claude_host", operation_id=operation, phase="not_started",
        submission="not_submitted", terminal_proof="absent", status="failed", code=code,
        failure_kind="local_config", provider_should_retry=False,
        receipt={"automatic_retry": False, "runtime_unverified": True},
    )


def _valid_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _validate_profile(profile: Any) -> tuple[Mapping[str, Any], float, float] | None:
    if type(profile) is not dict or set(profile) != _PROFILE_FIELDS:
        return None
    model = profile.get("model")
    capability = CLAUDE_MODEL_CAPABILITIES.get(model)
    if capability is None or profile.get("effort") not in capability["efforts"]:
        return None
    timeout = profile.get("timeout_seconds")
    budget = profile.get("max_budget_usd")
    if (not _valid_number(timeout) or timeout <= 0 or not _valid_number(budget)
            or budget <= 0 or budget > capability["max_budget_usd"]
            or type(profile.get("auth_home")) is not str or not profile["auth_home"]):
        return None
    return capability, float(timeout), float(budget)


async def _collect(query_fn: Any, prompt: str, options: Any, cancel_event: Any):
    final = None
    terminal_events = 0
    assistant_models = []
    assistant_error = False
    async for message in query_fn(prompt=prompt, options=options):
        if cancel_event is not None and cancel_event.is_set():
            raise asyncio.CancelledError()
        is_terminal = (message.__class__.__name__ == "ResultMessage"
                       or (hasattr(message, "result") and hasattr(message, "is_error")))
        if is_terminal:
            terminal_events += 1
            final = message
            continue
        if message.__class__.__name__ == "AssistantMessage":
            model = getattr(message, "model", None)
            if type(model) is str and model:
                assistant_models.append(model)
            else:
                assistant_error = True
            if getattr(message, "error", None) not in (None, False):
                assistant_error = True
    return final, terminal_events, tuple(assistant_models), assistant_error


def _field(value: Any, *names: str) -> Any:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _usage(terminal: Any) -> dict[str, int] | None:
    value = getattr(terminal, "usage", None)
    if not isinstance(value, Mapping):
        return None
    result = {}
    for key in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                "cache_creation_input_tokens"):
        item = value.get(key)
        if type(item) is not int or item < 0:
            return None
        result[key] = item
    return result


def _model_usage(terminal: Any):
    value = getattr(terminal, "model_usage", None)
    if not isinstance(value, Mapping) or not value:
        return None
    models = []
    keys = []
    providers = []
    aggregate = {
        "input_tokens": 0, "output_tokens": 0,
        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
    }
    aggregate_cost = 0.0
    for key, row in value.items():
        if type(key) is not str or not key:
            return None
        canonical = _field(row, "canonicalModel")
        if canonical is None:
            canonical = key
        provider = _field(row, "provider")
        input_tokens = _field(row, "inputTokens")
        output_tokens = _field(row, "outputTokens")
        cache_read = _field(row, "cacheReadInputTokens")
        cache_creation = _field(row, "cacheCreationInputTokens")
        web_searches = _field(row, "webSearchRequests")
        cost = _field(row, "costUSD")
        context_window = _field(row, "contextWindow")
        max_output = _field(row, "maxOutputTokens")
        if (type(canonical) is not str or canonical != key
                or (provider is not None and (type(provider) is not str or not provider))
                or type(input_tokens) is not int or input_tokens < 0
                or type(output_tokens) is not int or output_tokens < 0
                or type(cache_read) is not int or cache_read < 0
                or type(cache_creation) is not int or cache_creation < 0
                or type(web_searches) is not int or web_searches < 0
                or not _valid_number(cost) or cost < 0
                or type(context_window) is not int or context_window <= 0
                or type(max_output) is not int or max_output <= 0):
            return None
        keys.append(key)
        models.append(canonical)
        if provider is not None:
            providers.append((key, provider))
        aggregate["input_tokens"] += input_tokens
        aggregate["output_tokens"] += output_tokens
        aggregate["cache_read_input_tokens"] += cache_read
        aggregate["cache_creation_input_tokens"] += cache_creation
        aggregate_cost += float(cost)
    provider_sha = _sha(_canonical(sorted(providers))) if providers else None
    return tuple(models), tuple(keys), aggregate, aggregate_cost, provider_sha


def _terminal_failure(terminal: Any, *, configured_model: str, budget: float,
                      terminal_events: int, assistant_models: tuple[str, ...],
                      assistant_error: bool):
    """Validate only documented AssistantMessage/ResultMessage fields."""
    usage = _usage(terminal)
    model_usage = _model_usage(terminal)
    cost = getattr(terminal, "total_cost_usd", None)
    cost_value = float(cost) if _valid_number(cost) and cost >= 0 else None
    stop_reason = getattr(terminal, "stop_reason", None)
    terminal_reason = getattr(terminal, "terminal_reason", None)
    subtype = getattr(terminal, "subtype", None)
    status = getattr(terminal, "api_error_status", None)
    observed_model = None
    model_keys = ()
    if model_usage is not None:
        models, model_keys, aggregate, aggregate_cost, provider_evidence_sha256 = model_usage
        if len(set(models)) == 1:
            observed_model = models[0]
    else:
        aggregate = None
        aggregate_cost = None
        provider_evidence_sha256 = None

    if stop_reason == "refusal":
        return "CLAUDE_HOST_POLICY_FAILURE", "refusal", observed_model, model_keys, usage, cost_value, provider_evidence_sha256
    if status == 400:
        return "CLAUDE_HOST_CONFIG_FAILURE", "config", observed_model, model_keys, usage, cost_value, provider_evidence_sha256
    if status in (401, 403):
        return "CLAUDE_HOST_AUTH_FAILURE", "auth", observed_model, model_keys, usage, cost_value, provider_evidence_sha256
    if status == 404:
        return "CLAUDE_HOST_CONFIG_FAILURE", "model_rejection", observed_model, model_keys, usage, cost_value, provider_evidence_sha256
    if status == 429:
        return "SOURCE_HTTP_429", "rate_limit", observed_model, model_keys, usage, cost_value, provider_evidence_sha256
    if type(status) is int and 500 <= status <= 599:
        return "SOURCE_HTTP_" + str(status), "provider_http", observed_model, model_keys, usage, cost_value, provider_evidence_sha256
    if subtype == "error_max_budget_usd" or (cost_value is not None and cost_value > budget):
        return "CLAUDE_HOST_QUOTA_EXHAUSTED", "over_budget", observed_model, model_keys, usage, cost_value, provider_evidence_sha256
    if terminal_events != 1:
        return "CLAUDE_HOST_PARTIAL_RESULT", "terminal_shape", observed_model, model_keys, usage, cost_value, provider_evidence_sha256
    if assistant_error or not assistant_models:
        return "CLAUDE_HOST_PARTIAL_RESULT", "assistant_invalid", observed_model, model_keys, usage, cost_value, provider_evidence_sha256
    if any(model != configured_model for model in assistant_models):
        return "CLAUDE_HOST_IDENTITY_MISMATCH", "assistant_model_identity", observed_model, model_keys, usage, cost_value, provider_evidence_sha256
    if observed_model != configured_model or any(key != configured_model for key in model_keys):
        return "CLAUDE_HOST_IDENTITY_MISMATCH", "model_identity", observed_model, model_keys, usage, cost_value, provider_evidence_sha256
    if usage is None or aggregate is None or usage != aggregate:
        return "CLAUDE_HOST_PARTIAL_RESULT", "usage_invalid", observed_model, model_keys, usage, cost_value, provider_evidence_sha256
    if cost_value is None or aggregate_cost is None or not math.isclose(
            cost_value, aggregate_cost, rel_tol=0.0, abs_tol=1e-9):
        return "CLAUDE_HOST_PARTIAL_RESULT", "cost_invalid", observed_model, model_keys, usage, cost_value, provider_evidence_sha256
    result_value = getattr(terminal, "result", None)
    if (getattr(terminal, "subtype", None) != "success"
            or getattr(terminal, "is_error", None) is not False
            or terminal_reason not in (None, "success", "end_turn")
            or type(result_value) is not str or not result_value):
        return "CLAUDE_HOST_PARTIAL_RESULT", "terminal_invalid", observed_model, model_keys, usage, cost_value, provider_evidence_sha256
    try:
        result_value.encode("utf-8")
    except UnicodeEncodeError:
        return "CLAUDE_HOST_PARTIAL_RESULT", "terminal_invalid", observed_model, model_keys, usage, cost_value, provider_evidence_sha256
    return None, "success", observed_model, model_keys, usage, cost_value, provider_evidence_sha256

def _option_kwargs(options_factory: Any, capability: Mapping[str, Any],
                   profile: Mapping[str, Any], timeout: float, budget: float):
    signature = inspect.signature(options_factory)
    parameters = signature.parameters
    accepts_extra = any(item.kind is inspect.Parameter.VAR_KEYWORD
                        for item in parameters.values())
    required = capability["required_option_fields"]
    if not accepts_extra and not required <= set(parameters):
        raise ClaudeBridgeError("CLAUDE_HOST_SDK_OPTION_SURFACE")
    values = {
        "model": profile["model"],
        "effort": profile["effort"],
        "tools": [],
        "mcp_servers": {},
        "strict_mcp_config": True,
        "agents": {},
        "skills": [],
        "permission_mode": "dontAsk",
        "max_turns": capability["max_turns"],
        "max_budget_usd": budget,
        "env": {
            "CLAUDE_CONFIG_DIR": str(Path(profile["auth_home"]).resolve()),
            "CLAUDE_CODE_MAX_RETRIES": str(capability["max_retries"]),
            "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1",
            "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "1",
            "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
            "API_TIMEOUT_MS": str(int(timeout * 1000)),
        },
        "setting_sources": [],
        "include_partial_messages": False,
    }
    if "plugins" in parameters:
        values["plugins"] = []
    return values


def run_claude_host(profile: dict, prompt: bytes, workspace: Path, run_dir: Path,
                    operation_id: str, context: dict | None = None, *, query_fn: Any = None,
                    options_factory: Any = None) -> ProviderResultV1:
    """Run one fresh tool-free Claude session and normalize sealed evidence."""
    if type(prompt) is not bytes or not prompt:
        return _closed_failure(operation_id, "CLAUDE_HOST_PROMPT_INVALID")
    validated = _validate_profile(profile)
    if validated is None:
        return _closed_failure(operation_id, "CLAUDE_HOST_PROFILE_INVALID")
    capability, timeout, budget = validated
    context = context or {}
    cancel = context.get("cancel_event")
    try:
        text = prompt.decode("utf-8")
    except UnicodeDecodeError:
        return _closed_failure(operation_id, "CLAUDE_HOST_PROMPT_INVALID")

    workspace = Path(workspace).resolve(strict=True)
    raw_run_dir = Path(run_dir).absolute()
    run_dir = raw_run_dir.resolve(strict=False)
    if (raw_run_dir.is_symlink() or run_dir.exists()
            or not run_dir.is_relative_to((workspace / ".job-runtime").resolve())):
        return _closed_failure(operation_id, "CLAUDE_HOST_EVIDENCE_PATH")
    if cancel is not None and cancel.is_set():
        return _closed_failure(operation_id, "CLAUDE_HOST_CANCELLED_BEFORE_DISPATCH")

    try:
        if (query_fn is None) != (options_factory is None):
            raise ClaudeBridgeError("CLAUDE_HOST_PARTIAL_SDK_INJECTION")
        if query_fn is None:
            if sys.version_info < capability["minimum_python"]:
                raise ClaudeBridgeError("CLAUDE_HOST_PYTHON_UNSUPPORTED")
            if importlib.metadata.version("claude-agent-sdk") != "0.2.179":
                raise ClaudeBridgeError("CLAUDE_HOST_SDK_VERSION")
            from claude_agent_sdk import ClaudeAgentOptions, query
            query_signature = inspect.signature(query)
            if not {"prompt", "options"} <= set(query_signature.parameters):
                raise ClaudeBridgeError("CLAUDE_HOST_SDK_QUERY_SURFACE")
            query_fn = query
            options_factory = ClaudeAgentOptions
        options = options_factory(**_option_kwargs(
            options_factory, capability, profile, timeout, budget))
    except Exception:
        return _closed_failure(operation_id, "CLAUDE_HOST_SDK_UNAVAILABLE")

    run_dir.mkdir(mode=0o700, parents=True)
    (run_dir / "private").mkdir(mode=0o700)
    started = datetime.now(timezone.utc)
    deadline = started + timedelta(seconds=timeout + 5)
    dispatch = "dispatch-" + _sha((operation_id + _timestamp(started)).encode())[:24]
    input_sha = _sha(prompt)
    terminal = None
    terminal_events = 0
    assistant_models = ()
    assistant_error = False
    outcome_code = None
    try:
        terminal, terminal_events, assistant_models, assistant_error = asyncio.run(
            asyncio.wait_for(_collect(query_fn, text, options, cancel), timeout=timeout))
    except (asyncio.TimeoutError, asyncio.CancelledError):
        outcome_code = "CLAUDE_HOST_LATE_RESULT"
    except Exception:
        outcome_code = "CLAUDE_HOST_PARTIAL_RESULT"

    finished = datetime.now(timezone.utc)
    captured_at = finished if terminal is not None else None
    session_id = (str(getattr(terminal, "session_id", "unavailable"))
                  if terminal is not None else "unavailable")
    identities = {
        "host_session": _identity(
            run_dir, "host_session", operation_id, dispatch, input_sha,
            "session-" + _sha(session_id.encode())[:24]),
        "host_profile": _identity(
            run_dir, "host_profile", operation_id, dispatch, input_sha,
            "profile-" + _sha(_canonical({
                "model": profile["model"], "effort": profile["effort"],
                "max_budget_usd": budget,
            }))[:24]),
        "backend_identity": _identity(
            run_dir, "backend_identity", operation_id, dispatch, input_sha,
            "configured-model-" + _sha(profile["model"].encode())[:24]),
        "tool_identity": _identity(
            run_dir, "tool_identity", operation_id, dispatch, input_sha,
            "tools-disabled-v1"),
    }

    observed_model = None
    provider_model_keys = ()
    provider_evidence_sha256 = None
    usage = None
    total_cost_usd = None
    terminal_class = "post_dispatch_unknown"
    if terminal is not None:
        (outcome_code, terminal_class, observed_model, provider_model_keys, usage,
         total_cost_usd, provider_evidence_sha256) = _terminal_failure(
            terminal, configured_model=profile["model"], budget=budget,
            terminal_events=terminal_events, assistant_models=assistant_models,
            assistant_error=assistant_error)

    success = terminal is not None and outcome_code is None
    result_ref = None
    result_sha = None
    terminal_status = "unknown"
    if success:
        raw = terminal.result.encode("utf-8")
        result_ref = _write(run_dir, "result.bin", raw, binary=True)
        result_sha = result_ref["sha256"]
        terminal_status = "captured"
    elif terminal is not None:
        terminal_status = "failed"
    states = ["prepared", "claimed", "invocation_started",
              "captured" if terminal is not None else "possibly_dispatched"]
    times = [started, started, started, captured_at or finished]
    envelope = {
        "operation_id": operation_id,
        "dispatch_id": dispatch,
        "input_sha256": input_sha,
        "terminal_status": terminal_status,
        "failure_code": outcome_code,
        "result_sha256": result_sha,
        "started_at": _timestamp(started),
        "captured_at": _timestamp(captured_at) if captured_at else None,
        "finished_at": _timestamp(min(finished, deadline)),
        "deadline_at": _timestamp(deadline),
    }
    if terminal_status == "failed":
        failure_record = {"schema_version": "ClaudeHostFailureV1", **envelope}
        terminal_evidence = _sha(_canonical(failure_record))
    elif success:
        terminal_evidence = result_sha
    else:
        terminal_evidence = None
    journal = _journal(
        run_dir, operation_id, dispatch, input_sha, states, times, terminal_evidence)
    proof = None
    if terminal is not None:
        hashes = {kind: ref["sha256"] for kind, ref in identities.items()}
        proof = _write(run_dir, "proof.json", {
            "schema_version": TERMINAL_PROOF_VERSION,
            "operation_id": operation_id,
            "dispatch_id": dispatch,
            "input_sha256": input_sha,
            "identity_artifact_sha256s": hashes,
            "journal_sha256": journal["sha256"],
            "result_sha256": result_sha,
            "terminal_state": "captured",
            "terminal_status": terminal_status,
            "failure_code": outcome_code,
            "started_at": envelope["started_at"],
            "captured_at": envelope["captured_at"],
            "finished_at": envelope["finished_at"],
            "deadline_at": envelope["deadline_at"],
        })
    evidence = {
        "schema_version": CLAUDE_HOST_EVIDENCE_VERSION,
        "provider": "claude_host",
        "operation_id": operation_id,
        "dispatch_id": dispatch,
        "input_sha256": input_sha,
        "host_session_ref": identities["host_session"],
        "host_profile_ref": identities["host_profile"],
        "backend_identity_ref": identities["backend_identity"],
        "tool_identity_ref": identities["tool_identity"],
        "dispatch_journal_ref": journal,
        "terminal_status": terminal_status,
        "failure_code": outcome_code,
        "result_ref": result_ref,
        "result_sha256": result_sha,
        "terminal_proof_ref": proof,
        "started_at": envelope["started_at"],
        "captured_at": envelope["captured_at"],
        "finished_at": envelope["finished_at"],
        "deadline_at": envelope["deadline_at"],
    }
    result = normalize_invocation(evidence, file_resolver=WorkspaceEvidenceResolver(run_dir))
    receipt = dict(result.receipt)
    receipt.update({
        "retry_configured_max": capability["max_retries"],
        "configured_retry_zero": capability["max_retries"] == 0,
        "typed_retry_observed_supported": False,
        "configured_model": profile["model"],
        "provider_reported_model": observed_model if observed_model is not None else False,
        "observed_model_matches_configured": observed_model == profile["model"],
        "provider_model_keys": provider_model_keys,
        "provider_evidence_sha256": (
            provider_evidence_sha256 if provider_evidence_sha256 is not None else False),
        "assistant_model_count": len(assistant_models),
        "assistant_issue_observed": assistant_error,
        "terminal_event_count": terminal_events,
        "terminal_class": terminal_class,
        "usage": usage if usage is not None else False,
        "total_cost_usd": total_cost_usd if total_cost_usd is not None else False,
        "max_budget_usd": budget,
    })
    return ProviderResultV1(
        provider=result.provider, operation_id=result.operation_id, phase=result.phase,
        submission=result.submission, terminal_proof=result.terminal_proof,
        status=result.status, code=result.code, failure_kind=result.failure_kind,
        http_status=result.http_status, provider_should_retry=False,
        retry_after_at=result.retry_after_at, retry_after_source=result.retry_after_source,
        receipt=receipt,
    )
