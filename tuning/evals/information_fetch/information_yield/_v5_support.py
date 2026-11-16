"""Sanitized provider-free fixtures for EIY v5 Lane A tests only."""
from __future__ import annotations
from copy import deepcopy
from investment.research.acquisition_review import record_reviewer_decision
from pathlib import Path
from typing import Callable

from investment.research.acquisition_eiy_checker_v5 import (
    FreshEiyEvaluationV5, FreshEiyFactV5, _CONTEXT_TOKEN, _FACT_TOKEN,
    check_eiy_evaluation_v5,
)
from investment.research.tests.test_acquisition_eiy_v3 import EiyV3Fixture
from shared.research_sources.artifacts import ROOT,read
from shared.research_sources.information_yield_v5_contracts import digest_v5
from tuning.evals.information_fetch.information_yield.policy_v5 import canonical_policy_ref_v5

_COMMON=("case_roster_ref","allocation_ref","baseline_ref","reference_set_ref","required_fields_ref","freshness_targets_ref","financial_element_roster_ref","source_closure_ref")

def _inject_development_failure(fixture):
    manifest=deepcopy(fixture.arms["F"]);old=read(manifest["review_refs"][0]);binding=old["binding"]
    replacement=record_reviewer_decision(fixture.artifacts,assessment_ref=binding["assessment_ref"],unit_ref=binding["unit_ref"],reviewer_id=old["reviewer_id"]+"-v5",assessment_author_id=old["assessment_author_id"],operator_id=old["operator_id"],disposition="reject",checks={"question_relevance":True,"literal_support":False,"canonical_lineage":True},reason="Candidate literal support failed reviewer verification.")
    manifest["review_refs"]=[replacement];manifest["config"]["expected_credited_units"]=0
    fixture.arms["F"]=manifest;fixture.arm_refs["F"]=fixture.put("arm-F-v5-hard-failure.json",manifest)
def build_v5_batch(testcase,*,confirmation:int=6,development:int=1,mode:str="evaluation",development_hard_failure:bool=False,closure_drift:bool=False,issue:bool=True):
    total=confirmation+development;rows=[];seen=0
    for index in range(1,total+1):
        dev=index<=development
        if dev:level,split,order,subject="development","development",["B0","F"],"ACME"
        else:
            level,split,subject="confirmation","untouched","ACME";order=["B0","F"] if seen<3 else ["F","B0"];seen+=1
        rows.append({"case_id":f"case-{index}","issuer_id":f"ISSUER-{index}","subject":subject,"window_id":f"2026Q{index}","cutoff":"2026-01-01T00:00:00Z","evidence_level":level,"split":split,"arm_order":order})
    if mode=="now_diagnostic":
        rows=[{"case_id":"case-1","issuer_id":"ISSUER-1","subject":"NOW","window_id":"2026Q1","cutoff":"2026-01-01T00:00:00Z","evidence_level":"diagnostic","split":"diagnostic","arm_order":["B0","F"]}]
    ids=[r["case_id"] for r in rows];fixtures=[]
    for index,row in enumerate(rows,1):
        fixture=EiyV3Fixture(testcase,case_index=index,issuer=row["issuer_id"],subject=row["subject"],mode=mode,
            all_case_ids=ids,all_case_rows=rows,arm_order=row["arm_order"],evidence_level=row["evidence_level"],split=row["split"],
            disposition_by_arm={"B0":"reject","F":"approve"} if mode=="evaluation" else None,closure_drift=closure_drift)
        fixtures.append(fixture)
    first=fixtures[0]
    if development_hard_failure:
        if mode!="evaluation" or development<1:raise ValueError("EIY_V5_DEVELOPMENT_FAILURE_FIXTURE")
        _inject_development_failure(first)
    canonical=canonical_policy_ref_v5()
    for fixture in fixtures:
        fixture.values["metric_policy_ref"]=canonical
        for name in _COMMON:fixture.values[name]=first.values[name]
        fixture.rebuild_request()
    wrapper_refs=[]
    for fixture in fixtures:
        unsigned={"schema_version":"information-yield-check-request-5","evaluation_id":"eval-v3","mode":mode,
                  "canonical_policy_ref":canonical,"case_request_ref":fixture.request_ref}
        wrapper={**unsigned,"request_sha256":digest_v5(unsigned)}
        wrapper_refs.append(fixture.put(f"request-v5-{fixture.case_id}.json",wrapper))
    custody_unsigned={"schema_version":"information-yield-evaluation-custody-5","evaluation_id":"eval-v3","mode":mode,
                      "canonical_policy_ref":canonical,**{name:first.values[name] for name in _COMMON},"request_refs":wrapper_refs}
    custody={**custody_unsigned,"custody_sha256":digest_v5(custody_unsigned)}
    custody_ref=first.put("evaluation-custody-v5.json",custody)
    manifest_unsigned={"schema_version":"information-yield-evaluation-manifest-5","evaluation_custody_ref":custody_ref}
    manifest={**manifest_unsigned,"manifest_sha256":digest_v5(manifest_unsigned)}
    manifest_ref=first.put("evaluation-manifest-v5.json",manifest)
    fresh=check_eiy_evaluation_v5(manifest_ref,read_ref=first.read_ref,workspace_root=ROOT) if issue else None
    return fixtures,fresh,manifest_ref,custody_ref

def mutate_fresh_v5(fresh:FreshEiyEvaluationV5,mutator:Callable[[dict],None])->FreshEiyEvaluationV5:
    """Corruption-injection helper; nominal opacity is not a same-user boundary."""
    data=fresh.to_audit_mapping();mutator(data)
    for fact in data["facts"]:
        fact["fact_sha256"]=digest_v5({k:v for k,v in fact.items() if k!="fact_sha256"})
    by={f["case_id"]:f for f in data["facts"]}
    for row in data["context"]["planned_cases"]:row["fact_sha256"]=by[row["case_id"]]["fact_sha256"]
    core={k:v for k,v in data["context"].items() if k not in {"context_sha256","fact_set_sha256","fact_bindings"}}
    context_sha=digest_v5(core)
    bindings=[{"case_id":r["case_id"],"request_sha256":r["request_sha256"],"fact_sha256":r["fact_sha256"],"context_sha256":context_sha} for r in data["context"]["planned_cases"]]
    data["context"].update({"context_sha256":context_sha,"fact_bindings":bindings,"fact_set_sha256":digest_v5(bindings)})
    facts=[FreshEiyFactV5(f,_FACT_TOKEN) for f in data["facts"]]
    return FreshEiyEvaluationV5(data["context"],facts,data["policy"],data["evaluation_ref"],data["custody_ref"],fresh.input_paths,_CONTEXT_TOKEN)
