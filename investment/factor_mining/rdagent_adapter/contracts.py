"""Closed JSON contracts for a one-loop RD-Agent factor subprocess boundary."""
import hashlib
import json
import math
from pathlib import Path
import re


RDAGENT_REVISION = "484776c211e4fbbeef03e0ec00d6bbee7362a4f4"
RDAGENT_TREE = "d4444284fb4554f75f352ecb1f072cedbf4c6421"
QLIB_PROFILE = "qlib-rdagent-compatible"
QLIB_REVISION = "2fb9380b342556ddb50a4b24e4fe8655d548b2b8"
QLIB_TREE = "0f541590a9efecb9bfb5342155be50461ad7d002"
ADAPTER_VERSION = "rdagent-adapter-v1"
MAX_REQUEST_BYTES = 64 * 1024
MAX_RECEIPT_BYTES = 128 * 1024
NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,95}\Z")
SHA64 = re.compile(r"[a-f0-9]{64}\Z")
STAGE_IDS = ("proposal", "coding", "factor-output", "feedback")
STAGE_STATUSES = {"succeeded", "failed", "timed_out", "skipped"}
RECEIPT_STATUSES = {"succeeded", "failed", "timed_out"}
FAILURE_CODES = {
    "RUNTIME_NONZERO", "RUNTIME_TIMEOUT", "RUNTIME_OUTPUT_INVALID",
    "RUNTIME_OUTPUT_OVERSIZE", "FACTOR_CODE_MISSING", "FACTOR_OUTPUT_MISSING",
    "ARTIFACT_INVALID", "PROCESS_CLEANUP_FAILED", "REQUEST_INVALID",
}
ARTIFACT_KINDS = {"generated-code", "factor-data", "combined-factor", "evaluation"}


class ContractError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ContractError(code)


def _name(value, code="ADAPTER_ID_INVALID"):
    require(isinstance(value, str) and NAME.fullmatch(value), code)
    return value


def _sha(value, code="ADAPTER_SHA_INVALID", optional=False):
    if optional and value is None:
        return None
    require(isinstance(value, str) and SHA64.fullmatch(value), code)
    return value


def _strict(value, keys, code):
    require(isinstance(value, dict) and set(value) == set(keys), code)
    return value


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "ADAPTER_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ContractError("ADAPTER_JSON_NONFINITE")


def loads_strict(raw, maximum, size_code):
    if isinstance(raw, str):
        raw = raw.encode()
    require(isinstance(raw, bytes) and 0 < len(raw) <= maximum, size_code)
    try:
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except ContractError:
        raise
    except (ValueError, UnicodeError):
        raise ContractError("ADAPTER_JSON_INVALID") from None


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode()
    except (TypeError, ValueError):
        raise ContractError("ADAPTER_JSON_INVALID") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def engine_contract():
    return {
        "rdagent_revision": RDAGENT_REVISION,
        "rdagent_tree": RDAGENT_TREE,
        "qlib_profile": QLIB_PROFILE,
        "qlib_revision": QLIB_REVISION,
        "qlib_tree": QLIB_TREE,
        "adapter_version": ADAPTER_VERSION,
    }


def _validate_engine(engine):
    _strict(engine, set(engine_contract()), "ADAPTER_ENGINE_SCHEMA")
    require(engine == engine_contract(), "ADAPTER_ENGINE_MISMATCH")


def _relative_path(value):
    require(isinstance(value, str) and value and len(value) <= 512,
            "ADAPTER_ARTIFACT_PATH_INVALID")
    path = Path(value)
    require(not path.is_absolute() and ".." not in path.parts and not value.startswith("~") and
            all(part not in {"", "."} for part in path.parts), "ADAPTER_ARTIFACT_PATH_INVALID")


