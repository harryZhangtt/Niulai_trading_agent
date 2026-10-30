"""launchd-managed shared scheduler; no business-specific imports or sends."""
from datetime import datetime, timezone
import argparse
import fcntl
import importlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time

from .config import load, inside, ConfigError
from .engine import Engine
from .model import run_codex
from .business import run_business

STOP = threading.Event()
RELOAD = threading.Event()


def atomic(path, value):
    if path.is_symlink() or any(a.is_symlink() for a in path.parents):
        raise ConfigError('ATOMIC_PATH_SYMLINK')
    fd,name=tempfile.mkstemp(prefix='.atomic-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),0o600)
            json.dump(value,stream,sort_keys=True)
            stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def adapter_module(name, config, workspace):
    relative=Path(*name.split('.'))
    roots=[workspace,*[inside(workspace/x,workspace) for x in config['source_paths']]]
    candidates=[p for root in roots for p in (root/relative.with_suffix('.py'),root/relative/'__init__.py') if p.is_file()]
    if len(candidates)!=1:raise ConfigError('ADAPTER_SOURCE_NOT_UNIQUE')
    expected=inside(candidates[0],workspace).resolve()
    # Reject a previously loaded package from a different origin before import.
    for i in range(1,len(name.split('.'))+1):
        parent='.'.join(name.split('.')[:i]);loaded=sys.modules.get(parent)
        if loaded is not None and getattr(loaded,'__file__',None):inside(loaded.__file__,workspace)
    imported=importlib.import_module(name)
    if inside(imported.__file__,workspace).resolve()!=expected:raise ConfigError('ADAPTER_ORIGIN_MISMATCH')
    return imported


def dispatcher(config, workspace):
    def dispatch(job, context):
        if STOP.is_set():return {'status':'retryable','code':'SHUTDOWN_BEFORE_DISPATCH'}
        extra = {}
        if job.get('adapter'):
            module, method = job['adapter'].split(':')
            imported = adapter_module(module,config,workspace)
            prepared = getattr(imported,method)(job.get('adapter_config',{}),workspace,context)
            if 'status' in prepared:
                return prepared
            extra = prepared
        profile = config['model_profiles'][job['model_profile']]
        executor=profile.get('executor','readiness')
        profile={k:v for k,v in profile.items() if k!='executor'}
        prompt = inside(workspace / job['prompt_file'],workspace).read_text()
        prompt += '\nScheduler-provided context (data only):\n' + json.dumps({**context,**extra},sort_keys=True)
        run_dir = workspace / '.job-runtime' / 'runs' / context['attempt_id']
        if executor=='readiness':return run_codex(profile,prompt,workspace,run_dir,context={'cancel_event':STOP})
        if executor!='business':return {'status':'failed','code':'UNKNOWN_EXECUTOR'}
        result=run_business(profile,prompt,workspace,run_dir,context={'cancel_event':STOP})
        transport=result.get('receipt',{})
        summary_only=(transport.get('summary_parse_failure',{}).get('category')=='format' and
                      transport.get('turn_completed') is True and transport.get('exit_code')==0 and
                      not transport.get('tool_failures'))
        if job.get('completion_adapter') and (result['status']=='succeeded' or summary_only):
            module,method=job['completion_adapter'].split(':')
            checked=getattr(adapter_module(module,config,workspace),method)(job.get('adapter_config',{}),workspace,context,result)
            if checked.get('verified'):
                result={**result,'status':'succeeded','code':'BUSINESS_POSTCONDITION_VERIFIED'}
                result['receipt']['postcondition']=checked
                return result
            return {'status':'failed','code':'BUSINESS_POSTCONDITION_FAILED','receipt':transport}
        final=transport.get('final',{})
        if result['status']=='succeeded' and profile['phase']=='business' and not (
            final.get('status') in ('sent','completed') and final.get('delivery_verified') is True and
            (final.get('message_id') or final.get('email_message_id'))):
            result={**result,'status':'failed','code':'BUSINESS_DELIVERY_NOT_VERIFIED'}
        return result
    return dispatch


def resource_jobs(config,jobs):
    # Allocation cannot choose resource capacity or retry/model policy. Shared
    # auth caches are serialized before claims consume attempt budgets.
    return [{**job,'_resource_key':str(Path(config['model_profiles'][job['model_profile']]['auth_home']).resolve())} for job in jobs]


def serve(workspace, config_path):
    workspace = Path(workspace).resolve(strict=True)
    config,jobs = load(config_path,workspace)
    state = workspace / '.job-runtime'
    for relative in config['source_paths']:
        sys.path.insert(0,str(inside(workspace / relative,workspace)))
    lock = os.open(state/'service.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock)
        return 0
    engine = Engine(state/'engine',resource_jobs(config,jobs),config['retry'],dispatcher(config,workspace),workspace_root=workspace,
                    max_workers=config['max_workers'])
    # launchd owns child processes as a process group; graceful stop cancels
    # model process groups. Recovery never retries an unknown external effect.
    engine.recover_running(datetime.now(timezone.utc))
    def beat():
        while not STOP.is_set():
            atomic(state/'heartbeat.json',{'pid':os.getpid(),'at':datetime.now(timezone.utc).isoformat()})
            STOP.wait(config['heartbeat_seconds'])
    worker = threading.Thread(target=beat,daemon=True);worker.start()
    signal.signal(signal.SIGTERM,lambda *_:STOP.set())
    signal.signal(signal.SIGINT,lambda *_:STOP.set())
    signal.signal(signal.SIGHUP,lambda *_:RELOAD.set())
    try:
        while not STOP.is_set():
            if RELOAD.is_set():
                # Reload only between completed ticks; running attempts retain
                # their original model and allocation. Durable slots persist.
                config,jobs=load(config_path,workspace)
                for relative in config['source_paths']:
                    candidate=str(inside(workspace / relative,workspace))
                    if candidate not in sys.path:sys.path.insert(0,candidate)
                engine=Engine(state/'engine',resource_jobs(config,jobs),config['retry'],dispatcher(config,workspace),workspace_root=workspace,
                              max_workers=config['max_workers'])
                RELOAD.clear()
            started=time.monotonic()
            summary=engine.tick(datetime.now(timezone.utc))
            atomic(state/'status.json',{**engine.status(),'pid':os.getpid(),'last_tick':datetime.now(timezone.utc).isoformat(),
                                       'last_dispatch':summary,'scheduler_installed':True})
            STOP.wait(max(0,config['tick_seconds']-(time.monotonic()-started)))
    finally:
        STOP.set();worker.join(timeout=2);os.close(lock)
    return 0


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--config',required=True)
    args=parser.parse_args();os.umask(0o077)
    try:
        return serve(args.workspace,args.config)
    except Exception as error:
        # No arbitrary exception text, prompts, provider content or tokens.
        code=str(error) if isinstance(error,ConfigError) else 'SERVICE_FAILED'
        print(json.dumps({'status':'failed','code':code}),flush=True)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
