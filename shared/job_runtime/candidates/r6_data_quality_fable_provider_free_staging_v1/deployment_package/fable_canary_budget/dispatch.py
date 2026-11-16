"""TEST_ONLY inactive claim-immediately-before-provider Service seam."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from threading import local
from shared.job_runtime.prompt_custody import PromptArtifactDescriptorV1
from shared.job_runtime.provider_contract import ProviderResultV1
from shared.job_runtime.service import dispatcher as service_dispatcher
from . import budget as budget_module
from .budget import ARMS,CAMPAIGN,JOBS,BudgetError,CampaignBudgetLedger
from .journal import EffectClaim,JournalError,derive_effect_nonce
ACTIVATION=False;MODEL="claude-fable-5-1";PROFILE="fable-5-1-dq-disabled";RESOURCE="fable-5-1-dq-v1-shared";PROMPT_SHA256="3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b"
class DispatchFenceError(ValueError):pass
def _canonical(value):return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode()
def _provider(value):return value.value if hasattr(value,"value") else value
def _unknown(operation,code):
 return ProviderResultV1(provider='claude_host',operation_id=operation,phase='submitted',submission='possibly_submitted',terminal_proof='absent',status='unknown',code=code,failure_kind='unknown',provider_should_retry=False,receipt={'candidate':CAMPAIGN,'activation':False})
def _job_identity(job,context):
 arm=ARMS.get(job.get('id'));artifact=job.get('_prompt_artifact');contract=job.get('_replay_contract');retry=job.get('_retry_policy')
 valid=(arm is not None and job.get('model_profile')==PROFILE and _provider(job.get('_provider'))=='claude_host' and job.get('_resource_key')==RESOURCE and isinstance(artifact,PromptArtifactDescriptorV1) and artifact.sha256==PROMPT_SHA256 and artifact.length==526 and getattr(getattr(contract,'effect',None),'value',None)=='none' and getattr(retry,'max_attempts',None)==1 and all(isinstance(context.get(k),str) and context[k] for k in ('slot_id','attempt_id','operation_id')) and context.get('prompt_artifact')==artifact)
 if not valid:raise DispatchFenceError('CANARY_ENGINE_IDENTITY_INVALID')
 return arm
def campaign_dispatcher(config,workspace,provider_callable):
 if ACTIVATION or not callable(provider_callable):raise DispatchFenceError('PROVIDER_FAKE_REQUIRED')
 workspace=Path(workspace).resolve();slot=local();ledger=CampaignBudgetLedger(workspace/'.job-runtime/acceptance/fable-5-1-dq-v1/campaign-budget.sqlite',approved_root=workspace/'.job-runtime/acceptance/fable-5-1-dq-v1',create=False)
 def override(profile,prompt,provider_workspace,run_dir,operation_id,provider_context):
  binding=getattr(slot,'binding',None)
  if not binding or operation_id!=binding['operation_id'] or Path(provider_workspace).resolve()!=workspace:return _unknown(operation_id,'CANARY_BINDING_INVALID')
  if profile.get('model')!=MODEL or profile.get('effort')!='low' or profile.get('max_budget_usd')!=0.02:return _unknown(operation_id,'CANARY_PROFILE_INVALID')
  try:
   expected_nonce=derive_effect_nonce(binding)
   with EffectClaim(ledger.root,binding) as effect:
    if effect.nonce!=expected_nonce:raise JournalError('EFFECT_NONCE_DERIVATION_MISMATCH')
    try:claim=ledger.claim(binding['job_id'],effect.nonce,'0.02',deployment_id=CAMPAIGN,attempt_id=binding['attempt_id'],slot_id=binding['slot_id'],operation_id=operation_id)
    except BudgetError:return _unknown(operation_id,'CANARY_LEDGER_BLOCKED')
    try:budget_module._hook('pre_provider',ledger.path);ledger.assert_custody();result=provider_callable(profile,prompt,provider_workspace,run_dir,operation_id,provider_context)
    except Exception:return _unknown(operation_id,'CANARY_PROVIDER_OUTCOME_UNKNOWN')
    if not isinstance(result,ProviderResultV1):return _unknown(operation_id,'CANARY_PROVIDER_RESULT_INVALID')
    exact=(_provider(result.provider)=='claude_host' and result.operation_id==operation_id and result.phase.value=='terminal' and result.terminal_proof.value=='verified')
    if not exact:return _unknown(operation_id,'CANARY_PROVIDER_IDENTITY_INVALID')
    if result.status.value=='succeeded' and result.submission.value=='definitely_submitted' and result.failure_kind.value=='none':outcome='VALID'
    elif result.status.value=='failed':outcome='INVALID'
    else:return _unknown(operation_id,'CANARY_PROVIDER_RESULT_NONTERMINAL')
    try:effect.terminal(outcome,result);ledger.resolve(claim['claim_id'],outcome,provider='claude_host',operation_id=operation_id,result_sha256=result.canonical_sha256)
    except (BudgetError,JournalError):return _unknown(operation_id,'CANARY_RESOLUTION_INVALID')
    return result
  except JournalError:return _unknown(operation_id,'CANARY_EFFECT_CLAIM_BLOCKED')
 base=service_dispatcher(config,workspace,provider_registry={'claude_host':override})
 def dispatch(job,context):
  arm=_job_identity(job,context);binding={'deployment_id':CAMPAIGN,'campaign_id':CAMPAIGN,'job_id':job['id'],'arm':arm,'slot_id':context['slot_id'],'attempt_id':context['attempt_id'],'operation_id':context['operation_id'],'profile':PROFILE,'model':MODEL,'cap':'0.02','resource':RESOURCE,'prompt_sha256':PROMPT_SHA256};slot.binding=binding
  try:return base(job,context)
  finally:slot.binding=None
 return dispatch