def validate_request(request):
    _strict(request, {"schema_version", "kind", "request_id", "engine", "task", "limits",
                      "credential_refs"}, "ADAPTER_REQUEST_SCHEMA")
    require(type(request["schema_version"]) is int and request["schema_version"] == 1 and
            request["kind"] == "rdagent_factor_request",
            "ADAPTER_REQUEST_VERSION")
    _name(request["request_id"], "ADAPTER_REQUEST_ID_INVALID")
    _validate_engine(request["engine"])
    task = _strict(request["task"],
                   {"mode", "hypothesis", "constraints", "base_features_sha256",
                    "expected_factor_ids"}, "ADAPTER_TASK_SCHEMA")
    require(task["mode"] == "fin-factor-one-loop" and isinstance(task["hypothesis"], str) and
            1 <= len(task["hypothesis"]) <= 4000, "ADAPTER_TASK_INVALID")
    require(isinstance(task["constraints"], list) and len(task["constraints"]) <= 32 and
            all(isinstance(item, str) and 1 <= len(item) <= 500 for item in task["constraints"]),
            "ADAPTER_CONSTRAINTS_INVALID")
    _sha(task["base_features_sha256"], optional=True)
    require(isinstance(task["expected_factor_ids"], list) and
            1 <= len(task["expected_factor_ids"]) <= 16 and
            all(isinstance(item, str) for item in task["expected_factor_ids"]) and
            len(task["expected_factor_ids"]) == len(set(task["expected_factor_ids"])),
            "ADAPTER_FACTOR_IDS_INVALID")
    for factor_id in task["expected_factor_ids"]:
        _name(factor_id, "ADAPTER_FACTOR_ID_INVALID")
    limits = _strict(request["limits"],
                     {"timeout_seconds", "stdout_bytes", "artifact_bytes", "max_factors"},
                     "ADAPTER_LIMITS_SCHEMA")
    require(type(limits["timeout_seconds"]) is int and 1 <= limits["timeout_seconds"] <= 3600 and
            type(limits["stdout_bytes"]) is int and 1024 <= limits["stdout_bytes"] <= 1024 * 1024 and
            type(limits["artifact_bytes"]) is int and 1024 <= limits["artifact_bytes"] <= 1024 * 1024 * 1024 and
            type(limits["max_factors"]) is int and
            len(task["expected_factor_ids"]) <= limits["max_factors"] <= 16,
            "ADAPTER_LIMITS_INVALID")
    require(isinstance(request["credential_refs"], list) and len(request["credential_refs"]) <= 8 and
            all(isinstance(item, str) for item in request["credential_refs"]) and
            len(request["credential_refs"]) == len(set(request["credential_refs"])),
            "ADAPTER_CREDENTIAL_REFS_INVALID")
    for reference in request["credential_refs"]:
        require(re.fullmatch(r"credential-ref-[a-z0-9_.-]{1,80}", reference),
                "ADAPTER_CREDENTIAL_REF_INVALID")
    return request


def parse_request(raw):
    return validate_request(loads_strict(raw, MAX_REQUEST_BYTES, "ADAPTER_REQUEST_SIZE_LIMIT"))


def request_sha256(request):
    return digest(validate_request(request))


