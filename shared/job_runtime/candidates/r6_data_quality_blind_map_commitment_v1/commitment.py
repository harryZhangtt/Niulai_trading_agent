"""Disabled, provider-free pre-call blind-map commitment for frozen R6 DQ 2x2.

The public creation and validation surfaces intentionally accept no root, map,
clock, or randomness.  The private map is not read by ``authorize_opening`` until
existing evaluation-v3 packet, gate, grade, and derived-metric validation passes.
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
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise CommitmentError("CANONICAL_VALUE_INVALID") from None


WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
RUNTIME_RELATIVE_ROOT = Path("runtime/r6_data_quality_blind_map_commitment_v1")
PRIVATE_MAP_NAME = "owner-private-canonical-map-v1.json"
COMMITMENT_NAME = "sanitized-commitment-v1.json"
MAP_SCHEMA_ID = "r6-data-quality-blind-map-v1"
COMMITMENT_SCHEMA_ID = "r6-data-quality-blind-map-commitment-v1"
CELL_IDS = (
    "R6DQ-7F2C91A4",
    "R6DQ-1B8E43D7",
    "R6DQ-C4A7095E",
    "R6DQ-92D6F0B3",
)
LABEL_RE = re.compile(r"[0-9a-f]{32}\Z")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")

DESIGN_IDENTITY = "fcf096d0c641f373eab7163fa894e5d4f9605ab3ab36ff867e4b586bdcaf278e"
DESIGN_REVIEW_IDENTITY = "0018e413e40371bb2703aecf3963433f1a883a93b1070e815dccc0dc61866d3f"
EVALUATION_IDENTITY = "8bef52f4f1c7511ec8897b17dbee2f542b0a822acaf22ebbe2e0e267d7c6714d"
EVALUATION_PRODUCER_IDENTITY = "2df4cae89b8942a8eb38b766608381f4bc41aeb8f4c984a9d32aa677068718ea"
EVALUATION_REVIEW_IDENTITY = "da36e2ae03c7a74ef7b5dce91eb7fc7e627b3cb431a0064c6efde37ef744b429"

PINNED_SOURCES = (
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-addon-2x2-ab-design.json", 26277, DESIGN_IDENTITY),
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-addon-2x2-ab-design-independent-review.json", 18741, DESIGN_REVIEW_IDENTITY),
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-evaluation-contract-v3.json", 9944, EVALUATION_IDENTITY),
    ("tuning/architecture/r6_data_quality_2x2_evaluation_v3/producer-verification-v3.json", 2588, EVALUATION_PRODUCER_IDENTITY),
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-evaluation-v3-independent-review.json", 10585, EVALUATION_REVIEW_IDENTITY),
    ("shared/job_runtime/candidates/r6_data_quality_2x2_evaluation_v3/harness.py", 31895, "a42f1d0303857f443b5352ed7cfd244551767d347168e3ada6b7f8042cdaa7e4"),
)


def _root_path() -> Path:
    # Do not resolve: lstat/open(O_NOFOLLOW) must observe a substituted root symlink.
    root = WORKSPACE_ROOT / RUNTIME_RELATIVE_ROOT
    _require(root.is_absolute(), "ROOT_NOT_ABSOLUTE")
    return root


def _verify_pinned_sources() -> None:
    for relative, expected_bytes, expected_sha256 in PINNED_SOURCES:
        path = WORKSPACE_ROOT / relative
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise CommitmentError("PINNED_SOURCE_MISSING") from exc
        _require(len(raw) == expected_bytes, "PINNED_SOURCE_BYTES")
        _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "PINNED_SOURCE_DIGEST")


def _validate_root() -> os.stat_result:
    root = _root_path()
    _require(root.is_absolute(), "ROOT_NOT_ABSOLUTE")
    try:
        status = os.lstat(root)
    except OSError as exc:
        raise CommitmentError("ROOT_MISSING") from exc
    _require(not stat.S_ISLNK(status.st_mode), "ROOT_SYMLINK")
    _require(stat.S_ISDIR(status.st_mode), "ROOT_NOT_DIRECTORY")
    _require(status.st_uid == os.getuid(), "ROOT_OWNER")
    _require(stat.S_IMODE(status.st_mode) == 0o700, "ROOT_MODE")
    return status


def _ensure_root() -> None:
    root = _root_path()
    parent = root.parent
    try:
        parent_status = os.lstat(parent)
    except OSError as exc:
        raise CommitmentError("ROOT_PARENT_MISSING") from exc
    _require(stat.S_ISDIR(parent_status.st_mode) and not stat.S_ISLNK(parent_status.st_mode), "ROOT_PARENT_INVALID")
    _require(parent_status.st_uid == os.getuid(), "ROOT_PARENT_OWNER")
    try:
        os.mkdir(root, 0o700)
        os.chmod(root, 0o700, follow_symlinks=False)
        parent_fd = os.open(str(parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except FileExistsError:
        pass
    except OSError as exc:
        raise CommitmentError("ROOT_CREATE") from exc
    _validate_root()


def _safe_name(name: str) -> None:
    _require(isinstance(name, str) and name in (PRIVATE_MAP_NAME, COMMITMENT_NAME), "PATH_NOT_FIXED")
    _require("/" not in name and "\\" not in name and name not in ("", ".", ".."), "PATH_TRAVERSAL")


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


def _read_file(name: str, expected_identity: Tuple[int, int] | None = None) -> Tuple[bytes, Tuple[int, int]]:
    _safe_name(name)
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
        chunks = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        path_status = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        _require((path_status.st_dev, path_status.st_ino) == identity, "ARTIFACT_SUBSTITUTION")
        current_root = os.fstat(root_fd)
        _require((current_root.st_dev, current_root.st_ino) == (root_status.st_dev, root_status.st_ino), "ROOT_SUBSTITUTION")
        return b"".join(chunks), identity
    except CommitmentError:
        raise
    except OSError as exc:
        raise CommitmentError("ARTIFACT_OPEN_NOFOLLOW") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(root_fd)


def _atomic_no_replace(name: str, data: bytes) -> Tuple[int, int]:
    _safe_name(name)
    root_fd, root_status = _open_root_fd()
    fd = -1
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(name, flags, 0o600, dir_fd=root_fd)
        os.fchmod(fd, 0o600)
        offset = 0
        while offset < len(data):
            written = os.write(fd, data[offset:])
            _require(written > 0, "ARTIFACT_SHORT_WRITE")
            offset += written
        os.fsync(fd)
        status = os.fstat(fd)
        _require(stat.S_ISREG(status.st_mode), "ARTIFACT_NOT_REGULAR")
        _require(status.st_uid == os.getuid(), "ARTIFACT_OWNER")
        _require(stat.S_IMODE(status.st_mode) == 0o600, "ARTIFACT_MODE")
        identity = (status.st_dev, status.st_ino)
        os.close(fd)
        fd = -1
        os.fsync(root_fd)
        current_root = os.fstat(root_fd)
        _require((current_root.st_dev, current_root.st_ino) == (root_status.st_dev, root_status.st_ino), "ROOT_SUBSTITUTION")
    except CommitmentError:
        raise
    except FileExistsError as exc:
        raise CommitmentError("ARTIFACT_EXISTS_NO_REPLACE") from exc
    except OSError as exc:
        raise CommitmentError("ARTIFACT_ATOMIC_WRITE") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(root_fd)
    reopened, reopened_identity = _read_file(name, identity)
    _require(reopened == data, "ARTIFACT_REOPEN_BYTES")
    _require(hashlib.sha256(reopened).digest() == hashlib.sha256(data).digest(), "ARTIFACT_REOPEN_HASH")
    return reopened_identity


def _fixed_identity_fields() -> Dict[str, str]:
    return {
        "design_identity": DESIGN_IDENTITY,
        "design_review_identity": DESIGN_REVIEW_IDENTITY,
        "evaluation_identity": EVALUATION_IDENTITY,
        "evaluation_producer_identity": EVALUATION_PRODUCER_IDENTITY,
        "evaluation_review_identity": EVALUATION_REVIEW_IDENTITY,
    }


def _labels_are_order_leaking(labels: Sequence[str], cells_in_label_order: Sequence[str]) -> bool:
    values = sorted(int(label, 16) for label in labels)
    sequential = len(values) > 1 and all(b - a == 1 for a, b in zip(values, values[1:]))
    source_order = tuple(cells_in_label_order) in (CELL_IDS, tuple(reversed(CELL_IDS)))
    return sequential or source_order


def _validate_private_map(value: Mapping[str, Any]) -> None:
    required = {"version", "schema", *tuple(_fixed_identity_fields()), "cells"}
    _require(isinstance(value, Mapping) and set(value) == required, "MAP_FIELDS")
    _require(value["version"] == 1 and value["schema"] == MAP_SCHEMA_ID, "MAP_VERSION_SCHEMA")
    for field, expected in _fixed_identity_fields().items():
        _require(value[field] == expected, "MAP_IDENTITY")
    cells = value["cells"]
    _require(isinstance(cells, list) and len(cells) == 4, "MAP_CELL_COUNT")
    labels = []
    cell_ids = []
    for item in cells:
        _require(isinstance(item, Mapping) and set(item) == {"label", "cell_id"}, "MAP_CELL_FIELDS")
        label = item["label"]
        cell_id = item["cell_id"]
        _require(isinstance(label, str) and LABEL_RE.fullmatch(label) is not None, "MAP_LABEL_OPAQUE")
        _require(cell_id in CELL_IDS, "MAP_CELL_ID")
        labels.append(label)
        cell_ids.append(cell_id)
    _require(len(set(labels)) == 4, "MAP_LABEL_DUPLICATE")
    _require(set(cell_ids) == set(CELL_IDS) and len(set(cell_ids)) == 4, "MAP_CELL_DUPLICATE")
    _require(labels == sorted(labels), "MAP_CANONICAL_ORDER")
    _require(not _labels_are_order_leaking(labels, cell_ids), "MAP_ORDER_LEAKAGE")


def _validate_commitment_value(value: Mapping[str, Any]) -> None:
    _require(isinstance(value, Mapping), "COMMITMENT_TYPE")
    _require(set(value) == {"version", "schema", "canonical_digest", "canonical_bytes"}, "COMMITMENT_FIELDS")
    _require(value["version"] == 1 and value["schema"] == MAP_SCHEMA_ID, "COMMITMENT_VERSION_SCHEMA")
    _require(isinstance(value["canonical_digest"], str) and SHA_RE.fullmatch(value["canonical_digest"]) is not None, "COMMITMENT_DIGEST")
    _require(isinstance(value["canonical_bytes"], int) and value["canonical_bytes"] > 0, "COMMITMENT_BYTES")


def _decode_canonical(raw: bytes, code: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CommitmentError(code + "_JSON") from exc
    _require(canonical_bytes(value) == raw, code + "_NOT_CANONICAL")
    _require(isinstance(value, Mapping), code + "_TYPE")
    return value


def _generate_private_map() -> Dict[str, Any]:
    for _ in range(128):
        pairs = [(secrets.token_hex(16), cell_id) for cell_id in CELL_IDS]
        if len({label for label, _ in pairs}) != 4:
            continue
        pairs.sort()
        labels = [label for label, _ in pairs]
        ordered_cells = [cell for _, cell in pairs]
        if _labels_are_order_leaking(labels, ordered_cells):
            continue
        value = {"version": 1, "schema": MAP_SCHEMA_ID, **_fixed_identity_fields(), "cells": [{"label": label, "cell_id": cell} for label, cell in pairs]}
        _validate_private_map(value)
        return value
    raise CommitmentError("LABEL_GENERATION_EXHAUSTED")


def create_commitment() -> Dict[str, Any]:
    """Create exactly one private map and one sanitized commitment, no replace."""
    _verify_pinned_sources()
    _ensure_root()
    private_map = _generate_private_map()
    map_raw = canonical_bytes(private_map)
    commitment = {
        "version": 1,
        "schema": MAP_SCHEMA_ID,
        "canonical_digest": hashlib.sha256(map_raw).hexdigest(),
        "canonical_bytes": len(map_raw),
    }
    _validate_commitment_value(commitment)
    commitment_raw = canonical_bytes(commitment)
    map_identity = _atomic_no_replace(PRIVATE_MAP_NAME, map_raw)
    _atomic_no_replace(COMMITMENT_NAME, commitment_raw)
    reopened_map, _ = _read_file(PRIVATE_MAP_NAME, map_identity)
    _require(reopened_map == map_raw, "MAP_FINAL_REOPEN_BYTES")
    _require(hashlib.sha256(reopened_map).hexdigest() == commitment["canonical_digest"], "MAP_FINAL_REOPEN_HASH")
    return dict(commitment)


def _read_sanitized_commitment() -> Dict[str, Any]:
    raw, _ = _read_file(COMMITMENT_NAME)
    value = _decode_canonical(raw, "COMMITMENT")
    _validate_commitment_value(value)
    return dict(value)


def _read_private_map(commitment: Mapping[str, Any]) -> Dict[str, Any]:
    raw, _ = _read_file(PRIVATE_MAP_NAME)
    _require(len(raw) == commitment["canonical_bytes"], "MAP_COMMITTED_BYTES")
    _require(hashlib.sha256(raw).hexdigest() == commitment["canonical_digest"], "MAP_COMMITTED_DIGEST")
    value = _decode_canonical(raw, "MAP")
    _validate_private_map(value)
    return dict(value)


def validate_commitment() -> Dict[str, Any]:
    """Validate the fixed candidate artifacts without accepting caller choices."""
    _verify_pinned_sources()
    commitment = _read_sanitized_commitment()
    _read_private_map(commitment)
    return commitment


def _evaluation_harness():
    _verify_pinned_sources()
    harness = importlib.import_module("shared.job_runtime.candidates.r6_data_quality_2x2_evaluation_v3.harness")
    _require(tuple(harness.CELL_ORDER) == CELL_IDS, "EVALUATION_CELL_DRIFT")
    return harness


def authorize_opening(packets: Mapping[str, Mapping[str, Any]], grades: Mapping[str, Sequence[Mapping[str, Any]]], authority: Any) -> Dict[str, Any]:
    """Open only after evaluation-v3 immutably validates gates, grades, and metrics.

    This disabled wrapper never marks the block countable and has no provider,
    network, account, credential, email, business, scheduler, or host effects.
    """
    commitment = _read_sanitized_commitment()
    harness = _evaluation_harness()
    _require(tuple(packets) == CELL_IDS and tuple(grades) == CELL_IDS, "OPENING_FOUR_CELL_ORDER")
    store = authority.store
    evaluations: Dict[str, Mapping[str, Any]] = {}
    evidence: Dict[str, Mapping[str, Any]] = {}
    for cell_id in CELL_IDS:
        packet = packets[cell_id]
        harness.validate_packet_runtime(store, packet)
        evaluations[cell_id] = harness.evaluate_cell(store, packet, grades[cell_id], authority)
        evidence[cell_id] = harness.evidence_from(store, packet)
    metrics = harness.derive_block(evidence)
    harness.verify_seal(metrics, "OPENING_METRICS")
    _require(metrics.get("immutable") is True, "OPENING_METRICS_IMMUTABLE")
    private_map = _read_private_map(commitment)
    return {
        "version": 1,
        "status": "DISABLED_PROVIDER_FREE_NOT_COUNTABLE",
        "activation": False,
        "countable": False,
        "final_block_authority": "REQUIRED",
        "independent_review": "REQUIRED",
        "commitment": dict(commitment),
        "mapping": list(private_map["cells"]),
        "cell_evaluations": evaluations,
        "derived_metrics": metrics,
    }
