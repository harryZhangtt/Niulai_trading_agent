"""One future-triggered, isolated acceptance allocation for the scoped pilot."""
from datetime import datetime, timedelta, timezone
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import signal
import shlex
import subprocess

from shared.job_runtime.engine import Engine
from shared.job_runtime.model import _private_path
from shared.job_runtime.service import atomic
from shared.research_sources.artifacts import ROOT, INVESTMENT_STATE, digest, read, require
from .run_pilot import execute


def fingerprint():
    patterns = ('investment/research/*.py', 'investment/research/examples/*.json', 'investment/research/profiles/*.json',
                'shared/actions/*.py', 'shared/actions/*.json', 'shared/research_sources/*.py',
                'shared/research_sources/*requirements.txt', 'shared/job_runtime/model.py',
                'shared/job_runtime/business.py', 'shared/job_runtime/campaign.py', 'shared/job_runtime/engine.py',
                'investment/research/report.css', 'shared/research_sources/*.mjs', 'AGENTS.md', 'investment/AGENTS.md',
                'shared/research_sources/tests/test_cache.py', 'shared/market_data_mcp/core/portal.mjs',
                'shared/market_data_mcp/core/errors.mjs', 'shared/market_data_mcp/adapters/research-stdio.mjs',
                'tuning/evals/evidence_runtime/*.py', 'tuning/evals/evidence_runtime/*.json',
                'niulai/skills/investment-research-financial-services/references/niulai-workflow/scripts/evidence_crosscheck.py')
    files = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
             for pattern in patterns for p in ROOT.glob(pattern) if p.is_file()}
    return {'sha256': digest(files), 'files': files}


def source_workload(base, context):
    """Actual scheduled agent calls the public validation CLI through shell."""
    from shared.job_runtime.campaign import development_turn
    from shared.research_sources.runtime_validation import verify as verify_sources
    from shared.research_sources.artifacts import SOURCE_STATE
    profile = json.loads((ROOT / '.job-runtime/config/runtime.json').read_text())['model_profiles']['default']
    attempt = base / ('source-agent-' + context['attempt_id']); attempt.mkdir(mode=0o700)
    out = SOURCE_STATE / 'runtime/acceptance' / base.name / context['attempt_id']
    command = ' '.join(shlex.quote(value) for value in [str(ROOT / '.research-sources/.venv/bin/python'),
                        '-B', '-m', 'shared.research_sources.runtime_validation', '--out', str(out)])
    prompt = ('Authorized bounded runtime source/cache test. Do not edit source or configuration. '
              'Execute exactly this existing public CLI via your shell tool, wait for completion, '
              'and report the actual result pointer and failures. Do not create results yourself, '
              'send email, retry providers, invoke web, or launch background work. Command: ' + command)
    transport = development_turn({'profile': profile}, ROOT, ROOT, attempt, prompt, 600)
    atomic(attempt / 'transport.json', transport)
    require(transport['status'] == 'succeeded' and transport['receipt'].get('thread_id')
            and transport['receipt'].get('tool_names'), 'SOURCE_AGENT_TRANSPORT_FAILED')
    raw = (attempt / 'events.jsonl').read_bytes()
    require(hashlib.sha256(raw).hexdigest() == transport['receipt']['event_sha256']
            and b'shared.research_sources.runtime_validation' in raw, 'SOURCE_AGENT_CALL_NOT_OBSERVED')
    result = json.loads((out / 'result.json').read_text())
    postcondition = verify_sources(result['report_ref'], not_before=context['scheduled_at'])
    return {'transport': transport, 'result': result, 'postcondition': postcondition,
            'attempt_directory': str(attempt)}


