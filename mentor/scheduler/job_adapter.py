"""Trusted installed-runtime adapter for one evidence-bearing mentor cycle."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Mapping

from .contracts import ContractError, WorkOrder, canonical_json_bytes, sha256_file, strict_json_loads
from .runner import RunnerError, run_cycles, validate_committed_external_attempt
from .state import DurableSessionStore, StateError

RUNTIME_CONTEXT_VERSION = 1
_OPTIONS = {"work_order_path", "state_directory", "owner_id", "candidate_manifest_path",
            "candidate_manifest_sha256", "required_source_paths", "expected_model_profile",
            "model_profile_sha256", "verifier_kind"}
_CONTEXT = {"attempt_id", "slot_id", "scheduled_at", "attempt_no"}
_SERVICE_CONTEXT = _CONTEXT | {"job_id"}
_RUNTIME_CONTEXT = {"version", "model_profile_name", "model_profile", "cancel_event"}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_SLOT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,255}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_FILE_BYTES = 1_048_576  # Manifest/source snapshots are intentionally bounded.
_MAX_RECEIPT_BYTES = 4096
_SUPPORTED_SYNTHETIC_CRITERIA = frozenset({"closed-response", "frozen-binding"})


class AdapterError(ValueError):
    pass


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise AdapterError(code)


def _identifier(value: Any, code: str, pattern: re.Pattern[str] = _ID) -> str:
    _require(isinstance(value, str) and bool(pattern.fullmatch(value)), code)
    return value


def _path(workspace: Path, relative: Any, *, code: str, directory: bool = False,
          private: bool = False, private_code: str = "MENTOR_JOB_PRIVATE_PATH_REQUIRED") -> Path:
    _require(isinstance(relative, str) and 0 < len(relative) <= 1024 and "\\" not in relative, code)
    pure = PurePosixPath(relative)
    _require(not pure.is_absolute() and all(part not in ("", ".", "..") for part in pure.parts), code)
    if private:
        _require(pure.parts[0] == ".job-runtime", private_code)
    current = workspace
    for part in pure.parts:
        current = current / part
        _require(not current.is_symlink(), code)
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(workspace)
    except (OSError, ValueError):
        raise AdapterError(code) from None
    _require(resolved.is_dir() if directory else resolved.is_file(), code)
    return resolved


def _validate_context(context: Any) -> dict[str, Any]:
    _require(isinstance(context, dict) and set(context) in (_CONTEXT, _SERVICE_CONTEXT),
             "MENTOR_JOB_CONTEXT_INVALID")
    attempt = _identifier(context["attempt_id"], "MENTOR_JOB_CONTEXT_INVALID")
    slot = _identifier(context["slot_id"], "MENTOR_JOB_CONTEXT_INVALID", _SLOT)
    scheduled = context["scheduled_at"]
    _require(isinstance(scheduled, str) and len(scheduled) <= 64, "MENTOR_JOB_CONTEXT_INVALID")
    try:
        parsed = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
    except ValueError:
        raise AdapterError("MENTOR_JOB_CONTEXT_INVALID") from None
    attempt_no = context["attempt_no"]
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None and
             type(attempt_no) is int and 1 <= attempt_no <= 10_000,
             "MENTOR_JOB_CONTEXT_INVALID")
    if "job_id" in context:
        _identifier(context["job_id"], "MENTOR_JOB_CONTEXT_INVALID", _JOB_ID)
    return {"attempt_id": attempt, "slot_id": slot, "scheduled_at": scheduled,
            "attempt_no": attempt_no}


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    _require(value is None or type(value) in (str, int, float, bool), "MENTOR_JOB_PROFILE_INVALID")
    return value


def profile_fingerprint(profile: Any) -> str:
    value = _plain(profile)
    _require(isinstance(value, dict), "MENTOR_JOB_PROFILE_INVALID")
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _open_snapshot(path: Path, code: str) -> tuple[int, bytes, tuple[int, int]]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                not 0 < info.st_size <= _MAX_FILE_BYTES):
            raise AdapterError(code)
        chunks, remaining = [], info.st_size
        while remaining:
            chunk = os.read(descriptor, min(131072, remaining))
            if not chunk:
                raise AdapterError(code)
            chunks.append(chunk); remaining -= len(chunk)
        return descriptor, b"".join(chunks), (info.st_dev, info.st_ino)
    except AdapterError:
        try: os.close(descriptor)
        except (OSError, UnboundLocalError): pass
        raise
    except OSError:
        try: os.close(descriptor)
        except (OSError, UnboundLocalError): pass
        raise AdapterError(code) from None


def _rehash_open(descriptor: int, path: Path, identity: tuple[int, int], expected: str) -> None:
    try:
        info = os.fstat(descriptor)
        current = path.lstat()
        _require(stat.S_ISREG(current.st_mode) and not path.is_symlink() and
                 (info.st_dev, info.st_ino) == identity == (current.st_dev, current.st_ino) and
                 info.st_size == current.st_size and 0 < info.st_size <= _MAX_FILE_BYTES,
                 "MENTOR_JOB_CANDIDATE_DRIFT")
        os.lseek(descriptor, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(131072, remaining))
            _require(bool(chunk), "MENTOR_JOB_CANDIDATE_DRIFT")
            digest.update(chunk); remaining -= len(chunk)
        _require(digest.hexdigest() == expected, "MENTOR_JOB_CANDIDATE_DRIFT")
    except OSError:
        raise AdapterError("MENTOR_JOB_CANDIDATE_DRIFT") from None


def _candidate_open(options: dict[str, Any], workspace: Path):
    claimed_manifest = options["candidate_manifest_sha256"]
    _require(isinstance(claimed_manifest, str) and _SHA256.fullmatch(claimed_manifest),
             "MENTOR_JOB_CANDIDATE_INVALID")
    required = options["required_source_paths"]
    _require(isinstance(required, list) and 1 <= len(required) <= 256 and
             all(isinstance(item, str) for item in required),
             "MENTOR_JOB_CANDIDATE_INVALID")
    _require(len(required) == len(set(required)), "MENTOR_JOB_CANDIDATE_INVALID")
    for relative in required:
        _path(workspace, relative, code="MENTOR_JOB_CANDIDATE_INVALID")
    manifest_path = _path(workspace, options["candidate_manifest_path"], code="MENTOR_JOB_CANDIDATE_INVALID")
    manifest_fd, raw, manifest_identity = _open_snapshot(manifest_path, "MENTOR_JOB_CANDIDATE_INVALID")
    descriptors = [manifest_fd]
    try:
        _require(hashlib.sha256(raw).hexdigest() == claimed_manifest, "MENTOR_JOB_CANDIDATE_DRIFT")
        try: manifest = strict_json_loads(raw.decode("utf-8"))
        except (UnicodeError, ContractError): raise AdapterError("MENTOR_JOB_CANDIDATE_INVALID") from None
        _require(isinstance(manifest, dict) and set(manifest) == {"schema_version", "sources"} and
                 type(manifest["schema_version"]) is int and manifest["schema_version"] == 1 and
                 isinstance(manifest["sources"], list), "MENTOR_JOB_CANDIDATE_INVALID")
        paths = [item.get("path") if isinstance(item, dict) else None for item in manifest["sources"]]
        _require(len(paths) == len(required) and set(paths) == set(required), "MENTOR_JOB_CANDIDATE_SOURCE_SET_INVALID")
        snapshots = []
        for item in manifest["sources"]:
            _require(set(item) == {"path", "sha256"} and isinstance(item["sha256"], str) and
                     _SHA256.fullmatch(item["sha256"]), "MENTOR_JOB_CANDIDATE_INVALID")
            source_path = _path(workspace, item["path"], code="MENTOR_JOB_CANDIDATE_INVALID")
            descriptor, source_raw, identity = _open_snapshot(source_path, "MENTOR_JOB_CANDIDATE_INVALID")
            descriptors.append(descriptor)
            _require(hashlib.sha256(source_raw).hexdigest() == item["sha256"], "MENTOR_JOB_CANDIDATE_DRIFT")
            snapshots.append((descriptor, source_path, identity, item["sha256"]))
        return (manifest_fd, manifest_path, manifest_identity, claimed_manifest), snapshots, descriptors
    except Exception:
        for descriptor in descriptors:
            try: os.close(descriptor)
            except OSError: pass
        raise


def _exclusive_json(path: Path, value: dict[str, Any]) -> None:
    expected = canonical_json_bytes(value)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                             getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        if (path.is_symlink() or not path.is_file() or path.stat().st_size != len(expected)
                or path.read_bytes() != expected):
            raise AdapterError("MENTOR_VERIFIER_ARTIFACT_CONFLICT") from None
        return
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(expected); stream.flush(); os.fsync(stream.fileno())


def _expected_updates(work_order: WorkOrder) -> list[dict[str, Any]]:
    return [{"criterion_id": item.criterion_id, "outcome": "satisfied",
             "evidence_id": "binding-" + hashlib.sha256(item.criterion_id.encode()).hexdigest()}
            for item in sorted(work_order.acceptance_criteria, key=lambda value: value.criterion_id)]


def _synthetic_bindings_v1(*, work_order: WorkOrder, cycle_id: str, output: Any,
                           verifier_directory: Path, deadline: datetime,
                           cancel_event: Any | None) -> str | None:
    del deadline
    if cancel_event is not None and cancel_event.is_set(): return None
    criteria = {item.criterion_id: item.critical for item in work_order.acceptance_criteria}
    if set(criteria) != _SUPPORTED_SYNTHETIC_CRITERIA or not all(criteria.values()):
        return None
    expected = _expected_updates(work_order)
    keys = {"schema_version", "cycle_id", "variant_id", "action_id", "criterion_updates"}
    if (not isinstance(output, dict) or set(output) != keys or type(output.get("schema_version")) is not int or
            output.get("schema_version") != 1 or output.get("cycle_id") != cycle_id or
            output.get("variant_id") != "baseline" or output.get("action_id") != "verify-synthetic-bindings" or
            output.get("criterion_updates") != expected):
        return None
    evidence = verifier_directory / "synthetic-bindings.json"
    artifact = verifier_directory / "progress.json"
    _exclusive_json(evidence, {"schema_version": 1, "evidence_kind": "synthetic_bindings_v1",
        "work_order_id": work_order.work_order_id, "cycle_id": cycle_id, "variant_id": "baseline",
        "validated_bindings": ["closed_output", "cycle_id", "variant_id", "declared_criteria"]})
    _exclusive_json(artifact, {"schema_version": 1, "work_order_id": work_order.work_order_id,
        "plan_sha256": work_order.plan.sha256, "acceptance_sha256": work_order.acceptance.sha256,
        "cycle_id": cycle_id, "observations": [{
            "evidence_id": "synthetic-bindings-" + hashlib.sha256(cycle_id.encode()).hexdigest(),
            "evidence_path": str(evidence.relative_to(work_order.workspace)), "sha256": sha256_file(evidence)}]})
    return str(artifact.relative_to(work_order.workspace))


def _runner_result(result: Any) -> tuple[str, str, int]:
    if not isinstance(result, dict): return "unknown", "MENTOR_RUNNER_RESULT_INVALID", 0
    status = result.get("status")
    if status not in {"succeeded", "retryable", "failed", "unknown", "blocked"}: status = "unknown"
    code = result.get("code")
    if not isinstance(code, str) or not _CODE.fullmatch(code): code = "MENTOR_RUNNER_CODE_INVALID"
    attempted = result.get("cycles_attempted")
    if type(attempted) is not int or not 0 <= attempted <= 1:
        return "unknown", "MENTOR_RUNNER_RESULT_INVALID", 0
    return status, code, attempted


def _read_private_json(path: Path) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink() and path.stat().st_size <= _MAX_FILE_BYTES,
             "MENTOR_JOB_SUCCESS_UNCONFIRMED")
    try: value = strict_json_loads(path.read_text(encoding="utf-8"))
    except Exception: raise AdapterError("MENTOR_JOB_SUCCESS_UNCONFIRMED") from None
    _require(isinstance(value, dict), "MENTOR_JOB_SUCCESS_UNCONFIRMED")
    return value


def _verify_success(work_order: WorkOrder, store: DurableSessionStore, before: dict[str, Any],
                    after: dict[str, Any], attempt_id: str) -> tuple[str, str]:
    _require(after["revision"] == before["revision"] + 2 and
             len(after["provider_threads"]) == len(before["provider_threads"]) + 1 and
             len(after["cycle_ids"]) == len(before["cycle_ids"]) + 1 and
             after["turns_used"] == before["turns_used"] + 1 and not after["pending_effects"],
             "MENTOR_JOB_SUCCESS_UNCONFIRMED")
    thread_id = after["provider_threads"][-1]["thread_id"]
    cycle_id = after["cycle_ids"][-1]
    provider = _read_private_json(store.events_directory / f"{before['revision'] + 1:08d}.json")
    cycle = _read_private_json(store.events_directory / f"{before['revision'] + 2:08d}.json")
    _require(provider.get("kind") == "provider_thread" and provider.get("data", {}).get("thread_id") == thread_id and
             cycle.get("kind") == "cycle", "MENTOR_JOB_SUCCESS_UNCONFIRMED")
    data = cycle.get("data", {})
    _require(data.get("cycle_id") == cycle_id and data.get("outcome") == "succeeded" and
             isinstance(data.get("verified_evidence_artifact_path"), str) and
             isinstance(data.get("verified_evidence_artifact_sha256"), str) and
             _SHA256.fullmatch(data["verified_evidence_artifact_sha256"]) and
             data.get("effect_id") is None and data.get("effect_status") == "none" and
             bool(data.get("verified_evidence_ids")), "MENTOR_JOB_SUCCESS_UNCONFIRMED")
    validated = []
    root = work_order.workspace / ".job-runtime" / "mentor-attempts" / work_order.logical_session.logical_session_id
    for path in root.glob("*/journal.json"):
        try:
            value = validate_committed_external_attempt(
                work_order,
                path,
                external_engine_attempt_id=attempt_id,
                cycle_id=cycle_id,
            )
        except RunnerError:
            continue
        validated.append(value)
    _require(len(validated) == 1 and validated[0]["thread_id"] == thread_id,
             "MENTOR_JOB_SUCCESS_UNCONFIRMED")
    return thread_id, cycle_id


def _receipt(work_order: WorkOrder, trusted: dict[str, str], runner_status: str, runner_code: str,
             head: dict[str, Any], fingerprint: str, thread_id: str | None, cycle_id: str | None) -> dict[str, Any]:
    value = {"work_order_id": work_order.work_order_id,
        "logical_session_id": work_order.logical_session.logical_session_id,
        "attempt_id": trusted["attempt_id"], "slot_id": trusted["slot_id"],
        "scheduled_at": trusted["scheduled_at"], "runner_status": runner_status,
        "runner_code": runner_code, "head_revision": head["revision"],
        "provider_thread_count": len(head["provider_threads"]), "turns_used": head["turns_used"],
        "pending_effects_count": len(head["pending_effects"]), "candidate_fingerprint": fingerprint,
        "thread_id": thread_id, "cycle_id": cycle_id}
    _require(len(json.dumps(value, sort_keys=True).encode()) <= _MAX_RECEIPT_BYTES, "MENTOR_JOB_RECEIPT_INVALID")
    return value


def prepare(options: Any, workspace: Path | str, context: Any, runtime_context: Any) -> dict[str, Any]:
    invoked = False
    descriptors: list[int] = []
    try:
        _require(isinstance(options, dict) and set(options) == _OPTIONS, "MENTOR_JOB_OPTIONS_INVALID")
        root = Path(workspace).resolve(strict=True)
        _require(root.is_dir(), "MENTOR_JOB_WORKSPACE_INVALID")
        trusted = _validate_context(context)
        _require(isinstance(runtime_context, Mapping) and set(runtime_context) == _RUNTIME_CONTEXT and
                 runtime_context["version"] == 1, "MENTOR_JOB_RUNTIME_CONTEXT_INVALID")
        expected_name = _identifier(options["expected_model_profile"], "MENTOR_JOB_PROFILE_INVALID")
        expected_profile_sha = options["model_profile_sha256"]
        _require(isinstance(expected_profile_sha, str) and _SHA256.fullmatch(expected_profile_sha) and
                 runtime_context["model_profile_name"] == expected_name and
                 profile_fingerprint(runtime_context["model_profile"]) == expected_profile_sha,
                 "MENTOR_JOB_PROFILE_MISMATCH")
        cancel_event = runtime_context["cancel_event"]
        _require(hasattr(cancel_event, "is_set"), "MENTOR_JOB_RUNTIME_CONTEXT_INVALID")
        _require(options["verifier_kind"] == "synthetic_bindings_v1", "MENTOR_JOB_VERIFIER_UNSUPPORTED")
        work_order_path = _path(root, options["work_order_path"], code="MENTOR_JOB_WORK_ORDER_INVALID")
        state_path = _path(root, options["state_directory"], code="MENTOR_JOB_STATE_INVALID", directory=True,
                           private=True, private_code="MENTOR_JOB_PRIVATE_STATE_REQUIRED")
        owner = _identifier(options["owner_id"], "MENTOR_JOB_OWNER_INVALID")
        try:
            work_order = WorkOrder.from_json(work_order_path.read_text(encoding="utf-8"), root)
            store = DurableSessionStore(root, str(state_path.relative_to(root)), owner)
            before = store.load(work_order)
        except (OSError, UnicodeError, ContractError, StateError):
            raise AdapterError("MENTOR_JOB_CONTRACT_INVALID") from None
        manifest, sources, descriptors = _candidate_open(options, root)
        invoked = True
        result = run_cycles(work_order, store, _plain(runtime_context["model_profile"]), _synthetic_bindings_v1,
                            max_cycles_this_run=1, cancel_event=cancel_event,
                            external_engine_attempt_id=trusted["attempt_id"])
        runner_status, runner_code, attempted = _runner_result(result)
        _rehash_open(manifest[0], manifest[1], manifest[2], manifest[3])
        for descriptor, path, identity, digest in sources:
            _rehash_open(descriptor, path, identity, digest)
        work_order.verify_bindings()
        after = store.load(work_order)
        thread_id = after["provider_threads"][-1]["thread_id"] if attempted == 1 and after["provider_threads"] else None
        cycle_id = after["cycle_ids"][-1] if attempted == 1 and after["cycle_ids"] else None
        transient_block = runner_status == "blocked" and runner_code == "MENTOR_SESSION_DISPATCH_BUSY"
        mapped = ("retryable" if transient_block else
                  {"succeeded": "succeeded", "retryable": "retryable", "failed": "failed",
                   "blocked": "failed", "unknown": "unknown"}[runner_status])
        code = ("MENTOR_JOB_CYCLE_RETRYABLE" if transient_block else
                {"succeeded": "MENTOR_JOB_CYCLE_SUCCEEDED", "retryable": "MENTOR_JOB_CYCLE_RETRYABLE",
                 "failed": "MENTOR_JOB_CYCLE_FAILED", "blocked": "MENTOR_JOB_CYCLE_BLOCKED",
                 "unknown": "MENTOR_JOB_CYCLE_UNKNOWN"}[runner_status])
        if mapped == "succeeded":
            _require(attempted == 1, "MENTOR_JOB_SUCCESS_UNCONFIRMED")
            thread_id, cycle_id = _verify_success(work_order, store, before, after, trusted["attempt_id"])
        receipt = _receipt(work_order, trusted, runner_status, runner_code, after, manifest[3], thread_id, cycle_id)
        return {"status": mapped, "code": code, "receipt": receipt}
    except AdapterError as error:
        uncertain = invoked and str(error) in {"MENTOR_JOB_CANDIDATE_DRIFT", "MENTOR_JOB_SUCCESS_UNCONFIRMED"}
        return {"status": "unknown" if uncertain else "failed", "code": str(error)}
    except Exception:
        return {"status": "unknown" if invoked else "failed",
                "code": "MENTOR_JOB_ADAPTER_UNKNOWN" if invoked else "MENTOR_JOB_ADAPTER_FAILED"}
    finally:
        for descriptor in descriptors:
            try: os.close(descriptor)
            except OSError: pass
