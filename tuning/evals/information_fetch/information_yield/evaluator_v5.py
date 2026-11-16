"""Total EIY v5 reducer with exact C/D/E/N bindings and precedence."""
from __future__ import annotations
from copy import deepcopy
from typing import Any, Mapping

from investment.research.acquisition_eiy_checker_v5 import (
    EiyCheckerV5Error, private_unwrap_only,
)
from shared.research_sources.information_yield_v5_contracts import (
    EvaluationContextV5, InformationYieldV5ContractError, canonical_v5, digest_v5,
)
from tuning.evals.information_fetch.information_yield.evaluator import compute_policy_gates_v4
from tuning.evals.information_fetch.information_yield.policy_v5 import (
    CANONICAL_METRIC_POLICY_V5_SHA256, GATE_SPECS_V5, PolicyV5Error,
    load_canonical_metric_policy_v5, verify_gate_set_v5,
)

RESULT_VERSION="information-yield-result-5"
NOW_RESULT_VERSION="information-yield-now-diagnostic-result-5"
_RESULT_TOKEN=object();_NOW_TOKEN=object()

class InformationYieldV5Error(ValueError):
    pass

def _fail(code:str)->None:
    raise InformationYieldV5Error(code)

def _unwrap_fresh(value:Any)->dict[str,Any]:
    try:return private_unwrap_only(value)
    except EiyCheckerV5Error:raise InformationYieldV5Error("EIY_V5_EVALUATION_CONTEXT_REQUIRED") from None

def _v4_arithmetic_policy(policy:Mapping[str,Any])->dict[str,Any]:
    value=deepcopy(dict(policy));value.pop("population_contract",None)
    value["schema_version"]="information-yield-metric-policy-4"
    value["source_contract_sha256"]="72f93cfac1c8e47084fd3c86b6d5cdb4ba7e4e8b11df90f20895fa1166b1ce9f"
    return value

def _validate(data:Mapping[str,Any])->tuple[dict[str,Any],list[dict[str,Any]],dict[str,Any]]:
    try:
        context=deepcopy(data["context"]);facts=deepcopy(data["facts"]);policy=deepcopy(data["policy"])
        EvaluationContextV5.from_mapping(context)
        canonical=load_canonical_metric_policy_v5()
    except (KeyError,InformationYieldV5ContractError,PolicyV5Error) as error:
        _fail(str(error))
    if policy!=canonical or context["policy"]!=canonical or context["policy_sha256"]!=CANONICAL_METRIC_POLICY_V5_SHA256:
        _fail("ACQ_EIY_POLICY_NOT_CANONICAL")
    if not isinstance(facts,list) or len(facts)!=len(context["planned_cases"]):
        _fail("ACQ_EIY_V5_FACT_SET_MISMATCH")
    planned=context["planned_cases"];bindings=context["fact_bindings"]
    if len(planned)!=len(facts) or len(bindings)!=len(facts):_fail("ACQ_EIY_V5_FACT_SET_MISMATCH")
    by_case={f.get("case_id"):f for f in facts if isinstance(f,Mapping)}
    if len(by_case)!=len(facts) or [r.get("case_id") for r in planned]!=[f.get("case_id") for f in facts] or [b.get("case_id") for b in bindings]!=[f.get("case_id") for f in facts]:_fail("ACQ_EIY_V5_FACT_SET_MISMATCH")
    for row,binding,fact in zip(planned,bindings,facts):
        if (not fact or digest_v5({k:v for k,v in fact.items() if k!="fact_sha256"})!=fact.get("fact_sha256")
                or row.get("fact_sha256")!=fact.get("fact_sha256") or row.get("request_sha256")!=fact.get("request_sha256")
                or binding!={"case_id":row["case_id"],"request_sha256":row["request_sha256"],"fact_sha256":row["fact_sha256"],"context_sha256":context["context_sha256"]}):
            _fail("ACQ_EIY_V5_FACT_SET_MISMATCH")
    C=[f["case_id"] for f in facts if (f.get("evidence_level"),f.get("split"))==("confirmation","untouched")]
    D=[f["case_id"] for f in facts if (f.get("evidence_level"),f.get("split"))==("development","development")]
    N=[f["case_id"] for f in facts if (f.get("evidence_level"),f.get("split"))==("diagnostic","diagnostic")]
    expected={"C":C,"D":D,"E":C+D,"N":N}
    if context.get("populations")!=expected:_fail("EIY_V5_GATE_POPULATION")
    if context["mode"]=="evaluation" and (N or len(C)+len(D)!=len(facts)):_fail("ACQ_EIY_V5_NOW_BOUNDARY")
    if context["mode"]=="now_diagnostic" and (C or D or not N or len(N)!=len(facts)):_fail("ACQ_EIY_V5_NOW_BOUNDARY")
    return context,facts,policy

