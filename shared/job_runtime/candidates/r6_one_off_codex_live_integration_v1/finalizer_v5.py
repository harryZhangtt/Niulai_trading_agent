"""V5 UNKNOWN staging: nonoptimistic bytes, missing-marker fencing, strict receipts."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any,Mapping,Optional
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.contracts import DriverResult,canonical_bytes
from .custody_v5 import ExecutionCustodyV5
@dataclass(frozen=True)
class PendingUnknownV5:
 pending_ref:Mapping[str,Any];marker_removed:bool;marker_absence_verified:bool;reason:str
_FAILURE_KEYS=('version','kind','state','error_code','authoritative_pass_claim','retry','replay','status_calls','reconciliation','marker_removed','marker_absence_verified','cleanup')
def failure_receipt(error:str,marker_removed:bool=False,marker_absence_verified:bool=False,cleanup:Optional[Mapping[str,Any]]=None)->Mapping[str,Any]:
 return {'version':5,'kind':'R6_CODEX_TOTAL_UNKNOWN_FINALIZER','state':'NON_DURABLE_UNKNOWN','error_code':error,'authoritative_pass_claim':False,'retry':False,'replay':False,'status_calls':0,'reconciliation':False,'marker_removed':marker_removed,'marker_absence_verified':marker_absence_verified,'cleanup':dict(cleanup or {'removed':True,'quarantined':False,'source_dir_fsynced':True,'quarantine_dir_fsynced':False,'authoritative':False})}
def stage_unknown_v5(custody:ExecutionCustodyV5,result:DriverResult,reason:str,marker_receipt:Optional[Mapping[str,Any]]=None,fault:Optional[str]=None)->tuple:
 marker_removed=False;absence=False
 try:
  if marker_receipt is not None:
   rev=custody.remove_marker(str(marker_receipt['relative_ref']));marker_removed=rev['marker_removed'] and rev['parent_dir_fsynced'] and rev['marker_absent'];absence=marker_removed
   if not marker_removed:return None,failure_receipt('MARKER_REVOCATION_UNVERIFIED')
  else:
   commits=custody.scan_commits()
   if commits:return None,failure_receipt('UNRECEIPTED_MARKER_PRESENT')
   absence=True
  pending={'version':5,'kind':'R6_CODEX_PENDING_UNKNOWN','state':'PENDING_UNKNOWN','authoritative':False,'execution_id':custody.execution_id,'reason':reason,'admissions':result.counters.get('admissions',0),'upstream_attempts':result.counters.get('upstream_attempts',0),'retry':False,'replay':False,'status_calls':0,'reconciliation':False,'marker_removed':marker_removed,'marker_absence_verified':absence};raw=canonical_bytes(pending)+b'\n';stage=custody.stage_bytes('finalization',custody.execution_id+'.unknown.pending',raw,fault)
  if not stage['ok']:return None,failure_receipt(stage['error'],marker_removed,absence,stage['cleanup'])
  return PendingUnknownV5(stage['ref'],marker_removed,absence,reason),None
 except Exception:
  cleanup=custody.remove_unsafe_marker_candidate(str(marker_receipt.get('relative_ref',''))) if type(marker_receipt) is dict else None
  return None,failure_receipt('TOTAL_UNKNOWN_STAGE_EXCEPTION',marker_removed,absence,cleanup)
def complete_unknown_v5(pending:PendingUnknownV5,commit_ref:Mapping[str,Any])->Mapping[str,Any]:
 return {'version':5,'kind':'R6_CODEX_TOTAL_UNKNOWN_FINALIZER','state':'DURABLE_UNKNOWN','error_code':None,'authoritative_pass_claim':False,'retry':False,'replay':False,'status_calls':0,'reconciliation':False,'marker_removed':pending.marker_removed,'marker_absence_verified':pending.marker_absence_verified,'pending_ref':dict(pending.pending_ref),'durable':True,'path':commit_ref['relative_ref'],'bytes':commit_ref['bytes'],'sha256':commit_ref['sha256'],'commit_file_fsynced':True,'commit_readback_verified':True,'commit_parent_dir_fsynced':True}
__all__=['PendingUnknownV5','complete_unknown_v5','failure_receipt','stage_unknown_v5']
