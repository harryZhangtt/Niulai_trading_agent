"""Fixture-only evaluator request and receipt contracts.

The evaluator verifies structural identity flow only. It never opens labels, computes
metrics, judges performance, or authorizes publication.
"""
import hashlib
import json
from pathlib import Path
import re
import sys
import types

from investment.factor_mining.rdagent_adapter.v2 import contracts as runner_contracts
from investment.factor_mining.rdagent_adapter.v2 import fixed_worker
from investment.factor_mining.rdagent_adapter.v2 import runner as runner_module
from tuning.factor_mining.admission_authority import authority as authority_contract
from tuning.factor_mining.admission_policy import policy as admission_policy


PACKAGE = Path(__file__).resolve().parent
POLICY_PATH = PACKAGE.parent / "admission_policy/initial-confirmatory-policy.json"
ADMISSION_POLICY_SHA256 = "d010b96585994ba2bc712ba96d580cbc2cd669b03bbf41eaeee2b855c53c0b9f"
AUTHORITY_ID = runner_contracts.AUTHORITY_ID
AUTHORITY_POLICY_SHA256 = runner_contracts.AUTHORITY_POLICY_SHA256
AUTHORITY_GENESIS_SHA256 = runner_contracts.GENESIS_SHA256
RUNNER_SCHEMA_VERSION = 2
EVALUATOR_SCHEMA_VERSION = 1
MAX_JSON_BYTES = 256 * 1024
ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,95}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")
FORBIDDEN_TEXT = re.compile(
    r"(?i)(api[_-]?key|password|bearer\s|secret\s*[=:]|sk-proj-|/users/|/private/|"
    r"protected[_-]?(label|outcome|metric)|\bp[_-]?value\b|confidence[_-]?interval)"
)
BINDING_FIELDS = frozenset(runner_contracts.BINDING_KEYS)
REQUEST_FIELDS = {"schema_version", "kind", "evaluation_id", "runner_event_sha256",
                  "runner_request", "runner_receipt", "runner_artifact"}
ARTIFACT_FIELDS = {"schema_version", "kind", "worker_version", "request_sha256",
                   "builder_receipt_sha256", "observation_set_sha256",
                   "feature_snapshot_sha256", "evaluation_population_sha256",
                   "split_fingerprints", "outcome_accessed", "protected_labels_accessed",
                   "performance_claim"}
RECEIPT_FIELDS = {
    "schema_version", "kind", "evaluation_id", "request_sha256",
    "authority_binding", "runner_receipt_sha256", "evaluator_implementation_sha256",
    "registered_sensitivity_ids", "registered_control_ids",
    "registered_quarantine_trigger_ids", "terminal_status", "scientific_verdict",
    "performance_claim", "independent_check_status", "outcome_accessed",
    "protected_labels_accessed", "limitations",
}


class EvaluatorError(ValueError):
    """Stable, sanitized evaluator-contract rejection."""


def require(condition, code):
    if not condition:
        raise EvaluatorError(code)


def _pairs(items):
    value = {}
    for key, item in items:
        require(key not in value, "EVALUATOR_DUPLICATE_KEY")
        value[key] = item
    return value


def loads_strict(raw):
    try:
        require(type(raw) in {bytes, str} and 0 < len(raw) <= MAX_JSON_BYTES,
                "EVALUATOR_JSON_SIZE")
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _value: (_ for _ in ()).throw(
                              EvaluatorError("EVALUATOR_NONFINITE")))
    except EvaluatorError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise EvaluatorError("EVALUATOR_JSON_INVALID") from None


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError):
        raise EvaluatorError("EVALUATOR_JSON_INVALID") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _strict(value, fields, code):
    require(type(value) is dict and set(value) == set(fields), code)
    return value


def _sha(value, code="EVALUATOR_SHA_INVALID"):
    require(type(value) is str and SHA.fullmatch(value), code)
    return value


def _id(value, code="EVALUATOR_ID_INVALID"):
    require(type(value) is str and ID.fullmatch(value), code)
    return value


def _scan(value):
    require(not FORBIDDEN_TEXT.search(canonical(value).decode("ascii")),
            "EVALUATOR_SENSITIVE_CONTENT")


def _load_policy():
    try:
        value = admission_policy.load_policy(POLICY_PATH)
    except Exception:
        raise EvaluatorError("EVALUATOR_POLICY_INVALID") from None
    require(admission_policy.digest(value) == ADMISSION_POLICY_SHA256,
            "EVALUATOR_POLICY_MISMATCH")
    return value


