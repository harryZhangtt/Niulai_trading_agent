"""Closed contracts for the disabled provider-free Claude driver."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, json, re
from typing import Any, Dict, Iterable, Mapping, Optional
MODEL="claude-opus-5-5"; EFFORT="low"; SURFACE="claude_cli"
LIMITS={"claude_hard_subcap_usd":0.01,"combined_hard_cap_usd":0.02,"window_minutes":30,"request_retries":0,"stream_retries":0,"max_attempts":1,"concurrency":1,"countable":False,"replay":False,"status_after_unknown":False}
EFFECT_NAMES=("provider","network","account","login","private_live_root","email","host","persistent","r5")
SECRET_TOKENS=("api_key","auth_token","authorization","bearer ","password","secret_value","credential_value","x-api-key")
_SHA=re.compile(r"[0-9a-f]{64}\Z")
class ContractError(ValueError): pass
def require(v:bool,code:str)->None:
    if not v: raise ContractError(code)
def canonical_bytes(v:Any)->bytes:return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii")
def sha256_bytes(v:bytes)->str:return hashlib.sha256(v).hexdigest()
def no_effects()->Dict[str,int]:return {k:0 for k in EFFECT_NAMES}
def exact(v:Any,keys:Iterable[str],code:str)->Mapping[str,Any]:require(type(v)is dict and set(v)==set(keys),code);return v
def digest(v:Any,code:str)->str:require(type(v)is str and _SHA.fullmatch(v) is not None,code);return v
def safe_public(v:Any)->None:
    raw=canonical_bytes(v).decode("ascii").lower();require(not any(t in raw for t in SECRET_TOKENS),"SENSITIVE_PUBLICATION_FORBIDDEN");require("/users/" not in raw and ".job-runtime" not in raw,"PRIVATE_PATH_PUBLICATION_FORBIDDEN")
def descriptor(v:Any,code="DESCRIPTOR_INVALID"):
    x=exact(v,{"identity","bytes","sha256","regular","no_symlink"},code);require(type(x["identity"])is str and x["identity"] and not x["identity"].startswith("/"),code);require(type(x["bytes"])is int and x["bytes"]>0,code);digest(x["sha256"],code);require(x["regular"]is True and x["no_symlink"]is True,code);return x
def validate_held_manifest(v:Any):
    keys={"binary","argv","config","catalog","prompt","parser","cleanup_policy","model","effort","model_membership","no_shell","env_allowlist","digest"};x=exact(v,keys,"HELD_MANIFEST_SHAPE")
    require(x["model"]==MODEL and x["effort"]==EFFORT and x["model_membership"]is True and x["no_shell"]is True,"HELD_BINDING_DRIFT");require(x["env_allowlist"]==["CLAUDE_CONFIG_DIR","HOME","LANG","PATH","TMPDIR"],"ENV_ALLOWLIST_DRIFT")
    for k in ("binary","argv","config","catalog","prompt","parser","cleanup_policy"):descriptor(x[k])
    body=dict(x);d=body.pop("digest");require(d==sha256_bytes(canonical_bytes(body)),"HELD_MANIFEST_DIGEST_DRIFT");return x
def validate_engine_readback(v:Any):
    keys={"version","verified","job_id","slot_id","attempt_id","operation_id","provider_process_id","request_id","native_prompt","counts","transaction","digest"};x=exact(v,keys,"ENGINE_READBACK_SHAPE")
    require(x["version"]==1 and x["verified"]is True and all(type(x[k])is str and x[k] for k in ("job_id","slot_id","attempt_id","operation_id","provider_process_id","request_id")),"ENGINE_READBACK_ID")
    p=exact(x["native_prompt"],{"artifact_ref","sha256","bytes","source_identity_sha256","binding_sha256"},"ENGINE_PROMPT_SHAPE");digest(p["sha256"],"ENGINE_PROMPT_SHA");digest(p["source_identity_sha256"],"ENGINE_PROMPT_ID");digest(p["binding_sha256"],"ENGINE_PROMPT_BINDING");require(type(p["bytes"])is int and p["bytes"]>0,"ENGINE_PROMPT_BYTES")
    require(x["counts"]=={"job":1,"slot":1,"attempt":1,"prompt_artifact":1},"ENGINE_COUNTS");require(x["transaction"]=="BEGIN_IMMEDIATE_POST_WRITE_READBACK","ENGINE_TRANSACTION")
    body=dict(x);d=body.pop("digest");require(d==sha256_bytes(canonical_bytes(body)),"ENGINE_READBACK_DIGEST");return x
def validate_launch_spec(v:Any):
    keys={"version","binary","argv","shell","env_allowlist","config","catalog","model","prompt","process_group","deadline_seconds","terminate","kill","reap","engine_readback_digest","digest"};x=exact(v,keys,"LAUNCH_SPEC_SHAPE")
    for k in ("binary","argv","config","catalog","prompt"):descriptor(x[k],"LAUNCH_DESCRIPTOR")
    require(x["version"]==1 and x["shell"]is False and x["model"]==MODEL and x["process_group"]is True and x["deadline_seconds"]==30 and x["terminate"]is True and x["kill"]is True and x["reap"]is True,"LAUNCH_POLICY_DRIFT");require(x["env_allowlist"]==["CLAUDE_CONFIG_DIR","HOME","LANG","PATH","TMPDIR"],"LAUNCH_ENV_DRIFT");digest(x["engine_readback_digest"],"LAUNCH_ENGINE_DIGEST")
    body=dict(x);d=body.pop("digest");require(d==sha256_bytes(canonical_bytes(body)),"LAUNCH_SPEC_DIGEST_DRIFT");return x
def validate_ferry_receipt(v:Any):
    keys={"version","observer_id","job_id","slot_id","attempt_id","operation_id","provider_process_id","request_id","model","native_prompt_artifact_identity","native_prompt_sha256","grant_digest","launch_spec_digest","request_fingerprint","engine_readback_event","admission_event","admission_count","upstream_count","second_reject_count","status_calls","durable"};x=exact(v,keys,"FERRY_RECEIPT_SHAPE")
    require(x["version"]==1 and x["model"]==MODEL and x["admission_count"]==1 and x["upstream_count"] in (0,1) and x["second_reject_count"] in (0,1) and x["status_calls"]==0 and x["durable"]is True,"FERRY_COUNTS");[digest(x[k],"FERRY_DIGEST") for k in ("native_prompt_artifact_identity","native_prompt_sha256","grant_digest","launch_spec_digest","request_fingerprint")];require(x["engine_readback_event"]==1 and x["admission_event"]==2,"FERRY_EVENT_ORDER");return x
def validate_process_receipt(v:Any):
    keys={"version","starts","terminations","kills","reaps","descriptors_closed","launch_spec_digest_echo","binary_sha256","argv_sha256","shell","env_allowlist","config_sha256","catalog_sha256","model","prompt_sha256","process_group","deadline_seconds","terminate_policy","kill_policy","reap_policy","output_identity","parser_identity","terminal_state","exit_code","nested_error"};x=exact(v,keys,"PROCESS_RECEIPT_SHAPE")
    require(x["version"]==1 and all(type(x[k])is int and 0<=x[k]<=2 for k in ("starts","terminations","kills","reaps","descriptors_closed")),"PROCESS_COUNTS");[digest(x[k],"PROCESS_DIGEST") for k in ("launch_spec_digest_echo","binary_sha256","argv_sha256","config_sha256","catalog_sha256","prompt_sha256")];require(type(x["nested_error"])is dict and set(x["nested_error"])=={"present","code"},"PROCESS_ERROR_SHAPE");return x
def validate_terminal(v):
    x=exact(v,{"state","exact","parser_identity","output_identity"},"TERMINAL_SHAPE");require(x["state"] in ("absent","exact","truncated") and type(x["exact"])is bool and type(x["parser_identity"])is str and type(x["output_identity"])is str,"TERMINAL_VALUE");return x
def validate_cleanup(v):
    x=exact(v,{"state","process_group_reaped","descriptors_closed","residuals"},"CLEANUP_SHAPE");require(x["state"] in ("not_started","complete","uncertain") and type(x["process_group_reaped"])is bool and type(x["descriptors_closed"])is bool and type(x["residuals"])is list and all(type(y)is str for y in x["residuals"]),"CLEANUP_VALUE");return x
def validate_publication(v):
    x=exact(v,{"owner_private","sanitized","atomic","owner_final","public_final","collision_preserved"},"PUBLICATION_SHAPE");require(all(type(x[k])is bool for k in ("owner_private","sanitized","atomic","collision_preserved")) and all(x[k] is None or type(x[k])is str for k in ("owner_final","public_final")),"PUBLICATION_VALUE");return x
def validate_unknown(v):
    x=exact(v,{"durable","retry","replay","status_calls","receipt"},"UNKNOWN_SHAPE");require(type(x["durable"])is bool and x["retry"]is False and x["replay"]is False and x["status_calls"]==0 and (x["receipt"] is None or x["receipt"]=="unknown-fence.json"),"UNKNOWN_VALUE");return x
def validate_evidence(v:Any):
    keys={"version","status","reason","countable","surface","model","effort","limits","engine_readback","request_fingerprint","launch_spec_digest","process","ferry","terminal","cleanup","publication","effects","unknown_fence"};x=exact(v,keys,"EVIDENCE_SHAPE")
    require(x["version"]==1 and x["status"] in ("PASS","STOP","UNKNOWN") and type(x["reason"])is str and x["reason"] and x["countable"]is False and x["surface"]==SURFACE and x["model"]==MODEL and x["effort"]==EFFORT,"EVIDENCE_HEADER");require(x["limits"]==LIMITS and x["effects"]==no_effects(),"EVIDENCE_LIMIT_EFFECT")
    if x["engine_readback"] is not None:validate_engine_readback(x["engine_readback"])
    if x["request_fingerprint"] is not None:digest(x["request_fingerprint"],"EVIDENCE_REQUEST")
    if x["launch_spec_digest"] is not None:digest(x["launch_spec_digest"],"EVIDENCE_LAUNCH")
    if x["process"] is not None:validate_process_receipt(x["process"])
    if x["ferry"] is not None:validate_ferry_receipt(x["ferry"])
    validate_terminal(x["terminal"]);validate_cleanup(x["cleanup"]);validate_publication(x["publication"]);validate_unknown(x["unknown_fence"]);safe_public(x);return x
@dataclass(frozen=True)
class DriverResult:
    evidence:Dict[str,Any];owner_private_final:Optional[str];sanitized_final:Optional[str]
