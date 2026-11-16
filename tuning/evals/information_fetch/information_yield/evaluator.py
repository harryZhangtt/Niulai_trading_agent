"""Total pure EIY v4 reducer over one checker-issued evaluation context."""
from __future__ import annotations
from statistics import mean,median
from fractions import Fraction
import math
from typing import Any,Mapping
from investment.research.acquisition_eiy_checker import unwrap_fresh_eiy_evaluation,EiyCheckerError
from .contracts import InformationYieldError,exact_keys,need,digest
STATES={"unknown":0,"partial":1,"resolved":2}
RESULT_VERSION="information-yield-result-4";NOW_RESULT_VERSION="information-yield-now-diagnostic-result-4"
def evaluate_checked_cases(**_):raise InformationYieldError("EIY_SELF_ASSERTED_BUNDLE_DISABLED")
def evaluate_fresh_checked_facts(**_):raise InformationYieldError("EIY_V3_EVALUATION_CONTEXT_REQUIRED")
def evaluate_now_diagnostics(**_):raise InformationYieldError("EIY_V3_EVALUATION_CONTEXT_REQUIRED")
def _gate(name,status,*,observed=None,threshold=None,numerator=None,denominator=None,cases=(),reasons=()):
 need(status in {"pass","fail","unknown","not_applicable"},"EIY_GATE_STATUS")
 return {"name":name,"status":status,"observed":observed,"threshold":threshold,"numerator":numerator,"denominator":denominator,"case_results":list(cases),"reason_codes":list(reasons)}
def _policy(policy,claimed):
 keys={"schema_version","source_contract_sha256","confirmation_case_count","confirmation_order_counts","minimum_eiy_r","minimum_eiy_d","minimum_positive_cases","minimum_case_delta","require_positive_issuer_loo","minimum_precision_delta","maximum_arm_wall_seconds","maximum_aggregate_wall_ratio","maximum_case_wall_ratio","zero_hard_failures","complete_trace_ratio","zero_critical_unsupported","minimum_aggregate_lineage_delta","minimum_case_lineage_delta","hard_failure_codes","scalar_score_prohibited","now_excluded"}
 exact_keys(policy,keys,"EIY_POLICY_FIELDS");need(policy["schema_version"]=="information-yield-metric-policy-4" and policy["scalar_score_prohibited"] is True and policy["now_excluded"] is True and digest(policy)==claimed,"EIY_POLICY_INVALID")
def _unwrap(value):
 try:return unwrap_fresh_eiy_evaluation(value)
 except EiyCheckerError as error:raise InformationYieldError(str(error)) from None
def _validate_context(data):
 context=data["context"];facts=data["facts"];planned=context["planned_cases"]
 need(context.get("policy")==data["policy"],"EIY_POLICY_CONTEXT_MISMATCH")
 core={k:v for k,v in context.items() if k not in {"context_sha256","fact_set_sha256","fact_bindings"}}
 need(digest(core)==context["context_sha256"],"EIY_CONTEXT_DIGEST")
 bindings=[{"case_id":row["case_id"],"request_sha256":row["request_sha256"],"fact_sha256":row["fact_sha256"],"context_sha256":context["context_sha256"]} for row in planned]
 need(bindings==context.get("fact_bindings") and digest(bindings)==context["fact_set_sha256"],"EIY_FACT_SET_DIGEST")
 need(all(digest({k:v for k,v in fact.items() if k!="fact_sha256"})==fact.get("fact_sha256") for fact in facts),"EIY_FACT_DIGEST")
 need(len(planned)==len(facts) and [r["case_id"] for r in planned]==[f["case_id"] for f in facts] and all(p["request_sha256"]==f["request_sha256"] and p["fact_sha256"]==f["fact_sha256"] for p,f in zip(planned,facts)),"EIY_EVALUATION_FACT_SET_MISMATCH")
 return context,facts
