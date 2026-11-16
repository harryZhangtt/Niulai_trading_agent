"""Frozen synthetic runner request/receipt v2 contracts.

Version 2 is fixture-only. It cannot select commands, environments, credentials,
paths, generated code, protected outcomes, or performance publication.
"""
import hashlib
import json
import re
import types

RDAGENT_REVISION = "484776c211e4fbbeef03e0ec00d6bbee7362a4f4"
RDAGENT_TREE = "d4444284fb4554f75f352ecb1f072cedbf4c6421"
QLIB_REVISION = "2fb9380b342556ddb50a4b24e4fe8655d548b2b8"
QLIB_TREE = "0f541590a9efecb9bfb5342155be50461ad7d002"
AUTHORITY_ID = "factor-admission-main-v1"
AUTHORITY_POLICY_SHA256 = "ed5ab71c758489d8e3c3917794a80054abe5c31d5885fc8c808b5535986c0d81"
GENESIS_SHA256 = "e13a6f0d6c55d7a482dfaeb85657406df2418e72850015a3950cfca724693ce5"
ADMISSION_POLICY_SHA256 = "d010b96585994ba2bc712ba96d580cbc2cd669b03bbf41eaeee2b855c53c0b9f"
PURPOSE = "synthetic-contract-verification"
MAX_REQUEST_BYTES = 64 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
SHA = re.compile(r"[a-f0-9]{64}\Z")
ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,95}\Z")
BINDING_KEYS = {
    "authority_id", "authority_policy_sha256", "genesis_sha256",
    "admission_policy_sha256", "dataset_event_sha256", "nonce_event_sha256",
    "nonce_sha256", "builder_receipt_sha256", "observation_set_sha256",
    "feature_snapshot_sha256", "evaluation_population_sha256",
    "split_fingerprints", "semantic_config_sha256",
}
IMPLEMENTATION_CONSTANT_NAMES = (
    "RDAGENT_REVISION", "RDAGENT_TREE", "QLIB_REVISION", "QLIB_TREE",
    "AUTHORITY_ID", "AUTHORITY_POLICY_SHA256", "GENESIS_SHA256",
    "ADMISSION_POLICY_SHA256", "PURPOSE", "MAX_REQUEST_BYTES",
    "MAX_RECEIPT_BYTES", "SHA", "ID", "BINDING_KEYS",
)


class ContractError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ContractError(code)


def _pairs(items):
    value = {}
    for key, item in items:
        require(key not in value, "ADAPTER_V2_DUPLICATE_KEY")
        value[key] = item
    return value


def loads_strict(raw, maximum, code):
    if isinstance(raw, str):
        raw = raw.encode()
    require(type(raw) is bytes and 0 < len(raw) <= maximum, code)
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _value: (_ for _ in ()).throw(
                              ContractError("ADAPTER_V2_NONFINITE")))
    except ContractError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise ContractError("ADAPTER_V2_JSON_INVALID") from None


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError):
        raise ContractError("ADAPTER_V2_JSON_INVALID") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _strict(value, keys, code):
    require(type(value) is dict and set(value) == set(keys), code)
    return value


def _sha(value, code="ADAPTER_V2_SHA_INVALID"):
    require(type(value) is str and SHA.fullmatch(value), code)
    return value


def _id(value, code="ADAPTER_V2_ID_INVALID"):
    require(type(value) is str and ID.fullmatch(value), code)
    return value


def engine_contract():
    return {
        "rdagent_revision": RDAGENT_REVISION,
        "rdagent_tree": RDAGENT_TREE,
        "qlib_profile": "qlib-rdagent-compatible",
        "qlib_revision": QLIB_REVISION,
        "qlib_tree": QLIB_TREE,
        "adapter_version": "rdagent-adapter-v2-synthetic",
    }


def validate_binding(binding):
    _strict(binding, BINDING_KEYS, "ADAPTER_V2_BINDING_SCHEMA")
    require(binding["authority_id"] == AUTHORITY_ID and
            binding["authority_policy_sha256"] == AUTHORITY_POLICY_SHA256 and
            binding["genesis_sha256"] == GENESIS_SHA256 and
            binding["admission_policy_sha256"] == ADMISSION_POLICY_SHA256,
            "ADAPTER_V2_AUTHORITY_MISMATCH")
    for key in BINDING_KEYS - {"authority_id", "split_fingerprints"}:
        _sha(binding[key], "ADAPTER_V2_BINDING_SHA_INVALID")
    splits = _strict(binding["split_fingerprints"],
                     {"development", "validation", "protected"},
                     "ADAPTER_V2_SPLIT_SCHEMA")
    for value in splits.values():
        _sha(value, "ADAPTER_V2_SPLIT_SHA_INVALID")
    return binding


