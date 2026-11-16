"""Fail-closed, bounded model execution for one durable mentor session.

A per-logical-session lock serializes guard, intent creation, dispatch and durable
closure.  Recovery never dispatches: it consumes retained transport evidence or
fences an uncertain intent using its original in-window event timestamp.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import signal
import stat
import tempfile
import time
from typing import Any, Callable

from shared.job_runtime.model import run_codex
from .contracts import ContractError, WorkOrder, canonical_json_bytes, strict_json_loads
from .state import DurableSessionStore, StateError

UTC = timezone.utc
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")
_MAX_PROMPT_BYTES = 512 * 1024
_MAX_RESPONSE_BYTES = 1024 * 1024
_PROFILE_REQUIRED = {"codex_bin", "model", "effort", "timeout_seconds", "auth_home"}
_PROFILE_OPTIONAL = {"max_output_bytes"}
_EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
_PHASES = {"prepared", "model_returned", "ledger_committed"}
_PROVEN_PRE_DISPATCH_CODES = {
    "CODEX_BINARY_UNAVAILABLE",
    "MODEL_AUTH_CACHE_BUSY",
    "MODEL_AUTH_FILE_UNSAFE",
    "MODEL_AUTH_HOME_UNSAFE",
    "MODEL_AUTH_REQUIRED",
    "MODEL_CANCELLED_BEFORE_START",
    "MODEL_CONTEXT_INVALID",
    "MODEL_EFFORT_INVALID",
    "MODEL_NAME_INVALID",
    "MODEL_OUTPUT_LIMIT_INVALID",
    "MODEL_PATH_OUTSIDE_STATE",
    "MODEL_PATH_OWNER_MISMATCH",
    "MODEL_PATH_SYMLINK",
    "MODEL_PROFILE_INVALID",
    "MODEL_PROMPT_INVALID",
    "MODEL_RUN_DIRECTORY_EXISTS",
    "MODEL_SCHEMA_INVALID",
    "MODEL_TIMEOUT_INVALID",
    "MODEL_WORKSPACE_INVALID",
}
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|password)\b\s*[:=]\s*[\"']?[^\s\"']{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{8,}\b"),
)


class RunnerError(RuntimeError):
    """Stable diagnostics never include prompt, provider or credential text."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise RunnerError(code)


def _now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    _require(isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None,
             "MENTOR_CLOCK_INVALID")
    return value.astimezone(UTC)


def _identifier(value: Any, code: str) -> str:
    _require(isinstance(value, str) and bool(_ID_RE.fullmatch(value)), code)
    return value


def _state_root(workspace: Path) -> Path:
    state = workspace / ".job-runtime"
    _require(not state.is_symlink(), "MENTOR_RUNTIME_ROOT_SYMLINK")
    if state.exists():
        _require(state.is_dir() and state.stat().st_uid == os.getuid(), "MENTOR_RUNTIME_ROOT_UNSAFE")
    else:
        try: state.mkdir(mode=0o700)
        except FileExistsError: pass
    _require(not state.is_symlink() and state.is_dir() and state.stat().st_uid == os.getuid(),
             "MENTOR_RUNTIME_ROOT_UNSAFE")
    os.chmod(state, 0o700)
    return state


def _private_directory(path: Path, workspace: Path) -> Path:
    state = _state_root(workspace)
    _require(path.is_relative_to(state) and path != state, "MENTOR_RUNNER_PATH_INVALID")
    current = state
    for part in path.relative_to(state).parts:
        current = current / part
        _require(not current.is_symlink(), "MENTOR_RUNNER_PATH_SYMLINK")
        current.mkdir(mode=0o700, exist_ok=True)
        _require(not current.is_symlink() and current.is_dir() and current.stat().st_uid == os.getuid(),
                 "MENTOR_RUNNER_PATH_OWNER_MISMATCH")
        os.chmod(current, 0o700)
    return path


def _atomic(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    candidate = Path(temporary)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json_bytes(value)); stream.flush(); os.fsync(stream.fileno())
        os.replace(candidate, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        candidate.unlink(missing_ok=True)


def _read_journal(path: Path) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), "MENTOR_ATTEMPT_JOURNAL_INVALID")
    info = path.stat()
    _require(info.st_uid == os.getuid() and not stat.S_IMODE(info.st_mode) & 0o077,
             "MENTOR_ATTEMPT_JOURNAL_UNSAFE")
    try: value = strict_json_loads(path.read_text(encoding="utf-8"))
    except Exception: raise RunnerError("MENTOR_ATTEMPT_JOURNAL_INVALID") from None
    _require(isinstance(value, dict) and value.get("phase") in _PHASES, "MENTOR_ATTEMPT_JOURNAL_INVALID")
    return value


def _attempt_root(work_order: WorkOrder) -> Path:
    return _private_directory(work_order.workspace / ".job-runtime" / "mentor-attempts" /
                              work_order.logical_session.logical_session_id, work_order.workspace)


@contextmanager
def _session_lock(work_order: WorkOrder):
    root = _attempt_root(work_order)
    path = root / ".dispatch.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        try: fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RunnerError("MENTOR_SESSION_DISPATCH_BUSY") from None
        yield
    finally:
        try: fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally: os.close(descriptor)


