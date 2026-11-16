"""Provider-free, disabled R6 blind-map commitment transaction v6.

The owner-private namespace uses one fixed O_EXCL reservation. Every published
artifact binds its transaction and its own device/inode in canonical bytes.
Unsafe deletion is intentionally absent: failed owned artifacts are atomically
moved to transaction-scoped quarantine, and any identity uncertainty fences.
"""
from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Sequence, Tuple


class CommitmentError(ValueError):
    pass


def _require(value: bool, code: str) -> None:
    if not value:
        raise CommitmentError(code)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise CommitmentError("CANONICAL_VALUE_INVALID") from None


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
RUNTIME_RELATIVE_ROOT = Path("runtime/r6_data_quality_blind_map_commitment_v6")
PRIVATE_MAP_NAME = "owner-private-canonical-map-v6.json"
COMMITMENT_NAME = "sanitized-commitment-v6.json"
RECEIPT_NAME = "transaction-receipt-v6.json"
LOCK_NAME = ".transaction-lock-v6.json"
MAP_SCHEMA_ID = "r6-data-quality-blind-map-v6"
COMMITMENT_SCHEMA_ID = "r6-data-quality-blind-map-commitment-v6"
RECEIPT_SCHEMA_ID = "r6-data-quality-blind-map-transaction-v6"
LOCK_SCHEMA_ID = "r6-data-quality-blind-map-transaction-lock-v6"
CELL_IDS = ("R6DQ-7F2C91A4", "R6DQ-1B8E43D7", "R6DQ-C4A7095E", "R6DQ-92D6F0B3")
LABEL_RE = re.compile(r"[0-9a-f]{32}\Z")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
TX_RE = re.compile(r"[0-9a-f]{32}\Z")
STAGE_RE = re.compile(r"\.stage-([0-9a-f]{32})-(map|commitment|receipt)\.json\Z")
QUARANTINE_RE = re.compile(r"\.quarantine-([0-9a-f]{32})-[0-9a-f]{32}-(.+)\Z")
RELEASED_RE = re.compile(r"\.released-([0-9a-f]{32})-[0-9a-f]{32}\.json\Z")

MAP_MAX_BYTES = 4096
COMMITMENT_MAX_BYTES = 2048
RECEIPT_MAX_BYTES = 8192
LOCK_MAX_BYTES = 2048
TRANSIENT_MAX_BYTES = 8192

DESIGN_IDENTITY = "fcf096d0c641f373eab7163fa894e5d4f9605ab3ab36ff867e4b586bdcaf278e"
DESIGN_REVIEW_IDENTITY = "0018e413e40371bb2703aecf3963433f1a883a93b1070e815dccc0dc61866d3f"
EVALUATION_IDENTITY = "8bef52f4f1c7511ec8897b17dbee2f542b0a822acaf22ebbe2e0e267d7c6714d"
EVALUATION_PRODUCER_IDENTITY = "2df4cae89b8942a8eb38b766608381f4bc41aeb8f4c984a9d32aa677068718ea"
EVALUATION_REVIEW_IDENTITY = "da36e2ae03c7a74ef7b5dce91eb7fc7e627b3cb431a0064c6efde37ef744b429"
OPEN_REVIEW_IDENTITY = "a76216d40b8af7617e7169f0969ab15bd69e3333dce6b6e9543af77612f783e8"
EVALUATION_HARNESS_IDENTITY = "a42f1d0303857f443b5352ed7cfd244551767d347168e3ada6b7f8042cdaa7e4"

PINNED_SOURCES = (
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-addon-2x2-ab-design.json", 26277, DESIGN_IDENTITY),
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-addon-2x2-ab-design-independent-review.json", 18741, DESIGN_REVIEW_IDENTITY),
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-evaluation-contract-v3.json", 9944, EVALUATION_IDENTITY),
    ("tuning/architecture/r6_data_quality_2x2_evaluation_v3/producer-verification-v3.json", 2588, EVALUATION_PRODUCER_IDENTITY),
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-evaluation-v3-independent-review.json", 10585, EVALUATION_REVIEW_IDENTITY),
    ("shared/job_runtime/candidates/r6_data_quality_2x2_evaluation_v3/harness.py", 31895, EVALUATION_HARNESS_IDENTITY),
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/claude-r6-data-quality-blind-map-commitment-v5-independent-review-open-v1-fable-20261113.json", 23467, OPEN_REVIEW_IDENTITY),
)

