import unittest
from unittest.mock import patch
from investment.research.acquisition_eiy_checker import check_eiy_evaluation_v4,audit_eiy_evaluation_v4,EiyCheckerError
from shared.research_sources.artifacts import ROOT
from tuning.evals.information_fetch.information_yield._v4_support import build_batch
class EiyV4ContextTests(unittest.TestCase):
 def test_exact_context_and_o2_audit_parity(self):
  fixtures,evaluation,custody,_=build_batch(self);data=evaluation.to_audit_mapping();self.assertEqual(len(data['context']['planned_cases']),6);self.assertEqual([r['case_id'] for r in data['context']['planned_cases']],[f'case-{i}' for i in range(1,7)]);audit=audit_eiy_evaluation_v4(custody,read_ref=fixtures[0].read_ref,workspace_root=ROOT,expected_context_sha256=data['context']['context_sha256'],expected_fact_set_sha256=data['context']['fact_set_sha256']);self.assertEqual(audit['status'],'pass')
 def test_phantom_seven_roster_six_requests_no_context(self):
  fixtures,_evaluation,_custody,_=build_batch(self)
  rows=fixtures[0].read_ref(fixtures[0].values['case_roster_ref'])['cases'];rows.append({'case_id':'case-7','issuer_id':'ISSUER-7','subject':'ACME','window_id':'2026Q7','cutoff':'2026-01-01T00:00:00Z','evidence_level':'confirmation','split':'untouched','arm_order':['B0','F']});bad=fixtures[0].put('phantom-roster.json',{'schema_version':'information-yield-case-roster-4','evaluation_id':'eval-v3','case_ids':[r['case_id'] for r in rows],'cases':rows})
  for f in fixtures:f.values['case_roster_ref']=bad;f.rebuild_request()
  custody,_=fixtures[0].batch(fixtures,[f.request_ref for f in fixtures])
  with self.assertRaisesRegex(EiyCheckerError,'ACQ_EIY_EVALUATION_FACT_SET_MISMATCH'):check_eiy_evaluation_v4(custody,read_ref=fixtures[0].read_ref,workspace_root=ROOT)
 def test_allocation_mismatch_fixed_code(self):
  fixtures,_evaluation,_custody,_=build_batch(self);allocation=fixtures[0].read_ref(fixtures[0].values['allocation_ref']);allocation['cases'].pop('case-6');bad=fixtures[0].put('bad-allocation.json',allocation)
  for f in fixtures:f.values['allocation_ref']=bad;f.rebuild_request()
  custody,_=fixtures[0].batch(fixtures,[f.request_ref for f in fixtures])
  with self.assertRaisesRegex(EiyCheckerError,'ACQ_EIY_V4_ALLOCATION_MISMATCH'):check_eiy_evaluation_v4(custody,read_ref=fixtures[0].read_ref,workspace_root=ROOT)
 def test_shuffled_requests_return_roster_order_and_one_checker_each(self):
  fixtures,evaluation,custody,_=build_batch(self,confirmation=6,development=1,shuffle=True);data=evaluation.to_audit_mapping();self.assertEqual([r['case_id'] for r in data['context']['planned_cases']],[f'case-{i}' for i in range(1,8)])
  with patch('investment.research.acquisition_eiy_checker.check_eiy_case_v3',wraps=__import__('investment.research.acquisition_eiy_checker',fromlist=['check_eiy_case_v3']).check_eiy_case_v3) as spy:check_eiy_evaluation_v4(custody,read_ref=fixtures[0].read_ref,workspace_root=ROOT);self.assertEqual(spy.call_count,7)
 def test_extra_duplicate_and_substitute_requests_rejected(self):
  fixtures,_evaluation,_custody,_=build_batch(self);refs=[f.request_ref for f in fixtures]
  for label,changed in [('extra',refs+[refs[0]]),('duplicate',[refs[0],refs[0],*refs[2:]]),('substitute',[refs[1],*refs[1:]])]:
   with self.subTest(label=label):
    custody,_=fixtures[0].batch(fixtures,changed)
    with self.assertRaisesRegex(EiyCheckerError,'ACQ_EIY_V4_REQUEST_REFS|ACQ_EIY_EVALUATION_FACT_SET_MISMATCH'):check_eiy_evaluation_v4(custody,read_ref=fixtures[0].read_ref,workspace_root=ROOT)
 def test_checker_failure_yields_no_context(self):
  fixtures,_evaluation,custody,_=build_batch(self)
  with patch('investment.research.acquisition_eiy_checker.check_eiy_case_v3',side_effect=EiyCheckerError('ACQ_EIY_EVIDENCE_CHAIN_UNKNOWN')):
   with self.assertRaisesRegex(EiyCheckerError,'ACQ_EIY_EVIDENCE_CHAIN_UNKNOWN'):check_eiy_evaluation_v4(custody,read_ref=fixtures[0].read_ref,workspace_root=ROOT)
if __name__=='__main__':unittest.main()
