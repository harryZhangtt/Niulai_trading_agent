from __future__ import annotations
import copy,hashlib,json,os,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest import mock
from shared.job_runtime.engine import Engine
from shared.job_runtime.prompt_custody import PromptArtifactDescriptorV1
from shared.job_runtime.provider_contract import FailureKind,Phase,ProviderResultV1,ReplayContractV1,ReplayEffect,ResultStatus,Submission,TerminalProof
from shared.job_runtime.retry_policy import RetryPolicyV2
from shared.job_runtime.candidates.r6_data_quality_fable_allocation_integration_v1 import integration as module
from shared.job_runtime.candidates.r6_data_quality_fable_allocation_integration_v1.integration import IntegrationError,default_integrate,run_integration,validate_integration
from shared.job_runtime.candidates.r6_data_quality_fable_adapter_v1.adapter import DESIGN_SHA256,INPUTS_SHA256,JOB_IDS
from shared.job_runtime.candidates.r6_data_quality_fable_ab_v1.contracts import CELL_ORDER,DQ_CHECKS,FROZEN_INPUTS,MODEL_ID,sha256_json
ROOT=Path(__file__).resolve().parents[5];FIX=ROOT/'shared/job_runtime/tests/fixtures';SPEC=json.loads((FIX/'r6_data_quality_fable_allocation_integration_v1/integration-v1.json').read_text());ALLOCATION=json.loads((FIX/'r6_data_quality_fable_allocation_bridge_v1/allocation-v1.json').read_text());QUIESCENCE={"engine_closed":True,"active_service":False,"sidecars_absent":True};UTC=timezone.utc
def checks():return [{"name":n,"status":"PASS","code":"CHECK_PASS"} for n in DQ_CHECKS]
def provider_result(index,context):
 receipt={"version":1,"design_sha256":DESIGN_SHA256,"cell_id":CELL_ORDER[index],"configured_model":MODEL_ID,"provider_reported_model":MODEL_ID,"inputs_sha256":INPUTS_SHA256,"terminal_state":"PASS","terminal_ascii":"integration-sanitized-"+CELL_ORDER[index],"dq_checks":checks() if index else None};return ProviderResultV1('claude_host',context['operation_id'],Phase.TERMINAL,Submission.DEFINITELY_SUBMITTED,TerminalProof.VERIFIED,ResultStatus.SUCCEEDED,'INTEGRATION_FIXTURE_PASS',failure_kind=FailureKind.NONE,receipt=receipt)
def thaw(value):
 if hasattr(value,'items'):return {k:thaw(v) for k,v in value.items()}
 if isinstance(value,tuple):return [thaw(v) for v in value]
 return value