_RENAME_EXCL = 0x00000004


def _root_path() -> Path:
    root = WORKSPACE_ROOT / RUNTIME_RELATIVE_ROOT
    _require(root.is_absolute(), "ROOT_NOT_ABSOLUTE")
    return root


def _identity(status: os.stat_result) -> Tuple[int, int]:
    return status.st_dev, status.st_ino


def _identity_value(identity: Tuple[int, int]) -> Dict[str, int]:
    return {"device": identity[0], "inode": identity[1]}


def _validate_identity(value: Any, actual: Tuple[int, int], code: str) -> None:
    _require(isinstance(value, Mapping) and set(value) == {"device", "inode"}, code + "_FIELDS")
    _require(value["device"] == actual[0] and value["inode"] == actual[1], code + "_MISMATCH")


def _read_fd_bounded(fd: int, maximum: int, code: str) -> Tuple[bytes, os.stat_result]:
    before = os.fstat(fd)
    _require(stat.S_ISREG(before.st_mode), code + "_NOT_REGULAR")
    _require(0 <= before.st_size <= maximum, code + "_OVERSIZE")
    remaining = before.st_size
    chunks = []
    total = 0
    while remaining:
        chunk = os.read(fd, min(65536, remaining))
        _require(bool(chunk), code + "_TRUNCATED")
        chunks.append(chunk)
        total += len(chunk)
        remaining -= len(chunk)
    _require(os.read(fd, 1) == b"", code + "_GREW")
    after = os.fstat(fd)
    _require((_identity(after), after.st_size, after.st_mtime_ns) == (_identity(before), before.st_size, before.st_mtime_ns), code + "_RACY")
    _require(total == before.st_size, code + "_SIZE")
    return b"".join(chunks), after


def _read_pinned(relative: str, expected_bytes: int, expected_sha: str) -> None:
    parts = relative.split("/")
    _require(all(part not in ("", ".", "..") for part in parts), "PINNED_SOURCE_PATH")
    opened = []
    try:
        fd = os.open(str(WORKSPACE_ROOT), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)); opened.append(fd)
        for part in parts[:-1]:
            fd = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd); opened.append(fd)
        fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd); opened.append(fd)
        raw, status = _read_fd_bounded(fd, expected_bytes, "PINNED_SOURCE")
        _require(status.st_uid == os.getuid(), "PINNED_SOURCE_OWNER")
    except CommitmentError:
        raise
    except OSError as exc:
        raise CommitmentError("PINNED_SOURCE_MISSING") from exc
    finally:
        for descriptor in reversed(opened):
            try: os.close(descriptor)
            except OSError: pass
    _require(len(raw) == expected_bytes, "PINNED_SOURCE_BYTES")
    _require(hashlib.sha256(raw).hexdigest() == expected_sha, "PINNED_SOURCE_DIGEST")


def _verify_pinned_sources() -> None:
    for relative, expected_bytes, expected_sha in PINNED_SOURCES:
        _read_pinned(relative, expected_bytes, expected_sha)


def _validate_root() -> os.stat_result:
    try: status = os.lstat(_root_path())
    except OSError as exc: raise CommitmentError("ROOT_MISSING") from exc
    _require(not stat.S_ISLNK(status.st_mode) and stat.S_ISDIR(status.st_mode), "ROOT_NOT_DIRECTORY")
    _require(status.st_uid == os.getuid(), "ROOT_OWNER")
    _require(stat.S_IMODE(status.st_mode) == 0o700, "ROOT_MODE")
    return status


