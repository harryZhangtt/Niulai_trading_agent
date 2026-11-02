"""Synthetic classification/judge consumers; no real key or provider access."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import base64
import io
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

from shared.research_sources.artifacts import SOURCE_STATE
from shared.typed_judge import BooleanQuestion, EnumQuestion, DecisionPolicy, JudgeClient, JudgeError, TransportResponse


MODEL = 'jev-1.14.0'
SYNTHETIC_SECRET = 'SYNTHETIC_SECRET_NEVER_A_REAL_KEY'


class JudgeTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.calls = []
        self.policy = DecisionPolicy(.8, .2)
        self.questions = [BooleanQuestion('is_actual', 'Does the supplied passage describe a reported actual?', policy=self.policy),
            EnumQuestion('support', 'Does the passage support the supplied claim?',
                {'supported': 'Directly supported in the scoped passage', 'insufficient': 'Not established by this passage'},
                policy=self.policy, abstain_options=('insufficient',))]

    def payload(self):
        return {'model': MODEL, 'answers': {'is_actual': {'type': 'noul', 'noul': .9},
            'support': {'type': 'choice', 'choice': 'supported', 'confidence': .8,
                'probabilities': {'supported': .9, 'insufficient': .1}}},
            'usage': {'input_tokens': 123, 'output_tokens': 4}}

    def transport(self, body, **limits):
        self.calls.append((json.loads(body), limits))
        return TransportResponse(200, json.dumps(self.payload()).encode())

    def client(self, **kwargs):
        return JudgeClient('synthetic-source-labels', transport=self.transport, **kwargs)

    def test_boolean_and_enum_consumers_return_typed_probability_records(self):
        result = self.client().judge({'passage': 'Explicit synthetic issuer statement.', 'claim': 'Synthetic claim.'}, self.questions)
        self.assertEqual(result.status, 'ok')
        self.assertIs(result.decisions['is_actual'].value, True)
        self.assertEqual(result.decisions['support'].value, 'supported')
        self.assertAlmostEqual(result.decisions['is_actual'].probabilities['false'], .1)
        self.assertIsNone(result.decisions['is_actual'].confidence)
        self.assertEqual(result.decisions['support'].confidence, .8)
        self.assertTrue(all(d.model_resolved == MODEL and len(d.schema_sha256) == 64 for d in result.decisions.values()))
        self.assertFalse(result.receipt['semantic_approval'])
        self.assertEqual(set(self.calls[0][0]), {'model', 'state', 'questions'})
        self.assertEqual(self.calls[0][0]['questions']['is_actual']['type'], 'noul')
        self.assertEqual(self.calls[0][0]['questions']['support']['type'], 'choice')

    def test_default_disabled_and_injected_transport_never_lookup_real_credentials(self):
        with patch('shared.typed_judge.client.subprocess.run') as worker, \
                patch('shared.typed_judge._worker._credential') as credential:
            result = JudgeClient('source-labels').judge('Synthetic input', self.questions)
            self.assertEqual((result.status, result.error_code), ('disabled', 'JUDGE_LIVE_DISABLED'))
            self.assertEqual(self.client().judge('Synthetic input', self.questions).status, 'ok')
            worker.assert_not_called(); credential.assert_not_called()

    def test_policy_absence_low_probability_small_margin_and_unknown_are_abstentions(self):
        absent = [BooleanQuestion('is_actual', 'Synthetic question'), self.questions[1]]
        result = self.client().judge('Synthetic input', absent)
        self.assertEqual(result.status, 'partial')
        self.assertIsNone(result.decisions['is_actual'].value)
        self.assertEqual(result.decisions['is_actual'].reason_code, 'JUDGE_POLICY_NOT_CONFIGURED')
        for p, reason in ((.7, 'JUDGE_LOW_PROBABILITY'), (.81, 'JUDGE_SMALL_MARGIN')):
            question = BooleanQuestion('is_actual', 'Synthetic question', policy=DecisionPolicy(.8, .7))
            def transport(body, **kwargs):
                value = self.payload(); value['answers'] = {'is_actual': {'type': 'noul', 'noul': p}}
                return TransportResponse(200, json.dumps(value).encode())
            result = JudgeClient('synthetic', transport=transport).judge('Synthetic input', [question])
            self.assertEqual(result.status, 'abstained')
            self.assertEqual(result.decisions['is_actual'].reason_code, reason)
        def unknown(body, **kwargs):
            value = self.payload(); value['answers']['support'].update(choice='insufficient',
                probabilities={'supported': .1, 'insufficient': .9})
            return TransportResponse(200, json.dumps(value).encode())
        result = JudgeClient('synthetic', transport=unknown).judge('Synthetic input', self.questions)
        self.assertEqual(result.decisions['support'].reason_code, 'JUDGE_MODEL_ABSTAIN_OPTION')

    def test_closed_probability_contract_rejects_provider_faults(self):
        faults = {
            'missing_question': lambda v: v['answers'].pop('support'),
            'extra_question': lambda v: v['answers'].update(oracle={'type': 'noul', 'noul': .9}),
            'null_noul': lambda v: v['answers']['is_actual'].update(noul=None),
            'bool_noul': lambda v: v['answers']['is_actual'].update(noul=True),
            'nan_noul': lambda v: v['answers']['is_actual'].update(noul=float('nan')),
            'bad_range': lambda v: v['answers']['is_actual'].update(noul=1.1),
            'unknown_label': lambda v: v['answers']['support'].update(choice='invented'),
            'extra_probability': lambda v: v['answers']['support']['probabilities'].update(invented=0),
            'bad_sum': lambda v: v['answers']['support']['probabilities'].update(supported=.99, insufficient=.5),
            'not_argmax': lambda v: v['answers']['support'].update(choice='insufficient'),
            'bad_confidence': lambda v: v['answers']['support'].update(confidence='high'),
            'model_alias': lambda v: v.update(model='jev-latest'),
            'model_upgrade': lambda v: v.update(model='jev-1.15.0'),
            'bad_usage': lambda v: v['usage'].update(input_tokens=True),
            'unexpected_field': lambda v: v.update(debug=SYNTHETIC_SECRET),
        }
        for name, mutate in faults.items():
            with self.subTest(fault=name):
                value = self.payload(); mutate(value)
                client = JudgeClient('synthetic', transport=lambda *a, **k: TransportResponse(200, json.dumps(value).encode()))
                result = client.judge('Synthetic input', self.questions)
                self.assertEqual(result.status, 'error')
                self.assertEqual(result.decisions, {})
                self.assertNotIn(SYNTHETIC_SECRET, json.dumps(result.to_dict()))

    def test_duplicate_json_keys_and_huge_body_are_rejected(self):
        for body, maximum, code in ((b'{"model":"a","model":"b"}', 1024, 'JUDGE_RESPONSE_INVALID'),
                (b'x'*1025, 1024, 'JUDGE_RESPONSE_TOO_LARGE')):
            client = JudgeClient('synthetic', transport=lambda *a, **k: TransportResponse(200, body), max_response_bytes=maximum)
            self.assertEqual(client.judge('Synthetic input', self.questions).error_code, code)

    def test_receipts_and_cache_never_contain_prompt_credential_or_raw_errors(self):
        state = 'SYNTHETIC_PRIVATE_PROMPT_BODY'
        result = self.client(cache_directory=self.directory/'cache').judge(state, self.questions)
        self.assertNotIn(state, json.dumps(result.receipt))
        for path in (self.directory/'cache').glob('*.json'):
            self.assertNotIn(state, path.read_text())
            self.assertNotIn(SYNTHETIC_SECRET, path.read_text())
        for exception in (RuntimeError(SYNTHETIC_SECRET), JudgeError(SYNTHETIC_SECRET)):
            def broken(*a, **k): raise exception
            result = JudgeClient('synthetic', transport=broken).judge(state, self.questions)
            self.assertEqual(result.error_code, 'JUDGE_TRANSPORT_FAILED')
            self.assertNotIn(SYNTHETIC_SECRET, json.dumps(result.to_dict()))

    def test_canonical_cache_is_durable_and_isolated_by_engine_schema_model_and_transport(self):
        directory = self.directory/'cache'
        first = self.client(cache_directory=directory).judge({'b': 2, 'a': 1}, self.questions)
        second = self.client(cache_directory=directory).judge({'a': 1, 'b': 2}, self.questions)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(second.receipt['cache_hit'])
        self.assertEqual(second.receipt['usage_scope'], 'original_cached_inference_no_new_call')
        self.assertEqual(first.receipt['cache_key'], second.receipt['cache_key'])
        self.assertEqual(first.decisions, second.decisions)
        changed = [BooleanQuestion('is_actual', 'Changed synthetic instruction', policy=self.policy), self.questions[1]]
        self.client(cache_directory=directory).judge({'a': 1, 'b': 2}, changed)
        self.assertEqual(len(self.calls), 2)
        JudgeClient('second-judge-engine', transport=self.transport, cache_directory=directory).judge({'a': 1, 'b': 2}, self.questions)
        self.assertEqual(len(self.calls), 3)
        disabled = JudgeClient('synthetic-source-labels', cache_directory=directory).judge({'a': 1, 'b': 2}, self.questions)
        self.assertEqual(disabled.status, 'disabled')
        self.assertNotEqual(disabled.receipt['cache_key'], first.receipt['cache_key'])
        new_model = JudgeClient('synthetic-source-labels', model='jev-1.13.0', transport=self.transport, cache_directory=directory)
        mismatch = new_model.judge({'a': 1, 'b': 2}, self.questions)
        self.assertEqual(mismatch.error_code, 'JUDGE_MODEL_MISMATCH')

    def test_corrupt_cache_fails_closed_without_network_refetch(self):
        client = self.client(cache_directory=self.directory/'cache')
        first = client.judge('Synthetic input', self.questions)
        marker = self.directory/'cache'/(first.receipt['cache_key']+'.json')
        artifact_ref = json.loads(marker.read_text())
        Path(artifact_ref['path']).write_bytes(b'Synthetic corrupted normalized output')
        second = client.judge('Synthetic input', self.questions)
        self.assertEqual(second.error_code, 'JUDGE_CACHE_INVALID')
        self.assertEqual(len(self.calls), 1)

    def test_concurrent_identical_requests_share_one_validated_fetch(self):
        calls = []
        lock = threading.Lock()
        def transport(body, **limits):
            with lock: calls.append(1)
            time.sleep(.02)
            return TransportResponse(200, json.dumps(self.payload()).encode())
        clients = [JudgeClient('synthetic', transport=transport, cache_directory=self.directory/'cache') for _ in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda client: client.judge('Synthetic input', self.questions), clients))
        self.assertTrue(all(result.status == 'ok' for result in results))
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(result.receipt['cache_hit'] for result in results), 3)

    def test_unknown_failure_never_becomes_positive_cache_and_optional_publication_isolated(self):
        calls = []
        def transport(body, **kwargs):
            calls.append(1)
            if len(calls) == 1: raise TimeoutError(SYNTHETIC_SECRET)
            return TransportResponse(200, json.dumps(self.payload()).encode())
        client = JudgeClient('synthetic', transport=transport, cache_directory=self.directory/'cache')
        self.assertEqual(client.judge('Synthetic input', self.questions).error_code, 'JUDGE_TIMEOUT_UNKNOWN_OUTCOME')
        self.assertEqual(client.judge('Synthetic input', self.questions).status, 'ok')
        self.assertEqual(len(calls), 2)
        other = self.client()
        with patch.object(other, '_publish', side_effect=RuntimeError(SYNTHETIC_SECRET)):
            result = other.judge('Synthetic input', self.questions)
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.receipt['warnings'], ['JUDGE_CACHE_PUBLICATION_FAILED'])

    def test_retry_is_bounded_only_explicit_overload_or_rate_limit(self):
        calls = []
        def limited(body, **kwargs):
            calls.append(1)
            return TransportResponse(429, b'Synthetic provider error', 0) if len(calls) == 1 else self.transport(body, **kwargs)
        result = JudgeClient('synthetic', transport=limited, max_retries=1).judge('Synthetic input', self.questions)
        self.assertEqual((result.status, result.receipt['attempts']), ('ok', 2))
        for status in (401, 500, 529):
            attempts = []
            def error(*a, **k):
                attempts.append(1); return TransportResponse(status, SYNTHETIC_SECRET.encode())
            result = JudgeClient('synthetic', transport=error).judge('Synthetic input', self.questions)
            self.assertEqual(result.status, 'error'); self.assertEqual(len(attempts), 1)
            self.assertNotIn(SYNTHETIC_SECRET, json.dumps(result.to_dict()))
        result = JudgeClient('synthetic', transport=lambda *a, **k: TransportResponse(429, b'', 1000), max_retries=1).judge('Synthetic input', self.questions)
        self.assertEqual(result.error_code, 'JUDGE_RETRY_BUDGET_EXHAUSTED')

    def test_late_injected_result_and_hard_live_worker_timeout_are_not_cached(self):
        def late(*a, **k):
            time.sleep(.005)
            return TransportResponse(200, json.dumps(self.payload()).encode())
        result = JudgeClient('synthetic', transport=late, total_timeout_seconds=.001).judge('Synthetic input', self.questions)
        self.assertEqual(result.error_code, 'JUDGE_DEADLINE_EXPIRED')
        with patch('shared.typed_judge.client.subprocess.run', side_effect=subprocess.TimeoutExpired('synthetic-worker', .01)) as worker:
            result = JudgeClient('synthetic').judge('Synthetic input', self.questions, allow_live=True)
        self.assertEqual(result.error_code, 'JUDGE_TIMEOUT_UNKNOWN_OUTCOME')
        call = worker.call_args
        self.assertNotIn('Authorization', str(call.args))
        self.assertNotIn(SYNTHETIC_SECRET, str(call))

    def test_input_and_model_pins_rejected_before_transport(self):
        with self.assertRaisesRegex(JudgeError, 'JUDGE_PINNED_MODEL_REQUIRED'):
            JudgeClient('synthetic', model='jev-latest')
        with self.assertRaisesRegex(JudgeError, 'JUDGE_CREDENTIAL_REF_REJECTED'):
            JudgeClient('synthetic', credential_ref='/unrelated/secret')
        client = self.client(max_request_bytes=20)
        self.assertEqual(client.judge('Synthetic long state'*100, self.questions).error_code, 'JUDGE_REQUEST_TOO_LARGE')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.client().judge({'x': float('nan')}, self.questions).error_code, 'JUDGE_REQUEST_INVALID')


class CredentialIsolationTests(unittest.TestCase):
    def test_only_synthetic_file_is_read_under_mocked_root(self):
        from shared.typed_judge import _worker
        parent = SOURCE_STATE/'tmp'; parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temp:
            root = Path(temp)
            path = root/'.job-runtime/credentials/jev.api-key'
            path.parent.mkdir(parents=True, mode=0o700)
            path.write_text(SYNTHETIC_SECRET); path.chmod(0o600)
            with patch.object(_worker, 'ROOT', root):
                self.assertEqual(_worker._credential('.job-runtime/credentials/jev.api-key'), SYNTHETIC_SECRET)
                path.chmod(0o644)
                with self.assertRaisesRegex(ValueError, 'JUDGE_CREDENTIAL_UNSAFE'):
                    _worker._credential('.job-runtime/credentials/jev.api-key')


class TransportDiagnosticsTests(unittest.TestCase):
    def test_real_child_wall_timeout_is_reaped_and_not_retried_or_cached(self):
        import shared.typed_judge.client as implementation
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            directory = Path(folder)
            script = directory / 'synthetic-worker'
            # exec retains the launched PID and creates no detached descendant.
            script.write_text('#!/bin/sh\nexec /bin/sleep 10\n')
            script.chmod(0o700)
            launched = []; actual_popen = subprocess.Popen
            def launch(*args, **kwargs):
                process = actual_popen(*args, **kwargs)
                launched.append(process.pid)
                return process
            # Observe the PID in the parent. A valid hard timeout can occur
            # before any child-side startup marker has been written.
            with patch.object(implementation.sys, 'executable', str(script)), \
                 patch.object(implementation.subprocess, 'Popen', side_effect=launch):
                result = JudgeClient('synthetic-process-wall', timeout_seconds=1, total_timeout_seconds=2,
                    max_retries=1, cache_directory=directory / 'cache').judge('Synthetic public state',
                        [BooleanQuestion('topic', 'Synthetic question')], allow_live=True)
            self.assertEqual(result.error_code, 'JUDGE_TIMEOUT_UNKNOWN_OUTCOME')
            self.assertEqual(result.receipt['attempts'], 1)
            self.assertEqual(result.receipt['provider_outcome'], 'unknown')
            self.assertFalse((directory / 'cache' / (result.receipt['cache_key'] + '.json')).exists())
            self.assertEqual(len(launched), 1)
            with self.assertRaises(ProcessLookupError):
                os.kill(launched[0], 0)

    def test_explicit_host_diagnostic_budget_is_bounded_and_defaults_unchanged(self):
        ordinary = JudgeClient('synthetic-defaults')
        self.assertEqual((ordinary.timeout_seconds, ordinary.total_timeout_seconds), (5, 10))
        configured = JudgeClient('synthetic-slow-host', timeout_seconds=45, total_timeout_seconds=60)
        self.assertEqual((configured.timeout_seconds, configured.total_timeout_seconds), (45, 60))
        for limits in ({'timeout_seconds': 61}, {'total_timeout_seconds': 121}):
            with self.assertRaisesRegex(JudgeError, 'JUDGE_LIMITS_INVALID'):
                JudgeClient('synthetic-limit-rejected', **limits)

    def test_socket_timeout_inside_worker_retains_unknown_outcome_and_no_error_text(self):
        from shared.typed_judge import _worker
        from urllib.error import URLError
        message = {'body': '{}', 'credential_ref': '.job-runtime/credentials/jev.api-key',
                   'timeout_seconds': 45, 'max_response_bytes': 1024}
        for failure in (TimeoutError(SYNTHETIC_SECRET), URLError(TimeoutError(SYNTHETIC_SECRET))):
            output = io.BytesIO()
            with patch.object(_worker.sys, 'stdin', types.SimpleNamespace(buffer=io.BytesIO(json.dumps(message).encode()))), \
                 patch.object(_worker.sys, 'stdout', types.SimpleNamespace(buffer=output)), \
                 patch.object(_worker, '_credential', return_value=SYNTHETIC_SECRET), \
                 patch.object(_worker.request, 'build_opener') as opener:
                opener.return_value.open.side_effect = failure
                _worker.main()
            result = json.loads(output.getvalue())
            self.assertEqual(result, {'code': 'JUDGE_TIMEOUT_UNKNOWN_OUTCOME'})
            self.assertNotIn(SYNTHETIC_SECRET, output.getvalue().decode())

    def test_retry_after_accepts_dates_and_rejects_nonfinite_or_negative_values(self):
        from shared.typed_judge import _worker
        now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.assertEqual(_worker._retry_after('30', now), 30)
        self.assertEqual(_worker._retry_after('Sun, 01 Nov 2026 00:01:00 GMT', now), 60)
        for value in ('NaN', 'inf', '-2', 'not-a-date', None):
            self.assertIsNone(_worker._retry_after(value, now))

    def test_live_worker_environment_and_sanitized_attempt_receipt(self):
        payload = {'model': MODEL, 'answers': {'topic': {'type': 'noul', 'noul': .9}},
                   'usage': {'input_tokens': 3, 'output_tokens': 0}}
        envelope = {'status': 200, 'body_base64': base64.b64encode(json.dumps(payload).encode()).decode(),
                    'retry_after_seconds': None}
        complete = subprocess.CompletedProcess(['synthetic'], 0, stdout=json.dumps(envelope).encode())
        with patch.dict(os.environ, {'UNRELATED_PROVIDER_API_KEY': SYNTHETIC_SECRET}), \
             patch('shared.typed_judge.client.subprocess.run', return_value=complete) as worker:
            result = JudgeClient('synthetic-live', timeout_seconds=45, total_timeout_seconds=60).judge(
                'Synthetic public state', [BooleanQuestion('topic', 'Synthetic question', policy=DecisionPolicy(.8))], allow_live=True)
        self.assertEqual(result.status, 'ok')
        self.assertFalse('UNRELATED_PROVIDER_API_KEY' in worker.call_args.kwargs['env'])
        self.assertEqual(worker.call_args.kwargs['timeout'], 45)
        self.assertEqual(result.receipt['configured_limits']['timeout_seconds'], 45)
        self.assertEqual(result.receipt['provider_outcome'], 'response_received')
        self.assertEqual(result.receipt['http_status'], 200)
        attempt = result.receipt['transport_attempts'][0]
        self.assertEqual((attempt['timeout_seconds'], attempt['http_status']), (45, 200))
        self.assertGreaterEqual(attempt['elapsed_seconds'], 0)
        self.assertNotIn(SYNTHETIC_SECRET, json.dumps(result.to_dict()))


if __name__ == '__main__':
    unittest.main()
