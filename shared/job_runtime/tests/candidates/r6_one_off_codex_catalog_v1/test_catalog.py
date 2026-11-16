from __future__ import annotations
import ast,copy,hashlib,http.server,json,os,tempfile,threading,unittest
from pathlib import Path
from unittest import mock
from shared.job_runtime.candidates.r6_one_off_codex_catalog_v1 import catalog,gateway
import shared.job_runtime.candidates.r6_one_off_codex_catalog_v1 as package
from shared.job_runtime.candidates.r6_one_off_codex_catalog_v1.catalog import CatalogError,CatalogExecutor,FIXED_GRANT,FIXED_REVIEW,HISTORY,SOURCE_RESEARCH,V7_PRODUCER,V7_REVIEW
from shared.job_runtime.candidates.r6_one_off_codex_catalog_v1.integration import issue_transient_auth_token
ROOT=Path(__file__).resolve().parents[5];FIX=ROOT/'shared/job_runtime/tests/fixtures/r6_one_off_codex_catalog_v1';SECRET=b'synthetic-v8-auth-secret'
def canon(x):return json.dumps(x,separators=(',',':'),sort_keys=True).encode()
def binary(parent):p=parent/'fake-codex';p.write_bytes((FIX/'fake_codex_0167.py').read_bytes());p.chmod(0o700);return p
class Upstream:
 def __init__(self,body=None,status=200):self.body=body if body is not None else b'{"models":[{"slug":"gpt-6.1-sol"}]}';self.status=status;self.requests=[]
 def __enter__(self):
  outer=self
  class H(http.server.BaseHTTPRequestHandler):
   def log_message(self,*a):pass
   def do_GET(self):outer.requests.append((self.path,self.headers.get('Authorization')));self.send_response(outer.status);self.send_header('Content-Length',str(len(outer.body)));self.end_headers();self.wfile.write(outer.body)
  self.server=http.server.HTTPServer(('127.0.0.1',0),H);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();return self
 def __exit__(self,*a):self.server.shutdown();self.server.server_close();self.thread.join(2)
 @property
 def endpoint(self):return gateway._Endpoint('127.0.0.1',self.server.server_address[1],False)
class Harness:
 def __init__(self,td,up):self.td=td;self.up=up;self.bin=binary(td);self.global_home=td/'global';self.global_home.mkdir(mode=0o700);(self.global_home/'sentinel').write_text('unchanged')
 def read_bound(self,root,ref):
  if ref==FIXED_GRANT:return canon({'version':'r6-one-off-codex-catalog-gateway-grant-v2','binary':{'path':str(self.bin),'bytes':self.bin.stat().st_size,'sha256':hashlib.sha256(self.bin.read_bytes()).hexdigest()}})
  if ref==FIXED_REVIEW:return canon({'verdict':'CLEAN_GATEWAY_CATALOG_ONLY'})
  return b'bound'
 def patches(self):return (mock.patch.object(catalog,'_read_bound',side_effect=self.read_bound),mock.patch.object(gateway,'_production_endpoint',return_value=self.up.endpoint),mock.patch.dict(os.environ,{'HOME':str(self.global_home)},clear=False))
 def run(self,mode='nominal',timeout=3):
  material=bytearray(SECRET);auth=issue_transient_auth_token(material);parent=self.td/'custody'
  with self.patches()[0],self.patches()[1],self.patches()[2]:result=CatalogExecutor().execute(custody_parent=parent,execution_id='catalog.v8.'+mode,timeout_seconds=timeout,auth_token=auth)
  return result,auth,parent