def _ensure_root() -> None:
    root = _root_path(); parent = root.parent
    try:
        parent_status = os.lstat(parent)
        _require(not stat.S_ISLNK(parent_status.st_mode) and stat.S_ISDIR(parent_status.st_mode), "ROOT_PARENT_INVALID")
        _require(parent_status.st_uid == os.getuid(), "ROOT_PARENT_OWNER")
        try:
            os.mkdir(root, 0o700); os.chmod(root, 0o700, follow_symlinks=False)
            pfd = os.open(str(parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
            try: os.fsync(pfd)
            finally: os.close(pfd)
        except FileExistsError: pass
    except CommitmentError: raise
    except OSError as exc: raise CommitmentError("ROOT_CREATE") from exc
    _validate_root()


def _open_root_fd() -> Tuple[int, os.stat_result]:
    expected = _validate_root()
    try: fd = os.open(str(_root_path()), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc: raise CommitmentError("ROOT_OPEN_NOFOLLOW") from exc
    actual = os.fstat(fd)
    if _identity(actual) != _identity(expected):
        os.close(fd); raise CommitmentError("ROOT_SUBSTITUTION")
    return fd, actual


def _safe_name(name: str, *, transient: bool = False) -> None:
    fixed = name in (PRIVATE_MAP_NAME, COMMITMENT_NAME, RECEIPT_NAME, LOCK_NAME)
    extra = transient and (STAGE_RE.fullmatch(name) or QUARANTINE_RE.fullmatch(name) or RELEASED_RE.fullmatch(name))
    _require(isinstance(name, str) and bool(fixed or extra), "PATH_NOT_FIXED")
    _require("/" not in name and "\\" not in name and name not in ("", ".", ".."), "PATH_TRAVERSAL")


def _max_bytes(name: str) -> int:
    if name == PRIVATE_MAP_NAME or (m := STAGE_RE.fullmatch(name)) and m.group(2) == "map": return MAP_MAX_BYTES
    if name == COMMITMENT_NAME or (m := STAGE_RE.fullmatch(name)) and m.group(2) == "commitment": return COMMITMENT_MAX_BYTES
    if name == RECEIPT_NAME or (m := STAGE_RE.fullmatch(name)) and m.group(2) == "receipt": return RECEIPT_MAX_BYTES
    if name == LOCK_NAME or RELEASED_RE.fullmatch(name): return LOCK_MAX_BYTES
    return TRANSIENT_MAX_BYTES


def _read_name(name: str, *, transient: bool = False, expected_identity: Tuple[int, int] | None = None) -> Tuple[bytes, Tuple[int, int]]:
    _safe_name(name, transient=transient)
    root_fd, root_status = _open_root_fd(); fd = -1
    try:
        fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=root_fd)
        raw, status = _read_fd_bounded(fd, _max_bytes(name), "ARTIFACT")
        _require(status.st_uid == os.getuid() and stat.S_IMODE(status.st_mode) == 0o600, "ARTIFACT_OWNER_MODE")
        identity = _identity(status)
        if expected_identity is not None: _require(identity == expected_identity, "ARTIFACT_SUBSTITUTION")
        named = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        _require(_identity(named) == identity, "ARTIFACT_SUBSTITUTION")
        _require(_identity(os.fstat(root_fd)) == _identity(root_status), "ROOT_SUBSTITUTION")
        return raw, identity
    except CommitmentError: raise
    except OSError as exc: raise CommitmentError("ARTIFACT_OPEN_NOFOLLOW") from exc
    finally:
        if fd >= 0: os.close(fd)
        os.close(root_fd)


def _write_bound(name: str, builder: Callable[[Tuple[int, int]], Mapping[str, Any]], *, transient: bool = False) -> Tuple[bytes, Tuple[int, int], Dict[str, Any]]:
    _safe_name(name, transient=transient)
    root_fd, root_status = _open_root_fd(); fd = -1
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=root_fd)
        os.fchmod(fd, 0o600)
        status = os.fstat(fd); identity = _identity(status)
        value = dict(builder(identity)); raw = canonical_bytes(value)
        _require(0 < len(raw) <= _max_bytes(name), "ARTIFACT_SCHEMA_MAX_BYTES")
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:]); _require(written > 0, "ARTIFACT_ZERO_WRITE"); offset += written
        os.fsync(fd)
        after = os.fstat(fd)
        _require(_identity(after) == identity and after.st_size == len(raw), "ARTIFACT_WRITE_IDENTITY")
        os.fsync(root_fd)
        _require(_identity(os.fstat(root_fd)) == _identity(root_status), "ROOT_SUBSTITUTION")
    except CommitmentError: raise
    except FileExistsError as exc: raise CommitmentError("ARTIFACT_EXCLUSIVE_CONFLICT") from exc
    except OSError as exc: raise CommitmentError("ARTIFACT_WRITE") from exc
    finally:
        if fd >= 0: os.close(fd)
        os.close(root_fd)
    reopened, reopened_identity = _read_name(name, transient=transient, expected_identity=identity)
    _require(reopened == raw and hashlib.sha256(reopened).digest() == hashlib.sha256(raw).digest(), "ARTIFACT_REOPEN_HASH")
    return raw, reopened_identity, value


