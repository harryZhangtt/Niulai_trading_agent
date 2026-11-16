"""Validated non-authoritative staging and sole commit-last publication for v6."""
from __future__ import annotations
from typing import Any,Mapping,Optional
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.contracts import canonical_bytes
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.publication import validate_public
from .custody_v5 import ExecutionCustodyV5
class PublicationV6Error(RuntimeError):pass
def _stage(custody:ExecutionCustodyV5,label:str,name:str,raw:bytes,fault:Optional[str]=None)->Mapping[str,Any]:
 result=custody.stage_bytes(label,name,raw,fault)
 if not result['ok']:raise PublicationV6Error(result['error'])
 return result['ref']
def capture_raw_v6(custody:ExecutionCustodyV5,raw:bytes,fault:Optional[str]=None)->Mapping[str,Any]:return _stage(custody,'evidence','provider-terminal.raw',raw,fault)
def stage_sanitized_v6(custody:ExecutionCustodyV5,value:Mapping[str,Any],fault:Optional[str]=None)->Mapping[str,Any]:
 validate_public(dict(value));return _stage(custody,'staging','sanitized-provider-artifact.json',canonical_bytes(dict(value)),fault)
def stage_research_v6(custody:ExecutionCustodyV5,name:str,value:Mapping[str,Any],fault:Optional[str]=None)->Mapping[str,Any]:return _stage(custody,'staging',name,canonical_bytes(dict(value)),fault)
def stage_json_v6(custody:ExecutionCustodyV5,name:str,value:Mapping[str,Any],fault:Optional[str]=None)->Mapping[str,Any]:return _stage(custody,'staging',name,canonical_bytes(dict(value))+b'\n',fault)
def commit_last_v6(custody:ExecutionCustodyV5,outcome:str,payload_ref:Mapping[str,Any],p0_ref:Mapping[str,Any],seal_ref:Mapping[str,Any],pending_ref:Optional[Mapping[str,Any]]=None,fault:Optional[str]=None)->Mapping[str,Any]:
 refs=[payload_ref,p0_ref,seal_ref]+([pending_ref] if pending_ref else [])
 if not all(custody.verify_ref(x) for x in refs):raise PublicationV6Error('V6_COMMIT_REF_INVALID')
 body={'version':6,'kind':'R6_CODEX_AUTHORITATIVE_COMMIT','outcome':outcome,'execution_id':custody.execution_id,'payload_ref':dict(payload_ref),'p0_ref':dict(p0_ref),'seal_ref':dict(seal_ref),'pending_unknown_ref':dict(pending_ref) if pending_ref else None,'complete_before_commit':True};return _stage(custody,'publication',custody.execution_id+'.commit',canonical_bytes(body)+b'\n',fault)
__all__=['PublicationV6Error','capture_raw_v6','commit_last_v6','stage_json_v6','stage_research_v6','stage_sanitized_v6']
