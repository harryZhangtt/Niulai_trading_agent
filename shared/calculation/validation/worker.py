"""Offline trusted calculation child, launched through the OS-restricted runner."""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys

from .runner import SUITES

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / '.job-runtime/calculation'
INTERPRETER = str(STATE / '.venv/bin/python')
VALUATION_PROBE_SHA256 = '7196f1e12891d85573379dd2f5705fb2415cd069f301c7a14a8a213d2971036d'
RESOURCE_LIMITS = {
    'RLIMIT_CORE': 0,
    'RLIMIT_CPU': 150,
    'RLIMIT_AS': 8 * 1024 * 1024 * 1024,
    'RLIMIT_FSIZE': 16 * 1024 * 1024,
    'RLIMIT_NOFILE': 256,
    # Darwin applies this per real UID; 1024 is above the observed host baseline
    # while still bounding additional process creation by trusted suites.
    'RLIMIT_NPROC': 1024,
}
PROCESS_AUDIT_EVENTS = frozenset({'subprocess.Popen', 'os.exec', 'os.posix_spawn', 'os.fork', 'os.forkpty', 'pty.spawn'})


def _as_text(value):
    try:return os.fsdecode(value)
    except TypeError:return ''


def _within(path, root):
    try:return Path(path).resolve().is_relative_to(Path(root).resolve())
    except (OSError,TypeError,ValueError):return False


def _trusted_python_subprocess(suite, audit_args, output):
    """Allow only the reviewed Python child shapes required by three suites."""
    if len(audit_args)<4:return False
    executable,argv,cwd,child_env=audit_args[:4]
    if _as_text(executable)!=INTERPRETER or not isinstance(argv,(list,tuple)):
        return False
    args=[_as_text(value) for value in argv]
    if not args or args[0]!=INTERPRETER:return False
    scratch=os.environ.get('CALCULATION_WORKER_SCRATCH','')
    cwd_path=Path(cwd).resolve() if cwd is not None else ROOT
    if suite=='contracts':
        expected_env={'PYTHONDONTWRITEBYTECODE':'1','PYTHONHASHSEED':'0',
                      'PYTHONPATH':str(ROOT/'shared/calculation/legacy/holdings'),
                      'TMPDIR':str(STATE/'tmp')}
        return (args==[INTERPRETER,'-B','-m','unittest','test_execution_pnl_independent']
                and cwd_path==Path(output).resolve() and child_env==expected_env)
    if suite=='leveraged_operator':
        script=str(ROOT/'shared/calculation/operators/leveraged_funds.py')
        return (len(args)==6 and args[:2]==[INTERPRETER,script]
                and args[2]=='--input' and args[4]=='--output'
                and _within(args[3],scratch) and _within(args[5],scratch)
                and cwd_path==ROOT and child_env is None)
    if suite=='valuation':
        if len(args)<3 or args[1]!='-B':return False
        offset=2
        if len(args)>offset and args[offset]=='-O':offset+=1
        if len(args)!=offset+5 or args[offset]!='-c':return False
        code=args[offset+1]
        expected_env={'PYTHONDONTWRITEBYTECODE':'1','PYTHONHASHSEED':'0','PYTHONPATH':str(ROOT)}
        return (hashlib.sha256(code.encode()).hexdigest()==VALUATION_PROBE_SHA256
                and args[offset+2]==str(ROOT/'shared/calculation/legacy/holdings/position_totals.py')
                and args[offset+4] in {'legacy','maintained'}
                and _within(cwd_path,output) and child_env==expected_env)
    return False


def process_event_allowed(event, args, suite=None, output=None):
    return event=='subprocess.Popen' and output is not None and _trusted_python_subprocess(suite,args,output)


def audit_policy_sha256():
    policy={'events':sorted(PROCESS_AUDIT_EVENTS),'interpreter':INTERPRETER,
            'suites':{'contracts':'unittest:test_execution_pnl_independent',
                      'leveraged_operator':'operators/leveraged_funds.py --input STATE --output STATE',
                      'valuation':'frozen -c probe '+VALUATION_PROBE_SHA256}}
    return hashlib.sha256(json.dumps(policy,sort_keys=True).encode()).hexdigest()