def _case(fact):
 arms={}
 for name in ("B0","F"):
  arm=fact["arms"][name];fields=arm["required_fields"];p=arm["precision"];trace=arm["trace_accounting"]
  arms[name]={"richness":len({u["canonical_key_sha256"] for u in arm["canonical_units"]}),"depth":sum(STATES[x["post_state"]]-STATES[x["baseline_state"]] for x in fields),"lineages":len({u["lineage_sha256"] for u in arm["canonical_units"]}),"precision":p,"wall_seconds":arm["execution"]["deadlines"].get("observed_wall_seconds"),"trace":trace,"critical_unsupported":sum(1 for x in fields if x.get("critical") is True and (x["post_state"]=="unknown" or not x["chain_ids"])),"critical_metadata_known":all(type(x.get("critical")) is bool for x in fields),"recovery_preclassified":arm.get("recovery_preclassified") is True,"execution":arm["execution"]}
 return {"case_id":fact["case_id"],"issuer_id":fact["issuer_id"],"subject":fact["subject"],"window_id":fact["window_id"],"evidence_level":fact["evidence_level"],"split":fact["split"],"arm_order":fact["arm_order"],"request_sha256":fact["request_sha256"],"fact_sha256":fact["fact_sha256"],"arms":arms,"delta_r":arms["F"]["richness"]-arms["B0"]["richness"],"delta_d":arms["F"]["depth"]-arms["B0"]["depth"],"lineage_delta":arms["F"]["lineages"]-arms["B0"]["lineages"],"hard_failures":fact["hard_failures"]}
def _vector(values,rows):
 issuers=sorted({r["issuer_id"] for r in rows});loo=[]
 for issuer in issuers:
  left=[v for v,r in zip(values,rows) if r["issuer_id"]!=issuer];loo.append({"issuer_id":issuer,"mean":mean(left) if left else None})
 wins=sum(v>0 for v in values);ties=sum(v==0 for v in values);losses=sum(v<0 for v in values)
 return {"mean":mean(values) if values else None,"median":median(values) if values else None,"minimum":min(values) if values else None,"maximum":max(values) if values else None,"range":(max(values)-min(values)) if values else None,"wins":wins,"ties":ties,"losses":losses,"total":sum(values),"denominator":len(values),"leave_one_issuer_out":loo}
