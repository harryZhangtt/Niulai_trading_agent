"""A bounded cache workload with real cold fetch and explicitly labeled replay.

This harness exercises acquisition reuse and request-specific eligibility. It
does not turn a cache hit into a supported investment conclusion. Existing cache
stress cases are reused in a child process with retained independent receipts.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

from .artifacts import ROOT, SourceError, private_path, read, require, save
from .cache import Cache, FetchKey, validate_source
from . import source_matrix as sources
from .store import Store, instant

TOTAL_SECONDS = 180
ISSUER_CASE = 'official_document.nvidia_release'
MODULES = ('cache_matrix.py', 'cache.py', 'store.py', 'source_matrix.py', 'tests/test_cache.py')


def _now():
    return datetime.now(timezone.utc).isoformat()


def _fingerprint():
    return {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() for name in MODULES}


def _key(case_id):
    case = sources.CASES[case_id]
    if case['capability'] == 'discover':
        parameters = {'query': case['target']}
    elif case_id.startswith('arxiv'):
        parameters = {'paper_id': case['target']}
    else:
        parameters = {'url': case['target']}
    return FetchKey(case['provider'], case['capability'], parameters,
                    native_version='2' if case_id.startswith('arxiv') and case['capability'] == 'read' else None)


def _unavailable():
    raise SourceError('CONTROLLED_FETCH_UNAVAILABLE')


def _eligible(case_id, directory):
    def check(receipt):
        quality = sources.inspect(case_id, save(directory, receipt))
        return None if quality['status'] == 'pass' else 'CLAIM_COVERAGE_INSUFFICIENT'
    return check


def _source_captures(source_matrix_ref):
    if source_matrix_ref is None:
        return {}
    report = read(source_matrix_ref)
    require(report.get('kind') == 'bounded_source_runtime_matrix', 'SOURCE_MATRIX_REPORT_REQUIRED')
    # Deduplicate repeated primary/fallback operations without inventing calls.
    result = {}
    for attempt in report['attempts']:
        if attempt.get('source_ref') and attempt['case_id'] in sources.CASES:
            read(attempt['source_ref'])
            result[attempt['case_id']] = attempt['source_ref']
    return result


def _timed(operation):
    start = time.monotonic()
    result = operation()
    return {'outcome': result.to_dict(), 'elapsed_seconds': time.monotonic() - start}


def _runtime_stress(directory):
    """Reuse the reviewed fixture methods; keep their counter and attempts."""
    from .tests.test_cache import CacheTests

    def case_at(name, child):
        case = CacheTests(name)
        case.directory = private_path(directory / child, create=True)
        case.store = Store(case.directory / 'store')
        case.at = datetime.now(timezone.utc)
        case.clock = [case.at]
        case.cache = Cache(case.store, now=lambda: case.clock[0])
        case.key = FetchKey('official_document', 'read', {'url': 'https://example.com/q1', 'period': '2025Q1'})
        case.source = case.document()
        case.calls = 0
        return case

    def attempt_refs(case):
        result = []
        for path in case.store.blobs.glob('*.json'):
            ref = {'path': str(path), 'sha256': path.stem}
            value = read(ref)
            if value.get('scope') == 'acquisition_integrity_and_declared_eligibility':
                result.append(ref)
        return result

    five = case_at('test_five_process_same_key_singleflight', 'five-process')
    try:
        five.test_five_process_same_key_singleflight()
        five_result = {'status': 'pass', 'processes': 5, 'counter_path': str(five.directory / 'provider-count'),
            'counter_ref': save(five.directory, (five.directory / 'provider-count').read_bytes(), suffix='txt'),
            'source_ref': five.source, 'fetch_key': five.key.to_dict(), 'store_directory': str(five.store.directory),
            'attempt_refs': attempt_refs(five)}
    finally:
        five.doCleanups()
    hundred = case_at('test_hundred_warm_reads_zero_provider_calls', 'hundred-warm')
    hundred.test_hundred_warm_reads_zero_provider_calls()
    hundred_result = {'status': 'pass', 'source_callback_count': hundred.calls,
        'source_ref': hundred.source, 'fetch_key': hundred.key.to_dict(),
        'store_directory': str(hundred.store.directory), 'attempt_refs': attempt_refs(hundred)}
    return {'ok': True, 'classification': 'controlled_fixture_subprocess_stress',
            'actual_public_provider_calls': 0, 'five_process': five_result, 'hundred_warm': hundred_result,
            'limitations': ['Counter measures controlled callback execution, not remote HTTP service capacity.']}


def _stress(directory, timeout):
    return sources._process([sys.executable, '-m', 'shared.research_sources.cache_matrix',
                             '--stress', '--out', str(directory)], timeout)


def run(out, source_matrix_ref=None, *, executor=None, stress_runner=None):
    """One real cold fetch, warm hit, captured-source replays, and bounded stress."""
    root = private_path(out, create=True)
    directory = private_path(root / ('run-' + uuid.uuid4().hex), create=True)
    started = _now()
    began, candidate = time.monotonic(), _fingerprint()
    deadline = began + TOTAL_SECONDS
    captures = _source_captures(source_matrix_ref)
    manifest_ref = save(directory, {'schema_version': 1, 'candidate': candidate,
        'source_matrix_ref': source_matrix_ref, 'frozen_capture_refs': captures,
        'max_seconds': TOTAL_SECONDS, 'maximum_actual_issuer_acquisitions': 1,
        'expected_cold_route': 'fetch', 'expected_warm_route': 'cache_hit',
        'quality_checker_version': sources.CHECKER_VERSION,
        'negative_cases': ['wrong_url_key', 'expired_without_stale_policy',
                           'expired_fixed_fact_fallback', 'corrupt_own_copy'],
        'stress_cases': ['five_process_same_key_singleflight', 'hundred_warm_reads_zero_provider_calls']})

    def remaining(limit=20):
        return max(.001, min(limit, deadline - time.monotonic()))

    def end(limit=20):
        return time.monotonic() + remaining(limit)

    live_store = Store(directory / 'live-cache')
    live_cache = Cache(live_store)
    live_calls, actual_attempts = [], []

    def acquire():
        require(time.monotonic() < deadline, 'CACHE_MATRIX_DEADLINE_EXPIRED')
        require(not live_calls, 'IDENTICAL_SOURCE_ATTEMPT_NOT_RETRIED')
        live_calls.append({'started_at': _now()})
        result = (executor or sources._execute)(ISSUER_CASE, directory / 'live-source', None,
                                                timeout=remaining(26))
        actual_attempts.append(result)
        require(result.get('ok'), result.get('error', 'ISSUER_COLD_FETCH_FAILED'))
        return result['source_ref']

    issuer_key = _key(ISSUER_CASE)
    cold = _timed(lambda: live_cache.get_or_fetch(issuer_key, acquire, deadline=end(32),
                  eligible=_eligible(ISSUER_CASE, directory / 'quality'), max_age_seconds=3600))
    before_warm = len(live_calls)
    warm = _timed(lambda: live_cache.get_or_fetch(issuer_key, acquire, deadline=end(),
                  eligible=_eligible(ISSUER_CASE, directory / 'quality'), max_age_seconds=3600))
    # The callback guard prevents a second source attempt after a failed cold call.
    live = {'case_id': ISSUER_CASE, 'store_directory': str(live_store.directory),
            'fetch_key': issuer_key.to_dict(), 'cold': cold, 'warm': warm,
            'callback_count_before_warm': before_warm, 'callback_count_after_warm': len(live_calls),
            'actual_attempts': actual_attempts, 'callback_events': live_calls,
            'quality': sources.inspect(ISSUER_CASE, cold['outcome']['source_ref'])
                       if cold['outcome']['source_ref'] else None}

    replays = []
    for case_id, capture_ref in captures.items():
        store = Store(directory / 'replay' / case_id)
        cache, key = Cache(store), _key(case_id)
        imports = []

        def import_capture(ref=capture_ref):
            imports.append(ref)
            return ref

        imported = _timed(lambda: cache.get_or_fetch(key, import_capture, deadline=end(), max_age_seconds=3600))
        integrity_warm = _timed(lambda: cache.get_or_fetch(key, _unavailable, deadline=end(), max_age_seconds=3600))
        quality = sources.inspect(case_id, capture_ref)
        decision_warm = _timed(lambda: cache.get_or_fetch(key, _unavailable, deadline=end(), max_age_seconds=3600,
                                                        eligible=_eligible(case_id, directory / 'quality')))
        replays.append({'case_id': case_id, 'classification': 'import_of_recorded_live_capture',
            'source_ref': capture_ref, 'store_directory': str(store.directory), 'fetch_key': key.to_dict(),
            'import': imported, 'integrity_warm': integrity_warm, 'decision_eligible_warm': decision_warm,
            'import_callback_count': len(imports), 'actual_provider_calls': 0, 'claim_coverage': quality,
            'limitation': 'Import is a cache population operation, not a new source retrieval.'})

    seed_ref = cold['outcome']['source_ref'] or captures.get(ISSUER_CASE)
    negatives = {'status': 'blocked', 'reason': 'NO_VALID_ISSUER_CAPTURE'}
    if seed_ref:
        seed = read(seed_ref)
        store = Store(directory / 'negative-cache')
        cache = Cache(store)
        wrong_key = FetchKey('official_document', 'read', {'url': sources.CASES['official_document.nvidia_blackwell']['target']})
        wrong = _timed(lambda: cache.get_or_fetch(wrong_key, lambda: seed_ref, deadline=end()))
        wall = [datetime.now(timezone.utc)]
        expiry_cache = Cache(Store(directory / 'expiry-cache'), now=lambda: wall[0])
        expiry_seed = _timed(lambda: expiry_cache.get_or_fetch(issuer_key, lambda: seed_ref, deadline=end(), max_age_seconds=1))
        wall[0] += timedelta(seconds=2)
        expired = _timed(lambda: expiry_cache.get_or_fetch(issuer_key, _unavailable, deadline=end(), max_age_seconds=1))
        stale = _timed(lambda: expiry_cache.get_or_fetch(issuer_key, _unavailable, deadline=end(), max_age_seconds=1,
                       allow_stale=True, eligible=_eligible(ISSUER_CASE, directory / 'quality')))
        # Corrupt only a private clone; other evidence artifacts remain immutable.
        copied = dict(seed, raw=save(directory / 'corrupt-copy', read(seed['raw'], json_value=False), suffix='html'),
                      text=save(directory / 'corrupt-copy', read(seed['text'], json_value=False), suffix='txt'))
        copied_ref = save(directory / 'corrupt-copy', copied)
        corrupt_store = Store(directory / 'corrupt-cache')
        corrupt_cache = Cache(corrupt_store)
        corrupt_seed = _timed(lambda: corrupt_cache.get_or_fetch(issuer_key, lambda: copied_ref, deadline=end()))
        Path(copied['text']['path']).write_bytes(b'Injected corruption in this private test copy only.')
        corrupt = _timed(lambda: corrupt_cache.get_or_fetch(issuer_key, _unavailable, deadline=end()))
        negatives = {'status': 'exercised', 'wrong_key': wrong, 'wrong_key_value': wrong_key.to_dict(),
            'wrong_key_store_directory': str(store.directory), 'expiry_seed': expiry_seed,
            'expiry_without_policy': expired, 'expiry_explicit_fixed_fact_fallback': stale,
            'expiry_store_directory': str(expiry_cache.store.directory), 'controlled_cache_clock': wall[0].isoformat(),
            'original_retrieved_at': seed['retrieved_at'], 'source_ref': seed_ref,
            'corrupt_seed': corrupt_seed, 'corrupt': corrupt, 'corrupt_source_ref': copied_ref,
            'corrupt_store_directory': str(corrupt_store.directory), 'fault_injected': True,
            'actual_provider_calls': 0}

    stress = (stress_runner or _stress)(directory / 'stress', remaining(70))
    report = {'schema_version': 1, 'kind': 'bounded_runtime_cache_matrix', 'manifest_ref': manifest_ref,
        'execution_mode': 'fixture_injected_executor' if executor is not None else 'isolated_live',
        'stress_execution_mode': 'injected_runner' if stress_runner is not None else 'controlled_subprocesses',
        'candidate': candidate, 'started_at': started, 'finished_at': _now(),
        'elapsed_seconds': time.monotonic() - began, 'max_seconds': TOTAL_SECONDS,
        'live': live, 'replays': replays, 'negatives': negatives, 'stress': stress,
        'limitations': ['One cold issuer request does not establish provider-wide reliability.',
            'Replay uses captured live payloads and sends no new requests to those providers.',
            'Cache eligibility and claim coverage are reported separately; metadata remains discovery.',
            'Future scheduled Codex acceptance and verified notification remain separate.']}
    ref = save(directory, report)
    verdict = verify(ref, allow_fixture=executor is not None or stress_runner is not None)
    status = ('pass' if verdict['verified'] else 'qualified' if
              verdict.get('assessment') == 'incomplete_verification_evidence' else 'failed')
    return {'report_ref': ref, 'status': status, 'verification': verdict}


def _verify_outcome(value, key):
    outcome = value['outcome']
    require(len(outcome['attempt_refs']) == 1, 'CACHE_ATTEMPT_RECEIPT_REQUIRED')
    receipt = read(outcome['attempt_refs'][0])
    for name in ('status', 'source_ref', 'route', 'cache_hit', 'fetch_executed', 'reasons'):
        require(outcome[name] == receipt[name], 'CACHE_OUTCOME_RECEIPT_MISMATCH')
    require(receipt['fetch_key'] == key.to_dict(), 'CACHE_OUTCOME_KEY_MISMATCH')
    return outcome


def _fetch_key(value):
    return FetchKey(**{k: v for k, v in value.items() if k != 'schema_version'})


def verify(report_ref, *, allow_fixture=False):
    """Re-read source bytes, cache attempts, end states, and stress counter."""
    try:
        report = read(report_ref)
        require(report['kind'] == 'bounded_runtime_cache_matrix', 'CACHE_MATRIX_REPORT_REQUIRED')
        require(allow_fixture or report.get('execution_mode') == 'isolated_live'
                and report.get('stress_execution_mode') == 'controlled_subprocesses', 'FIXTURE_NOT_LIVE_RUNTIME_EVIDENCE')
        manifest = read(report['manifest_ref'])
        require(report['candidate'] == manifest['candidate'] == _fingerprint(), 'CACHE_MATRIX_CANDIDATE_CHANGED')
        require(0 <= (instant(report['finished_at']) - instant(report['started_at'])).total_seconds() <= TOTAL_SECONDS,
                'CACHE_MATRIX_DEADLINE_EXCEEDED')
        live, key = report['live'], _key(ISSUER_CASE)
        cold, warm = _verify_outcome(live['cold'], key), _verify_outcome(live['warm'], key)
        require(cold['status'] == 'usable' and cold['route'] == 'fetch' and not cold['cache_hit'], 'LIVE_COLD_NOT_OBSERVED')
        require(warm['route'] == 'cache_hit' and not warm['fetch_executed'] and warm['source_ref'] == cold['source_ref'],
                'LIVE_WARM_REFETCHED')
        require(live['callback_count_before_warm'] == live['callback_count_after_warm'] == len(live['actual_attempts']) == 1,
                'LIVE_PROVIDER_CALL_COUNT_INVALID')
        direct = live['actual_attempts'][0]
        http = direct.get('http_attempts') or []
        require(direct.get('ok') and len(http) == 1 and http[0].get('status') == 'returned'
                and http[0]['url'] == sources.ISSUER_URL, 'ACTUAL_ISSUER_HTTP_NOT_OBSERVED')
        source = validate_source(key, cold['source_ref'])
        require(instant(report['started_at']) <= instant(source['retrieved_at']) <= instant(report['finished_at']),
                'LIVE_SOURCE_NOT_FRESHLY_OBSERVED')
        require(sources.inspect(ISSUER_CASE, cold['source_ref'])['status'] == 'pass', 'LIVE_CLAIM_COVERAGE_FAILED')
        require(Store(live['store_directory']).cache_read(key.sha256)['source_ref'] == cold['source_ref'],
                'LIVE_CACHE_END_STATE_INVALID')

        frozen = manifest['frozen_capture_refs']
        require({r['case_id']: r['source_ref'] for r in report['replays']} == frozen, 'CACHE_REPLAY_ROSTER_CHANGED')
        for replay in report['replays']:
            case_id, key = replay['case_id'], _fetch_key(replay['fetch_key'])
            require(key.to_dict() == _key(case_id).to_dict() and replay['actual_provider_calls'] == 0
                    and replay['import_callback_count'] == 1, 'CACHE_REPLAY_CALLS_INVALID')
            imported = _verify_outcome(replay['import'], key)
            warm = _verify_outcome(replay['integrity_warm'], key)
            decision = _verify_outcome(replay['decision_eligible_warm'], key)
            require(imported['route'] == 'fetch' and imported['source_ref'] == replay['source_ref']
                    and warm['route'] == 'cache_hit' and not warm['fetch_executed'], 'CACHE_REPLAY_REUSE_FAILED')
            quality = sources.inspect(case_id, replay['source_ref'])
            require(quality == replay['claim_coverage'], 'CACHE_REPLAY_QUALITY_CHANGED')
            require(decision['route'] == ('cache_hit' if quality['status'] == 'pass' else 'unresolved'),
                    'CACHE_REPLAY_CLAIM_LAUNDERED')
            if quality['status'] != 'pass':
                require(decision['source_ref'] is None and 'CLAIM_COVERAGE_INSUFFICIENT' in decision['reasons'],
                        'CACHE_REPLAY_CLAIM_LAUNDERED')
            validate_source(key, warm['source_ref'])
            require(Store(replay['store_directory']).cache_read(key.sha256)['source_ref'] == replay['source_ref'],
                    'CACHE_REPLAY_END_STATE_INVALID')

        negative, key = report['negatives'], _key(ISSUER_CASE)
        require(negative.get('status') == 'exercised', 'CACHE_NEGATIVE_CASES_MISSING')
        wrong_key = _fetch_key(negative['wrong_key_value'])
        wrong = _verify_outcome(negative['wrong_key'], wrong_key)
        require(wrong['status'] == 'unavailable' and 'CACHE_URL_MISMATCH' in wrong['reasons']
                and Store(negative['wrong_key_store_directory']).cache_read(wrong_key.sha256) is None,
                'CACHE_WRONG_KEY_ACCEPTED')
        expired = _verify_outcome(negative['expiry_without_policy'], key)
        stale = _verify_outcome(negative['expiry_explicit_fixed_fact_fallback'], key)
        require(expired['status'] == 'unavailable' and 'CACHE_EXPIRED' in expired['reasons'], 'CACHE_EXPIRED_ACCEPTED')
        require(stale['route'] == 'cache_fallback' and stale['source_ref'] == negative['source_ref']
                and 'CACHE_EXPIRED' in stale['reasons'], 'CACHE_EXPLICIT_STALE_FALLBACK_FAILED')
        require(read(stale['source_ref'])['retrieved_at'] == negative['original_retrieved_at'], 'CACHE_OBSERVATION_REJUVENATED')
        corrupt = _verify_outcome(negative['corrupt'], key)
        require(corrupt['status'] == 'unavailable' and 'ARTIFACT_HASH_MISMATCH' in corrupt['reasons']
                and Store(negative['corrupt_store_directory']).cache_read(key.sha256)['state'] == 'quarantined',
                'CACHE_CORRUPTION_ACCEPTED')
        damaged = read(negative['corrupt_source_ref'])
        try:
            read(damaged['text'], json_value=False)
        except SourceError as exc:
            require(str(exc) == 'ARTIFACT_HASH_MISMATCH', 'CACHE_CORRUPTION_NOT_EXERCISED')
        else:
            raise SourceError('CACHE_CORRUPTION_NOT_EXERCISED')
        # The untouched original remains readable after the injected clone damage.
        validate_source(key, negative['source_ref'])

        stress = report['stress']
        require(stress.get('ok') and stress['actual_public_provider_calls'] == 0, 'CACHE_STRESS_FAILED')
        five, hundred = stress['five_process'], stress['hundred_warm']
        counter = private_path(five['counter_path'])
        require(counter.read_text() == read(five['counter_ref'], json_value=False).decode() == '1',
                'CACHE_SINGLEFLIGHT_COUNTER_INVALID')
        five_attempts = [read(ref) for ref in five['attempt_refs']]
        require(len(five_attempts) == 5 and sum(a['route'] == 'fetch' for a in five_attempts) == 1
                and sum(a['route'] == 'cache_hit' for a in five_attempts) == 4
                and all(a['status'] == 'usable' and a['source_ref'] == five['source_ref'] for a in five_attempts),
                'CACHE_SINGLEFLIGHT_POSTCONDITION_FAILED')
        warm_attempts = [read(ref) for ref in hundred['attempt_refs']]
        require(len(warm_attempts) == 101 and sum(a['route'] == 'fetch' for a in warm_attempts) == 1
                and sum(a['route'] == 'cache_hit' for a in warm_attempts) == 100
                and hundred['source_callback_count'] == 1, 'CACHE_HUNDRED_WARM_POSTCONDITION_FAILED')
        return {'verified': True, 'live_provider_acquisitions': 1, 'additional_warm_provider_calls': 0,
                'replayed_cases': len(frozen), 'replay_provider_calls': 0,
                'five_process_callbacks': 1, 'five_process_cache_hits': 4, 'hundred_warm_hits': 100,
                'scope': 'Acquisition reuse, per-case eligibility, and controlled one-host concurrency; no universal source truth.'}
    except Exception as exc:
        reason = sources._code(exc)
        evidence_only = reason in {'CACHE_ATTEMPT_RECEIPT_REQUIRED', 'CACHE_MATRIX_CANDIDATE_CHANGED',
                                   'FIXTURE_NOT_LIVE_RUNTIME_EVIDENCE'}
        return {'verified': False, 'reason': reason,
                'assessment': 'incomplete_verification_evidence' if evidence_only else 'observed_postcondition_failure',
                'acquisition_rejected': False if evidence_only else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out')
    parser.add_argument('--source-matrix-ref')
    parser.add_argument('--verify')
    parser.add_argument('--stress', action='store_true')
    args = parser.parse_args()
    if args.verify:
        result = verify(json.loads(args.verify))
    else:
        require(args.out is not None, 'CACHE_MATRIX_OUTPUT_REQUIRED')
        result = _runtime_stress(private_path(args.out, create=True)) if args.stress else run(
            args.out, json.loads(args.source_matrix_ref) if args.source_matrix_ref else None)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
