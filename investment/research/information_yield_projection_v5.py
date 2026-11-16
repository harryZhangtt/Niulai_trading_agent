"""Custody-only, fixed-root read projection for additive EIY v5 publications."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from shared.research_sources.artifacts import ROOT
from shared.research_sources.information_yield_v5_contracts import (
    ArtifactRefV5,
    EvaluationContextV5,
    InformationYieldV5ContractError,
    canonical_relative_path_v5,
    digest_v5,
    resolve_workspace_path_v5,
)
from tuning.evals.information_fetch.information_yield.policy_v5 import (
    CANONICAL_GATE_ORDER_V5,
    CANONICAL_METRIC_POLICY_V5_SHA256,
    GATE_RECORD_FIELDS_V5,
    GATE_SPECS_V5,
    canonical_policy_ref_v5,
)

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
SHA = re.compile(r"^[a-f0-9]{64}$")
FORBIDDEN = re.compile(
    r"(?:^|_)(?:raw(?:_result)?|payload|prompt|credentials?|auth(?:entication|orization)?|"
    r"token|secret|private|path|quote|exception|password|api_?key|access_?key)(?:$|_)",
    re.I,
)
PUBLICATION_ROOT = ROOT / "tuning/runtime/information-yield-v5"
SCHEMA_ROOT = ROOT / "shared/research_sources/schemas"
MAX_INDEX_BYTES = 64 * 1024
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 512 * 1024
GATE_NAMES = tuple(CANONICAL_GATE_ORDER_V5)
GATE_SPECS = tuple(dict(spec) for spec in GATE_SPECS_V5)
GATE_FIELDS = set(GATE_RECORD_FIELDS_V5)
CASE_FIELDS = {
    "case_id", "issuer_id", "window_id", "evidence_level", "split", "arm_order",
    "request_sha256", "fact_sha256", "delta_r", "delta_d", "arms", "hard_failure_codes",
}
ARM_FIELDS = {"richness", "depth", "precision", "wall_seconds", "trace"}
TRACE_FIELDS = {"complete", "credited", "unjudged"}


class ProjectionV5Error(ValueError):
    def __init__(self, code: str, exit_code: int = 1):
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ProjectionV5Error("INVALID_INFORMATION_YIELD_V5_QUERY", 2)


def _fail(code: str, exit_code: int = 1) -> None:
    raise ProjectionV5Error(code, exit_code)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode()
    except (TypeError, ValueError):
        _fail("EIY_PROJECTION_V5_PRIVATE_FIELD")


def _digest(value: Any) -> str:
    return digest_v5(value)


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        _fail("EIY_PROJECTION_V5_IDENTITY_CONFLICT", 4)
    return value


def _sha(value: Any, code: str) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        _fail(code, 4)
    return value


def _exact(value: Any, keys: set[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        _fail(code, 4)
    return value


def _schema(name: str) -> Mapping[str, Any]:
    try:
        value = json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectionV5Error("EIY_PROJECTION_V5_AUTHORITY_MISMATCH", 4) from error
    if not isinstance(value, Mapping):
        _fail("EIY_PROJECTION_V5_AUTHORITY_MISMATCH", 4)
    return value


def _validate_schema(value: Any, name: str, code: str) -> None:
    try:
        Draft202012Validator(_schema(name)).validate(value)
    except Exception as error:
        raise ProjectionV5Error(code, 4) from error


def _public(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        _fail("EIY_PROJECTION_V5_PRIVATE_FIELD", 4)
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and (value != value or abs(value) == float("inf")):
            _fail("EIY_PROJECTION_V5_PRIVATE_FIELD", 4)
        if isinstance(value, str) and len(value.encode("utf-8")) > MAX_OUTPUT_BYTES:
            _fail("EIY_PROJECTION_V5_OUTPUT_LIMIT", 4)
        return value
    if isinstance(value, list):
        if len(value) > 256:
            _fail("EIY_PROJECTION_V5_PRIVATE_FIELD", 4)
        return [_public(item, depth + 1) for item in value]
    if not isinstance(value, Mapping) or len(value) > 128:
        _fail("EIY_PROJECTION_V5_PRIVATE_FIELD", 4)
    output: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or len(key) > 64 or FORBIDDEN.search(key):
            _fail("EIY_PROJECTION_V5_PRIVATE_FIELD", 4)
        output[key] = _public(item, depth + 1)
    return output


def _publication_ref_root() -> str:
    try:
        workspace = ROOT.resolve(strict=True)
        if workspace != ROOT or not PUBLICATION_ROOT.is_absolute() or not PUBLICATION_ROOT.is_relative_to(ROOT):
            _fail("EIY_PROJECTION_V5_INDEX_INVALID", 4)
        relative = PUBLICATION_ROOT.relative_to(ROOT).as_posix()
        canonical_relative_path_v5(relative, "EIY_PROJECTION_V5_INDEX_INVALID")
        return relative
    except (OSError, ValueError, InformationYieldV5ContractError) as error:
        raise ProjectionV5Error("EIY_PROJECTION_V5_INDEX_INVALID", 4) from error


def _read_relative_bytes(relative: str, maximum: int, code: str, *, missing_code: str | None = None) -> bytes:
    try:
        canonical_relative_path_v5(relative, code)
        expected = resolve_workspace_path_v5(relative, ROOT, code)
        parts = PurePosixPath(relative).parts
        root_fd = os.open(ROOT, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        current_fd = root_fd
        file_fd: int | None = None
        try:
            for part in parts[:-1]:
                child_fd = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                                   getattr(os, "O_NOFOLLOW", 0), dir_fd=current_fd)
                info = os.fstat(child_fd)
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                    os.close(child_fd)
                    _fail(code, 4)
                if current_fd != root_fd:
                    os.close(current_fd)
                current_fd = child_fd
            file_fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=current_fd)
            before = os.fstat(file_fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or
                    before.st_size < 0 or before.st_size > maximum):
                _fail(code, 4)
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(file_fd, min(64 * 1024, maximum - total + 1))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > maximum:
                    _fail(code, 4)
            after = os.fstat(file_fd)
            if ((before.st_dev, before.st_ino, before.st_uid, before.st_size) !=
                    (after.st_dev, after.st_ino, after.st_uid, after.st_size)):
                _fail(code, 4)
            if expected != ROOT.joinpath(*parts):
                _fail(code, 4)
            return b"".join(chunks)
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if current_fd != root_fd:
                os.close(current_fd)
            os.close(root_fd)
    except ProjectionV5Error:
        raise
    except FileNotFoundError as error:
        raise ProjectionV5Error(missing_code or code, 3 if missing_code else 4) from error
    except (OSError, InformationYieldV5ContractError) as error:
        raise ProjectionV5Error(code, 4) from error


def _artifact_ref(value: Any, code: str) -> ArtifactRefV5:
    try:
        return ArtifactRefV5.from_mapping(value, code)
    except (InformationYieldV5ContractError, TypeError) as error:
        raise ProjectionV5Error(code, 4) from error


def _json_bytes(raw: bytes, code: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ProjectionV5Error(code, 4) from error
    if not isinstance(value, Mapping):
        _fail(code, 4)
    return value


def _read_json_ref(value: Any, expected_relative: str, schema: str, code: str) -> Mapping[str, Any]:
    ref = _artifact_ref(value, code)
    if ref.path != expected_relative:
        _fail(code, 4)
    raw = _read_relative_bytes(ref.path, MAX_ARTIFACT_BYTES, code)
    if sha256(raw).hexdigest() != ref.sha256:
        _fail(code, 4)
    output = _json_bytes(raw, code)
    _validate_schema(output, schema, code)
    return output


def _fixed_index(evaluation_id: str) -> tuple[Mapping[str, Any], str]:
    relative = f"{_publication_ref_root()}/index/{evaluation_id}.json"
    raw = _read_relative_bytes(relative, MAX_INDEX_BYTES, "EIY_PROJECTION_V5_INDEX_INVALID",
                               missing_code="EIY_PROJECTION_V5_NOT_FOUND")
    value = _json_bytes(raw, "EIY_PROJECTION_V5_INDEX_INVALID")
    _validate_schema(value, "information-yield-result-index-entry-v1.schema.json",
                     "EIY_PROJECTION_V5_INDEX_INVALID")
    _artifact_ref(value.get("custody_ref"), "EIY_PROJECTION_V5_INDEX_INVALID")
    return value, sha256(raw).hexdigest()


def _canonical_policy(ref_value: Any) -> Mapping[str, Any]:
    expected = canonical_policy_ref_v5()
    ref = _artifact_ref(ref_value, "EIY_PROJECTION_V5_POLICY_MISMATCH")
    if ref.to_mapping() != expected:
        _fail("EIY_PROJECTION_V5_POLICY_MISMATCH", 4)
    return _read_json_ref(ref.to_mapping(), expected["path"],
                          "information-yield-metric-policy-v5.schema.json",
                          "EIY_PROJECTION_V5_POLICY_MISMATCH")


def _validate_custody(custody: Mapping[str, Any], index: Mapping[str, Any]) -> None:
    unsigned = {key: value for key, value in custody.items() if key != "custody_sha256"}
    if _digest(unsigned) != custody.get("custody_sha256"):
        _fail("EIY_PROJECTION_V5_CUSTODY_INVALID", 4)
    for name in ("evaluation_ref", "custody_ref", "context_ref", "result_ref", "canonical_policy_ref"):
        _artifact_ref(custody.get(name), "EIY_PROJECTION_V5_CUSTODY_INVALID")
    if custody.get("publication_kind") != "evaluation" or index.get("publication_kind") != "evaluation":
        _fail("EIY_PROJECTION_V5_AUTHORITY_MISMATCH", 4)
    for key in ("evaluation_id", "result_sha256", "context_sha256", "policy_sha256"):
        if custody.get(key) != index.get(key):
            _fail("EIY_PROJECTION_V5_IDENTITY_CONFLICT", 4)
    expected_limitations = [
        "no_malicious_same_user_resistance", "no_remote_attestation",
        "registry_and_self_hash_do_not_elevate_trust",
    ]
    claim_limits = custody.get("claim_limits")
    if (not isinstance(claim_limits, list) or len(claim_limits) > 128 or
            any(not isinstance(item, str) or not ID.fullmatch(item) or FORBIDDEN.search(item)
                for item in claim_limits)):
        _fail("EIY_PROJECTION_V5_PRIVATE_FIELD", 4)
    if (custody.get("same_user_trust") != "integrity_and_nominal_issuance_only" or
            custody.get("same_user_limitations") != expected_limitations):
        _fail("EIY_PROJECTION_V5_AUTHORITY_MISMATCH", 4)


def _validate_context(context: Mapping[str, Any], custody: Mapping[str, Any]) -> None:
    try:
        EvaluationContextV5.from_mapping(context)
    except InformationYieldV5ContractError as error:
        raise ProjectionV5Error("EIY_PROJECTION_V5_CONTEXT_MISMATCH", 4) from error
    if context.get("mode") != "evaluation":
        _fail("EIY_PROJECTION_V5_AUTHORITY_MISMATCH", 4)
    for key in ("evaluation_id", "context_sha256", "fact_set_sha256", "policy_sha256",
                "gate_authority_sha256", "source_closure_sha256"):
        if context.get(key) != custody.get(key):
            _fail("EIY_PROJECTION_V5_CONTEXT_MISMATCH", 4)
    for planned in context.get("planned_cases", []):
        if not isinstance(planned, Mapping):
            _fail("EIY_PROJECTION_V5_CONTEXT_MISMATCH", 4)
        _artifact_ref(planned.get("request_ref"), "EIY_PROJECTION_V5_CONTEXT_MISMATCH")


def _finite(value: Any, *, nullable: bool = False) -> float | int | None:
    if nullable and value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value != value or abs(value) == float("inf"):
        _fail("EIY_PROJECTION_V5_RESULT_DRIFT", 4)
    return value


def _case_row(value: Any, expected_level: str, expected_split: str) -> dict[str, Any]:
    row = _exact(value, CASE_FIELDS, "EIY_PROJECTION_V5_RESULT_DRIFT")
    case_id = _identifier(row["case_id"])
    issuer_id = _identifier(row["issuer_id"])
    window_id = _identifier(row["window_id"])
    if row["evidence_level"] != expected_level or row["split"] != expected_split:
        _fail("EIY_PROJECTION_V5_AUTHORITY_MISMATCH", 4)
    order = row["arm_order"]
    if not isinstance(order, list) or len(order) != 2 or set(order) != {"B0", "F"}:
        _fail("EIY_PROJECTION_V5_RESULT_DRIFT", 4)
    request_sha = _sha(row["request_sha256"], "EIY_PROJECTION_V5_RESULT_DRIFT")
    fact_sha = _sha(row["fact_sha256"], "EIY_PROJECTION_V5_RESULT_DRIFT")
    delta_r = _finite(row["delta_r"])
    delta_d = _finite(row["delta_d"])
    arms = _exact(row["arms"], {"B0", "F"}, "EIY_PROJECTION_V5_RESULT_DRIFT")
    projected_arms: dict[str, Any] = {}
    for arm_id in ("B0", "F"):
        arm = _exact(arms[arm_id], ARM_FIELDS, "EIY_PROJECTION_V5_RESULT_DRIFT")
        trace = _exact(arm["trace"], TRACE_FIELDS, "EIY_PROJECTION_V5_RESULT_DRIFT")
        projected_arms[arm_id] = {
            "richness": _finite(arm["richness"]), "depth": _finite(arm["depth"]),
            "precision": _finite(arm["precision"], nullable=True),
            "wall_seconds": _finite(arm["wall_seconds"], nullable=True),
            "trace": {key: _finite(trace[key], nullable=True) for key in ("complete", "credited", "unjudged")},
        }
    codes = row["hard_failure_codes"]
    if (not isinstance(codes, list) or len(codes) > 64 or len(codes) != len(set(codes)) or
            any(not isinstance(code, str) or not ID.fullmatch(code) for code in codes)):
        _fail("EIY_PROJECTION_V5_RESULT_DRIFT", 4)
    return {"case_id": case_id, "issuer_id": issuer_id, "window_id": window_id,
            "evidence_level": expected_level, "split": expected_split, "arm_order": list(order),
            "request_sha256": request_sha, "fact_sha256": fact_sha,
            "delta_r": delta_r, "delta_d": delta_d, "arms": projected_arms,
            "hard_failure_codes": list(codes)}


def _validate_result(result: Mapping[str, Any], context: Mapping[str, Any],
                     custody: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    unsigned = {key: value for key, value in result.items() if key != "result_sha256"}
    if _digest(unsigned) != result.get("result_sha256"):
        _fail("EIY_PROJECTION_V5_RESULT_DRIFT", 4)
    for key in ("evaluation_id", "context_sha256", "fact_set_sha256", "policy_sha256",
                "gate_authority_sha256", "source_closure_sha256", "result_sha256", "claim_limits"):
        if result.get(key) != custody.get(key):
            _fail("EIY_PROJECTION_V5_RESULT_DRIFT", 4)
    if result.get("populations") != context.get("populations"):
        _fail("EIY_PROJECTION_V5_AUTHORITY_MISMATCH", 4)
    confirmation = [_case_row(row, "confirmation", "untouched") for row in result["confirmation_cases"]]
    development = [_case_row(row, "development", "development") for row in result["development_cases"]]
    populations = result["populations"]
    c_ids = [row["case_id"] for row in confirmation]
    d_ids = [row["case_id"] for row in development]
    if (len(set(c_ids + d_ids)) != len(c_ids) + len(d_ids) or populations !=
            {"C": c_ids, "D": d_ids, "E": c_ids + d_ids, "N": []}):
        _fail("EIY_PROJECTION_V5_AUTHORITY_MISMATCH", 4)
    counts = result.get("counts")
    if counts != {"planned": len(c_ids) + len(d_ids), "C": len(c_ids), "D": len(d_ids)} or len(c_ids) != 6:
        _fail("EIY_PROJECTION_V5_AUTHORITY_MISMATCH", 4)
    planned = context.get("planned_cases")
    bindings = context.get("fact_bindings")
    if not isinstance(planned, list) or not isinstance(bindings, list) or len(planned) != len(populations["E"]):
        _fail("EIY_PROJECTION_V5_AUTHORITY_MISMATCH", 4)
    planned_ids = [row.get("case_id") for row in planned if isinstance(row, Mapping)]
    if (len(planned_ids) != len(planned) or len(set(planned_ids)) != len(planned_ids) or
            set(planned_ids) != set(populations["E"]) or len(bindings) != len(planned)):
        _fail("EIY_PROJECTION_V5_AUTHORITY_MISMATCH", 4)
    projected_by_id = {row["case_id"]: row for row in confirmation + development}
    for planned_row, binding in zip(planned, bindings):
        case_id = planned_row["case_id"]
        projected = projected_by_id.get(case_id)
        expected_binding = {"case_id": case_id, "request_sha256": planned_row.get("request_sha256"),
                            "fact_sha256": planned_row.get("fact_sha256"),
                            "context_sha256": context.get("context_sha256")}
        if (not projected or binding != expected_binding or
                planned_row.get("request_sha256") != projected["request_sha256"] or
                planned_row.get("fact_sha256") != projected["fact_sha256"]):
            _fail("EIY_PROJECTION_V5_AUTHORITY_MISMATCH", 4)
    return confirmation, development


def _validate_gates(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    gates = result.get("policy_gates")
    populations = result["populations"]
    if not isinstance(gates, list) or len(gates) != len(GATE_SPECS):
        _fail("EIY_PROJECTION_V5_AUTHORITY_MISMATCH", 4)
    output: list[dict[str, Any]] = []
    for gate, spec in zip(gates, GATE_SPECS):
        row = _exact(gate, GATE_FIELDS, "EIY_PROJECTION_V5_AUTHORITY_MISMATCH")
        if any(row.get(key) != spec[key] for key in ("ordinal", "name", "population", "decisive")):
            _fail("EIY_PROJECTION_V5_AUTHORITY_MISMATCH", 4)
        if row.get("population_case_ids") != populations[spec["population"]] or row.get("status") not in {"pass", "fail", "unknown", "not_applicable"}:
            _fail("EIY_PROJECTION_V5_AUTHORITY_MISMATCH", 4)
        output.append({key: _public(row[key]) for key in (
            "ordinal", "name", "population", "decisive", "population_case_ids", "status",
            "observed", "threshold", "numerator", "denominator", "case_results", "reason_codes")})
    expected = ("reject" if any(g["decisive"] and g["status"] == "fail" for g in output)
                else "inconclusive" if any(g["status"] == "unknown" for g in output)
                else "inconclusive" if any(not g["decisive"] and g["status"] == "fail" for g in output)
                else "pass" if len(populations["C"]) == 6 and all(g["status"] == "pass" for g in output)
                else "inconclusive")
    if result.get("verdict") != expected or result.get("gate_authority_sha256") != _digest(list(GATE_SPECS)):
        _fail("EIY_PROJECTION_V5_AUTHORITY_MISMATCH", 4)
    return output


def _observation(value: float | int | None, unit: str, reason: str) -> dict[str, Any]:
    return ({"state": "known", "value": value, "unit": unit} if value is not None
            else {"state": "unavailable", "reason_code": reason})


def _metric(rows: list[dict[str, Any]], key: str, unit: str) -> dict[str, Any]:
    values = [row[key] for row in rows]; total = sum(values); ordered = sorted(values); middle = len(values) // 2
    median = ((ordered[middle - 1] + ordered[middle]) / 2 if len(values) % 2 == 0 else ordered[middle])
    wins = sum(value > 0 for value in values); losses = sum(value < 0 for value in values); ties = len(values) - wins - losses
    return {"mean": _observation(total / len(values), unit, "OUTCOME_UNAVAILABLE"),
            "median": _observation(median, unit, "OUTCOME_UNAVAILABLE"),
            "minimum": _observation(min(values), unit, "OUTCOME_UNAVAILABLE"),
            "maximum": _observation(max(values), unit, "OUTCOME_UNAVAILABLE"),
            "range": _observation(max(values) - min(values), unit, "OUTCOME_UNAVAILABLE"),
            "total": _observation(total, unit, "OUTCOME_UNAVAILABLE"),
            "denominator": len(values), "wins": wins, "ties": ties, "losses": losses,
            "leave_one_issuer_out": []}


def _case_wire(row: Mapping[str, Any]) -> dict[str, Any]:
    def arm_wire(arm: Mapping[str, Any]) -> dict[str, Any]:
        return {"richness": _observation(arm["richness"], "canonical_units", "RICHNESS_UNAVAILABLE"),
                "depth": _observation(arm["depth"], "field_state_steps", "DEPTH_UNAVAILABLE"),
                "precision": _observation(arm["precision"], "ratio", "PRECISION_UNAVAILABLE"),
                "wall_seconds": _observation(arm["wall_seconds"], "seconds", "WALL_TIME_UNAVAILABLE"),
                "trace": dict(arm["trace"])}
    return {**{key: row[key] for key in ("case_id", "issuer_id", "window_id", "evidence_level", "split",
                                          "arm_order", "request_sha256", "fact_sha256")},
            "delta_r": _observation(row["delta_r"], "canonical_units", "RICHNESS_UNAVAILABLE"),
            "delta_d": _observation(row["delta_d"], "field_state_steps", "DEPTH_UNAVAILABLE"),
            "arms": {arm_id: arm_wire(row["arms"][arm_id]) for arm_id in ("B0", "F")},
            "hard_failure_codes": list(row["hard_failure_codes"])}


def project_result_custody_v1(evaluation_id: str, *, case_id: str | None = None,
                              arm: str | None = None) -> dict[str, Any]:
    evaluation_id = _identifier(evaluation_id)
    if case_id is not None:
        case_id = _identifier(case_id)
    if arm is not None and (case_id is None or arm not in {"B0", "F"}):
        _fail("EIY_PROJECTION_V5_IDENTITY_CONFLICT", 4)
    index, index_sha = _fixed_index(evaluation_id)
    if index.get("evaluation_id") != evaluation_id:
        _fail("EIY_PROJECTION_V5_IDENTITY_CONFLICT", 4)
    object_ref_root = f"{_publication_ref_root()}/objects/{index['result_sha256']}"
    custody = _read_json_ref(index.get("custody_ref"), f"{object_ref_root}/custody.json",
                             "information-yield-result-custody-v1.schema.json",
                             "EIY_PROJECTION_V5_CUSTODY_INVALID")
    _validate_custody(custody, index)
    if custody.get("evaluation_id") != evaluation_id:
        _fail("EIY_PROJECTION_V5_IDENTITY_CONFLICT", 4)
    policy = _canonical_policy(custody.get("canonical_policy_ref"))
    if custody.get("policy_sha256") != CANONICAL_METRIC_POLICY_V5_SHA256:
        _fail("EIY_PROJECTION_V5_POLICY_MISMATCH", 4)
    context = _read_json_ref(custody.get("context_ref"), f"{object_ref_root}/context.json",
                             "information-yield-evaluation-context-v5.schema.json",
                             "EIY_PROJECTION_V5_CONTEXT_MISMATCH")
    _validate_context(context, custody)
    if context.get("policy") != policy:
        _fail("EIY_PROJECTION_V5_POLICY_MISMATCH", 4)
    result = _read_json_ref(custody.get("result_ref"), f"{object_ref_root}/result.json",
                            "information-yield-result-5.schema.json",
                            "EIY_PROJECTION_V5_RESULT_DRIFT")
    confirmation, development = _validate_result(result, context, custody)
    gates = _validate_gates(result)
    cases = [_case_wire(row) for row in confirmation + development]
    selected = None if case_id is None else next((row for row in cases if row["case_id"] == case_id), None)
    if case_id is not None and selected is None:
        _fail("EIY_PROJECTION_V5_NOT_FOUND", 3)
    visible = cases if selected is None else [selected]
    hard_failures = [{"case_id": row["case_id"], "code": code}
                     for row in visible for code in row["hard_failure_codes"]]
    output = {"wire_version": "information-yield-wire-5", "publication": "information-yield-v5",
              "view": "summary" if selected is None else "detail", "evaluation_id": evaluation_id,
              "index_sha256": index_sha,
              "custody_sha256": _sha(custody.get("custody_sha256"), "EIY_PROJECTION_V5_CUSTODY_INVALID"),
              "result_sha256": _sha(result.get("result_sha256"), "EIY_PROJECTION_V5_RESULT_DRIFT"),
              "verdict": result["verdict"],
              "counts": {"planned": result["counts"]["planned"], "confirmation": result["counts"]["C"],
                         "development": result["counts"]["D"]},
              "evidence": {"context_sha256": context["context_sha256"], "fact_set_sha256": context["fact_set_sha256"],
                           "policy_sha256": context["policy_sha256"], "gate_authority_sha256": context["gate_authority_sha256"],
                           "source_closure_sha256": context["source_closure_sha256"],
                           "claim_limits": list(custody["claim_limits"]), "same_user_trust": custody["same_user_trust"],
                           "same_user_limitations": list(custody["same_user_limitations"])},
              "outcomes": {"richness": _metric(confirmation, "delta_r", "canonical_units"),
                           "depth": _metric(confirmation, "delta_d", "field_state_steps")},
              "populations": {key: list(result["populations"][key]) for key in ("C", "D", "E", "N")},
              "policy_gates": gates, "hard_failures": hard_failures,
              "cases": cases if selected is None else [], "selection": {"case_id": case_id, "arm": arm},
              "case": selected, "selected_arm": selected["arms"][arm] if selected is not None and arm is not None else None,
              "projection_state": "fresh", "read_only": True}
    if len(_canonical(output)) > MAX_OUTPUT_BYTES:
        _fail("EIY_PROJECTION_V5_OUTPUT_LIMIT", 4)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = SafeParser(add_help=False); parser.add_argument("--evaluation-id"); parser.add_argument("--case-id"); parser.add_argument("--arm")
    try:
        args = parser.parse_args(argv)
        if args.evaluation_id is None:
            _fail("INVALID_INFORMATION_YIELD_V5_QUERY", 2)
        output = project_result_custody_v1(args.evaluation_id, case_id=args.case_id, arm=args.arm)
        print(json.dumps(output, sort_keys=True, separators=(",", ":"), allow_nan=False)); return 0
    except ProjectionV5Error as error:
        print(json.dumps({"error": {"code": error.code}}, separators=(",", ":"))); return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
