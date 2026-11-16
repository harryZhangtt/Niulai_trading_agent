import unittest
from ._v4_support import build_batch,mutate_evaluation
from .evaluator import evaluate_fresh_eiy_evaluation,compute_policy_gates_v4
class PolicyGateV4Tests(unittest.TestCase):
 def base(self):
  fixtures,evaluation,_,_=build_batch(self);return fixtures,evaluation
 def gates(self,evaluation):
  data=evaluation.to_audit_mapping();return {g['name']:g for g in compute_policy_gates_v4(policy=data['policy'],facts=data['facts'],context=data['context'])['gates']}
 def test_all_frozen_gates_pass_nominal(self):
  _fixtures,evaluation=self.base();result=evaluate_fresh_eiy_evaluation(fresh_evaluation=evaluation);self.assertEqual(result['verdict'],'pass');names={g['name'] for g in result['policy_gates']};self.assertEqual(names,{'confirmation_cohort','richness_mean','richness_positive_cases','depth_mean','depth_positive_cases','case_delta_floor','issuer_loo','precision_delta','arm_wall_limit','case_wall_ratio','aggregate_wall_ratio','complete_trace_ratio','complete_pooled_review','zero_critical_unsupported','lineage','execution_custody','zero_hard_failures','unknown_semantics'})
 def test_precision_boundary_and_unknown(self):
  _f,e=self.base();g=self.gates(e);self.assertEqual(g['precision_delta']['status'],'pass')
  unknown=mutate_evaluation(e,lambda d:d['facts'][0]['arms']['F']['precision'].update({'status':'unavailable','supported_numerator':None,'judged_denominator':None,'pooled_total':None,'unjudged_unknown_count':1}));self.assertEqual(self.gates(unknown)['precision_delta']['status'],'unknown');self.assertEqual(evaluate_fresh_eiy_evaluation(fresh_evaluation=unknown)['verdict'],'inconclusive')
 def test_precision_exact_threshold_and_below(self):
  _f,e=self.base()
  def precision(d,supported):
   for fact in d['facts']:
    fact['arms']['B0']['precision'].update({'status':'known','supported_numerator':20,'judged_denominator':20,'pooled_total':20,'unjudged_unknown_count':0});fact['arms']['F']['precision'].update({'status':'known','supported_numerator':supported,'judged_denominator':20,'pooled_total':20,'unjudged_unknown_count':0})
  at=mutate_evaluation(e,lambda d:precision(d,19));self.assertEqual(self.gates(at)['precision_delta']['status'],'pass')
  below=mutate_evaluation(e,lambda d:precision(d,18));self.assertEqual(self.gates(below)['precision_delta']['status'],'fail')
  zero=mutate_evaluation(e,lambda d:d['facts'][0]['arms']['F']['precision'].update({'judged_denominator':0,'pooled_total':0,'supported_numerator':0}));self.assertEqual(self.gates(zero)['precision_delta']['status'],'unknown')
 def test_wall_boundaries_and_unknowns(self):
  _f,e=self.base();at=mutate_evaluation(e,lambda d:[fact['arms'][a]['execution']['deadlines'].update({'observed_wall_seconds':600}) for fact in d['facts'] for a in ('B0','F')]);self.assertEqual(self.gates(at)['arm_wall_limit']['status'],'pass')
  over=mutate_evaluation(e,lambda d:d['facts'][0]['arms']['F']['execution']['deadlines'].update({'observed_wall_seconds':601}));self.assertEqual(self.gates(over)['arm_wall_limit']['status'],'fail')
  ratio=mutate_evaluation(e,lambda d:d['facts'][0]['arms']['F']['execution']['deadlines'].update({'observed_wall_seconds':8}));self.assertEqual(self.gates(ratio)['case_wall_ratio']['status'],'fail')
  aggregate_at=mutate_evaluation(e,lambda d:[fact['arms'][a]['execution']['deadlines'].update({'observed_wall_seconds':4 if a=='B0' else 5}) for fact in d['facts'] for a in ('B0','F')]);self.assertEqual(self.gates(aggregate_at)['aggregate_wall_ratio']['status'],'pass')
  aggregate_over=mutate_evaluation(e,lambda d:[fact['arms'][a]['execution']['deadlines'].update({'observed_wall_seconds':4 if a=='B0' else 5.01}) for fact in d['facts'] for a in ('B0','F')]);self.assertEqual(self.gates(aggregate_over)['aggregate_wall_ratio']['status'],'fail')
  case_at=mutate_evaluation(e,lambda d:d['facts'][0]['arms']['F']['execution']['deadlines'].update({'observed_wall_seconds':7.5}));self.assertEqual(self.gates(case_at)['case_wall_ratio']['case_results'][0]['ratio'],1.5)
  unknown=mutate_evaluation(e,lambda d:d['facts'][0]['arms']['B0']['execution']['deadlines'].update({'observed_wall_seconds':0}));self.assertEqual(self.gates(unknown)['aggregate_wall_ratio']['status'],'unknown')
 def test_trace_pooled_review_and_zero_denominators(self):
  _f,e=self.base();self.assertEqual(self.gates(e)['complete_trace_ratio']['status'],'pass')
  bad=mutate_evaluation(e,lambda d:d['facts'][0]['arms']['F']['trace_accounting'].update({'complete_chains':0}));self.assertEqual(self.gates(bad)['complete_trace_ratio']['status'],'fail')
  unknown=mutate_evaluation(e,lambda d:d['facts'][0]['arms']['F']['trace_accounting'].update({'unjudged_units':1}));self.assertEqual(self.gates(unknown)['complete_trace_ratio']['status'],'unknown');self.assertEqual(self.gates(unknown)['complete_pooled_review']['status'],'fail')
 def test_critical_lineage_and_hard_failure_precedence(self):
  _f,e=self.base();critical=mutate_evaluation(e,lambda d:d['facts'][0]['arms']['F']['required_fields'][0].update({'post_state':'unknown','chain_ids':[]}));self.assertEqual(self.gates(critical)['zero_critical_unsupported']['status'],'fail');self.assertEqual(evaluate_fresh_eiy_evaluation(fresh_evaluation=critical)['verdict'],'reject')
  missing=mutate_evaluation(e,lambda d:d['facts'][0]['arms']['F']['required_fields'][0].update({'critical':None}));self.assertEqual(self.gates(missing)['zero_critical_unsupported']['status'],'unknown')
  def break_lineage(d):
   source=d['facts'][0]['arms']['F']['canonical_units'][0]
   d['facts'][0]['arms']['B0']['canonical_units']=[{**source,'canonical_key_sha256':str(i)*64,'lineage_sha256':str(i+3)*64} for i in (1,2,3)]
  lineage=mutate_evaluation(e,break_lineage);self.assertEqual(self.gates(lineage)['lineage']['status'],'fail')
  def at_lineage_floor(d):
   source=d['facts'][0]['arms']['F']['canonical_units'][0];d['facts'][0]['arms']['B0']['canonical_units']=[{**source,'canonical_key_sha256':'1'*64,'lineage_sha256':'4'*64},{**source,'canonical_key_sha256':'2'*64,'lineage_sha256':'5'*64}]
  floor=mutate_evaluation(e,at_lineage_floor);self.assertEqual(self.gates(floor)['lineage']['status'],'pass')
  execution=mutate_evaluation(e,lambda d:d['facts'][0]['arms']['F']['execution'].update({'backend':'different'}));self.assertEqual(self.gates(execution)['execution_custody']['status'],'fail')
  def add_failure(d):
   chain=d['facts'][0]['arms']['F']['canonical_units'][0]['chain_ids'][0];d['facts'][0]['hard_failures']=[{'code':'MISSING_TRACE','chain_ids':[chain]}]
  hard=mutate_evaluation(e,add_failure);self.assertEqual(evaluate_fresh_eiy_evaluation(fresh_evaluation=hard)['verdict'],'reject')
if __name__=='__main__':unittest.main()
