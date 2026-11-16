"""Explicit routing decisions. Native search remains a host tool, not an HTTP imitation."""
from copy import deepcopy
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit

from shared.research_sources.artifacts import require

DEFAULT_CONFIG = Path(__file__).with_name('candidate.json')
_QUERY_SECRET = re.compile(r'(?i)(?:bearer\s+|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret|authorization|cookie|jwt)')
_SHA256 = re.compile(r'[a-f0-9]{64}')


def discovery_key(query):
    require(isinstance(query, str), 'WEB_QUERY_INVALID')
    normalized = ' '.join(query.split())
    require(0 < len(normalized) <= 2000 and _QUERY_SECRET.search(normalized) is None, 'WEB_QUERY_INVALID')
    return hashlib.sha256(normalized.encode()).hexdigest()


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def origin(url):
    require(isinstance(url, str) and len(url) <= 4096 and not re.search(r'[\x00-\x20\\]', url), 'WEB_URL_INVALID')
    try:
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port
        require(parsed.scheme == 'https' and bool(host) and parsed.username is None and parsed.password is None
                and port in (None, 443), 'WEB_URL_INVALID')
        require(host.isascii() and host != 'localhost' and '.' in host, 'WEB_URL_INVALID')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError('literal-address')
        require(not parsed.fragment, 'WEB_URL_FRAGMENT_REJECTED')
        require(not re.search(r'(?i)(token|password|secret|authorization|signature|api.?key)=', parsed.query), 'WEB_URL_SECRET_REJECTED')
        return 'https://' + host.lower()
    except (ValueError, TypeError):
        require(False, 'WEB_URL_INVALID')


def validate_config(value):
    require(type(value) is dict and set(value) == {'schema_version', 'status', 'egolite', 'allowed_origins', 'limits'}
            and type(value['schema_version']) is int and value['schema_version'] == 1
            and value['status'] in ('candidate', 'accepted'), 'WEB_CONFIG_INVALID')
    browser = value['egolite']
    require(type(browser) is dict and set(browser) == {'enabled', 'executable', 'sha256', 'profile_id'}
            and type(browser['enabled']) is bool, 'WEB_CONFIG_INVALID')
    require(browser['profile_id'] is None or isinstance(browser['profile_id'], str) and
            re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', browser['profile_id']), 'WEB_PROFILE_INVALID')
    if browser['enabled']:
        require(isinstance(browser['executable'], str) and Path(browser['executable']).is_absolute()
                and isinstance(browser['sha256'], str) and re.fullmatch('[a-f0-9]{64}', browser['sha256']), 'WEB_EXECUTABLE_PIN_REQUIRED')
    else:
        require(browser['executable'] is None and browser['sha256'] is None, 'WEB_DISABLED_CONFIG_INVALID')
    origins = value['allowed_origins']
    require(type(origins) is list and 0 < len(origins) <= 64 and len(origins) == len(set(origins))
            and all(origin(item) == item and urlsplit(item).path == '' and not urlsplit(item).query for item in origins), 'WEB_ORIGINS_INVALID')
    limits = value['limits']
    bounds = {'timeout_seconds': (1, 90), 'max_output_bytes': (1024, 2097152),
              'max_snapshot_chars': (100, 240000), 'max_reads': (1, 20), 'deadline_seconds': (1, 1800)}
    require(type(limits) is dict and set(limits) == set(bounds), 'WEB_LIMITS_INVALID')
    require(all(type(limits[k]) is int and low <= limits[k] <= high for k, (low, high) in bounds.items()), 'WEB_LIMITS_INVALID')
    return deepcopy(value)


def load_config(path=DEFAULT_CONFIG):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 65536, 'WEB_CONFIG_FILE_INVALID')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'WEB_CONFIG_DUPLICATE_KEY')
            result[key] = value
        return result
    return validate_config(json.loads(path.read_bytes(), object_pairs_hook=pairs))


