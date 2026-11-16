"""Source-only normalization of sealed Claude host custody evidence.

No host, provider, model, network, scheduler, daemon, SDK, or email is invoked.
The adapter verifies local operational evidence only; it does not provide remote
attestation and never claims that a Claude runtime is installed.
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
from typing import Any, Mapping

from shared.job_runtime.provider_contract import ProviderResultV1
from shared.research_sources.acquisition_contracts import (
    ContractError, DispatchEvent, DispatchState, validate_dispatch_history,
)

CLAUDE_HOST_EVIDENCE_VERSION = "claude-host-provider-evidence-2"
HOST_IDENTITY_VERSION = "HostIdentityV1"
DISPATCH_JOURNAL_VERSION = "DispatchJournalV1"
TERMINAL_PROOF_VERSION = "TerminalProofV1"
CAPABILITIES = {"contract_ready": True, "runtime_unverified": True}
MAX_ARTIFACT_BYTES = 1024 * 1024
MAX_AGGREGATE_BYTES = 1024 * 1024
MAX_JSON_BYTES = 64 * 1024
MAX_DEPTH = 12
MAX_ITEMS = 256
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_SECRET = re.compile(r"(?i)(bearer\s+|sk-(?:ant-|proj-)?|api[_-]?key\s*[=:]|password\s*[=:]|private key)")
_TOP_FIELDS = {
    "schema_version", "provider", "operation_id", "dispatch_id", "input_sha256",
    "host_session_ref", "host_profile_ref", "backend_identity_ref", "tool_identity_ref",
    "dispatch_journal_ref", "terminal_status", "failure_code", "result_ref",
    "result_sha256", "terminal_proof_ref", "started_at", "captured_at", "finished_at",
    "deadline_at",
}
_REF_FIELDS = {"path", "sha256"}
_IDENTITY_FIELDS = {
    "schema_version", "kind", "operation_id", "dispatch_id", "input_sha256",
    "identity_ref", "identity_sha256",
}
_JOURNAL_FIELDS = {"schema_version", "operation_id", "dispatch_id", "input_sha256", "events"}
_EVENT_FIELDS = {
    "operation_id", "dispatch_id", "input_sha256", "sequence", "state",
    "evidence_sha256", "recorded_at", "previous_event_sha256", "event_sha256",
}
_PROOF_FIELDS = {
    "schema_version", "operation_id", "dispatch_id", "input_sha256",
    "identity_artifact_sha256s", "journal_sha256", "result_sha256",
    "terminal_state", "terminal_status", "failure_code", "started_at",
    "captured_at", "finished_at", "deadline_at",
}
_IDENTITY_KINDS = ("host_session", "host_profile", "backend_identity", "tool_identity")
_PERMANENT = {
    "CLAUDE_HOST_QUOTA_EXHAUSTED": "quota_exhausted",
    "CLAUDE_HOST_AUTH_FAILURE": "auth",
    "CLAUDE_HOST_POLICY_FAILURE": "policy",
    "CLAUDE_HOST_CONFIG_FAILURE": "config",
    "HOST_WEB_FUTURE_EXPOSURE": "policy",
    "HOST_WEB_SOURCE_CHANGED": "policy",
}
_UNKNOWN_CODES = {
    "HOST_WEB_DEADLINE", "HOST_WEB_RESULT_UNKNOWN", "HOST_WEB_UNKNOWN_OUTCOME",
    "CLAUDE_HOST_CONNECTION_RESET", "CLAUDE_HOST_PARTIAL_RESULT",
    "CLAUDE_HOST_TRUNCATED_RESULT", "CLAUDE_HOST_LATE_RESULT",
    "CLAUDE_HOST_IDENTITY_MISMATCH",
    "ACQ_RUNNER_DEADLINE_AFTER_DISPATCH", "ACQ_RUNNER_PROVIDER_OUTCOME_UNKNOWN",
    "ACQ_RUNNER_RESTART_OUTCOME_UNKNOWN",
}
_ALLOWED_CODES = frozenset(_PERMANENT) | _UNKNOWN_CODES | {
    "HOST_WEB_BODY_TOO_LARGE", "HOST_WEB_SOURCE_INACCESSIBLE",
    "HOST_WEB_BODY_UNPARSEABLE", "HOST_WEB_DEADLINE_BEFORE_DISPATCH",
    "NATIVE_TRANSPORT_FAILED", "NATIVE_TRANSPORT_CIRCUIT_OPEN",
    "ACQ_PERMANENT_FAILURE",
}
_FAILURE_RECORD_VERSION = "ClaudeHostFailureV1"


class ClaudeHostAdapterError(ValueError):
    """A stable error code, never raw provider or evidence text."""


class _Duplicate(ValueError):
    pass


@dataclass(frozen=True)
class ArtifactSnapshot:
    data: bytes
    sha256: str
    size: int
    device: int
    inode: int


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise ClaudeHostAdapterError(code)


def _pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in rows:
        if key in out:
            raise _Duplicate
        out[key] = value
    return out


def _bounded(value: Any) -> None:
    stack = [(value, 0)]
    active: set[int] = set()
    while stack:
        current, depth = stack.pop()
        _require(depth <= MAX_DEPTH, "CLAUDE_HOST_JSON_DEPTH")
        if isinstance(current, str):
            _require(len(current) <= 4096 and not _SECRET.search(current),
                     "CLAUDE_HOST_SECRET_REJECTED")
        elif isinstance(current, Mapping):
            identity = id(current)
            _require(identity not in active and len(current) <= MAX_ITEMS,
                     "CLAUDE_HOST_JSON_BOUNDS")
            active.add(identity)
            stack.extend((item, depth + 1) for pair in current.items() for item in pair)
        elif isinstance(current, (list, tuple)):
            identity = id(current)
            _require(identity not in active and len(current) <= MAX_ITEMS,
                     "CLAUDE_HOST_JSON_BOUNDS")
            active.add(identity)
            stack.extend((item, depth + 1) for item in current)
        else:
            _require(current is None or type(current) in {bool, int, float},
                     "CLAUDE_HOST_JSON_TYPE")
            if type(current) is float:
                _require(current == current and abs(current) != float("inf"),
                         "CLAUDE_HOST_JSON_NUMBER")


def _json(value: bytes | str | Mapping[str, Any], code: str = "CLAUDE_HOST_JSON_INVALID") -> dict[str, Any]:
    if isinstance(value, Mapping):
        _bounded(value)
        try:
            raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode()
        except (TypeError, ValueError):
            raise ClaudeHostAdapterError(code) from None
        _require(0 < len(raw) <= MAX_JSON_BYTES, code)
        return dict(value)
    _require(isinstance(value, (bytes, str)), code)
    raw = value.encode() if isinstance(value, str) else value
    _require(0 < len(raw) <= MAX_JSON_BYTES, code)
    try:
        parsed = json.loads(raw, object_pairs_hook=_pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (_Duplicate, TypeError, ValueError, UnicodeError):
        raise ClaudeHostAdapterError(code) from None
    _require(isinstance(parsed, dict), code)
    _bounded(parsed)
    return parsed


def _identifier(value: Any, code: str) -> str:
    _require(type(value) is str and _ID.fullmatch(value) is not None, code)
    return value


def _hash(value: Any, code: str) -> str:
    _require(type(value) is str and _SHA.fullmatch(value) is not None, code)
    return value


def _timestamp(value: Any, code: str) -> datetime:
    _require(type(value) is str, code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ClaudeHostAdapterError(code) from None
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, code)
    return parsed


def _ref(value: Any, code: str, *, optional: bool = False) -> dict[str, str] | None:
    if value is None and optional:
        return None
    _require(isinstance(value, Mapping) and set(value) == _REF_FIELDS, code)
    path = value.get("path")
    _require(type(path) is str and path and not Path(path).is_absolute(), code)
    relative = Path(path)
    _require(relative.parts and ".." not in relative.parts and not _SECRET.search(path), code)
    return {"path": path, "sha256": _hash(value.get("sha256"), code)}


class WorkspaceEvidenceResolver:
    """Descriptor-sealed reader for private evidence under one private workspace root."""

    def __init__(self, workspace_root: str | os.PathLike[str]):
        root = Path(workspace_root)
        _require(bool(root.parts), "CLAUDE_HOST_WORKSPACE_ROOT")
        root = Path(os.path.abspath(os.fspath(root)))
        try:
            details = os.lstat(root)
        except OSError:
            raise ClaudeHostAdapterError("CLAUDE_HOST_EVIDENCE_PATH") from None
        self._private_stat(details, directory=True)
        self.workspace_root = root
        self._root_identity = (details.st_dev, details.st_ino)

    @staticmethod
    def _private_stat(details: os.stat_result, *, directory: bool) -> None:
        _require(details.st_uid == os.getuid() and stat.S_IMODE(details.st_mode) & 0o077 == 0,
                 "CLAUDE_HOST_EVIDENCE_PRIVACY")
        _require(stat.S_ISDIR(details.st_mode) if directory else stat.S_ISREG(details.st_mode),
                 "CLAUDE_HOST_EVIDENCE_PATH")

    def _after_open_directory(self, _path: Path, _descriptor: int) -> None:
        """Test seam after a directory is sealed by descriptor."""

    def _after_open(self, _path: Path, _descriptor: int) -> None:
        """Test seam after the final artifact is sealed by descriptor."""

    def _open_root(self) -> int:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.workspace_root, flags)
        except OSError:
            raise ClaudeHostAdapterError("CLAUDE_HOST_EVIDENCE_OPEN") from None
        try:
            details = os.fstat(descriptor)
            self._private_stat(details, directory=True)
            _require((details.st_dev, details.st_ino) == self._root_identity,
                     "CLAUDE_HOST_EVIDENCE_CHANGED")
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    def read(self, relative_path: str, *, max_bytes: int = MAX_ARTIFACT_BYTES) -> ArtifactSnapshot:
        relative = Path(relative_path)
        _require(relative.parts and not relative.is_absolute()
                 and ".." not in relative.parts and "." not in relative.parts,
                 "CLAUDE_HOST_EVIDENCE_PATH")
        directories: list[int] = []
        descriptor = -1
        try:
            current_fd = self._open_root()
            directories.append(current_fd)
            current_path = self.workspace_root
            self._after_open_directory(current_path, current_fd)
            directory_flags = (os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                               | getattr(os, "O_NOFOLLOW", 0))
            for part in relative.parts[:-1]:
                try:
                    next_fd = os.open(part, directory_flags, dir_fd=current_fd)
                except OSError:
                    raise ClaudeHostAdapterError("CLAUDE_HOST_EVIDENCE_OPEN") from None
                directories.append(next_fd)
                self._private_stat(os.fstat(next_fd), directory=True)
                current_fd = next_fd
                current_path = current_path / part
                self._after_open_directory(current_path, current_fd)
            try:
                final_details = os.stat(relative.parts[-1], dir_fd=current_fd,
                                        follow_symlinks=False)
            except OSError:
                raise ClaudeHostAdapterError("CLAUDE_HOST_EVIDENCE_PATH") from None
            self._private_stat(final_details, directory=False)
            final_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(relative.parts[-1], final_flags, dir_fd=current_fd)
            except OSError:
                raise ClaudeHostAdapterError("CLAUDE_HOST_EVIDENCE_OPEN") from None
            before = os.fstat(descriptor)
            self._private_stat(before, directory=False)
            _require(0 < before.st_size <= max_bytes, "CLAUDE_HOST_EVIDENCE_SIZE")
            self._after_open(current_path / relative.parts[-1], descriptor)
            chunks: list[bytes] = []
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = os.read(descriptor, min(65536, max_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                _require(total <= max_bytes, "CLAUDE_HOST_EVIDENCE_SIZE")
                chunks.append(chunk)
                digest.update(chunk)
            after = os.fstat(descriptor)
            _require((before.st_dev, before.st_ino, before.st_size)
                     == (after.st_dev, after.st_ino, total),
                     "CLAUDE_HOST_EVIDENCE_CHANGED")
            return ArtifactSnapshot(b"".join(chunks), digest.hexdigest(), total,
                                    after.st_dev, after.st_ino)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            for directory in reversed(directories):
                os.close(directory)


def _read_ref(resolver: WorkspaceEvidenceResolver, ref: dict[str, str], *,
              max_bytes: int, total: list[int]) -> ArtifactSnapshot:
    snapshot = resolver.read(ref["path"], max_bytes=max_bytes)
    _require(snapshot.sha256 == ref["sha256"], "CLAUDE_HOST_EVIDENCE_DRIFT")
    total[0] += snapshot.size
    _require(total[0] <= MAX_AGGREGATE_BYTES, "CLAUDE_HOST_EVIDENCE_AGGREGATE_SIZE")
    return snapshot


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def _event_hash(event: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical({key: value for key, value in event.items()
                                      if key != "event_sha256"})).hexdigest()


def _invocation_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in (
        "operation_id", "dispatch_id", "input_sha256", "terminal_status",
        "failure_code", "result_sha256", "started_at", "captured_at",
        "finished_at", "deadline_at",
    )}


def _failure_evidence_sha256(value: Mapping[str, Any]) -> str:
    record = {"schema_version": _FAILURE_RECORD_VERSION, **_invocation_envelope(value)}
    return hashlib.sha256(_canonical(record)).hexdigest()


def _parse_identity(snapshot: ArtifactSnapshot, *, kind: str, operation_id: str,
                    dispatch_id: str, input_sha256: str) -> dict[str, Any]:
    value = _json(snapshot.data, "CLAUDE_HOST_IDENTITY_INVALID")
    _require(set(value) == _IDENTITY_FIELDS and value["schema_version"] == HOST_IDENTITY_VERSION
             and value["kind"] == kind and value["operation_id"] == operation_id
             and value["dispatch_id"] == dispatch_id and value["input_sha256"] == input_sha256,
             "CLAUDE_HOST_IDENTITY_BINDING")
    identity_ref = _identifier(value["identity_ref"], "CLAUDE_HOST_IDENTITY_REF")
    _require(value["identity_sha256"] == hashlib.sha256(identity_ref.encode()).hexdigest(),
             "CLAUDE_HOST_IDENTITY_HASH")
    return value


def _parse_journal(snapshot: ArtifactSnapshot, *, operation_id: str, dispatch_id: str,
                   input_sha256: str, started: datetime, finished: datetime,
                   captured_at: datetime | None) -> tuple[list[dict[str, Any]], tuple[DispatchEvent, ...]]:
    value = _json(snapshot.data, "CLAUDE_HOST_JOURNAL_INVALID")
    _require(set(value) == _JOURNAL_FIELDS and value["schema_version"] == DISPATCH_JOURNAL_VERSION
             and value["operation_id"] == operation_id and value["dispatch_id"] == dispatch_id
             and value["input_sha256"] == input_sha256 and type(value["events"]) is list
             and bool(value["events"]), "CLAUDE_HOST_JOURNAL_BINDING")
    previous_hash = None
    previous_time = None
    typed = []
    for sequence, event in enumerate(value["events"]):
        _require(type(event) is dict and set(event) == _EVENT_FIELDS
                 and event["operation_id"] == operation_id and event["dispatch_id"] == dispatch_id
                 and event["input_sha256"] == input_sha256 and event["sequence"] == sequence
                 and event["previous_event_sha256"] == previous_hash
                 and event["event_sha256"] == _event_hash(event), "CLAUDE_HOST_JOURNAL_CHAIN")
        recorded = _timestamp(event["recorded_at"], "CLAUDE_HOST_JOURNAL_TIME")
        _require(started <= recorded <= finished
                 and (previous_time is None or recorded >= previous_time),
                 "CLAUDE_HOST_JOURNAL_TIME")
        evidence_hash = event["evidence_sha256"]
        if evidence_hash is not None:
            _hash(evidence_hash, "CLAUDE_HOST_JOURNAL_EVIDENCE")
        try:
            typed.append(DispatchEvent(dispatch_id, sequence, DispatchState(event["state"]), evidence_hash))
        except (TypeError, ValueError, ContractError):
            raise ClaudeHostAdapterError("CLAUDE_HOST_JOURNAL_EVENT") from None
        previous_hash = event["event_sha256"]
        previous_time = recorded
    try:
        validated = validate_dispatch_history(typed)
    except ContractError:
        raise ClaudeHostAdapterError("CLAUDE_HOST_JOURNAL_TRANSITION") from None
    if validated[-1].state is DispatchState.CAPTURED:
        _require(captured_at is not None
                 and _timestamp(value["events"][-1]["recorded_at"], "CLAUDE_HOST_JOURNAL_TIME") == captured_at,
                 "CLAUDE_HOST_CAPTURE_TIME_BINDING")
    else:
        _require(captured_at is None, "CLAUDE_HOST_CAPTURE_TIME_BINDING")
    return value["events"], validated


def _validated_failure_code(code: Any) -> int | None:
    _require(type(code) is str and _CODE.fullmatch(code) is not None,
             "CLAUDE_HOST_FAILURE_CODE")
    if code.startswith("SOURCE_HTTP_"):
        suffix = code.removeprefix("SOURCE_HTTP_")
        _require(len(suffix) == 3 and suffix.isdigit(), "CLAUDE_HOST_FAILURE_CODE")
        status = int(suffix)
        _require(100 <= status <= 599, "CLAUDE_HOST_HTTP_STATUS")
        return status
    _require(code in _ALLOWED_CODES, "CLAUDE_HOST_FAILURE_CODE_UNKNOWN")
    return None


def _failure(code: str | None, *, post_dispatch: bool, verified_terminal: bool) -> tuple[str, int | None, bool]:
    if code is None:
        return "unknown", None, False
    http_status = _validated_failure_code(code)
    if http_status is not None:
        if post_dispatch and not verified_terminal:
            return "http", http_status, False
        typed_retry = http_status in {408, 409, 429, 529} or http_status >= 500
        return "http", http_status, typed_retry
    if post_dispatch and not verified_terminal:
        if "DEADLINE" in code or "TIMEOUT" in code or "LATE" in code:
            return "timeout", None, False
        if "PARTIAL" in code or "TRUNCATED" in code:
            return "partial_response", None, False
        if "RESET" in code:
            return "connection_reset", None, False
        return "unknown", None, False
    if code in _PERMANENT:
        return _PERMANENT[code], None, False
    if code == "NATIVE_TRANSPORT_FAILED":
        return "connection", None, True
    if "DEADLINE_BEFORE_DISPATCH" in code:
        return "timeout", None, True
    if code in _UNKNOWN_CODES:
        return "unknown", None, False
    return "provider", None, False


def _result(*, operation_id: str, phase: str, submission: str, proof: str,
            status: str, code: str, failure_kind: str, http_status: int | None = None,
            retry: bool | None = None, receipt: Mapping[str, Any] | None = None) -> ProviderResultV1:
    return ProviderResultV1(
        provider="claude_host", operation_id=operation_id, phase=phase,
        submission=submission, terminal_proof=proof, status=status, code=code,
        failure_kind=failure_kind, http_status=http_status,
        provider_should_retry=retry, receipt=receipt or {}, version=1,
    )


def normalize_invocation(
    evidence: bytes | str | Mapping[str, Any], *,
    file_resolver: WorkspaceEvidenceResolver | None = None,
) -> ProviderResultV1:
    """Normalize one invocation from sealed custody; never invoke or replay it."""
    value = _json(evidence)
    _require(set(value) == _TOP_FIELDS and value["schema_version"] == CLAUDE_HOST_EVIDENCE_VERSION,
             "CLAUDE_HOST_EVIDENCE_FIELDS")
    _require(value["provider"] == "claude_host", "CLAUDE_HOST_PROVIDER")
    operation_id = _identifier(value["operation_id"], "CLAUDE_HOST_OPERATION_ID")
    dispatch_id = _identifier(value["dispatch_id"], "CLAUDE_HOST_DISPATCH_ID")
    input_sha256 = _hash(value["input_sha256"], "CLAUDE_HOST_INPUT_HASH")
    failure_code = value["failure_code"]
    if failure_code is not None:
        _validated_failure_code(failure_code)
    if file_resolver is None:
        return _result(operation_id=operation_id, phase="not_started", submission="not_submitted",
                       proof="absent", status="unknown", code="CLAUDE_HOST_CUSTODY_UNVERIFIED",
                       failure_kind="unknown", retry=False,
                       receipt={**CAPABILITIES, "custody_verified": False})
    _require(isinstance(file_resolver, WorkspaceEvidenceResolver), "CLAUDE_HOST_RESOLVER_INVALID")

    started = _timestamp(value["started_at"], "CLAUDE_HOST_TIME")
    finished = _timestamp(value["finished_at"], "CLAUDE_HOST_TIME")
    deadline = _timestamp(value["deadline_at"], "CLAUDE_HOST_DEADLINE")
    captured_at = None if value["captured_at"] is None else _timestamp(value["captured_at"], "CLAUDE_HOST_TIME")
    _require(started <= finished <= deadline
             and (captured_at is None or started <= captured_at <= finished), "CLAUDE_HOST_TIME_ORDER")
    terminal_status = value["terminal_status"]
    _require(terminal_status in {"captured", "failed", "unknown"}, "CLAUDE_HOST_TERMINAL_STATUS")

    refs = [_ref(value[name], "CLAUDE_HOST_EVIDENCE_REF") for name in (
        "host_session_ref", "host_profile_ref", "backend_identity_ref", "tool_identity_ref")]
    journal_ref = _ref(value["dispatch_journal_ref"], "CLAUDE_HOST_JOURNAL_REF")
    result_ref = _ref(value["result_ref"], "CLAUDE_HOST_RESULT_REF", optional=True)
    proof_ref = _ref(value["terminal_proof_ref"], "CLAUDE_HOST_PROOF_REF", optional=True)
    result_sha256 = value["result_sha256"]
    if result_sha256 is not None:
        _hash(result_sha256, "CLAUDE_HOST_RESULT_HASH")
    _require((result_ref is None) == (result_sha256 is None), "CLAUDE_HOST_RESULT_BINDING")

    total = [0]
    identity_snapshots = [_read_ref(file_resolver, ref, max_bytes=16 * 1024, total=total) for ref in refs]
    for kind, snapshot in zip(_IDENTITY_KINDS, identity_snapshots):
        _parse_identity(snapshot, kind=kind, operation_id=operation_id,
                        dispatch_id=dispatch_id, input_sha256=input_sha256)
    journal_snapshot = _read_ref(file_resolver, journal_ref, max_bytes=MAX_JSON_BYTES, total=total)
    events, typed = _parse_journal(
        journal_snapshot, operation_id=operation_id, dispatch_id=dispatch_id,
        input_sha256=input_sha256, started=started, finished=finished, captured_at=captured_at)
    last = typed[-1]
    result_snapshot = None
    if result_ref is not None:
        result_snapshot = _read_ref(file_resolver, result_ref, max_bytes=MAX_ARTIFACT_BYTES, total=total)
        _require(result_snapshot.sha256 == result_sha256, "CLAUDE_HOST_RESULT_DRIFT")
    proof_snapshot = None
    proof_value = None
    if proof_ref is not None:
        proof_snapshot = _read_ref(file_resolver, proof_ref, max_bytes=MAX_JSON_BYTES, total=total)
        proof_value = _json(proof_snapshot.data, "CLAUDE_HOST_PROOF_INVALID")
        identity_hashes = {kind: snapshot.sha256 for kind, snapshot in zip(_IDENTITY_KINDS, identity_snapshots)}
        _require(set(proof_value) == _PROOF_FIELDS
                 and proof_value["schema_version"] == TERMINAL_PROOF_VERSION
                 and proof_value["operation_id"] == operation_id
                 and proof_value["dispatch_id"] == dispatch_id
                 and proof_value["input_sha256"] == input_sha256
                 and proof_value["identity_artifact_sha256s"] == identity_hashes
                 and proof_value["journal_sha256"] == journal_snapshot.sha256
                 and proof_value["result_sha256"] == result_sha256
                 and proof_value["terminal_state"] == last.state.value
                 and all(proof_value[key] == value[key] for key in (
                     "terminal_status", "failure_code", "started_at", "captured_at",
                     "finished_at", "deadline_at")),
                 "CLAUDE_HOST_PROOF_BINDING")

    if last.state is DispatchState.CAPTURED:
        if terminal_status == "captured":
            _require(failure_code is None and result_sha256 is not None
                     and last.evidence_sha256 == result_sha256,
                     "CLAUDE_HOST_TERMINAL_EVIDENCE")
        elif terminal_status == "failed":
            _require(failure_code is not None and result_sha256 is None
                     and last.evidence_sha256 == _failure_evidence_sha256(value),
                     "CLAUDE_HOST_TERMINAL_EVIDENCE")
        else:
            _require(last.evidence_sha256 is None, "CLAUDE_HOST_TERMINAL_EVIDENCE")

    phase, submission = {
        DispatchState.PREPARED: ("not_started", "not_submitted"),
        DispatchState.CLAIMED: ("not_started", "not_submitted"),
        DispatchState.DEFINITELY_NOT_DISPATCHED: ("not_started", "not_submitted"),
        DispatchState.INVOCATION_STARTED: ("submitted", "possibly_submitted"),
        DispatchState.POSSIBLY_DISPATCHED: ("streaming", "possibly_submitted"),
        DispatchState.CAPTURED: ("terminal", "definitely_submitted"),
    }[last.state]
    verified_terminal = proof_value is not None and last.state is DispatchState.CAPTURED
    post_dispatch = submission != "not_submitted"
    failure_kind, http_status, should_retry = _failure(
        failure_code, post_dispatch=post_dispatch, verified_terminal=verified_terminal)
    identity_hashes = {kind: snapshot.sha256 for kind, snapshot in zip(_IDENTITY_KINDS, identity_snapshots)}
    receipt_unsigned = {
        "evidence_version": CLAUDE_HOST_EVIDENCE_VERSION,
        "operation_id": operation_id,
        "dispatch_id": dispatch_id,
        "input_sha256": input_sha256,
        "identity_artifact_sha256s": identity_hashes,
        "journal_sha256": journal_snapshot.sha256,
        "journal_head_sha256": events[-1]["event_sha256"],
        "proof_sha256": proof_snapshot.sha256 if proof_snapshot else None,
        "result_sha256": result_sha256 if verified_terminal else None,
        "terminal_state": last.state.value,
        "contract_ready": True,
        "runtime_unverified": True,
        "custody_verified": True,
    }
    receipt = dict(receipt_unsigned)
    receipt["receipt_sha256"] = hashlib.sha256(_canonical(receipt_unsigned)).hexdigest()

    success = (verified_terminal and terminal_status == "captured" and failure_code is None
               and result_snapshot is not None and last.evidence_sha256 == result_sha256)
    if success:
        return _result(operation_id=operation_id, phase="terminal",
                       submission="definitely_submitted", proof="verified",
                       status="succeeded", code="CLAUDE_HOST_CAPTURED",
                       failure_kind="none", receipt=receipt)
    if verified_terminal and terminal_status == "failed" and failure_code is not None:
        return _result(operation_id=operation_id, phase="terminal", submission=submission,
                       proof="verified", status="failed", code=failure_code,
                       failure_kind=failure_kind, http_status=http_status,
                       retry=False, receipt=receipt)
    if last.state is DispatchState.DEFINITELY_NOT_DISPATCHED and failure_code is not None:
        status = "retryable" if should_retry else "failed"
        return _result(operation_id=operation_id, phase="not_started", submission="not_submitted",
                       proof="absent", status=status, code=failure_code,
                       failure_kind=failure_kind, http_status=http_status,
                       retry=should_retry, receipt=receipt)
    unknown_kind = failure_kind if failure_kind in {
        "http", "timeout", "connection_reset", "partial_response", "missing_terminal"
    } else "unknown"
    return _result(operation_id=operation_id, phase=phase, submission=submission,
                   proof="contradictory" if phase == "terminal" and proof_value is not None else "absent",
                   status="unknown", code=failure_code or "CLAUDE_HOST_OUTCOME_UNKNOWN",
                   failure_kind=unknown_kind, http_status=http_status,
                   retry=False, receipt=receipt)
