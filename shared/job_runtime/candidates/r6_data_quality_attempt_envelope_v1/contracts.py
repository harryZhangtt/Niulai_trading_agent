"""Closed provider-neutral contracts for the disabled R6 DQ attempt sidecar."""
from __future__ import annotations
import hashlib, json, math, re
from typing import Any, Dict, Iterable, Mapping

SHA = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
CELL_BINDINGS = {
    "R6DQ-7F2C91A4": ("ARM-A", "CONDITION-X", False),
    "R6DQ-1B8E43D7": ("ARM-B", "CONDITION-Y", True),
    "R6DQ-C4A7095E": ("ARM-A", "CONDITION-Y", True),
    "R6DQ-92D6F0B3": ("ARM-B", "CONDITION-X", False),
}
PROVIDER_BINDINGS = {
    "ARM-A": {"blind_provider_label":"ARM-A","provider_schema":"claude-evidence-v1","adapter_type":"ClaudeAttemptAdapterV9","publication_driver":"claude_publish_public","publication_driver_identity_sha256":"1ae0b76d43fcc2371042d78cefadcb89f972c14c7aac80f251b7a61ff9d5dd25","research_material_profile_sha256":"95fd61d9271ed5659d75fa036393724c11a9fe7e22f46ca226294c2fb9311468"},
    "ARM-B": {"blind_provider_label":"ARM-B","provider_schema":"stage-b-execution-v3","adapter_type":"CodexAttemptAdapterV9","publication_driver":"AtomicPublisher.publish","publication_driver_identity_sha256":"15c4baba5461bf501f08b713be9dddfeb881e31832e09bd66bc04e3b9099d3a6","research_material_profile_sha256":"99d77ac9cc71d9f2fed80c65b956d2c15af32e327e8a6abb9b47f52051c9a9c3"},
}
PROVIDER_IDENTITY_KEYS = frozenset(("blind_provider_label","provider_schema","adapter_type","publication_driver","publication_driver_identity_sha256","research_material_profile_sha256"))
CHECK_NAMES = (
    "source_catalog_freshness", "evidence_metadata_completeness",
    "lineage_metadata_completeness", "official_evidence_conflict",
    "duplicate_fact_citation", "dq_publication_quality",
)
KEY_FIELDS = ("cell_id", "job_id", "slot_id", "attempt_id", "operation_id",
              "prompt_binding_sha256", "canonical_engine_readback_digest")
TERMINALS = frozenset(("PASS", "FAIL", "STOP", "MALFORMED", "MISSING", "UNKNOWN"))
TRACE = ("provider_terminal", "immutable_owner_private_raw_ref", "provider_neutral_envelope",
         "addon_decision", "sanitized_publication_decision", "canonical_engine_readback_ref")
SECRET = re.compile(r"bearer\s+|authorization|cookie|set-cookie|api[_-]?key|token|secret", re.I)

class ContractError(ValueError):
    """Content-free contract rejection."""

def require(condition: bool, code: str) -> None:
    if not condition: raise ContractError(code)

def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ContractError("CANONICAL_VALUE_INVALID") from None

def validate_json_tree(value: Any, code: str = "JSON_VALUE_INVALID", depth: int = 0) -> Any:
    require(depth <= 64, code)
    if value is None or type(value) in (bool, str, int): return value
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

def canonical_json_bytes(value: Any, code: str = "JSON_VALUE_INVALID") -> bytes:
    validate_json_tree(value, code); return canonical_bytes(value)

def strict_json_loads(value: str, code: str = "JSON_TEXT_INVALID") -> Any:
    require(type(value) is str, code)
    def pairs(items: Any) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, item in items:
            require(type(key) is str and key not in result, code); result[key] = item
        return result
    def invalid_constant(_: str) -> Any: raise ContractError(code)
    try: parsed = json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (json.JSONDecodeError, UnicodeError, RecursionError): raise ContractError(code) from None
    validate_json_tree(parsed, code); return parsed

def sha256_bytes(value: bytes) -> str:
    require(type(value) is bytes, "BYTES_REQUIRED")
    return hashlib.sha256(value).hexdigest()

def sha256_json(value: Any) -> str: return sha256_bytes(canonical_bytes(value))

def exact(value: Any, keys: Iterable[str], code: str) -> Mapping[str, Any]:
    require(type(value) is dict and set(value) == set(keys), code); return value

def digest(value: Any, code: str) -> str:
    require(type(value) is str and SHA.fullmatch(value) is not None, code); return value

def identity(value: Any, code: str) -> str:
    require(type(value) is str and ID.fullmatch(value) is not None, code); return value

