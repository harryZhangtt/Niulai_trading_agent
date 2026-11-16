from __future__ import annotations
import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from .test_v3 import ROOT,FIX,Upstream
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.contracts import PROVIDER_BINDINGS,validate_attempt_bundle,validate_envelope
from shared.job_runtime.candidates.r6_one_off_codex_live_integration_v1.contracts import ContractError
from shared.job_runtime.candidates.r6_one_off_codex_live_integration_v1.v6 import CODEX_CELLS,P0_V10_RECLOSURE_REQUIRED,_adversarial_bundle_v6,_execute_case,execute_provider_free_v6
class V6Tests(unittest.TestCase):
 def run_case(self,case='nominal',execution_id=None,cell_id='R6DQ-92D6F0B3'):
  execution_id=execution_id or ('execution-v6-'+cell_id.lower()+'-'+case)
  with tempfile.TemporaryDirectory(dir=FIX) as td,Upstream() as up:
   p=Path(td).resolve();r=_execute_case(custody_parent=p,execution_id=execution_id,fixture_port=up.port,cell_id=cell_id,case=case);root=Path(r.custody_root);files={x.relative_to(root).as_posix():x.read_bytes() for x in root.rglob('*') if x.is_file() or x.is_symlink()};return r,list(up.requests),files
 def test_exact_two_codex_cells_full_bundle_commit_last(self):
  self.assertEqual(CODEX_CELLS,{'R6DQ-1B8E43D7','R6DQ-92D6F0B3'});self.assertTrue(P0_V10_RECLOSURE_REQUIRED)
  for cell in sorted(CODEX_CELLS):
   with self.subTest(cell=cell):
    r,requests,files=self.run_case(cell_id=cell);self.assertEqual(r.result.outcome,'PASS');validate_attempt_bundle(r.p0_bundle);self.assertEqual(r.p0_bundle['provider_identity'],PROVIDER_BINDINGS['ARM-B']);self.assertEqual(r.p0_bundle['publication_artifact_ref']['provider_schema'],'stage-b-execution-v3');self.assertEqual(r.p0_bundle['normalized_attempt']['provider_identity'],r.p0_bundle['envelope']['provider_identity']);self.assertEqual(len(requests),1);commits=[json.loads(v) for n,v in files.items() if n.endswith('.commit')];self.assertEqual(len(commits),1);self.assertEqual(commits[0]['version'],6);self.assertTrue(commits[0]['complete_before_commit']);self.assertIn('staging/p0-attempt-bundle.json',files)
 def test_both_claude_cells_reject_before_admission_effect_artifact_p0_commit(self):
  for cell in ('R6DQ-7F2C91A4','R6DQ-C4A7095E'):
   with self.subTest(cell=cell),tempfile.TemporaryDirectory(dir=FIX) as td,Upstream() as up:
    root=Path(td).resolve()
    with self.assertRaisesRegex(ContractError,'V6_CODEX_CELL_DENIED'):execute_provider_free_v6(custody_parent=root,execution_id='execution-v6-reject-'+cell.lower(),fixture_port=up.port,cell_id=cell)
    self.assertEqual(list(up.requests),[]);self.assertEqual(list(root.iterdir()),[])
 def test_bundle_identity_binds_request_raw_research_publication_and_readback(self):
  r,_,files=self.run_case();b=r.p0_bundle;p=PROVIDER_BINDINGS['ARM-B'];key=b['key'];self.assertEqual(b['provider_identity'],p);self.assertEqual(b['normalized_attempt']['key'],key);self.assertEqual(b['envelope']['readback_ref'],r.observed_readback);self.assertEqual(b['raw_custody_receipt']['binding']['provider_schema'],p['provider_schema']);self.assertEqual(b['raw_custody_receipt']['binding']['publication_driver_identity_sha256'],p['publication_driver_identity_sha256'])
  for entry in b['research_evidence'].values():self.assertEqual(entry['body']['binding']['blind_provider_label'],'ARM-B');self.assertEqual(entry['body']['binding']['provider_schema'],p['provider_schema']);self.assertEqual(entry['body']['binding']['publication_driver_identity_sha256'],p['publication_driver_identity_sha256'])
  artifact=json.loads(b['provider_publication_artifact_body']);self.assertEqual(artifact['version'],'stage-b-execution-v3');self.assertEqual(hashlib.sha256(b['provider_publication_artifact_body'].encode('ascii')).hexdigest(),b['publication_artifact_ref']['sha256']);self.assertIn('staging/sanitized-provider-artifact.json',files)
 def test_direct_arm_a_and_cross_provider_adversaries_have_zero_commit(self):
  for case in ('cross_provider_publication_schema_swap','coherent_relabel_reseal','envelope_valid_bundle_invalid','publication_body_swap'):
   with self.subTest(case=case):
    r,requests,files=self.run_case(case);self.assertEqual(r.result.outcome,'UNKNOWN');self.assertIsNone(r.commit_ref);self.assertIsNone(r.p0_bundle);self.assertFalse(any(n.endswith('.commit') for n in files));self.assertFalse(any(n.startswith('evidence/') or n.startswith('staging/') for n in files));self.assertEqual(len(requests),1)
 def test_envelope_valid_bundle_invalid_is_rejected_by_full_validator(self):
  r,_,_=self.run_case();bad=_adversarial_bundle_v6(r.p0_bundle,'envelope_valid_bundle_invalid');validate_envelope(bad['envelope'])
  with self.assertRaisesRegex(Exception,'ATTEMPT_BUNDLE_ARTIFACT_REF_BINDING'):validate_attempt_bundle(bad)
 def test_cross_provider_swap_and_coherent_reseal_reject(self):
  r,_,_=self.run_case()
  for case,code in (('cross_provider_publication_schema_swap','ATTEMPT_BUNDLE_PROVIDER_ARTIFACT_IDENTITY'),('coherent_relabel_reseal','ATTEMPT_PROVIDER_IDENTITY')):
   with self.subTest(case=case):
    with self.assertRaisesRegex(Exception,code):validate_attempt_bundle(_adversarial_bundle_v6(r.p0_bundle,case))
 def test_crash_cuts_have_no_apparent_commit_and_cleanup_stages(self):
  for case in ('crash_after_raw','crash_after_artifact','crash_after_unknown_stage','crash_after_p0','crash_after_seal','crash_before_commit'):
   with self.subTest(case=case):
    r,_,files=self.run_case(case);self.assertEqual(r.result.outcome,'UNKNOWN');self.assertIsNone(r.commit_ref);self.assertFalse(any(n.endswith('.commit') for n in files));self.assertNotIn('durable',r.finalization);self.assertTrue(r.finalization['cleanup']['all_removed_or_quarantined']);self.assertTrue(r.finalization['cleanup']['all_parent_fsynced'])
 def test_total_unknown_commit_and_exact_cleanup_schema(self):
  r,_,files=self.run_case('second');self.assertEqual(r.result.outcome,'UNKNOWN');self.assertTrue(r.finalization['durable']);self.assertTrue(r.finalization['marker_absence_verified']);self.assertEqual(len([n for n in files if n.endswith('.commit')]),1)
  r,_,_=self.run_case('unknown_partial_quarantine');cleanup=r.finalization['cleanup'];self.assertTrue(cleanup['quarantined']);self.assertTrue(cleanup['source_dir_fsynced'] and cleanup['quarantine_dir_fsynced']);expected={'label','name','removed','quarantined','quarantine_name','source_dir_fsynced','quarantine_dir_fsynced','authoritative'};entries=self.run_case('crash_after_p0')[0].finalization['cleanup']['entries'];self.assertTrue(entries);self.assertTrue(all(set(x)==expected for x in entries))
 def test_schema_enabled_success_failure_and_codex_admission(self):
  try:from jsonschema import Draft202012Validator,ValidationError
  except ImportError:self.skipTest('jsonschema unavailable')
  schema=json.loads((ROOT/'shared/job_runtime/candidates/r6_one_off_codex_live_integration_v1/schemas/total-unknown-finalizer-v6.schema.json').read_text());validator=Draft202012Validator(schema)
  for case in ('second','raw_stage_failure','artifact_stage_failure','p0_stage_failure','seal_stage_failure','commit_failure','marker_path_absolute','unknown_partial_quarantine'):
   receipt=self.run_case(case)[0].finalization;validator.validate(receipt)
   if 'durable' not in receipt:
    for key,value in (('durable',False),('bytes',1),('sha256','a'*64),('path','x')):
     bad=copy.deepcopy(receipt);bad[key]=value
     with self.assertRaises(ValidationError):validator.validate(bad)
  admission={'version':6,'cell_id':'R6DQ-92D6F0B3','provider_identity':PROVIDER_BINDINGS['ARM-B'],'full_bundle_validated':True,'publication_reread_exact':True,'owner_artifacts_reread':True,'p0_v10_reclosure_required':True};Draft202012Validator(json.loads((ROOT/'shared/job_runtime/candidates/r6_one_off_codex_live_integration_v1/schemas/codex-p0-admission-v6.schema.json').read_text())).validate(admission)
 def test_paths_late_effect_tamper_and_failure_faults_never_commit_pass(self):
  with tempfile.TemporaryDirectory(dir=FIX) as td:
   p=Path(td).resolve()
   with self.assertRaises(ContractError):execute_provider_free_v6(custody_parent=p,execution_id='../escape',fixture_port=1,cell_id='R6DQ-92D6F0B3')
  for case in ('marker_path_absolute','marker_path_traversal','marker_symlink','late_effect','tamper_raw_evidence','tamper_artifact_evidence','raw_stage_failure','artifact_stage_failure','p0_stage_failure','seal_stage_failure','commit_failure'):
   with self.subTest(case=case):
    r,_,files=self.run_case(case);self.assertEqual(r.result.outcome,'UNKNOWN');self.assertFalse(any(json.loads(v).get('outcome')=='PASS' for n,v in files.items() if n.endswith('.commit')))
 def test_v1_through_v5_and_open_review_are_immutable(self):
  expected={'v1':'1515116fdef27fe585151a3d1e2e7d81ebb94260a59219c6329b01cb8e3c62ff','v2':'2f742d45199ba16abee393829a98bf28b886acb1e8df2f5a8bc92484cf2966c8','v3':'0304137d28892e4a43999875bab89fadecab40d579e3ac448dbdcb8a1c718f89','v4':'d8d9fdf99169635dfb57ccc4cfaed08c9cd220ed32d14bfab37ae7a19e47a0f1'};base=ROOT/'tuning/architecture/r6_one_off_codex_live_integration_v1'
  for version,digest in expected.items():self.assertEqual(hashlib.sha256((base/('producer-verification-'+version+'.json')).read_bytes()).hexdigest(),digest)
  review=ROOT/'mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-codex-live-integration-v5-p0-v9-rebase-independent-review-fable-20261111-8e9a8076-open.json';self.assertEqual((len(review.read_bytes()),hashlib.sha256(review.read_bytes()).hexdigest()),(11876,'48b02aae9a5a34314fbfd0446a4798a6357461c811a326955341b04a85ae92dc'))
if __name__=='__main__':unittest.main()
