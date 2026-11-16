#!/usr/bin/env python3
"""Deterministic, read-only verifier for the P0 attempt-envelope v10 design package."""
from __future__ import annotations
import argparse, copy, hashlib, json, re, sys
from pathlib import Path
from typing import Any, Mapping, Sequence
ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
STATUS = "DESIGN_ONLY_PENDING_SUCCESSOR_BYTES_AND_INDEPENDENT_REVIEW"
ARTIFACTS = ["architecture-v10.json","protocol-v10.json","schemas-v10.json","source-graph-v10.json","acceptance-v10.json","decision-v10.json","mentor-reviewable-design-v10-20261112.json"]
SHA = re.compile(r"^[0-9a-f]{64}$")
CHECK_NAMES = ["source_catalog_freshness","evidence_metadata_completeness","lineage_metadata_completeness","official_evidence_conflict","duplicate_fact_citation","dq_publication_quality"]
class VerificationError(ValueError): pass
def require(v: bool, code: str) -> None:
    if not v: raise VerificationError(code)
def strict_loads(raw: bytes) -> Any:
    require(not raw.startswith(b"\xef\xbb\xbf"), "UTF8_BOM")
    try: text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc: raise VerificationError("UTF8_INVALID") from exc
    def pairs(items: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        out = {}
        for k, v in items:
            require(k not in out, "JSON_DUPLICATE:" + k); out[k] = v
        return out
    def bad(v: str) -> None: raise VerificationError("JSON_NONFINITE:" + v)
    try: return json.loads(text, object_pairs_hook=pairs, parse_constant=bad)
    except VerificationError: raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc: raise VerificationError("JSON_INVALID") from exc
def load(path: Path) -> Any: return strict_loads(path.read_bytes())
def sha(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()
def verify_row(row: Mapping[str, Any], code: str) -> None:
    require(set(row) >= {"path","bytes","sha256"}, "ROW_SHAPE:" + code)
    require(isinstance(row["path"], str) and not row["path"].startswith("/") and ".." not in Path(row["path"]).parts, "ROW_PATH:" + code)
    require(isinstance(row["bytes"], int) and row["bytes"] >= 0 and isinstance(row["sha256"], str) and SHA.fullmatch(row["sha256"]) is not None, "ROW_VALUE:" + code)
    path = ROOT / row["path"]
    require(path.is_file() and not path.is_symlink(), "CLOSURE_DRIFT:MISSING_OR_ALIAS:" + row["path"])
    raw = path.read_bytes()
    require(len(raw) == row["bytes"], "CLOSURE_DRIFT:BYTES:" + row["path"])
    require(sha(raw) == row["sha256"], "CLOSURE_DRIFT:SHA256:" + row["path"])
def aggregate(nodes: Sequence[Mapping[str, Any]]) -> str:
    raw = b"".join(f"{n['path']}\0{n['bytes']}\0{n['sha256']}\n".encode("utf-8") for n in sorted(nodes, key=lambda x: x["path"]))
    return sha(raw)
def unresolved(artifacts: Mapping[str, Any]) -> list[str]:
    expected = artifacts["acceptance"]["unresolved_pins"]
    require(expected == artifacts["decision"]["unresolved_pins"] == artifacts["mentor"]["unresolved_pins"], "UNRESOLVED_LIST_DRIFT")
    graph = artifacts["source_graph"]["unresolved_pins"]
    require([x["pin"] for x in graph] == expected, "UNRESOLVED_GRAPH_DRIFT")
    require(all(x["path"] is None and x["bytes"] is None and x["sha256"] is None for x in graph), "UNRESOLVED_FALSE_PIN")
    return expected
def verify_schemas(s: Mapping[str, Any]) -> None:
    require(s["$schema"] == "https://json-schema.org/draft/2020-12/schema", "SCHEMA_DRAFT")
    require(s["status"] == STATUS and s["not_implementation"] is True, "SCHEMA_STATUS")
    defs = s["$defs"]; cond = defs["checks_enabled_dq_checks_conditional"]
    branch = cond["allOf"][0]; require(set(branch) == {"if","then","else"}, "SCHEMA_CONDITIONAL")
    enabled = defs["enabled_six_dq_checks"]; disabled = defs["disabled_six_dq_checks"]
    for name, schema, statuses, code in (("enabled",enabled,{"PASS","FAIL","UNKNOWN"},None),("disabled",disabled,{"NOT_RUN_TREATMENT_DISABLED"},"NOT_RUN_TREATMENT_DISABLED")):
        require(schema["minItems"] == schema["maxItems"] == 6 and schema["items"] is False, "SCHEMA_COUNT:" + name)
        require([x["properties"]["name"]["const"] for x in schema["prefixItems"]] == CHECK_NAMES, "SCHEMA_NAMES:" + name)
        for item in schema["prefixItems"]:
            status = item["properties"]["status"]; actual = {status["const"]} if "const" in status else set(status["enum"])
            require(actual == statuses, "SCHEMA_STATUS_SET:" + name)
            if code is not None: require(item["properties"]["code"] == {"const":code}, "SCHEMA_DISABLED_CODE")
    caller = defs["public_caller_input_no_provider_identity"]
    forbidden = {"provider_identity","adapter_type","publication_driver","provider_schema","research_material_profile_sha256","provider_root","executable"}
    require(caller["additionalProperties"] is False and not (set(caller["properties"]) & forbidden), "CALLER_PROVIDER_IDENTITY")
    providers = defs["sealed_provider_binding"]["oneOf"]
    require(len(providers) == 2 and {x["properties"]["blind_provider_label"]["const"] for x in providers} == {"ARM-A","ARM-B"}, "PROVIDER_BINDINGS")
    owner = defs["owner_uid_bound_artifact_ref"]; require(owner["properties"]["owner_uid"]["const"] == 501, "OWNER_UID")
    predecessor = defs["runner_v2_public_predecessor_identity"]; require(predecessor["additionalProperties"] is False and predecessor["properties"]["history_status"] == {"const":"OPEN"} and predecessor["properties"]["sha256"] == {"const":"bc45fceff79a1106ef66c09376075f3bb72a235ac4a23ca69b7344f914ff0bff"}, "PUBLIC_PREDECESSOR_IDENTITY")
    require(set(defs["fact_citation_source_tuple"]["required"]) == {"fact_id","claim_id","value","citation_id","source_id","literal_location","quote_sha256","url","document_identity_sha256","source_cutoff_sha256"}, "LINEAGE_TUPLE")
    fence = defs["terminal_crash_restart_no_replay_fence"]["properties"]
    require(all(fence[x]["const"] is False for x in ("replay_allowed","retry_allowed","status_query_allowed")), "NO_REPLAY_FENCE")
def verify_source_graph(g: Mapping[str, Any]) -> None:
    require(g["status"] == STATUS and g["authority"] == "NONE" and g["activation"] is False, "GRAPH_STATUS")
    nodes = g["nodes"]; require(len(nodes) == g["node_count"] and len({x["path"] for x in nodes}) == len(nodes), "GRAPH_NODE_SET")
    require(aggregate(nodes) == g["node_aggregate_sha256"], "CLOSURE_DRIFT:AGGREGATE")
    for i, node in enumerate(nodes): verify_row(node, "node-" + str(i))
    for name, row in g["anchors"].items(): verify_row(row, "anchor-" + name)
    external = g["external_identity_nodes"]
    require(len(external) == 2 and all(x["path"].startswith("/") and x["verification"] == "TRANSITIVE_VIA_PINNED_EXECUTION_WINDOW_SOURCE_CLOSURE_ONLY" for x in external), "EXTERNAL_IDENTITY_SHAPE")
    window = load(ROOT / g["anchors"]["execution_window_source_closure"]["path"])["provider_binary_identities"]
    expected_external = sorted((x["path"], x["bytes"], x["sha256"]) for x in window.values())
    actual_external = sorted((x["path"], x["bytes"], x["sha256"]) for x in external)
    require(actual_external == expected_external, "CLOSURE_DRIFT:EXTERNAL_IDENTITIES")
    required_sets = {"p0_v9_candidate_production_consumers","p0_v9_direct_dependencies","p0_v9_integration_bridge_dependencies","p0_v9_test_consumers","p0_v9_active_runtime_consumers","runner_v2_additive_production_consumer","runner_v2_additive_test_consumers","codex_v6_additive_production_and_schema_consumers","codex_v6_additive_test_consumers","codex_v6_transitive_dependencies","claude_v8_recursive_production_schema_and_test_consumers"}
    require(set(g["consumer_sets"]) == required_sets, "CONSUMER_SET_CLOSURE")
    node_paths = {x["path"] for x in nodes}
    for name, rows in g["consumer_sets"].items():
        for item in rows:
            require(item["path"] in node_paths, "CONSUMER_NOT_IN_GRAPH:" + name + ":" + item["path"])
def load_artifacts() -> dict[str, Any]:
    vals = {n[:-5].replace("-v10","").replace("-20261112","").replace("-","_"): load(PACKAGE/n) for n in ARTIFACTS}
    # Stable explicit names avoid filename-normalization ambiguity.
    return {"architecture":load(PACKAGE/ARTIFACTS[0]),"protocol":load(PACKAGE/ARTIFACTS[1]),"schemas":load(PACKAGE/ARTIFACTS[2]),"source_graph":load(PACKAGE/ARTIFACTS[3]),"acceptance":load(PACKAGE/ARTIFACTS[4]),"decision":load(PACKAGE/ARTIFACTS[5]),"mentor":load(PACKAGE/ARTIFACTS[6])}
def verify_structure() -> tuple[dict[str, Any], list[str]]:
    a = load_artifacts()
    for name, value in a.items(): require(value["status"] == STATUS, "STATUS:" + name)
    require(a["architecture"]["implementation_claimed"] is False and a["decision"]["implementation_claimed"] is False, "IMPLEMENTATION_CLAIM")
    require(a["source_graph"]["anchors"]["blind_map_v5_historical_review_revoked"]["current_status"] == "CONTRADICTED_HISTORY_ONLY_BY_13_FINDING_OPEN_REVIEW", "BLIND_MAP_HISTORY")
    require(a["source_graph"]["anchors"]["blind_map_v5_open_review_revoking_clean"]["sha256"] == "a76216d40b8af7617e7169f0969ab15bd69e3333dce6b6e9543af77612f783e8" and a["source_graph"]["anchors"]["blind_map_v5_open_review_revoking_clean"]["finding_count"] == 13, "BLIND_MAP_OPEN_REVIEW")
    require(a["source_graph"]["successor_requirements"]["blind_map_v6"]["status"] == "UNRESOLVED_CONTRACT_CLOSURE_PRODUCER_AND_CLEAN_REVIEW", "BLIND_MAP_V6")
    require(a["source_graph"]["anchors"]["claude_v8_open_review"]["sha256"] == "65e425cab9b0fd7ed9381e0f8019360fad0e5c0f2da432c3b5c4e4c27c16df0d" and a["source_graph"]["anchors"]["claude_v8_open_review"]["verdict"] == "OPEN", "CLAUDE_V8_OPEN_REVIEW")
    require(a["source_graph"]["successor_requirements"]["claude_evidence_only_v9"]["status"] == "UNRESOLVED_CONTRACT_CLOSURE_PRODUCER_AND_CLEAN_REVIEW", "CLAUDE_V9")
    require(a["source_graph"]["anchors"]["runner_v2_open_review"]["sha256"] == "c2669dec8fd1e32f616a6d97ce1e75f6de9a736d106814db1c99f8328215cff1" and a["source_graph"]["anchors"]["runner_v2_open_review"]["verdict"] == "OPEN", "RUNNER_V2_OPEN_REVIEW")
    require(a["source_graph"]["successor_requirements"]["runner_v3"]["status"] == "UNRESOLVED_CONTRACT_CLOSURE_PRODUCER_AND_CLEAN_REVIEW", "RUNNER_V3")
    require(a["source_graph"]["successor_requirements"]["execution_window_v2"]["status"] == "UNRESOLVED_V2_TEMPLATE_CLOSURE_AND_REVIEW", "EXECUTION_WINDOW_V2")
    seq = a["protocol"]["sequencing"]; closure = seq.index("4_final_closure_last_after_consumer_discovery_and_bytes_are_stable"); producer = seq.index("5_producer_verification_after_final_closure"); authority = seq.index("6_authority_last_fresh_independent_exact_subject_reviews_after_producer_bytes_are_stable"); require(closure < producer < authority and all(not x.startswith("3") for x in seq[closure+1:producer]), "SEQUENCING")
    verify_schemas(a["schemas"]); verify_source_graph(a["source_graph"])
    pins = unresolved(a)
    return a, pins
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--structure-only", action="store_true"); args = parser.parse_args(argv)
    try: _, pins = verify_structure()
    except (VerificationError, KeyError, TypeError, ValueError, OSError) as exc:
        print(json.dumps({"status":"FAIL_STRUCTURE_OR_CLOSURE_DRIFT","error":str(exc)},sort_keys=True,separators=(",",":"))); return 1
    result = {"status":"STRUCTURE_VALID_DESIGN_ONLY" if args.structure_only else "FAIL_UNRESOLVED_PINS","design_status":STATUS,"unresolved_pins":pins,"unresolved_count":len(pins),"effects":{"writes":0,"provider":0,"network":0,"bytedcli":0,"live":0}}
    print(json.dumps(result,sort_keys=True,separators=(",",":")))
    return 0 if args.structure_only else 2
if __name__ == "__main__": sys.exit(main())
