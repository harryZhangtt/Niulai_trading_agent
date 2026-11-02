"""Candidate native slash-selector transport. No CLI-only fallback or retry loop.

This drives the pinned interactive client through /skills; it does not put a
slash string in codex exec's prompt and call that command dispatch. Raw terminal
output stays bounded in RAM. Native Codex may persist its own private session.
"""
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import sqlite3
import struct
import subprocess
import sys
import termios
import time

from .model import ModelError, _environment, _private_path, _profile, _require, _terminate, _write
from .business import _writable_roots
from .business import SECRET

ANSI = re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def native_completion(run_dir, home, skill, prompt):
    """Read native history outside model-writable roots; never trust idle text.

    This is pinned to the observed 0.166.0 local SQLite/rollout format. A changed
    format fails closed. Only structural bindings leave the private history.
    """
    db=Path(run_dir)/'sqlite/state_5.sqlite'
    if not db.is_file():return None
    try:
        with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True,timeout=.2) as c:
            rows=c.execute('select id,rollout_path from threads where cwd=?',
                (str(Path(run_dir)/'work'),)).fetchall()
    except sqlite3.OperationalError:return None
    if not rows:return None
    _require(len(rows)==1,'SKILL_TUI_NATIVE_THREAD_AMBIGUOUS')
    thread_id,path=rows[0]
    return history_completion(Path(path),home,skill,prompt,thread_id)


def history_completion(path,home,skill,prompt,thread_id):
    path=Path(path)
    _require(path.resolve().is_relative_to(Path(home).resolve()/'sessions') and
        not path.is_symlink(),'SKILL_TUI_NATIVE_HISTORY_REJECTED')
    if not path.is_file():return None
    _require(path.stat().st_size<=8*1024*1024,'SKILL_TUI_NATIVE_HISTORY_LIMIT')
    raw=path.read_bytes();items=[]
    for line in raw.splitlines(keepends=True):
        if not line.endswith(b'\n'):break
        items.append(json.loads(line))
    starts=[];ends=[];explicit=False;attachment=False;attached_path=None
    for item in items:
        p=item.get('payload',{})
        if item.get('type')=='event_msg':
            if p.get('type')=='task_started':starts.append(p)
            if p.get('type')=='task_complete':ends.append(p)
            _require(p.get('type')!='turn_aborted','SKILL_TUI_NATIVE_TURN_ABORTED')
        if item.get('type')=='response_item' and p.get('type')=='message' and p.get('role')=='user':
            text='\n'.join(x.get('text','') for x in p.get('content',[]) if isinstance(x,dict))
            prefix='$'+skill['name']
            if text.startswith(prefix) and text[len(prefix):].strip()==prompt.strip():explicit=True
            match=re.search(r'<skill>\s*<name>'+re.escape(skill['name'])+r'</name>\s*<path>([^<]+)</path>',text)
            if match:
                attached_path=match.group(1)
                _require(sha(attached_path)==skill['sha256'],'SKILL_TUI_NATIVE_SKILL_MISMATCH')
                attachment=True
    if not ends:return None
    _require(len(starts)==len(ends)==1 and starts[0]['turn_id']==ends[0]['turn_id'],
        'SKILL_TUI_NATIVE_TURN_BINDING')
    _require(explicit and attachment,'SKILL_TUI_NATIVE_SKILL_NOT_INJECTED')
    return {'thread_id':thread_id,'turn_id':ends[0]['turn_id'],'turn_completed':True,
        'native_skill_attachment_verified':True,'native_skill_path':attached_path,
        'native_history_path':str(path),'native_started_at':starts[0].get('started_at'),
        'native_history_sha256':hashlib.sha256(raw).hexdigest(),'completed_at':ends[0].get('completed_at')}