def install_audit_guard(suite=None, output=None):
    # Defense in depth for reviewed/trusted Python. Seatbelt propagates its
    # filesystem/network policy to allowlisted children; Python audit hooks do
    # not propagate and do not isolate hostile native extensions or memory bugs.
    readable = [ROOT/'shared/calculation', STATE, ROOT/'.job-runtime/python',
                Path('/System'), Path('/usr'), Path('/Library'),
                Path('/private/etc'), Path('/private/var/db/timezone'), Path('/dev')]
    readable = [p.resolve() for p in readable]
    def audit(event, args):
        if event.startswith('socket.'):
            raise PermissionError('CALCULATION_NETWORK_DENIED')
        if event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
            mode = args[1] if len(args) > 1 and isinstance(args[1], str) else ''
            writing = bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)) or any(x in mode for x in 'wax+')
            if writing:
                if not path.is_relative_to(STATE.resolve()) and path != Path('/dev/null'):
                    raise PermissionError('CALCULATION_WRITE_DENIED')
            elif not any(path == base or path.is_relative_to(base) for base in readable):
                raise PermissionError('CALCULATION_READ_DENIED')
        if event == 'os.system':
            raise PermissionError('CALCULATION_SHELL_DENIED')
        if event in PROCESS_AUDIT_EVENTS and not process_event_allowed(event,args,suite,output):
            raise PermissionError('CALCULATION_PROCESS_DENIED')
    sys.addaudithook(audit)


def apply_resource_limits():
    observed={}
    for name,requested in RESOURCE_LIMITS.items():
        key=getattr(resource,name,None)
        required=not (name=='RLIMIT_AS' and sys.platform=='darwin')
        if key is None:
            observed[name]={'available':False,'supported':False,'required':False,
                            'requested':requested,'applied':False}
            continue
        before=resource.getrlimit(key)
        hard=before[1]
        target=requested if hard==resource.RLIM_INFINITY else min(requested,hard)
        soft=min(before[0],target) if before[0]!=resource.RLIM_INFINITY else target
        try:
            resource.setrlimit(key,(soft,target))
            after=resource.getrlimit(key)
            observed[name]={'available':True,'supported':True,'required':required,
                            'requested':requested,'soft':after[0],'hard':after[1],
                            'applied':after[0]<=requested and after[1]<=requested}
        except (OSError,ValueError) as exc:
            observed[name]={'available':True,'supported':False,'required':required,
                            'requested':requested,'applied':False,
                            'error_type':type(exc).__name__}
    return observed


def security_probe():
    limits=apply_resource_limits()
    install_audit_guard()
    checks={}
    for name,command in (('native_cat_denied',['/bin/cat','/dev/null']),
                         ('arbitrary_native_denied',['/usr/bin/true'])):
        try:
            subprocess.run(command,check=False,capture_output=True)
            checks[name]=False
        except PermissionError:
            checks[name]=True
    try:
        os.posix_spawn('/usr/bin/true',['/usr/bin/true'],{})
        checks['direct_spawn_denied']=False
    except PermissionError:
        checks['direct_spawn_denied']=True
    try:
        child=os.fork()
        if child==0:os._exit(73)
        os.waitpid(child,0)
        checks['fork_denied']=False
    except PermissionError:
        checks['fork_denied']=True
    checks['direct_exec_event_denied']=not process_event_allowed('os.exec',('/usr/bin/true',),None,None)
    checks['forkpty_event_denied']=not process_event_allowed('os.forkpty',(),None,None)
    return {'checks':checks,'resource_limits':limits,'audit_policy_sha256':audit_policy_sha256()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('suite', nargs='?', choices=SUITES)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--security-probe', action='store_true')
    args = parser.parse_args()
    if args.security_probe:
        if args.suite is not None or args.output is not None:parser.error('security probe takes no suite/output')
        print(json.dumps(security_probe(),sort_keys=True))
        return 0
    if args.suite is None or args.output is None:parser.error('suite and --output are required')
    out = args.output.resolve()
    if not out.is_relative_to(STATE/'validation'/args.suite):
        raise ValueError('CALCULATION_WORKER_OUTPUT_INVALID')
    limits=apply_resource_limits()
    if any(value.get('required') and not value.get('applied') for value in limits.values()):
        raise ValueError('CALCULATION_RESOURCE_LIMIT_FAILED')
    install_audit_guard(args.suite,out)
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    try:
        module = importlib.import_module('shared.calculation.validation.'+args.suite)
        result = module.run(out)
        raw = json.dumps(result, sort_keys=True, allow_nan=False).encode()
        if len(raw) > 2*1024*1024:
            raise ValueError('CALCULATION_RESULT_TOO_LARGE')
        path = out/'worker-result.json'
        with path.open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        print(json.dumps({'completed': True, 'result_path': str(path.relative_to(ROOT)),
                          'sha256': hashlib.sha256(raw).hexdigest(),
                          'resource_limits':limits,'audit_policy_sha256':audit_policy_sha256()}))
    except Exception as exc:
        # A fixed exception class is retained; raw provider/input exceptions are
        # never copied into parent logs or email.
        print(json.dumps({'completed': False, 'error_type': type(exc).__name__}))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
