"""Sealed development/validation packets and a tiny append-only attempt ledger.

Packet separation is not an OS security boundary or proof of blindness. The host
owns execution, observed usage, source closure selection, and grading callbacks.
This module does not rank models or establish investment alpha.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re

from shared.research_sources.artifacts import ROOT, SourceError, digest, encoded, private_path, read, require, save


_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}')
_SHA = re.compile(r'[a-f0-9]{64}')
_SPEC_KEYS = {'id', 'version', 'split', 'blindness', 'cases', 'metrics', 'budget'}
_CONTRACT_KEYS = _SPEC_KEYS | {'schema_version', 'kind', 'spec_source', 'grader_sources',
    'candidate_fingerprints', 'blindness_enforcement', 'scope', 'superiority_established', 'sealed_at'}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _name(value):
    require(isinstance(value, str) and _NAME.fullmatch(value), 'EVAL_ID_INVALID')
    return value


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _source(path):
    path = Path(os.path.abspath(ROOT / path if not Path(path).is_absolute() else path))
    require(path.is_relative_to(ROOT) and path != ROOT, 'EVAL_SOURCE_PATH_REJECTED')
    for part in (path, *path.parents):
        if part == ROOT:
            break
        require(not part.is_symlink(), 'EVAL_SOURCE_PATH_REJECTED')
    require(path.is_file() and path.stat().st_size <= 8 * 1024 * 1024, 'EVAL_SOURCE_INVALID')
    raw = path.read_bytes()
    return {'path': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(raw).hexdigest()}, raw


def _spec(value):
    require(isinstance(value, dict) and set(value) == _SPEC_KEYS, 'EVAL_SPEC_SCHEMA')
    _name(value['id'])
    require(type(value['version']) is int and value['version'] > 0 or
            isinstance(value['version'], str) and _NAME.fullmatch(value['version']), 'EVAL_VERSION_INVALID')
    require(value['split'] in ('development', 'validation', 'protected'), 'EVAL_SPLIT_INVALID')
    require(value['blindness'] in ('unblinded', 'answers_withheld'), 'EVAL_BLINDNESS_INVALID')
    require(isinstance(value['metrics'], list) and 0 < len(value['metrics']) <= 64 and
            len(set(value['metrics'])) == len(value['metrics']), 'EVAL_METRICS_INVALID')
    for metric in value['metrics']:
        _name(metric)
    budget = value['budget']
    require(isinstance(budget, dict) and 0 < len(budget) <= 32, 'EVAL_BUDGET_INVALID')
    require(all(_NAME.fullmatch(k) and _number(v) for k, v in budget.items()), 'EVAL_BUDGET_INVALID')
    require(isinstance(value['cases'], list) and 0 < len(value['cases']) <= 1000, 'EVAL_CASES_INVALID')
    seen = set()
    for case in value['cases']:
        require(isinstance(case, dict) and set(case) == {'id', 'input', 'expected', 'critical'}, 'EVAL_CASE_SCHEMA')
        _name(case['id'])
        require(case['id'] not in seen, 'EVAL_DUPLICATE_CASE')
        require(type(case['critical']) is bool, 'EVAL_CRITICAL_INVALID')
        seen.add(case['id'])
    return value


def _pins(value):
    require(isinstance(value, dict) and 'candidate' in value and set(value) <= {'baseline', 'candidate'}, 'EVAL_PINS_INVALID')
    for pin in value.values():
        require(isinstance(pin, str) and _SHA.fullmatch(pin) or isinstance(pin, dict) and bool(pin), 'EVAL_PIN_INVALID')
        encoded(pin)
    return value


def _publish(directory, name, value):
    """Publish only complete bytes; an existing named record is never replaced."""
    directory = private_path(directory, create=True)
    ref = save(directory / 'blobs', value)
    path = directory / name
    try:
        os.link(ref['path'], path)
    except FileExistsError:
        raise SourceError('EVAL_RECORD_EXISTS') from None
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return ref


def _named(directory, name):
    path = private_path(directory / name)
    require(path.is_file() and path.stat().st_size <= 8 * 1024 * 1024, 'EVAL_ATTEMPT_NOT_FOUND')
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    ref = {'path': str(directory / 'blobs' / (sha + '.json')), 'sha256': sha}
    return read(ref), ref


@contextmanager
def _lock(directory):
    directory = private_path(directory, create=True)
    fd = os.open(directory / 'claim.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SourceError('EVAL_CLAIM_BUSY') from None
        yield directory
    finally:
        os.close(fd)


def seal(spec_path, grader_paths, candidate_fingerprints, directory):
    """Freeze case inputs/answers separately and hash the explicit source closure."""
    root = private_path(directory, create=True)
    spec_source, raw = _source(spec_path)
    try:
        spec = _spec(json.loads(raw))
    except (TypeError, ValueError) as exc:
        if isinstance(exc, SourceError):
            raise
        raise SourceError('EVAL_SPEC_SCHEMA') from None
    pins = _pins(candidate_fingerprints)
    require(isinstance(grader_paths, (list, tuple)) and bool(grader_paths), 'EVAL_GRADER_SOURCES_REQUIRED')
    closure = [_source(path)[0] for path in grader_paths]
    require(len({p['path'] for p in closure}) == len(closure), 'EVAL_GRADER_SOURCE_DUPLICATE')
    contract = {k: spec[k] for k in ('id', 'version', 'split', 'blindness', 'metrics', 'budget')}
    contract.update(schema_version=1, kind='sealed_evaluation_contract', spec_source=spec_source,
        grader_sources=sorted(closure, key=lambda x: x['path']), candidate_fingerprints=pins,
        cases=[{'id': case['id'], 'critical': case['critical'],
                'input_ref': save(root / 'packets/inputs', case['input']),
                'expected_ref': save(root / 'packets/expected', case['expected'])} for case in spec['cases']],
        blindness_enforcement='packet_separation_only_no_os_isolation',
        scope='development_conformance' if spec['split'] == 'development' else 'declared_evaluation_split',
        superiority_established=False)
    registry = root / 'sealed' / spec['id'] / str(spec['version'])
    with _lock(registry):
        if (registry / 'contract.json').exists():
            prior, ref = _named(registry, 'contract.json')
            require({k: v for k, v in prior.items() if k != 'sealed_at'} == contract, 'EVAL_VERSION_CONFLICT')
            validate(ref, candidate_fingerprints=pins)
            return ref
        contract['sealed_at'] = _now()
        ref = _publish(registry, 'contract.json', contract)
    validate(ref, candidate_fingerprints=pins)
    return ref


def validate(contract_ref, *, candidate_fingerprints=None):
    """Re-open frozen packets and verify current spec/grader bytes before/after work."""
    contract = read(contract_ref)
    require(isinstance(contract, dict) and set(contract) == _CONTRACT_KEYS and
            contract.get('kind') == 'sealed_evaluation_contract' and type(contract.get('schema_version')) is int
            and contract['schema_version'] == 1,
            'EVAL_CONTRACT_INVALID')
    require(contract['blindness_enforcement'] == 'packet_separation_only_no_os_isolation' and
            contract['superiority_established'] is False and contract['scope'] ==
            ('development_conformance' if contract['split'] == 'development' else 'declared_evaluation_split'),
            'EVAL_CONTRACT_INVALID')
    require(isinstance(contract['cases'], list) and all(isinstance(case, dict) and
            set(case) == {'id', 'critical', 'input_ref', 'expected_ref'} for case in contract['cases']), 'EVAL_CASE_SCHEMA')
    _pins(contract['candidate_fingerprints'])
    for source in (contract['spec_source'], *contract['grader_sources']):
        observed, _ = _source(source['path'])
        require(observed == source, 'EVAL_SOURCE_CHANGED')
    _, raw = _source(contract['spec_source']['path'])
    spec = _spec(json.loads(raw))
    require([{k: c[k] for k in ('id', 'critical')} for c in contract['cases']] ==
            [{k: c[k] for k in ('id', 'critical')} for c in spec['cases']], 'EVAL_CASE_ROSTER_CHANGED')
    for case, original in zip(contract['cases'], spec['cases']):
        require(encoded(read(case['input_ref'])) == encoded(original['input']) and
                encoded(read(case['expected_ref'])) == encoded(original['expected']),
                'EVAL_PACKET_CHANGED')
    require(all(contract[k] == spec[k] for k in ('id', 'version', 'split', 'blindness', 'metrics', 'budget')),
            'EVAL_SPEC_CHANGED')
    if candidate_fingerprints is not None:
        require(encoded(_pins(candidate_fingerprints)) == encoded(contract['candidate_fingerprints']), 'EVAL_PIN_CHANGED')
    return contract


def worker_packet(contract_ref):
    """Answers withheld from this packet only; no filesystem blindness is claimed."""
    contract = validate(contract_ref)
    return {k: contract[k] for k in ('id', 'version', 'split', 'blindness', 'blindness_enforcement')} | {
        'cases': [{'id': case['id'], 'input_ref': case['input_ref']} for case in contract['cases']],
        'budget': contract['budget']}


def _attempt_root(directory, contract_ref):
    read(contract_ref)
    return private_path(Path(directory) / 'attempts' / contract_ref['sha256'], create=True)


def begin(contract_ref, directory, attempt_id, *, arm, budget, fingerprint):
    """Claim once before execution. Existing or unknown claims cannot be replayed."""
    _name(attempt_id)
    contract = validate(contract_ref)
    require(arm in contract['candidate_fingerprints'], 'EVAL_ARM_UNKNOWN')
    require(encoded(budget) == encoded(contract['budget']), 'EVAL_BUDGET_MISMATCH')
    require(encoded(fingerprint) == encoded(contract['candidate_fingerprints'][arm]), 'EVAL_PIN_CHANGED')
    with _lock(_attempt_root(directory, contract_ref)) as root:
        require(not (root / (attempt_id + '.claim.json')).exists(), 'EVAL_ATTEMPT_EXISTS')
        claim = {'schema_version': 1, 'kind': 'evaluation_attempt_claim', 'contract_ref': contract_ref,
                 'attempt_id': attempt_id, 'arm': arm, 'budget': budget, 'fingerprint': fingerprint,
                 'started_at': _now(), 'state': 'started', 'replay_allowed': False}
        return _publish(root, attempt_id + '.claim.json', claim)


def _reason(exc):
    value = str(exc)
    return value if isinstance(exc, SourceError) and re.fullmatch('[A-Z][A-Z_0-9]{0,99}', value) else 'EVAL_GRADER_FAILED'


def finish(contract_ref, directory, attempt_id, *, submissions, usage, grade):
    """Host grades immutable outputs; failures survive and critical failures dominate.

    A durable finish intent precedes callbacks. Process death after that intent is
    an unknown outcome and requires inspection, never automatic callback replay.
    """
    _name(attempt_id)
    root = _attempt_root(directory, contract_ref)
    with _lock(root):
        claim, claim_ref = _named(root, attempt_id + '.claim.json')
        require(claim['contract_ref'] == contract_ref and claim['attempt_id'] == attempt_id, 'EVAL_CLAIM_MISMATCH')
        require(not (root / (attempt_id + '.result.json')).exists(), 'EVAL_ATTEMPT_FINISHED')
        require(not (root / (attempt_id + '.intent.json')).exists(), 'EVAL_ATTEMPT_OUTCOME_UNKNOWN')
        intent = {'claim_ref': claim_ref, 'submissions': submissions, 'usage': usage, 'started_at': _now()}
        intent_ref = _publish(root, attempt_id + '.intent.json', intent)
        rows, unknowns, errors = [], [], []
        try:
            contract = validate(contract_ref)
            require(encoded(claim['budget']) == encoded(contract['budget']) and
                    encoded(claim['fingerprint']) == encoded(contract['candidate_fingerprints'][claim['arm']]), 'EVAL_CLAIM_MISMATCH')
            require(isinstance(usage, dict) and set(usage) == set(contract['budget']) and
                    all(_number(v) for v in usage.values()), 'EVAL_USAGE_INVALID')
            require(all(usage[k] <= limit for k, limit in contract['budget'].items()), 'EVAL_BUDGET_EXCEEDED')
            require(isinstance(submissions, list), 'EVAL_SUBMISSIONS_INVALID')
            for submitted in submissions:
                require(isinstance(submitted, dict) and set(submitted) == {'id', 'output_ref'}, 'EVAL_SUBMISSION_SCHEMA')
                _name(submitted['id'])
            ids = [row['id'] for row in submissions]
            require(len(ids) == len(set(ids)), 'EVAL_DUPLICATE_SUBMISSION')
            require(set(ids) == {case['id'] for case in contract['cases']}, 'EVAL_CASE_ROSTER_MISMATCH')
            require(callable(grade), 'EVAL_GRADER_REQUIRED')
            callback_path = inspect.getsourcefile(grade)
            require(callback_path is not None and _source(callback_path)[0] in contract['grader_sources'], 'EVAL_GRADER_UNPINNED')
            by_id = {item['id']: item for item in submissions}
            for case in contract['cases']:
                output = read(by_id[case['id']]['output_ref'])
                verdict = grade(case['id'], read(case['input_ref']), read(case['expected_ref']), output)
                require(isinstance(verdict, dict) and set(verdict) == {'passed', 'metrics', 'reasons'} and
                        type(verdict['passed']) is bool, 'EVAL_VERDICT_SCHEMA')
                metrics = verdict['metrics']
                require(isinstance(metrics, dict) and set(metrics) == set(contract['metrics']) and
                        all(v is None or type(v) is bool or _finite(v) for v in metrics.values()), 'EVAL_REQUIRED_METRIC_MISSING')
                require(isinstance(verdict['reasons'], list) and all(isinstance(r, str) and len(r) <= 2000
                        for r in verdict['reasons']), 'EVAL_VERDICT_SCHEMA')
                unknowns.extend({'case_id': case['id'], 'metric': k} for k, v in metrics.items() if v is None)
                rows.append({'id': case['id'], 'critical': case['critical'], 'output_ref': by_id[case['id']]['output_ref'], **verdict})
            validate(contract_ref)  # Do not accept source changes during callbacks.
        except Exception as exc:
            errors.append(_reason(exc))
        critical = [row['id'] for row in rows if row['critical'] and not row['passed']]
        passed = not errors and bool(rows) and all(row['passed'] for row in rows)
        result = {'schema_version': 1, 'kind': 'host_graded_evaluation_attempt', 'contract_ref': contract_ref,
            'claim_ref': claim_ref, 'intent_ref': intent_ref, 'attempt_id': attempt_id, 'arm': claim['arm'],
            'status': 'passed' if passed else 'failed', 'cases': rows, 'critical_failures': critical,
            'errors': errors, 'usage': usage, 'unknown_metrics': unknowns, 'finished_at': _now(),
            'superiority_established': False, 'blindness_enforcement': 'packet_separation_only_no_os_isolation'}
        return _publish(root, attempt_id + '.result.json', result)
