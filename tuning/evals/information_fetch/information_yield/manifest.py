"""One-held-root no-follow loader and no-clobber result publication for EIY v3."""
from __future__ import annotations
from hashlib import sha256
import json,os,stat
from pathlib import Path
from typing import Any,Mapping
from .contracts import InformationYieldError,decode,safe_rel,need,canonical

class HeldWorkspace:
 def __init__(self,root:Path):
  root=Path(root)
  need(root.is_absolute(),"EIY_ROOT_ABSOLUTE_REQUIRED")
  self.root=root
  flags=os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0)
  try:self.fd=os.open(root,flags)
  except OSError as exc:raise InformationYieldError("EIY_ROOT_INVALID") from exc
  info=os.fstat(self.fd);need(stat.S_ISDIR(info.st_mode) and info.st_uid==os.getuid(),"EIY_ROOT_INVALID")
 def close(self):
  if self.fd is not None:os.close(self.fd);self.fd=None
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
 def _read(self,relative:str,max_bytes:int)->bytes:
  rel=safe_rel(relative);parts=Path(rel).parts;current=os.dup(self.fd)
  try:
   flags_dir=os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0)
   for part in parts[:-1]:
    nxt=os.open(part,flags_dir,dir_fd=current);info=os.fstat(nxt)
    need(stat.S_ISDIR(info.st_mode) and info.st_uid==os.getuid() and not(info.st_mode&0o022),"EIY_PATH_TYPE")
    os.close(current);current=nxt
   fd=os.open(parts[-1],os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0),dir_fd=current)
   try:
    before=os.fstat(fd);need(stat.S_ISREG(before.st_mode) and before.st_uid==os.getuid() and before.st_nlink==1 and not(before.st_mode&0o022) and 0<before.st_size<=max_bytes,"EIY_PATH_TYPE")
    chunks=[];remaining=max_bytes+1
    while remaining:
     chunk=os.read(fd,min(65536,remaining))
     if not chunk:break
     chunks.append(chunk);remaining-=len(chunk)
    after=os.fstat(fd);need((before.st_dev,before.st_ino,before.st_mode,before.st_uid,before.st_nlink,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_mode,after.st_uid,after.st_nlink,after.st_size,after.st_mtime_ns,after.st_ctime_ns),"EIY_PATH_CHANGED")
    data=b''.join(chunks);need(len(data)<=max_bytes,"EIY_ARTIFACT_SIZE");return data
   finally:os.close(fd)
  except InformationYieldError:raise
  except OSError as exc:raise InformationYieldError("EIY_PATH_UNAVAILABLE") from exc
  finally:os.close(current)
 def reopen_json(self,ref:Mapping[str,Any],max_bytes:int=2*1024*1024):
  need(isinstance(ref,Mapping) and set(ref)=={"path","sha256"},"EIY_REF_FIELDS")
  data=self._read(ref["path"],max_bytes);need(sha256(data).hexdigest()==ref["sha256"],"EIY_ARTIFACT_DRIFT")
  return decode(data,max_bytes,"EIY_ARTIFACT_JSON")
 def read_json(self,relative:str,max_bytes:int=256*1024):return decode(self._read(relative,max_bytes),max_bytes,"EIY_MANIFEST_JSON")
 def publish(self,relative:str,value:Mapping[str,Any],*,input_paths:set[str]):
  rel=safe_rel(relative);need(all(not _overlap(rel,p) and Path(rel).parts[0]!=Path(p).parts[0] for p in input_paths),"EIY_OUTPUT_OVERLAP")
  payload=canonical(value)+b'\n';parts=Path(rel).parts;current=os.dup(self.fd);temp=f'.{parts[-1]}.{os.getpid()}.tmp'
  def existing():
   try:fd=os.open(parts[-1],os.O_RDONLY|getattr(os,"O_NOFOLLOW",0),dir_fd=current)
   except FileNotFoundError:return False
   try:
    st=os.fstat(fd);need(stat.S_ISREG(st.st_mode) and st.st_uid==os.getuid() and st.st_nlink==1 and not(st.st_mode&0o077),"EIY_OUTPUT_CONFLICT")
    raw=b''
    while len(raw)<=len(payload):
     chunk=os.read(fd,min(65536,len(payload)+1-len(raw)))
     if not chunk:break
     raw+=chunk
    need(raw==payload,"EIY_OUTPUT_CONFLICT");return True
   finally:os.close(fd)
  try:
   flags=os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0)
   for part in parts[:-1]:
    try:nxt=os.open(part,flags,dir_fd=current)
    except FileNotFoundError:
     os.mkdir(part,0o700,dir_fd=current);nxt=os.open(part,flags,dir_fd=current)
    st=os.fstat(nxt);need(st.st_uid==os.getuid() and not(st.st_mode&0o077),"EIY_OUTPUT_PATH")
    os.close(current);current=nxt
   if existing():return True
   fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600,dir_fd=current)
   try:
    view=memoryview(payload)
    while view:view=view[os.write(fd,view):]
    os.fsync(fd)
   finally:os.close(fd)
   try:os.link(temp,parts[-1],src_dir_fd=current,dst_dir_fd=current,follow_symlinks=False);os.unlink(temp,dir_fd=current);os.fsync(current);return False
   except FileExistsError:os.unlink(temp,dir_fd=current);need(existing(),"EIY_OUTPUT_CONFLICT");return True
  except InformationYieldError:raise
  except OSError as exc:raise InformationYieldError("EIY_OUTPUT_UNKNOWN") from exc
  finally:
   try:os.unlink(temp,dir_fd=current)
   except OSError:pass
   os.close(current)

def _overlap(a:str,b:str)->bool:
 pa,pb=Path(a).parts,Path(b).parts
 return pa==pb or pa[:len(pb)]==pb or pb[:len(pa)]==pa
