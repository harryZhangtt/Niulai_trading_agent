from __future__ import annotations
from datetime import datetime,timezone
import copy,hashlib,importlib.util,json,os,sqlite3,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
from unittest import mock
from shared.job_runtime.candidates.r6_data_quality_fable_provider_free_staging_v1 import BudgetError,CampaignBudgetLedger,StagingError,build_candidate,campaign_dispatcher,load_candidate,materialize_disposable,open_disabled_engine,rollback_disposable,recover_rollback
from shared.job_runtime.candidates.r6_data_quality_fable_provider_free_staging_v1 import staging as staging_impl
from shared.job_runtime.candidates.r6_data_quality_fable_provider_free_staging_v1.staging import engine_projection
from shared.job_runtime.candidates.r6_data_quality_fable_provider_free_staging_v1.deployment_package.fable_canary_budget import budget as budget_impl
from shared.job_runtime.candidates.r6_data_quality_fable_provider_free_staging_v1.deployment_package.fable_canary_budget import journal as journal_impl
from shared.job_runtime.candidates.r6_data_quality_fable_provider_free_staging_v1.deployment_package.fable_canary_budget.journal import BINDING_FIELDS,CLAIM_FIELDS,TERMINAL_FIELDS,EffectClaim,JournalError,derive_effect_nonce
from shared.job_runtime.config import load
from shared.job_runtime.provider_contract import ProviderResultV1
from shared.job_runtime.engine import Engine
from shared.job_runtime import service
ROOT=Path(__file__).resolve().parents[5]
def success(operation):return ProviderResultV1(provider='claude_host',operation_id=operation,phase='terminal',submission='definitely_submitted',terminal_proof='verified',status='succeeded',code='MODEL_TURN_COMPLETED',failure_kind='none',receipt={'fixture':True})
def context(job,attempt):return {'slot_id':'slot-'+attempt,'attempt_id':attempt,'scheduled_at':'2099-11-12T12:02:00Z','attempt_no':1,'operation_id':'attempt/'+attempt,'prompt_artifact':job['_prompt_artifact']}
class StagingTests(unittest.TestCase):
 def setUp(self):service.STOP.clear();self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name).resolve();self.root=self.base/'fable-5-1-dq-v1-source';self.external=self.base/'fable-5-1-dq-v1-deployment'
 def tearDown(self):service.STOP.clear();self.temp.cleanup()
 def build(self):return build_candidate(self.root,'2099-11-12T12:02:00Z')
 def test_schema2_cas_engine_and_concurrent_reopen_dispatch_boundary(self):
  manifest=self.build();config,captured=load(self.root.resolve()/'.job-runtime/config/runtime.json',self.root.resolve())
  self.assertEqual((config['schema_version'],config['max_workers'],len(captured)),(2,1,2));self.assertFalse(any(j['enabled'] for j in captured));self.assertEqual({j['_prompt_capture'].length for j in captured},{526});self.assertEqual({j['_prompt_capture'].sha256 for j in captured},{manifest['prompt']['sha256']})
  calls=[];engine=open_disabled_engine(self.root,lambda *a:calls.append(a));self.assertEqual(engine.tick(datetime(2099,11,12,12,2,tzinfo=timezone.utc))['dispatched'],0);self.assertEqual(calls,[])
  config,jobs=engine_projection(self.root);entered=threading.Event();release=threading.Event();provider_calls=[]
  def fake(_profile,_prompt,_workspace,_run_dir,operation,_provider_context):
   provider_calls.append(operation)
   if operation=='attempt/off-a':entered.set();release.wait(2)
   return success(operation)
  dispatch=campaign_dispatcher(config,self.root,fake);first=[]
  thread=threading.Thread(target=lambda:first.append(dispatch(jobs[0],context(jobs[0],'off-a'))));thread.start();self.assertTrue(entered.wait(2))
  concurrent=dispatch(jobs[0],context(jobs[0],'off-b'));release.set();thread.join(2)
  self.assertEqual(first[0].status.value,'succeeded');self.assertEqual(concurrent.status.value,'unknown');self.assertEqual(provider_calls,['attempt/off-a'])
  reopened=campaign_dispatcher(config,self.root,fake);on=reopened(jobs[1],context(jobs[1],'on-a'));self.assertEqual(on.status.value,'succeeded');self.assertEqual(provider_calls,['attempt/off-a','attempt/on-a'])
  ledger=CampaignBudgetLedger(self.root/'.job-runtime/acceptance/fable-5-1-dq-v1/campaign-budget.sqlite',approved_root=self.root/'.job-runtime/acceptance/fable-5-1-dq-v1',create=False);claims=ledger.snapshot()['claims'];self.assertEqual([(c['arm'],c['outcome'],c['slot_id'],c['attempt_id'],c['operation_id']) for c in claims],[('OFF','VALID','slot-off-a','off-a','attempt/off-a'),('ON','VALID','slot-on-a','on-a','attempt/on-a')])
  self.assertEqual(manifest['effects'],{'provider':0,'network':0,'email':0,'business':0,'ixic':0});self.assertFalse(manifest['activation'])
 def test_materializer_physical_ledger_reuse_and_identity_bound_rollback(self):
  manifest=self.build();receipt=materialize_disposable(self.root,self.external);again=materialize_disposable(self.root,self.external);self.assertEqual(receipt,again)
  host=receipt['host_receipt'];self.assertEqual((host['service_label'],host['watchdog_label']),(manifest['host']['service_label'],manifest['host']['watchdog_label']))
  deployed=Path(receipt['deployment_root'])/'workspace';ledger=deployed/'.job-runtime/acceptance/fable-5-1-dq-v1/campaign-budget.sqlite';self.assertTrue(ledger.is_file());self.assertEqual(oct(ledger.stat().st_mode&0o777),'0o600');self.assertEqual(len(receipt['package']),4);self.assertTrue(all((deployed/row['path']).is_file() for row in receipt['package']));self.assertFalse(any(p.is_symlink() for p in self.external.rglob('*')))
  with self.assertRaises(StagingError):rollback_disposable(self.root,self.external,source_parent=self.base/'wrong',deployment_parent=self.base,expected=receipt)
  bad=copy.deepcopy(receipt);bad['host_receipt']['workspace_id']='bad'
  with self.assertRaisesRegex(StagingError,'ROLLBACK_RECEIPT_MISMATCH'):rollback_disposable(self.root,self.external,source_parent=self.base,deployment_parent=self.base,expected=bad)
  allocation=self.root/'.job-runtime/config/fable-dq-allocation.json';raw=allocation.read_bytes();value=json.loads(raw);value['jobs'][0]['enabled']=True;allocation.write_text(json.dumps(value,separators=(',',':'),sort_keys=True)+'\n')
  with self.assertRaises(StagingError):rollback_disposable(self.root,self.external,source_parent=self.base,deployment_parent=self.base,expected=receipt)
  allocation.write_bytes(raw);pointer=self.root/'.job-runtime/setup/host-deployment.json';pointer_raw=pointer.read_bytes();pointer.unlink()
  with self.assertRaises(StagingError):rollback_disposable(self.root,self.external,source_parent=self.base,deployment_parent=self.base,expected=receipt)
  pointer.write_bytes(pointer_raw);pointer.chmod(0o600);evil=self.external/'evil';evil.symlink_to('/tmp')
  with self.assertRaisesRegex(StagingError,'ROLLBACK_SYMLINK_REJECTED'):rollback_disposable(self.root,self.external,source_parent=self.base,deployment_parent=self.base,expected=receipt)
  self.assertTrue(self.root.exists() and self.external.exists());evil.unlink()
  for index,target in enumerate(('journal','before_write','before_replace','rename_deployment','before_fsync_deployment_parent_stage','after_rename_source','commit')):
   source=self.base/f'inject-source-{index}';deployment=self.base/f'inject-deployment-{index}';build_candidate(source,'2099-11-12T12:02:00Z');injected=materialize_disposable(source,deployment);fired=[]
   def fail(phase,target=target):
    if phase==target and not fired:fired.append(phase);raise RuntimeError('injected')
   staging_impl._ROLLBACK_TEST_HOOK=fail
   try:
    with self.assertRaises(RuntimeError):rollback_disposable(source,deployment,source_parent=self.base,deployment_parent=self.base,expected=injected)
   finally:staging_impl._ROLLBACK_TEST_HOOK=None
   self.assertTrue(fired and source.exists() and deployment.exists())
  rollback_disposable(self.root,self.external,source_parent=self.base,deployment_parent=self.base,expected=receipt);self.assertFalse(self.root.exists() or self.external.exists());journals=[json.loads(p.read_text()) for p in self.base.glob('.fable-rollback-*.json')];self.assertEqual(sum(j['state']=='RETIRED_COMMITTED' for j in journals),1);self.assertTrue(all(j['state'] in ('RECOVERED','RETIRED_COMMITTED') for j in journals));self.assertEqual(len(list(self.base.glob('.*.rollback-*'))),2)
 def test_crash_after_claim_reopen_blocks_replay_and_prompt_tamper(self):
  self.build();config,jobs=engine_projection(self.root);calls=[]
  def crash(*_):calls.append('called');raise RuntimeError('fixture crash')
  jobs[0]['enabled']=True;jobs[1]['enabled']=False;dispatch=campaign_dispatcher(config,self.root,crash);canonical=self.root.resolve();engine=Engine(canonical/'.job-runtime/canary-engine',jobs,config['retry'],dispatch,workspace_root=canonical,max_workers=1)
  first=engine.tick(datetime(2099,11,12,12,2,tzinfo=timezone.utc));self.assertEqual(first['unknown'],1)
  reopened=Engine(canonical/'.job-runtime/canary-engine',jobs,config['retry'],campaign_dispatcher(config,self.root,crash),workspace_root=canonical,max_workers=1);second=reopened.tick(datetime(2099,11,12,12,3,tzinfo=timezone.utc));self.assertEqual(second['dispatched'],0);self.assertEqual(calls,['called'])
  ledger=CampaignBudgetLedger(self.root/'.job-runtime/acceptance/fable-5-1-dq-v1/campaign-budget.sqlite',approved_root=self.root/'.job-runtime/acceptance/fable-5-1-dq-v1',create=False);claims=ledger.snapshot()['claims'];self.assertEqual(len(claims),1);self.assertEqual((claims[0]['outcome'],claims[0]['job_id']),('UNKNOWN','fable-5-1-dq-off'))
  race_root=self.base/'pre-provider';build_candidate(race_root,'2099-11-12T12:02:00Z');race_config,race_jobs=engine_projection(race_root);ledger_path=race_root/'.job-runtime/acceptance/fable-5-1-dq-v1/campaign-budget.sqlite';replacement=ledger_path.with_name('replacement.sqlite')
  with sqlite3.connect(ledger_path) as src,sqlite3.connect(replacement) as dst:src.backup(dst)
  replacement.chmod(0o600);original=ledger_path.with_name('original.sqlite');provider_calls=[]
  def preprovider(phase,path):
   if phase=='pre_provider' and not original.exists():os.replace(path,original);os.replace(replacement,path)
  budget_impl._TEST_HOOK=preprovider
  try:result=campaign_dispatcher(race_config,race_root,lambda *args:(provider_calls.append(1) or success(args[4])))(race_jobs[0],context(race_jobs[0],'swap-a'));self.assertEqual(result.status.value,'unknown');self.assertEqual(provider_calls,[])
  finally:
   budget_impl._TEST_HOOK=None
   if original.exists():
    if ledger_path.exists():ledger_path.unlink()
    os.replace(original,ledger_path)
  with self.assertRaisesRegex(StagingError,'CANDIDATE_ROOT_EXISTS'):self.build()
  (self.root/'.job-runtime/config/prompts/fable-dq-off.txt').write_bytes(b'x'*526)
  with self.assertRaisesRegex(StagingError,'PROMPT_CUSTODY_INVALID'):load_candidate(self.root)
 def test_active_repository_state_unchanged_and_no_active_names(self):
  watched=[ROOT/'.job-runtime/config/runtime.json',ROOT/'.job-runtime/engine/schedule.sqlite',ROOT/'.job-runtime/launchd/com.local.trading-agent.job-runtime.plist',ROOT/'.job-runtime/launchd/com.local.trading-agent.job-runtime.watchdog.plist']
  def baseline():
   rows=[]
   for path in watched:
    exists=path.exists() or path.is_symlink();raw=path.read_bytes() if path.is_file() and not path.is_symlink() else b'';rows.append({'path':str(path.relative_to(ROOT)),'exists':exists,'kind':'file' if path.is_file() else ('symlink' if path.is_symlink() else 'absent'),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest() if raw else None})
   aggregate=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest();return rows,aggregate
  before=baseline();manifest=self.build();receipt=materialize_disposable(self.root,self.external);deployed=Path(receipt['deployment_root'])/'workspace';after=baseline();self.assertEqual(before,after);self.assertEqual(len(before[0]),len(watched));text=json.dumps(manifest,sort_keys=True);self.assertNotIn('Library/LaunchAgents',text);self.assertNotIn('.niulai-state',text)
  script="""import json,sys
from pathlib import Path
from datetime import datetime,timezone
root=Path(sys.argv[1]).resolve();sys.path.insert(0,str(root))
from shared.job_runtime import service
from shared.job_runtime import engine as engine_module
from shared.job_runtime.config import load
from shared.job_runtime.engine import Engine
from shared.job_runtime.provider_contract import ProviderResultV1
from shared.job_runtime.fable_canary_budget import campaign_dispatcher
assert Path(service.__file__).resolve().is_relative_to(root) and Path(engine_module.__file__).resolve().is_relative_to(root)
config,captured=load(root/'.job-runtime/config/runtime.json',root);jobs=service.resource_jobs(config,service.publish_prompt_jobs(root,captured,'fable-5-1-dq-v1'));[(job.__setitem__('_resource_key','fable-5-1-dq-v1-shared')) for job in jobs];jobs[0]['enabled']=True;jobs[1]['enabled']=False
def fake(_p,_q,_w,_r,op,_c):return ProviderResultV1(provider='claude_host',operation_id=op,phase='terminal',submission='definitely_submitted',terminal_proof='verified',status='succeeded',code='MODEL_TURN_COMPLETED',failure_kind='none',receipt={'fixture':True})
dispatch=campaign_dispatcher(config,root,fake);engine=Engine(root/'.job-runtime/deployed-engine',jobs,config['retry'],dispatch,workspace_root=root,max_workers=1);summary=engine.tick(datetime(2099,11,12,12,2,tzinfo=timezone.utc));import shared.job_runtime.fable_canary_budget as package;print(json.dumps({'summary':summary,'succeeded':summary['succeeded'],'package':str(Path(package.__file__).resolve()),'service':str(Path(service.__file__).resolve())}))"""
  completed=subprocess.run(['/usr/bin/python3','-I','-c',script,str(deployed)],text=True,capture_output=True,check=False,env={'PATH':'/usr/bin:/bin'});self.assertEqual(completed.returncode,0,completed.stderr);sub=json.loads(completed.stdout);self.assertEqual(sub['succeeded'],1,sub);self.assertTrue(Path(sub['package']).is_relative_to(deployed) and Path(sub['service']).is_relative_to(deployed))

 def test_rollback_process_death_recovery_and_strict_journal(self):
  targets=('after_create_journal','after_rename_deployment','after_replace_fsync','after_rename_source','after_fsync_source_parent_stage')
  for index,target in enumerate(targets):
   source=self.base/f'death-source-{index}';deployment=self.base/f'death-deployment-{index}';build_candidate(source,'2099-11-12T12:02:00Z');receipt=materialize_disposable(source,deployment);token=receipt['rollback_binding']['nonce'];journal=self.base/f'.fable-rollback-{token}.json'
   script="""import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from shared.job_runtime.candidates.r6_data_quality_fable_provider_free_staging_v1 import staging as s
import json
source=Path(sys.argv[2]);deployment=Path(sys.argv[3]);receipt=json.loads(Path(sys.argv[4]).read_text())
s._ROLLBACK_TEST_HOOK=lambda phase: os._exit(93) if phase==sys.argv[5] else None
s.rollback_disposable(source,deployment,source_parent=source.parent,deployment_parent=deployment.parent,expected=receipt)
"""
   receipt_path=self.base/f'death-receipt-{index}.json';receipt_path.write_text(json.dumps(receipt,sort_keys=True,separators=(',',':')));completed=subprocess.run(['/usr/bin/python3','-I','-c',script,str(ROOT),str(source),str(deployment),str(receipt_path),target],env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True);self.assertEqual(completed.returncode,93,(target,completed.stderr));self.assertEqual(recover_rollback(self.base,self.base,journal),'RECOVERED');self.assertEqual(recover_rollback(self.base,self.base,journal),'RECOVERED');self.assertTrue(source.is_dir() and deployment.is_dir())
  source=self.base/'strict-source';deployment=self.base/'strict-deployment';build_candidate(source,'2099-11-12T12:02:00Z');receipt=materialize_disposable(source,deployment);token=receipt['rollback_binding']['nonce'];journal=self.base/f'.fable-rollback-{token}.json'
  fired=[]
  def stop(phase):
   if phase=='after_create_journal' and not fired:fired.append(phase);raise RuntimeError('stop')
  staging_impl._ROLLBACK_TEST_HOOK=stop
  try:
   with self.assertRaises(RuntimeError):rollback_disposable(source,deployment,source_parent=self.base,deployment_parent=self.base,expected=receipt)
  finally:staging_impl._ROLLBACK_TEST_HOOK=None
  original=journal.read_bytes();value=json.loads(original)
  for field in sorted(value):
   mutated=copy.deepcopy(value);mutated[field]=None;journal.write_text(json.dumps(mutated,sort_keys=True,separators=(',',':'))+'\n');journal.chmod(0o600)
   with self.assertRaises(StagingError):recover_rollback(self.base,self.base,journal)
  journal.write_bytes(original);journal.chmod(0o600);mutated=json.loads(original);mutated['state']='PREPARED';mutated['source']['original']='foreign';mutated['journal_sha256']=staging_impl._journal_hash(mutated);journal.write_bytes(staging_impl._canonical(mutated));journal.chmod(0o600)
  with self.assertRaises(StagingError):recover_rollback(self.base,self.base,journal)
  journal.write_bytes(original);journal.chmod(0o600);self.assertEqual(recover_rollback(self.base,self.base,journal),'RECOVERED')
 def test_exhaustive_namespace_presence_classifier(self):
  namespace=self.base/'namespace';namespace.mkdir(mode=0o700);fd=os.open(namespace,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);journal={'source':{'original':'source','staged':'.source.rollback-'+'a'*32},'deployment':{'original':'deployment','staged':'.deployment.rollback-'+'a'*32}}
  try:
   names=(journal['source']['original'],journal['source']['staged'],journal['deployment']['original'],journal['deployment']['staged'])
   for mask in range(16):
    for name in names:
     path=namespace/name
     if path.exists():path.rmdir()
    expected=tuple(bool(mask&(1<<bit)) for bit in range(4))
    for present,name in zip(expected,names):
     if present:(namespace/name).mkdir(mode=0o700)
    self.assertEqual(staging_impl._namespace(fd,fd,journal),expected)
  finally:
   os.close(fd)
   for path in namespace.iterdir():path.rmdir()
 def _assert_parent_symlink_components_rejected(self):
  source=self.base/'parent-source';deployment=self.base/'parent-deployment';build_candidate(source,'2099-11-12T12:02:00Z');receipt=materialize_disposable(source,deployment);link=self.base/'parent-link';link.symlink_to(self.base,target_is_directory=True)
  with self.assertRaisesRegex(StagingError,'ROLLBACK_ROOT_INVALID'):rollback_disposable(link/source.name,deployment,source_parent=link,deployment_parent=self.base,expected=receipt)
  with self.assertRaisesRegex(StagingError,'ROLLBACK_ROOT_INVALID'):rollback_disposable(source,link/deployment.name,source_parent=self.base,deployment_parent=link,expected=receipt)
 def test_descriptor_ancestor_and_full_inventory_mutations_fail_closed(self):
  self._assert_parent_symlink_components_rejected();source=self.root;deployment=self.external;self.build();receipt=materialize_disposable(source,deployment);setup=source/'.job-runtime/setup';held=source/'.job-runtime/setup-held';setup.rename(held);setup.symlink_to(held.name)
  with self.assertRaises(StagingError):rollback_disposable(source,deployment,source_parent=self.base,deployment_parent=self.base,expected=receipt)
  setup.unlink();held.rename(setup);target=deployment/'workspace/shared/job_runtime/fable_canary_budget/journal.py';raw=target.read_bytes();target.write_bytes(raw+b'\n')
  with self.assertRaisesRegex(StagingError,'ROLLBACK_RECEIPT_MISMATCH'):rollback_disposable(source,deployment,source_parent=self.base,deployment_parent=self.base,expected=receipt)
 def test_isolated_materialized_root_e2e_matrix(self):
  script="""import json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve();case=sys.argv[2];sys.path.insert(0,str(root))
from shared.job_runtime.config import load
from shared.job_runtime.service import publish_prompt_jobs,resource_jobs
from shared.job_runtime.provider_contract import ProviderResultV1
from shared.job_runtime.fable_canary_budget import campaign_dispatcher
config,captured=load(root/'.job-runtime/config/runtime.json',root);jobs=resource_jobs(config,publish_prompt_jobs(root,captured,'fable-5-1-dq-v1'))
for job in jobs:job['_resource_key']='fable-5-1-dq-v1-shared'
def ctx(job,name):return {'slot_id':'slot-'+name,'attempt_id':name,'scheduled_at':'2099-11-12T12:02:00Z','attempt_no':1,'operation_id':'attempt/'+name,'prompt_artifact':job['_prompt_artifact']}
calls=[]
def result(operation,provider='claude_host',op=None):return ProviderResultV1(provider=provider,operation_id=op or operation,phase='terminal',submission='definitely_submitted',terminal_proof='verified',status='succeeded',code='MODEL_TURN_COMPLETED',failure_kind='none',receipt={'fixture':True})
def fake(_p,_q,_w,_r,operation,_c):
 calls.append(operation)
 if case=='crash':raise RuntimeError('death after claim')
 if case=='wrong-provider':return result(operation,'codex_cli')
 if case=='wrong-operation':return result(operation,op='attempt/foreign')
 return result(operation)
if case=='wrong-profile':config['model_profiles']['fable-5-1-dq-disabled']['model']='claude-opus-5-5'
d=campaign_dispatcher(config,root,fake);first=d(jobs[0],ctx(jobs[0],case+'-off'));second=campaign_dispatcher(config,root,fake)(jobs[1],ctx(jobs[1],case+'-on'))
print(json.dumps({'first':first.status.value,'second':second.status.value,'calls':len(calls),'case':case}))
"""
  for index,case in enumerate(('success','crash','wrong-provider','wrong-operation','wrong-profile')):
   source=self.base/f'e2e-source-{index}';deployment=self.base/f'e2e-deployment-{index}';build_candidate(source,'2099-11-12T12:02:00Z');receipt=materialize_disposable(source,deployment);deployed=Path(receipt['deployment_root'])/'workspace';completed=subprocess.run(['/usr/bin/python3','-I','-c',script,str(deployed),case],text=True,capture_output=True,env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1'});self.assertEqual(completed.returncode,0,completed.stderr);value=json.loads(completed.stdout)
   if case=='success':self.assertEqual((value['first'],value['second'],value['calls']),('succeeded','succeeded',2))
   else:self.assertEqual((value['first'],value['second']),('unknown','unknown'));self.assertLessEqual(value['calls'],1)
 def test_frozen_source_closure_and_review_pending(self):
  architecture=ROOT/'tuning/architecture/r6_data_quality_fable_provider_free_staging_v1';closure=json.loads((architecture/'source-closure-v1.json').read_text());manifest=json.loads((architecture/'staging-manifest-v1.json').read_text());self.assertEqual(manifest['status'],'REVIEW_PENDING');self.assertFalse(manifest['activation']);raw=(architecture/'source-closure-v1.json').read_bytes();self.assertEqual(manifest['source_closure']['sha256'],hashlib.sha256(raw).hexdigest())
  for row in closure['members']:
   data=(ROOT/row['path']).read_bytes();self.assertEqual((len(data),hashlib.sha256(data).hexdigest()),(row['bytes'],row['sha256']))
 def test_dual_prompt_and_root_physical_closure(self):
  manifest=self.build();self.assertEqual(manifest['jobs'],[{'id':'fable-5-1-dq-off','arm':'OFF','enabled':False},{'id':'fable-5-1-dq-on','arm':'ON','enabled':False}]);self.assertEqual(manifest['limits'],{'attempts':1,'retries':0,'fallbacks':0,'status_queries':0});self.assertFalse(any(p.is_symlink() for p in self.root.rglob('*')))
  cases=('wrong-provider','wrong-operation','invalid-success','wrong-profile')
  for index,case in enumerate(cases):
   root=self.base/f'invalid-{index}';build_candidate(root,'2099-11-12T12:02:00Z');config,jobs=engine_projection(root);calls=[]
   if case=='wrong-profile':config['model_profiles']['fable-5-1-dq-disabled']['model']='claude-opus-5-5'
   def fake(_profile,_prompt,_workspace,_run_dir,operation,_ctx,case=case):
    calls.append(operation)
    if case=='wrong-provider':return ProviderResultV1(provider='codex_cli',operation_id=operation,phase='terminal',submission='definitely_submitted',terminal_proof='verified',status='succeeded',code='MODEL_TURN_COMPLETED',failure_kind='none',receipt={'fixture':True})
    if case=='wrong-operation':return success('attempt/foreign')
    if case=='invalid-success':return ProviderResultV1(provider='claude_host',operation_id=operation,phase='terminal',submission='definitely_submitted',terminal_proof='absent',status='succeeded',code='MODEL_TURN_COMPLETED',failure_kind='none',receipt={'fixture':True})
    return success(operation)
   result=campaign_dispatcher(config,root,fake)(jobs[0],context(jobs[0],f'bad-{index}'));self.assertEqual(result.status.value,'unknown')
   blocked=campaign_dispatcher(config,root,fake)(jobs[1],context(jobs[1],f'on-{index}'));self.assertEqual(blocked.status.value,'unknown');self.assertLessEqual(len(calls),1)
   ledger=CampaignBudgetLedger(root/'.job-runtime/acceptance/fable-5-1-dq-v1/campaign-budget.sqlite',approved_root=root/'.job-runtime/acceptance/fable-5-1-dq-v1',create=False);claims=ledger.snapshot()['claims'];self.assertEqual(len(claims),0 if case=='wrong-profile' else 1);self.assertTrue(not claims or claims[0]['outcome']=='UNKNOWN')
class BudgetTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'approved';self.path=self.root/'campaign-budget.sqlite';self.ledger=CampaignBudgetLedger(self.path,approved_root=self.root)
 def tearDown(self):self.temp.cleanup()
 def test_whitelist_caps_off_before_on_one_shot_nonce_and_bindings(self):
  with self.assertRaisesRegex(BudgetError,'JOB_NOT_WHITELISTED'):self.ledger.claim('other','nonce-0001','0.01')
  with self.assertRaisesRegex(BudgetError,'BUDGET_INVALID'):self.ledger.claim('fable-5-1-dq-off','nonce-0001','0.03')
  with self.assertRaisesRegex(BudgetError,'OFF_NOT_VALID'):self.ledger.claim('fable-5-1-dq-on','nonce-0002','0.02')
  off=self.ledger.claim('fable-5-1-dq-off','nonce-0001','0.02',attempt_id='a1',operation_id='op/a1');self.assertEqual(self.ledger.claim('fable-5-1-dq-off','nonce-0001','0.02',attempt_id='a1',operation_id='op/a1'),off)
  with self.assertRaisesRegex(BudgetError,'NONCE_REUSE_CONFLICT'):self.ledger.claim('fable-5-1-dq-off','nonce-0001','0.02',attempt_id='a2',operation_id='op/a2')
  with self.assertRaisesRegex(BudgetError,'UNRESOLVED_UNKNOWN'):self.ledger.claim('fable-5-1-dq-on','nonce-0002','0.02')
  self.ledger.resolve(off['claim_id'],'VALID',provider='claude_host',operation_id='op/a1',result_sha256='a'*64);on=self.ledger.claim('fable-5-1-dq-on','nonce-0002','0.02',attempt_id='a2',operation_id='op/a2');self.ledger.resolve(on['claim_id'],'VALID',provider='claude_host',operation_id='op/a2',result_sha256='b'*64)
  with self.assertRaisesRegex(BudgetError,'ONE_SHOT_ALREADY_CLAIMED'):self.ledger.claim('fable-5-1-dq-on','nonce-0003','0.01')
  self.assertEqual(sum(float(x['reserved']) for x in self.ledger.snapshot()['claims']),0.04)
 def _assert_effect_claim_directory_custody_and_terminal_failures_close_fds(self):
  binding={'deployment_id':'fable-5-1-dq-v1','campaign_id':'fable-5-1-dq-v1','job_id':'fable-5-1-dq-off','arm':'OFF','slot_id':'slot-fd','attempt_id':'attempt-fd','operation_id':'operation/fd','profile':'fable-5-1-dq-disabled','model':'claude-fable-5-1','cap':'0.02','resource':'fable-5-1-dq-v1-shared','prompt_sha256':'3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b'}
  for index,kind in enumerate(('collision','write','fsync')):
   authority=Path(self.temp.name).resolve()/f'fd-{index}';authority.mkdir(mode=0o700);before=len(os.listdir('/dev/fd'))
   with self.assertRaises(JournalError):
    with EffectClaim(authority,binding) as claim:
     if kind=='collision':
      target=authority/'effect-claims'/claim.terminal_name;target.write_text('{}\n');target.chmod(0o600);claim.terminal('VALID',success(binding['operation_id']))
     elif kind=='write':
      with mock.patch.object(journal_impl.os,'write',side_effect=OSError('injected write')):claim.terminal('VALID',success(binding['operation_id']))
     else:
      with mock.patch.object(journal_impl.os,'fsync',side_effect=OSError('injected fsync')):claim.terminal('VALID',success(binding['operation_id']))
   self.assertEqual(len(os.listdir('/dev/fd')),before,kind)
  bad_root=Path(self.temp.name).resolve()/'bad-root';bad_root.mkdir(mode=0o755)
  with self.assertRaisesRegex(JournalError,'JOURNAL_DIRECTORY_CUSTODY_INVALID'):EffectClaim(bad_root,binding)
  bad_claims=Path(self.temp.name).resolve()/'bad-claims';bad_claims.mkdir(mode=0o700);(bad_claims/'effect-claims').mkdir(mode=0o755)
  with self.assertRaisesRegex(JournalError,'JOURNAL_DIRECTORY_CUSTODY_INVALID'):EffectClaim(bad_claims,binding)
 def test_custody_rejects_reopen_unknown_symlink_hardlink_sidecar_extra_and_malformed(self):
  self._assert_effect_claim_directory_custody_and_terminal_failures_close_fds();self.ledger.claim('fable-5-1-dq-off','crash-0001','0.02');reopened=CampaignBudgetLedger(self.path,approved_root=self.root,create=False)
  with self.assertRaisesRegex(BudgetError,'UNRESOLVED_UNKNOWN'):reopened.claim('fable-5-1-dq-on','nonce-0002','0.02')
  link=self.root/'other';os.link(self.path,link)
  with self.assertRaisesRegex(BudgetError,'LEDGER_CUSTODY_INVALID'):reopened.snapshot()
  link.unlink();side=Path(str(self.path)+'-wal');side.write_bytes(b'x')
  with self.assertRaisesRegex(BudgetError,'LEDGER_SIDECAR_PRESENT'):reopened.snapshot()
  side.unlink();extra=Path(self.temp.name)/'extra';extra_ledger=CampaignBudgetLedger(extra/'campaign-budget.sqlite',approved_root=extra)
  with sqlite3.connect(extra_ledger.path) as db:db.execute("INSERT INTO arms VALUES('extra','EXTRA','0.02')")
  with self.assertRaisesRegex(BudgetError,'LEDGER_ARMS_INVALID'):CampaignBudgetLedger(extra_ledger.path,approved_root=extra_ledger.root,create=False)
  forged=Path(self.temp.name)/'forged';forged_ledger=CampaignBudgetLedger(forged/'campaign-budget.sqlite',approved_root=forged);forged_ledger.claim('fable-5-1-dq-off','forged-001','0.02')
  with sqlite3.connect(forged_ledger.path) as db:db.execute("UPDATE claims SET outcome='VALID'")
  with self.assertRaisesRegex(BudgetError,'CLAIM_RESOLUTION_INVALID'):CampaignBudgetLedger(forged_ledger.path,approved_root=forged_ledger.root,create=False)
  swapped=Path(self.temp.name)/'swapped';swapped_ledger=CampaignBudgetLedger(swapped/'campaign-budget.sqlite',approved_root=swapped);replacement=swapped/'replacement.sqlite'
  with sqlite3.connect(swapped_ledger.path) as src,sqlite3.connect(replacement) as dst:src.backup(dst)
  replacement.chmod(0o600);os.replace(replacement,swapped_ledger.path)
  with self.assertRaisesRegex(BudgetError,'LEDGER_PATH_SWAP'):swapped_ledger.snapshot()
  schema=Path(self.temp.name)/'schema';schema_ledger=CampaignBudgetLedger(schema/'campaign-budget.sqlite',approved_root=schema)
  with sqlite3.connect(schema_ledger.path) as db:db.execute('CREATE VIEW extra_view AS SELECT * FROM campaign')
  with self.assertRaisesRegex(BudgetError,'LEDGER_SCHEMA_INVALID'):CampaignBudgetLedger(schema_ledger.path,approved_root=schema_ledger.root,create=False)
  malformed=Path(self.temp.name)/'malformed';bad=CampaignBudgetLedger(malformed/'campaign-budget.sqlite',approved_root=malformed);bad.path.write_bytes(b'bad');bad.path.chmod(0o600)
  with self.assertRaises(BudgetError):CampaignBudgetLedger(bad.path,approved_root=bad.root,create=False)
  for index,sql in enumerate(("UPDATE claims SET claim_id='forged'","UPDATE claims SET reserved='0.020'","UPDATE claims SET reserved=x'3032'")):
   forged_root=Path(self.temp.name)/f'row-forgery-{index}';forged_row=CampaignBudgetLedger(forged_root/'campaign-budget.sqlite',approved_root=forged_root);forged_row.claim('fable-5-1-dq-off',f'row-forge-{index:02d}','0.02')
   with sqlite3.connect(forged_row.path) as db:db.execute(sql)
   with self.assertRaises(BudgetError):CampaignBudgetLedger(forged_row.path,approved_root=forged_root,create=False)
  for phase in ('pre_open','post_open','precommit'):
   race=Path(self.temp.name)/('race-'+phase);race_ledger=CampaignBudgetLedger(race/'campaign-budget.sqlite',approved_root=race);replacement=race/'replacement.sqlite'
   with sqlite3.connect(race_ledger.path) as src,sqlite3.connect(replacement) as dst:src.backup(dst)
   replacement.chmod(0o600);original=race/'original.sqlite';fired=[]
   def swap(current,path,phase=phase):
    if current==phase and not fired:os.replace(path,original);os.replace(replacement,path);fired.append(current)
   budget_impl._TEST_HOOK=swap
   try:
    with self.assertRaises(BudgetError):race_ledger.claim('fable-5-1-dq-off','race-0001','0.02')
   finally:
    budget_impl._TEST_HOOK=None
    if original.exists():
     if race_ledger.path.exists():race_ledger.path.unlink()
     os.replace(original,race_ledger.path)
   self.assertTrue(fired)
  binding={'deployment_id':'fable-5-1-dq-v1','campaign_id':'fable-5-1-dq-v1','job_id':'fable-5-1-dq-off','arm':'OFF','slot_id':'slot-journal','attempt_id':'attempt-journal','operation_id':'operation/journal','profile':'fable-5-1-dq-disabled','model':'claude-fable-5-1','cap':'0.02','resource':'fable-5-1-dq-v1-shared','prompt_sha256':'3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b'}
  nonce=derive_effect_nonce(binding);self.assertEqual(nonce,derive_effect_nonce(dict(binding)))
  for index,(kind,field) in enumerate([('claim',f) for f in sorted(CLAIM_FIELDS)]+[('terminal',f) for f in sorted(TERMINAL_FIELDS)]):
   authority=Path(self.temp.name)/f'journal-{index}';authority.mkdir(mode=0o700);claim=EffectClaim(authority,binding);self.assertEqual(claim.nonce,nonce);claim.terminal('VALID',success(binding['operation_id']));claim.close();target=authority/'effect-claims'/((kind+'-')+nonce+'.json');value=json.loads(target.read_text());value[field]=2 if field=='schema_version' else ('tampered' if field!='sealed_result' else {});target.write_text(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n');target.chmod(0o600)
   with self.assertRaises(JournalError):EffectClaim(authority,{**binding,'job_id':'fable-5-1-dq-on','arm':'ON'})
  bad_binding=Path(self.temp.name)/'bad-binding';bad_binding.mkdir(mode=0o700)
  with self.assertRaisesRegex(JournalError,'BINDING_SCHEMA_INVALID'):EffectClaim(bad_binding,{**binding,'nonce':'c'*64})
  symlink=Path(self.temp.name)/'symlink';real=CampaignBudgetLedger(symlink/'campaign-budget.sqlite',approved_root=symlink);real.path.rename(symlink/'real.sqlite');real.path.symlink_to(symlink/'real.sqlite')
  with self.assertRaisesRegex(BudgetError,'LEDGER_CUSTODY_INVALID'):CampaignBudgetLedger(real.path,approved_root=real.root,create=False)
