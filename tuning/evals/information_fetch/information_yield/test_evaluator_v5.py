import unittest
from investment.research.acquisition_eiy_checker_v5 import FreshEiyEvaluationV5,FreshEiyFactV5,_CONTEXT_TOKEN,_FACT_TOKEN
from shared.research_sources.information_yield_v5_contracts import digest_v5
from ._v5_support import build_v5_batch,mutate_fresh_v5
from .evaluator_v5 import InformationYieldV5Error,evaluate_fresh_eiy_evaluation_v5,evaluate_fresh_now_evaluation_v5
from .policy_v5 import GATE_RECORD_FIELDS_V5
class EvaluatorV5Tests(unittest.TestCase):
 def test_nominal_six_c_one_d_exact_gates_pass(self):
  _f,fresh,_,_=build_v5_batch(self);result=evaluate_fresh_eiy_evaluation_v5(fresh_evaluation=fresh).to_audit_mapping();self.assertEqual(result['verdict'],'pass');self.assertEqual(result['counts'],{'planned':7,'C':6,'D':1});self.assertEqual([g['ordinal'] for g in result['policy_gates']],list(range(1,19)));self.assertTrue(all(set(g)==GATE_RECORD_FIELDS_V5 for g in result['policy_gates']));self.assertEqual([g['ordinal'] for g in result['policy_gates'] if g['decisive']],list(range(12,18)))
 def test_genuine_development_hard_failure_rejects_before_c_unknown(self):
  _f,fresh,_,_=build_v5_batch(self,development_hard_failure=True)
  def unknown(data):next(f for f in data['facts'] if f['split']=='untouched')['arms']['F']['precision'].update({'status':'unavailable','supported_numerator':None,'judged_denominator':None,'pooled_total':None,'unjudged_unknown_count':1})
  result=evaluate_fresh_eiy_evaluation_v5(fresh_evaluation=mutate_fresh_v5(fresh,unknown)).to_audit_mapping();self.assertEqual(result['verdict'],'reject');hard=next(g for g in result['policy_gates'] if g['name']=='zero_hard_failures');self.assertEqual((hard['status'],hard['population'],len(hard['population_case_ids'])),('fail','E',7));self.assertEqual(next(g for g in result['policy_gates'] if g['name']=='precision_delta')['status'],'unknown')
 def test_seven_facts_six_bindings_fixed_fails_before_verdict(self):
  _f,fresh,_,_=build_v5_batch(self);data=fresh.to_audit_mapping();data['context']['fact_bindings'].pop();data['context']['fact_set_sha256']=digest_v5(data['context']['fact_bindings']);facts=[FreshEiyFactV5(f,_FACT_TOKEN) for f in data['facts']];bad=FreshEiyEvaluationV5(data['context'],facts,data['policy'],data['evaluation_ref'],data['custody_ref'],fresh.input_paths,_CONTEXT_TOKEN)
  with self.assertRaisesRegex(InformationYieldV5Error,'ACQ_EIY_V5_FACT_SET_MISMATCH'):evaluate_fresh_eiy_evaluation_v5(fresh_evaluation=bad)
 def test_population_corruption_and_self_issued_fixed_fail(self):
  _f,fresh,_,_=build_v5_batch(self);bad=mutate_fresh_v5(fresh,lambda d:d['context']['populations']['E'].pop())
  with self.assertRaisesRegex(InformationYieldV5Error,'EIY_V5_GATE_POPULATION'):evaluate_fresh_eiy_evaluation_v5(fresh_evaluation=bad)
  with self.assertRaisesRegex(InformationYieldV5Error,'EIY_V5_EVALUATION_CONTEXT_REQUIRED'):evaluate_fresh_eiy_evaluation_v5(fresh_evaluation={'facts':[]})
 def test_now_is_n_only_and_cannot_enter_evaluation(self):
  _f,fresh,_,_=build_v5_batch(self,confirmation=0,development=0,mode='now_diagnostic');self.assertEqual(evaluate_fresh_now_evaluation_v5(fresh_evaluation=fresh).to_audit_mapping()['population_N'],['case-1'])
  with self.assertRaisesRegex(InformationYieldV5Error,'ACQ_EIY_V5_NOW_BOUNDARY'):evaluate_fresh_eiy_evaluation_v5(fresh_evaluation=fresh)
if __name__=='__main__':unittest.main()
