"""Synthetic evaluator faults, not label-model or generalization evidence."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from shared.research_sources.artifacts import SOURCE_STATE, SourceError, read, save
from tuning.evals.label_accuracy import grade as evaluator


class LabelAccuracyTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.chunk = save(self.directory, b'Synthetic reported sales 3; target sales 6.', suffix='txt')
        self.source = save(self.directory, {'provider': 'synthetic', 'raw': self.chunk, 'text': self.chunk,
            'retrieved_at': '2026-10-31T00:00:00Z', 'available_at': '2026-10-31T00:00:00Z'})
        self.taxonomy = save(self.directory, {'document_types': ['earnings_release', 'analyst_report'],
            'topics': ['financial.performance', 'business.model']})
        self.inputs = {'source_ref': self.source, 'chunk_ref': self.chunk, 'taxonomy_ref': self.taxonomy,
            'source_group': 'same-source-group', 'cutoff': '2026-11-01T00:00:00Z',
            'allowed_document_types': ['earnings_release', 'analyst_report'],
            'allowed_topics': ['financial.performance', 'business.model']}
        self.gold = {'document_types': ['earnings_release'], 'topic_sets': [['financial.performance']], 'abstention_allowed': False}
        self.output = {'transport_status': 'ok', 'source_sha256': self.source['sha256'], 'chunk_sha256': self.chunk['sha256'],
            'taxonomy_sha256': self.taxonomy['sha256'], 'document_type': 'earnings_release', 'topics': ['financial.performance'],
            'topic_abstentions': [], 'document_probabilities': {'earnings_release': .8, 'analyst_report': .2},
            'topic_probabilities': {'financial.performance': .7, 'business.model': .7}, 'latency_ms': 12, 'cost': None}
        self.pins = {'baseline': 'b' * 64, 'candidate': 'a' * 64}
        self.spec = {'id': 'synthetic-labels', 'version': '1.0.0', 'split': 'development', 'blindness': 'answers_withheld',
            'cases': [{'id': 'case_0', 'input': self.inputs, 'expected': self.gold, 'critical': True}],
            'metrics': evaluator.METRICS, 'budget': {'model_calls': 8, 'wall_seconds': 30}}

    def seal(self, spec=None):
        self.spec_ref = save(self.directory, spec or self.spec)
        return evaluator.seal(self.spec_ref['path'], self.pins, self.directory / 'ledger')

    def begin(self, contract):
        return evaluator.begin(contract, self.directory / 'ledger', 'candidate-one', arm='candidate',
            budget=self.spec['budget'], fingerprint=self.pins['candidate'])

    def finish(self, contract, *, submissions=None, usage=None):
        return evaluator.finish(contract, self.directory / 'ledger', 'candidate-one',
            submissions=submissions if submissions is not None else [{'id': 'case_0', 'output_ref': save(self.directory, self.output)}],
            usage=usage or {'model_calls': 1, 'wall_seconds': 1})

    def test_sealed_grade_worker_separation_and_probability_metrics(self):
        contract = self.seal(); self.begin(contract)
        packet = evaluator.worker_packet(contract)
        self.assertNotIn('expected_ref', json.dumps(packet)); self.assertNotIn('topic_sets', json.dumps(packet))
        result_ref = self.finish(contract); result = read(result_ref)
        self.assertEqual(result['status'], 'passed'); metrics = result['cases'][0]['metrics']
        self.assertAlmostEqual(metrics['document_brier'], .08)
        self.assertAlmostEqual(metrics['topic_brier'], .29)
        self.assertEqual(metrics['topic_exact_set'], 1)
        summary = evaluator.summarize(contract, result_ref)
        self.assertEqual(summary['document_macro_f1'], 1)
        self.assertEqual(summary['coverage'], 1); self.assertEqual(summary['source_groups'], 1)
        self.assertEqual(summary['probabilistic_and_usage']['cost'], {'mean': None, 'known': 0, 'unknown': 1})
        self.assertFalse(summary['superiority_established'])

    def test_omitted_case_and_exceeded_budget_are_terminal_failures(self):
        for omitted in [True, False]:
            with self.subTest(omitted=omitted), tempfile.TemporaryDirectory(dir=self.directory) as child:
                self.directory = Path(child); contract = self.seal(); self.begin(contract)
                result = read(self.finish(contract, submissions=[] if omitted else None,
                    usage={'model_calls': 9 if not omitted else 1, 'wall_seconds': 1}))
                self.assertEqual(result['status'], 'failed')
                self.assertIn('EVAL_CASE_ROSTER_MISMATCH' if omitted else 'EVAL_BUDGET_EXCEEDED', result['errors'])
                self.directory = Path(self.tmp.name)

    def test_changed_gold_and_output_source_mismatch_are_rejected(self):
        contract = self.seal(); self.begin(contract)
        spec = deepcopy(self.spec); spec['cases'][0]['expected']['document_types'] = ['analyst_report']
        Path(self.spec_ref['path']).write_text(json.dumps(spec))
        self.assertIn('EVAL_SOURCE_CHANGED', read(self.finish(contract))['errors'])
        self.directory = self.directory / 'mismatch'; self.directory.mkdir()
        contract = self.seal(); self.begin(contract); self.output['source_sha256'] = 'c' * 64
        result = read(self.finish(contract)); self.assertEqual(result['status'], 'failed')
        self.assertIn('LABEL_OUTPUT_SOURCE_MISMATCH', result['errors'])

    def test_future_chunk_mismatch_and_gold_leak_fail_before_dispatch(self):
        for change, code in [({'cutoff': '2026-01-01T00:00:00Z'}, 'LABEL_FUTURE_INPUT'),
                             ({'chunk_ref': save(self.directory, b'not in source', suffix='txt')}, 'LABEL_CHUNK_SOURCE_MISMATCH'),
                             ({'expected': self.gold}, 'LABEL_INPUT_SCHEMA')]:
            spec = deepcopy(self.spec); spec['cases'][0]['input'].update(change)
            with self.subTest(code=code), self.assertRaisesRegex(SourceError, code): self.seal(spec)

    def test_full_abstention_is_unknown_metric_not_perfect_accuracy(self):
        output = {**self.output, 'document_type': None, 'topics': [], 'topic_abstentions': self.inputs['allowed_topics']}
        verdict = evaluator.grade('case_0', self.inputs, self.gold, output)
        self.assertFalse(verdict['passed']); self.assertIsNone(verdict['metrics']['topic_f1'])
        self.assertIsNone(verdict['metrics']['document_accuracy']); self.assertEqual(verdict['metrics']['classified_count'], 0)
        self.gold['abstention_allowed'] = True
        self.assertTrue(evaluator.grade('case_0', self.inputs, self.gold, output)['passed'])

    def test_future_version_bounds_and_transport_failure_cannot_pass_as_abstention(self):
        for field in ['modified_at', 'updated_at', 'version_available_at']:
            source = save(self.directory, {**read(self.source), field: '2026-12-01T00:00:00Z'})
            inputs = {**self.inputs, 'source_ref': source}
            with self.subTest(field=field), self.assertRaisesRegex(SourceError, 'LABEL_FUTURE_INPUT'):
                evaluator._input(inputs)
        self.gold['abstention_allowed'] = True
        for status in ['disabled', 'error', None]:
            output = {**self.output, 'transport_status': status, 'document_type': None,
                'topics': [], 'topic_abstentions': self.inputs['allowed_topics']}
            verdict = evaluator.grade('case_0', self.inputs, self.gold, output)
            self.assertFalse(verdict['passed']); self.assertEqual(verdict['reasons'], ['LABEL_TRANSPORT_UNVERIFIED'])
            self.assertEqual(verdict['metrics']['latency_ms'], 12)
            self.assertTrue(all(value is None for key, value in verdict['metrics'].items() if key != 'latency_ms'))
        self.output = output; contract = self.seal(); self.begin(contract)
        summary = evaluator.summarize(contract, self.finish(contract))
        self.assertEqual(summary['transport_failures'], 1); self.assertIsNone(summary['document_accuracy'])

    def test_transport_error_reduces_full_coverage_and_retains_observed_failure_latency(self):
        spec = deepcopy(self.spec)
        spec['cases'].append({**deepcopy(spec['cases'][0]), 'id': 'case_1'})
        contract = self.seal(spec); self.begin(contract)
        failed = {**self.output, 'transport_status': 'error', 'latency_ms': 12000,
                  'document_type': None, 'topics': [], 'topic_abstentions': self.inputs['allowed_topics']}
        result = self.finish(contract, submissions=[{'id': 'case_0', 'output_ref': save(self.directory, self.output)},
            {'id': 'case_1', 'output_ref': save(self.directory, failed)}])
        summary = evaluator.summarize(contract, result)
        self.assertEqual(summary['coverage'], .5)
        self.assertEqual(summary['coverage_given_valid_transport'], 1)
        self.assertEqual(summary['semantic_abstentions'], 0)
        self.assertEqual(summary['unavailable_decisions'], 3)
        self.assertEqual(summary['document_completion_rate'], .5)
        self.assertEqual(summary['document_end_to_end_accuracy'], .5)
        self.assertEqual(summary['document_selective_accuracy'], 1)
        self.assertEqual(summary['probabilistic_and_usage']['latency_ms'], {'mean': 6006, 'known': 2, 'unknown': 0})

    def test_positive_hints_do_not_get_perfect_full_set_recall_from_abstaining(self):
        self.gold['topic_sets'] = [self.inputs['allowed_topics']]
        self.output.update(topic_abstentions=['business.model'], document_probabilities=None, topic_probabilities=None)
        contract = self.seal(); self.begin(contract)
        summary = evaluator.summarize(contract, self.finish(contract))
        self.assertEqual(summary['topic_micro_recall'], 1)  # Known-decision conditional metric.
        self.assertEqual(summary['emitted_tag_recall'], .5)
        self.assertEqual(summary['emitted_tag_exact_set_rate'], 0)
        self.assertEqual(summary['emitted_tag_counts']['missed_gold_positives'], 1)
        self.assertAlmostEqual(summary['coverage'], 2 / 3)
        self.assertEqual(summary['semantic_abstentions'], 1)

    def test_shared_probability_tolerance_preserves_rounding_without_renormalization(self):
        self.output['document_probabilities']['earnings_release'] = .8004
        evaluator.grade('case_0', self.inputs, self.gold, self.output)
        contract = self.seal(); self.begin(contract)
        summary = evaluator.summarize(contract, self.finish(contract))
        self.assertAlmostEqual(summary['document_probability_sum_deviation']['max'], .0004)
        self.assertFalse(summary['document_probability_sum_deviation']['renormalized'])
        self.output['document_probabilities']['earnings_release'] = .802
        with self.assertRaisesRegex(SourceError, 'LABEL_PROBABILITIES_NOT_NORMALIZED'):
            evaluator.grade('case_0', self.inputs, self.gold, self.output)
        wrong_winner = {**self.output, 'document_probabilities': {'earnings_release': .2, 'analyst_report': .8}}
        with self.assertRaisesRegex(SourceError, 'LABEL_DOCUMENT_NOT_ARGMAX'):
            evaluator.grade('case_0', self.inputs, self.gold, wrong_winner)

    def test_enum_probabilities_must_normalize_but_binary_topics_need_not(self):
        evaluator.grade('case_0', self.inputs, self.gold, self.output)
        output = {**self.output, 'document_probabilities': {'earnings_release': .7, 'analyst_report': .7}}
        with self.assertRaisesRegex(SourceError, 'LABEL_PROBABILITIES_NOT_NORMALIZED'):
            evaluator.grade('case_0', self.inputs, self.gold, output)

    def test_changed_grader_dependency_fails_the_frozen_closure(self):
        dependency = self.directory / 'synthetic_dependency.py'; dependency.write_text('VERSION = 1\n')
        self.spec_ref = save(self.directory, self.spec)
        contract = evaluator.seal(self.spec_ref['path'], self.pins, self.directory / 'ledger',
            extra_grader_paths=[str(dependency)])
        self.begin(contract); dependency.write_text('VERSION = 2\n')
        result = read(self.finish(contract))
        self.assertEqual(result['status'], 'failed'); self.assertIn('EVAL_SOURCE_CHANGED', result['errors'])

    def test_unknown_attempt_and_failed_attempt_cannot_be_overwritten_or_rebegun(self):
        contract = self.seal(); claim_ref = self.begin(contract)
        unknown = evaluator.record_unknown(claim_ref, self.directory)
        self.assertEqual(read(unknown)['status'], 'unknown'); self.assertFalse(read(unknown)['replay_allowed'])
        with self.assertRaisesRegex(SourceError, 'EVAL_ATTEMPT_EXISTS'): self.begin(contract)
        result = self.finish(contract)
        self.assertEqual(read(result)['status'], 'passed')
        with self.assertRaisesRegex(SourceError, 'EVAL_ATTEMPT_FINISHED'): self.finish(contract)


if __name__ == '__main__': unittest.main()