def _journals(work_order: WorkOrder) -> list[tuple[Path, dict[str, Any]]]:
    return [(path, _read_journal(path)) for path in sorted(_attempt_root(work_order).glob("*/journal.json"))]


def _blocking_attempts(work_order: WorkOrder) -> list[Path]:
    return [path for path, value in _journals(work_order)
            if value["phase"] != "ledger_committed" or value.get("fence_type") == "manual_unknown"]


def _identity(work_order: WorkOrder, journal: dict[str, Any]) -> dict[str, Any]:
    value = journal.get("identity")
    required = {"attempt_id", "attempt_type", "external_engine_attempt_id", "cycle_id", "variant_id",
                "work_order_id", "logical_session_id", "plan_sha256", "acceptance_sha256"}
    _require(isinstance(value, dict) and set(value) == required, "MENTOR_ATTEMPT_IDENTITY_MISMATCH")
    _identifier(value["attempt_id"], "MENTOR_ATTEMPT_IDENTITY_MISMATCH")
    _identifier(value["cycle_id"], "MENTOR_ATTEMPT_IDENTITY_MISMATCH")
    _identifier(value["variant_id"], "MENTOR_ATTEMPT_IDENTITY_MISMATCH")
    _require(value["attempt_type"] in {"manual", "scheduled_external"}, "MENTOR_ATTEMPT_IDENTITY_MISMATCH")
    if value["attempt_type"] == "scheduled_external":
        _identifier(value["external_engine_attempt_id"], "MENTOR_ATTEMPT_IDENTITY_MISMATCH")
    else:
        _require(value["external_engine_attempt_id"] is None, "MENTOR_ATTEMPT_IDENTITY_MISMATCH")
    _require(value["work_order_id"] == work_order.work_order_id and
             value["logical_session_id"] == work_order.logical_session.logical_session_id and
             value["plan_sha256"] == work_order.plan.sha256 and
             value["acceptance_sha256"] == work_order.acceptance.sha256,
             "MENTOR_ATTEMPT_IDENTITY_MISMATCH")
    return value


def _event_at(work_order: WorkOrder, journal: dict[str, Any]) -> datetime:
    try: value = datetime.fromisoformat(journal["event_at"].replace("Z", "+00:00"))
    except Exception: raise RunnerError("MENTOR_ATTEMPT_TIMESTAMP_INVALID") from None
    _require(value.tzinfo is not None and value.utcoffset() is not None and
             work_order.execution.starts_at <= value <= work_order.execution.ends_at,
             "MENTOR_ATTEMPT_TIMESTAMP_INVALID")
    return value


def _validated_profile(profile: Any, work_order: WorkOrder, at: datetime) -> tuple[dict[str, Any], float]:
    _require(isinstance(profile, dict), "MENTOR_MODEL_PROFILE_INVALID")
    keys = set(profile) - {"executor"}
    _require(_PROFILE_REQUIRED <= keys and keys <= _PROFILE_REQUIRED | _PROFILE_OPTIONAL,
             "MENTOR_MODEL_PROFILE_INVALID")
    _require(isinstance(profile["codex_bin"], (str, Path)) and isinstance(profile["auth_home"], (str, Path)) and
             isinstance(profile["model"], str) and bool(_MODEL_RE.fullmatch(profile["model"])) and
             profile["effort"] in _EFFORTS, "MENTOR_MODEL_PROFILE_INVALID")
    timeout = profile["timeout_seconds"]
    _require(type(timeout) is int and 0 < timeout <= 3600, "MENTOR_MODEL_TIMEOUT_INVALID")
    if "max_output_bytes" in profile:
        maximum = profile["max_output_bytes"]
        _require(type(maximum) is int and 1024 <= maximum <= 64 * 1024 * 1024,
                 "MENTOR_MODEL_PROFILE_INVALID")
    remaining = int((work_order.execution.ends_at - at).total_seconds())
    _require(remaining >= 1, "MENTOR_EXECUTION_WINDOW_CLOSED")
    effective = min(timeout, work_order.execution.turn_timeout_seconds, remaining)
    clean = {key: value for key, value in profile.items() if key != "executor"}
    clean["timeout_seconds"] = effective
    return clean, effective


