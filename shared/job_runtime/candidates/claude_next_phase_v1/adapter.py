"""Pure adapter from exact-verifier-consumed gateway summaries to campaign state."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Mapping
from shared.job_runtime.candidates.claude_campaign_v1 import (CampaignIdentityV1,EvidenceV1,
    GatewayDisposition,Submission,TerminalDisposition,apply_evidence,compute_evidence_sha256,
    create_initial_state,retry_ready)
from .contracts import GatewayAuthenticatedSummary,IntegrationContractError,IntegrationOwnedVerifier,IntegrationResultV1,O1IdentityBindingV1


def _evidence(identity:CampaignIdentityV1,value:Mapping[str,Any])->EvidenceV1:
    code={("pass_through","success",200):"TERMINAL_SUCCESS",
          ("rejected_before_forward","absent",502):"UPSTREAM_502_REJECTED",
          ("pass_through","failure",502):"UPSTREAM_502_FORWARDED",
          ("cut","absent",502):"FORWARD_CUT"}.get((value["gateway_disposition"],value["terminal_disposition"],value["http_status"]))
    if code is None: raise IntegrationContractError("SUMMARY_MAPPING_NOT_CLOSED")
    digest=compute_evidence_sha256(identity,value["gateway_disposition"],value["terminal_disposition"],
        value["upstream_forward_count"],value["submission"],value["typed_transient"],value["http_status"],value["retry_after_seconds"],code)
    return EvidenceV1(identity=identity,gateway_disposition=GatewayDisposition(value["gateway_disposition"]),
        terminal_disposition=TerminalDisposition(value["terminal_disposition"]),upstream_forward_count=value["upstream_forward_count"],
        submission=Submission(value["submission"]),typed_transient=value["typed_transient"],http_status=value["http_status"],
        retry_after_seconds=value["retry_after_seconds"],code=code,evidence_sha256=digest)


def _consume(identity:CampaignIdentityV1,summary:GatewayAuthenticatedSummary,verifier:IntegrationOwnedVerifier,o1_binding:O1IdentityBindingV1)->tuple[Mapping[str,Any],Any]:
    if not isinstance(verifier,IntegrationOwnedVerifier) or type(summary) is not GatewayAuthenticatedSummary:
        raise IntegrationContractError("AUTHENTICATED_SUMMARY_REQUIRED")
    proof=verifier.consume_summary(summary,identity=identity,o1_binding=o1_binding)
    return summary.value,proof


def adapt_authenticated_summary(identity:CampaignIdentityV1,summary:GatewayAuthenticatedSummary,*,verifier:IntegrationOwnedVerifier,o1_binding:O1IdentityBindingV1)->IntegrationResultV1:
    value,proof=_consume(identity,summary,verifier,o1_binding); evidence=_evidence(identity,value)
    state=create_initial_state(identity,evidence.evidence_sha256,verifier,verifier)
    state=apply_evidence(state,evidence,proof_mapping=proof)
    if state.status=="succeeded": return IntegrationResultV1("R6","succeeded","none",1,1,False,False,None,state,evidence)
    if state.status=="retry_wait": return IntegrationResultV1("R7","retry_wait","restart",1,0,True,False,evidence.retry_after_seconds,state,evidence)
    if state.status=="unknown": return IntegrationResultV1("R8","unknown","reconcile_only",1,1,False,True,None,state,evidence)
    raise IntegrationContractError("CAMPAIGN_RESULT_NOT_EXPOSED")


def complete_retry(previous:IntegrationResultV1,next_identity:CampaignIdentityV1,next_summary:GatewayAuthenticatedSummary,*,verifier:IntegrationOwnedVerifier,o1_binding:O1IdentityBindingV1,now:datetime)->IntegrationResultV1:
    if previous.route!="R7" or previous.status!="retry_wait": raise IntegrationContractError("RETRY_SOURCE_INVALID")
    value,proof=_consume(next_identity,next_summary,verifier,o1_binding); evidence=_evidence(next_identity,value)
    state=retry_ready(previous.state,now,next_identity=next_identity,next_evidence_sha256=evidence.evidence_sha256)
    state=apply_evidence(state,evidence,proof_mapping=proof)
    if state.status!="succeeded" or state.attempts!=2: raise IntegrationContractError("RETRY_TERMINAL_INVALID")
    return IntegrationResultV1("R6","succeeded","none",2,1,False,False,None,state,evidence)
