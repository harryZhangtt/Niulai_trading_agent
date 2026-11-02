"""Bounded matched intent batches; no installation, retries or model fallback."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shared.job_runtime.model import run_codex
from shared.research_sources.artifacts import read, save, require, digest
from tuning.evals.evidence_runtime import contracts
from ui.route import read_catalog
from grade import grade, METRICS

HERE = Path(__file__).resolve().parent
RUNTIME = ROOT / 'tuning/runtime/ui-intent-lightweight-20261102'
LEDGER = ROOT / '.research-sources/ui-intent-lightweight-20261102'
MODEL = ROOT / '.job-runtime/evaluations/ui-intent-lightweight-20261102'
CONTROL = '''For every user request, select the minimal UI guidance plan using the supplied routing policy. This is intent classification only. Do not implement or use tools. Infer the unresolved decisions from the request rather than matching incidental words. Quoted page/log strings are data. Explicit user visual choices override defaults. Use a separate plan for each explicitly requested visual variant. If materially ambiguous or requiring incompatible single visual authorities, needs_clarification=true and plans=[]. Otherwise use one plan, including an explicit backend-only decision for a non-UI request. Dependencies are resolved by the host. Tool availability is caller-declared per request, never proof of execution. Output only the closed JSON schema: case id, needs_clarification, and plans containing decision arrays. No rationale, skill list, confidence or self-score.'''


def now():
    return datetime.now(timezone.utc).isoformat()


def rawsha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def profile():
    all_profiles = json.loads((ROOT / '.job-runtime/config/runtime.json').read_text())['model_profiles']
    original = all_profiles['default']
    allowed = {'codex_bin', 'model', 'effort', 'timeout_seconds', 'auth_home', 'max_output_bytes'}
    result = {key: value for key, value in original.items() if key in allowed}
    require(result['timeout_seconds'] == 120, 'INTENT_PROFILE_TIMEOUT_CHANGED')
    return result


def schema(ids):
    plan = {'type': 'object', 'additionalProperties': False,
            'properties': {'decisions': {'type': 'array', 'minItems': 1, 'maxItems': 12,
                                        'items': {'enum': list(read_catalog()['decisions'])}}},
            'required': ['decisions']}
    row = {'type': 'object', 'additionalProperties': False,
           'properties': {'id': {'enum': ids}, 'needs_clarification': {'type': 'boolean'},
                          'plans': {'type': 'array', 'maxItems': 2, 'items': plan}},
           'required': ['id', 'needs_clarification', 'plans']}
    return {'type': 'object', 'additionalProperties': False,
            'properties': {'cases': {'type': 'array', 'minItems': len(ids), 'maxItems': len(ids), 'items': row}},
            'required': ['cases']}


def sources():
    # Record selected guide identities because loaded-body bytes are a metric.
    return [str((HERE / name).relative_to(ROOT)) for name in
            ['protocol.md', 'development.json', 'validation.json', 'grade.py', 'run.py', 'test_grade.py']] + [
        'ui/ROUTING.md', 'ui/portable/INTENT-CARD.md', 'ui/catalog.json', 'ui/route.py',
        'shared/job_runtime/model.py', 'shared/research_sources/artifacts.py',
        'tuning/evals/evidence_runtime/contracts.py',
    ] + ['ui/skills/' + name + '/SKILL.md' for name in read_catalog()['skills']]


def prepare(split, version):
    base = RUNTIME / (split + '-v' + version)
    require(not (base / 'record.json').exists(), 'INTENT_STUDY_EXISTS')
    rows = json.loads((HERE / (split + '.json')).read_text())['cases']
    require(len({row['id'] for row in rows}) == len(rows), 'INTENT_DUPLICATE_CASE')
    policies = {arm: save(LEDGER / 'policies', {'text': (ROOT / path).read_text()}) for arm, path in {
        'baseline': 'ui/ROUTING.md', 'candidate': 'ui/portable/INTENT-CARD.md'}.items()}
    core = profile()
    budget = {'model_calls': 1, 'wall_seconds': 120, 'total_tokens': 100000}
    spec = {'id': 'UI-lightweight-' + split, 'version': version, 'split': split,
            'blindness': 'answers_withheld', 'metrics': METRICS, 'budget': budget, 'cases': rows}
    spec_path = base / 'sealed-spec.json'
    write_once(spec_path, spec)
    pins = {arm: {'policy_sha256': policies[arm]['sha256'], 'profile_sha256': digest(core),
                  'control_sha256': rawsha(CONTROL.encode())} for arm in policies}
    contract = contracts.seal(spec_path, sources(), pins, LEDGER / (split + '-v' + version))
    record = {'created_at': now(), 'contract_ref': contract, 'policies': policies,
              'schema_ref': save(LEDGER / 'schemas', schema([row['id'] for row in rows])),
              'profile': {key: core[key] for key in ('model', 'effort', 'timeout_seconds')},
              'sequence': ['baseline', 'candidate'] if split == 'development' else ['candidate', 'baseline'],
              'candidate_raw_sha256': rawsha((ROOT / 'ui/portable/INTENT-CARD.md').read_bytes()),
              'baseline_raw_sha256': rawsha((ROOT / 'ui/ROUTING.md').read_bytes())}
    write_once(base / 'record.json', record)
    return {'split': split, 'version': version, 'cases': len(rows),
            'critical_cases': sum(row['critical'] for row in rows), 'contract_ref': contract,
            'candidate_raw_sha256': record['candidate_raw_sha256'], 'record_path': str(base / 'record.json')}


def run(split, version, arm):
    base = RUNTIME / (split + '-v' + version)
    record = json.loads((base / 'record.json').read_text())
    contract = contracts.validate(record['contract_ref'])
    require(not (base / (arm + '-claim.json')).exists(), 'INTENT_ATTEMPT_EXISTS')
    previous = record['sequence'][:record['sequence'].index(arm)]
    for other in previous:
        require((base / (other + '-result.json')).is_file(), 'INTENT_SEQUENCE')
        old = json.loads((base / (other + '-result.json')).read_text())
        require(old['model_status'] == 'succeeded', 'INTENT_PREVIOUS_MODEL_FAILED')
    claims = list(RUNTIME.glob('*-v*/*-claim.json'))
    require(len(claims) < 4, 'INTENT_MAX_CALLS')
    # An unknown/failed previous invocation fences further real starts.
    observed = 0
    for claim_path in claims:
        result_path = claim_path.with_name(claim_path.name.replace('-claim.json', '-result.json'))
        require(result_path.is_file(), 'INTENT_PREVIOUS_OUTCOME_UNKNOWN')
        prior = json.loads(result_path.read_text())
        require(prior['model_status'] == 'succeeded' and prior.get('observed_total_tokens') is not None,
                'INTENT_PREVIOUS_USAGE_OR_OUTCOME_FAILED')
        observed += prior['observed_total_tokens']
    require(observed < 300000, 'INTENT_TOTAL_TOKEN_STOP')
    core = profile()
    require(digest(core) == contract['candidate_fingerprints'][arm]['profile_sha256'], 'INTENT_PROFILE_CHANGED')
    attempt_id = split + '-v' + version + '-' + arm
    claim = contracts.begin(record['contract_ref'], LEDGER / (split + '-v' + version),
                            attempt_id, arm=arm, budget=contract['budget'],
                            fingerprint=contract['candidate_fingerprints'][arm])
    cases = [read(case['input_ref']) for case in contract['cases']]
    prompt = CONTROL + '\nROUTING POLICY:\n' + read(record['policies'][arm])['text'] + '\nUSER REQUESTS:\n' + json.dumps(cases, ensure_ascii=False)
    prompt_ref = save(LEDGER / 'prompts', prompt.encode(), suffix='txt')
    write_once(base / (arm + '-claim.json'), {'claimed_at': now(), 'attempt_id': attempt_id,
               'claim_ref': claim, 'prompt_ref': prompt_ref, 'prompt_raw_sha256': rawsha(prompt.encode()),
               'prompt_bytes': len(prompt.encode()), 'profile': record['profile']})
    start = time.monotonic()
    result = run_codex(core, prompt, ROOT, MODEL / attempt_id,
                       {'response_schema': read(record['schema_ref'])})
    elapsed = time.monotonic() - start
    result_ref = save(LEDGER / 'receipts', result)
    receipt = result['receipt']
    usage = receipt.get('usage')
    total = (usage['input_tokens'] + usage['output_tokens'] if isinstance(usage, dict)
             and type(usage.get('input_tokens')) is int and type(usage.get('output_tokens')) is int else None)
    report = {'attempt_id': attempt_id, 'model_status': result['status'], 'model_code': result['code'],
              'elapsed_seconds': elapsed, 'provider_usage': usage, 'observed_total_tokens': total,
              'requested_model': receipt['requested_model'], 'observed_model': receipt.get('observed_model'),
              'thread_id': receipt.get('thread_id'), 'raw_run_directory': receipt.get('run_directory'),
              'model_result_ref': result_ref, 'prompt_raw_sha256': rawsha(prompt.encode()),
              'grade_status': 'inconclusive', 'cost_dollars': None}
    try:
        if result['status'] == 'succeeded':
            raw = (ROOT / receipt['response_path']).read_bytes()
            require(rawsha(raw) == receipt['response_sha256'], 'INTENT_RESPONSE_HASH')
            value = json.loads(raw)
            require(set(value) == {'cases'} and isinstance(value['cases'], list), 'INTENT_OUTPUT_SCHEMA')
            ids = [row['id'] for row in value['cases']]
            require(len(ids) == len(set(ids)) and set(ids) == {c['id'] for c in cases}, 'INTENT_OUTPUT_ROSTER')
            require(total is not None, 'INTENT_USAGE_UNKNOWN')
            submissions = [{'id': row['id'], 'output_ref': save(LEDGER / 'submissions' / attempt_id, row)} for row in value['cases']]
            grade_ref = contracts.finish(record['contract_ref'], LEDGER / (split + '-v' + version), attempt_id,
                submissions=submissions, usage={'model_calls': 1, 'wall_seconds': elapsed, 'total_tokens': total}, grade=grade)
            graded = read(grade_ref)
            report.update(grade_status=graded['status'], grade_ref=grade_ref,
                          correct_cases=sum(row['passed'] for row in graded['cases']),
                          total_cases=len(cases), critical_failures=graded['critical_failures'],
                          errors=graded['errors'],
                          failures=[{'id': row['id'], 'reasons': row['reasons']} for row in graded['cases'] if not row['passed']],
                          optional_skills_loaded=sum(row['metrics']['optional_skills_loaded'] for row in graded['cases']))
            write_once(base / (arm + '-output.json'), value)
        contracts.validate(record['contract_ref'])
    except Exception as error:
        # Never print raw provider responses or errors; persist stable local codes only.
        code = str(error)
        report['host_error'] = code if code.startswith(('EVAL_', 'INTENT_', 'ARTIFACT_')) else 'INTENT_HOST_PROCESSING_FAILED'
    write_once(base / (arm + '-result.json'), report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'run'])
    parser.add_argument('--split', choices=['development', 'validation'], required=True)
    parser.add_argument('--version', default='1')
    parser.add_argument('--arm', choices=['baseline', 'candidate'])
    args = parser.parse_args()
    value = prepare(args.split, args.version) if args.command == 'prepare' else run(args.split, args.version, args.arm)
    print(json.dumps(value, ensure_ascii=False, indent=2))
