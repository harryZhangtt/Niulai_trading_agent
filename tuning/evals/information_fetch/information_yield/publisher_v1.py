"""No-clobber EIY v5 result/custody publisher with immutable index."""
from __future__ import annotations
import errno,fcntl,json,os,shutil,sqlite3,stat,tempfile,uuid
from hashlib import sha256
from pathlib import Path
import re
from typing import Any,Mapping,Optional,Union
from shared.research_sources.artifacts import ROOT
from shared.research_sources.information_yield_v5_contracts import ArtifactRefV5,canonical_v5,digest_v5
from tuning.evals.information_fetch.information_yield.evaluator_v5 import InformationYieldV5Error,private_unwrap_issued_v5
from tuning.evals.information_fetch.information_yield.policy_v5 import canonical_policy_ref_v5
_ID=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MAX_FILE_BYTES=8*1024*1024
_DIR_FLAGS=os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
_FILE_NOFOLLOW=getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
CANONICAL_INFORMATION_YIELD_V5_ROOT = ROOT / 'tuning/runtime/information-yield-v5'
class EiyPublisherV1Error(ValueError):pass
def _fail(code:str)->None:raise EiyPublisherV1Error(code)
def _bytes(value:Any)->bytes:return canonical_v5(value)+b"\n"
def _lexists(path:Path)->bool:return os.path.lexists(path)
def _ref(path:Path,raw:bytes)->dict[str,str]:
 try:relative=path.relative_to(ROOT.resolve(strict=True)).as_posix()
 except (OSError,ValueError):_fail("EIY_PUBLICATION_CONFLICT")
 return ArtifactRefV5(relative,sha256(raw).hexdigest()).to_mapping()
def _dir_stat_ok(value,*,private_exact:bool)->bool:
 mode=stat.S_IMODE(value.st_mode)
 return stat.S_ISDIR(value.st_mode) and not stat.S_ISLNK(value.st_mode) and value.st_uid==os.getuid() and not mode&0o022 and (not private_exact or mode==0o700)
def _file_stat_ok(value)->bool:
 return stat.S_ISREG(value.st_mode) and not stat.S_ISLNK(value.st_mode) and value.st_uid==os.getuid() and stat.S_IMODE(value.st_mode)==0o600 and value.st_nlink==1 and 0<=value.st_size<=_MAX_FILE_BYTES
def _same_identity(left,right)->bool:
 return (left.st_dev,left.st_ino,left.st_uid,stat.S_IMODE(left.st_mode),left.st_nlink,left.st_size)==(right.st_dev,right.st_ino,right.st_uid,stat.S_IMODE(right.st_mode),right.st_nlink,right.st_size)
def _validated_dir_fd(path:Path,*,private_exact:bool=False)->int:
 linked=os.lstat(path)
 if not _dir_stat_ok(linked,private_exact=private_exact):_fail("EIY_PUBLICATION_CONFLICT")
 fd=os.open(path,_DIR_FLAGS);opened=os.fstat(fd);named=os.lstat(path)
 if not _dir_stat_ok(opened,private_exact=private_exact) or not _same_identity(linked,opened) or not _same_identity(opened,named):os.close(fd);_fail("EIY_PUBLICATION_CONFLICT")
 return fd
def _validated_child_dir_fd(parent_fd:int,name:str,*,private_exact:bool=True)->int:
 if not isinstance(name,str) or not name or "/" in name or name in {".",".."}:_fail("EIY_PUBLICATION_CONFLICT")
 linked=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
 if not _dir_stat_ok(linked,private_exact=private_exact):_fail("EIY_PUBLICATION_CONFLICT")
 fd=os.open(name,_DIR_FLAGS,dir_fd=parent_fd);opened=os.fstat(fd);named=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
 if not _dir_stat_ok(opened,private_exact=private_exact) or not _same_identity(linked,opened) or not _same_identity(opened,named):os.close(fd);_fail("EIY_PUBLICATION_CONFLICT")
 return fd
