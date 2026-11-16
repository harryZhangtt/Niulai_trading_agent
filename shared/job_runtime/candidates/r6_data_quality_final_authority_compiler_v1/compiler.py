"""Fixed-root, source-pinned, DENY-only final-authority compiler skeleton.

No caller-selected trust root, registry, grant, review, clock, policy, or output
path exists.  No artifact is written.  Even a complete pin set remains denied
until a separately owned authority-last adoption artifact is exact-pinned and
this disabled candidate is replaced by a separately reviewed implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

STATUS = "DISABLED_AUTHORITY_COMPILER_PENDING_FIXED_PINS_AND_FRESH_REVIEW"
DENY = "DENY"
_WORKSPACE_ROOT = Path(__file__).absolute().parents[4]
_EFFECTS = {
    "account": 0, "business": 0, "bytedcli": 0, "credential": 0,
    "email": 0, "host": 0, "network": 0, "provider": 0,
    "publication": 0, "scheduler": 0,
}


class ContractError(ValueError):
    """A fixed pin or closed contract failed verification."""


@dataclass(frozen=True)
class _Pin:
    name: str
    path: str
    bytes: Optional[int]
    sha256: Optional[str]
    mode: int
    expectations: Tuple[Tuple[Tuple[str, ...], Any], ...] = ()
    review_of: Optional[str] = None
    conditional: Optional[str] = None


def _expect(path: str, value: Any) -> Tuple[Tuple[str, ...], Any]:
    return tuple(path.split(".")), value


_CURRENT_PINS: Tuple[_Pin, ...] = (
    _Pin("user_no_bytedcli_authorization", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-four-cell-user-authorization-v4-no-bytedcli-addendum.json", 2920, "4c00d39ff71ec20be18f91f8882a58f0ac54ae83a571940de060b44849a41dec", 0o600, (_expect("status", "AUTHORIZED_EXECUTION_SCOPE_PENDING_SAFETY_VALIDITY_AND_ATTRIBUTION_GATES"), _expect("tool_constraint.bytedcli_allowed", False))),
    _Pin("user_no_bytedcli_authorization_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-four-cell-user-authorization-v4-no-bytedcli-addendum-independent-review-fable-20261111.json", 8947, "fbdc1eb36dcb04af06c42edf2a809925508306e80fea4192d5c113a949df8ac1", 0o600, (_expect("verdict", "CLEAN_NO_BYTEDCLI_ADDENDUM"),), "user_no_bytedcli_authorization"),
    _Pin("exact_input_v3", "tuning/architecture/r6_data_quality_exact_input_binding_fable_v3/current-input-manifest-v3.json", 44891, "ed63dec9a5f386a095ffee43f84cb2c6130143579251918b4d6d4c0ffc187f1a", 0o600),
    _Pin("exact_input_v3_schema", "tuning/architecture/r6_data_quality_exact_input_binding_fable_v3/input-manifest-v3.schema.json", 18567, "66a2d49fb336682763f0732cd5ae9d44f087b1bba322590c0b2e0acc2d72cd4b", 0o600),
    _Pin("exact_input_v3_clean_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-exact-input-binding-fable-v3-independent-review-20261111-8e9a8076.json", 12726, "ef6f127291528442ddee27f25a9be71f1388a4ed9674978a870252ccb51bdae6", 0o600, (_expect("status", "CLEAN_EXACT_INPUT_BINDING_V3"), _expect("verdict", "CLEAN_EXACT_INPUT_BINDING_V3")), "exact_input_v3"),
    _Pin("evaluation_v3", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-evaluation-contract-v3.json", 9944, "8bef52f4f1c7511ec8897b17dbee2f542b0a822acaf22ebbe2e0e267d7c6714d", 0o644),
    _Pin("evaluation_v3_producer", "tuning/architecture/r6_data_quality_2x2_evaluation_v3/producer-verification-v3.json", 2588, "2df4cae89b8942a8eb38b766608381f4bc41aeb8f4c984a9d32aa677068718ea", 0o644, (_expect("verdict", "PASS"), _expect("activation", False))),
    _Pin("evaluation_v3_clean_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-evaluation-v3-independent-review.json", 10585, "da36e2ae03c7a74ef7b5dce91eb7fc7e627b3cb431a0064c6efde37ef744b429", 0o644, (_expect("status", "CLEAN_PROVIDER_FREE_2X2_EVALUATION_V3"), _expect("verdict", "CLEAN_PROVIDER_FREE_2X2_EVALUATION_V3")), "evaluation_v3"),
    _Pin("tool_policy_v7_closure", "tuning/architecture/r6_frozen_tool_web_allowance_v7/source-closure-v7.json", 7078, "854d663f168ff1b43f9dbb770fdbbd0b2d297b35fc4b3d3a65bed436de26944f", 0o644, (_expect("activation", False),)),
    _Pin("tool_policy_v7_producer", "tuning/architecture/r6_frozen_tool_web_allowance_v7/producer-verification-v7.json", 6204, "b023cb373243bc3be90027877e372040ef2de1fdd6edd13b9bb18ddc08ca30ce", 0o644, (_expect("activation", False),)),
    _Pin("tool_policy_v7_clean_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-frozen-tool-web-allowance-v7-independent-review-fable-20261112-8e9a8076.json", 11817, "10a073d131cee84e9e7d439b9e19b015c323d68d991919ad5ff6e3daf980e150", 0o644, (_expect("verdict", "CLEAN_TOOL_POLICY_V7"),), "tool_policy_v7_closure"),
    _Pin("codex_live_catalog_membership", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-codex-live-catalog-membership-execution-evidence-receipt-fable-20261111-8e9a8076.json", 3552, "4904c8cb0400f7e89985f1cb0237937efa06a9f1092f08dfa08070a4ab76d265", 0o600, (_expect("status", "CLEAN_LIVE_CODEX_CATALOG_MEMBERSHIP"),)),
    _Pin("codex_live_catalog_membership_clean_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-codex-live-catalog-membership-independent-review-fable-20261111-8e9a8076.json", 6290, "bd5d57561e911d77d6ada1e97b67baa915f6e83330dd3a29b4bf7c8ba7d0799d", 0o600, (_expect("status", "CLEAN_LIVE_CODEX_CATALOG_MEMBERSHIP"),), "codex_live_catalog_membership"),
    _Pin("current_binary_identities", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-provider-binary-identity-current-20261111.json", 1788, "d1307d8dc05cfb543ac2abc3e044f6de390d1bd7bd017538cbfa2a527a43d848", 0o600),
    _Pin("current_binary_identities_clean_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-provider-binary-identity-current-20261111-independent-review-fable-20261111T085348Z.json", 5166, "3af2710961a409f3c50077bf919b2c851422b185955572355254141d8cd5b40b", 0o600, (_expect("verdict", "CLEAN_LOCAL_FILE_IDENTITY_ONLY"),), "current_binary_identities"),
    _Pin("codex_v6_clean_pending_p0_v10", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-codex-live-integration-v6-independent-review-clean-fable-20261113-8e9a8076.json", 11249, "a612f581be86741f49be7ee2e511fdf9526b2ac6481da65a3e4bd069e602221b", 0o644, (_expect("verdict", "CLEAN_CODEX_LIVE_BOUNDARY_V6_PENDING_P0_V10"),)),
    _Pin("claude_v9_evidence_reseal_clean_pending_p0_v10", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-claude-live-integration-v9-independent-review-clean-fable-20261113-8e9a8076-evidence-reseal.json", 10250, "fb7fbe185b6b403aa67cd8bfeb64bdc9baf636c7788b39cd6fba6258f48e515f", 0o644, (_expect("verdict", "CLEAN_CLAUDE_LIVE_BOUNDARY_V9_EVIDENCE_RESEAL_PENDING_P0_V10"), _expect("countable", False))),
)

# These paths are fixed, but bytes/SHA values cannot be invented.  A null digest
# is itself a missing pin and therefore a permanent DENY in this candidate.
_BLOCKER_PINS: Tuple[_Pin, ...] = (
    _Pin("runner_v8_open_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-runner-v8-independent-review-fable-20261112-8e9a8076-open.json", 6255, "145265647df2a9231d7b64f3b7c70c7266403b38cb15ad98e38deef3a6d588f5", 0o644, (_expect("verdict", "OPEN"), _expect("activation", False), _expect("countable", False))),
    _Pin("blind_map_v5_open_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/claude-r6-data-quality-blind-map-commitment-v5-independent-review-open-v1-fable-20261113.json", 23467, "a76216d40b8af7617e7169f0969ab15bd69e3333dce6b6e9543af77612f783e8", 0o644, (_expect("verdict", "OPEN"), _expect("finding_count", 13), _expect("activation", False), _expect("countable", False))),
    _Pin("claude_v8_open_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-claude-live-integration-v8-independent-review-open-fable-20261113-8e9a8076.json", 10896, "65e425cab9b0fd7ed9381e0f8019360fad0e5c0f2da432c3b5c4e4c27c16df0d", 0o644, (_expect("verdict", "OPEN"),)),
    _Pin("runner_v2_open_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-runner-v2-independent-review-fable-20261113-8e9a8076-open.json", 13206, "c2669dec8fd1e32f616a6d97ce1e75f6de9a736d106814db1c99f8328215cff1", 0o644, (_expect("status", "OPEN_RUNNER_V2_CONCURRENCY_SUCCESSOR_PENDING_P0_V10"), _expect("verdict", "OPEN"), _expect("activation", False), _expect("countable", False))),
)


_FUTURE_PINS: Tuple[_Pin, ...] = (
    _Pin("blind_map_v6_clean", "tuning/architecture/r6_data_quality_blind_map_commitment_v6/independent-review-v6-clean.json", None, None, 0o644, (_expect("verdict", "CLEAN_BLIND_MAP_V6"),)),
    _Pin("p0_v10_clean", "tuning/architecture/r6_data_quality_attempt_envelope_v2/independent-review-p0-v10-clean.json", None, None, 0o644, (_expect("verdict", "CLEAN_P0_V10"),)),
    _Pin("runner_v3_open_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-runner-v3-independent-review-fable-20261113-8e9a8076-open.json", None, None, 0o644, (_expect("verdict", "OPEN"),)),
    _Pin("runner_v4_clean", "tuning/architecture/r6_data_quality_2x2_runner_v4/independent-review-v4-clean.json", None, None, 0o644, (_expect("verdict", "CLEAN_RUNNER_V4"),)),
    _Pin("codex_v6_p0_v10_clean", "tuning/architecture/r6_one_off_codex_live_integration_v1/independent-review-v6-p0-v10-clean.json", None, None, 0o644, (_expect("verdict", "CLEAN_CODEX_V6_P0_V10"),)),
    _Pin("common_orchestrator_v3_clean", "tuning/architecture/r6_common_four_cell_orchestrator_v3/independent-review-v3-clean.json", None, None, 0o644, (_expect("verdict", "CLEAN_COMMON_ORCHESTRATOR_V3"),)),
    _Pin("execution_window_final_clean", "tuning/architecture/r6_common_execution_window_v1/independent-review-v1-final-clean.json", None, None, 0o644, (_expect("verdict", "CLEAN_EXECUTION_WINDOW_V1_FINAL"),)),
    _Pin("final_block_grant", "tuning/architecture/r6_data_quality_final_authority_adoption_v1/final-block-grant-v1.json", None, None, 0o600),
    _Pin("final_block_grant_clean_review", "tuning/architecture/r6_data_quality_final_authority_adoption_v1/final-block-grant-review-v1.json", None, None, 0o600, (_expect("verdict", "CLEAN_FINAL_BLOCK_GRANT"),), "final_block_grant"),
    _Pin("final_cell_grant_r6dq_7f2c91a4", "tuning/architecture/r6_data_quality_final_authority_adoption_v1/final-cell-grant-r6dq-7f2c91a4-v1.json", None, None, 0o600),
    _Pin("final_cell_grant_r6dq_7f2c91a4_clean_review", "tuning/architecture/r6_data_quality_final_authority_adoption_v1/final-cell-grant-r6dq-7f2c91a4-review-v1.json", None, None, 0o600, (_expect("verdict", "CLEAN_FINAL_CELL_GRANT"),), "final_cell_grant_r6dq_7f2c91a4"),
    _Pin("final_cell_grant_r6dq_1b8e43d7", "tuning/architecture/r6_data_quality_final_authority_adoption_v1/final-cell-grant-r6dq-1b8e43d7-v1.json", None, None, 0o600),
    _Pin("final_cell_grant_r6dq_1b8e43d7_clean_review", "tuning/architecture/r6_data_quality_final_authority_adoption_v1/final-cell-grant-r6dq-1b8e43d7-review-v1.json", None, None, 0o600, (_expect("verdict", "CLEAN_FINAL_CELL_GRANT"),), "final_cell_grant_r6dq_1b8e43d7"),
    _Pin("final_cell_grant_r6dq_c4a7095e", "tuning/architecture/r6_data_quality_final_authority_adoption_v1/final-cell-grant-r6dq-c4a7095e-v1.json", None, None, 0o600),
    _Pin("final_cell_grant_r6dq_c4a7095e_clean_review", "tuning/architecture/r6_data_quality_final_authority_adoption_v1/final-cell-grant-r6dq-c4a7095e-review-v1.json", None, None, 0o600, (_expect("verdict", "CLEAN_FINAL_CELL_GRANT"),), "final_cell_grant_r6dq_c4a7095e"),
    _Pin("final_cell_grant_r6dq_92d6f0b3", "tuning/architecture/r6_data_quality_final_authority_adoption_v1/final-cell-grant-r6dq-92d6f0b3-v1.json", None, None, 0o600),
    _Pin("final_cell_grant_r6dq_92d6f0b3_clean_review", "tuning/architecture/r6_data_quality_final_authority_adoption_v1/final-cell-grant-r6dq-92d6f0b3-review-v1.json", None, None, 0o600, (_expect("verdict", "CLEAN_FINAL_CELL_GRANT"),), "final_cell_grant_r6dq_92d6f0b3"),
    _Pin("human_registry_authentic", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-human-grader-registry-subject-v1.json", None, None, 0o600, (_expect("status", "HUMAN_SIGNED_ATTESTATION"),)),
    _Pin("human_registry_authentic_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-human-grader-registry-subject-v1-independent-review.json", None, None, 0o600, (_expect("status", "CLEAN"),), "human_registry_authentic"),
    _Pin("g1_authentic", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-human-grader-g1-role-grant-subject-v1.json", None, None, 0o600, (_expect("status", "HUMAN_SIGNED_ATTESTATION"),)),
    _Pin("g1_authentic_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-human-grader-g1-role-grant-subject-v1-independent-review.json", None, None, 0o600, (_expect("status", "CLEAN"),), "g1_authentic"),
    _Pin("g2_authentic", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-human-grader-g2-role-grant-subject-v1.json", None, None, 0o600, (_expect("status", "HUMAN_SIGNED_ATTESTATION"),)),
    _Pin("g2_authentic_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-human-grader-g2-role-grant-subject-v1-independent-review.json", None, None, 0o600, (_expect("status", "CLEAN"),), "g2_authentic"),
    _Pin("g3_authentic", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-human-grader-g3-role-grant-subject-v1.json", None, None, 0o600, (_expect("status", "HUMAN_SIGNED_ATTESTATION"),), conditional="G3_TRIGGERED"),
    _Pin("g3_authentic_review", "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-human-grader-g3-role-grant-subject-v1-independent-review.json", None, None, 0o600, (_expect("status", "CLEAN"),), "g3_authentic", "G3_TRIGGERED"),
    _Pin("authority_last_adoption", "tuning/architecture/r6_data_quality_final_authority_adoption_v1/authority-last-adoption-review-v1.json", None, None, 0o644, (_expect("verdict", "CLEAN_AUTHORITY_LAST_ADOPTION"),)),
)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


def _pairs(items: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in items:
        _require(key not in out, "DUPLICATE_JSON_KEY")
        out[key] = value
    return out


def _secure_read(root: Path, pin: _Pin) -> Mapping[str, Any]:
    _require(root == _WORKSPACE_ROOT, "CALLER_ROOT_FORBIDDEN")
    root_stat = os.lstat(str(root))
    _require(stat.S_ISDIR(root_stat.st_mode) and not stat.S_ISLNK(root_stat.st_mode), "ROOT_NOT_FIXED_DIRECTORY")
    _require(root_stat.st_uid == os.getuid(), "ROOT_OWNER_DRIFT")
    parts = pin.path.split("/")
    _require(parts and all(part not in ("", ".", "..") for part in parts) and "\\" not in pin.path, "PIN_PATH_INVALID")
    dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    opened = []
    try:
        fd = os.open(str(root), dir_flags)
        opened.append(fd)
        for part in parts[:-1]:
            fd = os.open(part, dir_flags, dir_fd=fd)
            opened.append(fd)
            item = os.fstat(fd)
            _require(stat.S_ISDIR(item.st_mode) and item.st_uid == os.getuid(), "PIN_PARENT_INVALID")
        fd = os.open(parts[-1], file_flags, dir_fd=fd)
        opened.append(fd)
        item = os.fstat(fd)
        _require(stat.S_ISREG(item.st_mode), "PIN_NOT_REGULAR")
        _require(item.st_uid == os.getuid(), "PIN_OWNER_DRIFT")
        _require(stat.S_IMODE(item.st_mode) == pin.mode, "PIN_MODE_DRIFT")
        chunks = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
    except FileNotFoundError as exc:
        raise ContractError("PIN_ABSENT") from exc
    except OSError as exc:
        raise ContractError("PIN_NOFOLLOW_OR_IO") from exc
    finally:
        for fd in reversed(opened):
            try:
                os.close(fd)
            except OSError:
                pass
    _require(pin.bytes is not None and pin.sha256 is not None, "PIN_DIGEST_NOT_ADOPTED")
    _require(len(raw) == pin.bytes, "PIN_BYTES_DRIFT")
    _require(hashlib.sha256(raw).hexdigest() == pin.sha256, "PIN_SHA256_DRIFT")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("PIN_JSON_INVALID") from exc
    _require(type(value) is dict, "PIN_JSON_NOT_OBJECT")
    for path, expected in pin.expectations:
        actual: Any = value
        for key in path:
            _require(type(actual) is dict and key in actual, "PIN_STATUS_FIELD_MISSING")
            actual = actual[key]
        _require(actual == expected, "PIN_STATUS_NOT_CLEAN")
    return value


def _g3_required(evaluation: Mapping[str, Any]) -> bool:
    """Derive G3 only from the fixed evaluation contract; callers cannot select it."""
    grading = evaluation.get("grading")
    if type(grading) is dict and grading.get("g3_triggered") is True:
        return True
    return False


def _missing(pin: _Pin, reason: str) -> Dict[str, Any]:
    return {
        "name": pin.name,
        "path": pin.path,
        "required_bytes": pin.bytes,
        "required_sha256": pin.sha256,
        "required_mode": format(pin.mode, "04o"),
        "review_of": pin.review_of,
        "conditional": pin.conditional,
        "reason": reason,
    }


def compile_deny_report() -> Dict[str, Any]:
    """Verify fixed pins and return a DENY report; never issue or write authority."""
    verified = []
    missing = []
    values: Dict[str, Mapping[str, Any]] = {}
    for pin in _CURRENT_PINS:
        try:
            values[pin.name] = _secure_read(_WORKSPACE_ROOT, pin)
            verified.append(pin.name)
        except (ContractError, OSError) as exc:
            missing.append(_missing(pin, str(exc) or type(exc).__name__))
    for pin in _BLOCKER_PINS:
        try:
            _secure_read(_WORKSPACE_ROOT, pin)
            missing.append(_missing(pin, "VERIFIED_OPEN_BLOCKER_NOT_AUTHORITY"))
        except (ContractError, OSError) as exc:
            missing.append(_missing(pin, str(exc) or type(exc).__name__))
    g3 = _g3_required(values.get("evaluation_v3", {}))
    for pin in _FUTURE_PINS:
        if pin.conditional == "G3_TRIGGERED" and not g3:
            continue
        reason = "PIN_DIGEST_NOT_ADOPTED"
        try:
            if pin.bytes is not None and pin.sha256 is not None:
                _secure_read(_WORKSPACE_ROOT, pin)
                verified.append(pin.name)
                continue
            if not (_WORKSPACE_ROOT / pin.path).exists():
                reason = "ARTIFACT_ABSENT_AND_PIN_DIGEST_NOT_ADOPTED"
        except (ContractError, OSError) as exc:
            reason = str(exc) or type(exc).__name__
        missing.append(_missing(pin, reason))
    missing.sort(key=lambda item: item["name"])
    return {
        "version": "r6-data-quality-final-authority-deny-report-v1",
        "status": STATUS,
        "decision": DENY,
        "activation": False,
        "authority_issued": False,
        "countable": False,
        "provider_free": True,
        "all_or_nothing_countability": "DENY_UNLESS_ALL_FOUR_VALID_UNDER_SEPARATE_AUTHORITY_LAST_ADOPTION",
        "cell_order": ["R6DQ-7F2C91A4", "R6DQ-1B8E43D7", "R6DQ-C4A7095E", "R6DQ-92D6F0B3"],
        "g3_required": g3,
        "verified_pin_names": sorted(verified),
        "missing_pin_count": len(missing),
        "missing_pins": missing,
        "effects": dict(_EFFECTS),
    }


def main() -> int:
    print(json.dumps(compile_deny_report(), sort_keys=True, separators=(",", ":")))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
