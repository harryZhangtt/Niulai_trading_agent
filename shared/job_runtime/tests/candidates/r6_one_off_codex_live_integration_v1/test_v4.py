from __future__ import annotations
import hashlib,json,tempfile,unittest
from pathlib import Path
from .test_v3 import ROOT,FIX,Upstream
from shared.job_runtime.candidates.r6_one_off_codex_live_integration_v1.v4 import _execute_case
class V4Tests(unittest.TestCase):
 def run_case(self,case):
  with tempfile.TemporaryDirectory(dir=FIX) as td,Upstream() as up:
   p=Path(td);r=_execute_case(custody_parent=p,execution_id='v4-'+case,fixture_port=up.port,cell_id='R6DQ-92D6F0B3',case=case);files={x.name:x.read_bytes() for x in p.iterdir() if x.is_file()};return r,files
 def test_checked_write_all_normal_fence_is_exact_and_durable(self):
  r,files=self.run_case('second');f=r.finalization;raw=files[f['path']];self.assertTrue(f['durable'] and f['fence_readback_verified'] and f['fence_file_fsynced'] and f['fence_parent_dir_fsynced']);self.assertEqual((f['bytes'],f['sha256']),(len(raw),hashlib.sha256(raw).hexdigest()));self.assertFalse(f['authoritative_marker_present']);self.assertFalse(r.post_run_seal['authoritative_pass_claim'])
 def test_partial_short_and_zero_write_are_non_durable_non_authoritative(self):
  for case in ('fence_partial_short_write','fence_zero_write'):
   with self.subTest(case=case):
    r,files=self.run_case(case);f=r.finalization;self.assertEqual((r.result.outcome,r.result.code),('UNKNOWN','NON_DURABLE_UNKNOWN'));self.assertFalse(f['durable']);self.assertNotIn('bytes',f);self.assertNotIn('sha256',f);self.assertFalse(r.post_run_seal['authoritative_pass_claim']);self.assertFalse(any(n.endswith('.commit') for n in files));raw=files.get(f.get('path',''),b'')
    if case=='fence_partial_short_write':self.assertGreater(len(raw),0);self.assertRaises((json.JSONDecodeError,UnicodeDecodeError),json.loads,raw.decode('utf-8','strict'))
    else:self.assertEqual(raw,b'')
 def test_write_fsync_and_readback_exceptions_never_claim_durable(self):
  for case in ('fence_write_exception','fence_file_fsync_failure','fence_readback_exception','fence_dirfsync_failure'):
   with self.subTest(case=case):
    r,files=self.run_case(case);f=r.finalization;self.assertEqual((r.result.outcome,r.result.code),('UNKNOWN','NON_DURABLE_UNKNOWN'));self.assertFalse(f['durable']);self.assertNotIn('bytes',f);self.assertNotIn('sha256',f);self.assertFalse(r.post_run_seal['authoritative_pass_claim']);self.assertFalse(any(n.endswith('.commit') for n in files));self.assertTrue(r.post_run_seal['gateway_closed'] and r.post_run_seal['process_reaped'])
 def test_v4_draft_durable_and_non_durable_instances(self):
  try:from jsonschema import Draft202012Validator
  except ImportError:self.skipTest('jsonschema unavailable')
  schema=json.loads((ROOT/'shared/job_runtime/candidates/r6_one_off_codex_live_integration_v1/schemas/total-unknown-finalizer-v4.schema.json').read_text());Draft202012Validator.check_schema(schema)
  for case in ('second','fence_partial_short_write','fence_zero_write','fence_file_fsync_failure','fence_readback_exception'):
   r,_=self.run_case(case);Draft202012Validator(schema).validate(r.finalization)
 def test_source_has_checked_loop_zero_rejection_and_exact_readback(self):
  text=(ROOT/'shared/job_runtime/candidates/r6_one_off_codex_live_integration_v1/finalizer_v4.py').read_text();self.assertIn('while view:',text);self.assertIn('if n<=0:',text);self.assertIn('actual=path.read_bytes()',text);self.assertIn('if actual!=raw:',text);self.assertLess(text.index('if actual!=raw:'),text.index('durable=True',text.index('if actual!=raw:')))
 def test_v1_v2_v3_producers_immutable(self):
  root=ROOT/'tuning/architecture/r6_one_off_codex_live_integration_v1';expected={'producer-verification-v1.json':'1515116fdef27fe585151a3d1e2e7d81ebb94260a59219c6329b01cb8e3c62ff','producer-verification-v2.json':'2f742d45199ba16abee393829a98bf28b886acb1e8df2f5a8bc92484cf2966c8','producer-verification-v3.json':'0304137d28892e4a43999875bab89fadecab40d579e3ac448dbdcb8a1c718f89'}
  for n,h in expected.items():self.assertEqual(hashlib.sha256((root/n).read_bytes()).hexdigest(),h)
if __name__=='__main__':unittest.main()
