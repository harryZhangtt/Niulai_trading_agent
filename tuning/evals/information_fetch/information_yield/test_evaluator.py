import unittest
from ._v4_support import build_batch,mutate_evaluation
from investment.research.acquisition_eiy_checker import check_eiy_evaluation_v4
from investment.research.tests.test_acquisition_eiy_v3 import EiyV3Fixture
from shared.research_sources.artifacts import ROOT
from .contracts import InformationYieldError,digest
from .evaluator import evaluate_fresh_eiy_evaluation,evaluate_fresh_now_evaluation,evaluate_fresh_checked_facts
class EiyV4EvaluatorTests(unittest.TestCase):
 def test_exact_six_confirmation_passes_without_scalar(self):
  _fixtures,evaluation,_,_=build_batch(self);result=evaluate_fresh_eiy_evaluation(fresh_evaluation=evaluation);self.assertEqual(result['verdict'],'pass');self.assertEqual((result['statistics']['richness']['mean'],result['statistics']['depth']['mean']),(1,1));self.assertNotIn('eiy',result);self.assertNotIn('alpha',result);claimed=result['summary_sha256'];self.assertEqual(claimed,digest({k:v for k,v in result.items() if k!='summary_sha256'}))
 def test_one_development_plus_six_confirmation_is_noncompensating_and_ordered(self):
  _fixtures,evaluation,_,_=build_batch(self,confirmation=6,development=1,shuffle=True);result=evaluate_fresh_eiy_evaluation(fresh_evaluation=evaluation);self.assertEqual(result['counts'],{'planned':7,'confirmation':6,'development':1});self.assertEqual([r['case_id'] for r in result['development_cases']],['case-1']);self.assertEqual([r['case_id'] for r in result['confirmation_cases']],[f'case-{i}' for i in range(2,8)]);self.assertEqual(result['statistics']['richness']['denominator'],6);self.assertEqual(result['verdict'],'pass')
 def test_direct_v3_fact_lists_fixed_fail(self):
  with self.assertRaisesRegex(InformationYieldError,'EIY_V3_EVALUATION_CONTEXT_REQUIRED'):evaluate_fresh_checked_facts(fresh_facts=[])
 def test_changed_fact_and_context_hashes_fail_before_metrics(self):
  _fixtures,evaluation,_,_=build_batch(self);evaluation._facts[0]._value['issuer_id']='forged'
  with self.assertRaisesRegex(InformationYieldError,'EIY_FACT_DIGEST'):evaluate_fresh_eiy_evaluation(fresh_evaluation=evaluation)
  _fixtures,evaluation,_,_=build_batch(self);evaluation._context['context_sha256']='0'*64
  with self.assertRaisesRegex(InformationYieldError,'EIY_CONTEXT_DIGEST'):evaluate_fresh_eiy_evaluation(fresh_evaluation=evaluation)
 def test_inverse_now_boundary_fixed_fails_both_directions(self):
  row={'case_id':'case-1','issuer_id':'ISSUER-1','subject':'NOW','window_id':'2026Q1','cutoff':'2026-01-01T00:00:00Z','evidence_level':'diagnostic','split':'diagnostic','arm_order':['B0','F']};f=EiyV3Fixture(self,mode='now_diagnostic',subject='NOW',all_case_rows=[row],all_case_ids=['case-1'],evidence_level='diagnostic',split='diagnostic');custody,_=f.batch();now_evaluation=check_eiy_evaluation_v4(custody,read_ref=f.read_ref,workspace_root=ROOT)
  with self.assertRaisesRegex(InformationYieldError,'EIY_NOW_CONFIRMATION_FORBIDDEN'):evaluate_fresh_eiy_evaluation(fresh_evaluation=now_evaluation)
  _fixtures,normal,_,_=build_batch(self)
  with self.assertRaisesRegex(InformationYieldError,'EIY_NOW_BOUNDARY'):evaluate_fresh_now_evaluation(fresh_evaluation=normal)
 def test_known_improvement_miss_is_inconclusive(self):
  _fixtures,evaluation,_,_=build_batch(self);changed=mutate_evaluation(evaluation,lambda d:[fact['arms']['F'].update({'canonical_units':[]}) for fact in d['facts']]);self.assertEqual(evaluate_fresh_eiy_evaluation(fresh_evaluation=changed)['verdict'],'inconclusive')
if __name__=='__main__':unittest.main()