def _schema(cycle_id: str, variant_id: str, criterion_ids: list[str]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
        "required": ["schema_version", "cycle_id", "variant_id", "action_id", "criterion_updates"],
        "properties": {
            "schema_version": {"type": "integer", "const": 1},
            "cycle_id": {"type": "string", "const": cycle_id},
            "variant_id": {"type": "string", "const": variant_id},
            "action_id": {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"},
            "criterion_updates": {"type": "array", "maxItems": len(criterion_ids), "items": {
                "type": "object", "additionalProperties": False,
                "required": ["criterion_id", "outcome", "evidence_id"],
                "properties": {
                    "criterion_id": {"type": "string", "enum": criterion_ids},
                    "outcome": {"type": "string", "enum": ["satisfied", "not_satisfied", "unknown"]},
                    "evidence_id": {"type": ["string", "null"], "maxLength": 128},
                }}}}}


def _plan_text(work_order: WorkOrder) -> str:
    path = work_order.workspace / work_order.plan.path
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            _require(stat.S_ISREG(info.st_mode), "MENTOR_PLAN_UNSAFE")
            raw = stream.read(_MAX_PROMPT_BYTES + 1)
    except RunnerError: raise
    except OSError: raise RunnerError("MENTOR_PLAN_UNAVAILABLE") from None
    _require(len(raw) <= _MAX_PROMPT_BYTES, "MENTOR_PLAN_TOO_LARGE")
    _require(hashlib.sha256(raw).hexdigest() == work_order.plan.sha256, "MENTOR_PLAN_BINDING_DRIFT")
    try: text = raw.decode("utf-8")
    except UnicodeError: raise RunnerError("MENTOR_PLAN_ENCODING_INVALID") from None
    _require(not any(pattern.search(text) for pattern in _SECRET_PATTERNS), "MENTOR_PLAN_SECRET_REJECTED")
    return text


def _prompt(work_order: WorkOrder, head: dict[str, Any], cycle_id: str, variant_id: str,
            plan_text: str) -> str:
    value = {"schema_version": 1,
        "objective": "Execute one bounded mentor cycle against the frozen plan and return only closed-schema JSON.",
        "frozen_plan": plan_text,
        "bindings": {"work_order_id": work_order.work_order_id,
            "logical_session_id": work_order.logical_session.logical_session_id,
            "plan_sha256": work_order.plan.sha256, "acceptance_sha256": work_order.acceptance.sha256,
            "criteria": [{"criterion_id": item.criterion_id, "critical": item.critical}
                         for item in work_order.acceptance_criteria],
            "cycle_id": cycle_id, "variant_id": variant_id},
        "verified_state": {"turns_used": head["turns_used"],
            "verified_evidence_ids": head["verified_evidence_ids"][-64:],
            "consecutive_no_progress": head["consecutive_no_progress"],
            "repeated_action_count": head["repeated_action_count"]},
        "restrictions": ["No credentials, tools, files, network, holdouts, or prior provider text.",
                         "Do not create or claim the verifier-owned progress artifact.",
                         "Return only the closed-schema JSON object."]}
    prompt = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    _require(0 < len(prompt.encode("utf-8")) <= _MAX_PROMPT_BYTES, "MENTOR_MODEL_PROMPT_TOO_LARGE")
    return prompt


def _strict_output(value: Any, cycle_id: str, variant_id: str, criteria: set[str]) -> dict[str, Any]:
    keys = {"schema_version", "cycle_id", "variant_id", "action_id", "criterion_updates"}
    _require(isinstance(value, dict) and set(value) == keys and value.get("schema_version") == 1 and
             value.get("cycle_id") == cycle_id and value.get("variant_id") == variant_id,
             "MENTOR_MODEL_RESPONSE_INVALID")
    _identifier(value["action_id"], "MENTOR_MODEL_RESPONSE_INVALID")
    updates = value["criterion_updates"]
    _require(isinstance(updates, list) and len(updates) <= len(criteria), "MENTOR_MODEL_RESPONSE_INVALID")
    seen = set()
    for item in updates:
        _require(isinstance(item, dict) and set(item) == {"criterion_id", "outcome", "evidence_id"},
                 "MENTOR_MODEL_RESPONSE_INVALID")
        evidence = item["evidence_id"]
        _require(item["criterion_id"] in criteria and item["criterion_id"] not in seen and
                 item["outcome"] in {"satisfied", "not_satisfied", "unknown"} and
                 (evidence is None or isinstance(evidence, str) and 0 < len(evidence) <= 128),
                 "MENTOR_MODEL_RESPONSE_INVALID")
        seen.add(item["criterion_id"])
    return value


def _semantic_action_sha(output: dict[str, Any]) -> str:
    updates = sorted(output["criterion_updates"], key=lambda item: item["criterion_id"])
    return hashlib.sha256(canonical_json_bytes({"action_id": output["action_id"],
                                                "criterion_updates": updates})).hexdigest()


def _load_store(work_order: WorkOrder, store: DurableSessionStore) -> dict[str, Any]:
    try:
        return store.load(work_order)
    except StateError as original:
        try:
            return store.recover_orphan(work_order)
        except StateError:
            raise original


def _guard(work_order: WorkOrder, store: DurableSessionStore, at: datetime,
           cancel_event: Any | None, variant_id: str) -> dict[str, Any]:
    work_order.verify_bindings()
    head = _load_store(work_order, store)
    _require(head["status"] == "active" and not head["pending_effects"], "MENTOR_SESSION_NOT_ACTIVE")
    _require(cancel_event is None or not cancel_event.is_set(), "MENTOR_RUN_CANCELLED")
    _require(work_order.execution.starts_at <= at < work_order.execution.ends_at, "MENTOR_EXECUTION_WINDOW_CLOSED")
    _require(head["turns_used"] < work_order.execution.max_turns, "MENTOR_TURN_BUDGET_EXHAUSTED")
    _require(len(head["provider_threads"]) < work_order.logical_session.max_provider_threads,
             "MENTOR_PROVIDER_THREAD_BUDGET_EXHAUSTED")
    _require(variant_id in head["variants"] or len(head["variants"]) < work_order.evidence_policy.max_variants,
             "MENTOR_VARIANT_BUDGET_EXHAUSTED")
    _require(head["consecutive_no_progress"] < work_order.supervision.max_no_progress_cycles,
             "MENTOR_NO_PROGRESS_BUDGET_EXHAUSTED")
    _require(head["repeated_action_count"] < work_order.supervision.max_repeated_actions,
             "MENTOR_REPEATED_ACTION_BUDGET_EXHAUSTED")
    _require(not _blocking_attempts(work_order), "MENTOR_UNFINISHED_ATTEMPT_REQUIRES_RECONCILIATION")
    return head


def _source_path(workspace: Path, run_directory: Path, relative: Any) -> Path:
    _require(isinstance(relative, str) and relative and "\\" not in relative,
             "MENTOR_MODEL_RESPONSE_PATH_INVALID")
    pure = PurePosixPath(relative)
    _require(not pure.is_absolute() and all(part not in ("", ".", "..") for part in pure.parts),
             "MENTOR_MODEL_RESPONSE_PATH_INVALID")
    raw_path = workspace
    for part in pure.parts:
        raw_path = raw_path / part
        _require(not raw_path.is_symlink(), "MENTOR_MODEL_RESPONSE_PATH_INVALID")
    try:
        path = raw_path.resolve(strict=True)
        path.relative_to(run_directory.resolve(strict=True))
    except (OSError, ValueError): raise RunnerError("MENTOR_MODEL_RESPONSE_PATH_INVALID") from None
    _require(path.is_file() and path.stat().st_size <= _MAX_RESPONSE_BYTES,
             "MENTOR_MODEL_RESPONSE_PATH_INVALID")
    return path


def _transport(result: Any, expected_model: str) -> dict[str, Any]:
    _require(isinstance(result, dict) and set(result) <= {"status", "code", "receipt"} and
             result.get("status") == "succeeded" and result.get("code") == "MODEL_TURN_COMPLETED",
             "MENTOR_MODEL_OUTCOME_UNKNOWN")
    receipt = result.get("receipt")
    required = {"thread_id", "response_path", "response_sha256", "turn_completed", "requested_model",
                "observed_model", "automatic_retry", "fallback_used"}
    _require(isinstance(receipt, dict) and required <= set(receipt) and
             receipt["requested_model"] == expected_model and receipt["observed_model"] in (None, expected_model) and
             receipt["automatic_retry"] is False and receipt["fallback_used"] is False and
             receipt["turn_completed"] is True, "MENTOR_MODEL_RECEIPT_INVALID")
    _identifier(receipt["thread_id"], "MENTOR_MODEL_THREAD_INVALID")
    return receipt


def _pre_dispatch_result(result: Any) -> tuple[str, str] | None:
    if not isinstance(result, dict) or result.get("status") not in {"failed", "retryable"}:
        return None
    receipt = result.get("receipt")
    code = result.get("code")
    if not isinstance(receipt, dict):
        return None
    if result["status"] == "retryable":
        # The read-only transport owns this classification and performs no tools or
        # external effects; preserve it for the scheduler without replaying here.
        code = code if isinstance(code, str) and _CODE_RE.fullmatch(code) else "MENTOR_MODEL_RETRYABLE"
        return "retryable", code
    explicit_pre_dispatch = isinstance(code, str) and code in _PROVEN_PRE_DISPATCH_CODES
    if not explicit_pre_dispatch and any(receipt.get(key) for key in ("started_at", "run_directory", "thread_id")):
        return None
    code = code if isinstance(code, str) and _CODE_RE.fullmatch(code) else "MENTOR_MODEL_PRE_DISPATCH_FAILED"
    return result["status"], code


def _record_thread(work_order: WorkOrder, store: DurableSessionStore, thread_id: str,
                   at: datetime) -> None:
    head = _load_store(work_order, store)
    existing = next((item for item in head["provider_threads"] if item["thread_id"] == thread_id), None)
    if existing is None: store.record_provider_thread(work_order, provider="codex", thread_id=thread_id, at=at)
    else: _require(existing["provider"] == "codex", "MENTOR_PROVIDER_THREAD_CONFLICT")


def _retain_output(work_order: WorkOrder, journal_path: Path, journal: dict[str, Any]) -> dict[str, Any]:
    identity = _identity(work_order, journal)
    transport = journal.get("transport")
    _require(isinstance(transport, dict), "MENTOR_MODEL_RECEIPT_INVALID")
    retained = journal_path.parent / "retained-output.json"
    if not retained.exists():
        run_dir = work_order.workspace / transport["run_directory"]
        source = _source_path(work_order.workspace, run_dir, transport["response_path"])
        raw = source.read_bytes()
        _require(hashlib.sha256(raw).hexdigest() == transport["response_sha256"],
                 "MENTOR_MODEL_RESPONSE_HASH_MISMATCH")
        try: output = _strict_output(strict_json_loads(raw.decode("utf-8")), identity["cycle_id"],
                                     identity["variant_id"], {item.criterion_id for item in work_order.acceptance_criteria})
        except RunnerError: raise
        except Exception: raise RunnerError("MENTOR_MODEL_RESPONSE_INVALID") from None
        descriptor = os.open(retained, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json_bytes(output)); stream.flush(); os.fsync(stream.fileno())
        journal = {**journal, "transport": {**transport,
                    "retained_sha256": hashlib.sha256(retained.read_bytes()).hexdigest()}}
        _atomic(journal_path, journal)
    expected = journal["transport"].get("retained_sha256")
    _require(retained.is_file() and not retained.is_symlink() and isinstance(expected, str) and
             hashlib.sha256(retained.read_bytes()).hexdigest() == expected, "MENTOR_RETAINED_OUTPUT_INVALID")
    try: output = _strict_output(strict_json_loads(retained.read_text(encoding="utf-8")), identity["cycle_id"],
                                 identity["variant_id"], {item.criterion_id for item in work_order.acceptance_criteria})
    except RunnerError: raise
    except Exception: raise RunnerError("MENTOR_RETAINED_OUTPUT_INVALID") from None
    return output


def _invoke_verifier(verifier: Callable[..., Any], work_order: WorkOrder, cycle_id: str,
                     output: dict[str, Any], directory: Path, timeout: float,
                     cancel_event: Any | None, clock: Callable[[], datetime]) -> tuple[str | None, str | None]:
    """Run verifier in a killable child; parent owns timeout and cancellation."""
    _now(clock)  # validate the injected clock without using it as the hard deadline
    if cancel_event is not None and cancel_event.is_set():
        return None, "MENTOR_VERIFIER_CANCELLED"
    read_fd, write_fd = os.pipe()
    try:
        pid = os.fork()
    except OSError:
        os.close(read_fd); os.close(write_fd)
        return None, "MENTOR_VERIFIER_PROCESS_FAILED"
    if pid == 0:
        try:
            os.close(read_fd)
            deadline = datetime.now(UTC) + timedelta(seconds=timeout)
            try:
                result = verifier(work_order=work_order, cycle_id=cycle_id, output=output,
                                  verifier_directory=directory, deadline=deadline,
                                  cancel_event=cancel_event)
                if result is not None and not isinstance(result, str):
                    payload = {"kind": "invalid_result", "result": None}
                else:
                    payload = {"kind": "ok", "result": result}
            except (ContractError, StateError):
                payload = {"kind": "artifact_invalid", "result": None}
            except BaseException:
                payload = {"kind": "failed", "result": None}
            raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if len(raw) <= 4096:
                os.write(write_fd, raw)
        finally:
            try: os.close(write_fd)
            except OSError: pass
            os._exit(0)

    os.close(write_fd)
    stop_at = time.monotonic() + timeout
    failure = None
    while True:
        finished, _ = os.waitpid(pid, os.WNOHANG)
        if finished == pid:
            break
        if cancel_event is not None and cancel_event.is_set():
            failure = "MENTOR_VERIFIER_CANCELLED"
            break
        if time.monotonic() >= stop_at:
            failure = "MENTOR_VERIFIER_TIMEOUT"
            break
        time.sleep(min(0.01, max(0.001, timeout / 20)))
    if failure is not None:
        try: os.kill(pid, signal.SIGKILL)
        except ProcessLookupError: pass
        os.waitpid(pid, 0)
        os.close(read_fd)
        return None, failure
    try:
        raw = os.read(read_fd, 4097)
    finally:
        os.close(read_fd)
    if not raw or len(raw) > 4096:
        return None, "MENTOR_VERIFIER_PROCESS_FAILED"
    try:
        payload = strict_json_loads(raw.decode("utf-8"))
    except Exception:
        return None, "MENTOR_VERIFIER_PROCESS_FAILED"
    if not isinstance(payload, dict) or set(payload) != {"kind", "result"}:
        return None, "MENTOR_VERIFIER_PROCESS_FAILED"
    if payload["kind"] == "artifact_invalid":
        return None, "MENTOR_VERIFIER_ARTIFACT_INVALID"
    if payload["kind"] == "invalid_result":
        return None, "MENTOR_VERIFIER_RESULT_INVALID"
    if payload["kind"] != "ok":
        return None, "MENTOR_VERIFIER_FAILED"
    result = payload["result"]
    if result is None:
        return None, "MENTOR_VERIFIER_NO_PROGRESS"
    if not isinstance(result, str):
        return None, "MENTOR_VERIFIER_RESULT_INVALID"
    candidate = work_order.workspace / result
    try: candidate.resolve(strict=True).relative_to(directory.resolve(strict=True))
    except (OSError, ValueError): return None, "MENTOR_VERIFIER_PATH_INVALID"
    try: work_order.verify_progress_artifact(result, cycle_id)
    except (ContractError, OSError): return None, "MENTOR_VERIFIER_ARTIFACT_INVALID"
    return result, None


def validate_committed_external_attempt(
    work_order: WorkOrder,
    journal_path: Path,
    *,
    external_engine_attempt_id: str,
    cycle_id: str,
) -> dict[str, str]:
    """Validate one exact successful scheduled-attempt journal and retained output."""
    journal = _read_journal(journal_path)
    expected_keys = {
        "schema_version", "phase", "identity", "intent_sha256",
        "effective_timeout_seconds", "event_at", "created_at", "updated_at",
        "transport", "ledger",
    }
    _require(set(journal) == expected_keys and journal.get("schema_version") == 1 and
             journal.get("phase") == "ledger_committed", "MENTOR_COMMITTED_JOURNAL_INVALID")
    identity = _identity(work_order, journal)
    _require(identity["attempt_type"] == "scheduled_external" and
             identity["external_engine_attempt_id"] == external_engine_attempt_id and
             identity["cycle_id"] == cycle_id,
             "MENTOR_COMMITTED_JOURNAL_INVALID")
    transport = journal.get("transport")
    _require(isinstance(transport, dict) and set(transport) == {
        "thread_id", "response_path", "response_sha256", "run_directory", "retained_sha256"
    }, "MENTOR_COMMITTED_JOURNAL_INVALID")
    thread_id = _identifier(transport.get("thread_id"), "MENTOR_COMMITTED_JOURNAL_INVALID")
    for key in ("response_sha256", "retained_sha256"):
        _require(isinstance(transport.get(key), str) and _SHA_RE.fullmatch(transport[key]),
                 "MENTOR_COMMITTED_JOURNAL_INVALID")
    retained = journal_path.parent / "retained-output.json"
    _require(retained.is_file() and not retained.is_symlink() and
             retained.stat().st_uid == os.getuid() and
             not stat.S_IMODE(retained.stat().st_mode) & 0o077 and
             hashlib.sha256(retained.read_bytes()).hexdigest() == transport["retained_sha256"],
             "MENTOR_COMMITTED_JOURNAL_INVALID")
    ledger = journal.get("ledger")
    _require(isinstance(ledger, dict) and set(ledger) == {
        "recorded", "revision", "outcome", "progress_verified"
    } and ledger["recorded"] is True and type(ledger["revision"]) is int and
             ledger["revision"] >= 1 and ledger["outcome"] == "succeeded" and
             ledger["progress_verified"] is True,
             "MENTOR_COMMITTED_JOURNAL_INVALID")
    return {"thread_id": thread_id, "cycle_id": identity["cycle_id"]}


def _actual_cycle(work_order: WorkOrder, store: DurableSessionStore, cycle_id: str) -> dict[str, Any]:
    head = _load_store(work_order, store)
    _require(cycle_id in head["cycle_ids"], "MENTOR_COMMITTED_CYCLE_MISSING")
    for path in sorted(store.events_directory.glob("*.json")):
        try: event = strict_json_loads(path.read_text(encoding="utf-8"))
        except Exception: continue
        if event.get("kind") == "cycle" and event.get("data", {}).get("cycle_id") == cycle_id:
            data = event["data"]
            return {"status": "succeeded" if data["outcome"] == "succeeded" else
                              "unknown" if data["outcome"] == "unknown" else "failed",
                    "code": "MENTOR_CYCLE_ALREADY_COMMITTED", "cycle_id": cycle_id,
                    "outcome": data["outcome"], "progressed": bool(data["verified_evidence_ids"])}
    raise RunnerError("MENTOR_COMMITTED_CYCLE_MISSING")


def _close_cycle(work_order: WorkOrder, store: DurableSessionStore, journal_path: Path,
                 outcome: str, code: str, *, action_sha: str, artifact: str | None = None,
                 effect_id: str | None = None, at: datetime) -> dict[str, Any]:
    journal = _read_journal(journal_path); identity = _identity(work_order, journal)
    head = _load_store(work_order, store)
    if identity["cycle_id"] not in head["cycle_ids"]:
        pending = effect_id is not None
        head = store.record_cycle(work_order, cycle_id=identity["cycle_id"], variant_id=identity["variant_id"],
            action_sha256=action_sha, outcome=outcome, verified_evidence_artifact_path=artifact,
            effect_id=effect_id, effect_status="pending" if pending else "none", at=at)
    progressed = bool(artifact)
    ledger = {"recorded": True, "revision": head["revision"], "outcome": outcome,
              "progress_verified": progressed}
    journal = {**journal, "phase": "ledger_committed", "updated_at": datetime.now(UTC).isoformat(), "ledger": ledger}
    _atomic(journal_path, journal)
    status = "succeeded" if outcome == "succeeded" else "unknown" if outcome == "unknown" else "failed"
    return {"status": status, "code": code, "cycle_id": identity["cycle_id"], "progressed": progressed}


def _close_without_cycle(work_order: WorkOrder, journal_path: Path, code: str,
                         *, status: str = "failed") -> dict[str, Any]:
    _require(status in {"failed", "retryable"}, "MENTOR_TERMINAL_STATUS_INVALID")
    journal = _read_journal(journal_path); identity = _identity(work_order, journal)
    journal = {**journal, "phase": "ledger_committed", "updated_at": datetime.now(UTC).isoformat(),
               "ledger": {"recorded": False, "outcome": status, "progress_verified": False,
                           "terminal_code": code}}
    _atomic(journal_path, journal)
    return {"status": status, "code": code, "cycle_id": identity["cycle_id"], "progressed": False}


def _fence_unknown(work_order: WorkOrder, store: DurableSessionStore, journal_path: Path,
                   code: str) -> dict[str, Any]:
    journal = _read_journal(journal_path); identity = _identity(work_order, journal); at = _event_at(work_order, journal)
    external = identity["external_engine_attempt_id"] if identity["attempt_type"] == "scheduled_external" else None
    result = _close_cycle(work_order, store, journal_path, "unknown", code,
                          action_sha=journal["intent_sha256"], effect_id=external, at=at)
    if external is None:
        value = _read_journal(journal_path); value["fence_type"] = "manual_unknown"; _atomic(journal_path, value)
    return result


def _commit_retained(work_order: WorkOrder, store: DurableSessionStore, journal_path: Path,
                     verifier: Callable[..., Any], cancel_event: Any | None,
                     clock: Callable[[], datetime]) -> dict[str, Any]:
    journal = _read_journal(journal_path); identity = _identity(work_order, journal)
    _require(journal["phase"] == "model_returned", "MENTOR_ATTEMPT_NOT_RECONCILABLE")
    at = _event_at(work_order, journal)
    _record_thread(work_order, store, journal["transport"]["thread_id"], at)
    if identity["cycle_id"] in _load_store(work_order, store)["cycle_ids"]:
        journal = {**journal, "phase": "ledger_committed", "updated_at": datetime.now(UTC).isoformat()}
        _atomic(journal_path, journal)
        return _actual_cycle(work_order, store, identity["cycle_id"])
    output = _retain_output(work_order, journal_path, journal)
    journal = _read_journal(journal_path)
    verifier_dir = _private_directory(work_order.workspace / ".job-runtime" / "mentor-verifier" /
                                      work_order.logical_session.logical_session_id / identity["cycle_id"],
                                      work_order.workspace)
    artifact, failure = _invoke_verifier(verifier, work_order, identity["cycle_id"], output, verifier_dir,
                                         journal["effective_timeout_seconds"], cancel_event, clock)
    return _close_cycle(work_order, store, journal_path, "succeeded" if artifact else "failed",
                        "MENTOR_CYCLE_VERIFIED" if artifact else failure or "MENTOR_VERIFIER_FAILED",
                        action_sha=_semantic_action_sha(output), artifact=artifact, at=at)


def _prepare(work_order: WorkOrder, store: DurableSessionStore, profile: dict[str, Any],
             variant_id: str, external_engine_attempt_id: str | None, cancel_event: Any | None,
             clock: Callable[[], datetime], run_root: Path) -> tuple[Path, dict[str, Any], dict[str, Any], str, Path]:
    at = _now(clock); head = _guard(work_order, store, at, cancel_event, variant_id)
    clean_profile, timeout = _validated_profile(profile, work_order, at)
    plan = _plan_text(work_order)
    cycle_id = f"cycle-{head['turns_used'] + 1}-{secrets.token_hex(8)}"
    schema = _schema(cycle_id, variant_id, [item.criterion_id for item in work_order.acceptance_criteria])
    _require(len(canonical_json_bytes(schema)) <= 32 * 1024, "MENTOR_MODEL_SCHEMA_TOO_LARGE")
    prompt = _prompt(work_order, head, cycle_id, variant_id, plan)
    attempt_id = "attempt-" + secrets.token_hex(12)
    attempt_type = "scheduled_external" if external_engine_attempt_id is not None else "manual"
    if external_engine_attempt_id is not None:
        external_engine_attempt_id = _identifier(external_engine_attempt_id, "MENTOR_ENGINE_ATTEMPT_ID_INVALID")
    identity = {"attempt_id": attempt_id, "attempt_type": attempt_type,
                "external_engine_attempt_id": external_engine_attempt_id, "cycle_id": cycle_id,
                "variant_id": variant_id, "work_order_id": work_order.work_order_id,
                "logical_session_id": work_order.logical_session.logical_session_id,
                "plan_sha256": work_order.plan.sha256, "acceptance_sha256": work_order.acceptance.sha256}
    intent_sha = hashlib.sha256(canonical_json_bytes({"action": "model_turn", "variant_id": variant_id,
                                                      "plan_sha256": work_order.plan.sha256,
                                                      "acceptance_sha256": work_order.acceptance.sha256})).hexdigest()
    attempt_dir = _private_directory(_attempt_root(work_order) / attempt_id, work_order.workspace)
    journal_path = attempt_dir / "journal.json"
    journal = {"schema_version": 1, "phase": "prepared", "identity": identity,
               "intent_sha256": intent_sha, "effective_timeout_seconds": timeout,
               "event_at": at.isoformat(), "created_at": at.isoformat(), "updated_at": at.isoformat()}
    _atomic(journal_path, journal)
    return journal_path, clean_profile, schema, prompt, run_root / cycle_id


def run_cycles(work_order: WorkOrder, store: DurableSessionStore, profile: dict[str, Any],
               verifier: Callable[..., Any], *, model_call: Callable[..., dict[str, Any]] = run_codex,
               max_cycles_this_run: int = 1, cancel_event: Any | None = None,
               clock: Callable[[], datetime] = lambda: datetime.now(UTC), variant_id: str = "baseline",
               external_engine_attempt_id: str | None = None) -> dict[str, Any]:
    """Run bounded sequential cycles; external engine IDs are trusted scheduler input."""
    results: list[dict[str, Any]] = []
    try:
        _require(isinstance(work_order, WorkOrder) and isinstance(store, DurableSessionStore) and
                 work_order.workspace == store.workspace and callable(model_call) and callable(verifier),
                 "MENTOR_RUNNER_INPUT_INVALID")
        _require(type(max_cycles_this_run) is int and 1 <= max_cycles_this_run <= 128,
                 "MENTOR_RUN_CYCLE_BOUND_INVALID")
        variant_id = _identifier(variant_id, "MENTOR_VARIANT_ID_INVALID")
        with _session_lock(work_order):
            run_root = _private_directory(work_order.workspace / ".job-runtime" / "mentor-runs" /
                work_order.logical_session.logical_session_id / ("run-" + secrets.token_hex(12)), work_order.workspace)
            for index in range(max_cycles_this_run):
                journal_path, clean_profile, schema, prompt, run_dir = _prepare(
                    work_order, store, profile, variant_id, external_engine_attempt_id,
                    cancel_event, clock, run_root)
                try:
                    result = model_call(clean_profile, prompt, work_order.workspace, run_dir,
                                        context={"response_schema": schema, "cancel_event": cancel_event})
                except Exception:
                    results.append(_fence_unknown(work_order, store, journal_path, "MENTOR_MODEL_CALL_EXCEPTION")); break
                deterministic = _pre_dispatch_result(result)
                if deterministic is not None:
                    status, code = deterministic
                    if status == "retryable":
                        closed = _close_without_cycle(work_order, journal_path, code, status="retryable")
                    else:
                        closed = _close_cycle(work_order, store, journal_path, "failed", code,
                            action_sha=_read_journal(journal_path)["intent_sha256"],
                            at=_event_at(work_order, _read_journal(journal_path)))
                    results.append(closed)
                    break
                try:
                    receipt = _transport(result, clean_profile["model"])
                    event_at = _event_at(work_order, _read_journal(journal_path))
                    journal = _read_journal(journal_path)
                    response_path = receipt["response_path"]
                    if not (isinstance(response_path, str) and len(response_path) <= 1024): response_path = None
                    response_sha = receipt["response_sha256"]
                    if not (isinstance(response_sha, str) and _SHA_RE.fullmatch(response_sha)): response_sha = None
                    transport = {"thread_id": receipt["thread_id"], "response_path": response_path,
                                 "response_sha256": response_sha,
                                 "run_directory": str(run_dir.relative_to(work_order.workspace))}
                    journal = {**journal, "phase": "model_returned", "transport": transport,
                               "updated_at": datetime.now(UTC).isoformat()}
                    _atomic(journal_path, journal)
                    _record_thread(work_order, store, receipt["thread_id"], event_at)
                    _retain_output(work_order, journal_path, journal)
                    results.append(_commit_retained(work_order, store, journal_path, verifier, cancel_event, clock))
                    if results[-1]["status"] != "succeeded": break
                except RunnerError as error:
                    results.append(_fence_unknown(work_order, store, journal_path, str(error))); break
                except (ContractError, StateError):
                    results.append(_close_without_cycle(work_order, journal_path,
                                                        "MENTOR_POST_MODEL_STATE_LIMIT"))
                    break
                except Exception:
                    results.append(_fence_unknown(work_order, store, journal_path, "MENTOR_CYCLE_PROCESSING_FAILED")); break
                if external_engine_attempt_id is not None: break
        return {"status": results[-1]["status"] if results else "failed",
                "code": "MENTOR_RUN_COMPLETED" if results and all(item["status"] == "succeeded" for item in results)
                        else results[-1]["code"] if results else "MENTOR_RUN_NO_CYCLES",
                "cycles": results, "cycles_attempted": len(results)}
    except RunnerError as error:
        return {"status": "blocked", "code": str(error), "cycles": results, "cycles_attempted": len(results)}
    except (ContractError, StateError):
        return {"status": "blocked", "code": "MENTOR_STATE_REVALIDATION_FAILED",
                "cycles": results, "cycles_attempted": len(results)}
    except Exception:
        return {"status": "unknown", "code": "MENTOR_RUNNER_FAILED", "cycles": results,
                "cycles_attempted": len(results)}


def reconcile_attempt(work_order: WorkOrder, store: DurableSessionStore, attempt_id: str,
                      verifier: Callable[..., Any], *, cancel_event: Any | None = None,
                      clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> dict[str, Any]:
    """Reconcile retained evidence under the dispatch lock, never invoking a model."""
    try:
        attempt_id = _identifier(attempt_id, "MENTOR_ATTEMPT_ID_INVALID")
        with _session_lock(work_order):
            work_order.verify_bindings()
            path = _attempt_root(work_order) / attempt_id / "journal.json"
            journal = _read_journal(path); identity = _identity(work_order, journal)
            if journal["phase"] == "ledger_committed":
                ledger = journal.get("ledger", {})
                if ledger.get("recorded") is False:
                    return {"status": "failed", "code": ledger.get("terminal_code", "MENTOR_TERMINAL_LOCAL_FAILURE"),
                            "cycle_id": identity["cycle_id"], "outcome": "failed", "progressed": False}
                return _actual_cycle(work_order, store, identity["cycle_id"])
            if journal["phase"] == "prepared": return _fence_unknown(work_order, store, path, "MENTOR_PREPARED_INTENT_FENCED")
            return _commit_retained(work_order, store, path, verifier, cancel_event, clock)
    except RunnerError as error: return {"status": "blocked", "code": str(error)}
    except (ContractError, StateError): return {"status": "blocked", "code": "MENTOR_STATE_REVALIDATION_FAILED"}
    except Exception: return {"status": "unknown", "code": "MENTOR_RECONCILIATION_FAILED"}
