"""Single-owner provider-free state machine with durable UNKNOWN fencing."""
from pathlib import Path
from typing import Any,Dict,Mapping
from .cleanup import cleanup
from .contracts import ContractError,LiveAuthorization,validate_outcome
from .preflight import prepare
from .reconciliation import persist_unknown
from .translator import translate
def _stop(reason:str,cleanup_receipt:Mapping[str,Any],catalog_count:int=0)->Dict[str,Any]:
    value={"schema_version":"codex-live-evidence-r6-live-evidence-v1","terminal_outcome":"STOP","reason_code":reason,"countable_observation":False,"submission":"DEFINITELY_NOT_SUBMITTED","catalog_preflight_count":catalog_count,"admission_count":0,"upstream_attempt_count":0,"inference_invocation_count":0,"cleanup_complete":cleanup_receipt.get("complete") is True,"cleanup_receipt":dict(cleanup_receipt)};validate_outcome(value);return value
def _cross_bind(grant:Mapping[str,Any],process_receipt:Mapping[str,Any],gateway_receipt:Mapping[str,Any])->None:
    identity=grant["identity"]
    expected_process={"provider_process_start_identity":identity["provider_process_start_identity"],"engine_identity":identity["engine_identity"],"operation_id":identity["operation_id"],"held":True}
    if dict(process_receipt)!=expected_process:raise ContractError("R6_PROCESS_IDENTITY_MISMATCH")
    for key in ("request_fingerprint","request_local_gateway_id","request_local_gateway_fingerprint","engine_identity","provider_process_start_identity","operation_id"):
        expected=process_receipt[key] if key=="provider_process_start_identity" else identity[key]
        if gateway_receipt.get(key)!=expected:raise ContractError("R6_GATEWAY_IDENTITY_MISMATCH")
def run(grant:Mapping[str,Any],authorization:Any,now:Any,root:Path,request:bytes,process:Any,gateway_factory:Any)->Dict[str,Any]:
    lease=None;process_started=False;operation_key="";error=None;raw=None;translated=None;process_receipt=None;gateway_receipt=None
    try:
        if type(authorization) is not LiveAuthorization:raise ContractError("R6_LIVE_AUTHORIZATION_REQUIRED")
        lease=prepare(grant,authorization,now,root);operation_key=lease.operation_key;process_receipt=process.start(grant["identity"]);process_started=True
        _cross_bind(grant,process_receipt,{"request_fingerprint":grant["identity"]["request_fingerprint"],"request_local_gateway_id":grant["identity"]["request_local_gateway_id"],"request_local_gateway_fingerprint":grant["identity"]["request_local_gateway_fingerprint"],"engine_identity":grant["identity"]["engine_identity"],"provider_process_start_identity":process_receipt.get("provider_process_start_identity"),"operation_id":grant["identity"]["operation_id"]});gateway=gateway_factory(lease.store);gateway_receipt=gateway.admit(request,grant["identity"],operation_key,process_receipt);_cross_bind(grant,process_receipt,gateway_receipt);raw=process.invoke(request);translated=translate(raw)
    except Exception as e:error=e if isinstance(e,ContractError) else ContractError("R6_BOUNDARY_EXCEPTION")
    admitted=bool(lease is not None and operation_key and lease.store.is_admitted(operation_key))
    clean=cleanup(process,admitted)
    if lease is not None:lease.close()
    if not admitted:
        return _stop(str(error or "R6_DEFINITELY_NOT_SUBMITTED"),clean,1 if lease is not None else 0)
    if error is None and translated is not None and translated["terminal"]=="PASS" and clean["complete"]:
        value={"schema_version":"codex-live-evidence-r6-live-evidence-v1","terminal_outcome":"PASS","reason_code":"R6_PASS","countable_observation":False,"catalog_preflight_count":1,"admission_count":1,"upstream_attempt_count":1,"inference_invocation_count":1,"cleanup_complete":True,"process_receipt":process_receipt,"gateway_receipt":gateway_receipt,"translator_receipt":translated,"cleanup_receipt":clean};validate_outcome(value);return value
    value={"schema_version":"codex-live-evidence-r6-live-evidence-v1","terminal_outcome":"UNKNOWN","reason_code":"R6_CLEANUP_UNKNOWN" if not clean["complete"] else str(error or "R6_POST_ADMISSION_UNKNOWN"),"countable_observation":False,"catalog_preflight_count":1,"admission_count":1,"upstream_attempt_count":1,"inference_invocation_count":getattr(process,"invocations",0),"cleanup_complete":clean["complete"],"retry":False,"replay":False,"provider_status_calls":0,"reconciliation_dispatch":False,"durable_owner_private_evidence":True,"cleanup_receipt":clean};validate_outcome(value);path=root/("unknown-"+operation_key+".json");persist_unknown(path,value);value["unknown_evidence_path"]=str(path);return value