def compute_policy_gates_v4(*,policy:Mapping[str,Any],facts,context):
 rows=[_case(f) for f in facts];confirmation=[r for r in rows if r["evidence_level"]=="confirmation" and r["split"]=="untouched"]
 development=[r for r in rows if r not in confirmation];gates=[];ids=[r["case_id"] for r in confirmation]
 distinct=len({r["issuer_id"] for r in confirmation})==len(confirmation)==len({(r["issuer_id"],r["window_id"]) for r in confirmation});orders={"B0_first":sum(r["arm_order"]==["B0","F"] for r in confirmation),"F_first":sum(r["arm_order"]==["F","B0"] for r in confirmation)};cohort_ok=len(confirmation)==policy["confirmation_case_count"] and distinct and orders==policy["confirmation_order_counts"]
 gates.append(_gate("confirmation_cohort","pass" if cohort_ok else "fail",observed={"count":len(confirmation),"distinct":distinct,"orders":orders},threshold={"count":policy["confirmation_case_count"],"orders":policy["confirmation_order_counts"]},cases=ids,reasons=() if cohort_ok else ("EIY_CONFIRMATION_COHORT",)))
 dr=[r["delta_r"] for r in confirmation];dd=[r["delta_d"] for r in confirmation];stats={"richness":_vector(dr,confirmation),"depth":_vector(dd,confirmation)}
 for name,vals,minimum in (("richness",dr,policy["minimum_eiy_r"]),("depth",dd,policy["minimum_eiy_d"])):
  known=bool(vals);m=mean(vals) if vals else None;gates.append(_gate(f"{name}_mean","pass" if known and m>=minimum else "fail" if known else "unknown",observed=m,threshold=minimum,numerator=sum(vals) if vals else None,denominator=len(vals) if vals else None,cases=[{"case_id":r["case_id"],"delta":v} for r,v in zip(confirmation,vals)],reasons=() if known and m>=minimum else (f"EIY_{name.upper()}_MEAN",)))
  pos=sum(v>0 for v in vals);gates.append(_gate(f"{name}_positive_cases","pass" if known and pos>=policy["minimum_positive_cases"] else "fail" if known else "unknown",observed=pos,threshold=policy["minimum_positive_cases"],numerator=pos,denominator=len(vals) if vals else None,cases=ids,reasons=() if known and pos>=policy["minimum_positive_cases"] else (f"EIY_{name.upper()}_POSITIVE",)))
 floor_ok=bool(dr) and all(v>=policy["minimum_case_delta"] for v in dr+dd);gates.append(_gate("case_delta_floor","pass" if floor_ok else "fail" if dr else "unknown",observed=min(dr+dd) if dr else None,threshold=policy["minimum_case_delta"],cases=[{"case_id":r["case_id"],"delta_r":r["delta_r"],"delta_d":r["delta_d"]} for r in confirmation],reasons=() if floor_ok else ("EIY_CASE_DELTA_FLOOR",)))
 loo_rows=stats["richness"]["leave_one_issuer_out"]+stats["depth"]["leave_one_issuer_out"]
 if not policy["require_positive_issuer_loo"]:gates.append(_gate("issuer_loo","not_applicable",observed=None,threshold=None,cases=loo_rows))
 else:
  loo_known=bool(loo_rows) and all(x["mean"] is not None for x in loo_rows);loo_ok=loo_known and all(x["mean"]>0 for x in loo_rows);gates.append(_gate("issuer_loo","pass" if loo_ok else "fail" if loo_known else "unknown",observed=[x["mean"] for x in loo_rows],threshold=">0",cases=loo_rows,reasons=() if loo_ok else ("EIY_ISSUER_LOO",)))
 precision_cases=[];unknown_precision=False;sum_s={"B0":0,"F":0};sum_j={"B0":0,"F":0}
 for r in confirmation:
  vals={}
  for a in ("B0","F"):
   p=r["arms"][a]["precision"];known=p.get("status")=="known" and type(p.get("judged_denominator")) is int and p["judged_denominator"]>0 and p.get("unjudged_unknown_count")==0 and type(p.get("supported_numerator")) is int
   if not known:unknown_precision=True;vals[a]=None
   else:sum_s[a]+=p["supported_numerator"];sum_j[a]+=p["judged_denominator"];vals[a]=p["supported_numerator"]/p["judged_denominator"]
  precision_cases.append({"case_id":r["case_id"],"B0":vals["B0"],"F":vals["F"],"delta":None if None in vals.values() else vals["F"]-vals["B0"]})
 precision_known=not unknown_precision and all(sum_j[a]>0 for a in ("B0","F"));pdelta_fraction=(Fraction(sum_s["F"],sum_j["F"])-Fraction(sum_s["B0"],sum_j["B0"])) if precision_known else None;pdelta=float(pdelta_fraction) if pdelta_fraction is not None else None;pok=precision_known and pdelta_fraction>=Fraction(str(policy["minimum_precision_delta"]));gates.append(_gate("precision_delta","pass" if pok else "fail" if precision_known else "unknown",observed=pdelta,threshold=policy["minimum_precision_delta"],numerator=[sum_s["F"],sum_s["B0"]],denominator=[sum_j["F"],sum_j["B0"]],cases=precision_cases,reasons=() if pok else ("EIY_PRECISION_DELTA" if precision_known else "EIY_PRECISION_UNKNOWN",)))
 wall_cases=[];wall_unknown=False;arm_ok=True;ratio_ok=True;sum_wall={"B0":0.0,"F":0.0}
 for r in confirmation:
  b=r["arms"]["B0"]["wall_seconds"];f=r["arms"]["F"]["wall_seconds"];known=type(b) in (int,float) and type(f) in (int,float) and math.isfinite(b) and math.isfinite(f) and b>0 and f>=0
  if not known:wall_unknown=True;ratio=None
  else:ratio=f/b;sum_wall["B0"]+=b;sum_wall["F"]+=f;arm_ok &= b<=policy["maximum_arm_wall_seconds"] and f<=policy["maximum_arm_wall_seconds"];ratio_ok &= ratio<=policy["maximum_case_wall_ratio"]
  wall_cases.append({"case_id":r["case_id"],"B0":b,"F":f,"ratio":ratio})
 gates.append(_gate("arm_wall_limit","unknown" if wall_unknown else "pass" if arm_ok else "fail",observed=wall_cases,threshold=policy["maximum_arm_wall_seconds"],cases=wall_cases,reasons=() if not wall_unknown and arm_ok else ("EIY_WALL_UNKNOWN" if wall_unknown else "EIY_ARM_WALL_LIMIT",)))
 gates.append(_gate("case_wall_ratio","unknown" if wall_unknown else "pass" if ratio_ok else "fail",observed=[x["ratio"] for x in wall_cases],threshold=policy["maximum_case_wall_ratio"],cases=wall_cases,reasons=() if not wall_unknown and ratio_ok else ("EIY_WALL_UNKNOWN" if wall_unknown else "EIY_CASE_WALL_RATIO",)))
 aggregate=(sum_wall["F"]/sum_wall["B0"]) if not wall_unknown and sum_wall["B0"]>0 else None;agg_ok=aggregate is not None and aggregate<=policy["maximum_aggregate_wall_ratio"];gates.append(_gate("aggregate_wall_ratio","pass" if agg_ok else "fail" if aggregate is not None else "unknown",observed=aggregate,threshold=policy["maximum_aggregate_wall_ratio"],numerator=sum_wall["F"] if aggregate is not None else None,denominator=sum_wall["B0"] if aggregate is not None else None,cases=wall_cases,reasons=() if agg_ok else ("EIY_AGGREGATE_WALL_RATIO" if aggregate is not None else "EIY_WALL_UNKNOWN",)))
 trace_cases=[];trace_fail=False;trace_unknown=False
 for r in confirmation:
  for a in ("B0","F"):
   t=r["arms"][a]["trace"];c=t.get("complete_chains");d=t.get("credited_units");unjudged=t.get("unjudged_units")
   if c==0 and d==0 and unjudged==0:status="not_applicable";ratio=None
   elif type(c) is int and type(d) is int and d>0 and unjudged==0:ratio=c/d;status="pass" if ratio>=policy["complete_trace_ratio"] else "fail";trace_fail |= status=="fail"
   else:ratio=None;status="unknown";trace_unknown=True
   trace_cases.append({"case_id":r["case_id"],"arm":a,"status":status,"ratio":ratio,"complete":c,"credited":d,"unjudged":unjudged})
 gates.append(_gate("complete_trace_ratio","unknown" if trace_unknown else "fail" if trace_fail else "pass",observed=trace_cases,threshold=policy["complete_trace_ratio"],cases=trace_cases,reasons=() if not trace_unknown and not trace_fail else ("EIY_TRACE_UNKNOWN" if trace_unknown else "EIY_TRACE_RATIO",)))
 pooled=[];pooled_unknown=False;pooled_fail=False
 for r in confirmation:
  for a in ("B0","F"):
   t=r["arms"][a]["trace"];reviewed=t.get("reviewed_complete_units");total=t.get("pooled_total_units");unjudged=t.get("unjudged_units")
   known=all(type(x) is int and x>=0 for x in (reviewed,total,unjudged));ok=known and reviewed==total and unjudged==0;pooled_unknown|=not known;pooled_fail|=known and not ok;pooled.append({"case_id":r["case_id"],"arm":a,"status":"unknown" if not known else "pass" if ok else "fail","reviewed":reviewed,"pooled":total,"unjudged":unjudged})
 gates.append(_gate("complete_pooled_review","unknown" if pooled_unknown else "fail" if pooled_fail else "pass",observed=pooled,threshold="reviewed=pooled;unjudged=0",cases=pooled,reasons=() if not pooled_unknown and not pooled_fail else ("EIY_POOLED_REVIEW_UNKNOWN" if pooled_unknown else "EIY_POOLED_REVIEW_INCOMPLETE",)))
 critical=[{"case_id":r["case_id"],"count":r["arms"]["F"]["critical_unsupported"],"metadata_known":r["arms"]["F"]["critical_metadata_known"]} for r in confirmation];critical_known=all(x["metadata_known"] for x in critical);critical_total=sum(x["count"] for x in critical);critical_ok=critical_known and critical_total==0
 if not policy["zero_critical_unsupported"]:gates.append(_gate("zero_critical_unsupported","not_applicable",observed=critical_total if critical_known else None,threshold=None,cases=critical))
 else:gates.append(_gate("zero_critical_unsupported","pass" if critical_ok else "fail" if critical_known else "unknown",observed=critical_total if critical_known else None,threshold=0,numerator=critical_total if critical_known else None,denominator=len(critical),cases=critical,reasons=() if critical_ok else ("EIY_CRITICAL_UNSUPPORTED" if critical_known else "EIY_CRITICAL_METADATA_UNKNOWN",)))
 lineage_cases=[{"case_id":r["case_id"],"delta":r["lineage_delta"]} for r in confirmation];lineage_total=sum(x["delta"] for x in lineage_cases);lineage_ok=bool(lineage_cases) and lineage_total>=policy["minimum_aggregate_lineage_delta"] and all(x["delta"]>=policy["minimum_case_lineage_delta"] for x in lineage_cases);gates.append(_gate("lineage","pass" if lineage_ok else "fail" if lineage_cases else "unknown",observed=lineage_total if lineage_cases else None,threshold={"aggregate":policy["minimum_aggregate_lineage_delta"],"case":policy["minimum_case_lineage_delta"]},cases=lineage_cases,reasons=() if lineage_ok else ("EIY_LINEAGE",)))
 execution=[];execution_ok=True
 for r in confirmation:
  b=r["arms"]["B0"]["execution"];f=r["arms"]["F"]["execution"];ignored={"experiment_id","execution_id","trace_id","cache_namespace","order_index"};ok={k:v for k,v in b.items() if k not in ignored}=={k:v for k,v in f.items() if k not in ignored} and b["cache_namespace"]!=f["cache_namespace"] and b.get("cache_mode")==f.get("cache_mode")=="disabled" and b["order_index"]==r["arm_order"].index("B0") and f["order_index"]==r["arm_order"].index("F") and r["arms"]["B0"]["recovery_preclassified"] and r["arms"]["F"]["recovery_preclassified"];execution_ok &= ok;execution.append({"case_id":r["case_id"],"matched":ok})
 gates.append(_gate("execution_custody","pass" if execution_ok and execution else "fail",observed=execution_ok,threshold=True,cases=execution,reasons=() if execution_ok and execution else ("EIY_EXECUTION_CUSTODY",)))
 allowed=set(policy["hard_failure_codes"]);hard=[];hard_unknown=False
 for r in confirmation:
  for failure in r["hard_failures"]:
   if not isinstance(failure,dict) or set(failure)!={"code","chain_ids"} or failure.get("code") not in allowed or not failure.get("chain_ids"):hard_unknown=True
   else:hard.append({"case_id":r["case_id"],**failure})
 hard_status="unknown" if hard_unknown else "fail" if hard else "pass"
 if not policy["zero_hard_failures"]:gates.append(_gate("zero_hard_failures","not_applicable",observed=len(hard) if not hard_unknown else None,threshold=None,cases=hard))
 else:gates.append(_gate("zero_hard_failures",hard_status,observed=len(hard) if not hard_unknown else None,threshold=0,numerator=len(hard) if not hard_unknown else None,denominator=len(confirmation),cases=hard,reasons=() if hard_status=="pass" else ("EIY_HARD_FAILURE_UNKNOWN" if hard_unknown else "EIY_HARD_FAILURE",)))
 unknown=[g["name"] for g in gates if g["status"]=="unknown"];gates.append(_gate("unknown_semantics","pass" if not unknown else "fail",observed=unknown,threshold=[],cases=[],reasons=() if not unknown else ("EIY_UNKNOWN_SEMANTICS",)))
 return {"gates":gates,"statistics":stats,"confirmation_cases":confirmation,"development_cases":development}
