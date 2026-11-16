"""Canonical Engine adapter exposing its actual P0 readback receipt."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any,Mapping
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.contracts import sha256_json,validate_readback
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.driver import CanonicalEngineAdapter,CanonicalReadback
from shared.job_runtime.engine import Engine
from shared.job_runtime.provider_contract import Phase,ReplayContractV1,ReplayEffect
from shared.job_runtime.retry_policy import RetryPolicyV2
@dataclass(frozen=True)
class ObservedEngineReadbackV3:
 canonical:CanonicalReadback;p0_receipt:Mapping[str,Any];p0_receipt_sha256:str;cardinalities:Mapping[str,int];transaction:str
class CanonicalEngineAdapterV3(CanonicalEngineAdapter):
 def run(self,lifecycle)->Mapping[str,int]:
  if self.fault=='before_tick':raise RuntimeError('ENGINE_INJECTED_BEFORE_TICK')
  policy=RetryPolicyV2(1,1,1,deadline_seconds=60);contract=ReplayContractV1(ReplayEffect.NONE,(Phase.NOT_STARTED,),'r6-o1/codex-fixture-v3')
  slot=self.now.strftime('%H:%M');job={'id':self.job_id,'enabled':True,'replay_safe':False,'schedule':{'kind':'daily','timezone':'UTC','times':[slot],'grace_seconds':3600},'_provider':'codex_cli','_replay_contract':contract,'_retry_policy':policy,'_prompt_artifact':self.descriptor}
  def dispatcher(_job,context):
   result,receipt,state=lifecycle(context,self.job_id);self.expected_receipt=receipt;self.lifecycle=state
   if self.fault=='after_dispatch_before_finish':raise RuntimeError('ENGINE_INJECTED_FINISH')
   return result
  self.engine=Engine(self.state,[job],policy,dispatcher,workspace_root=self.workspace,clock=lambda:self.now,max_workers=1);return self.engine.tick(self.now)
 def observed_readback(self)->ObservedEngineReadbackV3:
  canonical=super().readback();b=canonical.binding;counts=b['counts'];receipt={'version':1,'job_id':b['job_id'],'slot_id':b['slot_id'],'attempt_id':b['attempt_id'],'operation_id':b['operation_id'],'prompt_binding_sha256':b['prompt_binding_sha256'],'transaction':'BEGIN_IMMEDIATE_SINGLE_READBACK','counts':{'job':counts['jobs'],'slot':counts['slots'],'attempt':counts['attempts']}};validate_readback(receipt);return ObservedEngineReadbackV3(canonical,receipt,sha256_json(receipt),dict(counts),'BEGIN_IMMEDIATE_SINGLE_READBACK')
__all__=['CanonicalEngineAdapterV3','ObservedEngineReadbackV3']
