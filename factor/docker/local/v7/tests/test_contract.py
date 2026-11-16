import json,os,shutil,signal,socket,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from factor.docker.local.v7 import launcher
MAIN=Path('/Users/bytedance/Desktop/Trading Agent');PLAN=MAIN/'docs/plans/factor-mining-local-docker-activation-v7-20261106.md'
class V7Tests(unittest.TestCase):
 def ws(self,t):
  w=Path(t).resolve()
  for ver in ('v6','v5'):
   shutil.copytree(MAIN/f'factor/docker/local/{ver}',w/f'factor/docker/local/{ver}',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  for rel in ('factor/docker/local/v4/runtime-profile-v4.json','factor/docker/local/v2/installation-receipt.json','factor/docker/local/v2/runtime-profile-v2.json'):
   p=w/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(MAIN/rel,p)
  return w
 def status(self,e,b,r=True):return {'profile':'factor-mining','running':r,'context':'colima-factor-mining','endpoint':e['COLIMA_HOME']+'/sock','global_context_before':b,'global_context_after':b}
 def call(self,w,run=lambda *a:{'returncode':0,'timed_out':False},probe=None,before=None):
  with patch.object(launcher.v4,'SOCKET_SUFFIX',Path('s')):return launcher._activate_for_test(w,run,probe or (lambda e,h,b:self.status(e,b)),lambda h:'default',before)
 def test_default_public_fixed_no_injection(self):
  import inspect
  self.assertNotIn('runner',inspect.signature(launcher.activate).parameters);self.assertEqual(launcher.activate(MAIN)['status'],'selected-disabled')
 def test_exact_path_cwd_real_pwd(self):
  with tempfile.TemporaryDirectory() as t:
   w=self.ws(t);r=launcher._run_colima(['/bin/pwd','-P'],{},w,10,1);self.assertEqual(r,{'returncode':0,'timed_out':False})
 def test_success_and_home_root(self):
  with tempfile.TemporaryDirectory() as t:
   w=self.ws(t);seen={}
   def run(a,e,c,to,g):seen['cwd']=c;seen['env']=e;return {'returncode':0,'timed_out':False}
   r=self.call(w,run);self.assertEqual(r['status'],'success');self.assertEqual(seen['cwd'],w);self.assertIn('HOME',seen['env']);self.assertTrue((w/'factor/runtime/local/home').is_dir())
 def test_timeout_absent_status_still_unknown(self):
  with tempfile.TemporaryDirectory() as t:
   w=self.ws(t);r=self.call(w,lambda *a:{'returncode':None,'timed_out':True},lambda e,h,b:self.status(e,b,False));self.assertEqual(r['status'],'unknown');self.assertTrue(r['retained_roots'])
 def test_context_mismatch_unknown(self):
  with tempfile.TemporaryDirectory() as t:
   w=self.ws(t);r=self.call(w,probe=lambda e,h,b:{**self.status(e,b),'context':'wrong'});self.assertEqual(r['status'],'unknown')
 def test_workspace_rename_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   w=self.ws(t);called=[];r=self.call(w,lambda *a:called.append(1),before=lambda p:p.rename(p.with_name(p.name+'x')));self.assertEqual(r['status'],'failed');self.assertEqual(called,[])
 def test_fixed_probe_rejects_nonzero_even_parseable(self):
  e={'COLIMA_HOME':'/x','COLIMA_CACHE_HOME':'/y','COLIMA_PROFILE':'factor-mining','DOCKER_CONFIG':'/z','HOME':'/h','PATH':launcher.v6.PATH_VALUE}
  fake=type('R',(),{'returncode':1,'stdout':b'{"profile":"factor-mining","status":"Running"}','stderr':b''})()
  with patch.object(launcher,'_command',return_value=fake),self.assertRaisesRegex(launcher.V7ContractError,'PROBE_RC'):launcher._probe(e,'/h','default')
 def test_probe_rejects_traversal_and_symlink_escape(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);home=root/'home';home.mkdir();outside=root/'outside';outside.mkdir();sock=outside/'s';s=socket.socket(socket.AF_UNIX);s.bind(str(sock));link=home/'link';link.symlink_to(outside,target_is_directory=True)
   col=type('R',(),{'returncode':0,'stdout':b'{"profile":"factor-mining","status":"Running"}','stderr':b''})();ctx=type('R',(),{'returncode':0,'stdout':json.dumps([{'Endpoints':{'docker':{'Host':'unix://'+str(link/'s')}}}]).encode(),'stderr':b''})()
   e={'COLIMA_HOME':str(home),'DOCKER_CONFIG':str(root/'dc'),'HOME':str(root/'h'),'PATH':launcher.v6.PATH_VALUE}
   with patch.object(launcher,'_command',side_effect=[col,ctx]),patch.object(launcher,'_global',return_value='default'),self.assertRaisesRegex(launcher.V7ContractError,'CONTAINMENT'):launcher._probe(e,'/h','default')
   s.close()
 def test_probe_accepts_existing_contained_socket(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);home=root/'home';home.mkdir();sock=home/'s';s=socket.socket(socket.AF_UNIX);s.bind(str(sock));col=type('R',(),{'returncode':0,'stdout':b'{"profile":"factor-mining","status":"Running"}','stderr':b''})();ctx=type('R',(),{'returncode':0,'stdout':json.dumps([{'Endpoints':{'docker':{'Host':'unix://'+str(sock)}}}]).encode(),'stderr':b''})();e={'COLIMA_HOME':str(home),'DOCKER_CONFIG':str(root/'dc'),'HOME':str(root/'h'),'PATH':launcher.v6.PATH_VALUE}
   with patch.object(launcher,'_command',side_effect=[col,ctx]),patch.object(launcher,'_global',return_value='default'):self.assertTrue(launcher._probe(e,'/h','default')['running'])
   s.close()
 def test_timeout_always_kills_original_group_after_leader_exits(self):
  with tempfile.TemporaryDirectory() as t:
   pidfile=Path(t)/'pid';script='import os,signal,sys,time\np=os.fork()\nif p==0:\n signal.signal(signal.SIGTERM,signal.SIG_IGN);open(sys.argv[1],"w").write(str(os.getpid()));time.sleep(60)\nelse:\n time.sleep(60)'
   r=launcher._run_colima([sys.executable,'-c',script,str(pidfile)],{},Path(t),1,1);self.assertTrue(r['timed_out']);pid=int(pidfile.read_text())
   gone=False
   for _ in range(30):
    try:os.kill(pid,0)
    except ProcessLookupError:gone=True;break
    time.sleep(.1)
   self.assertTrue(gone)
 def test_v6_v5_drift_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   w=self.ws(t);p=w/'factor/docker/local/v6/runtime-profile-v6.json';p.write_bytes(p.read_bytes()+b'\n')
   with self.assertRaises(launcher.V7ContractError):launcher.validate_profile(launcher.load(launcher.PROFILE_PATH),w)
 def test_threat_nonclaim_and_plan(self):
  p=launcher.validate_profile(launcher.load(launcher.PROFILE_PATH),MAIN);self.assertFalse(p['threat_model']['malicious_same_user_after_check_prevented']);text=PLAN.read_text().lower();self.assertIn('exact workspace pathname',text);self.assertIn('same-user',text)
if __name__=='__main__':unittest.main()