class Terminal:
    def __init__(self, master, *, deadline, maximum, cancel=None):
        self.master, self.deadline, self.maximum, self.cancel = master, deadline, maximum, cancel
        self.total = 0
        self.hooks_skipped = False
        self.transitions = []
        self.last_stage = None
        self.terminal_queries = []
        self.startup_excerpt = None
        self.hook_skip_attempts = []

    def send(self, value):
        data = value.encode() if isinstance(value, str) else value
        view = memoryview(data)
        while view:
            _require(time.monotonic() < self.deadline, 'SKILL_TUI_DEADLINE')
            if self.cancel is not None and self.cancel.is_set():
                raise ModelError('SKILL_TUI_CANCELLED')
            if select.select([], [self.master], [], .1)[1]:
                view = view[os.write(self.master, view):]

    def wait(self, stage, predicate, *, seconds=20, external=None):
        self.last_stage = stage
        end = min(self.deadline, time.monotonic()+seconds)
        raw = bytearray()
        hook_retry_at = None
        while time.monotonic() < end:
            if external is not None:
                result=external()
                if result is not None:
                    self.transitions.append({'stage':stage,'observed_at':datetime.now(timezone.utc).isoformat(),
                        'source':'native_history'})
                    return result
            if self.cancel is not None and self.cancel.is_set():
                raise ModelError('SKILL_TUI_CANCELLED')
            if hook_retry_at is not None and time.monotonic() >= hook_retry_at:
                # Escape can only decline/close this pre-turn modal. Never
                # replay Enter or another key capable of submitting a turn.
                self.send(b'\x1b')
                self.hooks_skipped=True
                self.hook_skip_attempts.append(datetime.now(timezone.utc).isoformat())
                hook_retry_at=(time.monotonic()+2) if len(self.hook_skip_attempts)<3 else None
            if not select.select([self.master], [], [], .1)[0]:
                continue
            try:
                chunk = os.read(self.master, 65536)
            except OSError as error:
                if error.errno == errno.EIO:
                    raise ModelError('SKILL_TUI_CLOSED') from None
                raise
            _require(bool(chunk), 'SKILL_TUI_CLOSED')
            self.total += len(chunk)
            _require(self.total <= self.maximum, 'SKILL_TUI_OUTPUT_LIMIT')
            raw.extend(chunk)
            _require(len(raw) <= self.maximum, 'SKILL_TUI_OUTPUT_LIMIT')
            # Supply the device replies an interactive terminal normally sends.
            # Without these, startup probing can consume the first Escape key.
            for query,response,name in ((b'\x1b[?u',b'\x1b[?0u','keyboard'),
                (b'\x1b[c',b'\x1b[?1;2c','device'),(b'\x1b[6n',b'\x1b[1;1R','cursor')):
                if query in raw and name not in self.terminal_queries:
                    self.send(response);self.terminal_queries.append(name)
            screen=bytes(raw).rsplit(b'\x1b[1;1H\x1b[J',1)[-1]
            text = ANSI.sub(b'', screen).decode(errors='replace')
            if stage == 'ready':
                # Before any user turn/tool call, retain only a bounded screened
                # startup UI diagnostic. Never capture model/provider content.
                self.startup_excerpt='\n'.join('[redacted]' if SECRET.search(line) or
                    re.search(r'(?i)(password|api.?key|authorization|https?://)',line)
                    else line for line in text.splitlines())[-4096:]
            frame_done=raw.rfind(b'\x1b[?2026l')>raw.rfind(b'Hooks need review')
            if stage == 'ready' and 'Hooks need review' in text and frame_done and hook_retry_at is None and not self.hooks_skipped:
                # Do not grant trust or bypass hook review. Skipping is observed.
                _require('Continue' in text and 'without' in text and 'trusting' in text,
                         'SKILL_TUI_HOOK_REVIEW_REQUIRED')
                hook_retry_at=time.monotonic()+1
            _require('Unrecognized command' not in text, 'SKILL_TUI_UNSUPPORTED_SLASH')
            if predicate(bytes(raw), text):
                self.transitions.append({'stage':stage, 'observed_at':datetime.now(timezone.utc).isoformat(),
                    'terminal_bytes':len(raw), 'terminal_sha256':hashlib.sha256(raw).hexdigest()})
                return bytes(raw)
        raise ModelError('SKILL_TUI_STAGE_TIMEOUT')

    def drain(self, seconds=10):
        end=min(self.deadline,time.monotonic()+seconds)
        while time.monotonic()<end:
            if not select.select([self.master],[],[],.1)[0]:continue
            try:chunk=os.read(self.master,65536)
            except OSError as error:
                if error.errno==errno.EIO:return
                raise
            if not chunk:return
            self.total+=len(chunk)
            _require(self.total<=self.maximum,'SKILL_TUI_OUTPUT_LIMIT')
        raise ModelError('SKILL_TUI_SHUTDOWN_TIMEOUT')


