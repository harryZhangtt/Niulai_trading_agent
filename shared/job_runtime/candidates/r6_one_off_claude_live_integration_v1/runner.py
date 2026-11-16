"""Disabled provider-free Claude integration v4 with total UNKNOWN fencing."""
from __future__ import annotations
import copy
import json
import os
import secrets
import stat
import tempfile
from pathlib import Path
from typing import Optional

from shared.job_runtime.candidates.r6_one_off_evidence_v1 import (
    execute_provider_free, materialize_provider_free_case,
)
from .authority import ValidatedAuthority, load_pinned
from .contracts import (
    ContractError, PROVIDER, blank_seal, canonical_bytes, sha256_bytes, validate_seal,
)
from .process import LocalOnlyProcessEffect

FENCE_NAME = "unknown-fence-v4.json"
PUBLIC_NAME = "post-run-seal-v4.json"
_ORDERING = "WRITE_ALL_FILE_FSYNC_LINK_DIR_FSYNC_REOPEN_NOFOLLOW_READBACK_FILE_FSYNC_DIR_FSYNC"


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _terminal(raw: bytes) -> dict:
    try:
        lines = [json.loads(line) for line in raw.decode("utf-8", "strict").splitlines()
                 if line.strip()]
    except (UnicodeError, ValueError, TypeError):
        return {"recognized": False, "exactly_one": False, "state": "truncated",
                "parser": "claude-stream-json-v1"}
    items = [item for item in lines
             if type(item) is dict and item.get("type") == "result"]
    expected = {"type", "subtype", "is_error", "model", "result"}
    ok = (len(items) == 1 and set(items[0]) == expected and
          items[0]["subtype"] == "success" and items[0]["is_error"] is False and
          items[0]["model"] == "claude-opus-5-5")
    return {"recognized": ok, "exactly_one": len(items) == 1,
            "state": "exact" if ok else "truncated",
            "parser": "claude-stream-json-v1"}


def _write_all(fd: int, raw: bytes) -> None:
    view = memoryview(raw)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise OSError("WRITE_ZERO")
        offset += written