def validate_key(value: Any) -> Mapping[str, Any]:
    value = exact(value, KEY_FIELDS, "KEY_SHAPE")
    require(value["cell_id"] in CELL_BINDINGS, "CELL_ID_INVALID")
    for key in ("job_id", "slot_id", "attempt_id", "operation_id"): identity(value[key], "ENGINE_ID_INVALID")
    digest(value["prompt_binding_sha256"], "PROMPT_BINDING_INVALID")
    digest(value["canonical_engine_readback_digest"], "READBACK_DIGEST_INVALID")
    return value

def validate_ref(value: Any, code: str = "REF_SHAPE") -> Mapping[str, Any]:
    value = exact(value, ("name", "sha256", "bytes", "owner_private", "public"), code)
    identity(value["name"], "REF_NAME_INVALID"); digest(value["sha256"], "REF_DIGEST_INVALID")
    require(type(value["bytes"]) is int and 0 <= value["bytes"] <= 1048576, "REF_BYTES_INVALID")
    require(value["owner_private"] is True and value["public"] is False, "REF_PRIVACY_INVALID")
    return value

def validate_artifact_ref(value: Any) -> Mapping[str, Any]:
    value = exact(value, ("name", "provider_schema", "publication_driver_identity_sha256", "sha256", "bytes", "owner_private", "public", "provider_validated"), "ARTIFACT_REF_SHAPE")
    identity(value["name"], "ARTIFACT_REF_NAME")
    require(value["provider_schema"] in ("claude-evidence-v1", "stage-b-execution-v3"), "ARTIFACT_REF_SCHEMA")
    digest(value["publication_driver_identity_sha256"], "ARTIFACT_REF_DRIVER_IDENTITY")
    digest(value["sha256"], "ARTIFACT_REF_DIGEST")
    require(type(value["bytes"]) is int and 2 <= value["bytes"] <= 1048576, "ARTIFACT_REF_BYTES")
    require(value["owner_private"] is True and value["public"] is False and type(value["provider_validated"]) is bool, "ARTIFACT_REF_FENCE")
    return value

def validate_provider_identity(value: Any) -> Mapping[str, Any]:
    value = exact(value, PROVIDER_IDENTITY_KEYS, "PROVIDER_IDENTITY_SHAPE")
    require(value["blind_provider_label"] in PROVIDER_BINDINGS, "PROVIDER_IDENTITY_LABEL")
    expected = PROVIDER_BINDINGS[value["blind_provider_label"]]
    require(canonical_json_bytes(value, "PROVIDER_IDENTITY_TYPE") == canonical_json_bytes(expected, "PROVIDER_IDENTITY_TYPE"), "PROVIDER_IDENTITY_MISMATCH")
    return value

def validate_readback(value: Any) -> Mapping[str, Any]:
    value = exact(value, ("version", "job_id", "slot_id", "attempt_id", "operation_id",
                          "prompt_binding_sha256", "transaction", "counts"), "READBACK_SHAPE")
    require(value["version"] == 1 and type(value["version"]) is int, "READBACK_VERSION")
    for key in ("job_id", "slot_id", "attempt_id", "operation_id"): identity(value[key], "READBACK_ID")
    digest(value["prompt_binding_sha256"], "READBACK_PROMPT")
    require(value["transaction"] in ("BEGIN_IMMEDIATE_POST_WRITE_READBACK", "BEGIN_IMMEDIATE_SINGLE_READBACK"), "READBACK_TRANSACTION")
    counts = exact(value["counts"], ("job", "slot", "attempt"), "READBACK_COUNTS")
    require(all(type(v) is int and v == 1 for v in counts.values()), "READBACK_CARDINALITY")
    return value

def derive_readback_match(key: Mapping[str, Any], readback: Mapping[str, Any]) -> bool:
    validate_key(dict(key)); validate_readback(dict(readback))
    return (all(readback[k] == key[k] for k in ("job_id", "slot_id", "attempt_id", "operation_id", "prompt_binding_sha256")) and
            sha256_json(readback) == key["canonical_engine_readback_digest"])

def derive_decisions(value: Mapping[str, Any]) -> tuple:
    checks = value["dq_checks"]; enabled = value["checks_enabled"]
    validate_checks(checks, enabled)
    derived_readback = derive_readback_match(value["key"], value["readback_ref"])
    safety = (value["raw_capture_verified"] and value["provider_artifact_validated"] and
              value["sanitization_safe"] and derived_readback)
    statuses = tuple(item["status"] for item in checks)
    if value["terminal_state"] == "UNKNOWN" or (enabled and "UNKNOWN" in statuses):
        return derived_readback, "UNKNOWN", "SUPPRESS_UNKNOWN"
    if not safety:
        return derived_readback, "REJECT", "SUPPRESS_SAFETY"
    if value["terminal_state"] != "PASS":
        return derived_readback, "REJECT", "SUPPRESS_TERMINAL"
    if enabled:
        if statuses == ("PASS",) * 6:
            return derived_readback, "ALLOW", "DELEGATE_SANITIZED"
        return derived_readback, "REJECT", "SUPPRESS_GATE_REJECTED"
    require(statuses == ("NOT_RUN_TREATMENT_DISABLED",) * 6, "OFF_CHECK_SEMANTICS")
    return derived_readback, "ALLOW", "DELEGATE_SANITIZED"

