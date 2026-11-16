"""Owner-private locked append-only answer ledger."""
from __future__ import annotations
import fcntl, json, os, stat
from pathlib import Path
from typing import Any, List, Mapping, Optional, Tuple
from .contracts import AnswerDecision, ContractError, canonical_bytes, digest, require, sanitize_tree

EVENT_KEYS={"sequence","job_id","question_id","identity_sha256","operation_sha256","observed_monotonic_ns","state","option_ids","previous_sha256","event_sha256"}

def _write_all(fd: int, raw: bytes) -> None:
    view=memoryview(raw)
    while view:
        written=os.write(fd,view)
        if written<=0: raise OSError("short write")
        view=view[written:]

def _fsync(fd: int) -> None: os.fsync(fd)

def _secure_fd(parent_fd: int, name: str, flags: int, mode: int=0o600) -> Tuple[int,bool]:
    nofollow=getattr(os,"O_NOFOLLOW",0); cloexec=getattr(os,"O_CLOEXEC",0); base=(flags & ~os.O_CREAT)|nofollow|cloexec
    created=False
    if flags & os.O_CREAT:
        try: fd=os.open(name,base,dir_fd=parent_fd)
        except FileNotFoundError:
            try: fd=os.open(name,base|os.O_CREAT|os.O_EXCL,mode,dir_fd=parent_fd);created=True
            except FileExistsError: fd=os.open(name,base,dir_fd=parent_fd)
    else: fd=os.open(name,base,dir_fd=parent_fd)
    info=os.fstat(fd)
    try:require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)==0o600,"LEDGER_FILE_UNSAFE")
    except BaseException:os.close(fd);raise
    return fd,created

