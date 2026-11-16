import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from investment.research.information_yield_projection import ProjectionError, main, project
from shared.research_sources.artifacts import ROOT, digest, save
from tuning.evals.information_fetch.information_yield._v4_support import build_batch
from tuning.evals.information_fetch.information_yield.evaluator import evaluate_fresh_eiy_evaluation


class InformationYieldProjectionTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.research-sources/test-tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent, prefix='eiy-projection-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        _fixtures, evaluation, *_ = build_batch(self)
        self.result = evaluate_fresh_eiy_evaluation(fresh_evaluation=evaluation)
        self.result_ref = save(self.base / 'results', self.result)
        self.registry_ref = save(self.base / 'registry', {
            'schema_version': 1,
            'information_yield_results': [{'evaluation_id': self.result['evaluation_id'], 'result_ref': self.result_ref}],
        })

    def test_summary_is_bounded_vector_projection(self):
        value = project(self.registry_ref, self.result['evaluation_id'])
        self.assertEqual((value['view'], value['verdict']), ('summary', 'pass'))
        self.assertEqual(value['outcomes']['richness']['mean'], {'state': 'known', 'value': 1, 'unit': 'canonical_units'})
        self.assertEqual(value['outcomes']['depth']['mean'], {'state': 'known', 'value': 1, 'unit': 'field_state_steps'})
        public = json.dumps(value)
        for forbidden in ('"eiy"', 'alpha_score', 'private_path', 'raw_result', 'quote'):
            self.assertNotIn(forbidden, public)

    def test_exact_case_and_arm_detail_never_falls_back(self):
        case_id = self.result['confirmation_cases'][0]['case_id']
        value = project(self.registry_ref, self.result['evaluation_id'], case_id=case_id, arm='F')
        self.assertEqual(value['case']['case_id'], case_id)
        self.assertEqual(value['selection'], {'case_id': case_id, 'arm': 'F', 'run': None, 'source': None})
        self.assertEqual(value['selected_arm']['richness']['state'], 'known')
        with self.assertRaisesRegex(ProjectionError, 'EIY_PROJECTION_NOT_FOUND'):
            project(self.registry_ref, self.result['evaluation_id'], case_id='missing')
        with self.assertRaisesRegex(ProjectionError, 'EIY_PROJECTION_SELECTOR_INVALID'):
            project(self.registry_ref, self.result['evaluation_id'], arm='F')

    def test_unproved_run_and_source_are_not_invented(self):
        case_id = self.result['confirmation_cases'][0]['case_id']
        with self.assertRaisesRegex(ProjectionError, 'EIY_PROJECTION_NOT_FOUND'):
            project(self.registry_ref, self.result['evaluation_id'], case_id=case_id, arm='F', run='run-1')

    def test_registry_exact_lookup_hash_and_duplicate_contract(self):
        with self.assertRaisesRegex(ProjectionError, 'EIY_PROJECTION_NOT_FOUND'):
            project(self.registry_ref, 'missing')
        duplicate = save(self.base / 'registry2', {'schema_version': 1, 'information_yield_results': [
            {'evaluation_id': self.result['evaluation_id'], 'result_ref': self.result_ref},
            {'evaluation_id': self.result['evaluation_id'], 'result_ref': self.result_ref},
        ]})
        with self.assertRaisesRegex(ProjectionError, 'EIY_PROJECTION_REGISTRY_DUPLICATE'):
            project(duplicate, self.result['evaluation_id'])
        changed = dict(self.result_ref); changed['sha256'] = '0' * 64
        bad = save(self.base / 'registry3', {'schema_version': 1, 'information_yield_results': [
            {'evaluation_id': self.result['evaluation_id'], 'result_ref': changed}]})
        with self.assertRaisesRegex(ProjectionError, 'EIY_PROJECTION_RESULT_UNAVAILABLE'):
            project(bad, self.result['evaluation_id'])

    def test_hard_failure_and_unknown_are_preserved(self):
        result = json.loads(json.dumps(self.result)); result['verdict'] = 'reject'
        result['confirmation_cases'][0]['hard_failures'] = [{'code': 'TRACE_FAILURE', 'chain_ids': ['a' * 64]}]
        result['statistics']['depth']['mean'] = None
        signed = dict(result); signed.pop('summary_sha256'); result['summary_sha256'] = digest(signed)
        ref = save(self.base / 'results2', result)
        registry = save(self.base / 'registry4', {'schema_version': 1, 'information_yield_results': [
            {'evaluation_id': result['evaluation_id'], 'result_ref': ref}]})
        value = project(registry, result['evaluation_id'])
        self.assertEqual(value['hard_failures'][0]['code'], 'TRACE_FAILURE')
        self.assertEqual(value['outcomes']['depth']['mean']['state'], 'unavailable')

    def test_detail_failure_union_is_scoped_to_selected_case(self):
        result = json.loads(json.dumps(self.result)); result['verdict'] = 'reject'
        result['confirmation_cases'][0]['hard_failures'] = [{'code': 'TRACE_FAILURE', 'chain_ids': ['a' * 64]}]
        result['confirmation_cases'][1]['hard_failures'] = [{'code': 'SOURCE_MISMATCH', 'chain_ids': ['b' * 64]}]
        signed = dict(result); signed.pop('summary_sha256'); result['summary_sha256'] = digest(signed)
        ref = save(self.base / 'results-detail-failures', result)
        registry = save(self.base / 'registry-detail-failures', {'schema_version': 1, 'information_yield_results': [{'evaluation_id': result['evaluation_id'], 'result_ref': ref}]})
        case_id = result['confirmation_cases'][0]['case_id']; value = project(registry, result['evaluation_id'], case_id=case_id, arm='F')
        self.assertEqual(value['hard_failures'], [{'case_id': case_id, 'code': 'TRACE_FAILURE', 'chain_ids': ['a' * 64]}])

    def test_internal_summary_hash_conflict_is_rejected(self):
        result = json.loads(json.dumps(self.result)); result['verdict'] = 'reject'
        ref = save(self.base / 'results-summary-conflict', result)
        registry = save(self.base / 'registry-summary-conflict', {'schema_version': 1, 'information_yield_results': [
            {'evaluation_id': result['evaluation_id'], 'result_ref': ref}]})
        with self.assertRaisesRegex(ProjectionError, 'EIY_PROJECTION_SUMMARY_CONFLICT'):
            project(registry, result['evaluation_id'])

    def test_pass_with_hard_failures_is_rejected(self):
        result = json.loads(json.dumps(self.result)); result['verdict'] = 'pass'
        result['confirmation_cases'][0]['hard_failures'] = [{'code': 'TRACE_FAILURE', 'chain_ids': ['a' * 64]}]
        signed = dict(result); signed.pop('summary_sha256'); result['summary_sha256'] = digest(signed)
        ref = save(self.base / 'results-verdict-conflict', result)
        registry = save(self.base / 'registry-verdict-conflict', {'schema_version': 1, 'information_yield_results': [{'evaluation_id': result['evaluation_id'], 'result_ref': ref}]})
        with self.assertRaisesRegex(ProjectionError, 'EIY_PROJECTION_VERDICT_CONFLICT'): project(registry, result['evaluation_id'])

    def test_global_pass_failure_rejects_clean_detail_selector(self):
        result = json.loads(json.dumps(self.result)); result['verdict'] = 'pass'
        result['confirmation_cases'][0]['hard_failures'] = [{'code': 'TRACE_FAILURE', 'chain_ids': ['a' * 64]}]
        signed = dict(result); signed.pop('summary_sha256'); result['summary_sha256'] = digest(signed)
        ref = save(self.base / 'results-global-pass-conflict', result)
        registry = save(self.base / 'registry-global-pass-conflict', {'schema_version': 1, 'information_yield_results': [{'evaluation_id': result['evaluation_id'], 'result_ref': ref}]})
        clean_case = result['confirmation_cases'][1]['case_id']
        with self.assertRaisesRegex(ProjectionError, 'EIY_PROJECTION_VERDICT_CONFLICT'):
            project(registry, result['evaluation_id'], case_id=clean_case, arm='F')

    def test_global_inconclusive_failure_rejects_summary_and_clean_detail(self):
        result = json.loads(json.dumps(self.result)); result['verdict'] = 'inconclusive'
        result['confirmation_cases'][0]['hard_failures'] = [{'code': 'TRACE_FAILURE', 'chain_ids': ['a' * 64]}]
        signed = dict(result); signed.pop('summary_sha256'); result['summary_sha256'] = digest(signed)
        ref = save(self.base / 'results-global-inconclusive-conflict', result)
        registry = save(self.base / 'registry-global-inconclusive-conflict', {'schema_version': 1, 'information_yield_results': [{'evaluation_id': result['evaluation_id'], 'result_ref': ref}]})
        with self.assertRaisesRegex(ProjectionError, 'EIY_PROJECTION_VERDICT_CONFLICT'):
            project(registry, result['evaluation_id'])
        clean_case = result['confirmation_cases'][1]['case_id']
        with self.assertRaisesRegex(ProjectionError, 'EIY_PROJECTION_VERDICT_CONFLICT'):
            project(registry, result['evaluation_id'], case_id=clean_case, arm='F')

    def test_global_reject_persists_while_clean_detail_failures_are_scoped(self):
        result = json.loads(json.dumps(self.result)); result['verdict'] = 'reject'
        result['confirmation_cases'][0]['hard_failures'] = [{'code': 'TRACE_FAILURE', 'chain_ids': ['a' * 64]}]
        signed = dict(result); signed.pop('summary_sha256'); result['summary_sha256'] = digest(signed)
        ref = save(self.base / 'results-global-reject', result)
        registry = save(self.base / 'registry-global-reject', {'schema_version': 1, 'information_yield_results': [{'evaluation_id': result['evaluation_id'], 'result_ref': ref}]})
        clean_case = result['confirmation_cases'][1]['case_id']; value = project(registry, result['evaluation_id'], case_id=clean_case, arm='F')
        self.assertEqual(value['verdict'], 'reject'); self.assertEqual(value['hard_failures'], [])

    def test_nested_credentials_never_serialize(self):
        result = json.loads(json.dumps(self.result)); result['confirmation_cases'][0]['arms']['F']['trace']['credentials'] = {'auth_token': 'synthetic'}
        signed = dict(result); signed.pop('summary_sha256'); result['summary_sha256'] = digest(signed)
        ref = save(self.base / 'results-private', result)
        registry = save(self.base / 'registry-private', {'schema_version': 1, 'information_yield_results': [{'evaluation_id': result['evaluation_id'], 'result_ref': ref}]})
        with self.assertRaisesRegex(ProjectionError, 'EIY_PROJECTION_RESULT_INVALID|EIY_PROJECTION_PRIVATE_FIELD'): project(registry, result['evaluation_id'])

    def test_cli_has_fixed_codes_and_does_not_echo(self):
        out = StringIO()
        with redirect_stdout(out):
            code = main(['--registry-ref', json.dumps(self.registry_ref), '--evaluation-id', self.result['evaluation_id']])
        self.assertEqual(code, 0); self.assertEqual(json.loads(out.getvalue())['view'], 'summary')
        marker = 'github_pat_SYNTHETIC_PRIVATE_1234567890'; out = StringIO()
        with redirect_stdout(out): code = main([marker])
        self.assertEqual(code, 2); self.assertNotIn(marker, out.getvalue())


if __name__ == '__main__':
    unittest.main()
