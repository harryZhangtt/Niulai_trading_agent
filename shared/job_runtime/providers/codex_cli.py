"""Source-only normalization of provider-neutral one-shot runner evidence.

A separate trusted translation boundary must convert pinned provider output into
``NormalizedCodexRunnerEvidenceV1``. The Codex 0.167 source candidate remains
activation-blocked pending official asset and sanitized live-capture evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Mapping

from shared.job_runtime.provider_contract import ProviderResultV1
from shared.job_runtime.retry_policy import parse_retry_after

CAPABILITIES = {
    "contract_ready": True,
    "runner_translation_verified": False,
    "runtime_unverified": True,
}
NORMALIZED_SCHEMA = "normalized_codex_runner_v1"
NORMALIZED_VERSION = 1
PRODUCTION_TRANSLATION = {
    "provider_cli_version": "0.167.0",
    "available": False,
    "activation_blocked": True,
    "activation_requires": (
        "official_asset_binding", "sanitized_live_capture_conformance",
        "canonical_integration_review",
    ),
    "source_candidate_conformance_verified": True,
    "official_asset_binding_verified": False,
    "sanitized_live_capture_conformance_verified": False,
    "canonical_integration_reviewed": False,
}
MAX_EVENT_BYTES = 1024 * 1024
MAX_FINAL_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 64 * 1024
MAX_DEPTH = 12
MAX_ITEMS = 256
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ACTIVITY_KINDS = frozenset({
    "command", "mcp", "web_search", "file_change", "tool", "collaboration",
})
_USAGE_KEYS = (
    "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens",
)
_CLASS_FIELDS = {
    "category", "authority", "http_status", "provider_should_retry",
    "retry_after", "retry_after_source",
}
_CATEGORIES = frozenset({
    "none", "http", "connection", "dns", "tls", "timeout",
    "connection_reset", "quota_exhausted", "auth", "model", "config",
    "policy", "provider",
})
_AUTHORITIES = frozenset({"none", "not_submitted", "verified_terminal"})
_PERMANENT = {"quota_exhausted", "auth", "model", "config", "policy"}
_EVENT_FIELDS = {
    "invocation.started": frozenset({"type", "opaque_identity", "model"}),
    "invocation.completed": frozenset({"type", "usage", "model"}),
    "invocation.failed": frozenset({"type", "failure", "model"}),
    "runner.error": frozenset({"type", "failure", "model"}),
    "activity.observed": frozenset({"type", "activity", "model"}),
}
_FAILURE_FIELDS = frozenset({"classification"})
_ACTIVITY_FIELDS = frozenset({"kind"})


class CodexCliAdapterError(ValueError):
    """Stable local input error; never includes runner/provider text."""


class _EvidenceError(ValueError):
    def __init__(self, code: str, kind: str = "partial_response") -> None:
        super().__init__(code)
        self.code = code
        self.kind = kind


@dataclass(frozen=True)
class NormalizedCodexRunnerEvidenceV1:
    """Provider-neutral output of a separately trusted runner translation."""

    schema: str
    process_phase: str
    exit_code: int | None
    signal: int | None
    events_jsonl: bytes
    events_ref: str
    events_sha256: str
    final_output_ref: str | None
    final_output_sha256: str | None
    final_output_size: int | None
    started_at: datetime
    ended_at: datetime
    deadline_at: datetime
    stderr_classification: Mapping[str, Any]


@dataclass(frozen=True)
class ArtifactSnapshot:
    data: bytes
    sha256: str
    size: int
    device: int
    inode: int


class FinalOutputResolver:
    """Descriptor-sealed reader under one owner-private evidence root."""

    def __init__(self, evidence_root: str | os.PathLike[str]):
        try:
            self.evidence_root = Path(os.path.abspath(evidence_root))
        except (OSError, TypeError, ValueError):
            raise CodexCliAdapterError("CODEX_FINAL_ROOT_INVALID") from None
        details = self._private(self.evidence_root, directory=True)
        self._root_identity = (details.st_dev, details.st_ino)

    @staticmethod
    def _private(path: Path, *, directory: bool) -> os.stat_result:
        try:
            details = os.lstat(path)
        except OSError:
            raise CodexCliAdapterError("CODEX_FINAL_PATH_INVALID") from None
        expected = stat.S_ISDIR if directory else stat.S_ISREG
        if (stat.S_ISLNK(details.st_mode) or details.st_uid != os.getuid()
                or stat.S_IMODE(details.st_mode) & 0o077 or not expected(details.st_mode)):
            raise CodexCliAdapterError("CODEX_FINAL_PATH_UNSAFE")
        return details

    def _after_open(self, _path: Path, _descriptor: int) -> None:
        """Test seam for replacement races; production performs no action."""

    def read(self, relative_path: str, *, max_bytes: int = MAX_FINAL_BYTES) -> ArtifactSnapshot:
        if type(relative_path) is not str:
            raise CodexCliAdapterError("CODEX_FINAL_REF_INVALID")
        relative = Path(relative_path)
        if (not relative.parts or relative.is_absolute() or ".." in relative.parts
                or any(part in ("", ".") for part in relative.parts)):
            raise CodexCliAdapterError("CODEX_FINAL_REF_INVALID")
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            directory = os.open(self.evidence_root, directory_flags)
        except OSError:
            raise CodexCliAdapterError("CODEX_FINAL_OPEN_FAILED") from None
        root_details = os.fstat(directory)
        if ((root_details.st_dev, root_details.st_ino) != self._root_identity
                or not stat.S_ISDIR(root_details.st_mode)
                or root_details.st_uid != os.getuid()
                or stat.S_IMODE(root_details.st_mode) & 0o077):
            os.close(directory)
            raise CodexCliAdapterError("CODEX_FINAL_PATH_UNSAFE")
        opened_directories = [directory]
        descriptor = None
        candidate = self.evidence_root / relative
        try:
            for part in relative.parts[:-1]:
                try:
                    directory = os.open(part, directory_flags, dir_fd=directory)
                except OSError:
                    raise CodexCliAdapterError("CODEX_FINAL_PATH_UNSAFE") from None
                opened_directories.append(directory)
                details = os.fstat(directory)
                if (not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid()
                        or stat.S_IMODE(details.st_mode) & 0o077):
                    raise CodexCliAdapterError("CODEX_FINAL_PATH_UNSAFE")
            try:
                candidate_details = os.stat(relative.parts[-1], dir_fd=directory,
                                            follow_symlinks=False)
            except OSError:
                raise CodexCliAdapterError("CODEX_FINAL_OPEN_FAILED") from None
            if stat.S_ISLNK(candidate_details.st_mode):
                raise CodexCliAdapterError("CODEX_FINAL_PATH_UNSAFE")
            try:
                descriptor = os.open(relative.parts[-1],
                                     os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                                     dir_fd=directory)
            except OSError:
                raise CodexCliAdapterError("CODEX_FINAL_OPEN_FAILED") from None
            before = os.fstat(descriptor)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or stat.S_IMODE(before.st_mode) & 0o077
                    or not 0 < before.st_size <= max_bytes):
                raise CodexCliAdapterError("CODEX_FINAL_PATH_UNSAFE")
            self._after_open(candidate, descriptor)
            chunks: list[bytes] = []
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = os.read(descriptor, min(65536, max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise CodexCliAdapterError("CODEX_FINAL_SIZE_INVALID")
                chunks.append(chunk)
                digest.update(chunk)
            after = os.fstat(descriptor)
            try:
                current_path = os.stat(relative.parts[-1], dir_fd=directory,
                                       follow_symlinks=False)
            except OSError:
                raise CodexCliAdapterError("CODEX_FINAL_CHANGED") from None
            if ((before.st_dev, before.st_ino, before.st_size,
                 before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_dev, after.st_ino, total,
                        after.st_mtime_ns, after.st_ctime_ns)
                    or (after.st_dev, after.st_ino)
                    != (current_path.st_dev, current_path.st_ino)):
                raise CodexCliAdapterError("CODEX_FINAL_CHANGED")
            return ArtifactSnapshot(b"".join(chunks), digest.hexdigest(), total,
                                    after.st_dev, after.st_ino)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            for opened in reversed(opened_directories):
                os.close(opened)


def _require(ok: bool, code: str, kind: str = "partial_response") -> None:
    if not ok:
        raise _EvidenceError(code, kind)


def _pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in rows:
        if key in result:
            raise _EvidenceError("CODEX_EVENT_DUPLICATE_KEY")
        result[key] = value
    return result


def _bounded(value: Any) -> None:
    count = 0
    stack = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        count += 1
        _require(count <= MAX_ITEMS and depth <= MAX_DEPTH, "CODEX_EVENT_BOUNDS")
        if isinstance(current, Mapping):
            _require(len(current) <= MAX_ITEMS, "CODEX_EVENT_BOUNDS")
            stack.extend((item, depth + 1) for pair in current.items() for item in pair)
        elif isinstance(current, list):
            _require(len(current) <= MAX_ITEMS, "CODEX_EVENT_BOUNDS")
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, str):
            _require(len(current.encode()) <= MAX_LINE_BYTES, "CODEX_EVENT_BOUNDS")
        else:
            _require(current is None or type(current) in {bool, int, float},
                     "CODEX_EVENT_TYPE")
            if type(current) is float:
                _require(current == current and abs(current) != float("inf"),
                         "CODEX_EVENT_NUMBER")


def _timestamp(value: Any, code: str) -> datetime:
    _require(isinstance(value, datetime) and value.tzinfo is not None
             and value.utcoffset() is not None, code, "unknown")
    return value


def _identifier(value: Any, code: str) -> str:
    _require(type(value) is str and _ID.fullmatch(value) is not None, code, "unknown")
    return value


def _hash(value: Any, code: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    _require(type(value) is str and _SHA.fullmatch(value) is not None
             and value != "0" * 64, code, "unknown")
    return value


def _has_first_valid_event(raw: bytes) -> bool:
    """Return whether the stream begins with one complete, bounded event object."""
    first, separator, _ = raw.partition(b"\n")
    if not separator or not first or len(first) > MAX_LINE_BYTES:
        return False
    try:
        event = json.loads(first, object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if type(event) is not dict or type(event.get("type")) is not str or not event["type"]:
            return False
        _bounded(event)
        return True
    except (TypeError, ValueError, UnicodeError):
        return False


def _parse_events(raw: bytes, expected_model: str) -> dict[str, Any]:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_EVENT_BYTES,
             "CODEX_EVENT_STREAM_SIZE")
    _require(not raw.startswith(b"\xef\xbb\xbf"), "CODEX_EVENT_ENCODING")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _EvidenceError("CODEX_EVENT_ENCODING") from None
    _require(text.endswith("\n"), "CODEX_EVENT_TRUNCATED")
    invocation_count = terminal_count = valid_count = 0
    terminal_kind = None
    terminal_failure = False
    tool_activity = False
    observed_model = None
    usage = None
    for encoded in raw.splitlines():
        _require(0 < len(encoded) <= MAX_LINE_BYTES, "CODEX_EVENT_LINE_SIZE")
        try:
            event = json.loads(encoded, object_pairs_hook=_pairs,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except _EvidenceError:
            raise
        except (TypeError, ValueError, UnicodeError):
            raise _EvidenceError("CODEX_EVENT_MALFORMED") from None
        _require(type(event) is dict, "CODEX_EVENT_MALFORMED")
        _bounded(event)
        kind = event.get("type")
        _require(type(kind) is str and kind in _EVENT_FIELDS, "CODEX_EVENT_TYPE")
        _require(set(event) <= _EVENT_FIELDS[kind], "CODEX_EVENT_FIELDS")
        _require(terminal_count == 0, "CODEX_EVENT_AFTER_TERMINAL")
        valid_count += 1
        if kind == "invocation.started":
            invocation_count += 1
            _require(invocation_count == 1 and valid_count == 1, "CODEX_INVOCATION_ORDER")
        else:
            _require(invocation_count == 1, "CODEX_INVOCATION_ORDER")
        model = event.get("model")
        if model is not None:
            _require(type(model) is str and model == expected_model,
                     "CODEX_MODEL_MISMATCH", "provider")
            observed_model = model
        if kind in {"invocation.failed", "runner.error"}:
            failure = event.get("failure")
            _require(type(failure) is dict and set(failure) <= _FAILURE_FIELDS,
                     "CODEX_NORMALIZED_FAILURE_FIELDS")
        if kind == "activity.observed":
            activity = event.get("activity")
            _require(type(activity) is dict and set(activity) == _ACTIVITY_FIELDS,
                     "CODEX_NORMALIZED_ACTIVITY_FIELDS")
            _require(activity["kind"] in _ACTIVITY_KINDS,
                     "CODEX_NORMALIZED_ACTIVITY_UNSUPPORTED")
            tool_activity = True
        if kind in {"invocation.completed", "invocation.failed", "runner.error"}:
            terminal_count += 1
            terminal_kind = kind
            terminal_failure = kind != "invocation.completed"
            if kind == "invocation.completed" and isinstance(event.get("usage"), Mapping):
                usage_value = event["usage"]
                if all(type(value) is int and value >= 0 for value in usage_value.values()):
                    usage = {key: usage_value[key] for key in _USAGE_KEYS
                             if key in usage_value}
    _require(invocation_count == 1, "CODEX_INVOCATION_COUNT")
    _require(terminal_count == 1, "CODEX_TERMINAL_COUNT", "missing_terminal")
    return {
        "event_count": valid_count, "terminal_kind": terminal_kind,
        "terminal_failure": terminal_failure, "tool_activity": tool_activity,
        "observed_model": observed_model, "usage": usage,
    }


def _result(operation_id: str, *, phase: str, submission: str, proof: str,
            status: str, code: str, failure_kind: str, receipt: Mapping[str, Any],
            http_status: int | None = None, retry: bool | None = None,
            retry_after_at: datetime | None = None,
            retry_after_source: str | None = None) -> ProviderResultV1:
    return ProviderResultV1(
        provider="codex_cli", operation_id=operation_id, phase=phase,
        submission=submission, terminal_proof=proof, status=status, code=code,
        failure_kind=failure_kind, http_status=http_status,
        provider_should_retry=retry, retry_after_at=retry_after_at,
        retry_after_source=retry_after_source, receipt=receipt,
    )


def _base_receipt() -> dict[str, Any]:
    return {**CAPABILITIES, "automatic_retry": False,
            "normalized_schema": NORMALIZED_SCHEMA,
            "normalized_version": NORMALIZED_VERSION}


def _unknown(operation_id: str, phase: str, submission: str, code: str,
             kind: str, receipt: Mapping[str, Any]) -> ProviderResultV1:
    safe_kind = kind if kind in {
        "timeout", "connection_reset", "partial_response", "missing_terminal"
    } else "unknown"
    return _result(operation_id, phase=phase, submission=submission, proof="absent",
                   status="unknown", code=code, failure_kind=safe_kind,
                   retry=False, receipt=receipt)


def _validate_envelope(value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    _require(isinstance(value, NormalizedCodexRunnerEvidenceV1),
             "CODEX_NORMALIZED_EVIDENCE_TYPE", "unknown")
    _require(value.schema == NORMALIZED_SCHEMA,
             "CODEX_NORMALIZED_SCHEMA", "unknown")
    value = {
        "process_phase": value.process_phase,
        "exit_code": value.exit_code,
        "signal": value.signal,
        "events_jsonl": value.events_jsonl,
        "events_ref": value.events_ref,
        "events_sha256": value.events_sha256,
        "final_output_ref": value.final_output_ref,
        "final_output_sha256": value.final_output_sha256,
        "final_output_size": value.final_output_size,
        "started_at": value.started_at,
        "ended_at": value.ended_at,
        "deadline_at": value.deadline_at,
        "stderr_classification": dict(value.stderr_classification)
        if isinstance(value.stderr_classification, Mapping) else value.stderr_classification,
    }
    phase = value["process_phase"]
    _require(phase in {"not_started", "connecting", "submitted"},
             "CODEX_PROCESS_PHASE", "unknown")
    exit_code, signal = value["exit_code"], value["signal"]
    _require((exit_code is None or type(exit_code) is int)
             and (signal is None or type(signal) is int and signal > 0)
             and not (exit_code is not None and signal is not None),
             "CODEX_PROCESS_STATUS", "unknown")
    raw = value["events_jsonl"]
    _require(type(raw) is bytes and len(raw) <= MAX_EVENT_BYTES,
             "CODEX_EVENT_STREAM_SIZE")
    _identifier(value["events_ref"], "CODEX_EVENT_REF")
    stream_hash = _hash(value["events_sha256"], "CODEX_EVENT_HASH")
    _require(hashlib.sha256(raw).hexdigest() == stream_hash,
             "CODEX_EVENT_HASH_MISMATCH")
    _identifier(value["final_output_ref"], "CODEX_FINAL_REF") if value["final_output_ref"] is not None else None
    _hash(value["final_output_sha256"], "CODEX_FINAL_HASH", optional=True)
    size = value["final_output_size"]
    _require(size is None or type(size) is int and 0 <= size <= MAX_FINAL_BYTES,
             "CODEX_FINAL_SIZE")
    final_values = (value["final_output_ref"], value["final_output_sha256"], size)
    _require(all(item is None for item in final_values) or all(item is not None for item in final_values),
             "CODEX_FINAL_BINDING")
    started = _timestamp(value["started_at"], "CODEX_STARTED_AT")
    ended = _timestamp(value["ended_at"], "CODEX_ENDED_AT")
    deadline = _timestamp(value["deadline_at"], "CODEX_DEADLINE_AT")
    _require(started <= ended <= deadline, "CODEX_TIME_ORDER", "unknown")
    classification = value["stderr_classification"]
    _require(type(classification) is dict and set(classification) == _CLASS_FIELDS,
             "CODEX_CLASSIFICATION_FIELDS", "unknown")
    _require(classification["category"] in _CATEGORIES
             and classification["authority"] in _AUTHORITIES,
             "CODEX_CLASSIFICATION_VALUE", "unknown")
    _require(classification["authority"] != "not_submitted" or phase in {"not_started", "connecting"},
             "CODEX_CLASSIFICATION_AUTHORITY", "unknown")
    http_status = classification["http_status"]
    _require(http_status is None or type(http_status) is int and 100 <= http_status <= 599,
             "CODEX_HTTP_STATUS", "unknown")
    _require((classification["category"] == "http") == (http_status is not None),
             "CODEX_HTTP_CLASSIFICATION", "unknown")
    retry = classification["provider_should_retry"]
    _require(retry is None or type(retry) is bool, "CODEX_RETRY_HINT", "unknown")
    retry_value, retry_source = classification["retry_after"], classification["retry_after_source"]
    _require((retry_value is None) == (retry_source is None),
             "CODEX_RETRY_AFTER_BINDING", "unknown")
    return value, classification


def run_one_shot(*, operation_id: str, expected_model: str,
                 invocation_runner: Callable[[], NormalizedCodexRunnerEvidenceV1],
                 file_resolver: FinalOutputResolver | None = None,
                 configured_model_nonclaim: bool = False) -> ProviderResultV1:
    """Invoke a trusted runner exactly once and normalize detached evidence.

    The runner must return provider-neutral normalized evidence.  A separate,
    currently absent production translator owns provider-specific parsing and must
    classify stderr before returning; raw stderr is never accepted as authority.
    """
    if type(operation_id) is not str or _ID.fullmatch(operation_id) is None:
        raise CodexCliAdapterError("CODEX_OPERATION_ID_INVALID")
    if type(expected_model) is not str or _ID.fullmatch(expected_model) is None:
        raise CodexCliAdapterError("CODEX_EXPECTED_MODEL_INVALID")
    if not callable(invocation_runner):
        raise CodexCliAdapterError("CODEX_RUNNER_INVALID")
    if type(configured_model_nonclaim) is not bool:
        raise CodexCliAdapterError("CODEX_MODEL_POLICY_INVALID")
    if file_resolver is not None and not isinstance(file_resolver, FinalOutputResolver):
        raise CodexCliAdapterError("CODEX_FINAL_RESOLVER_INVALID")
    receipt = _base_receipt()
    receipt.update(model_binding_source=("configured_cli_argument" if configured_model_nonclaim else "provider_event"),
                   provider_reported_model=False if configured_model_nonclaim else None)
    try:
        raw_evidence = invocation_runner()
    except Exception:
        return _unknown(operation_id, "submitted", "possibly_submitted",
                        "CODEX_RUNNER_OUTCOME_UNKNOWN", "unknown", receipt)
    phase = "submitted"
    submission = "possibly_submitted"
    try:
        evidence, classification = _validate_envelope(raw_evidence)
        process_phase = evidence["process_phase"]
        if process_phase in {"not_started", "connecting"}:
            phase, submission = process_phase, "not_submitted"
        event_hash = evidence["events_sha256"]
        receipt.update({
            "process_phase": process_phase,
            "event_stream_sha256": event_hash,
            "event_stream_size": len(evidence["events_jsonl"]),
            "exit_code": evidence["exit_code"], "signal_number": evidence["signal"],
        })
        category, authority = classification["category"], classification["authority"]
        if process_phase in {"not_started", "connecting"}:
            _require(authority == "not_submitted", "CODEX_PRELAUNCH_ATTESTATION", "unknown")
            _require(evidence["events_jsonl"] == b""
                     and evidence["final_output_ref"] is None
                     and evidence["final_output_sha256"] is None
                     and evidence["final_output_size"] is None
                     and evidence["exit_code"] is None and evidence["signal"] is None,
                     "CODEX_PRELAUNCH_EVIDENCE_CONFLICT", "unknown")
            if category in _PERMANENT:
                code = {
                    "quota_exhausted": "MODEL_QUOTA_EXHAUSTED",
                    "auth": "MODEL_AUTH_REQUIRED", "model": "MODEL_UNAVAILABLE",
                    "config": "MODEL_CONFIGURATION_REJECTED",
                    "policy": "MODEL_POLICY_VIOLATION",
                }[category]
                return _result(operation_id, phase=phase, submission=submission, proof="absent",
                               status="failed", code=code, failure_kind=category,
                               retry=False, receipt=receipt)
            hint = classification["provider_should_retry"]
            typed_candidate = (category in {"connection", "dns", "tls"}
                               or category == "http" and classification["http_status"] in
                               ({408, 409, 429, 529} | set(range(500, 600))))
            retryable = hint is True or (hint is None and typed_candidate)
            if retryable:
                retry_at = None
                source = classification["retry_after_source"]
                if source is not None:
                    retry_at = parse_retry_after(classification["retry_after"], source,
                                                 now=evidence["ended_at"])
                kind = ("http" if category == "http" else "connection"
                        if category in {"connection", "dns", "tls"} else "provider")
                code = ("CODEX_HTTP_RETRY_CANDIDATE" if kind == "http" else
                        "CODEX_CONNECT_RETRY_CANDIDATE" if kind == "connection" else
                        "CODEX_PROVIDER_RETRY_CANDIDATE")
                return _result(operation_id, phase=phase, submission=submission, proof="absent",
                               status="retryable", code=code, failure_kind=kind,
                               http_status=classification["http_status"], retry=True,
                               retry_after_at=retry_at, retry_after_source=source,
                               receipt=receipt)
            return _result(operation_id, phase=phase, submission=submission, proof="absent",
                           status="failed", code="CODEX_PRELAUNCH_FAILURE",
                           failure_kind="provider", retry=False, receipt=receipt)

        if _has_first_valid_event(evidence["events_jsonl"]):
            phase = "streaming"
        parsed = _parse_events(evidence["events_jsonl"], expected_model)
        phase = "streaming"
        receipt.update({
            "event_count": parsed["event_count"],
            "observed_model_verified": parsed["observed_model"] is not None,
            "terminal_kind": parsed["terminal_kind"],
            "usage": parsed["usage"],
            "final_output_sha256": evidence["final_output_sha256"],
            "final_output_size": evidence["final_output_size"],
        })
        if (not parsed["terminal_failure"] and authority == "verified_terminal"
                and category in _PERMANENT):
            return _result(operation_id, phase="terminal", submission="definitely_submitted",
                           proof="contradictory", status="unknown",
                           code="CODEX_TERMINAL_EVIDENCE_CONTRADICTORY",
                           failure_kind="unknown", retry=False, receipt=receipt)
        if parsed["tool_activity"]:
            return _result(operation_id, phase="terminal", submission="definitely_submitted",
                           proof="verified", status="failed",
                           code="MODEL_TOOL_POLICY_VIOLATION", failure_kind="policy",
                           retry=False, receipt=receipt)
        if parsed["terminal_failure"]:
            if authority != "verified_terminal":
                return _unknown(operation_id, phase, "definitely_submitted",
                                "CODEX_TERMINAL_FAILURE_UNVERIFIED", "unknown", receipt)
            if category in _PERMANENT:
                code = {
                    "quota_exhausted": "MODEL_QUOTA_EXHAUSTED",
                    "auth": "MODEL_AUTH_REQUIRED", "model": "MODEL_UNAVAILABLE",
                    "config": "MODEL_CONFIGURATION_REJECTED",
                    "policy": "MODEL_POLICY_VIOLATION",
                }[category]
                return _result(operation_id, phase="terminal", submission="definitely_submitted",
                               proof="verified", status="failed", code=code,
                               failure_kind=category, retry=False, receipt=receipt)
            if category in {"timeout", "connection_reset"}:
                kind = "timeout" if category == "timeout" else "connection_reset"
                return _result(operation_id, phase="terminal", submission="definitely_submitted",
                               proof="verified", status="unknown",
                               code="CODEX_VERIFIED_TERMINAL_TRANSPORT_FAILURE",
                               failure_kind=kind, retry=False, receipt=receipt)
            kind = ("http" if category == "http" else "connection"
                    if category in {"connection", "dns", "tls"} else "provider")
            return _result(operation_id, phase="terminal", submission="definitely_submitted",
                           proof="verified", status="failed",
                           code="CODEX_VERIFIED_TERMINAL_FAILURE", failure_kind=kind,
                           http_status=classification["http_status"], retry=False,
                           receipt=receipt)
        success = (evidence["exit_code"] == 0 and evidence["signal"] is None
                   and evidence["ended_at"] <= evidence["deadline_at"]
                   and evidence["final_output_sha256"] is not None
                   and evidence["final_output_size"] is not None
                   and 0 < evidence["final_output_size"] <= MAX_FINAL_BYTES)
        if success and parsed["observed_model"] is None and not configured_model_nonclaim:
            return _unknown(operation_id, phase, "definitely_submitted",
                            "MODEL_IDENTITY_UNVERIFIED", "unknown", receipt)
        if success and file_resolver is None:
            return _unknown(operation_id, phase, "definitely_submitted",
                            "CODEX_FINAL_CUSTODY_UNVERIFIED", "unknown", receipt)
        if success:
            try:
                snapshot = file_resolver.read(evidence["final_output_ref"])
            except CodexCliAdapterError as error:
                return _unknown(operation_id, phase, "definitely_submitted",
                                str(error), "partial_response", receipt)
            if (snapshot.sha256 != evidence["final_output_sha256"]
                    or snapshot.size != evidence["final_output_size"]):
                return _unknown(operation_id, phase, "definitely_submitted",
                                "CODEX_FINAL_BINDING_MISMATCH", "partial_response", receipt)
            receipt.update(final_custody_verified=True,
                           final_output_sha256=snapshot.sha256,
                           final_output_size=snapshot.size)
            return _result(operation_id, phase="terminal", submission="definitely_submitted",
                           proof="verified", status="succeeded",
                           code="MODEL_TURN_COMPLETED", failure_kind="none",
                           receipt=receipt)
        kind = "partial_response"
        code = "CODEX_FINAL_OUTPUT_UNVERIFIED"
        if evidence["signal"] is not None:
            code = "CODEX_PROCESS_SIGNALLED"
        elif category == "timeout":
            kind, code = "timeout", "MODEL_DEADLINE_EXCEEDED"
        elif category == "connection_reset":
            kind, code = "connection_reset", "CODEX_CONNECTION_RESET"
        return _unknown(operation_id, phase, "definitely_submitted", code, kind, receipt)
    except _EvidenceError as error:
        return _unknown(operation_id, phase, submission, error.code, error.kind, receipt)
    except Exception:
        return _unknown(operation_id, phase, submission,
                        "CODEX_EVIDENCE_NORMALIZATION_FAILED", "unknown", receipt)
