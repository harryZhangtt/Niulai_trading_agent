"""Instrumented fsynced staging, no-replace publication, and UNKNOWN fence."""
from __future__ import annotations
import ctypes,errno,json,os,shutil,sys
from pathlib import Path
from .contracts import canonical_bytes,safe_public,sha256_bytes,validate_evidence
class PublicationError(ValueError):pass
class PublicationTrace:
    def __init__(self,fail_at=None):self.fail_at=fail_at;self.events=[]
    def event(self,name):
        self.events.append(name)
        if self.fail_at==name:raise OSError("INJECTED_"+name.upper())
def _fsync_dir(path,trace,name):
    fd=os.open(str(path),os.O_RDONLY)
    try:os.fsync(fd);trace.event(name)
    finally:os.close(fd)
def _rename_noreplace(src,dst,trace,name):
    trace.event(name+"_attempt")
    if sys.platform=="darwin":
        fn=ctypes.CDLL(None,use_errno=True).renamex_np;fn.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint];fn.restype=ctypes.c_int;rc=fn(os.fsencode(src),os.fsencode(dst),4)
    elif sys.platform.startswith("linux"):
        fn=ctypes.CDLL(None,use_errno=True).renameat2;fn.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];fn.restype=ctypes.c_int;rc=fn(-100,os.fsencode(src),-100,os.fsencode(dst),1)
    else:
        if Path(dst).exists():raise FileExistsError(str(dst))
        os.rename(src,dst);rc=0
    if rc!=0:
        e=ctypes.get_errno();raise FileExistsError(e,os.strerror(e),str(dst)) if e==errno.EEXIST else OSError(e,os.strerror(e),str(dst))
    trace.event(name+"_committed")
def atomic_file_noreplace(path,data,trace,prefix):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True);stage=path.parent/("."+path.name+".staging-"+sha256_bytes(data)[:16]);fd=os.open(str(stage),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:os.write(fd,data);os.fsync(fd);trace.event(prefix+"_file_fsync")
    except BaseException:os.close(fd);stage.unlink(missing_ok=True);raise
    else:os.close(fd)
    try:_rename_noreplace(stage,path,trace,prefix+"_no_replace");_fsync_dir(path.parent,trace,prefix+"_dir_fsync")
    except BaseException:
        stage.unlink(missing_ok=True)
        if path.exists() and prefix=="fence":path.unlink();_fsync_dir(path.parent,PublicationTrace(),"fence_rollback_dir_fsync")
        raise
def _validate_bundle(stage,expected):
    parsed=json.loads((stage/"manifest.json").read_text(encoding="ascii"))
    if type(parsed)is not dict or set(parsed)!={"version","files"} or parsed!={"version":1,"files":expected}:raise PublicationError("BUNDLE_MANIFEST_INVALID")
    if set(p.name for p in stage.iterdir())!=set(expected)|{"manifest.json"}:raise PublicationError("BUNDLE_FILE_SET_INVALID")
    for name,d in expected.items():
        p=stage/name;raw=p.read_bytes()
        if p.is_symlink() or not p.is_file() or (p.stat().st_mode&0o777)!=0o600 or set(d)!={"bytes","sha256"} or d!={"bytes":len(raw),"sha256":sha256_bytes(raw)}:raise PublicationError("BUNDLE_FILE_INVALID")
def _stage(root,name,files,trace,prefix):
    root.mkdir(mode=0o700,parents=True,exist_ok=True);stage=root/("."+name+".staging");stage.mkdir(mode=0o700);manifest={}
    try:
        for fname,data in files.items():
            p=stage/fname;fd=os.open(str(p),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            try:os.write(fd,data);os.fsync(fd);trace.event(prefix+"_file_fsync")
            finally:os.close(fd)
            manifest[fname]={"bytes":len(data),"sha256":sha256_bytes(data)}
        raw=canonical_bytes({"version":1,"files":manifest});fd=os.open(str(stage/"manifest.json"),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:os.write(fd,raw);os.fsync(fd);trace.event(prefix+"_manifest_fsync")
        finally:os.close(fd)
        _fsync_dir(stage,trace,prefix+"_stage_dir_fsync");_validate_bundle(stage,manifest);return stage
    except BaseException:shutil.rmtree(stage,ignore_errors=True);raise
def _commit(stage,final,trace,prefix):
    try:_rename_noreplace(stage,final,trace,prefix+"_commit");_fsync_dir(final.parent,trace,prefix+"_parent_dir_fsync")
    except FileExistsError:shutil.rmtree(stage,ignore_errors=True);raise PublicationError("PUBLICATION_COLLISION")
    except BaseException:
        shutil.rmtree(stage,ignore_errors=True)
        if final.exists():shutil.rmtree(final,ignore_errors=True);_fsync_dir(final.parent,PublicationTrace(),prefix+"_rollback_dir_fsync")
        raise PublicationError(prefix.upper()+"_PUBLICATION_UNCERTAIN")
def publish_owner(root,files,trace):
    try:
        stage=_stage(root,"execution",files,trace,"owner");_commit(stage,root/"execution",trace,"owner");return "execution"
    except PublicationError:raise
    except OSError as exc:raise PublicationError("OWNER_PUBLICATION_UNCERTAIN") from exc
def publish_public(root,evidence,trace):
    try:
        validate_evidence(evidence);safe_public(evidence);stage=_stage(root,"execution",{"evidence.json":canonical_bytes(evidence)},trace,"public");_commit(stage,root/"execution",trace,"public");return "execution"
    except PublicationError:raise
    except OSError as exc:raise PublicationError("PUBLIC_PUBLICATION_UNCERTAIN") from exc
def durable_unknown_fence(root,evidence,trace):
    validate_evidence(evidence)
    if evidence["status"]!="UNKNOWN" or evidence["unknown_fence"]!={"durable":True,"retry":False,"replay":False,"status_calls":0,"receipt":"unknown-fence.json"}:raise PublicationError("UNKNOWN_FENCE_INVALID")
    path=root/"unknown-fence.json"
    try:atomic_file_noreplace(path,canonical_bytes(evidence),trace,"fence")
    except FileExistsError:
        current=json.loads(path.read_text(encoding="ascii"));validate_evidence(current)
    except BaseException as exc:raise PublicationError("UNKNOWN_FENCE_NOT_DURABLE") from exc
    return path.name
