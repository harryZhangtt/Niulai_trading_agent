"""Disabled additive R6 runner-v3 with closed identity and exact-death recovery."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from shared.job_runtime.candidates.r6_data_quality_2x2_evaluation_v3 import harness as _grading_module
from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1 import runner as _predecessor_module
from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1 import contracts as _contracts_module
from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1.contracts import ContractError

from .reservation import ReservationManager

STATUS = "P0_V10_RECLOSURE_REQUIRED"
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def default_run(*_args: Any, **_kwargs: Any) -> Mapping[str, Any]:
    return {
        "status": STATUS,
        "p0_schema_status": "P0_V10_REQUIRED",
        "consumer_status": "P0_V10_RECLOSURE_REQUIRED",
        "countable": False,
        "activation": False,
        "orchestrator_rebind": "PENDING",
        "fresh_independent_review": "PENDING",
    }


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


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
        return _sha(_canonical({"device": after.st_dev, "inode": after.st_ino}))
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
    return _sha(_canonical({"absolute_path_sha256": _sha(os.fsencode(str(path)))}))


def _fixture_owner_roots(boundaries: Optional[Mapping[str, Any]]) -> Mapping[str, str]:
    if type(boundaries) is not dict or set(boundaries) != {"ARM-A", "ARM-B"}:
        raise ContractError("FIXTURE_BOUNDARIES")
    roots: dict[str, str] = {}
    for arm in ("ARM-A", "ARM-B"):
        owner_root = getattr(getattr(boundaries[arm], "adapter", None), "owner_root", None)
        if owner_root is None:
            raise ContractError("RESERVATION_P0_OWNER_ROOT_MISSING")
        roots[arm] = _root_identity(Path(owner_root))
    if roots["ARM-A"] == roots["ARM-B"]:
        raise ContractError("RESERVATION_P0_OWNER_ROOT_ALIAS")
    return roots


def _known_destinations_absent(owner_root: Path, bundle_root: Path, cell_order: tuple[str, ...]) -> bool:
    owner = Path(owner_root)
    bundle = Path(bundle_root)
    owner_targets = [owner / "receipt/block-v6.json", owner / "receipt/.stage-block-v6.json"]
    owner_targets.extend(owner / ("cell%02d/ref%02d.json" % (cell_index, ref_index)) for cell_index in range(1, 5) for ref_index in range(1, 7))
    bundle_targets: list[Path] = []
    for cell_id in cell_order:
        cell = bundle / cell_id
        bundle_targets.extend((cell / (cell_id + ".attempt-bundle.json"), cell / (".stage-" + cell_id + ".attempt-bundle.json")))
    return not any(os.path.lexists(path) for path in owner_targets + bundle_targets)


def _build_closed_runtime():
    repo_root = Path(__file__).resolve().parents[4]
    sha256_constructor = hashlib.sha256
    json_dumps = json.dumps
    reservation_manager = ReservationManager
    fixture_owner_roots = _fixture_owner_roots
    destination_identity = _destination_identity
    known_destinations_absent = _known_destinations_absent

    def closed_canonical(value: Any) -> bytes:
        return json_dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")

    def closed_sha(raw: bytes) -> str:
        return sha256_constructor(raw).hexdigest()

    specs = (
        ("predecessor_runner", "shared/job_runtime/candidates/r6_data_quality_2x2_runner_v1/runner.py", 39451, "bc45fceff79a1106ef66c09376075f3bb72a235ac4a23ca69b7344f914ff0bff"),
        ("predecessor_contracts", "shared/job_runtime/candidates/r6_data_quality_2x2_runner_v1/contracts.py", 14745, "9f0bc41282461e64ca795cb64365e84341c029e11760efbfc68dc29d72846be7"),
        ("grading_harness", "shared/job_runtime/candidates/r6_data_quality_2x2_evaluation_v3/harness.py", 31895, "a42f1d0303857f443b5352ed7cfd244551767d347168e3ada6b7f8042cdaa7e4"),
        ("p0_v9_contract", "shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1/p0-contract-v9.json", 5231, "51f36fb46eb7a74994abf0a23152ce5d1f3fd7f4e8687aa900d1328e3b9aae1e"),
        ("p0_v9_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-attempt-envelope-v1-successor-v9-independent-review-fable-20261111-clean.json", 15534, "0505e961774d325fdc6b89105215fd88cb0a71f8b942a78976d7ea1e8f49fbb2"),
        ("runner_v8_open_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-runner-v8-independent-review-fable-20261112-8e9a8076-open.json", 6255, "145265647df2a9231d7b64f3b7c70c7266403b38cb15ad98e38deef3a6d588f5"),
        ("runner_v2_open_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-runner-v2-independent-review-fable-20261113-8e9a8076-open.json", 13206, "c2669dec8fd1e32f616a6d97ce1e75f6de9a736d106814db1c99f8328215cff1"),
    )
    expected_module_files = (
        (_predecessor_module, specs[0][1]),
        (_contracts_module, specs[1][1]),
        (_grading_module, specs[2][1]),
    )
    frozen_input_sha = "6238b65ef5734d74a06e1747f2125e75a82cdf43f6ca1ba248be4693d007d885"
    cell_order = ("R6DQ-7F2C91A4", "R6DQ-1B8E43D7", "R6DQ-C4A7095E", "R6DQ-92D6F0B3")
    authority = _predecessor_module._authority
    reconcile = _predecessor_module._reconcile_execution_receipt
    execute = _predecessor_module.execute_block
    finalize = _predecessor_module.finalize_block
    artifact_store = _grading_module.ArtifactStore
    validate_map = _grading_module.validate_map_commitment

    def verify_sources() -> Mapping[str, str]:
        observed: dict[str, str] = {}
        for name, relative, expected_bytes, expected_sha in specs:
            path = repo_root / relative
            try:
                raw = path.read_bytes()
            except OSError as exc:
                raise ContractError("RUNNER_V3_SOURCE_PIN_READ_FAILED") from exc
            if len(raw) != expected_bytes or closed_sha(raw) != expected_sha:
                raise ContractError("RUNNER_V3_SOURCE_PIN_MISMATCH")
            observed[name] = expected_sha
        for module, relative in expected_module_files:
            module_file = getattr(module, "__file__", None)
            if module_file is None or Path(module_file).resolve() != (repo_root / relative).resolve():
                raise ContractError("RUNNER_V3_IMPORTED_SOURCE_MISMATCH")
        if closed_sha(closed_canonical(_contracts_module.FROZEN_INPUTS)) != frozen_input_sha:
            raise ContractError("RUNNER_V3_FROZEN_INPUT_MUTATION")
        observed["source_identity"] = closed_sha(closed_canonical(tuple((name, relative, length, digest) for name, relative, length, digest in specs)))
        return observed

    def bindings_impl(
        authority_registry_ref: Mapping[str, Any],
        owner_root: Path,
        map_commitment_ref: Mapping[str, Any],
        bundle_root: Path,
        boundaries: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], str, bool]:
        pins = verify_sources()
        root = Path(owner_root).absolute()
        store = artifact_store(root)
        fixture = True
        registry, grant, _grader_authority = authority(root, authority_registry_ref, fixture)
        map_value = store.read(map_commitment_ref)
        validate_map(map_value)
        grant_sha = closed_sha(closed_canonical(grant))
        map_sha = closed_sha(closed_canonical(map_value))
        if grant_sha != registry["block_grant_ref"]["canonical_content_sha256"]:
            raise ContractError("RUNNER_V3_GRANT_CONTENT_BINDING")
        if map_sha != map_commitment_ref["canonical_content_sha256"]:
            raise ContractError("RUNNER_V3_MAP_CONTENT_BINDING")
        values = {
            "block_id": grant["block_id"],
            "grant_content_sha256": grant_sha,
            "input_identity_sha256": frozen_input_sha,
            "map_content_sha256": map_sha,
            "runner_owner_root_id": store.root_id(),
            "source_identity_sha256": pins["source_identity"],
            "authority_registry_ref_sha256": closed_sha(closed_canonical(dict(authority_registry_ref))),
            "map_commitment_ref_sha256": closed_sha(closed_canonical(dict(map_commitment_ref))),
            "p0_owner_root_ids": dict(fixture_owner_roots(boundaries)),
            "destination_identity_sha256": destination_identity(bundle_root),
            "predecessor_runner_sha256": pins["predecessor_runner"],
            "predecessor_contracts_sha256": pins["predecessor_contracts"],
            "grading_harness_sha256": pins["grading_harness"],
            "p0_v9_contract_sha256": pins["p0_v9_contract"],
            "p0_v9_review_sha256": pins["p0_v9_review"],
            "runner_v8_open_review_sha256": pins["runner_v8_open_review"],
            "runner_v2_open_review_sha256": pins["runner_v2_open_review"],
            "fixture": fixture,
        }
        return values, grant["block_id"], fixture

    def zero_effects(root: Path, bundle: Path) -> Mapping[str, Any]:
        absent = known_destinations_absent(root, bundle, cell_order)
        return {
            "zero_effects": absent,
            "admission_absent": True,
            "receipt_absent": absent,
            "destinations_absent": absent,
            "program_order_proof": True,
        }

    def execute_impl(
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
        owner_input = Path(owner_root).absolute()
        if owner_input.is_symlink():
            raise ContractError("OWNER_ROOT_SYMLINK")
        root = owner_input.resolve()
        bundle = Path(bundle_root).absolute()
        bindings, block_id, fixture = bindings_impl(authority_registry_ref, root, map_commitment_ref, bundle, _fixture_boundaries)
        with reservation_manager(root, bindings) as manager:
            handle, is_owner = manager.acquire(lambda: zero_effects(root, bundle), fault=_reservation_fault)
            if not is_owner:
                receipt = reconcile(root, authority_registry_ref, map_commitment_ref, fixture, block_id)
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
                receipt = execute(
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

    def finalize_impl(
        execution_ref: Mapping[str, Any],
        owner_root: Path,
        grade_refs: Mapping[str, Any],
        opening_ref: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        verify_sources()
        return finalize(execution_ref, owner_root, grade_refs, opening_ref)

    return bindings_impl, execute_impl, finalize_impl, verify_sources


_bindings, execute_block, finalize_block, _verify_closed_sources = _build_closed_runtime()
del _build_closed_runtime

__all__ = ["STATUS", "default_run", "execute_block", "finalize_block"]