def _legacy_gate_set(policy:Mapping[str,Any],facts:list[dict[str,Any]],population:str)->dict[str,dict[str,Any]]:
    rows=deepcopy(facts)
    if population=="E":
        for row in rows:row["evidence_level"]="confirmation";row["split"]="untouched"
    computed=compute_policy_gates_v4(policy=_v4_arithmetic_policy(policy),facts=rows,context={})
    return {gate["name"]:gate for gate in computed["gates"]}

def _bounded_gate_value(value:Any)->Any:
    if isinstance(value,(dict,list)):return canonical_v5(value).decode("utf-8")
    if value is None or type(value) in (str,int,float,bool):return value
    _fail("EIY_V5_RESULT_INVALID")
def _record(spec:Mapping[str,Any],legacy:Mapping[str,Any],ids:list[str])->dict[str,Any]:
    cases=[]
    for value in legacy.get("case_results",[]):
        case_id=value.get("case_id","") if isinstance(value,Mapping) else value if isinstance(value,str) else ""
        cases.append({"case_id":case_id,"detail_json":canonical_v5(value).decode("utf-8")})
    return {"ordinal":spec["ordinal"],"name":spec["name"],"population":spec["population"],"decisive":spec["decisive"],"population_case_ids":list(ids),"status":legacy["status"],"observed":_bounded_gate_value(legacy.get("observed")),"threshold":_bounded_gate_value(legacy.get("threshold")),"numerator":_bounded_gate_value(legacy.get("numerator")),"denominator":_bounded_gate_value(legacy.get("denominator")),"case_results":cases,"reason_codes":deepcopy(legacy.get("reason_codes",[]))}

def compute_policy_gates_v5(*,policy:Mapping[str,Any],facts:list[Mapping[str,Any]],context:Mapping[str,Any])->dict[str,Any]:
    canonical=load_canonical_metric_policy_v5()
    if dict(policy)!=canonical:_fail("ACQ_EIY_POLICY_NOT_CANONICAL")
    populations=context.get("populations")
    if not isinstance(populations,Mapping) or set(populations)!={"C","D","E","N"}:_fail("EIY_V5_GATE_POPULATION")
    by_case={row.get("case_id"):deepcopy(dict(row)) for row in facts}
    if any(case_id not in by_case for case_id in populations["E"]):_fail("EIY_V5_GATE_POPULATION")
    C=[by_case[x] for x in populations["C"]];E=[by_case[x] for x in populations["E"]]
    c_gates=_legacy_gate_set(policy,C,"C");e_gates=_legacy_gate_set(policy,E,"E")
    gates=[]
    for spec in GATE_SPECS_V5[:-1]:
        source=c_gates if spec["population"]=="C" else e_gates
        gates.append(_record(spec,source[spec["name"]],list(populations[spec["population"]])))
    unknown=[g["name"] for g in gates if g["status"]=="unknown"]
    last={"status":"pass" if not unknown else "fail","observed":unknown,"threshold":[],
          "numerator":None,"denominator":None,"case_results":[],
          "reason_codes":[] if not unknown else ["EIY_UNKNOWN_SEMANTICS"]}
    gates.append(_record(GATE_SPECS_V5[-1],last,list(populations["E"])))
    verify_gate_set_v5(gates,population_case_ids=populations)
    return {"gates":gates,"populations":deepcopy(dict(populations))}

