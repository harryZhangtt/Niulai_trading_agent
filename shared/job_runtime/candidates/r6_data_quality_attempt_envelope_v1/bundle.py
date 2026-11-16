"""Crash-recoverable single-file immutable attempt-bundle commit."""
from __future__ import annotations
from dataclasses import dataclass
import json, os, stat
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional
from .contracts import ContractError, canonical_bytes, sha256_bytes, strict_json_loads, validate_attempt_bundle
_DIR_FLAGS=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
_WRITE_FLAGS=os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC
_READ_FLAGS=os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC
class BundleCommitError(ValueError):
    def __init__(self,code:str,recoverable:bool=True)->None:super().__init__(code);self.recoverable=recoverable
@dataclass(frozen=True)
class BundleReceipt:
    path:Path;sha256:str;bytes:int;primitive:str;file_fsync:bool;parent_dir_fsync:bool;no_overwrite:bool;recovered_fault:Optional[str]
class AttemptBundleStore:
    def __init__(self,root:Path,fault:Optional[str]=None,crash_hook:Optional[Callable[[str],None]]=None,owner_root:Optional[Path]=None)->None:self.root=Path(root);self.fault=fault;self.crash_hook=crash_hook;self.owner_root=None if owner_root is None else Path(owner_root);self._fault_used=False
    def _trip(self,name:str)->bool:
        if self.fault==name and not self._fault_used:self._fault_used=True;return True
        return False
    def _directory(self)->int:
        try:self.root.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(self.root,0o700);before=self.root.lstat();fd=os.open(self.root,_DIR_FLAGS);after=os.fstat(fd)
        except OSError:raise BundleCommitError('BUNDLE_DIRECTORY_OPEN',False) from None
        if not stat.S_ISDIR(before.st_mode) or before.st_ino!=after.st_ino or before.st_dev!=after.st_dev or after.st_uid!=os.getuid() or stat.S_IMODE(after.st_mode)!=0o700:os.close(fd);raise BundleCommitError('BUNDLE_DIRECTORY_UNSAFE',False)
        return fd
    @staticmethod
    def _stat(fd:int,name:str)->Optional[os.stat_result]:
        try:return os.stat(name,dir_fd=fd,follow_symlinks=False)
        except FileNotFoundError:return None
        except OSError:raise BundleCommitError('BUNDLE_STAT_FAILED',False) from None
    @staticmethod
    def _safe(meta:os.stat_result,links:tuple)->bool:return stat.S_ISREG(meta.st_mode) and meta.st_uid==os.getuid() and stat.S_IMODE(meta.st_mode)==0o600 and meta.st_nlink in links
    @staticmethod
    def _fsync(fd:int,code:str='BUNDLE_DIR_FSYNC_OSERROR')->None:
        try:os.fsync(fd)
        except OSError:raise BundleCommitError(code,False) from None
    @classmethod
    def _unlink(cls,fd:int,name:str,code:str)->None:
        try:os.unlink(name,dir_fd=fd)
        except OSError:raise BundleCommitError(code,False) from None
    def _read_named(self,fd:int,name:str,expected:str)->Dict[str,Any]:
        file_fd=-1
        try:
            file_fd=os.open(name,_READ_FLAGS,dir_fd=fd);meta=os.fstat(file_fd)
            if not self._safe(meta,(1,2)):raise BundleCommitError('BUNDLE_READBACK_UNSAFE',False)
            chunks=[];total=0
            while True:
                try:chunk=os.read(file_fd,16384)
                except OSError:raise BundleCommitError('BUNDLE_READBACK_FAILED',False) from None
                if not chunk:break
                chunks.append(chunk);total+=len(chunk)
                if total>1048576:raise BundleCommitError('BUNDLE_READBACK_TOO_LARGE',False)
            raw=b''.join(chunks)
        except OSError:raise BundleCommitError('BUNDLE_READBACK_FAILED',False) from None
        finally:
            if file_fd>=0:os.close(file_fd)
        if sha256_bytes(raw)!=expected:raise BundleCommitError('BUNDLE_READBACK_DIGEST',False)
        try:value=strict_json_loads(raw.decode('ascii'),'BUNDLE_READBACK_JSON')
        except (UnicodeError,ContractError):raise BundleCommitError('BUNDLE_READBACK_JSON',False) from None
        validate_attempt_bundle(value)
        if canonical_bytes(value)!=raw:raise BundleCommitError('BUNDLE_READBACK_CANONICAL',False)
        return value
    def _entry_recovery(self,fd:int,stage:str,destination:str,expected:str)->Optional[Dict[str,Any]]:
        sm=self._stat(fd,stage);dm=self._stat(fd,destination)
        if sm is None and dm is None:return None
        if sm is not None and dm is None:
            if not self._safe(sm,(1,)):raise BundleCommitError('BUNDLE_STAGE_UNSAFE',False)
            self._unlink(fd,stage,'BUNDLE_STAGE_UNLINK_FAILED');self._fsync(fd);return None
        if sm is None and dm is not None:raise BundleCommitError('BUNDLE_NO_OVERWRITE',False)
        if not self._safe(sm,(2,)) or not self._safe(dm,(2,)) or (sm.st_dev,sm.st_ino)!=(dm.st_dev,dm.st_ino):raise BundleCommitError('BUNDLE_CRASH_STATE_CONFLICT',False)
        value=self._read_named(fd,destination,expected)
        self._unlink(fd,stage,'BUNDLE_STAGE_UNLINK_FAILED');self._fsync(fd)
        final=self._stat(fd,destination)
        if final is None or not self._safe(final,(1,)):raise BundleCommitError('BUNDLE_FINAL_LINKCOUNT',False)
        if self._read_named(fd,destination,expected)!=value:raise BundleCommitError('BUNDLE_READBACK_MISMATCH',False)
        return value
    def commit(self,bundle:Mapping[str,Any],recovered_fault:Optional[str]=None)->BundleReceipt:
        value=dict(bundle);validate_attempt_bundle(value)
        if self.owner_root is None:raise BundleCommitError('BUNDLE_OWNER_ROOT_REQUIRED',False)
        from .artifacts import validate_bundle_owner_artifacts
        try:validate_bundle_owner_artifacts(self.owner_root,value)
        except Exception as exc:raise BundleCommitError(str(exc),False) from exc
        raw=canonical_bytes(value);expected=sha256_bytes(raw);cell=value['key']['cell_id'];destination=cell+'.attempt-bundle.json';stage='.stage-'+cell+'.attempt-bundle.json';fd=self._directory();stage_fd=-1;linked=False
        try:
            recovered=self._entry_recovery(fd,stage,destination,expected)
            if recovered is not None:
                return BundleReceipt(self.root/destination,expected,len(raw),'LINK_NO_REPLACE_SINGLE_FILE',True,True,True,recovered_fault or 'REAL_CRASH_POST_LINK')
            try:stage_fd=os.open(stage,_WRITE_FLAGS,0o600,dir_fd=fd)
            except OSError:raise BundleCommitError('BUNDLE_STAGE_OPEN') from None
            if self.crash_hook is not None and self.fault=='crash_stage_created':self.crash_hook('stage_created')
            view=memoryview(raw)
            while view:
                try:
                    if self._trip('short_write'):
                        n=os.write(stage_fd,view[:max(1,len(view)//2)]);view=view[n:];raise BundleCommitError('BUNDLE_SHORT_WRITE')
                    n=os.write(stage_fd,view)
                except BundleCommitError:raise
                except OSError:raise BundleCommitError('BUNDLE_WRITE_OSERROR') from None
                if n<=0:raise BundleCommitError('BUNDLE_SHORT_WRITE')
                view=view[n:]
            if self._trip('file_fsync'):raise BundleCommitError('BUNDLE_FILE_FSYNC')
            try:os.fsync(stage_fd)
            except OSError:raise BundleCommitError('BUNDLE_FILE_FSYNC_OSERROR') from None
            os.close(stage_fd);stage_fd=-1
            if self._trip('crash'):raise BundleCommitError('BUNDLE_CRASH_AFTER_STAGE_FSYNC')
            if self._trip('commit'):raise BundleCommitError('BUNDLE_COMMIT')
            try:os.link(stage,destination,src_dir_fd=fd,dst_dir_fd=fd,follow_symlinks=False);linked=True
            except FileExistsError:raise BundleCommitError('BUNDLE_NO_OVERWRITE',False) from None
            except OSError:raise BundleCommitError('BUNDLE_LINK_OSERROR') from None
            if self.crash_hook is not None and self.fault=='crash_post_link':self.crash_hook('post_link')
            try:os.unlink(stage,dir_fd=fd)
            except OSError:raise BundleCommitError('BUNDLE_STAGE_UNLINK_OSERROR') from None
            linked=False
            if self._trip('dir_fsync'):
                self._unlink(fd,destination,'BUNDLE_ROLLBACK_UNLINK_FAILED');self._fsync(fd);raise BundleCommitError('BUNDLE_DIR_FSYNC')
            self._fsync(fd)
            final=self._stat(fd,destination)
            if final is None or not self._safe(final,(1,)):raise BundleCommitError('BUNDLE_FINAL_LINKCOUNT',False)
            if self._read_named(fd,destination,expected)!=value:raise BundleCommitError('BUNDLE_READBACK_MISMATCH',False)
            return BundleReceipt(self.root/destination,expected,len(raw),'LINK_NO_REPLACE_SINGLE_FILE',True,True,True,recovered_fault)
        except BundleCommitError as exc:
            if stage_fd>=0:
                try:os.close(stage_fd)
                except OSError:pass
                stage_fd=-1
            if exc.recoverable and self.fault not in ('crash_stage_created','crash_post_link'):
                sm=self._stat(fd,stage);dm=self._stat(fd,destination)
                if sm is not None and dm is None:
                    if not self._safe(sm,(1,)):raise BundleCommitError('BUNDLE_STAGE_UNSAFE',False) from exc
                    self._unlink(fd,stage,'BUNDLE_STAGE_UNLINK_FAILED');self._fsync(fd)
                elif sm is not None and dm is not None:
                    if not self._safe(sm,(2,)) or not self._safe(dm,(2,)) or (sm.st_dev,sm.st_ino)!=(dm.st_dev,dm.st_ino):raise BundleCommitError('BUNDLE_CRASH_STATE_CONFLICT',False) from exc
                elif sm is None and dm is not None and linked:
                    self._unlink(fd,destination,'BUNDLE_ROLLBACK_UNLINK_FAILED');self._fsync(fd)
            raise
        finally:
            if stage_fd>=0:
                try:os.close(stage_fd)
                except OSError:pass
            os.close(fd)
def read_attempt_bundle(path:Path,expected_sha256:str)->Dict[str,Any]:
    store=AttemptBundleStore(Path(path).parent);fd=store._directory()
    try:
        value=store._read_named(fd,Path(path).name,expected_sha256);meta=store._stat(fd,Path(path).name)
        if meta is None or not store._safe(meta,(1,)):raise BundleCommitError('BUNDLE_FINAL_LINKCOUNT',False)
        return value
    finally:os.close(fd)
__all__=['AttemptBundleStore','BundleCommitError','BundleReceipt','read_attempt_bundle']
