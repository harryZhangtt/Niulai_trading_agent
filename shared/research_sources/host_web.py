"""Cooperative hosted-native web begin/capture portal, with immutable receipts.

Python never invokes web__run or substitutes HTTP. A hosted functions.exec cell
must hold the raw tool result, capture it, and emit only the screened packet.
This is application-level cooperation, not an OS sandbox or signed tool log.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import uuid
from urllib.parse import urlsplit

from .artifacts import ROOT, SOURCE_STATE, SourceError, digest, encoded, private_path, read, require, save
from .cache import FetchKey, validate_source
from .store import Store, instant
from shared.job_runtime.service import atomic

VERSION = 'host-web-1.1.0'
CODE_FILES = ('shared/research_sources/host_web.py', 'shared/research_sources/artifacts.py',
              'shared/research_sources/cache.py', 'shared/research_sources/store.py', 'shared/job_runtime/service.py')
MAX_RAW = 65536
MAX_SEARCH_TEXT = 48000
MAX_OPERATIONS = 32
DEFAULT_CACHE = SOURCE_STATE / 'cache/host-web'
HASH = re.compile('[a-f0-9]{64}')
NAME = re.compile('[A-Za-z0-9][A-Za-z0-9_-]{0,63}')
FAILURES = {'NATIVE_TRANSPORT_FAILED', 'SOURCE_HTTP_401', 'SOURCE_HTTP_403', 'SOURCE_HTTP_404',
            'SOURCE_HTTP_429', 'SOURCE_HTTP_503', 'HOST_WEB_BODY_UNPARSEABLE', 'HOST_WEB_RESULT_UNKNOWN', 'HOST_WEB_FUTURE_EXPOSURE', 'HOST_WEB_DEADLINE', 'HOST_WEB_SOURCE_CHANGED'}


def stamp(): return datetime.now(timezone.utc).isoformat()


def _observed_code():
    files = {}
    for name in CODE_FILES:
        path = ROOT / name
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(ROOT), 'HOST_WEB_SOURCE_CHANGED')
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'version': VERSION, 'files': files}


def freeze_config(config):
    """Freeze the explicit public direct dependencies before sealing/dispatch."""
    return _config({**config, 'code_pins': _observed_code()})


def _code_provenance(config, *, verify=False):
    try: observed = _observed_code()
    except (SourceError, OSError):
        require(not verify, 'HOST_WEB_SOURCE_CHANGED')
        return {'version': VERSION, 'implementation_sha256': None, 'dependency_sha256': None, 'pin_status': 'changed'}
    pins = config.get('code_pins')
    status = 'unverified' if pins is None else 'verified' if pins == observed else 'changed'
    require(not verify or status != 'changed', 'HOST_WEB_SOURCE_CHANGED')
    return {'version': VERSION, 'implementation_sha256': observed['files'][CODE_FILES[0]],
            'dependency_sha256': digest(observed['files']), 'pin_status': status}


def _url(value):
    require(isinstance(value, str) and len(value) <= 4096, 'HOST_WEB_URL_INVALID')
    parsed = urlsplit(value); host = parsed.hostname or ''
    require(parsed.scheme == 'https' and bool(host) and not parsed.username and not parsed.password and not parsed.fragment
            and parsed.port in (None, 443) and host != 'localhost' and not host.endswith(('.local', '.internal')), 'HOST_WEB_URL_INVALID')
    try: require(ipaddress.ip_address(host).is_global, 'HOST_WEB_URL_INVALID')
    except ValueError: pass
    FetchKey('native_open_primary_capture', 'read', {'url': value})
    return value


def _args(arguments):
    require(isinstance(arguments, dict) and set(arguments) <= {'search_query', 'open', 'find', 'response_length'}
            and sum(key in arguments for key in ('search_query', 'open', 'find')) == 1, 'HOST_WEB_ARGUMENTS_INVALID')
    key = next(key for key in ('search_query', 'open', 'find') if key in arguments); operation = 'search' if key == 'search_query' else 'open'
    items = arguments[key]
    require(isinstance(items, list) and 0 < len(items) <= (4 if operation == 'search' else 12), 'HOST_WEB_ITEMS_INVALID')
    if operation == 'search' and len(items) == 4:
        require(arguments.get('response_length') in {'medium', 'long'}, 'HOST_WEB_RESPONSE_LENGTH')
    for item in items:
        require(isinstance(item, dict), 'HOST_WEB_ITEM_INVALID')
        if operation == 'search':
            require(set(item) <= {'q', 'domains', 'recency'} and isinstance(item.get('q'), str)
                    and 0 < len(item['q']) <= 1000, 'HOST_WEB_QUERY_INVALID')
            if 'domains' in item: require(isinstance(item['domains'], list) and len(item['domains']) <= 8
                and all(isinstance(domain, str) and re.fullmatch('[A-Za-z0-9.-]{1,253}', domain) for domain in item['domains']), 'HOST_WEB_DOMAINS_INVALID')
            if 'recency' in item: require(type(item['recency']) is int and 0 <= item['recency'] <= 3650, 'HOST_WEB_RECENCY_INVALID')
        elif key == 'find':
            require(set(item) == {'ref_id', 'pattern'} and isinstance(item['pattern'], str)
                    and 0 < len(item['pattern']) <= 400, 'HOST_WEB_FIND_INVALID'); _url(item['ref_id'])
        else:
            require(set(item) <= {'ref_id', 'lineno'} and 'ref_id' in item, 'HOST_WEB_OPEN_INVALID'); _url(item['ref_id'])
            if 'lineno' in item: require(type(item['lineno']) is int and 0 <= item['lineno'] <= 1000000, 'HOST_WEB_LINE_INVALID')
    require(arguments.get('response_length', 'long') in {'short', 'medium', 'long'}, 'HOST_WEB_RESPONSE_LENGTH')
    require(len(encoded(arguments)) <= 16384, 'HOST_WEB_ARGUMENTS_TOO_LARGE')
    return operation, key, items


def _config(config):
    fields = {'schema_version', 'execution_id', 'arm', 'question', 'baseline_ref', 'cutoff', 'model_sha256',
        'backend', 'cohort', 'cache_enabled', 'cache_max_age_seconds', 'max_fallbacks', 'budget'}
    require(isinstance(config, dict) and fields <= set(config) <= fields | {'catalog_ref', 'requirement_ids', 'code_pins'}, 'HOST_WEB_CONFIG_INVALID')
    if 'code_pins' in config:
        pins = config['code_pins']
        require(isinstance(pins, dict) and set(pins) == {'version', 'files'} and isinstance(pins['version'], str)
                and isinstance(pins['files'], dict) and set(pins['files']) == set(CODE_FILES)
                and all(isinstance(value, str) and HASH.fullmatch(value) for value in pins['files'].values()), 'HOST_WEB_CODE_PINS_INVALID')
    require(config['schema_version'] == 1 and str(uuid.UUID(config['execution_id'])) == config['execution_id'], 'HOST_WEB_EXECUTION_INVALID')
    require(config['arm'] in {'A', 'B'} and config['cohort'] in {'cold', 'warm_cache', 'fault'} and
        isinstance(config['question'], str) and 0 < len(config['question']) <= 1800 and
        HASH.fullmatch(config['model_sha256']) and config['backend'] == 'native_tools.web__run', 'HOST_WEB_CONTROLS_INVALID')
    require(type(config['cache_enabled']) is bool and type(config['cache_max_age_seconds']) in (int, float)
        and 0 <= config['cache_max_age_seconds'] <= 604800 and type(config['max_fallbacks']) is int
        and 0 <= config['max_fallbacks'] <= 8, 'HOST_WEB_POLICY_INVALID')
    budget = config['budget']; require(isinstance(budget, dict) and set(budget) == {'search_items', 'open_items', 'provider_items', 'wall_seconds'}, 'HOST_WEB_BUDGET_INVALID')
    require(all(type(budget[key]) is int and 0 <= budget[key] <= 64 for key in ['search_items', 'open_items', 'provider_items'])
        and type(budget['wall_seconds']) in (int, float) and 1 <= budget['wall_seconds'] <= 3600, 'HOST_WEB_BUDGET_INVALID')
    if config.get('requirement_ids') is not None:
        require(isinstance(config['requirement_ids'], list) and 0 < len(config['requirement_ids']) <= 8 and
            all(isinstance(value, str) and NAME.fullmatch(value) for value in config['requirement_ids']), 'HOST_WEB_REQUIREMENT_IDS')
    read(config['baseline_ref']); instant(config['cutoff'])
    if config.get('catalog_ref'): read(config['catalog_ref'])
    return json.loads(encoded(config))


def _text(raw):
    if isinstance(raw, str): return raw
    if isinstance(raw, dict): return '\n'.join(_text(value) for key, value in raw.items() if key in {'content', 'text', 'result', 'data', 'message'})
    if isinstance(raw, list): return '\n'.join(_text(value) for value in raw[:64])
    return ''


def _body(text):
    lines = re.findall(r'(?m)^L\d+(?:@P[\d-]+)?: ?(.*)$', text)
    return '\n'.join(lines) if lines else None


def _documents(raw, items, supplied):
    text = _text(raw); normalized = _body(text) or text
    require(len(text) >= 80, 'HOST_WEB_BODY_UNPARSEABLE')
    if supplied is None:
        require(len(items) == 1 and _body(text) is not None, 'HOST_WEB_BODY_UNPARSEABLE')
        supplied = [{'url': items[0]['ref_id'], 'text': _body(text)}]
    require(isinstance(supplied, list) and len(supplied) == len(items), 'HOST_WEB_BODY_UNPARSEABLE')
    for item, document in zip(items, supplied):
        require(isinstance(document, dict) and set(document) <= {'url', 'text', 'title', 'published_at', 'modified_at'}
            and document.get('url') == item['ref_id'] and document['url'] in text
            and isinstance(document.get('text'), str) and 80 <= len(document['text']) <= 48000
            and (document['text'] in text or document['text'] in normalized), 'HOST_WEB_BODY_UNPARSEABLE')
    return supplied


class HostWeb:
    def __init__(self, directory, *, config=None, cache_directory=None, now=None):
        self.directory = private_path(directory, create=True); self.now = now or stamp
        self.cache_directory = private_path(cache_directory or DEFAULT_CACHE, create=True)
        self.head = self.directory / 'state.json'
        if config is not None:
            config = _config(config)
            with self._lock():
                if self.head.exists(): require(read(self._head())['config_ref']['sha256'] == digest(config), 'HOST_WEB_CONFIG_CONFLICT')
                else:
                    began = self.now(); config_ref = save(self.directory, config)
                    self._write({'config_ref': config_ref, 'started_at': began, 'operations': {}, 'source_refs': [],
                        'usage': {'search_items': 0, 'open_items': 0, 'provider_items': 0, 'cache_items': 0},
                        'search_receipt_refs': [], 'open_receipt_refs': [], 'cache_attempt_refs': [], 'exposure_refs': [],
                        'transport_circuit': False, 'unknown_fence': False, 'fallbacks': 0, 'final_ref': None, 'cache_directory': str(self.cache_directory)})
        self.state = read(self._head()); self.config = read(self.state['config_ref'])
        if self.state.get('cache_directory'):
            require(cache_directory is None or str(self.cache_directory) == self.state['cache_directory'], 'HOST_WEB_CACHE_PATH_CONFLICT')
            self.cache_directory = private_path(self.state['cache_directory'], create=True)

    @contextmanager
    def _lock(self):
        fd = os.open(self.directory / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise SourceError('HOST_WEB_BUSY') from None
            yield
        finally: os.close(fd)

    def _head(self):
        require(self.head.is_file() and not self.head.is_symlink() and self.head.stat().st_size <= 8192, 'HOST_WEB_STATE_INVALID')
        return json.loads(self.head.read_bytes())

    def _write(self, state): atomic(self.head, save(self.directory, state))

    def _state(self):
        state = read(self._head()); require(not state['final_ref'], 'HOST_WEB_RUN_FINISHED')
        return state

    def _time(self, state):
        at = instant(self.now())
        require(at <= instant(self.config['cutoff']) and (at - instant(state['started_at'])).total_seconds()
                <= self.config['budget']['wall_seconds'], 'HOST_WEB_DEADLINE')
        return at.isoformat()

    def _key(self, url, view):
        return FetchKey('native_open_primary_capture', 'read', {'url': url},
            access_scope='public:host-web:' + digest([VERSION, self.config['backend'], view]))

    def _bounds(self, source):
        values = [source['retrieved_at'], source['available_at']]
        values += [source[name] for name in ['published_at', 'modified_at', 'updated_at', 'version_available_at'] if source.get(name)]
        return [instant(value + 'T00:00:00Z' if len(value) == 10 else value) for value in values]

    def _cached(self, url, view, state):
        store = Store(self.cache_directory); key = self._key(url, view); row = store.cache_read(key.sha256)
        source = None; reason = 'CACHE_MISS'
        if row and row['state'] == 'active':
            try:
                source = validate_source(key, row['source_ref'])
                age = (instant(self.now()) - instant(row['checked_at'])).total_seconds()
                bounds = self._bounds(source)
                require(max(bounds) <= instant(self.config['cutoff']), 'HOST_WEB_CACHE_AFTER_CUTOFF')
                require(0 <= age <= self.config['cache_max_age_seconds'], 'CACHE_EXPIRED')
            except (SourceError, OSError, ValueError): source = None; reason = 'CACHE_NOT_ELIGIBLE'
        receipt = {'fetch_key': key.to_dict(), 'status': 'usable' if source else 'miss', 'route': 'cache_hit' if source else 'unresolved',
            'source_ref': row['source_ref'] if source else None, 'cache_hit': bool(source), 'fetch_executed': False,
            'occurred_at': self.now(), 'reasons': [] if source else [reason]}
        state['cache_attempt_refs'].append(save(self.directory, receipt)); state['usage']['cache_items'] += 1
        return row['source_ref'] if source else None

    def _expose(self, state, source_refs, packet, operation_id, requirement_ids):
        _code_provenance(self.config, verify=True)
        checked = self._time(state)
        for ref in source_refs:
            source = read(ref)
            bounds = self._bounds(source)
            require(max(bounds) <= instant(self.config['cutoff']) and instant(source['retrieved_at']) <= instant(checked), 'HOST_WEB_FUTURE_EXPOSURE')
        exposed = self._time(state)
        guard = {'kind': 'acquisition_operation_exposure', 'operation_id': operation_id, 'requirement_ids': requirement_ids, 'execution_id': self.config['execution_id'], 'cutoff': self.config['cutoff'],
            'exposed_source_refs': source_refs, 'screened_at': checked, 'exposed_at': exposed,
            'packet_sha256': digest(packet), 'mode': 'per_operation_host_screened'}
        state['exposure_refs'].append(save(self.directory, guard))
        known = {ref['sha256']: ref for ref in [*state['source_refs'], *source_refs]}; state['source_refs'] = list(known.values())
        return packet

    def prepare(self, operation_id, arguments, *, fallback_of=None, requirement_ids=()):
        require(isinstance(operation_id, str) and NAME.fullmatch(operation_id), 'HOST_WEB_OPERATION_ID')
        operation, key, items = _args(arguments)
        require(isinstance(requirement_ids, (list, tuple)) and len(requirement_ids) <= 8 and all(isinstance(value, str) and NAME.fullmatch(value) for value in requirement_ids), 'HOST_WEB_REQUIREMENT_IDS')
        if self.config.get('requirement_ids'): require(set(requirement_ids) <= set(self.config['requirement_ids']) and bool(requirement_ids), 'HOST_WEB_REQUIREMENT_IDS')
        requirement_ids = list(requirement_ids)
        with self._lock():
            state = self._state(); self._time(state); code = _code_provenance(self.config, verify=True)
            native_verb = 'search' if key == 'search_query' else key
            if operation_id in state['operations']:
                prior = read(state['operations'][operation_id]); require(prior['arguments'] == arguments and prior['requirement_ids'] == requirement_ids, 'HOST_WEB_OPERATION_CONFLICT')
                return {'status': 'pending' if prior['status'] == 'pending' else 'already_captured', 'intent_ref': state['operations'][operation_id], 'dispatch': False}
            require(len(state['operations']) < MAX_OPERATIONS, 'HOST_WEB_OPERATION_LIMIT')
            require(not any(read(ref)['status'] == 'pending' for ref in state['operations'].values()), 'HOST_WEB_PENDING_OUTCOME')
            if fallback_of:
                require(fallback_of in state['operations'] and state['fallbacks'] < self.config['max_fallbacks'], 'HOST_WEB_FALLBACK_INVALID')
                previous = read(state['operations'][fallback_of]); require(previous['status'] == 'failed' and previous['arguments'] != arguments, 'HOST_WEB_FALLBACK_INVALID')
                state['fallbacks'] += 1
            for ref in state['operations'].values():
                prior = read(ref)
                if prior['arguments'] == arguments and prior['status'] in {'failed', 'unknown'}:
                    return {'status': 'not_retry', 'code': prior.get('code', 'HOST_WEB_PREVIOUS_FAILURE'), 'dispatch': False}
            count = len(items); budget = self.config['budget']
            require(state['usage'][operation + '_items'] + count <= budget[operation + '_items'], 'HOST_WEB_ITEM_BUDGET')
            state['usage'][operation + '_items'] += count
            cached = []
            cache_start = len(state['cache_attempt_refs'])
            if native_verb == 'open' and self.config['cache_enabled'] and all('lineno' not in item for item in items):
                cached = []
                for item in items:
                    view = {'lineno': item.get('lineno'), 'response_length': arguments.get('response_length', 'long')}
                    try: cached.append(self._cached(item['ref_id'], view, state))
                    except (SourceError, OSError, ValueError): cached.append(None)
            if cached and all(cached):
                packet = {'documents': [{'source_ref': ref, 'url': read(ref)['source_url'], 'text': read(read(ref)['text'], json_value=False).decode()} for ref in cached]}
                result = {'kind': 'host_web_intent', 'status': 'cached', 'arguments': arguments, 'operation': operation, 'native_verb': native_verb, 'code_provenance': code,
                    'operation_id': operation_id, 'requirement_ids': requirement_ids, 'started_at': self.now(), 'source_refs': cached}
                state['operations'][operation_id] = save(self.directory, result)
                packet = self._expose(state, cached, packet, operation_id, requirement_ids)
                state['open_receipt_refs'].append(save(self.directory, {'kind': 'acquisition_operation_receipt',
                    'execution_id': self.config['execution_id'], 'operation_id': operation_id, 'requirement_ids': requirement_ids,
                    'operation': 'open', 'native_verb': native_verb, 'code_provenance': code, 'backend': self.config['backend'], 'status': 'cache_hit', 'fetch_executed': False, 'provider_items': 0,
                    'request_ref': save(self.directory, {'items': items, 'arguments': arguments}), 'response_ref': save(self.directory, packet),
                    'source_sha256s': [ref['sha256'] for ref in cached], 'started_at': result['started_at'], 'finished_at': result['started_at']}))
                self._write(state)
                return {'status': 'cache_hit', 'dispatch': False, 'packet': packet, 'intent_ref': state['operations'][operation_id]}
            if cached and any(cached):
                # A tool call has one exposure event. Mixed batches are fetched
                # together; eligible but unused cached bodies are never exposed.
                for index in range(cache_start, len(state['cache_attempt_refs'])):
                    attempt = read(state['cache_attempt_refs'][index])
                    if attempt['cache_hit']:
                        state['cache_attempt_refs'][index] = save(self.directory, {**attempt,
                            'source_ref': None, 'cache_hit': False, 'lookup_hit': True,
                            'route': 'unresolved', 'reasons': ['CACHE_PARTIAL_BATCH_NOT_USED']})
            if state['transport_circuit'] or state.get('unknown_fence'):
                self._write(state)
                return {'status': 'not_retry', 'code': 'NATIVE_TRANSPORT_CIRCUIT_OPEN' if state['transport_circuit'] else 'HOST_WEB_UNKNOWN_OUTCOME', 'dispatch': False}
            require(state['usage']['provider_items'] + count <= budget['provider_items'], 'HOST_WEB_ITEM_BUDGET')
            state['usage']['provider_items'] += count
            intent = {'kind': 'host_web_intent', 'execution_id': self.config['execution_id'], 'operation_id': operation_id,
                'arguments': arguments, 'operation': operation, 'native_verb': native_verb, 'code_provenance': code, 'requirement_ids': requirement_ids, 'started_at': self.now(), 'status': 'pending', 'fallback_of': fallback_of,
                'request_ref': save(self.directory, {'items': items, 'arguments': arguments})}
            ref = save(self.directory, intent); state['operations'][operation_id] = ref; self._write(state)
            return {'status': 'dispatch', 'dispatch': True, 'intent_ref': ref, 'arguments': arguments,
                    'remaining_provider_items': budget['provider_items'] - state['usage']['provider_items']}

    def capture(self, operation_id, capture, *, observer=None):
        require(isinstance(capture, dict) and set(capture) <= {'actual_arguments', 'raw_result', 'status', 'code', 'documents'}, 'HOST_WEB_CAPTURE_INVALID')
        with self._lock():
            state = self._state(); at = self.now(); late = False
            try: self._time(state)
            except SourceError: late = True
            require(operation_id in state['operations'], 'HOST_WEB_INTENT_UNKNOWN')
            intent = read(state['operations'][operation_id]); require(intent['status'] == 'pending', 'HOST_WEB_CAPTURE_REPLAY')
            require(capture.get('actual_arguments') == intent['arguments'] and 'raw_result' in capture, 'HOST_WEB_TOOL_ARGUMENT_MISMATCH')
            require(len(encoded(capture['raw_result'])) <= MAX_RAW, 'HOST_WEB_RESULT_TOO_LARGE')
            raw = capture['raw_result']; raw_ref = save(self.directory, raw)
            status = capture.get('status'); require(status in {'returned', 'failed', 'unknown'}, 'HOST_WEB_CAPTURE_STATUS')
            failure = capture.get('code'); sources = []; packet = {}; operation = intent['operation']
            native_verb = intent.get('native_verb', operation); code = _code_provenance(self.config)
            if code['pin_status'] == 'changed': status = 'failed'; failure = 'HOST_WEB_SOURCE_CHANGED'
            if late: status = 'failed'; failure = 'HOST_WEB_DEADLINE'
            if status == 'returned':
                try:
                    if native_verb == 'find':
                        text = _text(raw); urls = list(dict.fromkeys(item['ref_id'] for item in intent['arguments']['find']))
                        require(bool(text) and all(url in text for url in urls), 'HOST_WEB_BODY_UNPARSEABLE')
                        packet = {'urls': urls, 'find_text': text[:MAX_SEARCH_TEXT], 'find_text_truncated': len(text) > MAX_SEARCH_TEXT,
                            'find_text_total_chars': len(text), 'line_hints': sorted({int(n) for n in re.findall(r'\bL(\d+)', text)})[:64],
                            'scope': 'current_locator_metadata_only', 'native_reference_warning': 'Native turn IDs are session-only; open the portable full URL at a selected line to obtain document evidence.'}
                        sources = [save(self.directory, {'schema_version': 1, 'provider': 'native_web_find', 'access_level': 'metadata',
                            'source_url': 'native-find://' + digest(intent['arguments']), 'upstream_id': digest(intent['arguments']),
                            'source_version': raw_ref['sha256'], 'raw': raw_ref, 'text': save(self.directory, packet['find_text'].encode(), suffix='txt'),
                            'retrieved_at': at, 'available_at': at, 'availability_basis': 'first_observed_native_locator_metadata',
                            'metadata': {'current_only': True, 'semantic_admission': False, 'historical_backdating': False}, 'candidates': urls})]
                    elif operation == 'search':
                        candidates = []
                        for candidate in re.findall(r'https://[^\s<>"\\()]+', _text(raw)):
                            candidate = candidate.rstrip('.,;]}')
                            try: _url(candidate)
                            except (SourceError, ValueError): continue
                            if candidate not in candidates: candidates.append(candidate)
                        require(bool(candidates), 'HOST_WEB_BODY_UNPARSEABLE')
                        # Retain actual discovery clues, without inventing a parsed
                        # title/snippet schema or treating metadata as opened evidence.
                        text = _text(raw); issued = text[:MAX_SEARCH_TEXT]
                        packet = {'urls': candidates[:64], 'search_text': issued,
                            'search_text_truncated': len(issued) < len(text), 'search_text_total_chars': len(text),
                            'scope': 'current_search_metadata_only',
                            'native_reference_warning': 'Native turn IDs are session-only; open portable full URLs, never cached/session references.'}
                        sources = [save(self.directory, {'schema_version': 1, 'provider': 'native_web_search',
                            'source_url': 'native-search://' + digest(intent['arguments']), 'upstream_id': digest(intent['arguments']),
                            'source_version': raw_ref['sha256'], 'access_level': 'metadata', 'raw': raw_ref,
                            'text': save(self.directory, issued.encode(), suffix='txt'), 'retrieved_at': at, 'available_at': at,
                            'availability_basis': 'first_observed_native_search_metadata', 'candidates': candidates[:64],
                            'metadata': {'current_only': True, 'semantic_admission': False, 'historical_backdating': False,
                                'native_ids_session_only': True, 'text_truncated': len(issued) < len(text), 'text_total_chars': len(text)}})]
                    else:
                        documents = _documents(raw, intent['arguments']['open'], capture.get('documents'))
                        for item, doc in zip(intent['arguments']['open'], documents):
                            receipt = {'schema_version': 1, 'provider': 'native_open_primary_capture', 'source_url': doc['url'],
                                'upstream_id': doc['url'], 'source_version': raw_ref['sha256'], 'access_level': 'document',
                                'raw': raw_ref, 'text': save(self.directory, doc['text'].encode(), suffix='txt'),
                                'retrieved_at': at, 'available_at': at, 'published_at': doc.get('published_at'), 'modified_at': doc.get('modified_at'),
                                'availability_basis': 'first_observed_native_capture', 'title': doc.get('title'),
                                'metadata': {'request_view': {'lineno': item.get('lineno'), 'response_length': intent['arguments'].get('response_length', 'long')}},
                                'capture_method': 'native_open_passage_not_original_publisher_bytes', 'limitations': ['No original historical byte attestation or semantic admission.']}
                            sources.append(save(self.directory, receipt))
                        packet = {'documents': [{'source_ref': ref, 'url': read(ref)['source_url'], 'text': read(read(ref)['text'], json_value=False).decode()} for ref in sources]}
                    packet = self._expose(state, sources, packet, operation_id, intent['requirement_ids'])
                except (SourceError, ValueError, TypeError, KeyError) as error:
                    failure = str(error) if isinstance(error, SourceError) and str(error) in {'HOST_WEB_FUTURE_EXPOSURE', 'HOST_WEB_DEADLINE', 'HOST_WEB_SOURCE_CHANGED'} else 'HOST_WEB_BODY_UNPARSEABLE'
                    status = 'failed'; sources = []; packet = {}
            if status == 'unknown': state['unknown_fence'] = True
            if status != 'returned':
                require(failure in FAILURES, 'HOST_WEB_FAILURE_CODE_INVALID')
                if failure == 'NATIVE_TRANSPORT_FAILED': state['transport_circuit'] = True
            receipt = {'kind': 'acquisition_operation_receipt', 'execution_id': self.config['execution_id'], 'operation': operation,
                'backend': self.config['backend'], 'operation_id': operation_id, 'requirement_ids': intent['requirement_ids'],
                'native_verb': native_verb, 'code_provenance': _code_provenance(self.config),
                'fetch_executed': True, 'provider_items': len(intent['arguments']['find' if native_verb == 'find' else 'search_query' if operation == 'search' else 'open']),
                'request_ref': intent['request_ref'], 'response_ref': raw_ref,
                'started_at': intent['started_at'], 'finished_at': at, 'source_sha256s': [ref['sha256'] for ref in sources],
                'status': 'success' if status == 'returned' else status, 'code': failure, 'intent_ref': state['operations'][operation_id]}
            operation_ref = save(self.directory, receipt); state[operation + '_receipt_refs'].append(operation_ref)
            if native_verb == 'open' and status == 'returned' and self.config['cache_enabled']:
                for source_ref in sources:
                    source = read(source_ref); key = self._key(source['source_url'], source['metadata']['request_view']); warning = []
                    try:
                        store = Store(self.cache_directory); previous = store.cache_read(key.sha256); validate_source(key, source_ref)
                        store.cache_publish('host:' + digest([self.config['execution_id'], operation_id, key.sha256]), key.to_dict(), source_ref, at, previous['generation'] if previous else 0)
                    except (SourceError, OSError, ValueError): warning = ['HOST_WEB_CACHE_PUBLICATION_UNAVAILABLE']
                    state['cache_attempt_refs'].append(save(self.directory, {'fetch_key': key.to_dict(), 'status': 'usable', 'route': 'fetch_uncached' if warning else 'fetch',
                        'source_ref': source_ref, 'cache_hit': False, 'fetch_executed': True, 'occurred_at': self.now(), 'reasons': warning}))
            completed = {**intent, 'status': 'captured' if status == 'returned' else status, 'code': failure, 'operation_ref': operation_ref}
            state['operations'][operation_id] = save(self.directory, completed); self._write(state)
        diagnostic = None
        if observer:
            try: observer(operation_ref)
            except Exception: diagnostic = 'HOST_WEB_OBSERVER_UNAVAILABLE'
        return {'status': status, 'code': failure, 'operation_ref': operation_ref, 'source_refs': sources, 'packet': packet, 'warning': diagnostic}

    def finish(self, unit_refs=()):
        with self._lock():
            state = read(self._head())
            if state['final_ref']: return {'run_ref': state['final_ref'], 'run': read(state['final_ref'])}
            require(not any(read(ref)['status'] == 'pending' for ref in state['operations'].values()), 'HOST_WEB_PENDING_OUTCOME')
            for ref in unit_refs: read(ref)
            events = [read(ref) for ref in state['exposure_refs']]
            guard = {'kind': 'acquisition_worker_exposure', 'execution_id': self.config['execution_id'], 'cutoff': self.config['cutoff'],
                'exposure_mode': 'per_operation_host_screened', 'event_refs': state['exposure_refs'], 'exposed_source_refs': state['source_refs']}
            run = {'kind': 'acquisition_eval_run', 'execution_id': self.config['execution_id'], 'arm': self.config['arm'],
                'question_sha256': digest(self.config['question']), 'baseline_sha256': self.config['baseline_ref']['sha256'],
                'model_sha256': self.config['model_sha256'], 'backend': self.config['backend'], 'cohort': self.config['cohort'],
                'config_sha256': state['config_ref']['sha256'], 'config_ref': state['config_ref'], 'cutoff': self.config['cutoff'],
                'code_provenance': _code_provenance(self.config),
                'started_at': state['started_at'], 'finished_at': self.now(), 'first_worker_at': events[0]['exposed_at'] if events else None,
                'search_receipt_refs': state['search_receipt_refs'], 'open_receipt_refs': state['open_receipt_refs'],
                'cache_attempt_refs': state['cache_attempt_refs'], 'exposure_ref': save(self.directory, guard),
                'exposure_mode': 'per_operation_host_screened', 'unit_refs': list(unit_refs), 'source_refs': state['source_refs'],
                'status': 'unknown' if any(read(ref)['status'] == 'unknown' for ref in state['operations'].values()) else 'partial' if any(read(ref)['status'] == 'failed' for ref in state['operations'].values()) else 'completed',
                'usage': {**state['usage'], 'tokens': None, 'cost': None}, 'scope': 'hosted_native_acquisition_not_semantic_admission'}
            ref = save(self.directory, run); state['final_ref'] = ref; self._write(state)
            return {'run_ref': ref, 'run': run}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('command', choices=['init', 'prepare', 'capture', 'show', 'finish'])
    parser.add_argument('--directory', required=True); parser.add_argument('--input-file'); parser.add_argument('--result-file'); parser.add_argument('--result-json')
    args = parser.parse_args(); os.umask(0o077)
    try:
        if args.input_file:
            path = private_path(args.input_file); require(path.stat().st_size <= 131072, 'HOST_WEB_INPUT_TOO_LARGE'); payload = json.loads(path.read_bytes())
        else:
            data = sys.stdin.buffer.read(131073); require(len(data) <= 131072, 'HOST_WEB_INPUT_TOO_LARGE')
            payload = json.loads(data or b'{}')
        portal = HostWeb(args.directory, config=payload['config'] if args.command == 'init' else None, cache_directory=payload.get('cache_directory'))
        if args.command == 'prepare': result = portal.prepare(payload['operation_id'], payload['arguments'], fallback_of=payload.get('fallback_of'), requirement_ids=payload.get('requirement_ids', []))
        elif args.command == 'capture':
            capture = payload['capture']
            if args.result_file:
                path = private_path(args.result_file); require(path.stat().st_size <= MAX_RAW, 'HOST_WEB_RESULT_TOO_LARGE'); capture['raw_result'] = json.loads(path.read_bytes())
            if args.result_json: capture['raw_result'] = json.loads(args.result_json)
            result = portal.capture(payload['operation_id'], capture)
        elif args.command == 'finish': result = portal.finish(payload.get('unit_refs', []))
        else: result = {'config': portal.config, 'state_ref': portal._head()}
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except Exception as error:
        code = str(error) if isinstance(error, SourceError) and re.fullmatch('[A-Z][A-Z_0-9]{0,99}', str(error)) else 'HOST_WEB_FAILED'
        print(json.dumps({'status': 'failed', 'code': code})); raise SystemExit(1)


if __name__ == '__main__': main()
