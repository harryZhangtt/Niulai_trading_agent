from __future__ import annotations
import ast,copy,http.server,inspect,json,tempfile,threading,unittest
from datetime import datetime,timezone
from pathlib import Path
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.contracts import CELL_BINDINGS,ContractError as P0Error,validate_envelope
from shared.job_runtime.candidates.r6_one_off_codex_live_integration_v1.authority_v2 import FixedAuthority,load_fixed_authority,validate_fixed_grant
from shared.job_runtime.candidates.r6_one_off_codex_live_integration_v1.contracts import ContractError
from shared.job_runtime.candidates.r6_one_off_codex_live_integration_v1.v2 import ROOT,FIXTURE_ROOT,_execute_case,_p0,execute_provider_free_v2
ROOT=Path(ROOT);FIX=Path(FIXTURE_ROOT);RESPONSE=(ROOT/'shared/job_runtime/tests/fixtures/r6_one_off_codex_live_driver_v1/fake_terminal_exact.jsonl').read_bytes()
class Upstream:
 def __init__(self):self.requests=[]
 def __enter__(self):
  outer=self
  class H(http.server.BaseHTTPRequestHandler):
   def log_message(self,*a):pass
   def do_POST(self):
    n=int(self.headers.get('Content-Length','0'));outer.requests.append((self.path,self.headers.get('Authorization'),self.rfile.read(n)));self.send_response(200);self.send_header('Content-Length',str(len(RESPONSE)));self.end_headers();self.wfile.write(RESPONSE)
  self.server=http.server.HTTPServer(('127.0.0.1',0),H);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();return self
 def __exit__(self,*a):self.server.shutdown();self.server.server_close();self.thread.join(2)
 @property
 def port(self):return int(self.server.server_address[1])