def validate_attempt(value: Any) -> Mapping[str, Any]:
    value = exact(value, ("version", "key", "blind_provider_label", "blind_addon_label",
                          "checks_enabled", "terminal_state", "raw_ref", "publication_artifact_ref",
                          "source_inventory", "citation_inventory", "source_cutoff_sha256", "provider_identity",
                          "raw_capture_before_decision", "no_replay", "readback_ref"), "ATTEMPT_SHAPE")
    require(value["version"] == 1 and type(value["version"]) is int, "ATTEMPT_VERSION")
    key = validate_key(value["key"]); binding = CELL_BINDINGS[key["cell_id"]]; provider_identity = validate_provider_identity(value["provider_identity"])
    require(provider_identity == PROVIDER_BINDINGS[binding[0]], "ATTEMPT_PROVIDER_IDENTITY")
    require((value["blind_provider_label"], value["blind_addon_label"], value["checks_enabled"]) == binding,
            "BLIND_CELL_BINDING")
    require("claude" not in value["blind_provider_label"].lower() and "codex" not in value["blind_provider_label"].lower(), "PROVIDER_LABEL_NOT_BLIND")
    require(value["terminal_state"] in TERMINALS, "TERMINAL_INVALID")
    validate_ref(value["raw_ref"]); validate_artifact_ref(value["publication_artifact_ref"])
    for name in ("source_inventory", "citation_inventory"):
        require(type(value[name]) is list and len(value[name]) <= 256 and
                all(type(v) is str and 1 <= len(v) <= 256 for v in value[name]), "INVENTORY_INVALID")
    digest(value["source_cutoff_sha256"], "CUTOFF_INVALID")
    require(value["raw_capture_before_decision"] is True and value["no_replay"] is True, "ATTEMPT_FENCE_INVALID")
    readback = validate_readback(value["readback_ref"])
    derive_readback_match(key, readback)
    return value

def validate_checks(value: Any, enabled: bool) -> None:
    require(type(value) is list and len(value) == 6, "CHECK_COUNT")
    require(tuple(item.get("name") if type(item) is dict else None for item in value) == CHECK_NAMES, "CHECK_NAMES")
    for item in value:
        exact(item, ("name", "status", "code"), "CHECK_SHAPE")
        require(item["status"] in ("PASS", "FAIL", "UNKNOWN", "NOT_RUN_TREATMENT_DISABLED"), "CHECK_STATUS")
        identity(item["code"], "CHECK_CODE")
        if enabled: require(item["status"] != "NOT_RUN_TREATMENT_DISABLED", "ON_CHECK_DISABLED")
        else: require(item["status"] == "NOT_RUN_TREATMENT_DISABLED" and item["code"] == "NOT_RUN_TREATMENT_DISABLED", "OFF_CHECK_NOT_DISABLED")

DUPLICATED_AUTHORITY_FIELDS = (
    "blind_provider_label", "blind_addon_label", "checks_enabled", "terminal_state",
    "raw_ref", "source_inventory", "citation_inventory", "source_cutoff_sha256",
    "readback_ref", "key", "publication_artifact_ref", "provider_identity",
)
DUPLICATED_AUTHORITY_TYPES = {
    "blind_provider_label": str, "blind_addon_label": str, "checks_enabled": bool,
    "terminal_state": str, "raw_ref": dict, "source_inventory": list,
    "citation_inventory": list, "source_cutoff_sha256": str, "readback_ref": dict,
    "key": dict, "publication_artifact_ref": dict, "provider_identity": dict,
}

def canonical_cross_projection(attempt: Mapping[str, Any], envelope: Mapping[str, Any]) -> Dict[str, Any]:
    require(type(attempt) is dict and type(envelope) is dict, "ATTEMPT_BUNDLE_CROSS_BIND_SHAPE")
    representations: Dict[str, bytes] = {}
    for field in DUPLICATED_AUTHORITY_FIELDS:
        type_code = "ATTEMPT_BUNDLE_CROSS_BIND_TYPE_" + field.upper()
        require(field in attempt and field in envelope, type_code)
        require(type(attempt[field]) is DUPLICATED_AUTHORITY_TYPES[field] and type(envelope[field]) is DUPLICATED_AUTHORITY_TYPES[field], type_code)
        left = canonical_json_bytes(attempt[field], type_code); right = canonical_json_bytes(envelope[field], type_code)
        require(left == right, "ATTEMPT_BUNDLE_CROSS_BIND_" + field.upper()); representations[field] = left
    projection = dict(envelope)
    for field in DUPLICATED_AUTHORITY_FIELDS:
        projection[field] = strict_json_loads(representations[field].decode("ascii"), "ATTEMPT_BUNDLE_CROSS_BIND_TYPE_" + field.upper())
    return projection

