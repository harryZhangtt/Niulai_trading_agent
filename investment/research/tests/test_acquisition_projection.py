"""Synthetic projection boundaries; no model/provider calls or research gold."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from shared.research_sources.artifacts import INVESTMENT_STATE, save, read
from investment.research import datasource as ds


class AcquisitionProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=INVESTMENT_STATE, prefix='test-acq-projection-')
        self.addCleanup(self.temp.cleanup); self.base = Path(self.temp.name)
        self.common = save(self.base, {'tasks': [{'id': 'TST_topic', 'question': 'What is supported?', 'required_answer_bearing_facets': ['one']} ]})
        self.contract = save(self.base, {'cases': [{'id': 'TST_workload'}]})
        body = save(self.base, b'Bound actual fixture quotation.', suffix='txt')
        self.source = save(self.base, {'provider': 'synthetic', 'source_url': 'https://example.com/public?token=SYNTHETIC_SECRET',
            'text': body, 'raw': body, 'access_level': 'document', 'retrieved_at': '2026-11-01T00:00:00Z', 'available_at': '2026-11-01T00:00:00Z'})
        self.metrics = {'unique_new_units': 1, 'supported_reference_coverage': 1.0, 'search_items': 6, 'open_items': 6, 'tokens': None}
        self.originals = {}; self.derived = {}; self.units = {}
        for arm in 'AB':
            operation = save(self.base, {'kind': 'acquisition_operation_receipt', 'execution_id': 'exec-' + arm, 'backend': 'synthetic'})
            config = save(self.base, {'arm': arm, 'execution_id': 'exec-' + arm, 'baseline_ref': self.common, 'backend': 'synthetic',
                'budget': {'search_items': 6}, 'question': 'TST secret=SYNTHETIC_SECRET /Users/private/file', 'cache_enabled': arm == 'A'})
            original = {'kind': 'acquisition_eval_run', 'arm': arm, 'execution_id': 'exec-' + arm, 'unit_refs': [],
                'baseline_sha256': self.common['sha256'], 'config_ref': config, 'config_sha256': config['sha256'],
                'question_sha256': 'a' * 64, 'model_sha256': 'b' * 64, 'backend': 'synthetic', 'cohort': 'cold',
                'cutoff': '2026-11-01T01:00:00Z', 'source_refs': [self.source], 'cache_attempt_refs': [],
                'search_receipt_refs': [operation], 'open_receipt_refs': [operation], 'status': 'completed'}
            self.originals[arm] = save(self.base, original)
            unit = save(self.base, {'id': 'D01_U1', 'source_ref': self.source, 'claim': 'Bound claim', 'quote': 'Bound actual fixture quotation.', 'arm_binding': arm})
            self.units[arm] = unit
            self.derived[arm] = save(self.base, {**original, 'unit_refs': [unit], 'origin_run_ref': self.originals[arm]})
        self.reviews = {}
        for order in ['forward', 'reverse']:
            rows = [{'id': 'D01_U1', 'doc_id': 'D01', 'unit_ref': ref, 'supported': True, 'answer_bearing': True,
                     'novelty_kind': 'new_fact', 'facets': ['TST_topic'], 'economic_key': {'epistemic_status': 'provisional', 'period': 'unknown', 'unit': 'unknown'},
                     'original_lineage': 'example', 'freshness_class': 'undated' if order == 'forward' else 'current_version',
                     'first_verified_available_at': None, 'limitations': []} for ref in self.units.values()]
            self.reviews[order] = save(self.base, {'kind': 'acquisition_pooled_review', 'arm_labels_withheld': True,
                'pool_run_refs': list(self.derived.values()), 'units': rows})
        results = {}
        for arm in 'AB':
            submission = save(self.base, {'run_ref': self.derived[arm], 'review_ref': self.reviews['forward'],
                'replicate_review_ref': self.reviews['reverse'], 'replicate_metrics_equal': True})
            results[arm] = save(self.base, {'arm': {'A': 'candidate', 'B': 'baseline'}[arm], 'contract_ref': self.contract, 'status': 'passed',
                'cases': [{'id': 'TST_workload', 'metrics': self.metrics, 'output_ref': submission}]})
        self.report = {'kind': 'controlled_acquisition_comparison', 'schema_version': 1, 'id': 'TST_acq', 'scope': 'one pair',
            'common_ref': self.common, 'contract_ref': self.contract, 'result_refs': results, 'review_refs': self.reviews,
            'original_run_refs': self.originals, 'primary_metrics': {arm: self.metrics for arm in 'AB'},
            'per_task_new_units': {arm: {'TST_topic': 1} for arm in 'AB'}, 'exploratory_sensitivity': {arm: {'excluding_explicitly_anonymous_reports': 1} for arm in 'AB'},
            'quality_limits': ['Not independent truth. /Users/private/file secret=SYNTHETIC_SECRET']}

    def project(self, report=None):
        return ds.acquisition_projection.project(ds.Reader(), save(self.base, report or self.report), 'TST', text=ds.text,
            identifier=ds.identifier, timestamp=ds.timestamp, sha=ds.sha, source_dto=ds.source_dto, numeric_metrics=ds.numeric_metrics, aggregate=ds.aggregate)

    def expanded_report(self, count, omit_review_hash=None):
        units = {arm: [save(self.base, {**read(self.units[arm]), 'id': 'D01_U' + str(index), 'binding_index': index})
                       for index in range(count)] for arm in 'AB'}
        derived = {arm: save(self.base, {**read(self.derived[arm]), 'unit_refs': refs}) for arm, refs in units.items()}
        reviews = {}
        for order, ref in self.reviews.items():
            value = read(ref); value['pool_run_refs'] = list(derived.values()); rows = []
            for arm in 'AB':
                template = next(row for row in value['units'] if row['unit_ref'] == self.units[arm])
                rows.extend({**template, 'id': read(unit)['id'], 'unit_ref': unit} for unit in units[arm]
                            if unit['sha256'] != omit_review_hash)
            value['units'] = rows; reviews[order] = save(self.base, value)
        results = {}
        for arm in 'AB':
            result = read(self.report['result_refs'][arm]); submission = read(result['cases'][0]['output_ref'])
            submission.update(run_ref=derived[arm], review_ref=reviews['forward'], replicate_review_ref=reviews['reverse'])
            result['cases'][0]['output_ref'] = save(self.base, submission); results[arm] = save(self.base, result)
        return {**self.report, 'review_refs': reviews, 'result_refs': results}, units

    def test_preview_bound_preserves_full_metrics_and_rejects_unpreviewed_roster_omission(self):
        report, units = self.expanded_report(9)
        value, _ = self.project(report)
        for collection in value['acquisition']['collections']:
            self.assertEqual(len(collection['units']), 8)
            self.assertEqual((collection['units_total'], collection['units_truncated']), (9, 1))
            self.assertEqual(collection['metrics'], self.metrics)
        self.assertEqual(value['acquisition']['reviews']['units_reviewed'], 18)
        incomplete, _ = self.expanded_report(9, omit_review_hash=units['B'][-1]['sha256'])
        with self.assertRaisesRegex(ValueError, 'ACQ_PROJECTION_POOL_BINDING_INVALID'): self.project(incomplete)

    def test_bound_result_collection_quote_and_denominators_are_sanitized(self):
        before = {p: p.stat().st_mtime_ns for p in self.base.iterdir()}
        value, sources = self.project()
        self.assertEqual(value['status'], 'qualified')
        self.assertEqual(value['acquisition']['collections'][0]['units'][0]['quote'], 'Bound actual fixture quotation.')
        self.assertEqual(value['acquisition']['reviews']['unique_observations'], 1)
        self.assertEqual(value['acquisition']['reviews']['units_reviewed'], 2)
        self.assertEqual(value['acquisition']['reviews']['unique_freshness_disagreements'], 1)
        self.assertEqual(value['acquisition']['reviews']['freshness_disagreements'], 2)
        self.assertIsNone(value['acquisition']['collections'][0]['metrics']['tokens'])
        public = json.dumps(value)
        for token in ['SYNTHETIC_SECRET', '/Users/', 'output_ref', 'raw_neutral_review_ref']: self.assertNotIn(token, public)
        self.assertIsNone(sources[0]['url'])
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in before})

    def test_mismatched_metrics_and_swapped_collection_bindings_fail_closed(self):
        wrong = json.loads(json.dumps(self.report)); wrong['primary_metrics']['A']['unique_new_units'] = 99
        with self.assertRaisesRegex(ValueError, 'ACQ_PROJECTION_METRIC_BINDING_INVALID'): self.project(wrong)
        wrong = {**self.report, 'original_run_refs': {'A': self.originals['B'], 'B': self.originals['A']}}
        with self.assertRaisesRegex(ValueError, 'ACQ_PROJECTION_COLLECTION_BINDING_INVALID'): self.project(wrong)

    def test_tampered_source_quote_and_unbounded_registry_are_rejected(self):
        unit = read(self.units['A']); altered = save(self.base, {**unit, 'quote': 'Invented quote'})
        derived = {**self.derived, 'A': save(self.base, {**read(self.derived['A']), 'unit_refs': [altered]})}
        reviews = {}
        for order, ref in self.reviews.items():
            value = read(ref); value['pool_run_refs'] = list(derived.values())
            for row in value['units']:
                if row['unit_ref'] == self.units['A']: row['unit_ref'] = altered
            reviews[order] = save(self.base, value)
        results = {}
        for arm in 'AB':
            result = read(self.report['result_refs'][arm]); submission = read(result['cases'][0]['output_ref'])
            submission.update(run_ref=derived[arm], review_ref=reviews['forward'], replicate_review_ref=reviews['reverse'])
            result['cases'][0]['output_ref'] = save(self.base, submission); results[arm] = save(self.base, result)
        with self.assertRaisesRegex(ValueError, 'ACQ_PROJECTION_QUOTE_INVALID'):
            self.project({**self.report, 'review_refs': reviews, 'result_refs': results})
        registry = save(self.base, {'acquisition_comparison_refs': [{}] * 5})
        with self.assertRaisesRegex(ValueError, 'PROJECTION_REGISTRY_LIMIT'): ds._registry(ds.Reader(), registry)


if __name__ == '__main__': unittest.main()
