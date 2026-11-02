"""Bounded offline suites with source-bound results and OS boundary probes."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT/'.job-runtime/calculation'
SUITES = ('valuation', 'options', 'paths', 'contracts')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint():
    paths = list((ROOT/'shared/calculation').rglob('*'))
    # The scheduled acceptance also binds the common executor that supplies the
    # calculator's explicit private writable scope.
    paths += list((ROOT/'shared/job_runtime').glob('*.py'))
    paths += [p for suite in SUITES for p in (STATE/'validation'/suite).glob('public*') if p.is_file()]
    paths += list((STATE/'validation/valuation').glob('issuer-*.html'))
    values = {str(p.relative_to(ROOT)): sha(p) for p in paths
              if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts
              and p.suffix in ('.py', '.json', '.md', '.txt', '.html')}
    raw = json.dumps(values, sort_keys=True).encode()
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'files': dict(sorted(values.items()))}


def environment_snapshot():
    script="""import importlib.metadata as m,json,platform,sys
print(json.dumps({'python':sys.version,'executable':sys.executable,'platform':platform.platform(),
 'distributions':{d.metadata['Name']:d.version for d in m.distributions()}},sort_keys=True))
"""
    raw=subprocess.check_output([str(STATE/'.venv/bin/python'),'-B','-c',script],
        cwd=ROOT,env=environment(),timeout=10)
    value=json.loads(raw)
    norm=lambda name:re.sub('[-_.]+','-',name).lower()
    expected={norm(line.split('==')[0]):line.split('==')[1] for line in
              (ROOT/'shared/calculation/validation/requirements-lock.txt').read_text().splitlines()
              if line and not line.startswith('#')}
    actual={norm(k):v for k,v in value['distributions'].items()}
    if actual!=expected:raise ValueError('VALIDATION_ENVIRONMENT_LOCK_MISMATCH')
    value['interpreter_sha256']=sha(Path(STATE/'.venv/bin/python').resolve())
    value['lock_matches']=True
    return {'sha256':hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest(),
            'attestation':value}


def state_path(path):
    path=Path(path).absolute()
    if not path.is_relative_to(STATE) or not path.resolve().is_relative_to(STATE.resolve()):
        raise ValueError('CALCULATION_STATE_PATH_INVALID')
    for ancestor in [path,*path.parents]:
        if ancestor==ROOT:break
        if ancestor.is_symlink():raise ValueError('CALCULATION_STATE_SYMLINK')
    return path


def json_digest(value):
    return hashlib.sha256(json.dumps(value,indent=2,sort_keys=True,allow_nan=False).encode()).hexdigest()


def atomic(path, value):
    path=state_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.result-')
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):os.unlink(name)


def environment():
    paths = {'HOME': STATE/'worker-home', 'TMPDIR': STATE/'tmp',
             'MPLCONFIGDIR': STATE/'cache/matplotlib',
             'NUMBA_CACHE_DIR': STATE/'cache/numba',
             'XDG_CACHE_HOME': STATE/'cache', 'HYPOTHESIS_STORAGE_DIRECTORY': STATE/'cache/hypothesis'}
    for p in paths.values():p.mkdir(parents=True, exist_ok=True, mode=0o700)
    return {**{k:str(v) for k,v in paths.items()}, 'PATH':'/usr/bin:/bin',
            'PYTHONDONTWRITEBYTECODE':'1', 'PYTHONPATH':str(ROOT),
            'OMP_NUM_THREADS':'1', 'OPENBLAS_NUM_THREADS':'1', 'MKL_NUM_THREADS':'1'}


def sandbox_profile(folder):
    # allow-default is deliberate for numerical framework/native-library reads.
    # Denies below are inherited by all subprocesses; worker audit restricts
    # Python reads further. This is not isolation from arbitrary hostile code.
    q=lambda p:json.dumps(str(p))
    private=[ROOT/'.niulai-state', ROOT/'niulai-private', ROOT/'.market-data-mcp',
             Path.home()/'.codex', Path.home()/'.ssh', Path.home()/'.aws',
             Path.home()/'.config', Path.home()/'Library/Keychains']
    text='(version 1)\n(allow default)\n(deny network*)\n'
    text+='(deny file-read* '+' '.join('(subpath '+q(p)+')' for p in private)+')\n'
    # Parent-directory metadata is needed to reject symlink ancestors. Contents
    # outside calculation/python remain denied, including directory listing.
    text+='(deny file-read-data (require-all (subpath '+q(ROOT/'.job-runtime')+') '
    text+='(require-not (subpath '+q(STATE)+')) (require-not (subpath '+q(ROOT/'.job-runtime/python')+'))))\n'
    text+='(deny file-write* (require-not (subpath '+q(STATE)+')))\n'
    text+='(deny file-write* (subpath '+q(STATE/'.venv')+') (literal '+q(folder/'worker.sb')+'))\n'
    captures=[p for suite in SUITES for p in (STATE/'validation'/suite).glob('public*') if p.is_file()]
    captures+=list((STATE/'validation/valuation').glob('issuer-*.html'))
    if captures:text+='(deny file-write* '+' '.join('(literal '+q(p)+')' for p in captures)+')\n'
    path=folder/'worker.sb';path.write_text(text);path.chmod(0o600)
    # The launched policy is this trusted in-memory string. The writable
    # diagnostic copy cannot alter the policy used by subsequent workers.
    return text


def child(command, profile, env, timeout=180):
    proc=subprocess.Popen(['/usr/bin/sandbox-exec','-p',profile,*command], cwd=ROOT,
                          env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          start_new_session=True)
    streams=selectors.DefaultSelector();buffers={'stdout':bytearray(),'stderr':bytearray()}
    for pipe,name in ((proc.stdout,'stdout'),(proc.stderr,'stderr')):
        os.set_blocking(pipe.fileno(),False);streams.register(pipe,selectors.EVENT_READ,name)
    deadline=time.monotonic()+timeout;reason=None
    try:
        while streams.get_map():
            if time.monotonic()>=deadline:reason='timed_out';break
            for key,_ in streams.select(min(.05,max(0,deadline-time.monotonic()))):
                try:chunk=os.read(key.fileobj.fileno(),65536)
                except BlockingIOError:continue
                if not chunk:
                    streams.unregister(key.fileobj);key.fileobj.close();continue
                if sum(map(len,buffers.values()))+len(chunk)>2*1024*1024:
                    reason='oversized';break
                buffers[key.data].extend(chunk)
            if reason:break
        if reason:
            try:os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        proc.wait(timeout=5)
    finally:
        for key in list(streams.get_map().values()):key.fileobj.close()
        streams.close()
        if proc.poll() is None:
            os.killpg(proc.pid,signal.SIGKILL);proc.wait()
    if reason:
        return {'exit_code':proc.returncode,reason:True,'stdout':'',
                'stderr_bytes':len(buffers['stderr']),'process_reaped':True}
    return {'exit_code':proc.returncode,'stdout':buffers['stdout'].decode(errors='replace'),
            'stderr_bytes':len(buffers['stderr']),
            'stderr_tail':buffers['stderr'].decode(errors='replace')[-1200:],
            'process_reaped':True}


def boundary_probes(folder, profile, env):
    canary=ROOT/'.job-runtime/calculation-denied-canary.txt'
    # Prepared once by the coordinator outside the model's writable scope.
    # Public synthetic content, never an actual credential file.
    if not canary.is_file() or canary.is_symlink() or canary.read_text()!='SYNTHETIC_NOT_A_CREDENTIAL':
        raise ValueError('SYNTHETIC_BOUNDARY_CANARY_REQUIRED')
    target=ROOT/('.job-runtime/calculation-denied-write-'+folder.name+'.txt')
    if target.exists():raise ValueError('BOUNDARY_PROBE_TARGET_EXISTS')
    script="""import json,socket
