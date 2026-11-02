"""Engine-scoped, provider-pinned typed classifier with an optional local cache.

No prompt, credential, provider error body, or raw response is put in receipts or
cache. The cache holds only validated typed outputs and hashes. It never turns an
unknown transport result into positive evidence. Live calls are off per call by
default; injected transports use no credential lookup.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid

from shared.research_sources.artifacts import ROOT, digest, encoded, private_path, read, save
from .contracts import (VERSION, PROVIDER, ENDPOINT, CREDENTIAL_REF, BooleanQuestion, EnumQuestion,
    Decision, JudgeError, JudgeResult, TransportResponse, identifier, number, probability, require,
    MAX_ATTEMPT_TIMEOUT_SECONDS, MAX_TOTAL_TIMEOUT_SECONDS, PROBABILITY_SUM_TOLERANCE)

_ERROR_CODES = {'JUDGE_REQUEST_INVALID', 'JUDGE_REQUEST_TOO_LARGE', 'JUDGE_RESPONSE_INVALID',
    'JUDGE_PROBABILITIES_INVALID', 'JUDGE_CHOICE_NOT_ARGMAX', 'JUDGE_MODEL_MISMATCH',
    'JUDGE_RESPONSE_QUESTION_MISMATCH', 'JUDGE_USAGE_INVALID', 'JUDGE_CACHE_LOCK_TIMEOUT',
    'JUDGE_CACHE_INVALID', 'JUDGE_TRANSPORT_FAILED', 'JUDGE_TIMEOUT_UNKNOWN_OUTCOME',
    'JUDGE_CREDENTIAL_UNAVAILABLE', 'JUDGE_CREDENTIAL_UNSAFE', 'JUDGE_RESPONSE_TOO_LARGE',
    'JUDGE_DEADLINE_EXPIRED', 'JUDGE_RETRY_BUDGET_EXHAUSTED', 'JUDGE_AUTH_FAILED',
    'JUDGE_RATE_LIMITED', 'JUDGE_PROVIDER_OVERLOADED', 'JUDGE_HTTP_FAILED'}


def _decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'JUDGE_RESPONSE_INVALID')
            result[key] = value
        return result
    def invalid(_):
        raise JudgeError('JUDGE_RESPONSE_INVALID')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise JudgeError('JUDGE_RESPONSE_INVALID') from None


def _decision(question, answer, model):
    require(isinstance(answer, dict), 'JUDGE_RESPONSE_INVALID')
    if isinstance(question, BooleanQuestion):
        require(set(answer) == {'type', 'noul'} and answer['type'] == 'noul' and probability(answer['noul']),
                'JUDGE_RESPONSE_INVALID')
        p = float(answer['noul'])
        probabilities = {'false': 1.0 - p, 'true': p}
        candidate = p >= .5
        winner = 'true' if candidate else 'false'
        confidence = None
        kind = 'boolean'
    else:
        require(set(answer) == {'type', 'choice', 'probabilities', 'confidence'} and answer['type'] == 'choice' and
                isinstance(answer['choice'], str) and answer['choice'] in question.options and
                isinstance(answer['probabilities'], dict) and set(answer['probabilities']) == set(question.options) and
                all(probability(value) for value in answer['probabilities'].values()) and probability(answer['confidence']),
                'JUDGE_RESPONSE_INVALID')
        probabilities = {key: float(answer['probabilities'][key]) for key in sorted(question.options)}
        require(abs(math.fsum(probabilities.values()) - 1) <= PROBABILITY_SUM_TOLERANCE + 1e-12, 'JUDGE_PROBABILITIES_INVALID')
        candidate = winner = answer['choice']
        require(abs(probabilities[winner] - max(probabilities.values())) <= 1e-6, 'JUDGE_CHOICE_NOT_ARGMAX')
        confidence = float(answer['confidence'])
        kind = 'enum'
    # Preserve the provider's distribution; do not silently renormalize malformed
    # responses. Confidence is a distribution statistic, not P(correct).
    ordered = sorted(probabilities.values(), reverse=True)
    reason = None
    if question.policy is None:
        reason = 'JUDGE_POLICY_NOT_CONFIGURED'
    elif isinstance(question, EnumQuestion) and candidate in question.abstain_options:
        reason = 'JUDGE_MODEL_ABSTAIN_OPTION'
    elif probabilities[winner] < question.policy.min_probability:
        reason = 'JUDGE_LOW_PROBABILITY'
    elif ordered[0] - ordered[1] < question.policy.min_margin:
        reason = 'JUDGE_SMALL_MARGIN'
    return Decision(question.id, kind, 'abstained' if reason else 'classified', None if reason else candidate,
        candidate, probabilities, confidence, reason, model, digest(question.contract()))


def _normalize(payload, questions, model):
    require(isinstance(payload, dict) and set(payload) == {'model', 'answers', 'usage'}, 'JUDGE_RESPONSE_INVALID')
    require(payload['model'] == model, 'JUDGE_MODEL_MISMATCH')
    require(isinstance(payload['answers'], dict) and set(payload['answers']) == {q.id for q in questions},
            'JUDGE_RESPONSE_QUESTION_MISMATCH')
    usage = payload['usage']
    require(isinstance(usage, dict) and set(usage) == {'input_tokens', 'output_tokens'} and
            all(type(value) is int and 0 <= value <= 10**9 for value in usage.values()), 'JUDGE_USAGE_INVALID')
    decisions = {q.id: _decision(q, payload['answers'][q.id], model) for q in questions}
    return decisions, dict(usage)


def _cache_payload(decisions, usage, model):
    answers = {}
    for key, decision in decisions.items():
        answers[key] = ({'type': 'noul', 'noul': decision.probabilities['true']} if decision.type == 'boolean' else
            {'type': 'choice', 'choice': decision.candidate, 'probabilities': decision.probabilities,
             'confidence': decision.confidence})
    return {'model': model, 'answers': answers, 'usage': usage}


class JudgeClient:
    def __init__(self, engine_scope, *, model='jev-1.14.0', cache_directory=None, transport=None,
                 credential_ref=CREDENTIAL_REF, timeout_seconds=5, total_timeout_seconds=10,
                 max_retries=0, max_request_bytes=65536, max_response_bytes=65536):
        identifier(engine_scope)
        require(isinstance(model, str) and re.fullmatch(r'jev-[1-9][0-9]*\.[0-9]+\.[0-9]+', model), 'JUDGE_PINNED_MODEL_REQUIRED')
        require(credential_ref == CREDENTIAL_REF, 'JUDGE_CREDENTIAL_REF_REJECTED')
        require(transport is None or callable(transport), 'JUDGE_TRANSPORT_INVALID')
        require(number(timeout_seconds) and 0 < timeout_seconds <= MAX_ATTEMPT_TIMEOUT_SECONDS and number(total_timeout_seconds) and
                0 < total_timeout_seconds <= MAX_TOTAL_TIMEOUT_SECONDS and type(max_retries) is int and 0 <= max_retries <= 1 and
                type(max_request_bytes) is int and 1 <= max_request_bytes <= 256*1024 and
                type(max_response_bytes) is int and 1 <= max_response_bytes <= 256*1024, 'JUDGE_LIMITS_INVALID')
        self.engine_scope, self.model, self.credential_ref = engine_scope, model, credential_ref
        self.transport = transport
        self.timeout_seconds, self.total_timeout_seconds = timeout_seconds, total_timeout_seconds
        self.max_retries = max_retries
        self.max_request_bytes, self.max_response_bytes = max_request_bytes, max_response_bytes
        self.directory = private_path(cache_directory, create=True) if cache_directory is not None else None

    @contextmanager
    def _lock(self, key, deadline):
        if self.directory is None:
            yield
            return
        path = self.directory / (key + '.lock')
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    remaining = deadline - time.monotonic()
                    require(remaining > 0, 'JUDGE_CACHE_LOCK_TIMEOUT')
                    time.sleep(min(.02, remaining))
            yield
        finally:
            os.close(descriptor)

    def _cached(self, key, questions):
        if self.directory is None:
            return None
        marker = self.directory / (key + '.json')
        if not marker.exists():
            return None
        try:
            require(not marker.is_symlink() and marker.stat().st_size <= 1024, 'JUDGE_CACHE_INVALID')
            ref = _decode(marker.read_bytes())
            value = read(ref)
            require(set(value) == {'kind', 'fingerprint', 'payload'} and value['kind'] == 'typed_judge_cache' and
                    value['fingerprint'] == key, 'JUDGE_CACHE_INVALID')
            return _normalize(value['payload'], questions, self.model)
        except Exception:
            raise JudgeError('JUDGE_CACHE_INVALID') from None

    def _publish(self, key, decisions, usage):
        if self.directory is None:
            return
        ref = save(self.directory, {'kind': 'typed_judge_cache', 'fingerprint': key,
            'payload': _cache_payload(decisions, usage, self.model)})
        pointer_ref = save(self.directory, ref)
        try:
            os.link(pointer_ref['path'], self.directory / (key + '.json'))
        except FileExistsError:
            # Another valid host must not replace the first immutable result.
            require(not (self.directory / (key + '.json')).is_symlink(), 'JUDGE_CACHE_INVALID')
        descriptor = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _live(self, body, timeout):
        request = {'body': body.decode(), 'credential_ref': self.credential_ref,
            'timeout_seconds': timeout, 'max_response_bytes': self.max_response_bytes}
        try:
            names = ('PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
                'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
                'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy')
            environment = {name: os.environ[name] for name in names if name in os.environ}
            environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', TMPDIR=str(ROOT/'.job-runtime/tmp'))
            result = subprocess.run([sys.executable, '-m', 'shared.typed_judge._worker'], input=encoded(request),
                cwd=ROOT, env=environment, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise JudgeError('JUDGE_TIMEOUT_UNKNOWN_OUTCOME') from None
        require(result.returncode == 0 and len(result.stdout) <= self.max_response_bytes*2 + 2048, 'JUDGE_TRANSPORT_FAILED')
        envelope = _decode(result.stdout)
        require(isinstance(envelope, dict), 'JUDGE_TRANSPORT_FAILED')
        if envelope.get('code'):
            code = envelope['code']
            require(set(envelope) == {'code'} and code in {'JUDGE_CREDENTIAL_UNAVAILABLE', 'JUDGE_CREDENTIAL_UNSAFE',
                'JUDGE_TRANSPORT_FAILED', 'JUDGE_TIMEOUT_UNKNOWN_OUTCOME', 'JUDGE_RESPONSE_TOO_LARGE'}, 'JUDGE_TRANSPORT_FAILED')
            raise JudgeError(code)
        require(set(envelope) == {'status', 'body_base64', 'retry_after_seconds'}, 'JUDGE_TRANSPORT_FAILED')
        import base64
        try:
            raw = base64.b64decode(envelope['body_base64'], validate=True)
            return TransportResponse(envelope['status'], raw, envelope.get('retry_after_seconds'))
        except (KeyError, ValueError, TypeError):
            raise JudgeError('JUDGE_TRANSPORT_FAILED') from None

    def judge(self, state, questions, *, allow_live=False):
        started = time.monotonic()
        deadline = started + self.total_timeout_seconds
        receipt = {'schema_version': 1, 'adapter_version': VERSION, 'execution_id': str(uuid.uuid4()),
            'engine_scope': self.engine_scope, 'provider': PROVIDER, 'model_requested': self.model,
            'model_resolved': None, 'request_sha256': None, 'schema_sha256': None, 'cache_key': None,
            'transport_kind': 'injected' if self.transport is not None else 'https', 'route': 'not_started',
            'attempts': 0, 'cache_hit': False, 'usage': None, 'usage_scope': 'not_observed',
            'elapsed_seconds': 0, 'warnings': [],
            'configured_limits': {'timeout_seconds': self.timeout_seconds, 'total_timeout_seconds': self.total_timeout_seconds,
                'max_retries': self.max_retries, 'max_request_bytes': self.max_request_bytes, 'max_response_bytes': self.max_response_bytes},
            'transport_attempts': [], 'http_status': None, 'provider_outcome': 'not_started',
            'probability_semantics': 'provider_estimates_not_independently_calibrated', 'semantic_approval': False}
        def finish(status, decisions=None, code=None):
            receipt['elapsed_seconds'] = max(0, time.monotonic() - started)
            receipt['status'], receipt['error_code'] = status, code
            return JudgeResult(status, decisions or {}, dict(receipt), code)
        try:
            require(type(allow_live) is bool and isinstance(questions, (list, tuple)) and
                    1 <= len(questions) <= 32 and all(isinstance(q, (BooleanQuestion, EnumQuestion)) for q in questions) and
                    len({q.id for q in questions}) == len(questions) and isinstance(state, (str, dict, list)), 'JUDGE_REQUEST_INVALID')
            try:
                body = encoded({'model': self.model, 'state': state, 'questions': {q.id: q.wire() for q in questions}})
            except (ValueError, TypeError, RecursionError):
                raise JudgeError('JUDGE_REQUEST_INVALID') from None
            require(len(body) <= self.max_request_bytes, 'JUDGE_REQUEST_TOO_LARGE')
            schema_sha = digest({q.id: q.contract() for q in questions})
            receipt.update(request_sha256=digest(_decode(body)), schema_sha256=schema_sha)
            key = digest({'adapter_version': VERSION, 'provider': PROVIDER, 'endpoint': ENDPOINT,
                'engine_scope': self.engine_scope, 'model': self.model, 'request_sha256': receipt['request_sha256'],
                'schema_sha256': schema_sha, 'transport_kind': receipt['transport_kind']})
            receipt['cache_key'] = key
            with self._lock(key, deadline):
                cached = self._cached(key, questions)
                if cached is not None:
                    decisions, usage = cached
                    require(time.monotonic() <= deadline, 'JUDGE_DEADLINE_EXPIRED')
                    receipt.update(route='cache', cache_hit=True, model_resolved=self.model, usage=usage,
                        usage_scope='original_cached_inference_no_new_call', provider_outcome='cached_response')
                else:
                    if self.transport is None and not allow_live:
                        return finish('disabled', code='JUDGE_LIVE_DISABLED')
                    transport = self.transport or (lambda body, *, timeout_seconds, max_response_bytes:
                        self._live(body, timeout_seconds))
                    response = None
                    for attempt in range(self.max_retries + 1):
                        remaining = deadline - time.monotonic()
                        require(remaining > 0, 'JUDGE_DEADLINE_EXPIRED')
                        receipt.update(attempts=attempt + 1, route='injected' if self.transport else 'https')
                        attempt_started = time.monotonic()
                        observed_attempt = {'index': attempt + 1, 'timeout_seconds': min(self.timeout_seconds, remaining),
                            'elapsed_seconds': 0, 'http_status': None, 'provider_outcome': 'unknown'}
                        receipt['transport_attempts'].append(observed_attempt)
                        receipt['provider_outcome'] = 'unknown'
                        try:
                            response = transport(body, timeout_seconds=observed_attempt['timeout_seconds'],
                                max_response_bytes=self.max_response_bytes)
                        except JudgeError as exc:
                            if str(exc) in ('JUDGE_CREDENTIAL_UNAVAILABLE', 'JUDGE_CREDENTIAL_UNSAFE'):
                                receipt['provider_outcome'] = observed_attempt['provider_outcome'] = 'not_started'
                            raise
                        except TimeoutError:
                            raise JudgeError('JUDGE_TIMEOUT_UNKNOWN_OUTCOME') from None
                        except Exception:
                            raise JudgeError('JUDGE_TRANSPORT_FAILED') from None
                        finally:
                            observed_attempt['elapsed_seconds'] = max(0, time.monotonic() - attempt_started)
                        require(isinstance(response, TransportResponse) and type(response.status) is int and
                                100 <= response.status <= 599 and isinstance(response.body, bytes), 'JUDGE_TRANSPORT_FAILED')
                        receipt['provider_outcome'] = observed_attempt['provider_outcome'] = 'response_received'
                        receipt['http_status'] = observed_attempt['http_status'] = response.status
                        require(time.monotonic() <= deadline, 'JUDGE_DEADLINE_EXPIRED')
                        require(len(response.body) <= self.max_response_bytes, 'JUDGE_RESPONSE_TOO_LARGE')
                        if response.status not in (429, 529) or attempt == self.max_retries:
                            break
                        delay = response.retry_after_seconds if response.retry_after_seconds is not None else .1
                        require(number(delay) and delay >= 0 and delay < deadline - time.monotonic(), 'JUDGE_RETRY_BUDGET_EXHAUSTED')
                        time.sleep(delay)
                    if response.status != 200:
                        code = ('JUDGE_AUTH_FAILED' if response.status == 401 else 'JUDGE_RATE_LIMITED' if response.status == 429 else
                            'JUDGE_PROVIDER_OVERLOADED' if response.status == 529 else 'JUDGE_HTTP_FAILED')
                        raise JudgeError(code)
                    decisions, usage = _normalize(_decode(response.body), questions, self.model)
                    receipt.update(model_resolved=self.model, usage=usage, usage_scope='this_inference_provider_reported')
                    try:
                        self._publish(key, decisions, usage)
                    except Exception:
                        receipt['warnings'].append('JUDGE_CACHE_PUBLICATION_FAILED')
                accepted = sum(decision.status == 'classified' for decision in decisions.values())
                return finish('ok' if accepted == len(decisions) else 'abstained' if accepted == 0 else 'partial', decisions)
        except JudgeError as exc:
            return finish('error', code=str(exc) if str(exc) in _ERROR_CODES else 'JUDGE_TRANSPORT_FAILED')
        except Exception:
            return finish('error', code='JUDGE_LOCAL_FAILED')

