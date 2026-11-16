"""Closed two-stage grant and trusted held-file authorization verifier."""
from __future__ import annotations
from pathlib import Path
from typing import Any,Dict,Mapping,Optional
from .contracts import ContractError,DESIGN_SHA256,HeldArtifactSet,IDENTITY_FIELDS,LIMITS,LiveAuthorization,PACKAGE,PLACEHOLDER,_LIVE_AUTH_MARKER,canonical_bytes,exact_keys,is_sha,parse_time,require_bool,require_int,require_number,require_string,scan_forbidden,sha256_bytes,strict_json_bytes
EXTERNAL_FIELDS=("expected_account_fingerprint","credential_reference","model_entitlement","selected_model","hard_usd_cap","cost_authority","not_before","deadline","owner_private_custody_root","held_binary_identity","official_asset","canonical_argv","canonical_config","raw_catalog_custody","selected_model_membership","native_prompt_identity","engine_identity","request_local_gateway_fingerprint")
def stage_a_template()->Dict[str,Any]:return {"schema_version":"codex-live-evidence-r6-live-grant-template-v1","package":PACKAGE,"enabled":False,"live_authority":False,"synthetic_only":True,"authority":"NON_AUTHORIZING","external_fields":{k:PLACEHOLDER for k in EXTERNAL_FIELDS}}
def validate_stage_a(v:Mapping[str,Any])->None:
    exact_keys(v,("schema_version","package","enabled","live_authority","synthetic_only","authority","external_fields"),"R6_STAGE_A_CLOSED")
    if v!=stage_a_template():raise ContractError("R6_STAGE_A_NONAUTHORIZATION_INVALID")
def seal_payload_sha256(v:Mapping[str,Any])->str:
    copy=dict(v);copy.pop("seal_sha256",None);return sha256_bytes(canonical_bytes(copy))
def grant_core_sha256(v:Mapping[str,Any])->str:
    copy=dict(v);copy.pop("seal_sha256",None);copy.pop("authority",None);return sha256_bytes(canonical_bytes(copy))
def _binding(path:Any,size:Any,digest:Any)->Dict[str,Any]:return {"path":require_string(path,"R6_AUTH_PATH"),"bytes":require_int(size,"R6_AUTH_BYTES"),"sha256":require_string(digest,"R6_AUTH_SHA")}
def validate_grant_structure(v:Mapping[str,Any],now:Any)->None:
    try:
        top=("schema_version","package","enabled","live_authority","synthetic_only","email_authorized","authority","identity","account","model","cost","window","custody","binary","canonical_invocation","catalog","prompt","limits","seal_sha256")
        exact_keys(v,top,"R6_GRANT_CLOSED");scan_forbidden(v)
        if (v["schema_version"],v["package"],v["enabled"],v["live_authority"],v["synthetic_only"],v["email_authorized"])!=("codex-live-evidence-r6-live-grant-seal-v1",PACKAGE,True,True,False,False):raise ContractError("R6_GRANT_CONSTANT")
        exact_keys(v["limits"],LIMITS,"R6_LIMITS_CLOSED")
        if v["limits"]!=LIMITS:raise ContractError("R6_LIMITS_INVALID")
        exact_keys(v["identity"],IDENTITY_FIELDS,"R6_IDENTITY_CLOSED")
        for k in IDENTITY_FIELDS:require_string(v["identity"][k],"R6_IDENTITY_INVALID")
        a=v["account"];exact_keys(a,("expected_account_fingerprint","observed_opaque_account_fingerprint","credential_reference","credential_reference_only","login_authorized","auth_checked_at","auth_expires_at"),"R6_ACCOUNT_CLOSED")
        ref=require_string(a["credential_reference"],"R6_CREDENTIAL_REFERENCE_INVALID")
        if len(ref)>512 or any(x.isspace() for x in ref) or "://" not in ref:raise ContractError("R6_CREDENTIAL_REFERENCE_INVALID")
        if not is_sha(a["expected_account_fingerprint"]) or a["expected_account_fingerprint"]!=a["observed_opaque_account_fingerprint"] or require_bool(a["credential_reference_only"],"R6_ACCOUNT_TYPE") is not True or require_bool(a["login_authorized"],"R6_ACCOUNT_TYPE") is not True:raise ContractError("R6_ACCOUNT_AUTH_INVALID")
        m=v["model"];exact_keys(m,("model_entitlement","selected_model","entitlement_checked_at","entitlement_expires_at"),"R6_MODEL_CLOSED");require_bool(m["model_entitlement"],"R6_MODEL_TYPE");require_string(m["selected_model"],"R6_MODEL_TYPE")
        c=v["cost"];exact_keys(c,("currency","hard_usd_cap","cost_authority","estimated_maximum_usd","final_cost_receipt_private_path"),"R6_COST_CLOSED");cap=require_number(c["hard_usd_cap"],"R6_COST_TYPE");estimate=require_number(c["estimated_maximum_usd"],"R6_COST_TYPE")
        if c["currency"]!="USD" or cap<=0 or estimate<=0 or estimate>cap or require_string(c["cost_authority"],"R6_COST_INVALID")=="synthetic_non_authorizing":raise ContractError("R6_COST_INVALID")
        win=v["window"];exact_keys(win,("not_before","deadline"),"R6_WINDOW_CLOSED")
        if not(parse_time(win["not_before"])<=now<parse_time(win["deadline"])):raise ContractError("R6_WINDOW_INVALID")
        if parse_time(a["auth_expires_at"])<=now or parse_time(m["entitlement_expires_at"])<=now:raise ContractError("R6_AUTH_EXPIRED")
        custody=v["custody"];exact_keys(custody,("owner_private_custody_root","owner_uid","mode_0700","nofollow_components","atomic_finalization","raw_private_only"),"R6_CUSTODY_CLOSED");require_string(custody["owner_private_custody_root"],"R6_CUSTODY_TYPE");require_int(custody["owner_uid"],"R6_CUSTODY_TYPE")
        if any(require_bool(custody[k],"R6_CUSTODY_TYPE") is not True for k in ("mode_0700","nofollow_components","atomic_finalization","raw_private_only")):raise ContractError("R6_CUSTODY_INVALID")
        binary=v["binary"];exact_keys(binary,("held_fd_identity","canonical_path","bytes","sha256","device","inode","owner_uid","mode","official_asset_reference","official_asset_sha256"),"R6_BINARY_CLOSED")
        for k in ("bytes","device","inode","owner_uid","mode"):require_int(binary[k],"R6_BINARY_TYPE")
        for k in ("held_fd_identity","canonical_path","sha256","official_asset_reference","official_asset_sha256"):require_string(binary[k],"R6_BINARY_TYPE")
        inv=v["canonical_invocation"];exact_keys(inv,("argv_path","argv_bytes","argv_sha256","config_path","config_bytes","config_sha256","environment_allowlist_sha256"),"R6_INVOCATION_CLOSED")
        cat=v["catalog"];exact_keys(cat,("raw_catalog_private_path","raw_catalog_bytes","raw_catalog_sha256","catalog_parser_path","catalog_parser_bytes","catalog_parser_sha256","selected_model","selected_model_occurrences","membership_verified","catalog_preflight_count"),"R6_CATALOG_CLOSED")
        prompt=v["prompt"];exact_keys(prompt,("native_prompt_path","native_prompt_bytes","native_prompt_sha256","native_prompt_identity","engine_identity","treatment_fingerprint"),"R6_PROMPT_CLOSED")
        authority=v["authority"];exact_keys(authority,("explicit_user_authorization_receipt_path","explicit_user_authorization_receipt_bytes","explicit_user_authorization_receipt_sha256","independent_grant_review_path","independent_grant_review_bytes","independent_grant_review_sha256","stage_a_source_closure_path","stage_a_source_closure_bytes","stage_a_source_closure_sha256"),"R6_AUTHORITY_CLOSED")
        if m["model_entitlement"] is not True or m["selected_model"]!=cat["selected_model"] or cat["membership_verified"] is not True or cat["selected_model_occurrences"]!=1 or cat["catalog_preflight_count"]!=1:raise ContractError("R6_MODEL_CATALOG_INVALID")
        if prompt["native_prompt_identity"]!=v["identity"]["native_prompt_identity"] or prompt["engine_identity"]!=v["identity"]["engine_identity"]:raise ContractError("R6_PROMPT_IDENTITY_MISMATCH")
        if not is_sha(v["seal_sha256"]) or v["seal_sha256"]!=seal_payload_sha256(v):raise ContractError("R6_SEAL_MISMATCH")
    except ContractError:raise
    except Exception as e:raise ContractError("R6_GRANT_MALFORMED") from e
