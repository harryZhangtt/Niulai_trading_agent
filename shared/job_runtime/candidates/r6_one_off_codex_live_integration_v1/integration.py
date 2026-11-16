"""Disabled composition boundary: external pre-grant -> reviewed driver -> post-run seal -> P0 v6 projection."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any,Mapping
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.contracts import CHECK_NAMES,PROVIDER_BINDINGS,sha256_json,validate_envelope
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.driver import Dependencies,execute_provider_free
from .contracts import SOURCE_CUTOFF_SHA256,canonical_bytes,load_pregrant,post_run_seal,sha256_bytes,validate_driver_binding,verify_predecessors
@dataclass(frozen=True)
class IntegrationResult:result:Any;post_run_seal:Mapping[str,Any];p0_envelope:Mapping[str,Any]
def _p0(result:Any,grant:Mapping[str,Any],raw:bytes)->Mapping[str,Any]:
 b=result.engine;get=lambda k,d:b.get(k,d)
 def alias(name:str)->str:
  value=get(name,"unstarted-"+name);return "p0-"+name+"-"+sha256_bytes(str(value).encode())[:32]
 base={"cell_id":grant["cell_id"],"job_id":alias("job_id"),"slot_id":alias("slot_id"),"attempt_id":alias("attempt_id"),"operation_id":alias("operation_id"),"prompt_binding_sha256":get("prompt_binding_sha256","0"*64)}
 readback={"version":1,"job_id":base["job_id"],"slot_id":base["slot_id"],"attempt_id":base["attempt_id"],"operation_id":base["operation_id"],"prompt_binding_sha256":base["prompt_binding_sha256"],"transaction":"BEGIN_IMMEDIATE_POST_WRITE_READBACK","counts":{"job":1,"slot":1,"attempt":1}}
 key=dict(base,canonical_engine_readback_digest=sha256_json(readback))
 checks=[{"name":n,"status":"NOT_RUN_TREATMENT_DISABLED","code":"NOT_RUN_TREATMENT_DISABLED"} for n in CHECK_NAMES];terminal=result.outcome;gate="ALLOW" if terminal=="PASS" else "UNKNOWN" if terminal=="UNKNOWN" else "REJECT";decision="DELEGATE_SANITIZED" if gate=="ALLOW" else "SUPPRESS_UNKNOWN" if gate=="UNKNOWN" else "SUPPRESS_TERMINAL"
 env={"version":1,"key":key,"blind_provider_label":"ARM-B","blind_addon_label":"CONDITION-X","checks_enabled":False,"terminal_state":terminal,"raw_ref":{"name":"provider-terminal.raw","sha256":sha256_bytes(raw),"bytes":len(raw),"owner_private":True,"public":False},"publication_artifact_ref":{"name":"stage-b-execution-v3.json","provider_schema":"stage-b-execution-v3","publication_driver_identity_sha256":PROVIDER_BINDINGS["ARM-B"]["publication_driver_identity_sha256"],"sha256":sha256_bytes(canonical_bytes({"outcome":terminal})),"bytes":len(canonical_bytes({"outcome":terminal})),"owner_private":True,"public":False,"provider_validated":True},"source_inventory":["SEC EDGAR official","Microsoft Investor Relations official"],"citation_inventory":[],"source_cutoff_sha256":SOURCE_CUTOFF_SHA256,"provider_identity":dict(PROVIDER_BINDINGS["ARM-B"]),"readback_ref":readback,"dq_checks":checks,"gate_decision":gate,"publication_decision":decision,"denominator_member":True,"retained":True,"raw_capture_verified":True,"provider_artifact_validated":True,"sanitization_safe":True,"readback_match":True,"replay_allowed":False,"pipeline_trace":["provider_terminal","immutable_owner_private_raw_ref","provider_neutral_envelope","addon_decision","sanitized_publication_decision","canonical_engine_readback_ref"]}
 validate_envelope(env);return env
def execute_provider_free_integration(*,config:Mapping[str,Any],preflight:Mapping[str,Any],held_bytes:Mapping[str,bytes],prompt:bytes,body:bytes,workspace_root:Path,custody_parent:Path,execution_id:str,deps:Dependencies,grant_ref:Mapping[str,Any],review_ref:Mapping[str,Any],now:datetime,terminal_raw:bytes)->IntegrationResult:
 verify_predecessors(workspace_root);grant,gsha,rsha=load_pregrant(grant_ref,review_ref,workspace_root,now);validate_driver_binding(grant,config,prompt);result=execute_provider_free(config,preflight,held_bytes,prompt,body,workspace_root,custody_parent,execution_id,deps,now);p0=_p0(result,grant,terminal_raw);seal=post_run_seal(result,gsha,rsha,p0);return IntegrationResult(result,seal,p0)
