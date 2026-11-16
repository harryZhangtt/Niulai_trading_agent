"""Strict pure-JSON validator for the inactive Fable allocation design."""
from __future__ import annotations
import hashlib,json,math
from types import MappingProxyType
from typing import Any,Mapping
class DesignError(ValueError):pass
def require(ok:bool,code:str)->None:
 if not ok:raise DesignError(code)
DESIGN_SHA256="fda54b15cb47753f03922a419d8098e2b81316cdc084657003b2d9a5dd3d0197";MODEL="claude-fable-5-1";PROVIDER="claude_host";PROMPT_SHA="35a99586bd30c9ca70b0f5fb22dbf60e915f2dfcaf4d1be15fcfe9b9ea630c8e";INTEGRATION_CLOSURE="3e7eb079ad924500f448517819845c30ed7a673c75d05288f6c46e6d166db893";INTEGRATION_SHA="7ed93bfa249f77db21514c969137100e9468fcc9f166a7fb7d29f8474a5040c2";BRIDGE_CLOSURE="743a329930ae2bd9c96ed8f2f2e63c3c41bda73bc7f4c9bf358a53b41de07293";ADAPTER_CLOSURE="fa2ccbfa531e5880defe4eb816c22be024b9e9187f7d267d803752da5a6208a8";CELLS=("F51DQ-6E3A9C17","F51DQ-B4D208FE");JOBS=("fable-adapter-cell-0","fable-adapter-cell-1");RESOURCE="fable-ab-serialized";INTENT="fable-ab-bounded-intent"
def _tree(v:Any,depth:int=0)->Any:
 require(depth<=64,"JSON_DEPTH")
 if v is None or type(v) in (bool,str,int):return v
 if type(v) is float:require(math.isfinite(v),"JSON_NONFINITE");return v
 if type(v) is list:
  for x in v:_tree(x,depth+1)
  return v
 if type(v) is dict:
  for k,x in v.items():require(type(k) is str,"JSON_KEY_TYPE");_tree(x,depth+1)
  return v
 raise DesignError("JSON_TYPE")
def canonical_bytes(v:Any)->bytes:
 _tree(v)
 try:return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii")
 except (TypeError,ValueError,UnicodeError,RecursionError):raise DesignError("JSON_CANONICAL") from None
def strict_json_loads(text:str)->Any:
 require(type(text) is str,"JSON_TEXT")
 def pairs(items):
  out={}
  for k,v in items:require(type(k) is str and k not in out,"JSON_DUPLICATE_KEY");out[k]=v
  return out
 try:v=json.loads(text,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(DesignError("JSON_NONFINITE")))
 except (json.JSONDecodeError,UnicodeError,RecursionError):raise DesignError("JSON_TEXT") from None
 return _tree(v)
