"""Configurable public acquisition batches; no model or semantic admission.

A persistent Cache(Store) is shared across executions. Immutable execution
archives outlive retrieval TTL. An interrupted intent is fenced, never replayed.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid

from jsonschema import Draft202012Validator
from shared.actions import freeze_release, invoke
from shared.actions.runtime import ActionError, _OwnedWorker
from shared.job_runtime.business import _stream
from shared.job_runtime.service import atomic
from . import fetch
from .artifacts import ROOT, SOURCE_STATE, SourceError, digest, encoded, private_path, read, require, save
from .cache import Cache, FetchKey
from .store import Store

VERSION = '1.0.0'
CATALOG = Path(__file__).with_name('catalog.json')
STATE = SOURCE_STATE / 'runtime/batches'
CACHE = SOURCE_STATE / 'cache/acquisition'
EXECUTABLE = {'official_document.read', 'arxiv.read', 'arxiv.discover', 'openalex.discover'}
TRANSIENT = {'SOURCE_NETWORK_FAILED', 'SOURCE_HTTP_502', 'SOURCE_HTTP_503', 'SOURCE_HTTP_504'}
UNKNOWN = {'CACHE_FETCH_TIMEOUT', 'BATCH_DISCOVERY_TIMEOUT', 'ACTION_DEADLINE_EXCEEDED', 'ACTION_WORKER_FAILED',
           'ACTION_WORKER_RECEIPT_MISMATCH', 'ACTION_OUTPUT_LIMIT_EXCEEDED', 'BATCH_DISCOVERY_WORKER_FAILED',
           'CACHE_FETCH_FAILED', 'BATCH_FETCH_FAILED', 'ACTION_EXECUTION_FAILED'}
ID = {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'}


def obj(properties):
    return {'type': 'object', 'additionalProperties': False, 'required': list(properties), 'properties': properties}


ROUTE = obj({'capability': {'type': 'string', 'maxLength': 96}, 'parameters': {'type': 'object', 'maxProperties': 1}})
REQUIREMENT = obj({'id': ID, 'subject': ID, 'access': {'enum': ['document', 'metadata']},
    'routes': {'type': 'array', 'minItems': 1, 'maxItems': 3, 'items': ROUTE},
    'max_attempts': {'type': 'integer', 'minimum': 1, 'maximum': 2},
    'cache_max_age_seconds': {'type': 'number', 'minimum': 0, 'maximum': 604800},
    'timeout_seconds': {'type': 'number', 'minimum': 1, 'maximum': 120}})
CONFIG = obj({'schema_version': {'const': 1}, 'batch_id': ID,
    'query': {'type': 'string', 'minLength': 1, 'maxLength': 1800},
    'requirements': {'type': 'array', 'minItems': 1, 'maxItems': 32, 'items': REQUIREMENT},
    'budget': obj({'deadline_seconds': {'type': 'number', 'minimum': 1, 'maximum': 600},
        'max_workers': {'type': 'integer', 'minimum': 1, 'maximum': 4},
        'max_provider_calls': {'type': 'integer', 'minimum': 1, 'maximum': 64}})})


def stamp(): return datetime.now(timezone.utc).isoformat()


def code(error):
    value = str(error)
    return value if isinstance(error, (SourceError, ActionError)) and re.fullmatch('[A-Z][A-Z_0-9]{0,99}', value) else 'BATCH_FETCH_FAILED'


def configuration(value):
    try: value = json.loads(encoded(value))
    except (TypeError, ValueError): raise SourceError('BATCH_CONFIG_INVALID') from None
    require(Draft202012Validator(CONFIG).is_valid(value), 'BATCH_CONFIG_INVALID')
    catalog = json.loads(CATALOG.read_bytes())
    routes = {provider['id'] + '.' + operation['name']: operation['output_access']
              for provider in catalog['providers'] for operation in provider['operations']}
    seen = set()
    for item in value['requirements']:
        require(item['id'] not in seen, 'BATCH_REQUIREMENT_DUPLICATE'); seen.add(item['id'])
        for route in item['routes']:
            capability = route['capability']; parameters = route['parameters']
            require(capability in routes and routes[capability] == item['access'], 'BATCH_CAPABILITY_ACCESS_INVALID')
            expected = 'url' if capability == 'official_document.read' else 'paper_id' if capability.endswith('.read') else 'query'
            require(set(parameters) == {expected} and isinstance(parameters[expected], str)
                    and 0 < len(parameters[expected]) <= 4096, 'BATCH_PARAMETERS_INVALID')
            provider, operation = capability.split('.', 1)
            FetchKey(provider, operation, parameters)
    return value, catalog


def _discovery(route, directory):
    callback = {'openalex.discover': fetch.discover_openalex, 'arxiv.discover': fetch.discover_arxiv}[route['capability']]
    return {'source_ref': callback(route['parameters']['query'], directory), 'action_execution_ref': None}


def _acquire(route, directory, timeout, request_id, release):
    capability = route['capability']
    if capability.endswith('.read'):
        kind = 'arxiv' if capability == 'arxiv.read' else 'official_document'
        value = route['parameters']['paper_id' if kind == 'arxiv' else 'url']
        outcome = invoke({'schema_version': 1, 'action': 'evidence.acquire_document@1.1.1', 'request_id': request_id,
            'arguments': {'kind': kind, 'value': value}, 'release_ref': release['release_ref'],
            'expected_release_sha256': release['release_sha256']}, output_directory=directory, timeout_seconds=timeout)
        require(outcome['status'] == 'success', (outcome.get('error') or {}).get('code', 'BATCH_ACTION_FAILED'))
        return {'source_ref': outcome['data']['source_ref'], 'action_execution_ref': outcome['execution_ref']}
    # Discovery uses existing credential-free fetchers in the same bounded pipe/
    # unreaped-process-group machinery as registered actions. Never print source text.
    process = subprocess.Popen([sys.executable, '-B', '-m', 'shared.research_sources.batch', '--worker'], cwd=ROOT,
        env={'PATH': '/usr/bin:/bin', 'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1',
             'TMPDIR': str(private_path(directory / 'tmp', create=True))},
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    worker = _OwnedWorker(process)
    try:
        raw, _, reason = _stream(worker, encoded({'route': route, 'directory': str(directory)}), timeout, 65536, None)
    finally:
        try: worker.wait(timeout=2)
        finally:
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe and not pipe.closed: pipe.close()
    require(reason is None, 'BATCH_DISCOVERY_TIMEOUT' if reason == 'BUSINESS_DEADLINE_EXCEEDED' else 'BATCH_DISCOVERY_WORKER_FAILED')
    try: result = json.loads(raw)
    except (ValueError, UnicodeError): raise SourceError('BATCH_DISCOVERY_WORKER_FAILED') from None
    require(isinstance(result, dict), 'BATCH_DISCOVERY_WORKER_FAILED')
    if process.returncode == 1 and result.get('status') == 'failed':
        failure = result.get('code')
        require(isinstance(failure, str) and re.fullmatch('[A-Z][A-Z_0-9]{0,99}', failure), 'BATCH_DISCOVERY_WORKER_FAILED')
        raise SourceError(failure)
    require(process.returncode == 0 and result.get('status') == 'returned', 'BATCH_DISCOVERY_WORKER_FAILED')
    return result['result']


def run_batch(config, *, execution_id=None, state_directory=None, cache_directory=None, fetcher=None, observer=None):
    """One immutable execution; injected test fetchers own their hard I/O timeout.

    ``fetcher(route, directory, timeout_seconds, request_id)`` returns a source
    ArtifactRef or {source_ref, action_execution_ref}. No model is called here.
    Different executions share the configured persistent acquisition cache.
    """
    config, catalog = configuration(config)
    execution_id = execution_id or str(uuid.uuid4())
    try: valid = str(uuid.UUID(execution_id)) == execution_id
    except (ValueError, TypeError, AttributeError): valid = False
    require(valid, 'BATCH_EXECUTION_ID_INVALID')
    root = private_path(state_directory or STATE, create=True)
    directory = private_path(root / execution_id, create=True)
    fd = os.open(directory / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise SourceError('BATCH_EXECUTION_BUSY') from None
        fingerprint = digest(config); final_path = directory / 'final.json'; intent_path = directory / 'intent.json'
        for path in (final_path, intent_path): require(not path.is_symlink(), 'BATCH_POINTER_UNSAFE')
        if final_path.exists():
            ref = json.loads(final_path.read_bytes()); prior = read(ref)
            require(prior.get('execution_id') == execution_id and prior.get('config_sha256') == fingerprint,
                    'BATCH_EXECUTION_CONFLICT')
            return {**prior, 'report_ref': ref, 'idempotent_replay': prior['status'] == 'completed', 'reconciled': True}
        if intent_path.exists():
            intent = read(json.loads(intent_path.read_bytes()))
            require(intent.get('execution_id') == execution_id and intent.get('config_sha256') == fingerprint, 'BATCH_EXECUTION_CONFLICT')
            return {'execution_id': execution_id, 'status': 'unknown', 'reason': 'BATCH_EXECUTION_UNCERTAIN',
                    'report_ref': None, 'idempotent_replay': False, 'reconciled': False}
        started = stamp(); began = time.monotonic(); deadline = began + config['budget']['deadline_seconds']
        config_ref = save(directory, config); catalog_ref = save(directory, catalog)
        script_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        intent = {'kind': 'acquisition_batch_intent', 'execution_id': execution_id, 'config_sha256': fingerprint,
                  'config_ref': config_ref, 'capability_catalog_ref': catalog_ref, 'started_at': started,
                  'script_sha256': script_sha, 'provider_outcome': 'unknown_until_final_manifest'}
        atomic(intent_path, save(directory, intent))
        cache = Cache(Store(cache_directory or CACHE)); reservation = threading.Lock(); dispatched = [0]
        release = (freeze_release('evidence.acquire_document@1.1.1', directory=directory / 'releases')
            if fetcher is None and any(r['capability'] in {'official_document.read', 'arxiv.read'}
                for item in config['requirements'] for r in item['routes']) else None)
        adapter_pin = release['release_sha256'] if release else ('injected' if fetcher else hashlib.sha256(Path(fetch.__file__).read_bytes()).hexdigest())
        # Query labels and execution budgets do not change acquisition identity.
        scope = 'public:batch:' + digest([VERSION, digest(catalog), adapter_pin])

        def requirement(item):
            item_start = time.monotonic(); attempts = []; selected = None; selected_capability = None
            reasons = []; hits = retries = fallbacks = 0; uncertain = False
            for route_number, route in enumerate(item['routes']):
                if route_number: fallbacks += 1
                provider, operation = route['capability'].split('.', 1)
                key = FetchKey(provider, operation, route['parameters'], access_scope=scope,
                    native_version=route['parameters']['paper_id'].rsplit('v', 1)[-1] if route['capability'] == 'arxiv.read' else None)
                for retry in range(item['max_attempts']):
                    if retry: retries += 1
                    action_ref = [None]; before = stamp()
                    attempt_intent_ref = save(directory, {'schema_version': 1, 'kind': 'acquisition_attempt_intent',
                        'execution_id': execution_id, 'requirement_id': item['id'], 'ordinal': len(attempts) + 1,
                        'capability': route['capability'], 'fetch_key_sha256': key.sha256, 'started_at': before,
                        'provider_outcome': 'unknown_until_attempt_result'})
                    def acquire():
                        with reservation:
                            require(time.monotonic() < deadline, 'BATCH_DEADLINE_EXPIRED')
                            require(dispatched[0] < config['budget']['max_provider_calls'], 'BATCH_PROVIDER_BUDGET')
                            dispatched[0] += 1
                        timeout = min(item['timeout_seconds'], deadline - time.monotonic())
                        request_id = execution_id + ':' + item['id'] + ':' + str(len(attempts) + 1)
                        require(timeout > 0, 'BATCH_DEADLINE_EXPIRED')
                        try:
                            result = (fetcher(route, directory / 'sources', timeout, request_id) if fetcher else
                                      _acquire(route, directory / 'sources', timeout, request_id, release))
                        except ActionError as error: raise SourceError(code(error)) from None
                        if isinstance(result, dict) and 'source_ref' in result:
                            action_ref[0] = result.get('action_execution_ref'); return result['source_ref']
                        return result
                    if route['capability'] not in EXECUTABLE:
                        result = {'status': 'unavailable', 'source_ref': None, 'route': 'unresolved', 'cache_hit': False,
                                  'fetch_executed': False, 'reasons': ['BATCH_EXTERNAL_CAPABILITY_REQUIRED'], 'attempt_refs': []}
                    else:
                        result = cache.get_or_fetch(key, acquire, deadline=deadline, max_age_seconds=item['cache_max_age_seconds'],
                            force_refresh=retry > 0).to_dict()
                    # Long-retained snapshots cannot depend on disposable cache telemetry.
                    archived_cache_refs = [save(directory, read(ref)) for ref in result['attempt_refs']]
                    reasons.extend(result['reasons']); uncertain = bool(UNKNOWN & set(result['reasons']))
                    row = {'schema_version': 1, 'kind': 'acquisition_attempt', 'execution_id': execution_id,
                        'requirement_id': item['id'], 'ordinal': len(attempts) + 1, 'capability': route['capability'],
                        'intent_ref': attempt_intent_ref,
                        'fetch_key_sha256': key.sha256, 'status': 'unknown' if uncertain else result['status'],
                        'route': result['route'], 'source_ref': result['source_ref'], 'fetch_executed': result['fetch_executed'],
                        'cache_hit': result['cache_hit'], 'reasons': result['reasons'], 'cache_attempt_refs': archived_cache_refs,
                        'started_at': before, 'finished_at': stamp(), 'action_execution_ref': action_ref[0]}
                    attempts.append(save(directory, row)); hits += int(result['cache_hit'])
                    if result['status'] == 'usable': selected = result['source_ref']; selected_capability = route['capability']; break
                    if uncertain or not (TRANSIENT & set(result['reasons'])): break
                if selected or uncertain: break
            result = {'schema_version': 1, 'kind': 'acquisition_requirement_result', 'execution_id': execution_id,
                'requirement_id': item['id'], 'subject': item['subject'],
                'status': 'available' if selected else 'unknown' if uncertain else 'unavailable',
                'selected_source_ref': selected, 'attempt_refs': attempts, 'route': selected_capability,
                'cache_hit': bool(hits), 'reasons': list(dict.fromkeys(reasons)),
                'elapsed_seconds': time.monotonic() - item_start, 'counts': {'cache_hits': hits, 'fallbacks': fallbacks, 'retries': retries}}
            return result, save(directory, result)

        with ThreadPoolExecutor(max_workers=config['budget']['max_workers']) as pool:
            results = list(pool.map(requirement, config['requirements']))
        rows = [row for row, _ in results]; available = sum(row['status'] == 'available' for row in rows)
        unknown = sum(row['status'] == 'unknown' for row in rows)
        manifest = {'schema_version': 1, 'kind': 'acquisition_batch', 'version': VERSION, 'execution_id': execution_id,
            'batch_id': config['batch_id'], 'query': config['query'], 'subjects': sorted({i['subject'] for i in config['requirements']}),
            'config_ref': config_ref, 'config_sha256': fingerprint, 'capability_catalog_ref': catalog_ref,
            'capability_catalog_sha256': digest(catalog), 'script_versions': [{'id': 'shared.research_sources.batch', 'sha256': script_sha}],
            'action_release_ref': release['release_ref'] if release else None,
            'status': 'unknown' if unknown else 'completed' if available == len(rows) else 'partial' if available else 'failed',
            'started_at': started, 'finished_at': stamp(), 'elapsed_seconds': time.monotonic() - began,
            'requirement_result_refs': [ref for _, ref in results],
            'source_refs': list({row['selected_source_ref']['sha256']: row['selected_source_ref'] for row in rows if row['selected_source_ref']}.values()),
            'observation_refs': [], 'counts': {'requirements': len(rows), 'fulfilled': available, 'unavailable': len(rows) - available - unknown,
                'unknown': unknown, 'provider_calls': dispatched[0], **{key: sum(row['counts'][key] for row in rows) for key in ('cache_hits', 'fallbacks', 'retries')}},
            'counting_unit': 'adapter_dispatch', 'http_requests': None,
            'retention': {'snapshots': 'retain_until_explicit_gc', 'cache_is_disposable_index': True},
            'scope': 'acquisition_only_not_semantic_admission',
            'limitations': ['Current acquisition timestamps remain unchanged; consumers must screen pinned versions against their cutoff.',
                'Fallback routes do not establish semantic equivalence. No labels, model, quality, truth or investment alpha is inferred.']}
        ref = save(directory, manifest); atomic(final_path, ref)
        observed = {'status': 'not_requested'}
        if observer:
            try: observer(ref); observed = {'status': 'recorded'}
            except Exception: observed = {'status': 'unavailable', 'code': 'BATCH_OBSERVER_UNAVAILABLE'}
        return {**manifest, 'report_ref': ref, 'idempotent_replay': False, 'reconciled': False, 'observability': observed}
    finally: os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--config'); parser.add_argument('--execution-id')
    parser.add_argument('--worker', action='store_true'); args = parser.parse_args(); os.umask(0o077)
    try:
        if args.worker:
            request = json.loads(sys.stdin.buffer.read(16385)); require(len(encoded(request)) <= 16384, 'BATCH_WORKER_INPUT_LIMIT')
            route = request['route']; require(route['capability'] in {'openalex.discover', 'arxiv.discover'}, 'BATCH_WORKER_CAPABILITY_INVALID')
            result = {'status': 'returned', 'result': _discovery(route, private_path(request['directory'], create=True))}
        else:
            path = Path(args.config).resolve(); require(path.is_relative_to(ROOT), 'BATCH_CONFIG_OUTSIDE_WORKSPACE')
            result = run_batch(json.loads(path.read_bytes()), execution_id=args.execution_id)
        print(json.dumps(result, allow_nan=False))
    except Exception as error:
        print(json.dumps({'status': 'failed', 'code': code(error)})); raise SystemExit(1)


if __name__ == '__main__': main()
