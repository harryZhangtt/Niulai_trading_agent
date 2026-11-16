"""Synthetic Stage B fixtures; no provider or process surface."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from shared.job_runtime.candidates.r6_one_off_claude_adapter_v1.contracts import (
    EFFORT,
    FROZEN_REFS,
    HistoricalIdentityLedger,
    LIMITS,
    MODEL,
    PAYLOAD_SHA256,
    SURFACE,
    TrustedArtifactRef,
    TrustedExternalGrant,
    TrustedExternalGrantRegistry,
    UNKNOWN_FENCE,
    canonical_bytes,
    held_binding_digest,
    sha256_bytes,
    sha256_json,
)

ROOT = Path(__file__).resolve().parents[5]
FIXTURES = ROOT / "shared/job_runtime/tests/fixtures/r6_one_off_claude_adapter_v1"


def ref_for(path: Path) -> Dict[str, Any]:
    raw = path.read_bytes()
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
    }


def write_artifact(base: Path, name: str, raw: bytes) -> Dict[str, Any]:
    path = base / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return ref_for(path)


def write_json_artifact(base: Path, name: str, value: Any) -> Dict[str, Any]:
    return write_artifact(base, name, canonical_bytes(value))


def build_seal(base: Path, now: Optional[datetime] = None):
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = current - timedelta(minutes=1)
    end = start + timedelta(minutes=30)
    stamp = lambda value: value.isoformat().replace("+00:00", "Z")
    closure = ref_for(ROOT / "tuning/architecture/r6_one_off_claude_adapter_v1/source-closure-v1.json")
    execution_id = "execution/fresh-0001"
    request_id = "request/fresh-0001"
    engine_ids = {"job_id":"job/fresh-0001","slot_id":"slot/fresh-0001","attempt_id":"attempt/fresh-0001","operation_id":"operation/fresh-0001"}
    request_fingerprint = "e" * 64
    canonical_path = "/opt/held/claude"
    descriptor = {"canonical_path":canonical_path,"device":7,"inode":101,"owner_uid":501,"mode":0o755}
    binary = {"artifact":write_artifact(base,"held/claude.bin",b"synthetic-held-cli-bytes\n"),"canonical_path":canonical_path,"descriptor_identity_sha256":sha256_json(descriptor),"device":7,"inode":101,"owner_uid":501,"mode":0o755,"official_asset":write_artifact(base,"held/official-asset.txt",b"synthetic-official-asset-reference\n")}
    allowlist=["HOME","PATH"]
    config={"artifact":write_artifact(base,"held/config.json",b'{"synthetic":true}\n'),"environment_allowlist":allowlist,"environment_allowlist_sha256":sha256_json(allowlist)}
    argv=[canonical_path,"--model",MODEL,"--effort",EFFORT,"--print"]
    command={"artifact":write_artifact(base,"held/argv.json",canonical_bytes(argv)),"argv":argv,"shell":False,"model_occurrences":1,"effort_occurrences":1,"environment_allowlist_sha256":config["environment_allowlist_sha256"]}
    catalog={"artifact":write_artifact(base,"held/catalog.txt",(MODEL+"\n").encode("ascii")),"parser":write_json_artifact(base,"held/catalog-parser.json",{"version":1,"kind":"R6_HELD_CATALOG_PARSER","line_mode":"exact_unique","model":MODEL}),"model":MODEL,"model_occurrence_count":1,"membership_verified":True,"check_count":1,"entitlement_verified":True}
    process={"process_id":42001,"process_group_id":42001,"new_process_group":True,"shell":False,"binary_descriptor_identity_sha256":binary["descriptor_identity_sha256"],"stdout":write_artifact(base,"held/stdout.raw",b"synthetic stdout\n"),"stderr":write_artifact(base,"held/stderr.raw",b""),"terminal":write_json_artifact(base,"held/terminal.json",{"version":1,"kind":"R6_HELD_TERMINAL","status":"COMPLETE","process_id":42001,"attempt_id":engine_ids["attempt_id"]}),"cleanup_receipt":write_json_artifact(base,"held/process-cleanup.json",{"version":1,"kind":"R6_PROCESS_CLEANUP","complete":True,"process_id":42001,"process_group_id":42001})}
    prompt_artifact=write_artifact(base,"held/prompt.txt",b"synthetic held native prompt\n")
    prompt={"artifact":prompt_artifact,"payload_sha256":PAYLOAD_SHA256,"source_cutoff_sha256":FROZEN_REFS["source_cutoff"]["sha256"],"operation_id":engine_ids["operation_id"],"job_id":engine_ids["job_id"],"slot_id":engine_ids["slot_id"],"attempt_id":engine_ids["attempt_id"],"provider_process_id":process["process_id"]}
    engine={"canonical_engine":copy.deepcopy(FROZEN_REFS["canonical_engine"]),"readback":copy.deepcopy(engine_ids),"job_count":1,"slot_count":1,"attempt_count":1,"operation_count":1,"operation_equal":True,"native_prompt_equal":True,"prompt_sha256":prompt_artifact["sha256"]}
    request_artifact=write_json_artifact(base,"held/request.json",{"version":1,"kind":"R6_HELD_REQUEST","model":MODEL,"request_fingerprint_sha256":request_fingerprint,"operation_id":engine_ids["operation_id"],"provider_process_id":process["process_id"]})
    request={"artifact":request_artifact,"request_fingerprint_sha256":request_fingerprint,"operation_binding_sha256":sha256_bytes((engine_ids["operation_id"]+request_fingerprint).encode()),"operation_id":engine_ids["operation_id"],"provider_process_id":process["process_id"]}
    observer={"observer_id":"observer/fresh-0001","source_fingerprint_sha256":"1"*64,"config_fingerprint_sha256":"2"*64,"listener_fingerprint_sha256":"3"*64,"request":copy.deepcopy(request_artifact),"request_fingerprint_sha256":request_fingerprint,"model":MODEL,"native_prompt_sha256":prompt_artifact["sha256"],"engine_ids":copy.deepcopy(engine_ids),"attempt_id":engine_ids["attempt_id"],"process_id":process["process_id"],"admission_count":1,"observed_upstream_count":1,"grant_seal_sha256":"0"*64}
    custody={"root":".job-runtime/live-provider-evidence/r6-one-off/claude_cli/execution-fresh-0001/owner-private/","owner_uid":501,"mode":0o700,"nofollow_path_walk":True,"separate_root":True,"owner_private":True,"workspace_local":True}
    publication_facts={"atomic":True,"no_overwrite":True,"owner_private_complete":True,"sanitized_complete":True,"files_fsynced":True,"directories_fsynced":True,"closed_schema_validated":True,"hashes_validated":True,"modes_validated":True,"recursive_secret_scan_clean":True,"partial_final_absent":True}
    publication=dict(publication_facts); publication["receipt"]=write_json_artifact(base,"held/publication-receipt.json",dict({"version":1,"kind":"R6_PUBLICATION_RECEIPT"},**publication_facts))
    cleanup_facts={"process_group_terminated":True,"process_group_reaped":True,"observer_stopped":True,"endpoint_removed":True,"descriptors_closed":True,"only_enumerated_temps_removed":True,"residual_children":0,"unlisted_effects":False,"unknown_evidence_preserved":True}
    cleanup=dict(cleanup_facts); cleanup["receipt"]=write_json_artifact(base,"held/cleanup-receipt.json",dict({"version":1,"kind":"R6_CLEANUP_RECEIPT"},**cleanup_facts))
    bindings={"binary":binary,"command":command,"config":config,"catalog":catalog,"prompt":prompt,"engine":engine,"process":process,"observer":observer,"custody":custody,"request":request}
    digest=held_binding_digest(bindings,publication,cleanup)
    common={"version":1,"kind":"R6_PROVIDER_FINAL_GRANT","authority_owner":"external_user_authority","self_minted":False,"authorization_sha256":FROZEN_REFS["authorization"]["sha256"],"authorization_review_sha256":FROZEN_REFS["authorization_review"]["sha256"],"design_sha256":FROZEN_REFS["design"]["sha256"],"design_review_sha256":FROZEN_REFS["design_review"]["sha256"],"stage_a_source_closure_sha256":closure["sha256"],"execution_id":execution_id,"request_id":request_id,"engine_ids":copy.deepcopy(engine_ids),"not_before":stamp(start),"deadline":stamp(end),"claude_subcap_usd":0.01,"combined_cap_usd":0.02,"remaining_combined_budget_usd":0.02,"request_fingerprint_sha256":request_fingerprint,"held_binding_digest_sha256":digest}
    grant_signers={SURFACE:"signer/claude-external-0001","other_cli":"signer/other-external-0001"}; review_signers={SURFACE:"reviewer/claude-external-0001","other_cli":"reviewer/other-external-0001"}
    grants={}; reviews={}
    for provider,stem in ((SURFACE,"claude"),("other_cli","other")):
        grants[provider]=write_json_artifact(base,f"external-authority/{stem}-final-grant.json",dict(common,provider=provider,signer_id=grant_signers[provider]))
    observer["grant_seal_sha256"]=grants[SURFACE]["sha256"]
    for provider,stem in ((SURFACE,"claude"),("other_cli","other")):
        reviews[provider]=write_json_artifact(base,f"external-authority/{stem}-review.json",{"version":1,"kind":"R6_PROVIDER_FINAL_GRANT_INDEPENDENT_REVIEW","provider":provider,"authority_owner":"external_independent_reviewer","signer_id":review_signers[provider],"self_review":False,"decision":"CLEAN","grant_sha256":grants[provider]["sha256"],"authorization_sha256":FROZEN_REFS["authorization"]["sha256"],"design_sha256":FROZEN_REFS["design"]["sha256"]})
    entries=[]
    for provider in (SURFACE,"other_cli"):
        entries.append(TrustedExternalGrant(provider,TrustedArtifactRef.from_mapping(grants[provider]),TrustedArtifactRef.from_mapping(reviews[provider]),"external_user_authority",grant_signers[provider],"external_independent_reviewer",review_signers[provider],digest))
    registry=TrustedExternalGrantRegistry(entries)
    historical=frozenset(("execution/historical-0000","request/historical-0000","job/historical-0000","slot/historical-0000","attempt/historical-0000","operation/historical-0000"))
    ledger_ref=write_json_artifact(base,"external-ledger/historical-identities.json",{"version":1,"kind":"R6_HISTORICAL_IDENTITY_LEDGER","identities":sorted(historical)})
    ledger=HistoricalIdentityLedger(TrustedArtifactRef.from_mapping(ledger_ref),historical)
    opaque="opaque-ref://claude/current"
    seal={"version":1,"kind":"EXTERNALLY_SEALED_R6_CLAUDE_FINAL_GRANT","authority_owner":"external_dual_provider_authority","self_minted":False,"independent_review_clean":True,"frozen_bindings":copy.deepcopy(FROZEN_REFS),"claude_final_grant":grants[SURFACE],"claude_final_grant_review":reviews[SURFACE],"other_provider_final_grant":grants["other_cli"],"other_provider_final_grant_review":reviews["other_cli"],"stage_a_source_closure":closure,"surface":SURFACE,"model":MODEL,"effort":EFFORT,"expected_profile_fingerprint_sha256":"a"*64,"observed_profile_fingerprint_sha256":"a"*64,"credential_reference":opaque,"credential_reference_sha256":sha256_bytes(opaque.encode()),"model_entitled":True,"membership_verified":True,"claude_subcap_usd":0.01,"combined_cap_usd":0.02,"remaining_combined_budget_usd":0.02,"not_before":stamp(start),"deadline":stamp(end),"execution_id":execution_id,"request_id":request_id,"engine_ids":engine_ids,"held_bindings":bindings,"publication":publication,"cleanup":cleanup,"unknown_fence":copy.deepcopy(UNKNOWN_FENCE),"limits":copy.deepcopy(LIMITS),"countable_observation":False,"identities_fresh":True}
    return seal,current,registry,ledger
