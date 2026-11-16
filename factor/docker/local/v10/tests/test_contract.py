import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from factor.docker.local.v10 import lifecycle as l
class R:
 def __init__(self,code=0,out=b''):self.returncode=code;self.stdout=out;self.stderr=b''
class Fake:
 def __init__(self,fail=None):self.calls=[];self.fail=fail
 def __call__(self,argv,timeout=120):
  self.calls.append(argv);s=' '.join(argv)
  if self.fail and self.fail in s:return R(7)
  if 'image inspect' in s:return R(0,b'sha256:' + b'a'*64 + b'\n')
  if ' wait ' in ' '+s+' ':return R(0,b'0\n')
  if 'logs' in s:return R(0,b'{"status":"health-only"}\n')
  return R()
class Tests(unittest.TestCase):
 def test_profile_and_source_hashes(self):
  p=l.validate_profile(l.load(l.PROFILE_PATH));self.assertFalse(p['apply_allowed']);self.assertFalse(p['runnable']);self.assertEqual(p['reconciliation_evidence_sha256'],'95b18403e961557f3968407fb39a2c481ea751472039cb09ec14435c4eefc910')
 def test_exact_isolation_argv(self):
  p=l.load(l.PROFILE_PATH);c=l.commands(p,'sha256:'+'a'*64)['create'];text=' '.join(c)
  for token in ('--context colima-factor-mining','--network none','--read-only','--cap-drop ALL','no-new-privileges=true','--pids-limit 128','--cpus 0.5','--memory 256m','--memory-swap 256m','--restart no','--log-driver local','max-size=10m','max-file=3'):self.assertIn(token,text)
  for token in ('--rm','docker.sock','--privileged','--mount','--secret'):self.assertNotIn(token,text)
 def test_build_requires_pull_then_no_pull(self):
  c=l.commands(l.load(l.PROFILE_PATH));self.assertIn('pull',c['pull']);self.assertIn('--pull=false',c['build']);self.assertIn('sha256:a83ba18a', ' '.join(c['pull']))
 def test_selected_disabled_default(self):self.assertEqual(l.execute()['status'],'selected-disabled')
 def test_success_receipt_before_remove(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);(root/'factor/runtime/local').mkdir(parents=True);f=Fake()
   with patch.object(l,'ROOT',root),patch.object(l,'DOCKER_CONFIG',root/'factor/runtime/local/docker-config'):
    out=l._execute_for_test(f,root/'factor/runtime/local/receipt.json')
   self.assertEqual(out['status'],'success');self.assertEqual(json.loads((root/'factor/runtime/local/receipt.json').read_text())['remove_returncode'],0);self.assertIn('rm',f.calls[-1])
 def test_postcreate_failure_unknown_no_remove(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);(root/'factor/runtime/local').mkdir(parents=True);f=Fake('start')
   with patch.object(l,'ROOT',root),patch.object(l,'DOCKER_CONFIG',root/'factor/runtime/local/docker-config'):
    out=l._execute_for_test(f,root/'factor/runtime/local/receipt.json')
   self.assertEqual(out['status'],'unknown');self.assertFalse(any('rm' in x for x in f.calls))
 def test_worker_blocks_execution(self):
  from factor.docker.local.v10 import health_worker as w
  self.assertEqual(w.IDENTITY['code'],'SCIENTIFIC_EXECUTION_UNAVAILABLE')
if __name__=='__main__':unittest.main()
