"""Pure renderer/validator for two identical disabled bounded once schedules."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib,json,math
from types import MappingProxyType
from typing import Any,Mapping
class MaterializationError(ValueError):pass
def require(ok:bool,code:str)->None:
 if not ok:raise MaterializationError(code)
DESIGN_SHA256="fda54b15cb47753f03922a419d8098e2b81316cdc084657003b2d9a5dd3d0197";INTEGRATION_SHA="7ed93bfa249f77db21514c969137100e9468fcc9f166a7fb7d29f8474a5040c2";INTEGRATION_CLOSURE="3e7eb079ad924500f448517819845c30ed7a673c75d05288f6c46e6d166db893";BRIDGE_CLOSURE="743a329930ae2bd9c96ed8f2f2e63c3c41bda73bc7f4c9bf358a53b41de07293";ADAPTER_CLOSURE="fa2ccbfa531e5880defe4eb816c22be024b9e9187f7d267d803752da5a6208a8";MODEL="claude-fable-5-1";PROVIDER="claude_host";PROMPT_SHA="35a99586bd30c9ca70b0f5fb22dbf60e915f2dfcaf4d1be15fcfe9b9ea630c8e";CELLS=("F51DQ-6E3A9C17","F51DQ-B4D208FE");JOBS=("fable-adapter-cell-0","fable-adapter-cell-1");RESOURCE="fable-ab-serialized";EFFECTS={"provider":0,"service":0,"scheduler":0,"process":0,"network":0,"email":0,"publication":0,"tools":0,"web":0,"subagents":0};LIMITS={"attempts":1,"retries":0,"replays":0,"status_queries":0,"tools":0,"web":0,"subagents":0,"fallbacks":0}
PROMPT={"version":1,"ref":"pa1:sha256:"+PROMPT_SHA+":1","sha256":PROMPT_SHA,"length":1,"source_identity_sha256":"b"*64,"generation":"fable-adapter-fixture","provenance":"native_v1"}
@dataclass(frozen=True)
class Materialized:document:Mapping[str,Any];sha256:str
def _freeze(v:Any)->Any:
 if type(v) is dict:return MappingProxyType({k:_freeze(x) for k,x in v.items()})
 if type(v) is list:return tuple(_freeze(x) for x in v)
 return v
def _tree(v:Any,depth:int=0)->Any:
 require(depth<=64,"JSON_DEPTH")
 if v is None or type(v) in (bool,str,int):return v
 if type(v) is float:require(math.isfinite(v),"JSON_NONFINITE");return v
 if type(v) is list:
  for x in v:_tree(x,depth+1)
  return v
 if type(v) is dict:
  for k,x in v.items():require(type(k) is str,"JSON_KEY");_tree(x,depth+1)
  return v
 raise MaterializationError("JSON_TYPE")
def canonical_bytes(v:Any)->bytes:
 _tree(v)
 try:return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii")
 except (TypeError,ValueError,UnicodeError,RecursionError):raise MaterializationError("JSON_CANONICAL") from None
def strict_json_loads(text:str)->Any:
 require(type(text) is str,"JSON_TEXT")
 def pairs(items):
  out={}
  for k,v in items:require(type(k) is str and k not in out,"JSON_DUPLICATE_KEY");out[k]=v
  return out
 try:v=json.loads(text,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(MaterializationError("JSON_NONFINITE")))
 except (json.JSONDecodeError,UnicodeError,RecursionError):raise MaterializationError("JSON_TEXT") from None
 return _tree(v)
def exact(v:Any,keys:tuple[str,...],code:str)->Mapping[str,Any]:require(type(v) is dict and set(v)==set(keys),code);return v
def _utc(value:datetime,code:str)->datetime:
 require(type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None,code);require(value.utcoffset().total_seconds()==0 and value.microsecond==0,code);return value.astimezone(timezone.utc)
def _text(value:datetime)->str:return value.strftime("%Y-%m-%dT%H:%M:%SZ")
def _parse(text:Any,code:str)->datetime:
 require(type(text) is str and text.endswith("Z"),code)
 try:value=datetime.fromisoformat(text[:-1]+"+00:00")
 except ValueError:raise MaterializationError(code) from None
 require(_text(value)==text,code);return value
def _validate_design(design:Any)->None:
 require(type(design) is dict and hashlib.sha256(canonical_bytes(design)).hexdigest()==DESIGN_SHA256,"SOURCE_DESIGN_BINDING");require(design.get("activation") is False and design.get("countable") is False and design.get("integration_closure_sha256")==INTEGRATION_CLOSURE,"SOURCE_DESIGN_STATE")
ROOT_KEYS=("version","kind","activation","countable","design_sha256","integration_sha256","integration_closure_sha256","bridge_closure_sha256","adapter_closure_sha256","logical_database_id","model","provider","evaluation_time","not_before","scheduled_at","deadline","window_seconds","execution","prompt_artifact","jobs","installed_jobs","installed_schedules","effects")
def validate_materialized(v:Any)->Mapping[str,Any]:
 v=exact(v,ROOT_KEYS,"MATERIALIZED_SHAPE");require(type(v["version"]) is int and v["version"]==1 and v["kind"]=="R6_FABLE_PROVIDER_FREE_ALLOCATION_MATERIALIZATION","MATERIALIZED_VERSION");require(v["activation"] is False and v["countable"] is False,"MATERIALIZED_INACTIVE");require((v["design_sha256"],v["integration_sha256"],v["integration_closure_sha256"],v["bridge_closure_sha256"],v["adapter_closure_sha256"])==(DESIGN_SHA256,INTEGRATION_SHA,INTEGRATION_CLOSURE,BRIDGE_CLOSURE,ADAPTER_CLOSURE),"MATERIALIZED_BINDINGS");require(v["logical_database_id"]=="closed-engine/fable-ab/schedule.sqlite" and v["model"]==MODEL and v["provider"]==PROVIDER,"MATERIALIZED_IDENTITY")
 evaluation=_parse(v["evaluation_time"],"EVALUATION_TIME");not_before=_parse(v["not_before"],"NOT_BEFORE");scheduled=_parse(v["scheduled_at"],"SCHEDULED_AT");deadline=_parse(v["deadline"],"DEADLINE");require(evaluation<scheduled and evaluation<=not_before<=scheduled<=deadline,"TIME_ORDER");window=(deadline-not_before).total_seconds();require(0<=window<=300 and type(v["window_seconds"]) is int and v["window_seconds"]==int(window),"TIME_WINDOW")
 execution=exact(v["execution"],("max_workers","resource_serialization","resource_key"),"EXECUTION_SHAPE");require(execution=={"max_workers":1,"resource_serialization":True,"resource_key":RESOURCE} and type(execution["max_workers"]) is int,"EXECUTION_BINDING");require(v["prompt_artifact"]==PROMPT,"PROMPT_BINDING");require(type(v["jobs"]) is list and len(v["jobs"])==2,"JOB_COUNT");normalized=[]
 for i,job in enumerate(v["jobs"]):
  job=exact(job,("job_id","cell_id","enabled","replay_safe","dq_enabled","model","provider","prompt_artifact","limits","resource_key","schedule"),"JOB_SHAPE");require(job["job_id"]==JOBS[i] and job["cell_id"]==CELLS[i] and job["enabled"] is False and job["replay_safe"] is False and job["dq_enabled"] is bool(i),"JOB_ORDER");require(job["model"]==MODEL and job["provider"]==PROVIDER and job["prompt_artifact"]==PROMPT and job["resource_key"]==RESOURCE,"JOB_BINDING");require(job["limits"]==LIMITS and all(type(x) is int for x in job["limits"].values()),"JOB_LIMITS");schedule=exact(job["schedule"],("kind","at","grace_seconds"),"JOB_SCHEDULE_SHAPE");require(schedule["kind"]=="once" and schedule["at"]==v["scheduled_at"] and type(schedule["grace_seconds"]) is int and 1<=schedule["grace_seconds"]<=300 and scheduled.timestamp()+schedule["grace_seconds"]<=deadline.timestamp(),"JOB_SCHEDULE");normalized.append({k:job[k] for k in job if k not in ("job_id","cell_id","dq_enabled")})
 require(normalized[0]==normalized[1],"JOB_ASYMMETRY");require(v["installed_jobs"]==[] and v["installed_schedules"]==[],"MATERIALIZED_NOT_INSTALLED");require(v["effects"]==EFFECTS and all(type(x) is int for x in v["effects"].values()),"MATERIALIZED_EFFECTS");return v
def render_materialization(design:Mapping[str,Any],evaluation_time:datetime,not_before:datetime,deadline:datetime,scheduled_at:datetime,*,grace_seconds:int)->Materialized:
 source=dict(design);_validate_design(source);evaluation=_utc(evaluation_time,"EVALUATION_TIME");lower=_utc(not_before,"NOT_BEFORE");upper=_utc(deadline,"DEADLINE");at=_utc(scheduled_at,"SCHEDULED_AT");require(type(grace_seconds) is int and 1<=grace_seconds<=300,"GRACE_SECONDS");window=(upper-lower).total_seconds();require(evaluation<at and evaluation<=lower<=at<=upper and 0<=window<=300 and at.timestamp()+grace_seconds<=upper.timestamp(),"TIME_BOUNDS");schedule={"kind":"once","at":_text(at),"grace_seconds":grace_seconds};jobs=[]
 for i in range(2):jobs.append({"job_id":JOBS[i],"cell_id":CELLS[i],"enabled":False,"replay_safe":False,"dq_enabled":bool(i),"model":MODEL,"provider":PROVIDER,"prompt_artifact":dict(PROMPT),"limits":dict(LIMITS),"resource_key":RESOURCE,"schedule":dict(schedule)})
 document={"version":1,"kind":"R6_FABLE_PROVIDER_FREE_ALLOCATION_MATERIALIZATION","activation":False,"countable":False,"design_sha256":DESIGN_SHA256,"integration_sha256":INTEGRATION_SHA,"integration_closure_sha256":INTEGRATION_CLOSURE,"bridge_closure_sha256":BRIDGE_CLOSURE,"adapter_closure_sha256":ADAPTER_CLOSURE,"logical_database_id":"closed-engine/fable-ab/schedule.sqlite","model":MODEL,"provider":PROVIDER,"evaluation_time":_text(evaluation),"not_before":_text(lower),"scheduled_at":_text(at),"deadline":_text(upper),"window_seconds":int(window),"execution":{"max_workers":1,"resource_serialization":True,"resource_key":RESOURCE},"prompt_artifact":dict(PROMPT),"jobs":jobs,"installed_jobs":[],"installed_schedules":[],"effects":dict(EFFECTS)};validate_materialized(document);return Materialized(_freeze(document),hashlib.sha256(canonical_bytes(document)).hexdigest())
def default_materialization()->Mapping[str,Any]:return MappingProxyType({"status":"DENIED_PURE_INACTIVE_MATERIALIZATION","activation":False,"countable":False,"effects":MappingProxyType(dict(EFFECTS))})
__all__=["MaterializationError","Materialized","canonical_bytes","default_materialization","render_materialization","strict_json_loads","validate_materialized"]
