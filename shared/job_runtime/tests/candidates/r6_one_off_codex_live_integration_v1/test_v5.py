from __future__ import annotations
import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from .test_v3 import ROOT,FIX,Upstream
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.contracts import CELL_BINDINGS
from shared.job_runtime.candidates.r6_one_off_codex_live_integration_v1.contracts import ContractError
from shared.job_runtime.candidates.r6_one_off_codex_live_integration_v1.v5 import _execute_case,execute_provider_free_v5
class V5Tests(unittest.TestCase):
 def run_case(self,case='nominal',execution_id=None,cell_id='R6DQ-92D6F0B3'):
  execution_id=execution_id or ('execution-v5-'+cell_id.lower()+'-'+case)
  with tempfile.TemporaryDirectory(dir=FIX) as td,Upstream() as up:
   p=Path(td).resolve();r=_execute_case(custody_parent=p,execution_id=execution_id,fixture_port=up.port,cell_id=cell_id,case=case);root=Path(r.custody_root);files={x.relative_to(root).as_posix():x.read_bytes() for x in root.rglob('*') if x.is_file() or x.is_symlink()};return r,list(up.requests),files
 def test_commit_is_last_and_real_p0_evidence_exists(self):
  r,requests,files=self.run_case();self.assertEqual(r.result.outcome,'PASS');commits=[n for n in files if n.endswith('.commit')];self.assertEqual(len(commits),1);commit=json.loads(files[commits[0]]);self.assertTrue(commit['complete_before_commit']);self.assertEqual(commit['outcome'],'PASS');self.assertEqual(len(requests),1);self.assertTrue(r.p0_envelope['raw_capture_verified'] and r.p0_envelope['provider_artifact_validated'] and r.p0_envelope['sanitization_safe']);raw=r.p0_envelope['raw_ref'];art=r.p0_envelope['publication_artifact_ref'];self.assertIn(raw['name'],files);self.assertIn(art['name'],files);self.assertEqual((len(files[raw['name']]),hashlib.sha256(files[raw['name']]).hexdigest()),(raw['bytes'],raw['sha256']));self.assertEqual((len(files[art['name']]),hashlib.sha256(files[art['name']]).hexdigest()),(art['bytes'],art['sha256']));self.assertEqual(r.post_run_seal['publication_state'],'COMMITTED');self.assertTrue(r.post_run_seal['authoritative_pass_claim'])
 def test_all_four_cells_commit_last_with_real_evidence(self):
  for cell,labels in CELL_BINDINGS.items():
   r,requests,files=self.run_case(cell_id=cell);self.assertEqual(r.result.outcome,'PASS');self.assertEqual((r.p0_envelope['blind_provider_label'],r.p0_envelope['blind_addon_label'],r.p0_envelope['checks_enabled']),labels);self.assertTrue(r.p0_envelope['raw_capture_verified'] and r.p0_envelope['provider_artifact_validated'] and r.p0_envelope['readback_match']);self.assertEqual(len([n for n in files if n.endswith('.commit')]),1);self.assertEqual(len(requests),1)
 def test_crash_cuts_have_no_apparent_commit_and_cleanup_stages(self):
  for case in ('crash_after_raw','crash_after_artifact','crash_after_unknown_stage','crash_after_p0','crash_after_seal','crash_before_commit'):
   with self.subTest(case=case):
    r,_,files=self.run_case(case);self.assertEqual(r.result.outcome,'UNKNOWN');self.assertIsNone(r.commit_ref);self.assertFalse(any(n.endswith('.commit') for n in files));self.assertNotIn('durable',r.finalization);self.assertNotIn('path',r.finalization);self.assertNotIn('bytes',r.finalization);self.assertNotIn('sha256',r.finalization);self.assertTrue(r.finalization['cleanup']['all_removed_or_quarantined']);self.assertTrue(r.finalization['cleanup']['all_parent_fsynced'])
 def test_missing_marker_receipt_still_commits_total_unknown(self):
  r,_,files=self.run_case('second');self.assertEqual(r.result.outcome,'UNKNOWN');self.assertTrue(r.finalization['durable']);self.assertTrue(r.finalization['marker_absence_verified']);self.assertFalse(r.finalization['marker_removed']);self.assertEqual(len([n for n in files if n.endswith('.commit')]),1);pending=files[r.finalization['pending_ref']['relative_ref']];self.assertNotIn(b'"durable"',pending);self.assertIn(b'"state":"PENDING_UNKNOWN"',pending)
 def test_execution_marker_and_fence_paths_are_confined(self):
  with tempfile.TemporaryDirectory(dir=FIX) as td:
   p=Path(td).resolve()
   with self.assertRaises(ContractError):execute_provider_free_v5(custody_parent=p,execution_id='../escape',fixture_port=1,cell_id='R6DQ-92D6F0B3')
  for case in ('marker_path_absolute','marker_path_traversal','marker_symlink'):
   with self.subTest(case=case):
    r,_,files=self.run_case(case);self.assertEqual(r.result.outcome,'UNKNOWN');self.assertIsNone(r.commit_ref);self.assertNotIn('durable',r.finalization);self.assertFalse(r.finalization['authoritative_pass_claim']);self.assertFalse(any(n.endswith('.commit') for n in files))
 def test_failure_receipts_omit_authoritative_fields_and_schema_rejects_contradictions(self):
  try:from jsonschema import Draft202012Validator,ValidationError
  except ImportError:self.skipTest('jsonschema unavailable')
  schema=json.loads((ROOT/'shared/job_runtime/candidates/r6_one_off_codex_live_integration_v1/schemas/total-unknown-finalizer-v5.schema.json').read_text());validator=Draft202012Validator(schema)
  for case in ('raw_stage_failure','artifact_stage_failure','p0_stage_failure','seal_stage_failure','commit_failure','marker_path_absolute','unknown_partial_quarantine'):
   r,_,_=self.run_case(case);receipt=r.finalization;validator.validate(receipt)
   for key in ('durable','bytes','sha256','path'):self.assertNotIn(key,receipt)
   for key,value in (('durable',False),('bytes',1),('sha256','a'*64),('path','x')):
    bad=copy.deepcopy(receipt);bad[key]=value
    with self.assertRaises(ValidationError):validator.validate(bad)
 def test_failed_and_truncated_files_removed_or_quarantined_with_fsync(self):
  r,_,files=self.run_case('unknown_partial_quarantine');cleanup=r.finalization['cleanup'];self.assertFalse(any(n.endswith('.commit') for n in files));self.assertTrue(cleanup['quarantined']);self.assertTrue(cleanup['source_dir_fsynced'] and cleanup['quarantine_dir_fsynced']);q=[n for n in files if n.startswith('quarantine/')];self.assertEqual(len(q),1);self.assertNotIn(b'"durable"',files[q[0]])
  for case in ('raw_stage_failure','artifact_stage_failure','p0_stage_failure','seal_stage_failure','commit_failure'):
   with self.subTest(case=case):
    r,_,files=self.run_case(case);self.assertFalse(any(n.endswith('.commit') for n in files));self.assertNotIn('durable',r.finalization)
 def test_late_effect_never_passes_or_commits_pass(self):
  r,_,files=self.run_case('late_effect');self.assertEqual(r.result.outcome,'UNKNOWN');self.assertNotEqual(r.result.code,'V2_NOMINAL_ONE');commits=[json.loads(v) for n,v in files.items() if n.endswith('.commit')];self.assertTrue(all(x['outcome']!='PASS' for x in commits));self.assertFalse(r.post_run_seal and r.post_run_seal.get('authoritative_pass_claim'))
 def test_tampered_or_missing_real_p0_evidence_never_commits(self):
  for case in ('tamper_raw_evidence','tamper_artifact_evidence'):
   with self.subTest(case=case):
    r,_,files=self.run_case(case);self.assertEqual(r.result.outcome,'UNKNOWN');self.assertIsNone(r.commit_ref);self.assertFalse(any(n.endswith('.commit') for n in files));self.assertNotIn('durable',r.finalization)
 def test_v1_through_v4_producers_and_review_are_exact(self):
  root=ROOT/'tuning/architecture/r6_one_off_codex_live_integration_v1';expected={'producer-verification-v1.json':'1515116fdef27fe585151a3d1e2e7d81ebb94260a59219c6329b01cb8e3c62ff','producer-verification-v2.json':'2f742d45199ba16abee393829a98bf28b886acb1e8df2f5a8bc92484cf2966c8','producer-verification-v3.json':'0304137d28892e4a43999875bab89fadecab40d579e3ac448dbdcb8a1c718f89','producer-verification-v4.json':'d8d9fdf99169635dfb57ccc4cfaed08c9cd220ed32d14bfab37ae7a19e47a0f1'}
  for n,h in expected.items():self.assertEqual(hashlib.sha256((root/n).read_bytes()).hexdigest(),h)
  review=ROOT/'mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-codex-live-integration-v4-independent-review-20261111-001.json';self.assertEqual((len(review.read_bytes()),hashlib.sha256(review.read_bytes()).hexdigest()),(10611,'96f09638785d1d64c531357c5eb0d73894f9a1ae6290e4e542438a77cc69261d'))
if __name__=='__main__':unittest.main()
