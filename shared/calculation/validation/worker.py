"""Offline calculation child, launched only through the OS-restricted runner."""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import resource
import sys

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / '.job-runtime/calculation'


def install_audit_guard():
    # Defense in depth. The parent seatbelt profile also protects subprocesses;
    # Python audit hooks alone do not propagate into a new interpreter.
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
    sys.addaudithook(audit)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('suite', choices=['valuation', 'options', 'paths', 'contracts'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(STATE/'validation'/args.suite):
        raise ValueError('CALCULATION_WORKER_OUTPUT_INVALID')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (150, 150))
    install_audit_guard()
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
                          'sha256': hashlib.sha256(raw).hexdigest()}))
    except Exception as exc:
        # A fixed exception class is retained; raw provider/input exceptions are
        # never copied into parent logs or email.
        print(json.dumps({'completed': False, 'error_type': type(exc).__name__}))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
