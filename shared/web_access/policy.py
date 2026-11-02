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
    def __init__(self, config, *, clock=time.monotonic):
        self.config = validate_config(config)
        self.clock = clock
        self.started = clock()
        self.reads = 0
        self.native_available = True
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

    def plan(self, *, operation, url=None, native_outcome=None, interactive=False,
             browser='egolite', authenticated=False, authorized_session=False, document_format='auto'):
        with self._lock:
            return self._plan(operation=operation, url=url, native_outcome=native_outcome,
                interactive=interactive, browser=browser, authenticated=authenticated,
                authorized_session=authorized_session, document_format=document_format)

    def _plan(self, *, operation, url, native_outcome, interactive, browser,
              authenticated, authorized_session, document_format):
        require(operation in ('discover', 'read') and type(interactive) is bool and
                type(authenticated) is bool and type(authorized_session) is bool, 'WEB_REQUEST_INVALID')
        require(browser in ('egolite', 'chrome'), 'WEB_BROWSER_INVALID')
        require(document_format in ('auto', 'html', 'pdf'), 'WEB_FORMAT_INVALID')
        remaining = self.config['limits']['deadline_seconds'] - (self.clock() - self.started)
        require(math.isfinite(remaining) and remaining > 0, 'WEB_SESSION_DEADLINE')
        if native_outcome is not None:
            self.record_native(native_outcome)
        if operation == 'discover':
            route = 'native_search' if self.native_available else 'work_browser_discovery'
            return {'route': route, 'reason': 'broad_discovery' if self.native_available else 'native_circuit_open',
                    'requires_host_tool': True}
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
