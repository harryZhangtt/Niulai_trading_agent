"""EIY v5 checker: canonical policy, genuine chain derivation and opaque issuance.

This additive checker reopens the existing immutable acquisition-chain inputs via
its established checker, but reissues only v5 facts/context after independently
binding the one canonical v5 policy. It does not publish, dispatch, or perform any
provider operation. Opaque Python tokens are same-process nominal typing only.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import sqlite3
from typing import Any, Callable, Mapping, Union

from investment.research.acquisition_eiy_checker import (
    EiyCheckerError as LegacyCheckerError,
    check_eiy_case_v3,
    check_eiy_evaluation_v4,
)
from investment.research.acquisition_trace import derive_acquisition_chain_authority
from shared.research_sources.artifacts import SourceError
from shared.research_sources.information_yield_v5_contracts import (
    ArtifactRefV5, CheckedEiyEvaluationManifestV5, CheckedEiyV5Request,
    EvaluationContextV5, EvaluationCustodyV5, InformationYieldV5ContractError,
    digest_v5,
)
from tuning.evals.information_fetch.information_yield.policy_v5 import (
    CANONICAL_METRIC_POLICY_V5_SHA256, GATE_SPECS_V5, PolicyV5Error,
    canonical_policy_ref_v5, load_canonical_metric_policy_v5,
    require_canonical_policy_ref_v5,
)

FACT_VERSION = "information-yield-checked-fact-5"
NOW_FACT_VERSION = "information-yield-now-diagnostic-fact-5"
_CONTEXT_TOKEN = object()
_FACT_TOKEN = object()
_V4_POLICY_SOURCE_SHA256 = "72f93cfac1c8e47084fd3c86b6d5cdb4ba7e4e8b11df90f20895fa1166b1ce9f"

class EiyCheckerV5Error(ValueError):
    pass

def _fail(code: str) -> None:
    raise EiyCheckerV5Error(code)

def _translate(error: Exception) -> None:
    if isinstance(error, PolicyV5Error):
        _fail("ACQ_EIY_POLICY_NOT_CANONICAL")
    if isinstance(error, (OSError, sqlite3.Error, SourceError)):
        _fail("ACQ_EIY_V5_IO")
    if isinstance(error, (InformationYieldV5ContractError, LegacyCheckerError, EiyCheckerV5Error)):
        _fail(str(error))
    _fail("ACQ_EIY_V5_BOUNDARY_FAILURE")

def _v4_policy() -> dict[str, Any]:
    value = load_canonical_metric_policy_v5()
    value.pop("population_contract")
    value["schema_version"] = "information-yield-metric-policy-4"
    value["source_contract_sha256"] = _V4_POLICY_SOURCE_SHA256
    return value

def _ref_key(ref: Mapping[str, Any]) -> tuple[str, str]:
    return str(ref.get("path")), str(ref.get("sha256"))

def _canonical_read_bridge(read_ref: Callable[[Mapping[str, str]], Mapping[str, Any]],
                           virtual: Mapping[tuple[str, str], Mapping[str, Any]]):
    canonical = canonical_policy_ref_v5()
    def read(bound_ref: Mapping[str, str]) -> Mapping[str, Any]:
        key = _ref_key(bound_ref)
        if key == _ref_key(canonical):
            require_canonical_policy_ref_v5(bound_ref)
            return _v4_policy()
        if key in virtual:
            return deepcopy(virtual[key])
        return read_ref(bound_ref)
    return read

def _bind_hard_failures(fact: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    allowed = set(policy["hard_failure_codes"])
    failures = fact.get("hard_failures")
    if not isinstance(failures, list):
        _fail("ACQ_EIY_V5_HARD_FAILURE_BINDING")
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for failure in failures:
        if (not isinstance(failure, Mapping) or set(failure) != {"code", "chain_ids"}
                or failure.get("code") not in allowed
                or not isinstance(failure.get("chain_ids"), list)
                or not failure["chain_ids"]
                or not all(isinstance(x, str) and x for x in failure["chain_ids"])):
            _fail("ACQ_EIY_V5_HARD_FAILURE_BINDING")
        identity=(failure["code"],tuple(failure["chain_ids"]))
        if identity in seen:
            _fail("ACQ_EIY_V5_HARD_FAILURE_BINDING")
        seen.add(identity)

def _derive_candidate_hard_failures(raw_request: Mapping[str, Any], fact: Mapping[str, Any], *, read_ref) -> list[dict[str, Any]]:
    if (fact.get("evidence_level"), fact.get("split")) != ("development", "development"):
        return []
    failures=[]
    code_by_check={"literal_support":"FABRICATED_SUPPORT","canonical_lineage":"MISSING_TRACE","question_relevance":"SOURCE_MISMATCH"}
    for arm in ("B0", "F"):
        manifest=read_ref(raw_request["arms"][arm]["manifest_ref"]);config=manifest["config"]
        authority=derive_acquisition_chain_authority(driver_ref=manifest["driver_ref"],dispatch_refs=manifest["dispatch_refs"],review_refs=manifest["review_refs"],proposal_refs=manifest["proposal_refs"],host_invocation_refs=manifest["host_invocation_refs"],host_session_id=config["host_session_id"],arm=arm)
        reviews={row.get("review_id"):row for row in authority["reviews"]}
        for chain in authority["chains"]:
            if chain.get("disposition")!="reject":continue
            review=reviews.get(chain.get("review_id"),{});checks=review.get("checks",{})
            for check,code in code_by_check.items():
                if checks.get(check) is False:failures.append({"code":code,"chain_ids":[chain["chain_id"]]})
    return sorted(failures,key=lambda x:(x["code"],x["chain_ids"]))

class FreshEiyFactV5:
    __slots__=("_value","_token")
    def __init__(self,value:Mapping[str,Any],token:object):
        if token is not _FACT_TOKEN:
            _fail("ACQ_EIY_V5_GATE_AUTHORITY")
        self._value=deepcopy(dict(value));self._token=token
    def to_audit_mapping(self)->dict[str,Any]:
        return deepcopy(self._value)

class FreshEiyEvaluationV5:
    __slots__=("_context","_facts","_policy","_evaluation_ref","_custody_ref","_input_paths","_token")
    def __init__(self,context,facts,policy,evaluation_ref,custody_ref,input_paths,token):
        if token is not _CONTEXT_TOKEN:
            _fail("ACQ_EIY_V5_GATE_AUTHORITY")
        self._context=deepcopy(context);self._facts=tuple(facts);self._policy=deepcopy(policy)
        self._evaluation_ref=deepcopy(evaluation_ref);self._custody_ref=deepcopy(custody_ref)
        self._input_paths=frozenset(input_paths);self._token=token
    def to_audit_mapping(self)->dict[str,Any]:
        return {"context":deepcopy(self._context),"facts":[f.to_audit_mapping() for f in self._facts],
                "policy":deepcopy(self._policy),"evaluation_ref":deepcopy(self._evaluation_ref),
                "custody_ref":deepcopy(self._custody_ref)}
    @property
    def input_paths(self)->set[str]:
        return set(self._input_paths)

def private_unwrap_only(value: Any) -> dict[str, Any]:
    if not isinstance(value, FreshEiyEvaluationV5) or value._token is not _CONTEXT_TOKEN:
        _fail("EIY_V5_EVALUATION_CONTEXT_REQUIRED")
    return value.to_audit_mapping()

def _load_evaluation_ref(evaluation_ref: Mapping[str,str], *, read_ref):
    outer=read_ref(evaluation_ref)
    if isinstance(outer,Mapping) and outer.get("schema_version")=="information-yield-evaluation-manifest-5":
        manifest=CheckedEiyEvaluationManifestV5.from_mapping(outer)
        custody_ref=manifest.evaluation_custody_ref.to_mapping()
        custody=EvaluationCustodyV5.from_mapping(read_ref(custody_ref))
        return dict(evaluation_ref),custody_ref,custody
    custody=EvaluationCustodyV5.from_mapping(outer)
    return dict(evaluation_ref),dict(evaluation_ref),custody

def _load_wrappers(custody: EvaluationCustodyV5, *, read_ref):
    wrappers=[];underlying=[]
    canonical=require_canonical_policy_ref_v5(custody.canonical_policy_ref.to_mapping())
    for ref in custody.request_refs:
        wrapper=CheckedEiyV5Request.from_mapping(read_ref(ref.to_mapping()))
        if wrapper.evaluation_id!=custody.evaluation_id or wrapper.mode!=custody.mode:
            _fail("ACQ_EIY_V5_FACT_SET_MISMATCH")
        require_canonical_policy_ref_v5(wrapper.canonical_policy_ref.to_mapping())
        raw=read_ref(wrapper.case_request_ref.to_mapping())
        if not isinstance(raw,Mapping) or raw.get("metric_policy_ref")!=canonical:
            _fail("ACQ_EIY_POLICY_NOT_CANONICAL")
        wrappers.append((ref.to_mapping(),wrapper,raw));underlying.append(wrapper.case_request_ref.to_mapping())
    return wrappers,underlying

def check_eiy_case_v5(request: Union[Mapping[str,Any], CheckedEiyV5Request], *,
                      read_ref: Callable[[Mapping[str,str]],Mapping[str,Any]], workspace_root: Path) -> FreshEiyFactV5:
    try:
        wrapper=request if isinstance(request,CheckedEiyV5Request) else CheckedEiyV5Request.from_mapping(request)
        canonical=require_canonical_policy_ref_v5(wrapper.canonical_policy_ref.to_mapping())
        raw=read_ref(wrapper.case_request_ref.to_mapping())
        if raw.get("metric_policy_ref")!=canonical:
            _fail("ACQ_EIY_POLICY_NOT_CANONICAL")
        bridge=_canonical_read_bridge(read_ref,{})
        legacy=check_eiy_case_v3(raw,read_ref=bridge,workspace_root=workspace_root).to_audit_mapping()
        policy=load_canonical_metric_policy_v5();legacy["hard_failures"]=_derive_candidate_hard_failures(raw,legacy,read_ref=read_ref);_bind_hard_failures(legacy,policy)
        value=deepcopy(legacy);value["schema_version"]=NOW_FACT_VERSION if value.get("subject")=="NOW" else FACT_VERSION
        value["request_sha256"]=wrapper.request_sha256
        value["fact_sha256"]=digest_v5({k:v for k,v in value.items() if k!="fact_sha256"})
        return FreshEiyFactV5(value,_FACT_TOKEN)
    except (InformationYieldV5ContractError,PolicyV5Error,LegacyCheckerError,EiyCheckerV5Error,OSError,sqlite3.Error,SourceError) as error:
        _translate(error)

def check_eiy_evaluation_v5(evaluation_ref: Mapping[str,str], *,
                            read_ref: Callable[[Mapping[str,str]],Mapping[str,Any]], workspace_root: Path) -> FreshEiyEvaluationV5:
    try:
        manifest_ref,custody_ref,custody=_load_evaluation_ref(evaluation_ref,read_ref=read_ref)
        canonical=require_canonical_policy_ref_v5(custody.canonical_policy_ref.to_mapping())
        wrappers,underlying=_load_wrappers(custody,read_ref=read_ref)
        common={name:getattr(custody,name).to_mapping() for name in
                ("case_roster_ref","allocation_ref","baseline_ref","reference_set_ref","required_fields_ref","freshness_targets_ref","financial_element_roster_ref","source_closure_ref")}
        v4_unsigned={"schema_version":"information-yield-evaluation-custody-4","evaluation_id":custody.evaluation_id,
                     "mode":custody.mode,"metric_policy_ref":canonical,**common,"request_refs":underlying}
        v4_custody={**v4_unsigned,"custody_sha256":digest_v5(v4_unsigned)}
        virtual_ref={"path":"__eiy_v5_virtual_custody__","sha256":digest_v5(v4_custody)}
        bridge=_canonical_read_bridge(read_ref,{_ref_key(virtual_ref):v4_custody})
        legacy=check_eiy_evaluation_v4(virtual_ref,read_ref=bridge,workspace_root=workspace_root).to_audit_mapping()
        policy=load_canonical_metric_policy_v5()
        wrapper_by_case={}
        for wrapper_ref,wrapper,raw in wrappers:
            case=read_ref(raw["case_contract_ref"]);wrapper_by_case[case["case_id"]]=(wrapper_ref,wrapper,raw)
        facts=[];fact_by_case={}
        for old in legacy["facts"]:
            _bind_hard_failures(old,policy)
            wrapper_ref,wrapper,raw=wrapper_by_case[old["case_id"]]
            old["hard_failures"]=_derive_candidate_hard_failures(raw,old,read_ref=read_ref);_bind_hard_failures(old,policy)
            value=deepcopy(old);value["schema_version"]=NOW_FACT_VERSION if value.get("subject")=="NOW" else FACT_VERSION
            value["request_sha256"]=wrapper.request_sha256
            value["fact_sha256"]=digest_v5({k:v for k,v in value.items() if k!="fact_sha256"})
            fact=FreshEiyFactV5(value,_FACT_TOKEN);facts.append(fact);fact_by_case[value["case_id"]]=(wrapper_ref,wrapper,value)
        planned=[]
        for old in legacy["context"]["planned_cases"]:
            wrapper_ref,wrapper,fact=fact_by_case[old["case_id"]]
            row={key:deepcopy(old[key]) for key in ("case_id","issuer_id","subject","window_id","cutoff","evidence_level","split","arm_order")}
            row.update({"request_ref":wrapper_ref,"request_sha256":wrapper.request_sha256,"fact_sha256":fact["fact_sha256"]});planned.append(row)
        C=[r["case_id"] for r in planned if (r["evidence_level"],r["split"])==("confirmation","untouched")]
        D=[r["case_id"] for r in planned if (r["evidence_level"],r["split"])==("development","development")]
        N=[r["case_id"] for r in planned if (r["evidence_level"],r["split"])==("diagnostic","diagnostic")]
        if custody.mode=="evaluation" and N or custody.mode=="now_diagnostic" and (C or D or not N):
            _fail("ACQ_EIY_V5_NOW_BOUNDARY")
        E=C+D
        context_core={"schema_version":"information-yield-evaluation-context-5","evaluation_id":custody.evaluation_id,
                      "mode":custody.mode,"planned_cases":planned,"split_counts":{"confirmation_untouched":len(C),"development_development":len(D),"diagnostic_diagnostic":len(N)},
                      "populations":{"C":C,"D":D,"E":E,"N":N},"common_hashes":legacy["context"]["common_hashes"],
                      "policy":policy,"policy_sha256":CANONICAL_METRIC_POLICY_V5_SHA256,
                      "gate_authority_sha256":digest_v5(list(GATE_SPECS_V5)),
                      "source_closure_sha256":legacy["context"]["source_closure_sha256"]}
        context_sha=digest_v5(context_core)
        bindings=[{"case_id":r["case_id"],"request_sha256":r["request_sha256"],"fact_sha256":r["fact_sha256"],"context_sha256":context_sha} for r in planned]
        context={**context_core,"fact_bindings":bindings,"fact_set_sha256":digest_v5(bindings),"context_sha256":context_sha}
        EvaluationContextV5.from_mapping(context)
        paths={custody_ref["path"],manifest_ref["path"],canonical["path"]}
        paths.update(r.path for r in custody.request_refs);paths.update(r.path for r in (custody.case_roster_ref,custody.allocation_ref,custody.baseline_ref,custody.reference_set_ref,custody.required_fields_ref,custody.freshness_targets_ref,custody.financial_element_roster_ref,custody.source_closure_ref))
        return FreshEiyEvaluationV5(context,facts,policy,manifest_ref,custody_ref,paths,_CONTEXT_TOKEN)
    except (InformationYieldV5ContractError,PolicyV5Error,LegacyCheckerError,EiyCheckerV5Error,OSError,sqlite3.Error,SourceError) as error:
        _translate(error)

def audit_eiy_evaluation_v5(evaluation_ref: Mapping[str,str], *, read_ref, workspace_root:Path,
                            expected_context_sha256:str, expected_fact_set_sha256:str)->dict[str,str]:
    fresh=check_eiy_evaluation_v5(evaluation_ref,read_ref=read_ref,workspace_root=workspace_root)
    context=private_unwrap_only(fresh)["context"]
    if context["context_sha256"]!=expected_context_sha256 or context["fact_set_sha256"]!=expected_fact_set_sha256:
        _fail("ACQ_EIY_V5_AUDIT_MISMATCH")
    return {"status":"pass","context_sha256":expected_context_sha256,"fact_set_sha256":expected_fact_set_sha256,
            "scope":"provider_free_rerun_not_remote_attestation"}
