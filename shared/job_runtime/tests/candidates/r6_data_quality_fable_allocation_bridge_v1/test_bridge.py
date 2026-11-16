from __future__ import annotations
import copy,hashlib,json,os,shutil,sqlite3,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from shared.job_runtime.engine import Engine
from shared.job_runtime.prompt_custody import PromptArtifactDescriptorV1
from shared.job_runtime.provider_contract import FailureKind,Phase,ProviderResultV1,ReplayContractV1,ReplayEffect,ResultStatus,Submission,TerminalProof
from shared.job_runtime.retry_policy import RetryPolicyV2
from shared.job_runtime.candidates.r6_data_quality_fable_allocation_bridge_v1.bridge import ALLOCATION_SHA256,BridgeError,read_allocation_pair,validate_allocation,validate_joined_rows
from shared.job_runtime.candidates.r6_data_quality_fable_adapter_v1.adapter import DESIGN_SHA256,INPUTS_SHA256,JOB_IDS,adapt_engine_provider_results
from shared.job_runtime.candidates.r6_data_quality_fable_ab_v1.contracts import CELL_ORDER,DQ_CHECKS,FROZEN_INPUTS,MODEL_ID
UTC=timezone.utc;ROOT=Path(__file__).resolve().parents[5];FIX=ROOT/'shared/job_runtime/tests/fixtures/r6_data_quality_fable_allocation_bridge_v1';ALLOCATION=json.loads((FIX/'allocation-v1.json').read_text());QUIESCENCE={"engine_closed":True,"active_service":False,"sidecars_absent":True}
QUERY="""SELECT p.attempt_id pr_attempt_id,p.slot_id pr_slot_id,p.canonical_json,p.canonical_sha256,p.provider,p.operation_id,p.phase,p.submission,p.terminal_proof,p.status,p.failure_kind,p.recorded_at,p.prompt_binding_sha256,a.attempt_id attempt_join_id,a.slot_id attempt_slot_id,a.binding_sha256 attempt_binding_sha256,s.slot_id slot_join_id,s.job_id,s.binding_sha256 slot_binding_sha256,s.artifact_ref,s.sha256,s.length,s.version,s.source_identity_sha256,s.generation,s.proof_origin FROM provider_results p JOIN attempts a ON a.attempt_id=p.attempt_id JOIN slots s ON s.slot_id=p.slot_id AND s.slot_id=a.slot_id WHERE s.job_id IN (?,?) ORDER BY p.rowid"""
def checks():return [{"name":n,"status":"PASS","code":"CHECK_PASS"} for n in DQ_CHECKS]
def result(index,context):
 receipt={"version":1,"design_sha256":DESIGN_SHA256,"cell_id":CELL_ORDER[index],"configured_model":MODEL_ID,"provider_reported_model":MODEL_ID,"inputs_sha256":INPUTS_SHA256,"terminal_state":"PASS","terminal_ascii":"bridge-sanitized-"+CELL_ORDER[index],"dq_checks":checks() if index else None};return ProviderResultV1('claude_host',context['operation_id'],Phase.TERMINAL,Submission.DEFINITELY_SUBMITTED,TerminalProof.VERIFIED,ResultStatus.SUCCEEDED,'BRIDGE_FIXTURE_PASS',failure_kind=FailureKind.NONE,receipt=receipt)
