#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,re,sys
from pathlib import Path
from typing import Any,Mapping,Sequence
ROOT=Path(__file__).resolve().parents[3];PACKAGE=Path(__file__).resolve().parent
STATUS="DESIGN_ONLY_V2_PENDING_STABLE_SUCCESSOR_BYTES_AND_FRESH_INDEPENDENT_REVIEW"
FILES=["architecture-v2.json","protocol-v2.json","schemas-v2.json","source-graph-v2.json","namespace-manifest-v2.json","acceptance-v2.json","decision-v2.json","mentor-reviewable-design-v2-20261113.json"]
EXPECTED_PROVIDERS={'ARM-A': {'blind_provider_label': 'ARM-A', 'provider_schema': 'claude-evidence-v1', 'adapter_type': 'ClaudeAttemptAdapterV9', 'publication_driver': 'claude_publish_public', 'publication_driver_identity_sha256': '1ae0b76d43fcc2371042d78cefadcb89f972c14c7aac80f251b7a61ff9d5dd25', 'research_material_profile_sha256': '95fd61d9271ed5659d75fa036393724c11a9fe7e22f46ca226294c2fb9311468'}, 'ARM-B': {'blind_provider_label': 'ARM-B', 'provider_schema': 'stage-b-execution-v3', 'adapter_type': 'CodexAttemptAdapterV9', 'publication_driver': 'AtomicPublisher.publish', 'publication_driver_identity_sha256': '15c4baba5461bf501f08b713be9dddfeb881e31832e09bd66bc04e3b9099d3a6', 'research_material_profile_sha256': '99d77ac9cc71d9f2fed80c65b956d2c15af32e327e8a6abb9b47f52051c9a9c3'}}
EXPECTED_PROJECTIONS=[{'path': 'shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1/dq-attempt-envelope-v1.schema.json', 'json_pointer': '$', 'applies': 'checks_enabled_dq_checks_conditional'}, {'path': 'shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1/attempt-bundle-v1.schema.json', 'json_pointer': '$/properties/envelope', 'applies': 'checks_enabled_dq_checks_conditional'}]
EXPECTED_ADJ={'authority_compiler_v1': 'OPEN_PRESERVED_HISTORY', 'authority_compiler_v2': 'FUTURE_UNRESOLVED_UNSTABLE_SOURCE_AND_CLEAN_REVIEW', 'blind_map_v6': 'OPEN_FALSE_CLEAN_SCOPE_CAPABILITY_AND_EXTERNAL_AUTHORITY', 'blind_map_v7': 'CURRENT_PARTIAL_BYTES_UNSTABLE_PENDING_CLOSURE_PRODUCER_AND_CLEAN_REVIEW', 'claude_metadata_preflight_v1': 'OPEN_HELD_BINARY_CLEANUP_RESIDUE_AND_STALE_CLAUDE_V8_AUTHORITY', 'claude_metadata_preflight_v2': 'CURRENT_BYTES_UNSTABLE_PENDING_CLOSURE_PRODUCER_AND_CLEAN_REVIEW', 'claude_v9': 'CLEAN_CLAUDE_LIVE_BOUNDARY_V9_EVIDENCE_RESEAL_PENDING_P0_V10', 'codex_v6': 'CLEAN_CODEX_LIVE_BOUNDARY_V6_PENDING_P0_V10_CONSUMER_ONLY', 'execution_window_v1': 'OPEN_PRESERVED_HISTORY', 'execution_window_v2': 'OPEN_BOOLEAN_ORDINAL_RUNTIME_SCHEMA_MISMATCH', 'execution_window_v3': 'CURRENT_UNSTABLE_BYTES_PENDING_SOURCE_CLOSURE_PRODUCER_FINAL_GRANTS_AND_CLEAN_REVIEW', 'p0_v10_plan_v1': 'OPEN_PRESERVED_HISTORY', 'runner_v3': 'OPEN_PACKAGE_REACHABLE_KEY_AND_LIVENESS_AUTHORITY', 'runner_v4_bound_legacy_lineage': 'CLEAN_PROVIDER_FREE_2X2_RUNNER_V4_NOT_SUCCESSOR_TO_RUNNER_V3', 'runner_v4_current_successor': 'CURRENT_UNSTABLE_BYTES_PENDING_SOURCE_CLOSURE_PRODUCER_AND_CLEAN_REVIEW', 'tool_policy_v7': 'CLEAN_TOOL_POLICY_V7', 'metadata_preflight_v2': 'CURRENT_UNSTABLE_BYTES_PENDING_SOURCE_CLOSURE_PRODUCER_AND_CLEAN_REVIEW'}
class VerificationError(ValueError):pass
def require(v,code):
 if not v:raise VerificationError(code)
