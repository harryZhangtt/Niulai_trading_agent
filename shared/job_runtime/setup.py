"""Prepare private runtime configuration; never starts services or overwrites auth."""
import argparse,hashlib,json,os,shutil,stat,subprocess
from pathlib import Path

def create_json_once(path,value):
    try:fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    except FileExistsError:return False
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream,indent=2,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    return True

def _directories(root):
    state=root/'.job-runtime'
    for name in ('','config','config/prompts','codex-home','claude-home','logs','runs','tmp','launchd','tests','setup'):
        directory=state/name
        if directory.is_symlink():raise ValueError('STATE_SYMLINK_REJECTED')
        directory.mkdir(mode=0o700,parents=True,exist_ok=True);directory.chmod(0o700)
    return state

def _provider_identity(binary):
    binary=Path(binary).resolve(strict=True)
    if not binary.is_file() or not os.access(binary,os.X_OK):raise ValueError('PROVIDER_BINARY_REQUIRED')
    raw=binary.read_bytes();result=subprocess.run([str(binary),'--version'],capture_output=True,text=True,timeout=15)
    if result.returncode:raise ValueError('PROVIDER_VERSION_UNAVAILABLE')
    return binary,{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'version':(result.stdout or result.stderr).strip()[:160]}

def _seed_auth(source,target):
    if not source:return False
    source=Path(source).resolve(strict=True);info=source.stat()
    if (not source.is_file() or source.is_symlink() or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077 or not 0<info.st_size<=1024*1024):raise ValueError('AUTH_SOURCE_INVALID')
    if target.exists():return False
    before=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with source.open('rb') as src,os.fdopen(fd,'wb') as dst:shutil.copyfileobj(src,dst);dst.flush();os.fsync(dst.fileno())
    after=source.stat()
    if before!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):target.unlink(missing_ok=True);raise ValueError('AUTH_SOURCE_CHANGED')
    return True

def prepare(workspace,*,schema_version=2,provider='claude-host',provider_bin=None,model='claude-opus-5-5',auth_source=None,allocation_files=None,source_paths=None):
    root=Path(workspace).resolve(strict=True);state=_directories(root);python=(state/'.venv/bin/python').resolve(strict=True)
    if not python.is_relative_to(state):raise ValueError('WORKSPACE_PYTHON_REQUIRED')
    provider_name=provider.replace('-','_')
    if provider_name not in ('codex_cli','claude_host') or schema_version not in (1,2):raise ValueError('SETUP_PROFILE_INVALID')
    identity=None;binary=None
    if provider_name=='codex_cli':binary,identity=_provider_identity(provider_bin)
    elif schema_version==1:raise ValueError('SCHEMA1_CODEX_REQUIRED')
    home=state/('codex-home' if provider_name=='codex_cli' else 'claude-home');target=home/'auth.json';seeded=_seed_auth(auth_source,target)
    allocation=state/'config'/f'jobs-v{schema_version}.json';create_json_once(allocation,{'schema_version':schema_version,'jobs':[]})
    config=state/'config'/'runtime.json'
    if schema_version==1:
        profile={'codex_bin':str(binary),'model':model,'effort':'low','timeout_seconds':120,'auth_home':str(home)}
        retry={'max_attempts':3,'backoff_seconds':30,'max_backoff_seconds':120}
    else:
        profile={'provider':provider_name,'model':model,'effort':'low','timeout_seconds':120,'auth_home':str(home),'circuit':{'failure_threshold':3,'open_seconds':60,'probe_seconds':10}}
        if provider_name=='claude_host':profile['max_budget_usd']=1.0
        if provider_name=='codex_cli':profile.update(codex_bin=str(binary))
        retry={'version':2,'max_attempts':1,'base_delay_seconds':5,'max_delay_seconds':30,'deadline_seconds':300,'jitter':'sha256-full-jitter-v1'}
    value={'schema_version':schema_version,'python_bin':str(python),'tick_seconds':5,'heartbeat_seconds':5,'stale_seconds':90,'max_workers':2,'retry':retry,'model_profiles':{'default':profile},'allocation_files':allocation_files or [str(allocation.relative_to(root))],'source_paths':source_paths or []}
    created=create_json_once(config,value)
    from .config import load
    loaded,_=load(config,root)
    receipt={'schema_version':1,'prepared':True,'configuration_created':created,'runtime_schema':loaded['schema_version'],'provider':provider_name,'provider_identity':identity,'auth_present':target.is_file(),'auth_seeded_once':seeded,'services_started':False}
    create_json_once(state/'setup/provider.json',receipt)
    return receipt

def inspect(workspace):
    root=Path(workspace).resolve(strict=True);state=root/'.job-runtime';config=state/'config/runtime.json'
    if not config.is_file():return {'schema_version':1,'status':'missing','prepared':False}
    try:
        from .config import load_projection
        value,_=load_projection(config,root)
    except Exception:return {'schema_version':1,'status':'invalid','prepared':False}
    profile=next(iter(value['model_profiles'].values()));home=Path(profile['auth_home'])
    return {'schema_version':1,'status':'ready','prepared':True,'runtime_schema':value['schema_version'],'provider':profile.get('provider','codex_cli'),'auth_present':(home/'auth.json').is_file(),'services_started':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',required=True);p.add_argument('--codex-bin');p.add_argument('--provider',choices=['codex-cli','claude-host']);p.add_argument('--schema-version',type=int,choices=[1,2]);p.add_argument('--auth-source',type=Path);p.add_argument('--model');p.add_argument('--allocation',action='append',default=[]);p.add_argument('--source-path',action='append',default=[])
    a=p.parse_args();os.umask(0o077)
    provider=a.provider or ('codex-cli' if a.codex_bin else 'claude-host')
    schema=a.schema_version or (1 if provider=='codex-cli' and a.codex_bin else 2)
    model=a.model or ('gpt-6.1-sol' if provider=='codex-cli' else 'claude-opus-5-5')
    try:print(json.dumps(prepare(a.workspace,schema_version=schema,provider=provider,provider_bin=a.codex_bin,model=model,auth_source=a.auth_source,allocation_files=a.allocation or None,source_paths=a.source_path),sort_keys=True,separators=(',',':')));return 0
    except Exception:print(json.dumps({'status':'failed','code':'SETUP_PREPARATION_FAILED'}));return 2
if __name__=='__main__':raise SystemExit(main())
