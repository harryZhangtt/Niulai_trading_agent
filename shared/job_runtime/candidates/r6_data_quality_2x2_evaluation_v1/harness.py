"""Pure local intake/validation for the disabled R6 DQ 2x2 evaluation candidate.

There is deliberately no provider, network, account, scheduler, or private-state
adapter in this package. Human records are intake only; the harness never creates
human judgments. ``seal_grade`` only seals a supplied record and is used by
explicit non-countable fixtures.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


class ContractError(ValueError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ContractError("CANONICAL_VALUE_INVALID") from None


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


SHA = re.compile(r"[0-9a-f]{64}\Z")
CELL_ORDER = ("R6DQ-7F2C91A4", "R6DQ-1B8E43D7", "R6DQ-C4A7095E", "R6DQ-92D6F0B3")
CELL_MAP = {
    "R6DQ-7F2C91A4": ("CLAUDE", "OFF"),
    "R6DQ-1B8E43D7": ("CODEX", "ON"),
    "R6DQ-C4A7095E": ("CLAUDE", "ON"),
    "R6DQ-92D6F0B3": ("CODEX", "OFF"),
}
ALIASES = dict(zip(CELL_ORDER, ("BLIND-01", "BLIND-02", "BLIND-03", "BLIND-04")))
DIMENSIONS = (
    "freshness", "richness", "depth", "accuracy", "citation_accuracy",
    "source_coverage", "incremental_information_value", "cost", "latency",
)
LEVELS = ("L0_UNUSABLE", "L1_WEAK", "L2_ADEQUATE", "L3_STRONG", "L4_EXCEPTIONAL")
HARD_GATES = (
    "cell_identity_unique", "frozen_payload_cutoff", "provider_model_effort",
    "common_tool_web_allowance", "common_budget_time", "common_engine_contracts",
    "one_attempt_no_replay", "raw_and_sanitized_custody", "reference_parseability",
    "terminal_unknown_durability", "dq_treatment_integrity", "all_variants_retained",
)
REQUIRED_REF_KINDS = (
    "sanitized_output", "evidence_record", "source_inventory", "citation_inventory",
    "deterministic_gate_report", "raw_custody_receipt",
)
SCHEMA_DIR = Path(__file__).resolve().parent


def _closed(value: Mapping[str, Any], required: Iterable[str], allowed: Iterable[str], code: str) -> None:
    req, allow = set(required), set(allowed)
    require(set(value) >= req, code + "_MISSING")
    require(set(value) <= allow, code + "_EXTRA")


def _ref(value: Mapping[str, Any], code: str) -> None:
    _closed(value, ("kind", "path", "sha256", "bytes", "immutable_at_ms"),
            ("kind", "path", "sha256", "bytes", "immutable_at_ms"), code)
    require(isinstance(value["kind"], str) and value["kind"], code + "_KIND")
    require(isinstance(value["path"], str) and value["path"] and not value["path"].startswith("/"), code + "_PATH")
    require(bool(SHA.fullmatch(str(value["sha256"]))), code + "_SHA")
    require(isinstance(value["bytes"], int) and not isinstance(value["bytes"], bool) and value["bytes"] >= 0, code + "_BYTES")
    require(isinstance(value["immutable_at_ms"], int) and value["immutable_at_ms"] > 0, code + "_TIME")


def _seal(body: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(body)
    out["artifact_sha256"] = sha256_json(out)
    out["artifact_bytes"] = len(canonical_bytes(body))
    return out


def _verify_seal(value: Mapping[str, Any], code: str) -> None:
    require(value.get("immutable") is True, code + "_NOT_IMMUTABLE")
    body = {k: v for k, v in value.items() if k not in ("artifact_sha256", "artifact_bytes")}
    require(value.get("artifact_sha256") == sha256_json(body), code + "_HASH")
    require(value.get("artifact_bytes") == len(canonical_bytes(body)), code + "_BYTES")


def preflight_readiness(storage_manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate local storage and grade-intake schemas before any future call.

    This candidate has no call path. A PASS means only that local evaluation
    storage/intake contracts are parseable, closed, identity-bound, and disabled.
    """
    checked = []
    for name, expected_id in (
        ("evaluation-storage-v1.schema.json", "r6-data-quality-2x2-evaluation-storage-v1"),
        ("grade-record-v1.schema.json", "r6-data-quality-2x2-grade-record-v1"),
    ):
        path = SCHEMA_DIR / name
        require(path.is_file(), "PREFLIGHT_SCHEMA_MISSING")
        schema = json.loads(path.read_text(encoding="utf-8"))
        require(schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema", "PREFLIGHT_SCHEMA_DRAFT")
        require(schema.get("$id") == expected_id, "PREFLIGHT_SCHEMA_ID")
        require(schema.get("type") == "object" and schema.get("additionalProperties") is False, "PREFLIGHT_SCHEMA_NOT_CLOSED")
        require(isinstance(schema.get("required"), list) and schema["required"], "PREFLIGHT_SCHEMA_REQUIRED")
        require(isinstance(schema.get("properties"), dict) and set(schema["required"]) <= set(schema["properties"]), "PREFLIGHT_SCHEMA_PROPERTIES")
        checked.append({"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size})
    _closed(storage_manifest,
            ("version", "activation", "provider_calls_permitted", "root", "atomic_create", "no_replace", "artifact_kinds"),
            ("version", "activation", "provider_calls_permitted", "root", "atomic_create", "no_replace", "artifact_kinds"),
            "STORAGE")
    require(storage_manifest["version"] == 1, "STORAGE_VERSION")
    require(storage_manifest["activation"] is False and storage_manifest["provider_calls_permitted"] is False, "STORAGE_DISABLED")
    require(isinstance(storage_manifest["root"], str) and storage_manifest["root"] and not storage_manifest["root"].startswith("/"), "STORAGE_ROOT")
    require(storage_manifest["atomic_create"] is True and storage_manifest["no_replace"] is True, "STORAGE_IMMUTABILITY")
    require(set(storage_manifest["artifact_kinds"]) >= set(REQUIRED_REF_KINDS) | {"blind_packet", "grade", "metric", "unblind"}, "STORAGE_KINDS")
    return {"status": "PASS_PROVIDER_FREE_PREFLIGHT", "activation": False,
            "provider_calls_permitted": False, "schemas": checked}


def build_blind_packet(cell_id: str, refs: Sequence[Mapping[str, Any]], committed_at_ms: int,
                       masking_breach: bool = False) -> Dict[str, Any]:
    require(cell_id in CELL_MAP, "PACKET_CELL")
    require(isinstance(committed_at_ms, int) and committed_at_ms > 0, "PACKET_TIME")
    kinds = []
    for item in refs:
        _ref(item, "PACKET_REF")
        kinds.append(item["kind"])
        require(item["immutable_at_ms"] <= committed_at_ms, "PACKET_REF_AFTER_COMMIT")
    require(len(kinds) == len(set(kinds)), "PACKET_REF_DUPLICATE")
    require(set(REQUIRED_REF_KINDS) <= set(kinds), "PACKET_REF_MISSING")
    forbidden = ("provider", "model", "addon", "dq_layer", "transport", "order", "cost", "latency")
    text = canonical_bytes(refs).decode("ascii").lower()
    require(not any(('"' + x + '"') in text for x in forbidden), "PACKET_UNBLINDED_METADATA")
    body = {"version": 1, "packet_id": "packet/" + ALIASES[cell_id],
            "blind_alias": ALIASES[cell_id], "committed_at_ms": committed_at_ms,
            "masking_breach": bool(masking_breach), "refs": [dict(x) for x in refs],
            "immutable": True}
    return _seal(body)


def seal_grade(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Seal supplied intake; never invents or changes a judgment."""
    body = dict(record)
    require("artifact_sha256" not in body and "artifact_bytes" not in body, "GRADE_ALREADY_SEALED")
    body["immutable"] = True
    return _seal(body)


def validate_grade(grade: Mapping[str, Any], packet: Mapping[str, Any], fixture: bool = False) -> None:
    required = (
        "version", "grade_id", "cell_blind_alias", "packet_sha256", "grader_role",
        "reviewer_kind", "human_reviewer_id", "blind", "countable", "dimensions",
        "hard_gates", "evidence_refs", "comments", "independence_attestation",
        "packet_committed_at_ms", "produced_at_ms", "immutable", "artifact_sha256",
        "artifact_bytes",
    )
    _closed(grade, required, required, "GRADE")
    _verify_seal(grade, "GRADE")
    _verify_seal(packet, "PACKET")
    require(grade["version"] == 1 and grade["grader_role"] in ("G1", "G2", "G3"), "GRADE_ROLE")
    require(grade["cell_blind_alias"] == packet["blind_alias"], "GRADE_ALIAS")
    require(grade["packet_sha256"] == packet["artifact_sha256"], "GRADE_PACKET_HASH")
    require(grade["packet_committed_at_ms"] == packet["committed_at_ms"], "GRADE_PACKET_TIME")
    require(isinstance(grade["produced_at_ms"], int) and grade["produced_at_ms"] > packet["committed_at_ms"], "GRADE_PREPACKET")
    require(grade["blind"] is True, "GRADE_NOT_BLIND")
    require(isinstance(grade["human_reviewer_id"], str) and grade["human_reviewer_id"], "GRADE_REVIEWER")
    if fixture:
        require(grade["reviewer_kind"] == "FIXTURE_HUMAN" and grade["countable"] is False, "FIXTURE_GRADE_COUNTABILITY")
    else:
        require(grade["reviewer_kind"] == "HUMAN" and grade["countable"] is True, "LIVE_FAKE_HUMAN_FORBIDDEN")
    require(tuple(grade["dimensions"].keys()) == DIMENSIONS, "GRADE_DIMENSION_ORDER")
    for dimension, level in grade["dimensions"].items():
        require(dimension in DIMENSIONS and level in LEVELS, "GRADE_LEVEL")
    require(tuple(grade["hard_gates"].keys()) == HARD_GATES, "GRADE_GATE_ORDER")
    require(all(v in ("PASS", "FAIL") for v in grade["hard_gates"].values()), "GRADE_GATE_VALUE")
    require(isinstance(grade["comments"], Mapping) and tuple(grade["comments"].keys()) == DIMENSIONS + ("hard_gates",), "GRADE_COMMENTS")
    require(all(isinstance(v, str) and v.strip() for v in grade["comments"].values()), "GRADE_COMMENT_EMPTY")
    require(isinstance(grade["evidence_refs"], list) and grade["evidence_refs"], "GRADE_EVIDENCE")
    packet_hashes = {r["sha256"] for r in packet["refs"]}
    require(all(bool(SHA.fullmatch(str(x))) and x in packet_hashes for x in grade["evidence_refs"]), "GRADE_EVIDENCE_REF")
    att = grade["independence_attestation"]
    _closed(att, ("no_contact_with_other_graders", "no_provider_identity_access", "no_mapping_access", "no_conflict_of_interest", "attested_at_ms"),
            ("no_contact_with_other_graders", "no_provider_identity_access", "no_mapping_access", "no_conflict_of_interest", "attested_at_ms"), "GRADE_ATTEST")
    require(all(att[x] is True for x in ("no_contact_with_other_graders", "no_provider_identity_access", "no_mapping_access", "no_conflict_of_interest")), "GRADE_NOT_INDEPENDENT")
    require(isinstance(att["attested_at_ms"], int) and packet["committed_at_ms"] < att["attested_at_ms"] <= grade["produced_at_ms"], "GRADE_ATTEST_TIME")


def _level_distance(left: str, right: str) -> int:
    return abs(LEVELS.index(left) - LEVELS.index(right))


def _g3_required(g1: Mapping[str, Any], g2: Mapping[str, Any]) -> bool:
    return any(g1["hard_gates"][x] != g2["hard_gates"][x] for x in HARD_GATES) or any(
        _level_distance(g1["dimensions"][x], g2["dimensions"][x]) > 1 for x in DIMENSIONS
    )


def _metric(status: str, numerator: Any, denominator: Any, missing: int, unknown: int,
            value: Any, **extra: Any) -> Dict[str, Any]:
    result = {"status": status, "numerator": numerator, "denominator": denominator,
              "missing_count": missing, "unknown_count": unknown, "value": value}
    result.update(extra)
    return result


def _unknown(*values: Any) -> bool:
    return any(v == "UNKNOWN" for v in values)


def _ratio(numerator: Any, denominator: Any, missing: int = 0, unknown: int = 0, **extra: Any) -> Dict[str, Any]:
    if unknown or _unknown(numerator, denominator):
        return _metric("UNKNOWN", numerator, denominator, missing, max(1, unknown), None, **extra)
    require(isinstance(numerator, int) and not isinstance(numerator, bool) and numerator >= 0, "METRIC_NUMERATOR")
    require(isinstance(denominator, int) and not isinstance(denominator, bool) and denominator >= 0, "METRIC_DENOMINATOR")
    require(numerator <= denominator, "METRIC_NUMERATOR_GT_DENOMINATOR")
    if denominator == 0:
        return _metric("NOT_APPLICABLE", numerator, denominator, missing, unknown, None, **extra)
    return _metric("VALUE", numerator, denominator, missing, unknown, numerator / denominator, **extra)


def _evidence(value: Mapping[str, Any]) -> None:
    required = (
        "version", "cell_id", "retained", "unknown_fields", "requested_field_count",
        "cited_source_count", "fresh_eligible_source_count", "requested_fields_without_eligible_citation",
        "metadata_correct_count", "depth_supported_field_count", "atomic_claim_count",
        "verified_atomic_claim_count", "citation_count", "citation_match_count",
        "uncited_numeric_claim_count", "covered_required_field_count", "correct_fact_ids",
        "false_fact_ids", "resolved_conflict_ids", "provider_cost_usd", "metered_tool_cost_usd",
        "elapsed_ms", "provider_time_ms", "tool_time_ms", "artifact_refs",
    )
    _closed(value, required, required, "EVIDENCE")
    require(value["version"] == 1 and value["cell_id"] in CELL_MAP and value["retained"] is True, "EVIDENCE_ID")
    require(value["requested_field_count"] == 6, "EVIDENCE_REQUIRED_FIELDS")
    require(isinstance(value["unknown_fields"], list) and len(value["unknown_fields"]) == len(set(value["unknown_fields"])), "EVIDENCE_UNKNOWN")
    for key in ("correct_fact_ids", "false_fact_ids", "resolved_conflict_ids"):
        require(isinstance(value[key], list) and len(value[key]) == len(set(value[key])) and all(isinstance(x, str) and x for x in value[key]), "EVIDENCE_FACT_IDS")
    for r in value["artifact_refs"]:
        _ref(r, "EVIDENCE_REF")


def derive_cell_metrics(evidence: Mapping[str, Any], off_evidence: Mapping[str, Any] = None) -> Dict[str, Any]:
    _evidence(evidence)
    unknown = len(evidence["unknown_fields"])
    m: Dict[str, Any] = {}
    m["freshness"] = _ratio(evidence["fresh_eligible_source_count"],
        evidence["cited_source_count"] + evidence["requested_fields_without_eligible_citation"],
        evidence["requested_fields_without_eligible_citation"], unknown)
    m["richness"] = _ratio(evidence["metadata_correct_count"], 60,
        60 - evidence["metadata_correct_count"] if evidence["metadata_correct_count"] != "UNKNOWN" else 0, unknown)
    m["depth"] = _ratio(evidence["depth_supported_field_count"], 6,
        6 - evidence["depth_supported_field_count"] if evidence["depth_supported_field_count"] != "UNKNOWN" else 0, unknown)
    m["accuracy"] = _ratio(evidence["verified_atomic_claim_count"], evidence["atomic_claim_count"],
        0, unknown)
    m["citation_accuracy"] = _ratio(evidence["citation_match_count"],
        evidence["citation_count"] + evidence["uncited_numeric_claim_count"], evidence["uncited_numeric_claim_count"], unknown)
    m["source_coverage"] = _ratio(evidence["covered_required_field_count"], 6,
        6 - evidence["covered_required_field_count"] if evidence["covered_required_field_count"] != "UNKNOWN" else 0, unknown)
    provider, addon = CELL_MAP[evidence["cell_id"]]
    if addon == "OFF":
        m["incremental_information_value"] = _metric("NOT_APPLICABLE", 0, 0, 0, unknown, None,
            false_new_fact_count=0, signed_false_new_fact_count=0)
    else:
        require(off_evidence is not None, "INCREMENTAL_OFF_EVIDENCE_MISSING")
        _evidence(off_evidence)
        require(CELL_MAP[off_evidence["cell_id"]] == (provider, "OFF"), "INCREMENTAL_PROVIDER_MISMATCH")
        unknown_i = unknown + len(off_evidence["unknown_fields"])
        on_correct = set(evidence["correct_fact_ids"]) | set(evidence["resolved_conflict_ids"])
        off_correct = set(off_evidence["correct_fact_ids"]) | set(off_evidence["resolved_conflict_ids"])
        new = on_correct - off_correct
        union = on_correct | off_correct
        false_new = set(evidence["false_fact_ids"]) - set(off_evidence["false_fact_ids"])
        m["incremental_information_value"] = _ratio(len(new), len(union), 0, unknown_i,
            false_new_fact_count=len(false_new), signed_false_new_fact_count=-len(false_new))
    costs = (evidence["provider_cost_usd"], evidence["metered_tool_cost_usd"])
    if _unknown(*costs) or unknown:
        m["cost"] = _metric("UNKNOWN", "UNKNOWN", 1, 0, max(1, unknown), None,
                            usd_per_correct_atomic_claim=None)
    else:
        require(all(isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0 for x in costs), "COST_INPUT")
        total = sum(costs)
        claims = evidence["verified_atomic_claim_count"]
        per_claim = None if claims in (0, "UNKNOWN") else total / claims
        m["cost"] = _metric("VALUE", total, 1, 0, 0, total,
                            usd_per_correct_atomic_claim=per_claim,
                            usd_per_correct_atomic_claim_status="NOT_APPLICABLE" if claims == 0 else "VALUE")
    times = (evidence["elapsed_ms"], evidence["provider_time_ms"], evidence["tool_time_ms"])
    if _unknown(*times) or unknown:
        m["latency"] = _metric("UNKNOWN", evidence["elapsed_ms"], 1, 0, max(1, unknown), None,
                               provider_time_ms=evidence["provider_time_ms"], tool_time_ms=evidence["tool_time_ms"])
    else:
        require(all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in times), "LATENCY_INPUT")
        m["latency"] = _metric("VALUE", evidence["elapsed_ms"], 1, 0, 0, evidence["elapsed_ms"],
                               provider_time_ms=evidence["provider_time_ms"], tool_time_ms=evidence["tool_time_ms"])
    require(tuple(m.keys()) == DIMENSIONS, "METRIC_ORDER")
    body = {"version": 1, "cell_id": evidence["cell_id"], "evidence_sha256": sha256_json(evidence),
            "metrics": m, "immutable": True}
    return _seal(body)


def validate_metric_artifact(metric: Mapping[str, Any], evidence: Mapping[str, Any], off_evidence: Mapping[str, Any] = None) -> None:
    _verify_seal(metric, "METRIC")
    expected = derive_cell_metrics(evidence, off_evidence)
    require(metric == expected, "METRIC_TAMPER_OR_DERIVATION_MISMATCH")


def _contrast(values: Mapping[str, Any], terms: Sequence[Tuple[float, str]]) -> Dict[str, Any]:
    selected = [values[cell] for _, cell in terms]
    if any(x["status"] == "UNKNOWN" for x in selected):
        return {"status": "UNKNOWN", "value": None, "formula": list(terms)}
    if any(x["status"] == "NOT_APPLICABLE" for x in selected):
        return {"status": "NOT_APPLICABLE", "value": None, "formula": list(terms)}
    return {"status": "VALUE", "value": sum(weight * values[cell]["value"] for weight, cell in terms), "formula": list(terms)}


def derive_block_metrics(evidence_by_cell: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    require(tuple(evidence_by_cell.keys()) == CELL_ORDER, "BLOCK_EVIDENCE_ORDER")
    off = {provider: evidence_by_cell[cell] for cell, (provider, addon) in CELL_MAP.items() if addon == "OFF"}
    artifacts = {}
    for cell in CELL_ORDER:
        provider, addon = CELL_MAP[cell]
        artifacts[cell] = derive_cell_metrics(evidence_by_cell[cell], off[provider] if addon == "ON" else None)
    contrasts = {}
    for dimension in DIMENSIONS:
        values = {cell: artifacts[cell]["metrics"][dimension] for cell in CELL_ORDER}
        contrasts[dimension] = {
            "provider_within_off": _contrast(values, ((1, "R6DQ-92D6F0B3"), (-1, "R6DQ-7F2C91A4"))),
            "provider_within_on": _contrast(values, ((1, "R6DQ-1B8E43D7"), (-1, "R6DQ-C4A7095E"))),
            "addon_within_claude": _contrast(values, ((1, "R6DQ-C4A7095E"), (-1, "R6DQ-7F2C91A4"))),
            "addon_within_codex": _contrast(values, ((1, "R6DQ-1B8E43D7"), (-1, "R6DQ-92D6F0B3"))),
            "provider_main_effect": _contrast(values, ((.5, "R6DQ-92D6F0B3"), (.5, "R6DQ-1B8E43D7"), (-.5, "R6DQ-7F2C91A4"), (-.5, "R6DQ-C4A7095E"))),
            "addon_main_effect": _contrast(values, ((.5, "R6DQ-C4A7095E"), (.5, "R6DQ-1B8E43D7"), (-.5, "R6DQ-7F2C91A4"), (-.5, "R6DQ-92D6F0B3"))),
            "interaction": _contrast(values, ((1, "R6DQ-1B8E43D7"), (-1, "R6DQ-92D6F0B3"), (-1, "R6DQ-C4A7095E"), (1, "R6DQ-7F2C91A4"))),
        }
    body = {"version": 1, "cell_metrics": artifacts, "contrasts": contrasts,
            "unknown_count": sum(m["unknown_count"] for a in artifacts.values() for m in a["metrics"].values()),
            "immutable": True}
    return _seal(body)


def evaluate_cell(packet: Mapping[str, Any], grades: Sequence[Mapping[str, Any]],
                  deterministic_gates: Mapping[str, str], fixture: bool = False) -> Dict[str, Any]:
    _verify_seal(packet, "PACKET")
    require(tuple(deterministic_gates.keys()) == HARD_GATES, "DETERMINISTIC_GATE_ORDER")
    require(all(x in ("PASS", "FAIL") for x in deterministic_gates.values()), "DETERMINISTIC_GATE_VALUE")
    roles = [x.get("grader_role") for x in grades]
    require(roles.count("G1") == 1 and roles.count("G2") == 1, "G1_G2_REQUIRED")
    require(len(roles) == len(set(roles)), "GRADE_ROLE_DUPLICATE")
    by_role = {g["grader_role"]: g for g in grades}
    for grade in grades:
        validate_grade(grade, packet, fixture)
    require(by_role["G1"]["human_reviewer_id"] != by_role["G2"]["human_reviewer_id"], "G1_G2_NONINDEPENDENT")
    needed = _g3_required(by_role["G1"], by_role["G2"])
    require(("G3" in by_role) == needed, "G3_REQUIREMENT")
    if needed:
        require(by_role["G3"]["human_reviewer_id"] not in (by_role["G1"]["human_reviewer_id"], by_role["G2"]["human_reviewer_id"]), "G3_NONINDEPENDENT")
        for gate, disposition in deterministic_gates.items():
            require(not (disposition == "FAIL" and by_role["G3"]["hard_gates"][gate] == "PASS"), "G3_HARD_GATE_OVERRIDE")
    final_grade = by_role.get("G3")
    final_gates = dict(final_grade["hard_gates"] if final_grade else by_role["G1"]["hard_gates"])
    for gate, disposition in deterministic_gates.items():
        if disposition == "FAIL":
            final_gates[gate] = "FAIL"
    return {"status": "COMPLETE" if all(x == "PASS" for x in final_gates.values()) else "HARD_GATE_FAIL",
            "g3_required": needed, "final_hard_gates": final_gates,
            "latest_grade_at_ms": max(g["produced_at_ms"] for g in grades),
            "countable": (not fixture) and all(x == "PASS" for x in final_gates.values())}


def authorize_unblinding(packets: Mapping[str, Mapping[str, Any]],
                         grades: Mapping[str, Sequence[Mapping[str, Any]]],
                         deterministic_gates: Mapping[str, Mapping[str, str]],
                         block_metric: Mapping[str, Any], evidence_by_cell: Mapping[str, Mapping[str, Any]],
                         mapping: Mapping[str, Mapping[str, str]], nonce: str,
                         commitment_sha256: str, opened_at_ms: int,
                         fixture: bool = False) -> Dict[str, Any]:
    require(tuple(packets.keys()) == CELL_ORDER and tuple(grades.keys()) == CELL_ORDER and tuple(deterministic_gates.keys()) == CELL_ORDER, "UNBLIND_FOUR_CELLS")
    results = {}
    latest = 0
    for cell in CELL_ORDER:
        require(packets[cell]["blind_alias"] == ALIASES[cell], "UNBLIND_ALIAS")
        results[cell] = evaluate_cell(packets[cell], grades[cell], deterministic_gates[cell], fixture)
        latest = max(latest, results[cell]["latest_grade_at_ms"])
    _verify_seal(block_metric, "BLOCK_METRIC")
    require(block_metric == derive_block_metrics(evidence_by_cell), "BLOCK_METRIC_TAMPER_OR_DERIVATION_MISMATCH")
    latest = max(latest, max(p["committed_at_ms"] for p in packets.values()))
    require(isinstance(opened_at_ms, int) and opened_at_ms > latest, "UNBLIND_EARLY")
    expected_mapping = {ALIASES[cell]: {"cell_id": cell, "provider": CELL_MAP[cell][0], "addon": CELL_MAP[cell][1]} for cell in CELL_ORDER}
    require(mapping == expected_mapping, "UNBLIND_MAPPING")
    require(isinstance(nonce, str) and nonce, "UNBLIND_NONCE")
    require(commitment_sha256 == sha256_json({"mapping": mapping, "nonce": nonce}), "UNBLIND_COMMITMENT")
    no_unknown = block_metric["unknown_count"] == 0
    countable = (not fixture) and no_unknown and all(r["countable"] for r in results.values())
    body = {"version": 1, "opened_at_ms": opened_at_ms, "mapping": dict(mapping),
            "commitment_sha256": commitment_sha256, "block_metric_sha256": block_metric["artifact_sha256"],
            "cell_evaluations": results, "countable": countable,
            "status": "COUNTABLE" if countable else "FIXTURE_NOT_COUNTABLE" if fixture else "INCONCLUSIVE_NOT_COUNTABLE",
            "immutable": True}
    return _seal(body)