def validate_request(request):
    _strict(request, {"schema_version", "kind", "request_id", "purpose",
                      "authority_binding", "engine", "limits"},
            "ADAPTER_V2_REQUEST_SCHEMA")
    require(type(request["schema_version"]) is int and request["schema_version"] == 2 and
            request["kind"] == "rdagent_synthetic_runner_request" and
            request["purpose"] == PURPOSE, "ADAPTER_V2_REQUEST_VERSION")
    _id(request["request_id"], "ADAPTER_V2_REQUEST_ID_INVALID")
    validate_binding(request["authority_binding"])
    require(request["engine"] == engine_contract(), "ADAPTER_V2_ENGINE_MISMATCH")
    limits = _strict(request["limits"], {"artifact_bytes"},
                     "ADAPTER_V2_LIMITS_SCHEMA")
    require(type(limits["artifact_bytes"]) is int and 256 <= limits["artifact_bytes"] <= 65536,
            "ADAPTER_V2_LIMITS_INVALID")
    return request


def parse_request(raw):
    return validate_request(loads_strict(raw, MAX_REQUEST_BYTES, "ADAPTER_V2_REQUEST_SIZE"))


def request_sha256(request):
    return digest(validate_request(request))


def validate_receipt(receipt, request=None):
    _strict(receipt, {"schema_version", "kind", "request_sha256", "authority_binding",
                      "runner_implementation_sha256", "status", "artifact", "failure_code",
                      "outcome_accessed", "protected_labels_accessed", "performance_claim"},
            "ADAPTER_V2_RECEIPT_SCHEMA")
    require(type(receipt["schema_version"]) is int and receipt["schema_version"] == 2 and
            receipt["kind"] == "rdagent_synthetic_runner_receipt",
            "ADAPTER_V2_RECEIPT_VERSION")
    _sha(receipt["request_sha256"]); validate_binding(receipt["authority_binding"])
    _sha(receipt["runner_implementation_sha256"])
    require(receipt["status"] in {"synthetic-structural-complete", "failed"} and
            receipt["outcome_accessed"] is False and
            receipt["protected_labels_accessed"] is False and
            receipt["performance_claim"] == "withheld", "ADAPTER_V2_RECEIPT_STATUS")
    artifact = receipt["artifact"]
    if receipt["status"] == "synthetic-structural-complete":
        _strict(artifact, {"id", "kind", "sha256", "size_bytes"},
                "ADAPTER_V2_ARTIFACT_SCHEMA")
        require(artifact["id"] == "structural-proof" and
                artifact["kind"] == "authority-binding-proof" and
                type(artifact["size_bytes"]) is int and 0 < artifact["size_bytes"] <= 65536 and
                receipt["failure_code"] is None, "ADAPTER_V2_ARTIFACT_INVALID")
        _sha(artifact["sha256"])
    else:
        require(artifact is None and receipt["failure_code"] == "FIXED_WORKER_REJECTED",
                "ADAPTER_V2_FAILURE_INVALID")
    if request is not None:
        require(receipt["request_sha256"] == request_sha256(request) and
                receipt["authority_binding"] == request["authority_binding"],
                "ADAPTER_V2_RECEIPT_BINDING_MISMATCH")
        if artifact is not None:
            require(artifact["size_bytes"] <= request["limits"]["artifact_bytes"],
                    "ADAPTER_V2_ARTIFACT_BUDGET")
    return receipt


def parse_receipt(raw, request=None):
    return validate_receipt(loads_strict(raw, MAX_RECEIPT_BYTES, "ADAPTER_V2_RECEIPT_SIZE"),
                            request=request)


def _code_value(value):
    if isinstance(value, types.CodeType):
        return _code_semantics(value)
    if isinstance(value, re.Pattern):
        return {"pattern": value.pattern, "flags": value.flags}
    if value is None or type(value) in {bool, int, float, str}:
        return value
    if isinstance(value, (set, frozenset)):
        return sorted((_code_value(item) for item in value), key=canonical)
    if isinstance(value, (tuple, list)):
        return [_code_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _code_value(item) for key, item in sorted(value.items())}
    return {"type": type(value).__name__, "repr": repr(value)}


def _code_semantics(code):
    return {"name": code.co_name, "argcount": code.co_argcount,
            "kwonlyargcount": code.co_kwonlyargcount, "flags": code.co_flags,
            "bytecode": code.co_code.hex(), "names": list(code.co_names),
            "varnames": list(code.co_varnames),
            "constants": [_code_value(item) for item in code.co_consts]}


def implementation_sha256():
    functions = [{"symbol": name, "code": _code_semantics(value.__code__)}
                 for name, value in globals().items()
                 if callable(value) and getattr(value, "__module__", None) == __name__ and
                 hasattr(value, "__code__") and name != "implementation_sha256"]
    constants = {name: _code_value(globals()[name]) for name in IMPLEMENTATION_CONSTANT_NAMES}
    return digest({"functions": sorted(functions, key=lambda item: item["symbol"]),
                   "constants": constants})
