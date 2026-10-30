"""Run frozen outcome checks on one finished implementation, without model calls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).resolve().parent
RUN = ROOT / 'tuning/runtime/ui-implementation-quality-v1'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=pairs)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def immutable_errors(worker, protected):
    errors = []
    for relative, expected in protected.items():
        path = worker / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(worker.resolve()):
            errors.append('missing/unsafe protected file: ' + relative)
        elif digest(path) != expected:
            errors.append('protected file modified: ' + relative)
    for path in (worker / 'app').rglob('*'):
        relative = str(path.relative_to(worker))
        if path.is_symlink():
            errors.append('app symlink is outside editable contract: ' + relative)
        elif path.is_file() and not relative.startswith('app/src/') and relative not in protected:
            errors.append('new file outside editable source: ' + relative)
    return errors


def parse_cases(report, expected_ids):
    cases = {}

    def visit(suite):
        for spec in suite.get('specs', []):
            match = re.match(r'^(Q\d{2})\b', spec.get('title', ''))
            require(match is not None, 'Unrecognized grader case')
            cid = match.group(1)
            require(cid not in cases, 'Duplicate grader case')
            tests = spec.get('tests', [])
            require(len(tests) == 1, 'Expected one project per case')
            test = tests[0]
            results = test.get('results', [])
            require(len(results) == 1, 'Missing result or unplanned retry')
            outcome = results[0]['status']
            require(outcome in ('passed', 'failed', 'timedOut', 'skipped', 'interrupted'), 'Invalid outcome')
            require(outcome not in ('skipped', 'interrupted'), 'Incomplete browser evidence')
            errors = results[0].get('errors', [])
            cases[cid] = {'passed': outcome == 'passed', 'outcome': outcome,
                          'evidence': [str(e.get('message', ''))[:1000].replace(str(ROOT), '<workspace>') for e in errors]}
        for child in suite.get('suites', []):
            visit(child)
    for suite in report.get('suites', []):
        visit(suite)
    require(set(cases) == set(expected_ids), 'Missing/extra browser cases')
    require(not report.get('errors'), 'Global browser infrastructure error')
    return cases


def execute(command, env, output, label, timeout=180):
    start = time.monotonic()
    with (output / (label + '.stdout')).open('w') as out, (output / (label + '.stderr')).open('w') as err:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=out, stderr=err, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=3)
            code = 124
    return {'exit_code': code, 'seconds': round(time.monotonic() - start, 3)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('worker', choices=['repair-1', 'repair-2'])
    args = parser.parse_args()
    manifest = read(RUN / 'manifest.json')
    for relative, expected in manifest['source_sha256'].items():
        require(digest(ROOT / relative) == expected, 'Frozen source changed: ' + relative)
    job = next(j for j in manifest['jobs'] if j['id'] == args.worker)
    worker = RUN / job['id']
    output = RUN / 'evaluations' / job['id']
    output.mkdir(parents=True, exist_ok=False)
    result = {'worker': job['id'], 'immutable_errors': immutable_errors(worker, job['protected_sha256']),
              'cases': {}, 'status': 'inconclusive', 'provider_usage': None}
    try:
        if result['immutable_errors']:
            result['status'] = 'failed_validity'
        require(not result['immutable_errors'], 'Immutable contract violation')
        require((worker / 'inspection.json').is_file() and (worker / 'result.json').is_file(), 'Missing worker evidence')
        implementation = {str(p.relative_to(worker)): digest(p) for p in (worker / 'app/src').rglob('*') if p.is_file()}
        result['implementation_sha256'] = implementation
        temporary = output / 'tmp'
        temporary.mkdir()
        tools = ROOT / 'ui/verification'
        port = 5196
        with socket.socket() as probe:
            require(probe.connect_ex(('127.0.0.1', port)) != 0, 'Evaluation port already occupied')
        env = {**os.environ, 'UI_TOOL_ROOT': str(tools), 'BENCH_APP': str(worker / 'app'),
               'BENCH_OUTPUT': str(output), 'BENCH_PORT': str(port), 'CI': '1',
               'PLAYWRIGHT_BROWSERS_PATH': str(ROOT / 'ui/runtime/browsers'),
               'TMPDIR': str(temporary), 'XDG_CACHE_HOME': str(output / 'cache'),
               'PYTHONDONTWRITEBYTECODE': '1'}
        result['typecheck'] = execute(['node', str(SOURCE / 'tests/typecheck.cjs')], env, output, 'typecheck')
        result['build'] = execute(['node', str(tools / 'node_modules/vite/bin/vite.js'), 'build', '--config', str(SOURCE / 'tests/vite.config.mjs')], env, output, 'build')
        if result['typecheck']['exit_code'] != 0 or result['build']['exit_code'] != 0:
            result['status'] = 'failed_validity'
        require(result['typecheck']['exit_code'] == result['build']['exit_code'] == 0, 'Implementation typecheck/build failed')
        result['browser'] = execute(['node', str(tools / 'node_modules/@playwright/test/cli.js'), 'test', '--config', str(SOURCE / 'tests/playwright.config.cjs')], env, output, 'browser')
        gold = read(SOURCE / 'gold.json')
        result['cases'] = parse_cases(read(output / 'results.json'), [c['id'] for c in gold['cases']])
        require(result['browser']['exit_code'] in (0, 1), 'Browser process incomplete')
        with socket.socket() as probe:
            require(probe.connect_ex(('127.0.0.1', port)) != 0, 'Owned evaluation server still listening')
        require(not immutable_errors(worker, job['protected_sha256']), 'Protected artifact changed during execution')
        require(all(digest(worker / p) == value for p, value in implementation.items()), 'Implementation changed during grading')
        result['passed'] = sum(c['passed'] for c in result['cases'].values())
        result['total'] = len(gold['cases'])
        result['critical_failures'] = [c['id'] for c in gold['cases'] if c['severity'] == 'critical' and not result['cases'][c['id']]['passed']]
        result['status'] = 'passed' if result['passed'] == result['total'] else 'failed_checks'
        result['cleanup'] = 'evaluation port closed; Playwright runner completed'
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc).replace(str(ROOT), '<workspace>')
    (output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('implementation_sha256', 'cases')}, indent=2))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
