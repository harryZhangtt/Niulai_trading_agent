"""Workspace-local scheduler dependency bootstrap; never installs globally."""
import argparse,hashlib,json,os,stat,subprocess,sys
from pathlib import Path

PYTHON_VERSION='3.12.16'
class BootstrapError(ValueError):pass

def _private(path):
    if path.is_symlink():raise BootstrapError('BOOTSTRAP_SYMLINK_REJECTED')
    path.mkdir(mode=0o700,parents=True,exist_ok=True);path.chmod(0o700);return path
def _run(command,*,env,timeout=600):
    value=subprocess.run(command,env=env,capture_output=True,text=True,timeout=timeout)
    if value.returncode:raise BootstrapError('BOOTSTRAP_COMMAND_FAILED')
    return value
def _identity(path,state):
    resolved=Path(path).resolve(strict=True)
    if not resolved.is_relative_to(state.resolve()):raise BootstrapError('BOOTSTRAP_PATH_INVALID')
    info=resolved.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o022 or not os.access(resolved,os.X_OK):raise BootstrapError('BOOTSTRAP_FILE_INVALID')
    raw=resolved.read_bytes();return {'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
def _receipt(path):
    try:info=os.lstat(path)
    except OSError:raise BootstrapError('BOOTSTRAP_RECEIPT_INVALID') from None
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077 or not 0<info.st_size<=65536:raise BootstrapError('BOOTSTRAP_RECEIPT_INVALID')
    try:value=json.loads(path.read_text())
    except Exception:raise BootstrapError('BOOTSTRAP_RECEIPT_INVALID') from None
    keys={'schema_version','status','python_version','python','uv_version','uv','requirements_sha256','global_install'}
    if type(value) is not dict or set(value)!=keys or value['schema_version']!=1 or value['status']!='prepared' or value['global_install'] is not False:raise BootstrapError('BOOTSTRAP_RECEIPT_INVALID')
    return value
def _version(command,env):
    value=_run(command,env=env,timeout=30);return (value.stdout or value.stderr).strip()

def inspect(workspace):
    root=Path(workspace).resolve(strict=True);state=root/'.job-runtime';receipt_path=state/'setup/dependencies.json'
    if not receipt_path.exists():return {'schema_version':1,'status':'missing','prepared':False}
    try:
        value=_receipt(receipt_path);python=state/'.venv/bin/python';uv=state/'bootstrap/bin/uv';requirements=root/'shared/job_runtime/bootstrap-requirements.txt'
        env={'PATH':os.environ.get('PATH','/usr/bin:/bin')}
        python_id=_identity(python,state);uv_id=_identity(uv,state)
        if python_id!=value['python'] or uv_id!=value['uv'] or hashlib.sha256(requirements.read_bytes()).hexdigest()!=value['requirements_sha256']:raise BootstrapError('BOOTSTRAP_STATE_INVALID')
        if _version([str(python),'--version'],env)!=value['python_version'] or _version([str(uv),'--version'],env)!=value['uv_version']:raise BootstrapError('BOOTSTRAP_STATE_INVALID')
    except Exception:return {'schema_version':1,'status':'invalid','prepared':False}
    return {'schema_version':1,'status':'ready','prepared':True,'python_sha256':value['python']['sha256'],'python_version':value['python_version'],'uv_version':value['uv_version']}

def install(workspace,offline_cache=None):
    root=Path(workspace).resolve(strict=True);state=_private(root/'.job-runtime');cache=_private(state/'cache');tmp=_private(state/'tmp');_private(state/'bin');setup=_private(state/'setup');bootstrap=state/'bootstrap';venv=state/'.venv';receipt=setup/'dependencies.json'
    if receipt.exists() or venv.exists():
        current=inspect(root)
        if current['status']!='ready':raise BootstrapError('BOOTSTRAP_STATE_INVALID')
        return current
    env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'HOME':str(Path.home()),'TMPDIR':str(tmp),'PIP_CACHE_DIR':str(cache/'pip'),'UV_CACHE_DIR':str(cache/'uv'),'UV_PYTHON_INSTALL_DIR':str(state/'python'),'UV_PYTHON_BIN_DIR':str(state/'bin')}
    _run([sys.executable,'-m','venv',str(bootstrap)],env=env)
    pip=[str(bootstrap/'bin/python'),'-m','pip','install','--no-cache-dir','-r',str(root/'shared/job_runtime/bootstrap-requirements.txt')]
    if offline_cache:
        source=Path(offline_cache).resolve(strict=True);pip[4:4]=['--no-index','--find-links',str(source)];env['UV_OFFLINE']='1'
    _run(pip,env=env);uv=bootstrap/'bin/uv';_run([str(uv),'python','install',PYTHON_VERSION],env=env);_run([str(uv),'venv','--python','3.12',str(venv)],env=env);_run([str(uv),'pip','install','--python',str(venv/'bin/python'),'-r',str(root/'shared/job_runtime/claude-requirements.txt')],env=env)
    python=venv/'bin/python';requirements=root/'shared/job_runtime/bootstrap-requirements.txt'
    value={'schema_version':1,'status':'prepared','python_version':_version([str(python),'--version'],env),'python':_identity(python,state),'uv_version':_version([str(uv),'--version'],env),'uv':_identity(uv,state),'requirements_sha256':hashlib.sha256(requirements.read_bytes()).hexdigest(),'global_install':False}
    fd=os.open(receipt,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(value,stream,sort_keys=True,separators=(',',':'));stream.write('\n');stream.flush();os.fsync(stream.fileno())
    return inspect(root)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',required=True);p.add_argument('--offline-cache');a=p.parse_args();os.umask(0o077)
    try:print(json.dumps(install(a.workspace,a.offline_cache),sort_keys=True,separators=(',',':')));return 0
    except Exception:print(json.dumps({'status':'failed','code':'BOOTSTRAP_FAILED'}));return 2
if __name__=='__main__':raise SystemExit(main())