def load(p):return json.loads(p.read_text())
def sha(b):return hashlib.sha256(b).hexdigest()
def row(f):
 b=f.read_bytes();return {"path":f.relative_to(ROOT).as_posix(),"bytes":len(b),"sha256":sha(b)}
def under(rel):
 b=ROOT/rel
 if not b.is_dir():return []
 return [row(f) for f in sorted(x for x in b.rglob("*") if x.is_file() and "__pycache__" not in x.parts and x.suffix!=".pyc")]
def discover(specs):
 out=[]
 for s in specs:
  b=ROOT/s["root"];ps=[re.compile("^"+x+"$") for x in s["patterns"]]
  for d in sorted(x for x in b.iterdir() if x.is_dir() and any(p.fullmatch(x.name) for p in ps)):out+=under(d.relative_to(ROOT).as_posix())
 return sorted(out,key=lambda x:x["path"])
def agg(xs):return sha(b"".join(f"{x['path']}\0{x['bytes']}\0{x['sha256']}\n".encode() for x in sorted(xs,key=lambda y:y["path"])))
def artifacts():
 vals=[load(PACKAGE/x) for x in FILES];return dict(zip(("architecture","protocol","schemas","graph","manifest","acceptance","decision","mentor"),vals))
def statuses(a):
 require(a["architecture"]["status"]==STATUS,"STATUS_ENUM:architecture");require(a["decision"]["status"]==STATUS,"STATUS_ENUM:decision")
 for n in ("protocol","schemas","graph","manifest","acceptance","mentor"):require(a[n]["status"]==STATUS,"STATUS:"+n)
 for n in ("architecture","protocol","graph","acceptance","decision","mentor"):require(a[n]["adjudications"]==EXPECTED_ADJ,"ADJUDICATIONS:"+n)
def providers(a):
 require(a["schemas"]["exact_provider_bindings"]==EXPECTED_PROVIDERS,"PROVIDER_FIELDS:schemas");require(a["protocol"]["provider_contract"]==EXPECTED_PROVIDERS,"PROVIDER_FIELDS:protocol");require(a["graph"]["exact_provider_bindings"]==EXPECTED_PROVIDERS,"PROVIDER_FIELDS:graph")
def projections(a):
 for n,k in (("schemas","required_schema_projections"),("protocol","projection_contract"),("graph","required_schema_projections")):require(a[n][k]==EXPECTED_PROJECTIONS,"PROJECTIONS:"+n)
 require(len(EXPECTED_PROJECTIONS)==2 and EXPECTED_PROJECTIONS[1]["json_pointer"]=="$/properties/envelope","BUNDLE_PROJECTION")
def consumers(a):
 g=a["graph"];require(set(g["consumer_sets"])==set(g["consumer_set_roots"]),"CONSUMER_NAMES")
 for name,roots in g["consumer_set_roots"].items():require(g["consumer_sets"][name]==sorted([x for r in roots for x in under(r)],key=lambda x:x["path"]),"CONSUMER_SET_EQUALITY:"+name)
def namespace(a):
 m=a["manifest"];now=discover(m["watch_specs"]);require(now==m["snapshot"],"STALE_SUCCESSOR_NAMESPACE");require(len(now)==m["snapshot_count"] and agg(now)==m["snapshot_aggregate_sha256"],"NAMESPACE_AGGREGATE");require(a["graph"]["namespace_snapshot"]==now,"GRAPH_NAMESPACE")
