"""Fixture-only verified-executable controller with bounded process-group eradication."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, os, signal, stat, subprocess, time
from pathlib import Path
from typing import Dict, Mapping, Optional
from .contracts import ContractError, EffectGuard, ExecutionBinding, require

@dataclass(frozen=True)
class ProcessPlan:
    argv: tuple; environment: Mapping[str,str]; cwd: str; stdin: bytes; shell: bool=False; new_process_group: bool=True; total_timeout_seconds:float=5.0; fixture_port:int=0; scenario:str='nominal'; stdout_path:Optional[str]=None; stderr_path:Optional[str]=None; expected_binary_bytes:int=0; expected_binary_sha256:str=''; expected_binary_mode:int=0o755; expected_binary_uid:int=-1
@dataclass(frozen=True)
class PreparedExecutable:
    original_path:str; private_path:str; bytes:int; sha256:str; mode:int; uid:int
@dataclass(frozen=True)
class ProcessResult:
    started:bool; stdout:bytes; stderr:bytes; exit_code:int; timed_out:bool; process_group_reaped:bool; descendants_reaped:bool; descriptors_closed:bool; actual_binary_path:str; actual_binary_sha256:str; pid:int=0; pgid:int=0; child_pid:int=0; effective_argv:tuple=(); environment_keys:tuple=(); stdin_bytes:int=0; pid_gone:bool=False; child_pid_gone:bool=False; executed_private_copy:bool=False

class FixtureProcessController:
    def __init__(self,binding:ExecutionBinding,guard:EffectGuard)->None:
        self.binding=binding; self.guard=guard; self.active=None; self.pgid=0; self.last=None; self.prepared=None; self.cleanup_history=[]
    @staticmethod
    def _exists_pid(pid:int)->bool:
        if pid<=0: return False
        try: os.kill(pid,0); return True
        except ProcessLookupError: return False
        except PermissionError: return True
    @staticmethod
    def _exists_group(pgid:int)->bool:
        if pgid<=0: return False
        try: os.killpg(pgid,0); return True
        except ProcessLookupError: return False
        except PermissionError: return True
    @staticmethod
    def _sync_dir(path:Path)->None:
        fd=os.open(path,os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    def prepare_verified_binary(self,plan:ProcessPlan)->PreparedExecutable:
        self.guard.check('before_binary_verify')
        source=Path(plan.argv[0]); flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)
        try: fd=os.open(source,flags)
        except OSError as exc: raise ContractError('BINARY_NOFOLLOW_REJECTED') from exc
        try:
            info=os.fstat(fd); require(stat.S_ISREG(info.st_mode),'BINARY_NOT_REGULAR'); require(info.st_uid==plan.expected_binary_uid,'BINARY_OWNER_DRIFT'); require(stat.S_IMODE(info.st_mode)==plan.expected_binary_mode,'BINARY_MODE_DRIFT')
            chunks=[]
            while True:
                chunk=os.read(fd,1024*1024)
                if not chunk: break
                chunks.append(chunk)
            raw=b''.join(chunks); require(len(raw)==plan.expected_binary_bytes and hashlib.sha256(raw).hexdigest()==plan.expected_binary_sha256,'BINARY_IDENTITY_DRIFT')
        finally: os.close(fd)
        private=Path(plan.stderr_path).parent/('.held-exec-'+plan.expected_binary_sha256[:16]); out=os.open(private,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o700)
        try:
            view=memoryview(raw)
            while view:
                n=os.write(out,view); require(n>0,'BINARY_COPY_SHORT_WRITE'); view=view[n:]
            os.fsync(out)
        finally: os.close(out)
        os.chmod(private,0o700); self._sync_dir(private.parent)
        copied=private.read_bytes(); require(hashlib.sha256(copied).hexdigest()==plan.expected_binary_sha256,'BINARY_COPY_DRIFT')
        self.prepared=PreparedExecutable(str(source),str(private),len(raw),plan.expected_binary_sha256,plan.expected_binary_mode,plan.expected_binary_uid)
        self.guard.check('after_binary_verify'); return self.prepared
    def _bounded_reap(self,pgid:int,child_pid:int,grace:float=.25,forced:float=1.5)->Dict[str,bool]:
        if self._exists_group(pgid):
            try: os.killpg(pgid,signal.SIGTERM)
            except ProcessLookupError: pass
            end=time.monotonic()+grace
            while time.monotonic()<end and self._exists_group(pgid): time.sleep(.02)
        if self._exists_group(pgid):
            try: os.killpg(pgid,signal.SIGKILL)
            except ProcessLookupError: pass
        end=time.monotonic()+forced
        while time.monotonic()<end and (self._exists_group(pgid) or self._exists_pid(child_pid)): time.sleep(.02)
        return {'group_gone':not self._exists_group(pgid),'child_pid_gone':not self._exists_pid(child_pid)}
    def run(self,plan:ProcessPlan)->ProcessResult:
        require(plan.shell is False and plan.new_process_group and plan.fixture_port>0 and self.prepared is not None,'PROCESS_PLAN_INVALID'); self.guard.check('before_process_start')
        argv=[self.prepared.private_path]+list(plan.argv[1:])+['--fixture-port',str(plan.fixture_port),'--scenario',plan.scenario,'--fingerprint',self.binding.request_fingerprint,'--admission',hashlib.sha256((self.binding.operation_id+self.binding.request_fingerprint).encode()).hexdigest()]
        env={k:v for k,v in plan.environment.items()}; out=open(plan.stdout_path,'xb',buffering=0); err=open(plan.stderr_path,'xb',buffering=0); os.chmod(plan.stdout_path,0o600); os.chmod(plan.stderr_path,0o600); timed=False; child_pid=0
        try:
            p=subprocess.Popen(argv,cwd=plan.cwd,env=env,stdin=subprocess.PIPE,stdout=out,stderr=err,shell=False,start_new_session=True,close_fds=True); self.active=p; self.pgid=os.getpgid(p.pid); self.guard.observe('after_process_start')
            try: p.communicate(plan.stdin,timeout=plan.total_timeout_seconds)
            except subprocess.TimeoutExpired: timed=True
            if timed and p.poll() is None:
                try: os.killpg(self.pgid,signal.SIGTERM)
                except ProcessLookupError: pass
                try: p.wait(timeout=.25)
                except subprocess.TimeoutExpired:
                    try: os.killpg(self.pgid,signal.SIGKILL)
                    except ProcessLookupError: pass
                    p.wait(timeout=1)
            else: p.wait(timeout=1)
            exit_code=p.returncode if p.returncode is not None else -signal.SIGKILL
        finally: out.close(); err.close()
        stderr=Path(plan.stderr_path).read_bytes(); stdout=Path(plan.stdout_path).read_bytes()
        for line in stderr.decode('utf-8','replace').splitlines():
            if line.startswith('CHILD_PID='):
                try: child_pid=int(line.split('=',1)[1])
                except ValueError: pass
        eradicated=self._bounded_reap(self.pgid,child_pid); pid_gone=not self._exists_pid(p.pid)
        result=ProcessResult(True,stdout,stderr,exit_code,timed,eradicated['group_gone'],eradicated['group_gone'] and eradicated['child_pid_gone'],True,self.prepared.original_path,self.prepared.sha256,p.pid,self.pgid,child_pid,tuple(argv),tuple(sorted(env)),len(plan.stdin),pid_gone,eradicated['child_pid_gone'],True)
        self.last=result; return result
    def close(self)->Dict[str,object]:
        self.guard.observe('before_process_cleanup')
        if self.active and self.active.poll() is None:
            try: os.killpg(self.pgid,signal.SIGKILL)
            except ProcessLookupError: pass
            try: self.active.wait(timeout=1)
            except subprocess.TimeoutExpired: pass
        child=self.last.child_pid if self.last else 0; eradicated=self._bounded_reap(self.pgid,child); pid=self.last.pid if self.last else 0; pid_gone=not self._exists_pid(pid)
        copy_removed=True
        if self.prepared:
            private=Path(self.prepared.private_path)
            try: private.unlink()
            except FileNotFoundError: pass
            self._sync_dir(private.parent); copy_removed=not private.exists()
        on_time=self.guard.observe('after_process_cleanup'); self.active=None
        receipt={'cleanup_deadline_ok':on_time,'process_active':False,'process_group_reaped':eradicated['group_gone'],'descendants_reaped':eradicated['group_gone'] and eradicated['child_pid_gone'],'descriptors_closed':True,'pid_gone':pid_gone,'child_pid_gone':eradicated['child_pid_gone'],'verified_copy_removed':copy_removed}
        self.cleanup_history.append(receipt); return receipt
