import json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from factor.docker.local.v6 import launcher
MAIN=Path('/Users/bytedance/Desktop/Trading Agent');PLAN=MAIN/'docs/plans/factor-mining-local-docker-activation-v6-20261106.md'
class V6Tests(unittest.TestCase):
 def ws(self,t):
  w=Path(t).resolve()
  for rel in ('factor/docker/local/v5/runtime-profile-v5.json','factor/docker/local/v4/runtime-profile-v4.json','factor/docker/local/v2/installation-receipt.json','factor/docker/local/v2/runtime-profile-v2.json'):
   p=w/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(MAIN/rel,p)
  # tree binding requires complete v5
  shutil.rmtree(w/'factor/docker/local/v5');shutil.copytree(MAIN/'factor/docker/local/v5',w/'factor/docker/local/v5',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  return w
 def status(self,env,before,running=True,context='colima-factor-mining'):
  return {'profile':'factor-mining','running':running,'context':context,'endpoint':'unix://'+env['COLIMA_HOME']+'/socket','global_context_before':before,'global_context_after':before}
 def call(self,w,run=lambda *a:{'returncode':0,'timed_out':False},probe=None,before=None):
  with patch.object(launcher.v4,'SOCKET_SUFFIX',Path('s')):
   return launcher._activate_for_test(w,runner=run,probe=probe or (lambda e,h,b:self.status(e,b)),global_context=lambda h:'default',before_spawn=before)
 def test_default_public_has_no_injection_and_is_disabled(self):
  import inspect
  self.assertNotIn('runner',inspect.signature(launcher.activate).parameters)
  r=launcher.activate(MAIN);self.assertEqual(r['status'],'selected-disabled');self.assertFalse(r['apply_allowed'])
 def test_success_exact_env_home_argv_status(self):
  with tempfile.TemporaryDirectory() as t:
   w=self.ws(t);seen={}
   def run(a,e,fd,to,g):seen.update(a=a,e=e,fd=fd,to=to,g=g);return {'returncode':0,'timed_out':False}
   r=self.call(w,run);self.assertEqual(r['status'],'success');self.assertEqual(set(seen['e']),{'COLIMA_HOME','COLIMA_CACHE_HOME','COLIMA_PROFILE','DOCKER_CONFIG','HOME','PATH'});self.assertEqual(seen['a'],launcher.START_ARGV)
 def test_home_is_private_transaction_root_and_no_global_fallback(self):
  with tempfile.TemporaryDirectory() as t:
   w=self.ws(t);r=self.call(w);self.assertEqual(r['status'],'success');p=w/'factor/runtime/local/home';self.assertTrue(p.is_dir());self.assertEqual(p.stat().st_mode&0o777,0o700)
 def test_timeout_always_unknown_even_absent(self):
  with tempfile.TemporaryDirectory() as t:
   w=self.ws(t);r=self.call(w,lambda *a:{'returncode':None,'timed_out':True},lambda e,h,b:self.status(e,b,False));self.assertEqual(r['status'],'unknown');self.assertTrue(r['retained_roots'])
 def test_nonzero_absent_failed_cleanup(self):
  with tempfile.TemporaryDirectory() as t:
   w=self.ws(t);r=self.call(w,lambda *a:{'returncode':3,'timed_out':False},lambda e,h,b:self.status(e,b,False));self.assertEqual(r['status'],'failed');self.assertTrue(r['cleanup_complete'])
 def test_context_or_global_mismatch_unknown(self):
  for probe in (lambda e,h,b:self.status(e,b,True,'wrong'),lambda e,h,b:{**self.status(e,b),'global_context_after':'changed'}):
   with tempfile.TemporaryDirectory() as t:self.assertEqual(self.call(self.ws(t),probe=probe)['status'],'unknown')
 def test_probe_fabrication_cannot_enter_public_api(self):
  with tempfile.TemporaryDirectory() as t:
   with self.assertRaises(TypeError):launcher.activate(self.ws(t),apply=True,capability=launcher.CAPABILITY,parent_approved=True,probe=lambda:True)
 def test_workspace_rename_rejected_before_runner(self):
  with tempfile.TemporaryDirectory() as t:
   w=self.ws(t);called=[]
   def tamper(root):root.rename(root.with_name(root.name+'x'))
   r=self.call(w,lambda *a:called.append(1),before=tamper);self.assertEqual(r['status'],'failed');self.assertEqual(called,[])
 def test_partial_root_failure_and_nonempty_preserved(self):
  with tempfile.TemporaryDirectory() as t:
   w=self.ws(t);p=w/'.c';p.mkdir(mode=0o700);(p/'x').write_text('x');r=self.call(w);self.assertEqual(r['status'],'failed');self.assertTrue((p/'x').exists())
 def test_predecessor_drift(self):
  with tempfile.TemporaryDirectory() as t:
   w=self.ws(t);p=w/'factor/docker/local/v2/runtime-profile-v2.json';p.write_bytes(p.read_bytes()+b'\n')
   with self.assertRaises(launcher.V6ContractError):launcher.validate_profile(launcher.load_json(launcher.PROFILE_PATH),w)
 def test_fixed_runner_timeout_kills_group(self):
  proc=Mock();proc.pid=123;proc.wait.side_effect=[subprocess.TimeoutExpired('x',1),None]
  with patch('factor.docker.local.v6.launcher.subprocess.Popen',return_value=proc) as pop,patch('factor.docker.local.v6.launcher.os.killpg') as kill:
   r=launcher._run_command(['x'],{},5,1,1);self.assertTrue(r['timed_out']);pop.assert_called_once();self.assertTrue(pop.call_args.kwargs['start_new_session']);kill.assert_called_once_with(123,15)
 def test_cli_defaults_selected_disabled_and_has_no_injection_flags(self):
  r=subprocess.run([sys.executable,'-B','-m','factor.docker.local.v6.launcher'],cwd=MAIN,capture_output=True,text=True,timeout=10);self.assertEqual(r.returncode,0,r.stderr);payload=json.loads(r.stdout);self.assertEqual(payload['status'],'selected-disabled');self.assertFalse(payload['apply_allowed'])
 def test_profile_threat_nonclaim_and_plan(self):
  p=launcher.validate_profile(launcher.load_json(launcher.PROFILE_PATH),MAIN);self.assertFalse(p['threat_model']['malicious_same_user_mutation_after_check_prevented']);text=PLAN.read_text().lower();self.assertIn('same-user',text);self.assertIn('timeout',text)
if __name__=='__main__':unittest.main()
