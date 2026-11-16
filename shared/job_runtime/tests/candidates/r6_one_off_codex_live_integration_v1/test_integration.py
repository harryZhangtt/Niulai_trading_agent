from __future__ import annotations
import ast,copy,hashlib,http.client,http.server,json,tempfile,threading,time,unittest
from pathlib import Path
from ._support import ROOT,FIX,NOW,config,deps,grant,held,preflight,prompt,raw,write_authority
from shared.job_runtime.candidates.r6_one_off_codex_live_integration_v1 import ContractError,Endpoint,ResponsesGateway,execute_provider_free_integration,load_pregrant,validate_post_seal,validate_pregrant
class IntegrationTests(unittest.TestCase):
 def run_case(self,scenario='nominal',mutate_grant=None,mutate_held=None,fault=None,engine_fault=None,retain=False):
  with tempfile.TemporaryDirectory(dir=FIX) as td:
   p=Path(td);c=config();g=grant(c)
   if mutate_grant:mutate_grant(g)
   gr,rr=write_authority(p,g);h=held(c)
   if mutate_held:mutate_held(h)
   value=execute_provider_free_integration(config=c,preflight=preflight(),held_bytes=h,prompt=prompt(),body=b'{}',workspace_root=ROOT,custody_parent=p,execution_id='integration-'+scenario,deps=deps(p,scenario,fault,engine_fault,retain),grant_ref=gr,review_ref=rr,now=NOW,terminal_raw=raw('fake_terminal_exact.jsonl'))
   public=b''.join(x.read_bytes() for x in p.rglob('*') if x.is_file() and (x.name.endswith('.payload') or x.name.endswith('.commit')));return value,public
 def test_nominal_postseal_p0_and_engine(self):
  v,public=self.run_case();self.assertEqual(v.result.outcome,'PASS');validate_post_seal(v.post_run_seal);self.assertEqual(v.p0_envelope['terminal_state'],'PASS');self.assertEqual(v.result.receipts['engine_readback']['status'],'succeeded');self.assertEqual((v.result.counters['admissions'],v.result.counters['upstream_attempts'],v.result.counters['retries']),(1,1,0));self.assertNotIn(b'Bearer',public)
 def test_stop_unknown_cleanup_publication_engine(self):
  v,_=self.run_case(mutate_held=lambda h:h.__setitem__('grant',b'drift'));self.assertEqual((v.result.outcome,v.result.counters['upstream_attempts']),('STOP',0))
  for kw in ({'scenario':'malformed'},{'scenario':'second'},{'scenario':'post_timeout'},{'scenario':'nominal','retain':True},{'scenario':'nominal','fault':'short_write'},{'scenario':'nominal','engine_fault':'readback'}):
   with self.subTest(kw=kw):v,public=self.run_case(**kw);self.assertEqual(v.result.outcome,'UNKNOWN');self.assertEqual((v.result.counters['retries'],v.result.counters['replays'],v.result.counters['status_calls']),(0,0,0));self.assertNotIn(b'synthetic-exception-secret',public)
 def test_process_timeout_before_admission_stops_without_forward(self):
  v,_=self.run_case('pre_timeout');self.assertEqual((v.result.outcome,v.result.counters['upstream_attempts']),('STOP',0))
 def test_grant_self_mint_drift_and_binary_path_swap(self):
  c=config();g=grant(c);g['issuer_role']='candidate';
  with self.assertRaises(ContractError):validate_pregrant(g)
  with tempfile.TemporaryDirectory(dir=FIX) as td:
   p=Path(td);g=grant(c);gr,rr=write_authority(p,g);(p/'external-grant.json').write_text('{}')
   with self.assertRaises(ContractError):load_pregrant(gr,rr,ROOT,NOW)
  with tempfile.TemporaryDirectory(dir=FIX) as td:
   p=Path(td);binary=p/'codex';binary.write_bytes(raw('fake_codex_process.py'));binary.chmod(0o755);c=config(binary);g=grant(c);gr,rr=write_authority(p,g);binary.write_bytes(b'path swap');binary.chmod(0o755)
   v=execute_provider_free_integration(config=c,preflight=preflight(),held_bytes=held(c),prompt=prompt(),body=b'{}',workspace_root=ROOT,custody_parent=p,execution_id='integration-path-swap',deps=deps(p),grant_ref=gr,review_ref=rr,now=NOW,terminal_raw=raw('fake_terminal_exact.jsonl'));self.assertEqual((v.result.outcome,v.result.counters['upstream_attempts']),('STOP',0))
 def test_source_is_disabled_no_live_callbacks(self):
  root=ROOT/'shared/job_runtime/candidates/r6_one_off_codex_live_integration_v1';text='\n'.join(p.read_text() for p in root.glob('*.py'))
  for p in root.glob('*.py'):ast.parse(p.read_text())
  self.assertNotIn('auth_material_provider',text);self.assertNotIn('enabled=True',text);self.assertNotIn('urlopen(',text)
