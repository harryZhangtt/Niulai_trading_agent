from __future__ import annotations
import hashlib,http.server,json,tempfile,threading,unittest
from pathlib import Path
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.contracts import CELL_BINDINGS,sha256_json
from shared.job_runtime.candidates.r6_one_off_codex_live_integration_v1.v3 import ROOT,FIXTURE_ROOT,_execute_case,execute_provider_free_v3
ROOT=Path(ROOT);FIX=Path(FIXTURE_ROOT);RESPONSE=(ROOT/'shared/job_runtime/tests/fixtures/r6_one_off_codex_live_driver_v1/fake_terminal_exact.jsonl').read_bytes()
class Upstream:
 def __enter__(self):
  outer=self;self.requests=[]
  class H(http.server.BaseHTTPRequestHandler):
   def log_message(self,*a):pass
   def do_POST(self):
    n=int(self.headers.get('Content-Length','0'));outer.requests.append((self.path,self.headers.get('Authorization'),self.rfile.read(n)));self.send_response(200);self.send_header('Content-Length',str(len(RESPONSE)));self.end_headers();self.wfile.write(RESPONSE)
  self.server=http.server.HTTPServer(('127.0.0.1',0),H);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();return self
 def __exit__(self,*a):self.server.shutdown();self.server.server_close();self.thread.join(2)
 @property
 def port(self):return int(self.server.server_address[1])
