"""Disabled provider-free vertical; canonical Engine first, then injected boundaries."""
from __future__ import annotations
import copy,json
from pathlib import Path
from typing import Optional
from shared.job_runtime.candidates.r6_one_off_evidence_v1 import execute_provider_free,materialize_provider_free_case
from .claude_cli import launch_spec,synthetic_held_manifest
from .cleanup import receipt as cleanup_receipt
from .contracts import ContractError,DriverResult,EFFORT,LIMITS,MODEL,SURFACE,canonical_bytes,no_effects,safe_public,sha256_bytes,validate_engine_readback,validate_evidence,validate_launch_spec
from .custody import payloads
from .ferry import FakeFerryObserver
from .grant import provider_free_template
from .preflight import early,engine_readback
from .process import FakeProcess
from .publication import PublicationError,PublicationTrace,durable_unknown_fence,publish_owner,publish_public
from .terminal import parse as parse_terminal
EARLY={"auth","model","cost","window","custody"}
POST={"truncation":"truncation","cleanup":"cleanup","timeout":"timeout","process":"process_loss","terminal":"terminal","parser":"parser","path_swap":"path_swap","secret":"secret","launch_echo":"launch_echo","fence_file_fsync":"terminal","fence_dir_fsync":"terminal"}
def _empty(status,reason):
    return {"version":1,"status":status,"reason":reason,"countable":False,"surface":SURFACE,"model":MODEL,"effort":EFFORT,"limits":dict(LIMITS),"engine_readback":None,"request_fingerprint":None,"launch_spec_digest":None,"process":None,"ferry":None,"terminal":{"state":"absent","exact":False,"parser_identity":"claude_terminal_v1","output_identity":"owner/stdout.raw"},"cleanup":{"state":"not_started","process_group_reaped":False,"descriptors_closed":False,"residuals":[]},"publication":{"owner_private":False,"sanitized":False,"atomic":False,"owner_final":None,"public_final":None,"collision_preserved":False},"effects":no_effects(),"unknown_fence":{"durable":False,"retry":False,"replay":False,"status_calls":0,"receipt":None}}
def _unknown(evidence,reason):
    evidence["status"]="UNKNOWN";evidence["reason"]=reason;evidence["unknown_fence"]={"durable":True,"retry":False,"replay":False,"status_calls":0,"receipt":"unknown-fence.json"};return evidence
def _verify_process(spec,receipt):
    expected={"launch_spec_digest_echo":spec["digest"],"binary_sha256":spec["binary"]["sha256"],"argv_sha256":spec["argv"]["sha256"],"shell":False,"env_allowlist":spec["env_allowlist"],"config_sha256":spec["config"]["sha256"],"catalog_sha256":spec["catalog"]["sha256"],"model":MODEL,"prompt_sha256":spec["prompt"]["sha256"],"process_group":True,"deadline_seconds":30,"terminate_policy":True,"kill_policy":True,"reap_policy":True}
    for k,v in expected.items():
        if receipt[k]!=v:raise ContractError("PROCESS_LAUNCH_ECHO_DRIFT")
def _public_process(receipt):
    x=copy.deepcopy(receipt)
    if x["nested_error"]["present"]:x["nested_error"]={"present":True,"code":"REDACTED_SENSITIVE_ERROR"}
    return x
