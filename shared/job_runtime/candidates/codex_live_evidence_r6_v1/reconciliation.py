"""Atomic synthetic UNKNOWN custody and permanent no-replay reconciliation."""
from __future__ import annotations
import os,stat
from pathlib import Path
from typing import Any,Dict,Mapping
from .contracts import R6ContractError,assert_same_identity,canonical_bytes,strict_json_bytes,validate_identity

def reconcile_unknown(evidence:Mapping[str,Any])->Dict[str,Any]:
 if type(evidence) is not dict or evidence.get("terminal_outcome")!="UNKNOWN":raise R6ContractError("R6_RECONCILIATION_INPUT_INVALID")
 identity=validate_identity(evidence.get("identity"))
 return {"schema_version":"reconciliation-receipt-v1","identity":dict(identity),"outcome":"UNKNOWN_UNRESOLVED","artifact_only":True,"dispatch_count":0,"provider_status_calls":0,"replay":False,"retry":False,"original_evidence_mutated":False,"countable_observation":False}
def reconstruct_unknown(data:bytes)->Dict[str,Any]:
 value=strict_json_bytes(data)
 if type(value) is not dict or value.get("terminal_outcome")!="UNKNOWN" or value.get("replay") is not False or value.get("durable_after_reconstruction") is not True:raise R6ContractError("R6_RECONSTRUCTION_INVALID")
 identity=validate_identity(value.get("identity"));receipt=value.get("reconciliation");assert_same_identity(identity,receipt)
 if receipt.get("dispatch_count")!=0 or receipt.get("provider_status_calls")!=0 or receipt.get("replay") is not False:raise R6ContractError("R6_RECONSTRUCTION_REPLAY_FENCE_INVALID")
 return value
def _parent(path:Path,root:Path):
 root=root.resolve(strict=True);path=path.parent.resolve(strict=True)/path.name
 try:relative=path.relative_to(root)
 except ValueError:raise R6ContractError("R6_UNKNOWN_PATH_INVALID") from None
 if len(relative.parts)!=1:raise R6ContractError("R6_UNKNOWN_PATH_INVALID")
 flags=os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
 try:return os.open(str(root),flags),relative.name
 except OSError:raise R6ContractError("R6_UNKNOWN_PATH_INVALID") from None
def persist_unknown(path:Path,evidence:Mapping[str,Any],*,synthetic_root:Path)->Dict[str,Any]:
 data=canonical_bytes(evidence);reconstruct_unknown(data);parent,name=_parent(path,synthetic_root);tmp="."+name+".tmp";fd=-1
 try:
  fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0),0o600,dir_fd=parent)
  offset=0
  while offset<len(data):offset+=os.write(fd,data[offset:])
  os.fsync(fd);os.close(fd);fd=-1
  os.rename(tmp,name,src_dir_fd=parent,dst_dir_fd=parent);os.fsync(parent)
 except OSError:
  try:os.unlink(tmp,dir_fd=parent)
  except OSError:pass
  raise R6ContractError("R6_UNKNOWN_ATOMIC_PERSIST_FAILED") from None
 finally:
  if fd>=0:os.close(fd)
  os.close(parent)
 return {"path":str(path),"bytes":len(data),"sha256":__import__('hashlib').sha256(data).hexdigest(),"atomic":True,"fsync_file":True,"fsync_directory":True}
def load_unknown(path:Path,*,synthetic_root:Path)->Dict[str,Any]:
 parent,name=_parent(path,synthetic_root);fd=-1
 try:
  fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0),dir_fd=parent);info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600:raise R6ContractError("R6_UNKNOWN_CUSTODY_INVALID")
  chunks=[]
  while True:
   chunk=os.read(fd,65536)
   if not chunk:break
   chunks.append(chunk)
  return reconstruct_unknown(b"".join(chunks))
 except OSError:raise R6ContractError("R6_UNKNOWN_LOAD_FAILED") from None
 finally:
  if fd>=0:os.close(fd)
  os.close(parent)
class UnknownLifecycle:
 def __init__(self,path:Path,synthetic_root:Path)->None:self.path=path;self.synthetic_root=synthetic_root;self.dispatch_count=0;self.replay_count=0
 def resume(self)->Dict[str,Any]:return load_unknown(self.path,synthetic_root=self.synthetic_root)
