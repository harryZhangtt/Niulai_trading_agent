"""V3 vertical with observed Engine projection and total UNKNOWN finalization."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib,json,os,time
from pathlib import Path
from typing import Any,Dict,Mapping,Optional
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.contracts import CELL_BINDINGS,CHECK_NAMES,PROVIDER_BINDINGS,derive_readback_match,validate_envelope
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.contracts import DriverResult,EffectGuard,ExecutionBinding,canonical_bytes,make_request_fingerprint,sha256_bytes
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.custody import FixtureCustody
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.process import FixtureProcessController,ProcessPlan
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.publication import AtomicPublisher
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.terminal import translate
from shared.job_runtime.provider_contract import FailureKind,Phase,ProviderResultV1,ResultStatus,Submission,TerminalProof
from .authority_v3 import FixedAuthorityV3,load_fixed_authority_v3
from .engine_v3 import CanonicalEngineAdapterV3,ObservedEngineReadbackV3
from .finalizer_v3 import finalize_unknown_v3
from .contracts import ContractError,require
from .gateway import Endpoint,ResponsesGateway
ROOT=Path(__file__).resolve().parents[4];FIXTURE_ROOT=(ROOT/'shared/job_runtime/tests/fixtures/r6_one_off_codex_live_integration_v1').resolve();UPSTREAM_RAW=(ROOT/'shared/job_runtime/tests/fixtures/r6_one_off_codex_live_driver_v1/fake_terminal_exact.jsonl').read_bytes()
CASES=frozenset(('nominal','second','malformed','multiple','contradictory','pre_timeout','post_timeout','nonzero_success','publication_fault','second_publication_failure','engine_mismatch','post_p0_exception','post_seal_exception','revoke_failure','unlink_failure','dirfsync_failure','fence_write_failure','fence_dirfsync_failure','surviving_marker'))
@dataclass(frozen=True)
class IntegrationResultV3:
 result:DriverResult;post_run_seal:Optional[Mapping[str,Any]];p0_envelope:Optional[Mapping[str,Any]];finalization:Optional[Mapping[str,Any]];observed_readback:Optional[Mapping[str,Any]]
def _digest(v:Any)->str:return sha256_bytes(json.dumps(v,sort_keys=True,separators=(',',':')).encode())
def _counters()->Dict[str,int]:return {'catalog_requests':0,'process_starts':0,'admissions':0,'dispatches':0,'upstream_attempts':0,'second_rejections':0,'terminals':0,'retries':0,'replays':0,'status_calls':0,'reconciliations':0}
def _prompt(authority:FixedAuthorityV3)->bytes:
 rel=authority.grant['prompt']['source_ref'];value=json.loads((ROOT/rel).read_text());raw=value['prompt_utf8'].encode();require((len(raw),sha256_bytes(raw))==(authority.grant['prompt']['bytes'],authority.grant['prompt']['sha256']),'V2_PROMPT_DRIFT');return raw
def _custody_parent(path:Path)->Path:
 p=path.resolve();require(p.is_dir() and not p.is_symlink() and (p==FIXTURE_ROOT or FIXTURE_ROOT in p.parents),'V2_FIXTURE_CUSTODY_ONLY');return p
def _p0_v3(result:DriverResult,observed:ObservedEngineReadbackV3,grant:Mapping[str,Any],raw:bytes,artifact:Mapping[str,Any])->Mapping[str,Any]:
 provider_label,addon_label,enabled=CELL_BINDINGS[grant['cell_id']];readback=dict(observed.p0_receipt);key={'cell_id':grant['cell_id'],'job_id':readback['job_id'],'slot_id':readback['slot_id'],'attempt_id':readback['attempt_id'],'operation_id':readback['operation_id'],'prompt_binding_sha256':readback['prompt_binding_sha256'],'canonical_engine_readback_digest':observed.p0_receipt_sha256};matched=derive_readback_match(key,readback)
 checks=[{'name':n,'status':'UNKNOWN' if enabled else 'NOT_RUN_TREATMENT_DISABLED','code':'CHECK_RESULT_MISSING' if enabled else 'NOT_RUN_TREATMENT_DISABLED'} for n in CHECK_NAMES];terminal=result.outcome;gate='UNKNOWN' if terminal=='UNKNOWN' or enabled else 'ALLOW' if terminal=='PASS' else 'REJECT';decision='SUPPRESS_UNKNOWN' if gate=='UNKNOWN' else 'DELEGATE_SANITIZED' if gate=='ALLOW' else 'SUPPRESS_TERMINAL';artifact_raw=canonical_bytes(dict(artifact))
 env={'version':1,'key':key,'blind_provider_label':provider_label,'blind_addon_label':addon_label,'checks_enabled':enabled,'terminal_state':terminal,'raw_ref':{'name':'provider-terminal.raw','sha256':sha256_bytes(raw),'bytes':len(raw),'owner_private':True,'public':False},'publication_artifact_ref':{'name':'stage-b-execution-v3.json','provider_schema':'stage-b-execution-v3','publication_driver_identity_sha256':PROVIDER_BINDINGS[provider_label]['publication_driver_identity_sha256'],'sha256':sha256_bytes(artifact_raw),'bytes':len(artifact_raw),'owner_private':True,'public':False,'provider_validated':True},'source_inventory':list(grant['source']['allowed']),'citation_inventory':[],'source_cutoff_sha256':grant['source']['cutoff_sha256'],'provider_identity':dict(PROVIDER_BINDINGS[provider_label]),'readback_ref':readback,'dq_checks':checks,'gate_decision':gate,'publication_decision':decision,'denominator_member':True,'retained':True,'raw_capture_verified':True,'provider_artifact_validated':True,'sanitization_safe':True,'readback_match':matched,'replay_allowed':False,'pipeline_trace':['provider_terminal','immutable_owner_private_raw_ref','provider_neutral_envelope','addon_decision','sanitized_publication_decision','canonical_engine_readback_ref']};validate_envelope(env);return env
def _seal_v3(result:DriverResult,authority:FixedAuthorityV3,p0:Optional[Mapping[str,Any]],observed:Optional[ObservedEngineReadbackV3],finalization:Optional[Mapping[str,Any]])->Dict[str,Any]:
 process=result.receipts.get('process',{});gateway=result.receipts.get('gateway',{});cleanup=result.receipts.get('custody_cleanup',{});engine=result.receipts.get('engine_readback',{});durable=bool(finalization and finalization.get('durable'));surviving=bool(finalization and finalization.get('authoritative_marker_present'))
 if result.outcome=='PASS':require(process.get('exit_code')==0 and result.counters.get('terminals')==1,'V3_PASS_EXIT_OR_TERMINAL');require(gateway.get('listener_closed') is True and gateway.get('thread_stopped') is True and cleanup.get('authoritative_pass_safe') is True,'V3_PASS_CLEANUP');require(result.engine.get('grant_sha256')==authority.grant_sha256 and engine.get('exact') is True and engine.get('status')=='succeeded','V3_PASS_ENGINE_GRANT');require(observed is not None,'V3_PASS_READBACK')
 return {'version':3,'kind':'R6_CODEX_POST_RUN_EXECUTION_SEAL','authority':'EVIDENCE_ONLY_NOT_DISPATCH_AUTHORITY','pregrant_sha256':authority.grant_sha256,'pregrant_review_sha256':authority.review_sha256,'engine_grant_sha256':result.engine.get('grant_sha256','0'*64),'outcome':result.outcome,'code':result.code,'process_exit_code':process.get('exit_code'),'exact_terminal':result.counters.get('terminals')==1,'gateway_closed':gateway.get('listener_closed') is True and gateway.get('thread_stopped') is True,'process_reaped':all(process.get(k) is True for k in ('process_group_reaped','descendants_reaped','pid_gone','child_pid_gone','verified_copy_removed')),'custody_clean':cleanup.get('authoritative_pass_safe') is True,'observed_readback_sha256':observed.p0_receipt_sha256 if observed else '0'*64,'observed_transaction':observed.transaction if observed else None,'observed_cardinalities':dict(observed.cardinalities) if observed else None,'p0_envelope_sha256':sha256_bytes(canonical_bytes(p0)) if p0 else '0'*64,'durable_unknown':durable,'surviving_authoritative_marker':surviving,'authoritative_pass_claim':result.outcome=='PASS' and not surviving,'fence':{'retry':False,'replay':False,'status_calls':0,'reconciliation':False},'countable_observation':False}
def _unknown_result_v3(result:DriverResult,finalization:Mapping[str,Any])->DriverResult:
 code='DURABLE_UNKNOWN' if finalization.get('durable') else 'NON_DURABLE_UNKNOWN';receipts=dict(result.receipts,total_unknown_finalizer=dict(finalization));return DriverResult('UNKNOWN',code,False,result.engine,result.counters,receipts,finalization)
def execute_provider_free_v3(*,custody_parent:Path,execution_id:str,fixture_port:int,cell_id:str)->IntegrationResultV3:return _execute_case(custody_parent=custody_parent,execution_id=execution_id,fixture_port=fixture_port,cell_id=cell_id,case='nominal')
def _execute_case(*,custody_parent:Path,execution_id:str,fixture_port:int,cell_id:str,case:str)->IntegrationResultV3:
 require(case in CASES,'V3_CASE_DENIED');parent=_custody_parent(custody_parent);require(type(fixture_port) is int and 0<fixture_port<65536,'V3_FIXTURE_PORT');authority=load_fixed_authority_v3(cell_id);grant=authority.grant;prompt=_prompt(authority);publisher=AtomicPublisher(parent,'short_write' if case in ('publication_fault','second_publication_failure') else None);counters=_counters();receipts:Dict[str,Any]={};raw_terminal=b'';lifecycle_state:Dict[str,Any]={};now=datetime.now(timezone.utc);engine_workspace=parent/('.engine-v3-'+execution_id);engine_workspace.mkdir(mode=0o700);adapter=CanonicalEngineAdapterV3(engine_workspace,engine_workspace/'.job-runtime/state',execution_id,prompt,authority.grant_sha256,now,'readback' if case=='engine_mismatch' else None);guard=EffectGuard('0.01','0.01',time.monotonic()+60,time.monotonic)
 def lifecycle(context:Mapping[str,Any],job_id:str):
  nonlocal raw_terminal
  ids={'job_id':job_id,'slot_id':context['slot_id'],'attempt_id':context['attempt_id'],'operation_id':context['operation_id']};custody=None;controller=None;gateway=None;binding=None;outcome='STOP';code='NOT_STARTED';local={};cleanup={};admitted=False
  try:
   custody=FixtureCustody(parent,execution_id);fingerprint,admission=make_request_fingerprint(ids['operation_id'],grant['prompt']['sha256'],sha256_bytes(b'{}'));binding=ExecutionBinding(ids['job_id'],ids['slot_id'],ids['attempt_id'],ids['operation_id'],'process-'+execution_id,fingerprint,grant['treatment']['model'],grant['prompt']['sha256'],authority.grant_sha256);controller=FixtureProcessController(binding,guard);stdout=custody.path_for('stdout.jsonl');stderr=custody.path_for('stderr.log');plan=ProcessPlan(tuple(grant['argv']),{'HOME':str(parent),'CODEX_HOME':str(parent),'PATH':'/usr/bin:/bin'},str(ROOT),prompt,False,True,float(grant['limits']['process_timeout_seconds']),0,case if case in ('second','malformed','multiple','contradictory','pre_timeout','post_timeout','nonzero_success') else 'nominal',str(stdout),str(stderr),grant['binary']['bytes'],grant['binary']['sha256'],0o755,os.getuid());controller.prepare_verified_binary(plan);gateway=ResponsesGateway(fingerprint,admission,3,fixture_endpoint=Endpoint('127.0.0.1',fixture_port,False),provider_free_fixture=True);port=gateway.start();plan=ProcessPlan(plan.argv,plan.environment,plan.cwd,plan.stdin,plan.shell,plan.new_process_group,plan.total_timeout_seconds,port,plan.scenario,plan.stdout_path,plan.stderr_path,plan.expected_binary_bytes,plan.expected_binary_sha256,plan.expected_binary_mode,plan.expected_binary_uid);pr=controller.run(plan);counters['process_starts']=1;raw_terminal=pr.stdout;local['process']={'kind':'process','binding':binding.public(),'exit_code':pr.exit_code,'timed_out':pr.timed_out,'process_group_reaped':pr.process_group_reaped,'descendants_reaped':pr.descendants_reaped,'descriptors_closed':pr.descriptors_closed,'pid_gone':pr.pid_gone,'child_pid_gone':pr.child_pid_gone,'verified_copy_removed':False,'stdin_bytes':pr.stdin_bytes,'executed_private_copy':pr.executed_private_copy}
   if pr.timed_out:code='TIMEOUT_AFTER_ADMISSION' if gateway.admissions else 'TIMEOUT_BEFORE_ADMISSION'
   elif pr.exit_code!=0:code='PROCESS_NONZERO'
   else:
    try:local['terminal']=translate(pr.stdout,{'upstream_attempts':gateway.provider_forwards,'terminal_present':gateway.terminal_present},binding);counters['terminals']=1;outcome='PASS';code='V2_NOMINAL_ONE'
    except Exception:code='TERMINAL_INVALID'
  except Exception:code='V2_LOCAL_FAILURE'
  finally:
   if controller:
    try:cleanup.update(controller.close())
    except Exception:cleanup.update({'process_group_reaped':False,'descendants_reaped':False,'descriptors_closed':False,'pid_gone':False,'child_pid_gone':False,'verified_copy_removed':False})
   if gateway:
    try:g=gateway.close();local['gateway']=dict(g,kind='gateway',binding=binding.public() if binding else {})
    except Exception:g={'listener_closed':False,'thread_stopped':False,'admissions':gateway.admissions,'provider_forwards':gateway.provider_forwards,'second_rejections':gateway.second_rejections};local['gateway']=dict(g,kind='gateway',binding=binding.public() if binding else {})
    admitted=g.get('admissions')==1;counters.update(admissions=g.get('admissions',0),dispatches=g.get('admissions',0),upstream_attempts=g.get('provider_forwards',0),second_rejections=g.get('second_rejections',0))
   if custody:local['custody_cleanup']=custody.destroy(False)
   if 'process' in local:
    for k in ('process_group_reaped','descendants_reaped','descriptors_closed','pid_gone','child_pid_gone','verified_copy_removed'):local['process'][k]=cleanup.get(k,False)
   clean=bool(local.get('gateway',{}).get('listener_closed') and local.get('gateway',{}).get('thread_stopped') and local.get('custody_cleanup',{}).get('authoritative_pass_safe') and all(local.get('process',{}).get(k) for k in ('process_group_reaped','descendants_reaped','pid_gone','child_pid_gone','verified_copy_removed')))
   if admitted and (outcome!='PASS' or not clean or counters['second_rejections']):outcome='UNKNOWN'
   elif not admitted and outcome!='PASS':outcome='STOP'
   if counters['second_rejections']:code='SECOND_REQUEST_REJECTED_AFTER_ADMISSION'
   if not clean and admitted:code='CLEANUP_INCOMPLETE' if code=='V2_NOMINAL_ONE' else code
  receipts.update(local);rd={k:_digest(v) for k,v in local.items()};er={'job_id':ids['job_id'],'slot_id':ids['slot_id'],'attempt_id':ids['attempt_id'],'operation_id':ids['operation_id'],'process_id':binding.process_id if binding else 'process-unstarted','request_fingerprint':binding.request_fingerprint if binding else '0'*64,'model':grant['treatment']['model'],'input_sha256':grant['prompt']['sha256'],'grant_sha256':authority.grant_sha256,'receipt_digests':rd,'outcome':outcome};lifecycle_state.update(outcome=outcome,code=code,binding=binding,engine_receipt=er,admitted=admitted)
  if outcome=='PASS':typed=ProviderResultV1('codex_cli',ids['operation_id'],Phase.TERMINAL,Submission.DEFINITELY_SUBMITTED,TerminalProof.VERIFIED,ResultStatus.SUCCEEDED,'V2_PASS',receipt=er)
  elif outcome=='UNKNOWN':typed=ProviderResultV1('codex_cli',ids['operation_id'],Phase.STREAMING,Submission.POSSIBLY_SUBMITTED,TerminalProof.ABSENT,ResultStatus.UNKNOWN,'V2_UNKNOWN',failure_kind=FailureKind.MISSING_TERMINAL,receipt=er)
  else:typed=ProviderResultV1('codex_cli',ids['operation_id'],Phase.NOT_STARTED,Submission.NOT_SUBMITTED,TerminalProof.ABSENT,ResultStatus.FAILED,'V2_STOP',failure_kind=FailureKind.LOCAL_CONFIG,receipt=er)
  return typed,er,lifecycle_state
 observed=None;readback=None;engine_error=None
 try:adapter.run(lifecycle);observed=adapter.observed_readback();readback=observed.canonical
 except Exception:engine_error='ENGINE_READBACK_INVALID'
 outcome=lifecycle_state.get('outcome','UNKNOWN' if counters['admissions'] else 'STOP');code=lifecycle_state.get('code',engine_error or 'V3_LOCAL_FAILURE');binding=lifecycle_state.get('binding');expected={'PASS':'succeeded','UNKNOWN':'unknown','STOP':'failed'}[outcome];exact=readback is not None and readback.status==expected and binding is not None and all(readback.binding.get(k)==binding.public().get(k) for k in binding.public()) and readback.receipt==lifecycle_state.get('engine_receipt')
 if not exact:outcome='UNKNOWN' if counters['admissions'] else 'STOP';code=engine_error or 'ENGINE_READBACK_INVALID'
 engine=dict(readback.binding) if readback else {};public={'version':'stage-b-execution-v3','outcome':outcome,'code':code,'countable_observation':False,'binding':binding.public() if binding else None,'engine':{'status':readback.status if readback else None,'transaction':readback.transaction if readback else None,'receipt_sha256':readback.receipt_sha256 if readback else None,'exact_binding':exact},'counters':counters,'receipt_digests':{k:_digest(v) for k,v in receipts.items()},'cleanup':{'gateway_closed':receipts.get('gateway',{}).get('listener_closed') is True,'process_reaped':all(receipts.get('process',{}).get(k) is True for k in ('process_group_reaped','descendants_reaped','pid_gone','child_pid_gone','verified_copy_removed')),'custody_removed':receipts.get('custody_cleanup',{}).get('authoritative_pass_safe') is True},'unknown_fence':{'durable':outcome=='UNKNOWN' and exact and readback.status=='unknown','retry':False,'replay':False,'status_calls':0,'reconciliation':False},'effect_checks':[]}
 publication=None;publication_error=None
 try:publication=publisher.publish('stage-b-execution-v3.json',public,lambda:True)
 except Exception:
  outcome='UNKNOWN' if counters['admissions'] else 'STOP';code='PUBLICATION_FAILED';public.update(outcome=outcome,code=code,unknown_fence={'durable':False,'retry':False,'replay':False,'status_calls':0,'reconciliation':False})
  try:
   if case=='second_publication_failure':raise RuntimeError('SECOND_PUBLICATION_FAILED')
   publication=publisher.publish('stage-b-execution-v3-fence.json',public,lambda:True)
  except Exception:publication_error='SECOND_PUBLICATION_FAILED';publication=None
 receipts['engine_readback']={'status':readback.status if readback else None,'exact':exact,'error':engine_error,'p0_receipt':dict(observed.p0_receipt) if observed else None,'p0_receipt_sha256':observed.p0_receipt_sha256 if observed else None,'cardinalities':dict(observed.cardinalities) if observed else None,'transaction':observed.transaction if observed else None};result=DriverResult(outcome,code,False,engine,counters,receipts,publication);finalization=None;p0=None;fault=case if case in ('revoke_failure','unlink_failure','dirfsync_failure','fence_write_failure','fence_dirfsync_failure','surviving_marker') else None
 try:
  if outcome=='UNKNOWN' and counters['admissions']==1:finalization=finalize_unknown_v3(parent,execution_id,result,publisher,publication_error or code,fault);result=_unknown_result_v3(result,finalization)
  if case in ('revoke_failure','unlink_failure','dirfsync_failure','fence_write_failure','fence_dirfsync_failure','surviving_marker'):raise RuntimeError('FINALIZER_FAULT_TRIGGER')
  if case=='post_p0_exception':raise RuntimeError('POST_P0_EXCEPTION')
  if observed is not None:p0=_p0_v3(result,observed,grant,raw_terminal,public)
  if case=='post_seal_exception':raise RuntimeError('POST_SEAL_EXCEPTION')
  seal=_seal_v3(result,authority,p0,observed,finalization);return IntegrationResultV3(result,seal,p0,finalization,dict(observed.p0_receipt) if observed else None)
 except Exception:
  if counters['admissions']!=1:raise
  if finalization is None:finalization=finalize_unknown_v3(parent,execution_id,result,publisher,'POST_ADMISSION_EXCEPTION',fault)
  result=_unknown_result_v3(result,finalization)
  try:p0=_p0_v3(result,observed,grant,raw_terminal,dict(public,outcome='UNKNOWN',code=result.code,unknown_fence={'durable':bool(finalization.get('durable')),'retry':False,'replay':False,'status_calls':0,'reconciliation':False})) if observed is not None else None
  except Exception:p0=None
  try:seal=_seal_v3(result,authority,p0,observed,finalization)
  except Exception:seal={'version':3,'kind':'R6_CODEX_POST_RUN_EXECUTION_SEAL','outcome':'UNKNOWN','code':'NON_DURABLE_UNKNOWN','authoritative_pass_claim':False,'durable_unknown':False,'surviving_authoritative_marker':bool(finalization.get('authoritative_marker_present')),'countable_observation':False}
  return IntegrationResultV3(result,seal,p0,finalization,dict(observed.p0_receipt) if observed else None)
__all__=['IntegrationResultV3','execute_provider_free_v3']
