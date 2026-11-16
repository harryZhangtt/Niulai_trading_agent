"""Validate injected immutable Engine joins and emit frozen Fable A/B artifacts."""
from __future__ import annotations
import hashlib, math, re
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence
from shared.job_runtime.engine_schema import prompt_binding_sha256
from shared.job_runtime.provider_contract import ProviderResultV1
from shared.job_runtime.candidates.r6_data_quality_fable_ab_v1.contracts import (
    CELL_ORDER, DQ_CHECKS, FROZEN_INPUTS, MODEL_ID, sha256_json, strict_json_loads,
)
from shared.job_runtime.candidates.r6_data_quality_fable_ab_v1.runner import run_pair

class AdapterError(ValueError): pass
def require(ok: bool, code: str) -> None:
    if not ok: raise AdapterError(code)

SHA=re.compile(r"[0-9a-f]{64}\Z"); ID=re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}\Z")
ROW_KEYS=("attempt_id","slot_id","canonical_json","canonical_sha256","provider","operation_id","phase","submission","terminal_proof","status","failure_kind","recorded_at","prompt_binding_sha256")
EXPECTED_KEYS=("cell_id","job_id","slot_id","attempt_id","prompt_binding_sha256","artifact_ref","sha256","length","version","source_identity_sha256","generation","proof_origin")
DESCRIPTOR_KEYS=("artifact_ref","sha256","length","version","source_identity_sha256","generation","proof_origin")
DESIGN_SHA256="414bdf36dfd20b745cb36ba5cc4904743a4d08d6a23a415d77ae08c0c61c51d7"
INPUTS_SHA256="cd8cdc28b0abff887dce0e2fe7171e72b40393a1792384731bcab4119db0ed19"
JOB_IDS=("fable-adapter-cell-0","fable-adapter-cell-1")
RECEIPT_KEYS=("version","design_sha256","cell_id","configured_model","provider_reported_model","inputs_sha256","terminal_state","terminal_ascii","dq_checks")
STATUS_BINDING={"PASS":"succeeded","FAIL":"failed","STOP":"failed","MALFORMED":"failed","MISSING":"unknown","UNKNOWN":"unknown"}

def default_adapt(*args: Any,**kwargs: Any)->Dict[str,Any]:
    return {"status":"DENIED_NO_INJECTED_ENGINE_PROVIDER_RESULTS","countable":False,"effects":{"provider":0,"network":0,"publication":0,"email":0,"tools":0,"web":0,"subagents":0}}

def _plain(value:Any)->Any:
    if isinstance(value,Mapping):return {k:_plain(v) for k,v in value.items()}
    if isinstance(value,tuple):return [_plain(v) for v in value]
    return value

def _expected(value:Mapping[str,Any],index:int)->Dict[str,Any]:
    require(type(value) is dict and set(value)==set(EXPECTED_KEYS),"EXPECTED_READBACK_SHAPE")
    require(value["cell_id"]==CELL_ORDER[index] and value["job_id"]==JOB_IDS[index],"EXPECTED_CELL_JOB_BINDING")
    for key in ("job_id","slot_id","attempt_id","artifact_ref","generation","proof_origin"):
        require(type(value[key]) is str and ID.fullmatch(value[key]) is not None,"EXPECTED_ID")
    for key in ("prompt_binding_sha256","sha256","source_identity_sha256"):
        require(type(value[key]) is str and SHA.fullmatch(value[key]) is not None,"EXPECTED_SHA")
    require(value["sha256"]==FROZEN_INPUTS["prompt_sha256"],"EXPECTED_FROZEN_PROMPT")
    require(type(value["length"]) is int and type(value["length"]) is not bool and 1<=value["length"]<=65536,"EXPECTED_LENGTH")
    require(type(value["version"]) is int and value["version"]==1 and value["proof_origin"]=="native_v1","EXPECTED_DESCRIPTOR")
    descriptor={k:value[k] for k in DESCRIPTOR_KEYS}
    derived=prompt_binding_sha256(value["job_id"],value["slot_id"],descriptor)
    require(value["prompt_binding_sha256"]==derived,"EXPECTED_PROMPT_BINDING")
    return dict(value)