def _rename_exclusive(source: str, destination: str, *, source_transient: bool = False, destination_transient: bool = False) -> None:
    _safe_name(source, transient=source_transient); _safe_name(destination, transient=destination_transient)
    root_fd, root_status = _open_root_fd()
    try:
        function = getattr(ctypes.CDLL(None, use_errno=True), "renameatx_np", None)
        _require(function is not None, "ATOMIC_RENAME_UNAVAILABLE")
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        rc = function(root_fd, os.fsencode(source), root_fd, os.fsencode(destination), _RENAME_EXCL)
        if rc != 0:
            error = ctypes.get_errno()
            if error == errno.ENOENT: raise FileNotFoundError(source)
            if error == errno.EEXIST: raise FileExistsError(destination)
            raise OSError(error, os.strerror(error))
        os.fsync(root_fd)
        _require(_identity(os.fstat(root_fd)) == _identity(root_status), "ROOT_SUBSTITUTION")
    except (CommitmentError, FileNotFoundError, FileExistsError): raise
    except OSError as exc: raise CommitmentError("ATOMIC_RENAME_FAILED") from exc
    finally: os.close(root_fd)


def _publish_stage(stage: str, final: str, identity: Tuple[int, int]) -> None:
    try: _rename_exclusive(stage, final, source_transient=True)
    except FileExistsError as exc: raise CommitmentError("NAMESPACE_CONFLICT") from exc
    _read_name(final, expected_identity=identity)


def _quarantine_owned(name: str, transaction_id: str, expected_identity: Tuple[int, int], *, transient: bool = False) -> str:
    _require(TX_RE.fullmatch(transaction_id) is not None, "CLEANUP_TX")
    quarantine = f".quarantine-{transaction_id}-{secrets.token_hex(16)}-{name.lstrip('.')}"
    try: _rename_exclusive(name, quarantine, source_transient=transient, destination_transient=True)
    except FileNotFoundError as exc: raise CommitmentError("CLEANUP_OWNED_MISSING_FENCED") from exc
    try: _read_name(quarantine, transient=True, expected_identity=expected_identity)
    except CommitmentError as exc: raise CommitmentError("CLEANUP_IDENTITY_FENCED") from exc
    return quarantine


def _acquire_reservation(transaction_id: str, operation: str) -> Tuple[int, int]:
    _require(operation in ("CREATE", "RECOVER"), "LOCK_OPERATION")
    try:
        _, identity, value = _write_bound(LOCK_NAME, lambda own: {"version": 6, "schema": LOCK_SCHEMA_ID, "transaction_id": transaction_id, "artifact_identity": _identity_value(own), "operation": operation, "owner_pid": os.getpid(), "immutable": True})
    except CommitmentError as exc:
        if str(exc) == "ARTIFACT_EXCLUSIVE_CONFLICT": raise CommitmentError("TRANSACTION_LOCKED_NO_INSPECTION") from exc
        raise
    _validate_lock(value, identity)
    return identity