def verify_resume(before, after):
    paused, resumed = read(before['report_ref']), read(after['report_ref'])
    first, latest = read(before['checkpoint_ref']), read(after['checkpoint_ref'])
    require(paused['status'] == 'paused' and resumed['status'] == 'completed', 'PILOT_RESUME_STATUS')
    require(paused['run_id'] == resumed['run_id'] and first['deadline_at'] == latest['deadline_at'], 'PILOT_RESUME_ID_OR_DEADLINE')
    require(paused['phases']['comparison'] == resumed['phases']['comparison']
            and paused['phase_refs']['comparison'] == resumed['phase_refs']['comparison'], 'PILOT_RESUME_REPEATED_COMPARISON')
    require(len([x for x in resumed['events'] if x['event_type'] == 'phase_started' and x.get('phase_id') == 'comparison']) == 1,
            'PILOT_RESUME_COMPARISON_COUNT')
    require(first['descriptors'] == latest['descriptors'] and latest['pending'] is None, 'PILOT_RESUME_PINS')
    return {'verified': True, 'execution_id': resumed['run_id'], 'deadline_at': latest['deadline_at'],
            'comparison_execution_ref': resumed['phases']['comparison']['execution_ref'],
            'comparison_runs': 1, 'same_frozen_releases': True}


def verify(result, context):
    require(result['status'] == 'completed', 'PILOT_ACCEPTANCE_NOT_COMPLETED')
    report, request = read(result['report_ref']), read(result['request_ref'])
    require(report['completion_scope'] == 'evidence_resolution_pilot', 'PILOT_ACCEPTANCE_SCOPE')
    source = read(request['source_ref'])
    require(datetime.fromisoformat(source['retrieved_at']) >= datetime.fromisoformat(context['scheduled_at']), 'PILOT_ACCEPTANCE_STALE_SOURCE')
    read(source['raw'], json_value=False); read(source['text'], json_value=False)
    threads = []
    for ref in report['model_execution_refs']:
        model = read(ref)
        require(model['status'] == 'succeeded' and model['receipt']['turn_completed']
                and model['receipt']['thread_id'] and model['receipt']['exit_code'] == 0, 'PILOT_ACCEPTANCE_MODEL_TRANSPORT')
        threads.append(model['receipt']['thread_id'])
        transport = model['receipt']
        response = ROOT / transport['response_path']
        events = ROOT / transport['run_directory'] / 'events.jsonl'
        require(hashlib.sha256(response.read_bytes()).hexdigest() == transport['response_sha256']
                and hashlib.sha256(events.read_bytes()).hexdigest() == transport['event_stream_sha256'], 'PILOT_ACCEPTANCE_TRANSPORT_HASH')
        from shared.job_runtime.model import _parse
        parsed = _parse(events)
        require(parsed['completed'] and parsed['thread_id'] == transport['thread_id']
                and not parsed['failures'] and not parsed['parse_errors'], 'PILOT_ACCEPTANCE_TRANSPORT_EVENT')
    require(bool(threads), 'PILOT_ACCEPTANCE_MODEL_REQUIRED')
    require(any(x['action'].startswith('evidence.read@') for x in report['action_records']), 'PILOT_ACCEPTANCE_AGENT_READ_REQUIRED')
    from .pilot import Pilot
    pilot = Pilot(Path(result['report_ref']['path']).parent, request)
    context = {'request': request, 'run_id': report['run_id'], 'action_records': report['action_records']}
    pilot.critical_guard('evidence.compare_numeric', {'packet_ref': request['packet_ref']}, context)
    pilot._read_receipt(context)  # independent readback of actual argument/outcome/execution bytes
    final = read(report['final_ref'])
    require(final['independent_sources'] is False and final['status'] == 'supported', 'PILOT_ACCEPTANCE_FINDING')
    from shared.research_sources.store import Store
    snapshot = Store(request['store_directory']).read_snapshot(final['snapshot']['snapshot_id'])
    require(snapshot['manifest']['requirement_ref'] == request['requirement_ref'], 'PILOT_ACCEPTANCE_SNAPSHOT')
    require(len(snapshot['manifest']['bindings']) == 2, 'PILOT_ACCEPTANCE_ROSTER')
    for binding in snapshot['manifest']['bindings']:
        current = Store(request['store_directory']).read(binding['observation_id'])
        require(current['revision'] == binding['revision'] and current['lifecycle_revision'] == binding['lifecycle_revision'], 'PILOT_ACCEPTANCE_DEPENDENCY')
        read(binding['use_receipt_ref'])
    if result.get('view_ref'): read(result['view_ref'])
    if result.get('html_ref'): read(result['html_ref'], json_value=False)
    return {'verified': True, 'threads': threads, 'source_ref': request['source_ref'], 'snapshot_id': final['snapshot']['snapshot_id'],
            'model_turns': report['counts']['model_turns'], 'action_calls': report['counts']['actions'],
            'scope': 'fresh original release -> typed acquisition -> guarded comparison -> actual model-selected read -> scoped snapshot'}


