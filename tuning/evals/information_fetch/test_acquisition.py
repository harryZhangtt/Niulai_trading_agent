"""Synthetic acquisition-gate integrity checks; no web or model is invoked."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from shared.research_sources.artifacts import SOURCE_STATE, SourceError, digest, read, save
from tuning.evals.evidence_runtime import contracts
from tuning.evals.information_fetch import acquisition as gate


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup); self.out = Path(self.tmp.name)
        self.raw = save(self.out, b'Synthetic issuer defines one managed asset as one subscription unit.', suffix='txt')
        self.source = save(self.out, {'raw': self.raw, 'text': self.raw, 'provider': 'synthetic',
            'retrieved_at': '2026-10-31T09:00:00Z', 'available_at': '2026-10-31T09:00:00Z'})
        self.frozen = {'cohort': 'cold', 'question_sha256': digest('same economic question'), 'baseline_sha256': digest([]),
            'cutoff': '2026-11-01T00:00:00Z', 'model_sha256': 'a' * 64, 'backend': 'synthetic-shared-backend',
            'arm_config_sha256': {'A': 'b' * 64, 'B': 'c' * 64}, 'cache_required_arms': ['A'],
            'worker_ids': ['worker-A', 'worker-B'], 'facets': ['meter', 'paid_conversion'],
            'resource_limits': {'search_items': 6, 'open_items': 6, 'provider_items': 12,
                                'wall_seconds': 600, 'tokens': None, 'cost': None}}
        self.key = {'entity': 'NOW', 'product': 'synthetic-control', 'metric': 'counted asset per subscription unit',
            'period': 'synthetic-effective-period', 'cohort': 'licensed assets', 'unit': 'asset per subscription unit',
            'currency': 'not_applicable', 'epistemic_status': 'contractual_definition', 'value_or_condition': 'one'}
        self.units = [save(self.out, {'source_ref': self.source, 'quote': read(self.raw, json_value=False).decode(),
            'wording': wording}) for wording in ['one wording', 'different wording of same unit', 'baseline wording']]
        self.a = self.make_run('A', self.units[:2]); self.b = self.make_run('B', self.units[2:])
        self.review = {'kind': 'acquisition_pooled_review', 'pool_run_refs': [self.a, self.b],
            'arm_labels_withheld': True, 'reviewer_id': 'independent-reviewer', 'units': [{
                'unit_ref': ref, 'status': 'judged', 'supported': True, 'economic_key': self.key,
                'facets': ['meter'], 'original_lineage': 'one-original-issuer-disclosure',
                'first_verified_available_at': None} for ref in self.units]}
        self.expected = {'prior_unit_ids': [], 'reference_unit_ids': [gate.canonical_id(self.key)]}

    def make_run(self, arm, units):
        execution = 'synthetic-' + arm
        response = save(self.out, b'Synthetic retained actual-operation response.', suffix='txt')
        refs = {}
        for kind in ['search', 'open']:
            receipt = {'kind': 'acquisition_operation_receipt', 'operation': kind, 'execution_id': execution,
                'backend': self.frozen['backend'], 'request_ref': save(self.out, {'items': [{'query': 'same question'}]}),
                'response_ref': response, 'source_sha256s': [self.source['sha256']],
                'started_at': '2026-10-31T10:00:00Z', 'finished_at': '2026-10-31T10:00:01Z'}
            refs[kind + '_receipt_refs'] = [save(self.out, receipt)]
        guard = save(self.out, {'kind': 'acquisition_worker_exposure', 'execution_id': execution,
            'cutoff': self.frozen['cutoff'], 'screened_at': '2026-10-31T10:00:02Z', 'exposed_source_refs': [self.source]})
        cache = save(self.out, {'fetch_key': {'provider': 'synthetic'}, 'fetch_executed': True, 'cache_hit': False,
            'route': 'fetch', 'source_ref': self.source, 'occurred_at': '2026-10-31T10:00:01Z'})
        run = {**{key: self.frozen[key] for key in ['cohort', 'question_sha256', 'baseline_sha256', 'cutoff', 'model_sha256', 'backend']},
            'kind': 'acquisition_eval_run', 'execution_id': execution, 'arm': arm,
            'config_sha256': self.frozen['arm_config_sha256'][arm], 'exposure_ref': guard,
            'started_at': '2026-10-31T10:00:00Z', 'finished_at': '2026-10-31T10:01:00Z',
            'first_worker_at': '2026-10-31T10:00:03Z', 'cache_attempt_refs': [cache] if arm == 'A' else [],
            'unit_refs': units, 'usage': {'provider_items': 2, 'tokens': None, 'cost': None}, **refs}
        return save(self.out, run)

    def grade(self, a=None, review=None):
        return gate.grade('NOW', self.frozen, self.expected,
            {'run_ref': a or self.a, 'review_ref': save(self.out, review or self.review)})

    def test_economic_dedup_counts_one_new_unit_not_two_wordings(self):
        result = self.grade(); self.assertTrue(result['passed']); metrics = result['metrics']
        self.assertEqual((metrics['proposed_units'], metrics['unique_new_units'], metrics['original_lineages']), (2, 1, 1))
        self.assertEqual(metrics['redundancy'], .5); self.assertEqual(metrics['facet_coverage'], .5)
        self.assertIsNone(metrics['detection_lag_seconds']); self.assertIsNone(metrics['cost'])
        self.expected['prior_unit_ids'] = [gate.canonical_id(self.key)]
        self.assertEqual(self.grade()['metrics']['unique_new_units'], 0)

    def test_same_packet_interpretation_without_search_open_cannot_pass(self):
        for missing in ['search_receipt_refs', 'open_receipt_refs']:
            run = read(self.a); run[missing] = []
            with self.subTest(missing=missing), self.assertRaisesRegex(SourceError, 'RECEIPTS_REQUIRED'):
                gate.validate_run(save(self.out, run), self.frozen)

    def test_native_find_and_search_metadata_cannot_supply_scored_units(self):
        for provider in ['native_web_find', 'native_web_search']:
            self.source = save(self.out, {**read(self.source), 'provider': provider, 'access_level': 'metadata'})
            self.units = [save(self.out, {'source_ref': self.source, 'quote': read(self.raw, json_value=False).decode()})]
            self.a = self.make_run('A', self.units); self.b = self.make_run('B', [])
            review = deepcopy(self.review); review['pool_run_refs'] = [self.a, self.b]
            review['units'] = [{**review['units'][0], 'unit_ref': self.units[0]}]
            with self.subTest(provider=provider), self.assertRaisesRegex(SourceError, 'ACQ_METADATA_UNIT_NOT_DOCUMENT'):
                self.grade(review=review)

    def test_claimed_cache_requires_actual_receipts_baseline_does_not(self):
        run = read(self.a); run['cache_attempt_refs'] = []
        with self.assertRaisesRegex(SourceError, 'ACQ_CACHE_RECEIPTS_REQUIRED'): gate.validate_run(save(self.out, run), self.frozen)
        gate.validate_run(self.b, self.frozen)

    def test_unjudged_in_either_arm_blocks_improvement_for_both(self):
        review = deepcopy(self.review); review['units'][-1]['status'] = 'unjudged'
        result = self.grade(review=review)
        self.assertFalse(result['passed']); self.assertIsNone(result['metrics']['unique_new_units'])
        self.assertEqual(result['metrics']['pool_unjudged_units'], 1)
        self.assertIn('ACQ_UNJUDGED_NOT_IMPROVEMENT', result['reasons'])

    def test_future_version_is_not_available_at_old_publication_date(self):
        future = save(self.out, {**read(self.source), 'published_at': '2025-01-01', 'modified_at': '2026-12-01T00:00:00Z'})
        run = read(self.b); guard = read(run['exposure_ref']); guard['exposed_source_refs'] = [future]
        run['exposure_ref'] = save(self.out, guard)
        with self.assertRaisesRegex(SourceError, 'ACQ_FUTURE_OR_UNVERIFIED_VERSION'):
            gate.validate_run(save(self.out, run), self.frozen)

    def test_date_only_metadata_keeps_exact_capture_bound_and_future_rejection(self):
        source = save(self.out, {**read(self.source), 'published_at': '2025-11-19', 'modified_at': '2026-09-28'})
        gate._source(source, self.frozen['cutoff'])
        future = save(self.out, {**read(source), 'modified_at': '2026-12-01'})
        with self.assertRaisesRegex(SourceError, 'ACQ_FUTURE_OR_UNVERIFIED_VERSION'):
            gate._source(future, self.frozen['cutoff'])
        malformed_capture = save(self.out, {**read(source), 'retrieved_at': '2026-10-31'})
        with self.assertRaisesRegex(SourceError, 'CHECK_TIME_INVALID'):
            gate._source(malformed_capture, self.frozen['cutoff'])

    def test_wrong_execution_and_post_worker_guard_rejected(self):
        run = read(self.a); run['search_receipt_refs'] = read(self.b)['search_receipt_refs']
        with self.assertRaisesRegex(SourceError, 'ACQ_OPERATION_BINDING'): gate.validate_run(save(self.out, run), self.frozen)
        run = read(self.a); run['first_worker_at'] = '2026-10-31T10:00:01Z'
        with self.assertRaisesRegex(SourceError, 'ACQ_BEFORE_WORKER_GUARD_REQUIRED'): gate.validate_run(save(self.out, run), self.frozen)

    def test_unknown_cost_cannot_satisfy_numeric_cost_limit(self):
        frozen = deepcopy(self.frozen); frozen['resource_limits']['cost'] = 1
        with self.assertRaisesRegex(SourceError, 'ACQ_BUDGET_OR_UNKNOWN_LIMIT'): gate.validate_run(self.a, frozen)

    def test_semantic_baseline_match_and_confirmation_are_not_new_information(self):
        self.frozen['novelty_labels_required'] = True
        self.expected['baseline_known_ids'] = ['old-meter']
        review = deepcopy(self.review)
        for check in review['units']:
            check.update(answer_bearing=True, novelty_kind='redundant', matched_old_ids=['old-meter'])
        result = self.grade(review=review)
        self.assertEqual(result['metrics']['unique_new_units'], 0)
        self.assertEqual(result['metrics']['known_units'], 1)
        for check in review['units']: check['novelty_kind'] = 'independent_confirmation'
        result = self.grade(review=review)
        self.assertEqual(result['metrics']['unique_new_units'], 0)
        self.assertEqual(result['metrics']['confirmation_units'], 1)
        for check in review['units']: check['novelty_kind'] = 'refinement'
        with self.assertRaisesRegex(SourceError, 'ACQ_DELTA_EXPLANATION_REQUIRED'):
            self.grade(review=review)

    def test_common_extraction_derivation_cannot_change_acquisition_or_invent_passages(self):
        original = {**read(self.a), 'unit_refs': []}
        original_ref = save(self.out, original)
        bound = gate.attach_units(original_ref, self.units[:1], self.out)
        gate.validate_run(bound, self.frozen)
        self.assertEqual(read(original_ref)['unit_refs'], [])
        changed = read(bound); changed['usage']['provider_items'] = 0
        with self.assertRaisesRegex(SourceError, 'ACQ_COLLECTION_DERIVATION_INVALID'):
            gate.validate_run(save(self.out, changed), self.frozen)
        invented = save(self.out, {'source_ref': self.source, 'quote': 'This fact is absent.'})
        with self.assertRaisesRegex(SourceError, 'ACQ_UNIT_QUOTE_INVALID'):
            gate.attach_units(original_ref, [invented], self.out)

    def test_existing_sealed_finish_records_interpretation_run_failure(self):
        run = read(self.a); run['search_receipt_refs'] = []; bad = save(self.out, run)
        output = save(self.out, {'run_ref': bad, 'review_ref': save(self.out, self.review)})
        spec = {'id': 'synthetic-acquisition', 'version': '1.0.0', 'split': 'development', 'blindness': 'answers_withheld',
            'cases': [{'id': 'NOW', 'input': self.frozen, 'expected': self.expected, 'critical': True}],
            'metrics': gate.METRICS, 'budget': {'provider_items': 12, 'wall_seconds': 600}}
        paths = ['tuning/evals/information_fetch/acquisition.py', 'tuning/evals/evidence_runtime/contracts.py']
        pins = {'candidate': 'a' * 64}; contract = contracts.seal(save(self.out, spec)['path'], paths, pins, self.out / 'ledger')
        contracts.begin(contract, self.out / 'ledger', 'one', arm='candidate', budget=spec['budget'], fingerprint=pins['candidate'])
        result_ref = gate.finish(contract, self.out / 'ledger', 'one', submissions=[{'id': 'NOW', 'output_ref': output}],
            usage={'provider_items': 2, 'wall_seconds': 60})
        result = read(result_ref); self.assertEqual(result['status'], 'failed')
        self.assertIn('ACQ_SEARCH_RECEIPTS_REQUIRED', result['errors'])


if __name__ == '__main__': unittest.main()
