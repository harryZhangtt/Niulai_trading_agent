"""Synthetic callbacks, real registered local read, and host validation faults."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from investment.research.datasource_query import CONFIG_PATH, FACETS, SUMMARY, OUTPUT_SCHEMA, run_query
from investment.research.execution import proposal_schema
from investment.research.information_labels import read_sidecar
from shared.research_sources.artifacts import SOURCE_STATE, read, save


CAPTURED = '2026-11-01T00:00:00Z'
CUTOFF = '2026-11-01T01:00:00Z'
FUTURE = '2026-12-01T00:00:00Z'


class DatasourceQueryTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.source = self.make_source()
        self.manifest = save(self.directory, {'study': 'explicit_synthetic_fixture', 'source_refs': {'S01': self.source}})
        row = {'record_id': 'known', 'entity': 'NOW', 'title': 'Synthetic old research question',
            'kind': 'evidence_note', 'content_access': 'secondary_note', 'source_family': 'synthetic',
            'available_at': '2026-01-01T00:00:00Z', 'content': {'note': 'Synthetic planning context only.'}}
        self.roster = save(self.directory, {'records': [row,
            {**row, 'record_id': 'future', 'title': 'FUTURE_PRIOR_ORACLE', 'available_at': FUTURE},
            {**row, 'record_id': 'unknown', 'title': 'UNKNOWN_PRIOR_ORACLE', 'available_at': None}]})
        self.prompts = []

    def make_source(self, **changes):
        text = changes.pop('fixture_text', 'Synthetic ServiceNow disclosure: this is an issuer statement, not independent evidence. ' * 8)
        raw = save(self.directory, text.encode(), suffix='txt')
        return save(self.directory, {'schema_version': 1, 'provider': 'native_open_primary_capture',
            'source_url': 'https://investor.servicenow.com/synthetic-disclosure',
            'upstream_id': 'https://investor.servicenow.com/synthetic-disclosure',
            'source_version': raw['sha256'], 'raw': raw, 'text': raw, 'access_level': 'document',
            'retrieved_at': CAPTURED, 'available_at': '2025-04-01T23:59:59Z',
            'published_at': '2025-04-01', 'modified_at': None,
            'availability_basis': 'issuer_dated_reconstruction',
            'capture_method': 'Explicit synthetic native-open fixture',
            'limitations': ['Explicit synthetic capture; no original historical provenance claim.'], **changes})

    def answer(self, prompt, schema):
        prompt = json.loads(prompt); self.prompts.append(prompt)
        inputs = prompt['inputs']
        quote = inputs['issued_read']['passage']['text'][:92]
        proposal = {'catalog_proposal': {'context_sha256': inputs['catalog_context_sha256'],
            'questions': [{'id': facet, 'facet': facet, 'question': 'What source evidence resolves this synthetic research need?',
                'why_needed': 'Synthetic ambiguity remains unresolved.', 'evidence_to_seek': 'Original scoped source observations.',
                'source_roles': ['issuer specification', 'customer operations'], 'capability_ids': ['web_search'],
                'depends_on': [], 'priority': 'required', 'stop_rule': 'Stop at the bounded question budget.'} for facet in FACETS],
            'expansion_reason': 'Initial bounded plan, not factual conclusions.'},
            'observations': [{'source_id': inputs['source']['source_id'], 'quote': quote, 'claim': quote,
                'epistemic_status': 'unknown', 'topics': ['business.model']}],
            'summary': SUMMARY, 'gaps': ['semantics_require_review', 'catalog_does_not_prove_coverage']}
        return {'kind': 'phase_result', 'call_id': 'catalog_done', 'action': None, 'arguments': None, 'data': proposal}

    def run_query(self, callback=None, **changes):
        arguments = {'source_manifest_ref': self.manifest, 'roster_ref': self.roster,
            'cutoff': CUTOFF, 'output_directory': self.directory / 'run', 'model_callback': callback or self.answer}
        return run_query(**{**arguments, **changes})

    def test_real_read_catalog_compilation_and_provisional_document_claim_sidecars(self):
        result = self.run_query()
        self.assertEqual(result['status'], 'completed', result.get('reason'))
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.prompts[0]['permitted_actions'], {})
        pipeline = read(result['pipeline_report_ref'])
        self.assertEqual(pipeline['counts'], {'actions': 1, 'model_turns': 1})
        self.assertEqual(pipeline['action_records'][0]['action'], 'evidence.read@1.1.1')
        self.assertTrue(read(pipeline['action_records'][0]['execution_ref'])['status'] == 'success')
        catalog = read(result['catalog_ref'])
        self.assertEqual({q['facet'] for q in catalog['proposal']['questions']}, set(FACETS))
        self.assertEqual(catalog['coverage_status'], 'not_fetched')
        self.assertEqual(len(result['label_refs']), 2)
        labels = [read_sidecar(ref)['label'] for ref in result['label_refs']]
        self.assertEqual({label['scope'] for label in labels}, {'document', 'claim'})
        self.assertTrue(all(label['annotation']['status'] == 'provisional' for label in labels))
        self.assertTrue(all(label['annotation']['review_ref'] is None for label in labels))
        self.assertEqual(read(result['report_ref'])['status'], 'completed')

    def test_normalization_preserves_original_bytes_times_and_only_one_worker_copy(self):
        result = self.run_query()
        normalized = read(result['source_refs'][0]); original = read(self.source)
        self.assertEqual(result['original_capture_ref'], self.source)
        for key in ('raw', 'text', 'source_version', 'retrieved_at', 'available_at', 'published_at', 'limitations'):
            self.assertEqual(normalized[key], original[key])
        self.assertEqual(normalized['metadata']['original_capture_ref'], self.source)
        self.assertEqual(normalized['metadata']['normalization'], 'read_schema_compatibility_only_no_new_acquisition')
        self.assertNotIn(self.source['sha256'], json.dumps(self.prompts[0]))
        diagnostic = read(result['temporal_diagnostic_ref'])
        original_row = next(row for row in diagnostic['sources'] if row['source_sha256'] == self.source['sha256'])
        self.assertFalse(original_row['worker_visible'])
        self.assertEqual(diagnostic['lineage']['independent_sources'], 1)

    def test_future_unknown_and_corrupt_probes_and_prior_oracles_stay_host_only(self):
        future = self.make_source(retrieved_at=FUTURE, available_at=FUTURE,
            metadata={'title': 'FUTURE_SOURCE_ORACLE'}, fixture_text='FUTURE_SOURCE_ORACLE')
        unknown = self.make_source(retrieved_at=None, metadata={'title': 'UNKNOWN_SOURCE_ORACLE'})
        damaged = self.make_source(upstream_id='synthetic-corrupt-probe', fixture_text='CORRUPT_SOURCE_ORACLE')
        Path(read(damaged)['text']['path']).write_bytes(b'Synthetic corrupt canary')
        result = self.run_query(probe_pins=[future, unknown, damaged])
        self.assertEqual(result['status'], 'completed', result.get('reason'))
        prompt = json.dumps(self.prompts[0])
        for oracle in ('FUTURE_SOURCE_ORACLE', 'UNKNOWN_SOURCE_ORACLE', 'CORRUPT_SOURCE_ORACLE',
                'FUTURE_PRIOR_ORACLE', 'UNKNOWN_PRIOR_ORACLE', 'quarantined_counts',
                future['sha256'], unknown['sha256'], damaged['sha256']):
            self.assertNotIn(oracle, prompt)
        rows = read(result['temporal_diagnostic_ref'])['sources']
        self.assertEqual(next(row for row in rows if row['source_sha256'] == unknown['sha256'])['status'], 'unknown')
        self.assertIn('ARTIFACT_HASH_MISMATCH', next(row for row in rows if row['source_sha256'] == damaged['sha256'])['reason_codes'])

    def test_future_original_blocks_before_action_and_model(self):
        source = self.make_source(retrieved_at=FUTURE)
        manifest = save(self.directory, {'source_refs': {'S01': source}})
        with patch('investment.research.execution.invoke') as action:
            result = self.run_query(source_manifest_ref=manifest)
            action.assert_not_called()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['reason'], 'TEMPORAL_SOURCE_UNAVAILABLE')
        self.assertEqual(self.prompts, [])
        self.assertEqual(read(result['temporal_diagnostic_ref'])['sources'][0]['status'], 'blocked')

    def test_unknown_original_never_gains_availability_from_old_publication_or_boolean(self):
        source = self.make_source(retrieved_at=None, historical_provenance_verified=True)
        result = self.run_query(source_manifest_ref=save(self.directory, {'source_refs': {'S01': source}}))
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.prompts, [])
        self.assertIsNone(result['catalog_ref'])

    def test_wrong_issuer_manifest_not_accepted_as_now_query(self):
        source = self.make_source(source_url='https://example.com/another-issuer', provider='official_document',
            truth_or_independence_certified=False)
        result = self.run_query(source_manifest_ref=save(self.directory, {'source_refs': {'S01': source}}))
        self.assertEqual(result['reason'], 'DATASOURCE_QUERY_NOW_SOURCE_REQUIRED')
        self.assertEqual(self.prompts, [])

    def test_unknown_source_output_rejected(self):
        def model(prompt, schema):
            response = self.answer(prompt, schema)
            response['data']['observations'][0]['source_id'] = 'f' * 64
            return response
        result = self.run_query(model)
        self.assertEqual(result['reason'], 'DATASOURCE_QUERY_SOURCE_UNKNOWN')
        self.assertIsNone(result['final_ref'])
        self.assertEqual(result['label_refs'], [])

    def test_future_model_memory_claim_or_quote_rejected(self):
        for fault in ('claim', 'quote'):
            with self.subTest(fault=fault):
                def model(prompt, schema):
                    response = self.answer(prompt, schema)
                    response['data']['observations'][0][fault] = 'Synthetic future-memory outcome 9999 absent from the issued source.'
                    return response
                result = self.run_query(model, output_directory=self.directory / ('run-' + fault))
                self.assertEqual(result['status'], 'blocked')
                self.assertEqual(result['reason'], 'DATASOURCE_QUERY_CLAIM_NOT_LITERAL' if fault == 'claim' else 'DATASOURCE_QUERY_QUOTE_NOT_ISSUED')
                self.assertIsNone(result['catalog_ref'])

    def test_closed_schema_rejects_forecast_field(self):
        def model(prompt, schema):
            response = self.answer(prompt, schema); response['data']['forecast'] = {'point': '9999'}
            return response
        result = self.run_query(model)
        self.assertEqual(result['reason'], 'DATASOURCE_QUERY_SCHEMA')
        self.assertIsNone(result['final_ref'])

    def test_transport_subset_omits_unique_items_but_host_rejects_duplicate_labels(self):
        phase = {'output_schema': OUTPUT_SCHEMA, 'permitted_actions': []}
        transport = proposal_schema(phase, {})
        self.assertNotIn('uniqueItems', json.dumps(transport))
        self.assertIn('uniqueItems', json.dumps(OUTPUT_SCHEMA))
        def model(prompt, schema):
            response = self.answer(prompt, schema)
            response['data']['observations'][0]['topics'] = ['business.model', 'business.model']
            return response
        result = self.run_query(model)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['reason'], 'DATASOURCE_QUERY_SCHEMA')
        self.assertIsNone(result['final_ref'])

    def test_missing_facet_or_stale_context_not_compiled_or_published(self):
        for fault in ('facet', 'context'):
            with self.subTest(fault=fault):
                def model(prompt, schema):
                    response = self.answer(prompt, schema)
                    if fault == 'facet': response['data']['catalog_proposal']['questions'].pop()
                    else: response['data']['catalog_proposal']['context_sha256'] = 'f' * 64
                    return response
                result = self.run_query(model, output_directory=self.directory / ('run-' + fault))
                self.assertEqual(result['status'], 'blocked')
                self.assertEqual(result['reason'], 'INFO_REQUIRED_FACET_MISSING' if fault == 'facet' else 'INFO_CONTEXT_STALE')
                self.assertIsNone(result['final_ref'])

    def test_optional_observer_failure_preserves_authoritative_success(self):
        def observer(ref):
            self.assertEqual(read(ref)['status'], 'completed')
            raise RuntimeError('Synthetic observer failure; raw exception must not escape.')
        result = self.run_query(observer=observer)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(read(result['report_ref'])['status'], 'completed')
        self.assertEqual(result['observation_warnings'], ['OPTIONAL_OBSERVABILITY_FAILED'])
        self.assertNotIn('Synthetic observer', json.dumps(result))

    def test_additional_model_action_is_rejected(self):
        def model(prompt, schema):
            return {'kind': 'call_action', 'call_id': 'future_fetch', 'action': 'evidence.acquire_document@1',
                'arguments': {}, 'data': None}
        result = self.run_query(model)
        self.assertEqual(result['reason'], 'DATASOURCE_QUERY_TOOL_FREE_REQUIRED')
        self.assertEqual(read(result['pipeline_report_ref'])['counts']['actions'], 1)

    def test_changed_recipe_cannot_add_an_acquisition_or_extra_model_turn(self):
        config = json.loads(CONFIG_PATH.read_text())
        config['phases'][0]['action'] = 'evidence.acquire_document@1'
        changed = self.directory / 'changed.pipeline.json'
        changed.write_text(json.dumps(config))
        with patch('investment.research.datasource_query.CONFIG_PATH', changed), \
                patch('investment.research.execution.invoke') as action:
            result = self.run_query()
            action.assert_not_called()
        self.assertEqual(result['reason'], 'DATASOURCE_QUERY_RECIPE_BOUNDARY')
        self.assertEqual(self.prompts, [])

    def test_mutated_source_after_read_not_published(self):
        def model(prompt, schema):
            response = self.answer(prompt, schema)
            Path(read(self.source)['text']['path']).write_bytes(b'Synthetic post-read corruption')
            return response
        result = self.run_query(model)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['reason'], 'TEMPORAL_SOURCE_UNAVAILABLE')
        self.assertIsNone(result['final_ref'])


if __name__ == '__main__':
    unittest.main()