def validate_envelope_structure(value: Any) -> Mapping[str, Any]:
    value = exact(value, ("version", "key", "blind_provider_label", "blind_addon_label",
                          "checks_enabled", "terminal_state", "raw_ref", "publication_artifact_ref",
                          "source_inventory", "citation_inventory", "source_cutoff_sha256", "readback_ref", "provider_identity",
                          "dq_checks", "gate_decision", "publication_decision", "denominator_member",
                          "retained", "raw_capture_verified", "provider_artifact_validated", "sanitization_safe", "readback_match",
                          "replay_allowed", "pipeline_trace"), "ENVELOPE_SHAPE")
    require(value["version"] == 1 and type(value["version"]) is int, "ENVELOPE_VERSION")
    key = validate_key(value["key"]); binding = CELL_BINDINGS[key["cell_id"]]; provider_identity = validate_provider_identity(value["provider_identity"])
    require(provider_identity == PROVIDER_BINDINGS[binding[0]], "ENVELOPE_PROVIDER_IDENTITY")
    require((value["blind_provider_label"], value["blind_addon_label"], value["checks_enabled"]) == binding, "ENVELOPE_CELL_BINDING")
    require(value["terminal_state"] in TERMINALS, "ENVELOPE_TERMINAL")
    validate_ref(value["raw_ref"]); validate_artifact_ref(value["publication_artifact_ref"])
    for name in ("source_inventory", "citation_inventory"):
        require(type(value[name]) is list and all(type(v) is str for v in value[name]), "ENVELOPE_INVENTORY")
    digest(value["source_cutoff_sha256"], "ENVELOPE_CUTOFF")
    validate_readback(value["readback_ref"])
    validate_checks(value["dq_checks"], value["checks_enabled"])
    require(value["gate_decision"] in ("ALLOW", "REJECT", "UNKNOWN"), "GATE_DECISION")
    require(value["publication_decision"] in ("DELEGATE_SANITIZED", "SUPPRESS_GATE_REJECTED", "SUPPRESS_TERMINAL", "SUPPRESS_UNKNOWN", "SUPPRESS_SAFETY"), "PUBLICATION_DECISION")
    require(value["denominator_member"] is True and value["retained"] is True and value["replay_allowed"] is False, "RETENTION_FENCE")
    require(all(type(value[k]) is bool for k in ("raw_capture_verified", "provider_artifact_validated", "sanitization_safe", "readback_match")), "SAFETY_BOOLEAN")
    require(tuple(value["pipeline_trace"]) == TRACE, "PIPELINE_TRACE")
    return value

def validate_envelope(value: Any, canonical_projection: Any = None) -> Mapping[str, Any]:
    value = validate_envelope_structure(value)
    semantic = value if canonical_projection is None else canonical_projection
    expected_readback, expected_gate, expected_publication = derive_decisions(semantic)
    require(value["readback_match"] is expected_readback, "READBACK_MATCH_NOT_DERIVED")
    require(value["gate_decision"] == expected_gate, "GATE_DECISION_NOT_DERIVED")
    require(value["publication_decision"] == expected_publication, "PUBLICATION_DECISION_NOT_DERIVED")
    return value

def validate_publication_decision(value: Any) -> Mapping[str, Any]:
    value = exact(value, ("version", "key_digest", "cell_id", "decision", "publication_artifact_sha256", "publication_driver_identity_sha256",
                          "raw_included", "path_included", "secret_included", "replay_allowed"), "PUBLIC_DECISION_SHAPE")
    require(value["version"] == 1 and type(value["version"]) is int, "PUBLIC_DECISION_VERSION")
    digest(value["key_digest"], "KEY_DIGEST"); digest(value["publication_artifact_sha256"], "PUBLICATION_ARTIFACT_DIGEST"); digest(value["publication_driver_identity_sha256"], "PUBLICATION_DRIVER_IDENTITY")
    require(value["cell_id"] in CELL_BINDINGS and value["decision"] in ("DELEGATE_SANITIZED", "SUPPRESS_GATE_REJECTED", "SUPPRESS_TERMINAL", "SUPPRESS_UNKNOWN", "SUPPRESS_SAFETY"), "PUBLIC_DECISION")
    require(value["raw_included"] is False and value["path_included"] is False and value["secret_included"] is False and value["replay_allowed"] is False, "PUBLIC_SAFETY")
    return value

