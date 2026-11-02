"""One public-source Jev E2E and read-only host postcondition check.

The root coordinator seals the manifest after reviewing the exact public input.
One durable attempt invokes label_source once; only a valid result permits a
cache-only repeat. No unknown/error outcome is replayed, no email is sent, and
this operational check does not grade label accuracy or promote a policy.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

from shared.research_sources.artifacts import ROOT, SourceError, digest, encoded, private_path, read, require, save
from shared.typed_judge import DecisionPolicy, JudgeClient, TransportResponse
from shared.research_sources.temporal import prepare_corpus

HERE = Path(__file__).parent

VERSION = 'jev-source-e2e-1.0.0'
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')
_SHA = re.compile(r'[a-f0-9]{64}')
_VALID = {'ok', 'partial', 'abstained'}
_MANIFEST = {'schema_version', 'change_id', 'source_ref', 'chunk_ref', 'cutoff',
             'policy', 'client', 'public_input_review', 'candidate_fingerprint'}
_CLIENT = {'engine_scope', 'model', 'timeout_seconds', 'total_timeout_seconds',
           'max_retries', 'max_request_bytes', 'max_response_bytes'}


def fingerprint():
    paths = [*list((ROOT / 'shared/typed_judge').glob('*.py')),
        *(HERE / name for name in ('jev_acceptance.py', 'source_labeler.py', 'information_labels.py',
                                  'information-taxonomy.json', 'information-labels.schema.json')),
        *(ROOT / 'shared/research_sources' / name for name in ('artifacts.py', 'temporal.py', 'store.py'))]
    files = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    return {'sha256': digest(files), 'files': files}


def _identifier(value):
    require(isinstance(value, str) and _ID.fullmatch(value), 'JEV_E2E_ID_INVALID')


def manifest(ref):
    value = read(ref)
    require(isinstance(value, dict) and set(value) == _MANIFEST and value['schema_version'] == 1,
            'JEV_E2E_MANIFEST_INVALID')
    _identifier(value['change_id'])
    require(isinstance(value['candidate_fingerprint'], str) and _SHA.fullmatch(value['candidate_fingerprint'])
            and fingerprint()['sha256'] == value['candidate_fingerprint'], 'JEV_E2E_CANDIDATE_CHANGED')
    require(isinstance(value['client'], dict) and set(value['client']) == _CLIENT and
            value['client']['model'] == 'jev-1.14.0' and value['client']['max_retries'] == 0,
            'JEV_E2E_CLIENT_INVALID')
    thresholds = value['policy']
    require(isinstance(thresholds, dict) and set(thresholds) == {'version', 'min_probability', 'min_margin'}
            and isinstance(thresholds['version'], str) and _ID.fullmatch(thresholds['version']),
            'JEV_E2E_POLICY_REQUIRED')
    DecisionPolicy(thresholds['min_probability'], thresholds['min_margin'])
    review = value['public_input_review']
    require(isinstance(review, dict) and set(review) == {'source_sha256', 'chunk_sha256', 'reviewed_by', 'rationale'}
            and review['source_sha256'] == value['source_ref']['sha256']
            and review['chunk_sha256'] == value['chunk_ref']['sha256']
            and all(isinstance(review[k], str) and 0 < len(review[k]) <= 2000 for k in ('reviewed_by', 'rationale')),
            'JEV_E2E_PUBLIC_INPUT_REVIEW_REQUIRED')
    source = read(value['source_ref']); chunk = read(value['chunk_ref'], json_value=False)
    parsed = urlsplit(source.get('source_url', ''))
    require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
            and source.get('access_scope') in (None, 'public') and bool(chunk), 'JEV_E2E_PUBLIC_SOURCE_REQUIRED')
    broker = prepare_corpus([value['source_ref']], cutoff=value['cutoff'])
    broker.open(value['source_ref']['sha256'], max_chars=1)
    text = read(source['text'], json_value=False).decode('utf-8')
    passage = chunk.decode('utf-8')
    require(0 < len(passage) <= 12000 and passage in text, 'JEV_E2E_EXACT_CHUNK_REQUIRED')
    # Review is a coordinator declaration, not proof of truth or authenticated history.
    return value


def _typed_decisions(outcome, questions, passage, model):
    """Reuse the existing typed validator locally; this performs no provider call."""
    require(set(outcome['decisions']) == {q.id for q in questions}, 'JEV_E2E_QUESTION_BINDING_MISMATCH')
    answers = {}
    for question in questions:
        row = outcome['decisions'][question.id]
        if question.id == 'document_type':
            answers[question.id] = {'type': 'choice', 'choice': row['candidate'],
                'probabilities': row['probabilities'], 'confidence': row['confidence']}
        else:
            answers[question.id] = {'type': 'noul', 'noul': row['probabilities']['true']}
    payload = encoded({'model': model, 'answers': answers, 'usage': outcome['receipt']['usage']})
    local = JudgeClient('jev-e2e-normalized-validation', model=model,
        transport=lambda *_args, **_kwargs: TransportResponse(200, payload))
    checked = local.judge({'passage': passage}, questions)
    require(checked.status == outcome['status'] and
            {k: v.to_dict() for k, v in checked.decisions.items()} == outcome['decisions'],
            'JEV_E2E_TYPED_RESULT_INVALID')


def _publish_named(directory, name, value):
    ref = save(directory, value)
    target = directory / name
    require(not target.exists() and not target.is_symlink(), 'JEV_E2E_ATTEMPT_EXISTS')
    os.link(ref['path'], target)
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return ref


def exercise(manifest_ref, directory, *, attempt_id, allow_live=False, client_factory=None):
    """Run a separately registered attempt; its directory cannot be replayed.

    client_factory is fixture-only injection. The deployed CLI exposes no custom
    transport, credential value, endpoint override or automatic retry switch.
    """
    _identifier(attempt_id)
    require(type(allow_live) is bool, 'JEV_E2E_LIVE_FLAG_INVALID')
    selected = manifest(manifest_ref)
    directory = private_path(directory, create=True)
    started = datetime.now(timezone.utc).isoformat()
    intent_ref = _publish_named(directory, 'attempt.json', {'schema_version': 1, 'kind': 'jev_e2e_attempt',
        'attempt_id': attempt_id, 'manifest_ref': manifest_ref, 'started_at': started,
        'allow_live': allow_live, 'same_call_replay_allowed': False})
    first_ref = repeat_ref = None
    status, code = 'failed', 'JEV_E2E_NOT_COMPLETED'
    try:
        from .source_labeler import label_source
        arguments = dict(selected['client'], cache_directory=directory / 'judge-cache')
        client = (client_factory or JudgeClient)(**arguments)
        policy = DecisionPolicy(selected['policy']['min_probability'], selected['policy']['min_margin'])
        arguments = {'source_ref': selected['source_ref'], 'cutoff': selected['cutoff'],
            'chunk_ref': selected['chunk_ref'], 'client': client, 'policy': policy}
        first = label_source(**arguments, directory=directory / 'first', allow_live=allow_live)
        first_ref = save(directory / 'results', first)
        code = first['reason'] or 'JEV_E2E_FIRST_RESULT_INVALID'
        if first['status'] in _VALID and first['evaluation_output'] is not None:
            # A missing/corrupt cache must fail rather than become another POST.
            repeat = label_source(**arguments, directory=directory / 'repeat', allow_live=False)
            repeat_ref = save(directory / 'results', repeat)
            if repeat['status'] in _VALID and repeat['evaluation_output'] is not None:
                status, code = 'completed', 'JEV_SOURCE_E2E_RECORDED'
            else:
                code = repeat['reason'] or 'JEV_E2E_REPEAT_INVALID'
    except Exception as exc:
        text = str(exc)
        code = text if isinstance(exc, SourceError) and re.fullmatch(r'[A-Z][A-Z_0-9]{0,99}', text) else 'JEV_E2E_EXECUTION_FAILED'
    report = {'schema_version': 1, 'kind': 'jev_source_e2e', 'version': VERSION,
        'attempt_id': attempt_id, 'manifest_ref': manifest_ref, 'intent_ref': intent_ref,
        'candidate_fingerprint': selected['candidate_fingerprint'], 'status': status, 'code': code,
        'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
        'first_ref': first_ref, 'repeat_ref': repeat_ref, 'semantic_approval': False,
        'accuracy_or_calibration_established': False}
    report_ref = save(directory / 'results', report)
    _publish_named(directory, 'index.json', {'report_ref': report_ref})
    return {'status': status, 'code': code, 'report_directory': str(directory),
            'report_ref': report_ref, 'delivery_verified': False}


def validate_report(report_ref, manifest_ref, *, expected_transport='https'):
    """Independently reread all source, typed receipt, cache and sidecar bindings."""
    from .source_labeler import _questions
    from .information_labels import read_sidecar
    selected = manifest(manifest_ref); report = read(report_ref)
    require(report.get('kind') == 'jev_source_e2e' and report.get('status') == 'completed'
            and report['manifest_ref'] == manifest_ref and report['candidate_fingerprint'] == selected['candidate_fingerprint']
            and report['semantic_approval'] is False and report['accuracy_or_calibration_established'] is False,
            'JEV_E2E_POSTCONDITION_FAILED')
    intent = read(report['intent_ref'])
    require(intent['attempt_id'] == report['attempt_id'] and intent['manifest_ref'] == manifest_ref
            and intent['same_call_replay_allowed'] is False, 'JEV_E2E_ATTEMPT_BINDING_MISMATCH')
    results = [read(report[key]) for key in ('first_ref', 'repeat_ref')]
    outcomes = []
    taxonomy_sha = hashlib.sha256((HERE / 'information-taxonomy.json').read_bytes()).hexdigest()
    taxonomy = json.loads((HERE / 'information-taxonomy.json').read_text())
    thresholds = selected['policy']
    questions = _questions(taxonomy, DecisionPolicy(thresholds['min_probability'], thresholds['min_margin']))
    schema = digest({q.id: q.contract() for q in questions})
    passage = read(selected['chunk_ref'], json_value=False).decode('utf-8')
    for result in results:
        authoritative = read(result['report_ref'])
        require(all(result.get(k) == v for k, v in authoritative.items())
                and result['status'] in _VALID and result['source_ref'] == selected['source_ref']
                and result['chunk_ref']['sha256'] == selected['chunk_ref']['sha256']
                and result['taxonomy_sha256'] == taxonomy_sha and result['question_schema_sha256'] == schema
                and result['semantic_approval'] is False,
                'JEV_E2E_SOURCE_BINDING_MISMATCH')
        require(read(result['chunk_ref'], json_value=False) == read(selected['chunk_ref'], json_value=False),
                'JEV_E2E_CHUNK_CHANGED')
        outcome = read(result['judge_outcome_ref']); outcomes.append(outcome)
        require(outcome['status'] == result['status'] and len(outcome['decisions']) == 12
                and outcome['receipt']['provider'] == 'typesafe'
                and outcome['receipt']['engine_scope'] == selected['client']['engine_scope']
                and outcome['receipt']['model_requested'] == selected['client']['model']
                and outcome['receipt']['model_resolved'] == selected['client']['model']
                and outcome['receipt']['schema_sha256'] == schema
                and outcome['receipt']['semantic_approval'] is False, 'JEV_E2E_TYPED_RESULT_INVALID')
        _typed_decisions(outcome, questions, passage, selected['client']['model'])
        require(result['label_ref'] is not None and not result['observation_warnings'], 'JEV_E2E_SIDECAR_REQUIRED')
        sidecar = read_sidecar(result['label_ref'], source_ref=selected['source_ref'])
        policy = read(result['policy_ref'])
        require(sidecar['policy'] == policy and policy['source_sha256'] == selected['source_ref']['sha256']
                and policy['input_chunk_ref'] == result['chunk_ref']
                and policy['judge_outcome_ref'] == result['judge_outcome_ref']
                and policy['thresholds'] == {k: thresholds[k] for k in ('min_probability', 'min_margin')}
                and policy['question_schema_sha256'] == schema
                and sidecar['label']['annotation']['status'] == 'provisional'
                and sidecar['label']['annotation']['method'] == 'model'
                and sidecar['label']['epistemic_status'] == 'unknown', 'JEV_E2E_SIDECAR_BINDING_MISMATCH')
        output = result['evaluation_output']
        require(output['source_sha256'] == selected['source_ref']['sha256']
                and output['chunk_sha256'] == selected['chunk_ref']['sha256']
                and output['taxonomy_sha256'] == taxonomy_sha and output['cost'] is None,
                'JEV_E2E_EVAL_BINDING_MISMATCH')
        document = outcome['decisions']['document_type']
        topics = {topic: outcome['decisions']['topic_' + topic.replace('.', '_')] for topic in taxonomy['topics']}
        expected_topics = [topic for topic, row in topics.items() if row['value'] is True]
        expected_abstentions = [topic for topic, row in topics.items() if row['status'] == 'abstained']
        require(output['document_type'] == document['value'] and output['topics'] == expected_topics
                and output['topic_abstentions'] == expected_abstentions
                and output['document_probabilities'] == document['probabilities']
                and output['topic_probabilities'] == {topic: row['probabilities']['true'] for topic, row in topics.items()}
                and sidecar['label']['document_type'] == (document['value'] or 'unknown')
                and sidecar['label']['topics'] == (expected_topics or ['unclassified']),
                'JEV_E2E_LABEL_PROJECTION_MISMATCH')
    first, repeat = (o['receipt'] for o in outcomes)
    limits = {key: selected['client'][key] for key in ('timeout_seconds', 'total_timeout_seconds',
              'max_retries', 'max_request_bytes', 'max_response_bytes')}
    require(first['configured_limits'] == repeat['configured_limits'] == limits
            and first['http_status'] == 200 and first['provider_outcome'] == 'response_received'
            and len(first['transport_attempts']) == 1 and repeat['transport_attempts'] == [],
            'JEV_E2E_TRANSPORT_RECEIPT_MISMATCH')
    require(first['route'] == expected_transport and first['transport_kind'] == expected_transport
            and first['cache_hit'] is False and first['attempts'] == 1,
            'JEV_E2E_FRESH_CLASSIFICATION_REQUIRED')
    require(repeat['route'] == 'cache' and repeat['cache_hit'] is True and repeat['attempts'] == 0
            and repeat['usage_scope'] == 'original_cached_inference_no_new_call', 'JEV_E2E_CACHE_REUSE_REQUIRED')
    require(outcomes[0]['decisions'] == outcomes[1]['decisions'] and first['usage'] == repeat['usage']
            and first['request_sha256'] == repeat['request_sha256']
            and first['schema_sha256'] == repeat['schema_sha256']
            and first['cache_key'] == repeat['cache_key'], 'JEV_E2E_CACHE_BINDING_MISMATCH')
    return {'verified': True, 'report_ref': report_ref, 'source_sha256': selected['source_ref']['sha256'],
        'chunk_sha256': selected['chunk_ref']['sha256'], 'pinned_model': first['model_resolved'],
        'fresh_classification_attempts': 1, 'repeat_live_calls': 0, 'questions': 12,
        'original_usage': first['usage'], 'elapsed_seconds': first['elapsed_seconds'], 'cost': None,
        'scope': 'typed operational E2E; no label accuracy, calibration or promotion claim'}


def verify(options, workspace, context, result):
    """Stdlib-only scheduler adapter using the explicit domain environment.

    jsonschema is already a research-environment dependency, not a hidden shared
    scheduler dependency. The child performs read-only validation with no live
    option, custom transport, credential lookup or email/network operation.
    """
    try:
        require(set(options) == {'manifest_ref', 'output_root'}, 'JEV_E2E_ALLOCATION_INVALID')
        require(Path(workspace).resolve() == ROOT, 'JEV_E2E_WORKSPACE_MISMATCH')
        selected = manifest(options['manifest_ref'])
        directory = private_path(Path(workspace) / options['output_root'] / context['attempt_id'])
        report_ref = json.loads((directory / 'index.json').read_text())['report_ref']
        report = read(report_ref)
        require(report['attempt_id'] == context['attempt_id']
                and datetime.fromisoformat(report['started_at']) >= datetime.fromisoformat(context['scheduled_at']),
                'JEV_E2E_SCHEDULE_BINDING_MISMATCH')
        python = ROOT / '.research-sources/.venv/bin/python'
        require(python.is_file(), 'JEV_E2E_VALIDATOR_ENVIRONMENT_REQUIRED')
        temp = private_path(ROOT / '.research-sources/jev-validator-tmp', create=True)
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'USER', 'LANG') if key in os.environ}
        env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(temp))
        process = subprocess.run([str(python), '-m', 'investment.research.jev_acceptance',
            '--manifest-ref', json.dumps(options['manifest_ref']), '--verify-report-ref', json.dumps(report_ref)],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=30)
        require(process.returncode == 0 and len(process.stdout) <= 32768, 'JEV_E2E_HOST_VALIDATION_FAILED')
        checked = json.loads(process.stdout)
        require(isinstance(checked, dict) and checked.get('verified') is True,
                'JEV_E2E_HOST_VALIDATION_FAILED')
        return {**checked, 'change_id': selected['change_id']}
    except Exception:
        return {'verified': False}


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest-ref', required=True); p.add_argument('--out')
    p.add_argument('--attempt-id'); p.add_argument('--allow-live', action='store_true')
    p.add_argument('--verify-report-ref')
    a = p.parse_args()
    try:
        if a.verify_report_ref is not None:
            require(not a.allow_live and a.out is None and a.attempt_id is None, 'JEV_E2E_VALIDATOR_ARGUMENTS_INVALID')
            print(json.dumps(validate_report(json.loads(a.verify_report_ref), json.loads(a.manifest_ref))))
            return 0
        require(a.out is not None and a.attempt_id is not None, 'JEV_E2E_EXECUTION_ARGUMENTS_REQUIRED')
        result = exercise(json.loads(a.manifest_ref), a.out, attempt_id=a.attempt_id, allow_live=a.allow_live)
        print(json.dumps({k: result[k] for k in ('status', 'code', 'report_directory', 'delivery_verified')}))
        return 0 if result['status'] == 'completed' else 2
    except Exception as exc:
        code = str(exc) if isinstance(exc, SourceError) and re.fullmatch(r'[A-Z][A-Z_0-9]{0,99}', str(exc)) else 'JEV_E2E_FAILED'
        print(json.dumps({'status': 'failed', 'code': code, 'delivery_verified': False})); return 2


if __name__ == '__main__':
    raise SystemExit(main())