def expectation(path):
 m=path.stat();raw=path.read_bytes();return {"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"st_dev":m.st_dev,"st_ino":m.st_ino,"st_mtime_ns":m.st_mtime_ns}
class IntegrationTests(unittest.TestCase):
 def setUp(self):
  private=FIX/'r6_data_quality_fable_allocation_integration_v1/.runtime';private.mkdir(mode=0o700,parents=True,exist_ok=True);self.tmp=tempfile.TemporaryDirectory(dir=private);self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.now=datetime(2026,11,11,12,0,tzinfo=UTC)
 def engine(self,name='engine'):
  sha=FROZEN_INPUTS['prompt_sha256'];artifact=PromptArtifactDescriptorV1(1,'pa1:sha256:'+sha+':1',sha,1,'b'*64,'fable-adapter-fixture','native_v1');jobs=[{'id':JOB_IDS[i],'enabled':True,'replay_safe':False,'schedule':{'kind':'interval','seconds':60,'grace_seconds':120},'_provider':'claude_host','_replay_contract':ReplayContractV1(ReplayEffect.NONE,(Phase.NOT_STARTED,),'scope/integration-'+str(i)),'_retry_policy':RetryPolicyV2(1,1,1),'_prompt_artifact':artifact} for i in range(2)];engine=Engine(self.root/'.job-runtime'/name,jobs,{'max_attempts':1,'backoff_seconds':1,'max_backoff_seconds':1},lambda job,ctx:provider_result(JOB_IDS.index(job['id']),ctx),workspace_root=self.root,clock=lambda:self.now,max_workers=1);engine.tick(self.now);return engine
 def execute(self,engine=None,root=None,**kw):
  engine=engine or self.engine();return run_integration(kw.pop('spec',SPEC),ALLOCATION,kw.pop('expect',expectation(engine.path)),kw.pop('quiescence',QUIESCENCE),kw.pop('database',engine.path),root or self.root/'bundles')
 def test_default_and_frozen_spec_inactive(self):
  validate_integration(copy.deepcopy(SPEC));value=default_integrate();self.assertFalse(value['activation']);self.assertFalse(value['countable']);self.assertTrue(all(v==0 for v in value['effects'].values()))
 def test_actual_closed_engine_nominal_bridge_adapter_once_and_immutable_receipt(self):
  engine=self.engine();before=(hashlib.sha256(engine.path.read_bytes()).hexdigest(),engine.path.stat().st_mtime_ns);bridge_calls=[];adapter_calls=[];real_bridge=module.read_allocation_pair;real_adapter=module.adapt_engine_provider_results
  with mock.patch.object(module,'read_allocation_pair',side_effect=lambda *a,**k:(bridge_calls.append(1),real_bridge(*a,**k))[1]),mock.patch.object(module,'adapt_engine_provider_results',side_effect=lambda *a,**k:(adapter_calls.append(1),real_adapter(*a,**k))[1]):out=self.execute(engine)
  self.assertEqual((bridge_calls,adapter_calls),([1],[1]));r=out.receipt;self.assertEqual((r['denominator_count'],r['publication_attempts'],r['countable']),(2,0,False));self.assertEqual(r['source_db_sha256'],expectation(engine.path)['sha256']);self.assertEqual(r['snapshot_sha256'],r['source_db_sha256']);self.assertEqual(len(r['bundles']),2);self.assertEqual(before,(hashlib.sha256(engine.path.read_bytes()).hexdigest(),engine.path.stat().st_mtime_ns))
  with self.assertRaises(TypeError):r['status']='changed'
  self.assertEqual(r['result_sha256'],sha256_json(thaw(out.result)))
 def test_false_missing_quiescence_and_stale_expectation_fail_without_bundle(self):
  engine=self.engine();root=self.root/'bundle-fail'
  for q in ({},dict(QUIESCENCE,active_service=True)):
   with self.assertRaises(IntegrationError):self.execute(engine,root,quiescence=q)
   self.assertFalse(root.exists())
  stale=expectation(engine.path);stale['sha256']='0'*64
  with self.assertRaises(IntegrationError):self.execute(engine,root,expect=stale)
  self.assertFalse(root.exists())
 def test_database_path_and_sidecar_snapshot_errors_leave_no_bundle(self):
  engine=self.engine();root=self.root/'bundle-path'
  with self.assertRaises(IntegrationError):self.execute(engine,root,database=self.root/'missing.sqlite')
  self.assertFalse(root.exists());side=Path(str(engine.path)+'-wal');side.write_bytes(b'x')
  try:
   with self.assertRaises(IntegrationError):self.execute(engine,root)
  finally:side.unlink()
  self.assertFalse(root.exists())
 def test_bridge_adapter_closure_and_integration_digest_drift_reject(self):
  engine=self.engine();root=self.root/'bundle-drift'
  for key,value in [('bridge_closure_sha256','0'*64),('adapter_closure_sha256','0'*64),('activation',True),('logical_database_id','other')]:
   spec=copy.deepcopy(SPEC);spec[key]=value
   with self.assertRaises(IntegrationError):self.execute(engine,root,spec=spec)
   self.assertFalse(root.exists())
 def test_partial_adapter_failure_cleans_owned_root(self):
  engine=self.engine();root=self.root/'partial'
  def partial(*args,**kwargs):
   cell=root/CELL_ORDER[0];cell.mkdir(parents=True);(cell/'partial').write_bytes(b'x');raise ValueError('injected')
  with mock.patch.object(module,'adapt_engine_provider_results',side_effect=partial):
   with self.assertRaisesRegex(IntegrationError,'INTEGRATION_FAILED'):self.execute(engine,root)
  self.assertFalse(root.exists())
 def test_missing_bundle_after_adapter_cleans_owned_root(self):
  engine=self.engine();root=self.root/'missing-bundle';real=module.adapt_engine_provider_results
  def missing(*args,**kwargs):
   result=real(*args,**kwargs);(root/CELL_ORDER[1]/(CELL_ORDER[1]+'.bundle.json')).unlink();return result
  with mock.patch.object(module,'adapt_engine_provider_results',side_effect=missing):
   with self.assertRaises(IntegrationError):self.execute(engine,root)
  self.assertFalse(root.exists())
 def test_preexisting_bundle_root_rejects_without_change(self):
  engine=self.engine();root=self.root/'existing';root.mkdir();marker=root/'marker';marker.write_bytes(b'x')
  with self.assertRaisesRegex(IntegrationError,'INTEGRATION_BUNDLE_ROOT_NOT_FRESH'):self.execute(engine,root)
  self.assertEqual(marker.read_bytes(),b'x')
 def test_raw_post_adapter_tamper_and_valid_result_mismatch_cleanup(self):
  for mode in ('raw','result'):
   engine=self.engine('tamper-'+mode);root=self.root/('tamper-out-'+mode);real=module.adapt_engine_provider_results
   def changed(*args,which=mode,**kwargs):
    result=real(*args,**kwargs)
    if which=='raw':(root/CELL_ORDER[0]/(CELL_ORDER[0]+'.raw')).write_bytes(b'tampered')
    else:
     result=copy.deepcopy(result);result['cells'][0]['raw_ref']['sha256']='0'*64
    return result
   with mock.patch.object(module,'adapt_engine_provider_results',side_effect=changed):
    with self.assertRaises(IntegrationError):self.execute(engine,root)
   self.assertFalse(root.exists())
 def test_root_and_parent_swap_symlink_and_mode_drift_reject_cleanup(self):
  engine=self.engine('root-swap');root=self.root/'root-swap-out';swapped=self.root/'root-swapped'
  def root_hook(stage,fd,name):
   if stage=='after_adapter':root.rename(swapped);os.symlink(swapped.name,root)
  with self.assertRaises(IntegrationError):run_integration(SPEC,ALLOCATION,expectation(engine.path),QUIESCENCE,engine.path,root,_test_hook=root_hook)
  self.assertFalse(root.exists());self.assertFalse(swapped.exists())
  engine=self.engine('parent-swap');parent=self.root/'owned-parent';parent.mkdir(mode=0o700);root=parent/'bundles';old=self.root/'owned-parent-old'
  def parent_hook(stage,fd,name):
   if stage=='after_adapter':parent.rename(old);os.symlink(old.name,parent)
  try:
   with self.assertRaisesRegex(IntegrationError,'INTEGRATION_PARENT_SWAPPED'):run_integration(SPEC,ALLOCATION,expectation(engine.path),QUIESCENCE,engine.path,root,_test_hook=parent_hook)
  finally:
   if parent.is_symlink():parent.unlink()
   if old.exists():old.rename(parent)
  self.assertFalse((parent/'bundles').exists())
  engine=self.engine('mode-drift');root=self.root/'mode-out'
  def mode_hook(stage,fd,name):
   if stage=='after_adapter':os.chmod(root,0o755)
  with self.assertRaises(IntegrationError):run_integration(SPEC,ALLOCATION,expectation(engine.path),QUIESCENCE,engine.path,root,_test_hook=mode_hook)
  self.assertFalse(root.exists())
 def test_create_failure_root_symlink_and_cleanup_failure_receipt(self):
  engine=self.engine('create-fail');root=self.root/'create-out'
  with mock.patch.object(module.os,'mkdir',side_effect=PermissionError('injected')):
   with self.assertRaises(IntegrationError) as caught:self.execute(engine,root)
  self.assertFalse(root.exists());self.assertEqual(caught.exception.cleanup_receipt['status'],'NOT_CREATED')
  target=self.root/'target';target.mkdir();link=self.root/'link-root';os.symlink(target.name,link)
  with self.assertRaises(IntegrationError):self.execute(engine,link)
  self.assertTrue(link.is_symlink());link.unlink();target.rmdir()
  engine=self.engine('cleanup-fail');root=self.root/'cleanup-out'
  def partial(*args,**kwargs):
   cell=root/CELL_ORDER[0];cell.mkdir(parents=True);(cell/'partial').write_bytes(b'x');raise ValueError('original')
  real_unlink=module.os.unlink;calls=[0]
  def flaky(*args,**kwargs):
   calls[0]+=1
   if calls[0]==1:raise OSError('cleanup injected')
   return real_unlink(*args,**kwargs)
  real_cleanup=module._cleanup
  def scoped_cleanup(*args,**kwargs):
   with mock.patch.object(module.os,'unlink',side_effect=flaky):return real_cleanup(*args,**kwargs)
  with mock.patch.object(module,'adapt_engine_provider_results',side_effect=partial),mock.patch.object(module,'_cleanup',side_effect=scoped_cleanup):
   with self.assertRaisesRegex(IntegrationError,'INTEGRATION_FAILED') as caught:self.execute(engine,root)
  self.assertIn('CLEANUP_UNLINK',caught.exception.cleanup_receipt['errors']);self.assertFalse(caught.exception.cleanup_receipt['residue']);self.assertFalse(root.exists())
 def test_raw_identity_swap_while_held_rejects_and_cleans(self):
  engine=self.engine('identity-swap');root=self.root/'identity-out';fired=[False]
  def hook(stage,dirfd,name):
   if stage=='during_raw_read' and not fired[0]:
    fired[0]=True;os.rename(name,name+'.old',src_dir_fd=dirfd,dst_dir_fd=dirfd);fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=dirfd)
    try:os.write(fd,b'replacement');os.fsync(fd)
    finally:os.close(fd)
  with self.assertRaises(IntegrationError):run_integration(SPEC,ALLOCATION,expectation(engine.path),QUIESCENCE,engine.path,root,_test_hook=hook)
  self.assertFalse(root.exists())
 def test_final_barrier_rejects_late_root_cell_and_file_swaps(self):
  for mode in ('root','cell','file'):
   engine=self.engine('late-'+mode);root=self.root/('late-out-'+mode);fired=[False]
   def hook(stage,rootfd,name,which=mode):
    if stage!='before_final_barrier' or fired[0]:return
    fired[0]=True
    if which=='root':root.rename(root.with_name(root.name+'.old'));os.symlink(root.name+'.old',root)
    elif which=='cell':os.rename(CELL_ORDER[0],CELL_ORDER[0]+'.old',src_dir_fd=rootfd,dst_dir_fd=rootfd);os.symlink(CELL_ORDER[0]+'.old',CELL_ORDER[0],dir_fd=rootfd)
    else:
     cfd=os.open(CELL_ORDER[0],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=rootfd)
     try:
      raw=CELL_ORDER[0]+'.raw';os.rename(raw,raw+'.old',src_dir_fd=cfd,dst_dir_fd=cfd);fd=os.open(raw,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=cfd);os.write(fd,b'late');os.close(fd)
     finally:os.close(cfd)
   with self.assertRaises(IntegrationError):run_integration(SPEC,ALLOCATION,expectation(engine.path),QUIESCENCE,engine.path,root,_test_hook=hook)
   self.assertFalse(root.exists());self.assertFalse(root.with_name(root.name+'.old').exists())
 def test_final_barrier_rejects_extra_root_file_and_cell_directory(self):
  for mode in ('root-file','cell-dir'):
   engine=self.engine('extra-'+mode);root=self.root/('extra-out-'+mode)
   def hook(stage,rootfd,name,which=mode):
    if stage!='before_final_barrier':return
    if which=='root-file':fd=os.open('extra',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=rootfd);os.close(fd)
    else:
     cfd=os.open(CELL_ORDER[0],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=rootfd)
     try:os.mkdir('extra-dir',0o700,dir_fd=cfd)
     finally:os.close(cfd)
   with self.assertRaises(IntegrationError) as caught:run_integration(SPEC,ALLOCATION,expectation(engine.path),QUIESCENCE,engine.path,root,_test_hook=hook)
   self.assertFalse(root.exists(),(mode,dict(caught.exception.cleanup_receipt)))
 def test_creation_open_and_fstat_failure_cleanup_and_replacement_preservation(self):
  engine=self.engine('create-open');root=self.root/'create-open-out'
  with mock.patch.object(module,'_open_created_root',side_effect=OSError('open injected')):
   with self.assertRaises(IntegrationError) as caught:self.execute(engine,root)
  self.assertFalse(root.exists());self.assertFalse(caught.exception.cleanup_receipt['residue'])
  engine=self.engine('create-stat');root=self.root/'create-stat-out'
  with mock.patch.object(module,'_capture_created',side_effect=OSError('stat injected')):
   with self.assertRaises(IntegrationError) as caught:self.execute(engine,root)
  self.assertTrue(root.is_dir());receipt=caught.exception.cleanup_receipt;self.assertTrue(receipt['residue_unknown']);self.assertTrue(receipt['named_entry_present']);self.assertFalse(receipt['cleanup_complete']);self.assertIn('IDENTITY_UNAVAILABLE',receipt['errors']);root.rmdir()
  engine=self.engine('create-replace');root=self.root/'create-replace-out'
  def replace(parentfd,name,identity):
   os.rename(name,name+'.owned',src_dir_fd=parentfd,dst_dir_fd=parentfd);os.mkdir(name,0o700,dir_fd=parentfd);raise OSError('replacement injected')
  with mock.patch.object(module,'_open_created_root',side_effect=replace):
   with self.assertRaises(IntegrationError) as caught:self.execute(engine,root)
  self.assertTrue(root.is_dir());self.assertFalse(root.with_name(root.name+'.owned').exists());self.assertFalse(caught.exception.cleanup_receipt['residue']);root.rmdir()
 def test_capture_identity_unavailable_races_never_delete_by_name(self):
  for mode in ('empty-replacement','nonempty-mode-replacement','name-absent'):
   engine=self.engine('capture-race-'+mode);root=self.root/('capture-out-'+mode);owned=root.with_name(root.name+'.owned')
   def race(parentfd,name,which=mode):
    if which=='name-absent':os.rmdir(name,dir_fd=parentfd)
    else:
     os.rename(name,name+'.owned',src_dir_fd=parentfd,dst_dir_fd=parentfd);os.mkdir(name,0o755 if which=='nonempty-mode-replacement' else 0o700,dir_fd=parentfd)
     if which=='nonempty-mode-replacement':
      replacement_fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parentfd)
      try:fd=os.open('marker',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600,dir_fd=replacement_fd);os.close(fd)
      finally:os.close(replacement_fd)
    raise OSError('capture unavailable')
   with mock.patch.object(module,'_capture_created',side_effect=race):
    with self.assertRaises(IntegrationError) as caught:self.execute(engine,root)
   receipt=caught.exception.cleanup_receipt;self.assertTrue(receipt['residue_unknown']);self.assertFalse(receipt['cleanup_complete']);self.assertIn('IDENTITY_UNAVAILABLE',receipt['errors']);self.assertEqual(receipt['named_entry_present'],mode!='name-absent')
   if mode!='name-absent':
    self.assertTrue(root.is_dir());self.assertTrue(owned.is_dir())
    marker=root/'marker'
    if marker.exists():marker.unlink()
    root.rmdir();owned.rmdir()
   else:self.assertFalse(root.exists());self.assertFalse(owned.exists());self.assertFalse(receipt['residue'])
 def test_no_forbidden_imports_or_effects(self):
  text=(ROOT/'shared/job_runtime/candidates/r6_data_quality_fable_allocation_integration_v1/integration.py').read_text()
  for token in ('provider_contract','service','scheduler','subprocess','socket','smtplib','urllib','requests','anthropic','publication'):self.assertNotIn('import '+token,text)
  self.assertEqual(SPEC['installed_jobs'],[]);self.assertEqual(SPEC['installed_schedules'],[])
if __name__=='__main__':unittest.main()