class Session:
    """One host-owned research session; callers cannot reset its limits in proposals."""
    def __init__(self, config, *, clock=time.monotonic, native_search_budget=None,
                 transient_retry_limit=2):
        self.config = validate_config(config)
        require(native_search_budget is None or type(native_search_budget) is int
                and 1 <= native_search_budget <= 64, 'WEB_SEARCH_BUDGET_INVALID')
        require(type(transient_retry_limit) is int and 0 <= transient_retry_limit <= 4,
                'WEB_SEARCH_RETRY_LIMIT_INVALID')
        self.clock = clock
        self.started = clock()
        self.reads = 0
        self.native_available = True
        self.native_search_budget = (self.config['limits']['max_reads']
                                     if native_search_budget is None else native_search_budget)
        self.transient_retry_limit = transient_retry_limit
        self.native_searches = 0
        self.native_quota_exhausted = False
        self.discoveries = {}
        self.events = []
        self._lock = threading.RLock()

    def record_native(self, outcome):
        with self._lock:
            return self._record_native(outcome)

    def _record_native(self, outcome):
        require(outcome in ('success', 'transport_error', 'access_blocked', 'insufficient_content'), 'WEB_OUTCOME_INVALID')
        if outcome == 'transport_error':
            self.native_available = False
        self.events.append({'kind': 'native_outcome', 'outcome': outcome})

    def record_discovery(self, query, outcome, *, result_sha256=None):
        with self._lock:
            key = discovery_key(query)
            require(outcome in ('success', 'quota_exhausted', 'transient_error',
                                'permanent_error', 'unknown_outcome'), 'WEB_DISCOVERY_OUTCOME_INVALID')
            state = self.discoveries.get(key)
            require(state is not None and state.get('status') == 'pending',
                    'WEB_DISCOVERY_NOT_PENDING')
            if outcome == 'success':
                require(isinstance(result_sha256, str) and _SHA256.fullmatch(result_sha256),
                        'WEB_DISCOVERY_RESULT_INVALID')
                state.update(status='success', result_sha256=result_sha256)
            else:
                require(result_sha256 is None, 'WEB_DISCOVERY_RESULT_INVALID')
                state['status'] = outcome
                if outcome == 'quota_exhausted':
                    self.native_quota_exhausted = True
                elif outcome == 'unknown_outcome':
                    state['fenced'] = True
            self.events.append({'kind': 'discovery_outcome', 'query_sha256': key,
                                'outcome': outcome, 'attempts': state['attempts']})
            return deepcopy(state)

    def _plan_discovery(self, query):
        if query is None:
            if self.native_quota_exhausted or not self.native_available:
                return {'route': 'work_browser_discovery',
                        'reason': ('native_quota_exhausted' if self.native_quota_exhausted
                                   else 'native_circuit_open'), 'requires_host_tool': True}
            if self.native_searches >= self.native_search_budget:
                return {'route': 'work_browser_discovery', 'reason': 'task_native_search_budget',
                        'requires_host_tool': True}
            self.native_searches += 1
            return {'route': 'native_search', 'reason': 'broad_discovery',
                    'attempt_ordinal': 1, 'requires_host_tool': True}
        key = discovery_key(query)
        state = self.discoveries.get(key)
        if state:
            status = state['status']
            if status == 'success':
                return {'route': 'cached_discovery', 'reason': 'exact_query_cache',
                        'query_sha256': key, 'result_sha256': state['result_sha256'],
                        'requires_host_tool': False}
            if status == 'pending':
                return {'route': 'wait', 'reason': 'duplicate_query_inflight',
                        'query_sha256': key, 'requires_host_tool': False}
            if status in ('permanent_error', 'unknown_outcome'):
                return {'route': 'blocked', 'reason': status, 'query_sha256': key,
                        'requires_host_tool': False}
        if self.native_quota_exhausted or not self.native_available:
            return {'route': 'work_browser_discovery',
                    'reason': ('native_quota_exhausted' if self.native_quota_exhausted
                               else 'native_circuit_open'), 'query_sha256': key,
                    'requires_host_tool': True}
        attempts = 0 if state is None else state['attempts']
        if state and state['status'] == 'quota_exhausted':
            return {'route': 'work_browser_discovery', 'reason': 'native_quota_exhausted',
                    'query_sha256': key, 'requires_host_tool': True}
        if state and state['status'] == 'transient_error' and attempts >= 1 + self.transient_retry_limit:
            return {'route': 'work_browser_discovery', 'reason': 'transient_retry_exhausted',
                    'query_sha256': key, 'requires_host_tool': True}
        if self.native_searches >= self.native_search_budget:
            return {'route': 'work_browser_discovery', 'reason': 'task_native_search_budget',
                    'query_sha256': key, 'requires_host_tool': True}
        attempts += 1
        self.native_searches += 1
        self.discoveries[key] = {'status': 'pending', 'attempts': attempts}
        decision = {'route': 'native_search', 'reason': ('broad_discovery' if attempts == 1
                    else 'bounded_transient_retry'), 'query_sha256': key,
                    'attempt_ordinal': attempts, 'requires_host_tool': True}
        if attempts > 1:
            decision['retry_after_seconds'] = min(30, 2 ** (attempts - 1))
        self.events.append({'kind': 'discovery_route', **decision})
        return decision

    def plan(self, *, operation, url=None, native_outcome=None, interactive=False,
             browser='egolite', authenticated=False, authorized_session=False, document_format='auto', query=None):
        with self._lock:
            return self._plan(operation=operation, url=url, native_outcome=native_outcome,
                interactive=interactive, browser=browser, authenticated=authenticated,
                authorized_session=authorized_session, document_format=document_format, query=query)

    def _plan(self, *, operation, url, native_outcome, interactive, browser,
              authenticated, authorized_session, document_format, query):
        require(operation in ('discover', 'read') and type(interactive) is bool and
                type(authenticated) is bool and type(authorized_session) is bool, 'WEB_REQUEST_INVALID')
        require(browser in ('egolite', 'chrome'), 'WEB_BROWSER_INVALID')
        require(document_format in ('auto', 'html', 'pdf'), 'WEB_FORMAT_INVALID')
        remaining = self.config['limits']['deadline_seconds'] - (self.clock() - self.started)
        require(math.isfinite(remaining) and remaining > 0, 'WEB_SESSION_DEADLINE')
        if native_outcome is not None:
            self.record_native(native_outcome)
        if operation == 'discover':
            return self._plan_discovery(query)
        require(origin(url) in self.config['allowed_origins'], 'WEB_ORIGIN_NOT_ALLOWED')
        require(not authenticated or authorized_session, 'WEB_AUTHORIZATION_REQUIRED')
        require(self.reads < self.config['limits']['max_reads'], 'WEB_READ_BUDGET')
        # PDF goes through the current source/PDF route, not an invented Ego extractor.
        path = urlsplit(url).path.lower()
        if document_format == 'pdf' or path.endswith('.pdf') or origin(url) == 'https://arxiv.org' and path.startswith('/pdf/'):
            route, reason = 'native_pdf_reader', 'preserve_pdf_route'
        elif not self.native_available:
            route, reason = browser, 'native_circuit_open'
        elif interactive or authenticated or native_outcome in ('access_blocked', 'insufficient_content'):
            route, reason = browser, 'rendering_or_session_required'
        else:
            route, reason = 'native_open', 'least_cost_source_open'
        if route == 'native_pdf_reader' and not self.native_available:
            route, reason = 'existing_pdf_adapter', 'native_circuit_open_pdf'
        if route == 'egolite' and not self.config['egolite']['enabled']:
            route, reason = 'blocked', 'egolite_not_configured'
        self.reads += 1
        decision = {'route': route, 'reason': reason, 'url': url,
                    'timeout_seconds': min(remaining, self.config['limits']['timeout_seconds']),
                    'read_ordinal': self.reads, 'requires_host_tool': route not in ('egolite', 'blocked')}
        self.events.append({'kind': 'route', **decision})
        return decision
