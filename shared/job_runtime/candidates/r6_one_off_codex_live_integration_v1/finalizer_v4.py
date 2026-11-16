"""V4 total finalizer with checked write-all and exact fence readback."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any,Dict,Mapping,Optional
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.contracts import DriverResult,canonical_bytes,sha256_bytes
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.publication import AtomicPublisher
FAULTS=frozenset((None,'revoke_failure','unlink_failure','dirfsync_failure','fence_write_failure','fence_dirfsync_failure','surviving_marker','fence_partial_short_write','fence_zero_write','fence_write_exception','fence_file_fsync_failure','fence_readback_exception'))
class FenceIOError(RuntimeError):pass
def _write_all(fd:int,raw:bytes,fault:Optional[str])->int:
 view=memoryview(raw);total=0;step=0
 while view:
  if fault in ('fence_write_failure','fence_write_exception'):raise FenceIOError('UNKNOWN_FENCE_WRITE_EXCEPTION')
  if fault=='fence_partial_short_write' and step>0:raise FenceIOError('UNKNOWN_FENCE_PARTIAL_WRITE_EXCEPTION')
  if fault=='fence_zero_write':n=0
  else:
   chunk=view[:max(1,len(view)//2)] if fault=='fence_partial_short_write' and step==0 else view;n=os.write(fd,chunk)
  if n<=0:raise FenceIOError('UNKNOWN_FENCE_ZERO_PROGRESS')
  total+=n;view=view[n:];step+=1
 return total
def finalize_unknown_v4(parent:Path,execution_id:str,result:DriverResult,publisher:AtomicPublisher,reason:str,fault:Optional[str]=None)->Mapping[str,Any]:
 state:Dict[str,Any]={'version':4,'kind':'R6_CODEX_TOTAL_UNKNOWN_FINALIZER','execution_id':execution_id,'reason':reason,'admissions':result.counters.get('admissions',0),'upstream_attempts':result.counters.get('upstream_attempts',0),'retry':False,'replay':False,'status_calls':0,'reconciliation':False,'authoritative_pass_claim':False,'revocation_required':False,'marker_removed':False,'revocation_dir_fsynced':False,'authoritative_marker_present':False,'fence_written':False,'fence_file_fsynced':False,'fence_readback_verified':False,'fence_parent_dir_fsynced':False,'durable':False,'state':'NON_DURABLE_UNKNOWN','error_code':None}
 path=parent/(execution_id+'-total-unknown-v4.json')
 try:
  if fault not in FAULTS:raise FenceIOError('FINALIZER_FAULT_INVALID')
  marker=None
  if result.publication and result.publication.get('authoritative_marker'):marker=parent/str(result.publication['authoritative_marker']);state['revocation_required']=True;state['authoritative_marker_present']=marker.exists()
  if marker is None:state['error_code']='AUTHORITATIVE_MARKER_RECEIPT_ABSENT';return state
  if fault in ('revoke_failure','unlink_failure','surviving_marker'):state['error_code']='MARKER_REVOCATION_FAILED';state['authoritative_marker_present']=marker.exists();return state
  try:rev=publisher.revoke_authority(result.publication);state['marker_removed']=rev.get('marker_removed') is True;state['revocation_dir_fsynced']=rev.get('dir_fsynced') is True
  except Exception:state['error_code']='MARKER_REVOCATION_EXCEPTION';state['authoritative_marker_present']=marker.exists();return state
  state['authoritative_marker_present']=marker.exists()
  if fault=='dirfsync_failure':state['revocation_dir_fsynced']=False;state['error_code']='MARKER_PARENT_DIR_FSYNC_FAILED';return state
  if not(state['marker_removed'] and state['revocation_dir_fsynced'] and not state['authoritative_marker_present']):state['error_code']='MARKER_REVOCATION_UNVERIFIED';return state
  payload={k:v for k,v in state.items() if k not in ('fence_written','fence_file_fsynced','fence_readback_verified','fence_parent_dir_fsynced','durable','state','error_code')};payload.update({'fence_written':True,'fence_file_fsynced':True,'fence_readback_verified':True,'fence_parent_dir_fsynced':True,'durable':True,'state':'DURABLE_UNKNOWN','error_code':None});raw=canonical_bytes(payload)+b'\n';fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
  try:
   _write_all(fd,raw,fault);state['fence_written']=True
   if fault=='fence_file_fsync_failure':raise FenceIOError('UNKNOWN_FENCE_FILE_FSYNC_FAILED')
   os.fsync(fd);state['fence_file_fsynced']=True
  finally:os.close(fd)
  if fault=='fence_readback_exception':raise FenceIOError('UNKNOWN_FENCE_READBACK_EXCEPTION')
  actual=path.read_bytes()
  if actual!=raw:raise FenceIOError('UNKNOWN_FENCE_READBACK_MISMATCH')
  state['fence_readback_verified']=True
  if fault=='fence_dirfsync_failure':raise FenceIOError('UNKNOWN_FENCE_PARENT_DIR_FSYNC_FAILED')
  d=os.open(parent,os.O_RDONLY)
  try:os.fsync(d)
  finally:os.close(d)
  state.update(fence_parent_dir_fsynced=True,durable=True,state='DURABLE_UNKNOWN',error_code=None,path=path.name,bytes=len(actual),sha256=sha256_bytes(actual));return state
 except Exception as exc:
  state.update(durable=False,state='NON_DURABLE_UNKNOWN',error_code=str(exc) if isinstance(exc,FenceIOError) else 'TOTAL_FINALIZER_EXCEPTION')
  try:state['fence_written']=path.exists() and path.stat().st_size>0
  except OSError:state['fence_written']=False
  if path.exists():state['path']=path.name
  state.pop('bytes',None);state.pop('sha256',None);return state
__all__=['finalize_unknown_v4']