def _decode(row:Mapping[str,Any],expected:Mapping[str,Any])->Dict[str,Any]:
    require(type(row) is dict and set(row)==set(ROW_KEYS),"ENGINE_ROW_SHAPE")
    for key in ("attempt_id","slot_id","canonical_json","canonical_sha256","provider","operation_id","phase","submission","terminal_proof","status","failure_kind","prompt_binding_sha256"):
        require(type(row[key]) is str,"ENGINE_ROW_TYPE")
    when=row["recorded_at"]
    require(type(when) in (int,float) and type(when) is not bool and (type(when) is int or math.isfinite(when)),"ENGINE_ROW_TIME")
    require(row["provider"]=="claude_host","ENGINE_PROVIDER")
    require(row["attempt_id"]==expected["attempt_id"] and row["slot_id"]==expected["slot_id"] and row["prompt_binding_sha256"]==expected["prompt_binding_sha256"],"ENGINE_EXPECTED_JOIN")
    operation="attempt/"+expected["attempt_id"]+"/prompt/"+expected["prompt_binding_sha256"]
    require(row["operation_id"]==operation,"ENGINE_NATIVE_OPERATION")
    encoded=row["canonical_json"].encode("utf-8")
    require(hashlib.sha256(encoded).hexdigest()==row["canonical_sha256"],"ENGINE_CANONICAL_DIGEST")
    value=strict_json_loads(row["canonical_json"],"ENGINE_CANONICAL_JSON");require(type(value) is dict,"ENGINE_CANONICAL_SHAPE")
    try:result=ProviderResultV1(**value)
    except (TypeError,ValueError):raise AdapterError("ENGINE_PROVIDER_RESULT_INVALID") from None
    require(result.canonical_sha256==row["canonical_sha256"],"ENGINE_RESULT_DIGEST")
    require((result.provider.value,result.operation_id,result.phase.value,result.submission.value,result.terminal_proof.value,result.status.value,result.failure_kind.value)==(row["provider"],row["operation_id"],row["phase"],row["submission"],row["terminal_proof"],row["status"],row["failure_kind"]),"ENGINE_ROW_BINDING")
    receipt=_plain(result.receipt);require(type(receipt) is dict and set(receipt)==set(RECEIPT_KEYS),"SANITIZED_RECEIPT_SHAPE")
    require(receipt["version"]==1 and type(receipt["version"]) is int,"SANITIZED_RECEIPT_VERSION")
    require(receipt["design_sha256"]==DESIGN_SHA256 and receipt["cell_id"]==expected["cell_id"],"SANITIZED_RECEIPT_BINDING")
    require(receipt["configured_model"]==MODEL_ID and receipt["provider_reported_model"]==MODEL_ID,"SANITIZED_MODEL_BINDING")
    require(receipt["inputs_sha256"]==INPUTS_SHA256==sha256_json(FROZEN_INPUTS),"SANITIZED_INPUT_BINDING")
    terminal=receipt["terminal_state"];require(terminal in STATUS_BINDING and result.status.value==STATUS_BINDING[terminal],"SANITIZED_TERMINAL_BINDING")
    try:raw=receipt["terminal_ascii"].encode("ascii")
    except (AttributeError,UnicodeError):raise AdapterError("SANITIZED_TERMINAL_ASCII") from None
    require(len(raw)<=1048576,"SANITIZED_TERMINAL_ASCII")
    checks=receipt["dq_checks"]
    if expected["cell_id"]==CELL_ORDER[0]:require(checks is None,"OFF_DQ_CHECKS_PRESENT")
    else:require(type(checks) is list and len(checks)==len(DQ_CHECKS),"ON_DQ_CHECKS_MISSING")
    return {"cell_id":expected["cell_id"],"terminal_state":terminal,"raw":raw,"dq_checks":checks,"attempt_id":row["attempt_id"]}

def adapt_engine_provider_results(rows:Sequence[Mapping[str,Any]],expected_readback:Sequence[Mapping[str,Any]],bundle_root:Path,*,fault_cell:str="")->Dict[str,Any]:
    require(type(rows) in (list,tuple) and len(rows)==2 and type(expected_readback) in (list,tuple) and len(expected_readback)==2,"ENGINE_RESULT_COUNT")
    expected=[_expected(dict(value),i) for i,value in enumerate(expected_readback)]
    decoded=[_decode(dict(rows[i]),expected[i]) for i in range(2)]
    require(tuple(item["cell_id"] for item in decoded)==CELL_ORDER,"ENGINE_RESULT_CELL_ORDER")
    require(len({item["attempt_id"] for item in decoded})==2 and len({item["slot_id"] for item in expected})==2,"ENGINE_RESULT_ID_DUPLICATE")
    by_cell={item["cell_id"]:item for item in decoded}
    def outcome(plan:Mapping[str,Any])->Mapping[str,Any]:
        item=by_cell[plan["cell_id"]]
        return {"plan_echo":dict(plan),"attempt_id":item["attempt_id"],"terminal_state":item["terminal_state"],"attempt_count":0 if item["terminal_state"]=="STOP" else 1,"raw":item["raw"],"dq_checks":item["dq_checks"]}
    result=run_pair(outcome,Path(bundle_root),fault_cell=fault_cell)
    require(result["countable"] is False and result["publication_attempts"]==0,"ADAPTER_OUTPUT_FENCE")
    return result

__all__=["AdapterError","DESIGN_SHA256","INPUTS_SHA256","JOB_IDS","ROW_KEYS","EXPECTED_KEYS","adapt_engine_provider_results","default_adapt"]
