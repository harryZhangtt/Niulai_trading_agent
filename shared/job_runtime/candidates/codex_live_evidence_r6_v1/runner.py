"""Provider-free structural runner consuming only injected synthetic observations."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any,Dict,Mapping,Optional
from .adapter import SyntheticObservationAdapter
from .contracts import assert_same_identity,canonical_bytes,enforce_authority,identity_receipts,public_projection,strict_json_bytes,validate_identity,validate_live_evidence,validate_outcome
from .gateway import GatewayObserver
from .preflight import run_preflight
from .reconciliation import reconcile_unknown
from .translator import translate

def _resource()->Dict[str,Any]:return {"applicable":False,"evidence":"provider_free_no_resource_created"}
def _cleanup(identity:Mapping[str,str])->Dict[str,Any]:
 enforce_authority("process_custodian",{"cleanup"})
 return {"identity":dict(identity),"process_group":_resource(),"listener":_resource(),"socket_path":_resource(),"file_descriptors":_resource(),"temporary_paths":_resource(),"residual_children":0,"unlisted_effects":0}
def _stop(identity:Mapping[str,str],preflight:Mapping[str,Any])->Mapping[str,Any]:
 enforce_authority("Engine",{"status"},("NEW","PREFLIGHT_STOP"))
 result={"schema_version":"live-evidence-v1","identity":dict(identity),"identity_receipts":{k:dict(v) for k,v in identity_receipts(identity).items()},"terminal_outcome":"STOP","countable_observation":False,"submission":"DEFINITELY_NOT_SUBMITTED","upstream_attempt_count":0,"preflight":dict(preflight),"live_authority":False,"enabled":False,"provider_calls":0,"network_calls":0,"account_calls":0,"email_calls":0,"private_state_calls":0}
 validate_outcome(result);projection=public_projection(result);validate_live_evidence(strict_json_bytes(canonical_bytes(projection)));return projection
def run_synthetic(*,grant:Mapping[str,Any],synthetic_root:Path,now:datetime,request:bytes,adapter:SyntheticObservationAdapter,gateway:Optional[GatewayObserver]=None)->Mapping[str,Any]:
 identity=validate_identity(grant.get("identity") if type(grant) is dict else None);preflight=run_preflight(grant,synthetic_root=synthetic_root,now=now)
 if preflight["decision"]=="STOP":return _stop(identity,preflight)
 enforce_authority("Engine",{"status"},("NEW","ADMITTED"));observer=gateway or GatewayObserver();gateway_receipt=observer.admit(request,identity);capture=adapter.observe_admitted_synthetic(identity);translator=translate(capture);cleanup=_cleanup(identity);assert_same_identity(identity,preflight,gateway_receipt,translator,cleanup)
 common={"schema_version":"live-evidence-v1","identity":dict(identity),"identity_receipts":{k:dict(v) for k,v in identity_receipts(identity).items()},"countable_observation":False,"upstream_attempt_count":1,"preflight":dict(preflight),"gateway":gateway_receipt,"translator":translator,"cleanup":cleanup,"live_authority":False,"enabled":False,"provider_calls":0,"network_calls":0,"account_calls":0,"email_calls":0,"private_state_calls":0}
 if capture["scenario"]=="post_admission_ambiguity":
  enforce_authority("Engine",{"status"},("ADMITTED","UNKNOWN"));reconciliation=reconcile_unknown({"identity":dict(identity),"terminal_outcome":"UNKNOWN"});result=dict(common,terminal_outcome="UNKNOWN",admission_count=1,durable_after_reconstruction=True,provider_status_calls=0,reconciliation_dispatch=False,replay=False,retry=False,reconciliation=reconciliation)
 else:
  enforce_authority("Engine",{"status"},("ADMITTED","PASS"));result=dict(common,terminal_outcome="PASS",terminal_complete=True,cleanup_complete=True,terminal={"identity":dict(identity),**translator["sanitized_terminal"]})
 validate_outcome(result);projection=public_projection(result);validate_live_evidence(strict_json_bytes(canonical_bytes(projection)));return projection
