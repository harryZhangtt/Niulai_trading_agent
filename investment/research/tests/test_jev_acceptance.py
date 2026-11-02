"""Synthetic source-bound E2E checks; no credentials, network or accuracy gold."""
from copy import deepcopy
import json
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from shared.research_sources.artifacts import ROOT, SOURCE_STATE, SourceError, read, save
from shared.typed_judge import JudgeClient, TransportResponse
from investment.research import jev_acceptance as e2e


class JevAcceptanceTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name); self.calls = []
        self.chunk = save(self.directory, b'Synthetic public issuer quarterly revenue and enterprise adoption discussion.', suffix='txt')
        self.source = save(self.directory, {'provider': 'synthetic_capture', 'source_url': 'https://newsroom.servicenow.com/financial-results/synthetic',
            'upstream_id': 'synthetic-jev-e2e', 'source_version': 'synthetic-1', 'access_level': 'document',
            'retrieved_at': '2026-11-01T00:00:00Z', 'available_at': '2026-11-01T00:00:00Z',
            'raw': self.chunk, 'text': self.chunk})
        self.value = {'schema_version': 1, 'change_id': 'synthetic-jev-e2e',
            'source_ref': self.source, 'chunk_ref': self.chunk, 'cutoff': '2026-11-01T01:00:00Z',
            'policy': {'version': 'development-provisional-v1', 'min_probability': .6, 'min_margin': .1},
            'client': {'engine_scope': 'synthetic-jev-source', 'model': 'jev-1.14.0',
                       'timeout_seconds': 5, 'total_timeout_seconds': 10, 'max_retries': 0,
                       'max_request_bytes': 262144, 'max_response_bytes': 65536},
            'public_input_review': {'source_sha256': self.source['sha256'], 'chunk_sha256': self.chunk['sha256'],
                                    'reviewed_by': 'synthetic-test-owner', 'rationale': 'Synthetic public fixture; no real provider call'},
            'candidate_fingerprint': e2e.fingerprint()['sha256']}
        self.manifest = save(self.directory, self.value)

    def response(self, body, **_limits):
        payload = json.loads(body); self.calls.append(payload); answers = {}
        for key, question in payload['questions'].items():
            if question['type'] == 'choice':
                count = len(question['criteria'])
                answers[key] = {'type': 'choice', 'choice': 'earnings_release', 'confidence': .98,
                    'probabilities': {option: .99 if option == 'earnings_release' else .01 / (count - 1)
                                      for option in question['criteria']}}
            else:
                answers[key] = {'type': 'noul', 'noul': .9 if key in ('topic_financial_performance', 'topic_adoption') else .1}
        return TransportResponse(200, json.dumps({'model': payload['model'], 'answers': answers,
            'usage': {'input_tokens': 99, 'output_tokens': 24}}).encode())

    def factory(self, **options):
        return JudgeClient(**options, transport=self.response)

    def run_attempt(self, directory='attempt', factory=None):
        return e2e.exercise(self.manifest, self.directory / directory, attempt_id='synthetic-attempt',
                            allow_live=True, client_factory=factory or self.factory)

    def test_one_classification_then_cache_only_repeat_and_strict_host_bindings(self):
        result = self.run_attempt()
        self.assertEqual(result['status'], 'completed', result['code'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.calls[0]['questions']), 12)
        checked = e2e.validate_report(result['report_ref'], self.manifest, expected_transport='injected')
        self.assertTrue(checked['verified']); self.assertEqual(checked['repeat_live_calls'], 0)
        report = read(result['report_ref']); first = read(report['first_ref']); repeat = read(report['repeat_ref'])
        self.assertEqual(first['evaluation_output']['topics'], ['financial.performance', 'adoption'])
        self.assertTrue(read(repeat['judge_outcome_ref'])['receipt']['cache_hit'])
        # Fixture evidence must never pass the deployed real-provider gate.
        with self.assertRaisesRegex(SourceError, 'JEV_E2E_FRESH_CLASSIFICATION_REQUIRED'):
            e2e.validate_report(result['report_ref'], self.manifest)

    def test_unknown_timeout_is_preserved_without_repeat_or_same_directory_replay(self):
        calls = []
        def timeout(body, **limits):
            calls.append(body); raise TimeoutError('synthetic-private-marker')
        result = self.run_attempt(factory=lambda **options: JudgeClient(**options, transport=timeout))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['code'], 'JUDGE_TIMEOUT_UNKNOWN_OUTCOME')
        report = read(result['report_ref'])
        self.assertIsNotNone(report['first_ref']); self.assertIsNone(report['repeat_ref'])
        self.assertEqual(len(calls), 1)
        self.assertNotIn('synthetic-private-marker', json.dumps(report))
        with self.assertRaisesRegex(SourceError, 'JEV_E2E_ATTEMPT_EXISTS'):
            self.run_attempt(factory=lambda **options: JudgeClient(**options, transport=timeout))
        self.assertEqual(len(calls), 1)

    def test_disabled_call_is_not_a_cache_or_label_success(self):
        result = e2e.exercise(self.manifest, self.directory / 'disabled', attempt_id='disabled-attempt')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['code'], 'JUDGE_LIVE_DISABLED')
        self.assertIsNone(read(result['report_ref'])['repeat_ref'])

    def test_changed_code_input_or_review_cannot_be_rebound_to_old_attempt(self):
        for name, mutate, code in (
            ('code', lambda v: v.update(candidate_fingerprint='a' * 64), 'JEV_E2E_CANDIDATE_CHANGED'),
            ('review', lambda v: v['public_input_review'].update(chunk_sha256='a' * 64), 'JEV_E2E_PUBLIC_INPUT_REVIEW_REQUIRED'),
            ('chunk', lambda v: v.update(chunk_ref=save(self.directory, b'Not in original source', suffix='txt')), 'JEV_E2E_PUBLIC_INPUT_REVIEW_REQUIRED')):
            value = deepcopy(self.value); mutate(value)
            with self.subTest(name=name), self.assertRaisesRegex(SourceError, code):
                e2e.exercise(save(self.directory, value), self.directory / name, attempt_id=name, client_factory=self.factory)
        self.assertEqual(self.calls, [])

    def test_tampered_wrapper_or_semantic_projection_does_not_pass_host(self):
        result = self.run_attempt(); report = read(result['report_ref']); first = read(report['first_ref'])
        # A model's rewritten wrapper cannot replace its authoritative report.
        first['evaluation_output']['topics'] = []
        report['first_ref'] = save(self.directory, first)
        with self.assertRaisesRegex(SourceError, 'JEV_E2E_SOURCE_BINDING_MISMATCH'):
            e2e.validate_report(save(self.directory, report), self.manifest, expected_transport='injected')

    def test_host_delegates_only_read_only_verification_to_declared_domain_environment(self):
        self.run_attempt(directory='synthetic-attempt')
        # This is host-wiring conformance only; no fixture is promoted as live evidence.
        with patch.object(e2e.subprocess, 'run', return_value=types.SimpleNamespace(
                returncode=0, stdout='{"verified":true,"scope":"synthetic host wiring only"}')) as invoke:
            result = e2e.verify({'manifest_ref': self.manifest, 'output_root': str(self.directory.relative_to(ROOT))},
                ROOT, {'attempt_id': 'synthetic-attempt', 'scheduled_at': '2026-01-01T00:00:00+00:00'}, {})
        self.assertTrue(result['verified'])
        args = invoke.call_args.args[0]
        self.assertEqual(args[0], str(ROOT / '.research-sources/.venv/bin/python'))
        self.assertIn('--verify-report-ref', args)
        self.assertNotIn('--allow-live', args)
        self.assertEqual(invoke.call_args.kwargs['timeout'], 30)

    def test_read_only_validator_cli_rejects_live_flag_before_inspecting_input(self):
        with patch.object(sys, 'argv', ['jev_acceptance', '--manifest-ref', '{}', '--verify-report-ref', '{}', '--allow-live']), \
             patch('sys.stdout', io.StringIO()) as output:
            code = e2e.main()
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())['code'], 'JEV_E2E_VALIDATOR_ARGUMENTS_INVALID')


if __name__ == '__main__':
    unittest.main()
