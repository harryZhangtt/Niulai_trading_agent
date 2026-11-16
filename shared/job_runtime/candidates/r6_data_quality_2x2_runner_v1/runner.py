"""Disabled provider-free v6 four-cell runner over committed P0 v9 contract evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping, Optional

from .contracts import (
    BLIND_ALIASES,
    CELL_BINDINGS,
    CELL_ORDER,
    FROZEN_INPUTS,
    TOOL_POLICY,
    WEB_POLICY,
    ContractError,
    sha256_json,
    validate_block_grant,
)
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.artifacts import (
    validate_bundle_owner_artifacts,
)
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.bundle import (
    read_attempt_bundle,
)
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.contracts import (
    strict_json_loads,
    validate_attempt_bundle,
)
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.pipeline import execute
from shared.job_runtime.candidates.r6_data_quality_2x2_evaluation_v3 import harness as grading

GRADING = {
    "contract": {"sha256": "8bef52f4f1c7511ec8897b17dbee2f542b0a822acaf22ebbe2e0e267d7c6714d", "bytes": 9944},
    "producer": {"sha256": "2df4cae89b8942a8eb38b766608381f4bc41aeb8f4c984a9d32aa677068718ea", "bytes": 2588},
    "review": {"sha256": "da36e2ae03c7a74ef7b5dce91eb7fc7e627b3cb431a0064c6efde37ef744b429", "bytes": 10585},
}
P0_V9 = {
    "bytes": 5231,
    "path": "shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1/p0-contract-v9.json",
    "review_bytes": 11667,
    "review_path": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-attempt-envelope-v1-successor-v8-independent-review-fable-20261111-provider-relabel-open.json",
    "review_sha256": "0a150a6221ba082ae38eae6951bff43fc904996a99623e425d36059e431ec2e6",
    "review_status": "OPEN",
    "sha256": "51f36fb46eb7a74994abf0a23152ce5d1f3fd7f4e8687aa900d1328e3b9aae1e"
}
_RECEIPT_PATH = "receipt/block-v6.json"
_RECEIPT_STAGE = "receipt/.stage-block-v6.json"
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
_FILE_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)


def default_run(*_args: Any, **_kwargs: Any) -> Mapping[str, Any]:
    return {"status": "DENIED_FIXED_AUTHORITY_OR_LIVE_BOUNDARY_UNAVAILABLE", "countable": False}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def _safe(root: Path, relative: str) -> Path:
    if not relative or relative.startswith("/") or "\\" in relative or any(x in ("", ".", "..") for x in relative.split("/")):
        raise ContractError("OWNER_PATH")
    path = root / relative
    for candidate in (root, *path.parents):
        if candidate.exists() and candidate.is_symlink():
            raise ContractError("OWNER_SYMLINK")
    return path


def _ensure_private_dir(path: Path) -> None:
    """Create one private directory or validate it without following/chmodding links."""
    path = Path(path)
    if os.path.lexists(path):
        st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
            raise ContractError("OWNER_DIRECTORY_UNSAFE")
        return
    parent = path.parent
    try:
        parent_st = os.lstat(parent)
    except OSError as exc:
        raise ContractError("OWNER_PARENT_MISSING") from exc
    if not stat.S_ISDIR(parent_st.st_mode) or stat.S_ISLNK(parent_st.st_mode):
        raise ContractError("OWNER_PARENT_UNSAFE")
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        return _ensure_private_dir(path)
    except OSError as exc:
        raise ContractError("OWNER_DIRECTORY_CREATE_FAILED") from exc
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
        raise ContractError("OWNER_DIRECTORY_UNSAFE")


def _read_canonical_file(path: Path, allowed_links: tuple[int, ...] = (1,)) -> tuple[bytes, Any]:
    fd = -1
    try:
        fd = os.open(path, _FILE_READ_FLAGS)
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid() or stat.S_IMODE(meta.st_mode) != 0o600 or meta.st_nlink not in allowed_links:
            raise ContractError("REOPEN_UNSAFE")
        chunks = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
    except OSError as exc:
        raise ContractError("REOPEN_FAILED") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    try:
        value = strict_json_loads(raw.decode("ascii"), "REOPEN_JSON")
    except Exception as exc:
        raise ContractError("REOPEN_JSON") from exc
    if _canonical(value) != raw:
        raise ContractError("REOPEN_NOT_CANONICAL")
    return raw, value


def _read_exact_file(path: Path, expected: bytes, allowed_links: tuple[int, ...] = (1,)) -> bytes:
    raw, _value = _read_canonical_file(path, allowed_links)
    if raw != expected or hashlib.sha256(raw).hexdigest() != hashlib.sha256(expected).hexdigest():
        raise ContractError("REOPEN_EXACT_MISMATCH")
    return raw

def _ref(kind: str, relative: str, raw: bytes, committed_at_ms: int) -> Mapping[str, Any]:
    return {
        "kind": kind,
        "path": relative,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "canonical_content_sha256": sha256_json(strict_json_loads(raw.decode("ascii"), "REF_JSON")),
        "immutable_at_ms": committed_at_ms,
    }


def _read(root: Path, ref: Mapping[str, Any], kind: Optional[str] = None) -> Any:
    expected = {"kind", "path", "sha256", "bytes", "canonical_content_sha256", "immutable_at_ms"}
    if type(ref) is not dict or set(ref) != expected:
        raise ContractError("REF_SHAPE")
    if kind is not None and ref["kind"] != kind:
        raise ContractError("REF_KIND")
    path = _safe(root, ref["path"])
    try:
        raw, value = _read_canonical_file(path)
    except ContractError as exc:
        raise ContractError("REF_OPEN_NOFOLLOW") from exc
    if len(raw) != ref["bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ContractError("REF_HASH_BYTES")
    if sha256_json(value) != ref["canonical_content_sha256"]:
        raise ContractError("REF_CONTENT")
    return value


def _write_ref(root: Path, kind: str, relative: str, value: Mapping[str, Any], committed_at_ms: int) -> Mapping[str, Any]:
    path = _safe(root, relative)
    _ensure_private_dir(path.parent)
    raw = _canonical(value)
    fd = -1
    try:
        fd = os.open(path, _FILE_WRITE_FLAGS, 0o600)
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise ContractError("REF_SHORT_WRITE")
            view = view[count:]
        os.fsync(fd)
    except FileExistsError as exc:
        raise ContractError("TARGET_COLLISION") from exc
    except OSError as exc:
        raise ContractError("REF_WRITE_FAILED") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    dir_fd = os.open(path.parent, _DIR_FLAGS)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    _read_exact_file(path, raw)
    return _ref(kind, relative, raw, committed_at_ms)


def _remove_and_sync(parent: Path, name: str) -> None:
    os.unlink(parent / name)
    fd = os.open(parent, _DIR_FLAGS)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _commit_execution_receipt(root: Path, value: Mapping[str, Any], committed_at_ms: int, fault: Optional[str] = None, crash_hook: Optional[Any] = None) -> Mapping[str, Any]:
    """Publish one receipt by hard-link no-replace and exact post-fsync reopen."""
    root = Path(root).resolve()
    final = _safe(root, _RECEIPT_PATH)
    stage = _safe(root, _RECEIPT_STAGE)
    _ensure_private_dir(final.parent)
    raw = _canonical(value)

    def finish_stage() -> Mapping[str, Any]:
        file_fd = os.open(stage, _FILE_READ_FLAGS)
        try:
            os.fsync(file_fd)
        finally:
            os.close(file_fd)
        try:
            os.link(stage, final, follow_symlinks=False)
        except FileExistsError as exc:
            raise ContractError("TARGET_COLLISION") from exc
        os.unlink(stage)
        dir_fd = os.open(final.parent, _DIR_FLAGS)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        _read_exact_file(final, raw)
        return _ref("execution_receipt_v6", _RECEIPT_PATH, raw, committed_at_ms)

    def recover() -> Optional[Mapping[str, Any]]:
        stage_exists, final_exists = os.path.lexists(stage), os.path.lexists(final)
        if not stage_exists and not final_exists:
            return None
        if stage_exists and not final_exists:
            try:
                _read_exact_file(stage, raw)
            except ContractError:
                _remove_and_sync(stage.parent, stage.name)
                return None
            return finish_stage()
        if not stage_exists and final_exists:
            _read_exact_file(final, raw)
            return _ref("execution_receipt_v6", _RECEIPT_PATH, raw, committed_at_ms)
        sm, fm = os.lstat(stage), os.lstat(final)
        if (sm.st_dev, sm.st_ino) != (fm.st_dev, fm.st_ino) or sm.st_nlink != 2 or fm.st_nlink != 2:
            raise ContractError("RECEIPT_CRASH_STATE_CONFLICT")
        _read_exact_file(final, raw, (2,))
        _remove_and_sync(stage.parent, stage.name)
        _read_exact_file(final, raw)
        return _ref("execution_receipt_v6", _RECEIPT_PATH, raw, committed_at_ms)

    prior = recover()
    if prior is not None:
        return prior

    def attempt(active_fault: Optional[str]) -> Mapping[str, Any]:
        fd = -1
        try:
            fd = os.open(stage, _FILE_WRITE_FLAGS, 0o600)
            view = memoryview(raw)
            while view:
                if active_fault == "short_write":
                    count = os.write(fd, view[: max(1, len(view) // 2)])
                    view = view[count:]
                    raise ContractError("RECEIPT_INJECTED_SHORT_WRITE")
                count = os.write(fd, view)
                if count <= 0:
                    raise ContractError("RECEIPT_SHORT_WRITE")
                view = view[count:]
            os.fsync(fd)
            os.close(fd)
            fd = -1
            if active_fault == "crash_after_stage_fsync":
                if crash_hook is not None:
                    crash_hook("crash_after_stage_fsync")
                raise ContractError("RECEIPT_INJECTED_CRASH_AFTER_STAGE_FSYNC")
            os.link(stage, final, follow_symlinks=False)
            if active_fault == "crash_post_link":
                if crash_hook is not None:
                    crash_hook("crash_post_link")
                raise ContractError("RECEIPT_INJECTED_CRASH_POST_LINK")
            os.unlink(stage)
            dir_fd = os.open(final.parent, _DIR_FLAGS)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
            _read_exact_file(final, raw)
            return _ref("execution_receipt_v6", _RECEIPT_PATH, raw, committed_at_ms)
        except FileExistsError as exc:
            raise ContractError("TARGET_COLLISION") from exc
        except OSError as exc:
            raise ContractError("RECEIPT_WRITE_FAILED") from exc
        finally:
            if fd >= 0:
                os.close(fd)

    try:
        return attempt(fault)
    except ContractError as exc:
        if not str(exc).startswith("RECEIPT_INJECTED_"):
            raise
        recovered = recover()
        if recovered is not None:
            return recovered
        return attempt(None)

def _authority(root: Path, registry_ref: Mapping[str, Any], fixture: bool):
    registry = _read(root, registry_ref, "authority_registry_v6")
    required = {
        "version", "fixture", "block_grant_ref", "block_review_ref", "provider_grant_refs",
        "provider_review_refs", "catalog_refs", "catalog_review_refs", "grading_registry_ref",
        "grading_registry_review_ref", "grading_grant_pairs",
    }
    if set(registry) != required or registry["version"] != 6 or registry["fixture"] is not fixture:
        raise ContractError("AUTHORITY_REGISTRY_SHAPE")
    grant = _read(root, registry["block_grant_ref"], "block_grant_v6")
    validate_block_grant(grant, fixture=fixture)
    review = _read(root, registry["block_review_ref"], "block_review_v6")
    if review != {"version": 6, "status": "CLEAN", "subject_sha256": registry["block_grant_ref"]["canonical_content_sha256"]}:
        raise ContractError("BLOCK_REVIEW")
    for name in ("provider_grant_refs", "provider_review_refs", "catalog_refs", "catalog_review_refs"):
        if type(registry[name]) is not list or len(registry[name]) != 4:
            raise ContractError("AUTHORITY_FOUR_REFS")
    for index, cell_id in enumerate(CELL_ORDER):
        provider_grant = _read(root, registry["provider_grant_refs"][index], "provider_grant_v6")
        provider_review = _read(root, registry["provider_review_refs"][index], "provider_review_v6")
        catalog = _read(root, registry["catalog_refs"][index], "catalog_v6")
        catalog_review = _read(root, registry["catalog_review_refs"][index], "catalog_review_v6")
        expected = "FIXTURE_AUTHORIZED" if fixture else "AUTHORIZED_FINAL_LIVE"
        if provider_grant != {"version": 6, "cell_id": cell_id, "status": expected} or provider_review != {"version": 6, "status": "CLEAN", "subject_sha256": registry["provider_grant_refs"][index]["canonical_content_sha256"]}:
            raise ContractError("PROVIDER_AUTHORITY")
        expected_catalog = "FIXTURE_CATALOG" if fixture else "PASS_CURRENT_LIVE_CATALOG_EVIDENCE"
        if catalog != {"version": 6, "cell_id": cell_id, "status": expected_catalog} or catalog_review != {"version": 6, "status": "CLEAN", "subject_sha256": registry["catalog_refs"][index]["canonical_content_sha256"]}:
            raise ContractError("CATALOG_AUTHORITY")
    pairs = {key: tuple(value) for key, value in registry["grading_grant_pairs"].items()}
    grader_authority = grading.GraderAuthority(
        grading.ArtifactStore(root), registry["grading_registry_ref"],
        registry["grading_registry_review_ref"], pairs, fixture,
    )
    return registry, grant, grader_authority


def _is_sha(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _validate_owner_descriptor(value: Any, expected_sha: Optional[str] = None) -> None:
    keys = {"relative_ref", "bytes", "sha256", "canonical_sha256", "mode", "owner_uid", "regular", "nofollow", "owner_private"}
    if type(value) is not dict or set(value) != keys:
        raise ContractError("EXECUTION_OWNER_REF_SHAPE")
    relative = value["relative_ref"]
    if type(relative) is not str or not relative or relative.startswith("/") or "\\" in relative or any(part in ("", ".", "..") for part in relative.split("/")):
        raise ContractError("EXECUTION_OWNER_REF_PATH")
    if type(value["bytes"]) is not int or isinstance(value["bytes"], bool) or value["bytes"] <= 0:
        raise ContractError("EXECUTION_OWNER_REF_BYTES")
    if not _is_sha(value["sha256"]) or value["sha256"] != value["canonical_sha256"] or (expected_sha is not None and value["sha256"] != expected_sha):
        raise ContractError("EXECUTION_OWNER_REF_SHA")
    if value["mode"] != "0600" or value["owner_uid"] != os.getuid() or value["regular"] is not True or value["nofollow"] is not True or value["owner_private"] is not True:
        raise ContractError("EXECUTION_OWNER_REF_AUTHENTICITY")


def _receipt_committed_at(value: Mapping[str, Any]) -> int:
    return max(value["packets"][cell_id]["committed_at_ms"] for cell_id in CELL_ORDER) + 1


def _validate_execution_body(root: Path, value: Any, authority_ref: Optional[Mapping[str, Any]] = None, map_ref: Optional[Mapping[str, Any]] = None, fixture: Optional[bool] = None, block_id: Optional[str] = None) -> Mapping[str, Any]:
    required = {
        "version", "block_id", "status", "countable", "authority_registry_ref", "p0_v9_contract",
        "grading_bindings", "map_commitment_ref", "owner_root_id", "cell_order", "denominator_cell_count",
        "attempted_variant_count", "partial_comparison", "cells", "packets", "fixture", "immutable",
    }
    if type(value) is not dict or set(value) != required or value["version"] != 6 or value["countable"] is not False or value["immutable"] is not True:
        raise ContractError("EXECUTION_RECEIPT_INVALID")
    if value["status"] not in ("PENDING_HUMAN_GRADING", "INCONCLUSIVE_NOT_FINALIZABLE") or type(value["block_id"]) is not str or not value["block_id"]:
        raise ContractError("EXECUTION_RECEIPT_STATUS")
    if value["p0_v9_contract"] != P0_V9 or value["grading_bindings"] != GRADING:
        raise ContractError("EXECUTION_PIN_DRIFT")
    if authority_ref is not None and value["authority_registry_ref"] != dict(authority_ref):
        raise ContractError("EXECUTION_AUTHORITY_BINDING")
    if map_ref is not None and value["map_commitment_ref"] != dict(map_ref):
        raise ContractError("EXECUTION_MAP_BINDING")
    if fixture is not None and value["fixture"] is not fixture:
        raise ContractError("EXECUTION_FIXTURE_BINDING")
    if block_id is not None and value["block_id"] != block_id:
        raise ContractError("EXECUTION_BLOCK_BINDING")
    store = grading.ArtifactStore(root)
    if value["owner_root_id"] != store.root_id():
        raise ContractError("EXECUTION_OWNER_ROOT_BINDING")
    if tuple(value["cell_order"]) != CELL_ORDER or value["attempted_variant_count"] != 4 or value["partial_comparison"] is not False:
        raise ContractError("EXECUTION_DENOMINATOR_INVALID")
    if type(value["packets"]) is not dict or set(value["packets"]) != set(CELL_ORDER):
        raise ContractError("EXECUTION_PACKETS_FOUR")
    if type(value["cells"]) is not list or len(value["cells"]) != 4:
        raise ContractError("EXECUTION_CELLS_FOUR")
    included = 0
    for index, cell_id in enumerate(CELL_ORDER):
        cell = value["cells"][index]
        expected_cell = {"cell_id", "order_index", "blind_alias", "terminal_state", "denominator_included", "replay_allowed", "bundle_digest", "bundle_receipt", "p0_evidence", "grading_refs", "engine_exact", "errors", "packet_sha256"}
        if type(cell) is not dict or set(cell) != expected_cell or cell["cell_id"] != cell_id or cell["order_index"] != index or cell["blind_alias"] != BLIND_ALIASES[cell_id]:
            raise ContractError("EXECUTION_CELL_BINDING")
        if cell["terminal_state"] not in ("PASS", "FAIL", "STOP", "MALFORMED", "MISSING", "UNKNOWN") or type(cell["engine_exact"]) is not bool or type(cell["errors"]) is not list or not all(type(item) is str for item in cell["errors"]):
            raise ContractError("EXECUTION_CELL_STATE")
        if cell["denominator_included"] is not True or cell["replay_allowed"] is not False or not _is_sha(cell["bundle_digest"]):
            raise ContractError("EXECUTION_CELL_DENOMINATOR")
        included += 1
        receipt = cell["bundle_receipt"]
        receipt_keys = {"path", "sha256", "bytes", "primitive", "file_fsync", "parent_dir_fsync", "no_overwrite", "recovered_fault"}
        if type(receipt) is not dict or set(receipt) != receipt_keys or receipt["path"] != cell_id + ".attempt-bundle.json" or not _is_sha(receipt["sha256"]) or type(receipt["bytes"]) is not int or receipt["bytes"] <= 0 or receipt["primitive"] != "LINK_NO_REPLACE_SINGLE_FILE" or receipt["file_fsync"] is not True or receipt["parent_dir_fsync"] is not True or receipt["no_overwrite"] is not True or (receipt["recovered_fault"] is not None and type(receipt["recovered_fault"]) is not str):
            raise ContractError("EXECUTION_BUNDLE_RECEIPT")
        provenance = cell["p0_evidence"]
        if type(provenance) is not dict or set(provenance) != {"research_evidence", "raw_custody_owner_ref"}:
            raise ContractError("EXECUTION_PROVENANCE_SHAPE")
        research = provenance["research_evidence"]
        names = ("sanitized_output", "factual_evidence", "source_inventory", "citation_inventory")
        if type(research) is not dict or set(research) != set(names):
            raise ContractError("EXECUTION_RESEARCH_PROVENANCE")
        for name in names:
            entry = research[name]
            if type(entry) is not dict or set(entry) != {"canonical_sha256", "owner_ref"} or not _is_sha(entry["canonical_sha256"]):
                raise ContractError("EXECUTION_RESEARCH_ENTRY")
            _validate_owner_descriptor(entry["owner_ref"], entry["canonical_sha256"])
        _validate_owner_descriptor(provenance["raw_custody_owner_ref"])
        refs = cell["grading_refs"]
        if type(refs) is not list or len(refs) != 6 or tuple(ref.get("kind") for ref in refs if type(ref) is dict) != grading.REF_KINDS:
            raise ContractError("EXECUTION_GRADING_REFS")
        try:
            for ref, kind in zip(refs, grading.REF_KINDS):
                intake = store.read(ref)
                grading.validate_intake(kind, intake, BLIND_ALIASES[cell_id])
            packet = value["packets"][cell_id]
            grading.validate_packet_runtime(store, packet)
        except grading.ContractError as exc:
            raise ContractError(str(exc)) from exc
        if packet["refs"] != refs or packet["artifact_sha256"] != cell["packet_sha256"] or packet["blind_alias"] != BLIND_ALIASES[cell_id] or packet["blind_map_commitment_ref"] != value["map_commitment_ref"]:
            raise ContractError("EXECUTION_PACKET_BINDING")
        if value["status"] == "PENDING_HUMAN_GRADING" and (cell["terminal_state"] != "PASS" or cell["engine_exact"] is not True or cell["errors"]):
            raise ContractError("EXECUTION_PENDING_NOT_CLEAN")
    if value["denominator_cell_count"] != included or included != 4:
        raise ContractError("EXECUTION_DENOMINATOR_INVALID")
    return value


def _reconcile_execution_receipt(root: Path, authority_ref: Mapping[str, Any], map_ref: Mapping[str, Any], fixture: bool, block_id: str) -> Optional[Mapping[str, Any]]:
    final = _safe(root, _RECEIPT_PATH)
    stage = _safe(root, _RECEIPT_STAGE)
    stage_exists, final_exists = os.path.lexists(stage), os.path.lexists(final)
    if not stage_exists and not final_exists:
        return None
    allowed = (2,) if stage_exists and final_exists else (1,)
    source = final if final_exists else stage
    try:
        raw, value = _read_canonical_file(source, allowed)
        _validate_execution_body(root, value, authority_ref, map_ref, fixture, block_id)
    except ContractError as exc:
        raise ContractError("TARGET_COLLISION") from exc
    committed_at = _receipt_committed_at(value)
    if stage_exists and final_exists:
        sm, fm = os.lstat(stage), os.lstat(final)
        if (sm.st_dev, sm.st_ino) != (fm.st_dev, fm.st_ino) or sm.st_nlink != 2 or fm.st_nlink != 2:
            raise ContractError("RECEIPT_CRASH_STATE_CONFLICT")
        _remove_and_sync(stage.parent, stage.name)
    elif stage_exists:
        file_fd = os.open(stage, _FILE_READ_FLAGS)
        try:
            os.fsync(file_fd)
        finally:
            os.close(file_fd)
        try:
            os.link(stage, final, follow_symlinks=False)
        except FileExistsError as exc:
            raise ContractError("RECEIPT_CRASH_STATE_CONFLICT") from exc
        os.unlink(stage)
        dir_fd = os.open(final.parent, _DIR_FLAGS)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    _read_exact_file(final, raw)
    return _ref("execution_receipt_v6", _RECEIPT_PATH, raw, committed_at)


def _preflight_destinations(owner_root: Path, bundle_root: Path) -> None:
    """Validate every destination and directory before creating any directory."""
    bundle_root = Path(bundle_root)
    cell_roots = [bundle_root / cell_id for cell_id in CELL_ORDER]
    directories = [bundle_root] + cell_roots
    for directory in directories:
        if os.path.lexists(directory):
            meta = os.lstat(directory)
            if not stat.S_ISDIR(meta.st_mode) or stat.S_ISLNK(meta.st_mode) or meta.st_uid != os.getuid() or stat.S_IMODE(meta.st_mode) != 0o700:
                raise ContractError("OWNER_DIRECTORY_UNSAFE")
    owner_targets = [_safe(owner_root, _RECEIPT_PATH), _safe(owner_root, _RECEIPT_STAGE)]
    owner_targets.extend(
        _safe(owner_root, "cell%02d/ref%02d.json" % (cell_index, ref_index))
        for cell_index in range(1, 5) for ref_index in range(1, 7)
    )
    bundle_targets = []
    for cell_id, cell_root in zip(CELL_ORDER, cell_roots):
        bundle_targets.extend((cell_root / (cell_id + ".attempt-bundle.json"), cell_root / (".stage-" + cell_id + ".attempt-bundle.json")))
    if any(os.path.lexists(path) for path in owner_targets + bundle_targets):
        raise ContractError("TARGET_COLLISION")
    _ensure_private_dir(bundle_root)
    for cell_root in cell_roots:
        _ensure_private_dir(cell_root)


def _unknown_items(prefix: str, count: int, digest: str) -> list[Mapping[str, Any]]:
    return [{"id": "%s-%02d-%s" % (prefix, index, digest[:12]), "state": "UNKNOWN"} for index in range(1, count + 1)]


def _evaluation_from_committed_bundle(alias: str, bundle: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    evidence = bundle["research_evidence"]
    output = evidence["sanitized_output"]["body"]
    factual = evidence["factual_evidence"]["body"]
    sources_body = evidence["source_inventory"]["body"]
    citations_body = evidence["citation_inventory"]["body"]
    envelope = bundle["envelope"]
    denominator = bundle["denominator_record"]
    source_digest = evidence["source_inventory"]["canonical_sha256"]
    output_digest = evidence["sanitized_output"]["canonical_sha256"]
    terminal = bundle["normalized_attempt"]["terminal_state"]

    values = {
        "sanitized_output": {"version": 3, "blind_alias": alias, "text": output["answer"]},
        "evidence_record": {
            "version": 3,
            "blind_alias": alias,
            "retained": envelope["retained"] is True and denominator["included"] is True,
            "freshness_items": [{"id": item["source_id"], "state": "UNKNOWN"} for item in sources_body["sources"]],
            "richness_items": _unknown_items("richness", 60, output_digest),
            "depth_items": _unknown_items("depth", 6, output_digest),
            "accuracy_claims": [{"id": claim_id, "state": "UNKNOWN"} for claim_id in output["claim_ids"]],
            "citation_items": [{"id": item["citation_id"], "state": "UNKNOWN"} for item in citations_body["citations"]],
            "source_coverage_items": _unknown_items("coverage", 6, source_digest),
            "incremental_facts": [{"id": item["fact_id"], "role": "FACT", "state": "UNKNOWN"} for item in factual["facts"]],
            "provider_cost_usd": {"state": "MISSING", "value": None},
            "metered_tool_cost_usd": {"state": "MISSING", "value": None},
            "elapsed_ms": {"state": "MISSING", "value": None},
            "provider_time_ms": {"state": "MISSING", "value": None},
            "tool_time_ms": {"state": "MISSING", "value": None},
        },
        "source_inventory": {
            "version": 3,
            "blind_alias": alias,
            "sources": [
                {"id": item["source_id"], "url": item["url"], "cutoff_ok": item["eligible"] is True and item["source_cutoff_sha256"] == bundle["normalized_attempt"]["source_cutoff_sha256"]}
                for item in sources_body["sources"]
            ],
        },
        "citation_inventory": {
            "version": 3,
            "blind_alias": alias,
            "citations": [{"id": item["citation_id"], "source_id": item["source_id"], "claim_id": item["claim_id"]} for item in citations_body["citations"]],
        },
        "deterministic_gate_report": {
            "version": 3,
            "blind_alias": alias,
            "hard_gates": {
                "cell_identity_unique": "FAIL",
                "frozen_payload_cutoff": "PASS",
                "provider_model_effort": "FAIL",
                "common_tool_web_allowance": "FAIL",
                "common_budget_time": "FAIL",
                "common_engine_contracts": "PASS" if envelope["readback_match"] else "FAIL",
                "one_attempt_no_replay": "PASS" if bundle["normalized_attempt"]["no_replay"] is True and denominator["replay_allowed"] is False else "FAIL",
                "raw_and_sanitized_custody": "PASS",
                "reference_parseability": "PASS",
                "terminal_unknown_durability": "PASS" if terminal in ("STOP", "UNKNOWN") and denominator["included"] is True or terminal not in ("STOP", "UNKNOWN") else "FAIL",
                "dq_treatment_integrity": "PASS",
                "all_variants_retained": "PASS" if envelope["retained"] is True and denominator["included"] is True else "FAIL",
            },
        },
        "raw_custody_receipt": {
            "version": 3,
            "blind_alias": alias,
            "raw_sha256": bundle["raw_custody_receipt"]["raw_sha256"],
            "owner_private": bundle["raw_custody_receipt"]["raw_ref"]["owner_private"],
        },
    }
    provenance = {
        "research_evidence": {
            name: {"canonical_sha256": evidence[name]["canonical_sha256"], "owner_ref": copy.deepcopy(evidence[name]["ref"])}
            for name in ("sanitized_output", "factual_evidence", "source_inventory", "citation_inventory")
        },
        "raw_custody_owner_ref": copy.deepcopy(bundle["raw_custody_receipt"]["raw_ref"]),
    }
    return values, provenance


def execute_block(
    authority_registry_ref: Mapping[str, Any],
    owner_root: Path,
    map_commitment_ref: Mapping[str, Any],
    bundle_root: Path,
    *,
    _fixture_boundaries: Optional[Mapping[str, Any]] = None,
    _receipt_fault: Optional[str] = None,
) -> Mapping[str, Any]:
    owner_input = Path(owner_root).absolute()
    if owner_input.is_symlink():
        raise ContractError("OWNER_ROOT_SYMLINK")
    root = owner_input.resolve()
    bundle_root = Path(bundle_root).absolute()
    store = grading.ArtifactStore(root)
    fixture = _fixture_boundaries is not None
    _registry, grant, _grader_authority = _authority(root, authority_registry_ref, fixture)
    grading.preflight_readiness({
        "version": 3, "activation": False, "provider_calls_permitted": False,
        "root": str(root), "atomic_create": True, "no_replace": True,
        "artifact_kinds": list(grading.ALL_ARTIFACT_KINDS) + ["blind_packet", "grade", "metric", "unblind"],
    })
    grading.validate_map_commitment(store.read(map_commitment_ref))
    recovered = _reconcile_execution_receipt(root, authority_registry_ref, map_commitment_ref, fixture, grant["block_id"])
    if recovered is not None:
        return recovered
    _preflight_destinations(root, bundle_root)
    if not fixture:
        raise ContractError("FIXED_LIVE_BOUNDARIES_UNAVAILABLE")
    boundaries = _fixture_boundaries
    if type(boundaries) is not dict or set(boundaries) != {"ARM-A", "ARM-B"}:
        raise ContractError("FIXTURE_BOUNDARIES")

    tool_policy = copy.deepcopy(TOOL_POLICY)
    web_policy = copy.deepcopy(WEB_POLICY)
    cells = []
    packets = {}
    window = grant["block_window"]
    for index, cell_id in enumerate(CELL_ORDER):
        provider, addon, enabled, model = CELL_BINDINGS[cell_id]
        plan = {
            "cell_id": cell_id, "blind_alias": BLIND_ALIASES[cell_id], "order_index": index,
            "checks_enabled": enabled, "model": model, "frozen_inputs": copy.deepcopy(FROZEN_INPUTS),
            "block_window": copy.deepcopy(window), "tool_policy": copy.deepcopy(tool_policy),
            "web_policy": copy.deepcopy(web_policy), "attempt_limit": 1, "retry_limit": 0,
            "replay_limit": 0, "status_query_limit": 0,
        }
        output = dict(boundaries[provider](copy.deepcopy(plan)))
        errors = []
        if any(key in output for key in ("grading_inputs", "grades", "metrics", "metric_evidence", "adjudication")):
            errors.append("PROVIDER_GRADING_REF_FORBIDDEN")
        if TOOL_POLICY != tool_policy or WEB_POLICY != web_policy or output.get("tool_readback") != plan["tool_policy"] or output.get("web_readback") != plan["web_policy"]:
            errors.append("POLICY_MUTATION_OR_DRIFT")
        readback = output.get("readback", {})
        engine_exact = output.get("engine_sha256") == grant["engine"]["sha256"] and output.get("model_readback") == model
        if not engine_exact:
            errors.append("ENGINE_READBACK_MISMATCH")
        try:
            p0_result = execute(
                boundaries[provider].adapter,
                bundle_root / cell_id,
                cell_id=cell_id,
                blind_addon_label=addon,
                checks_enabled=enabled,
                job_id=readback["job_id"], slot_id=readback["slot_id"],
                attempt_id=readback["attempt_id"], operation_id=readback["operation_id"],
                prompt_binding_sha256=readback["prompt_binding_sha256"],
                readback=output["p0_readback"], raw=output["raw"],
                provider_publication_artifact=output["provider_publication_artifact"],
                research_material=output["research_material"], terminal_state=output["terminal_state"],
                source_cutoff_sha256=FROZEN_INPUTS["source_cutoff_sha256"],
                dq_checks=output.get("dq_checks"),
            )
        except Exception as exc:
            raise ContractError("P0_REJECTION") from exc
        bundle_path = bundle_root / cell_id / p0_result["bundle_receipt"]["path"]
        committed = read_attempt_bundle(bundle_path, p0_result["bundle_receipt"]["sha256"])
        validate_attempt_bundle(committed)
        validate_bundle_owner_artifacts(boundaries[provider].adapter.owner_root, committed)
        if committed["bundle_digest"] != p0_result["attempt_bundle"]["bundle_digest"]:
            raise ContractError("P0_COMMITTED_RETURN_MISMATCH")
        terminal_state = committed["normalized_attempt"]["terminal_state"]
        if terminal_state != "PASS":
            errors.append("TERMINAL_" + terminal_state)
        values, provenance = _evaluation_from_committed_bundle(BLIND_ALIASES[cell_id], committed)
        refs = []
        for ref_index, kind in enumerate(grading.REF_KINDS, 1):
            grading.validate_intake(kind, values[kind], BLIND_ALIASES[cell_id])
            refs.append(_write_ref(root, kind, "cell%02d/ref%02d.json" % (index + 1, ref_index), values[kind], output["cell_window"]["end_ms"]))
        packet = grading.build_blind_packet(
            store, BLIND_ALIASES[cell_id], refs, map_commitment_ref,
            output["cell_window"]["end_ms"] + 1, window["start_ms"],
        )
        packets[cell_id] = packet
        cells.append({
            "cell_id": cell_id, "order_index": index, "blind_alias": BLIND_ALIASES[cell_id],
            "terminal_state": terminal_state, "denominator_included": committed["denominator_record"]["included"],
            "replay_allowed": committed["denominator_record"]["replay_allowed"],
            "bundle_digest": committed["bundle_digest"],
            "bundle_receipt": copy.deepcopy(p0_result["bundle_receipt"]),
            "p0_evidence": provenance, "grading_refs": refs,
            "engine_exact": engine_exact, "errors": errors, "packet_sha256": packet["artifact_sha256"],
        })
    complete = (
        tuple(cell["cell_id"] for cell in cells) == CELL_ORDER
        and all(cell["denominator_included"] is True and cell["replay_allowed"] is False for cell in cells)
    )
    body = {
        "version": 6, "block_id": grant["block_id"],
        "status": "PENDING_HUMAN_GRADING" if complete and all(not cell["errors"] for cell in cells) else "INCONCLUSIVE_NOT_FINALIZABLE",
        "countable": False, "authority_registry_ref": dict(authority_registry_ref),
        "p0_v9_contract": copy.deepcopy(P0_V9), "grading_bindings": GRADING,
        "map_commitment_ref": dict(map_commitment_ref), "owner_root_id": store.root_id(), "cell_order": list(CELL_ORDER),
        "denominator_cell_count": sum(cell["denominator_included"] is True for cell in cells),
        "attempted_variant_count": len(cells), "partial_comparison": False,
        "cells": cells, "packets": packets, "fixture": fixture, "immutable": True,
    }
    committed_at_ms = max(packet["committed_at_ms"] for packet in packets.values()) + 1
    return _commit_execution_receipt(root, body, committed_at_ms, _receipt_fault)


def finalize_block(
    execution_ref: Mapping[str, Any], owner_root: Path,
    grade_refs: Mapping[str, Any], opening_ref: Mapping[str, Any],
) -> Mapping[str, Any]:
    owner_input = Path(owner_root).absolute()
    if owner_input.is_symlink():
        raise ContractError("OWNER_ROOT_SYMLINK")
    root = owner_input.resolve()
    if type(execution_ref) is not dict or execution_ref.get("kind") != "execution_receipt_v6" or execution_ref.get("path") != _RECEIPT_PATH:
        raise ContractError("EXECUTION_REF_SOURCE_PIN")
    execution = _read(root, execution_ref, "execution_receipt_v6")
    _validate_execution_body(root, execution)
    if execution_ref["immutable_at_ms"] != _receipt_committed_at(execution):
        raise ContractError("EXECUTION_REF_TIME_BINDING")
    if execution["status"] != "PENDING_HUMAN_GRADING":
        raise ContractError("EXECUTION_RECEIPT_INVALID")
    _registry, _grant, grader_authority = _authority(root, execution["authority_registry_ref"], execution["fixture"])
    if execution["block_id"] != _grant["block_id"]:
        raise ContractError("EXECUTION_BLOCK_BINDING")
    if tuple(grade_refs) != CELL_ORDER:
        raise ContractError("GRADE_REFS_FOUR_CELLS")
    grades = {}
    for cell_id in CELL_ORDER:
        if type(grade_refs[cell_id]) is not list:
            raise ContractError("GRADE_REFS")
        grades[cell_id] = [_read(root, ref, "human_grade_v3") for ref in grade_refs[cell_id]]
    opening = _read(root, opening_ref, "blind_opening_v6")
    if set(opening) != {"version", "mapping", "nonce", "opened_at_ms"} or opening["version"] != 6:
        raise ContractError("OPENING_INVALID")
    packets = {cell_id: execution["packets"][cell_id] for cell_id in CELL_ORDER}
    ordered_grades = {cell_id: grades[cell_id] for cell_id in CELL_ORDER}
    try:
        result = grading.authorize_unblinding(
            grading.ArtifactStore(root), packets, ordered_grades, grader_authority,
            opening["mapping"], opening["nonce"], opening["opened_at_ms"],
        )
    except grading.ContractError as exc:
        raise ContractError(str(exc)) from exc
    return {
        "version": 6, "execution_ref": dict(execution_ref),
        "status": "PASS_COUNTABLE" if result["countable"] else result["status"],
        "countable": result["countable"], "grading_result": result, "immutable": True,
    }


__all__ = ["default_run", "execute_block", "finalize_block"]
