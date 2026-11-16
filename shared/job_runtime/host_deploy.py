"""Materialize an owner-private macOS host bundle outside protected checkout paths."""
from __future__ import annotations
import hashlib,json,os,secrets,shutil,stat
from pathlib import Path,PurePosixPath
from .config import inside,load_projection

class HostDeployError(ValueError):pass

def _canonical(value):return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
def _sha(raw):return hashlib.sha256(raw).hexdigest()
def _write(path,value):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True);raw=_canonical(value)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    return _sha(raw)
def _inventory(root):
    rows=[]
    for path in sorted(root.rglob('*')):
        if path.is_symlink():raise HostDeployError('HOST_DEPLOY_SYMLINK_REJECTED')
        if path.is_file():
            raw=path.read_bytes();rows.append({'path':path.relative_to(root).as_posix(),'sha256':_sha(raw),'bytes':len(raw)})
    return rows
def _relative(value):
    if type(value) is not str:raise HostDeployError('HOST_DEPLOY_PATH_INVALID')
    path=PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in ('','.','..') for part in path.parts):raise HostDeployError('HOST_DEPLOY_PATH_INVALID')
    return Path(*path.parts)
def _copy_file(source_root,destination_root,relative):
    relative=_relative(relative);source=inside(source_root/relative,source_root);destination=(destination_root/relative).absolute()
    if source.is_symlink() or not source.is_file() or not destination.is_relative_to(destination_root.absolute()):raise HostDeployError('HOST_DEPLOY_PATH_INVALID')
    for parent in [source,*source.parents]:
        if parent==source_root:break
        if parent.is_symlink():raise HostDeployError('HOST_DEPLOY_SYMLINK_REJECTED')
    destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if destination.exists() or destination.is_symlink():raise HostDeployError('HOST_DEPLOY_DESTINATION_CONFLICT')
    shutil.copy2(source,destination,follow_symlinks=False)
def _read_receipt(path):
    try:info=os.lstat(path)
    except OSError:raise HostDeployError('HOST_DEPLOY_RECEIPT_INVALID') from None
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077 or not 0<info.st_size<=65536:raise HostDeployError('HOST_DEPLOY_RECEIPT_INVALID')
    try:value=json.loads(path.read_text())
    except Exception:raise HostDeployError('HOST_DEPLOY_RECEIPT_INVALID') from None
    keys={'schema_version','status','workspace_id','service_label','watchdog_label','provider','credentials_copied','persistent_links','source_files','source_sha256','python_files','python_sha256','config_sha256'}
    if type(value) is not dict or set(value)!=keys or value['schema_version']!=1 or value['status']!='prepared':raise HostDeployError('HOST_DEPLOY_RECEIPT_INVALID')
    return value
def _verify_existing(base,identity):
    value=_read_receipt(base/'deployment-receipt.json');root=base/'workspace'
    if value['workspace_id']!=identity or root.is_symlink() or not root.is_dir():raise HostDeployError('HOST_DEPLOY_STALE')
    source_rows=_inventory(root/'shared');python_rows=_inventory(root/'.job-runtime/.venv');config=root/'.job-runtime/config/runtime.json'
    if (len(source_rows)!=value['source_files'] or _sha(_canonical(source_rows))!=value['source_sha256'] or len(python_rows)!=value['python_files'] or _sha(_canonical(python_rows))!=value['python_sha256'] or not config.is_file() or _sha(config.read_bytes())!=value['config_sha256']):raise HostDeployError('HOST_DEPLOY_STALE')
    return value