def graph(a):
 g=a["graph"];xs=g["nodes"];require(len(xs)==g["node_count"] and len({x["path"] for x in xs})==len(xs),"GRAPH_SET");require(agg(xs)==g["node_aggregate_sha256"],"GRAPH_AGGREGATE")
 for x in xs:
  f=ROOT/x["path"];require(f.is_file() and not f.is_symlink(),"GRAPH_MEMBER_MISSING");require(row(f)=={k:x[k] for k in ("path","bytes","sha256")},"GRAPH_MEMBER_DRIFT")
 ew=g["review_anchors"]["execution_window_v1_open"];require((ew["bytes"],ew["sha256"],ew["adjudication"])==(11922,"d83e4bd8f87f89fa607089d3a264503c82305d503451993b1efa105eb309940a","OPEN"),"EXECUTION_WINDOW_V1_OPEN")
 require(g["review_anchors"]["execution_window_v2_open"]["sha256"]=="70ceed48c522f0f59641b9eec4b9564f47d27840cb669aae4d1ae4e7a8f3e89a" and g["review_anchors"]["execution_window_v2_open"]["findings"]==["EW-V2-OPEN-004-001"],"EXECUTION_WINDOW_V2_OPEN"); require(g["review_anchors"]["metadata_preflight_v1_open"]["sha256"]=="548ae003bf8a29f21b60753942b3414895c058daf68b9a656839d7b0fad319b5" and g["review_anchors"]["metadata_preflight_v1_open"]["verdict"]=="OPEN","METADATA_PREFLIGHT_V1_OPEN"); require(g["review_anchors"]["codex_v6_clean"]["sha256"]=="a612f581be86741f49be7ee2e511fdf9526b2ac6481da65a3e4bd069e602221b" and g["review_anchors"]["codex_v6_clean"]["verdict"]=="CLEAN_CODEX_LIVE_BOUNDARY_V6_PENDING_P0_V10","CODEX_V6_CLEAN"); require(g["review_anchors"]["blind_map_v6_open"]["sha256"]=="3a1d63397c2c5732ec1f4a5f9b92a620e5da93cb6ede31ec4826ceb8adeed084" and g["review_anchors"]["blind_map_v6_open"]["findings"]==["OPEN-V6-01","OPEN-V6-02","OPEN-V6-03","OPEN-V6-04"],"BLIND_MAP_V6_OPEN"); require(g["review_anchors"]["runner_v3_open"]["verdict"]=="OPEN","RUNNER_V3_OPEN");require(g["review_anchors"]["runner_v3_open"]["findings"]==["OPEN-RUNNER-V3-PACKAGE-REACHABLE-KEY-AUTHORITY-001","OPEN-RUNNER-V3-PACKAGE-REACHABLE-LIVENESS-AUTHORITY-002","OPEN-P0-V9-G3-SCHEMA-002"],"RUNNER_V3_FINDINGS");require(g["review_anchors"]["runner_v4_clean_bound_legacy"]["scope"]=="RUNNER_V1_V4_LEGACY_LINEAGE_NOT_RUNNER_V3_SUCCESSOR","RUNNER_V4_SCOPE")
def unresolved(a):
 x=a["acceptance"]["unresolved_pins"];require(x==a["decision"]["unresolved_pins"]==a["mentor"]["unresolved_pins"],"UNRESOLVED_LIST");g=a["graph"]["unresolved_pins"];require([y["pin"] for y in g]==x and all(y["path"] is None and y["bytes"] is None and y["sha256"] is None for y in g),"UNRESOLVED_GRAPH");return x
def verify_structure(a=None):
 a=artifacts() if a is None else a;statuses(a);providers(a);projections(a);consumers(a);namespace(a);graph(a);return a,unresolved(a)
def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument("--structure-only",action="store_true");z=ap.parse_args(argv)
 try:_,pins=verify_structure()
 except Exception as e:print(json.dumps({"status":"FAIL_STRUCTURE_OR_CLOSURE_DRIFT","error":str(e)},sort_keys=True,separators=(",",":")));return 1
 out={"status":"STRUCTURE_VALID_DESIGN_ONLY_NO_PROMOTION" if z.structure_only else "FAIL_UNRESOLVED_PINS","design_status":STATUS,"unresolved_count":len(pins),"unresolved_pins":pins,"effects":{"writes":0,"provider":0,"network":0,"bytedcli":0,"live":0}};print(json.dumps(out,sort_keys=True,separators=(",",":")));return 0 if z.structure_only else 2
if __name__=="__main__":sys.exit(main())