def run(profile, prompt, skill, *, workspace, run_directory, expected_cli_sha256, cancel=None, host_tick=None):
    """One candidate attempt. Caller owns schedule/retry and business verification.

    Only auth-cache contention is retryable. Once Enter may have submitted a turn,
    failures are unknown and held. A TUI idle observation is not by itself a
    turn/completed event or independent business acceptance.
    """
    receipt = {'schema_version':1, 'started_at':datetime.now(timezone.utc).isoformat(),
        'route':'native_tui_slash', 'slash_command':'/skills', 'skill_selected':False,
        'turn_submitted':False, 'turn_idle_observed':False, 'turn_completed':None,
        'thread_id':None, 'automatic_retry':False, 'fallback_used':False,
        'process_cleanup_verified':False, 'effect_state':'not_started'}
    process = None; lock_fd = None; master = None; slave = None; terminal = None
    try:
        workspace = Path(workspace).resolve(strict=True)
        _require(type(profile) is dict and set(profile) == {'codex_bin','model','effort','timeout_seconds',
            'auth_home','max_output_bytes','approval_mode','writable_roots'}, 'SKILL_TUI_PROFILE_INVALID')
        base = {key:value for key,value in profile.items() if key not in ('approval_mode','writable_roots')}
        binary, home, timeout, maximum = _profile(base, workspace)
        _require(profile['approval_mode'] in ('never','automatic_review'), 'SKILL_TUI_APPROVAL_INVALID')
        _require(sha(binary) == expected_cli_sha256, 'SKILL_TUI_CLI_CHANGED')
        _require(type(skill) is dict and set(skill) == {'name','path','sha256'} and
            isinstance(skill['name'], str) and re.fullmatch('[a-z0-9][a-z0-9-]{0,63}',skill['name']), 'SKILL_TUI_SKILL_INVALID')
        _require(Path(skill['path']).is_file() and sha(skill['path']) == skill['sha256'], 'SKILL_TUI_SKILL_CHANGED')
        _require(isinstance(prompt,str) and 0<len(prompt.encode())<=16384 and
            not re.search(r'[\x00-\x08\x0b-\x1f\x7f]', prompt), 'SKILL_TUI_PROMPT_INVALID')
        roots = _writable_roots({'shell':True,'writable_roots':profile['writable_roots']}, workspace, home)
        lock_fd=os.open(home/'runtime.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try: fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status':'retryable','code':'MODEL_AUTH_CACHE_BUSY','receipt':receipt}
        run_dir = _private_path(run_directory,workspace)
        _require(not run_dir.exists(),'SKILL_TUI_RUN_EXISTS')
        run_dir = _private_path(run_dir,workspace,directory=True)
        receipt.update(cli_sha256=expected_cli_sha256, requested_model=profile['model'], skill=skill,
            prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(), run_directory=str(run_dir.relative_to(workspace)))
        _write(run_dir/'intent.json',json.dumps(receipt,sort_keys=True))
        work = run_dir/'work'; work.mkdir(mode=0o700)
        env = _environment(workspace,home,run_dir); env.update(TERM='xterm-256color',RUST_LOG='off')
        command=[str(binary),'--no-daemon','--no-alt-screen','--strict-config','--cd',str(work),'--model',profile['model']]
        if profile['approval_mode']=='automatic_review': command+=['--approve-for-me']
        else: command+=['--sandbox','workspace-write','--ask-for-approval','never']
        for root in roots: command+=['--add-dir',str(root)]
        overrides={'model_reasoning_effort':profile['effort'],'web_search':'disabled','features.shell_tool':True,
            'features.shell_snapshot':False,'features.apps':False,'mcp_servers':{},'history.persistence':'none',
            'sqlite_home':env['CODEX_SQLITE_HOME'],'check_for_update_on_startup':False,
            'sandbox_workspace_write.network_access':True}
        for key,value in overrides.items():command+=['-c',key+'='+json.dumps(value)]
        master,slave=pty.openpty()
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',40,120,0,0))
        # A PTY fd alone is not a controlling terminal after setsid(). Codex
        # keyboard input needs /dev/tty. A tiny exec bootstrap acquires it in
        # the child, avoiding preexec_fn (unsafe in scheduler worker threads).
        bootstrap='import fcntl,termios,os,sys;fcntl.ioctl(0,termios.TIOCSCTTY,0);os.execv(sys.argv[1],sys.argv[1:])'
        process=subprocess.Popen([sys.executable,'-B','-c',bootstrap,*command],stdin=slave,stdout=slave,stderr=slave,env=env,cwd=work,
            start_new_session=True,pass_fds=(lock_fd,))
        os.close(slave);slave=None
        terminal=Terminal(master,deadline=time.monotonic()+timeout,maximum=maximum,cancel=cancel)
        terminal.wait('ready',lambda raw,text:b'state=idle:app=codex' in raw or
            ('Ask Codex to do anything' in text and 'GPT-' in text and
             'Hooks need review' not in text and 'loading' not in text),seconds=min(timeout,45))
        terminal.send('/skills')
        terminal.wait('slash_offered',lambda raw,text:'/skills' in text and 'use skills' in text)
        terminal.send('\r')
        terminal.wait('slash_menu',lambda raw,text:'Skills' in text and 'Choose an action' in text)
        terminal.send('\r')
        terminal.wait('skill_picker',lambda raw,text:'insert' in text and '$' in text)
        terminal.send(skill['name'])
        terminal.wait('skill_filter',lambda raw,text:skill['name'] in text)
        terminal.send('\r')
        terminal.wait('skill_selected',lambda raw,text:'$'+skill['name'] in text)
        receipt['skill_selected']=True
        _require(sha(skill['path'])==skill['sha256'],'SKILL_TUI_SKILL_CHANGED')
        terminal.send(' \x1b[200~'+prompt+'\x1b[201~')
        # Long pastes collapse into a UI chip. The protected native history
        # later verifies the complete exact prompt; the composer only acks input.
        terminal.wait('task_pasted',lambda raw,text:'Pasted' in text or prompt.split()[0] in text)
        # Durable uncertainty fence precedes the key that can start model work.
        _write(run_dir/'turn-intent.json',json.dumps({'prompt_sha256':receipt['prompt_sha256'],
            'skill':skill,'at':datetime.now(timezone.utc).isoformat()},sort_keys=True))
        receipt.update(turn_submitted=True,effect_state='unknown')
        terminal.send('\r')
        def observed_completion():
            remaining=terminal.deadline-time.monotonic()
            _require(remaining>0,'SKILL_TUI_DEADLINE')
            if host_tick is not None:host_tick(remaining)
            return native_completion(run_dir,home,skill,prompt)
        completion=terminal.wait('turn_complete',lambda raw,text:False,seconds=timeout,external=observed_completion)
        receipt.update(completion)
        terminal.send('\x01\x0b/quit')
        terminal.wait('quit_offered',lambda raw,text:'/quit' in text and 'exit Codex' in text)
        terminal.send('\r')
        terminal.drain()
        process.wait(timeout=5)
        receipt['exit_code']=process.returncode
        _require(process.returncode==0,'SKILL_TUI_EXIT_FAILED')
        _require(sha(binary)==expected_cli_sha256 and sha(skill['path'])==skill['sha256'],'SKILL_TUI_PIN_CHANGED')
        receipt['cli_exit_verified']=True
        check=subprocess.run(['/bin/ps','-g',str(process.pid),'-o','pid=,stat='],capture_output=True,text=True,timeout=3)
        receipt['process_cleanup_verified']=check.returncode in (0,1) and not check.stdout.strip()
        _require(receipt['process_cleanup_verified'],'SKILL_TUI_PROCESS_GROUP_REMAINS')
        return {'status':'succeeded','code':'SLASH_SELECTOR_TURN_RETURNED','receipt':receipt}
    except ModelError as error:
        return {'status':'unknown' if receipt['turn_submitted'] else 'failed','code':str(error),'receipt':receipt}
    except Exception:
        return {'status':'unknown' if receipt['turn_submitted'] else 'failed','code':'SKILL_TUI_FAILED','receipt':receipt}
    finally:
        if process is not None and process.returncode is None:
            try:
                _terminate(process)
                receipt['cli_terminated']=True
            except Exception:
                receipt['cleanup_code']='SKILL_TUI_CLEANUP_UNVERIFIED'
                # Darwin can reject killpg for a zombie-only group. Reap our
                # exact owned leader; do not claim descendants were verified.
                try:
                    process.kill()
                    process.wait(timeout=5)
                except ProcessLookupError:
                    process.wait(timeout=5)
                except Exception:
                    receipt['cleanup_code']='SKILL_TUI_LEADER_REAP_UNVERIFIED'
        if terminal is not None:
            receipt.update(transitions=terminal.transitions,terminal_bytes=terminal.total,
                last_stage=terminal.last_stage,hooks_skipped_untrusted=terminal.hooks_skipped)
            receipt['terminal_queries_answered']=terminal.terminal_queries
            receipt['hook_skip_attempts']=terminal.hook_skip_attempts
            if terminal.last_stage=='ready' and not receipt['turn_submitted']:
                receipt['startup_diagnostic']=terminal.startup_excerpt
        receipt['ended_at']=datetime.now(timezone.utc).isoformat()
        for fd in (master,slave,lock_fd):
            if fd is not None:os.close(fd)