def setup(change, *, with_sources=False):
    require(change.replace('-', '').isalnum() and len(change) <= 65, 'PILOT_ACCEPTANCE_ID')
    base = _private_path(ROOT / '.job-runtime/acceptance' / change, ROOT)
    require(not base.exists(), 'PILOT_ACCEPTANCE_EXISTS')
    base.mkdir(parents=True, mode=0o700)
    due = datetime.now(timezone.utc) + timedelta(seconds=45)
    label = 'com.local.trading-agent.pilot.' + change
    job = {'id': change, 'enabled': True, 'replay_safe': False,
           'schedule': {'kind': 'once', 'at': due.isoformat(), 'grace_seconds': 180}}
    record = {'schema_version': 1, 'change_id': change, 'candidate': fingerprint(), 'job': job, 'label': label,
              'with_sources': with_sources, 'execution': {'status': 'pending'}, 'email': {'status': 'pending'},
              'profile_sha256': digest(json.loads((ROOT / '.job-runtime/config/runtime.json').read_text())['model_profiles']['default']),
              'interpreter_sha256': hashlib.sha256(Path(os.path.realpath(ROOT / '.research-sources/.venv/bin/python')).read_bytes()).hexdigest(),
              'criteria': {'completion_timeout_seconds': 1000 if with_sources else 420, 'max_start_lateness_seconds': 180,
                           'scope': 'fresh reported-fact acquisition; immutable releases; accepted-phase resume; optional actual-agent source/cache workload; full-company/production unverified'}}
    if with_sources:
        from tuning.evals.evidence_runtime.contracts import seal
        from shared.research_sources.artifacts import SOURCE_STATE
        record['evaluation_directory'] = str(SOURCE_STATE / 'runtime/evaluation-contracts')
        record['evaluation_contract_ref'] = seal(
            ROOT / 'tuning/evals/evidence_runtime/cases.json',
            [ROOT / name for name in record['candidate']['files']],
            {'candidate': record['candidate']}, record['evaluation_directory'])
    atomic(base / 'record.json', record)
    spec = {'Label': label, 'ProgramArguments': [str(ROOT / '.research-sources/.venv/bin/python'),
            '-B', '-m', 'investment.research.pilot_acceptance', 'tick', '--record', str(base / 'record.json')],
            'WorkingDirectory': str(ROOT), 'EnvironmentVariables': {'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1',
                'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(Path.home()),
                'TMPDIR': str(ROOT / '.niulai-state/reports/research-sources/tmp')},
            'StartInterval': 15, 'RunAtLoad': False, 'ProcessType': 'Background', 'Umask': 0o077,
            'StandardOutPath': str(base / 'stdout.log'), 'StandardErrorPath': str(base / 'stderr.log')}
    # The component owns its dependencies; do not add them to scheduler Python.
    path = base / 'once.plist'; path.write_bytes(plistlib.dumps(spec)); path.chmod(0o600)
    p = subprocess.run(['/bin/launchctl', 'bootstrap', 'gui/%d' % os.getuid(), str(path)], capture_output=True, timeout=15)
    require(p.returncode == 0, 'PILOT_ACCEPTANCE_BOOTSTRAP')
    return {'record': str(base / 'record.json'), 'due': due.isoformat(), 'label': label}