def _policy_rosters():
    value = _load_policy()
    return {
        "sensitivities": [item["id"] for item in value["sensitivities"]],
        "controls": [item["id"] for item in value["controls"]],
        "triggers": [item["id"] for item in value["quarantine_triggers"]],
    }


def validate_binding(value):
    try:
        runner_contracts.validate_binding(value)
    except runner_contracts.ContractError:
        raise EvaluatorError("EVALUATOR_AUTHORITY_BINDING_MISMATCH") from None
    require(set(value) == BINDING_FIELDS and
            value["admission_policy_sha256"] == ADMISSION_POLICY_SHA256,
            "EVALUATOR_AUTHORITY_BINDING_MISMATCH")
    return value


def validate_runner_receipt(value, runner_request=None):
    try:
        if runner_request is not None:
            runner_contracts.validate_request(runner_request)
        runner_contracts.validate_receipt(value, runner_request)
    except runner_contracts.ContractError:
        raise EvaluatorError("EVALUATOR_RUNNER_INVALID") from None
    require(value["status"] == "synthetic-structural-complete" and
            value["artifact"]["id"] == "structural-proof" and
            value["artifact"]["kind"] == "authority-binding-proof" and
            value["failure_code"] is None and value["outcome_accessed"] is False and
            value["protected_labels_accessed"] is False and
            value["performance_claim"] == "withheld",
            "EVALUATOR_RUNNER_NOT_SUCCESSFUL")
    validate_binding(value["authority_binding"])
    return value


def validate_runner_artifact(value, runner_request, runner_receipt):
    _strict(value, ARTIFACT_FIELDS, "EVALUATOR_RUNNER_ARTIFACT_SCHEMA")
    binding = runner_request["authority_binding"]
    expected = {"schema_version": 1, "kind": "synthetic_authority_binding_proof",
                "worker_version": fixed_worker.WORKER_VERSION,
                "request_sha256": runner_contracts.request_sha256(runner_request),
                "builder_receipt_sha256": binding["builder_receipt_sha256"],
                "observation_set_sha256": binding["observation_set_sha256"],
                "feature_snapshot_sha256": binding["feature_snapshot_sha256"],
                "evaluation_population_sha256": binding["evaluation_population_sha256"],
                "split_fingerprints": binding["split_fingerprints"],
                "outcome_accessed": False, "protected_labels_accessed": False,
                "performance_claim": "withheld"}
    require(value == expected, "EVALUATOR_RUNNER_ARTIFACT_INVALID")
    artifact_bytes = runner_contracts.canonical(value)
    require(hashlib.sha256(artifact_bytes).hexdigest() == runner_receipt["artifact"]["sha256"] and
            len(artifact_bytes) == runner_receipt["artifact"]["size_bytes"],
            "EVALUATOR_RUNNER_ARTIFACT_MISMATCH")
    return value, artifact_bytes


def _evaluation_id(runner_event_sha256, runner_receipt_sha256):
    _sha(runner_event_sha256); _sha(runner_receipt_sha256)
    identity = digest({"runner_event_sha256": runner_event_sha256,
                       "runner_receipt_sha256": runner_receipt_sha256})
    return "evaluation-" + identity[:24]


def _artifact_object(artifact):
    if type(artifact) is bytes:
        try:
            value = runner_contracts.loads_strict(
                artifact, runner_contracts.MAX_RECEIPT_BYTES,
                "EVALUATOR_RUNNER_ARTIFACT_SIZE")
        except runner_contracts.ContractError:
            raise EvaluatorError("EVALUATOR_RUNNER_ARTIFACT_INVALID") from None
        require(artifact == runner_contracts.canonical(value),
                "EVALUATOR_RUNNER_ARTIFACT_INVALID")
        return value, artifact
    require(type(artifact) is dict, "EVALUATOR_RUNNER_ARTIFACT_INVALID")
    return artifact, runner_contracts.canonical(artifact)


def create_request(runner_request, runner_receipt, runner_artifact,
                   runner_event_sha256, fixture_authority):
    require(isinstance(fixture_authority, authority_contract.FixtureAuthority),
            "EVALUATOR_AUTHORITY_REQUIRED")
    validate_runner_receipt(runner_receipt, runner_request)
    artifact_object, artifact_bytes = _artifact_object(runner_artifact)
    validate_runner_artifact(artifact_object, runner_request, runner_receipt)
    _sha(runner_event_sha256, "EVALUATOR_RUNNER_EVENT_INVALID")
    try:
        fixture_authority.verify_fixture_runner_event(
            runner_event_sha256, runner_request, runner_receipt, artifact_bytes)
    except authority_contract.AuthorityError:
        raise EvaluatorError("EVALUATOR_RUNNER_EVENT_INVALID") from None
    runner_sha = runner_contracts.digest(runner_receipt)
    value = {"schema_version": EVALUATOR_SCHEMA_VERSION,
             "kind": "synthetic_factor_evaluator_request",
             "evaluation_id": _evaluation_id(runner_event_sha256, runner_sha),
             "runner_event_sha256": runner_event_sha256,
             "runner_request": runner_request,
             "runner_receipt": runner_receipt,
             "runner_artifact": artifact_object}
    return validate_request(value, fixture_authority=fixture_authority)


