import json,sqlite3,tempfile,unittest
from pathlib import Path
from investment.research.acquisition_eiy_checker_v5 import EiyCheckerV5Error,audit_eiy_evaluation_v5,check_eiy_evaluation_v5,private_unwrap_only
from shared.research_sources.artifacts import ROOT
from shared.research_sources.information_yield_v5_contracts import digest_v5
from tuning.evals.information_fetch.information_yield._v5_support import build_v5_batch
from tuning.evals.information_fetch.information_yield.policy_v5 import CANONICAL_METRIC_POLICY_V5_SHA256
class EiyCheckerV5Tests(unittest.TestCase):
 def test_provider_free_six_c_one_d_issued_and_auditable(self):
  fixtures,fresh,manifest,_=build_v5_batch(self);data=private_unwrap_only(fresh);context=data['context'];self.assertEqual(context['populations'],{'C':[f'case-{i}' for i in range(2,8)],'D':['case-1'],'E':[f'case-{i}' for i in range(2,8)]+['case-1'],'N':[]});self.assertEqual(context['policy_sha256'],CANONICAL_METRIC_POLICY_V5_SHA256);self.assertEqual(len(data['facts']),7);self.assertEqual(set(context['planned_cases'][0]),{'case_id','issuer_id','subject','window_id','cutoff','evidence_level','split','arm_order','request_ref','request_sha256','fact_sha256'});self.assertEqual(audit_eiy_evaluation_v5(manifest,read_ref=fixtures[0].read_ref,workspace_root=ROOT,expected_context_sha256=context['context_sha256'],expected_fact_set_sha256=context['fact_set_sha256'])['status'],'pass')
 def test_genuine_reopened_development_failure_is_checker_issued(self):
  _fixtures,fresh,_,_=build_v5_batch(self,development_hard_failure=True);development=next(f for f in private_unwrap_only(fresh)['facts'] if f['split']=='development');self.assertEqual(development['hard_failures'][0]['code'],'FABRICATED_SUPPORT');self.assertRegex(development['hard_failures'][0]['chain_ids'][0],r'^[a-f0-9]{64}$')
 def test_source_closure_drift_is_invalid_not_failure_fact(self):
  fixtures,_fresh,manifest,_=build_v5_batch(self,closure_drift=True,issue=False)
  with self.assertRaisesRegex(EiyCheckerV5Error,'ACQ_EIY_SOURCE_CLOSURE_DRIFT'):check_eiy_evaluation_v5(manifest,read_ref=fixtures[0].read_ref,workspace_root=ROOT)
 def test_noncanonical_policy_ref_fixed_fails(self):
  fixtures,_fresh,_manifest,custody_ref=build_v5_batch(self);custody=fixtures[0].read_ref(custody_ref)
  with tempfile.TemporaryDirectory(dir=ROOT/'investment/runtime') as tmp:
   alternate=Path(tmp)/'policy.json';alternate.write_text('{}');custody['canonical_policy_ref']={'path':alternate.relative_to(ROOT).as_posix(),'sha256':'0'*64};custody['custody_sha256']=digest_v5({k:v for k,v in custody.items() if k!='custody_sha256'});bad=fixtures[0].put('bad-v5-custody.json',custody)
   with self.assertRaisesRegex(EiyCheckerV5Error,'ACQ_EIY_POLICY_NOT_CANONICAL'):check_eiy_evaluation_v5(bad,read_ref=fixtures[0].read_ref,workspace_root=ROOT)
 def test_boundary_failures_are_fixed_and_sanitized(self):
  _f,_fresh,manifest,_=build_v5_batch(self);marker='/Users/private/account.sqlite'
  for error in (OSError(marker),sqlite3.OperationalError(marker)):
   with self.subTest(error=type(error).__name__):
    with self.assertRaises(EiyCheckerV5Error) as caught:check_eiy_evaluation_v5(manifest,read_ref=lambda _ref,e=error:(_ for _ in ()).throw(e),workspace_root=ROOT)
    self.assertEqual(str(caught.exception),'ACQ_EIY_V5_IO');self.assertNotIn(marker,str(caught.exception))
 def test_self_issued_mapping_has_no_fresh_authority(self):
  with self.assertRaisesRegex(EiyCheckerV5Error,'EIY_V5_EVALUATION_CONTEXT_REQUIRED'):private_unwrap_only({'context':{}})
if __name__=='__main__':unittest.main()
