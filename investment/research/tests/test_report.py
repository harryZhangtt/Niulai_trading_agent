import tempfile
from pathlib import Path
import unittest
from shared.research_sources.artifacts import SOURCE_STATE, read, save
from investment.research.report import export_run, render


class ReportTests(unittest.TestCase):
    def directory(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def test_projection_keeps_status_separate_and_escapes_source_text(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as tmp:
            directory = Path(tmp)
            report = {'schema_version': 1, 'pipeline_id': '<script>alert(1)</script>', 'pipeline_version': '0.1.0',
                      'status': 'blocked', 'reason': 'Missing critical input', 'completion_scope': 'component',
                      'phases': {'compare': {'status': 'success', 'data': {'status': 'disagreement'}}},
                      'phase_refs': {}, 'counts': {'actions': 1, 'model_turns': 0}, 'events': [], 'input_manifest': {}}
            view = export_run(save(directory, report), output_directory=directory)
            self.assertEqual(read(view)['runtime_acceptance'], 'unverified')
            html = read(render(view, output_directory=directory), json_value=False).decode()
            self.assertNotIn('<script>', html)
            self.assertIn('&lt;script&gt;', html)
            self.assertIn('disagreement', html)
            self.assertIn('blocked', html)
            self.assertIn('<summary>Receipts</summary>', html)

    def test_replay_binds_configuration_calls_evidence_and_recorded_findings(self):
        directory = self.directory()
        config = save(directory, {'phases': [
            {'id': 'compare', 'objective': 'Compare revenue in the same units', 'mode': 'action',
             'gate': 'action_success', 'action': 'evidence.compare_numeric@1'},
            {'id': 'interpret', 'objective': 'Explain the discrepancy', 'mode': 'agent',
             'gate': 'structured_output', 'permitted_actions': ['evidence.read@1']}]})
        source = save(directory, {'provider': 'official_document', 'access_level': 'document',
            'source_url': 'https://nvidianews.nvidia.com/news/results?token=DO_NOT_EXPOSE',
            'retrieved_at': '2026-10-31T01:00:00Z', 'available_at': '2026-10-31T01:00:00Z',
            'availability_basis': 'first_observed', 'raw': save(directory, b'public original', suffix='html')})
        request = save(directory, {'source_ref': source, 'acquisition': {'mode': 'cached_source'},
                                  'api_key': 'UNSAFE_REQUEST_SECRET', 'prompt': 'UNSAFE_PRIVATE_PROMPT'})
        execution = save(directory, {'status': 'success', 'action_id': 'evidence.compare_numeric',
            'started_at': '2026-10-31T01:00:01Z', 'finished_at': '2026-10-31T01:00:02Z',
            'duration_ms': 1000, 'release_sha256': 'a' * 64})
        report = {'schema_version': 1, 'run_id': 'test-execution-1', 'pipeline_id': 'earnings_query',
            'pipeline_version': '0.2.0', 'status': 'completed', 'completion_scope': 'reported_revenue',
            'started_at': '2026-10-31T01:00:00Z', 'finished_at': '2026-10-31T01:00:04Z',
            'input_manifest': {'config_ref': config, 'request_ref': request},
            'phases': {'compare': {'status': 'success', 'execution_ref': execution,
                                  'data': {'status': 'shared_upstream_corroboration'}},
                       'interpret': {'status': 'success', 'data': {'conclusion': 'Rounding explains the difference',
                           'explanation': 'These are two extractions from one issuer release.',
                           'unresolved_gaps': ['Independent source body remains unavailable'],
                           'raw_prompt': 'UNSAFE_PHASE_PROMPT'}}},
            'phase_refs': {}, 'counts': {'actions': 1, 'model_turns': 2, 'secret': 'UNSAFE_COUNT'},
            'action_records': [{'call_id': 'compare:direct', 'action': 'evidence.compare_numeric@1',
                                'execution_ref': execution}],
            'events': [{'event_type': 'phase_started', 'phase_id': 'compare', 'occurred_at': '2026-10-31T01:00:01Z'},
                       {'event_type': 'action_started', 'call_id': 'compare:direct', 'action': 'evidence.compare_numeric@1', 'prompt': 'UNSAFE_EVENT'},
                       {'event_type': 'phase_accepted', 'phase_id': 'compare', 'occurred_at': '2026-10-31T01:00:02Z'}],
            'model_usage_observed': [{'input_tokens': 100, 'output_tokens': 20, 'secret': 'UNSAFE_USAGE'}, None]}
        view = read(export_run(save(directory, report), output_directory=directory))
        self.assertEqual(view['run_id'], 'test-execution-1')
        self.assertEqual(view['duration_ms'], 4000)
        self.assertEqual(view['phases'][0]['duration_ms'], 1000)
        self.assertEqual(view['actions'][0]['phase_id'], 'compare')
        self.assertEqual(view['actions'][0]['release_sha256'], 'a' * 64)
        self.assertEqual(view['evidence'][0]['acquisition'], 'cached_source')
        self.assertNotIn('?', view['evidence'][0]['source_url'])
        markup = read(render(save(directory, view), output_directory=directory), json_value=False).decode()
        for expected in ('Configured phases', 'evidence.compare_numeric@1', 'Rounding explains the difference',
                         'Independent source body remains unavailable', 'Reused an explicit cached source',
                         'Attempt timeline (3 recorded events)', 'input tokens 100', 'Token usage not recorded'):
            self.assertIn(expected, markup)
        for excluded in ('UNSAFE_', 'DO_NOT_EXPOSE', 'raw_prompt', str(directory)):
            self.assertNotIn(excluded, markup)
        self.assertNotIn('UNSAFE_', str(view))
        self.assertEqual(view['runtime_acceptance'], 'unverified')

    def test_blocked_run_retains_unrun_phases_and_missing_receipt_warning(self):
        directory = self.directory()
        config = save(directory, {'phases': [{'id': 'fetch', 'mode': 'action', 'action': 'evidence.acquire_document@1'},
                                           {'id': 'calculate', 'mode': 'action', 'action': 'evidence.compare_numeric@1'}]})
        missing = {'path': str(directory / 'absent.json'), 'sha256': 'a' * 64}
        report = {'schema_version': 1, 'pipeline_id': 'partial', 'pipeline_version': '1', 'status': 'blocked',
                  'reason': 'SOURCE_NOT_AVAILABLE', 'phases': {}, 'counts': {},
                  'input_manifest': {'config_ref': config, 'request_ref': missing},
                  'events': [{'event_type': 'phase_started', 'phase_id': 'fetch', 'occurred_at': '2026-10-31T01:00:01Z'}]}
        view = read(export_run(save(directory, report), output_directory=directory))
        self.assertEqual([p['completion'] for p in view['phases']], ['incomplete', 'not_run'])
        self.assertIsNone(view['phases'][0]['duration_ms'])
        self.assertEqual(len(view['warnings']), 1)
        markup = read(render(save(directory, view), output_directory=directory), json_value=False).decode()
        self.assertIn('SOURCE_NOT_AVAILABLE', markup)
        self.assertIn('Incomplete audit data', markup)
        self.assertIn('No source receipt was recorded. Evidence coverage is unknown.', markup)
        self.assertIn('not run', markup)

    def test_display_redacts_known_secret_forms_and_rejects_unsafe_source_url(self):
        directory = self.directory()
        source = save(directory, {'provider': 'official_document', 'source_url': 'javascript:alert(1)'})
        request = save(directory, {'source_ref': source})
        report = {'schema_version': 1, 'pipeline_id': 'test', 'pipeline_version': '1', 'status': 'blocked',
                  'reason': 'Authorization=synthetic-private Bearer synthetic-bearer',
                  'phases': {}, 'input_manifest': {'request_ref': request}, 'events': [], 'counts': {}}
        view = export_run(save(directory, report), output_directory=directory)
        markup = read(render(view, output_directory=directory), json_value=False).decode()
        self.assertNotIn('synthetic-private', markup)
        self.assertNotIn('synthetic-bearer', markup)
        self.assertNotIn('javascript:', markup)
        self.assertIn('[redacted]', markup)


if __name__ == '__main__':
    unittest.main()