class V3Tests(unittest.TestCase):
 def run_case(self,cell='R6DQ-92D6F0B3',case='nominal'):
  with tempfile.TemporaryDirectory(dir=FIX) as td,Upstream() as up:
   p=Path(td);r=_execute_case(custody_parent=p,execution_id='v3-'+cell.lower()+'-'+case,fixture_port=up.port,cell_id=cell,case=case);files={x.name:x.read_bytes() for x in p.iterdir() if x.is_file()};return r,list(up.requests),files
 def test_all_four_cells_use_fresh_actual_engine_readbacks(self):
  seen=set()
  for cell,labels in CELL_BINDINGS.items():
   r,requests,_=self.run_case(cell);self.assertEqual(r.result.outcome,'PASS');observed=r.observed_readback;receipt=r.result.receipts['engine_readback'];self.assertEqual(observed,receipt['p0_receipt']);self.assertEqual(observed,r.p0_envelope['readback_ref']);self.assertEqual(sha256_json(observed),receipt['p0_receipt_sha256']);self.assertEqual(r.p0_envelope['key']['canonical_engine_readback_digest'],receipt['p0_receipt_sha256']);self.assertEqual(observed['counts'],{'job':1,'slot':1,'attempt':1});self.assertEqual(receipt['cardinalities'],{'jobs':1,'slots':1,'attempts':1,'provider_results':1});self.assertEqual(observed['transaction'],'BEGIN_IMMEDIATE_SINGLE_READBACK');self.assertEqual((r.p0_envelope['blind_provider_label'],r.p0_envelope['blind_addon_label'],r.p0_envelope['checks_enabled']),labels);self.assertTrue(r.p0_envelope['readback_match']);self.assertFalse(any(str(observed[k]).startswith('p0-') for k in ('job_id','slot_id','attempt_id','operation_id')));self.assertEqual(len(requests),1);seen.add((observed['job_id'],observed['slot_id'],observed['attempt_id'],observed['operation_id']))
  self.assertEqual(len(seen),4)
 def test_normal_unknown_requires_marker_removal_and_fsync(self):
  r,_,files=self.run_case(case='second');f=r.finalization;self.assertEqual((r.result.outcome,r.result.code),('UNKNOWN','DURABLE_UNKNOWN'));self.assertTrue(f['marker_removed'] and f['revocation_dir_fsynced'] and f['fence_file_fsynced'] and f['fence_parent_dir_fsynced'] and f['durable']);self.assertFalse(f['authoritative_marker_present']);self.assertFalse(r.post_run_seal['authoritative_pass_claim']);self.assertFalse(any(n.endswith('.commit') for n in files));self.assertTrue(any(n.endswith('-total-unknown-v3.json') for n in files))
 def test_revoke_unlink_and_surviving_marker_are_non_durable(self):
  for case in ('revoke_failure','unlink_failure','surviving_marker'):
   with self.subTest(case=case):
    r,_,files=self.run_case(case=case);f=r.finalization;self.assertEqual((r.result.outcome,r.result.code),('UNKNOWN','NON_DURABLE_UNKNOWN'));self.assertFalse(f['durable']);self.assertTrue(f['authoritative_marker_present']);self.assertFalse(r.post_run_seal['authoritative_pass_claim']);self.assertTrue(r.post_run_seal['surviving_authoritative_marker']);self.assertTrue(any(n.endswith('.commit') for n in files))
 def test_dirfsync_and_fence_failures_truthfully_non_durable(self):
  for case in ('dirfsync_failure','fence_write_failure','fence_dirfsync_failure'):
   with self.subTest(case=case):
    r,_,files=self.run_case(case=case);f=r.finalization;self.assertEqual((r.result.outcome,r.result.code),('UNKNOWN','NON_DURABLE_UNKNOWN'));self.assertFalse(f['durable']);self.assertFalse(f['authoritative_marker_present']);self.assertFalse(r.post_run_seal['authoritative_pass_claim']);self.assertFalse(any(n.endswith('.commit') for n in files))
 def test_total_finalizer_catches_second_publication_and_post_failures(self):
  for case in ('second_publication_failure','post_p0_exception','post_seal_exception','publication_fault','engine_mismatch'):
   with self.subTest(case=case):
    r,_,_=self.run_case(case=case);self.assertEqual(r.result.outcome,'UNKNOWN');self.assertIsNotNone(r.finalization);self.assertFalse(r.post_run_seal['authoritative_pass_claim']);self.assertTrue(r.post_run_seal['gateway_closed'] and r.post_run_seal['process_reaped']);self.assertEqual((r.result.counters['retries'],r.result.counters['replays'],r.result.counters['status_calls']),(0,0,0))
  r,_,_=self.run_case(case='second_publication_failure');self.assertFalse(r.finalization['durable']);self.assertEqual(r.finalization['error_code'],'AUTHORITATIVE_MARKER_RECEIPT_ABSENT')
 def test_v3_draft_instances_and_static_projection_source(self):
  try:from jsonschema import Draft202012Validator
  except ImportError:self.skipTest('jsonschema unavailable')
  schemas=ROOT/'shared/job_runtime/candidates/r6_one_off_codex_live_integration_v1/schemas';nominal,_,_=self.run_case();unknown,_,_=self.run_case(case='second');values={'canonical-engine-readback-v3.schema.json':nominal.observed_readback,'total-unknown-finalizer-v3.schema.json':{k:v for k,v in unknown.finalization.items() if k not in ('path','bytes','sha256')}}
  for name,value in values.items():schema=json.loads((schemas/name).read_text());Draft202012Validator.check_schema(schema);Draft202012Validator(schema).validate(value)
  text=(ROOT/'shared/job_runtime/candidates/r6_one_off_codex_live_integration_v1/v3.py').read_text();self.assertNotIn("readback_match':True",text);self.assertNotIn("'p0-'",text);self.assertIn('derive_readback_match',text)
 def test_v1_v2_producers_remain_immutable_open_history(self):
  root=ROOT/'tuning/architecture/r6_one_off_codex_live_integration_v1';expected={'producer-verification-v1.json':'1515116fdef27fe585151a3d1e2e7d81ebb94260a59219c6329b01cb8e3c62ff','producer-verification-v2.json':'2f742d45199ba16abee393829a98bf28b886acb1e8df2f5a8bc92484cf2966c8'}
  for name,digest in expected.items():self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),digest)
if __name__=='__main__':unittest.main()