def _release_reservation(transaction_id: str, identity: Tuple[int, int]) -> str:
    released = f".released-{transaction_id}-{secrets.token_hex(16)}.json"
    try: _rename_exclusive(LOCK_NAME, released, destination_transient=True)
    except FileNotFoundError as exc: raise CommitmentError("LOCK_RELEASE_MISSING_FENCED") from exc
    raw, released_identity = _read_name(released, transient=True, expected_identity=identity)
    value = dict(_decode_canonical(raw, "LOCK")); _validate_lock(value, released_identity)
    _require(value["transaction_id"] == transaction_id, "LOCK_RELEASE_TX")
    return released


def _lock_present() -> bool:
    root_fd, _ = _open_root_fd()
    try:
        try: os.stat(LOCK_NAME, dir_fd=root_fd, follow_symlinks=False); return True
        except FileNotFoundError: return False
    finally: os.close(root_fd)


def _validate_lock(value: Mapping[str, Any], actual_identity: Tuple[int, int] | None = None) -> None:
    fields = {"version", "schema", "transaction_id", "artifact_identity", "operation", "owner_pid", "immutable"}
    _require(isinstance(value, Mapping) and set(value) == fields, "LOCK_FIELDS")
    _require(value["version"] == 6 and value["schema"] == LOCK_SCHEMA_ID, "LOCK_VERSION_SCHEMA")
    _require(isinstance(value["transaction_id"], str) and TX_RE.fullmatch(value["transaction_id"]), "LOCK_TX")
    if actual_identity is not None: _validate_identity(value["artifact_identity"], actual_identity, "LOCK_IDENTITY")
    _require(value["operation"] in ("CREATE", "RECOVER"), "LOCK_OPERATION")
    _require(isinstance(value["owner_pid"], int) and not isinstance(value["owner_pid"], bool) and value["owner_pid"] > 0, "LOCK_PID")
    _require(value["immutable"] is True, "LOCK_IMMUTABLE")


def _strict_ref(value: Mapping[str, Any], expected_path: str, code: str) -> None:
    _require(isinstance(value, Mapping) and set(value) == {"path", "bytes", "sha256", "mode"}, code + "_FIELDS")
    _require(value["path"] == expected_path and value["mode"] == "0600", code + "_PATH_MODE")
    _require(isinstance(value["bytes"], int) and value["bytes"] > 0, code + "_BYTES")
    _require(isinstance(value["sha256"], str) and SHA_RE.fullmatch(value["sha256"]) is not None, code + "_SHA")


def _decode_canonical(raw: bytes, code: str) -> Mapping[str, Any]:
    try: value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise CommitmentError(code + "_JSON") from exc
    _require(isinstance(value, Mapping) and canonical_bytes(value) == raw, code + "_NOT_CANONICAL")
    return value


def _identity_fields() -> Dict[str, str]:
    return {"design_identity": DESIGN_IDENTITY, "design_review_identity": DESIGN_REVIEW_IDENTITY, "evaluation_identity": EVALUATION_IDENTITY, "evaluation_producer_identity": EVALUATION_PRODUCER_IDENTITY, "evaluation_review_identity": EVALUATION_REVIEW_IDENTITY, "open_review_identity": OPEN_REVIEW_IDENTITY}


def _labels_leak_order(labels: Sequence[str]) -> bool:
    values = sorted(int(label, 16) for label in labels)
    return len(values) > 1 and all(b - a == 1 for a, b in zip(values, values[1:]))


def _validate_map(value: Mapping[str, Any], actual_identity: Tuple[int, int] | None = None) -> None:
    required = {"version", "schema", "transaction_id", "artifact_identity", *tuple(_identity_fields()), "cell_order", "labels"}
    _require(isinstance(value, Mapping) and set(value) == required, "MAP_FIELDS")
    _require(value["version"] == 6 and value["schema"] == MAP_SCHEMA_ID, "MAP_VERSION_SCHEMA")
    _require(isinstance(value["transaction_id"], str) and TX_RE.fullmatch(value["transaction_id"]), "MAP_TX")
    if actual_identity is not None: _validate_identity(value["artifact_identity"], actual_identity, "MAP_IDENTITY")
    for field, expected in _identity_fields().items(): _require(value[field] == expected, "MAP_SOURCE_IDENTITY")
    _require(value["cell_order"] == list(CELL_IDS), "MAP_CELL_ORDER")
    labels = value["labels"]
    _require(isinstance(labels, list) and len(labels) == 4, "MAP_LABEL_COUNT")
    _require(all(isinstance(label, str) and LABEL_RE.fullmatch(label) for label in labels), "MAP_LABEL_OPAQUE")
    _require(len(set(labels)) == 4 and not _labels_leak_order(labels), "MAP_LABEL_UNIQUE_OPAQUE")