def _public_case(fact:Mapping[str,Any])->dict[str,Any]:
    # Publisher-facing result intentionally carries only bounded identities and deltas.
    def metric(arm:Mapping[str,Any])->dict[str,Any]:
        required=arm.get("required_fields",[]);precision=arm.get("precision",{});trace=arm.get("trace_accounting",{})
        supported=precision.get("supported_numerator");judged=precision.get("judged_denominator")
        return {"richness":len({u.get("canonical_key_sha256") for u in arm.get("canonical_units",[])}),
                "depth":sum({"unknown":0,"partial":1,"resolved":2}.get(x.get("post_state"),0)-{"unknown":0,"partial":1,"resolved":2}.get(x.get("baseline_state"),0) for x in required),
                "precision":supported/judged if precision.get("status")=="known" and isinstance(judged,int) and judged>0 else None,
                "wall_seconds":arm.get("execution",{}).get("deadlines",{}).get("observed_wall_seconds"),
                "trace":{"complete":trace.get("complete_chains"),"credited":trace.get("credited_units"),"unjudged":trace.get("unjudged_units")}}
    B=metric(fact["arms"]["B0"]);F=metric(fact["arms"]["F"])
    return {"case_id":fact["case_id"],"issuer_id":fact["issuer_id"],"window_id":fact["window_id"],
            "evidence_level":fact["evidence_level"],"split":fact["split"],"arm_order":deepcopy(fact["arm_order"]),
            "request_sha256":fact["request_sha256"],"fact_sha256":fact["fact_sha256"],
            "delta_r":F["richness"]-B["richness"],"delta_d":F["depth"]-B["depth"],"arms":{"B0":B,"F":F},
            "hard_failure_codes":[x["code"] for x in fact["hard_failures"]]}

class IssuedEiyResult:
    __slots__=("_result","_envelope","_token")
    def __init__(self,result,envelope,token):
        if token is not _RESULT_TOKEN:_fail("EIY_V5_RESULT_INVALID")
        self._result=deepcopy(result);self._envelope=deepcopy(envelope);self._token=token
    def to_audit_mapping(self):return deepcopy(self._result)

class IssuedNowDiagnosticV5:
    __slots__=("_result","_envelope","_token")
    def __init__(self,result,envelope,token):
        if token is not _NOW_TOKEN:_fail("EIY_V5_RESULT_INVALID")
        self._result=deepcopy(result);self._envelope=deepcopy(envelope);self._token=token
    def to_audit_mapping(self):return deepcopy(self._result)

def private_unwrap_issued_v5(value:Any)->dict[str,Any]:
    if isinstance(value,IssuedEiyResult) and value._token is _RESULT_TOKEN:
        return {"kind":"evaluation","result":deepcopy(value._result),**deepcopy(value._envelope)}
    if isinstance(value,IssuedNowDiagnosticV5) and value._token is _NOW_TOKEN:
        return {"kind":"now_diagnostic","result":deepcopy(value._result),**deepcopy(value._envelope)}
    _fail("EIY_V5_RESULT_INVALID")

