"""Disabled additive R6 common execution-window authority v2.

The live public surface is fixed-root and fail-closed.  Activation remains
impossible until a separately reviewed source change installs all exact pins.
Provider-free tests exercise private descriptor-relative helpers only.
"""
from __future__ import annotations

import copy
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

STATUS = "DISABLED_TEMPLATE_PENDING_FINAL_PINS_AND_FRESH_REVIEW"
BLOCK_DURATION_SECONDS = 1800
BLOCK_DURATION_NS = BLOCK_DURATION_SECONDS * 1_000_000_000
CONCURRENCY = 1
CELL_ORDER = (
    "R6DQ-7F2C91A4",
    "R6DQ-1B8E43D7",
    "R6DQ-C4A7095E",
    "R6DQ-92D6F0B3",
)
ADMISSION_OFFSETS_SECONDS = (450, 900, 1350, 1800)
CLOCK_PAIR_MAX_SPAN_NS = 50_000_000
WALL_MONOTONIC_MAX_DRIFT_NS = 1_000_000_000
MAX_WIRE_INT = (1 << 63) - 1

WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
TEMPLATE_PATH = Path(__file__).with_name("window-template-v3.json")
TEMPLATE_RELATIVE_PATH = "shared/job_runtime/candidates/r6_common_execution_window_v3/window-template-v3.json"
RUNTIME_RELATIVE_ROOT = Path("runtime/r6_common_execution_window_v3")
CANONICAL_ROOT = WORKSPACE_ROOT / RUNTIME_RELATIVE_ROOT
RECEIPT_NAME = "canonical-window-receipt-v3.json"
MARKER_NAME = "canonical-window-receipt-v3.commit.json"
RECEIPT_STAGE_NAME = ".canonical-window-receipt-v3.stage"
MARKER_STAGE_NAME = ".canonical-window-receipt-v3.commit.stage"
CLAIM_NAMES = tuple(f"claim-cell-{i}-v3.json" for i in range(1, 5))
CLAIM_STAGE_NAMES = tuple(f".claim-cell-{i}-v3.stage" for i in range(1, 5))
CLAIM_COMMIT_NAMES = tuple(f"claim-cell-{i}-v3.commit.json" for i in range(1, 5))
CLAIM_COMMIT_STAGE_NAMES = tuple(f".claim-cell-{i}-v3.commit.stage" for i in range(1, 5))
TERMINAL_NAMES = tuple(f"terminal-cell-{i}-v3.json" for i in range(1, 5))
TERMINAL_STAGE_NAMES = tuple(f".terminal-cell-{i}-v3.stage" for i in range(1, 5))
TERMINAL_COMMIT_NAMES = tuple(f"terminal-cell-{i}-v3.commit.json" for i in range(1, 5))
TERMINAL_COMMIT_STAGE_NAMES = tuple(f".terminal-cell-{i}-v3.commit.stage" for i in range(1, 5))

# Absolute-path traversal is anchored at / and every component is opened relative
# to the preceding held descriptor.  Modes are fixed for this authorized checkout.
_TRUSTED_CHAIN = (
    ("Users", 0, 0o755),
    ("bytedance", os.getuid(), 0o750),
    ("Desktop", os.getuid(), 0o700),
    ("Trading Agent", os.getuid(), 0o755),
)
_RUNTIME_PARENT = ("runtime", os.getuid(), 0o700)

PIN_PATHS = {
    "final_block_grant": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-common-execution-window-v3-final-block-grant.json",
    "g1": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-common-execution-window-v3-g1-authority.json",
    "g2": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-common-execution-window-v3-g2-authority.json",
    "fresh_review": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-common-execution-window-v3-fresh-independent-review.json",
    "p0_v10": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-common-execution-window-v3-p0-v10-authority.json",
    "runner_v4": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-common-execution-window-v3-runner-v4-authority.json",
    "provider_authority": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-common-execution-window-v3-provider-authority.json",
    "human_authority": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-common-execution-window-v3-human-authority.json",
}
PIN_ROLES = {
    "final_block_grant": "FINAL_BLOCK_GRANT",
    "g1": "G1_AUTHORITY",
    "g2": "G2_AUTHORITY",
    "fresh_review": "FRESH_INDEPENDENT_REVIEW",
    "p0_v10": "P0_V10_AUTHORITY",
    "runner_v4": "RUNNER_V4_AUTHORITY",
    "provider_authority": "PROVIDER_AUTHORITY",
    "human_authority": "HUMAN_AUTHORITY",
}

# Deliberately absent.  A future activation requires a separate reviewed source
# change fixing exact path/bytes/SHA values; runtime callers cannot inject them.
ACTIVATION_ENABLED = False
FINAL_BLOCK_GRANT_PIN: Mapping[str, Any] | None = None
G1_AUTHORITY_PIN: Mapping[str, Any] | None = None
G2_AUTHORITY_PIN: Mapping[str, Any] | None = None
FRESH_REVIEW_PIN: Mapping[str, Any] | None = None
P0_V10_PIN: Mapping[str, Any] | None = None
RUNNER_V4_PIN: Mapping[str, Any] | None = None
PROVIDER_AUTHORITY_PIN: Mapping[str, Any] | None = None
HUMAN_AUTHORITY_PIN: Mapping[str, Any] | None = None