def _validate_commitment(value: Mapping[str, Any], actual_identity: Tuple[int, int] | None = None) -> None:
    _require(isinstance(value, Mapping) and set(value) == {"version", "schema", "transaction_id", "artifact_identity", "canonical_digest", "canonical_bytes"}, "COMMITMENT_FIELDS")
    _require(value["version"] == 6 and value["schema"] == COMMITMENT_SCHEMA_ID, "COMMITMENT_VERSION_SCHEMA")
    _require(isinstance(value["transaction_id"], str) and TX_RE.fullmatch(value["transaction_id"]), "COMMITMENT_TX")
    if actual_identity is not None: _validate_identity(value["artifact_identity"], actual_identity, "COMMITMENT_IDENTITY")
    _require(isinstance(value["canonical_digest"], str) and SHA_RE.fullmatch(value["canonical_digest"]), "COMMITMENT_DIGEST")
    _require(isinstance(value["canonical_bytes"], int) and 0 < value["canonical_bytes"] <= MAP_MAX_BYTES, "COMMITMENT_BYTES")


def _validate_receipt(value: Mapping[str, Any], actual_identity: Tuple[int, int] | None = None) -> None:
    fields = {"version", "schema", "transaction_id", "artifact_identity", "map_ref", "map_identity", "commitment_ref", "commitment_identity", "complete"}
    _require(isinstance(value, Mapping) and set(value) == fields, "RECEIPT_FIELDS")
    _require(value["version"] == 6 and value["schema"] == RECEIPT_SCHEMA_ID and value["complete"] is True, "RECEIPT_VERSION_SCHEMA")
    _require(isinstance(value["transaction_id"], str) and TX_RE.fullmatch(value["transaction_id"]), "RECEIPT_TX")
    if actual_identity is not None: _validate_identity(value["artifact_identity"], actual_identity, "RECEIPT_IDENTITY")
    _strict_ref(value["map_ref"], PRIVATE_MAP_NAME, "RECEIPT_MAP_REF")
    _strict_ref(value["commitment_ref"], COMMITMENT_NAME, "RECEIPT_COMMITMENT_REF")
    for key in ("map_identity", "commitment_identity"):
        _require(isinstance(value[key], Mapping) and set(value[key]) == {"device", "inode"}, "RECEIPT_BOUND_IDENTITY")


def _generate_map(transaction_id: str, identity: Tuple[int, int]) -> Dict[str, Any]:
    for _ in range(128):
        labels = [secrets.token_hex(16) for _ in CELL_IDS]
        value = {"version": 6, "schema": MAP_SCHEMA_ID, "transaction_id": transaction_id, "artifact_identity": _identity_value(identity), **_identity_fields(), "cell_order": list(CELL_IDS), "labels": labels}
        try: _validate_map(value, identity); return value
        except CommitmentError: continue
    raise CommitmentError("LABEL_GENERATION_EXHAUSTED")


def _artifact_ref(path: str, raw: bytes) -> Dict[str, Any]:
    return {"path": path, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "mode": "0600"}


def _binding(receipt: Mapping[str, Any], receipt_raw: bytes, commitment: Mapping[str, Any]) -> Dict[str, Any]:
    return {"transaction_id": receipt["transaction_id"], "receipt_ref": _artifact_ref(RECEIPT_NAME, receipt_raw), "commitment_ref": dict(receipt["commitment_ref"]), "canonical_digest": commitment["canonical_digest"], "canonical_bytes": commitment["canonical_bytes"]}


