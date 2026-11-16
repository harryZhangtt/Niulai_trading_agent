"""One-shot closed-source integration with descriptor-owned output custody."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib,os,stat
from pathlib import Path
from types import MappingProxyType
from typing import Any,Callable,Mapping,Optional,Tuple
from shared.job_runtime.candidates.r6_data_quality_fable_ab_v1.contracts import CELL_ORDER,MODEL_ID,canonical_bytes,sha256_json,strict_json_loads,validate_bundle,validate_result
from shared.job_runtime.candidates.r6_data_quality_fable_adapter_v1.adapter import adapt_engine_provider_results
from shared.job_runtime.candidates.r6_data_quality_fable_allocation_bridge_v1.bridge import ALLOCATION_SHA256,BridgeError,read_allocation_pair,validate_allocation
class IntegrationError(ValueError):
 def __init__(self,code:str,cleanup_receipt:Mapping[str,Any]|None=None):super().__init__(code);self.cleanup_receipt=cleanup_receipt
class OutputError(IntegrationError):pass
def require(ok:bool,code:str)->None:
 if not ok:raise IntegrationError(code)
INTEGRATION_SHA256="7ed93bfa249f77db21514c969137100e9468fcc9f166a7fb7d29f8474a5040c2";BRIDGE_CLOSURE_SHA256="743a329930ae2bd9c96ed8f2f2e63c3c41bda73bc7f4c9bf358a53b41de07293";ADAPTER_CLOSURE_SHA256="fa2ccbfa531e5880defe4eb816c22be024b9e9187f7d267d803752da5a6208a8";LOGICAL_DATABASE_ID="closed-engine/fable-ab/schedule.sqlite";EFFECTS={"provider":0,"service":0,"scheduler":0,"process":0,"network":0,"email":0,"publication":0};KEYS=("version","kind","activation","installed_jobs","installed_schedules","model","provider","allocation_sha256","bridge_closure_sha256","adapter_closure_sha256","logical_database_id","effects");MAX_FILE=64*1024*1024;DIR_FLAGS=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC;READ_FLAGS=os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC
@dataclass(frozen=True)
class IntegrationOutput:result:Mapping[str,Any];receipt:Mapping[str,Any]
def _freeze(v:Any)->Any:
 if type(v) is dict:return MappingProxyType({k:_freeze(x) for k,x in v.items()})
 if type(v) is list:return tuple(_freeze(x) for x in v)
 return v
def validate_integration(v:Any)->Mapping[str,Any]:
 require(type(v) is dict and set(v)==set(KEYS),"INTEGRATION_SHAPE");require(type(v["version"]) is int and v["version"]==1 and v["kind"]=="R6_FABLE_PROVIDER_FREE_ALLOCATION_INTEGRATION","INTEGRATION_VERSION");require(v["activation"] is False and v["installed_jobs"]==[] and v["installed_schedules"]==[],"INTEGRATION_ACTIVATION");require(v["model"]==MODEL_ID and v["provider"]=="claude_host","INTEGRATION_MODEL_PROVIDER");require(v["allocation_sha256"]==ALLOCATION_SHA256 and v["bridge_closure_sha256"]==BRIDGE_CLOSURE_SHA256 and v["adapter_closure_sha256"]==ADAPTER_CLOSURE_SHA256,"INTEGRATION_CLOSURE_BINDING");require(v["logical_database_id"]==LOGICAL_DATABASE_ID and v["effects"]==EFFECTS,"INTEGRATION_EFFECTS");require(hashlib.sha256(canonical_bytes(v)).hexdigest()==INTEGRATION_SHA256,"INTEGRATION_DIGEST");return v
def default_integrate(*a:Any,**k:Any)->Mapping[str,Any]:return MappingProxyType({"status":"DENIED_INACTIVE_INTEGRATION","activation":False,"countable":False,"effects":MappingProxyType(dict(EFFECTS))})
def _identity(m:os.stat_result)->tuple:return (m.st_dev,m.st_ino,m.st_uid,stat.S_IMODE(m.st_mode),m.st_nlink,m.st_size,m.st_mtime_ns,m.st_ctime_ns)
def _dir_identity(m:os.stat_result)->tuple:return (m.st_dev,m.st_ino,m.st_uid,stat.S_IMODE(m.st_mode))
def _walk_parent(path:Path)->tuple[int,os.stat_result]:
 require(path.is_absolute() and len(path.parts)>1,"INTEGRATION_OUTPUT_PATH");fd=os.open('/',DIR_FLAGS)
 try:
  for part in path.parts[1:-1]:n=os.open(part,DIR_FLAGS,dir_fd=fd);os.close(fd);fd=n
  meta=os.fstat(fd);require(stat.S_ISDIR(meta.st_mode) and meta.st_uid==os.getuid() and stat.S_IMODE(meta.st_mode)==0o700,"INTEGRATION_PARENT_UNSAFE");return fd,meta
 except BaseException:os.close(fd);raise
def _read_file(dirfd:int,name:str,code:str,hook:Optional[Callable[[str,int,str],None]]=None,stage:str="")->tuple[bytes,tuple,int]:
 fd=os.open(name,READ_FLAGS,dir_fd=dirfd)
 try:
  before=os.fstat(fd);named=os.stat(name,dir_fd=dirfd,follow_symlinks=False);admitted=_identity(before);require(admitted==_identity(named) and stat.S_ISREG(before.st_mode) and before.st_uid==os.getuid() and stat.S_IMODE(before.st_mode)==0o600 and before.st_nlink==1 and before.st_size<=MAX_FILE,code);parts=[];total=0
  while True:
   chunk=os.read(fd,65536)
   if not chunk:break
   parts.append(chunk);total+=len(chunk);require(total<=MAX_FILE,code)
  if hook:hook(stage,dirfd,name)
  require(_identity(os.fstat(fd))==admitted==_identity(os.stat(name,dir_fd=dirfd,follow_symlinks=False)),code);return b''.join(parts),admitted,fd
 except BaseException:
  os.close(fd);raise
def _capture_created(parentfd:int,name:str)->tuple:
 meta=os.stat(name,dir_fd=parentfd,follow_symlinks=False);require(stat.S_ISDIR(meta.st_mode) and meta.st_uid==os.getuid() and stat.S_IMODE(meta.st_mode)==0o700,"INTEGRATION_ROOT_UNSAFE");return _dir_identity(meta)
def _open_created_root(parentfd:int,name:str,created_identity:tuple)->int:
 fd=os.open(name,DIR_FLAGS,dir_fd=parentfd)
 try:require(_dir_identity(os.fstat(fd))==created_identity,"INTEGRATION_ROOT_SWAPPED");return fd
 except BaseException:os.close(fd);raise
def _cleanup_parent_created(parentfd:int,rootname:str,created_identity:tuple|None)->Mapping[str,Any]:
 errors=[]
 if created_identity is None:
  named=False
  try:
   os.stat(rootname,dir_fd=parentfd,follow_symlinks=False);named=True
  except FileNotFoundError:pass
  except OSError:errors.append("CLEANUP_CREATED_SCAN")
  errors.append("IDENTITY_UNAVAILABLE")
  return MappingProxyType({"status":"ERROR","errors":tuple(sorted(set(errors))),"residue":named,"residue_unknown":True,"named_entry_present":named,"cleanup_complete":False})
 for _ in range(2):
  try:
   for name in list(os.listdir(parentfd)):
    meta=os.stat(name,dir_fd=parentfd,follow_symlinks=False)
    if (meta.st_dev,meta.st_ino)==created_identity[:2]:
     try:os.rmdir(name,dir_fd=parentfd)
     except OSError:errors.append("CLEANUP_CREATED_RMDIR")
   os.fsync(parentfd)
  except OSError:errors.append("CLEANUP_CREATED_SCAN")
 residue=False
 try:residue=any((lambda m:(m.st_dev,m.st_ino)==created_identity[:2])(os.stat(n,dir_fd=parentfd,follow_symlinks=False)) for n in os.listdir(parentfd))
 except OSError:errors.append("CLEANUP_RESIDUE_CHECK");residue=True
 named=False
 try:os.stat(rootname,dir_fd=parentfd,follow_symlinks=False);named=True
 except FileNotFoundError:pass
 except OSError:errors.append("CLEANUP_CREATED_SCAN")
 complete=not errors and not residue
 return MappingProxyType({"status":"PASS" if complete else "ERROR","errors":tuple(sorted(set(errors))),"residue":residue,"residue_unknown":False,"named_entry_present":named,"cleanup_complete":complete})
def _cleanup(parentfd:int,rootfd:int,rootname:str,root_identity:tuple)->Mapping[str,Any]:
 errors=[]
 def attempt():
  try:
   for cell in list(os.listdir(rootfd)):
    try:
     cfd=os.open(cell,DIR_FLAGS,dir_fd=rootfd)
     try:
      for name in list(os.listdir(cfd)):
       try:
        entry=os.stat(name,dir_fd=cfd,follow_symlinks=False)
        if stat.S_ISDIR(entry.st_mode):
         xfd=os.open(name,DIR_FLAGS,dir_fd=cfd)
         try:
          for nested in list(os.listdir(xfd)):
           try:os.unlink(nested,dir_fd=xfd)
           except OSError:errors.append("CLEANUP_NESTED_UNLINK")
         finally:os.close(xfd)
         os.rmdir(name,dir_fd=cfd)
        else:os.unlink(name,dir_fd=cfd)
       except OSError:errors.append("CLEANUP_UNLINK")
      try:os.fsync(cfd)
      except OSError:errors.append("CLEANUP_CELL_FSYNC")
     finally:os.close(cfd)
     try:os.rmdir(cell,dir_fd=rootfd)
     except OSError:errors.append("CLEANUP_CELL_RMDIR")
    except OSError:
     try:os.unlink(cell,dir_fd=rootfd)
     except OSError:errors.append("CLEANUP_ROOT_ENTRY")
   try:os.fsync(rootfd)
   except OSError:errors.append("CLEANUP_ROOT_FSYNC")
  except OSError:errors.append("CLEANUP_LIST")
 for _ in range(2):attempt()
 fallback=_cleanup_parent_created(parentfd,rootname,root_identity);errors.extend(fallback["errors"]);residue=fallback["residue"]
 return MappingProxyType({"status":"PASS" if not errors and not residue else "ERROR","errors":tuple(sorted(set(errors))),"residue":residue,"residue_unknown":fallback["residue_unknown"],"named_entry_present":fallback["named_entry_present"],"cleanup_complete":not errors and not residue and fallback["cleanup_complete"]})
def _final_barrier(root:Path,parentfd:int,parent_meta:os.stat_result,rootfd:int,root_identity:tuple,cells:list[dict])->None:
 named_parent=os.lstat(root.parent);require(_dir_identity(named_parent)==_dir_identity(parent_meta) and not stat.S_ISLNK(named_parent.st_mode),"INTEGRATION_PARENT_SWAPPED");require(_dir_identity(os.fstat(rootfd))==root_identity==_dir_identity(os.stat(root.name,dir_fd=parentfd,follow_symlinks=False)),"INTEGRATION_ROOT_SWAPPED");require(tuple(sorted(os.listdir(rootfd)))==tuple(sorted(CELL_ORDER)),"INTEGRATION_FINAL_ROOT_LISTING")
 for state in cells:
  cfd=state["fd"];cell=state["name"];require(_dir_identity(os.fstat(cfd))==state["identity"]==_dir_identity(os.stat(cell,dir_fd=rootfd,follow_symlinks=False)),"INTEGRATION_FINAL_CELL_IDENTITY");require(tuple(sorted(os.listdir(cfd)))==(cell+".bundle.json",cell+".raw"),"INTEGRATION_FINAL_CELL_LISTING")
  for name,fd,identity in state["files"]:require(_identity(os.fstat(fd))==identity==_identity(os.stat(name,dir_fd=cfd,follow_symlinks=False)),"INTEGRATION_FINAL_FILE_IDENTITY")
def run_integration(integration:Mapping[str,Any],allocation:Mapping[str,Any],source_expectation:Mapping[str,Any],quiescence:Mapping[str,Any],database:Path,bundle_root:Path,*,_test_hook:Optional[Callable[[str,int,str],None]]=None)->IntegrationOutput:
 spec=dict(integration);validate_integration(spec);validate_allocation(dict(allocation));root=Path(bundle_root);parentfd=-1;rootfd=-1;created=False;created_identity=None;root_identity=();held_cells=[];held_files=[];cell_states=[]
 try:
  parentfd,parent_meta=_walk_parent(root);bridge=read_allocation_pair(Path(database),dict(allocation),dict(source_expectation),dict(quiescence));require(bridge.receipt["source_db_sha256"]==source_expectation["sha256"],"INTEGRATION_BRIDGE_RECEIPT")
  try:os.mkdir(root.name,0o700,dir_fd=parentfd);created=True
  except FileExistsError:raise IntegrationError("INTEGRATION_BUNDLE_ROOT_NOT_FRESH") from None
  created_identity=_capture_created(parentfd,root.name);rootfd=_open_created_root(parentfd,root.name,created_identity);root_identity=_dir_identity(os.fstat(rootfd));result=adapt_engine_provider_results(bridge.rows,bridge.expected_readback,root)
  if _test_hook:_test_hook("after_adapter",rootfd,root.name)
  validate_result(dict(result));require(result["denominator_count"]==2 and result["publication_attempts"]==0 and result["countable"] is False,"INTEGRATION_RESULT_FENCE");bundles=[]
  for i,cell in enumerate(CELL_ORDER):
   cfd=os.open(cell,DIR_FLAGS,dir_fd=rootfd);held_cells.append(cfd);cm=os.fstat(cfd);cn=os.stat(cell,dir_fd=rootfd,follow_symlinks=False);cell_identity=_dir_identity(cm);require(cell_identity==_dir_identity(cn) and cm.st_uid==os.getuid() and stat.S_IMODE(cm.st_mode)==0o700,"INTEGRATION_CELL_SWAPPED");require(tuple(sorted(os.listdir(cfd)))==(cell+".bundle.json",cell+".raw"),"INTEGRATION_BUNDLE_SET");bundle_raw,bundle_identity,bundlefd=_read_file(cfd,cell+".bundle.json","INTEGRATION_BUNDLE_UNSAFE",_test_hook,"during_bundle_read");held_files.append(bundlefd);raw,raw_identity,rawfd=_read_file(cfd,cell+".raw","INTEGRATION_RAW_UNSAFE",_test_hook,"during_raw_read");held_files.append(rawfd)
   try:bundle=strict_json_loads(bundle_raw.decode('ascii'),"INTEGRATION_BUNDLE_JSON")
   except UnicodeError:raise IntegrationError("INTEGRATION_BUNDLE_JSON") from None
   validate_bundle(bundle);require(canonical_bytes(bundle)==bundle_raw,"INTEGRATION_BUNDLE_NONCANONICAL");require(raw==bundle["raw_body_ascii"].encode('ascii') and hashlib.sha256(raw).hexdigest()==bundle["raw_sha256"]==bundle["cell"]["raw_ref"]["sha256"] and len(raw)==bundle["cell"]["raw_ref"]["bytes"],"INTEGRATION_RAW_BINDING");require(canonical_bytes(bundle["cell"])==canonical_bytes(result["cells"][i]),"INTEGRATION_BUNDLE_RESULT_MISMATCH");bundles.append({"cell_id":cell,"bundle_sha256":hashlib.sha256(bundle_raw).hexdigest(),"bundle_bytes":len(bundle_raw),"raw_sha256":hashlib.sha256(raw).hexdigest(),"raw_bytes":len(raw)});cell_states.append({"name":cell,"fd":cfd,"identity":cell_identity,"files":[(cell+".bundle.json",bundlefd,bundle_identity),(cell+".raw",rawfd,raw_identity)]})
  receipt={"version":1,"status":"PASS_INACTIVE_PROVIDER_FREE_INTEGRATION","activation":False,"countable":False,"publication_attempts":0,"denominator_count":2,"integration_sha256":INTEGRATION_SHA256,"allocation_sha256":ALLOCATION_SHA256,"bridge_closure_sha256":BRIDGE_CLOSURE_SHA256,"adapter_closure_sha256":ADAPTER_CLOSURE_SHA256,"logical_database_id":LOGICAL_DATABASE_ID,"source_db_sha256":bridge.receipt["source_db_sha256"],"source_db_bytes":bridge.receipt["source_db_bytes"],"source_db_identity":dict(bridge.receipt["source_db_identity"]),"quiescence":dict(bridge.receipt["quiescence"]),"bridge_readback_sha256":bridge.receipt["database_readback_sha256"],"snapshot_sha256":bridge.receipt["snapshot_sha256"],"result_sha256":sha256_json(result),"bundle_set_sha256":sha256_json(bundles),"bundles":bundles,"output_root_identity":{"st_dev":root_identity[0],"st_ino":root_identity[1]},"cleanup":{"status":"NOT_APPLICABLE","errors":[],"residue":False,"residue_unknown":False,"named_entry_present":True,"cleanup_complete":True},"effects":dict(EFFECTS)};output=IntegrationOutput(_freeze(dict(result)),_freeze(receipt))
  if _test_hook:_test_hook("before_final_barrier",rootfd,root.name)
  _final_barrier(root,parentfd,parent_meta,rootfd,root_identity,cell_states);return output
 except BaseException as exc:
  cleanup=MappingProxyType({"status":"NOT_CREATED","errors":(),"residue":False,"residue_unknown":False,"named_entry_present":False,"cleanup_complete":True})
  if created and parentfd>=0:
   cleanup=_cleanup(parentfd,rootfd,root.name,root_identity) if rootfd>=0 else _cleanup_parent_created(parentfd,root.name,created_identity)
  code=str(exc) if isinstance(exc,IntegrationError) else "INTEGRATION_FAILED";raise IntegrationError(code,cleanup) from exc
 finally:
  for fd in reversed(held_files+held_cells):
   try:os.close(fd)
   except OSError:pass
  if rootfd>=0:
   try:os.close(rootfd)
   except OSError:pass
  if parentfd>=0:
   try:os.close(parentfd)
   except OSError:pass
__all__=["ADAPTER_CLOSURE_SHA256","BRIDGE_CLOSURE_SHA256","INTEGRATION_SHA256","IntegrationError","IntegrationOutput","default_integrate","run_integration","validate_integration"]
