"""Strict closed contracts for a disabled provider-free same-model OFF/ON trial."""
from __future__ import annotations
import hashlib, json, math, re
from typing import Any, Dict, Iterable, Mapping

class ContractError(ValueError):
    pass

def require(ok: bool, code: str) -> None:
    if not ok:
        raise ContractError(code)

def validate_json_tree(value: Any, code: str = "JSON_VALUE_INVALID", depth: int = 0) -> Any:
    require(depth <= 64, code)
    if value is None or type(value) in (bool, str, int):
        return value
    if type(value) is float:
        require(math.isfinite(value), code); return value
    if type(value) is list:
        for item in value: validate_json_tree(item, code, depth + 1)
        return value
    if type(value) is dict:
        for key, item in value.items():
            require(type(key) is str, code); validate_json_tree(item, code, depth + 1)
        return value
    raise ContractError(code)

def strict_json_loads(text: str, code: str = "JSON_TEXT_INVALID") -> Any:
    require(type(text) is str, code)
    def pairs(items: Any) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in items:
            require(type(key) is str and key not in result, code); result[key] = value
        return result
    try:
        parsed = json.loads(text, object_pairs_hook=pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ContractError(code)))
    except (json.JSONDecodeError, UnicodeError, RecursionError):
        raise ContractError(code) from None
    return validate_json_tree(parsed, code)

def canonical_bytes(value: Any) -> bytes:
    validate_json_tree(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ContractError("CANONICAL_VALUE_INVALID") from None

def sha256_bytes(value: bytes) -> str:
    require(type(value) is bytes, "BYTES_REQUIRED")
    return hashlib.sha256(value).hexdigest()

def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))

def exact(value: Any, keys: Iterable[str], code: str) -> Mapping[str, Any]:
    require(type(value) is dict and set(value) == set(keys), code); return value

SHA = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
MODEL_ID = "claude-fable-5-1"
CELL_ORDER = ("F51DQ-6E3A9C17", "F51DQ-B4D208FE")
CELL_TREATMENT = {CELL_ORDER[0]: False, CELL_ORDER[1]: True}
TERMINALS = ("PASS", "FAIL", "STOP", "MALFORMED", "MISSING", "UNKNOWN")
DISPOSITIONS = {
    "PASS": "RETAIN_PASS_NO_PUBLICATION", "FAIL": "RETAIN_FAIL_NO_PUBLICATION",
    "STOP": "RETAIN_STOP_NO_PUBLICATION", "MALFORMED": "RETAIN_MALFORMED_NO_PUBLICATION",
    "MISSING": "RETAIN_MISSING_NO_PUBLICATION", "UNKNOWN": "RETAIN_UNKNOWN_NO_PUBLICATION",
}
DQ_CHECKS = ("schema_types", "duplicate_keys", "nonfinite_values", "evidence_completeness")
FROZEN_INPUTS = {
    "payload_sha256": "26d9a937f50dc22dade3251831e7860b4a7188c3001d5717ed4aac4d4ccac01a",
    "source_cutoff_sha256": "32f28a6cea0b1053321a52782abe40d6fd8a2d58b95bb954f90794ec5b733072",
    "prompt_sha256": "35a99586bd30c9ca70b0f5fb22dbf60e915f2dfcaf4d1be15fcfe9b9ea630c8e",
    "rubric_sha256": "81069b2ce57f30e56d70e7a2edd4672991838ebce1e2369b48effb8adde53d8f",
}
LIMITS = {"attempts": 1, "retries": 0, "replays": 0, "status_queries": 0,
          "tools": 0, "web": 0, "subagents": 0, "fallbacks": 0}

def digest(value: Any, code: str) -> str:
    require(type(value) is str and SHA.fullmatch(value) is not None, code); return value

def identity(value: Any, code: str) -> str:
    require(type(value) is str and ID.fullmatch(value) is not None, code); return value