class Tests(unittest.TestCase):
 def test_startup_first200_and_model_list_corroborate(self):
  with tempfile.TemporaryDirectory(dir=FIX) as d,Upstream() as up:
   h=Harness(Path(d),up);result,token,parent=h.run();self.assertEqual(result.receipt['status'],'PASS_FIRST_200_CORROBORATED');self.assertEqual(result.catalog.slugs,('gpt-6.1-sol',));self.assertEqual(result.catalog.body,up.body);self.assertEqual(len(up.requests),1);self.assertEqual(up.requests[0],(gateway.TARGET,'Bearer '+SECRET.decode()));self.assertTrue(token.wiped);self.assertTrue(result.receipt['contained_writes']['cleaned']);self.assertEqual((h.global_home/'sentinel').read_text(),'unchanged');self.assertFalse((parent/'catalog.v8.nominal').exists())
   dumped=json.dumps(result.receipt);self.assertNotIn(SECRET.decode(),dumped);self.assertNotIn('Authorization',dumped);self.assertNotIn('"body":',dumped);self.assertNotIn(SECRET,b''.join(p.read_bytes() for p in Path(d).rglob('*') if p.is_file()))
 def test_first200_authoritative_after_second409_and_rpc_failure(self):
  for mode in ('second','rpcfail'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory(dir=FIX) as d,Upstream() as up:
    result,_,_=Harness(Path(d),up).run(mode);self.assertEqual(result.receipt['status'],'PASS_FIRST_200_UNCORROBORATED');self.assertEqual(result.receipt['gateway']['first_200']['model_count'],1);self.assertEqual(len(up.requests),1)
    if mode=='second':self.assertEqual(result.receipt['gateway']['subsequent_rejections'],1)
 def test_all_subsequent_methods_409_without_forward(self):
  with tempfile.TemporaryDirectory(dir=FIX) as d,Upstream() as up:
   result,_,_=Harness(Path(d),up).run('alternate');self.assertEqual(result.receipt['gateway']['local_requests'],4);self.assertEqual(result.receipt['gateway']['subsequent_rejections'],3);self.assertEqual(result.receipt['gateway']['provider_forwards'],1);self.assertEqual(len(up.requests),1)
 def test_malformed_duplicate_oversize_stop(self):
  cases=(b'{bad',b'{"models":[{"slug":"x"},{"slug":"x"}]}',b'{"models":['+b' '*gateway.MAX_UPSTREAM_BODY+b']}')
  for body in cases:
   with self.subTest(size=len(body)),tempfile.TemporaryDirectory(dir=FIX) as d,Upstream(body) as up:
    result,_,_=Harness(Path(d),up).run();self.assertEqual(result.receipt['status'],'STOP_NO_VALID_FIRST_200');self.assertFalse(result.receipt['gateway']['first_200']['captured'])
 def test_wrong_route_body_timeout_and_exact_rpc_flags(self):
  for mode in ('wrongpath','wrongbody','inittimeout','id2timeout','boolid'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory(dir=FIX) as d,Upstream() as up:
    result,_,parent=Harness(Path(d),up).run(mode,timeout=1 if mode=='id2timeout' else .25);self.assertTrue(result.receipt['process']['cleanup']['group_gone']);self.assertTrue(result.receipt['gateway']['listener_closed']);self.assertFalse((parent/('catalog.v8.'+mode)).exists())
    if mode.startswith('wrong'):self.assertEqual(len(up.requests),0)
    if mode in ('inittimeout','boolid'):self.assertEqual(result.receipt['rpc']['initialize_sent'],True);self.assertEqual(result.receipt['rpc']['initialized_sent'],False);self.assertEqual(result.receipt['rpc']['model_list_sent'],False)
    if mode=='id2timeout':self.assertTrue(result.receipt['rpc']['initialized_sent'] and result.receipt['rpc']['model_list_sent'])
 def test_default_deny_forged_token_and_private_parent(self):
  class Forged:
   wiped=True
   def _consume(self):return bytearray(SECRET)
  with tempfile.TemporaryDirectory(dir=FIX) as d,Upstream() as up:
   h=Harness(Path(d),up)
   with h.patches()[0],h.patches()[1],h.patches()[2]:
    with self.assertRaises(CatalogError):CatalogExecutor().execute(custody_parent=Path(d)/'none',execution_id='catalog.v8.none',timeout_seconds=1)
   with h.patches()[0],h.patches()[1],h.patches()[2]:
    with self.assertRaises(CatalogError):CatalogExecutor().execute(custody_parent=Path(d)/'forged',execution_id='catalog.v8.forged',timeout_seconds=1,auth_token=Forged())
   shared=Path(d)/'shared';shared.mkdir(mode=0o755);before=shared.stat().st_mode&0o777;auth=issue_transient_auth_token(bytearray(SECRET))
   with h.patches()[0],h.patches()[1],h.patches()[2]:
    with self.assertRaises(CatalogError):CatalogExecutor().execute(custody_parent=shared,execution_id='catalog.v8.shared',timeout_seconds=1,auth_token=auth)
   self.assertEqual(shared.stat().st_mode&0o777,before);self.assertFalse(hasattr(package,'TransientAuthToken'));self.assertFalse((ROOT/'shared/job_runtime/candidates/r6_one_off_codex_catalog_v1/auth.py').exists());import shared.job_runtime.candidates.r6_one_off_codex_catalog_v1.integration as integration;self.assertFalse(hasattr(integration,'_issue'))
 def test_online_transport_never_used_and_exact_bindings(self):
  with tempfile.TemporaryDirectory(dir=FIX) as d,Upstream() as up,mock.patch.object(gateway.http.client,'HTTPSConnection',side_effect=AssertionError('online route')):
   result,_,_=Harness(Path(d),up).run();self.assertTrue(result.receipt['gateway']['first_200']['captured'])
  for ref in (FIXED_GRANT,FIXED_REVIEW)+HISTORY+(SOURCE_RESEARCH,):
   p=ROOT/ref[0];raw=p.read_bytes();self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),ref[1:])
  self.assertEqual(V7_PRODUCER[2][:4],'11cf');self.assertEqual(V7_REVIEW[2][:4],'7f84')
 def test_parser_duplicate_schema_unique_and_size(self):
  good=b'{"models":[{"slug":"a"},{"slug":"b"}]}';parsed=gateway.parse_provider_catalog(good);self.assertEqual(parsed.slugs,('a','b'));self.assertEqual(parsed.body,good)
  for bad in (b'{"models":[],"models":[]}',b'{"models":[]}',b'{"models":[{"slug":""}]}',b'{"models":[{"slug":"a"},{"slug":"a"}]}',b'x'*(gateway.MAX_UPSTREAM_BODY+1)):
   with self.assertRaises(gateway.GatewayError):gateway.parse_provider_catalog(bad)
 def test_imports_parse_and_no_callback_auth_surface(self):
  for p in (ROOT/'shared/job_runtime/candidates/r6_one_off_codex_catalog_v1').glob('*.py'):ast.parse(p.read_text())
  self.assertNotIn('auth_material_provider',(ROOT/'shared/job_runtime/candidates/r6_one_off_codex_catalog_v1/catalog.py').read_text())
