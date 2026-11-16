"""Canonical-Engine-owned provider-free Codex fixture driver."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib,json,os,sqlite3,time
from pathlib import Path
from typing import Any,Dict,Mapping,Optional
from shared.job_runtime.engine import Engine
from shared.job_runtime.prompt_custody import PromptArtifactDescriptorV1
from shared.job_runtime.provider_contract import FailureKind,Phase,ProviderResultV1,ReplayContractV1,ReplayEffect,ResultStatus,Submission,TerminalProof
from shared.job_runtime.retry_policy import RetryPolicyV2
from .contracts import ContractError,DriverResult,EffectGuard,ExecutionBinding,canonical_bytes,compose_reviewed_public_contracts,make_request_fingerprint,require,sha256_bytes,validate_config,validate_held_bytes,validate_preflight,validate_receipt_binding,verify_frozen_predecessors
from .custody import FixtureCustody
from .gateway import GatewayObserver
from .process import FixtureProcessController,ProcessPlan
from .publication import AtomicPublisher,PublicationError,Publisher
from .terminal import translate
UTC=timezone.utc
@dataclass(frozen=True)
class Dependencies:
 publisher:Publisher; fixture_upstream_path:Path; scenario:str='nominal'; monotonic:Any=time.monotonic; deadline_monotonic:Optional[float]=None; fixture_timeout:float=1.2; engine_fault:Optional[str]=None; retain_custody:bool=False; pre_binary_swap:Optional[bytes]=None
@dataclass(frozen=True)
class CanonicalReadback:
 status:str; binding:Mapping[str,Any]; receipt:Mapping[str,Any]; receipt_sha256:str; transaction:str='BEGIN_IMMEDIATE_REOPENED_SCHEMA9'
def _counters(**kw:int)->Dict[str,int]:
 v={'catalog_requests':0,'process_starts':0,'admissions':0,'dispatches':0,'upstream_attempts':0,'second_rejections':0,'terminals':0,'retries':0,'replays':0,'status_calls':0,'reconciliations':0};v.update(kw);return v
def _stop(code:str,counters=None)->DriverResult:return DriverResult('STOP',code,False,{},dict(counters or _counters()),{},None)
def _digest(value:Any)->str:return sha256_bytes(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
def _safe_code(value:str)->str:
 allowed={'BINARY_NOFOLLOW_REJECTED','BINARY_NOT_REGULAR','BINARY_OWNER_DRIFT','BINARY_MODE_DRIFT','BINARY_IDENTITY_DRIFT','BINARY_COPY_DRIFT','TERMINAL_CARDINALITY','TERMINAL_IDENTITY','TERMINAL_UTF8','TERMINAL_EVENT_SHAPE','TERMINAL_KEYS','TERMINAL_GATEWAY_DISAGREEMENT','TIMEOUT_BEFORE_ADMISSION','TIMEOUT_AFTER_ADMISSION','SECOND_REQUEST_REJECTED_AFTER_ADMISSION','CLEANUP_INCOMPLETE','CUSTODY_RETAINED','MONOTONIC_DEADLINE_EXPIRED','PROCESS_FAILURE'}
 return value if value in allowed else 'FIXTURE_LOCAL_FAILURE'
class CanonicalEngineAdapter:
 def __init__(self,workspace:Path,state:Path,execution_id:str,prompt:bytes,source_generation:str,now:datetime,fault:Optional[str]=None)->None:
  self.workspace=workspace;self.state=state;self.execution_id=execution_id;self.prompt=prompt;self.now=now.astimezone(UTC);self.fault=fault;self.engine=None;self.expected_receipt=None;self.lifecycle=None
  token=hashlib.sha256(execution_id.encode()).hexdigest()[:32];self.job_id='r6o1-'+token
  input_sha=sha256_bytes(prompt);identity=sha256_bytes(('r6-driver-v3:'+execution_id).encode());self.descriptor=PromptArtifactDescriptorV1(1,'pa1:sha256:%s:%d'%(input_sha,len(prompt)),input_sha,len(prompt),identity,source_generation,'native_v1')
 def run(self,lifecycle)->Mapping[str,int]:
  if self.fault=='before_tick':raise RuntimeError('ENGINE_INJECTED_BEFORE_TICK')
  policy=RetryPolicyV2(1,1,1,deadline_seconds=60);contract=ReplayContractV1(ReplayEffect.NONE,(Phase.NOT_STARTED,),'r6-o1/codex-fixture-v3')
  job={'id':self.job_id,'enabled':True,'replay_safe':False,'schedule':{'kind':'once','at':self.now.isoformat(),'grace_seconds':60},'_provider':'codex_cli','_replay_contract':contract,'_retry_policy':policy,'_prompt_artifact':self.descriptor}
  def dispatcher(_job,context):
   result,receipt,state=lifecycle(context,self.job_id);self.expected_receipt=receipt;self.lifecycle=state
   if self.fault=='after_dispatch_before_finish':raise RuntimeError('ENGINE_INJECTED_FINISH')
   return result
  self.engine=Engine(self.state,[job],policy,dispatcher,workspace_root=self.workspace,clock=lambda:self.now,max_workers=1)
  return self.engine.tick(self.now)
 def readback(self)->CanonicalReadback:
  if self.fault=='readback':raise RuntimeError('ENGINE_INJECTED_READBACK')
  require(self.engine is not None,'ENGINE_NOT_RUN');db=sqlite3.connect(self.engine.path,timeout=5);db.row_factory=sqlite3.Row
  try:
   db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
   counts={'jobs':db.execute('SELECT COUNT(*) FROM jobs WHERE job_id=?',(self.job_id,)).fetchone()[0],'slots':db.execute('SELECT COUNT(*) FROM slots WHERE job_id=?',(self.job_id,)).fetchone()[0],'attempts':db.execute('SELECT COUNT(*) FROM attempts a JOIN slots s ON s.slot_id=a.slot_id WHERE s.job_id=?',(self.job_id,)).fetchone()[0],'provider_results':db.execute('SELECT COUNT(*) FROM provider_results p JOIN attempts a ON a.attempt_id=p.attempt_id JOIN slots s ON s.slot_id=a.slot_id WHERE s.job_id=?',(self.job_id,)).fetchone()[0]}
   require(all(x==1 for x in counts.values()),'ENGINE_CARDINALITY')
   row=db.execute('''SELECT s.slot_id,s.status AS slot_status,s.operation_id,s.sha256 AS input_sha256,s.binding_sha256,a.attempt_id,a.status AS attempt_status,p.status AS result_status,p.operation_id AS result_operation,p.canonical_json,p.canonical_sha256,p.prompt_binding_sha256 FROM slots s JOIN attempts a ON a.slot_id=s.slot_id JOIN provider_results p ON p.attempt_id=a.attempt_id WHERE s.job_id=?''',(self.job_id,)).fetchone();require(row is not None,'ENGINE_READBACK_MISSING')
   value=json.loads(row['canonical_json']);receipt=value['receipt'];require(type(receipt) is dict,'ENGINE_RECEIPT_MISSING');require(self.expected_receipt is not None and receipt==self.expected_receipt,'ENGINE_RECEIPT_MISMATCH');require(row['slot_status']==row['attempt_status']==row['result_status'],'ENGINE_STATUS_MISMATCH');require(row['operation_id']==row['result_operation']==receipt['operation_id'],'ENGINE_OPERATION_MISMATCH');require(row['input_sha256']==receipt['input_sha256']==sha256_bytes(self.prompt),'ENGINE_INPUT_MISMATCH');require(row['binding_sha256']==row['prompt_binding_sha256'],'ENGINE_PROMPT_BINDING_MISMATCH')
   binding={'job_id':self.job_id,'slot_id':row['slot_id'],'attempt_id':row['attempt_id'],'operation_id':row['operation_id'],'process_id':receipt['process_id'],'request_fingerprint':receipt['request_fingerprint'],'model':receipt['model'],'prompt_sha256':row['input_sha256'],'grant_sha256':receipt['grant_sha256'],'counts':counts,'prompt_binding_sha256':row['binding_sha256'],'receipt_digests':receipt['receipt_digests']}
   status=None if self.fault=='status_none' else row['slot_status'];db.commit();return CanonicalReadback(status,binding,receipt,row['canonical_sha256'])
  except BaseException:db.rollback();raise
  finally:db.close()
def _fixture_upstream(workspace:Path,path:Path)->bytes:
 require(isinstance(path,Path),'FIXTURE_UPSTREAM_PATH_REQUIRED');text=str(path);require(not text.startswith(('http:','https:')) and '://' not in text,'LIVE_UPSTREAM_FORBIDDEN');expected=workspace/'shared/job_runtime/tests/fixtures/r6_one_off_codex_live_driver_v1/fake_terminal_exact.jsonl';require(path.resolve()==expected.resolve() and path.is_file() and not path.is_symlink(),'FIXTURE_UPSTREAM_REJECTED');return path.read_bytes()
def execute_provider_free(config:Mapping[str,Any],preflight:Mapping[str,Any],held_bytes:Mapping[str,bytes],prompt:bytes,body:bytes,workspace_root:Path,fixture_custody_parent:Path,execution_id:str,deps:Dependencies,now:Any=None)->DriverResult:
 try:
  validate_config(config);verify_frozen_predecessors(workspace_root);compose_reviewed_public_contracts('a'*64,'synthetic-current-profile-ref');validate_preflight(preflight,now=now);validate_held_bytes(config,held_bytes);require(len(prompt)==config['prompt']['bytes'] and sha256_bytes(prompt)==config['prompt']['sha256'],'PROMPT_DRIFT');upstream_raw=_fixture_upstream(workspace_root,deps.fixture_upstream_path);deadline=deps.deadline_monotonic if deps.deadline_monotonic is not None else deps.monotonic()+config['timeouts_seconds']['overall'];guard=EffectGuard(preflight['budget']['provider_remaining'],preflight['budget']['combined_remaining'],deadline,deps.monotonic);guard.check('preflight_complete')
 except (ContractError,OSError) as exc:return _stop(str(exc))
 counters=_counters(catalog_requests=1);receipts:Dict[str,Any]={};lifecycle_state:Dict[str,Any]={};now_dt=now if isinstance(now,datetime) else datetime.now(UTC);engine_workspace=fixture_custody_parent/('.engine-workspace-'+execution_id);engine_workspace.mkdir(mode=0o700);engine_state=engine_workspace/'.job-runtime'/'state';adapter=CanonicalEngineAdapter(engine_workspace,engine_state,execution_id,prompt,held_bytes['source_closure'].hex()[:64].ljust(64,'0'),now_dt,deps.engine_fault)
 def lifecycle(context,job_id):
  ids={'job_id':job_id,'slot_id':context['slot_id'],'attempt_id':context['attempt_id'],'operation_id':context['operation_id']};custody=None;gateway=None;controller=None;binding=None;outcome='STOP';code='NOT_STARTED';admitted=False;cleanup={};local={}
  try:
   guard.check('before_custody_create');custody=FixtureCustody(fixture_custody_parent,execution_id);guard.observe('after_custody_create');fingerprint,admission=make_request_fingerprint(ids['operation_id'],config['prompt']['sha256'],sha256_bytes(body));binding=ExecutionBinding(ids['job_id'],ids['slot_id'],ids['attempt_id'],ids['operation_id'],'process-'+execution_id,fingerprint,config['model'],config['prompt']['sha256'],sha256_bytes(held_bytes['grant']));controller=FixtureProcessController(binding,guard);stdout_path=custody.path_for('stdout.jsonl');stderr_path=custody.path_for('stderr.log');plan=ProcessPlan(tuple(config['argv']),dict(config['environment']['values']),str(workspace_root),prompt,False,True,deps.fixture_timeout,0,deps.scenario,str(stdout_path),str(stderr_path),config['binary']['bytes'],config['binary']['sha256'],0o755,os.getuid())
   if deps.pre_binary_swap is not None:Path(config['binary']['path']).write_bytes(deps.pre_binary_swap);os.chmod(config['binary']['path'],0o755)
   controller.prepare_verified_binary(plan);gateway=GatewayObserver(fingerprint,admission,lambda _body:upstream_raw,binding,guard);port=gateway.start();plan=ProcessPlan(plan.argv,plan.environment,plan.cwd,plan.stdin,plan.shell,plan.new_process_group,plan.total_timeout_seconds,port,plan.scenario,plan.stdout_path,plan.stderr_path,plan.expected_binary_bytes,plan.expected_binary_sha256,plan.expected_binary_mode,plan.expected_binary_uid);result=controller.run(plan);counters['process_starts']=1;local['process']={'kind':'process','binding':binding.public(),'started':True,'pid':result.pid,'pgid':result.pgid,'child_pid':result.child_pid,'exit_code':result.exit_code,'timed_out':result.timed_out,'process_group_reaped':result.process_group_reaped,'descendants_reaped':result.descendants_reaped,'descriptors_closed':result.descriptors_closed,'pid_gone':result.pid_gone,'child_pid_gone':result.child_pid_gone,'executed_private_copy':result.executed_private_copy,'shell':False,'new_process_group':True,'effective_argv_sha256':sha256_bytes(json.dumps(result.effective_argv,separators=(',',':')).encode()),'environment_keys':list(result.environment_keys),'stdin_bytes':result.stdin_bytes,'stdout':custody.describe_existing('stdout.jsonl'),'stderr':custody.describe_existing('stderr.log')}
   if result.timed_out:code='TIMEOUT_AFTER_ADMISSION' if gateway.admissions else 'TIMEOUT_BEFORE_ADMISSION'
   elif result.exit_code!=0:code='PROCESS_FAILURE'
   else:
    try:local['terminal']=translate(result.stdout,{'upstream_attempts':gateway.upstream_attempts,'terminal_present':gateway.terminal_present},binding);counters['terminals']=1;outcome='PASS';code='FAKE_NOMINAL_ONE'
    except ContractError as exc:code=_safe_code(str(exc))
  except (ContractError,OSError,AttributeError) as exc:code=_safe_code(str(exc))
  finally:
   if controller:
    try:
     cleanup.update(controller.close())
     if 'process' in local:
      for key in ('process_group_reaped','descendants_reaped','descriptors_closed','pid_gone','child_pid_gone','verified_copy_removed'):local['process'][key]=cleanup[key]
    except Exception:cleanup.update({'process_group_reaped':False,'descendants_reaped':False,'descriptors_closed':False,'pid_gone':False,'child_pid_gone':False,'verified_copy_removed':False})
   if gateway:
    try:local['gateway']=gateway.close()
    except Exception:local['gateway']={'kind':'gateway','binding':binding.public() if binding else {},'listener_closed':False,'admissions':gateway.admissions,'dispatches':gateway.dispatches,'upstream_attempts':gateway.upstream_attempts,'second_rejections':gateway.second_rejections}
    g=local['gateway'];admitted=g.get('admissions',0)==1;counters.update(admissions=g.get('admissions',0),dispatches=g.get('dispatches',0),upstream_attempts=g.get('upstream_attempts',0),second_rejections=g.get('second_rejections',0))
   if custody:
    guard.observe('before_custody_destroy');local['custody_cleanup']=custody.destroy(deps.retain_custody);guard.observe('after_custody_destroy')
   cleanup.update({'listener_closed':bool(local.get('gateway',{}).get('listener_closed')),'custody_removed':bool(local.get('custody_cleanup',{}).get('authoritative_pass_safe'))})
   cleanup_ok=all(cleanup.get(k) is True for k in ('process_group_reaped','descendants_reaped','descriptors_closed','pid_gone','child_pid_gone','verified_copy_removed','listener_closed','custody_removed'))
   if admitted and (outcome!='PASS' or not cleanup_ok or counters['second_rejections'] or guard.late_effects):outcome='UNKNOWN'
   elif not admitted and outcome!='PASS':outcome='STOP'
   if admitted and counters['second_rejections']:code='SECOND_REQUEST_REJECTED_AFTER_ADMISSION'
   if not cleanup.get('custody_removed',False):code='CUSTODY_RETAINED';outcome='UNKNOWN' if admitted else 'STOP'
   if admitted and not cleanup_ok and code!='CUSTODY_RETAINED':code='CLEANUP_INCOMPLETE'
   if guard.late_effects:code='MONOTONIC_DEADLINE_EXPIRED';outcome='UNKNOWN' if admitted else 'STOP'
  for name,value in local.items():receipts[name]=value
  receipt_digests={name:_digest(value) for name,value in local.items()};engine_receipt={'job_id':ids['job_id'],'slot_id':ids['slot_id'],'attempt_id':ids['attempt_id'],'operation_id':ids['operation_id'],'process_id':binding.process_id if binding else 'process-unstarted','request_fingerprint':binding.request_fingerprint if binding else '0'*64,'model':config['model'],'input_sha256':config['prompt']['sha256'],'grant_sha256':sha256_bytes(held_bytes['grant']),'receipt_digests':receipt_digests,'outcome':outcome};lifecycle_state.update({'outcome':outcome,'code':code,'binding':binding,'cleanup':cleanup,'engine_receipt':engine_receipt,'admitted':admitted})
  if outcome=='PASS':result=ProviderResultV1('codex_cli',ids['operation_id'],Phase.TERMINAL,Submission.DEFINITELY_SUBMITTED,TerminalProof.VERIFIED,ResultStatus.SUCCEEDED,'FIXTURE_PASS',receipt=engine_receipt)
  elif outcome=='UNKNOWN':result=ProviderResultV1('codex_cli',ids['operation_id'],Phase.STREAMING if admitted else Phase.NOT_STARTED,Submission.POSSIBLY_SUBMITTED if admitted else Submission.NOT_SUBMITTED,TerminalProof.ABSENT,ResultStatus.UNKNOWN,'FIXTURE_UNKNOWN',failure_kind=FailureKind.MISSING_TERMINAL if admitted else FailureKind.UNKNOWN,receipt=engine_receipt)
  else:result=ProviderResultV1('codex_cli',ids['operation_id'],Phase.NOT_STARTED,Submission.NOT_SUBMITTED,TerminalProof.ABSENT,ResultStatus.FAILED,'FIXTURE_STOP',failure_kind=FailureKind.LOCAL_CONFIG,receipt=engine_receipt)
  return result,engine_receipt,lifecycle_state
 engine_error=None;readback=None
 try:
  guard.check('before_engine_tick');adapter.run(lifecycle);guard.observe('after_engine_tick');guard.observe('before_engine_readback');readback=adapter.readback();guard.observe('after_engine_readback')
 except Exception as exc:engine_error='ENGINE_TRANSACTION_FAILED'
 outcome=lifecycle_state.get('outcome','UNKNOWN' if counters['upstream_attempts'] else 'STOP');code=lifecycle_state.get('code',engine_error or 'ENGINE_TRANSACTION_FAILED');canonical_status={'PASS':'succeeded','UNKNOWN':'unknown','STOP':'failed'}[outcome];binding_public=lifecycle_state.get('binding').public() if lifecycle_state.get('binding') else None;exact_engine=False
 if readback is not None:
  exact_engine=(readback.status==canonical_status and binding_public is not None and all(readback.binding.get(k)==binding_public.get(k) for k in binding_public) and readback.receipt==lifecycle_state.get('engine_receipt'))
 if not exact_engine:
  outcome='UNKNOWN' if lifecycle_state.get('admitted') else 'STOP';code=engine_error or 'ENGINE_READBACK_INVALID'
 unknown_durable=outcome=='UNKNOWN' and exact_engine and readback.status=='unknown';pass_authorized=outcome=='PASS' and exact_engine and readback.status=='succeeded' and not guard.late_effects and lifecycle_state.get('cleanup',{}).get('custody_removed') is True
 engine_public={'status':readback.status if readback else None,'transaction':readback.transaction if readback else None,'receipt_sha256':readback.receipt_sha256 if readback else None,'exact_binding':exact_engine};public={'version':'stage-b-execution-v3','outcome':outcome,'code':code,'countable_observation':False,'binding':binding_public,'engine':engine_public,'counters':counters,'receipt_digests':{name:_digest(value) for name,value in receipts.items()},'cleanup':lifecycle_state.get('cleanup',{}),'unknown_fence':{'durable':unknown_durable,'retry':False,'replay':False,'status_calls':0,'reconciliation':False},'effect_checks':list(guard.effects)}
 publication=None
 def authorize()->bool:return guard.observe('before_authoritative_marker') and (outcome!='PASS' or pass_authorized)
 try:
  guard.observe('before_primary_publication')
  if not exact_engine:raise PublicationError('ENGINE_NONPASS_FENCE_REQUIRED')
  publication=deps.publisher.publish('stage-b-execution-v3.json',public,authorize);on_time=guard.observe('after_primary_publication')
  if outcome=='PASS' and not on_time:
   if isinstance(deps.publisher,AtomicPublisher):deps.publisher.revoke_authority(publication)
   outcome='UNKNOWN';code='MONOTONIC_DEADLINE_EXPIRED';unknown_durable=False;raise PublicationError('LATE_AFTER_PUBLICATION')
 except Exception as exc:
  if not any(item.startswith('after_primary_publication') for item in guard.effects):guard.observe('after_primary_publication')
  outcome='UNKNOWN' if lifecycle_state.get('admitted') else 'STOP';code=('ENGINE_READBACK_INVALID' if not exact_engine else ('PUBLICATION_FAILED' if code!='MONOTONIC_DEADLINE_EXPIRED' else code));public.update(outcome=outcome,code=code,unknown_fence={'durable':unknown_durable,'retry':False,'replay':False,'status_calls':0,'reconciliation':False},effect_checks=list(guard.effects));guard.observe('before_fallback_publication')
  try:publication=deps.publisher.publish('non-pass-fence-v3.json',public,lambda:guard.observe('before_fallback_marker'))
  except Exception:publication=None
  guard.observe('after_fallback_publication')
 receipts['engine_readback']={'status':readback.status if readback else None,'exact':exact_engine,'unknown_durable':unknown_durable,'error':engine_error};receipts['timing']={'observations':list(guard.effects),'late':list(guard.late_effects)}
 return DriverResult(outcome,code,False,dict(readback.binding) if readback else {},counters,receipts,publication)