class Upstream:
 def __init__(self,body=b'{"type":"response.completed","model":"gpt-6.1-sol"}',delay=0,bad_length=False):self.body=body;self.delay=delay;self.bad_length=bad_length;self.requests=[]
 def __enter__(self):
  outer=self
  class H(http.server.BaseHTTPRequestHandler):
   def log_message(self,*a):pass
   def do_POST(self):
    n=int(self.headers.get('Content-Length','0'));body=self.rfile.read(n);outer.requests.append((self.path,self.headers.get('Authorization'),body));time.sleep(outer.delay);self.send_response(200);self.send_header('Content-Length',str(len(outer.body)+(5 if outer.bad_length else 0)));self.end_headers();self.wfile.write(outer.body)
  self.s=http.server.HTTPServer(('127.0.0.1',0),H);self.t=threading.Thread(target=self.s.serve_forever,daemon=True);self.t.start();return self
 def __exit__(self,*a):self.s.shutdown();self.s.server_close();self.t.join(2)
 @property
 def endpoint(self):return Endpoint('127.0.0.1',self.s.server_address[1],False)
class GatewayTests(unittest.TestCase):
 def send(self,port,path='/backend-api/codex/responses',auth=True,body=b'{}'):
  h={'X-R6-Fingerprint':'a'*64,'X-R6-Admission':'b'*64,'Content-Type':'application/json'}
  if auth:h['Authorization']='Bearer synthetic-gateway-secret'
  c=http.client.HTTPConnection('127.0.0.1',port,timeout=2);c.request('POST',path,body,h);r=c.getresponse();data=r.read();status=r.status;c.close();return status,data
 def test_nominal_one_forward_second409_headers_memory_only(self):
  with Upstream() as up:
   g=ResponsesGateway('a'*64,'b'*64,1,fixture_endpoint=up.endpoint,provider_free_fixture=True);port=g.start();self.assertEqual(self.send(port)[0],200);self.assertEqual(self.send(port)[0],409);receipt=g.close();self.assertEqual((len(up.requests),receipt['admissions'],receipt['provider_forwards'],receipt['second_rejections']),(1,1,1,1));self.assertFalse(receipt['sensitive_headers_persisted']);self.assertNotIn('synthetic-gateway-secret',json.dumps(receipt))
 def test_auth_route_timeout_malformed_truncated_and_default_deny(self):
  with Upstream() as up:
   g=ResponsesGateway('a'*64,'b'*64,1,fixture_endpoint=up.endpoint,provider_free_fixture=True);port=g.start();self.assertEqual(self.send(port,auth=False)[0],401);self.assertEqual(len(up.requests),0);g.close()
  with Upstream(delay=.2) as up:
   g=ResponsesGateway('a'*64,'b'*64,.03,fixture_endpoint=up.endpoint,provider_free_fixture=True);port=g.start();self.assertEqual(self.send(port)[0],502);g.close()
  for body,bad in ((b'{bad',False),(b'{}',True)):
   with Upstream(body,bad_length=bad) as up:
    g=ResponsesGateway('a'*64,'b'*64,.2,fixture_endpoint=up.endpoint,provider_free_fixture=True);port=g.start();status,_=self.send(port);self.assertEqual(status,502 if bad else 200);g.close()
  g=ResponsesGateway('a'*64,'b'*64,.1);port=g.start();self.assertEqual(self.send(port)[0],403);r=g.close();self.assertEqual(r['provider_forwards'],0)
 def test_nonloopback_fixture_rejected(self):
  with self.assertRaises(ContractError):ResponsesGateway('a'*64,'b'*64,1,fixture_endpoint=Endpoint('example.com',80,False),provider_free_fixture=True)
class SchemaTests(unittest.TestCase):
 def test_draft_202012_closed(self):
  for p in (ROOT/'shared/job_runtime/candidates/r6_one_off_codex_live_integration_v1/schemas').glob('*.json'):
   s=json.loads(p.read_text());self.assertEqual(s['$schema'],'https://json-schema.org/draft/2020-12/schema')
   def walk(v):
    if isinstance(v,dict):
     if v.get('type')=='object':self.assertIn('additionalProperties',v)
     for x in v.values():walk(x)
    elif isinstance(v,list):
     for x in v:walk(x)
   walk(s)
if __name__=='__main__':unittest.main()