class SchemaTests(unittest.TestCase):
 def test_draft_closed_semantic_and_all_receipts(self):
  try:from jsonschema import Draft202012Validator,ValidationError
  except ImportError:self.skipTest('jsonschema unavailable')
  schema=json.loads((ROOT/'shared/job_runtime/candidates/r6_one_off_codex_catalog_v1/schemas/catalog-execution-receipt-v8.schema.json').read_text());Draft202012Validator.check_schema(schema);validator=Draft202012Validator(schema)
  def walk(v):
   if isinstance(v,dict):
    if v.get('type')=='object':self.assertFalse(v.get('additionalProperties',True));self.assertFalse(v.get('unevaluatedProperties',True))
    for x in v.values():walk(x)
   elif isinstance(v,list):
    for x in v:walk(x)
  walk(schema);receipts=[]
  for mode in ('nominal','second','wrongpath','inittimeout'):
   with tempfile.TemporaryDirectory(dir=FIX) as d,Upstream() as up:result,_,_=Harness(Path(d),up).run(mode,timeout=.25 if mode=='inittimeout' else 3);validator.validate(result.receipt);receipts.append(result.receipt)
  bad=copy.deepcopy(receipts[0]);bad['gateway']['first_200']['captured']=False
  with self.assertRaises(ValidationError):validator.validate(bad)
  bad=copy.deepcopy(receipts[1]);bad['rpc']['model_list_corroborated']=True
  with self.assertRaises(ValidationError):validator.validate(bad)
  for field,value in (('status',502),('upstream_status',None)):
   bad=copy.deepcopy(receipts[0]);bad['gateway'][field]=value
   with self.assertRaises(ValidationError):validator.validate(bad)
if __name__=='__main__':unittest.main()