def _read_held(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ContractError("PUBLICATION_NOT_REGULAR")
        chunks = []
        while True:
            part = os.read(fd, 65536)
            if not part:
                break
            chunks.append(part)
        os.fsync(fd)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _publish_verified(path: Path, raw: bytes) -> bytes:
    """No-replace publish with unique stage, ordered fsync, final reopen and readback."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if _lexists(path):
        raise ContractError("PUBLICATION_NO_OVERWRITE")
    fd, stage_name = tempfile.mkstemp(
        prefix=".%s.stage." % path.name, dir=os.fspath(path.parent))
    stage = Path(stage_name)
    linked = False
    try:
        os.fchmod(fd, 0o600)
        _write_all(fd, raw)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.link(stage, path, follow_symlinks=False)
        linked = True
        _fsync_directory(path.parent)
        readback = _read_held(path)
        if len(readback) != len(raw) or sha256_bytes(readback) != sha256_bytes(raw) or readback != raw:
            raise ContractError("PUBLICATION_READBACK_MISMATCH")
        _fsync_directory(path.parent)
        return readback
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            stage.unlink()
        except FileNotFoundError:
            pass
        try:
            _fsync_directory(path.parent)
        except OSError:
            if not linked:
                raise


def _publication_basis(seal: dict) -> dict:
    value = copy.deepcopy(seal)
    value["publication"] = {
        "sanitized": True, "atomic": True, "file_fsynced": True,
        "directory_fsynced": True, "final_reopened_nofollow": True,
        "readback_verified": True, "ordering": _ORDERING, "public_sha256": "0" * 64,
    }
    return value


def _published_seal(seal: dict) -> dict:
    value = _publication_basis(seal)
    value["publication"]["public_sha256"] = sha256_bytes(
        canonical_bytes(_publication_basis(value)))
    validate_seal(value)
    return value


def _fence_wrapper(seal: dict) -> dict:
    return {"version": 4, "seal": seal,
            "seal_sha256": sha256_bytes(canonical_bytes(seal))}


def _read_fence(path: Path) -> dict:
    raw = _read_held(path)
    try:
        value = json.loads(raw.decode("ascii", "strict"))
    except (UnicodeError, ValueError, TypeError):
        raise ContractError("UNKNOWN_FENCE_JSON") from None
    if type(value) is not dict or set(value) != {"version", "seal", "seal_sha256"} or \
            value["version"] != 4:
        raise ContractError("UNKNOWN_FENCE_SCHEMA")
    if canonical_bytes(value) != raw or value["seal_sha256"] != \
            sha256_bytes(canonical_bytes(value["seal"])):
        raise ContractError("UNKNOWN_FENCE_HASH")
    validate_seal(value["seal"])
    if value["seal"]["status"] != "UNKNOWN" or \
            value["seal"]["unknown_fence"]["durability"] != "DURABLE":
        raise ContractError("UNKNOWN_FENCE_STATE")
    return value["seal"]


def _nondurable_unknown(code: str, seed: Optional[dict] = None) -> dict:
    seal = copy.deepcopy(seed if seed is not None else blank_seal())
    seal["status"] = "UNKNOWN"
    seal["code"] = code if code.endswith("_NON_DURABLE") else code + "_NON_DURABLE"
    seal["unknown_fence"] = {"durable": False, "durability": "NON_DURABLE",
        "retry": False, "replay": False, "status_calls": 0}
    seal["publication"] = {"sanitized": True, "atomic": False,
        "file_fsynced": False, "directory_fsynced": False,
        "final_reopened_nofollow": False, "readback_verified": False,
        "ordering": "NONE", "public_sha256": "0" * 64}
    validate_seal(seal)
    return seal


def _durable_fence(path: Path, seed: dict, code: str) -> dict:
    seal = copy.deepcopy(seed)
    seal["status"] = "UNKNOWN"
    seal["code"] = code
    seal["unknown_fence"] = {"durable": True, "durability": "DURABLE",
        "retry": False, "replay": False, "status_calls": 0}
    seal = _published_seal(seal)
    raw = canonical_bytes(_fence_wrapper(seal))
    _publish_verified(path, raw)
    readback = _read_fence(path)
    if readback != seal:
        raise ContractError("UNKNOWN_FENCE_READBACK")
    return readback


def _try_fence(path: Path, seed: dict, code: str) -> dict:
    try:
        return _durable_fence(path, seed, code)
    except BaseException:
        return _nondurable_unknown(code, seed)


def _engine(captured: dict, binding: dict) -> dict:
    request = captured.get("request", {})
    value = {"provider": binding.get("provider"),
        "job_id": binding.get("logical_job_id", request.get("logical_job_id")),
        "slot_id": binding.get("slot_id"),
        "attempt_id": binding.get("attempt_id", request.get("attempt_id")),
        "operation_id": binding.get("operation_id", request.get("operation_id")),
        "prompt_binding_sha256": binding.get(
            "prompt_binding_sha256", request.get("prompt_binding_sha256")),
        "readback_digest": None, "status": binding.get("engine_status", "unknown")}
    value["readback_digest"] = sha256_bytes(canonical_bytes(value))
    return value


def _seal(authority: ValidatedAuthority, captured: dict, binding: dict,
          status: str, code: str) -> dict:
    seal = blank_seal(code)
    seal.update({"status": status, "cell_id": authority.grant["cell_id"],
        "engine": _engine(captured, binding),
        "authority": {"grant_sha256": authority.grant_sha256,
            "grant_review_sha256": authority.grant_review_sha256,
            "registry_sha256": authority.registry_sha256,
            "registry_review_sha256": authority.registry_review_sha256,
            "scope_sha256": authority.scope_sha256, "clock_id": authority.clock_id,
            "validated_before_effect": True, "post_receipt_required_pregrant": False}})
    for key in ("process", "ferry", "custody", "cleanup", "terminal"):
        if key in captured:
            seal[key] = captured[key]
    return seal


def _publish_pass(path: Path, seed: dict) -> dict:
    seal = _published_seal(seed)
    raw = canonical_bytes(seal)
    readback = _publish_verified(path, raw)
    if readback != raw:
        raise ContractError("FINAL_PUBLICATION_READBACK")
    parsed = json.loads(readback.decode("ascii"))
    validate_seal(parsed)
    return parsed


def run(root: Path, *, effect: Optional[LocalOnlyProcessEffect] = None,
        scenario: str = "nominal") -> dict:
    """Run only with an injected local effect; no caller trust root or clock exists."""
    root = Path(root)
    fence = root / FENCE_NAME
    if _lexists(fence):
        try:
            return _read_fence(fence)
        except BaseException:
            return _nondurable_unknown("UNKNOWN_FENCE_INVALID")
    if effect is None:
        stopped = blank_seal("PINNED_AUTHORITY_AND_EFFECT_REQUIRED")
        validate_seal(stopped)
        return stopped
    try:
        authority = load_pinned()
    except BaseException as exc:
        stopped = blank_seal(str(exc) if isinstance(exc, ContractError)
                             else "PINNED_AUTHORITY_INVALID")
        validate_seal(stopped)
        return stopped

    nominal = {"nominal", "path_swap", "resistant_descendant",
        "parent_exit_resistant", "seal_exception", "publication_exception"}
    prepared = materialize_provider_free_case(
        root / "engine", "nominal" if scenario in nominal else
        "post_admission_unknown")
    captured = {}
    shared = None
    execution_error = None

    def transport(request):
        captured["request"] = dict(request)
        fingerprint = sha256_bytes(canonical_bytes(request))
        observed = effect.execute(root, authority.binary_path,
            authority.grant["binary"], fingerprint, scenario,
            authority.grant["timeout_seconds"])
        captured.update(observed)
        captured["terminal"] = _terminal(observed["stdout"])
        process = observed["process"]
        ferry = observed["ferry"]
        cleanup = observed["cleanup"]
        good = (observed["boundary_error"] is None and process["starts"] == 1 and
            process["exit_code"] == 0 and process["timed_out"] is False and
            process["provider"] == PROVIDER and captured["terminal"]["recognized"] and
            all(cleanup[key] is True for key in ("process_group_reaped",
                "verified_copy_removed", "listener_closed", "descriptors_closed")) and
            cleanup["exception_count"] == 0 and process["pid_gone"] and
            process["descendants_reaped"] and ferry["provider"] == PROVIDER and
            ferry["admissions"] == ferry["upstream_attempts"] == 1 and
            ferry["second_rejections"] == 0)
        if scenario == "readback_mismatch":
            good = False
        if scenario == "engine_exception":
            raise RuntimeError("INJECTED_ENGINE_EXCEPTION")
        return {"terminal": "exact" if good else "truncated",
                "cleanup": "complete" if good else "fault",
                "raw": b'{"type":"boundary.completed"}' if good else
                b'{"type":"boundary.partial"}'}

    try:
        shared = execute_provider_free(prepared, transport, provider=PROVIDER)
    except BaseException as exc:
        execution_error = exc
    admitted = captured.get("ferry", {}).get("admissions", 0) == 1
    binding = shared.binding if shared and shared.binding else {}
    seed = _seal(authority, captured, binding,
                 "UNKNOWN" if admitted else "STOP", "UNCLASSIFIED")
    try:
        if execution_error is not None:
            if admitted:
                return _try_fence(fence, seed, "POST_ADMISSION_ENGINE_EXCEPTION")
            stopped = blank_seal("ENGINE_OR_EFFECT_PRE_ADMISSION_FAILURE")
            validate_seal(stopped)
            return stopped
        if admitted and (captured.get("post_admission_cleanup_exception") or
                         captured.get("process", {}).get("cleanup_exception") or
                         captured.get("ferry", {}).get("cleanup_exception")):
            return _try_fence(fence, seed, "POST_ADMISSION_CLEANUP_EXCEPTION")
        request = captured.get("request", {})
        readback_match = (binding.get("provider") == PROVIDER and
            request.get("prompt_binding_sha256") ==
            binding.get("prompt_binding_sha256") and scenario != "readback_mismatch")
        process = captured.get("process", {})
        ferry = captured.get("ferry", {})
        cleanup = captured.get("cleanup", {})
        exact = (shared.evidence["decision"] == "PASS" and readback_match and
            process.get("exit_code") == 0 and captured.get("boundary_error") is None and
            captured.get("terminal", {}).get("recognized") and
            all(cleanup.get(key) is True for key in ("process_group_reaped",
                "verified_copy_removed", "listener_closed", "descriptors_closed")) and
            cleanup.get("exception_count") == 0 and
            ferry.get("admissions") == ferry.get("upstream_attempts") == 1 and
            ferry.get("second_rejections") == 0)
        status = "PASS" if exact else ("UNKNOWN" if admitted else "STOP")
        if exact:
            code = "EXACT_CLAUDE_HOST_TERMINAL_FERRY_ENGINE_EXIT_VERIFIED"
        elif not readback_match:
            code = "ENGINE_READBACK_MISMATCH"
        elif process.get("exit_code") not in (0, None):
            code = "NONZERO_EXIT_CONTRADICTORY_TERMINAL"
        else:
            code = "POST_ADMISSION_UNCERTAIN"
        seal = _seal(authority, captured, binding, status, code)
        if scenario == "seal_exception":
            raise RuntimeError("INJECTED_SEAL_EXCEPTION")
        if status == "UNKNOWN":
            return _try_fence(fence, seal, code)
        if scenario == "publication_exception":
            raise OSError("INJECTED_PUBLICATION_EXCEPTION")
        return _publish_pass(root / "public" / PUBLIC_NAME, seal)
    except BaseException:
        if admitted:
            return _try_fence(
                fence, _seal(authority, captured, binding, "UNKNOWN",
                             "POST_ADMISSION_SEAL_OR_PUBLICATION_EXCEPTION"),
                "POST_ADMISSION_SEAL_OR_PUBLICATION_EXCEPTION")
        stopped = blank_seal("PRE_ADMISSION_SEAL_OR_PUBLICATION_EXCEPTION")
        validate_seal(stopped)
        return stopped


def p0_output(seal: dict) -> dict:
    validate_seal(seal)
    return {"version": 4, "schema": "r6-one-off-claude-live-integration-v4",
        "cell_id": seal["cell_id"], "status": seal["status"],
        "engine_provider": seal["engine"]["provider"],
        "engine_readback_digest": seal["engine"]["readback_digest"],
        "post_run_seal_sha256": sha256_bytes(canonical_bytes(seal)),
        "raw_included": False, "path_included": False,
        "secret_included": False, "replay_allowed": False}