def _create_or_validate_private_dir(path:Path)->Path:
 if _lexists(path):
  fd=_validated_dir_fd(path,private_exact=True);os.close(fd);return path
 parent_fd=_validated_dir_fd(path.parent,private_exact=True)
 try:
  try:os.mkdir(path.name,0o700,dir_fd=parent_fd)
  except FileExistsError:_fail("EIY_PUBLICATION_CONFLICT")
  os.fsync(parent_fd);child_fd=_validated_child_dir_fd(parent_fd,path.name,private_exact=True)
  try:os.fsync(child_fd)
  finally:os.close(child_fd)
 finally:os.close(parent_fd)
 return path
def _safe_root(root:Union[Path,str])->Path:
 raw=os.fspath(root)
 if (not isinstance(raw,str) or not raw or "\\" in raw or not os.path.isabs(raw) or "//" in raw or (raw!=os.sep and raw.endswith(os.sep)) or any(x in {".",".."} for x in raw.split(os.sep)) or raw!=os.path.normpath(raw)):_fail("EIY_PUBLICATION_CONFLICT")
 workspace=ROOT
 try:
  if workspace.resolve(strict=True)!=workspace:_fail("EIY_PUBLICATION_CONFLICT")
 except OSError:_fail("EIY_PUBLICATION_CONFLICT")
 path=Path(raw)
 if path==workspace or not path.is_relative_to(workspace):_fail("EIY_PUBLICATION_CONFLICT")
 current=workspace;parent_fd=_validated_dir_fd(workspace);missing=()
 try:
  parts=path.relative_to(workspace).parts
  for index,part in enumerate(parts):
   candidate=current/part
   try:child_fd=_validated_dir_fd(candidate,private_exact=index==len(parts)-1)
   except FileNotFoundError:missing=parts[index:];break
   os.close(parent_fd);parent_fd=child_fd;current=candidate
  for part in missing:
   try:os.mkdir(part,0o700,dir_fd=parent_fd)
   except FileExistsError:_fail("EIY_PUBLICATION_CONFLICT")
   os.fsync(parent_fd);child_fd=_validated_child_dir_fd(parent_fd,part,private_exact=True)
   os.close(parent_fd);parent_fd=child_fd;current=current/part
  if missing:os.fsync(parent_fd)
 finally:os.close(parent_fd)
 return path
def _read_private_at(parent_fd:int,name:str)->bytes:
 linked=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
 if not _file_stat_ok(linked):_fail("EIY_PUBLICATION_CONFLICT")
 fd=os.open(name,os.O_RDONLY|_FILE_NOFOLLOW,dir_fd=parent_fd)
 try:
  opened=os.fstat(fd)
  if not _file_stat_ok(opened) or not _same_identity(linked,opened):_fail("EIY_PUBLICATION_CONFLICT")
  chunks=[];total=0
  while True:
   chunk=os.read(fd,min(65536,_MAX_FILE_BYTES+1-total))
   if not chunk:break
   chunks.append(chunk);total+=len(chunk)
   if total>_MAX_FILE_BYTES:_fail("EIY_PUBLICATION_CONFLICT")
  after=os.fstat(fd);named=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
  if not _file_stat_ok(after) or not _same_identity(opened,after) or not _same_identity(after,named) or total!=after.st_size:_fail("EIY_PUBLICATION_CONFLICT")
  return b"".join(chunks)
 finally:os.close(fd)
def _read_private_file(path:Path)->bytes:
 parent_fd=_validated_dir_fd(path.parent,private_exact=True)
 try:return _read_private_at(parent_fd,path.name)
 finally:os.close(parent_fd)
def _write_fd(path:Path,raw:bytes)->None:
 if len(raw)>_MAX_FILE_BYTES:_fail("EIY_PUBLICATION_CONFLICT")
 parent_fd=_validated_dir_fd(path.parent,private_exact=True);fd=None
 try:
  fd=os.open(path.name,os.O_CREAT|os.O_EXCL|os.O_WRONLY|_FILE_NOFOLLOW,0o600,dir_fd=parent_fd);view=memoryview(raw)
  while view:
   written=os.write(fd,view)
   if written<=0:raise OSError(errno.EIO,"short write")
   view=view[written:]
  os.fsync(fd);opened=os.fstat(fd);named=os.stat(path.name,dir_fd=parent_fd,follow_symlinks=False)
  if not _file_stat_ok(opened) or not _same_identity(opened,named) or opened.st_size!=len(raw):_fail("EIY_PUBLICATION_CONFLICT")
  os.fsync(parent_fd)
 finally:
  if fd is not None:os.close(fd)
  os.close(parent_fd)