def validate_request(value, *, fixture_authority=None):
    _strict(value, REQUEST_FIELDS, "EVALUATOR_REQUEST_SCHEMA")
    require(type(value["schema_version"]) is int and
            value["schema_version"] == EVALUATOR_SCHEMA_VERSION and
            value["kind"] == "synthetic_factor_evaluator_request",
            "EVALUATOR_REQUEST_INVALID")
    try:
        runner_contracts.validate_request(value["runner_request"])
    except runner_contracts.ContractError:
        raise EvaluatorError("EVALUATOR_RUNNER_REQUEST_INVALID") from None
    validate_runner_receipt(value["runner_receipt"], value["runner_request"])
    validate_runner_artifact(value["runner_artifact"], value["runner_request"],
                             value["runner_receipt"])
    _sha(value["runner_event_sha256"], "EVALUATOR_RUNNER_EVENT_INVALID")
    runner_sha = runner_contracts.digest(value["runner_receipt"])
    require(value["evaluation_id"] == _evaluation_id(value["runner_event_sha256"], runner_sha),
            "EVALUATOR_REQUEST_IDENTITY_MISMATCH")
    if fixture_authority is not None:
        require(isinstance(fixture_authority, authority_contract.FixtureAuthority),
                "EVALUATOR_AUTHORITY_REQUIRED")
        try:
            fixture_authority.verify_fixture_runner_event(
                value["runner_event_sha256"], value["runner_request"],
                value["runner_receipt"], runner_contracts.canonical(value["runner_artifact"]))
        except authority_contract.AuthorityError:
            raise EvaluatorError("EVALUATOR_RUNNER_EVENT_INVALID") from None
    return value


def _code_constant(value):
    if isinstance(value, types.CodeType):
        return _code_semantics(value)
    if value is None or type(value) in {bool, int, float, str}:
        return value
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, tuple):
        return [_code_constant(item) for item in value]
    if isinstance(value, frozenset):
        return {"frozenset": sorted(_code_constant(item) for item in value)}
    return {"type": type(value).__name__, "repr": repr(value)}


def _code_semantics(code):
    return {"name": code.co_name, "argcount": code.co_argcount,
            "kwonlyargcount": code.co_kwonlyargcount, "flags": code.co_flags,
            "bytecode": code.co_code.hex(), "names": list(code.co_names),
            "varnames": list(code.co_varnames),
            "constants": [_code_constant(item) for item in code.co_consts]}


def evaluator_implementation_sha256():
    semantic_functions = []
    for name, value in globals().items():
        if callable(value) and getattr(value, "__module__", None) == __name__ and hasattr(value, "__code__"):
            semantic_functions.append((name, _code_semantics(value.__code__)))
    return digest({"python_cache_tag": sys.implementation.cache_tag,
                   "schema_version": EVALUATOR_SCHEMA_VERSION,
                   "runner_schema_version": RUNNER_SCHEMA_VERSION,
                   "constants": {
                       "admission_policy_sha256": ADMISSION_POLICY_SHA256,
                       "authority_id": AUTHORITY_ID,
                       "authority_policy_sha256": AUTHORITY_POLICY_SHA256,
                       "authority_genesis_sha256": AUTHORITY_GENESIS_SHA256,
                       "binding_fields": sorted(BINDING_FIELDS),
                       "runner_binding_fields": sorted(runner_contracts.BINDING_KEYS),
                       "runner_implementation_sha256": runner_module.implementation_sha256(),
                       "authority_implementation_sha256": authority_contract.implementation_sha256(),
                       "runner_worker_version": fixed_worker.WORKER_VERSION,
                       "runner_request_validator": _code_semantics(runner_contracts.validate_request.__code__),
                       "runner_receipt_validator": _code_semantics(runner_contracts.validate_receipt.__code__),
                       "runner_binding_validator": _code_semantics(runner_contracts.validate_binding.__code__),
                       "runner_worker": _code_semantics(fixed_worker.build_artifact.__code__),
                       "authority_runner_event_verifier": _code_semantics(authority_contract.FixtureAuthority.verify_fixture_runner_event.__code__),
                       "admission_policy_validator": _code_semantics(admission_policy.validate_policy.__code__),
                       "admission_policy_sensitivities": admission_policy.SENSITIVITIES,
                       "admission_policy_controls": admission_policy.CONTROLS,
                       "admission_policy_triggers": admission_policy.TRIGGERS,
                       "admission_policy_blockers": admission_policy.BLOCKERS,
                       "request_fields": sorted(REQUEST_FIELDS),
                       "receipt_fields": sorted(RECEIPT_FIELDS),
                       "forbidden_pattern": FORBIDDEN_TEXT.pattern,
                       "forbidden_flags": FORBIDDEN_TEXT.flags,
                       "max_json_bytes": MAX_JSON_BYTES,
                   },
                   "functions": sorted(semantic_functions)})


