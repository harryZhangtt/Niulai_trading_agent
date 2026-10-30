"""Prepare private runtime configuration; never starts services or overwrites auth."""
import argparse,json,os,shutil
from pathlib import Path

def create_json_once(path,value):
    try:fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    except FileExistsError:return False
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream,indent=2);stream.flush();os.fsync(stream.fileno())
    return True

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',required=True);p.add_argument('--codex-bin',required=True)
    p.add_argument('--auth-source',type=Path);p.add_argument('--model',default='gpt-6.1-sol')
    p.add_argument('--allocation',action='append',default=[]);p.add_argument('--source-path',action='append',default=[])
    a=p.parse_args();os.umask(0o077);root=Path(a.workspace).resolve(strict=True);state=root/'.job-runtime'
    for name in ('','config','codex-home','logs','runs','tmp','launchd','tests'):
        directory=state/name
        if directory.is_symlink():raise ValueError('STATE_SYMLINK_REJECTED')
        directory.mkdir(mode=0o700,parents=True,exist_ok=True);directory.chmod(0o700)
    python=(state/'.venv/bin/python').resolve(strict=True)
    if not python.is_relative_to(state):raise ValueError('WORKSPACE_PYTHON_REQUIRED')
    binary=Path(a.codex_bin).absolute()
    if not binary.is_file() or not os.access(binary,os.X_OK):raise ValueError('CODEX_BINARY_REQUIRED')
    target=state/'codex-home/auth.json';seeded=False
    if target.is_symlink():raise ValueError('AUTH_TARGET_SYMLINK')
    if not target.exists() and a.auth_source:
        if not a.auth_source.is_file() or a.auth_source.is_symlink():raise ValueError('AUTH_SOURCE_INVALID')
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with a.auth_source.open('rb') as src,os.fdopen(fd,'wb') as dst:shutil.copyfileobj(src,dst)
        seeded=True
    config=state/'config/runtime.json'
    if config.is_symlink():raise ValueError('CONFIG_SYMLINK_REJECTED')
    if not config.exists():
        empty=state/'config/empty-jobs.json'
        if empty.is_symlink():raise ValueError('ALLOCATION_SYMLINK_REJECTED')
        create_json_once(empty,{'schema_version':1,'jobs':[]})
        value={'schema_version':1,'python_bin':str(python),'tick_seconds':5,'heartbeat_seconds':5,'stale_seconds':90,'max_workers':2,
          'retry':{'max_attempts':3,'backoff_seconds':30,'max_backoff_seconds':120},
          'model_profiles':{'default':{'codex_bin':str(binary),'model':a.model,'effort':'low','timeout_seconds':120,'auth_home':str(state/'codex-home')}},
          'allocation_files':a.allocation or ['.job-runtime/config/empty-jobs.json'],'source_paths':a.source_path}
        create_json_once(config,value)
    from .config import load
    load(config,root)
    print(json.dumps({'prepared':True,'auth_present':target.is_file(),'auth_seeded_once':seeded,'services_started':False}))

if __name__=='__main__':
    try:main()
    except Exception:
        print(json.dumps({'status':'failed','code':'SETUP_PREPARATION_FAILED'}));raise SystemExit(2)