__all__ = ["CELL_BINDINGS", "PROVIDER_BINDINGS", "PROVIDER_IDENTITY_KEYS", "CHECK_NAMES", "ContractError", "DUPLICATED_AUTHORITY_FIELDS", "DUPLICATED_AUTHORITY_TYPES", "TRACE", "canonical_bytes", "canonical_json_bytes", "canonical_cross_projection", "derive_decisions", "derive_readback_match",
           "research_material_profile", "sha256_bytes", "sha256_json", "strict_json_loads", "validate_json_tree", "validate_artifact_ref", "validate_attempt", "validate_envelope",
           "validate_envelope_structure", "validate_key", "validate_provider_identity", "validate_publication_decision", "validate_readback"]

DENOMINATOR_KEYS = frozenset(("version", "cell_id", "attempt_id", "terminal_state",
                              "disposition", "included", "replay_allowed", "envelope_sha256"))
BUNDLE_KEYS = frozenset(("version", "key", "key_digest", "normalized_attempt", "envelope",
                         "provider_publication_artifact_body", "publication_artifact_ref", "provider_identity",
                         "research_evidence", "raw_custody_receipt",
                         "denominator_record", "bundle_digest"))

def validate_denominator_record(value: Any, envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    value = exact(value, DENOMINATOR_KEYS, "DENOMINATOR_SHAPE")
    require(value["version"] == 1 and type(value["version"]) is int, "DENOMINATOR_VERSION")
    require(value["cell_id"] == envelope["key"]["cell_id"] and
            value["attempt_id"] == envelope["key"]["attempt_id"] and
            value["terminal_state"] == envelope["terminal_state"] and
            value["disposition"] == envelope["publication_decision"], "DENOMINATOR_BINDING")
    require(value["included"] is True and value["replay_allowed"] is False, "DENOMINATOR_FENCE")
    require(value["envelope_sha256"] == sha256_json(envelope), "DENOMINATOR_ENVELOPE_DIGEST")
    return value

OWNER_REF_KEYS = frozenset(("relative_ref", "bytes", "sha256", "canonical_sha256", "mode",
                            "owner_uid", "regular", "nofollow", "owner_private"))
EVIDENCE_BINDING_KEYS = frozenset(("cell_id", "job_id", "slot_id", "attempt_id", "operation_id",
                                   "prompt_binding_sha256", "canonical_engine_readback_digest",
                                   "source_cutoff_sha256", "blind_provider_label", "provider_schema", "publication_driver_identity_sha256"))
RESEARCH_EVIDENCE_KEYS = frozenset(("sanitized_output", "factual_evidence", "source_inventory",
                                    "citation_inventory"))
SUPPORT_ENTRY_KEYS = frozenset(("body", "ref", "canonical_sha256"))

def validate_owner_ref(value: Any) -> Mapping[str, Any]:
    value = exact(value, OWNER_REF_KEYS, "OWNER_REF_SHAPE")
    require(type(value["relative_ref"]) is str and 3 <= len(value["relative_ref"]) <= 512 and
            not value["relative_ref"].startswith("/") and "\\" not in value["relative_ref"] and
            "\x00" not in value["relative_ref"] and
            all(part not in ("", ".", "..") for part in value["relative_ref"].split("/")),
            "OWNER_REF_PATH_INVALID")
    require(type(value["bytes"]) is int and not isinstance(value["bytes"], bool) and
            1 <= value["bytes"] <= 1048576, "OWNER_REF_BYTES_INVALID")
    digest(value["sha256"], "OWNER_REF_SHA256_INVALID")
    digest(value["canonical_sha256"], "OWNER_REF_CANONICAL_SHA256_INVALID")
    require(value["sha256"] == value["canonical_sha256"], "OWNER_REF_DIGEST_CONFLICT")
    require(value["mode"] == "0600" and type(value["owner_uid"]) is int and
            not isinstance(value["owner_uid"], bool) and value["owner_uid"] >= 0 and
            value["regular"] is True and value["nofollow"] is True and
            value["owner_private"] is True, "OWNER_REF_SAFETY_INVALID")
    return value

def validate_evidence_binding(value: Any, key: Mapping[str, Any], cutoff: str,
                              provider_label: str, provider_schema: str, driver_identity: str) -> Mapping[str, Any]:
    value = exact(value, EVIDENCE_BINDING_KEYS, "EVIDENCE_BINDING_SHAPE")
    expected = {field: key[field] for field in ("cell_id", "job_id", "slot_id", "attempt_id",
               "operation_id", "prompt_binding_sha256", "canonical_engine_readback_digest")}
    expected["source_cutoff_sha256"] = cutoff
    expected["blind_provider_label"] = provider_label
    expected["provider_schema"] = provider_schema
    expected["publication_driver_identity_sha256"] = driver_identity
    require(canonical_json_bytes(value, "EVIDENCE_BINDING_TYPE") ==
            canonical_json_bytes(expected, "EVIDENCE_BINDING_TYPE"), "EVIDENCE_BINDING_MISMATCH")
    return value

def _safe_sanitized(value: Any, code: str) -> None:
    raw = canonical_json_bytes(value, code).decode("ascii")
    require(SECRET.search(raw) is None and "/Users/" not in raw and "../" not in raw,
            "RESEARCH_SECRET_OR_PATH_FORBIDDEN")

def _common_body(value: Any, keys: Iterable[str], code: str, key: Mapping[str, Any], cutoff: str,
                 terminal: str, raw_sha: str, artifact_sha: str,
                 provider_label: str, provider_schema: str, driver_identity: str) -> Mapping[str, Any]:
    value = exact(value, keys, code)
    require(value["version"] == 1 and type(value["version"]) is int, code)
    validate_evidence_binding(value["binding"], key, cutoff, provider_label, provider_schema, driver_identity)
    require(value["provider_terminal"] == terminal, "RESEARCH_TERMINAL_MISMATCH")
    require(value["raw_sha256"] == raw_sha, "RESEARCH_RAW_DIGEST_MISMATCH")
    require(value["publication_artifact_sha256"] == artifact_sha,
            "RESEARCH_PUBLICATION_ARTIFACT_MISMATCH")
    _safe_sanitized(value, code)
    return value

def research_material_profile(value: Mapping[str, Any]) -> str:
    normalized = strict_json_loads(canonical_bytes(dict(value)).decode("ascii"), "PROVIDER_MATERIAL_JSON")
    require(type(normalized) is dict and set(normalized) == {"sanitized_output", "factual_evidence", "source_inventory", "citation_inventory"}, "PROVIDER_MATERIAL_SHAPE")
    for name, body in normalized.items():
        require(type(body) is dict, "PROVIDER_MATERIAL_BODY")
        for field in ("binding", "provider_terminal", "raw_sha256", "publication_artifact_sha256"):
            body.pop(field, None)
        if name == "sanitized_output":
            body.pop("answer", None); body.pop("complete", None)
        if name == "source_inventory":
            for source in body.get("sources", []): source.pop("source_cutoff_sha256", None)
    return sha256_json(normalized)

def validate_research_evidence(value: Any, key: Mapping[str, Any], terminal: str,
                               raw_sha: str, artifact_sha: str, cutoff: str,
                               provider_label: str, provider_schema: str, driver_identity: str) -> Mapping[str, Any]:
    value = exact(value, RESEARCH_EVIDENCE_KEYS, "RESEARCH_EVIDENCE_SHAPE")
    common = ("version", "binding", "provider_terminal", "raw_sha256",
              "publication_artifact_sha256")
    output_entry = exact(value["sanitized_output"], SUPPORT_ENTRY_KEYS, "SANITIZED_OUTPUT_ENTRY")
    factual_entry = exact(value["factual_evidence"], SUPPORT_ENTRY_KEYS, "FACTUAL_EVIDENCE_ENTRY")
    source_entry = exact(value["source_inventory"], SUPPORT_ENTRY_KEYS, "SOURCE_INVENTORY_ENTRY")
    citation_entry = exact(value["citation_inventory"], SUPPORT_ENTRY_KEYS, "CITATION_INVENTORY_ENTRY")
    output = _common_body(output_entry["body"], common + ("answer", "claim_ids", "complete"),
                          "SANITIZED_OUTPUT_BODY", key, cutoff, terminal, raw_sha, artifact_sha, provider_label, provider_schema, driver_identity)
    require(type(output["answer"]) is str and 1 <= len(output["answer"]) <= 65536 and
            type(output["claim_ids"]) is list and len(output["claim_ids"]) <= 256 and
            all(type(item) is str and 1 <= len(item) <= 128 for item in output["claim_ids"]) and
            len(set(output["claim_ids"])) == len(output["claim_ids"]) and
            type(output["complete"]) is bool, "SANITIZED_OUTPUT_VALUE")
    factual = _common_body(factual_entry["body"], common + ("facts",), "FACTUAL_EVIDENCE_BODY",
                           key, cutoff, terminal, raw_sha, artifact_sha, provider_label, provider_schema, driver_identity)
    require(type(factual["facts"]) is list and len(factual["facts"]) <= 256,
            "FACTUAL_EVIDENCE_FACTS")
    fact_ids = set(); fact_claims = set()
    for fact in factual["facts"]:
        fact = exact(fact, ("fact_id", "claim_id", "value", "source_id", "citation_id"),
                     "FACTUAL_EVIDENCE_FACT")
        require(all(type(fact[name]) is str and 1 <= len(fact[name]) <= 4096 for name in fact),
                "FACTUAL_EVIDENCE_FACT_VALUE")
        require(fact["fact_id"] not in fact_ids, "FACTUAL_EVIDENCE_DUPLICATE_FACT")
        fact_ids.add(fact["fact_id"]); fact_claims.add(fact["claim_id"])
    sources = _common_body(source_entry["body"], common + ("sources",), "SOURCE_INVENTORY_BODY",
                           key, cutoff, terminal, raw_sha, artifact_sha, provider_label, provider_schema, driver_identity)
    require(type(sources["sources"]) is list and len(sources["sources"]) <= 256,
            "SOURCE_INVENTORY_SOURCES")
    source_map = {}
    for source in sources["sources"]:
        source = exact(source, ("source_id", "url", "document_identity_sha256",
                                "source_cutoff_sha256", "eligible", "literal_locations"),
                       "SOURCE_INVENTORY_SOURCE")
        require(type(source["source_id"]) is str and source["source_id"] not in source_map and
                type(source["url"]) is str and source["url"].startswith("https://") and
                len(source["url"]) <= 2048, "SOURCE_INVENTORY_ID_URL")
        digest(source["document_identity_sha256"], "SOURCE_DOCUMENT_IDENTITY")
        require(source["source_cutoff_sha256"] == cutoff and source["eligible"] is True,
                "SOURCE_CUTOFF_OR_ELIGIBILITY")
        require(type(source["literal_locations"]) is list and source["literal_locations"] and
                all(type(item) is str and 1 <= len(item) <= 512 for item in source["literal_locations"]),
                "SOURCE_LITERAL_LOCATIONS")
        source_map[source["source_id"]] = set(source["literal_locations"])
    citations = _common_body(citation_entry["body"], common + ("citations",),
                             "CITATION_INVENTORY_BODY", key, cutoff, terminal, raw_sha, artifact_sha, provider_label, provider_schema, driver_identity)
    require(type(citations["citations"]) is list and len(citations["citations"]) <= 256,
            "CITATION_INVENTORY_CITATIONS")
    citation_ids = set(); citation_claims = set(); citation_map = {}
    for citation in citations["citations"]:
        citation = exact(citation, ("citation_id", "claim_id", "source_id", "literal_location",
                                    "quote_sha256"), "CITATION_INVENTORY_CITATION")
        require(all(type(citation[name]) is str for name in
                    ("citation_id", "claim_id", "source_id", "literal_location")),
                "CITATION_INVENTORY_VALUE")
        digest(citation["quote_sha256"], "CITATION_QUOTE_DIGEST")
        require(citation["citation_id"] not in citation_ids and citation["source_id"] in source_map and
                citation["literal_location"] in source_map[citation["source_id"]],
                "CITATION_SOURCE_LOCATION_BINDING")
        citation_ids.add(citation["citation_id"]); citation_claims.add(citation["claim_id"]); citation_map[citation["citation_id"]] = citation
    claims = set(output["claim_ids"])
    require(fact_claims <= claims and citation_claims <= claims, "RESEARCH_CLAIM_BINDING")
    for fact in factual["facts"]:
        require(fact["source_id"] in source_map and fact["citation_id"] in citation_map and
                citation_map[fact["citation_id"]]["claim_id"] == fact["claim_id"] and
                citation_map[fact["citation_id"]]["source_id"] == fact["source_id"],
                "FACT_CITATION_SOURCE_TUPLE_BINDING")
    for entry, code in ((output_entry, "SANITIZED_OUTPUT"), (factual_entry, "FACTUAL_EVIDENCE"),
                        (source_entry, "SOURCE_INVENTORY"), (citation_entry, "CITATION_INVENTORY")):
        validate_owner_ref(entry["ref"])
        body_raw = canonical_json_bytes(entry["body"], code + "_BODY_TYPE")
        body_sha = sha256_bytes(body_raw)
        require(entry["canonical_sha256"] == body_sha and entry["ref"]["sha256"] == body_sha and
                entry["ref"]["bytes"] == len(body_raw), code + "_DIGEST_BINDING")
    expected_provider = PROVIDER_BINDINGS[provider_label]
    require(provider_schema == expected_provider["provider_schema"] and driver_identity == expected_provider["publication_driver_identity_sha256"], "PROVIDER_EVIDENCE_IDENTITY")
    bodies = {name: value[name]["body"] for name in ("sanitized_output", "factual_evidence", "source_inventory", "citation_inventory")}
    require(research_material_profile(bodies) == expected_provider["research_material_profile_sha256"], "PROVIDER_RESEARCH_MATERIAL_MISMATCH")
    return value

def validate_raw_custody_receipt(value: Any, key: Mapping[str, Any], terminal: str,
                                 raw_sha: str, cutoff: str,
                                 provider_label: str, provider_schema: str, driver_identity: str) -> Mapping[str, Any]:
    value = exact(value, ("version", "binding", "provider_terminal", "raw_sha256", "raw_ref"),
                  "RAW_CUSTODY_RECEIPT_SHAPE")
    require(value["version"] == 1 and type(value["version"]) is int, "RAW_CUSTODY_VERSION")
    validate_evidence_binding(value["binding"], key, cutoff, provider_label, provider_schema, driver_identity)
    require(value["provider_terminal"] == terminal and value["raw_sha256"] == raw_sha,
            "RAW_CUSTODY_BINDING")
    ref = validate_owner_ref(value["raw_ref"])
    require(ref["sha256"] == raw_sha, "RAW_CUSTODY_REF_DIGEST")
    return value

def validate_attempt_bundle(value: Any) -> Mapping[str, Any]:
    value = exact(value, BUNDLE_KEYS, "ATTEMPT_BUNDLE_SHAPE")
    require(value["version"] == 1 and type(value["version"]) is int, "ATTEMPT_BUNDLE_VERSION")
    require(type(value["normalized_attempt"]) is dict and type(value["envelope"]) is dict,
            "ATTEMPT_BUNDLE_CROSS_BIND_SHAPE")
    projection = canonical_cross_projection(value["normalized_attempt"], value["envelope"])
    key = validate_key(value["key"])
    require(value["key_digest"] == sha256_json(key), "ATTEMPT_BUNDLE_KEY_DIGEST")
    attempt = validate_attempt(value["normalized_attempt"])
    envelope = validate_envelope(value["envelope"], projection)
    artifact_ref = validate_artifact_ref(value["publication_artifact_ref"]); provider_identity = validate_provider_identity(value["provider_identity"])
    require(provider_identity == PROVIDER_BINDINGS[CELL_BINDINGS[key["cell_id"]][0]], "ATTEMPT_BUNDLE_PROVIDER_IDENTITY")
    require(attempt["key"] == key and envelope["key"] == key, "ATTEMPT_BUNDLE_KEY_BINDING")
    require(attempt["publication_artifact_ref"] == artifact_ref and
            envelope["publication_artifact_ref"] == artifact_ref, "ATTEMPT_BUNDLE_ARTIFACT_REF_BINDING")
    require(attempt["provider_identity"] == provider_identity and envelope["provider_identity"] == provider_identity, "ATTEMPT_BUNDLE_PROVIDER_CROSS_BINDING")
    require(artifact_ref["provider_schema"] == provider_identity["provider_schema"] and artifact_ref["publication_driver_identity_sha256"] == provider_identity["publication_driver_identity_sha256"], "ATTEMPT_BUNDLE_PROVIDER_ARTIFACT_IDENTITY")
    require(type(value["provider_publication_artifact_body"]) is str and
            2 <= len(value["provider_publication_artifact_body"].encode("ascii")) <= 1048576,
            "ATTEMPT_BUNDLE_ARTIFACT_BODY")
    parsed = strict_json_loads(value["provider_publication_artifact_body"], "ATTEMPT_BUNDLE_ARTIFACT_BODY")
    raw = canonical_bytes(parsed)
    require(raw.decode("ascii") == value["provider_publication_artifact_body"],
            "ATTEMPT_BUNDLE_ARTIFACT_NOT_CANONICAL")
    require(artifact_ref["sha256"] == sha256_bytes(raw) and artifact_ref["bytes"] == len(raw),
            "ATTEMPT_BUNDLE_ARTIFACT_DIGEST")
    raw_sha = attempt["raw_ref"]["sha256"]
    expected_provider_label = CELL_BINDINGS[key["cell_id"]][0]
    validate_raw_custody_receipt(value["raw_custody_receipt"], key, attempt["terminal_state"],
                                 raw_sha, attempt["source_cutoff_sha256"],
                                 expected_provider_label, artifact_ref["provider_schema"], provider_identity["publication_driver_identity_sha256"])
    validate_research_evidence(value["research_evidence"], key, attempt["terminal_state"],
                               raw_sha, artifact_ref["sha256"], attempt["source_cutoff_sha256"],
                               expected_provider_label, artifact_ref["provider_schema"], provider_identity["publication_driver_identity_sha256"])
    require([item["source_id"] for item in value["research_evidence"]["source_inventory"]["body"]["sources"]]
            == attempt["source_inventory"], "ATTEMPT_SOURCE_INVENTORY_BINDING")
    require([item["citation_id"] for item in value["research_evidence"]["citation_inventory"]["body"]["citations"]]
            == attempt["citation_inventory"], "ATTEMPT_CITATION_INVENTORY_BINDING")
    validate_denominator_record(value["denominator_record"], envelope)
    body = dict(value); observed = body.pop("bundle_digest")
    require(observed == sha256_json(body), "ATTEMPT_BUNDLE_DIGEST")
    return value

__all__ += ["BUNDLE_KEYS", "DENOMINATOR_KEYS", "EVIDENCE_BINDING_KEYS", "OWNER_REF_KEYS", "RESEARCH_EVIDENCE_KEYS", "SUPPORT_ENTRY_KEYS", "validate_attempt_bundle", "validate_denominator_record", "validate_evidence_binding", "validate_owner_ref", "validate_raw_custody_receipt", "validate_research_evidence"]
