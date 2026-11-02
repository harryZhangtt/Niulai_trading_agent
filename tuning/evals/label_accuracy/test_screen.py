"""Review/packet/normalizer conformance; no Jev or other network invocation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared.research_sources.artifacts import ROOT, SOURCE_STATE, SourceError, read, save
from tuning.evals.label_accuracy import grade, screen


class ScreenTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.manifest = {'schema_version': 1, 'id': 'synthetic-reviewed-label-screen', 'version': '1.0.0',
            'cutoff': '2026-11-01T15:59:29Z', 'taxonomy_path': 'investment/research/information-taxonomy.json',
            'label_schema_path': 'investment/research/information-labels.schema.json',
            'candidate_policy': {'min_probability': .6, 'min_margin': .1},
            'proposed_equal_per_arm_budget': {'model_calls': 8, 'wall_seconds': 1000}, 'cases': []}
        for index in range(8):
            text = ('Synthetic source passage ' + str(index) + '.').encode()
            ref = save(self.directory, text, suffix='txt')
            source = save(self.directory, {'provider': 'synthetic', 'raw': ref, 'text': ref,
                'source_url': 'https://newsroom.servicenow.com/financial-results/fixture-' + str(index),
                'retrieved_at': '2026-10-31T00:00:00Z', 'available_at': '2026-10-31T00:00:00Z'})
            self.manifest['cases'].append({'id': 'case_' + str(index), 'source_ref': source,
                'source_group': 'source-' + str(index), 'start_character': 0, 'end_character': len(text),
                'chunk_sha256': ref['sha256'], 'critical': True, 'gold': {'document_types': ['earnings_release'],
                'topic_sets': [['financial.performance']], 'abstention_allowed': False}})
        self.manifest_path = self.directory / 'manifest.json'; self.review_path = self.directory / 'review.json'
        self.write_reviewed()

    def write_reviewed(self):
        self.manifest_path.write_text(json.dumps(self.manifest))
        self.review_path.write_text(json.dumps({'manifest_sha256': hashlib.sha256(self.manifest_path.read_bytes()).hexdigest(),
            'decision': 'approved', 'reviewer_id': 'synthetic-coordinator',
            'review_kind': 'coordinator_ai_development_review_not_human_gold'}))

    def prepare(self):
        return screen.prepare(self.manifest_path, self.review_path, self.directory / 'prepared')

    def test_reviewed_materialization_preserves_raw_taxonomy_and_gold_free_worker_packet(self):
        prepared = self.prepare(); spec = read(prepared['spec_ref'])
        self.assertEqual(prepared['taxonomy_ref']['sha256'], hashlib.sha256((ROOT / self.manifest['taxonomy_path']).read_bytes()).hexdigest())
        self.assertEqual(len(spec['cases']), 8)
        contract = grade.seal(prepared['spec_ref']['path'], {'baseline': 'b' * 64, 'candidate': 'a' * 64},
            self.directory / 'ledger', extra_grader_paths=screen.CLASSIFIER_SOURCES)
        packet = grade.worker_packet(contract)
        self.assertNotIn('expected_ref', json.dumps(packet))
        for case in packet['cases']:
            inputs = read(case['input_ref'])
            self.assertEqual(set(inputs), grade.INPUT_KEYS)
            self.assertNotIn('gold', inputs)

    def test_gold_review_hash_cutoff_and_chunk_are_checked_before_dispatch(self):
        self.manifest['cases'][0]['gold']['topic_sets'] = [[]]
        self.manifest_path.write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(SourceError, 'LABEL_GOLD_REVIEW_REQUIRED'):
            self.prepare()
        self.write_reviewed(); self.manifest['cases'][0]['chunk_sha256'] = '0' * 64; self.write_reviewed()
        with self.assertRaisesRegex(SourceError, 'LABEL_REVIEWED_CHUNK_CHANGED'):
            self.prepare()
        self.manifest['cases'][0]['chunk_sha256'] = read(self.manifest['cases'][0]['source_ref'])['text']['sha256']
        self.manifest['cutoff'] = '2020-01-01T00:00:00Z'; self.write_reviewed()
        with self.assertRaisesRegex(SourceError, 'LABEL_FUTURE_INPUT'):
            self.prepare()

    def test_baseline_only_emits_existing_hints_and_abstains_on_every_other_topic(self):
        inputs = read(self.prepare()['spec_ref'])['cases'][0]['input']
        result = screen.normalize_rules(inputs)
        self.assertEqual(result['document_type'], 'earnings_release')
        self.assertEqual(result['topics'], ['financial.performance'])
        self.assertEqual(set(result['topic_abstentions']), set(inputs['allowed_topics']) - {'financial.performance'})
        self.assertIsNone(result['document_probabilities']); self.assertIsNone(result['topic_probabilities'])
        self.assertIsNone(result['cost'])
        self.assertEqual(result['transport_status'], 'partial')

    def test_model_transport_failure_preserves_latency_and_does_not_become_abstention(self):
        inputs = read(self.prepare()['spec_ref'])['cases'][0]['input']
        receipt = save(self.directory, {'receipt': {'elapsed_seconds': 12, 'usage': None}})
        report = {'source_ref': inputs['source_ref'], 'taxonomy_sha256': inputs['taxonomy_ref']['sha256'],
            'status': 'error', 'reason': 'JUDGE_TIMEOUT_UNKNOWN_OUTCOME', 'evaluation_output': None,
            'judge_outcome_ref': receipt}
        output = screen.normalize_labeler_report(inputs, report)
        self.assertEqual(output['transport_status'], 'error'); self.assertEqual(output['latency_ms'], 12000)
        expected = {'document_types': ['earnings_release'], 'topic_sets': [['financial.performance']], 'abstention_allowed': True}
        result = grade.grade('case_0', inputs, expected, output)
        self.assertFalse(result['passed']); self.assertEqual(result['reasons'], ['LABEL_TRANSPORT_UNVERIFIED'])
        bad = {**report, 'taxonomy_sha256': '0' * 64}
        with self.assertRaisesRegex(SourceError, 'LABEL_REPORT_BINDING_MISMATCH'):
            screen.normalize_labeler_report(inputs, bad)


if __name__ == '__main__':
    unittest.main()