def evaluate_fresh_eiy_evaluation_v5(*,fresh_evaluation)->IssuedEiyResult:
    data=_unwrap_fresh(fresh_evaluation);context,facts,policy=_validate(data)
    if context["mode"]!="evaluation":_fail("ACQ_EIY_V5_NOW_BOUNDARY")
    computed=compute_policy_gates_v5(policy=policy,facts=facts,context=context);gates=computed["gates"]
    if any(g["decisive"] and g["status"]=="fail" for g in gates):verdict="reject"
    elif any(g["status"]=="unknown" for g in gates):verdict="inconclusive"
    elif any(g["status"]=="fail" for g in gates):verdict="inconclusive"
    elif len(context["populations"]["C"])==6 and all(g["status"]=="pass" for g in gates):verdict="pass"
    else:verdict="inconclusive"
    # Recompute expected precedence to make accidental later mutation fixed-fail.
    decisive_fail=any(g["decisive"] and g["status"]=="fail" for g in gates)
    unknown=any(g["status"]=="unknown" for g in gates)
    nondecisive_fail=any(not g["decisive"] and g["status"]=="fail" for g in gates)
    expected="reject" if decisive_fail else "inconclusive" if unknown or nondecisive_fail else "pass" if len(context["populations"]["C"])==6 else "inconclusive"
    if verdict!=expected:_fail("EIY_V5_VERDICT_PRECEDENCE")
    public=[_public_case(f) for f in facts]
    result={"schema_version":RESULT_VERSION,"evaluation_id":context["evaluation_id"],"context_sha256":context["context_sha256"],
            "fact_set_sha256":context["fact_set_sha256"],"policy_sha256":context["policy_sha256"],
            "gate_authority_sha256":context["gate_authority_sha256"],"source_closure_sha256":context["source_closure_sha256"],
            "counts":{"planned":len(facts),"C":len(context["populations"]["C"]),"D":len(context["populations"]["D"])},
            "populations":deepcopy(context["populations"]),"policy_gates":gates,
            "confirmation_cases":[r for r in public if r["case_id"] in context["populations"]["C"]],
            "development_cases":[r for r in public if r["case_id"] in context["populations"]["D"]],
            "verdict":verdict,"reason_codes":sorted({code for g in gates if g["status"] in {"fail","unknown"} for code in g["reason_codes"]}),
            "claim_limits":["provider_free_structural_evidence_only","vector_only_no_scalar","not_remote_attestation","not_live_provider_quality","not_financial_alpha","not_population_superiority"]}
    result["result_sha256"]=digest_v5(result)
    envelope={"context":context,"policy":policy,"evaluation_ref":data["evaluation_ref"],"custody_ref":data["custody_ref"]}
    return IssuedEiyResult(result,envelope,_RESULT_TOKEN)

def evaluate_fresh_now_evaluation_v5(*,fresh_evaluation)->IssuedNowDiagnosticV5:
    data=_unwrap_fresh(fresh_evaluation);context,facts,policy=_validate(data)
    if context["mode"]!="now_diagnostic":_fail("ACQ_EIY_V5_NOW_BOUNDARY")
    rows=[{"case_id":f["case_id"],"fact_sha256":f["fact_sha256"],"arms":{a:{"units":len(f["arms"][a]["canonical_units"]),"known_fields":sum(x["post_state"]!="unknown" for x in f["arms"][a]["required_fields"])} for a in ("B0","F")}} for f in facts]
    result={"schema_version":NOW_RESULT_VERSION,"evaluation_id":context["evaluation_id"],"context_sha256":context["context_sha256"],
            "fact_set_sha256":context["fact_set_sha256"],"policy_sha256":context["policy_sha256"],
            "gate_authority_sha256":context["gate_authority_sha256"],"source_closure_sha256":context["source_closure_sha256"],
            "population_N":deepcopy(context["populations"]["N"]),"cases":rows,"diagnostic_status":"observed",
            "claim_limits":["now_only_no_confirmation","no_evaluation_publication","no_promotion","not_financial_alpha"]}
    result["result_sha256"]=digest_v5(result)
    envelope={"context":context,"policy":policy,"evaluation_ref":data["evaluation_ref"],"custody_ref":data["custody_ref"]}
    return IssuedNowDiagnosticV5(result,envelope,_NOW_TOKEN)