_ID_RE = re.compile(r"^(block|window|job|slot|attempt|operation)_[A-Za-z0-9_-]{32,}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_PROCESS_INSTANCE_TOKEN: str | None = None  # no import-time clock, entropy, or token call
_PROCESS_INSTANCE_PID: int | None = None


class WindowError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise WindowError(code)


def _is_exact_int(value: Any, *, minimum: int = 0, maximum: int = MAX_WIRE_INT) -> bool:
    """Return true only for a plain bounded wire integer, never bool/subclasses."""
    return type(value) is int and not isinstance(value, bool) and minimum <= value <= maximum


def _require_exact_int(
    value: Any, code: str, *, minimum: int = 0, maximum: int = MAX_WIRE_INT
) -> int:
    _require(_is_exact_int(value, minimum=minimum, maximum=maximum), code)
    return value


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise WindowError("CANONICAL_JSON_INVALID") from None


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_duplicate_pairs(pairs: Sequence[tuple[str, Any]]) -> Mapping[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        _require(key not in value, "DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def _strict_json(raw: bytes, code: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, WindowError):
        raise WindowError(code) from None
    _require(isinstance(value, dict), code)
    _require(canonical_bytes(value) == raw, code + "_NONCANONICAL")
    return value


def _seal(body: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(body))
    raw = canonical_bytes(result)
    result["seal"] = {"bytes": len(raw), "sha256": _sha256(raw)}
    return result


def _verify_seal(value: Mapping[str, Any], code: str) -> None:
    _require(isinstance(value.get("seal"), dict), code + "_SEAL")
    body = dict(value)
    seal = body.pop("seal")
    _require(set(seal) == {"bytes", "sha256"}, code + "_SEAL")
    _require_exact_int(seal.get("bytes"), code + "_SEAL_BYTES", minimum=1)
    _require(isinstance(seal.get("sha256"), str) and _SHA_RE.fullmatch(seal["sha256"]), code + "_SEAL_HASH")
    raw = canonical_bytes(body)
    _require(seal == {"bytes": len(raw), "sha256": _sha256(raw)}, code + "_SEAL")


def _fstat_directory(fd: int, uid: int, mode: int, code: str) -> os.stat_result:
    status = os.fstat(fd)
    _require(stat.S_ISDIR(status.st_mode), code + "_TYPE")
    _require(status.st_uid == uid, code + "_OWNER")
    _require(stat.S_IMODE(status.st_mode) == mode, code + "_MODE")
    return status


def _open_child_directory(parent_fd: int, name: str, uid: int, mode: int, code: str) -> int:
    _require(name not in ("", ".", "..") and "/" not in name and "\\" not in name, code + "_NAME")
    try:
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError:
        raise WindowError(code + "_OPEN") from None
    try:
        _fstat_directory(fd, uid, mode, code)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_workspace_fd() -> int:
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _fstat_directory(fd, 0, 0o755, "TRUST_ROOT")
        for index, (name, uid, mode) in enumerate(_TRUSTED_CHAIN):
            child = _open_child_directory(fd, name, uid, mode, f"TRUST_CHAIN_{index}")
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_runtime_parent_fd() -> int:
    workspace_fd = _open_workspace_fd()
    try:
        name, uid, mode = _RUNTIME_PARENT
        return _open_child_directory(workspace_fd, name, uid, mode, "RUNTIME_PARENT")
    finally:
        os.close(workspace_fd)


def _open_relative_regular(workspace_fd: int, relative: str, expected_mode: int, code: str) -> tuple[int, os.stat_result]:
    parts = Path(relative).parts
    _require(relative and not relative.startswith("/") and parts and ".." not in parts, code + "_PATH")
    current = os.dup(workspace_fd)
    try:
        for index, part in enumerate(parts[:-1]):
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            except OSError:
                raise WindowError(code + "_PARENT") from None
            status = os.fstat(child)
            _require(stat.S_ISDIR(status.st_mode), code + "_PARENT_TYPE")
            _require(status.st_uid == os.getuid(), code + "_PARENT_OWNER")
            _require(stat.S_IMODE(status.st_mode) & 0o022 == 0, code + "_PARENT_MODE")
            os.close(current)
            current = child
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current)
        except OSError:
            raise WindowError(code + "_MISSING") from None
        try:
            status = os.fstat(fd)
            _require(stat.S_ISREG(status.st_mode), code + "_TYPE")
            _require(status.st_uid == os.getuid(), code + "_OWNER")
            _require(stat.S_IMODE(status.st_mode) == expected_mode, code + "_MODE")
            return fd, status
        except BaseException:
            os.close(fd)
            raise
    finally:
        os.close(current)


def _read_fd_stable(fd: int, before: os.stat_result, code: str) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    after = os.fstat(fd)
    _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
             (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), code + "_RACE")
    return b"".join(chunks)


def _verify_activation_pin(workspace_fd: int, name: str, ref: Mapping[str, Any]) -> dict[str, Any]:
    code = "PIN_" + name.upper()
    _require(set(ref) == {"path", "bytes", "sha256"}, code + "_REF")
    _require(ref.get("path") == PIN_PATHS[name], code + "_FIXED_PATH")
    _require(_is_exact_int(ref.get("bytes"), minimum=1), code + "_BYTES_REF")
    _require(isinstance(ref.get("sha256"), str) and _SHA_RE.fullmatch(ref["sha256"]), code + "_HASH_REF")
    fd, status = _open_relative_regular(workspace_fd, ref["path"], 0o600, code)
    try:
        raw = _read_fd_stable(fd, status, code)
    finally:
        os.close(fd)
    _require(len(raw) == ref["bytes"], code + "_BYTES")
    _require(_sha256(raw) == ref["sha256"], code + "_HASH")
    value = _strict_json(raw, code + "_JSON")
    _require(set(value) == {"immutable", "role", "status", "subject", "version"}, code + "_FIELDS")
    _require(value["version"] == "r6-common-execution-window-activation-pin-v3", code + "_VERSION")
    _require(value["subject"] == "r6_common_execution_window_v3", code + "_SUBJECT")
    _require(value["role"] == PIN_ROLES[name], code + "_ROLE")
    _require(value["status"] == "APPROVED" and value["immutable"] is True, code + "_STATUS")
    return dict(ref)


def _verify_source_ref(workspace_fd: int, ref: Mapping[str, Any], index: int) -> None:
    code = f"SOURCE_PIN_{index}"
    _require(set(ref) == {"path", "bytes", "sha256"}, code + "_REF")
    _require(_is_exact_int(ref.get("bytes"), minimum=1), code + "_BYTES_REF")
    _require(isinstance(ref.get("sha256"), str) and _SHA_RE.fullmatch(ref["sha256"]), code + "_HASH_REF")
    fd, status = _open_relative_regular(workspace_fd, ref.get("path", ""), 0o600, code)
    try:
        raw = _read_fd_stable(fd, status, code)
    finally:
        os.close(fd)
    _require(len(raw) == ref["bytes"], code + "_BYTES")
    _require(_sha256(raw) == ref["sha256"], code + "_HASH")


def _pin_constants() -> dict[str, Mapping[str, Any] | None]:
    return {
        "final_block_grant": FINAL_BLOCK_GRANT_PIN,
        "g1": G1_AUTHORITY_PIN,
        "g2": G2_AUTHORITY_PIN,
        "fresh_review": FRESH_REVIEW_PIN,
        "p0_v10": P0_V10_PIN,
        "runner_v4": RUNNER_V4_PIN,
        "provider_authority": PROVIDER_AUTHORITY_PIN,
        "human_authority": HUMAN_AUTHORITY_PIN,
    }


def _activation_preflight() -> tuple[dict[str, Any], dict[str, Any]]:
    _require(ACTIVATION_ENABLED is True, STATUS)
    constants = _pin_constants()
    for name, ref in constants.items():
        _require(ref is not None, "PIN_" + name.upper() + "_MISSING")
    workspace_fd = _open_workspace_fd()
    try:
        verified = {name: _verify_activation_pin(workspace_fd, name, ref or {}) for name, ref in constants.items()}
    finally:
        os.close(workspace_fd)
    template = prepare_window_template()
    return template, verified


def _get_process_token() -> str:
    global _PROCESS_INSTANCE_PID, _PROCESS_INSTANCE_TOKEN
    current_pid = os.getpid()
    if _PROCESS_INSTANCE_TOKEN is None or _PROCESS_INSTANCE_PID != current_pid:
        _PROCESS_INSTANCE_TOKEN = hashlib.sha256(f"{current_pid}:{secrets.token_hex(32)}".encode("ascii")).hexdigest()
        _PROCESS_INSTANCE_PID = current_pid
    return _PROCESS_INSTANCE_TOKEN


@dataclass(frozen=True)
class ClockPair:
    wall_utc_ns: int
    monotonic_ns: int
    pair_span_ns: int


def _trusted_clock_pair() -> ClockPair:
    before = time.monotonic_ns()
    wall = time.time_ns()
    after = time.monotonic_ns()
    _require(after >= before, "MONOTONIC_ROLLBACK")
    span = after - before
    _require(span <= CLOCK_PAIR_MAX_SPAN_NS, "CLOCK_PAIR_SPAN")
    return ClockPair(wall, before + span // 2, span)


def _new_id(kind: str) -> str:
    value = f"{kind}_{secrets.token_urlsafe(24)}"
    _require(_ID_RE.fullmatch(value) is not None, "INTERNAL_ID_INVALID")
    return value


def _full_write(fd: int, raw: bytes, write_fn: Callable[[int, bytes], int] = os.write) -> None:
    offset = 0
    while offset < len(raw):
        written = write_fn(fd, raw[offset:])
        _require(type(written) is int and 0 < written <= len(raw) - offset, "WRITE_ZERO_OR_INVALID")
        offset += written


def _fsync_file(fd: int, boundary: str) -> None:
    del boundary
    os.fsync(fd)


def _fsync_dir(fd: int, boundary: str) -> None:
    del boundary
    os.fsync(fd)


def _verify_child_binding(parent_fd: int, name: str, child_fd: int) -> None:
    try:
        path_status = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        raise WindowError("ROOT_BINDING_MISSING") from None
    fd_status = _fstat_directory(child_fd, os.getuid(), 0o700, "ROOT")
    _require((path_status.st_dev, path_status.st_ino) == (fd_status.st_dev, fd_status.st_ino), "ROOT_BINDING")
    _require(stat.S_ISDIR(path_status.st_mode) and not stat.S_ISLNK(path_status.st_mode), "ROOT_BINDING_TYPE")
    _require(path_status.st_uid == os.getuid() and stat.S_IMODE(path_status.st_mode) == 0o700, "ROOT_BINDING_MODE")


def _rename_directory_exclusive(parent_fd: int, source: str, target: str) -> None:
    try:
        renameatx_np = ctypes.CDLL(None, use_errno=True).renameatx_np
    except AttributeError:
        raise WindowError("ROOT_RENAME_EXCLUSIVE_UNAVAILABLE") from None
    renameatx_np.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameatx_np.restype = ctypes.c_int
    if renameatx_np(parent_fd, source.encode("utf-8"), parent_fd, target.encode("utf-8"), 0x00000004) != 0:
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise WindowError("ROOT_EXISTS") from None
        raise WindowError("ROOT_RENAME_EXCLUSIVE") from None


def _create_new_root(parent_fd: int, name: str, *, after_bind: Callable[[], None] | None = None) -> int:
    _require(name == RUNTIME_RELATIVE_ROOT.name, "ROOT_NAME")
    stage = f".{name}.create-{secrets.token_hex(16)}"
    root_fd = -1
    renamed = False
    try:
        os.mkdir(stage, 0o700, dir_fd=parent_fd)
        root_fd = _open_child_directory(parent_fd, stage, os.getuid(), 0o700, "ROOT_STAGE")
        _rename_directory_exclusive(parent_fd, stage, name)
        renamed = True
        _fsync_dir(parent_fd, "root_create")
        _verify_child_binding(parent_fd, name, root_fd)
        if after_bind is not None:
            after_bind()
        return root_fd
    except BaseException:
        if root_fd >= 0:
            os.close(root_fd)
        if not renamed:
            try:
                os.rmdir(stage, dir_fd=parent_fd)
            except OSError:
                pass
        raise


def _create_or_open_root(parent_fd: int, name: str, *, before_open: Callable[[], None] | None = None) -> int:
    _require(name == RUNTIME_RELATIVE_ROOT.name, "ROOT_NAME")
    try:
        return _open_child_directory(parent_fd, name, os.getuid(), 0o700, "ROOT")
    except WindowError as exc:
        if exc.code != "ROOT_OPEN":
            raise
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return _create_new_root(parent_fd, name, after_bind=before_open)
        except OSError:
            raise WindowError("ROOT_OPEN") from None
        raise


def _open_canonical_root(*, create: bool = False) -> int:
    parent_fd = _open_runtime_parent_fd()
    try:
        if create:
            return _create_or_open_root(parent_fd, RUNTIME_RELATIVE_ROOT.name)
        return _open_child_directory(parent_fd, RUNTIME_RELATIVE_ROOT.name, os.getuid(), 0o700, "ROOT")
    finally:
        os.close(parent_fd)


def _read_name_fd(root_fd: int, name: str, *, missing_ok: bool = False) -> bytes | None:
    _require(name in {RECEIPT_NAME, MARKER_NAME, RECEIPT_STAGE_NAME, MARKER_STAGE_NAME, *CLAIM_NAMES, *CLAIM_STAGE_NAMES, *CLAIM_COMMIT_NAMES, *CLAIM_COMMIT_STAGE_NAMES, *TERMINAL_NAMES, *TERMINAL_STAGE_NAMES, *TERMINAL_COMMIT_NAMES, *TERMINAL_COMMIT_STAGE_NAMES}, "ARTIFACT_NAME")
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise WindowError("ARTIFACT_MISSING") from None
    except OSError:
        raise WindowError("ARTIFACT_OPEN") from None
    try:
        status = os.fstat(fd)
        _require(stat.S_ISREG(status.st_mode), "ARTIFACT_TYPE")
        _require(status.st_uid == os.getuid(), "ARTIFACT_OWNER")
        _require(stat.S_IMODE(status.st_mode) == 0o600, "ARTIFACT_MODE")
        return _read_fd_stable(fd, status, "ARTIFACT")
    finally:
        os.close(fd)


def _write_exclusive_fd(
    root_fd: int,
    name: str,
    raw: bytes,
    *,
    write_fn: Callable[[int, bytes], int] = os.write,
    crash_after: str | None = None,
    boundary: str = "artifact",
) -> None:
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root_fd)
    except FileExistsError:
        raise WindowError("ARTIFACT_EXISTS") from None
    except OSError:
        raise WindowError("ARTIFACT_CREATE") from None
    try:
        if crash_after == "created":
            raise WindowError("INJECTED_CRASH_CREATED")
        _full_write(fd, raw, write_fn)
        if crash_after == "written":
            raise WindowError("INJECTED_CRASH_WRITTEN")
        _fsync_file(fd, boundary + "_file")
        if crash_after == "file_fsynced":
            raise WindowError("INJECTED_CRASH_FILE_FSYNCED")
        status = os.fstat(fd)
        _require(stat.S_ISREG(status.st_mode) and status.st_uid == os.getuid(), "ARTIFACT_OWNER_TYPE")
        _require(stat.S_IMODE(status.st_mode) == 0o600 and status.st_size == len(raw), "ARTIFACT_MODE_SIZE")
    finally:
        os.close(fd)
    _fsync_dir(root_fd, boundary + "_parent")
    if crash_after == "parent_fsynced":
        raise WindowError("INJECTED_CRASH_PARENT_FSYNCED")
    actual = _read_name_fd(root_fd, name)
    _require(actual is not None and len(actual) == len(raw) and _sha256(actual) == _sha256(raw), "REOPEN_HASH_MISMATCH")
    if crash_after == "reopened":
        raise WindowError("INJECTED_CRASH_REOPENED")


def _lock_root(root_fd: int, *, exclusive: bool) -> None:
    operation = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
    try:
        fcntl.flock(root_fd, operation)
    except (BlockingIOError, OSError):
        raise WindowError("NAMESPACE_BUSY") from None


def _unlock_root(root_fd: int) -> None:
    fcntl.flock(root_fd, fcntl.LOCK_UN)


def _slot_names(kind: str, index: int) -> tuple[str, str, str, str]:
    _require(kind in {"claim", "terminal"}, "SLOT_KIND_INDEX")
    _require_exact_int(index, "SLOT_KIND_INDEX", maximum=3)
    if kind == "claim":
        return CLAIM_NAMES[index], CLAIM_STAGE_NAMES[index], CLAIM_COMMIT_NAMES[index], CLAIM_COMMIT_STAGE_NAMES[index]
    return TERMINAL_NAMES[index], TERMINAL_STAGE_NAMES[index], TERMINAL_COMMIT_NAMES[index], TERMINAL_COMMIT_STAGE_NAMES[index]


def _slot_marker(artifact_name: str, raw: bytes) -> dict[str, Any]:
    return {"version":"r6-common-execution-window-slot-commit-v3","artifact":artifact_name,"artifact_bytes":len(raw),"artifact_sha256":_sha256(raw),"committed":True}


def _validate_slot_marker(marker: Mapping[str, Any], artifact_name: str, raw: bytes) -> None:
    _require(set(marker) == {"version","artifact","artifact_bytes","artifact_sha256","committed"}, "SLOT_COMMIT_FIELDS")
    _require_exact_int(marker.get("artifact_bytes"), "SLOT_COMMIT_BYTES", minimum=1)
    _require(marker["version"] == "r6-common-execution-window-slot-commit-v3" and marker["artifact"] == artifact_name and marker["committed"] is True, "SLOT_COMMIT_CONTENT")
    _require(marker["artifact_bytes"] == len(raw) and marker["artifact_sha256"] == _sha256(raw), "SLOT_COMMIT_ARTIFACT_MISMATCH")


def _validate_receipt_marker(marker: Mapping[str, Any], raw: bytes) -> None:
    _require(set(marker) == {"version","receipt","receipt_bytes","receipt_sha256","committed"}, "COMMIT_FIELDS")
    _require_exact_int(marker.get("receipt_bytes"), "COMMIT_RECEIPT_BYTES", minimum=1)
    _require(marker["version"] == "r6-common-execution-window-commit-v3" and marker["receipt"] == RECEIPT_NAME and marker["committed"] is True, "COMMIT_CONTENT")
    _require(marker["receipt_bytes"] == len(raw) and marker["receipt_sha256"] == _sha256(raw), "COMMIT_RECEIPT_MISMATCH")


def _load_slot_raw_unlocked(root_fd: int, kind: str, index: int) -> bytes | None:
    final_name, stage_name, commit_name, commit_stage_name = _slot_names(kind, index)
    stage = _read_name_fd(root_fd, stage_name, missing_ok=True)
    commit_stage = _read_name_fd(root_fd, commit_stage_name, missing_ok=True)
    final = _read_name_fd(root_fd, final_name, missing_ok=True)
    commit_raw = _read_name_fd(root_fd, commit_name, missing_ok=True)
    code = f"INCOMPLETE_{kind.upper()}_{index + 1}"
    _require(stage is None and commit_stage is None, code)
    if final is None and commit_raw is None:
        return None
    _require(final is not None and commit_raw is not None, code)
    marker = _strict_json(commit_raw, f"{kind.upper()}_{index + 1}_COMMIT_JSON")
    try:
        _validate_slot_marker(marker, final_name, final)
    except WindowError:
        raise WindowError(code) from None
    return final


def _publish_slot(
    root_fd: int,
    kind: str,
    index: int,
    raw: bytes,
    *,
    write_fn: Callable[[int, bytes], int] = os.write,
    crash_after: str | None = None,
) -> None:
    final_name, stage_name, commit_name, commit_stage_name = _slot_names(kind, index)
    boundary = f"{kind}_{index + 1}"
    _lock_root(root_fd, exclusive=True)
    try:
        present = [_read_name_fd(root_fd, name, missing_ok=True) for name in (final_name, stage_name, commit_name, commit_stage_name)]
        if any(value is not None for value in present):
            if present[0] is not None and present[2] is not None and present[1] is None and present[3] is None:
                raise WindowError("SLOT_EXISTS")
            raise WindowError(f"INCOMPLETE_{kind.upper()}_{index + 1}")
        low_stages = {"created","written","file_fsynced","parent_fsynced","reopened"}
        data_crash = crash_after.removeprefix("data_") if crash_after and crash_after.startswith("data_") else (crash_after if crash_after in low_stages else None)
        _write_exclusive_fd(root_fd, stage_name, raw, write_fn=write_fn, crash_after=data_crash, boundary=boundary + "_data_stage")
        try:
            os.link(stage_name, final_name, src_dir_fd=root_fd, dst_dir_fd=root_fd, follow_symlinks=False)
        except FileExistsError:
            raise WindowError("SLOT_EXISTS") from None
        if crash_after == "data_published":
            raise WindowError("INJECTED_CRASH_DATA_PUBLISHED")
        _fsync_dir(root_fd, boundary + "_data_publish")
        if crash_after == "data_publish_parent_fsynced":
            raise WindowError("INJECTED_CRASH_DATA_PUBLISH_PARENT_FSYNCED")
        final = _read_name_fd(root_fd, final_name)
        _require(final == raw and _sha256(final or b"") == _sha256(raw), "REOPEN_HASH_MISMATCH")
        marker_raw = canonical_bytes(_slot_marker(final_name, raw))
        marker_crash = crash_after.removeprefix("marker_") if crash_after and crash_after.startswith("marker_") and crash_after.removeprefix("marker_") in low_stages else None
        _write_exclusive_fd(root_fd, commit_stage_name, marker_raw, write_fn=write_fn, crash_after=marker_crash, boundary=boundary + "_marker_stage")
        try:
            os.link(commit_stage_name, commit_name, src_dir_fd=root_fd, dst_dir_fd=root_fd, follow_symlinks=False)
        except FileExistsError:
            raise WindowError("SLOT_EXISTS") from None
        if crash_after == "marker_published":
            raise WindowError("INJECTED_CRASH_MARKER_PUBLISHED")
        _fsync_dir(root_fd, boundary + "_marker_publish")
        if crash_after == "marker_publish_parent_fsynced":
            raise WindowError("INJECTED_CRASH_MARKER_PUBLISH_PARENT_FSYNCED")
        actual_marker = _read_name_fd(root_fd, commit_name)
        _require(actual_marker == marker_raw and _sha256(actual_marker or b"") == _sha256(marker_raw), "REOPEN_HASH_MISMATCH")
        os.unlink(stage_name, dir_fd=root_fd)
        os.unlink(commit_stage_name, dir_fd=root_fd)
        if crash_after == "stages_cleaned":
            raise WindowError("INJECTED_CRASH_STAGES_CLEANED")
        _fsync_dir(root_fd, boundary + "_cleanup")
    finally:
        _unlock_root(root_fd)


def _validate_clock(receipt: Mapping[str, Any], pair: ClockPair) -> None:
    _require_exact_int(pair.wall_utc_ns, "CLOCK_WALL_UTC_NS")
    _require_exact_int(pair.monotonic_ns, "CLOCK_MONOTONIC_NS")
    _require_exact_int(pair.pair_span_ns, "CLOCK_PAIR_SPAN_NS", maximum=CLOCK_PAIR_MAX_SPAN_NS)
    _require(pair.monotonic_ns >= receipt["start_monotonic_ns"], "MONOTONIC_ROLLBACK_OR_REBOOT")
    elapsed = pair.monotonic_ns - receipt["start_monotonic_ns"]
    _require(abs(pair.wall_utc_ns - (receipt["start_utc_ns"] + elapsed)) <= WALL_MONOTONIC_MAX_DRIFT_NS, "WALL_CLOCK_JUMP")
    _require(receipt["start_utc_ns"] <= pair.wall_utc_ns <= receipt["deadline_utc_ns"], "WALL_WINDOW_BOUNDS")
    _require(pair.monotonic_ns <= receipt["deadline_monotonic_ns"], "MONOTONIC_WINDOW_EXPIRED")


def _validate_live_receipt(value: Mapping[str, Any]) -> None:
    required = {"authority_pins","block_duration_seconds","block_id","cell_order","clock_pair_span_ns","concurrency","deadline_monotonic_ns","deadline_utc_ns","extension_allowed","immutable","issuer_pid","issuer_process_token","jobs","reissue_allowed","replay_allowed","root","seal","start_monotonic_ns","start_utc_ns","status","template_sha256","version","window_id"}
    _require(set(value) == required, "WINDOW_RECEIPT_FIELDS")
    _require(value["version"] == "r6-common-execution-window-receipt-v3", "WINDOW_RECEIPT_VERSION")
    _require(value["status"] == "ISSUED" and value["immutable"] is True, "WINDOW_RECEIPT_STATUS")
    _require(value["root"] == RUNTIME_RELATIVE_ROOT.as_posix(), "WINDOW_ROOT")
    _require_exact_int(value.get("block_duration_seconds"), "WINDOW_BLOCK_DURATION", minimum=BLOCK_DURATION_SECONDS, maximum=BLOCK_DURATION_SECONDS)
    _require_exact_int(value.get("concurrency"), "WINDOW_CONCURRENCY", minimum=CONCURRENCY, maximum=CONCURRENCY)
    for key in ("start_utc_ns", "deadline_utc_ns", "start_monotonic_ns", "deadline_monotonic_ns"):
        _require_exact_int(value.get(key), "WINDOW_" + key.upper())
    _require_exact_int(value.get("clock_pair_span_ns"), "WINDOW_PAIR_SPAN", maximum=CLOCK_PAIR_MAX_SPAN_NS)
    _require_exact_int(value.get("issuer_pid"), "WINDOW_PID", minimum=1)
    _require(value["cell_order"] == list(CELL_ORDER), "WINDOW_ORDER")
    _require(value["deadline_utc_ns"] - value["start_utc_ns"] == BLOCK_DURATION_NS, "WINDOW_WALL_DURATION")
    _require(value["deadline_monotonic_ns"] - value["start_monotonic_ns"] == BLOCK_DURATION_NS, "WINDOW_MONOTONIC_DURATION")
    _require(isinstance(value["issuer_process_token"], str) and _SHA_RE.fullmatch(value["issuer_process_token"]), "WINDOW_PROCESS_TOKEN")
    for key, kind in (("block_id", "block"), ("window_id", "window")):
        _require(isinstance(value[key], str) and value[key].startswith(kind + "_") and _ID_RE.fullmatch(value[key]), "WINDOW_ID")
    jobs = value["jobs"]
    _require(isinstance(jobs, list) and len(jobs) == 4, "WINDOW_JOBS")
    fields = {"admission_deadline_monotonic_ns","admission_deadline_utc_ns","attempt_id","cell_id","job_id","operation_id","ordinal","slot_id"}
    for index, job in enumerate(jobs):
        _require(isinstance(job, dict) and set(job) == fields, "WINDOW_JOB_FIELDS")
        _require_exact_int(job.get("ordinal"), "WINDOW_JOB_ORDINAL", minimum=1, maximum=4)
        _require_exact_int(job.get("admission_deadline_utc_ns"), "WINDOW_JOB_WALL_NS")
        _require_exact_int(job.get("admission_deadline_monotonic_ns"), "WINDOW_JOB_MONOTONIC_NS")
        _require(job["ordinal"] == index + 1 and job["cell_id"] == CELL_ORDER[index], "WINDOW_JOB_ORDER")
        for key, kind in (("job_id","job"),("slot_id","slot"),("attempt_id","attempt"),("operation_id","operation")):
            _require(isinstance(job[key], str) and job[key].startswith(kind + "_") and _ID_RE.fullmatch(job[key]), "WINDOW_JOB_ID")
        offset = ADMISSION_OFFSETS_SECONDS[index] * 1_000_000_000
        _require(job["admission_deadline_utc_ns"] == value["start_utc_ns"] + offset, "WINDOW_JOB_WALL_DEADLINE")
        _require(job["admission_deadline_monotonic_ns"] == value["start_monotonic_ns"] + offset, "WINDOW_JOB_MONOTONIC_DEADLINE")
    _require(isinstance(value["authority_pins"], dict) and set(value["authority_pins"]) == set(PIN_PATHS), "WINDOW_AUTHORITY")
    for name, ref in value["authority_pins"].items():
        _require(isinstance(ref, dict) and set(ref) == {"path","bytes","sha256"}, "WINDOW_AUTHORITY_REF")
        _require(ref["path"] == PIN_PATHS[name], "WINDOW_AUTHORITY_PATH")
        _require_exact_int(ref.get("bytes"), "WINDOW_AUTHORITY_BYTES", minimum=1)
        _require(isinstance(ref["sha256"], str) and _SHA_RE.fullmatch(ref["sha256"]), "WINDOW_AUTHORITY_HASH")
    _require(value["reissue_allowed"] is False and value["extension_allowed"] is False and value["replay_allowed"] is False, "WINDOW_REPLAY_POLICY")
    _require(isinstance(value["template_sha256"], str) and _SHA_RE.fullmatch(value["template_sha256"]), "WINDOW_TEMPLATE_HASH")
    _verify_seal(value, "WINDOW")


def _validate_receipt_binding(receipt: Mapping[str, Any], template: Mapping[str, Any], pins: Mapping[str, Any]) -> None:
    _require(receipt["template_sha256"] == template["seal"]["sha256"], "WINDOW_TEMPLATE_BINDING")
    _require(receipt["authority_pins"] == pins, "WINDOW_AUTHORITY_BINDING")


def _build_live_receipt(template: Mapping[str, Any], pins: Mapping[str, Any], pair: ClockPair, process_token: str) -> dict[str, Any]:
    jobs = []
    for index, cell in enumerate(CELL_ORDER):
        offset = ADMISSION_OFFSETS_SECONDS[index] * 1_000_000_000
        jobs.append({"ordinal":index+1,"cell_id":cell,"job_id":_new_id("job"),"slot_id":_new_id("slot"),"attempt_id":_new_id("attempt"),"operation_id":_new_id("operation"),"admission_deadline_utc_ns":pair.wall_utc_ns+offset,"admission_deadline_monotonic_ns":pair.monotonic_ns+offset})
    return _seal({"version":"r6-common-execution-window-receipt-v3","status":"ISSUED","immutable":True,"block_id":_new_id("block"),"window_id":_new_id("window"),"root":RUNTIME_RELATIVE_ROOT.as_posix(),"block_duration_seconds":1800,"concurrency":1,"cell_order":list(CELL_ORDER),"start_utc_ns":pair.wall_utc_ns,"deadline_utc_ns":pair.wall_utc_ns+BLOCK_DURATION_NS,"start_monotonic_ns":pair.monotonic_ns,"deadline_monotonic_ns":pair.monotonic_ns+BLOCK_DURATION_NS,"clock_pair_span_ns":pair.pair_span_ns,"issuer_pid":os.getpid(),"issuer_process_token":process_token,"jobs":jobs,"template_sha256":template["seal"]["sha256"],"authority_pins":copy.deepcopy(dict(pins)),"reissue_allowed":False,"extension_allowed":False,"replay_allowed":False})


def _write_stage_and_link(root_fd: int, stage: str, final: str, raw: bytes, *, write_fn: Callable[[int,bytes],int] = os.write, crash_after: str | None = None, prefix: str) -> None:
    _write_exclusive_fd(root_fd, stage, raw, write_fn=write_fn, crash_after=(crash_after.removeprefix(prefix+"_") if crash_after and crash_after.startswith(prefix+"_") else None), boundary=prefix+"_stage")
    os.link(stage, final, src_dir_fd=root_fd, dst_dir_fd=root_fd, follow_symlinks=False)
    _fsync_dir(root_fd, prefix + "_publish")
    if crash_after == prefix + "_published":
        raise WindowError("INJECTED_CRASH_" + crash_after.upper())
    actual = _read_name_fd(root_fd, final)
    _require(actual == raw and _sha256(actual or b"") == _sha256(raw), "REOPEN_HASH_MISMATCH")
    os.unlink(stage, dir_fd=root_fd)
    _fsync_dir(root_fd, prefix + "_cleanup")


def _publish_receipt_at(
    parent_fd: int,
    receipt: Mapping[str, Any],
    *,
    write_fn: Callable[[int, bytes], int] = os.write,
    crash_after: str | None = None,
    before_open: Callable[[], None] | None = None,
    before_marker_parent_fsync: Callable[[], None] | None = None,
) -> Mapping[str, Any]:
    _validate_live_receipt(receipt)
    try:
        root_fd = _create_new_root(parent_fd, RUNTIME_RELATIVE_ROOT.name, after_bind=before_open)
    except WindowError as exc:
        if exc.code == "ROOT_EXISTS":
            raise WindowError("SINGLE_ISSUANCE_ONLY") from None
        raise
    _lock_root(root_fd, exclusive=True)
    try:
        names = set(os.listdir(root_fd))
        _require(not names.intersection({RECEIPT_NAME, MARKER_NAME, RECEIPT_STAGE_NAME, MARKER_STAGE_NAME}), "SINGLE_ISSUANCE_ONLY")
        raw = canonical_bytes(receipt)
        low_stages = {"created", "written", "file_fsynced", "parent_fsynced", "reopened"}
        receipt_crash = crash_after.removeprefix("receipt_") if crash_after and crash_after.startswith("receipt_") and crash_after.removeprefix("receipt_") in low_stages else None
        _write_exclusive_fd(root_fd, RECEIPT_STAGE_NAME, raw, write_fn=write_fn, crash_after=receipt_crash, boundary="receipt_stage")
        os.link(RECEIPT_STAGE_NAME, RECEIPT_NAME, src_dir_fd=root_fd, dst_dir_fd=root_fd, follow_symlinks=False)
        _fsync_dir(root_fd, "receipt_publish")
        if crash_after == "receipt_published":
            raise WindowError("INJECTED_CRASH_RECEIPT_PUBLISHED")
        receipt_final = _read_name_fd(root_fd, RECEIPT_NAME)
        _require(receipt_final == raw and _sha256(receipt_final or b"") == _sha256(raw), "REOPEN_HASH_MISMATCH")
        marker_raw = canonical_bytes({"version":"r6-common-execution-window-commit-v3","receipt":RECEIPT_NAME,"receipt_bytes":len(raw),"receipt_sha256":_sha256(raw),"committed":True})
        marker_crash = crash_after.removeprefix("marker_") if crash_after and crash_after.startswith("marker_") and crash_after.removeprefix("marker_") in low_stages else None
        _write_exclusive_fd(root_fd, MARKER_STAGE_NAME, marker_raw, write_fn=write_fn, crash_after=marker_crash, boundary="marker_stage")
        os.link(MARKER_STAGE_NAME, MARKER_NAME, src_dir_fd=root_fd, dst_dir_fd=root_fd, follow_symlinks=False)
        if before_marker_parent_fsync is not None:
            before_marker_parent_fsync()
        _fsync_dir(root_fd, "marker_publish")
        marker_final = _read_name_fd(root_fd, MARKER_NAME)
        _require(marker_final == marker_raw and _sha256(marker_final or b"") == _sha256(marker_raw), "REOPEN_HASH_MISMATCH")
        os.unlink(RECEIPT_STAGE_NAME, dir_fd=root_fd)
        os.unlink(MARKER_STAGE_NAME, dir_fd=root_fd)
        _fsync_dir(root_fd, "receipt_marker_cleanup")
        if crash_after == "marker_published":
            raise WindowError("INJECTED_CRASH_MARKER_PUBLISHED")
        recovered = _recover_receipt_unlocked(root_fd)
        _verify_child_binding(parent_fd, RUNTIME_RELATIVE_ROOT.name, root_fd)
        return recovered
    finally:
        _unlock_root(root_fd)
        os.close(root_fd)


def _recover_receipt_unlocked(root_fd: int) -> Mapping[str, Any]:
    names = set(os.listdir(root_fd))
    _require(RECEIPT_STAGE_NAME not in names and MARKER_STAGE_NAME not in names, "INCOMPLETE_WINDOW_NO_REISSUE")
    if MARKER_NAME not in names:
        if RECEIPT_NAME in names:
            raise WindowError("INCOMPLETE_WINDOW_NO_REISSUE")
        raise WindowError("WINDOW_NOT_ISSUED")
    _require(RECEIPT_NAME in names, "COMMIT_WITHOUT_RECEIPT")
    marker = _strict_json(_read_name_fd(root_fd, MARKER_NAME) or b"", "COMMIT_JSON")
    raw = _read_name_fd(root_fd, RECEIPT_NAME) or b""
    _validate_receipt_marker(marker, raw)
    receipt = _strict_json(raw, "WINDOW_RECEIPT_JSON")
    _validate_live_receipt(receipt)
    return receipt


def _recover_receipt_fd(root_fd: int) -> Mapping[str, Any]:
    _lock_root(root_fd, exclusive=False)
    try:
        return _recover_receipt_unlocked(root_fd)
    finally:
        _unlock_root(root_fd)


def _validate_claim(claim: Mapping[str, Any], receipt: Mapping[str, Any], index: int) -> None:
    _require_exact_int(index, "CLAIM_INDEX", maximum=3)
    fields = {"attempt_id","cell_id","claimant_pid","claimant_process_token","claimed_monotonic_ns","claimed_utc_ns","concurrency","decision","immutable","job_id","operation_id","ordinal","replay_allowed","seal","slot_id","version","window_id"}
    _require(set(claim) == fields, "CLAIM_FIELDS")
    _require(claim["version"] == "r6-common-execution-window-claim-v3" and claim["decision"] == "ADMIT" and claim["immutable"] is True, "CLAIM_VERSION")
    _require_exact_int(claim.get("ordinal"), "CLAIM_ORDINAL", minimum=1, maximum=4)
    _require_exact_int(claim.get("concurrency"), "CLAIM_CONCURRENCY", minimum=CONCURRENCY, maximum=CONCURRENCY)
    _require_exact_int(claim.get("claimant_pid"), "CLAIM_PID", minimum=1)
    _require_exact_int(claim.get("claimed_utc_ns"), "CLAIM_UTC_NS")
    _require_exact_int(claim.get("claimed_monotonic_ns"), "CLAIM_MONOTONIC_NS")
    job = receipt["jobs"][index]
    for key in ("cell_id","ordinal","job_id","slot_id","attempt_id","operation_id"):
        _require(claim[key] == job[key], "CLAIM_IDENTITY")
    _require(claim["window_id"] == receipt["window_id"], "CLAIM_WINDOW")
    _require(claim["concurrency"] == 1 and claim["replay_allowed"] is False, "CLAIM_POLICY")
    _require(isinstance(claim["claimant_process_token"], str) and _SHA_RE.fullmatch(claim["claimant_process_token"]), "CLAIM_TOKEN")
    _require(receipt["start_utc_ns"] <= claim["claimed_utc_ns"] <= job["admission_deadline_utc_ns"], "CLAIM_WALL_DEADLINE")
    _require(receipt["start_monotonic_ns"] <= claim["claimed_monotonic_ns"] <= job["admission_deadline_monotonic_ns"], "CLAIM_MONOTONIC_DEADLINE")
    elapsed = claim["claimed_monotonic_ns"] - receipt["start_monotonic_ns"]
    expected_wall = receipt["start_utc_ns"] + elapsed
    _require(abs(claim["claimed_utc_ns"] - expected_wall) <= WALL_MONOTONIC_MAX_DRIFT_NS, "CLAIM_CLOCK_DRIFT")
    _verify_seal(claim, "CLAIM")


def _validate_terminal(terminal: Mapping[str, Any], receipt: Mapping[str, Any], claim: Mapping[str, Any], index: int) -> None:
    _require_exact_int(index, "TERMINAL_INDEX", maximum=3)
    fields = {"attempt_id","cell_id","claim_sha256","immutable","job_id","operation_id","ordinal","seal","slot_id","terminal_state","version","window_id"}
    _require(set(terminal) == fields, "TERMINAL_FIELDS")
    _require(terminal["version"] == "r6-common-execution-window-terminal-v3" and terminal["immutable"] is True, "TERMINAL_VERSION")
    _require_exact_int(terminal.get("ordinal"), "TERMINAL_ORDINAL", minimum=1, maximum=4)
    job = receipt["jobs"][index]
    for key in ("cell_id","ordinal","job_id","slot_id","attempt_id","operation_id"):
        _require(terminal[key] == job[key], "TERMINAL_IDENTITY")
    _require(terminal["window_id"] == receipt["window_id"], "TERMINAL_WINDOW")
    _require(terminal["terminal_state"] in {"PASS","FAIL","STOP","MALFORMED","MISSING","UNKNOWN"}, "TERMINAL_STATE")
    _require(terminal["claim_sha256"] == _sha256(canonical_bytes(claim)), "TERMINAL_CLAIM")
    _verify_seal(terminal, "TERMINAL")


@dataclass(frozen=True)
class NamespaceState:
    completed: tuple[Mapping[str, Any], ...]
    active_claim: Mapping[str, Any] | None
    next_index: int


def _scan_namespace_unlocked(root_fd: int, receipt: Mapping[str, Any]) -> NamespaceState:
    claims: list[Mapping[str, Any] | None] = []
    terminals: list[Mapping[str, Any] | None] = []
    for index in range(4):
        claim_raw = _load_slot_raw_unlocked(root_fd, "claim", index)
        terminal_raw = _load_slot_raw_unlocked(root_fd, "terminal", index)
        claim = _strict_json(claim_raw, f"CLAIM_{index+1}_JSON") if claim_raw is not None else None
        terminal = _strict_json(terminal_raw, f"TERMINAL_{index+1}_JSON") if terminal_raw is not None else None
        if claim is not None:
            _validate_claim(claim, receipt, index)
        if terminal is not None:
            _require(claim is not None, "NAMESPACE_TERMINAL_WITHOUT_CLAIM")
            _validate_terminal(terminal, receipt, claim, index)
        claims.append(claim)
        terminals.append(terminal)
    completed: list[Mapping[str, Any]] = []
    active: Mapping[str, Any] | None = None
    gap_seen = False
    unknown_seen = False
    for claim, terminal in zip(claims, terminals):
        if gap_seen:
            _require(claim is None and terminal is None, "NAMESPACE_LATER_ARTIFACT")
            continue
        if claim is None:
            _require(terminal is None, "NAMESPACE_TERMINAL_WITHOUT_CLAIM")
            gap_seen = True
            continue
        if terminal is None:
            active = claim
            gap_seen = True
            continue
        _require(not unknown_seen, "UNKNOWN_FORBIDS_LATER_CELLS")
        completed.append(terminal)
        if terminal["terminal_state"] == "UNKNOWN":
            unknown_seen = True
            gap_seen = True
    if unknown_seen:
        return NamespaceState(tuple(completed), None, len(completed))
    next_index = len(completed)
    _require(active is None or active["ordinal"] == next_index + 1, "NAMESPACE_ACTIVE_ORDER")
    return NamespaceState(tuple(completed), active, next_index)


def _scan_namespace(root_fd: int, receipt: Mapping[str, Any]) -> NamespaceState:
    _lock_root(root_fd, exclusive=False)
    try:
        return _scan_namespace_unlocked(root_fd, receipt)
    finally:
        _unlock_root(root_fd)


def _claim_at(root_fd: int, receipt: Mapping[str, Any], pair: ClockPair, *, current_pid: int, process_token: str, write_fn: Callable[[int,bytes],int] = os.write, crash_after: str | None = None) -> dict[str, Any]:
    _validate_live_receipt(receipt)
    _validate_clock(receipt, pair)
    _require_exact_int(current_pid, "CLAIM_CURRENT_PID", minimum=1)
    state = _scan_namespace(root_fd, receipt)
    if state.completed and state.completed[-1]["terminal_state"] == "UNKNOWN":
        raise WindowError("UNKNOWN_FORBIDS_LATER_CELLS")
    if state.active_claim is not None:
        active = state.active_claim
        if active["claimant_pid"] == current_pid and active["claimant_process_token"] != process_token:
            raise WindowError("PID_REUSE_UNKNOWN")
        if active["claimant_pid"] != current_pid:
            raise WindowError("ACTIVE_PROCESS_RESTART_UNKNOWN")
        raise WindowError("CONCURRENCY_ONE_ACTIVE")
    index = state.next_index
    _require(index < 4, "WINDOW_COMPLETE")
    job = receipt["jobs"][index]
    _require(pair.monotonic_ns <= job["admission_deadline_monotonic_ns"], "CELL_MONOTONIC_DEADLINE")
    _require(pair.wall_utc_ns <= job["admission_deadline_utc_ns"], "CELL_WALL_DEADLINE")
    claim = _seal({"version":"r6-common-execution-window-claim-v3","decision":"ADMIT","window_id":receipt["window_id"],"ordinal":index+1,"cell_id":job["cell_id"],"job_id":job["job_id"],"slot_id":job["slot_id"],"attempt_id":job["attempt_id"],"operation_id":job["operation_id"],"concurrency":1,"replay_allowed":False,"claimant_pid":current_pid,"claimant_process_token":process_token,"claimed_utc_ns":pair.wall_utc_ns,"claimed_monotonic_ns":pair.monotonic_ns,"immutable":True})
    raw = canonical_bytes(claim)
    try:
        _publish_slot(root_fd, "claim", index, raw, write_fn=write_fn, crash_after=crash_after)
    except WindowError as exc:
        if exc.code not in {"SLOT_EXISTS", "NAMESPACE_BUSY"}:
            raise
        if exc.code == "SLOT_EXISTS":
            _scan_namespace(root_fd, receipt)
        raise WindowError("CLAIM_RACE_LOST") from None
    return claim


def _publish_terminal_at(root_fd: int, receipt: Mapping[str, Any], terminal_state: str, *, current_pid: int, process_token: str, write_fn: Callable[[int,bytes],int] = os.write, crash_after: str | None = None) -> dict[str, Any]:
    _require_exact_int(current_pid, "TERMINAL_CURRENT_PID", minimum=1)
    _require(terminal_state in {"PASS","FAIL","STOP","MALFORMED","MISSING","UNKNOWN"}, "TERMINAL_STATE")
    state = _scan_namespace(root_fd, receipt)
    _require(state.active_claim is not None, "NO_ACTIVE_CLAIM")
    claim = state.active_claim
    if claim["claimant_pid"] == current_pid and claim["claimant_process_token"] != process_token:
        raise WindowError("PID_REUSE_UNKNOWN")
    if claim["claimant_pid"] != current_pid:
        raise WindowError("ACTIVE_PROCESS_RESTART_UNKNOWN")
    _require(claim["claimant_process_token"] == process_token, "CLAIM_PROCESS_MISMATCH")
    index = claim["ordinal"] - 1
    terminal = _seal({"version":"r6-common-execution-window-terminal-v3","window_id":receipt["window_id"],"ordinal":claim["ordinal"],"cell_id":claim["cell_id"],"job_id":claim["job_id"],"slot_id":claim["slot_id"],"attempt_id":claim["attempt_id"],"operation_id":claim["operation_id"],"claim_sha256":_sha256(canonical_bytes(claim)),"terminal_state":terminal_state,"immutable":True})
    raw = canonical_bytes(terminal)
    try:
        _publish_slot(root_fd, "terminal", index, raw, write_fn=write_fn, crash_after=crash_after)
    except WindowError as exc:
        if exc.code == "NAMESPACE_BUSY":
            raise WindowError("TERMINAL_RACE_LOST") from None
        if exc.code != "SLOT_EXISTS":
            raise
        _lock_root(root_fd, exclusive=False)
        try:
            existing = _load_slot_raw_unlocked(root_fd, "terminal", index) or b""
        finally:
            _unlock_root(root_fd)
        existing_value = _strict_json(existing, "TERMINAL_REPLAY_JSON")
        _validate_terminal(existing_value, receipt, claim, index)
        if existing == raw:
            raise WindowError("TERMINAL_ALREADY_COMMITTED") from None
        raise WindowError("TERMINAL_REPLAY_MISMATCH") from None
    _scan_namespace(root_fd, receipt)
    return terminal


def _validate_template(value: Mapping[str, Any]) -> None:
    fields = {"activation","admission_offsets_seconds","block_duration_seconds","cell_order","clock","concurrency","countable","effects","pending_pins","provider_free","publication","seal","source_pins","status","version"}
    _require(set(value) == fields, "TEMPLATE_FIELDS")
    _require(value["version"] == "r6-common-execution-window-template-v3", "TEMPLATE_VERSION")
    _require(value["status"] == STATUS and value["activation"] is False and value["provider_free"] is True and value["countable"] is False, "TEMPLATE_STATUS")
    _require_exact_int(value.get("block_duration_seconds"), "TEMPLATE_BLOCK_DURATION", minimum=BLOCK_DURATION_SECONDS, maximum=BLOCK_DURATION_SECONDS)
    _require_exact_int(value.get("concurrency"), "TEMPLATE_CONCURRENCY", minimum=CONCURRENCY, maximum=CONCURRENCY)
    offsets = value.get("admission_offsets_seconds")
    _require(isinstance(offsets, list) and len(offsets) == len(ADMISSION_OFFSETS_SECONDS), "TEMPLATE_OFFSETS")
    for index, offset in enumerate(offsets):
        _require_exact_int(offset, "TEMPLATE_OFFSET", minimum=ADMISSION_OFFSETS_SECONDS[index], maximum=ADMISSION_OFFSETS_SECONDS[index])
    _require(value["cell_order"] == list(CELL_ORDER) and offsets == list(ADMISSION_OFFSETS_SECONDS), "TEMPLATE_ORDER")
    _require(isinstance(value.get("clock"), dict), "TEMPLATE_CLOCK")
    for key, expected in (("max_pair_span_ns", CLOCK_PAIR_MAX_SPAN_NS), ("max_wall_monotonic_drift_ns", WALL_MONOTONIC_MAX_DRIFT_NS)):
        _require_exact_int(value["clock"].get(key), "TEMPLATE_CLOCK_INTEGER", minimum=expected, maximum=expected)
    _require(value["clock"] == {"source":"internal-system-utc-monotonic-pair","caller_injection":"FORBIDDEN","rollback":"DENY","jump":"DENY","max_pair_span_ns":CLOCK_PAIR_MAX_SPAN_NS,"max_wall_monotonic_drift_ns":WALL_MONOTONIC_MAX_DRIFT_NS}, "TEMPLATE_CLOCK")
    _require(value["publication"] == {"root":RUNTIME_RELATIVE_ROOT.as_posix(),"root_mode":"0700","receipt":RECEIPT_NAME,"receipt_mode":"0600","commit_marker":MARKER_NAME,"commit_marker_last":True,"claim_slots":list(CLAIM_NAMES),"claim_commit_markers":list(CLAIM_COMMIT_NAMES),"terminal_slots":list(TERMINAL_NAMES),"terminal_commit_markers":list(TERMINAL_COMMIT_NAMES),"slot_mode":"0600","slot_commit_marker_last":True,"slot_locking":"root-flock-exclusive-publication-shared-scan-fail-closed","no_replace":True,"single_issuance":True,"extension":"FORBIDDEN","reissue":"FORBIDDEN","replay":"FORBIDDEN"}, "TEMPLATE_PUBLICATION")
    _require(value["pending_pins"] == ["final_reviewed_block_grant","authentic_g1_authority","authentic_g2_authority","p0_v10","runner_v4","provider_authority","human_authority","fresh_independent_review"], "TEMPLATE_PENDING")
    _require(isinstance(value.get("effects"), dict) and set(value["effects"]) == {"provider","credential","network","email","business","host","bytedcli"}, "TEMPLATE_EFFECTS")
    for amount in value["effects"].values():
        _require_exact_int(amount, "TEMPLATE_EFFECT_COUNT", minimum=0, maximum=0)
    _require(value["effects"] == {"provider":0,"credential":0,"network":0,"email":0,"business":0,"host":0,"bytedcli":0}, "TEMPLATE_EFFECTS")
    _require(isinstance(value["source_pins"], list) and len(value["source_pins"]) >= 1, "TEMPLATE_SOURCE_PINS")
    for ref in value["source_pins"]:
        _require(isinstance(ref, dict) and set(ref) == {"path","bytes","sha256"}, "TEMPLATE_SOURCE_PIN_FIELDS")
        _require_exact_int(ref.get("bytes"), "TEMPLATE_SOURCE_PIN_BYTES", minimum=1)
        _require(isinstance(ref.get("path"), str) and ref["path"], "TEMPLATE_SOURCE_PIN_PATH")
        _require(isinstance(ref.get("sha256"), str) and _SHA_RE.fullmatch(ref["sha256"]), "TEMPLATE_SOURCE_PIN_HASH")
    _verify_seal(value, "TEMPLATE")


def prepare_window_template() -> dict[str, Any]:
    workspace_fd = _open_workspace_fd()
    try:
        fd, status = _open_relative_regular(workspace_fd, TEMPLATE_RELATIVE_PATH, 0o600, "TEMPLATE")
        try:
            raw = _read_fd_stable(fd, status, "TEMPLATE")
        finally:
            os.close(fd)
        value = _strict_json(raw, "TEMPLATE_JSON")
        _validate_template(value)
        for index, ref in enumerate(value["source_pins"]):
            _require(isinstance(ref, dict), f"SOURCE_PIN_{index}_TYPE")
            _verify_source_ref(workspace_fd, ref, index)
        return copy.deepcopy(dict(value))
    finally:
        os.close(workspace_fd)


def issue_live_window() -> dict[str, Any]:
    template, pins = _activation_preflight()
    process_token = _get_process_token()
    pair = _trusted_clock_pair()
    receipt = _build_live_receipt(template, pins, pair, process_token)
    parent_fd = _open_runtime_parent_fd()
    try:
        return dict(_publish_receipt_at(parent_fd, receipt))
    finally:
        os.close(parent_fd)


def recover_live_window() -> dict[str, Any]:
    template, pins = _activation_preflight()
    root_fd = _open_canonical_root()
    try:
        receipt = _recover_receipt_fd(root_fd)
        _validate_receipt_binding(receipt, template, pins)
        return dict(receipt)
    finally:
        os.close(root_fd)


def validate_live_window() -> dict[str, Any]:
    receipt = recover_live_window()
    _validate_clock(receipt, _trusted_clock_pair())
    return receipt


def admit_next_cell() -> dict[str, Any]:
    template, pins = _activation_preflight()
    process_token = _get_process_token()
    pair = _trusted_clock_pair()
    root_fd = _open_canonical_root()
    try:
        receipt = _recover_receipt_fd(root_fd)
        _validate_receipt_binding(receipt, template, pins)
        return _claim_at(root_fd, receipt, pair, current_pid=os.getpid(), process_token=process_token)
    finally:
        os.close(root_fd)


def publish_terminal(terminal_state: str) -> dict[str, Any]:
    template, pins = _activation_preflight()
    process_token = _get_process_token()
    root_fd = _open_canonical_root()
    try:
        receipt = _recover_receipt_fd(root_fd)
        _validate_receipt_binding(receipt, template, pins)
        return _publish_terminal_at(root_fd, receipt, terminal_state, current_pid=os.getpid(), process_token=process_token)
    finally:
        os.close(root_fd)