def create_receipt(request):
    validate_request(request)
    rosters = _policy_rosters()
    value = {
        "schema_version": EVALUATOR_SCHEMA_VERSION,
        "kind": "synthetic_factor_evaluator_receipt",
        "evaluation_id": request["evaluation_id"],
        "request_sha256": digest(request),
        "authority_binding": request["runner_receipt"]["authority_binding"],
        "runner_receipt_sha256": digest(request["runner_receipt"]),
        "evaluator_implementation_sha256": evaluator_implementation_sha256(),
        "registered_sensitivity_ids": rosters["sensitivities"],
        "registered_control_ids": rosters["controls"],
        "registered_quarantine_trigger_ids": rosters["triggers"],
        "terminal_status": "synthetic-structural-complete",
        "scientific_verdict": "withheld",
        "performance_claim": "withheld",
        "independent_check_status": "unavailable",
        "outcome_accessed": False,
        "protected_labels_accessed": False,
        "limitations": [
            "Synthetic structural receipt only; no target data or publication authority."
        ],
    }
    return validate_receipt(value, request=request)


def validate_receipt(value, *, request=None):
    _strict(value, RECEIPT_FIELDS, "EVALUATOR_RECEIPT_SCHEMA")
    require(type(value["schema_version"]) is int and
            value["schema_version"] == EVALUATOR_SCHEMA_VERSION and
            value["kind"] == "synthetic_factor_evaluator_receipt" and
            value["terminal_status"] == "synthetic-structural-complete" and
            value["scientific_verdict"] == "withheld" and
            value["performance_claim"] == "withheld" and
            value["independent_check_status"] == "unavailable" and
            value["outcome_accessed"] is False and
            value["protected_labels_accessed"] is False,
            "EVALUATOR_RECEIPT_INVALID")
    _id(value["evaluation_id"]); _sha(value["request_sha256"])
    _sha(value["runner_receipt_sha256"]); _sha(value["evaluator_implementation_sha256"])
    validate_binding(value["authority_binding"])
    rosters = _policy_rosters()
    require(value["registered_sensitivity_ids"] == rosters["sensitivities"] and
            value["registered_control_ids"] == rosters["controls"] and
            value["registered_quarantine_trigger_ids"] == rosters["triggers"],
            "EVALUATOR_ROSTER_MISMATCH")
    require(type(value["limitations"]) is list and len(value["limitations"]) == 1 and
            type(value["limitations"][0]) is str and
            1 <= len(value["limitations"][0]) <= 500,
            "EVALUATOR_LIMITATIONS_INVALID")
    if request is not None:
        validate_request(request)
        require(value["evaluation_id"] == request["evaluation_id"] and
                value["request_sha256"] == digest(request) and
                value["runner_receipt_sha256"] == digest(request["runner_receipt"]) and
                value["authority_binding"] == request["runner_receipt"]["authority_binding"],
                "EVALUATOR_RECEIPT_BINDING_MISMATCH")
    _scan(value["limitations"])
    return value


def validate_receipt_set(receipts):
    require(type(receipts) is list and 1 <= len(receipts) <= 256,
            "EVALUATOR_RECEIPT_SET_INVALID")
    identities = set(); runners = set(); nonces = set()
    for value in receipts:
        validate_receipt(value)
        identity = value["evaluation_id"]
        runner = value["runner_receipt_sha256"]
        nonce = value["authority_binding"]["nonce_sha256"]
        require(identity not in identities and runner not in runners and nonce not in nonces,
                "EVALUATOR_DUPLICATE_EVALUATION")
        identities.add(identity); runners.add(runner); nonces.add(nonce)
    return receipts
