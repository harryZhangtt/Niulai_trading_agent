"""Closed-Engine descriptor snapshot bridge; provider-free and never active-DB safe."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib,json,os,secrets,sqlite3,stat
from pathlib import Path
from types import MappingProxyType
from typing import Any,Callable,Dict,Mapping,Optional,Sequence,Tuple
from shared.job_runtime.engine_schema import SCHEMA9_FINGERPRINT,prompt_binding_sha256,verify_schema9
from shared.job_runtime.candidates.r6_data_quality_fable_ab_v1.contracts import CELL_ORDER,MODEL_ID,canonical_bytes,sha256_json,strict_json_loads
from shared.job_runtime.candidates.r6_data_quality_fable_adapter_v1.adapter import DESIGN_SHA256,EXPECTED_KEYS,INPUTS_SHA256,JOB_IDS,ROW_KEYS
class BridgeError(ValueError):pass
def require(ok:bool,code:str)->None:
 if not ok:raise BridgeError(code)
ALLOCATION_SHA256="5861f566bebb5acb11c9a3c683326f8e93ec8ef4dd8ab3ab2fba74cdaf57f4bf";ADAPTER_CLOSURE_SHA256="fa2ccbfa531e5880defe4eb816c22be024b9e9187f7d267d803752da5a6208a8";MAX_DB_BYTES=64*1024*1024
ALLOCATION_KEYS=("version","kind","activation","installed_jobs","installed_schedules","model","provider","design_sha256","inputs_sha256","adapter_closure_sha256","cells","effects");EFFECTS={"provider":0,"network":0,"publication":0,"email":0,"tools":0,"web":0,"subagents":0};QUIESCENCE={"engine_closed":True,"active_service":False,"sidecars_absent":True};SOURCE_KEYS=("sha256","bytes","st_dev","st_ino","st_mtime_ns")
DIR_FLAGS=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC;READ_FLAGS=os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC;WRITE_FLAGS=os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC
@dataclass(frozen=True)
class BridgeReadback:rows:Tuple[Mapping[str,Any],Mapping[str,Any]];expected_readback:Tuple[Mapping[str,Any],Mapping[str,Any]];receipt:Mapping[str,Any]
def validate_allocation(v:Any)->Mapping[str,Any]:
 require(type(v) is dict and set(v)==set(ALLOCATION_KEYS),"ALLOCATION_SHAPE");require(type(v["version"]) is int and v["version"]==1 and v["kind"]=="R6_FABLE_PROVIDER_FREE_ALLOCATION_BRIDGE","ALLOCATION_VERSION");require(v["activation"] is False and v["installed_jobs"]==[] and v["installed_schedules"]==[],"ALLOCATION_ACTIVATION");require(v["model"]==MODEL_ID and v["provider"]=="claude_host","ALLOCATION_PROVIDER_MODEL");require(v["design_sha256"]==DESIGN_SHA256 and v["inputs_sha256"]==INPUTS_SHA256 and v["adapter_closure_sha256"]==ADAPTER_CLOSURE_SHA256,"ALLOCATION_BINDING");require(v["cells"]==[{"cell_id":CELL_ORDER[i],"job_id":JOB_IDS[i]} for i in range(2)],"ALLOCATION_CELL_ORDER");require(v["effects"]==EFFECTS,"ALLOCATION_EFFECTS");require(hashlib.sha256(canonical_bytes(v)).hexdigest()==ALLOCATION_SHA256,"ALLOCATION_DIGEST");return v
def validate_joined_rows(joined:Sequence[Mapping[str,Any]],allocation:Mapping[str,Any]):
 validate_allocation(dict(allocation));require(type(joined) in (list,tuple) and len(joined)==2,"BRIDGE_ROW_COUNT");rows=[];expected=[]
 for i,source in enumerate(joined):
  require(type(source) is dict,"BRIDGE_JOIN_SHAPE");cell=CELL_ORDER[i];job=JOB_IDS[i];require(source.get("job_id")==job,"BRIDGE_JOB_ORDER");require(source.get("pr_attempt_id")==source.get("attempt_join_id") and source.get("pr_slot_id")==source.get("attempt_slot_id")==source.get("slot_join_id"),"BRIDGE_AMBIGUOUS_JOIN");canonical=source.get("canonical_json");require(type(canonical) is str,"BRIDGE_CANONICAL_TYPE");value=strict_json_loads(canonical,"BRIDGE_CANONICAL_JSON");require(type(value) is dict,"BRIDGE_CANONICAL_SHAPE");require(value.get("provider")==source.get("provider")=="claude_host" and value.get("operation_id")==source.get("operation_id"),"BRIDGE_PROVIDER_BINDING");receipt=value.get("receipt");require(type(receipt) is dict and receipt.get("cell_id")==cell and receipt.get("configured_model")==MODEL_ID and receipt.get("provider_reported_model")==MODEL_ID,"BRIDGE_CELL_MODEL_BINDING");descriptor={k:source.get(k) for k in ("artifact_ref","sha256","length","version","source_identity_sha256","generation","proof_origin")};require(descriptor["sha256"]=="35a99586bd30c9ca70b0f5fb22dbf60e915f2dfcaf4d1be15fcfe9b9ea630c8e","BRIDGE_DESCRIPTOR_PROMPT");derived=prompt_binding_sha256(job,source["pr_slot_id"],descriptor);require(source.get("prompt_binding_sha256")==source.get("attempt_binding_sha256")==source.get("slot_binding_sha256")==derived,"BRIDGE_PROMPT_BINDING");require(source.get("operation_id")=="attempt/"+source["pr_attempt_id"]+"/prompt/"+derived,"BRIDGE_NATIVE_OPERATION")
  row={"attempt_id":source["pr_attempt_id"],"slot_id":source["pr_slot_id"],"canonical_json":canonical,"canonical_sha256":source["canonical_sha256"],"provider":source["provider"],"operation_id":source["operation_id"],"phase":source["phase"],"submission":source["submission"],"terminal_proof":source["terminal_proof"],"status":source["status"],"failure_kind":source["failure_kind"],"recorded_at":source["recorded_at"],"prompt_binding_sha256":source["prompt_binding_sha256"]};require(set(row)==set(ROW_KEYS),"BRIDGE_ROW_PROJECTION");exp={"cell_id":cell,"job_id":job,"slot_id":source["pr_slot_id"],"attempt_id":source["pr_attempt_id"],"prompt_binding_sha256":derived,**descriptor};require(set(exp)==set(EXPECTED_KEYS),"BRIDGE_EXPECTED_PROJECTION");rows.append(row);expected.append(exp)
 require(len({r["attempt_id"] for r in rows})==2 and len({r["slot_id"] for r in rows})==2,"BRIDGE_DUPLICATE_ID");return (rows[0],rows[1]),(expected[0],expected[1])
def _identity(m:os.stat_result)->tuple:return (m.st_dev,m.st_ino,m.st_uid,stat.S_IMODE(m.st_mode),m.st_nlink,m.st_size,m.st_mtime_ns,m.st_ctime_ns)
def _walk_parent(path:Path)->tuple[int,str]:
 require(path.is_absolute() and len(path.parts)>1,"BRIDGE_DATABASE_PATH");fd=os.open("/",DIR_FLAGS)
 try:
  for part in path.parts[1:-1]:
   nxt=os.open(part,DIR_FLAGS,dir_fd=fd);meta=os.fstat(nxt);require(stat.S_ISDIR(meta.st_mode),"BRIDGE_PARENT_UNSAFE");os.close(fd);fd=nxt
  return fd,path.name
 except BaseException:os.close(fd);raise
def _snapshot_source(path:Path,expectation:Mapping[str,Any],hook:Optional[Callable[[str],None]]):
 require(type(expectation) is dict and set(expectation)==set(SOURCE_KEYS),"SOURCE_EXPECTATION_SHAPE");parent,name=_walk_parent(path);dbfd=-1;snapdir=-1;snapfd=-1;snapname="snapshot.sqlite";dirname=".r6-fable-snapshot-"+secrets.token_hex(8);before_listing=tuple(sorted(os.listdir(parent)))
 try:
  for suffix in ("-wal","-shm","-journal"):
   try:os.stat(name+suffix,dir_fd=parent,follow_symlinks=False);raise BridgeError("SOURCE_NOT_QUIESCENT")
   except FileNotFoundError:pass
  dbfd=os.open(name,READ_FLAGS,dir_fd=parent);before=os.fstat(dbfd);named_before=os.stat(name,dir_fd=parent,follow_symlinks=False);require(_identity(before)==_identity(named_before),"SOURCE_DB_CHANGED");require(stat.S_ISREG(before.st_mode) and before.st_uid==os.getuid() and stat.S_IMODE(before.st_mode)==0o600 and before.st_nlink==1,"SOURCE_DB_UNSAFE");require(before.st_size<=MAX_DB_BYTES,"SOURCE_DB_TOO_LARGE")
  if hook:hook("after_source_open")
  chunks=[];total=0;first=True
  while True:
   part=os.read(dbfd,65536)
   if not part:break
   chunks.append(part);total+=len(part);require(total<=MAX_DB_BYTES,"SOURCE_DB_TOO_LARGE")
   if first and hook:first=False;hook("during_source_read")
  raw=b"".join(chunks);after=os.fstat(dbfd);named=os.stat(name,dir_fd=parent,follow_symlinks=False);require(_identity(before)==_identity(after)==_identity(named),"SOURCE_DB_CHANGED")
  digest=hashlib.sha256(raw).hexdigest();require(expectation=={"sha256":digest,"bytes":len(raw),"st_dev":before.st_dev,"st_ino":before.st_ino,"st_mtime_ns":before.st_mtime_ns},"SOURCE_EXPECTATION_MISMATCH")
  os.mkdir(dirname,0o700,dir_fd=parent);snapdir=os.open(dirname,DIR_FLAGS,dir_fd=parent);dm=os.fstat(snapdir);require(dm.st_uid==os.getuid() and stat.S_IMODE(dm.st_mode)==0o700,"SNAPSHOT_DIR_UNSAFE");snapfd=os.open(snapname,WRITE_FLAGS,0o600,dir_fd=snapdir);view=memoryview(raw)
  while view:
   n=os.write(snapfd,view);require(n>0,"SNAPSHOT_WRITE");view=view[n:]
  sm=os.fstat(snapfd);require(stat.S_ISREG(sm.st_mode) and sm.st_uid==os.getuid() and stat.S_IMODE(sm.st_mode)==0o600 and sm.st_nlink==1 and sm.st_size==len(raw),"SNAPSHOT_FILE_UNSAFE")
  os.fsync(snapfd);os.close(snapfd);snapfd=-1;os.fsync(snapdir)
  verifyfd=os.open(snapname,READ_FLAGS,dir_fd=snapdir)
  try:
   parts=[]
   while True:
    chunk=os.read(verifyfd,65536)
    if not chunk:break
    parts.append(chunk)
   require(hashlib.sha256(b"".join(parts)).hexdigest()==digest,"SNAPSHOT_DIGEST_MISMATCH")
  finally:os.close(verifyfd)
  snap_path=path.parent/dirname/snapname
  if hook:hook("after_snapshot")
  return parent,dbfd,snapdir,dirname,snapname,snap_path,raw,digest,before_listing
 except BaseException:
  if snapfd>=0:
   try:os.close(snapfd)
   except OSError:pass
  if snapdir>=0:
   try:
    try:os.unlink(snapname,dir_fd=snapdir)
    except FileNotFoundError:pass
    os.fsync(snapdir);os.close(snapdir);snapdir=-1
    try:os.rmdir(dirname,dir_fd=parent)
    except FileNotFoundError:pass
    os.fsync(parent)
   except OSError:pass
  for fd in (dbfd,parent):
   if fd>=0:
    try:os.close(fd)
    except OSError:pass
  raise
def read_allocation_pair(database:Path,allocation:Mapping[str,Any],source_expectation:Mapping[str,Any],quiescence:Mapping[str,Any],*,_test_hook:Optional[Callable[[str],None]]=None)->BridgeReadback:
 value=dict(allocation);validate_allocation(value);require(dict(quiescence)==QUIESCENCE,"QUIESCENCE_ASSERTION_REQUIRED");path=Path(database);state=None;db=None
 try:
  state=_snapshot_source(path,source_expectation,_test_hook);parent,dbfd,snapdir,dirname,snapname,snap_path,raw,source_sha,before_listing=state
  try:
   if _test_hook:_test_hook("before_sqlite_open")
   uri="file:"+str(snap_path)+"?mode=ro&immutable=1";db=sqlite3.connect(uri,uri=True,timeout=10);db.row_factory=sqlite3.Row
   if _test_hook:_test_hook("after_sqlite_open")
   db.execute("BEGIN");
   if _test_hook:_test_hook("after_begin")
   db.execute("PRAGMA query_only=ON");schema=verify_schema9(db)
   if _test_hook:_test_hook("after_pragmas")
   joined=[dict(r) for r in db.execute("""SELECT p.attempt_id pr_attempt_id,p.slot_id pr_slot_id,p.canonical_json,p.canonical_sha256,p.provider,p.operation_id,p.phase,p.submission,p.terminal_proof,p.status,p.failure_kind,p.recorded_at,p.prompt_binding_sha256,a.attempt_id attempt_join_id,a.slot_id attempt_slot_id,a.binding_sha256 attempt_binding_sha256,s.slot_id slot_join_id,s.job_id,s.binding_sha256 slot_binding_sha256,s.artifact_ref,s.sha256,s.length,s.version,s.source_identity_sha256,s.generation,s.proof_origin FROM provider_results p JOIN attempts a ON a.attempt_id=p.attempt_id JOIN slots s ON s.slot_id=p.slot_id AND s.slot_id=a.slot_id WHERE s.job_id IN (?,?) ORDER BY p.rowid""",JOB_IDS)]
   if _test_hook:_test_hook("after_query")
   rows,expected=validate_joined_rows(joined,value);readback_sha=sha256_json({"allocation_sha256":ALLOCATION_SHA256,"schema_fingerprint":schema,"provider_rows":list(rows),"expected_readbacks":list(expected)})
   if _test_hook:_test_hook("before_commit")
   db.commit();receipt={"version":1,"status":"PASS_CLOSED_QUIESCENT_SNAPSHOT","activation":False,"countable":False,"transaction":"BEGIN_READ_SNAPSHOT_IMMUTABLE","allocation_sha256":ALLOCATION_SHA256,"adapter_closure_sha256":ADAPTER_CLOSURE_SHA256,"schema_fingerprint":schema,"database_readback_sha256":readback_sha,"source_db_sha256":source_sha,"source_db_bytes":len(raw),"source_db_identity":{"st_dev":source_expectation["st_dev"],"st_ino":source_expectation["st_ino"],"st_mtime_ns":source_expectation["st_mtime_ns"]},"snapshot_sha256":hashlib.sha256(raw).hexdigest(),"quiescence":dict(QUIESCENCE),"row_count":2,"cell_order":list(CELL_ORDER),"effects":dict(EFFECTS)}
  except BaseException:
   if db is not None:
    try:db.rollback()
    except BaseException:pass
   raise
  finally:
   if db is not None:db.close();db=None
 except BridgeError:raise
 except (sqlite3.Error,ValueError,OSError):raise BridgeError("BRIDGE_DATABASE_READBACK_FAILED") from None
 finally:
  if state is not None:
   parent,dbfd,snapdir,dirname,snapname,_,_,_,before_listing=state
   try:
    try:os.unlink(snapname,dir_fd=snapdir)
    except FileNotFoundError:pass
    os.fsync(snapdir);os.close(snapdir);os.rmdir(dirname,dir_fd=parent);os.fsync(parent);os.close(dbfd);require(tuple(sorted(os.listdir(parent)))==before_listing,"SOURCE_DIRECTORY_CHANGED")
   finally:
    try:os.close(parent)
    except OSError:pass
 require(receipt["schema_fingerprint"]==SCHEMA9_FINGERPRINT,"BRIDGE_SCHEMA_FINGERPRINT");return BridgeReadback(tuple(MappingProxyType(dict(r)) for r in rows),tuple(MappingProxyType(dict(r)) for r in expected),MappingProxyType(receipt))
__all__=["ADAPTER_CLOSURE_SHA256","ALLOCATION_SHA256","BridgeError","BridgeReadback","read_allocation_pair","validate_allocation","validate_joined_rows"]
