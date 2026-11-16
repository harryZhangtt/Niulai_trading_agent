"""Non-authoritative staging and sole commit-last publication for v5."""
from __future__ import annotations
from typing import Any,Mapping,Optional
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.contracts import canonical_bytes
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.publication import validate_public
from .custody_v5 import ExecutionCustodyV5
class PublicationV5Error(RuntimeError):pass
def capture_raw_v5(custody:ExecutionCustodyV5,raw:bytes,fault:Optional[str]=None)->Mapping[str,Any]:
 result=custody.stage_bytes('evidence','provider-terminal.raw',raw,fault)
 if not result['ok']:raise PublicationV5Error(result['error'])
 return result['ref']
def stage_sanitized_v5(custody:ExecutionCustodyV5,value:Mapping[str,Any],fault:Optional[str]=None)->Mapping[str,Any]:
 validate_public(dict(value));raw=canonical_bytes(dict(value))+b'\n';result=custody.stage_bytes('staging','sanitized-provider-artifact.json',raw,fault)
 if not result['ok']:raise PublicationV5Error(result['error'])
 return result['ref']
def stage_json_v5(custody:ExecutionCustodyV5,name:str,value:Mapping[str,Any],fault:Optional[str]=None)->Mapping[str,Any]:
 raw=canonical_bytes(dict(value))+b'\n';result=custody.stage_bytes('staging',name,raw,fault)
 if not result['ok']:raise PublicationV5Error(result['error'])
 return result['ref']
def commit_last_v5(custody:ExecutionCustodyV5,outcome:str,payload_ref:Mapping[str,Any],p0_ref:Mapping[str,Any],seal_ref:Mapping[str,Any],pending_ref:Optional[Mapping[str,Any]]=None,fault:Optional[str]=None)->Mapping[str,Any]:
 refs=[payload_ref,p0_ref,seal_ref]+([pending_ref] if pending_ref else [])
 if not all(custody.verify_ref(x) for x in refs):raise PublicationV5Error('V5_COMMIT_REF_INVALID')
 body={'version':5,'kind':'R6_CODEX_AUTHORITATIVE_COMMIT','outcome':outcome,'execution_id':custody.execution_id,'payload_ref':dict(payload_ref),'p0_ref':dict(p0_ref),'seal_ref':dict(seal_ref),'pending_unknown_ref':dict(pending_ref) if pending_ref else None,'complete_before_commit':True};result=custody.stage_bytes('publication',custody.execution_id+'.commit',canonical_bytes(body)+b'\n',fault)
 if not result['ok']:raise PublicationV5Error(result['error'])
 return result['ref']
__all__=['PublicationV5Error','capture_raw_v5','commit_last_v5','stage_json_v5','stage_sanitized_v5']
