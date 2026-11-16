"""Closed validation for fresh evaluation-time checker facts only."""
from __future__ import annotations
from copy import deepcopy
from typing import Any
from .contracts import InformationYieldError,need,exact_keys,safe_id,digest
from investment.research.acquisition_eiy_checker import FreshEiyFact,unwrap_fresh_eiy_fact,EiyCheckerError
STATES={"unknown":0,"partial":1,"resolved":2}
HASH_KEYS=("metric_policy_sha256","case_roster_sha256","allocation_sha256","custody_sha256","baseline_sha256","reference_set_sha256","required_fields_sha256","freshness_targets_sha256","financial_element_roster_sha256","source_closure_sha256","request_sha256")
def _hash(v,code="EIY_FACT_HASH"):
 import re
 need(isinstance(v,str) and re.fullmatch(r"[a-f0-9]{64}",v),code);return v
def validate_checked_case(_value:Any):raise InformationYieldError("EIY_SELF_ASSERTED_BUNDLE_DISABLED")
def validate_fresh_fact(value:FreshEiyFact,*,now:bool=False)->dict[str,Any]:
 try:v=unwrap_fresh_eiy_fact(value)
 except EiyCheckerError as e:raise InformationYieldError(str(e)) from None
 keys={"schema_version","checker_version","evaluation_id","case_id","issuer_id","subject","window_id","cutoff","evidence_level","split","metric_policy_sha256","case_roster_sha256","allocation_sha256","custody_sha256","baseline_sha256","reference_set_sha256","required_fields_sha256","freshness_targets_sha256","financial_element_roster_sha256","source_closure_sha256","request_sha256","reference_canonical_key_sha256s","required_field_ids","freshness_target_ids","financial_element_ids","arm_order","arms","hard_failures","fact_sha256"}
 exact_keys(v,keys,"EIY_FACT_FIELDS");need((v["subject"]=="NOW") is now,"EIY_NOW_BOUNDARY")
 expected="information-yield-now-diagnostic-fact-3" if now else "information-yield-checked-fact-3";need(v["schema_version"]==expected,"EIY_FACT_VERSION")
 for k in ("evaluation_id","case_id","issuer_id","subject","window_id","checker_version"):safe_id(v[k],"EIY_FACT_ID")
 for k in HASH_KEYS:_hash(v[k])
 need(v["arm_order"] in [["B0","F"],["F","B0"]] and isinstance(v["arms"],dict) and set(v["arms"])=={"B0","F"},"EIY_FACT_ARMS")
 for name,arm in v["arms"].items():
  need(arm.get("arm")==name and isinstance(arm.get("canonical_units"),list) and isinstance(arm.get("required_fields"),list),"EIY_FACT_ARM")
  for unit in arm["canonical_units"]:
   exact_keys(unit,{"canonical_key_sha256","canonical_id","novelty_class","lineage_sha256","chain_ids"},"EIY_FACT_UNIT");_hash(unit["canonical_key_sha256"]);_hash(unit["lineage_sha256"]);need(unit["chain_ids"] and len(unit["chain_ids"])==len(set(unit["chain_ids"])) and all(_hash(x) for x in unit["chain_ids"]),"EIY_FACT_CHAIN")
  for field in arm["required_fields"]:
   exact_keys(field,{"field_id","critical","baseline_state","post_state","chain_ids"},"EIY_FACT_FIELD");need((field["critical"] is None or type(field["critical"]) is bool) and field["baseline_state"] in STATES and field["post_state"] in STATES and (field["post_state"]=="unknown" or field["chain_ids"]),"EIY_FACT_FIELD")
 failures=v["hard_failures"];need(isinstance(failures,list) and len(failures)<=64,"EIY_FACT_FAILURES")
 for row in failures:
  exact_keys(row,{"code","chain_ids"},"EIY_FACT_FAILURE");safe_id(row["code"],"EIY_FACT_FAILURE");need(isinstance(row["chain_ids"],list) and row["chain_ids"] and len(row["chain_ids"])==len(set(row["chain_ids"])) and all(_hash(x) for x in row["chain_ids"]),"EIY_FACT_FAILURE")
 copy=deepcopy(v);claimed=copy.pop("fact_sha256");need(_hash(claimed)==digest(copy),"EIY_FACT_DIGEST");return v