def run_provider_free(root:Path,scenario:str="nominal",process:Optional[FakeProcess]=None,ferry:Optional[FakeFerryObserver]=None,publication_trace:Optional[PublicationTrace]=None)->DriverResult:
    root=Path(root);fence=root/"unknown-fence.json";failures={"publication":"public_commit_attempt","owner_publication":"owner_file_fsync","owner_file_fsync":"owner_file_fsync","owner_dir_fsync":"owner_stage_dir_fsync","public_commit":"public_commit_attempt","public_dir_fsync":"public_parent_dir_fsync","fence_file_fsync":"fence_file_fsync","fence_dir_fsync":"fence_dir_fsync"};trace=publication_trace or PublicationTrace(failures.get(scenario));events=[]
    if fence.exists():
        x=json.loads(fence.read_text(encoding="ascii"));validate_evidence(x);return DriverResult(x,x["publication"]["owner_final"],x["publication"]["public_final"])
    provider_free_template();base_manifest=synthetic_held_manifest()
    if scenario in EARLY:
        if scenario=="model":base_manifest["model_membership"]=False
        if scenario=="custody":base_manifest["digest"]="0"*64
        try:early(base_manifest,grant_reviewed=scenario!="auth",account_binding=True,cost_cap=.02 if scenario=="cost" else .01,combined_cap=.02,window_minutes=31 if scenario=="window" else 30)
        except ContractError as exc:
            e=_empty("STOP",str(exc));validate_evidence(e);return DriverResult(e,None,None)
        raise AssertionError("EARLY_DRIFT_NOT_STOPPED")
    early(base_manifest,grant_reviewed=True,account_binding=True,cost_cap=.01,combined_cap=.02,window_minutes=30)
    public_scenario="nominal" if scenario in ("nominal","duplicate","collision","publication","owner_publication","owner_file_fsync","owner_dir_fsync","public_commit","public_dir_fsync") else "post_admission_unknown"
    prepared=materialize_provider_free_case(root/"engine-workspace",public_scenario)
    prompt=next(x for x in prepared.grant["custody"] if x["role"]=="prompt");manifest=synthetic_held_manifest(prompt)
    process=process or FakeProcess(POST.get(scenario,"none"));ferry=ferry or FakeFerryObserver();captured={};pre_stop={}
    def transport(request):
        rb=engine_readback(prepared,request,manifest);captured["readback"]=rb;events.append({"sequence":1,"type":"ENGINE_READBACK_VERIFIED","digest":rb["digest"]})
        if scenario=="binding":
            bad=copy.deepcopy(rb);bad["request_id"]+="-drift"
            try:validate_engine_readback(bad)
            except ContractError as exc:pre_stop["reason"]=str(exc);return {"terminal":"truncated","cleanup":"fault","raw":b'{"type":"binding.stop"}'}
        spec=launch_spec(manifest,rb);captured["spec"]=spec
        if scenario=="launch_spec":
            bad=copy.deepcopy(spec);bad["shell"]=True
            try:validate_launch_spec(bad)
            except ContractError as exc:pre_stop["reason"]=str(exc);return {"terminal":"truncated","cleanup":"fault","raw":b'{"type":"launch.stop"}'}
        admit_readback=copy.deepcopy(rb)
        if scenario=="ferry_mismatch":admit_readback["request_id"]+="-mismatch";admit_readback["digest"]=sha256_bytes(canonical_bytes({k:v for k,v in admit_readback.items() if k!="digest"}))
        try:fp=ferry.admit(root/"ferry",admit_readback,spec,sha256_bytes(canonical_bytes(prepared.grant)),events,rb)
        except ContractError as exc:pre_stop["reason"]=str(exc);return {"terminal":"truncated","cleanup":"fault","raw":b'{"type":"ferry.stop"}'}
        captured["fingerprint"]=fp
        if scenario=="duplicate":
            try:ferry.admit(root/"ferry",rb,spec,sha256_bytes(canonical_bytes(prepared.grant)),events,rb)
            except ContractError as exc:
                if str(exc)!="FERRY_SECOND_ADMISSION_REJECTED":raise
            else:raise AssertionError("SECOND_ADMISSION_ACCEPTED")
        ferry.observe_upstream();raw=process.start(spec,rb);captured["raw_process"]=raw
        try:_verify_process(spec,raw)
        except ContractError as exc:captured["boundary_error"]=str(exc)
        if raw["nested_error"]["present"]:
            try:safe_public(raw)
            except ContractError as exc:captured["boundary_error"]=str(exc)
        terminal=parse_terminal(raw);cleanup=cleanup_receipt(raw);captured["terminal"]=terminal;captured["cleanup"]=cleanup
        good=not captured.get("boundary_error") and terminal["exact"] and cleanup["state"]=="complete"
        return {"terminal":"exact" if good else "truncated","cleanup":"complete" if good else "fault","raw":b'{"type":"fake.completed"}' if good else b'{"type":"fake.partial"'}
    shared=execute_provider_free(prepared,transport)
    rb=captured["readback"]
    if pre_stop:
        e=_empty("STOP",pre_stop["reason"]);e["engine_readback"]=rb;e["launch_spec_digest"]=captured.get("spec",{}).get("digest");validate_evidence(e);return DriverResult(e,None,None)
    spec=captured["spec"];rawp=captured["raw_process"];pubp=_public_process(rawp);terminal=captured["terminal"];cleanup=captured["cleanup"]
    good=shared.evidence["decision"]=="PASS" and not captured.get("boundary_error") and terminal["exact"] and cleanup["state"]=="complete"
    e=_empty("PASS" if good else "UNKNOWN","EXACT_TERMINAL_VERIFIED" if good else captured.get("boundary_error","POST_ADMISSION_UNCERTAIN"));e.update({"engine_readback":rb,"request_fingerprint":captured["fingerprint"],"launch_spec_digest":spec["digest"],"process":pubp,"ferry":ferry.receipt(),"terminal":terminal,"cleanup":cleanup})
    try:
        owner=publish_owner(root/"owner-private",payloads(rawp),trace);e["publication"].update({"owner_private":True,"owner_final":owner})
    except PublicationError:
        e=_unknown(e,"OWNER_PUBLICATION_UNCERTAIN");validate_evidence(e);durable_unknown_fence(root,e,trace);return DriverResult(e,None,None)
    if good:
        intended=copy.deepcopy(e);intended["publication"].update({"sanitized":True,"atomic":True,"public_final":"execution"})
        try:
            public=publish_public(root/"sanitized",intended,trace);e=intended
        except PublicationError as exc:
            e["publication"]["collision_preserved"]=str(exc)=="PUBLICATION_COLLISION";e=_unknown(e,"PUBLICATION_UNCERTAIN")
    else:e=_unknown(e,e["reason"])
    if e["status"]=="UNKNOWN":validate_evidence(e);durable_unknown_fence(root,e,trace)
    else:validate_evidence(e)
    return DriverResult(e,e["publication"]["owner_final"],e["publication"]["public_final"])
