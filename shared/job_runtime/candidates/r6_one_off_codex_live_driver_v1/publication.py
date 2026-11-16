"""Two-object publication: payload is non-authoritative until one durable commit marker exists."""
from __future__ import annotations
import os,re
from pathlib import Path
from typing import Any,Callable,Dict,Mapping,Optional,Protocol
from .contracts import ContractError,canonical_bytes,require,sha256_bytes
_SECRET=re.compile(r'bearer\s+|authorization|cookie|set-cookie|api[_-]?key|token|secret',re.I)
PUBLIC_KEYS=frozenset(('version','outcome','code','countable_observation','binding','engine','counters','receipt_digests','cleanup','unknown_fence','effect_checks'))
def validate_public(value:Any)->Mapping[str,Any]:
 require(type(value) is dict and set(value)==PUBLIC_KEYS,'PUBLIC_SHAPE');require(value['version']=='stage-b-execution-v3' and value['outcome'] in ('PASS','STOP','UNKNOWN') and value['countable_observation'] is False,'PUBLIC_CONSTANT');raw=canonical_bytes(value);require(_SECRET.search(raw.decode('ascii')) is None,'PUBLIC_SECRET');f=value['unknown_fence'];require(type(f) is dict and set(f)=={'durable','retry','replay','status_calls','reconciliation'} and f['retry'] is False and f['replay'] is False and f['status_calls']==0 and f['reconciliation'] is False,'UNKNOWN_FENCE');require(value['outcome']=='UNKNOWN' or f['durable'] is False,'UNKNOWN_DURABILITY_CONFLICT');return value
class PublicationError(ContractError):
 def __init__(self,code:str,commit_state:str='NO_COMMIT',stage_clean:bool=True,cleanup_dir_fsynced:bool=False):super().__init__(code);self.commit_state=commit_state;self.stage_clean=stage_clean;self.cleanup_dir_fsynced=cleanup_dir_fsynced
class Publisher(Protocol):
 def publish(self,name:str,value:Mapping[str,Any],authorize_marker:Optional[Callable[[],bool]]=None)->Mapping[str,Any]:...
class AtomicPublisher:
 def __init__(self,root:Path,fault:Optional[str]=None)->None:self.root=root;self.fault=fault;self._fault_used=False;self.failure_history=[]
 def _trip(self,name:str)->bool:
  if self.fault==name and not self._fault_used:self._fault_used=True;return True
  return False
 def _sync_dir(self)->None:
  d=os.open(self.root,os.O_RDONLY)
  try:os.fsync(d)
  finally:os.close(d)
 def _unlink_sync(self,path:Path)->bool:
  try:path.unlink()
  except FileNotFoundError:pass
  self._sync_dir();return not path.exists()
 def recover_stages(self)->Dict[str,Any]:
  removed=[]
  for p in sorted(self.root.glob('.*.stage-*')):
   if p.is_file() and not p.is_symlink():p.unlink();removed.append(p.name);self._sync_dir()
  return {'removed':removed,'dir_fsynced':True,'remaining':sorted(p.name for p in self.root.glob('.*.stage-*'))}
 def _write_stage(self,path:Path,raw:bytes,prefix:str)->None:
  fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
  try:
   view=memoryview(raw)
   while view:
    short=self._trip('short_write') if prefix=='payload' else False;n=os.write(fd,view[:max(1,len(view)//2)] if short else view)
    if short or n<=0:raise PublicationError('PUBLICATION_SHORT_WRITE')
    view=view[n:]
   if self._trip('file_fsync') and prefix=='payload':raise OSError('file fsync')
   os.fsync(fd)
  finally:os.close(fd)
 def revoke_authority(self,receipt:Mapping[str,Any])->Dict[str,Any]:
  marker=self.root/str(receipt['authoritative_marker']);removed=self._unlink_sync(marker);return {'marker_removed':removed,'dir_fsynced':True,'payload_authoritative':False}
 def publish(self,name:str,value:Mapping[str,Any],authorize_marker:Optional[Callable[[],bool]]=None)->Dict[str,Any]:
  validate_public(value);require(self.root.is_dir() and not self.root.is_symlink() and '/' not in name,'PUBLICATION_ROOT');recovery=self.recover_stages();raw=canonical_bytes(value)+b'\n';payload=self.root/(name+'.payload');marker=self.root/(name+'.commit');pstage=self.root/('.'+name+'.stage-payload');mstage=self.root/('.'+name+'.stage-marker');require(not payload.exists() and not marker.exists(),'PUBLICATION_NO_OVERWRITE');state='NO_COMMIT'
  if self._trip('destination_race'):payload.write_bytes(b'racer');self._sync_dir()
  try:
   self._write_stage(pstage,raw,'payload');state='PAYLOAD_STAGED'
   if self._trip('link'):raise OSError('payload link')
   os.link(pstage,payload,follow_symlinks=False);state='PAYLOAD_LINKED';self._unlink_sync(pstage)
   if self._trip('dir_fsync'):raise OSError('payload dir fsync')
   self._sync_dir();state='PAYLOAD_DURABLE_NONAUTHORITATIVE'
   if self._trip('rename'):raise OSError('legacy rename boundary')
   if authorize_marker is not None and not authorize_marker():raise PublicationError('PUBLICATION_MARKER_DENIED',state)
   marker_value={'version':'authoritative-commit-marker-v1','payload':payload.name,'payload_sha256':sha256_bytes(raw),'outcome':value['outcome']};mraw=canonical_bytes(marker_value)+b'\n';self._write_stage(mstage,mraw,'marker');state='MARKER_STAGED';os.link(mstage,marker,follow_symlinks=False);state='MARKER_LINKED';self._unlink_sync(mstage)
   if self._trip('marker_dir_fsync'):raise OSError('marker dir fsync')
   self._sync_dir();state='AUTHORITATIVE_MARKER_DURABLE'
  except Exception as exc:
   clean1=self._unlink_sync(pstage);clean2=self._unlink_sync(mstage)
   if marker.exists() and state!='AUTHORITATIVE_MARKER_DURABLE':self._unlink_sync(marker)
   error=exc if isinstance(exc,PublicationError) else PublicationError('PUBLICATION_COMMIT_FAILED',state,clean1 and clean2,True);self.failure_history.append({'code':str(error),'commit_state':getattr(error,'commit_state',state),'stage_clean':clean1 and clean2,'cleanup_dir_fsynced':True,'authoritative_marker_exists':marker.exists()});raise error
  return {'atomic':True,'primitive':'link_no_replace_two_object','no_overwrite':True,'payload':payload.name,'payload_sha256':sha256_bytes(raw),'authoritative_marker':marker.name,'authoritative_marker_sha256':sha256_bytes(marker.read_bytes()),'commit_state':state,'file_fsync':True,'dir_fsync':True,'stage_clean':not pstage.exists() and not mstage.exists(),'recovery':recovery,'bytes':len(raw),'schema':'stage-b-execution-v3','raw_included':False}
