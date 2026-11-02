"""Temporary one-slot atomic-action evaluation; no production engine expansion."""
from datetime import datetime, timedelta, timezone
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess

from shared.job_runtime.engine import Engine
from shared.job_runtime.service import atomic
from shared.research_sources.artifacts import ROOT, SOURCE_STATE, digest, private_path, read, require, save
from tuning.evals.evidence_runtime import contracts
from . import workload


def fingerprint():
    from investment.research.pilot_acceptance import fingerprint as core
    files = dict(core()['files'])
    for pattern in ('tuning/evals/atomic_actions/*.py', 'tuning/evals/atomic_actions/*.json',
                    'shared/actions/tests/test_atomic_safety.py'):
        for p in ROOT.glob(pattern): files[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return {'sha256': digest(files), 'files': files}


def setup(change):
    require(change.replace('-', '').isalnum() and len(change) < 65, 'ATOMIC_CHANGE_ID')
    base = ROOT / '.job-runtime/acceptance' / change
    require(not base.exists(), 'ATOMIC_ACCEPTANCE_EXISTS'); base.mkdir(parents=True, mode=0o700)
    candidate = fingerprint(); out = private_path(SOURCE_STATE / 'runtime/atomic-open-questions' / change, create=True)
    spec_path = Path(save(out, workload.specification())['path'])
    ledger = SOURCE_STATE / 'runtime/atomic-evaluation-contracts'
    contract_ref = contracts.seal(spec_path, [ROOT / name for name in candidate['files']], {'candidate': candidate}, ledger)
    due = datetime.now(timezone.utc) + timedelta(seconds=45); label = 'com.local.trading-agent.atomic.' + change
    profile = json.loads((ROOT / '.job-runtime/config/runtime.json').read_text())['model_profiles']['default']
    record = {'schema_version': 1, 'change_id': change, 'candidate': candidate, 'output_directory': str(out),
        'contract_ref': contract_ref, 'ledger_directory': str(ledger), 'profile_sha256': digest(profile),
        'job': {'id': change, 'enabled': True, 'replay_safe': False,
                'schedule': {'kind': 'once', 'at': due.isoformat(), 'grace_seconds': 180}},
        'label': label, 'execution': {'status': 'pending'}, 'email': {'status': 'pending'},
        'criteria': {'max_seconds': 720, 'source_review': 'Required after actual answer; rubric/expected answers sealed before scheduling',
                     'scope': 'Four correlated development open-question cases, no blind quality/alpha claim'}}
    record['grader_source_snapshots'] = {name: save(out / 'grader-history', (ROOT / name).read_bytes(),
        suffix=Path(name).suffix.lstrip('.')) for name in candidate['files'] if name.startswith('tuning/evals/atomic_actions/')}
    atomic(base / 'record.json', record)
    spec = {'Label': label, 'ProgramArguments': [str(ROOT / '.research-sources/.venv/bin/python'), '-B', '-m',
        'tuning.evals.atomic_actions.acceptance', 'tick', '--record', str(base / 'record.json')],
        'WorkingDirectory': str(ROOT), 'EnvironmentVariables': {'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1',
        'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(Path.home()),
        'TMPDIR': str(SOURCE_STATE / 'tmp')}, 'StartInterval': 15, 'RunAtLoad': False, 'ProcessType': 'Background',
        'Umask': 0o077, 'StandardOutPath': str(base / 'stdout.log'), 'StandardErrorPath': str(base / 'stderr.log')}
    path = base / 'once.plist'; path.write_bytes(plistlib.dumps(spec)); path.chmod(0o600)
    p = subprocess.run(['/bin/launchctl', 'bootstrap', 'gui/%d' % os.getuid(), str(path)], capture_output=True, timeout=15)
    require(p.returncode == 0, 'ATOMIC_BOOTSTRAP_FAILED')
    return {'record': str(base / 'record.json'), 'due': due.isoformat(), 'label': label}


def tick(path):
    base = Path(path).parent
    fd = os.open(base / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return
        record = json.loads(Path(path).read_text())
        if record['execution']['status'] != 'pending':
            subprocess.run(['/bin/launchctl', 'bootout', 'gui/%d/%s' % (os.getuid(), record['label'])], capture_output=True, timeout=10)
            return
        def dispatch(job, context):
            try:
                require(fingerprint() == record['candidate'], 'ATOMIC_CANDIDATE_CHANGED')
                profile = json.loads((ROOT / '.job-runtime/config/runtime.json').read_text())['model_profiles']['default']
                require(digest(profile) == record['profile_sha256'], 'ATOMIC_PROFILE_CHANGED')
                contract = contracts.validate(record['contract_ref'], candidate_fingerprints={'candidate': record['candidate']})
                claim_ref = contracts.begin(record['contract_ref'], record['ledger_directory'], context['attempt_id'],
                    arm='candidate', budget=contract['budget'], fingerprint=record['candidate'])
                record['claim_ref'] = claim_ref; atomic(base / 'record.json', record)
                result = workload.run(Path(record['output_directory']) / context['attempt_id'])
                result_ref = save(Path(record['output_directory']), result)
                require(fingerprint() == record['candidate'], 'ATOMIC_CANDIDATE_CHANGED')
                incomplete = any(case['status'] != 'completed' for case in result['cases'])
                record['execution'] = {'status': 'failed' if incomplete else 'partial',
                    'code': 'ATOMIC_CASES_INCOMPLETE' if incomplete else 'ATOMIC_HOST_REVIEW_REQUIRED', 'context': context,
                    'result_ref': result_ref, 'finished_at': datetime.now(timezone.utc).isoformat()}
                atomic(base / 'record.json', record)
                return {'status': 'succeeded', 'code': 'ATOMIC_ANSWERS_STAGED', 'receipt': record['execution']}
            except Exception as error:
                from shared.research_sources.artifacts import SourceError
                record['execution'] = {'status': 'failed', 'code': str(error) if isinstance(error, SourceError) else type(error).__name__,
                                       'context': context, 'finished_at': datetime.now(timezone.utc).isoformat()}
                atomic(base / 'record.json', record)
                return {'status': 'failed', 'code': 'ATOMIC_EXECUTION_FAILED', 'receipt': record['execution']}
        engine = Engine(base / 'engine', [record['job']], {'max_attempts': 1, 'backoff_seconds': 30, 'max_backoff_seconds': 30},
                        dispatch, workspace_root=ROOT, max_workers=1)
        print(json.dumps(engine.tick(datetime.now(timezone.utc))))
    finally: os.close(fd)


def finalize(path, review_refs):
    from .grade import callback, inspect_case
    base = Path(path).parent; record = json.loads(Path(path).read_text())
    require(fingerprint() == record['candidate'], 'ATOMIC_CANDIDATE_CHANGED')
    contract = contracts.validate(record['contract_ref'], candidate_fingerprints={'candidate': record['candidate']})
    result = read(record['execution']['result_ref']); rows = result['cases']; context = record['execution']['context']
    require({r['case_id'] for r in rows} == {r['id'] for r in contract['cases']}, 'ATOMIC_ROSTER_CHANGED')
    submissions, counts = [], []
    oracle_sha = hashlib.sha256((Path(__file__).parent / 'oracle.json').read_bytes()).hexdigest()
    for row in rows:
        if row['status'] == 'completed':
            inspected = inspect_case(row, not_before=context['scheduled_at']); counts.append(inspected['counts'])
            review_ref = review_refs[row['case_id']]
        else:
            # Safe enforced upper bounds for budget maxima, not invented
            # observed counts. The failed case's metrics remain explicitly unknown.
            counts.append({'actions': contract['budget']['max_case_actions'], 'model_turns': contract['budget']['max_case_model_turns']})
            review_ref = None
        output_ref = save(Path(record['output_directory']), {'case': row, 'not_before': context['scheduled_at'],
            'review_ref': review_ref, 'oracle_sha256': oracle_sha})
        submissions.append({'id': row['case_id'], 'output_ref': output_ref})
    usage = {'case_count': len(rows), 'max_case_actions': max(c['actions'] for c in counts),
        'max_case_model_turns': max(c['model_turns'] for c in counts),
        # Each current reviewed adapter has no retries: one issuer call or two
        # arXiv calls. This is a declared upper bound, not packet-level telemetry.
        'fresh_http_upper_bound': sum(2 if read(case['input_ref'])['public_sources'][0]['provider'] == 'arxiv' else 1 for case in contract['cases']),
        'execution_seconds': result['elapsed_seconds']}
    ref = contracts.finish(record['contract_ref'], record['ledger_directory'], context['attempt_id'],
        submissions=submissions, usage=usage, grade=callback())
    graded = read(ref)
    record['execution'].update(status='passed' if graded['status'] == 'passed' else 'failed',
        code='ATOMIC_HOST_GRADED', evaluation_result_ref=ref, source_reviews=review_refs,
        independently_verified_at=datetime.now(timezone.utc).isoformat())
    atomic(base / 'record.json', record)
    return {'status': record['execution']['status'], 'evaluation_result_ref': ref}


def main():
    p = argparse.ArgumentParser(); p.add_argument('command', choices=('setup', 'tick', 'finalize'))
    p.add_argument('--change'); p.add_argument('--record'); p.add_argument('--reviews'); a = p.parse_args()
    if a.command == 'setup': print(json.dumps(setup(a.change)))
    elif a.command == 'tick': tick(a.record)
    else: print(json.dumps(finalize(a.record, json.loads(Path(a.reviews).read_text()))))


if __name__ == '__main__': main()
