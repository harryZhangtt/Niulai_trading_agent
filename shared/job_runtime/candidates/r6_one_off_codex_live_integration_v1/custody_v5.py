"""Exact-root owner-private custody with nofollow verified staging and cleanup."""
from __future__ import annotations
import hashlib,os,re,stat
from pathlib import Path
from typing import Any,Dict,Mapping,Optional
from .contracts import ContractError,require,sha256_bytes
_ID=re.compile(r'^[a-z0-9][a-z0-9._-]{7,127}$');_NAME=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$');_DIR=os.O_RDONLY|getattr(os,'O_DIRECTORY',0)|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_CLOEXEC',0);_READ=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_CLOEXEC',0);_WRITE=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_CLOEXEC',0)
FAULTS=frozenset((None,'partial_short_write','zero_write','write_exception','file_fsync_failure','readback_exception','readback_mismatch','dir_fsync_failure','partial_quarantine','cleanup_unlink_failure'))
class CustodyIOError(RuntimeError):pass
class ExecutionCustodyV5:
 def __init__(self,parent:Path,execution_id:str)->None:
  require(type(execution_id) is str and _ID.fullmatch(execution_id) is not None,'V5_EXECUTION_ID');parent=Path(parent);require(parent.is_absolute() and parent.is_dir() and not parent.is_symlink(),'V5_PARENT');st=parent.stat();require(st.st_uid==os.getuid() and stat.S_IMODE(st.st_mode)==0o700,'V5_PARENT_IDENTITY');self.parent=parent;self.execution_id=execution_id;self.root=parent/('v5-'+execution_id);self.parent_fd=os.open(parent,_DIR)
  try:os.mkdir(self.root.name,0o700,dir_fd=self.parent_fd)
  except FileExistsError as exc:raise ContractError('V5_CUSTODY_EXISTS') from exc
  self.root_fd=os.open(self.root.name,_DIR,dir_fd=self.parent_fd);rst=os.fstat(self.root_fd);require(stat.S_ISDIR(rst.st_mode) and rst.st_uid==os.getuid() and stat.S_IMODE(rst.st_mode)==0o700,'V5_ROOT_IDENTITY')
  for name in ('process','evidence','staging','publication','finalization','quarantine'):os.mkdir(name,0o700,dir_fd=self.root_fd)
  os.fsync(self.root_fd);os.fsync(self.parent_fd)
 def close(self)->None:
  for name in ('root_fd','parent_fd'):
   fd=getattr(self,name,-1)
   if fd>=0:
    try:os.close(fd)
    except OSError:pass
    setattr(self,name,-1)
 def __enter__(self):return self
 def __exit__(self,*a):self.close()
 def _dir(self,label:str)->int:
  require(label in ('process','evidence','staging','publication','finalization','quarantine'),'V5_DIR_LABEL');return os.open(label,_DIR,dir_fd=self.root_fd)
 @staticmethod
 def _name(name:str)->str:require(type(name) is str and _NAME.fullmatch(name) is not None,'V5_BASENAME');return name
 def _ref(self,label:str,name:str,raw:bytes)->Dict[str,Any]:return {'relative_ref':label+'/'+name,'bytes':len(raw),'sha256':sha256_bytes(raw),'mode':'0600','owner_uid':os.getuid(),'regular':True,'nofollow':True,'owner_private':True,'public':False}
 def _cleanup_failed(self,label:str,name:str,force_quarantine:bool=False)->Mapping[str,Any]:
  sfd=self._dir(label);removed=quarantined=source_fsynced=quarantine_fsynced=False;qname=None
  try:
   try:st=os.stat(name,dir_fd=sfd,follow_symlinks=False)
   except FileNotFoundError:return {'removed':True,'quarantined':False,'source_dir_fsynced':True,'quarantine_dir_fsynced':False,'authoritative':False}
   if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid():return {'removed':False,'quarantined':False,'source_dir_fsynced':False,'quarantine_dir_fsynced':False,'authoritative':False,'error':'UNSAFE_FAILED_ARTIFACT'}
   if not force_quarantine:
    try:os.unlink(name,dir_fd=sfd);os.fsync(sfd);removed=source_fsynced=True
    except OSError:force_quarantine=True
   if force_quarantine and not removed:
    qfd=self._dir('quarantine')
    try:qname='nonauthoritative-'+hashlib.sha256((label+'/'+name).encode()).hexdigest()[:24]+'.quarantine';os.rename(name,qname,src_dir_fd=sfd,dst_dir_fd=qfd);os.fsync(sfd);source_fsynced=True;os.fsync(qfd);quarantine_fsynced=True;quarantined=True
    except OSError:pass
    finally:os.close(qfd)
   return {'removed':removed,'quarantined':quarantined,'quarantine_name':qname,'source_dir_fsynced':source_fsynced,'quarantine_dir_fsynced':quarantine_fsynced,'authoritative':False}
  finally:os.close(sfd)
 def stage_bytes(self,label:str,name:str,raw:bytes,fault:Optional[str]=None)->Mapping[str,Any]:
  self._name(name);require(type(raw) is bytes and fault in FAULTS,'V5_STAGE_INPUT');dfd=self._dir(label);fd=-1;path_created=False
  try:
   fd=os.open(name,_WRITE,0o600,dir_fd=dfd);path_created=True;view=memoryview(raw);step=0
   while view:
    if fault=='write_exception':raise CustodyIOError('V5_WRITE_EXCEPTION')
    if fault in ('partial_short_write','partial_quarantine') and step>0:raise CustodyIOError('V5_PARTIAL_WRITE_EXCEPTION')
    if fault=='zero_write':n=0
    else:n=os.write(fd,view[:max(1,len(view)//2)] if fault in ('partial_short_write','partial_quarantine') and step==0 else view)
    if n<=0:raise CustodyIOError('V5_ZERO_PROGRESS')
    view=view[n:];step+=1
   if fault=='file_fsync_failure':raise CustodyIOError('V5_FILE_FSYNC')
   os.fsync(fd);os.close(fd);fd=-1
   if fault=='readback_exception':raise CustodyIOError('V5_READBACK_EXCEPTION')
   rfd=os.open(name,_READ,dir_fd=dfd)
   try:
    st=os.fstat(rfd);require(stat.S_ISREG(st.st_mode) and st.st_uid==os.getuid() and stat.S_IMODE(st.st_mode)==0o600,'V5_FILE_IDENTITY');chunks=[]
    while True:
     b=os.read(rfd,65536)
     if not b:break
     chunks.append(b)
   finally:os.close(rfd)
   observed=b''.join(chunks)
   if fault=='readback_mismatch':observed+=b'x'
   if observed!=raw:raise CustodyIOError('V5_READBACK_MISMATCH')
   if fault=='dir_fsync_failure':raise CustodyIOError('V5_DIR_FSYNC')
   os.fsync(dfd);return {'ok':True,'ref':self._ref(label,name,observed),'file_fsynced':True,'readback_verified':True,'parent_dir_fsynced':True,'authoritative':False}
  except Exception as exc:
   if fd>=0:
    try:os.close(fd)
    except OSError:pass
   cleanup=self._cleanup_failed(label,name,force_quarantine=fault in ('partial_quarantine','cleanup_unlink_failure')) if path_created else {'removed':True,'quarantined':False,'source_dir_fsynced':True,'quarantine_dir_fsynced':False,'authoritative':False}
   return {'ok':False,'error':str(exc) if isinstance(exc,(CustodyIOError,ContractError)) else 'V5_STAGE_EXCEPTION','cleanup':cleanup,'authoritative':False}
  finally:os.close(dfd)
 def verify_ref(self,ref:Mapping[str,Any])->bool:
  try:
   relative=Path(str(ref['relative_ref']));require(not relative.is_absolute() and len(relative.parts)==2 and '..' not in relative.parts,'V5_REF_PATH');label,name=relative.parts;self._name(name);dfd=self._dir(label);fd=os.open(name,_READ,dir_fd=dfd)
   try:
    st=os.fstat(fd);raw=b''
    while True:
     b=os.read(fd,65536)
     if not b:break
     raw+=b
   finally:os.close(fd);os.close(dfd)
   return stat.S_ISREG(st.st_mode) and st.st_uid==os.getuid() and stat.S_IMODE(st.st_mode)==0o600 and len(raw)==ref['bytes'] and sha256_bytes(raw)==ref['sha256']
  except Exception:return False
 def scan_commits(self)->tuple:
  dfd=self._dir('publication');names=[]
  try:
   for name in os.listdir(dfd):
    if name.endswith('.commit'):
     st=os.stat(name,dir_fd=dfd,follow_symlinks=False);require(stat.S_ISREG(st.st_mode) and st.st_uid==os.getuid(),'V5_COMMIT_UNSAFE');names.append(name)
   return tuple(sorted(names))
  finally:os.close(dfd)
 def remove_marker(self,relative_ref:str)->Mapping[str,Any]:
  p=Path(relative_ref);require(not p.is_absolute() and p.parts and len(p.parts)==2 and p.parts[0]=='publication' and '..' not in p.parts,'V5_MARKER_PATH');name=self._name(p.parts[1]);require(name.endswith('.commit'),'V5_MARKER_NAME');dfd=self._dir('publication')
  try:st=os.stat(name,dir_fd=dfd,follow_symlinks=False);require(stat.S_ISREG(st.st_mode) and st.st_uid==os.getuid(),'V5_MARKER_UNSAFE');os.unlink(name,dir_fd=dfd);os.fsync(dfd);return {'marker_removed':True,'parent_dir_fsynced':True,'marker_absent':name not in os.listdir(dfd)}
  finally:os.close(dfd)

def _cleanup_nonauthoritative(self:ExecutionCustodyV5)->Mapping[str,Any]:
 results=[]
 for label in ('evidence','staging','finalization'):
  dfd=self._dir(label)
  try:names=tuple(os.listdir(dfd))
  finally:os.close(dfd)
  for name in names:results.append(dict(label=label,name=name,**self._cleanup_failed(label,name)))
 return {'entries':results,'all_removed_or_quarantined':all(x.get('removed') or x.get('quarantined') for x in results),'all_parent_fsynced':all(x.get('source_dir_fsynced') and (not x.get('quarantined') or x.get('quarantine_dir_fsynced')) for x in results),'authoritative':False}
ExecutionCustodyV5.cleanup_nonauthoritative=_cleanup_nonauthoritative

def _remove_unsafe_marker_candidate(self:ExecutionCustodyV5,relative_ref:str)->Mapping[str,Any]:
 try:
  p=Path(relative_ref)
  if p.is_absolute() or len(p.parts)!=2 or p.parts[0]!='publication' or '..' in p.parts:return {'removed':False,'quarantined':False,'source_dir_fsynced':True,'quarantine_dir_fsynced':False,'authoritative':False}
  name=self._name(p.parts[1]);dfd=self._dir('publication')
  try:
   try:os.stat(name,dir_fd=dfd,follow_symlinks=False)
   except FileNotFoundError:return {'removed':True,'quarantined':False,'source_dir_fsynced':True,'quarantine_dir_fsynced':False,'authoritative':False}
   os.unlink(name,dir_fd=dfd);os.fsync(dfd);return {'removed':True,'quarantined':False,'source_dir_fsynced':True,'quarantine_dir_fsynced':False,'authoritative':False}
  finally:os.close(dfd)
 except Exception:return {'removed':False,'quarantined':False,'source_dir_fsynced':False,'quarantine_dir_fsynced':False,'authoritative':False}
ExecutionCustodyV5.remove_unsafe_marker_candidate=_remove_unsafe_marker_candidate
