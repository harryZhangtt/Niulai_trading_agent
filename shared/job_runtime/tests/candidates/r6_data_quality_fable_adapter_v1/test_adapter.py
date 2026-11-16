from __future__ import annotations
import copy, hashlib, json, math, sqlite3, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from shared.job_runtime.engine import Engine
from shared.job_runtime.engine_schema import prompt_binding_sha256
from shared.job_runtime.prompt_custody import PromptArtifactDescriptorV1
from shared.job_runtime.provider_contract import FailureKind,Phase,ProviderResultV1,ReplayContractV1,ReplayEffect,ResultStatus,Submission,TerminalProof
from shared.job_runtime.retry_policy import RetryPolicyV2
from shared.job_runtime.candidates.r6_data_quality_fable_adapter_v1.adapter import AdapterError,DESIGN_SHA256,INPUTS_SHA256,JOB_IDS,ROW_KEYS,adapt_engine_provider_results,default_adapt
from shared.job_runtime.candidates.r6_data_quality_fable_ab_v1.bundle import BundleError,read_bundle
from shared.job_runtime.candidates.r6_data_quality_fable_ab_v1.contracts import CELL_ORDER,DQ_CHECKS,FROZEN_INPUTS,MODEL_ID,validate_result
UTC=timezone.utc

def checks():return [{"name":n,"status":"PASS","code":"CHECK_PASS"} for n in DQ_CHECKS]
def receipt(cell,terminal):return {"version":1,"design_sha256":DESIGN_SHA256,"cell_id":cell,"configured_model":MODEL_ID,"provider_reported_model":MODEL_ID,"inputs_sha256":INPUTS_SHA256,"terminal_state":terminal,"terminal_ascii":"sanitized-"+cell+"-"+terminal,"dq_checks":checks() if cell==CELL_ORDER[1] else None}
def expected(index,slot=None,attempt=None):
 slot=slot or "slot-"+str(index);attempt=attempt or "attempt-"+str(index);descriptor={"artifact_ref":"pa1:sha256:"+FROZEN_INPUTS["prompt_sha256"]+":1","sha256":FROZEN_INPUTS["prompt_sha256"],"length":1,"version":1,"source_identity_sha256":"b"*64,"generation":"fable-adapter-fixture","proof_origin":"native_v1"};binding=prompt_binding_sha256(JOB_IDS[index],slot,descriptor)
 return {"cell_id":CELL_ORDER[index],"job_id":JOB_IDS[index],"slot_id":slot,"attempt_id":attempt,"prompt_binding_sha256":binding,**descriptor}
def provider_result(index,terminal,exp=None):
 exp=exp or expected(index);operation="attempt/"+exp["attempt_id"]+"/prompt/"+exp["prompt_binding_sha256"]
 if terminal=='PASS':args=(Phase.TERMINAL,Submission.DEFINITELY_SUBMITTED,TerminalProof.VERIFIED,ResultStatus.SUCCEEDED,"FABLE_FIXTURE_PASS",FailureKind.NONE)
 elif terminal=='STOP':args=(Phase.NOT_STARTED,Submission.NOT_SUBMITTED,TerminalProof.ABSENT,ResultStatus.FAILED,"FABLE_FIXTURE_STOP",FailureKind.CONFIG)
 elif terminal in ('MISSING','UNKNOWN'):args=(Phase.TERMINAL,Submission.POSSIBLY_SUBMITTED,TerminalProof.ABSENT,ResultStatus.UNKNOWN,"FABLE_FIXTURE_"+terminal,FailureKind.MISSING_TERMINAL if terminal=='MISSING' else FailureKind.UNKNOWN)
 else:args=(Phase.TERMINAL,Submission.DEFINITELY_SUBMITTED,TerminalProof.VERIFIED,ResultStatus.FAILED,"FABLE_FIXTURE_"+terminal,FailureKind.PROVIDER)
 return ProviderResultV1("claude_host",operation,*args[:5],failure_kind=args[5],receipt=receipt(CELL_ORDER[index],terminal))
def plain(value):
 if hasattr(value,'items'):return {k:plain(v) for k,v in value.items()}
 if isinstance(value,(tuple,list)):return [plain(v) for v in value]
 return value
def row(result,exp,recorded=1.0):
 encoded=json.dumps(plain(result.to_mapping()),sort_keys=True,separators=(',',':'))
 return {"attempt_id":exp["attempt_id"],"slot_id":exp["slot_id"],"canonical_json":encoded,"canonical_sha256":hashlib.sha256(encoded.encode()).hexdigest(),"provider":result.provider.value,"operation_id":result.operation_id,"phase":result.phase.value,"submission":result.submission.value,"terminal_proof":result.terminal_proof.value,"status":result.status.value,"failure_kind":result.failure_kind.value,"recorded_at":recorded,"prompt_binding_sha256":exp["prompt_binding_sha256"]}