def validate_plan(value: Any) -> Mapping[str, Any]:
    value = exact(value, ("version", "cell_id", "order_index", "model", "dq_enabled", "inputs", "limits"), "PLAN_SHAPE")
    require(type(value["version"]) is int and value["version"] == 1, "PLAN_VERSION")
    require(value["cell_id"] in CELL_ORDER, "PLAN_CELL")
    require(type(value["order_index"]) is int and value["order_index"] == CELL_ORDER.index(value["cell_id"]), "PLAN_ORDER")
    require(value["model"] == MODEL_ID, "PLAN_MODEL")
    require(type(value["dq_enabled"]) is bool and value["dq_enabled"] is CELL_TREATMENT[value["cell_id"]], "PLAN_TREATMENT")
    require(value["inputs"] == FROZEN_INPUTS and canonical_bytes(value["inputs"]) == canonical_bytes(FROZEN_INPUTS), "PLAN_INPUT_DRIFT")
    require(value["limits"] == LIMITS and canonical_bytes(value["limits"]) == canonical_bytes(LIMITS), "PLAN_LIMIT_DRIFT")
    return value

def validate_check(value: Any, enabled: bool) -> Mapping[str, Any]:
    value = exact(value, ("name", "status", "code"), "CHECK_SHAPE")
    require(value["name"] in DQ_CHECKS, "CHECK_NAME")
    identity(value["code"], "CHECK_CODE")
    allowed = ("PASS", "FAIL", "UNKNOWN") if enabled else ("NOT_RUN_TREATMENT_DISABLED",)
    require(value["status"] in allowed, "CHECK_STATUS")
    return value

def validate_raw_ref(value: Any) -> Mapping[str, Any]:
    value = exact(value, ("name", "sha256", "bytes", "owner_private", "public"), "RAW_REF_SHAPE")
    require(value["name"] == "model-terminal.raw", "RAW_REF_NAME"); digest(value["sha256"], "RAW_REF_SHA")
    require(type(value["bytes"]) is int and 0 <= value["bytes"] <= 1048576, "RAW_REF_BYTES")
    require(value["owner_private"] is True and value["public"] is False, "RAW_REF_PRIVACY")
    return value

def validate_cell(value: Any) -> Mapping[str, Any]:
    keys = ("version", "plan", "plan_sha256", "plan_echo_sha256", "attempt_id", "terminal_state",
            "attempt_count", "retry_count", "replay_count", "status_query_count", "tool_count", "web_count",
            "subagent_count", "fallback_count", "raw_ref", "raw_committed_before_decision", "dq_checks",
            "disposition", "denominator_included", "publication", "validity_errors")
    value = exact(value, keys, "CELL_SHAPE"); plan = validate_plan(value["plan"])
    require(type(value["version"]) is int and value["version"] == 1, "CELL_VERSION")
    digest(value["plan_sha256"], "PLAN_SHA"); digest(value["plan_echo_sha256"], "PLAN_ECHO_SHA")
    require(value["plan_sha256"] == sha256_json(plan), "PLAN_SHA_MISMATCH")
    identity(value["attempt_id"], "ATTEMPT_ID"); require(value["terminal_state"] in TERMINALS, "TERMINAL")
    counts = ("attempt_count", "retry_count", "replay_count", "status_query_count", "tool_count", "web_count", "subagent_count", "fallback_count")
    require(all(type(value[k]) is int and value[k] >= 0 for k in counts), "COUNT_TYPE")
    require(value["attempt_count"] in (0, 1) and all(value[k] == 0 for k in counts[1:]), "ZERO_EFFECT_LIMIT")
    validate_raw_ref(value["raw_ref"]); require(value["raw_committed_before_decision"] is True, "RAW_ORDER")
    require(type(value["dq_checks"]) is list and len(value["dq_checks"]) == len(DQ_CHECKS), "CHECK_COUNT")
    require(tuple(c.get("name") for c in value["dq_checks"] if type(c) is dict) == DQ_CHECKS, "CHECK_ORDER")
    for check in value["dq_checks"]: validate_check(check, plan["dq_enabled"])
    require(value["disposition"] == DISPOSITIONS[value["terminal_state"]], "DISPOSITION")
    require(value["denominator_included"] is True, "DENOMINATOR")
    publication = exact(value["publication"], ("status", "attempts", "unknown_fenced"), "PUBLICATION_SHAPE")
    require(publication == {"status": "SUPPRESSED_PROVIDER_FREE", "attempts": 0,
                            "unknown_fenced": value["terminal_state"] == "UNKNOWN"}, "PUBLICATION_FENCE")
    require(type(value["validity_errors"]) is list and all(type(x) is str for x in value["validity_errors"]), "VALIDITY_ERRORS")
    derived = []
    if value["plan_echo_sha256"] != value["plan_sha256"]: derived.append("PLAN_ECHO_DRIFT")
    if value["terminal_state"] == "STOP" and value["attempt_count"] != 0: derived.append("STOP_NOT_ZERO_ATTEMPT")
    elif value["terminal_state"] != "STOP" and value["attempt_count"] != 1: derived.append("ATTEMPT_COUNT_INVALID")
    if plan["dq_enabled"] and any(c["status"] != "PASS" for c in value["dq_checks"]): derived.append("DQ_NOT_ALL_PASS")
    require(value["validity_errors"] == sorted(derived), "VALIDITY_NOT_DERIVED")
    return value