def _fsync(path:Path)->None:
 fd=_validated_dir_fd(path,private_exact=True)
 try:os.fsync(fd)
 finally:os.close(fd)
def _matches(path:Path,expected:Mapping[str,bytes])->bool:
 fd=_validated_dir_fd(path,private_exact=True)
 try:
  if set(os.listdir(fd))!=set(expected):return False
  return all(_read_private_at(fd,name)==raw for name,raw in expected.items())
 finally:os.close(fd)
def _open_private_lock(lock_dir:Path,name:str)->int:
 parent_fd=_validated_dir_fd(lock_dir,private_exact=True);fd=None
 try:
  try:linked=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
  except FileNotFoundError:
   try:fd=os.open(name,os.O_CREAT|os.O_EXCL|os.O_RDWR|_FILE_NOFOLLOW,0o600,dir_fd=parent_fd)
   except FileExistsError:_fail("EIY_PUBLICATION_CONFLICT")
   os.fsync(parent_fd);linked=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
  else:fd=os.open(name,os.O_RDWR|_FILE_NOFOLLOW,dir_fd=parent_fd)
  opened=os.fstat(fd);named=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
  if not _file_stat_ok(linked) or not _file_stat_ok(opened) or not _same_identity(linked,opened) or not _same_identity(opened,named):_fail("EIY_PUBLICATION_CONFLICT")
  return fd
 except Exception:
  if fd is not None:os.close(fd)
  raise
 finally:os.close(parent_fd)
def _assert_safe_payload(value:Any)->None:
 if isinstance(value,Mapping):
  if set(value)=={"path","sha256"}:
   try:ArtifactRefV5.from_mapping(value)
   except Exception:_fail("EIY_V5_RESULT_INVALID")
   return
  for key,item in value.items():
   if not isinstance(key,str) or any(marker in key.lower() for marker in ("private","secret","credential")):_fail("EIY_V5_RESULT_INVALID")
   _assert_safe_payload(item)
 elif isinstance(value,list):
  for item in value:_assert_safe_payload(item)
 elif value is not None and type(value) not in (str,int,float,bool):_fail("EIY_V5_RESULT_INVALID")
def _legacy_code(value:Any)->Optional[str]:
 if isinstance(value,Mapping):
  version=value.get("schema_version")
  if isinstance(version,str) and version.endswith("-3"):return "EIY_V3_PUBLICATION_REJECTED"
  if isinstance(version,str) and version.endswith("-4"):return "EIY_V4_PUBLICATION_REJECTED"
 return None
def _unwrap(value:Any,kind:str)->dict[str,Any]:
 code=_legacy_code(value)
 if code:_fail(code)
 try:env=private_unwrap_issued_v5(value)
 except InformationYieldV5Error:_fail("EIY_RESULT_CUSTODY_REQUIRED")
 if env["kind"]!=kind:_fail("ACQ_EIY_V5_NOW_BOUNDARY")
 result=env["result"]
 if digest_v5({k:v for k,v in result.items() if k!="result_sha256"})!=result.get("result_sha256"):_fail("EIY_V5_RESULT_INVALID")
 return env
def _valid_index(raw:bytes,evaluation_id:str)->bool:
 try:value=json.loads(raw)
 except (json.JSONDecodeError,UnicodeDecodeError):return False
 expected={"schema_version","evaluation_id","publication_kind","custody_ref","result_sha256","context_sha256","policy_sha256"}
 if not isinstance(value,dict) or set(value)!=expected or value.get("schema_version")!="information-yield-result-index-entry-1" or value.get("evaluation_id")!=evaluation_id or value.get("publication_kind") not in {"evaluation","now_diagnostic"}:return False
 try:ArtifactRefV5.from_mapping(value["custody_ref"])
 except Exception:return False
 return all(isinstance(value[k],str) and re.fullmatch(r"[a-f0-9]{64}",value[k]) for k in ("result_sha256","context_sha256","policy_sha256"))