def _public_case(row):
 def arm(value):
  p=value["precision"];precision=(p["supported_numerator"]/p["judged_denominator"] if p.get("status")=="known" and type(p.get("judged_denominator")) is int and p["judged_denominator"]>0 and p.get("unjudged_unknown_count")==0 else None);t=value["trace"]
  return {"richness":value["richness"],"depth":value["depth"],"lineages":value["lineages"],"precision":precision,"wall_seconds":value["wall_seconds"] if type(value["wall_seconds"]) in (int,float) else None,"critical_unsupported":value["critical_unsupported"],"trace":{"complete":t.get("complete_chains"),"credited":t.get("credited_units"),"reviewed_complete":t.get("reviewed_complete_units"),"pooled_total":t.get("pooled_total_units"),"rejected":t.get("rejected_units"),"unjudged":t.get("unjudged_units")}}
 return {"case_id":row["case_id"],"issuer_id":row["issuer_id"],"subject":row["subject"],"window_id":row["window_id"],"evidence_level":row["evidence_level"],"split":row["split"],"arm_order":row["arm_order"],"request_sha256":row["request_sha256"],"fact_sha256":row["fact_sha256"],"delta_r":row["delta_r"],"delta_d":row["delta_d"],"lineage_delta":row["lineage_delta"],"arms":{"B0":arm(row["arms"]["B0"]),"F":arm(row["arms"]["F"])},"hard_failures":row["hard_failures"]}