def validate_bundle(value: Any) -> Mapping[str, Any]:
    value = exact(value, ("version", "cell", "raw_body_ascii", "raw_sha256", "decision_sha256", "bundle_sha256"), "BUNDLE_SHAPE")
    require(type(value["version"]) is int and value["version"] == 1, "BUNDLE_VERSION")
    cell = validate_cell(value["cell"]); require(type(value["raw_body_ascii"]) is str, "RAW_BODY_TYPE")
    raw = value["raw_body_ascii"].encode("ascii"); require(sha256_bytes(raw) == value["raw_sha256"] == cell["raw_ref"]["sha256"], "RAW_BINDING")
    require(len(raw) == cell["raw_ref"]["bytes"], "RAW_LENGTH")
    decision = dict(value); observed_bundle = decision.pop("bundle_sha256"); observed_decision = decision.pop("decision_sha256")
    require(observed_decision == sha256_json(decision), "DECISION_DIGEST")
    decision["decision_sha256"] = observed_decision
    require(observed_bundle == sha256_json(decision), "BUNDLE_DIGEST")
    return value

def validate_result(value: Any) -> Mapping[str, Any]:
    value = exact(value, ("version", "scope", "model", "cell_order", "cells", "denominator_count", "status", "countable", "publication_attempts", "symmetry_sha256"), "RESULT_SHAPE")
    require(value["version"] == 1 and type(value["version"]) is int and value["scope"] == "PROVIDER_FREE_FIXTURE", "RESULT_VERSION_SCOPE")
    require(value["model"] == MODEL_ID and tuple(value["cell_order"]) == CELL_ORDER, "RESULT_BINDING")
    require(type(value["cells"]) is list and len(value["cells"]) == 2, "RESULT_CELL_COUNT")
    require(tuple(c.get("plan", {}).get("cell_id") for c in value["cells"] if type(c) is dict) == CELL_ORDER, "RESULT_CELL_ORDER")
    for cell in value["cells"]: validate_cell(cell)
    require(value["denominator_count"] == 2 and type(value["denominator_count"]) is int, "RESULT_DENOMINATOR")
    require(value["publication_attempts"] == 0 and type(value["publication_attempts"]) is int, "RESULT_PUBLICATION")
    require(value["countable"] is False and value["status"] == "FIXTURE_ONLY_PENDING_INDEPENDENT_REVIEW", "RESULT_NONCOUNTABLE")
    digest(value["symmetry_sha256"], "SYMMETRY_SHA")
    normalized = [{k: v for k, v in cell["plan"].items() if k not in ("cell_id", "order_index", "dq_enabled")} for cell in value["cells"]]
    require(normalized[0] == normalized[1], "PLAN_ASYMMETRY")
    require(value["symmetry_sha256"] == sha256_json(normalized), "SYMMETRY_DIGEST")
    return value

__all__ = ["CELL_ORDER", "CELL_TREATMENT", "DISPOSITIONS", "DQ_CHECKS", "FROZEN_INPUTS", "LIMITS", "MODEL_ID", "TERMINALS", "ContractError", "canonical_bytes", "sha256_bytes", "sha256_json", "strict_json_loads", "validate_bundle", "validate_cell", "validate_json_tree", "validate_plan", "validate_result"]
