"""Source label adapter fixtures only; no live credentials or evaluation gold."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from investment.research import information_labels as labels
from investment.research.source_labeler import DOCUMENTS, VERSION, label_source
from shared.research_sources.artifacts import SOURCE_STATE, SourceError, read, save
from shared.typed_judge import DecisionPolicy, JudgeClient, TransportResponse


NOW = '2026-11-01T00:00:00Z'
CUTOFF = '2026-11-01T01:00:00Z'
FUTURE = '2026-12-01T00:00:00Z'


class SourceLabelerTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE/'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.calls = []
        self.source = self.make_source()

    def make_source(self, text='Synthetic issuer earnings statement; reported results and adoption claims are not independently verified.', **changes):
        return save(self.directory, {'provider': 'synthetic_capture', 'source_url': 'https://investor.servicenow.com/financial-results/synthetic',
            'upstream_id': 'synthetic-public-disclosure', 'source_version': 'synthetic-1',
            'access_level': 'document', 'retrieved_at': NOW, 'available_at': NOW,
            'raw': save(self.directory, text.encode(), suffix='raw'),
            'text': save(self.directory, text.encode(), suffix='txt'), **changes})

    def response(self, body, **limits):
        value = json.loads(body); self.calls.append(value)
        answers = {}
        for key, question in value['questions'].items():
            if question['type'] == 'choice':
                count = len(question['criteria'])
                answers[key] = {'type': 'choice', 'choice': 'earnings_release', 'confidence': .98,
                    'probabilities': {option: .99 if option == 'earnings_release' else .01/(count-1) for option in question['criteria']}}
            else:
                answers[key] = {'type': 'noul', 'noul': .95 if key in ('topic_financial_performance', 'topic_adoption') else .05}
        return TransportResponse(200, json.dumps({'model': value['model'], 'answers': answers,
            'usage': {'input_tokens': 1000, 'output_tokens': 30}}).encode())

    def run_label(self, **changes):
        arguments = {'source_ref': self.source, 'cutoff': CUTOFF, 'directory': self.directory/'run',
            'client': JudgeClient('datasource-labels', transport=self.response), 'policy': DecisionPolicy(.8, .1)}
        return label_source(**{**arguments, **changes})

    def test_one_enum_plus_eleven_independent_topics_and_explicit_model_policy(self):
        result = self.run_label()
        self.assertEqual(result['status'], 'ok', result['reason'])
        self.assertEqual(len(self.calls), 1)
        questions = self.calls[0]['questions']
        self.assertEqual(len(questions), 12)
        self.assertEqual(set(questions['document_type']['criteria']), set(labels.SCHEMA['properties']['document_type']['enum']))
        self.assertEqual(sum(q['type'] == 'noul' for q in questions.values()), 11)
        output = result['evaluation_output']
        self.assertEqual(output['document_type'], 'earnings_release')
        self.assertEqual(set(output['topics']), {'financial.performance', 'adoption'})
        self.assertEqual(output['topic_abstentions'], [])
        self.assertAlmostEqual(output['topic_probabilities']['adoption'], .95)
        self.assertGreater(sum(output['topic_probabilities'].values()), 1)
        self.assertEqual(output['transport_status'], 'ok')
        self.assertIsNone(output['cost'])
        envelope = labels.read_sidecar(result['label_ref'])
        self.assertEqual(envelope['policy']['version'], VERSION)
        self.assertEqual(envelope['policy']['model_resolved'], 'jev-1.14.0')
        self.assertEqual(envelope['policy']['input_chunk_ref'], result['chunk_ref'])
        self.assertEqual(envelope['label']['annotation']['method'], 'model')
        self.assertEqual(envelope['label']['annotation']['status'], 'provisional')
        self.assertEqual(envelope['label']['publisher_kind'], 'issuer')
        self.assertEqual(envelope['label']['perspectives'], ['supplier'])
        self.assertEqual(envelope['label']['epistemic_status'], 'unknown')
        self.assertFalse(result['semantic_approval'])

    def test_abstentions_never_force_argmax_labels_or_negative_topics(self):
        result = self.run_label(policy=None)
        self.assertEqual(result['status'], 'abstained')
        output = result['evaluation_output']
        self.assertIsNone(output['document_type'])
        self.assertEqual(output['topics'], [])
        self.assertEqual(len(output['topic_abstentions']), 11)
        self.assertEqual(set(output['document_probabilities']), set(DOCUMENTS))
        envelope = labels.read_sidecar(result['label_ref'])
        self.assertEqual(envelope['label']['document_type'], 'unknown')
        self.assertEqual(envelope['label']['topics'], ['unclassified'])

    def test_exact_unicode_chunk_is_bound_and_only_that_chunk_is_sent(self):
        self.source = self.make_source('Synthetic prefix. 精确原文片段。 Synthetic suffix.')
        supplied = save(self.directory, '精确原文片段。'.encode(), suffix='txt')
        result = self.run_label(chunk_ref=supplied)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(read(result['chunk_ref'], json_value=False).decode(), '精确原文片段。')
        self.assertEqual(self.calls[0]['state'], {'passage': '精确原文片段。'})
        self.assertEqual(result['evaluation_output']['chunk_sha256'], supplied['sha256'])

    def test_default_chunk_is_bounded_first_twelve_thousand_characters(self):
        text = 'Synthetic source. ' * 1000
        result = self.run_label(source_ref=self.make_source(text))
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(self.calls[0]['state']['passage'], text[:12000])
        self.assertEqual(len(read(result['chunk_ref'], json_value=False).decode()), 12000)

    def test_changed_or_oversized_chunk_never_reaches_judge(self):
        for chunk in ('Synthetic paraphrase not in source.', 'x'*12001):
            with self.subTest(chunk_length=len(chunk)):
                result = self.run_label(chunk_ref=save(self.directory, chunk.encode(), suffix='txt'))
                self.assertEqual(result['status'], 'blocked')
                self.assertEqual(result['reason'], 'SOURCE_LABELER_CHUNK_NOT_EXACT')
                self.assertIsNone(result['judge_outcome_ref'])
        self.assertEqual(self.calls, [])

    def test_future_unknown_or_corrupt_source_never_reaches_model(self):
        for changes in ({'retrieved_at': FUTURE}, {'retrieved_at': None}):
            result = self.run_label(source_ref=self.make_source(**changes))
            self.assertEqual(result['status'], 'blocked')
            self.assertIsNone(result['evaluation_output'])
            self.assertIsNone(result['label_ref'])
        Path(read(self.source)['text']['path']).write_bytes(b'Synthetic corruption')
        result = self.run_label()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.calls, [])

    def test_disabled_or_error_is_not_a_semantic_abstention(self):
        result = self.run_label(client=JudgeClient('datasource-labels'))
        self.assertEqual(result['status'], 'disabled')
        self.assertIsNone(result['evaluation_output'])
        self.assertIsNone(result['label_ref'])
        bad = JudgeClient('datasource-labels', transport=lambda *a, **k: TransportResponse(401, b'Synthetic private error'))
        result = self.run_label(client=bad)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['reason'], 'JUDGE_AUTH_FAILED')
        self.assertIsNone(result['evaluation_output'])

    def test_malformed_policy_is_a_preserved_blocked_result_before_model_exposure(self):
        result = self.run_label(policy={'min_probability': .8})
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['reason'], 'SOURCE_LABELER_POLICY_INVALID')
        self.assertIsNone(result['question_schema_sha256'])
        self.assertIsNone(result['evaluation_output'])
        self.assertEqual(read(result['report_ref'])['reason'], 'SOURCE_LABELER_POLICY_INVALID')
        self.assertEqual(self.calls, [])
        self.assertIsNone(result['label_ref'])

    def test_optional_model_sidecar_failure_preserves_authoritative_result(self):
        with patch('investment.research.source_labeler.annotate_source', side_effect=RuntimeError('Synthetic private exception')):
            result = self.run_label()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(read(result['report_ref'])['status'], 'ok')
        self.assertIsNone(result['label_ref'])
        self.assertEqual(result['observation_warnings'], ['OPTIONAL_MODEL_LABEL_SIDECAR_FAILED'])
        self.assertNotIn('Synthetic private exception', json.dumps(result))

    def test_post_judge_source_corruption_blocks_publication_but_keeps_attempt(self):
        def transport(body, **limits):
            response = self.response(body, **limits)
            Path(read(self.source)['text']['path']).write_bytes(b'Synthetic post-judge corruption')
            return response
        result = self.run_label(client=JudgeClient('datasource-labels', transport=transport))
        self.assertEqual(result['status'], 'error')
        self.assertIsNotNone(result['judge_outcome_ref'])
        self.assertIsNone(result['evaluation_output'])
        self.assertIsNone(result['label_ref'])

    def test_default_rule_policy_is_preserved_and_explicit_policy_requires_matching_version(self):
        ordinary = labels.annotate_source(self.source, self.directory/'rule')
        envelope = labels.read_sidecar(ordinary)
        self.assertEqual(envelope['policy'], labels.POLICY)
        self.assertEqual(envelope['policy_sha256'], labels.POLICY_SHA256)
        label = labels.classify(read(self.source), self.source)
        with self.assertRaisesRegex(SourceError, 'LABEL_POLICY_VERSION_MISMATCH'):
            labels.annotate_source(self.source, self.directory/'rule', label=label, policy={'version': 'some-other-policy'})


if __name__ == '__main__':
    unittest.main()