def _publish_index(indexes:Path,index_path:Path,index_raw:bytes,evaluation_id:str)->None:
 lock_dir=_create_or_validate_private_dir(indexes/".locks");lock_path=lock_dir/f"{evaluation_id}.lock";lock_fd=_open_private_lock(lock_dir,lock_path.name)
 staging=indexes/f".index-pending-{uuid.uuid4().hex}";staging_owned=False;recovered=None
 try:
  fcntl.flock(lock_fd,fcntl.LOCK_EX)
  if _lexists(staging):_read_private_file(staging);_fail("EIY_PUBLICATION_CONFLICT")
  _write_fd(staging,index_raw);staging_owned=True;_fsync(indexes)
  if _lexists(index_path):
   observed=_read_private_file(index_path)
   if observed==index_raw:return
   if _valid_index(observed,evaluation_id):_fail("EIY_INDEX_CONFLICT")
   recovered=indexes/f".recovered-{evaluation_id}-{uuid.uuid4().hex}"
   try:os.rename(index_path,recovered)
   except OSError:
    if _lexists(index_path):
     if _read_private_file(index_path)==index_raw:return
     _fail("EIY_PUBLICATION_UNKNOWN")
    if not _lexists(recovered):_fail("EIY_PUBLICATION_UNKNOWN")
   _read_private_file(recovered)
  index_fd=_validated_dir_fd(indexes,private_exact=True)
  try:
   try:os.link(staging.name,index_path.name,src_dir_fd=index_fd,dst_dir_fd=index_fd,follow_symlinks=False)
   except OSError as error:
    if _lexists(index_path):
     stage_stat=os.lstat(staging) if _lexists(staging) else None;index_stat=os.lstat(index_path)
     if stage_stat is not None and (stage_stat.st_dev,stage_stat.st_ino)==(index_stat.st_dev,index_stat.st_ino):staging.unlink();staging_owned=False;os.fsync(index_fd)
     observed=_read_private_at(index_fd,index_path.name)
     if observed==index_raw:pass
     elif error.errno==errno.EEXIST and _valid_index(observed,evaluation_id):_fail("EIY_INDEX_CONFLICT")
     else:_fail("EIY_PUBLICATION_UNKNOWN")
    else:_fail("EIY_PUBLICATION_UNKNOWN")
   else:
    staging.unlink();staging_owned=False;os.fsync(index_fd)
  finally:os.close(index_fd)
  try:_fsync(indexes)
  except OSError:
   if _read_private_file(index_path)!=index_raw:_fail("EIY_PUBLICATION_UNKNOWN")
  if _read_private_file(index_path)!=index_raw:_fail("EIY_PUBLICATION_UNKNOWN")
  if recovered and _lexists(recovered):
   try:recovered.unlink();_fsync(indexes)
   except OSError:pass
 finally:
  try:fcntl.flock(lock_fd,fcntl.LOCK_UN)
  finally:os.close(lock_fd)
  if staging_owned and _lexists(staging):
   try:staging.unlink()
   except OSError:pass