class AnswerLedger:
    def __init__(self,path:Path)->None:
        require(isinstance(path,Path) and path.is_absolute() and path.name not in ("",".",".."),"LEDGER_PATH_INVALID"); self.path=path; self.lock_path=path.with_name(path.name+".lock")
        parent_fd=self._open_parent();
        try:self._parent_identity=self._validate_parent(parent_fd)
        finally:os.close(parent_fd)
    def _open_parent(self)->int:
        flags=os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
        fd=os.open("/",flags)
        try:
            for component in self.path.parent.parts[1:]:
                next_fd=os.open(component,flags,dir_fd=fd);os.close(fd);fd=next_fd
            return fd
        except BaseException:
            os.close(fd);raise
    def _validate_parent(self,parent_fd:int):
        held=os.fstat(parent_fd)
        try:named=os.stat(str(self.path.parent),follow_symlinks=False)
        except FileNotFoundError:raise ContractError("LEDGER_PARENT_MISSING") from None
        require(stat.S_ISDIR(held.st_mode) and stat.S_ISDIR(named.st_mode) and held.st_dev==named.st_dev and held.st_ino==named.st_ino,"LEDGER_PARENT_IDENTITY_DRIFT")
        require(held.st_uid==os.getuid() and stat.S_IMODE(held.st_mode)==0o700 and held.st_nlink>=1,"LEDGER_PARENT_UNSAFE")
        identity=(held.st_dev,held.st_ino)
        if hasattr(self,"_parent_identity"):require(identity==self._parent_identity,"LEDGER_PARENT_IDENTITY_DRIFT")
        return identity
    def _read_all(self,fd:int)->bytes:
        os.lseek(fd,0,os.SEEK_SET); chunks=[]
        while True:
            chunk=os.read(fd,65536)
            if not chunk: return b"".join(chunks)
            chunks.append(chunk)
    def _decode_events(self,raw:bytes)->List[Mapping[str,Any]]:
        if not raw:return []
        require(raw.endswith(b"\n"),"LEDGER_PARTIAL_TAIL"); events=[]; previous="0"*64
        for line in raw[:-1].split(b"\n"):
            require(bool(line),"LEDGER_PARTIAL_TAIL")
            try:event=json.loads(line.decode("ascii"))
            except (ValueError,UnicodeError):raise ContractError("LEDGER_CORRUPT") from None
            require(type(event) is dict and set(event)==EVENT_KEYS,"LEDGER_CORRUPT"); claimed=event["event_sha256"]; body=dict(event);del body["event_sha256"]
            require(event["sequence"]==len(events)+1 and event["previous_sha256"]==previous and claimed==digest(body),"LEDGER_CORRUPT")
            require(event["state"] in ("SUBMITTING","ACKED","UNKNOWN"),"LEDGER_CORRUPT"); sanitize_tree(event);events.append(event);previous=claimed
        return events
    def _lock(self):
        parent_fd=self._open_parent();self._validate_parent(parent_fd)
        try:fd,created=_secure_fd(parent_fd,self.lock_path.name,os.O_RDWR|os.O_CREAT)
        except BaseException:os.close(parent_fd);raise
        fcntl.flock(fd,fcntl.LOCK_EX)
        try:
            if created:_fsync(parent_fd)
        except BaseException:
            fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd);os.close(parent_fd);raise
        return parent_fd,fd
    def _load_locked(self,parent_fd:int,lock_fd:int):
        ledger_created=False
        try:ledger_fd,ledger_created=_secure_fd(parent_fd,self.path.name,os.O_RDWR|os.O_CREAT)
        except BaseException:raise
        if ledger_created:_fsync(parent_fd)
        events=self._decode_events(self._read_all(ledger_fd))
        meta_raw=self._read_all(lock_fd)
        expected={"sequence":len(events),"head_sha256":events[-1]["event_sha256"] if events else "0"*64}
        if not meta_raw:
            require(not events,"LEDGER_TRUNCATED")
            self._write_meta(lock_fd,expected)
        else:
            try:meta=json.loads(meta_raw.decode("ascii"))
            except (ValueError,UnicodeError):raise ContractError("LEDGER_LOCK_CORRUPT") from None
            require(type(meta) is dict and meta==expected,"LEDGER_TRUNCATED")
        return ledger_fd,events
    def _write_meta(self,fd:int,meta:Mapping[str,Any])->None:
        raw=canonical_bytes(meta);os.lseek(fd,0,os.SEEK_SET);os.ftruncate(fd,0);_write_all(fd,raw);_fsync(fd)
    def _with_events(self):
        parent_fd,lock_fd=self._lock()
        try:
            ledger_fd,events=self._load_locked(parent_fd,lock_fd);self._validate_parent(parent_fd);return parent_fd,lock_fd,ledger_fd,events
        except BaseException:os.close(lock_fd);os.close(parent_fd);raise
    def state_for(self,decision:AnswerDecision)->Optional[str]:
        parent_fd,lock_fd,ledger_fd,events=self._with_events()
        try:
            matches=[e for e in events if e["job_id"]==decision.job.job_id]
            if matches:
                require(all(e["operation_sha256"]==decision.operation_sha256 and e["option_ids"]==list(decision.option_ids) for e in matches),"ANSWER_BINDING_MISMATCH")
            return matches[-1]["state"] if matches else None
        finally:os.close(ledger_fd);fcntl.flock(lock_fd,fcntl.LOCK_UN);os.close(lock_fd);os.close(parent_fd)
    def _append(self,decision:AnswerDecision,state:str)->Mapping[str,Any]:
        parent_fd,lock_fd,ledger_fd,events=self._with_events()
        try:
            same=[e for e in events if e["question_id"]==decision.job.question_id]
            require(not same or all(e["identity_sha256"]==decision.job.question_identity_sha256 for e in same),"STALE_OR_REPLACED_IDENTITY")
            current=[e for e in events if e["job_id"]==decision.job.job_id];prior=current[-1]["state"] if current else None
            if current:require(all(e["operation_sha256"]==decision.operation_sha256 and e["option_ids"]==list(decision.option_ids) and e["observed_monotonic_ns"]==decision.observed_monotonic_ns for e in current),"ANSWER_BINDING_MISMATCH")
            require((prior is None and state=="SUBMITTING") or (prior=="SUBMITTING" and state in ("ACKED","UNKNOWN")),"ANSWER_NO_REPLAY_FENCE")
            body={"sequence":len(events)+1,"job_id":decision.job.job_id,"question_id":decision.job.question_id,"identity_sha256":decision.job.question_identity_sha256,
                "operation_sha256":decision.operation_sha256,"observed_monotonic_ns":decision.observed_monotonic_ns,"state":state,"option_ids":list(decision.option_ids),
                "previous_sha256":events[-1]["event_sha256"] if events else "0"*64}
            event=dict(body,event_sha256=digest(body));os.lseek(ledger_fd,0,os.SEEK_END);_write_all(ledger_fd,canonical_bytes(event)+b"\n");_fsync(ledger_fd)
            self._write_meta(lock_fd,{"sequence":body["sequence"],"head_sha256":event["event_sha256"]});return event
        finally:os.close(ledger_fd);fcntl.flock(lock_fd,fcntl.LOCK_UN);os.close(lock_fd);os.close(parent_fd)
    def begin_submit(self,d):return self._append(d,"SUBMITTING")
    def acknowledge(self,d):return self._append(d,"ACKED")
    def mark_unknown(self,d):return self._append(d,"UNKNOWN")