def _read_complete_pair(read_map: bool, *, expected_binding: Mapping[str, Any] | None = None, allow_lock: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any] | None, Dict[str, Any]]:
    if not allow_lock and _lock_present(): raise CommitmentError("TRANSACTION_LOCKED_NO_PRIVATE_READ")
    receipt_raw, receipt_identity = _read_name(RECEIPT_NAME)
    receipt = dict(_decode_canonical(receipt_raw, "RECEIPT")); _validate_receipt(receipt, receipt_identity)
    commitment_raw, commitment_identity = _read_name(COMMITMENT_NAME)
    _require(_artifact_ref(COMMITMENT_NAME, commitment_raw) == receipt["commitment_ref"], "RECEIPT_COMMITMENT_BINDING")
    _validate_identity(receipt["commitment_identity"], commitment_identity, "RECEIPT_COMMITMENT_IDENTITY")
    commitment = dict(_decode_canonical(commitment_raw, "COMMITMENT")); _validate_commitment(commitment, commitment_identity)
    _require(commitment["transaction_id"] == receipt["transaction_id"], "COMMITMENT_TRANSACTION_BINDING")
    binding = _binding(receipt, receipt_raw, commitment)
    if expected_binding is not None: _require(binding == expected_binding, "EXPECTED_TRANSACTION_BINDING")
    map_value = None
    if read_map:
        map_raw, map_identity = _read_name(PRIVATE_MAP_NAME)
        _require(_artifact_ref(PRIVATE_MAP_NAME, map_raw) == receipt["map_ref"], "RECEIPT_MAP_BINDING")
        _validate_identity(receipt["map_identity"], map_identity, "RECEIPT_MAP_IDENTITY")
        _require(len(map_raw) == commitment["canonical_bytes"] and hashlib.sha256(map_raw).hexdigest() == commitment["canonical_digest"], "MAP_COMMITMENT_BINDING")
        map_value = dict(_decode_canonical(map_raw, "MAP")); _validate_map(map_value, map_identity)
        _require(map_value["transaction_id"] == receipt["transaction_id"], "MAP_TRANSACTION_BINDING")
        # Revalidate public names after private read; replacement cannot silently pass.
        _read_name(RECEIPT_NAME, expected_identity=receipt_identity)
        _read_name(COMMITMENT_NAME, expected_identity=commitment_identity)
    return receipt, commitment, map_value, binding


def _transaction_names() -> Sequence[str]:
    root_fd, _ = _open_root_fd()
    try: return tuple(os.listdir(root_fd))
    finally: os.close(root_fd)


def _cleanup_owned(owned: Mapping[str, Tuple[str, Tuple[int, int]]]) -> None:
    first_error = None
    for name, (transaction_id, identity) in reversed(tuple(owned.items())):
        try: _quarantine_owned(name, transaction_id, identity, transient=bool(STAGE_RE.fullmatch(name)))
        except CommitmentError as exc: first_error = first_error or exc
    if first_error is not None: raise CommitmentError("TRANSACTION_CLEANUP_FENCED") from first_error


def recover_incomplete() -> Dict[str, Any]:
    """Conservatively classify residue under an exclusive reservation; never delete it."""
    _ensure_root(); transaction_id = secrets.token_hex(16)
    lock_identity = _acquire_reservation(transaction_id, "RECOVER")
    result: Dict[str, Any]
    try:
        names = set(_transaction_names())
        fixed = names & {PRIVATE_MAP_NAME, COMMITMENT_NAME, RECEIPT_NAME}
        stages = {name for name in names if STAGE_RE.fullmatch(name)}
        if RECEIPT_NAME in fixed:
            try:
                _read_complete_pair(read_map=True, allow_lock=True)
                result = {"version": 6, "status": "COMPLETE", "recovered": 0, "fenced": False}
            except CommitmentError:
                result = {"version": 6, "status": "FENCED_INVALID", "recovered": 0, "fenced": True}
        elif fixed or stages:
            result = {"version": 6, "status": "FENCED_INCOMPLETE", "recovered": 0, "fenced": True}
        else:
            result = {"version": 6, "status": "CLEAN", "recovered": 0, "fenced": False}
    finally:
        _release_reservation(transaction_id, lock_identity)
    return result


