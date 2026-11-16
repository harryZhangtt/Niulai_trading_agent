import json,socket,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from factor.docker.local.v8 import launcher
MAIN=Path('/Users/bytedance/Desktop/Trading Agent');PLAN=MAIN/'docs/plans/factor-mining-local-docker-activation-v8-20261106.md'
class V8Tests(unittest.TestCase):
 def env_socket(self,temp):
  root=Path(temp);home=root/'home';home.mkdir();sock=home/'docker.sock';s=socket.socket(socket.AF_UNIX);s.bind(str(sock));env={'COLIMA_HOME':str(home),'COLIMA_CACHE_HOME':str(root/'cache'),'COLIMA_PROFILE':'factor-mining','DOCKER_CONFIG':str(root/'config'),'HOME':str(root/'txhome'),'PATH':launcher.v7.v6.PATH_VALUE};return env,sock,s
 def result(self,raw,rc=0):return SimpleNamespace(returncode=rc,stdout=raw,stderr=b'')
 def probe(self,colima,docker):
  with tempfile.TemporaryDirectory() as t:
   env,sock,s=self.env_socket(t);context=docker.replace(b'$SOCKET',str(sock).encode())
   try:
    with patch.object(launcher.v7,'_command',side_effect=[self.result(colima),self.result(context)]),patch.object(launcher.v7,'_global',return_value='default'):
     return launcher._probe(env,'/host','default')
   finally:s.close()
 def test_valid_exact_outputs_accepted(self):
  c=b'{"profile":"factor-mining","status":"Running"}';d=b'[{"Endpoints":{"docker":{"Host":"unix://$SOCKET"}}}]';self.assertTrue(self.probe(c,d)['running'])
 def test_colima_duplicate_last_key_wins_rejected(self):
  c=b'{"profile":"wrong","profile":"factor-mining","status":"Running"}';d=b'[{"Endpoints":{"docker":{"Host":"unix://$SOCKET"}}}]'
  with self.assertRaisesRegex(launcher.V8ContractError,'DUPLICATE'):self.probe(c,d)
 def test_docker_duplicate_last_key_wins_rejected(self):
  c=b'{"profile":"factor-mining","status":"Running"}';d=b'[{"Endpoints":{"docker":{"Host":"unix:///outside","Host":"unix://$SOCKET"}}}]'
  with self.assertRaisesRegex(launcher.V8ContractError,'DUPLICATE'):self.probe(c,d)
 def test_nonfinite_rejected_for_both_outputs(self):
  goodc=b'{"profile":"factor-mining","status":"Running"}';goodd=b'[{"Endpoints":{"docker":{"Host":"unix://$SOCKET"}}}]'
  for token in (b'NaN',b'Infinity',b'-Infinity'):
   with self.subTest(token=token),self.assertRaisesRegex(launcher.V8ContractError,'NONFINITE'):self.probe(b'{"profile":"factor-mining","status":"Running","x":'+token+b'}',goodd)
   with self.subTest(token=token),self.assertRaisesRegex(launcher.V8ContractError,'NONFINITE'):self.probe(goodc,b'[{"Endpoints":{"docker":{"Host":"unix://$SOCKET"}},"x":'+token+b'}]')
 def test_oversized_rejected_before_decode(self):
  with self.assertRaisesRegex(launcher.V8ContractError,'SIZE'):launcher._strict(b' '*launcher.MAX_BYTES+b'{}','COLIMA')
 def test_trailing_and_malformed_rejected(self):
  for raw in (b'{} {}',b'{',b'[1,]'):
   with self.subTest(raw=raw),self.assertRaises(launcher.V8ContractError):launcher._strict(raw,'COLIMA')
 def test_surrogate_and_invalid_utf8_rejected(self):
  for raw in (b'"\\ud800"',b'"\xff"'):
   with self.subTest(raw=raw),self.assertRaisesRegex(launcher.V8ContractError,'UNICODE'):launcher._strict(raw,'DOCKER')
 def test_nonzero_parseable_still_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   env,sock,s=self.env_socket(t)
   try:
    with patch.object(launcher.v7,'_command',side_effect=[self.result(b'{"profile":"factor-mining","status":"Running"}',1),self.result(json.dumps([{'Endpoints':{'docker':{'Host':'unix://'+str(sock)}}}]).encode())]),self.assertRaisesRegex(launcher.V8ContractError,'PROBE_RC'):launcher._probe(env,'/h','default')
   finally:s.close()
 def test_live_v7_chain_bound_and_profile_disabled(self):
  p=launcher.validate_profile(launcher.load(launcher.PROFILE_PATH),MAIN);self.assertFalse(p['runnable']);self.assertFalse(p['apply_allowed']);self.assertEqual(launcher.tree(MAIN/'factor/docker/local/v7'),launcher.EXPECTED['v7_tree_sha256'])
 def test_public_activation_has_no_injection(self):
  import inspect
  self.assertNotIn('probe',inspect.signature(launcher.activate).parameters);self.assertEqual(launcher.activate(MAIN)['status'],'selected-disabled')
 def test_plan_documents_exact_delta(self):
  text=PLAN.read_text().lower()
  for phrase in ('duplicate','nan/infinity','surrogate','trailing','65,536'):self.assertIn(phrase,text)
if __name__=='__main__':unittest.main()