def evaluate_fresh_eiy_evaluation(*,fresh_evaluation):
 data=_unwrap(fresh_evaluation);context,facts=_validate_context(data);policy=data["policy"]
 need(context["mode"]=="evaluation" and all(f["subject"]!="NOW" for f in facts),"EIY_NOW_CONFIRMATION_FORBIDDEN")
 _policy(policy,context["policy_sha256"]);computed=compute_policy_gates_v4(policy=policy,facts=facts,context=context);gates=computed["gates"]
 by={g["name"]:g for g in gates};decisive={"zero_hard_failures","zero_critical_unsupported","complete_trace_ratio","complete_pooled_review","execution_custody","lineage"}
 if any(by[n]["status"]=="fail" for n in decisive):verdict="reject"
 elif any(g["status"]=="unknown" for g in gates):verdict="inconclusive"
 elif any(g["status"]=="fail" for g in gates):verdict="inconclusive"
 elif not computed["confirmation_cases"]:verdict="inconclusive"
 else:verdict="pass"
 result={"schema_version":RESULT_VERSION,"evaluation_id":context["evaluation_id"],"context_sha256":context["context_sha256"],"fact_set_sha256":context["fact_set_sha256"],"policy_sha256":context["policy_sha256"],"source_closure_sha256":context["source_closure_sha256"],"counts":{"planned":len(context["planned_cases"]),"confirmation":len(computed["confirmation_cases"]),"development":len(computed["development_cases"])},"statistics":computed["statistics"],"policy_gates":gates,"confirmation_cases":[_public_case(r) for r in computed["confirmation_cases"]],"development_cases":[_public_case(r) for r in computed["development_cases"]],"verdict":verdict,"reason_codes":sorted({r for g in gates if g["status"] in {"fail","unknown"} for r in g["reason_codes"]}),"claim_limits":["vector_only_no_scalar","not_live_provider_quality","not_financial_alpha","not_population_superiority"]};result["summary_sha256"]=digest(result);return result
def evaluate_fresh_now_evaluation(*,fresh_evaluation):
 data=_unwrap(fresh_evaluation);context,facts=_validate_context(data);_policy(data["policy"],context["policy_sha256"]);need(context["mode"]=="now_diagnostic" and all(f["subject"]=="NOW" for f in facts),"EIY_NOW_BOUNDARY");rows=[{"case_id":f["case_id"],"fact_sha256":f["fact_sha256"],"arms":{a:{"units":len(f["arms"][a]["canonical_units"]),"known_fields":sum(x["post_state"]!="unknown" for x in f["arms"][a]["required_fields"])} for a in ("B0","F")}} for f in facts];result={"schema_version":NOW_RESULT_VERSION,"evaluation_id":context["evaluation_id"],"context_sha256":context["context_sha256"],"fact_set_sha256":context["fact_set_sha256"],"policy_sha256":context["policy_sha256"],"cases":rows,"diagnostic_status":"observed","claim_limits":["now_only_no_confirmation","no_promotion","not_financial_alpha"]};result["summary_sha256"]=digest(result);return result
