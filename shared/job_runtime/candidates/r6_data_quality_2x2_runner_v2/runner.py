"""Disabled additive R6 four-cell runner with one execution-wide reservation."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from shared.job_runtime.candidates.r6_data_quality_2x2_evaluation_v3 import harness as grading
from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1 import runner as predecessor
from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1.contracts import (
    CELL_ORDER,
    FROZEN_INPUTS,
    ContractError,
    sha256_json,
)

from .reservation import ReservationHandle, ReservationManager

PREDECESSOR = {
    "path": "shared/job_runtime/candidates/r6_data_quality_2x2_runner_v1/runner.py",
    "bytes": 39451,
    "sha256": "bc45fceff79a1106ef66c09376075f3bb72a235ac4a23ca69b7344f914ff0bff",
    "history_status": "OPEN",
}
RUNNER_V8_OPEN_REVIEW = {
    "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-runner-v8-independent-review-fable-20261112-8e9a8076-open.json",
    "bytes": 6255,
    "sha256": "145265647df2a9231d7b64f3b7c70c7266403b38cb15ad98e38deef3a6d588f5",
    "verdict": "OPEN",
    "producer_targeted_finding": "OPEN-RUNNER-V8-CONCURRENCY-001",
    "unresolved_finding": "OPEN-P0-V9-G3-SCHEMA-002",
}
P0_V9_CLEAN = {
    "path": "shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1/p0-contract-v9.json",
    "bytes": 5231,
    "sha256": "51f36fb46eb7a74994abf0a23152ce5d1f3fd7f4e8687aa900d1328e3b9aae1e",
    "review_path": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-attempt-envelope-v1-successor-v9-independent-review-fable-20261111-clean.json",
    "review_sha256": "0505e961774d325fdc6b89105215fd88cb0a71f8b942a78976d7ea1e8f49fbb2",
    "review_status": "CLEAN_P0_V9",
}
STATUS = "P0_V10_RECLOSURE_REQUIRED"
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def default_run(*_args: Any, **_kwargs: Any) -> Mapping[str, Any]:
    return {
        "status": STATUS,
        "p0_schema_status": "P0_V10_REQUIRED",
        "countable": False,
        "activation": False,
        "orchestrator_rebind": "PENDING",
        "remaining_runner_findings": "PENDING_ADJUDICATION_AND_FRESH_INDEPENDENT_REVIEW",
    }


def _root_identity(path: Path) -> str:
    candidate = Path(path).absolute()
    try:
        before = os.lstat(candidate)
        fd = os.open(candidate, _DIR_FLAGS)
        after = os.fstat(fd)
    except OSError as exc:
        raise ContractError("RESERVATION_BOUND_ROOT_OPEN_FAILED") from exc
    try:
        if (
            not stat.S_ISDIR(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or after.st_uid != os.getuid()
            or stat.S_IMODE(after.st_mode) != 0o700
        ):
            raise ContractError("RESERVATION_BOUND_ROOT_UNSAFE")
        return sha256_json({"device": after.st_dev, "inode": after.st_ino})
    finally:
        os.close(fd)


def _destination_identity(bundle_root: Path) -> str:
    path = Path(bundle_root).absolute()
    cursor = path
    while not os.path.lexists(cursor):
        if cursor.parent == cursor:
            raise ContractError("RESERVATION_DESTINATION_ANCESTOR_MISSING")
        cursor = cursor.parent
    try:
        meta = os.lstat(cursor)
    except OSError as exc:
        raise ContractError("RESERVATION_DESTINATION_STAT_FAILED") from exc
    if not stat.S_ISDIR(meta.st_mode) or stat.S_ISLNK(meta.st_mode) or meta.st_uid != os.getuid():
        raise ContractError("RESERVATION_DESTINATION_ANCESTOR_UNSAFE")
    # The key must stay identical before and after destination directories exist.
    # Existing ancestors are safety-checked above, but their inode is not key data.
    return sha256_json({"absolute_path_sha256": hashlib.sha256(os.fsencode(str(path))).hexdigest()})


def _fixture_owner_roots(boundaries: Optional[Mapping[str, Any]]) -> Mapping[str, str]:
    if type(boundaries) is not dict or set(boundaries) != {"ARM-A", "ARM-B"}:
        raise ContractError("FIXTURE_BOUNDARIES")
    roots: dict[str, str] = {}
    for arm in ("ARM-A", "ARM-B"):
        boundary = boundaries[arm]
        adapter = getattr(boundary, "adapter", None)
        owner_root = getattr(adapter, "owner_root", None)
        if owner_root is None:
            raise ContractError("RESERVATION_P0_OWNER_ROOT_MISSING")
        roots[arm] = _root_identity(Path(owner_root))
    if roots["ARM-A"] == roots["ARM-B"]:
        raise ContractError("RESERVATION_P0_OWNER_ROOT_ALIAS")
    return roots


def _known_destinations_absent(owner_root: Path, bundle_root: Path) -> bool:
    owner = Path(owner_root)
    bundle = Path(bundle_root)
    owner_targets = [owner / "receipt/block-v6.json", owner / "receipt/.stage-block-v6.json"]
    owner_targets.extend(owner / ("cell%02d/ref%02d.json" % (cell_index, ref_index)) for cell_index in range(1, 5) for ref_index in range(1, 7))
    bundle_targets: list[Path] = []
    for cell_id in CELL_ORDER:
        cell = bundle / cell_id
        bundle_targets.extend((cell / (cell_id + ".attempt-bundle.json"), cell / (".stage-" + cell_id + ".attempt-bundle.json")))
    return not any(os.path.lexists(path) for path in owner_targets + bundle_targets)


def _zero_effects_proof(owner_root: Path, bundle_root: Path) -> Mapping[str, Any]:
    destinations_absent = _known_destinations_absent(owner_root, bundle_root)
    return {
        "zero_effects": destinations_absent,
        "admission_absent": True,
        "receipt_absent": destinations_absent,
        "destinations_absent": destinations_absent,
        "program_order_proof": True,
    }


def _bindings(
    authority_registry_ref: Mapping[str, Any],
    owner_root: Path,
    map_commitment_ref: Mapping[str, Any],
    bundle_root: Path,
    boundaries: Mapping[str, Any],
) -> tuple[Mapping[str, Any], str, bool]:
    root = Path(owner_root).absolute()
    store = grading.ArtifactStore(root)
    fixture = True
    registry, grant, _grader_authority = predecessor._authority(root, authority_registry_ref, fixture)
    grading.validate_map_commitment(store.read(map_commitment_ref))
    grant_identity = sha256_json(
        {
            "authority_registry_ref": dict(authority_registry_ref),
            "block_grant_ref": dict(registry["block_grant_ref"]),
            "block_grant_sha256": sha256_json(grant),
        }
    )
    map_identity = sha256_json(
        {
            "map_ref": dict(map_commitment_ref),
            "map_content_sha256": map_commitment_ref["canonical_content_sha256"],
        }
    )
    values = {
        "block_id": grant["block_id"],
        "grant_identity_sha256": grant_identity,
        "input_identity_sha256": sha256_json(FROZEN_INPUTS),
        "map_identity_sha256": map_identity,
        "runner_owner_root_id": store.root_id(),
        "p0_owner_root_ids": dict(_fixture_owner_roots(boundaries)),
        "destination_identity_sha256": _destination_identity(bundle_root),
        "predecessor_runner_sha256": PREDECESSOR["sha256"],
        "p0_v9_contract_sha256": P0_V9_CLEAN["sha256"],
        "fixture": fixture,
    }
    return values, grant["block_id"], fixture


def _reconcile_receipt(
    root: Path,
    authority_registry_ref: Mapping[str, Any],
    map_commitment_ref: Mapping[str, Any],
    fixture: bool,
    block_id: str,
) -> Optional[Mapping[str, Any]]:
    return predecessor._reconcile_execution_receipt(root, authority_registry_ref, map_commitment_ref, fixture, block_id)


def execute_block(
    authority_registry_ref: Mapping[str, Any],
    owner_root: Path,
    map_commitment_ref: Mapping[str, Any],
    bundle_root: Path,
    *,
    _fixture_boundaries: Optional[Mapping[str, Any]] = None,
    _receipt_fault: Optional[str] = None,
    _reservation_fault: Optional[str] = None,
    _fault_hook: Optional[Callable[[str], None]] = None,
) -> Mapping[str, Any]:
    """Admit exactly one owner before any destination mutation or provider/P0 boundary."""
    owner_input = Path(owner_root).absolute()
    if owner_input.is_symlink():
        raise ContractError("OWNER_ROOT_SYMLINK")
    root = owner_input.resolve()
    bundle = Path(bundle_root).absolute()
    bindings, block_id, fixture = _bindings(
        authority_registry_ref,
        root,
        map_commitment_ref,
        bundle,
        _fixture_boundaries,
    )

    with ReservationManager(root, bindings) as manager:
        handle, is_owner = manager.acquire(
            lambda: _zero_effects_proof(root, bundle),
            fault=_reservation_fault,
        )
        if not is_owner:
            receipt = _reconcile_receipt(root, authority_registry_ref, map_commitment_ref, fixture, block_id)
            if receipt is not None:
                manager.mark_completed(handle, receipt)
                return receipt
            if manager.admitted(handle):
                manager.mark_unknown(handle)
                raise ContractError("RESERVATION_POST_ADMISSION_UNKNOWN_NO_REPLAY")
            raise ContractError("RESERVATION_NOT_OWNER")

        if _fault_hook is not None and _reservation_fault == "crash_after_reservation":
            _fault_hook("crash_after_reservation")
        handle.admit()
        if _fault_hook is not None and _reservation_fault in ("crash_after_admission", "crash_pre_first_boundary"):
            _fault_hook(_reservation_fault)
        try:
            receipt = predecessor.execute_block(
                authority_registry_ref,
                root,
                map_commitment_ref,
                bundle,
                _fixture_boundaries=_fixture_boundaries,
                _receipt_fault=_receipt_fault,
            )
        except Exception as exc:
            handle.mark_unknown()
            raise ContractError("RESERVATION_POST_ADMISSION_UNKNOWN_NO_REPLAY") from exc
        handle.mark_completed(receipt)
        return receipt


def finalize_block(
    execution_ref: Mapping[str, Any],
    owner_root: Path,
    grade_refs: Mapping[str, Any],
    opening_ref: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Preserve predecessor authenticated human/G3 finalization unchanged."""
    return predecessor.finalize_block(execution_ref, owner_root, grade_refs, opening_ref)


__all__ = [
    "P0_V9_CLEAN",
    "RUNNER_V8_OPEN_REVIEW",
    "PREDECESSOR",
    "STATUS",
    "default_run",
    "execute_block",
    "finalize_block",
]
