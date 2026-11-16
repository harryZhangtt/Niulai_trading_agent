"""Pure translation from CLEAN materialization to disabled Engine-facing data."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib,json,math
from types import MappingProxyType
from typing import Any,Mapping
class ProposalError(ValueError):pass
def require(ok:bool,code:str)->None:
 if not ok:raise ProposalError(code)
MATERIALIZED_SHA="04d67dccd6c6c5bf4403739f60b290a79f67bd9ce3212592cc38d94bcb5afc33";MATERIALIZATION_CLOSURE="ed3f7dbc7e481cba2c110626b4f1bd04102b0f3f5b882ed5fade0df085c78a49";DESIGN_SHA="fda54b15cb47753f03922a419d8098e2b81316cdc084657003b2d9a5dd3d0197";INTEGRATION_SHA="7ed93bfa249f77db21514c969137100e9468fcc9f166a7fb7d29f8474a5040c2";INTEGRATION_CLOSURE="3e7eb079ad924500f448517819845c30ed7a673c75d05288f6c46e6d166db893";BRIDGE_CLOSURE="743a329930ae2bd9c96ed8f2f2e63c3c41bda73bc7f4c9bf358a53b41de07293";ADAPTER_CLOSURE="fa2ccbfa531e5880defe4eb816c22be024b9e9187f7d267d803752da5a6208a8";PROMPT_SHA="35a99586bd30c9ca70b0f5fb22dbf60e915f2dfcaf4d1be15fcfe9b9ea630c8e";MODEL="claude-fable-5-1";PROVIDER="claude_host";PROFILE="fable-provider-free-proposal";SCHEMA="r6-data-quality-fable-installation-proposal-data-v1";JOBS=("fable-adapter-cell-0","fable-adapter-cell-1");CELLS=("F51DQ-6E3A9C17","F51DQ-B4D208FE");RESOURCE="fable-ab-serialized";EFFECTS={"provider":0,"service":0,"scheduler":0,"process":0,"network":0,"email":0,"publication":0,"filesystem_write":0};LIMITS={"max_attempts":1,"retries":0,"replays":0,"status_queries":0,"tools":0,"web":0,"subagents":0,"fallbacks":0};PROMPT={"version":1,"ref":"pa1:sha256:"+PROMPT_SHA+":1","sha256":PROMPT_SHA,"length":1,"source_identity_sha256":"b"*64,"generation":"fable-adapter-fixture","provenance":"native_v1"}
@dataclass(frozen=True)
class Proposal:document:Mapping[str,Any];schema:str;sha256:str
def _freeze(v:Any)->Any:
 if type(v) is dict:return MappingProxyType({k:_freeze(x) for k,x in v.items()})
 if type(v) is list:return tuple(_freeze(x) for x in v)
 return v
def _tree(v:Any,d:int=0)->Any:
 require(d<=64,"JSON_DEPTH")
 if v is None or type(v) in (bool,str,int):return v
 if type(v) is float:require(math.isfinite(v),"JSON_NONFINITE");return v
 if type(v) is list:
  for x in v:_tree(x,d+1)
  return v
 if type(v) is dict:
  for k,x in v.items():require(type(k) is str,"JSON_KEY");_tree(x,d+1)
  return v
 raise ProposalError("JSON_TYPE")
def canonical_bytes(v:Any)->bytes:
 _tree(v)
 try:return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii")
 except (TypeError,ValueError,UnicodeError,RecursionError):raise ProposalError("JSON_CANONICAL") from None
def strict_json_loads(text:str)->Any:
 require(type(text) is str,"JSON_TEXT")
 def pairs(items):
  out={}
  for k,v in items:require(type(k) is str and k not in out,"JSON_DUPLICATE_KEY");out[k]=v
  return out
 try:v=json.loads(text,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ProposalError("JSON_NONFINITE")))
 except (json.JSONDecodeError,UnicodeError,RecursionError):raise ProposalError("JSON_TEXT") from None
 return _tree(v)
def exact(v:Any,keys:tuple[str,...],code:str)->Mapping[str,Any]:require(type(v) is dict and set(v)==set(keys),code);return v
def _utc(v:datetime)->datetime:require(type(v) is datetime and v.tzinfo is not None and v.utcoffset() is not None and v.utcoffset().total_seconds()==0 and v.microsecond==0,"CURRENT_TIME");return v.astimezone(timezone.utc)
def _parse(text:Any,code:str)->datetime:
 require(type(text) is str and text.endswith('Z'),code)
 try:v=datetime.fromisoformat(text[:-1]+'+00:00')
 except ValueError:raise ProposalError(code) from None
 require(v.microsecond==0 and v.strftime('%Y-%m-%dT%H:%M:%SZ')==text,code);return v
def _text(v:datetime)->str:return v.strftime('%Y-%m-%dT%H:%M:%SZ')
def _custody(v:Any)->Mapping[str,Any]:
 v=exact(v,("logical_path","sha256","bytes","mode","owner_uid","owner_verified","no_symlink","source_generation"),"CUSTODY_SHAPE");require(v["logical_path"]=="custody/fable/prompt.txt" and v["sha256"]==PROMPT_SHA and type(v["bytes"]) is int and v["bytes"]==1 and v["mode"]=="0600","CUSTODY_BINDING");require(type(v["owner_uid"]) is int and type(v["owner_uid"]) is not bool and v["owner_uid"]>=0 and v["owner_verified"] is True and v["no_symlink"] is True and v["source_generation"]=="fable-adapter-fixture","CUSTODY_VERIFICATION");return v
ROOT_KEYS=("version","schema","classification","kind","activation","apply","countable","proposal_evaluation_time","approved_horizon_seconds","materialized_sha256","materialization_closure_sha256","design_sha256","integration_sha256","integration_closure_sha256","bridge_closure_sha256","adapter_closure_sha256","logical_database_id","materialized_lineage","output_custody_contract","execution","jobs","installed_jobs","installed_schedules","effects")
def validate_proposal(v:Any)->Mapping[str,Any]:
 v=exact(v,ROOT_KEYS,"PROPOSAL_SHAPE");require(type(v["version"]) is int and v["version"]==1 and v["schema"]==SCHEMA and v["classification"]=="DATA_ONLY_NOT_CONFIG_V2_NOT_ENGINE_INSTALLABLE" and v["kind"]=="R6_FABLE_PROVIDER_FREE_INSTALLATION_PROPOSAL_DATA","PROPOSAL_VERSION");require(v["activation"] is False and v["apply"] is False and v["countable"] is False,"PROPOSAL_INACTIVE");require((v["materialized_sha256"],v["materialization_closure_sha256"],v["design_sha256"],v["integration_sha256"],v["integration_closure_sha256"],v["bridge_closure_sha256"],v["adapter_closure_sha256"])==(MATERIALIZED_SHA,MATERIALIZATION_CLOSURE,DESIGN_SHA,INTEGRATION_SHA,INTEGRATION_CLOSURE,BRIDGE_CLOSURE,ADAPTER_CLOSURE),"PROPOSAL_BINDINGS");require(v["logical_database_id"]=="closed-engine/fable-ab/schedule.sqlite","PROPOSAL_DATABASE");current=_parse(v["proposal_evaluation_time"],"PROPOSAL_TIME");require(type(v["approved_horizon_seconds"]) is int and v["approved_horizon_seconds"]==300,"PROPOSAL_HORIZON");lineage=exact(v["materialized_lineage"],("evaluation_time","not_before","scheduled_at","deadline","grace_seconds"),"LINEAGE_SHAPE");require(lineage=={"evaluation_time":"2026-11-12T12:00:00Z","not_before":"2026-11-12T12:01:00Z","scheduled_at":"2026-11-12T12:02:00Z","deadline":"2026-11-12T12:06:00Z","grace_seconds":240},"LINEAGE_EXACT");materialized_evaluation=_parse(lineage["evaluation_time"],"LINEAGE_EVALUATION");not_before=_parse(lineage["not_before"],"LINEAGE_NOT_BEFORE");lineage_at=_parse(lineage["scheduled_at"],"LINEAGE_AT");lineage_deadline=_parse(lineage["deadline"],"LINEAGE_DEADLINE");require(type(lineage["grace_seconds"]) is int and materialized_evaluation<=current<lineage_at and not_before<=lineage_at<=lineage_deadline and lineage_at.timestamp()+lineage["grace_seconds"]<=lineage_deadline.timestamp(),"LINEAGE_BOUNDS");require(v["output_custody_contract"]=="FRESH_OWNER_PRIVATE_DESCRIPTOR_BARRIER_NO_REPLACE","PROPOSAL_CUSTODY");require(v["execution"]=={"max_workers":1,"resource_serialization":True,"resource_key":RESOURCE},"PROPOSAL_EXECUTION");require(type(v["jobs"]) is list and len(v["jobs"])==2,"JOB_COUNT");normalized=[];scheduled_values=[]
 for i,job in enumerate(v["jobs"]):
  job=exact(job,("id","cell_id","enabled","schedule","provider","provider_profile","model","replay_safe","execution_limits","prompt_artifact","prompt_custody","resource_key"),"JOB_SHAPE");require(job["id"]==JOBS[i] and job["cell_id"]==CELLS[i] and job["enabled"] is False and job["replay_safe"] is False,"JOB_ID_STATE");require(job["provider"]==PROVIDER and job["provider_profile"]==PROFILE and job["model"]==MODEL and job["resource_key"]==RESOURCE,"JOB_PROVIDER");require(job["execution_limits"]==LIMITS and all(type(x) is int for x in job["execution_limits"].values()),"JOB_LIMITS");prompt=job["prompt_artifact"];require(type(prompt) is dict and prompt==PROMPT,"JOB_PROMPT");_custody(job["prompt_custody"]);schedule=exact(job["schedule"],("kind","at","grace_seconds"),"JOB_SCHEDULE_SHAPE");require(schedule["kind"]=="once" and type(schedule["grace_seconds"]) is int and 1<=schedule["grace_seconds"]<=300 and schedule["at"]==lineage["scheduled_at"] and schedule["grace_seconds"]==lineage["grace_seconds"],"JOB_SCHEDULE");at=_parse(schedule["at"],"JOB_AT");require(current<at and (at-current).total_seconds()<=v["approved_horizon_seconds"],"JOB_STALE");scheduled_values.append((schedule["at"],schedule["grace_seconds"]));normalized.append({k:job[k] for k in job if k not in ("id","cell_id")})
 require(normalized[0]==normalized[1] and scheduled_values[0]==scheduled_values[1],"JOB_ASYMMETRY");require(v["installed_jobs"]==[] and v["installed_schedules"]==[],"PROPOSAL_NOT_INSTALLED");require(v["effects"]==EFFECTS and all(type(x) is int for x in v["effects"].values()),"PROPOSAL_EFFECTS");return v
def render_proposal(materialized:Mapping[str,Any],materialized_sha256:str,current_evaluation_time:datetime,prompt_custody:Mapping[str,Any])->Proposal:
 source=dict(materialized);require(materialized_sha256==MATERIALIZED_SHA and hashlib.sha256(canonical_bytes(source)).hexdigest()==MATERIALIZED_SHA,"MATERIALIZED_BINDING");current=_utc(current_evaluation_time);materialized_evaluation=_parse(source.get("evaluation_time"),"MATERIALIZED_EVALUATION");not_before=_parse(source.get("not_before"),"MATERIALIZED_NOT_BEFORE");scheduled_lineage=_parse(source.get("scheduled_at"),"MATERIALIZED_SCHEDULED");deadline_lineage=_parse(source.get("deadline"),"MATERIALIZED_DEADLINE");require(materialized_evaluation<=current<scheduled_lineage and not_before<=scheduled_lineage<=deadline_lineage,"MATERIALIZED_TIME_LINEAGE");custody=dict(_custody(dict(prompt_custody)));require(source.get("activation") is False and source.get("countable") is False and source.get("installed_jobs")==[] and source.get("installed_schedules")==[],"MATERIALIZED_STATE");require(source.get("integration_closure_sha256")==INTEGRATION_CLOSURE and source.get("bridge_closure_sha256")==BRIDGE_CLOSURE and source.get("adapter_closure_sha256")==ADAPTER_CLOSURE,"MATERIALIZED_CLOSURES");jobs=[]
 for i,item in enumerate(source.get("jobs",[])):
  require(type(item) is dict and item.get("job_id")==JOBS[i] and item.get("cell_id")==CELLS[i],"MATERIALIZED_JOB_ORDER");schedule=dict(item.get("schedule",{}));at=_parse(schedule.get("at"),"MATERIALIZED_AT");deadline=_parse(source.get("deadline"),"MATERIALIZED_DEADLINE");require(at==scheduled_lineage and deadline==deadline_lineage and current<at<=deadline and (at-current).total_seconds()<=300 and schedule==source["jobs"][0]["schedule"] and at.timestamp()+schedule.get("grace_seconds",0)<=deadline.timestamp(),"MATERIALIZED_STALE");jobs.append({"id":JOBS[i],"cell_id":CELLS[i],"enabled":False,"schedule":schedule,"provider":PROVIDER,"provider_profile":PROFILE,"model":MODEL,"replay_safe":False,"execution_limits":dict(LIMITS),"prompt_artifact":dict(item["prompt_artifact"]),"prompt_custody":dict(custody),"resource_key":RESOURCE})
 require(len(jobs)==2,"MATERIALIZED_JOB_COUNT");document={"version":1,"schema":SCHEMA,"classification":"DATA_ONLY_NOT_CONFIG_V2_NOT_ENGINE_INSTALLABLE","kind":"R6_FABLE_PROVIDER_FREE_INSTALLATION_PROPOSAL_DATA","activation":False,"apply":False,"countable":False,"proposal_evaluation_time":_text(current),"approved_horizon_seconds":300,"materialized_sha256":MATERIALIZED_SHA,"materialization_closure_sha256":MATERIALIZATION_CLOSURE,"design_sha256":DESIGN_SHA,"integration_sha256":INTEGRATION_SHA,"integration_closure_sha256":INTEGRATION_CLOSURE,"bridge_closure_sha256":BRIDGE_CLOSURE,"adapter_closure_sha256":ADAPTER_CLOSURE,"logical_database_id":"closed-engine/fable-ab/schedule.sqlite","materialized_lineage":{"evaluation_time":source["evaluation_time"],"not_before":source["not_before"],"scheduled_at":source["scheduled_at"],"deadline":source["deadline"],"grace_seconds":source["jobs"][0]["schedule"]["grace_seconds"]},"output_custody_contract":"FRESH_OWNER_PRIVATE_DESCRIPTOR_BARRIER_NO_REPLACE","execution":{"max_workers":1,"resource_serialization":True,"resource_key":RESOURCE},"jobs":jobs,"installed_jobs":[],"installed_schedules":[],"effects":dict(EFFECTS)};validate_proposal(document);return Proposal(_freeze(document),SCHEMA,hashlib.sha256(canonical_bytes(document)).hexdigest())
def default_proposal()->Mapping[str,Any]:return MappingProxyType({"status":"DENIED_PURE_PROPOSAL_ONLY","activation":False,"apply":False,"countable":False,"effects":MappingProxyType(dict(EFFECTS))})
__all__=["Proposal","ProposalError","canonical_bytes","default_proposal","render_proposal","strict_json_loads","validate_proposal"]
