"""Total post-admission finalizer with truthful durable/NON_DURABLE UNKNOWN state."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any,Dict,Mapping,Optional
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.contracts import DriverResult,canonical_bytes,sha256_bytes
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.publication import AtomicPublisher
FAULTS=frozenset((None,'revoke_failure','unlink_failure','dirfsync_failure','fence_write_failure','fence_dirfsync_failure','surviving_marker'))
def finalize_unknown_v3(parent:Path,execution_id:str,result:DriverResult,publisher:AtomicPublisher,reason:str,fault:Optional[str]=None)->Mapping[str,Any]:
 state:Dict[str,Any]={'version':3,'kind':'R6_CODEX_TOTAL_UNKNOWN_FINALIZER','execution_id':execution_id,'reason':reason,'admissions':result.counters.get('admissions',0),'upstream_attempts':result.counters.get('upstream_attempts',0),'retry':False,'replay':False,'status_calls':0,'reconciliation':False,'authoritative_pass_claim':False,'revocation_required':False,'marker_removed':False,'revocation_dir_fsynced':False,'authoritative_marker_present':False,'fence_written':False,'fence_file_fsynced':False,'fence_parent_dir_fsynced':False,'durable':False,'state':'NON_DURABLE_UNKNOWN','error_code':None}
 try:
  if fault not in FAULTS:raise ValueError('FINALIZER_FAULT_INVALID')
  marker=None
  if result.publication and result.publication.get('authoritative_marker'):marker=parent/str(result.publication['authoritative_marker']);state['revocation_required']=True;state['authoritative_marker_present']=marker.exists()
  if marker is None:
   state['error_code']='AUTHORITATIVE_MARKER_RECEIPT_ABSENT';return state
  if fault in ('revoke_failure','unlink_failure','surviving_marker'):
   state['error_code']='MARKER_REVOCATION_FAILED';state['authoritative_marker_present']=marker.exists();return state
  try:rev=publisher.revoke_authority(result.publication);state['marker_removed']=rev.get('marker_removed') is True;state['revocation_dir_fsynced']=rev.get('dir_fsynced') is True
  except Exception:state['error_code']='MARKER_REVOCATION_EXCEPTION';state['authoritative_marker_present']=marker.exists();return state
  state['authoritative_marker_present']=marker.exists()
  if fault=='dirfsync_failure':state['revocation_dir_fsynced']=False;state['error_code']='MARKER_PARENT_DIR_FSYNC_FAILED';return state
  if not(state['marker_removed'] and state['revocation_dir_fsynced'] and not state['authoritative_marker_present']):state['error_code']='MARKER_REVOCATION_UNVERIFIED';return state
  if fault=='fence_write_failure':state['error_code']='UNKNOWN_FENCE_WRITE_FAILED';return state
  payload={k:v for k,v in state.items() if k not in ('fence_written','fence_file_fsynced','fence_parent_dir_fsynced','durable','state','error_code')};payload.update({'fence_written':True,'fence_file_fsynced':True,'fence_parent_dir_fsynced':fault!='fence_dirfsync_failure','durable':fault!='fence_dirfsync_failure','state':'DURABLE_UNKNOWN' if fault!='fence_dirfsync_failure' else 'NON_DURABLE_UNKNOWN','error_code':None if fault!='fence_dirfsync_failure' else 'UNKNOWN_FENCE_PARENT_DIR_FSYNC_FAILED'});raw=canonical_bytes(payload)+b'\n';path=parent/(execution_id+'-total-unknown-v3.json');fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
  try:os.write(fd,raw);os.fsync(fd)
  finally:os.close(fd)
  state.update(fence_written=True,fence_file_fsynced=True)
  if fault!='fence_dirfsync_failure':
   d=os.open(parent,os.O_RDONLY)
   try:os.fsync(d)
   finally:os.close(d)
   state.update(fence_parent_dir_fsynced=True,durable=True,state='DURABLE_UNKNOWN',error_code=None)
  else:state['error_code']='UNKNOWN_FENCE_PARENT_DIR_FSYNC_FAILED'
  state.update(path=path.name,bytes=len(raw),sha256=sha256_bytes(raw));return state
 except Exception:
  state['error_code']=state['error_code'] or 'TOTAL_FINALIZER_EXCEPTION';return state
__all__=['finalize_unknown_v3']