class V2Tests(unittest.TestCase):
 def run_case(self,case='nominal'):
  with tempfile.TemporaryDirectory(dir=FIX) as td,Upstream() as up:
   p=Path(td);result=_execute_case(custody_parent=p,execution_id='v2-'+case,fixture_port=up.port,case=case);files={x.name:x.read_bytes() for x in p.iterdir() if x.is_file()};return result,up.requests,files
 def test_nominal_exact_grant_exit_terminal_engine_cleanup(self):
  r,requests,files=self.run_case();self.assertEqual(r.result.outcome,'PASS');self.assertEqual((r.post_run_seal['process_exit_code'],r.post_run_seal['exact_terminal']),(0,True));self.assertTrue(r.post_run_seal['gateway_closed'] and r.post_run_seal['process_reaped'] and r.post_run_seal['custody_clean']);self.assertEqual(r.result.engine['grant_sha256'],load_fixed_authority().grant_sha256);self.assertEqual(len(requests),1);self.assertIsNone(r.unknown_fence);self.assertFalse(any('unknown' in n for n in files))
 def test_fixed_noncaller_authority_and_internal_clock(self):
  params=set(inspect.signature(execute_provider_free_v2).parameters);self.assertEqual(params,{'custody_parent','execution_id','fixture_port'})
  with self.assertRaises(ContractError):FixedAuthority({},'a'*64,'b'*64,object())
  auth=load_fixed_authority();g=copy.deepcopy(auth.grant);g['issuer_role']='caller'
  with self.assertRaises(ContractError):validate_fixed_grant(g,datetime.now(timezone.utc))
  for start,end in [('2026-11-11T00:00:00','2026-11-12T00:00:00Z'),('bad','2026-11-12T00:00:00Z')]:
   g=copy.deepcopy(auth.grant);g['window']={'not_before':start,'deadline':end}
   with self.assertRaises(ContractError):validate_fixed_grant(g,datetime.now(timezone.utc))
  with self.assertRaises(ContractError):validate_fixed_grant(auth.grant,datetime(2027,1,1,tzinfo=timezone.utc))
  with self.assertRaises(ContractError):validate_fixed_grant(auth.grant,datetime(2026,11,11))
 def test_full_argv_config_cross_binding_rejects_mismatch(self):
  auth=load_fixed_authority()
  for mutate in (lambda g:g['argv'].__setitem__(3,'wrong'),lambda g:g['config'].__setitem__('effort','high'),lambda g:g['treatment'].__setitem__('release','0.168.0'),lambda g:g['profile'].__setitem__('credential_reference','opaque://caller')):
   g=copy.deepcopy(auth.grant);mutate(g)
   with self.assertRaises(ContractError):validate_fixed_grant(g,datetime.now(timezone.utc))
 def test_nonzero_second_and_terminal_failures_are_durable_unknown(self):
  for case in ('nonzero_success','second','malformed','multiple','contradictory'):
   with self.subTest(case=case):
    r,requests,files=self.run_case(case);self.assertEqual(r.result.outcome,'UNKNOWN');self.assertTrue(r.unknown_fence['durable']);self.assertTrue(r.unknown_fence['gateway_closed'] and r.unknown_fence['process_reaped']);self.assertEqual((r.result.counters['retries'],r.result.counters['replays'],r.result.counters['status_calls']),(0,0,0));self.assertTrue(any('post-admission-unknown-v2.json' in n for n in files));self.assertEqual(len(requests),1)
  r,_,_=self.run_case('second');self.assertEqual((r.result.counters['upstream_attempts'],r.result.counters['second_rejections']),(1,1))
 def test_post_admission_exceptions_publication_and_engine_fenced(self):
  for case in ('post_p0_exception','post_seal_exception','publication_fault','engine_mismatch'):
   with self.subTest(case=case):
    r,_,files=self.run_case(case);self.assertEqual(r.result.outcome,'UNKNOWN');self.assertTrue(r.unknown_fence['durable']);self.assertTrue(r.post_run_seal['gateway_closed'] and r.post_run_seal['process_reaped']);self.assertFalse(r.post_run_seal['fence']['retry']);self.assertTrue(any('post-admission-unknown-v2.json' in n for n in files))
 def test_process_timeout_before_admission_stops_cleanly(self):
  r,requests,_=self.run_case('pre_timeout');self.assertEqual((r.result.outcome,r.result.counters['admissions'],len(requests)),('STOP',0,0));self.assertTrue(r.result.receipts['gateway']['listener_closed'] and r.result.receipts['gateway']['thread_stopped']);self.assertTrue(r.result.receipts['process']['process_group_reaped'])
 def test_p0_labels_derive_for_all_cells_and_contradiction_rejects(self):
  nominal,_,_=self.run_case();auth=load_fixed_authority();artifact={'outcome':'PASS'}
  for cell,labels in CELL_BINDINGS.items():
   g=copy.deepcopy(auth.grant);g['cell_id']=cell;env=_p0(nominal.result,g,RESPONSE,artifact);self.assertEqual((env['blind_provider_label'],env['blind_addon_label'],env['checks_enabled']),labels)
   bad=copy.deepcopy(env);bad['blind_provider_label']='ARM-A' if labels[0]=='ARM-B' else 'ARM-B'
   with self.assertRaises(P0Error):validate_envelope(bad)
 def test_v2_draft_instances_and_recursive_closure(self):
  try:from jsonschema import Draft202012Validator
  except ImportError:self.skipTest('jsonschema unavailable')
  schemas=ROOT/'shared/job_runtime/candidates/r6_one_off_codex_live_integration_v1/schemas';nominal,_,_=self.run_case();unknown,_,_=self.run_case('post_p0_exception')
  values={'post-run-execution-seal-v2.schema.json':nominal.post_run_seal,'post-admission-unknown-fence-v2.schema.json':{k:v for k,v in unknown.unknown_fence.items() if k not in ('path','bytes','sha256','durable')}}
  for name,value in values.items():
   schema=json.loads((schemas/name).read_text());Draft202012Validator.check_schema(schema);Draft202012Validator(schema).validate(value)
   def walk(item):
    if isinstance(item,dict):
     if item.get('type')=='object':self.assertFalse(item.get('additionalProperties',True));self.assertFalse(item.get('unevaluatedProperties',True))
     for x in item.values():walk(x)
    elif isinstance(item,list):
     for x in item:walk(x)
   walk(schema)
 def test_no_callback_or_caller_authority_surface(self):
  root=ROOT/'shared/job_runtime/candidates/r6_one_off_codex_live_integration_v1';text=(root/'v2.py').read_text()+(root/'authority_v2.py').read_text()
  for p in (root/'v2.py',root/'authority_v2.py'):ast.parse(p.read_text())
  for forbidden in ('Callable','callback','grant_ref','review_ref','workspace_root','Dependencies','now:') :self.assertNotIn(forbidden,text)
  self.assertIn('ResponsesGateway(',text);self.assertNotIn('execute_provider_free(',text)
if __name__=='__main__':unittest.main()
