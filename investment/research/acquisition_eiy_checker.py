"""Evaluation-time EIY v3 checker over freshly reopened acquisition chains.

The checker owns all semantic derivation. Callers provide only immutable artifact
references and frozen denominator rosters. Returned facts are in-memory inputs to
pure metric reduction and are not an acceptance publication or remote attestation.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from investment.research.acquisition_trace import derive_acquisition_chain_authority
from shared.research_sources.acquisition_contracts import CheckedEiyV3Request, ContractError
from shared.research_sources.artifacts import SourceError, digest, read

VERSION = "acquisition-eiy-checker-3"
FACT_VERSION = "information-yield-checked-fact-3"
NOW_VERSION = "information-yield-now-diagnostic-fact-3"
POLICY_SOURCE_SHA256 = "72f93cfac1c8e47084fd3c86b6d5cdb4ba7e4e8b11df90f20895fa1166b1ce9f"
SEMANTIC_SOURCE_PATHS = (
    "shared/research_sources/acquisition_contracts.py",
    "shared/research_sources/schemas/acquisition-chain-authority-v1.schema.json",
    "shared/research_sources/schemas/information-yield-check-request-v3.schema.json",
    "shared/research_sources/schemas/information-yield-checked-fact-v3.schema.json",
    "shared/research_sources/schemas/information-yield-now-diagnostic-v3.schema.json",
    "investment/research/acquisition_trace.py",
    "investment/research/acquisition_eiy_checker.py",
    "tuning/evals/information_fetch/information_yield/__main__.py",
    "tuning/evals/information_fetch/information_yield/contracts.py",
    "tuning/evals/information_fetch/information_yield/manifest.py",
    "tuning/evals/information_fetch/information_yield/matched_case.py",
    "tuning/evals/information_fetch/information_yield/evaluator.py",
    "tuning/evals/information_fetch/information_yield/metric-policy-v1.json",
    "tuning/evals/information_fetch/information_yield/metric-policy-v4.json",
    "shared/research_sources/schemas/information-yield-evaluation-custody-v4.schema.json",
    "shared/research_sources/schemas/information-yield-evaluation-context-v4.schema.json",
    "shared/research_sources/schemas/information-yield-policy-gates-v4.schema.json",
    "shared/research_sources/schemas/information-yield-metric-policy-v4.schema.json",
    "shared/research_sources/schemas/information-yield-case-roster-v4.schema.json",
    "shared/research_sources/schemas/information-yield-allocation-v4.schema.json",
    "shared/research_sources/schemas/information-yield-required-fields-v4.schema.json",
    "tuning/evals/information_fetch/information_yield/schemas/evaluation-manifest.schema.json",
    "tuning/evals/information_fetch/information_yield/schemas/evaluation-result.schema.json",
    "tuning/evals/information_fetch/information_yield/schemas/now-diagnostic-result.schema.json",
)


class EiyCheckerError(ValueError):
    pass


_FRESH_TOKEN = object()


class FreshEiyFact:
    """Nominal in-memory fact issued only by this checker invocation."""
    __slots__ = ("_value", "_token")

    def __init__(self, value: Mapping[str, Any], token: object) -> None:
        if token is not _FRESH_TOKEN:
            raise EiyCheckerError("ACQ_EIY_FRESH_FACT_AUTHORITY")
        self._value = deepcopy(dict(value))
        self._token = token

    def to_audit_mapping(self) -> dict[str, Any]:
        return deepcopy(self._value)


def unwrap_fresh_eiy_fact(value: Any) -> dict[str, Any]:
    if not isinstance(value, FreshEiyFact) or value._token is not _FRESH_TOKEN:
        raise EiyCheckerError("EIY_SELF_ASSERTED_BUNDLE_DISABLED")
    return deepcopy(value._value)


def _need(ok: bool, code: str) -> None:
    if not ok:
        raise EiyCheckerError(code)


def _exact(value: Any, keys: set[str], code: str) -> Mapping[str, Any]:
    _need(isinstance(value, Mapping) and set(value) == keys, code)
    return value


def _hash(value: Any, code: str) -> str:
    _need(isinstance(value, str) and len(value) == 64
          and all(ch in "0123456789abcdef" for ch in value), code)
    return value


def _identifier(value: Any, code: str) -> str:
    import re
    _need(isinstance(value, str)
          and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is not None,
          code)
    return value


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError) as error:
        raise EiyCheckerError("ACQ_EIY_JSON_INVALID") from error


def current_semantic_source_closure(workspace_root: Path) -> dict[str, Any]:
    root = Path(workspace_root).resolve(strict=True)
    sources: dict[str, str] = {}
    for relative in SEMANTIC_SOURCE_PATHS:
        path = root / relative
        _need(path.is_file() and not path.is_symlink(), "ACQ_EIY_SOURCE_CLOSURE_INVALID")
        sources[relative] = sha256(path.read_bytes()).hexdigest()
    value = {"schema_version": "information-yield-source-closure-3",
             "sources": sources}
    value["sources_sha256"] = sha256(canonical(sources)).hexdigest()
    return value


def _ids(value: Mapping[str, Any], key: str, code: str) -> list[str]:
    rows = value.get(key)
    _need(isinstance(rows, list) and len(rows) == len(set(rows)), code)
    return sorted(_identifier(row, code) for row in rows)


def _hashes(value: Mapping[str, Any], key: str, code: str) -> list[str]:
    rows = value.get(key)
    _need(isinstance(rows, list) and len(rows) == len(set(rows)), code)
    return sorted(_hash(row, code) for row in rows)


def _arm_manifest(value: Any, arm: str) -> Mapping[str, Any]:
    forbidden = {"admission_ref", "canonical_units", "required_fields", "chain_ids",
                 "canonical_key_sha256s", "reviewed", "source_arm"}
    if isinstance(value, Mapping) and forbidden & set(value):
        raise EiyCheckerError("ACQ_EIY_EVIDENCE_CHAIN_UNKNOWN")
    keys = {"schema_version", "arm", "config", "driver_ref", "dispatch_refs",
            "proposal_refs", "review_refs", "reconciliation_ref",
            "host_invocation_refs", "host_profile_ref", "credential_readiness_ref",
            "recovery_opportunities"}
    _exact(value, keys, "ACQ_EIY_ARM_MANIFEST_FIELDS")
    _need(value["schema_version"] == "information-yield-arm-manifest-3"
          and value["arm"] == arm, "ACQ_EIY_ARM_MANIFEST")
    config = value["config"]
    config_keys = {"experiment_id", "execution_id", "trace_id", "backend",
                   "model_sha256", "effort", "prompt_sha256", "tool_sha256",
                   "safety_sha256", "catalog_sha256", "taxonomy_sha256", "budget",
                   "deadlines", "cache_namespace", "cache_mode", "order_index", "cutoff",
                   "expected_dispatches", "expected_credited_units", "trust_policy",
                   "host_session_id", "host_adapter"}
    _exact(config, config_keys, "ACQ_EIY_CONFIG_FIELDS")
    for key in ("experiment_id", "execution_id", "trace_id", "backend", "effort",
                "cache_namespace", "host_session_id", "host_adapter"):
        _identifier(config[key], "ACQ_EIY_CONFIG_ID")
    for key in ("model_sha256", "prompt_sha256", "tool_sha256", "safety_sha256",
                "catalog_sha256", "taxonomy_sha256"):
        _hash(config[key], "ACQ_EIY_CONFIG_HASH")
    _need(config["cache_mode"] == "disabled"
          and type(config["order_index"]) is int and config["order_index"] in {0, 1}
          and type(config["expected_dispatches"]) is int and config["expected_dispatches"] >= 0
          and type(config["expected_credited_units"]) is int
          and config["expected_credited_units"] >= 0
          and isinstance(config["budget"], Mapping)
          and isinstance(config["deadlines"], Mapping), "ACQ_EIY_CONFIG_INVALID")
    recovery = value["recovery_opportunities"]
    _need(isinstance(recovery, list)
          and all(isinstance(row, Mapping)
                  and set(row) == {"opportunity_id", "classification",
                                  "outcome_known_at_classification"}
                  and row["outcome_known_at_classification"] is False
                  for row in recovery), "ACQ_EIY_RECOVERY_CLASSIFICATION")
    for key in ("dispatch_refs", "proposal_refs", "review_refs", "host_invocation_refs"):
        _need(isinstance(value[key], list) and len(value[key]) <= 64, "ACQ_EIY_ARM_REFS")
    return value


def _derive_arm(arm: str, manifest: Mapping[str, Any], case: Mapping[str, Any],
                required: Mapping[str, Any], freshness: Mapping[str, Any],
                financial: Mapping[str, Any], baseline_keys: set[str]) -> dict[str, Any]:
    config = manifest["config"]
    for key in ("reconciliation_ref", "host_profile_ref", "credential_readiness_ref"):
        read(manifest[key])
    authority = derive_acquisition_chain_authority(
        driver_ref=manifest["driver_ref"], dispatch_refs=manifest["dispatch_refs"],
        review_refs=manifest["review_refs"], proposal_refs=manifest["proposal_refs"],
        host_invocation_refs=manifest["host_invocation_refs"],
        host_session_id=config["host_session_id"], arm=arm)
    identities = authority["identities"]
    _need(all(config[key] == identities[key] for key in
              ("experiment_id", "execution_id", "trace_id")),
          "ACQ_EIY_ARM_IDENTITY")
    _need(authority["host"].get("backend") == config["backend"],
          "ACQ_EIY_ARM_BACKEND")
    actual_dispatches = sum(
        row.get("provider_items", 1) for row in authority["dispatches"]
        if row.get("invocation_started") is True
        and row.get("status") in {"captured", "returned", "failed"})
    _need(actual_dispatches == config["expected_dispatches"],
          "ACQ_EIY_DISPATCH_BUDGET")
    driver_units = {_ref_key(row) for row in authority["driver"].get("unit_refs", [])}
    reviewed_units = {_ref_key(row.get("binding", {}).get("unit_ref"))
                      for row in authority["reviews"]}
    _need(driver_units == reviewed_units and len(authority["reviews"]) == len(driver_units),
          "ACQ_EIY_REVIEW_POOL_INCOMPLETE")
    approved = [row for row in authority["chains"] if row["disposition"] == "approve"]
    rejected_complete = [row for row in authority["chains"] if row["disposition"] == "reject"]
    rejected_broken = authority["rejected"]
    if any(any(reason not in {"review_disposition_reject"} for reason in row["reasons"])
           for row in rejected_broken):
        raise EiyCheckerError("ACQ_EIY_EVIDENCE_CHAIN_UNKNOWN")
    _need(len(approved) == config["expected_credited_units"], "ACQ_EIY_CREDIT_COUNT")
    # Every canonical fact is derived from frozen descriptor fields on one complete chain.
    canonical: dict[str, dict[str, Any]] = {}
    chain_by_question: dict[str, list[dict[str, Any]]] = {}
    for chain in approved:
        chain = dict(chain); chain["arm"] = arm
        descriptor = {key: chain[key] for key in
                      ("question_id", "source_url", "source_version", "raw_sha256",
                       "text_sha256", "quote_sha256")}
        key = digest(["information-yield-canonical-3", descriptor])
        lineage = digest(["information-yield-lineage-3", descriptor,
                          chain["exposure_ref_sha256"]])
        row = canonical.setdefault(key, {
            "canonical_key_sha256": key,
            "canonical_id": "fact." + key[:32],
            "novelty_class": "new_fact",
            "lineage_sha256": lineage,
            "chain_ids": [],
        })
        _need(row["lineage_sha256"] == lineage, "ACQ_EIY_CANONICAL_CONFLICT")
        row["chain_ids"].append(chain["chain_id"])
        chain_by_question.setdefault(chain["question_id"], []).append(chain)
    canonical_units=[]
    for key,row in sorted(canonical.items()):
        row["chain_ids"] = sorted(set(row["chain_ids"]))
        if key not in baseline_keys:
            canonical_units.append(row)
    field_rows=[]
    _need(required.get("schema_version") in {"information-yield-required-fields-3","information-yield-required-fields-4"}
          and isinstance(required.get("fields"), list), "ACQ_EIY_REQUIRED_FIELDS")
    for descriptor in required["fields"]:
        allowed=({"field_id", "question_ids", "baseline_state", "critical"},
                 {"field_id", "question_ids", "baseline_state"})
        _need(isinstance(descriptor,Mapping) and set(descriptor) in allowed,
              "ACQ_EIY_FIELD_DESCRIPTOR")
        field_id=_identifier(descriptor["field_id"], "ACQ_EIY_FIELD_DESCRIPTOR")
        _need(descriptor["baseline_state"] in {"unknown", "partial", "resolved"}
              and ("critical" not in descriptor or type(descriptor["critical"]) is bool)
              and isinstance(descriptor["question_ids"], list)
              and descriptor["question_ids"], "ACQ_EIY_FIELD_DESCRIPTOR")
        chains=[row for q in descriptor["question_ids"] for row in chain_by_question.get(q, [])]
        post="unknown" if not chains else "partial" if len(chains)==1 else "resolved"
        field_rows.append({"field_id":field_id,"critical":descriptor.get("critical"),"baseline_state":descriptor["baseline_state"],
                           "post_state":post,"chain_ids":sorted({row["chain_id"] for row in chains})})
    _need(freshness.get("schema_version") == "information-yield-freshness-targets-3"
          and isinstance(freshness.get("targets"), list), "ACQ_EIY_FRESHNESS")
    targets=[]
    for descriptor in freshness["targets"]:
        _exact(descriptor,{"target_id","question_ids","target_sha256"},"ACQ_EIY_TARGET_DESCRIPTOR")
        rows=[row for q in descriptor["question_ids"] for row in chain_by_question.get(q, [])]
        targets.append({"target_id":_identifier(descriptor["target_id"],"ACQ_EIY_TARGET_DESCRIPTOR"),
                        "target_sha256":_hash(descriptor["target_sha256"],"ACQ_EIY_TARGET_DESCRIPTOR"),
                        "availability_status":"known" if rows else "unknown",
                        "exposure_status":"detected" if rows else "undetected",
                        "on_time":None,"lag_seconds":None,
                        "chain_ids":sorted({row["chain_id"] for row in rows})})
    _need(financial.get("schema_version") == "information-yield-financial-roster-3"
          and isinstance(financial.get("elements"), list), "ACQ_EIY_FINANCIAL")
    by_field={row["field_id"]:row for row in field_rows};elements=[]
    for descriptor in financial["elements"]:
        _exact(descriptor,{"element_id","field_ids"},"ACQ_EIY_FINANCIAL_DESCRIPTOR")
        fields=descriptor["field_ids"]
        _need(isinstance(fields,list) and fields and all(field in by_field for field in fields),
              "ACQ_EIY_FINANCIAL_DESCRIPTOR")
        ready=all(by_field[field]["post_state"]!="unknown" for field in fields)
        elements.append({"element_id":_identifier(descriptor["element_id"],"ACQ_EIY_FINANCIAL_DESCRIPTOR"),
                         "ready":ready,"unknown_reason":None if ready else "required_field_unknown",
                         "chain_ids":sorted({chain for field in fields for chain in by_field[field]["chain_ids"]})})
    judged=len(approved)+len(rejected_complete);pooled=len(driver_units);unjudged=pooled-judged
    _need(unjudged==len(rejected_broken) and unjudged>=0,"ACQ_EIY_REVIEW_ACCOUNTING")
    return {"arm":arm,"execution":{key:deepcopy(config[key]) for key in
            ("experiment_id","execution_id","trace_id","backend","model_sha256","effort",
             "prompt_sha256","tool_sha256","safety_sha256","catalog_sha256","taxonomy_sha256",
             "budget","deadlines","cache_namespace","cache_mode","order_index")},
            "canonical_units":canonical_units,"required_fields":field_rows,
            "precision":{"status":"known" if judged else "unavailable",
                         "supported_numerator":len(approved) if judged else None,
                         "judged_denominator":judged if judged else None,
                         "pooled_total":pooled if judged else None,
                         "unjudged_unknown_count":unjudged},
            "freshness":{"targets":targets},
            "financial_readiness":{"status":"known","elements":elements},
            "hard_failures":[],"recovery_preclassified":True,
            "trace_accounting":{"complete_chains":len(approved),"credited_units":len(approved),
                                "reviewed_complete_units":len(approved)+len(rejected_complete),
                                "pooled_total_units":pooled,"rejected_units":len(rejected_complete),"unjudged_units":unjudged},
            "authority_sha256":authority["authority_sha256"]}


def _ref_key(ref: Any):
    return (ref.get("path"), ref.get("sha256")) if isinstance(ref, Mapping) else None


def check_eiy_case_v3(request: Mapping[str, Any] | CheckedEiyV3Request, *,
                      read_ref: Callable[[Mapping[str, str]], Mapping[str, Any]],
                      workspace_root: Path) -> dict[str, Any]:
    """Run one fresh acquisition checker and return private in-memory checked facts."""
    try:
        req = request if isinstance(request, CheckedEiyV3Request) else CheckedEiyV3Request.from_mapping(request)
    except ContractError as error:
        raise EiyCheckerError(str(error)) from None
    loaded={name:read_ref(getattr(req,name)) for name in
            ("metric_policy_ref","case_contract_ref","case_roster_ref","allocation_ref",
             "custody_ref","baseline_ref","reference_set_ref","required_fields_ref",
             "freshness_targets_ref","financial_element_roster_ref","source_closure_ref")}
    policy=loaded["metric_policy_ref"];case=loaded["case_contract_ref"]
    _need(policy.get("schema_version") in {"information-yield-metric-policy-1","information-yield-metric-policy-4"}
          and policy.get("source_contract_sha256")==POLICY_SOURCE_SHA256,
          "ACQ_EIY_POLICY_INVALID")
    _exact(case,{"schema_version","evaluation_id","case_id","issuer_id","subject","window_id",
                 "cutoff","evidence_level","split","arm_order"},"ACQ_EIY_CASE_FIELDS")
    _need(case["schema_version"]=="information-yield-case-contract-3"
          and case["evaluation_id"]==req.evaluation_id
          and case["arm_order"] in (["B0","F"],["F","B0"]),"ACQ_EIY_CASE_INVALID")
    is_now=case["subject"]=="NOW"
    _need((req.mode=="now_diagnostic") is is_now,
          "ACQ_EIY_NOW_ONLY" if req.mode=="now_diagnostic" else "ACQ_EIY_NOW_CONFIRMATION_FORBIDDEN")
    case_roster=loaded["case_roster_ref"]
    _need(case_roster.get("schema_version") in {"information-yield-case-roster-3","information-yield-case-roster-4"}
          and case_roster.get("evaluation_id")==req.evaluation_id
          and case_roster.get("case_ids",[]).count(case["case_id"])==1,"ACQ_EIY_CASE_ROSTER")
    allocation=loaded["allocation_ref"]
    _need(allocation.get("schema_version") in {"information-yield-allocation-3","information-yield-allocation-4"}
          and allocation.get("evaluation_id")==req.evaluation_id
          and allocation.get("cases",{}).get(case["case_id"])==case["arm_order"],
          "ACQ_EIY_ALLOCATION")
    observed_closure=current_semantic_source_closure(workspace_root)
    _need(loaded["source_closure_ref"]==observed_closure,"ACQ_EIY_SOURCE_CLOSURE_DRIFT")
    manifests={name:_arm_manifest(read_ref(req.arms[name].manifest_ref),name) for name in ("B0","F")}
    custody=loaded["custody_ref"]
    _need(custody.get("schema_version")=="information-yield-custody-3"
          and custody.get("evaluation_id")==req.evaluation_id
          and custody.get("case_id")==case["case_id"]
          and custody.get("pre_start_bound") is True
          and custody.get("request_core_sha256")==sha256(canonical({k:v for k,v in req.to_dict(include_digest=False).items() if k!="custody_ref"})).hexdigest()
          and custody.get("arm_manifest_sha256s")==
              {name:req.arms[name].manifest_ref["sha256"] for name in ("B0","F")},
          "ACQ_EIY_CUSTODY")
    baseline=loaded["baseline_ref"];reference=loaded["reference_set_ref"]
    _need(baseline.get("schema_version") == "information-yield-baseline-3",
          "ACQ_EIY_BASELINE")
    _need(reference.get("schema_version") == "information-yield-reference-set-3",
          "ACQ_EIY_REFERENCE")
    baseline_keys=set(_hashes(baseline,"canonical_key_sha256s","ACQ_EIY_BASELINE"))
    reference_keys=_hashes(reference,"canonical_key_sha256s","ACQ_EIY_REFERENCE")
    try:
        arms={name:_derive_arm(name,manifests[name],case,loaded["required_fields_ref"],
                               loaded["freshness_targets_ref"],loaded["financial_element_roster_ref"],
                               baseline_keys) for name in ("B0","F")}
    except EiyCheckerError as error:
        if is_now and str(error) == "ACQ_EIY_EVIDENCE_CHAIN_UNKNOWN":
            raise EiyCheckerError("ACQ_EIY_NOW_HARD_INTEGRITY_FAILURE") from None
        raise
    _need(all(arms["B0"]["execution"][key] != arms["F"]["execution"][key]
              for key in ("experiment_id", "execution_id", "trace_id")),
          "ACQ_EIY_ARM_IDENTITY_COLLISION")
    ignored={"experiment_id","execution_id","trace_id","cache_namespace","order_index"}
    _need({k:v for k,v in arms["B0"]["execution"].items() if k not in ignored}
          == {k:v for k,v in arms["F"]["execution"].items() if k not in ignored},
          "ACQ_EIY_PAIR_MISMATCH")
    _need(arms["B0"]["execution"]["cache_namespace"]!=arms["F"]["execution"]["cache_namespace"]
          and all(arms[name]["execution"]["order_index"]==case["arm_order"].index(name)
                  for name in ("B0","F")),"ACQ_EIY_PAIR_CUSTODY")
    hashes={name.removesuffix("_ref")+"_sha256":getattr(req,name)["sha256"] for name in
            ("case_roster_ref","allocation_ref","custody_ref","baseline_ref","reference_set_ref",
             "required_fields_ref","freshness_targets_ref","financial_element_roster_ref")}
    value={"schema_version":NOW_VERSION if is_now else FACT_VERSION,"checker_version":VERSION,
           "evaluation_id":req.evaluation_id,"case_id":case["case_id"],"issuer_id":case["issuer_id"],
           "subject":case["subject"],"window_id":case["window_id"],"cutoff":case["cutoff"],
           "evidence_level":case["evidence_level"],"split":case["split"],
           "metric_policy_sha256":req.metric_policy_ref["sha256"],**hashes,
           "source_closure_sha256":observed_closure["sources_sha256"],
           "request_sha256":req.request_sha256,"reference_canonical_key_sha256s":reference_keys,
           "required_field_ids":[row["field_id"] for row in loaded["required_fields_ref"]["fields"]],
           "freshness_target_ids":[row["target_id"] for row in loaded["freshness_targets_ref"]["targets"]],
           "financial_element_ids":[row["element_id"] for row in loaded["financial_element_roster_ref"]["elements"]],
           "arm_order":case["arm_order"],"arms":arms,"hard_failures":[]}
    if is_now and any(arm["hard_failures"] or arm["trace_accounting"]["unjudged_units"] for arm in arms.values()):
        raise EiyCheckerError("ACQ_EIY_NOW_HARD_INTEGRITY_FAILURE")
    value["fact_sha256"]=digest(value)
    return FreshEiyFact(value, _FRESH_TOKEN)


def audit_eiy_case_v3(request, *, read_ref, workspace_root: Path,
                      expected_fact_sha256: str) -> dict[str, Any]:
    """Re-run O2 derivation and compare one previously observed audit hash."""
    _hash(expected_fact_sha256, "ACQ_EIY_AUDIT_HASH")
    fact = check_eiy_case_v3(request, read_ref=read_ref, workspace_root=workspace_root)
    observed = fact.to_audit_mapping()["fact_sha256"]
    _need(observed == expected_fact_sha256, "ACQ_EIY_AUDIT_MISMATCH")
    return {"status": "pass", "fact_sha256": observed,
            "scope": "provider_free_checker_rerun_not_remote_attestation"}

_EVALUATION_TOKEN = object()


class FreshEiyEvaluation:
    """One private nominal batch context plus its exact fresh case facts."""
    __slots__ = ("_context", "_facts", "_policy", "_token", "_input_paths")

    def __init__(self, context, facts, policy, input_paths, token):
        if token is not _EVALUATION_TOKEN:
            raise EiyCheckerError("ACQ_EIY_EVALUATION_AUTHORITY")
        self._context = deepcopy(context); self._facts = tuple(facts)
        self._policy = deepcopy(policy); self._input_paths = frozenset(input_paths)
        self._token = token

    def to_audit_mapping(self):
        return {"context": deepcopy(self._context),
                "facts": [row.to_audit_mapping() for row in self._facts],
                "policy": deepcopy(self._policy)}

    @property
    def input_paths(self): return set(self._input_paths)


def unwrap_fresh_eiy_evaluation(value):
    if not isinstance(value, FreshEiyEvaluation) or value._token is not _EVALUATION_TOKEN:
        raise EiyCheckerError("EIY_V3_EVALUATION_CONTEXT_REQUIRED")
    return value.to_audit_mapping()


def check_eiy_evaluation_v4(evaluation_custody_ref, *, read_ref, workspace_root: Path):
    """Derive one exact planned evaluation context and all fresh case facts."""
    custody = read_ref(evaluation_custody_ref)
    keys={"schema_version","evaluation_id","mode","metric_policy_ref","case_roster_ref",
          "allocation_ref","baseline_ref","reference_set_ref","required_fields_ref",
          "freshness_targets_ref","financial_element_roster_ref","source_closure_ref",
          "request_refs","custody_sha256"}
    _exact(custody,keys,"ACQ_EIY_V4_CUSTODY_FIELDS")
    _need(custody["schema_version"]=="information-yield-evaluation-custody-4",
          "ACQ_EIY_V4_CUSTODY_VERSION")
    unsigned=dict(custody);claimed=unsigned.pop("custody_sha256")
    _need(claimed==digest(unsigned),"ACQ_EIY_V4_CUSTODY_DIGEST")
    refs=custody["request_refs"]
    _need(isinstance(refs,list) and refs and len(refs)<=64
          and len({(r.get("path"),r.get("sha256")) for r in refs})==len(refs),
          "ACQ_EIY_V4_REQUEST_REFS")
    loaded={name:read_ref(custody[name]) for name in
            ("metric_policy_ref","case_roster_ref","allocation_ref","baseline_ref",
             "reference_set_ref","required_fields_ref","freshness_targets_ref",
             "financial_element_roster_ref","source_closure_ref")}
    policy=loaded["metric_policy_ref"]
    _need(policy.get("schema_version")=="information-yield-metric-policy-4",
          "ACQ_EIY_V4_POLICY")
    roster=loaded["case_roster_ref"];allocation=loaded["allocation_ref"]
    _need(isinstance(roster,Mapping) and set(roster)=={"schema_version","evaluation_id","case_ids","cases"}
          and roster.get("schema_version")=="information-yield-case-roster-4"
          and roster.get("evaluation_id")==custody["evaluation_id"]
          and isinstance(roster.get("case_ids"),list)
          and isinstance(roster.get("cases"),list),"ACQ_EIY_V4_ROSTER")
    _need(allocation.get("schema_version")=="information-yield-allocation-4"
          and allocation.get("evaluation_id")==custody["evaluation_id"]
          and isinstance(allocation.get("cases"),dict),"ACQ_EIY_V4_ALLOCATION")
    planned=roster["cases"];case_ids=[row.get("case_id") for row in planned]
    legal_splits={("confirmation","untouched"),("development","development"),("diagnostic","diagnostic")}
    _need(all((row.get("evidence_level"),row.get("split")) in legal_splits for row in planned),
          "ACQ_EIY_V4_SPLIT_INVALID")
    _need(roster["case_ids"]==case_ids,"ACQ_EIY_EVALUATION_FACT_SET_MISMATCH")
    _need(case_ids and len(case_ids)==len(set(case_ids)) and len(refs)==len(case_ids),
          "ACQ_EIY_EVALUATION_FACT_SET_MISMATCH")
    _need(list(allocation["cases"])==case_ids,"ACQ_EIY_V4_ALLOCATION_MISMATCH")
    common_ref_names=("metric_policy_ref","case_roster_ref","allocation_ref","baseline_ref",
                      "reference_set_ref","required_fields_ref","freshness_targets_ref",
                      "financial_element_roster_ref","source_closure_ref")
    requests_by_case={}
    for request_ref in refs:
        request_value=read_ref(request_ref)
        try:req=CheckedEiyV3Request.from_mapping(request_value)
        except ContractError as error:raise EiyCheckerError(str(error)) from None
        case_value=read_ref(req.case_contract_ref);case_id=case_value.get("case_id")
        _need(isinstance(case_id,str) and case_id not in requests_by_case,
              "ACQ_EIY_EVALUATION_FACT_SET_MISMATCH")
        requests_by_case[case_id]=(request_ref,req)
    _need(set(requests_by_case)==set(case_ids),"ACQ_EIY_EVALUATION_FACT_SET_MISMATCH")
    facts=[];derived=[];input_paths={evaluation_custody_ref["path"]}
    for case_row in planned:
        request_ref,req=requests_by_case[case_row["case_id"]]
        _need(req.evaluation_id==custody["evaluation_id"]
              and req.mode==custody["mode"]
              and all(getattr(req,name)==custody[name] for name in common_ref_names),
              "ACQ_EIY_V4_REQUEST_BINDING")
        fact=check_eiy_case_v3(req,read_ref=read_ref,workspace_root=workspace_root)
        value=fact.to_audit_mapping()
        expected_keys={"case_id","issuer_id","subject","window_id","cutoff",
                       "evidence_level","split","arm_order"}
        _exact(case_row,expected_keys,"ACQ_EIY_V4_ROSTER_ROW")
        _need(all(value[key]==case_row[key] for key in expected_keys)
              ,"ACQ_EIY_EVALUATION_FACT_SET_MISMATCH")
        _need(allocation["cases"][case_row["case_id"]]==case_row["arm_order"],
              "ACQ_EIY_V4_ALLOCATION_MISMATCH")
        facts.append(fact)
        derived.append({**dict(case_row),"request_ref":dict(request_ref),
                        "request_sha256":req.request_sha256,
                        "case_custody_sha256":req.custody_ref["sha256"],
                        "arm_manifest_refs":{a:dict(req.arms[a].manifest_ref) for a in ("B0","F")},
                        "arm_executions":{a:deepcopy(value["arms"][a]["execution"]) for a in ("B0","F")},
                        "fact_sha256":value["fact_sha256"]})
        input_paths.add(request_ref["path"])
        for name in common_ref_names:input_paths.add(custody[name]["path"])
        input_paths.add(req.custody_ref["path"])
        input_paths.update(req.arms[a].manifest_ref["path"] for a in ("B0","F"))
    _need(case_ids==[row["case_id"] for row in derived],
          "ACQ_EIY_EVALUATION_FACT_SET_MISMATCH")
    split_counts={}
    for row in derived:
        key=f'{row["evidence_level"]}:{row["split"]}'
        split_counts[key]=split_counts.get(key,0)+1
    common_hashes={name.removesuffix("_ref")+"_sha256":custody[name]["sha256"]
                   for name in common_ref_names if name!="metric_policy_ref"}
    context_core={"schema_version":"information-yield-evaluation-context-4",
                  "evaluation_id":custody["evaluation_id"],"mode":custody["mode"],
                  "planned_cases":derived,"split_counts":dict(sorted(split_counts.items())),
                  "common_hashes":common_hashes,"policy":deepcopy(policy),
                  "policy_sha256":custody["metric_policy_ref"]["sha256"],
                  "source_closure_sha256":loaded["source_closure_ref"]["sources_sha256"]}
    context_sha=digest(context_core)
    bindings=[{"case_id":row["case_id"],"request_sha256":row["request_sha256"],
               "fact_sha256":row["fact_sha256"],"context_sha256":context_sha}
              for row in derived]
    fact_set_sha=digest(bindings)
    context={**context_core,"fact_bindings":bindings,"fact_set_sha256":fact_set_sha,"context_sha256":context_sha}
    return FreshEiyEvaluation(context,facts,policy,input_paths,_EVALUATION_TOKEN)


def audit_eiy_evaluation_v4(evaluation_custody_ref, *, read_ref, workspace_root: Path,
                            expected_context_sha256: str, expected_fact_set_sha256: str):
    evaluation=check_eiy_evaluation_v4(evaluation_custody_ref,read_ref=read_ref,
                                       workspace_root=workspace_root)
    context=evaluation.to_audit_mapping()["context"]
    _need(context["context_sha256"]==expected_context_sha256
          and context["fact_set_sha256"]==expected_fact_set_sha256,
          "ACQ_EIY_V4_AUDIT_MISMATCH")
    return {"status":"pass","context_sha256":expected_context_sha256,
            "fact_set_sha256":expected_fact_set_sha256,
            "scope":"provider_free_batch_rerun_not_remote_attestation"}
