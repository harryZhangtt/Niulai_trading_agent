"""Once-only development comparison; preparation and verification never call Jev."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time

from shared.research_sources.artifacts import ROOT, SourceError, digest, encoded, private_path, read, require, save
from shared.typed_judge import DecisionPolicy, JudgeClient
from investment.research.source_labeler import _questions, label_source
from shared.typed_judge.client import _normalize
from . import grade, screen

VERSION = 'source-label-screen-runner-1.0.0'
CLIENT = {'engine_scope': 'label-accuracy-dev-v1', 'model': 'jev-1.14.0',
    'timeout_seconds': 45, 'total_timeout_seconds': 60, 'max_retries': 0,
    'max_request_bytes': 256 * 1024, 'max_response_bytes': 64 * 1024}
POLICY = {'min_probability': .6, 'min_margin': .1}
EXTRA_SOURCES = list(dict.fromkeys([*screen.CLASSIFIER_SOURCES,
    'tuning/evals/label_accuracy/run_screen.py', 'shared/typed_judge/__init__.py',
    'shared/research_sources/temporal.py']))
_VALID = {'ok', 'partial', 'abstained'}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _publish(directory, name, value):
    directory = private_path(directory, create=True)
    ref = save(directory / 'records', value)
    try:
        os.link(ref['path'], directory / name)
    except FileExistsError:
        raise SourceError('LABEL_SCREEN_ALREADY_STARTED') from None
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return ref


def path_ref(path):
    path = private_path(path)
    require(path.is_file() and path.stat().st_size <= 8 * 1024 * 1024, 'LABEL_SCREEN_RECORD_INVALID')
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _named(directory, name):
    return path_ref(Path(directory) / name)


def _source_fingerprints():
    # grade.seal adds its standard closure. Do not duplicate those paths.
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in EXTRA_SOURCES}


def prepare(preparation_ref, directory):
    """Seal the reviewed spec and register BOTH arms before a caller can dispatch."""
    prepared = read(preparation_ref); manifest = read(prepared['manifest_ref'])
    review = read(prepared['review_ref']); spec = read(prepared['spec_ref'])
    require(review.get('decision') == 'approved' and review.get('manifest_sha256') == prepared['manifest_ref']['sha256']
            and review.get('review_kind') == 'coordinator_ai_development_review_not_human_gold', 'LABEL_GOLD_REVIEW_REQUIRED')
    require(prepared['candidate_policy']['min_probability'] == POLICY['min_probability']
            and prepared['candidate_policy']['min_margin'] == POLICY['min_margin']
            and all(manifest['candidate_policy'][key] == value for key, value in POLICY.items())
            and spec['budget'] == manifest['proposed_equal_per_arm_budget']
            and len(spec['cases']) == 8, 'LABEL_SCREEN_PREPARATION_CHANGED')
    taxonomy = read(prepared['taxonomy_ref'])
    schema = json.loads((ROOT / manifest['label_schema_path']).read_bytes())
    require(hashlib.sha256((ROOT / manifest['taxonomy_path']).read_bytes()).hexdigest() == prepared['taxonomy_ref']['sha256']
            and hashlib.sha256((ROOT / manifest['label_schema_path']).read_bytes()).hexdigest() == prepared['schema_sha256'],
            'LABEL_SCREEN_PREPARATION_CHANGED')
    # Bind the materialized host cases back to the reviewed roster before sealing.
    require([case['id'] for case in spec['cases']] == [case['id'] for case in manifest['cases']], 'LABEL_SCREEN_PREPARATION_CHANGED')
    for case, original in zip(spec['cases'], manifest['cases']):
        require(case['expected'] == original['gold'] and case['critical'] == original['critical']
                and case['input']['source_ref'] == original['source_ref']
                and case['input']['chunk_ref']['sha256'] == original['chunk_sha256']
                and case['input']['cutoff'] == manifest['cutoff']
                and case['input']['source_group'] == original['source_group']
                and case['input']['taxonomy_ref'] == prepared['taxonomy_ref']
                and case['input']['allowed_topics'] == list(taxonomy['topics'])
                and case['input']['allowed_document_types'] == schema['properties']['document_type']['enum'],
                'LABEL_SCREEN_PREPARATION_CHANGED')
    directory = private_path(directory, create=True)
    _publish(directory, 'preparation.intent.json', {'kind': 'label_screen_prepare_intent',
        'preparation_ref': preparation_ref, 'started_at': _now(), 'replay_allowed': False})
    sources = _source_fingerprints()
    common = {'source_files': sources, 'preparation_sha256': preparation_ref['sha256'],
        'policy': POLICY, 'client': CLIENT, 'scope': 'development_workflow_policy_comparison'}
    pins = {arm: {**common, 'arm': arm, 'normalization': screen.VERSION} for arm in ('baseline', 'candidate')}
    ledger = directory / 'ledger'
    contract_ref = grade.seal(prepared['spec_ref']['path'], pins, ledger, extra_grader_paths=EXTRA_SOURCES)
    claims = {arm: grade.begin(contract_ref, ledger, arm + '-v1', arm=arm,
        budget=spec['budget'], fingerprint=pins[arm]) for arm in ('baseline', 'candidate')}
    packet = grade.worker_packet(contract_ref)
    packets = {arm: save(directory / 'packets', {**packet, 'arm': arm, 'client': CLIENT, 'policy': POLICY})
               for arm in ('baseline', 'candidate')}
    return _publish(directory, 'run.json', {'kind': 'label_screen_run', 'version': VERSION,
        'directory': str(directory), 'preparation_ref': preparation_ref, 'contract_ref': contract_ref,
        'claims': claims, 'worker_packets': packets, 'client': CLIENT, 'policy': POLICY,
        'source_fingerprints': sources, 'created_at': _now(), 'replay_allowed': False})


def _validate(run_ref):
    run = read(run_ref); require(run.get('kind') == 'label_screen_run' and run.get('version') == VERSION
        and run['client'] == CLIENT and run['policy'] == POLICY and run['replay_allowed'] is False
        and run['source_fingerprints'] == _source_fingerprints(), 'LABEL_SCREEN_RUN_CHANGED')
    contract = grade.validate(run['contract_ref']); packet = grade.worker_packet(run['contract_ref'])
    require(set(run['claims']) == set(run['worker_packets']) == {'baseline', 'candidate'}, 'LABEL_SCREEN_BOTH_ARMS_REQUIRED')
    for arm in run['claims']:
        claim = read(run['claims'][arm])
        require(claim['contract_ref'] == run['contract_ref'] and claim['arm'] == arm
                and claim['fingerprint'] == contract['candidate_fingerprints'][arm]
                and claim['budget'] == contract['budget'] and claim['replay_allowed'] is False,
                'LABEL_SCREEN_CLAIM_MISMATCH')
        require(read(run['worker_packets'][arm]) == {**packet, 'arm': arm, 'client': CLIENT, 'policy': POLICY},
                'LABEL_SCREEN_PACKET_CHANGED')
    prepared = read(run['preparation_ref']); review = read(prepared['review_ref'])
    read(prepared['manifest_ref']); read(prepared['taxonomy_ref'])
    require(review['decision'] == 'approved' and review['manifest_sha256'] == prepared['manifest_ref']['sha256']
            and contract['spec_source']['sha256'] == prepared['spec_ref']['sha256'], 'LABEL_SCREEN_PREPARATION_CHANGED')
    return run, contract


def _unavailable(inputs, code, status='not_dispatched'):
    return {**screen._bindings(inputs), 'transport_status': status, 'document_type': None,
        'topics': [], 'topic_abstentions': list(inputs['allowed_topics']),
        'document_probabilities': None, 'topic_probabilities': None,
        'latency_ms': None, 'cost': None, 'error_code': code}


def _code(exc):
    text = str(exc)
    return text if isinstance(exc, SourceError) and re.fullmatch(r'[A-Z][A-Z_0-9]{0,99}', text) else 'LABEL_SCREEN_EXECUTION_FAILED'


def run_arm(run_ref, arm, *, allow_live=False, client_factory=None):
    """One durable invocation; client_factory is synthetic-test-only, absent in CLI."""
    require(arm in {'baseline', 'candidate'} and type(allow_live) is bool, 'LABEL_SCREEN_ARM_INVALID')
    run, contract = _validate(run_ref); directory = private_path(Path(run['directory']) / arm, create=True)
    intent_ref = _publish(directory, 'execution.intent.json', {'kind': 'label_screen_arm_intent',
        'run_ref': run_ref, 'claim_ref': run['claims'][arm], 'arm': arm,
        'allow_live': allow_live, 'started_at': _now(), 'replay_allowed': False})
    started = time.monotonic(); calls = 0; stop = None; rows = []; provider_usage = []
    packet = read(run['worker_packets'][arm])
    for case in packet['cases']:
        grade.validate(run['contract_ref'])
        inputs = read(case['input_ref']); case_dir = directory / case['id']
        case_intent = _publish(case_dir, 'intent.json', {'kind': 'label_screen_case_intent',
            'arm_intent_ref': intent_ref, 'case_id': case['id'], 'input_ref': case['input_ref'],
            'dispatch_allowed': stop is None, 'started_at': _now(), 'replay_allowed': False})
        report_ref = receipt_ref = None
        if stop is not None:
            output = _unavailable(inputs, 'LABEL_SCREEN_STOPPED_AFTER_' + stop)
        elif arm == 'baseline':
            try:
                output = screen.normalize_rules(inputs)
            except Exception as exc:
                stop = _code(exc); output = _unavailable(inputs, stop, status='error')
        else:
            try:
                client = (client_factory or JudgeClient)(**CLIENT, cache_directory=case_dir / 'judge-cache')
                report = label_source(inputs['source_ref'], cutoff=inputs['cutoff'], chunk_ref=inputs['chunk_ref'],
                    directory=case_dir / 'labeler', client=client, policy=DecisionPolicy(**POLICY), allow_live=allow_live)
                report_ref = save(case_dir / 'records', report)
                if report.get('judge_outcome_ref') is not None:
                    receipt_ref = report['judge_outcome_ref']; receipt = read(receipt_ref)['receipt']
                    attempts = receipt.get('transport_attempts', [])
                    observed = sum(row.get('provider_outcome') != 'not_started' for row in attempts)
                    calls += observed
                    provider_usage.append({'case_id': case['id'], 'outcome_ref': receipt_ref,
                        'usage': receipt.get('usage'), 'usage_scope': receipt.get('usage_scope'),
                        'observed_dispatch_attempts': observed, 'billing': 'unknown'})
                output = screen.normalize_labeler_report(inputs, report)
                if output['transport_status'] not in _VALID:
                    stop = report.get('reason') or 'TRANSPORT_UNVERIFIED'
            except Exception as exc:
                # No receipt after an unexpected exception cannot establish zero calls.
                calls = None; stop = _code(exc)
                output = _unavailable(inputs, stop, status='error')
        output_ref = save(case_dir / 'records', output)
        rows.append({'id': case['id'], 'intent_ref': case_intent, 'output_ref': output_ref,
                     'report_ref': report_ref, 'outcome_ref': receipt_ref})
        _publish(case_dir, 'index.json', rows[-1])
    usage = {'wall_seconds': max(0, time.monotonic() - started), 'model_calls': calls}
    result_ref = grade.finish(run['contract_ref'], Path(run['directory']) / 'ledger',
        read(run['claims'][arm])['attempt_id'], submissions=[{'id': row['id'], 'output_ref': row['output_ref']} for row in rows], usage=usage)
    summary_ref = save(directory / 'records', grade.summarize(run['contract_ref'], result_ref))
    return _publish(directory, 'report.json', {'kind': 'label_screen_arm_report', 'run_ref': run_ref,
        'arm': arm, 'intent_ref': intent_ref, 'cases': rows, 'result_ref': result_ref,
        'summary_ref': summary_ref, 'provider_usage': provider_usage, 'stopped_after': stop,
        'usage': usage, 'model_calls_semantics': 'observed transport dispatch attempts; not billed completions',
        'cost': None, 'finished_at': _now()})


def _verify_typed(inputs, model_report, outcome):
    """Reapply the existing pure typed validator without creating a client/call."""
    questions = _questions(read(inputs['taxonomy_ref']), DecisionPolicy(**POLICY))
    receipt = outcome['receipt']; answers = {}
    require(set(outcome['decisions']) == {question.id for question in questions}, 'LABEL_SCREEN_QUESTIONS_MISMATCH')
    for question in questions:
        row = outcome['decisions'][question.id]
        answers[question.id] = ({'type': 'choice', 'choice': row['candidate'],
            'probabilities': row['probabilities'], 'confidence': row['confidence']}
            if question.id == 'document_type' else {'type': 'noul', 'noul': row['probabilities']['true']})
    decisions, _ = _normalize({'model': receipt['model_resolved'], 'answers': answers, 'usage': receipt['usage']}, questions, CLIENT['model'])
    require({key: value.to_dict() for key, value in decisions.items()} == outcome['decisions'], 'LABEL_SCREEN_TYPED_RESULT_MISMATCH')
    schema_sha = digest({question.id: question.contract() for question in questions})
    passage = read(inputs['chunk_ref'], json_value=False).decode('utf-8')
    require(model_report['question_schema_sha256'] == receipt['schema_sha256'] == schema_sha
            and receipt['request_sha256'] == digest({'model': CLIENT['model'], 'state': {'passage': passage},
                'questions': {question.id: question.wire() for question in questions}}), 'LABEL_SCREEN_REQUEST_BINDING_MISMATCH')


def verify(run_ref, *, expected_transport='https'):
    """Read-only closure, output, host-grade and summary verification; no model call."""
    run, contract = _validate(run_ref); reports = {}; integrity = []
    packet_cases = {case['id']: case for case in grade.worker_packet(run['contract_ref'])['cases']}
    for arm in ('baseline', 'candidate'):
        try:
            report_ref = _named(Path(run['directory']) / arm, 'report.json'); report = read(report_ref)
            require(report['kind'] == 'label_screen_arm_report' and report['run_ref'] == run_ref and report['arm'] == arm,
                    'LABEL_SCREEN_REPORT_MISMATCH')
            intent = read(report['intent_ref'])
            require(intent['run_ref'] == run_ref and intent['claim_ref'] == run['claims'][arm]
                    and intent['arm'] == arm and intent['replay_allowed'] is False, 'LABEL_SCREEN_INTENT_MISMATCH')
            result = read(report['result_ref']); summary = grade.summarize(run['contract_ref'], report['result_ref'])
            require(result['claim_ref'] == run['claims'][arm] and result['arm'] == arm and result['usage'] == report['usage'],
                    'LABEL_SCREEN_RESULT_MISMATCH')
            require(not result['errors'] and len(result['cases']) == len(packet_cases)
                    and [row['id'] for row in report['cases']] == list(packet_cases)
                    and len(report['cases']) == len(packet_cases), 'LABEL_SCREEN_INTEGRITY_FAILURE')
            graded = {row['id']: row for row in result['cases']}
            observed_calls = 0; observed_provider_usage = []; stopped = None
            for row in report['cases']:
                case = packet_cases[row['id']]; case_intent = read(row['intent_ref'])
                require(case_intent['input_ref'] == case['input_ref'] and case_intent['case_id'] == row['id']
                        and case_intent['arm_intent_ref'] == report['intent_ref'] and case_intent['replay_allowed'] is False,
                        'LABEL_SCREEN_CASE_INTENT_MISMATCH')
                output = read(row['output_ref']); frozen = next(item for item in contract['cases'] if item['id'] == row['id'])
                require(case_intent['dispatch_allowed'] is (stopped is None), 'LABEL_SCREEN_DISPATCH_SEQUENCE_MISMATCH')
                if stopped is not None:
                    require(row['report_ref'] is None and row['outcome_ref'] is None and output ==
                            _unavailable(read(case['input_ref']), 'LABEL_SCREEN_STOPPED_AFTER_' + stopped),
                            'LABEL_SCREEN_DISPATCH_SEQUENCE_MISMATCH')
                require(graded[row['id']]['output_ref'] == row['output_ref'], 'LABEL_SCREEN_OUTPUT_MISMATCH')
                verdict = grade.grade(row['id'], read(case['input_ref']), read(frozen['expected_ref']), output)
                require(all(encoded(verdict[key]) == encoded(graded[row['id']][key]) for key in verdict), 'LABEL_SCREEN_REGRADE_MISMATCH')
                if row['report_ref'] is not None:
                    model_report = read(row['report_ref'])
                    require(screen.normalize_labeler_report(read(case['input_ref']), model_report) == output,
                            'LABEL_SCREEN_MODEL_OUTPUT_MISMATCH')
                    if row['outcome_ref'] is not None:
                        outcome = read(row['outcome_ref']); receipt = outcome['receipt']
                        require(model_report['judge_outcome_ref'] == row['outcome_ref']
                                and receipt['engine_scope'] == CLIENT['engine_scope']
                                and receipt['model_requested'] == CLIENT['model']
                                and receipt['configured_limits'] == {key: value for key, value in CLIENT.items()
                                    if key not in ('engine_scope', 'model')}
                                and receipt['attempts'] <= 1 and receipt['cache_hit'] is False
                                and receipt['transport_kind'] == expected_transport,
                                'LABEL_SCREEN_PROVIDER_BINDING_MISMATCH')
                        if output['transport_status'] in _VALID:
                            require(receipt['model_resolved'] == CLIENT['model'], 'LABEL_SCREEN_MODEL_MISMATCH')
                            _verify_typed(read(case['input_ref']), model_report, outcome)
                        observed = sum(item.get('provider_outcome') != 'not_started' for item in receipt['transport_attempts'])
                        observed_calls += observed
                        observed_provider_usage.append({'case_id': row['id'], 'outcome_ref': row['outcome_ref'],
                            'usage': receipt.get('usage'), 'usage_scope': receipt.get('usage_scope'),
                            'observed_dispatch_attempts': observed, 'billing': 'unknown'})
                if stopped is None and output['transport_status'] not in _VALID:
                    stopped = output.get('error_code') or 'TRANSPORT_UNVERIFIED'
            require(report['cost'] is None and observed_calls == report['usage']['model_calls']
                    and observed_provider_usage == report['provider_usage'] and stopped == report['stopped_after'],
                    'LABEL_SCREEN_USAGE_MISMATCH')
            expected_failures = [row['id'] for row in result['cases'] if row['critical'] and not row['passed']]
            require(result['critical_failures'] == expected_failures and result['status'] ==
                    ('passed' if all(row['passed'] for row in result['cases']) else 'failed'),
                    'LABEL_SCREEN_RESULT_STATUS_MISMATCH')
            require(read(report['summary_ref']) == summary, 'LABEL_SCREEN_SUMMARY_MISMATCH')
            reports[arm] = {'report_ref': report_ref, 'result_ref': report['result_ref'], 'summary_ref': report['summary_ref'],
                'integrity': 'verified', 'semantic_status': result['status'], 'semantic_failures': result['critical_failures'],
                'transport_failures': summary['transport_failures'], 'summary': summary}
        except Exception as exc:
            integrity.append({'arm': arm, 'code': _code(exc)})
    return {'kind': 'label_screen_read_only_verification', 'version': VERSION,
        'run_ref': run_ref, 'integrity_status': 'failed' if integrity else 'verified', 'integrity_errors': integrity,
        'arms': reports, 'semantic_all_cases_passed': bool(reports) and len(reports) == 2
            and all(report['semantic_status'] == 'passed' for report in reports.values()),
        'provider_call_performed': False, 'promotion': False,
        'scope': 'retained grouped development comparison; not generalization or calibration'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('prepare'); command.add_argument('--preparation', required=True); command.add_argument('--directory', required=True)
    command = commands.add_parser('run'); command.add_argument('--run', required=True); command.add_argument('--arm', choices=('baseline', 'candidate'), required=True); command.add_argument('--allow-live', action='store_true')
    command = commands.add_parser('verify'); command.add_argument('--run', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            result = {'run_ref': prepare(path_ref(args.preparation), Path(args.directory))}
        elif args.command == 'run':
            result = {'report_ref': run_arm(path_ref(args.run), args.arm, allow_live=args.allow_live)}
        else:
            result = verify(path_ref(args.run))
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return int(result.get('integrity_status') == 'failed')
    except Exception as exc:
        print(json.dumps({'status': 'error', 'code': _code(exc)})); return 1


if __name__ == '__main__':
    raise SystemExit(main())