def source_expectation(path):
 meta=path.stat();raw=path.read_bytes();return {"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"st_dev":meta.st_dev,"st_ino":meta.st_ino,"st_mtime_ns":meta.st_mtime_ns}
class BridgeTests(unittest.TestCase):
 def setUp(self):
  private=FIX/'.runtime';private.mkdir(mode=0o700,parents=True,exist_ok=True);self.tmp=tempfile.TemporaryDirectory(dir=private);self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.now=datetime(2026,11,11,12,0,tzinfo=UTC)
 def engine(self,count=2,name='engine'):
  sha=FROZEN_INPUTS['prompt_sha256'];artifact=PromptArtifactDescriptorV1(1,'pa1:sha256:'+sha+':1',sha,1,'b'*64,'fable-adapter-fixture','native_v1');jobs=[{'id':JOB_IDS[i],'enabled':True,'replay_safe':False,'schedule':{'kind':'interval','seconds':60,'grace_seconds':120},'_provider':'claude_host','_replay_contract':ReplayContractV1(ReplayEffect.NONE,(Phase.NOT_STARTED,),'scope/bridge-'+str(i)),'_retry_policy':RetryPolicyV2(1,1,1),'_prompt_artifact':artifact} for i in range(count)];return Engine(self.root/'.job-runtime'/name,jobs,{'max_attempts':1,'backoff_seconds':1,'max_backoff_seconds':1},lambda job,ctx:result(JOB_IDS.index(job['id']),ctx),workspace_root=self.root,clock=lambda:self.now,max_workers=1)
 def read(self,engine,hook=None):return read_allocation_pair(engine.path,ALLOCATION,source_expectation(engine.path),QUIESCENCE,_test_hook=hook)
 def joined(self,engine):
  db=sqlite3.connect(engine.path);db.row_factory=sqlite3.Row
  try:return [dict(x) for x in db.execute(QUERY,JOB_IDS)]
  finally:db.close()
 def snapshots(self,path):return list(path.parent.glob('.r6-fable-snapshot-*'))
 def test_nominal_closed_snapshot_bridge_adapter_roundtrip_and_source_unchanged(self):
  engine=self.engine();engine.tick(self.now);path=engine.path;before=(hashlib.sha256(path.read_bytes()).hexdigest(),path.stat().st_mtime_ns,tuple(sorted(p.name for p in path.parent.iterdir())))
  db=sqlite3.connect(path);tables_before=db.execute("SELECT count(*) FROM sqlite_master").fetchone()[0];db.close();bridge=self.read(engine);self.assertEqual((bridge.receipt['row_count'],bridge.receipt['allocation_sha256']),(2,ALLOCATION_SHA256));self.assertEqual(bridge.receipt['source_db_sha256'],bridge.receipt['snapshot_sha256']);output=adapt_engine_provider_results(bridge.rows,bridge.expected_readback,self.root/'bundles');self.assertEqual((output['denominator_count'],output['publication_attempts'],output['countable']),(2,0,False))
  after=(hashlib.sha256(path.read_bytes()).hexdigest(),path.stat().st_mtime_ns,tuple(sorted(p.name for p in path.parent.iterdir())));db=sqlite3.connect(path);tables_after=db.execute("SELECT count(*) FROM sqlite_master").fetchone()[0];db.close();self.assertEqual((before,tables_before),(after,tables_after));self.assertEqual(self.snapshots(path),[])
 def test_zero_one_and_more_than_two_rows_fail_closed(self):
  empty=self.engine(name='empty')
  with self.assertRaisesRegex(BridgeError,'BRIDGE_ROW_COUNT'):self.read(empty)
  one=self.engine(1,'one');one.tick(self.now)
  with self.assertRaisesRegex(BridgeError,'BRIDGE_ROW_COUNT'):self.read(one)
  many=self.engine(name='many');many.tick(self.now);many.clock=lambda:self.now+timedelta(seconds=60);many.tick(self.now+timedelta(seconds=60))
  with self.assertRaisesRegex(BridgeError,'BRIDGE_ROW_COUNT'):self.read(many)
 def test_reversed_ambiguous_and_join_drift_reject(self):
  engine=self.engine();engine.tick(self.now);base=self.joined(engine)
  with self.assertRaisesRegex(BridgeError,'BRIDGE_JOB_ORDER'):validate_joined_rows(list(reversed(base)),ALLOCATION)
  variants=[];x=copy.deepcopy(base);x[0]['attempt_join_id']='other';variants.append(x)
  for key,value in [('job_id','other-job'),('pr_slot_id','other-slot'),('sha256','0'*64),('prompt_binding_sha256','c'*64),('provider','codex_cli'),('operation_id','operation/not-native')]:x=copy.deepcopy(base);x[0][key]=value;variants.append(x)
  for x in variants:
   with self.assertRaises(BridgeError):validate_joined_rows(x,ALLOCATION)
 def test_model_cell_duplicate_attempt_and_slot_reject(self):
  engine=self.engine();engine.tick(self.now);base=self.joined(engine);variants=[]
  for field in ('configured_model','provider_reported_model','cell_id'):
   x=copy.deepcopy(base);value=json.loads(x[0]['canonical_json']);value['receipt'][field]='wrong';encoded=json.dumps(value,sort_keys=True,separators=(',',':'));x[0]['canonical_json']=encoded;x[0]['canonical_sha256']=hashlib.sha256(encoded.encode()).hexdigest();variants.append(x)
  for keys in (('pr_attempt_id','attempt_join_id'),('pr_slot_id','attempt_slot_id','slot_join_id')):
   x=copy.deepcopy(base)
   for key in keys:x[1][key]=x[0][key]
   variants.append(x)
  for x in variants:
   with self.assertRaises(BridgeError):validate_joined_rows(x,ALLOCATION)
 def test_allocation_and_quiescence_assertion_reject(self):
  validate_allocation(copy.deepcopy(ALLOCATION));engine=self.engine();engine.tick(self.now)
  for key,value in [('activation',True),('installed_jobs',['x']),('adapter_closure_sha256','0'*64),('model','claude-opus-5-5')]:
   x=copy.deepcopy(ALLOCATION);x[key]=value
   with self.assertRaises(BridgeError):validate_allocation(x)
  for q in ({},dict(QUIESCENCE,active_service=True)):
   with self.assertRaisesRegex(BridgeError,'QUIESCENCE_ASSERTION_REQUIRED'):read_allocation_pair(engine.path,ALLOCATION,source_expectation(engine.path),q)
 def test_wal_shm_and_journal_sidecars_reject(self):
  for suffix in ('-wal','-shm','-journal'):
   engine=self.engine(name='sidecar'+suffix[1:]);engine.tick(self.now);side=Path(str(engine.path)+suffix);side.write_bytes(b'x')
   with self.assertRaisesRegex(BridgeError,'SOURCE_NOT_QUIESCENT'):self.read(engine)
   side.unlink();self.assertEqual(self.snapshots(engine.path),[])
 def test_source_delete_symlink_and_regular_swap_during_read_reject(self):
  for mode in ('delete','symlink','regular'):
   engine=self.engine(name='race-'+mode);engine.tick(self.now);path=engine.path;backup=path.with_name(path.name+'.backup');expect=source_expectation(path);fired=[False]
   def hook(stage):
    if stage!='during_source_read' or fired[0]:return
    fired[0]=True;path.rename(backup)
    if mode=='symlink':os.symlink(backup.name,path)
    elif mode=='regular':shutil.copyfile(backup,path);path.chmod(0o600)
   try:
    with self.assertRaises((BridgeError,OSError)):read_allocation_pair(path,ALLOCATION,expect,QUIESCENCE,_test_hook=hook)
   finally:
    if path.is_symlink() or path.exists():path.unlink()
    if backup.exists():backup.rename(path)
   self.assertEqual(self.snapshots(path),[])
 def test_schema_valid_wrong_db_rejects_expected_source(self):
  right=self.engine(name='right');right.tick(self.now);wrong=self.engine(name='wrong');wrong.tick(self.now);expect=source_expectation(right.path)
  with self.assertRaisesRegex(BridgeError,'SOURCE_EXPECTATION_MISMATCH'):read_allocation_pair(wrong.path,ALLOCATION,expect,QUIESCENCE)
  self.assertEqual(self.snapshots(wrong.path),[])
 def test_sqlite_stage_failures_close_and_cleanup(self):
  stages=('before_sqlite_open','after_sqlite_open','after_begin','after_pragmas','after_query','before_commit')
  for stage in stages:
   engine=self.engine(name='fail-'+stage);engine.tick(self.now);before=(hashlib.sha256(engine.path.read_bytes()).hexdigest(),tuple(sorted(p.name for p in engine.path.parent.iterdir())))
   def hook(observed,target=stage):
    if observed==target:raise sqlite3.OperationalError('injected')
   with self.assertRaisesRegex(BridgeError,'BRIDGE_DATABASE_READBACK_FAILED'):read_allocation_pair(engine.path,ALLOCATION,source_expectation(engine.path),QUIESCENCE,_test_hook=hook)
   self.assertEqual(self.snapshots(engine.path),[]);self.assertEqual(before,(hashlib.sha256(engine.path.read_bytes()).hexdigest(),tuple(sorted(p.name for p in engine.path.parent.iterdir()))))
 def test_missing_db_and_inert_source(self):
  with self.assertRaises((BridgeError,OSError)):read_allocation_pair(self.root/'missing.sqlite',ALLOCATION,{"sha256":"0"*64,"bytes":0,"st_dev":0,"st_ino":0,"st_mtime_ns":0},QUIESCENCE)
  text=(ROOT/'shared/job_runtime/candidates/r6_data_quality_fable_allocation_bridge_v1/bridge.py').read_text()
  for token in ('provider_contract','subprocess','socket','smtplib','urllib','requests','anthropic','service','allocation.py'):self.assertNotIn('import '+token,text)
if __name__=='__main__':unittest.main()