def _publish(value:Any,*,publication_root:Union[Path,str],expected_kind:str)->dict[str,Any]:
 env=_unwrap(value,expected_kind);result=env["result"];context=env["context"]
 _assert_safe_payload(context);_assert_safe_payload(result);_assert_safe_payload(env["evaluation_ref"]);_assert_safe_payload(env["custody_ref"])
 if result["context_sha256"]!=context["context_sha256"] or result["fact_set_sha256"]!=context["fact_set_sha256"]:_fail("EIY_V5_RESULT_INVALID")
 root=_safe_root(publication_root);objects=root/"objects";indexes=root/"index";object_dir=objects/result["result_sha256"];context_path=object_dir/"context.json";result_path=object_dir/"result.json";custody_path=object_dir/"custody.json"
 context_raw=_bytes(context);result_raw=_bytes(result);policy_ref=canonical_policy_ref_v5();custody_unsigned={"schema_version":"information-yield-result-custody-1","publication_kind":expected_kind,"evaluation_id":result["evaluation_id"],"evaluation_ref":env["evaluation_ref"],"custody_ref":env["custody_ref"],"context_ref":_ref(context_path,context_raw),"result_ref":_ref(result_path,result_raw),"canonical_policy_ref":policy_ref,"context_sha256":context["context_sha256"],"fact_set_sha256":context["fact_set_sha256"],"result_sha256":result["result_sha256"],"policy_sha256":result["policy_sha256"],"gate_authority_sha256":result["gate_authority_sha256"],"source_closure_sha256":result["source_closure_sha256"],"claim_limits":result["claim_limits"],"same_user_trust":"integrity_and_nominal_issuance_only","same_user_limitations":["no_malicious_same_user_resistance","no_remote_attestation","registry_and_self_hash_do_not_elevate_trust"]};custody={**custody_unsigned,"custody_sha256":digest_v5(custody_unsigned)};custody_raw=_bytes(custody);expected={"context.json":context_raw,"result.json":result_raw,"custody.json":custody_raw}
 evaluation_id=result["evaluation_id"]
 if not isinstance(evaluation_id,str) or not _ID.fullmatch(evaluation_id):_fail("EIY_V5_RESULT_INVALID")
 index={"schema_version":"information-yield-result-index-entry-1","evaluation_id":evaluation_id,"publication_kind":expected_kind,"custody_ref":_ref(custody_path,custody_raw),"result_sha256":result["result_sha256"],"context_sha256":context["context_sha256"],"policy_sha256":result["policy_sha256"]};index_raw=_bytes(index);index_path=indexes/f"{evaluation_id}.json";lock_dir=indexes/".locks";lock_path=lock_dir/f"{evaluation_id}.lock"
 # Mutation-free preflight of every existing internal object.
 for directory in (objects,indexes,object_dir,lock_dir):
  if _lexists(directory):fd=_validated_dir_fd(directory,private_exact=True);os.close(fd)
 if _lexists(object_dir) and not _matches(object_dir,expected):_fail("EIY_PUBLICATION_CONFLICT")
 for file_path in (index_path,lock_path):
  if _lexists(file_path):_read_private_file(file_path)
 objects=_create_or_validate_private_dir(objects);indexes=_create_or_validate_private_dir(indexes)
 if _lexists(object_dir):
  if not _matches(object_dir,expected):_fail("EIY_PUBLICATION_CONFLICT")
 else:
  staging=Path(tempfile.mkdtemp(prefix=".eiy-v5-pending-",dir=objects));staging_owned=True
  try:
   fd=_validated_dir_fd(staging,private_exact=True);os.close(fd)
   for name,raw in expected.items():_write_fd(staging/name,raw)
   _fsync(staging)
   try:os.rename(staging,object_dir);staging_owned=False
   except OSError as error:
    if _lexists(object_dir) and _matches(object_dir,expected):pass
    elif error.errno in {errno.EEXIST,errno.ENOTEMPTY}:_fail("EIY_PUBLICATION_CONFLICT")
    else:_fail("EIY_PUBLICATION_UNKNOWN")
   try:_fsync(objects)
   except OSError:
    if not _matches(object_dir,expected):_fail("EIY_PUBLICATION_UNKNOWN")
   if not _matches(object_dir,expected):_fail("EIY_PUBLICATION_CONFLICT")
  finally:
   if staging_owned and _lexists(staging):shutil.rmtree(staging,ignore_errors=True)
 _publish_index(indexes,index_path,index_raw,evaluation_id)
 if _read_private_file(index_path)!=index_raw:_fail("EIY_PUBLICATION_UNKNOWN")
 return {"status":"published","idempotent":True,"custody_ref":_ref(custody_path,custody_raw),"index_ref":_ref(index_path,index_raw),"claim_limits":list(result["claim_limits"])}
def _public(value,root,kind):
 try:return _publish(value,publication_root=root,expected_kind=kind)
 except EiyPublisherV1Error:raise
 except (OSError,sqlite3.Error):_fail("EIY_PUBLICATION_UNKNOWN")
def publish_eiy_result_v1(result,*,publication_root:Union[Path,str])->dict[str,Any]:return _public(result,publication_root,"evaluation")
def publish_now_diagnostic_v1(result,*,publication_root:Union[Path,str])->dict[str,Any]:return _public(result,publication_root,"now_diagnostic")