from pathlib import Path
out={}
try:
 Path(CANARY).read_text();out['private_read_denied']=False
except PermissionError:out['private_read_denied']=True
try:
 Path(TARGET).write_text('synthetic');out['outside_write_denied']=False
except PermissionError:out['outside_write_denied']=True
try:
 s=socket.socket();s.settimeout(1);s.connect(('127.0.0.1',9));out['network_denied']=False
except PermissionError:out['network_denied']=True
except OSError:out['network_denied']=False
print(json.dumps(out))
""".replace('CANARY',repr(str(canary))).replace('TARGET',repr(str(target)))
    value=child([str(STATE/'.venv/bin/python'),'-B','-c',script],profile,env,10)
    checks=json.loads(value['stdout']) if value['exit_code']==0 else {}
    return {'passed':len(checks)==3 and all(checks.values()),'checks':checks,
            'scope':'OS-inherited network, private-runtime read and outside-state write denial; synthetic canary only.'}


def run(run_id):
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,100}',run_id):raise ValueError('RUN_ID_INVALID')
    folder=state_path(STATE/'runs'/run_id)
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    started=datetime.now(timezone.utc).isoformat();pin=fingerprint();env_pin=environment_snapshot()
    env=environment();profile=sandbox_profile(folder)
    security=boundary_probes(folder,profile,env)
    if not security['passed']:
        atomic(folder/'report.json',{'status':'blocked','security':security})
        raise ValueError('WORKER_BOUNDARY_NOT_VERIFIED')
    reports={}
    for suite in SUITES:
        out=STATE/'validation'/suite/'aggregate'/run_id
        command=[str(STATE/'.venv/bin/python'),'-B','-m','shared.calculation.validation.worker',suite,'--output',str(out)]
        before=time.monotonic();transport=child(command,profile,env)
        try:
            receipt=json.loads(transport['stdout'])
            path=ROOT/receipt['result_path']
            if not path.resolve().is_relative_to(out.resolve()) or sha(path)!=receipt['sha256']:
                raise ValueError('RESULT_REFERENCE_INVALID')
            result=json.loads(path.read_text())
            completed=transport['exit_code']==0 and receipt['completed'] is True
        except (KeyError,ValueError,OSError):
            completed=False;result={'status':'blocked','error_type':'WORKER_FAILED',
                'exit_code':transport['exit_code'],'stderr_tail':transport.get('stderr_tail','')}
            receipt={}
        reports[suite]={'completed':completed,'wall_seconds':round(time.monotonic()-before,3),
                        'result':result,'receipt':receipt}
    unchanged=fingerprint()['sha256']==pin['sha256']
    environment_unchanged=environment_snapshot()['sha256']==env_pin['sha256']
    report={'schema_version':1,'run_id':run_id,'started_at':started,
            'completed_at':datetime.now(timezone.utc).isoformat(),'fingerprint':pin,
            'candidate_unchanged':unchanged,'environment':env_pin,'environment_unchanged':environment_unchanged,
            'security':security,'suites':reports,
            'status':'completed' if unchanged and environment_unchanged and all(x['completed'] for x in reports.values()) else 'blocked',
            'claim':'Finite development validation; baseline defects retained separately from corrected candidates; no production or model calibration claim.'}
    atomic(folder/'report.json',report)
    return report,folder/'report.json'


if __name__=='__main__':
    os.umask(0o077)
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);a=p.parse_args()
    report,path=run(a.run_id)
    print(json.dumps({'status':report['status'],'report_path':str(path.relative_to(ROOT)),
                      'security_verified':report['security']['passed'],
                      'suite_statuses':{k:v['result'].get('status') for k,v in report['suites'].items()}}))
    raise SystemExit(0 if report['status']=='completed' else 2)
