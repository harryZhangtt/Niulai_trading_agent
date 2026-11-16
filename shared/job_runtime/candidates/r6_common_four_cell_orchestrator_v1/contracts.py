"""Closed contracts for the disabled provider-free common four-cell orchestrator."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

STATUS = "OPEN_PENDING_EXACT_SUCCESSOR_BINDINGS"
CELL_ORDER = (
    "R6DQ-7F2C91A4",
    "R6DQ-1B8E43D7",
    "R6DQ-C4A7095E",
    "R6DQ-92D6F0B3",
)
CELL_PLANS = (
    (CELL_ORDER[0], 0, "CLAUDE", "CONDITION-X", False, "p0/R6DQ-7F2C91A4"),
    (CELL_ORDER[1], 1, "CODEX", "CONDITION-Y", True, "p0/R6DQ-1B8E43D7"),
    (CELL_ORDER[2], 2, "CLAUDE", "CONDITION-Y", True, "p0/R6DQ-C4A7095E"),
    (CELL_ORDER[3], 3, "CODEX", "CONDITION-X", False, "p0/R6DQ-92D6F0B3"),
)
DESTINATION_IDS = tuple(item[5] for item in CELL_PLANS) + ("evaluation/four-cell-block",)
EFFECT_KEYS = ("provider", "network", "account", "private_state", "email", "business", "host")
PIN_NAMES = (
    "p0_attempt_envelope",
    "evaluation_runner",
    "claude_provider_boundary",
    "codex_provider_boundary",
)
P0_ARGUMENT_NAMES = (
    "cell_id", "blind_addon_label", "checks_enabled", "job_id", "slot_id",
    "attempt_id", "operation_id", "prompt_binding_sha256", "raw_sha256",
    "publication_artifact_sha256", "research_material_sha256", "terminal_state",
    "source_cutoff_sha256",
)

class ContractError(ValueError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ContractError("CANONICAL_JSON_INVALID") from exc


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def exact(value: Any, keys: tuple[str, ...], code: str) -> Mapping[str, Any]:
    require(type(value) is dict and set(value) == set(keys), code)
    return value


def _digest(value: Any, code: str) -> str:
    require(type(value) is str and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value), code)
    return value


def unresolved_pin(value: Any, name: str) -> Mapping[str, Any]:
    value = exact(value, ("path", "api", "sha256", "status"), "PIN_SHAPE_" + name)
    require(type(value["path"]) is str and value["path"], "PIN_PATH_" + name)
    require(type(value["api"]) is str and value["api"], "PIN_API_" + name)
    require(value["sha256"] is None, "PREMATURE_SUCCESSOR_BINDING_" + name)
    require(value["status"] == "UNRESOLVED_BUILD_TIME_PIN", "PIN_STATUS_" + name)
    return value


def validate_grant(value: Any) -> Mapping[str, Any]:
    value = exact(value, (
        "version", "candidate_status", "scope", "activation", "authority_effect",
        "clock_policy", "cell_order", "cells", "limits", "successor_pins",
        "countability_policy", "unknown_policy",
    ), "GRANT_SHAPE")
    require(value["version"] == 1, "GRANT_VERSION")
    require(value["candidate_status"] == STATUS, "GRANT_STATUS")
    require(value["scope"] == "PROVIDER_FREE_FIXTURE_ONLY", "GRANT_SCOPE")
    require(value["activation"] is False and value["authority_effect"] == "NONE", "GRANT_MUST_NOT_AUTHORIZE")
    require(value["clock_policy"] == "NO_LIVE_CLOCK_FIXTURE_ONLY", "GRANT_CLOCK_POLICY")
    require(tuple(value["cell_order"]) == CELL_ORDER, "GRANT_ORDER_DRIFT")
    require(type(value["cells"]) is list and len(value["cells"]) == 4, "GRANT_CELL_COUNT")
    for expected, cell in zip(CELL_PLANS, value["cells"]):
        cell = exact(cell, ("cell_id", "order_index", "provider_port", "blind_addon_label", "checks_enabled", "destination_id"), "CELL_GRANT_SHAPE")
        actual = (cell["cell_id"], cell["order_index"], cell["provider_port"], cell["blind_addon_label"], cell["checks_enabled"], cell["destination_id"])
        require(actual == expected, "CELL_GRANT_DRIFT")
    require(value["limits"] == {"concurrency": 1, "admissions_per_cell": 1, "retries": 0, "replays": 0}, "GRANT_LIMIT_DRIFT")
    pins = exact(value["successor_pins"], PIN_NAMES, "SUCCESSOR_PINS_SHAPE")
    for name in PIN_NAMES:
        unresolved_pin(pins[name], name)
    require(value["countability_policy"] == "ALL_FOUR_OR_NONE_LIVE_ONLY", "COUNTABILITY_POLICY_DRIFT")
    require(value["unknown_policy"] == "FENCE_BLOCK_NO_REPLAY", "UNKNOWN_POLICY_DRIFT")
    return value


def validate_provider_result(value: Any, plan: Mapping[str, Any]) -> Mapping[str, Any]:
    value = exact(value, (
        "version", "cell_id", "order_index", "provider_port", "admission_id",
        "terminal_state", "admission_count", "retry_count", "replay_count",
        "concurrency_observed", "effect_evidence", "p0_payload",
    ), "PROVIDER_RESULT_SHAPE")
    require(value["version"] == 1, "PROVIDER_RESULT_VERSION")
    for key in ("cell_id", "order_index", "provider_port"):
        require(value[key] == plan[key], "PROVIDER_RESULT_" + key.upper() + "_DRIFT")
    require(type(value["admission_id"]) is str and value["admission_id"], "ADMISSION_ID")
    require(value["terminal_state"] in ("PASS", "FAIL", "STOP", "UNKNOWN"), "TERMINAL_STATE")
    require(value["admission_count"] == 1, "ADMISSION_COUNT")
    require(value["retry_count"] == 0, "RETRY_FORBIDDEN")
    require(value["replay_count"] == 0, "REPLAY_FORBIDDEN")
    require(value["concurrency_observed"] == 1, "CONCURRENCY_NOT_ONE")
    effects = exact(value["effect_evidence"], EFFECT_KEYS, "EFFECT_EVIDENCE_SHAPE")
    require(all(effects[key] is False for key in EFFECT_KEYS), "EFFECT_LEAKAGE")
    payload = exact(value["p0_payload"], (
        "job_id", "slot_id", "attempt_id", "operation_id", "prompt_binding_sha256",
        "raw_sha256", "publication_artifact_sha256", "research_material_sha256",
        "terminal_state", "source_cutoff_sha256", "checks_enabled", "blind_addon_label",
    ), "P0_PAYLOAD_SHAPE")
    for key in ("job_id", "slot_id", "attempt_id", "operation_id"):
        require(type(payload[key]) is str and payload[key], "P0_PAYLOAD_" + key.upper())
    for key in ("prompt_binding_sha256", "raw_sha256", "publication_artifact_sha256", "research_material_sha256", "source_cutoff_sha256"):
        _digest(payload[key], "P0_PAYLOAD_" + key.upper())
    require(payload["terminal_state"] == value["terminal_state"], "P0_TERMINAL_DRIFT")
    require(payload["checks_enabled"] is plan["checks_enabled"], "P0_CHECKS_DRIFT")
    require(payload["blind_addon_label"] == plan["blind_addon_label"], "P0_ADDON_DRIFT")
    return value


def validate_p0_handoff(value: Any) -> Mapping[str, Any]:
    value = exact(value, (
        "version", "candidate_status", "target_package", "target_api", "target_pin",
        "cell_id", "order_index", "provider_port", "required_argument_names",
        "argument_values", "admission_receipt_sha256", "effects_executed",
    ), "P0_HANDOFF_SHAPE")
    require(value["version"] == 1 and value["candidate_status"] == STATUS, "P0_HANDOFF_STATUS")
    require(value["target_package"] == "shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1", "P0_TARGET")
    require(value["target_api"] == "execute", "P0_TARGET_API")
    unresolved_pin(value["target_pin"], "p0_attempt_envelope")
    require(value["cell_id"] in CELL_ORDER and value["order_index"] == CELL_ORDER.index(value["cell_id"]), "P0_CELL_ORDER")
    require(value["provider_port"] in ("CLAUDE", "CODEX"), "P0_PROVIDER_PORT")
    require(tuple(value["required_argument_names"]) == P0_ARGUMENT_NAMES, "P0_ARGUMENT_NAMES")
    args = exact(value["argument_values"], P0_ARGUMENT_NAMES, "P0_ARGUMENT_VALUES")
    require(args["cell_id"] == value["cell_id"], "P0_ARGUMENT_CELL")
    _digest(value["admission_receipt_sha256"], "P0_ADMISSION_RECEIPT_SHA")
    require(value["effects_executed"] is False, "P0_EFFECT_EXECUTED")
    return value


def validate_evaluation_handoff(value: Any) -> Mapping[str, Any]:
    value = exact(value, (
        "version", "candidate_status", "target_package", "target_api", "target_pin",
        "cell_order", "p0_handoff_sha256", "completed_cell_count", "all_four_present",
        "partial_comparison", "countable", "effects_executed",
    ), "EVALUATION_HANDOFF_SHAPE")
    require(value["version"] == 1 and value["candidate_status"] == STATUS, "EVALUATION_HANDOFF_STATUS")
    require(value["target_package"] == "shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1", "EVALUATION_TARGET")
    require(value["target_api"] == "execute_block", "EVALUATION_TARGET_API")
    unresolved_pin(value["target_pin"], "evaluation_runner")
    require(tuple(value["cell_order"]) == CELL_ORDER, "EVALUATION_ORDER_DRIFT")
    require(type(value["p0_handoff_sha256"]) is list and len(value["p0_handoff_sha256"]) == value["completed_cell_count"], "EVALUATION_HANDOFF_COUNT")
    for digest in value["p0_handoff_sha256"]:
        _digest(digest, "EVALUATION_P0_SHA")
    all_four = value["completed_cell_count"] == 4
    require(value["all_four_present"] is all_four, "EVALUATION_ALL_FOUR_DERIVATION")
    require(value["partial_comparison"] is False, "PARTIAL_COMPARISON_FORBIDDEN")
    require(value["countable"] is False, "FIXTURE_COUNTABILITY_FORBIDDEN")
    require(value["effects_executed"] is False, "EVALUATION_EFFECT_EXECUTED")
    return value


def validate_block_result(value: Any) -> Mapping[str, Any]:
    value = exact(value, (
        "version", "candidate_status", "scope", "status", "countable", "cell_order",
        "completed_cell_count", "admissions", "p0_handoffs", "evaluation_handoff",
        "unknown_fence", "partial_comparison", "effects_executed",
    ), "BLOCK_RESULT_SHAPE")
    require(value["version"] == 1 and value["candidate_status"] == STATUS, "BLOCK_STATUS")
    require(value["scope"] == "PROVIDER_FREE_FIXTURE_ONLY", "BLOCK_SCOPE")
    require(tuple(value["cell_order"]) == CELL_ORDER, "BLOCK_ORDER_DRIFT")
    require(type(value["admissions"]) is list and type(value["p0_handoffs"]) is list, "BLOCK_LISTS")
    require(value["completed_cell_count"] == len(value["admissions"]) == len(value["p0_handoffs"]), "BLOCK_COMPLETED_COUNT")
    observed = tuple(item.get("cell_id") for item in value["admissions"] if type(item) is dict)
    require(observed == CELL_ORDER[:len(observed)], "BLOCK_ADMISSION_ORDER_DRIFT")
    require(len(observed) == len(set(observed)), "BLOCK_DUPLICATE_ADMISSION")
    for handoff in value["p0_handoffs"]:
        validate_p0_handoff(handoff)
    validate_evaluation_handoff(value["evaluation_handoff"])
    require(value["evaluation_handoff"]["completed_cell_count"] == value["completed_cell_count"], "BLOCK_EVALUATION_COUNT_DRIFT")
    complete = value["completed_cell_count"] == 4 and all(item["terminal_state"] == "PASS" for item in value["admissions"])
    require(value["status"] == ("FIXTURE_COMPLETE_NON_COUNTABLE" if complete else "UNKNOWN_FENCED_INCOMPLETE"), "BLOCK_DERIVED_STATUS")
    require((value["unknown_fence"] is None) if complete else (value["unknown_fence"] is not None), "UNKNOWN_FENCE_DERIVATION")
    if value["unknown_fence"] is not None:
        fence = exact(value["unknown_fence"], ("terminal_cell_id", "terminal_state", "blocked_cell_ids", "replay_allowed"), "UNKNOWN_FENCE_SHAPE")
        require(fence["terminal_state"] == "UNKNOWN" and fence["replay_allowed"] is False, "UNKNOWN_FENCE_INVALID")
        require(tuple(fence["blocked_cell_ids"]) == CELL_ORDER[value["completed_cell_count"]:], "UNKNOWN_BLOCKED_CELLS")
    require(value["countable"] is False and value["partial_comparison"] is False, "FIXTURE_OR_PARTIAL_COUNTABILITY")
    require(value["effects_executed"] is False, "BLOCK_EFFECT_EXECUTED")
    return value
