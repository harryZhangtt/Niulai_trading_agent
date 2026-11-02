"""One-host acquisition cache: exact request keys, byte checks and bounded singleflight.

This is not an evidence admission gate. ``eligible`` belongs to the requesting
decision and receives the original receipt (including its original timestamps).
``checked_at`` only controls retrieval reuse. It never changes observation time.
The callback owns its hard I/O timeout: arbitrary Python callbacks cannot be
preempted here. A late result is rejected rather than published as timely.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import fcntl
import json
import math
import os
import re
import time
from urllib.parse import parse_qs, urlsplit
import uuid

from .artifacts import SourceError, digest, encoded, private_path, read, require, save
from .store import Store, instant


_CODE = re.compile(r'[A-Z][A-Z_0-9]{0,99}')
_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,191}')
_SECRET = re.compile(r'(^|[_-])(password|secret|token|api[_-]?key|authorization|credential)([_-]|$)', re.I)
_DEPENDENCY_ERRORS = {'SOURCE_HTTP_401', 'SOURCE_HTTP_403'}
_COOLDOWN_ERRORS = {'SOURCE_HTTP_404', 'SOURCE_HTTP_429', 'SOURCE_NETWORK_FAILED', 'SOURCE_DOCUMENT_INVALID',
    'CACHE_FETCH_TIMEOUT', 'CACHE_FETCH_FAILED', 'CACHE_PROVIDER_MISMATCH', 'CACHE_ACCESS_LEVEL_INVALID',
    'CACHE_RAW_EMPTY', 'CACHE_TEXT_EMPTY', 'CACHE_QUERY_MISMATCH', 'CACHE_IDENTITY_MISMATCH',
    'CACHE_URL_MISMATCH', 'CACHE_VERSION_MISMATCH', 'CACHE_COVERAGE_EMPTY', 'CACHE_DEFINITION_MISMATCH',
    'ARTIFACT_HASH_MISMATCH'}


def _safe_parameters(value):
    if isinstance(value, dict):
        require(all(isinstance(k, str) and not _SECRET.search(k) for k in value), 'CACHE_SECRET_PARAMETER')
        for nested in value.values():
            _safe_parameters(nested)
    elif isinstance(value, list):
        for nested in value:
            _safe_parameters(nested)
    elif isinstance(value, str) and value.startswith(('https://', 'http://')):
        parsed = urlsplit(value)
        require(not parsed.username and not parsed.password and
                not any(_SECRET.search(k) for k in parse_qs(parsed.query)), 'CACHE_SECRET_PARAMETER')


def _code(exc):
    if isinstance(exc, TimeoutError):
        return 'CACHE_FETCH_TIMEOUT'
    if isinstance(exc, SourceError) and _CODE.fullmatch(str(exc)):
        return str(exc)
    return 'CACHE_FETCH_FAILED'


@dataclass(frozen=True)
class FetchKey:
    provider: str
    capability: str
    parameters: dict
    access_scope: str = 'public'
    native_version: str | None = None

    def __post_init__(self):
        for value in (self.provider, self.capability, self.access_scope):
            require(isinstance(value, str) and _NAME.fullmatch(value), 'CACHE_KEY_INVALID')
        require(self.native_version is None or isinstance(self.native_version, str)
                and _NAME.fullmatch(self.native_version), 'CACHE_VERSION_INVALID')
        require(isinstance(self.parameters, dict) and bool(self.parameters), 'CACHE_PARAMETERS_REQUIRED')
        _safe_parameters(self.parameters)
        try:
            canonical = json.loads(encoded(self.parameters))
            require(len(encoded(canonical)) <= 8192, 'CACHE_PARAMETERS_TOO_LARGE')
        except (TypeError, ValueError):
            raise SourceError('CACHE_PARAMETERS_INVALID') from None
        _safe_parameters(canonical)
        # Own a canonical copy: caller mutation cannot change an in-flight key.
        object.__setattr__(self, 'parameters', canonical)

    def to_dict(self):
        return {'schema_version': 1, 'provider': self.provider, 'capability': self.capability,
                'parameters': json.loads(encoded(self.parameters)), 'access_scope': self.access_scope,
                'native_version': self.native_version}

    @property
    def sha256(self):
        return digest(self.to_dict())


@dataclass(frozen=True)
class CacheOutcome:
    status: str
    source_ref: dict | None
    route: str
    cache_hit: bool
    attempt_refs: tuple
    reasons: tuple
    fetch_executed: bool

    def to_dict(self):
        result = asdict(self)
        result['attempt_refs'] = list(self.attempt_refs)
        result['reasons'] = list(self.reasons)
        return result


def validate_source(key, source_ref, *, validate=None):
    """Validate bytes and declared request identity, not economic truth.

    Built-in parameter checks cover current public adapters. A new parameter
    requires a caller validator; unknown parameters are never silently ignored.
    """
    source = read(source_ref)
    require(isinstance(source, dict) and source.get('provider') == key.provider, 'CACHE_PROVIDER_MISMATCH')
    require(source.get('access_level') in ('metadata', 'document'), 'CACHE_ACCESS_LEVEL_INVALID')
    operation = key.capability.rsplit('.', 1)[-1]
    if operation in ('discover', 'read'):
        require(source['access_level'] == ('metadata' if operation == 'discover' else 'document'), 'CACHE_ACCESS_LEVEL_INVALID')
    require(bool(read(source.get('raw'), json_value=False)), 'CACHE_RAW_EMPTY')
    instant(source.get('retrieved_at'))
    url = source.get('source_url')
    require(isinstance(url, str), 'CACHE_SOURCE_URL_INVALID')
    parsed = urlsplit(url)
    require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password,
            'CACHE_SOURCE_URL_INVALID')
    query = parse_qs(parsed.query)
    require(not any(_SECRET.search(k) for k in query), 'CACHE_SECRET_PARAMETER')
    if source['access_level'] == 'document':
        require(isinstance(source.get('upstream_id'), str) and source['upstream_id'], 'CACHE_IDENTITY_REQUIRED')
        require(bool(read(source.get('text'), json_value=False)), 'CACHE_TEXT_EMPTY')
        instant(source.get('available_at'))
    else:
        require(isinstance(source.get('candidates'), list) and bool(source['candidates']), 'CACHE_COVERAGE_EMPTY')
    if key.native_version is not None:
        require(str(source.get('source_version')) == key.native_version, 'CACHE_VERSION_MISMATCH')
    metadata = source.get('metadata') or {}
    require(isinstance(metadata, dict), 'CACHE_METADATA_INVALID')
    for name, value in key.parameters.items():
        if name in ('url', 'source_url'):
            require(value == url, 'CACHE_URL_MISMATCH')
        elif name == 'query':
            actual = query.get('search', query.get('search_query'))
            require(actual == [value], 'CACHE_QUERY_MISMATCH')
        elif name in ('paper_id', 'upstream_id', 'identifier'):
            require(value == source.get('upstream_id'), 'CACHE_IDENTITY_MISMATCH')
        elif name in ('period', 'entity', 'metric'):
            require(value == source.get(name, metadata.get(name)), 'CACHE_DEFINITION_MISMATCH')
        else:
            require(validate is not None, 'CACHE_PARAMETER_VALIDATOR_REQUIRED')
    if validate is not None:
        reason = validate(source)
        require(reason is None, reason if isinstance(reason, str) and _CODE.fullmatch(reason) else 'CACHE_SOURCE_REJECTED')
    return source


class Cache:
    def __init__(self, store, *, now=None, clock=time.monotonic, failure_cooldown_seconds=60):
        require(isinstance(store, Store), 'CACHE_STORE_REQUIRED')
        self.store = store
        self.locks = private_path(store.directory / 'cache-locks', create=True)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.clock = clock
        require(type(failure_cooldown_seconds) in (int, float) and math.isfinite(failure_cooldown_seconds)
                and 0 < failure_cooldown_seconds <= 3600, 'CACHE_COOLDOWN_INVALID')
        self.failure_cooldown_seconds = failure_cooldown_seconds

    def _remaining(self, deadline):
        remaining = deadline - self.clock()
        require(remaining > 0, 'CACHE_DEADLINE_EXPIRED')
        return remaining

    def _inspect(self, key, row, max_age, eligible, validate):
        if row is None:
            return None, False, 'CACHE_MISS', False
        if row['state'] != 'active':
            return None, False, 'CACHE_QUARANTINED', False
        try:
            require(row['fetch_key'] == key.to_dict(), 'CACHE_KEY_MISMATCH')
            source = validate_source(key, row['source_ref'], validate=validate)
            age = (instant(self.now()) - instant(row['checked_at'])).total_seconds()
            require(age >= -1, 'CACHE_CHECK_TIME_IN_FUTURE')
        except (SourceError, OSError, ValueError, UnicodeError) as exc:
            return None, False, _code(exc), True
        if eligible is not None:
            try:
                reason = eligible(source)
            except Exception:
                reason = 'CACHE_ELIGIBILITY_FAILED'
            if reason is not None:
                return source, False, reason if isinstance(reason, str) and _CODE.fullmatch(reason) else 'CACHE_INELIGIBLE', False
        return source, age <= max_age, None if age <= max_age else 'CACHE_EXPIRED', False

    @staticmethod
    def _same_observation(old, new):
        # Keep first-observed provenance for unchanged content. A retrieval check
        # cannot make an old document newly available at a later cutoff.
        names = ('provider', 'source_url', 'upstream_id', 'source_version', 'access_level', 'metadata')
        return old is not None and all(old.get(k) == new.get(k) for k in names) and all(
            (old.get(k) or {}).get('sha256') == (new.get(k) or {}).get('sha256') for k in ('raw', 'text'))

    def get_or_fetch(self, key, fetch_callable, *, deadline, max_age_seconds=3600,
                     eligible=None, validate=None, allow_stale=False, force_refresh=False):
        """Return one validated receipt, with at most one provider callback.

        ``deadline`` is an absolute monotonic deadline. Lock waits and SQLite
        waits consume it; late callbacks cannot publish. The callback itself
        must provide a bounded transport/subprocess timeout. ``allow_stale``
        applies only to retrieval TTL and requires explicit decision eligibility.
        """
        require(isinstance(key, FetchKey), 'CACHE_KEY_REQUIRED')
        require(callable(fetch_callable), 'CACHE_FETCH_REQUIRED')
        require(type(deadline) in (int, float) and math.isfinite(deadline), 'CACHE_DEADLINE_INVALID')
        require(type(max_age_seconds) in (int, float) and math.isfinite(max_age_seconds)
                and max_age_seconds >= 0, 'CACHE_MAX_AGE_INVALID')
        require(type(allow_stale) is bool and type(force_refresh) is bool, 'CACHE_POLICY_INVALID')
        require((eligible is None or callable(eligible)) and (validate is None or callable(validate)), 'CACHE_VALIDATOR_INVALID')
        require(not allow_stale or eligible is not None, 'CACHE_STALE_POLICY_REQUIRED')
        # Freeze even the nested parameter dictionary before any asynchronous I/O.
        key = FetchKey(**{k: v for k, v in key.to_dict().items() if k != 'schema_version'})
        started = self.clock(); call_id = 'cache-' + uuid.uuid4().hex
        reasons = []; fetch_executed = False; fetched_ref = None; lock = None
        row = None; source = None; usable = False; invalid = False

        def finish(status, ref, route):
            receipt = {'schema_version': 1, 'call_id': call_id, 'fetch_key': key.to_dict(),
                'status': status, 'source_ref': ref, 'fetched_source_ref': fetched_ref,
                'route': route, 'cache_hit': route in ('cache_hit', 'cache_fallback'),
                'fetch_executed': fetch_executed, 'reasons': list(dict.fromkeys(reasons)),
                'occurred_at': instant(self.now()).isoformat(), 'elapsed_seconds': max(0, self.clock() - started),
                'scope': 'acquisition_integrity_and_declared_eligibility',
                'claim_support': 'not_established_by_cache'}
            try:
                attempt_refs = (save(self.store.blobs, receipt),)
            except Exception:
                # Optional acquisition diagnostics must not discard usable data.
                attempt_refs = ()
                receipt['reasons'].append('CACHE_RECEIPT_UNAVAILABLE')
            return CacheOutcome(status, ref, route, receipt['cache_hit'], attempt_refs, tuple(receipt['reasons']), fetch_executed)

        def inspect():
            current = self.store.cache_read(key.sha256, timeout=self._remaining(deadline))
            return (current, *self._inspect(key, current, max_age_seconds, eligible, validate))

        try:
            row, source, usable, reason, invalid = inspect()
            if usable and not force_refresh:
                self._remaining(deadline)
                return finish('usable', row['source_ref'], 'cache_hit')
            if reason:
                reasons.append(reason)
            fd = os.open(self.locks / (key.sha256 + '.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            lock = os.fdopen(fd, 'r+')
            while True:
                self._remaining(deadline)
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(min(.02, self._remaining(deadline)))
            # A peer may have completed while we waited. No duplicate fetch.
            row, source, usable, reason, invalid = inspect()
            if usable and not force_refresh:
                return finish('usable', row['source_ref'], 'cache_hit')
            if reason and reason not in reasons:
                reasons.append(reason)
            if invalid:
                self.store.cache_invalidate(call_id + '-quarantine', key.sha256, row['generation'], reason,
                                            timeout=self._remaining(deadline))
                row = self.store.cache_read(key.sha256, timeout=self._remaining(deadline))
                source = None
            failure = self.store.cache_failure_read(key.sha256, timeout=self._remaining(deadline))
            if failure is not None and not force_refresh and (failure['retry_at'] is None
                    or instant(failure['retry_at']) > instant(self.now())):
                require(failure['fetch_key'] == key.to_dict(), 'CACHE_KEY_MISMATCH')
                reasons.append('CACHE_ACCESS_DEPENDENCY' if failure['retry_at'] is None else 'CACHE_PROVIDER_COOLDOWN')
                raise SourceError(failure['reason'])
            self._remaining(deadline)
            fetch_executed = True
            fetched_ref = fetch_callable()
            self._remaining(deadline)
            fetched = validate_source(key, fetched_ref, validate=validate)
            # An unchanged fetch is a check of the same observation, not a new
            # observation. Preserve its original receipt and publication time.
            selected_ref = row['source_ref'] if row and self._same_observation(source, fetched) else fetched_ref
            selected = source if selected_ref != fetched_ref else fetched
            if eligible is not None:
                rejection = eligible(selected)
                require(rejection is None, rejection if isinstance(rejection, str) and _CODE.fullmatch(rejection) else 'CACHE_INELIGIBLE')
            try:
                self.store.cache_publish(call_id + '-publish', key.to_dict(), selected_ref,
                    instant(self.now()).isoformat(), row['generation'] if row else 0, timeout=self._remaining(deadline))
            except (SourceError, OSError) as exc:
                # Cache publication is optional for acquisition. Do not lose a
                # validated original response because its reuse index is busy.
                reasons.extend((_code(exc), 'CACHE_PUBLICATION_UNAVAILABLE'))
                return finish('usable', selected_ref, 'fetch_uncached')
            self._remaining(deadline)
            return finish('usable', selected_ref, 'fetch')
        except Exception as exc:
            error = _code(exc)
            reasons.append(error)
            if fetch_executed and error in (_DEPENDENCY_ERRORS | _COOLDOWN_ERRORS):
                try:
                    at = instant(self.now())
                    retry_at = None if error in _DEPENDENCY_ERRORS else at + timedelta(seconds=self.failure_cooldown_seconds)
                    self.store.cache_failure(call_id + '-failure', key.to_dict(), error, at.isoformat(),
                        retry_at.isoformat() if retry_at else None, row['generation'] if row else 0,
                        timeout=self._remaining(deadline))
                except (SourceError, OSError):
                    reasons.append('CACHE_FAILURE_RECEIPT_UNAVAILABLE')
            # Only already-validated and decision-eligible cache can recover a
            # fetch failure; expiry exceptions require explicit stale policy.
            if source is not None and not invalid and (usable or allow_stale):
                try:
                    if eligible is not None:
                        require(eligible(source) is None, 'CACHE_INELIGIBLE')
                    self._remaining(deadline)
                    return finish('usable', row['source_ref'], 'cache_fallback')
                except Exception:
                    pass
            return finish('unavailable', None, 'unresolved')
        finally:
            if lock is not None:
                lock.close()  # OS releases flock even on process death.