def materialize(source_workspace,*,external_root=None):
    source=Path(source_workspace).resolve(strict=True);state=source/'.job-runtime';config_path=state/'config/runtime.json'
    if not config_path.is_file() or not (state/'.venv/bin/python').exists():raise HostDeployError('HOST_DEPLOY_SOURCE_INVALID')
    config,jobs=load_projection(config_path,source)
    identity=_sha(str(source).encode())[:16];base=Path(external_root).expanduser().absolute() if external_root else Path.home()/'Library/Application Support/TradingAgentScheduler'/identity
    if base.exists():return _verify_existing(base,identity)
    parent=base.parent;parent.mkdir(mode=0o700,parents=True,exist_ok=True);parent.chmod(0o700)
    stage=parent/('.'+base.name+'.staging-'+secrets.token_hex(12));destination=stage/'workspace'
    try:
        destination.mkdir(parents=True,mode=0o700);destination=destination.resolve();final_destination=base.parent.resolve()/base.name/'workspace';(destination/'shared').mkdir(mode=0o700)
        repo=Path(__file__).resolve().parents[2]
        if any(path.is_symlink() for path in (repo/'shared/job_runtime').rglob('*')):raise HostDeployError('HOST_DEPLOY_SYMLINK_REJECTED')
        shutil.copy2(repo/'shared/exact_source.py',destination/'shared/exact_source.py',follow_symlinks=False)
        shutil.copytree(repo/'shared/job_runtime',destination/'shared/job_runtime',symlinks=False,ignore=shutil.ignore_patterns('tests','candidates','__pycache__','*.pyc'))
        target_state=destination/'.job-runtime';shutil.copytree(state/'.venv',target_state/'.venv',symlinks=False,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for name in ('config','logs','runs','tmp','launchd','setup','codex-home','claude-home'):(target_state/name).mkdir(parents=True,exist_ok=True,mode=0o700)
        config=json.loads(config_path.read_text());config['python_bin']=str(target_state/'.venv/bin/python')
        providers=[]
        for profile in config['model_profiles'].values():
            profile_provider=profile.get('provider','codex_cli');providers.append(profile_provider)
            profile['auth_home']=str(target_state/('claude-home' if profile_provider=='claude_host' else 'codex-home'))
        for relative in config['allocation_files']:_copy_file(source,destination,relative)
        for job in jobs:
            prompt=job.get('prompt_file')
            if isinstance(prompt,str) and not Path(prompt).is_absolute():_copy_file(source,destination,prompt)
        target_config=target_state/'config/runtime.json';target_config.write_bytes(_canonical(config))
        for path in destination.rglob('*'):
            if path.is_dir():path.chmod(0o700)
            elif path.is_file():path.chmod(0o700 if path.stat().st_mode&stat.S_IXUSR else 0o600)
        # Validate equivalent staging paths, then bind published bytes to final paths.
        load_projection(target_config,destination)
        final_config=json.loads(json.dumps(config));final_config['python_bin']=str(final_destination/'.job-runtime/.venv/bin/python')
        for profile in final_config['model_profiles'].values():
            profile_provider=profile.get('provider','codex_cli')
            profile['auth_home']=str(final_destination/'.job-runtime'/('claude-home' if profile_provider=='claude_host' else 'codex-home'))
        target_config.write_bytes(_canonical(final_config));target_config.chmod(0o600)
        source_rows=_inventory(destination/'shared');python_rows=_inventory(target_state/'.venv');label='com.local.trading-agent.job-runtime.'+identity
        provider='mixed' if len(set(providers))>1 else providers[0]
        receipt={'schema_version':1,'status':'prepared','workspace_id':identity,'service_label':label,'watchdog_label':label+'.watchdog','provider':provider,'credentials_copied':False,'persistent_links':False,'source_files':len(source_rows),'source_sha256':_sha(_canonical(source_rows)),'python_files':len(python_rows),'python_sha256':_sha(_canonical(python_rows)),'config_sha256':_sha(target_config.read_bytes())}
        _write(stage/'deployment-receipt.json',receipt)
        os.replace(stage,base);stage=None
        dirfd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);os.fsync(dirfd);os.close(dirfd)
        pointer=state/'setup/host-deployment.json'
        if not pointer.exists():_write(pointer,{'schema_version':1,'workspace_id':identity,'receipt_sha256':_sha((base/'deployment-receipt.json').read_bytes()),'service_label':label})
        return receipt
    finally:
        if stage is not None:shutil.rmtree(stage,ignore_errors=True)