def create_commitment() -> Dict[str, Any]:
    """Publish one self-bound map/commitment/receipt transaction with zero arguments."""
    _verify_pinned_sources(); _ensure_root(); transaction_id = secrets.token_hex(16)
    lock_identity = _acquire_reservation(transaction_id, "CREATE")
    owned: Dict[str, Tuple[str, Tuple[int, int]]] = {}
    succeeded = False
    try:
        names = set(_transaction_names())
        if names & {PRIVATE_MAP_NAME, COMMITMENT_NAME, RECEIPT_NAME} or any(STAGE_RE.fullmatch(name) for name in names):
            try:
                _read_complete_pair(False, allow_lock=True)
                raise CommitmentError("COMPLETE_TRANSACTION_EXISTS")
            except CommitmentError as exc:
                if str(exc) == "COMPLETE_TRANSACTION_EXISTS": raise
                raise CommitmentError("TRANSACTION_NAMESPACE_FENCED") from exc
        map_stage = f".stage-{transaction_id}-map.json"
        map_raw, map_identity, private_map = _write_bound(map_stage, lambda own: _generate_map(transaction_id, own), transient=True)
        owned[map_stage] = (transaction_id, map_identity)
        commitment_stage = f".stage-{transaction_id}-commitment.json"
        commitment_raw, commitment_identity, commitment = _write_bound(commitment_stage, lambda own: {"version": 6, "schema": COMMITMENT_SCHEMA_ID, "transaction_id": transaction_id, "artifact_identity": _identity_value(own), "canonical_digest": hashlib.sha256(map_raw).hexdigest(), "canonical_bytes": len(map_raw)}, transient=True)
        _validate_commitment(commitment, commitment_identity); owned[commitment_stage] = (transaction_id, commitment_identity)
        _publish_stage(map_stage, PRIVATE_MAP_NAME, map_identity); owned.pop(map_stage); owned[PRIVATE_MAP_NAME] = (transaction_id, map_identity)
        _publish_stage(commitment_stage, COMMITMENT_NAME, commitment_identity); owned.pop(commitment_stage); owned[COMMITMENT_NAME] = (transaction_id, commitment_identity)
        receipt_stage = f".stage-{transaction_id}-receipt.json"
        receipt_raw, receipt_identity, receipt = _write_bound(receipt_stage, lambda own: {"version": 6, "schema": RECEIPT_SCHEMA_ID, "transaction_id": transaction_id, "artifact_identity": _identity_value(own), "map_ref": _artifact_ref(PRIVATE_MAP_NAME, map_raw), "map_identity": _identity_value(map_identity), "commitment_ref": _artifact_ref(COMMITMENT_NAME, commitment_raw), "commitment_identity": _identity_value(commitment_identity), "complete": True}, transient=True)
        _validate_receipt(receipt, receipt_identity); owned[receipt_stage] = (transaction_id, receipt_identity)
        _publish_stage(receipt_stage, RECEIPT_NAME, receipt_identity); owned.pop(receipt_stage); owned[RECEIPT_NAME] = (transaction_id, receipt_identity)
        _read_complete_pair(read_map=True, expected_binding=_binding(receipt, receipt_raw, commitment), allow_lock=True)
        succeeded = True
        return dict(commitment)
    except BaseException as exc:
        try: _cleanup_owned(owned)
        except CommitmentError as cleanup_exc: raise CommitmentError("TRANSACTION_FAILED_CLEANUP_FENCED") from cleanup_exc
        if isinstance(exc, CommitmentError): raise
        raise CommitmentError("TRANSACTION_FAILED") from exc
    finally:
        try: _release_reservation(transaction_id, lock_identity)
        except CommitmentError:
            if succeeded: raise


def validate_commitment() -> Dict[str, Any]:
    _verify_pinned_sources()
    _, commitment, _, _ = _read_complete_pair(read_map=True)
    return commitment
