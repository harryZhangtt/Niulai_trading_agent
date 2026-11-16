"""Pure proposal-DATA to isolated config-v2/injection DATA translation."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib,json,math
from types import MappingProxyType
from typing import Any,Mapping
class TranslationError(ValueError):pass
def require(ok:bool,code:str)->None:
 if not ok:raise TranslationError(code)
PROPOSAL_SHA="6b28e29027942d6380ee467d8b70ab5092abdc1323bb7d762a2cd2e81f239955";PROPOSAL_CLOSURE="685fa492626a2666d286b48bb96a2306133d5b84840125ef0da77251fe4b8361";MATERIALIZATION_CLOSURE="ed3f7dbc7e481cba2c110626b4f1bd04102b0f3f5b882ed5fade0df085c78a49";MODEL="claude-fable-5-1";PROFILE="fable-ab-disabled";PROMPT_SHA="35a99586bd30c9ca70b0f5fb22dbf60e915f2dfcaf4d1be15fcfe9b9ea630c8e";PROMPT_FILE=".job-runtime/config/prompts/fable-ab.txt";AUTH_HOME=".job-runtime/config/fable-auth-home";ALLOCATION_FILE=".job-runtime/config/fable-allocation-v2.json";JOBS=("fable-adapter-cell-0","fable-adapter-cell-1");CELLS=("F51DQ-6E3A9C17","F51DQ-B4D208FE");RESOURCE="fable-ab-serialized";EFFECTS={"provider":0,"service":0,"scheduler":0,"process":0,"network":0,"email":0,"publication":0,"filesystem_write":0}
@dataclass(frozen=True)
class ConfigTranslation:config:Mapping[str,Any];allocation:Mapping[str,Any];injection:Mapping[str,Any];budget:Mapping[str,Any];sha256:str
def _freeze(v):
 if type(v) is dict:return MappingProxyType({k:_freeze(x) for k,x in v.items()})
 if type(v) is list:return tuple(_freeze(x) for x in v)
 return v
def _tree(v,d=0):
 require(d<=64,"JSON_DEPTH")
 if v is None or type(v) in (bool,str,int):return v
 if type(v) is float:require(math.isfinite(v),"JSON_NONFINITE");return v
 if type(v) is list:
  for x in v:_tree(x,d+1)
  return v
 if type(v) is dict:
  for k,x in v.items():require(type(k) is str,"JSON_KEY");_tree(x,d+1)
  return v
 raise TranslationError("JSON_TYPE")
def canonical_bytes(v):_tree(v);return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii")
def strict_json_loads(text):
 require(type(text) is str,"JSON_TEXT")
 def pairs(items):
  out={}
  for k,v in items:require(type(k) is str and k not in out,"JSON_DUPLICATE_KEY");out[k]=v
  return out
 try:v=json.loads(text,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(TranslationError("JSON_NONFINITE")))
 except (json.JSONDecodeError,UnicodeError,RecursionError):raise TranslationError("JSON_TEXT") from None
 return _tree(v)
def _utc(v):require(type(v) is datetime and v.tzinfo is not None and v.utcoffset() is not None and v.utcoffset().total_seconds()==0 and v.microsecond==0,"EVALUATION_TIME");return v.astimezone(timezone.utc)
def _text(v):return v.strftime('%Y-%m-%dT%H:%M:%SZ')
def _parse(v,code):
 require(type(v) is str and v.endswith('Z'),code)
 try:d=datetime.fromisoformat(v[:-1]+'+00:00')
 except ValueError:raise TranslationError(code) from None
 require(d.microsecond==0 and _text(d)==v,code);return d
def _custody(v):
 require(type(v) is dict and set(v)=={"logical_path","sha256","bytes","mode","owner_uid","owner_verified","no_symlink","source_generation"},"CUSTODY_SHAPE");require(v["logical_path"]=="custody/fable/prompt.txt" and v["sha256"]==PROMPT_SHA and v["bytes"]==1 and type(v["bytes"]) is int and v["mode"]=="0600" and type(v["owner_uid"]) is int and type(v["owner_uid"]) is not bool and v["owner_uid"]>=0 and v["owner_verified"] is True and v["no_symlink"] is True and v["source_generation"]=="fable-adapter-fixture","CUSTODY_BINDING");return v
def validate_translation(config,allocation,injection,budget):
 require(type(config) is dict and set(config)=={"schema_version","tick_seconds","heartbeat_seconds","stale_seconds","max_workers","retry","model_profiles","allocation_files","source_paths"},"CONFIG_SHAPE");require(type(config["schema_version"]) is int and config["schema_version"]==2 and type(config["max_workers"]) is int and config["max_workers"]==1 and all(type(config[k]) is int for k in ("tick_seconds","heartbeat_seconds","stale_seconds")) and config["allocation_files"]==[ALLOCATION_FILE] and config["source_paths"]==[],"CONFIG_ROOT");profile=config["model_profiles"].get(PROFILE);require(profile=={"provider":"claude_host","model":MODEL,"effort":"low","timeout_seconds":300,"auth_home":AUTH_HOME,"max_budget_usd":0.02,"circuit":{"failure_threshold":1,"open_seconds":60,"probe_seconds":10}},"CONFIG_PROFILE");require(config["retry"]=={"version":2,"max_attempts":1,"base_delay_seconds":1,"max_delay_seconds":1,"deadline_seconds":240} and all(type(x) is int for x in config["retry"].values()),"CONFIG_RETRY");require(type(allocation) is dict and allocation.get("schema_version")==2 and type(allocation.get("jobs")) is list and len(allocation["jobs"])==2,"ALLOCATION_SHAPE");require(type(injection) is dict and injection.get("schema_version")==1 and type(injection.get("jobs")) is list and len(injection["jobs"])==2,"INJECTION_SHAPE")
 for i,job in enumerate(allocation["jobs"]):
  require(set(job)=={"id","enabled","schedule","model_profile","prompt_file","replay_contract"} and job["id"]==JOBS[i] and job["enabled"] is False and job["model_profile"]==PROFILE and job["prompt_file"]==PROMPT_FILE,"ALLOCATION_JOB");require(job["schedule"].get("kind")=="once" and job["replay_contract"]=={"version":1,"effect":"none","automatic_phases":["not_started"],"slot_operation_scope":"fable/"+CELLS[i],"reconciliation_adapter":None},"ALLOCATION_SEMANTICS")
  inject=injection["jobs"][i];require(inject=={"id":JOBS[i],"cell_id":CELLS[i],"_provider":"claude_host","_replay_contract":job["replay_contract"],"_retry_policy":config["retry"],"_prompt_artifact":{"version":1,"ref":"pa1:sha256:"+PROMPT_SHA+":1","sha256":PROMPT_SHA,"length":1,"source_identity_sha256":"b"*64,"generation":"fable-adapter-fixture","provenance":"native_v1"},"_resource_key":RESOURCE,"_circuit_scope":{"profile":PROFILE,"resource_hash":hashlib.sha256(("claude_host|"+AUTH_HOME).encode()).hexdigest(),"failure_threshold":1,"open_seconds":60,"probe_seconds":10}},"INJECTION_JOB")
 require(budget=={"currency":"USD","two_arm_cap_usd":0.02,"per_arm_cap_usd":0.01,"prompt_token_evidence":{"status":"PLACEHOLDER_UNVERIFIED","input_tokens":None,"output_tokens":None},"budget_approved":False,"billed_authority":False},"BUDGET_FENCE");return True
def render_translation(proposal,proposal_sha256,current_evaluation_time,prompt_custody):
 source=dict(proposal);require(proposal_sha256==PROPOSAL_SHA and hashlib.sha256(canonical_bytes(source)).hexdigest()==PROPOSAL_SHA,"PROPOSAL_BINDING");require(source.get("classification")=="DATA_ONLY_NOT_CONFIG_V2_NOT_ENGINE_INSTALLABLE" and source.get("activation") is False and source.get("apply") is False,"PROPOSAL_STATE");current=_utc(current_evaluation_time);require(_parse(source["proposal_evaluation_time"],"PROPOSAL_TIME")<=current<_parse(source["materialized_lineage"]["scheduled_at"],"SCHEDULED"),"PROPOSAL_STALE");custody=dict(_custody(dict(prompt_custody)));config={"schema_version":2,"tick_seconds":5,"heartbeat_seconds":10,"stale_seconds":60,"max_workers":1,"retry":{"version":2,"max_attempts":1,"base_delay_seconds":1,"max_delay_seconds":1,"deadline_seconds":240},"model_profiles":{PROFILE:{"provider":"claude_host","model":MODEL,"effort":"low","timeout_seconds":300,"auth_home":AUTH_HOME,"max_budget_usd":0.02,"circuit":{"failure_threshold":1,"open_seconds":60,"probe_seconds":10}}},"allocation_files":[ALLOCATION_FILE],"source_paths":[]};allocation={"schema_version":2,"jobs":[]};injection={"schema_version":1,"proposal_sha256":PROPOSAL_SHA,"proposal_closure_sha256":PROPOSAL_CLOSURE,"materialization_closure_sha256":MATERIALIZATION_CLOSURE,"prompt_custody":custody,"jobs":[]}
 for i,job in enumerate(source["jobs"]):
  schedule=dict(job["schedule"]);allocation_job={"id":JOBS[i],"enabled":False,"schedule":schedule,"model_profile":PROFILE,"prompt_file":PROMPT_FILE,"replay_contract":{"version":1,"effect":"none","automatic_phases":["not_started"],"slot_operation_scope":"fable/"+CELLS[i],"reconciliation_adapter":None}};allocation["jobs"].append(allocation_job);injection["jobs"].append({"id":JOBS[i],"cell_id":CELLS[i],"_provider":"claude_host","_replay_contract":allocation_job["replay_contract"],"_retry_policy":config["retry"],"_prompt_artifact":{"version":1,"ref":"pa1:sha256:"+PROMPT_SHA+":1","sha256":PROMPT_SHA,"length":1,"source_identity_sha256":"b"*64,"generation":"fable-adapter-fixture","provenance":"native_v1"},"_resource_key":RESOURCE,"_circuit_scope":{"profile":PROFILE,"resource_hash":hashlib.sha256(("claude_host|"+AUTH_HOME).encode()).hexdigest(),"failure_threshold":1,"open_seconds":60,"probe_seconds":10}})
 budget={"currency":"USD","two_arm_cap_usd":0.02,"per_arm_cap_usd":0.01,"prompt_token_evidence":{"status":"PLACEHOLDER_UNVERIFIED","input_tokens":None,"output_tokens":None},"budget_approved":False,"billed_authority":False};validate_translation(config,allocation,injection,budget);artifact={"activation":False,"apply":False,"installed_jobs":[],"installed_schedules":[],"effects":dict(EFFECTS),"config":config,"allocation":allocation,"injection":injection,"budget":budget};return ConfigTranslation(_freeze(config),_freeze(allocation),_freeze(injection),_freeze(budget),hashlib.sha256(canonical_bytes(artifact)).hexdigest())
def default_translation():return MappingProxyType({"status":"DENIED_PURE_CONFIG_CANDIDATE","activation":False,"apply":False,"budget_approved":False,"effects":MappingProxyType(dict(EFFECTS))})
__all__=["ConfigTranslation","TranslationError","default_translation","render_translation","strict_json_loads","validate_translation"]
