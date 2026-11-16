"""Fail-closed structural preflight over caller-provided synthetic artifacts."""
from __future__ import annotations
import json,os,stat
from datetime import datetime
from pathlib import Path
from typing import Any,Dict,Mapping
from .contracts import CALL_BUDGET,R6ContractError,SecureArtifactSet,assert_same_identity,sha256_bytes,strict_json_bytes,validate_identity
from .translator import parser_binding
_ARTIFACTS=("executable","canonical_argv","canonical_config","model_catalog","prompt")
def _timestamp(value:Any)->datetime:
 if type(value) is not str or not value.endswith("Z"):raise R6ContractError("R6_TIMESTAMP_INVALID")
 try:return datetime.fromisoformat(value[:-1]+"+00:00")
 except ValueError:raise R6ContractError("R6_TIMESTAMP_INVALID") from None
def _stop(identity:Mapping[str,str],code:str)->Dict[str,Any]:return {"schema_version":"preflight-receipt-v1","identity":dict(identity),"decision":"STOP","reason_code":code,"submission":"DEFINITELY_NOT_SUBMITTED","upstream_attempt_count":0,"countable_observation":False}
def _private_root(value:Any,synthetic_root:Path)->None:
 keys={"canonical_path","owner_uid","mode_0700","nofollow_components","atomic_finalization"}
 if type(value) is not dict or set(value)!=keys:raise R6ContractError("R6_PRIVATE_ROOT_GATE_STOP")
 path=Path(value["canonical_path"])
 try:info=path.lstat();resolved=path.resolve(strict=True)
 except OSError:raise R6ContractError("R6_PRIVATE_ROOT_GATE_STOP") from None
 if not path.is_absolute() or resolved!=synthetic_root.resolve(strict=True) or stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or value["owner_uid"]!=os.getuid() or info.st_uid!=value["owner_uid"] or value["mode_0700"] is not True or stat.S_IMODE(info.st_mode)!=0o700 or value["nofollow_components"] is not True or value["atomic_finalization"] is not True:raise R6ContractError("R6_PRIVATE_ROOT_GATE_STOP")
def run_preflight(grant:Mapping[str,Any],*,synthetic_root:Path,now:datetime)->Dict[str,Any]:
 identity=validate_identity(grant.get("identity") if type(grant) is dict else None)
 try:
  keys={"schema_version","identity","enabled","live_authority","synthetic_only","call_budget","artifacts","account","budget","window","private_root","prompt_process"}
  if type(grant) is not dict or set(grant)!=keys or grant["schema_version"]!="r6-grant-v1" or grant["enabled"] is not False or grant["live_authority"] is not False or grant["synthetic_only"] is not True or grant["call_budget"]!=dict(CALL_BUDGET):raise R6ContractError("R6_GRANT_INVALID")
  _private_root(grant["private_root"],synthetic_root)
  artifacts=grant["artifacts"]
  if type(artifacts) is not dict or set(artifacts)!=set(_ARTIFACTS):raise R6ContractError("R6_ARTIFACT_SET_INVALID")
  for name in _ARTIFACTS:
   required={"path","bytes","sha256","inode","owner","mode"}
   if name=="executable":required.add("official_asset_ref")
   if name=="model_catalog":required|={"parser_source_sha256","selected_model_token","selected_model_occurrences"}
   if set(artifacts[name])!=required:raise R6ContractError("R6_CANONICAL_BINDING_INVALID")
  with SecureArtifactSet(artifacts,synthetic_root) as opened:
   loaded=opened.read_all()
   catalog=artifacts["model_catalog"];parser=parser_binding()
   if catalog["parser_source_sha256"]!=parser["sha256"]:raise R6ContractError("R6_PARSER_BINDING_STOP")
   try:argv=strict_json_bytes(loaded["canonical_argv"]);config=strict_json_bytes(loaded["canonical_config"])
   except R6ContractError:raise R6ContractError("R6_CANONICAL_CONFIG_STOP") from None
   expected_argv=[artifacts["executable"]["path"],"--model",catalog["selected_model_token"]]
   if argv!=expected_argv:raise R6ContractError("R6_CANONICAL_ARGV_STOP")
   if config!={"request_retries":0,"stream_retries":0}:raise R6ContractError("R6_CANONICAL_CONFIG_STOP")
   try:occurrences=loaded["model_catalog"].decode("utf-8").splitlines().count(catalog["selected_model_token"])
   except UnicodeDecodeError:raise R6ContractError("R6_CATALOG_SELECTED_MODEL_NOT_EXACTLY_ONCE") from None
   if catalog["selected_model_occurrences"]!=1 or occurrences!=1:raise R6ContractError("R6_CATALOG_SELECTED_MODEL_NOT_EXACTLY_ONCE")
   account=grant["account"]
   account_keys={"opaque_account_fingerprint","expected_account_fingerprint","entitlement","model_access","auth_checked_at","auth_expires_at","credential_reference_only"}
   if type(account) is not dict or set(account)!=account_keys or account["opaque_account_fingerprint"]!=account["expected_account_fingerprint"] or account["entitlement"] is not True or account["model_access"] is not True or account["credential_reference_only"] is not True or not (_timestamp(account["auth_checked_at"])<=now<_timestamp(account["auth_expires_at"])):raise R6ContractError("R6_ACCOUNT_GATE_STOP")
   budget=grant["budget"]
   if type(budget) is not dict or set(budget)!={"currency","hard_maximum","cost_authority","final_cost_receipt"} or budget["currency"]!="USD" or type(budget["hard_maximum"]) not in (int,float) or type(budget["hard_maximum"]) is bool or budget["hard_maximum"]<=0 or budget["cost_authority"]!="synthetic_non_authorizing" or budget["final_cost_receipt"] is not None:raise R6ContractError("R6_COST_GATE_STOP")
   window=grant["window"]
   if type(window) is not dict or set(window)!={"not_before","deadline"} or not (_timestamp(window["not_before"])<=now<_timestamp(window["deadline"])):raise R6ContractError("R6_WINDOW_GATE_STOP")
   prompt=grant["prompt_process"];prompt_keys={"identity","prompt_path","bytes","sha256","job_id","slot_id","attempt_id","operation_id","provider_process_start_identity","gateway_id","treatment_fingerprint"}
   if type(prompt) is not dict or set(prompt)!=prompt_keys or prompt["prompt_path"]!=artifacts["prompt"]["path"] or prompt["bytes"]!=artifacts["prompt"]["bytes"] or prompt["sha256"]!=artifacts["prompt"]["sha256"]:raise R6ContractError("R6_PROMPT_BINDING_INVALID")
   assert_same_identity(identity,prompt)
   for field in ("job_id","slot_id","attempt_id","operation_id","provider_process_start_identity","gateway_id"):
    if prompt[field]!=identity[field]:raise R6ContractError("R6_PROMPT_IDENTITY_MISMATCH")
   if type(prompt["treatment_fingerprint"]) is not str or len(prompt["treatment_fingerprint"])!=64:raise R6ContractError("R6_PROMPT_BINDING_INVALID")
  # Descriptor set remained held through every parser/catalog/prompt check above.
 except R6ContractError as error:return _stop(identity,error.code)
 return {"schema_version":"preflight-receipt-v1","identity":dict(identity),"decision":"PASS","reason_code":"r6.preflight.ok","submission":"DEFINITELY_NOT_SUBMITTED","upstream_attempt_count":0,"catalog_preflight_count":1,"artifact_set_sha256":sha256_bytes(b"".join(loaded[name] for name in _ARTIFACTS)),"countable_observation":False}
