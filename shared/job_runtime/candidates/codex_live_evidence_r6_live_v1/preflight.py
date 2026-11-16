"""Held-descriptor provider-free preflight and durable pre-dispatch authority burn."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any,Dict,Mapping
from .contracts import ContractError,DurableAuthorityStore,HeldArtifactSet,LiveAuthorization,sha256_bytes,strict_json_bytes
from .grant import validate_grant_seal
class PreflightLease:
    def __init__(self,held:HeldArtifactSet,store:DurableAuthorityStore,operation_key:str,artifacts:Dict[str,Dict[str,Any]],receipt:Dict[str,Any])->None:self.held=held;self.store=store;self.operation_key=operation_key;self.artifacts=artifacts;self.receipt=receipt
    def close(self)->None:self.held.close()
def _simple(path:Any,size:Any,digest:Any)->Dict[str,Any]:return {"path":path,"bytes":size,"sha256":digest}
def prepare(grant:Mapping[str,Any],authorization:LiveAuthorization,now:Any,root:Path)->PreflightLease:
    held=None
    try:
        validate_grant_seal(grant,authorization,now);custody=grant["custody"]
        if str(root)!=custody["owner_private_custody_root"]:raise ContractError("R6_CUSTODY_ROOT_MISMATCH")
        held=HeldArtifactSet(root,custody["owner_uid"]);b=grant["binary"];inv=grant["canonical_invocation"];cat=grant["catalog"];prompt=grant["prompt"]
        artifacts={"binary":held.open_exact({"path":b["canonical_path"],"bytes":b["bytes"],"sha256":b["sha256"],"device":b["device"],"inode":b["inode"],"owner_uid":b["owner_uid"],"mode":b["mode"]},"binary"),"argv":held.open_exact(_simple(inv["argv_path"],inv["argv_bytes"],inv["argv_sha256"]),"argv"),"config":held.open_exact(_simple(inv["config_path"],inv["config_bytes"],inv["config_sha256"]),"config"),"catalog":held.open_exact(_simple(cat["raw_catalog_private_path"],cat["raw_catalog_bytes"],cat["raw_catalog_sha256"]),"catalog"),"parser":held.open_exact(_simple(cat["catalog_parser_path"],cat["catalog_parser_bytes"],cat["catalog_parser_sha256"]),"parser"),"prompt":held.open_exact(_simple(prompt["native_prompt_path"],prompt["native_prompt_bytes"],prompt["native_prompt_sha256"]),"prompt")}
        if b["official_asset_sha256"]!=b["sha256"]:raise ContractError("R6_OFFICIAL_ASSET_MISMATCH")
        argv=strict_json_bytes(artifacts["argv"]["data"]);config=strict_json_bytes(artifacts["config"]["data"]);model=grant["model"]["selected_model"]
        if type(argv) is not list or argv.count(model)!=1 or not argv or argv[0]!=b["canonical_path"]:raise ContractError("R6_ARGV_INVALID")
        if type(config) is not dict or config!={"gateway_retries":0,"request_retries":0,"stream_retries":0}:raise ContractError("R6_CONFIG_INVALID")
        try:catalog=artifacts["catalog"]["data"].decode("utf-8")
        except UnicodeDecodeError as e:raise ContractError("R6_CATALOG_ENCODING") from e
        if sum(1 for line in catalog.splitlines() if line==model)!=1:raise ContractError("R6_CATALOG_MEMBERSHIP_INVALID")
        store=DurableAuthorityStore(root);op=store.reserve_and_burn(authorization.one_use_nonce,grant["identity"])
        receipt={"decision":"PASS","reason_code":"R6_PREFLIGHT_PASS","catalog_preflight_count":1,"membership_verified":True,"operation_key":op,"held_artifacts":{k:{x:v[x] for x in ("bytes","sha256","device","inode","owner_uid","mode")} for k,v in artifacts.items()},"custody_root_identity":held.root_identity}
        return PreflightLease(held,store,op,artifacts,receipt)
    except ContractError:
        if held is not None:held.close()
        raise
    except Exception as e:
        if held is not None:held.close()
        raise ContractError("R6_PREFLIGHT_MALFORMED") from e
def run_preflight(grant:Mapping[str,Any],authorization:Any,now:Any,root:Path)->Dict[str,Any]:
    try:
        lease=prepare(grant,authorization,now,root);receipt=dict(lease.receipt);lease.close();return receipt
    except Exception as e:return {"decision":"STOP","reason_code":str(e) if isinstance(e,ContractError) else "R6_PREFLIGHT_MALFORMED","catalog_preflight_count":0,"membership_verified":False}
