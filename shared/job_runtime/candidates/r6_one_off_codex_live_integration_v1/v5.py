"""V5 commit-last vertical with real owner-rooted P0 evidence."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib,json,os,stat,time
from pathlib import Path
from typing import Any,Dict,Mapping,Optional
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.contracts import CELL_BINDINGS,CHECK_NAMES,PROVIDER_BINDINGS,derive_readback_match,validate_envelope
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.contracts import DriverResult,EffectGuard,ExecutionBinding,canonical_bytes,make_request_fingerprint,sha256_bytes
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.custody import FixtureCustody
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.process import FixtureProcessController,ProcessPlan
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.publication import validate_public
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.terminal import translate
from shared.job_runtime.provider_contract import FailureKind,Phase,ProviderResultV1,ResultStatus,Submission,TerminalProof
from .authority_v3 import FixedAuthorityV3,load_fixed_authority_v3
from .engine_v3 import CanonicalEngineAdapterV3,ObservedEngineReadbackV3
from .custody_v5 import ExecutionCustodyV5
from .finalizer_v5 import complete_unknown_v5,failure_receipt,stage_unknown_v5
from .publication_v5 import PublicationV5Error,capture_raw_v5,commit_last_v5,stage_json_v5,stage_sanitized_v5
from .contracts import ContractError,require
from .gateway import Endpoint,ResponsesGateway
ROOT=Path(__file__).resolve().parents[4];FIXTURE_ROOT=(ROOT/'shared/job_runtime/tests/fixtures/r6_one_off_codex_live_integration_v1').resolve();UPSTREAM_RAW=(ROOT/'shared/job_runtime/tests/fixtures/r6_one_off_codex_live_driver_v1/fake_terminal_exact.jsonl').read_bytes()
CASES=frozenset(('nominal','second','malformed','multiple','contradictory','pre_timeout','post_timeout','nonzero_success','engine_mismatch','late_effect','raw_stage_failure','raw_partial_quarantine','artifact_stage_failure','tamper_raw_evidence','tamper_artifact_evidence','p0_stage_failure','seal_stage_failure','commit_failure','missing_marker_unknown','marker_path_absolute','marker_path_traversal','marker_symlink','unknown_partial_quarantine','crash_after_raw','crash_after_artifact','crash_after_unknown_stage','crash_after_p0','crash_after_seal','crash_before_commit'))
REVIEW=("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-codex-live-integration-v4-independent-review-20261111-001.json",10611,"96f09638785d1d64c531357c5eb0d73894f9a1ae6290e4e542438a77cc69261d")
class CrashCutV5(RuntimeError):pass
def _verify_v5_review()->None:
 p=ROOT/REVIEW[0];fd=os.open(p,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
 try:
  st=os.fstat(fd);require(stat.S_ISREG(st.st_mode) and st.st_uid==os.getuid(),'V5_REVIEW_IDENTITY');raw=b''
  while True:
   b=os.read(fd,65536)
   if not b:break
   raw+=b
 finally:os.close(fd)
 require((len(raw),sha256_bytes(raw))==REVIEW[1:],'V5_REVIEW_DRIFT');value=json.loads(raw);require(value.get('verdict')=='OPEN' and len(value.get('findings',[]))==7,'V5_REVIEW_SUBJECT')
@dataclass(frozen=True)
class IntegrationResultV5:
 result:DriverResult;post_run_seal:Optional[Mapping[str,Any]];p0_envelope:Optional[Mapping[str,Any]];finalization:Optional[Mapping[str,Any]];observed_readback:Optional[Mapping[str,Any]];custody_root:str;commit_ref:Optional[Mapping[str,Any]];crash_cut:Optional[str]
def _digest(v:Any)->str:return sha256_bytes(json.dumps(v,sort_keys=True,separators=(',',':')).encode())
def _counters()->Dict[str,int]:return {'catalog_requests':0,'process_starts':0,'admissions':0,'dispatches':0,'upstream_attempts':0,'second_rejections':0,'terminals':0,'retries':0,'replays':0,'status_calls':0,'reconciliations':0}
def _prompt(authority:FixedAuthorityV3)->bytes:
 rel=authority.grant['prompt']['source_ref'];value=json.loads((ROOT/rel).read_text());raw=value['prompt_utf8'].encode();require((len(raw),sha256_bytes(raw))==(authority.grant['prompt']['bytes'],authority.grant['prompt']['sha256']),'V2_PROMPT_DRIFT');return raw
def _custody_parent(path:Path)->Path:
 p=path.resolve();require(p.is_dir() and not p.is_symlink() and (p==FIXTURE_ROOT or FIXTURE_ROOT in p.parents),'V2_FIXTURE_CUSTODY_ONLY');return p
def _p0_v5(result:DriverResult,observed:ObservedEngineReadbackV3,grant:Mapping[str,Any],raw_ref:Mapping[str,Any],artifact_ref:Mapping[str,Any],artifact_value:Mapping[str,Any],custody:ExecutionCustodyV5)->Mapping[str,Any]:
 provider_label,addon_label,enabled=CELL_BINDINGS[grant['cell_id']];readback=dict(observed.p0_receipt);key={'cell_id':grant['cell_id'],'job_id':readback['job_id'],'slot_id':readback['slot_id'],'attempt_id':readback['attempt_id'],'operation_id':readback['operation_id'],'prompt_binding_sha256':readback['prompt_binding_sha256'],'canonical_engine_readback_digest':observed.p0_receipt_sha256};matched=derive_readback_match(key,readback);raw_verified=custody.verify_ref(raw_ref);artifact_verified=custody.verify_ref(artifact_ref)
 try:validate_public(dict(artifact_value));sanitization=True
 except Exception:sanitization=False
 checks=[{'name':n,'status':'UNKNOWN' if enabled else 'NOT_RUN_TREATMENT_DISABLED','code':'CHECK_RESULT_MISSING' if enabled else 'NOT_RUN_TREATMENT_DISABLED'} for n in CHECK_NAMES];terminal=result.outcome
 from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.contracts import derive_decisions
 semantic={'key':key,'readback_ref':readback,'dq_checks':checks,'checks_enabled':enabled,'terminal_state':terminal,'raw_capture_verified':raw_verified,'provider_artifact_validated':artifact_verified and sanitization,'sanitization_safe':sanitization};matched,gate,decision=derive_decisions(semantic);simple_raw={'name':raw_ref['relative_ref'],'sha256':raw_ref['sha256'],'bytes':raw_ref['bytes'],'owner_private':True,'public':False};simple_artifact={'name':artifact_ref['relative_ref'],'provider_schema':'stage-b-execution-v3','publication_driver_identity_sha256':PROVIDER_BINDINGS[provider_label]['publication_driver_identity_sha256'],'sha256':artifact_ref['sha256'],'bytes':artifact_ref['bytes'],'owner_private':True,'public':False,'provider_validated':artifact_verified and sanitization}
 env={'version':1,'key':key,'blind_provider_label':provider_label,'blind_addon_label':addon_label,'checks_enabled':enabled,'terminal_state':terminal,'raw_ref':simple_raw,'publication_artifact_ref':simple_artifact,'source_inventory':list(grant['source']['allowed']),'citation_inventory':[],'source_cutoff_sha256':grant['source']['cutoff_sha256'],'provider_identity':dict(PROVIDER_BINDINGS[provider_label]),'readback_ref':readback,'dq_checks':checks,'gate_decision':gate,'publication_decision':decision,'denominator_member':True,'retained':True,'raw_capture_verified':raw_verified,'provider_artifact_validated':artifact_verified and sanitization,'sanitization_safe':sanitization,'readback_match':matched,'replay_allowed':False,'pipeline_trace':['provider_terminal','immutable_owner_private_raw_ref','provider_neutral_envelope','addon_decision','sanitized_publication_decision','canonical_engine_readback_ref']};validate_envelope(env);return env
def _seal_v5(result:DriverResult,authority:FixedAuthorityV3,p0:Optional[Mapping[str,Any]],observed:Optional[ObservedEngineReadbackV3],raw_ref:Optional[Mapping[str,Any]],artifact_ref:Optional[Mapping[str,Any]],publication_state:str)->Dict[str,Any]:
 process=result.receipts.get('process',{});gateway=result.receipts.get('gateway',{});cleanup=result.receipts.get('custody_cleanup',{});engine=result.receipts.get('engine_readback',{})
 if result.outcome=='PASS':require(process.get('exit_code')==0 and result.counters.get('terminals')==1,'V5_PASS_EXIT_OR_TERMINAL');require(gateway.get('listener_closed') is True and gateway.get('thread_stopped') is True and cleanup.get('authoritative_pass_safe') is True,'V5_PASS_CLEANUP');require(result.engine.get('grant_sha256')==authority.grant_sha256 and engine.get('exact') is True and engine.get('status')=='succeeded','V5_PASS_ENGINE_GRANT');require(observed is not None,'V5_PASS_READBACK')
 return {'version':5,'kind':'R6_CODEX_POST_RUN_EXECUTION_SEAL','authority':'EVIDENCE_ONLY_NOT_DISPATCH_AUTHORITY','pregrant_sha256':authority.grant_sha256,'pregrant_review_sha256':authority.review_sha256,'engine_grant_sha256':result.engine.get('grant_sha256','0'*64),'outcome':result.outcome,'code':result.code,'process_exit_code':process.get('exit_code'),'exact_terminal':result.counters.get('terminals')==1,'gateway_closed':gateway.get('listener_closed') is True and gateway.get('thread_stopped') is True,'process_reaped':all(process.get(k) is True for k in ('process_group_reaped','descendants_reaped','pid_gone','child_pid_gone','verified_copy_removed')),'custody_clean':cleanup.get('authoritative_pass_safe') is True,'observed_readback_sha256':observed.p0_receipt_sha256 if observed else '0'*64,'observed_transaction':observed.transaction if observed else None,'observed_cardinalities':dict(observed.cardinalities) if observed else None,'p0_envelope_sha256':sha256_bytes(canonical_bytes(p0)) if p0 else '0'*64,'raw_ref':dict(raw_ref) if raw_ref else None,'artifact_ref':dict(artifact_ref) if artifact_ref else None,'publication_state':publication_state,'authoritative_pass_claim':False,'fence':{'retry':False,'replay':False,'status_calls':0,'reconciliation':False},'countable_observation':False}
def _unknown_result_v5(result:DriverResult,receipt:Mapping[str,Any])->DriverResult:
 receipts=dict(result.receipts,total_unknown_finalizer=dict(receipt));return DriverResult('UNKNOWN',receipt['state'],False,result.engine,result.counters,receipts,receipt)
def execute_provider_free_v5(*,custody_parent:Path,execution_id:str,fixture_port:int,cell_id:str)->IntegrationResultV5:return _execute_case(custody_parent=custody_parent,execution_id=execution_id,fixture_port=fixture_port,cell_id=cell_id,case='nominal')
def _execute_case(*,custody_parent:Path,execution_id:str,fixture_port:int,cell_id:str,case:str)->IntegrationResultV5:
 require(case in CASES,'V5_CASE_DENIED');parent=_custody_parent(custody_parent);require(type(fixture_port) is int and 0<fixture_port<65536,'V5_FIXTURE_PORT');_verify_v5_review();authority=load_fixed_authority_v3(cell_id);grant=authority.grant;prompt=_prompt(authority);custody_v5=ExecutionCustodyV5(parent,execution_id);process_parent=custody_v5.root/'process';counters=_counters();receipts:Dict[str,Any]={};raw_terminal=b'';lifecycle_state:Dict[str,Any]={};now=datetime.now(timezone.utc);engine_workspace=custody_v5.root/'.engine';engine_workspace.mkdir(mode=0o700);adapter=CanonicalEngineAdapterV3(engine_workspace,engine_workspace/'.job-runtime/state',execution_id,prompt,authority.grant_sha256,now,'readback' if case=='engine_mismatch' else None);guard=EffectGuard('0.01','0.01',time.monotonic()+60,time.monotonic)
 def lifecycle(context:Mapping[str,Any],job_id:str):
  nonlocal raw_terminal
  ids={'job_id':job_id,'slot_id':context['slot_id'],'attempt_id':context['attempt_id'],'operation_id':context['operation_id']};process_custody=None;controller=None;gateway=None;binding=None;outcome='STOP';code='NOT_STARTED';local={};cleanup={};admitted=False
  try:
   process_custody=FixtureCustody(process_parent,execution_id);fingerprint,admission=make_request_fingerprint(ids['operation_id'],grant['prompt']['sha256'],sha256_bytes(b'{}'));binding=ExecutionBinding(ids['job_id'],ids['slot_id'],ids['attempt_id'],ids['operation_id'],'process-'+execution_id,fingerprint,grant['treatment']['model'],grant['prompt']['sha256'],authority.grant_sha256);controller=FixtureProcessController(binding,guard);stdout=process_custody.path_for('stdout.jsonl');stderr=process_custody.path_for('stderr.log');plan=ProcessPlan(tuple(grant['argv']),{'HOME':str(custody_v5.root),'CODEX_HOME':str(custody_v5.root),'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1'},str(ROOT),prompt,False,True,float(grant['limits']['process_timeout_seconds']),0,case if case in ('second','malformed','multiple','contradictory','pre_timeout','post_timeout','nonzero_success') else 'second' if case in ('missing_marker_unknown','marker_path_absolute','marker_path_traversal','marker_symlink','unknown_partial_quarantine') else 'nominal',str(stdout),str(stderr),grant['binary']['bytes'],grant['binary']['sha256'],0o755,os.getuid());controller.prepare_verified_binary(plan);gateway=ResponsesGateway(fingerprint,admission,3,fixture_endpoint=Endpoint('127.0.0.1',fixture_port,False),provider_free_fixture=True);port=gateway.start();plan=ProcessPlan(plan.argv,plan.environment,plan.cwd,plan.stdin,plan.shell,plan.new_process_group,plan.total_timeout_seconds,port,plan.scenario,plan.stdout_path,plan.stderr_path,plan.expected_binary_bytes,plan.expected_binary_sha256,plan.expected_binary_mode,plan.expected_binary_uid);pr=controller.run(plan);counters['process_starts']=1;raw_terminal=pr.stdout;local['process']={'kind':'process','binding':binding.public(),'exit_code':pr.exit_code,'timed_out':pr.timed_out,'process_group_reaped':pr.process_group_reaped,'descendants_reaped':pr.descendants_reaped,'descriptors_closed':pr.descriptors_closed,'pid_gone':pr.pid_gone,'child_pid_gone':pr.child_pid_gone,'verified_copy_removed':False,'stdin_bytes':pr.stdin_bytes,'executed_private_copy':pr.executed_private_copy}
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
   if process_custody:local['custody_cleanup']=process_custody.destroy(False)
   if 'process' in local:
    for k in ('process_group_reaped','descendants_reaped','descriptors_closed','pid_gone','child_pid_gone','verified_copy_removed'):local['process'][k]=cleanup.get(k,False)
   clean=bool(local.get('gateway',{}).get('listener_closed') and local.get('gateway',{}).get('thread_stopped') and local.get('custody_cleanup',{}).get('authoritative_pass_safe') and all(local.get('process',{}).get(k) for k in ('process_group_reaped','descendants_reaped','pid_gone','child_pid_gone','verified_copy_removed')))
   if admitted and (outcome!='PASS' or not clean or counters['second_rejections']):outcome='UNKNOWN'
   elif not admitted and outcome!='PASS':outcome='STOP'
   if counters['second_rejections']:code='SECOND_REQUEST_REJECTED_AFTER_ADMISSION'
   if case=='late_effect' and admitted:guard.late_effects.append('INJECTED_LATE_EFFECT')
   if admitted and guard.late_effects:outcome='UNKNOWN';code='LATE_EFFECT_AFTER_ADMISSION'
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
 engine=dict(readback.binding) if readback else {};public={'version':'stage-b-execution-v3','outcome':outcome,'code':code,'countable_observation':False,'binding':binding.public() if binding else None,'engine':{'status':readback.status if readback else None,'transaction':readback.transaction if readback else None,'receipt_sha256':readback.receipt_sha256 if readback else None,'exact_binding':exact},'counters':counters,'receipt_digests':{k:_digest(v) for k,v in receipts.items()},'cleanup':{'gateway_closed':receipts.get('gateway',{}).get('listener_closed') is True,'process_reaped':all(receipts.get('process',{}).get(k) is True for k in ('process_group_reaped','descendants_reaped','pid_gone','child_pid_gone','verified_copy_removed')),'custody_removed':receipts.get('custody_cleanup',{}).get('authoritative_pass_safe') is True},'unknown_fence':{'durable':outcome=='UNKNOWN' and exact and readback.status=='unknown','retry':False,'replay':False,'status_calls':0,'reconciliation':False},'effect_checks':list(guard.effects)}
 result=DriverResult(outcome,code,False,engine,counters,dict(receipts,engine_readback={'status':readback.status if readback else None,'exact':exact,'error':engine_error,'p0_receipt':dict(observed.p0_receipt) if observed else None,'p0_receipt_sha256':observed.p0_receipt_sha256 if observed else None,'cardinalities':dict(observed.cardinalities) if observed else None,'transaction':observed.transaction if observed else None}),None);finalization=None;p0=None;commit_ref=None;crash_cut=None;raw_ref=None;artifact_ref=None
 def crash(point:str)->None:
  if case==point:raise CrashCutV5(point)
 try:
  if result.counters.get('admissions',0)==0:
   cleanup=custody_v5.cleanup_nonauthoritative();return IntegrationResultV5(result,None,None,None,dict(observed.p0_receipt) if observed else None,str(custody_v5.root),None,None)
  guard.observe('before_raw_capture');raw_ref=capture_raw_v5(custody_v5,raw_terminal,'write_exception' if case=='raw_stage_failure' else 'partial_quarantine' if case=='raw_partial_quarantine' else None);crash('crash_after_raw')
  guard.observe('before_artifact_stage');artifact_ref=stage_sanitized_v5(custody_v5,public,'write_exception' if case=='artifact_stage_failure' else None);crash('crash_after_artifact')
  if case=='tamper_raw_evidence':(custody_v5.root/raw_ref['relative_ref']).write_bytes(b'tampered')
  if case=='tamper_artifact_evidence':(custody_v5.root/artifact_ref['relative_ref']).write_bytes(b'tampered')
  pending=None
  if result.outcome=='UNKNOWN':
   if case=='marker_symlink':
    target=custody_v5.root/'evidence'/'provider-terminal.raw';link=custody_v5.root/'publication'/(execution_id+'.commit');link.symlink_to(target);marker_receipt={'relative_ref':'publication/'+execution_id+'.commit'}
   else:marker_receipt={'relative_ref':'/outside.commit'} if case=='marker_path_absolute' else {'relative_ref':'publication/../outside.commit'} if case=='marker_path_traversal' else None
   pending,failed=stage_unknown_v5(custody_v5,result,result.code,marker_receipt,'partial_quarantine' if case=='unknown_partial_quarantine' else None)
   if failed:finalization=failed;raise PublicationV5Error(failed['error_code'])
  crash('crash_after_unknown_stage')
  p0=_p0_v5(result,observed,grant,raw_ref,artifact_ref,public,custody_v5) if observed is not None else None
  if p0 is None or not(p0['raw_capture_verified'] and p0['provider_artifact_validated'] and p0['sanitization_safe'] and p0['readback_match']):raise PublicationV5Error('V5_P0_REAL_EVIDENCE_REQUIRED')
  p0_ref=stage_json_v5(custody_v5,'p0-envelope.json',p0,'write_exception' if case=='p0_stage_failure' else None);crash('crash_after_p0')
  staged_seal=_seal_v5(result,authority,p0,observed,raw_ref,artifact_ref,'NONAUTHORITATIVE_STAGED');seal_ref=stage_json_v5(custody_v5,'post-run-seal.json',staged_seal,'write_exception' if case=='seal_stage_failure' else None);crash('crash_after_seal');crash('crash_before_commit')
  if guard.late_effects and result.outcome=='PASS':raise PublicationV5Error('V5_LATE_EFFECT_BEFORE_COMMIT')
  guard.observe('before_authoritative_commit');commit_ref=commit_last_v5(custody_v5,result.outcome,artifact_ref,p0_ref,seal_ref,pending.pending_ref if pending else None,'write_exception' if case=='commit_failure' else None)
  if pending:finalization=complete_unknown_v5(pending,commit_ref);result=_unknown_result_v5(result,finalization)
  committed_result=DriverResult(result.outcome,result.code,False,result.engine,result.counters,result.receipts,commit_ref);final_seal=dict(staged_seal,publication_state='COMMITTED',authoritative_pass_claim=result.outcome=='PASS',commit_ref=dict(commit_ref));return IntegrationResultV5(committed_result,final_seal,p0,finalization,dict(observed.p0_receipt) if observed else None,str(custody_v5.root),dict(commit_ref),None)
 except CrashCutV5 as exc:
  crash_cut=str(exc);cleanup=custody_v5.cleanup_nonauthoritative();finalization=failure_receipt('CRASH_CUT_'+crash_cut.upper(),cleanup=cleanup);result=_unknown_result_v5(result,finalization);return IntegrationResultV5(result,None,p0,finalization,dict(observed.p0_receipt) if observed else None,str(custody_v5.root),None,crash_cut)
 except Exception as exc:
  cleanup=custody_v5.cleanup_nonauthoritative();finalization=finalization or failure_receipt(str(exc) if isinstance(exc,PublicationV5Error) else 'V5_POST_ADMISSION_EXCEPTION',cleanup=cleanup);result=_unknown_result_v5(result,finalization);return IntegrationResultV5(result,None,p0,finalization,dict(observed.p0_receipt) if observed else None,str(custody_v5.root),None,None)
 finally:custody_v5.close()
__all__=['IntegrationResultV5','execute_provider_free_v5']
