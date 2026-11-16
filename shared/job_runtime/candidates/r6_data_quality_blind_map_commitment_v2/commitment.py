"""R6 DQ blind-map commitment successor v2.

Disabled and provider-free.  Publishes a marker-bound private-map/commitment pair
transactionally, binds pre-call packets, grades, and metrics to that exact pair,
and denies opening unless externally pinned live human authority is present.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple


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


def seal(body: Mapping[str, Any]) -> Dict[str, Any]:
    result = dict(body)
    result["artifact_sha256"] = sha256_json(body)
    result["artifact_bytes"] = len(canonical_bytes(body))
    return result


def verify_seal(value: Mapping[str, Any], code: str) -> None:
    _require(isinstance(value, Mapping), code + "_TYPE")
    body = {key: item for key, item in value.items() if key not in ("artifact_sha256", "artifact_bytes")}
    _require(value.get("immutable") is True, code + "_IMMUTABLE")
    _require(value.get("artifact_sha256") == sha256_json(body), code + "_HASH")
    _require(value.get("artifact_bytes") == len(canonical_bytes(body)), code + "_BYTES")


WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
RUNTIME_RELATIVE_ROOT = Path("runtime/r6_data_quality_blind_map_commitment_v2")
PRIVATE_MAP_NAME = "owner-private-canonical-map-v2.json"
COMMITMENT_NAME = "sanitized-commitment-v2.json"
RECEIPT_NAME = "transaction-receipt-v2.json"
MAP_SCHEMA_ID = "r6-data-quality-blind-map-v2"
COMMITMENT_SCHEMA_ID = "r6-data-quality-blind-map-commitment-v2"
RECEIPT_SCHEMA_ID = "r6-data-quality-blind-map-transaction-v2"
PACKET_SCHEMA_ID = "r6-data-quality-blind-map-pre-call-packet-v2"
GRADE_BINDING_SCHEMA_ID = "r6-data-quality-blind-map-grade-binding-v2"
METRIC_BINDING_SCHEMA_ID = "r6-data-quality-blind-map-metric-binding-v2"
CELL_IDS = ("R6DQ-7F2C91A4", "R6DQ-1B8E43D7", "R6DQ-C4A7095E", "R6DQ-92D6F0B3")
LABEL_RE = re.compile(r"[0-9a-f]{32}\Z")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
TX_RE = re.compile(r"[0-9a-f]{32}\Z")
STAGE_RE = re.compile(r"\.stage-[0-9a-f]{32}-(?:map|commitment)\.json\Z")
QUARANTINE_RE = re.compile(r"\.quarantine-[0-9a-f]{32}-.+\Z")

DESIGN_IDENTITY = "fcf096d0c641f373eab7163fa894e5d4f9605ab3ab36ff867e4b586bdcaf278e"
DESIGN_REVIEW_IDENTITY = "0018e413e40371bb2703aecf3963433f1a883a93b1070e815dccc0dc61866d3f"
EVALUATION_IDENTITY = "8bef52f4f1c7511ec8897b17dbee2f542b0a822acaf22ebbe2e0e267d7c6714d"
EVALUATION_PRODUCER_IDENTITY = "2df4cae89b8942a8eb38b766608381f4bc41aeb8f4c984a9d32aa677068718ea"
EVALUATION_REVIEW_IDENTITY = "da36e2ae03c7a74ef7b5dce91eb7fc7e627b3cb431a0064c6efde37ef744b429"
OPEN_REVIEW_IDENTITY = "df607b44d873590be8d402eba0f95e0265c4cdf4f7a12f85b0e3d484c34802f5"
EVALUATION_HARNESS_IDENTITY = "a42f1d0303857f443b5352ed7cfd244551767d347168e3ada6b7f8042cdaa7e4"

PINNED_SOURCES = (
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-addon-2x2-ab-design.json", 26277, DESIGN_IDENTITY),
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-addon-2x2-ab-design-independent-review.json", 18741, DESIGN_REVIEW_IDENTITY),
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-evaluation-contract-v3.json", 9944, EVALUATION_IDENTITY),
    ("tuning/architecture/r6_data_quality_2x2_evaluation_v3/producer-verification-v3.json", 2588, EVALUATION_PRODUCER_IDENTITY),
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-evaluation-v3-independent-review.json", 10585, EVALUATION_REVIEW_IDENTITY),
    ("shared/job_runtime/candidates/r6_data_quality_2x2_evaluation_v3/harness.py", 31895, EVALUATION_HARNESS_IDENTITY),
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/claude-r6-data-quality-blind-map-commitment-v1-independent-review-open-v1.json", 7019, OPEN_REVIEW_IDENTITY),
)


def _root_path() -> Path:
    root = WORKSPACE_ROOT / RUNTIME_RELATIVE_ROOT
    _require(root.is_absolute(), "ROOT_NOT_ABSOLUTE")
    return root


def _verify_pinned_sources() -> None:
    for relative, expected_bytes, expected_sha in PINNED_SOURCES:
        try:
            raw = (WORKSPACE_ROOT / relative).read_bytes()
        except OSError as exc:
            raise CommitmentError("PINNED_SOURCE_MISSING") from exc
        _require(len(raw) == expected_bytes, "PINNED_SOURCE_BYTES")
        _require(hashlib.sha256(raw).hexdigest() == expected_sha, "PINNED_SOURCE_DIGEST")


def _validate_root() -> os.stat_result:
    try:
        status = os.lstat(_root_path())
    except OSError as exc:
        raise CommitmentError("ROOT_MISSING") from exc
    _require(not stat.S_ISLNK(status.st_mode), "ROOT_SYMLINK")
    _require(stat.S_ISDIR(status.st_mode), "ROOT_NOT_DIRECTORY")
    _require(status.st_uid == os.getuid(), "ROOT_OWNER")
    _require(stat.S_IMODE(status.st_mode) == 0o700, "ROOT_MODE")
    return status


def _fsync_file(fd: int, boundary: str) -> None:
    del boundary
    os.fsync(fd)


def _fsync_dir(fd: int, boundary: str) -> None:
    del boundary
    os.fsync(fd)


def _ensure_root() -> None:
    root = _root_path()
    parent = root.parent
    try:
        parent_status = os.lstat(parent)
    except OSError as exc:
        raise CommitmentError("ROOT_PARENT_MISSING") from exc
    _require(not stat.S_ISLNK(parent_status.st_mode) and stat.S_ISDIR(parent_status.st_mode), "ROOT_PARENT_INVALID")
    _require(parent_status.st_uid == os.getuid(), "ROOT_PARENT_OWNER")
    try:
        os.mkdir(root, 0o700)
        os.chmod(root, 0o700, follow_symlinks=False)
        parent_fd = os.open(str(parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            _fsync_dir(parent_fd, "root_parent_create")
        finally:
            os.close(parent_fd)
    except FileExistsError:
        pass
    except OSError as exc:
        raise CommitmentError("ROOT_CREATE") from exc
    _validate_root()


def _open_root_fd() -> Tuple[int, os.stat_result]:
    expected = _validate_root()
    try:
        fd = os.open(str(_root_path()), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise CommitmentError("ROOT_OPEN_NOFOLLOW") from exc
    actual = os.fstat(fd)
    if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
        os.close(fd)
        raise CommitmentError("ROOT_SUBSTITUTION")
    return fd, actual


def _safe_name(name: str, allow_stage: bool = False, allow_quarantine: bool = False) -> None:
    fixed = name in (PRIVATE_MAP_NAME, COMMITMENT_NAME, RECEIPT_NAME)
    staged = allow_stage and STAGE_RE.fullmatch(name) is not None
    quarantined = allow_quarantine and QUARANTINE_RE.fullmatch(name) is not None
    _require(isinstance(name, str) and (fixed or staged or quarantined), "PATH_NOT_FIXED")
    _require("/" not in name and "\\" not in name and name not in ("", ".", ".."), "PATH_TRAVERSAL")


def _read_name(name: str, allow_stage: bool = False, expected_identity: Tuple[int, int] | None = None) -> Tuple[bytes, Tuple[int, int]]:
    _safe_name(name, allow_stage=allow_stage)
    root_fd, root_status = _open_root_fd()
    fd = -1
    try:
        fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=root_fd)
        status = os.fstat(fd)
        _require(stat.S_ISREG(status.st_mode), "ARTIFACT_NOT_REGULAR")
        _require(status.st_uid == os.getuid(), "ARTIFACT_OWNER")
        _require(stat.S_IMODE(status.st_mode) == 0o600, "ARTIFACT_MODE")
        identity = (status.st_dev, status.st_ino)
        if expected_identity is not None:
            _require(identity == expected_identity, "ARTIFACT_SUBSTITUTION")
        parts = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            parts.append(chunk)
        path_status = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        _require((path_status.st_dev, path_status.st_ino) == identity, "ARTIFACT_SUBSTITUTION")
        current_root = os.fstat(root_fd)
        _require((current_root.st_dev, current_root.st_ino) == (root_status.st_dev, root_status.st_ino), "ROOT_SUBSTITUTION")
        return b"".join(parts), identity
    except CommitmentError:
        raise
    except OSError as exc:
        raise CommitmentError("ARTIFACT_OPEN_NOFOLLOW") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(root_fd)


def _write_stage(name: str, raw: bytes, boundary: str) -> Tuple[int, int]:
    _safe_name(name, allow_stage=True)
    root_fd, root_status = _open_root_fd()
    fd = -1
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=root_fd)
        os.fchmod(fd, 0o600)
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            _require(written > 0, "ARTIFACT_ZERO_WRITE")
            offset += written
        _fsync_file(fd, boundary + "_file")
        status = os.fstat(fd)
        _require(stat.S_ISREG(status.st_mode) and status.st_uid == os.getuid(), "ARTIFACT_OWNER_TYPE")
        _require(stat.S_IMODE(status.st_mode) == 0o600, "ARTIFACT_MODE")
        identity = (status.st_dev, status.st_ino)
        os.close(fd)
        fd = -1
        _fsync_dir(root_fd, boundary + "_stage_dir")
        current_root = os.fstat(root_fd)
        _require((current_root.st_dev, current_root.st_ino) == (root_status.st_dev, root_status.st_ino), "ROOT_SUBSTITUTION")
    except CommitmentError:
        raise
    except FileExistsError as exc:
        raise CommitmentError("ARTIFACT_STAGE_CONFLICT") from exc
    except OSError as exc:
        raise CommitmentError("ARTIFACT_STAGE_WRITE") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(root_fd)
    reopened, reopened_identity = _read_name(name, allow_stage=True, expected_identity=identity)
    _require(reopened == raw, "ARTIFACT_STAGE_REOPEN_BYTES")
    _require(hashlib.sha256(reopened).digest() == hashlib.sha256(raw).digest(), "ARTIFACT_STAGE_REOPEN_HASH")
    return reopened_identity


def _write_receipt(raw: bytes) -> Tuple[int, int]:
    root_fd, root_status = _open_root_fd()
    fd = -1
    try:
        fd = os.open(RECEIPT_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=root_fd)
        os.fchmod(fd, 0o600)
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            _require(written > 0, "RECEIPT_ZERO_WRITE")
            offset += written
        _fsync_file(fd, "receipt_file")
        status = os.fstat(fd)
        identity = (status.st_dev, status.st_ino)
        _require(stat.S_ISREG(status.st_mode) and status.st_uid == os.getuid() and stat.S_IMODE(status.st_mode) == 0o600, "RECEIPT_OWNER_MODE")
        os.close(fd)
        fd = -1
        _fsync_dir(root_fd, "receipt_commit_dir")
        current_root = os.fstat(root_fd)
        _require((current_root.st_dev, current_root.st_ino) == (root_status.st_dev, root_status.st_ino), "ROOT_SUBSTITUTION")
    except CommitmentError:
        raise
    except FileExistsError as exc:
        raise CommitmentError("RECEIPT_CONFLICT") from exc
    except OSError as exc:
        raise CommitmentError("RECEIPT_WRITE") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(root_fd)
    reopened, reopened_identity = _read_name(RECEIPT_NAME, expected_identity=identity)
    _require(reopened == raw, "RECEIPT_REOPEN_BYTES")
    _require(hashlib.sha256(reopened).digest() == hashlib.sha256(raw).digest(), "RECEIPT_REOPEN_HASH")
    return reopened_identity


def _link_stage(stage_name: str, final_name: str, identity: Tuple[int, int], boundary: str) -> None:
    _safe_name(stage_name, allow_stage=True)
    _safe_name(final_name)
    root_fd, _ = _open_root_fd()
    try:
        os.link(stage_name, final_name, src_dir_fd=root_fd, dst_dir_fd=root_fd, follow_symlinks=False)
        _fsync_dir(root_fd, boundary + "_dir")
    except FileExistsError as exc:
        raise CommitmentError("NAMESPACE_CONFLICT") from exc
    except OSError as exc:
        raise CommitmentError("NAMESPACE_COMMIT") from exc
    finally:
        os.close(root_fd)
    _read_name(final_name, expected_identity=identity)


def _name_identity(name: str) -> Tuple[int, int] | None:
    root_fd, _ = _open_root_fd()
    try:
        status = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        return status.st_dev, status.st_ino
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CommitmentError("ARTIFACT_LSTAT") from exc
    finally:
        os.close(root_fd)


def _quarantine_or_remove(name: str, expected_identity: Tuple[int, int] | None = None) -> bool:
    _safe_name(name, allow_stage=True)
    root_fd, _ = _open_root_fd()
    try:
        try:
            status = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        identity = (status.st_dev, status.st_ino)
        if expected_identity is not None and identity != expected_identity:
            return False
        try:
            if stat.S_ISDIR(status.st_mode) and not stat.S_ISLNK(status.st_mode):
                os.rmdir(name, dir_fd=root_fd)
            else:
                os.unlink(name, dir_fd=root_fd)
        except OSError:
            quarantine = ".quarantine-" + secrets.token_hex(16) + "-" + name.lstrip(".")
            _safe_name(quarantine, allow_quarantine=True)
            os.rename(name, quarantine, src_dir_fd=root_fd, dst_dir_fd=root_fd)
        _fsync_dir(root_fd, "cleanup_dir")
        return True
    except CommitmentError:
        raise
    except OSError as exc:
        raise CommitmentError("CLEANUP_FAILURE") from exc
    finally:
        os.close(root_fd)


def _list_transaction_names() -> Sequence[str]:
    root_fd, _ = _open_root_fd()
    try:
        return tuple(os.listdir(root_fd))
    finally:
        os.close(root_fd)


def _strict_ref(value: Mapping[str, Any], expected_path: str, code: str) -> None:
    _require(isinstance(value, Mapping) and set(value) == {"path", "bytes", "sha256"}, code + "_FIELDS")
    _require(value["path"] == expected_path, code + "_PATH")
    _require(isinstance(value["bytes"], int) and value["bytes"] > 0, code + "_BYTES")
    _require(isinstance(value["sha256"], str) and SHA_RE.fullmatch(value["sha256"]) is not None, code + "_SHA")


def _decode_canonical(raw: bytes, code: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CommitmentError(code + "_JSON") from exc
    _require(isinstance(value, Mapping), code + "_TYPE")
    _require(canonical_bytes(value) == raw, code + "_NOT_CANONICAL")
    return value


def _identity_fields() -> Dict[str, str]:
    return {
        "design_identity": DESIGN_IDENTITY,
        "design_review_identity": DESIGN_REVIEW_IDENTITY,
        "evaluation_identity": EVALUATION_IDENTITY,
        "evaluation_producer_identity": EVALUATION_PRODUCER_IDENTITY,
        "evaluation_review_identity": EVALUATION_REVIEW_IDENTITY,
        "open_review_identity": OPEN_REVIEW_IDENTITY,
    }


def _labels_leak_order(labels: Sequence[str], cells: Sequence[str]) -> bool:
    values = sorted(int(label, 16) for label in labels)
    sequential = len(values) > 1 and all(b - a == 1 for a, b in zip(values, values[1:]))
    return sequential or tuple(cells) in (CELL_IDS, tuple(reversed(CELL_IDS)))


def _validate_map(value: Mapping[str, Any]) -> None:
    required = {"version", "schema", *tuple(_identity_fields()), "cells"}
    _require(isinstance(value, Mapping) and set(value) == required, "MAP_FIELDS")
    _require(value["version"] == 2 and value["schema"] == MAP_SCHEMA_ID, "MAP_VERSION_SCHEMA")
    for field, expected in _identity_fields().items():
        _require(value[field] == expected, "MAP_IDENTITY")
    cells = value["cells"]
    _require(isinstance(cells, list) and len(cells) == 4, "MAP_CELL_COUNT")
    labels = []
    cell_ids = []
    for item in cells:
        _require(isinstance(item, Mapping) and set(item) == {"label", "cell_id"}, "MAP_CELL_FIELDS")
        _require(isinstance(item["label"], str) and LABEL_RE.fullmatch(item["label"]) is not None, "MAP_LABEL_OPAQUE")
        _require(item["cell_id"] in CELL_IDS, "MAP_CELL_ID")
        labels.append(item["label"])
        cell_ids.append(item["cell_id"])
    _require(len(set(labels)) == 4, "MAP_LABEL_DUPLICATE")
    _require(set(cell_ids) == set(CELL_IDS) and len(set(cell_ids)) == 4, "MAP_CELL_DUPLICATE")
    _require(labels == sorted(labels), "MAP_CANONICAL_ORDER")
    _require(not _labels_leak_order(labels, cell_ids), "MAP_ORDER_LEAKAGE")


def _validate_commitment(value: Mapping[str, Any]) -> None:
    _require(isinstance(value, Mapping) and set(value) == {"version", "schema", "canonical_digest", "canonical_bytes"}, "COMMITMENT_FIELDS")
    _require(value["version"] == 2 and value["schema"] == MAP_SCHEMA_ID, "COMMITMENT_VERSION_SCHEMA")
    _require(isinstance(value["canonical_digest"], str) and SHA_RE.fullmatch(value["canonical_digest"]) is not None, "COMMITMENT_DIGEST")
    _require(isinstance(value["canonical_bytes"], int) and value["canonical_bytes"] > 0, "COMMITMENT_BYTES")


def _validate_receipt(value: Mapping[str, Any]) -> None:
    _require(isinstance(value, Mapping) and set(value) == {"version", "schema", "transaction_id", "map_ref", "commitment_ref", "complete"}, "RECEIPT_FIELDS")
    _require(value["version"] == 2 and value["schema"] == RECEIPT_SCHEMA_ID and value["complete"] is True, "RECEIPT_VERSION_SCHEMA")
    _require(isinstance(value["transaction_id"], str) and TX_RE.fullmatch(value["transaction_id"]) is not None, "RECEIPT_TX")
    _strict_ref(value["map_ref"], PRIVATE_MAP_NAME, "RECEIPT_MAP_REF")
    _strict_ref(value["commitment_ref"], COMMITMENT_NAME, "RECEIPT_COMMITMENT_REF")


def _generate_map() -> Dict[str, Any]:
    for _ in range(128):
        pairs = [(secrets.token_hex(16), cell) for cell in CELL_IDS]
        if len({label for label, _ in pairs}) != 4:
            continue
        pairs.sort()
        if _labels_leak_order([x[0] for x in pairs], [x[1] for x in pairs]):
            continue
        value = {"version": 2, "schema": MAP_SCHEMA_ID, **_identity_fields(), "cells": [{"label": label, "cell_id": cell} for label, cell in pairs]}
        _validate_map(value)
        return value
    raise CommitmentError("LABEL_GENERATION_EXHAUSTED")


def _artifact_ref(path: str, raw: bytes) -> Dict[str, Any]:
    return {"path": path, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _read_complete_pair(read_map: bool) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any] | None, Dict[str, Any]]:
    receipt_raw, _ = _read_name(RECEIPT_NAME)
    receipt = dict(_decode_canonical(receipt_raw, "RECEIPT"))
    _validate_receipt(receipt)
    commitment_raw, _ = _read_name(COMMITMENT_NAME)
    _require(_artifact_ref(COMMITMENT_NAME, commitment_raw) == receipt["commitment_ref"], "RECEIPT_COMMITMENT_BINDING")
    commitment = dict(_decode_canonical(commitment_raw, "COMMITMENT"))
    _validate_commitment(commitment)
    map_value = None
    if read_map:
        map_raw, _ = _read_name(PRIVATE_MAP_NAME)
        _require(_artifact_ref(PRIVATE_MAP_NAME, map_raw) == receipt["map_ref"], "RECEIPT_MAP_BINDING")
        _require(len(map_raw) == commitment["canonical_bytes"], "MAP_COMMITTED_BYTES")
        _require(hashlib.sha256(map_raw).hexdigest() == commitment["canonical_digest"], "MAP_COMMITTED_DIGEST")
        map_value = dict(_decode_canonical(map_raw, "MAP"))
        _validate_map(map_value)
    binding = {
        "transaction_id": receipt["transaction_id"],
        "receipt_ref": _artifact_ref(RECEIPT_NAME, receipt_raw),
        "commitment_ref": dict(receipt["commitment_ref"]),
        "canonical_digest": commitment["canonical_digest"],
        "canonical_bytes": commitment["canonical_bytes"],
    }
    return receipt, commitment, map_value, binding


def _cleanup_incomplete(names: Sequence[str]) -> int:
    cleaned = 0
    recognized = [name for name in names if name in (PRIVATE_MAP_NAME, COMMITMENT_NAME, RECEIPT_NAME) or STAGE_RE.fullmatch(name)]
    for name in recognized:
        if _quarantine_or_remove(name):
            cleaned += 1
    return cleaned


def recover_incomplete() -> Dict[str, Any]:
    """Remove/quarantine markerless or invalid transaction residue; accept no inputs."""
    _ensure_root()
    names = _list_transaction_names()
    if RECEIPT_NAME in names:
        try:
            _read_complete_pair(read_map=True)
            return {"version": 2, "status": "COMPLETE", "recovered": 0}
        except CommitmentError:
            cleaned = _cleanup_incomplete(names)
            return {"version": 2, "status": "RECOVERED_INVALID", "recovered": cleaned}
    transaction_names = [name for name in names if name in (PRIVATE_MAP_NAME, COMMITMENT_NAME) or STAGE_RE.fullmatch(name)]
    if transaction_names:
        cleaned = _cleanup_incomplete(transaction_names)
        return {"version": 2, "status": "RECOVERED_INCOMPLETE", "recovered": cleaned}
    return {"version": 2, "status": "CLEAN", "recovered": 0}


def _cleanup_owned(owned: Mapping[str, Tuple[int, int]]) -> None:
    first_error = None
    for name, identity in tuple(owned.items()):
        try:
            _quarantine_or_remove(name, identity)
        except CommitmentError as exc:
            first_error = first_error or exc
    try:
        _cleanup_incomplete(_list_transaction_names())
    except CommitmentError as exc:
        first_error = first_error or exc
    if first_error is not None:
        raise CommitmentError("TRANSACTION_CLEANUP_INCOMPLETE") from first_error


def create_commitment() -> Dict[str, Any]:
    """Publish map+commitment as a receipt-bound no-replace transaction."""
    _verify_pinned_sources()
    recovery = recover_incomplete()
    if recovery["status"] == "COMPLETE":
        raise CommitmentError("COMPLETE_TRANSACTION_EXISTS")
    if recovery["status"].startswith("RECOVERED"):
        raise CommitmentError("TRANSACTION_RECOVERED_RETRY")
    transaction_id = secrets.token_hex(16)
    map_stage = f".stage-{transaction_id}-map.json"
    commitment_stage = f".stage-{transaction_id}-commitment.json"
    private_map = _generate_map()
    map_raw = canonical_bytes(private_map)
    commitment = {"version": 2, "schema": MAP_SCHEMA_ID, "canonical_digest": hashlib.sha256(map_raw).hexdigest(), "canonical_bytes": len(map_raw)}
    _validate_commitment(commitment)
    commitment_raw = canonical_bytes(commitment)
    owned: Dict[str, Tuple[int, int]] = {}
    try:
        map_identity = _write_stage(map_stage, map_raw, "map_stage")
        owned[map_stage] = map_identity
        commitment_identity = _write_stage(commitment_stage, commitment_raw, "commitment_stage")
        owned[commitment_stage] = commitment_identity
        _link_stage(map_stage, PRIVATE_MAP_NAME, map_identity, "map_namespace")
        owned[PRIVATE_MAP_NAME] = map_identity
        _link_stage(commitment_stage, COMMITMENT_NAME, commitment_identity, "commitment_namespace")
        owned[COMMITMENT_NAME] = commitment_identity
        final_map, _ = _read_name(PRIVATE_MAP_NAME, expected_identity=map_identity)
        final_commitment, _ = _read_name(COMMITMENT_NAME, expected_identity=commitment_identity)
        _require(final_map == map_raw and final_commitment == commitment_raw, "FINAL_PAIR_READBACK")
        receipt = {"version": 2, "schema": RECEIPT_SCHEMA_ID, "transaction_id": transaction_id, "map_ref": _artifact_ref(PRIVATE_MAP_NAME, map_raw), "commitment_ref": _artifact_ref(COMMITMENT_NAME, commitment_raw), "complete": True}
        _validate_receipt(receipt)
        receipt_raw = canonical_bytes(receipt)
        receipt_identity = _write_receipt(receipt_raw)
        owned[RECEIPT_NAME] = receipt_identity
        _read_complete_pair(read_map=True)
        _quarantine_or_remove(map_stage, map_identity)
        owned.pop(map_stage, None)
        _quarantine_or_remove(commitment_stage, commitment_identity)
        owned.pop(commitment_stage, None)
        return dict(commitment)
    except BaseException as exc:
        try:
            _cleanup_owned(owned)
        except CommitmentError as cleanup_exc:
            raise CommitmentError("TRANSACTION_FAILED_CLEANUP_PENDING") from cleanup_exc
        if isinstance(exc, CommitmentError):
            raise
        raise CommitmentError("TRANSACTION_FAILED") from exc


def validate_commitment() -> Dict[str, Any]:
    _verify_pinned_sources()
    _, commitment, _, _ = _read_complete_pair(read_map=True)
    return commitment


def _validate_binding(binding: Mapping[str, Any]) -> None:
    required = {"transaction_id", "receipt_ref", "commitment_ref", "canonical_digest", "canonical_bytes"}
    _require(isinstance(binding, Mapping) and set(binding) == required, "BINDING_FIELDS")
    _require(isinstance(binding["transaction_id"], str) and TX_RE.fullmatch(binding["transaction_id"]) is not None, "BINDING_TX")
    _strict_ref(binding["receipt_ref"], RECEIPT_NAME, "BINDING_RECEIPT_REF")
    _strict_ref(binding["commitment_ref"], COMMITMENT_NAME, "BINDING_COMMITMENT_REF")
    _require(isinstance(binding["canonical_digest"], str) and SHA_RE.fullmatch(binding["canonical_digest"]) is not None, "BINDING_DIGEST")
    _require(isinstance(binding["canonical_bytes"], int) and binding["canonical_bytes"] > 0, "BINDING_BYTES")


def _validate_packet(packet: Mapping[str, Any]) -> None:
    fields = {"version", "schema", "cell_id", "blind_alias", "commitment_binding", "phase", "pre_call", "immutable", "artifact_sha256", "artifact_bytes"}
    _require(isinstance(packet, Mapping) and set(packet) == fields, "PACKET_FIELDS")
    verify_seal(packet, "PACKET")
    _require(packet["version"] == 2 and packet["schema"] == PACKET_SCHEMA_ID, "PACKET_VERSION_SCHEMA")
    _require(packet["cell_id"] in CELL_IDS, "PACKET_CELL")
    _require(isinstance(packet["blind_alias"], str) and LABEL_RE.fullmatch(packet["blind_alias"]) is not None, "PACKET_ALIAS")
    _require(packet["phase"] == "PRE_CALL" and packet["pre_call"] is True, "PACKET_PHASE")
    _validate_binding(packet["commitment_binding"])


def build_pre_call_packets() -> Dict[str, Dict[str, Any]]:
    """Build exact packet bindings from the complete transaction before calls."""
    _verify_pinned_sources()
    _, _, private_map, binding = _read_complete_pair(read_map=True)
    assert private_map is not None
    aliases = {item["cell_id"]: item["label"] for item in private_map["cells"]}
    result = {}
    for cell_id in CELL_IDS:
        body = {"version": 2, "schema": PACKET_SCHEMA_ID, "cell_id": cell_id, "blind_alias": aliases[cell_id], "commitment_binding": dict(binding), "phase": "PRE_CALL", "pre_call": True, "immutable": True}
        result[cell_id] = seal(body)
        _validate_packet(result[cell_id])
    return result


def _evaluation_harness():
    _verify_pinned_sources()
    harness = importlib.import_module("shared.job_runtime.candidates.r6_data_quality_2x2_evaluation_v3.harness")
    _require(tuple(harness.CELL_ORDER) == CELL_IDS, "EVALUATION_CELL_DRIFT")
    return harness


def build_grade_binding(pre_call_packet: Mapping[str, Any], evaluation_packet: Mapping[str, Any], grade: Mapping[str, Any]) -> Dict[str, Any]:
    _validate_packet(pre_call_packet)
    harness = _evaluation_harness()
    harness.verify_seal(evaluation_packet, "EVALUATION_PACKET")
    harness.verify_seal(grade, "BASE_GRADE")
    body = {
        "version": 2,
        "schema": GRADE_BINDING_SCHEMA_ID,
        "cell_id": pre_call_packet["cell_id"],
        "blind_alias": pre_call_packet["blind_alias"],
        "commitment_binding": dict(pre_call_packet["commitment_binding"]),
        "pre_call_packet_sha256": pre_call_packet["artifact_sha256"],
        "evaluation_packet_sha256": evaluation_packet["artifact_sha256"],
        "base_grade_sha256": grade["artifact_sha256"],
        "grader_role": grade["grader_role"],
        "immutable": True,
    }
    result = seal(body)
    _validate_grade_binding(result)
    return result


def _validate_grade_binding(value: Mapping[str, Any]) -> None:
    fields = {"version", "schema", "cell_id", "blind_alias", "commitment_binding", "pre_call_packet_sha256", "evaluation_packet_sha256", "base_grade_sha256", "grader_role", "immutable", "artifact_sha256", "artifact_bytes"}
    _require(isinstance(value, Mapping) and set(value) == fields, "GRADE_BINDING_FIELDS")
    verify_seal(value, "GRADE_BINDING")
    _require(value["version"] == 2 and value["schema"] == GRADE_BINDING_SCHEMA_ID, "GRADE_BINDING_VERSION_SCHEMA")
    _require(value["cell_id"] in CELL_IDS and isinstance(value["blind_alias"], str) and LABEL_RE.fullmatch(value["blind_alias"]) is not None, "GRADE_BINDING_ID")
    _validate_binding(value["commitment_binding"])
    for field in ("pre_call_packet_sha256", "evaluation_packet_sha256", "base_grade_sha256"):
        _require(isinstance(value[field], str) and SHA_RE.fullmatch(value[field]) is not None, "GRADE_BINDING_SHA")
    _require(value["grader_role"] in ("G1", "G2", "G3"), "GRADE_BINDING_ROLE")


def _evaluate_bound(pre_packets, evaluation_packets, grades, grade_bindings, authority, expected_binding):
    harness = _evaluation_harness()
    _require(tuple(pre_packets) == CELL_IDS and tuple(evaluation_packets) == CELL_IDS and tuple(grades) == CELL_IDS and tuple(grade_bindings) == CELL_IDS, "BOUND_FOUR_CELL_ORDER")
    evaluations = {}
    evidence = {}
    aliases = []
    packet_hashes = []
    grade_hashes = []
    for cell_id in CELL_IDS:
        packet = pre_packets[cell_id]
        _validate_packet(packet)
        _require(packet["cell_id"] == cell_id, "BOUND_PACKET_CELL")
        _require(packet["commitment_binding"] == expected_binding, "BOUND_PACKET_COMMITMENT")
        _require(packet["blind_alias"] not in aliases, "BOUND_ALIAS_DUPLICATE")
        aliases.append(packet["blind_alias"])
        packet_hashes.append(packet["artifact_sha256"])
        evaluation_packet = evaluation_packets[cell_id]
        harness.validate_packet_runtime(authority.store, evaluation_packet)
        _require(evaluation_packet["blind_alias"] == harness.ALIASES[cell_id], "BOUND_EVALUATION_CELL")
        base_grades = grades[cell_id]
        bindings = grade_bindings[cell_id]
        _require(isinstance(base_grades, Sequence) and isinstance(bindings, Sequence) and len(base_grades) == len(bindings), "BOUND_GRADE_COUNT")
        cell_grade_hashes = []
        for base_grade, binding in zip(base_grades, bindings):
            _validate_grade_binding(binding)
            _require(binding["cell_id"] == cell_id and binding["blind_alias"] == packet["blind_alias"], "BOUND_GRADE_ALIAS")
            _require(binding["commitment_binding"] == expected_binding, "BOUND_GRADE_COMMITMENT")
            _require(binding["pre_call_packet_sha256"] == packet["artifact_sha256"], "BOUND_GRADE_PACKET")
            _require(binding["evaluation_packet_sha256"] == evaluation_packet["artifact_sha256"], "BOUND_GRADE_EVALUATION")
            _require(binding["base_grade_sha256"] == base_grade["artifact_sha256"] and binding["grader_role"] == base_grade["grader_role"], "BOUND_GRADE_BASE")
            cell_grade_hashes.append(binding["artifact_sha256"])
        evaluations[cell_id] = harness.evaluate_cell(authority.store, evaluation_packet, base_grades, authority)
        evidence[cell_id] = harness.evidence_from(authority.store, evaluation_packet)
        grade_hashes.append({"cell_id": cell_id, "binding_sha256s": cell_grade_hashes})
    metrics = harness.derive_block(evidence)
    harness.verify_seal(metrics, "BOUND_METRICS")
    return evaluations, metrics, aliases, packet_hashes, grade_hashes


def build_bound_metrics(pre_packets, evaluation_packets, grades, grade_bindings, authority) -> Dict[str, Any]:
    _, _, _, expected_binding = _read_complete_pair(read_map=False)
    _, metrics, aliases, packet_hashes, grade_hashes = _evaluate_bound(pre_packets, evaluation_packets, grades, grade_bindings, authority, expected_binding)
    body = {
        "version": 2,
        "schema": METRIC_BINDING_SCHEMA_ID,
        "commitment_binding": dict(expected_binding),
        "aliases": [{"cell_id": cell, "blind_alias": alias} for cell, alias in zip(CELL_IDS, aliases)],
        "pre_call_packet_sha256s": packet_hashes,
        "grade_binding_sha256s": grade_hashes,
        "derived_metrics_sha256": metrics["artifact_sha256"],
        "immutable": True,
    }
    binding = seal(body)
    _validate_metric_binding(binding)
    return {"metrics": metrics, "binding": binding}


def _validate_metric_binding(value: Mapping[str, Any]) -> None:
    fields = {"version", "schema", "commitment_binding", "aliases", "pre_call_packet_sha256s", "grade_binding_sha256s", "derived_metrics_sha256", "immutable", "artifact_sha256", "artifact_bytes"}
    _require(isinstance(value, Mapping) and set(value) == fields, "METRIC_BINDING_FIELDS")
    verify_seal(value, "METRIC_BINDING")
    _require(value["version"] == 2 and value["schema"] == METRIC_BINDING_SCHEMA_ID, "METRIC_BINDING_VERSION_SCHEMA")
    _validate_binding(value["commitment_binding"])
    _require(isinstance(value["aliases"], list) and len(value["aliases"]) == 4, "METRIC_BINDING_ALIASES")
    for expected, item in zip(CELL_IDS, value["aliases"]):
        _require(isinstance(item, Mapping) and set(item) == {"cell_id", "blind_alias"}, "METRIC_BINDING_ALIAS_FIELDS")
        _require(item["cell_id"] == expected and isinstance(item["blind_alias"], str) and LABEL_RE.fullmatch(item["blind_alias"]) is not None, "METRIC_BINDING_ALIAS")
    _require(isinstance(value["pre_call_packet_sha256s"], list) and len(value["pre_call_packet_sha256s"]) == 4 and all(SHA_RE.fullmatch(str(x)) for x in value["pre_call_packet_sha256s"]), "METRIC_BINDING_PACKETS")
    _require(isinstance(value["grade_binding_sha256s"], list) and len(value["grade_binding_sha256s"]) == 4, "METRIC_BINDING_GRADES")
    for expected, item in zip(CELL_IDS, value["grade_binding_sha256s"]):
        _require(isinstance(item, Mapping) and set(item) == {"cell_id", "binding_sha256s"} and item["cell_id"] == expected, "METRIC_BINDING_GRADE_FIELDS")
        _require(isinstance(item["binding_sha256s"], list) and all(SHA_RE.fullmatch(str(x)) for x in item["binding_sha256s"]), "METRIC_BINDING_GRADE_SHA")
    _require(isinstance(value["derived_metrics_sha256"], str) and SHA_RE.fullmatch(value["derived_metrics_sha256"]) is not None, "METRIC_BINDING_METRICS")


def _require_live_authority(authority: Any, harness: Any) -> None:
    _require(getattr(authority, "fixture", True) is False, "OPENING_FIXTURE_AUTHORITY_DENIED")
    registry = getattr(authority, "registry", {})
    _require(registry.get("registry_kind") == "LIVE" and registry.get("countable") is True, "OPENING_NONCOUNTABLE_AUTHORITY_DENIED")
    review_ref = getattr(authority, "registry_review_ref", {})
    trusted = harness.TRUSTED_LIVE_REGISTRY_REVIEW_SHA256S
    _require(bool(trusted) and review_ref.get("sha256") in trusted, "OPENING_PENDING_HUMAN_AUTHORITY_DENIED")


def authorize_opening(pre_packets, evaluation_packets, grades, grade_bindings, metrics, metric_binding, authority) -> Dict[str, Any]:
    """Open only after exact v2 binding, immutable evaluation, and live authority."""
    _, _, _, expected_binding = _read_complete_pair(read_map=False)
    harness = _evaluation_harness()
    _require_live_authority(authority, harness)
    evaluations, recomputed_metrics, aliases, packet_hashes, grade_hashes = _evaluate_bound(pre_packets, evaluation_packets, grades, grade_bindings, authority, expected_binding)
    harness.verify_seal(metrics, "OPENING_METRICS")
    _require(metrics == recomputed_metrics, "OPENING_METRICS_SUBSTITUTION")
    _validate_metric_binding(metric_binding)
    expected_metric_body = {
        "version": 2,
        "schema": METRIC_BINDING_SCHEMA_ID,
        "commitment_binding": dict(expected_binding),
        "aliases": [{"cell_id": cell, "blind_alias": alias} for cell, alias in zip(CELL_IDS, aliases)],
        "pre_call_packet_sha256s": packet_hashes,
        "grade_binding_sha256s": grade_hashes,
        "derived_metrics_sha256": metrics["artifact_sha256"],
        "immutable": True,
    }
    _require(metric_binding == seal(expected_metric_body), "OPENING_METRIC_BINDING_SUBSTITUTION")
    _, _, private_map, final_binding = _read_complete_pair(read_map=True)
    _require(final_binding == expected_binding, "OPENING_TRANSACTION_SUBSTITUTION")
    assert private_map is not None
    committed_aliases = {item["cell_id"]: item["label"] for item in private_map["cells"]}
    for cell_id in CELL_IDS:
        _require(pre_packets[cell_id]["blind_alias"] == committed_aliases[cell_id], "OPENING_ALIAS_MAP_BINDING")
    return {
        "version": 2,
        "status": "DISABLED_PROVIDER_FREE_NOT_COUNTABLE",
        "activation": False,
        "countable": False,
        "independent_review": "REQUIRED",
        "final_block_authority": "REQUIRED",
        "commitment_binding": dict(expected_binding),
        "mapping": list(private_map["cells"]),
        "cell_evaluations": evaluations,
        "derived_metrics": metrics,
    }
