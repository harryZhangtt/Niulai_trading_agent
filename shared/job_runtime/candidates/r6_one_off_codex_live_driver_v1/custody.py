"""Owner-private fixture custody with durable destruction before PASS."""
from __future__ import annotations
import os,stat
from pathlib import Path
from typing import Dict
from .contracts import ContractError,require,sha256_bytes
class FixtureCustody:
 def __init__(self,parent:Path,execution_id:str)->None:
  require(parent.is_dir() and not parent.is_symlink(),'CUSTODY_PARENT_INVALID');self.parent=parent;self.root=parent/execution_id;self.closed=False;self.open_descriptors=0;self._files:Dict[str,Path]={}
  try:self.root.mkdir(mode=0o700)
  except FileExistsError as exc:raise ContractError('CUSTODY_NO_OVERWRITE') from exc
  os.chmod(self.root,0o700);require(stat.S_IMODE(os.stat(self.root,follow_symlinks=False).st_mode)==0o700 and not self.root.is_symlink(),'CUSTODY_ROOT_MODE');self._sync_dir(parent)
 @staticmethod
 def _sync_dir(path:Path)->None:
  fd=os.open(path,os.O_RDONLY)
  try:os.fsync(fd)
  finally:os.close(fd)
 def path_for(self,name:str)->Path:
  require(not self.closed and name and '/' not in name and '..' not in name,'CUSTODY_FILE_INVALID');p=self.root/name;require(not p.exists() and not p.is_symlink(),'CUSTODY_NO_OVERWRITE');return p
 def write_private(self,name:str,raw:bytes)->Dict[str,object]:
  p=self.path_for(name);fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600);self.open_descriptors+=1
  try:
   view=memoryview(raw)
   while view:
    n=os.write(fd,view);require(n>0,'CUSTODY_SHORT_WRITE');view=view[n:]
   os.fsync(fd)
  finally:os.close(fd);self.open_descriptors-=1
  self._sync_dir(self.root);self._files[name]=p;return {'name':name,'bytes':len(raw),'sha256':sha256_bytes(raw),'owner_private':True,'public':False}
 def describe_existing(self,name:str)->Dict[str,object]:
  p=self.root/name;raw=p.read_bytes();self._files[name]=p;require(stat.S_IMODE(os.stat(p,follow_symlinks=False).st_mode)==0o600,'CUSTODY_FILE_MODE');return {'name':name,'bytes':len(raw),'sha256':sha256_bytes(raw),'owner_private':True,'public':False}
 def close(self)->Dict[str,object]:
  self.closed=True;return {'kind':'custody','root_mode':'0700','file_mode':'0600','nofollow':True,'files_closed':self.open_descriptors==0,'open_descriptors':self.open_descriptors,'file_count':len(self._files),'root_exists':self.root.is_dir()}
 def destroy(self,retain_fault:bool=False)->Dict[str,object]:
  self.closed=True;removed=[];retained=[];dir_fsynced=False
  if not retain_fault:
   for p in sorted(self.root.iterdir() if self.root.exists() else []):
    if p.is_file() and not p.is_symlink():p.unlink();removed.append(p.name);self._sync_dir(self.root)
    else:retained.append(p.name)
   if self.root.exists() and not any(self.root.iterdir()):self.root.rmdir();self._sync_dir(self.parent);dir_fsynced=True
  if self.root.exists():retained.extend(p.name for p in self.root.iterdir() if p.name not in retained)
  return {'kind':'custody_cleanup','removed':sorted(set(removed)),'retained':sorted(set(retained)),'root_removed':not self.root.exists(),'parent_dir_fsynced':dir_fsynced,'authoritative_pass_safe':not self.root.exists() and dir_fsynced,'open_descriptors':self.open_descriptors}