def tick(path):
    base = _private_path(path, ROOT).parent
    fd = os.open(base / 'tick.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        record = json.loads((base / 'record.json').read_text())
        if record['execution']['status'] != 'pending':
            subprocess.run(['/bin/launchctl', 'bootout', 'gui/%d/%s' % (os.getuid(), record['label'])], capture_output=True, timeout=10)
            return
        if datetime.now(timezone.utc) > datetime.fromisoformat(record['job']['schedule']['at']) + timedelta(seconds=600):
            record['execution'] = {'status': 'unverified', 'code': 'PILOT_ACCEPTANCE_WINDOW_EXPIRED'}
            atomic(base / 'record.json', record)
            return
        def dispatch(job, context):
            out = INVESTMENT_STATE / 'acceptance' / record['change_id'] / context['attempt_id']
            evaluation_claim = None
            evaluation_ref = None
            try:
                require(fingerprint() == record['candidate'], 'PILOT_ACCEPTANCE_CANDIDATE_CHANGED')
                require(digest(json.loads((ROOT / '.job-runtime/config/runtime.json').read_text())['model_profiles']['default'])
                        == record['profile_sha256'], 'PILOT_ACCEPTANCE_PROFILE_CHANGED')
                if record.get('evaluation_contract_ref'):
                    from tuning.evals.evidence_runtime import contracts
                    contract = contracts.validate(record['evaluation_contract_ref'], candidate_fingerprints={'candidate': record['candidate']})
                    evaluation_claim = contracts.begin(record['evaluation_contract_ref'], record['evaluation_directory'],
                        context['attempt_id'], arm='candidate', budget=contract['budget'], fingerprint=record['candidate'])
                    record['evaluation'] = {'status': 'started', 'claim_ref': evaluation_claim}
                    atomic(base / 'record.json', record)
                source = None
                if record.get('with_sources'):
                    try:
                        source = source_workload(base, context)
                    except Exception as error:
                        source = {'result': {'status': 'failed'}, 'postcondition': {'verified': False},
                                  'code': str(error) if isinstance(error, SourceError) else type(error).__name__,
                                  'attempt_directory': str(base / ('source-agent-' + context['attempt_id']))}
                paused = execute(out, pause_after_phase='comparison')
                require(paused['status'] == 'paused', 'PILOT_ACCEPTANCE_PAUSE_FAILED')
                result = execute(out, checkpoint_ref=paused['checkpoint_ref'])
                resume = verify_resume(paused, result)
                postcondition = verify(result, context)
                if evaluation_claim is not None:
                    from tuning.evals.evidence_runtime.grade import callback
                    from shared.research_sources.artifacts import SOURCE_STATE, save
                    require(source is not None and source.get('postcondition', {}).get('verified') is True, 'EVAL_RUNTIME_EVIDENCE_INCOMPLETE')
                    spec = {key: contract[key] for key in ('id', 'version', 'split', 'blindness', 'metrics', 'budget')}
                    spec['cases'] = [{'id': case['id'], 'critical': case['critical'],
                                      'input': read(case['input_ref']), 'expected': read(case['expected_ref'])} for case in contract['cases']]
                    observed = {'source_result_ref': source['result']['report_ref'], 'pipeline_result': result,
                                'paused_result': paused, 'not_before': context['scheduled_at'],
                                'completed_at': datetime.now(timezone.utc).isoformat(),
                                'source_agent_usage': source['transport']['receipt'].get('usage')}
                    observed_ref = save(SOURCE_STATE / 'runtime/evaluation-observations' / record['change_id'], observed)
                    combined = read(observed['source_result_ref'])
                    source_report, cache_report = read(combined['source']['report_ref']), read(combined['cache']['report_ref'])
                    pipeline_report, checkpoint = read(result['report_ref']), read(result['checkpoint_ref'])
                    usage = {'source_operations': source_report['observability']['operation_count'],
                        'source_seconds': source_report['elapsed_seconds'], 'cache_seconds': cache_report['elapsed_seconds'],
                        'cache_live_issuer_acquisitions': source['postcondition']['cache']['live_provider_acquisitions'],
                        'phase_actions': pipeline_report['counts']['actions'], 'phase_model_turns': pipeline_report['counts']['model_turns'],
                        'phase_seconds': checkpoint['spent_seconds'],
                        'combined_seconds': (datetime.now(timezone.utc) - datetime.fromisoformat(context['scheduled_at'])).total_seconds()}
                    evaluation_ref = contracts.finish(record['evaluation_contract_ref'], record['evaluation_directory'], context['attempt_id'],
                        submissions=[{'id': case['id'], 'output_ref': observed_ref} for case in contract['cases']],
                        usage=usage, grade=callback(spec))
                due = datetime.fromisoformat(context['scheduled_at'])
                require((datetime.now(timezone.utc) - due).total_seconds() <= record['criteria']['completion_timeout_seconds'], 'PILOT_ACCEPTANCE_TIMEOUT')
                require(fingerprint() == record['candidate'], 'PILOT_ACCEPTANCE_CANDIDATE_CHANGED')
                require(digest(json.loads((ROOT / '.job-runtime/config/runtime.json').read_text())['model_profiles']['default'])
                        == record['profile_sha256'], 'PILOT_ACCEPTANCE_PROFILE_CHANGED')
                status = 'partial' if source and (source['result']['status'] != 'pass'
                                                  or source['postcondition'].get('verified') is not True) else 'passed'
                if evaluation_ref and read(evaluation_ref)['status'] != 'passed': status = 'partial'
                record['execution'] = {'status': status, 'context': context, 'result': result, 'paused_result': paused,
                                       'evaluation_claim_ref': evaluation_claim, 'evaluation_result_ref': evaluation_ref,
                                       'source_workload': source, 'resume_postcondition': resume,
                                       'postcondition': postcondition, 'verified_at': datetime.now(timezone.utc).isoformat()}
                atomic(base / 'record.json', record)
                return {'status': 'succeeded', 'code': 'PILOT_POSTCONDITIONS_VERIFIED', 'receipt': record['execution']}
            except Exception as error:
                code = str(error) if isinstance(error, (SourceError,)) else type(error).__name__
                if evaluation_claim is not None and evaluation_ref is None:
                    try:
                        # A missing/incomplete workload cannot disappear from the
                        # fair-evaluation ledger. No fabricated zero usage.
                        evaluation_ref = contracts.finish(record['evaluation_contract_ref'], record['evaluation_directory'],
                            context['attempt_id'], submissions=[], usage={}, grade=None)
                    except Exception:
                        pass  # Existing finish intent stays unknown and fenced.
                record['execution'] = {'status': 'failed', 'context': context, 'code': code,
                                       'evaluation_claim_ref': evaluation_claim, 'evaluation_result_ref': evaluation_ref,
                                       'output_directory': str(out), 'recorded_at': datetime.now(timezone.utc).isoformat()}
                atomic(base / 'record.json', record)
                return {'status': 'failed', 'code': 'PILOT_ACCEPTANCE_FAILED', 'receipt': record['execution']}
        from shared.research_sources.artifacts import SourceError
        def cancel(signum, frame):
            raise KeyboardInterrupt('acceptance interrupted')
        signal.signal(signal.SIGTERM, cancel)
        engine = Engine(base / 'engine', [record['job']], {'max_attempts': 1, 'backoff_seconds': 30, 'max_backoff_seconds': 30},
                        dispatch, workspace_root=ROOT, max_workers=1)
        print(json.dumps(engine.tick(datetime.now(timezone.utc))))
    finally:
        os.close(fd)


def main():
    p = argparse.ArgumentParser(); p.add_argument('command', choices=('setup', 'tick'))
    p.add_argument('--with-sources', action='store_true')
    p.add_argument('--change'); p.add_argument('--record'); a = p.parse_args()
    if a.command == 'setup': print(json.dumps(setup(a.change, with_sources=a.with_sources)))
    else: tick(a.record)


if __name__ == '__main__':
    main()