def exact(v:Any,keys:tuple[str,...],code:str)->Mapping[str,Any]:require(type(v) is dict and set(v)==set(keys),code);return v
ROOT_KEYS=("version","kind","activation","countable","model","provider","integration_sha256","integration_closure_sha256","bridge_closure_sha256","adapter_closure_sha256","logical_database_id","prompt_artifact","jobs","execution","schedule_intent","installed_jobs","installed_schedules","output_custody","prerequisite","effects")
LIMITS={"attempts":1,"retries":0,"replays":0,"status_queries":0,"tools":0,"web":0,"subagents":0,"fallbacks":0};EFFECTS={"provider":0,"service":0,"scheduler":0,"process":0,"network":0,"email":0,"publication":0,"tools":0,"web":0,"subagents":0}
def validate_design(v:Any)->Mapping[str,Any]:
 v=exact(v,ROOT_KEYS,"DESIGN_SHAPE");require(type(v["version"]) is int and v["version"]==1 and v["kind"]=="R6_FABLE_PROVIDER_FREE_ALLOCATION_DESIGN","DESIGN_VERSION");require(v["activation"] is False and v["countable"] is False,"DESIGN_INACTIVE");require(v["model"]==MODEL and v["provider"]==PROVIDER,"DESIGN_MODEL_PROVIDER");require((v["integration_sha256"],v["integration_closure_sha256"],v["bridge_closure_sha256"],v["adapter_closure_sha256"])==(INTEGRATION_SHA,INTEGRATION_CLOSURE,BRIDGE_CLOSURE,ADAPTER_CLOSURE),"DESIGN_BINDINGS");require(v["logical_database_id"]=="closed-engine/fable-ab/schedule.sqlite","DESIGN_DATABASE")
 p=exact(v["prompt_artifact"],("version","ref","sha256","length","source_identity_sha256","generation","provenance"),"PROMPT_SHAPE");require(p=={"version":1,"ref":"pa1:sha256:"+PROMPT_SHA+":1","sha256":PROMPT_SHA,"length":1,"source_identity_sha256":"b"*64,"generation":"fable-adapter-fixture","provenance":"native_v1"},"PROMPT_BINDING")
 require(type(v["jobs"]) is list and len(v["jobs"])==2,"JOB_COUNT")
 normalized=[]
 for i,job in enumerate(v["jobs"]):
  job=exact(job,("job_id","cell_id","enabled","dq_enabled","model","provider","prompt_artifact_sha256","limits","resource_key","schedule_intent_id"),"JOB_SHAPE");require(job["job_id"]==JOBS[i] and job["cell_id"]==CELLS[i] and job["enabled"] is False and type(job["dq_enabled"]) is bool and job["dq_enabled"] is bool(i),"JOB_ORDER_TREATMENT");require(job["model"]==MODEL and job["provider"]==PROVIDER and job["prompt_artifact_sha256"]==PROMPT_SHA,"JOB_BINDING");require(type(job["limits"]) is dict and job["limits"]==LIMITS and all(type(x) is int for x in job["limits"].values()),"JOB_LIMITS");require(job["resource_key"]==RESOURCE and job["schedule_intent_id"]==INTENT,"JOB_SERIALIZATION");normalized.append({k:job[k] for k in job if k not in ("job_id","cell_id","dq_enabled")})
 require(normalized[0]==normalized[1],"JOB_ASYMMETRY")
 execution=exact(v["execution"],("max_workers","resource_serialization","resource_key"),"EXECUTION_SHAPE");require(type(execution["max_workers"]) is int and execution=={"max_workers":1,"resource_serialization":True,"resource_key":RESOURCE},"EXECUTION_BINDING")
 schedule=exact(v["schedule_intent"],("schedule_intent_id","kind","installed","not_before","deadline","window_seconds"),"SCHEDULE_SHAPE");require(schedule=={"schedule_intent_id":INTENT,"kind":"BOUNDED_FUTURE_ONCE_INTENT","installed":False,"not_before":"UNSET_EXTERNAL","deadline":"UNSET_EXTERNAL","window_seconds":300} and type(schedule["window_seconds"]) is int,"SCHEDULE_BINDING");require(v["installed_jobs"]==[] and v["installed_schedules"]==[],"DESIGN_NOT_INSTALLED")
 custody=exact(v["output_custody"],("owner_private_parent_required","fresh_root_required","no_replace","pre_return_descriptor_barrier","raw_bundle_exact_binding","cleanup_uncertainty"),"CUSTODY_SHAPE");require(custody=={"owner_private_parent_required":True,"fresh_root_required":True,"no_replace":True,"pre_return_descriptor_barrier":True,"raw_bundle_exact_binding":True,"cleanup_uncertainty":"IDENTITY_UNAVAILABLE_NEVER_DELETE_BY_NAME"},"CUSTODY_BINDING")
 prerequisite=exact(v["prerequisite"],("engine_closed","active_service_false","source_expectation_exact","sidecars_absent"),"PREREQUISITE_SHAPE");require(set(prerequisite.values())=={"EXTERNALLY_ESTABLISHED_REQUIRED"},"PREREQUISITE_BINDING");require(v["effects"]==EFFECTS and all(type(x) is int for x in v["effects"].values()),"DESIGN_EFFECTS");require(hashlib.sha256(canonical_bytes(v)).hexdigest()==DESIGN_SHA256,"DESIGN_DIGEST");return v
def default_design()->Mapping[str,Any]:return MappingProxyType({"status":"DENIED_INACTIVE_DESIGN_ONLY","activation":False,"countable":False,"effects":MappingProxyType(dict(EFFECTS))})
__all__=["DESIGN_SHA256","DesignError","canonical_bytes","default_design","strict_json_loads","validate_design"]
