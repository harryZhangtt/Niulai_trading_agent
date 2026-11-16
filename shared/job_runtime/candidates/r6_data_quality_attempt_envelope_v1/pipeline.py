"""Identical OFF/ON pipeline with owner-rooted research evidence in one attempt bundle."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence
from .adapters import PrimitiveAdapter,provider_identity_for_adapter
from .artifacts import OwnerArtifactStore, validate_bundle_owner_artifacts
from .bundle import AttemptBundleStore, BundleCommitError
from .contracts import (CHECK_NAMES, ContractError, TRACE, canonical_bytes, derive_decisions,
                        sha256_bytes, sha256_json, validate_attempt, validate_attempt_bundle,
                        validate_envelope, validate_publication_decision,
                        validate_raw_custody_receipt, validate_readback,
                        validate_research_evidence)
class PipelineError(ContractError):pass
def disabled_checks()->list:return [{"name":n,"status":"NOT_RUN_TREATMENT_DISABLED","code":"NOT_RUN_TREATMENT_DISABLED"} for n in CHECK_NAMES]
def _raw_ref(name:str,raw:bytes)->Dict[str,Any]:return {"name":name,"sha256":sha256_bytes(raw),"bytes":len(raw),"owner_private":True,"public":False}
def execute(adapter:PrimitiveAdapter,bundle_root:Path,*,cell_id:str,blind_addon_label:str,checks_enabled:bool,job_id:str,slot_id:str,attempt_id:str,operation_id:str,prompt_binding_sha256:str,readback:Mapping[str,Any],raw:bytes,provider_publication_artifact:Mapping[str,Any],research_material:Mapping[str,Any],terminal_state:str,source_cutoff_sha256:str,dq_checks:Optional[Sequence[Mapping[str,str]]]=None,claimed_readback_digest:Optional[str]=None,retention_fault:Optional[str]=None)->Dict[str,Any]:
    validate_readback(dict(readback));provider_identity=dict(provider_identity_for_adapter(adapter,cell_id));actual_readback_digest=sha256_json(readback)
    key={"cell_id":cell_id,"job_id":job_id,"slot_id":slot_id,"attempt_id":attempt_id,"operation_id":operation_id,"prompt_binding_sha256":prompt_binding_sha256,"canonical_engine_readback_digest":claimed_readback_digest or actual_readback_digest};key_digest=sha256_json(key);raw_ref=_raw_ref("provider-terminal.raw",raw)
    try:captured=dict(adapter.capture(key_digest,raw))
    except Exception as exc:raise PipelineError("RAW_CAPTURE_FAILED") from exc
    owner_store=OwnerArtifactStore(adapter.owner_root,key_digest)
    try:owner_raw_ref=owner_store.verify_raw(captured,raw)
    except Exception as exc:raise PipelineError(str(exc)) from exc
    capture_verified=True
    try:artifact_raw=canonical_bytes(dict(provider_publication_artifact))
    except ContractError as exc:raise PipelineError("PROVIDER_ARTIFACT_CANONICAL_INVALID") from exc
    provider_validated=True
    try:adapter.validate_publication(dict(provider_publication_artifact))
    except Exception:provider_validated=False
    artifact_ref={"name":"provider-sanitized-publication.json","provider_schema":provider_identity["provider_schema"],"publication_driver_identity_sha256":provider_identity["publication_driver_identity_sha256"],"sha256":sha256_bytes(artifact_raw),"bytes":len(artifact_raw),"owner_private":True,"public":False,"provider_validated":provider_validated}
    require_material={"sanitized_output","factual_evidence","source_inventory","citation_inventory"}
    if type(research_material) is not dict or set(research_material)!=require_material:raise PipelineError("RESEARCH_MATERIAL_SHAPE")
    binding={field:key[field] for field in ("cell_id","job_id","slot_id","attempt_id","operation_id","prompt_binding_sha256","canonical_engine_readback_digest")};binding["source_cutoff_sha256"]=source_cutoff_sha256;binding["blind_provider_label"]=provider_identity["blind_provider_label"];binding["provider_schema"]=provider_identity["provider_schema"];binding["publication_driver_identity_sha256"]=provider_identity["publication_driver_identity_sha256"]
    research_evidence={}
    file_names={"sanitized_output":"sanitized-output.json","factual_evidence":"factual-evidence.json","source_inventory":"source-inventory.json","citation_inventory":"citation-inventory.json"}
    for name in ("sanitized_output","factual_evidence","source_inventory","citation_inventory"):
        body=deepcopy(research_material[name]);ref=owner_store.write_json(file_names[name],body);research_evidence[name]={"body":body,"ref":ref,"canonical_sha256":sha256_json(body)}
    raw_receipt={"version":1,"binding":deepcopy(binding),"provider_terminal":terminal_state,"raw_sha256":raw_ref["sha256"],"raw_ref":owner_raw_ref}
    validate_raw_custody_receipt(raw_receipt,key,terminal_state,raw_ref["sha256"],source_cutoff_sha256,provider_identity["blind_provider_label"],provider_identity["provider_schema"],provider_identity["publication_driver_identity_sha256"])
    validate_research_evidence(research_evidence,key,terminal_state,raw_ref["sha256"],artifact_ref["sha256"],source_cutoff_sha256,provider_identity["blind_provider_label"],provider_identity["provider_schema"],provider_identity["publication_driver_identity_sha256"])
    adapter.validate_research_material(research_material)
    source_ids=[item["source_id"] for item in research_evidence["source_inventory"]["body"]["sources"]]
    citation_ids=[item["citation_id"] for item in research_evidence["citation_inventory"]["body"]["citations"]]
    safety=provider_validated;checks=[dict(x) for x in (dq_checks if checks_enabled else disabled_checks())]
    if checks_enabled and dq_checks is None:checks=[{"name":n,"status":"UNKNOWN","code":"CHECK_RESULT_MISSING"} for n in CHECK_NAMES]
    semantic_seed={"key":key,"readback_ref":dict(readback),"dq_checks":checks,"checks_enabled":checks_enabled,"terminal_state":terminal_state,"raw_capture_verified":capture_verified,"provider_artifact_validated":provider_validated,"sanitization_safe":safety}
    readback_match,gate,decision=derive_decisions(semantic_seed)
    attempt={"version":1,"key":key,"blind_provider_label":provider_identity["blind_provider_label"],"blind_addon_label":blind_addon_label,"checks_enabled":checks_enabled,"terminal_state":terminal_state,"raw_ref":raw_ref,"publication_artifact_ref":artifact_ref,"source_inventory":source_ids,"citation_inventory":citation_ids,"source_cutoff_sha256":source_cutoff_sha256,"provider_identity":deepcopy(provider_identity),"raw_capture_before_decision":True,"no_replay":True,"readback_ref":dict(readback)};validate_attempt(attempt)
    envelope={k:deepcopy(attempt[k]) for k in ("version","key","blind_provider_label","blind_addon_label","checks_enabled","terminal_state","raw_ref","publication_artifact_ref","source_inventory","citation_inventory","source_cutoff_sha256","provider_identity")};envelope["readback_ref"]=deepcopy(readback);envelope.update({"dq_checks":checks,"gate_decision":gate,"publication_decision":decision,"denominator_member":True,"retained":True,"raw_capture_verified":capture_verified,"provider_artifact_validated":provider_validated,"sanitization_safe":safety,"readback_match":readback_match,"replay_allowed":False,"pipeline_trace":list(TRACE)});validate_envelope(envelope)
    denominator={"version":1,"cell_id":cell_id,"attempt_id":attempt_id,"terminal_state":terminal_state,"disposition":decision,"included":True,"replay_allowed":False,"envelope_sha256":sha256_json(envelope)}
    bundle={"version":1,"key":deepcopy(key),"key_digest":key_digest,"normalized_attempt":deepcopy(attempt),"envelope":deepcopy(envelope),"provider_publication_artifact_body":artifact_raw.decode("ascii"),"publication_artifact_ref":deepcopy(artifact_ref),"provider_identity":deepcopy(provider_identity),"research_evidence":deepcopy(research_evidence),"raw_custody_receipt":deepcopy(raw_receipt),"denominator_record":deepcopy(denominator)};bundle["bundle_digest"]=sha256_json(bundle);validate_attempt_bundle(bundle);validate_bundle_owner_artifacts(adapter.owner_root,bundle)
    store=AttemptBundleStore(Path(bundle_root),retention_fault,owner_root=adapter.owner_root);recovery={"fault":None,"stages_removed":[],"replay":False}
    try:receipt=store.commit(bundle)
    except BundleCommitError as exc:
        if not exc.recoverable:raise PipelineError(str(exc)) from exc
        recovery={"fault":str(exc),"stages_removed":[],"replay":False};receipt=AttemptBundleStore(Path(bundle_root),owner_root=adapter.owner_root).commit(bundle,recovered_fault=str(exc))
    public_decision={"version":1,"key_digest":key_digest,"cell_id":cell_id,"decision":decision,"publication_artifact_sha256":artifact_ref["sha256"],"publication_driver_identity_sha256":provider_identity["publication_driver_identity_sha256"],"raw_included":False,"path_included":False,"secret_included":False,"replay_allowed":False};validate_publication_decision(public_decision);publication={"status":"SUPPRESSED","attempts":0,"replay":False}
    if decision=="DELEGATE_SANITIZED":
        try:publication={"status":"PASS","attempts":1,"replay":False,"receipt":adapter.publish_committed(key_digest,receipt.path,receipt.sha256)}
        except Exception:publication={"status":"UNKNOWN","attempts":1,"replay":False}
    return {"attempt":attempt,"envelope":envelope,"research_evidence":research_evidence,"raw_custody_receipt":raw_receipt,"denominator_record":denominator,"attempt_bundle":bundle,"bundle_receipt":{"path":receipt.path.name,"sha256":receipt.sha256,"bytes":receipt.bytes,"primitive":receipt.primitive,"file_fsync":receipt.file_fsync,"parent_dir_fsync":receipt.parent_dir_fsync,"no_overwrite":receipt.no_overwrite,"recovered_fault":receipt.recovered_fault},"retention_recovery":recovery,"publication_decision":public_decision,"publication":publication}
__all__=["PipelineError","disabled_checks","execute"]
