"""Once-only runner and read-only replay checks with synthetic local transport."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from shared.research_sources.artifacts import SourceError, read, save
from shared.typed_judge import JudgeClient, JudgeError, TransportResponse
from tuning.evals.label_accuracy import run_screen as runner
from tuning.evals.label_accuracy import test_screen


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_screen.ScreenTests('test_baseline_only_emits_existing_hints_and_abstains_on_every_other_topic')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.directory = self.fixture.directory; self.calls = []
        for item in self.fixture.manifest['cases']:
            source = read(item['source_ref'])
            item['source_ref'] = save(self.directory, {**source, 'access_level': 'document',
                'upstream_id': item['id'], 'source_version': 'synthetic-v1'})
        self.fixture.write_reviewed()
        self.preparation_ref = save(self.directory, self.fixture.prepare())

    def response(self, body, **limits):
        request = json.loads(body); self.calls.append(request)
        answers = {}
        for key, question in request['questions'].items():
            if question['type'] == 'choice':
                options = question['criteria']
                answers[key] = {'type': 'choice', 'choice': 'earnings_release', 'confidence': .99,
                    'probabilities': {option: .99 if option == 'earnings_release' else .01 / (len(options) - 1)
                                      for option in options}}
            else:
                answers[key] = {'type': 'noul', 'noul': .95 if key == 'topic_financial_performance' else .05}
        return TransportResponse(200, json.dumps({'model': request['model'], 'answers': answers,
            'usage': {'input_tokens': 100, 'output_tokens': 20}}).encode())

    def factory(self, **arguments):
        return JudgeClient(**arguments, transport=self.response)

    def prepare(self, name='run'):
        return runner.prepare(self.preparation_ref, self.directory / name)

    def test_both_claimed_before_once_only_arms_and_read_only_verify_separates_quality(self):
        run_ref = self.prepare(); run = read(run_ref)
        self.assertEqual(set(run['claims']), {'baseline', 'candidate'})
        for packet_ref in run['worker_packets'].values():
            self.assertNotIn('expected_ref', json.dumps(read(packet_ref)))
            self.assertNotIn('topic_sets', json.dumps(read(packet_ref)))
        runner.run_arm(run_ref, 'baseline')
        report_ref = runner.run_arm(run_ref, 'candidate', client_factory=self.factory)
        self.assertEqual(len(self.calls), 8)
        self.assertEqual(read(report_ref)['usage']['model_calls'], 8)
        self.assertIsNone(read(report_ref)['cost'])
        with self.assertRaisesRegex(SourceError, 'LABEL_SCREEN_ALREADY_STARTED'):
            runner.run_arm(run_ref, 'candidate', client_factory=self.factory)
        with patch.object(runner, 'JudgeClient', side_effect=AssertionError('verification must not call')):
            verification = runner.verify(run_ref, expected_transport='injected')
        self.assertEqual(len(self.calls), 8)
        self.assertEqual(verification['integrity_status'], 'verified', verification)
        self.assertFalse(verification['semantic_all_cases_passed'])  # Baseline's absent hints abstain.
        self.assertEqual(verification['arms']['candidate']['semantic_status'], 'passed')
        self.assertEqual(verification['arms']['baseline']['semantic_status'], 'failed')
        with self.assertRaisesRegex(SourceError, 'LABEL_SCREEN_ALREADY_STARTED'):
            self.prepare()

    def test_unknown_auth_and_model_invalid_stop_after_one_and_retain_full_roster(self):
        def timeout(body, **limits):
            self.calls.append(body); raise JudgeError('JUDGE_TIMEOUT_UNKNOWN_OUTCOME')
        def auth(body, **limits):
            self.calls.append(body); return TransportResponse(401, b'fixture')
        def model(body, **limits):
            result = self.response(body, **limits); value = json.loads(result.body)
            value['model'] = 'wrong-model'
            return TransportResponse(200, json.dumps(value).encode())
        for index, transport in enumerate((timeout, auth, model)):
            with self.subTest(index=index):
                self.calls = []; run_ref = self.prepare('failure-' + str(index))
                runner.run_arm(run_ref, 'baseline')
                factory = lambda **arguments: JudgeClient(**arguments, transport=transport)
                report = read(runner.run_arm(run_ref, 'candidate', client_factory=factory))
                self.assertEqual(len(self.calls), 1); self.assertEqual(len(report['cases']), 8)
                statuses = [read(row['output_ref'])['transport_status'] for row in report['cases']]
                self.assertEqual(statuses, ['error'] + ['not_dispatched'] * 7)
                verification = runner.verify(run_ref, expected_transport='injected')
                self.assertEqual(verification['integrity_status'], 'verified', verification)
                self.assertEqual(verification['arms']['candidate']['transport_failures'], 8)
                self.assertEqual(report['usage']['model_calls'], 1)

    def test_disabled_is_unavailable_not_abstained_and_corruption_fails_readback(self):
        run_ref = self.prepare(); runner.run_arm(run_ref, 'baseline')
        report_ref = runner.run_arm(run_ref, 'candidate')  # No opt-in, no transport/key access.
        report = read(report_ref); self.assertEqual(report['usage']['model_calls'], 0)
        statuses = [read(row['output_ref'])['transport_status'] for row in report['cases']]
        self.assertEqual(statuses, ['disabled'] + ['not_dispatched'] * 7)
        self.assertEqual(runner.verify(run_ref)['integrity_status'], 'verified')
        Path(report['summary_ref']['path']).write_text('{}')
        verification = runner.verify(run_ref)
        self.assertEqual(verification['integrity_status'], 'failed')
        self.assertEqual(verification['integrity_errors'][0]['code'], 'ARTIFACT_HASH_MISMATCH')


if __name__ == '__main__':
    unittest.main()