def validate_receipt(receipt, request=None):
    _strict(receipt, {"schema_version", "kind", "request_sha256", "status", "execution_mode",
                      "engine", "stages", "artifacts", "failure_code", "resources",
                      "process_group_cleanup_verified"}, "ADAPTER_RECEIPT_SCHEMA")
    require(type(receipt["schema_version"]) is int and receipt["schema_version"] == 1 and
            receipt["kind"] == "rdagent_factor_receipt",
            "ADAPTER_RECEIPT_VERSION")
    _sha(receipt["request_sha256"], "ADAPTER_REQUEST_SHA_INVALID")
    require(isinstance(receipt["status"], str) and receipt["status"] in RECEIPT_STATUSES and
            isinstance(receipt["execution_mode"], str) and
            receipt["execution_mode"] in {"synthetic-fixture", "upstream-isolated"},
            "ADAPTER_RECEIPT_STATUS_INVALID")
    _validate_engine(receipt["engine"])
    require(isinstance(receipt["stages"], list) and len(receipt["stages"]) == len(STAGE_IDS),
            "ADAPTER_STAGE_ROSTER_INVALID")
    for expected_id, stage in zip(STAGE_IDS, receipt["stages"]):
        _strict(stage, {"id", "status", "duration_seconds", "evidence_sha256"},
                "ADAPTER_STAGE_SCHEMA")
        require(stage["id"] == expected_id and isinstance(stage["status"], str) and
                stage["status"] in STAGE_STATUSES and _finite(stage["duration_seconds"]) and
                stage["duration_seconds"] >= 0, "ADAPTER_STAGE_INVALID")
        _sha(stage["evidence_sha256"], optional=True)
        if stage["status"] == "succeeded":
            require(stage["evidence_sha256"] is not None, "ADAPTER_STAGE_EVIDENCE_REQUIRED")
    require(isinstance(receipt["artifacts"], list) and len(receipt["artifacts"]) <= 64,
            "ADAPTER_ARTIFACTS_INVALID")
    artifact_ids = set()
    for artifact in receipt["artifacts"]:
        _strict(artifact, {"id", "kind", "path", "sha256", "size_bytes", "factor_ids"},
                "ADAPTER_ARTIFACT_SCHEMA")
        _name(artifact["id"], "ADAPTER_ARTIFACT_ID_INVALID")
        require(artifact["id"] not in artifact_ids and isinstance(artifact["kind"], str) and
                artifact["kind"] in ARTIFACT_KINDS and type(artifact["size_bytes"]) is int and
                artifact["size_bytes"] > 0 and isinstance(artifact["factor_ids"], list) and
                all(isinstance(item, str) for item in artifact["factor_ids"]) and
                len(artifact["factor_ids"]) <= 16 and
                len(artifact["factor_ids"]) == len(set(artifact["factor_ids"])),
                "ADAPTER_ARTIFACT_INVALID")
        for factor_id in artifact["factor_ids"]:
            _name(factor_id, "ADAPTER_FACTOR_ID_INVALID")
        _relative_path(artifact["path"]); _sha(artifact["sha256"])
        artifact_ids.add(artifact["id"])
    require(receipt["failure_code"] is None or
            isinstance(receipt["failure_code"], str) and receipt["failure_code"] in FAILURE_CODES,
            "ADAPTER_FAILURE_CODE_INVALID")
    resources = _strict(receipt["resources"], {"wall_seconds", "cpu_seconds", "peak_rss_bytes"},
                        "ADAPTER_RESOURCES_SCHEMA")
    require(_finite(resources["wall_seconds"]) and resources["wall_seconds"] >= 0 and
            _finite(resources["cpu_seconds"]) and resources["cpu_seconds"] >= 0 and
            type(resources["peak_rss_bytes"]) is int and resources["peak_rss_bytes"] >= 0,
            "ADAPTER_RESOURCES_INVALID")
    require(type(receipt["process_group_cleanup_verified"]) is bool, "ADAPTER_CLEANUP_INVALID")
    if receipt["status"] == "succeeded":
        require(receipt["process_group_cleanup_verified"] is True, "ADAPTER_CLEANUP_UNVERIFIED")
        require(receipt["failure_code"] is None and
                all(stage["status"] == "succeeded" for stage in receipt["stages"]),
                "ADAPTER_SUCCESS_STAGES_INVALID")
        kinds = {artifact["kind"] for artifact in receipt["artifacts"]}
        require({"generated-code", "factor-data"} <= kinds,
                "ADAPTER_SUCCESS_ARTIFACTS_MISSING")
    else:
        require(receipt["failure_code"] is not None and
                any(stage["status"] in {"failed", "timed_out"} for stage in receipt["stages"]),
                "ADAPTER_FAILURE_RECEIPT_INVALID")
        if receipt["process_group_cleanup_verified"] is False:
            require(receipt["failure_code"] == "PROCESS_CLEANUP_FAILED",
                    "ADAPTER_CLEANUP_FAILURE_CODE_INVALID")
        if receipt["status"] == "timed_out":
            require(receipt["failure_code"] == "RUNTIME_TIMEOUT",
                    "ADAPTER_TIMEOUT_CODE_INVALID")
    if request is not None:
        require(receipt["request_sha256"] == request_sha256(request) and
                receipt["engine"] == request["engine"], "ADAPTER_RECEIPT_REQUEST_MISMATCH")
        expected = sorted(request["task"]["expected_factor_ids"])
        require(sum(artifact["size_bytes"] for artifact in receipt["artifacts"]) <=
                request["limits"]["artifact_bytes"], "ADAPTER_ARTIFACT_BUDGET_EXCEEDED")
        if receipt["status"] == "succeeded":
            bound = [artifact for artifact in receipt["artifacts"]
                     if artifact["kind"] in {"generated-code", "factor-data"}]
            require(bound and all(sorted(artifact["factor_ids"]) == expected for artifact in bound) and
                    len(expected) <= request["limits"]["max_factors"],
                    "ADAPTER_FACTOR_OUTPUT_MISMATCH")
    return receipt


def parse_receipt(raw, request=None):
    return validate_receipt(loads_strict(raw, MAX_RECEIPT_BYTES, "ADAPTER_RECEIPT_SIZE_LIMIT"),
                            request=request)
