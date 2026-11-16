"""Owner-rooted immutable research artifacts and no-follow reference verification."""
from __future__ import annotations
import hashlib, os, stat
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from shared.job_runtime.candidates.r6_one_off_evidence_v1.custody import atomic_private_write
from .contracts import ContractError, canonical_bytes, require, validate_owner_ref
_DIR=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
_FILE=os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC
class OwnerArtifactError(ContractError):pass
def _need(ok:bool,code:str)->None:
 if not ok:raise OwnerArtifactError(code)
def _root(path:Path)->int:
 path=Path(path)
 try:before=path.lstat();fd=os.open(path,_DIR);after=os.fstat(fd)
 except OSError:raise OwnerArtifactError('OWNER_ROOT_OPEN_FAILED') from None
 if not stat.S_ISDIR(before.st_mode) or (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino) or after.st_uid!=os.getuid() or stat.S_IMODE(after.st_mode)!=0o700:
  os.close(fd);raise OwnerArtifactError('OWNER_ROOT_UNSAFE')
 return fd
def _parts(relative:str)->list:
 _need(type(relative)is str and relative and not relative.startswith('/') and '\\' not in relative and '\x00' not in relative,'OWNER_REF_PATH_INVALID')
 parts=relative.split('/');_need(all(p not in ('','.','..') and len(p)<=128 for p in parts),'OWNER_REF_PATH_INVALID');return parts
def read_owner_ref(root:Path,ref:Mapping[str,Any],expected:Optional[bytes]=None)->bytes:
 validate_owner_ref(dict(ref));parts=_parts(ref['relative_ref']);fd=_root(Path(root));opened=[]
 try:
  current=fd
  for part in parts[:-1]:
   try:nxt=os.open(part,_DIR,dir_fd=current)
   except OSError:raise OwnerArtifactError('OWNER_REF_DIRECTORY_UNSAFE') from None
   opened.append(nxt);current=nxt
  file_fd=-1
  try:
   file_fd=os.open(parts[-1],_FILE,dir_fd=current);meta=os.fstat(file_fd)
   _need(stat.S_ISREG(meta.st_mode) and meta.st_uid==os.getuid() and meta.st_uid==ref['owner_uid'] and ref['owner_uid']==os.getuid() and stat.S_IMODE(meta.st_mode)==0o600 and meta.st_nlink==1,'OWNER_REF_FILE_UNSAFE')
   chunks=[];total=0
   while True:
    chunk=os.read(file_fd,16384)
    if not chunk:break
    chunks.append(chunk);total+=len(chunk);_need(total<=1048576,'OWNER_REF_TOO_LARGE')
   raw=b''.join(chunks)
  except OSError:raise OwnerArtifactError('OWNER_REF_READ_FAILED') from None
  finally:
   if file_fd>=0:os.close(file_fd)
  digest=hashlib.sha256(raw).hexdigest();_need(len(raw)==ref['bytes'] and digest==ref['sha256'] and digest==ref['canonical_sha256'],'OWNER_REF_DIGEST_MISMATCH')
  if expected is not None:_need(raw==expected,'OWNER_REF_BODY_MISMATCH')
  return raw
 finally:
  for item in reversed(opened):os.close(item)
  os.close(fd)
def descriptor(relative:str,raw:bytes)->Dict[str,Any]:
 return {'relative_ref':relative,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'canonical_sha256':hashlib.sha256(raw).hexdigest(),'mode':'0600','owner_uid':os.getuid(),'regular':True,'nofollow':True,'owner_private':True}
class OwnerArtifactStore:
 def __init__(self,root:Path,key_digest:str)->None:
  self.root=Path(root);self.directory=self.root/(key_digest+'-research')
  self.root.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(self.root,0o700)
  self.directory.mkdir(mode=0o700);os.chmod(self.directory,0o700)
  fd=_root(self.root);os.close(fd);fd=_root(self.directory);os.close(fd)
 def write_json(self,name:str,value:Mapping[str,Any])->Dict[str,Any]:
  raw=canonical_bytes(dict(value));atomic_private_write(self.directory,name,raw);ref=descriptor(self.directory.name+'/'+name,raw);read_owner_ref(self.root,ref,raw);return ref
 def verify_raw(self,captured:Mapping[str,Any],raw:bytes)->Dict[str,Any]:
  relative=str(captured.get('name',''));ref=descriptor(relative,raw)
  _need(captured.get('bytes')==ref['bytes'] and captured.get('sha256')==ref['sha256'] and captured.get('owner_private') is True and captured.get('public') is False,'RAW_CAPTURE_DESCRIPTOR_MISMATCH')
  read_owner_ref(self.root,ref,raw);return ref
__all__=['OwnerArtifactError','OwnerArtifactStore','descriptor','read_owner_ref']

def validate_bundle_owner_artifacts(root:Path,bundle:Mapping[str,Any])->None:
 research=bundle['research_evidence']
 for name in ('sanitized_output','factual_evidence','source_inventory','citation_inventory'):
  entry=research[name];expected=canonical_bytes(entry['body']);read_owner_ref(root,entry['ref'],expected)
 receipt=bundle['raw_custody_receipt'];read_owner_ref(root,receipt['raw_ref'])
__all__.append('validate_bundle_owner_artifacts')
