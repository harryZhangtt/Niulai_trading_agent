"""Recorded, bounded cloud pacing; unknown writes are never retried here."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import re
import time
from uuid import uuid4

from langsmith import Client
from langsmith.utils import LangSmithRateLimitError

from .session_model import ROOT, private_read, private_write, require

CONFIG = Path(__file__).with_name('cloud-read-policy.json')
STATE = ROOT / '.langchain-pilot/runtime/cloud-rate'
READ_POSTS = {'/runs/query', '/examples/query', '/feedback/query'}


def policy(value=None):
    value = json.loads(CONFIG.read_text()) if value is None else value
    require(isinstance(value, dict), 'ATOMIC_RATE_POLICY_INVALID')
    value = dict(value)
    expected = {'read_interval_seconds', 'query_interval_seconds', 'write_interval_seconds',
                'max_read_attempts', 'read_budget_seconds', 'fallback_backoff_seconds',
                'max_backoff_seconds', 'warmup_delay_seconds'}
    require(set(value) == expected and all(isinstance(x, (int, float)) and not isinstance(x, bool)
            and math.isfinite(x) and 0 <= x <= 600 for x in value.values()), 'ATOMIC_RATE_POLICY_INVALID')
    require(isinstance(value['max_read_attempts'], int) and 1 <= value['max_read_attempts'] <= 5
            and 0 < value['read_budget_seconds'] <= 600
            and value['warmup_delay_seconds'] <= 60, 'ATOMIC_RATE_POLICY_INVALID')
    return value


def retry_after(value, *, now=None):
    if not isinstance(value, str): return None
    try:
        number = float(value)
        if math.isfinite(number) and number >= 0: return number
    except ValueError: pass
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None: date = date.replace(tzinfo=timezone.utc)
        return max(0, date.timestamp() - (time.time() if now is None else now))
    except (ValueError, TypeError, OverflowError): return None


def error_response(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        response = getattr(error, 'response', None)
        if response is not None: return response
        error = error.__cause__ or error.__context__
    return None


class RateAwareClient(Client):
    def __init__(self, *args, rate_state=STATE, read_policy=None, **kwargs):
        selected_policy = policy(read_policy)
        super().__init__(*args, **kwargs)
        self.read_policy = selected_policy
        self.rate_state = Path(rate_state)
        self.rate_state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._warm = False

    def _event(self, request_id, **value):
        private_write(self.rate_state / 'attempts' / (str(uuid4()) + '.json'),
                      {'request_id': request_id, 'at_ns': time.time_ns(), 'policy': self.read_policy, **value})

    @contextmanager
    def _slot(self, interval, deadline, request_id, category):
        lockpath = self.rate_state / 'pacing.lock'
        with os.fdopen(os.open(lockpath, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.rate_state / 'pacing.json'
            prior = private_read(path) if path.exists() else {}
            wait = max(0, prior.get('next_' + category + '_at', 0) - time.time())
            if time.monotonic() + wait > deadline:
                self._event(request_id, disposition='pacing_budget_exhausted', delay_seconds=wait,
                            category=category)
                raise ValueError('ATOMIC_RATE_WAIT_BUDGET_EXHAUSTED')
            if wait:
                self._event(request_id, disposition='pacing_wait', delay_seconds=wait)
                time.sleep(wait)
            # A reservation can be delayed before it reaches the transport.
            # Hold the lock through dispatch and start the next interval after
            # this attempt ends; delayed callers cannot release a later burst.
            try:
                yield
            finally:
                private_write(path, {**prior, 'next_' + category + '_at': time.time() + interval},
                              replace=path.exists())

    def warmup(self):
        if self._warm: return
        rid = str(uuid4())
        self._event(rid, disposition='warmup_started', delay_seconds=self.read_policy['warmup_delay_seconds'])
        time.sleep(self.read_policy['warmup_delay_seconds'])
        try: self.request_with_retries('GET', '/info')
        except BaseException as error:
            self._event(rid, disposition='warmup_failed', error_type=type(error).__name__)
            raise
        self._warm = True
        self._event(rid, disposition='warmup_completed')

    def request_with_retries(self, method, pathname, *, stop_after_attempt=1, **kwargs):
        # SDK helpers may request several retries. This component is the single
        # authority; underlying calls execute once. Only allowlisted reads retry.
        path = pathname.split('?', 1)[0]
        readonly = method == 'GET' or (method == 'POST' and path in READ_POSTS)
        attempts = self.read_policy['max_read_attempts'] if readonly else 1
        interval = self.read_policy['query_interval_seconds'] if path in READ_POSTS else (
            self.read_policy['read_interval_seconds'] if readonly else self.read_policy['write_interval_seconds'])
        category = 'query' if path in READ_POSTS else ('read' if readonly else 'write')
        deadline = time.monotonic() + self.read_policy['read_budget_seconds']
        rid = str(uuid4())
        # Record endpoint shape only: no payloads, query strings, headers or keys.
        safe_path = '/' + '/'.join(part if part in {'runs', 'query', 'info', 'examples', 'feedback',
            'datasets', 'sessions', 'agents', 'repos', 'commits', 'tags', 'search', 'latest', 'exists'}
            else '{resource}' for part in path.strip('/').split('/'))
        for attempt in range(1, attempts + 1):
            try:
                with self._slot(interval, deadline, rid, category):
                    self._event(rid, disposition='dispatching', method=method, endpoint=safe_path,
                                readonly=readonly, attempt=attempt)
                    response = super().request_with_retries(method, pathname, stop_after_attempt=1, **kwargs)
                self._event(rid, disposition='acknowledged', status=response.status_code, attempt=attempt)
                return response
            except LangSmithRateLimitError as error:
                response = error_response(error)
                after = retry_after(response.headers.get('Retry-After')) if response is not None else None
                delay = after if after is not None else min(self.read_policy['max_backoff_seconds'],
                    self.read_policy['fallback_backoff_seconds'] * 2 ** (attempt - 1))
                can_retry = readonly and attempt < attempts and time.monotonic() + delay <= deadline
                self._event(rid, disposition='retry_scheduled' if can_retry else 'rate_limit_stopped',
                            status=429, attempt=attempt, retry_after_seconds=after, delay_seconds=delay,
                            readonly=readonly, unknown_write=not readonly)
                if not can_retry: raise
                time.sleep(delay)
            except BaseException as error:
                self._event(rid, disposition='failed_or_unknown', attempt=attempt,
                            error_type=type(error).__name__, readonly=readonly)
                raise