def case(terminal):
 ex=[expected(i) for i in range(2)];return [row(provider_result(i,terminal,ex[i]),ex[i]) for i in range(2)],ex

class AdapterTests(unittest.TestCase):
 def setUp(self):
  private=Path(__file__).resolve().parents[3]/'fixtures/r6_data_quality_fable_adapter_v1/.runtime';private.mkdir(mode=0o700,parents=True,exist_ok=True);self.tmp=tempfile.TemporaryDirectory(dir=private);self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
 def adapt(self,terminal='PASS',root=None,**kw):rows,exp=case(terminal);return adapt_engine_provider_results(rows,exp,root or self.root,**kw)
 def test_default_disabled_zero_effects(self):self.assertTrue(all(v==0 for v in default_adapt()['effects'].values()))
 def test_actual_engine_join_nominal_two_cell_completion(self):
  now=datetime(2026,11,11,12,0,tzinfo=UTC);sha=FROZEN_INPUTS['prompt_sha256'];artifact=PromptArtifactDescriptorV1(1,'pa1:sha256:'+sha+':1',sha,1,'b'*64,'fable-adapter-fixture','native_v1')
  jobs=[{'id':JOB_IDS[i],'enabled':True,'replay_safe':False,'schedule':{'kind':'interval','seconds':60,'grace_seconds':120},'_provider':'claude_host','_replay_contract':ReplayContractV1(ReplayEffect.NONE,(Phase.NOT_STARTED,),'scope/fable-'+str(i)),'_retry_policy':RetryPolicyV2(1,1,1),'_prompt_artifact':artifact} for i in range(2)]
  def dispatch(job,context):
   i=JOB_IDS.index(job['id']);exp=expected(i,context['slot_id'],context['attempt_id']);self.assertEqual(context['prompt_binding_sha256'],exp['prompt_binding_sha256']);return provider_result(i,'PASS',exp)
  engine=Engine(self.root/'.job-runtime/engine',jobs,{'max_attempts':1,'backoff_seconds':1,'max_backoff_seconds':1},dispatch,workspace_root=self.root,clock=lambda:now,max_workers=1);summary=engine.tick(now);self.assertEqual((summary['dispatched'],summary['succeeded']),(2,2))
  db=sqlite3.connect(engine.path);db.row_factory=sqlite3.Row
  try:
   db.execute('BEGIN IMMEDIATE');joined=[dict(x) for x in db.execute('SELECT p.*,s.job_id,s.artifact_ref,s.sha256,s.length,s.version,s.source_identity_sha256,s.generation,s.proof_origin FROM provider_results p JOIN slots s ON s.slot_id=p.slot_id JOIN attempts a ON a.attempt_id=p.attempt_id ORDER BY s.job_id')];db.commit()
  finally:db.close()
  rows=[{k:x[k] for k in ROW_KEYS} for x in joined];expected_join=[{"cell_id":CELL_ORDER[i],**{k:joined[i][k] for k in ('job_id','slot_id','attempt_id','prompt_binding_sha256','artifact_ref','sha256','length','version','source_identity_sha256','generation','proof_origin')}} for i in range(2)]
  result=adapt_engine_provider_results(rows,expected_join,self.root/'bundles');validate_result(result);self.assertEqual((result['denominator_count'],result['publication_attempts']),(2,0))
 def test_all_six_dispositions_retained_unknown_fenced(self):
  for terminal in ('PASS','FAIL','STOP','MALFORMED','MISSING','UNKNOWN'):
   result=self.adapt(terminal,self.root/terminal)
   for cell in result['cells']:self.assertTrue(cell['denominator_included']);self.assertIn(terminal,cell['disposition']);self.assertEqual(cell['publication'],{'status':'SUPPRESSED_PROVIDER_FREE','attempts':0,'unknown_fenced':terminal=='UNKNOWN'})
 def test_second_cell_after_raw_restart_preserves_first(self):
  rows,exp=case('PASS')
  with self.assertRaisesRegex(BundleError,'CRASH_AFTER_RAW'):adapt_engine_provider_results(rows,exp,self.root,fault_cell=CELL_ORDER[1])
  first=self.root/CELL_ORDER[0];before={p.name:p.read_bytes() for p in first.iterdir()};second=self.root/CELL_ORDER[1];self.assertFalse(any(second.glob('*.json')));adapt_engine_provider_results(rows,exp,self.root);self.assertEqual(before,{p.name:p.read_bytes() for p in first.iterdir()});self.assertTrue(any(second.glob('*.json')))
 def test_completed_and_raw_conflicts_never_replace(self):
  rows,exp=case('PASS');adapt_engine_provider_results(rows,exp,self.root/'done');bundle=next((self.root/'done'/CELL_ORDER[0]).glob('*.json'));before=bundle.read_bytes();bundle.write_bytes(before+b' ')
  with self.assertRaisesRegex(BundleError,'COMPLETED_BUNDLE_CONFLICT'):adapt_engine_provider_results(rows,exp,self.root/'done')
  self.assertEqual(bundle.read_bytes(),before+b' ')
  with self.assertRaisesRegex(BundleError,'CRASH_AFTER_RAW'):adapt_engine_provider_results(rows,exp,self.root/'raw',fault_cell=CELL_ORDER[0])
  raw=next((self.root/'raw'/CELL_ORDER[0]).glob('*.raw'));raw.write_bytes(b'conflict')
  with self.assertRaisesRegex(BundleError,'NO_REPLACE'):adapt_engine_provider_results(rows,exp,self.root/'raw')
 def test_valid_hash_provider_operation_and_expected_binding_drift_reject(self):
  rows,exp=case('PASS');variants=[]
  x=copy.deepcopy(rows);x[0]['prompt_binding_sha256']='c'*64;variants.append((x,exp))
  x=copy.deepcopy(rows);x[0]['provider']='codex_cli';variants.append((x,exp))
  x=copy.deepcopy(rows);x[0]['operation_id']='operation/valid-but-not-native';variants.append((x,exp))
  x=copy.deepcopy(exp);x[0]['prompt_binding_sha256']='d'*64;variants.append((rows,x))
  for i,(r,e) in enumerate(variants):
   with self.assertRaises(AdapterError,msg=str(i)):adapt_engine_provider_results(r,e,self.root/('drift-'+str(i)))
 def test_duplicate_attempt_slot_order_and_nonfinite_time_reject(self):
  rows,exp=case('PASS');variants=[]
  x=copy.deepcopy(exp);x[1]['attempt_id']=x[0]['attempt_id'];variants.append((rows,x))
  x=copy.deepcopy(exp);x[1]['slot_id']=x[0]['slot_id'];variants.append((rows,x))
  variants.append((list(reversed(rows)),exp))
  for bad in (True,float('nan'),float('inf'),float('-inf')):
   x=copy.deepcopy(rows);x[0]['recorded_at']=bad;variants.append((x,exp))
  for i,(r,e) in enumerate(variants):
   with self.assertRaises(AdapterError,msg=str(i)):adapt_engine_provider_results(r,e,self.root/('identity-'+str(i)))
 def test_model_receipt_and_canonical_tamper_reject(self):
  rows,exp=case('PASS');variants=[]
  x=copy.deepcopy(rows);x[0]['canonical_sha256']='0'*64;variants.append(x)
  for field,value in [('configured_model','claude-opus-5-5'),('provider_reported_model','claude-opus-5-5'),('design_sha256','0'*64),('inputs_sha256','0'*64)]:
   changed=[]
   for i in range(2):
    m=plain(provider_result(i,'PASS',exp[i]).to_mapping());m['receipt'][field]=value;bad=ProviderResultV1(**m);changed.append(row(bad,exp[i]))
   variants.append(changed)
  for i,r in enumerate(variants):
   with self.assertRaises((AdapterError,ValueError),msg=str(i)):adapt_engine_provider_results(r,exp,self.root/('receipt-'+str(i)))
 def test_exact_complete_restart_and_outputs_validate(self):
  rows,exp=case('PASS');result=adapt_engine_provider_results(rows,exp,self.root);before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()};self.assertEqual(result,adapt_engine_provider_results(rows,exp,self.root));self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
  for cell in CELL_ORDER:
   path=self.root/cell/(cell+'.bundle.json');read_bundle(path,hashlib.sha256(path.read_bytes()).hexdigest())
 def test_no_external_effect_imports_or_active_defaults(self):
  text=(Path(__file__).resolve().parents[3]/'candidates/r6_data_quality_fable_adapter_v1/adapter.py').read_text()
  for token in ('socket','subprocess','smtplib','urllib','requests','anthropic'):self.assertNotIn('import '+token,text)

if __name__=='__main__':unittest.main()