def validate_grant_seal(v:Mapping[str,Any],authorization:Any,now:Any)->None:
    validate_grant_structure(v,now)
    if type(authorization) is not LiveAuthorization or authorization.grant_seal_sha256!=v["seal_sha256"] or authorization.explicit_user_authorization_receipt_sha256!=v["authority"]["explicit_user_authorization_receipt_sha256"]:raise ContractError("R6_LIVE_AUTHORIZATION_REQUIRED")
class TrustedAuthorizationVerifier:
    """The only constructor of LiveAuthorization; verifies held authority artifacts."""
    @classmethod
    def issue(cls,grant:Mapping[str,Any],trusted_root:Path,now:Any)->LiveAuthorization:
        validate_grant_structure(grant,now);a=grant["authority"];owner=grant["custody"]["owner_uid"]
        with HeldArtifactSet(trusted_root,owner) as held:
            auth=held.open_exact(_binding(a["explicit_user_authorization_receipt_path"],a["explicit_user_authorization_receipt_bytes"],a["explicit_user_authorization_receipt_sha256"]),"authorization")
            review=held.open_exact(_binding(a["independent_grant_review_path"],a["independent_grant_review_bytes"],a["independent_grant_review_sha256"]),"review")
            held.open_exact(_binding(a["stage_a_source_closure_path"],a["stage_a_source_closure_bytes"],a["stage_a_source_closure_sha256"]),"closure")
            av=strict_json_bytes(auth["data"]);rv=strict_json_bytes(review["data"]);core=grant_core_sha256(grant)
            exact_keys(av,("schema_version","authorized","grant_core_sha256","one_use_nonce"),"R6_AUTH_RECEIPT_CLOSED");exact_keys(rv,("schema_version","grant_core_sha256","verdict"),"R6_REVIEW_RECEIPT_CLOSED")
            if av!={"schema_version":"r6-explicit-user-authorization-v1","authorized":True,"grant_core_sha256":core,"one_use_nonce":av.get("one_use_nonce")} or not require_string(av.get("one_use_nonce"),"R6_AUTH_NONCE") or rv!={"schema_version":"r6-independent-grant-review-v1","grant_core_sha256":core,"verdict":"CLEAN"}:raise ContractError("R6_AUTH_PROVENANCE_INVALID")
            provenance=sha256_bytes(canonical_bytes({"authorization":auth["sha256"],"review":review["sha256"],"closure":a["stage_a_source_closure_sha256"],"root":held.root_identity}))
            return LiveAuthorization._issue(grant["seal_sha256"],auth["sha256"],av["one_use_nonce"],provenance,_LIVE_AUTH_MARKER)
