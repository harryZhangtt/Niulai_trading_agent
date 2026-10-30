"""Deterministic research routing; supplied evidence is not independently verified."""
import argparse,json,math
POLICY="2026-10-21-triage-2"
def evidenced(x, *keys):
    refs=x.get('evidence_refs', {})
    return isinstance(refs,dict) and all(isinstance(refs.get(k),list) and refs[k] and all(isinstance(v,str) and v.strip() for v in refs[k]) for k in keys)

def envelope_test(x):
    """Transparent optimistic wealth screen; not an EV or an upper-bound proof."""
    e=x.get('optimistic_envelope',{})
    if not isinstance(e,dict) or not evidenced(x,'envelope','capital_claims','independent_review'):return None
    keys=('price','terminal_wealth_per_share','years','required_annual_return')
    if any(type(e.get(k)) not in (int,float) or not math.isfinite(e[k]) for k in keys):return None
    p,w,t,h=(e[k] for k in keys)
    if p<=0 or w<0 or t<=0 or h<=-1:return None
    if e.get('option_value_considered') is not True or e.get('claims_reconciled') is not True:return None
    annual=(w/p)**(1/t)-1
    return {'optimistic_annual_return':annual,'hurdle':h,'below_hurdle':annual<h,'reopen_price':w/(1+h)**t}
def route(x):
    def out(mode,reason):return {"ticker":x.get("ticker"),"route":mode,"reason":reason,"policy":POLICY,"research_complete":False,"investment_recommendation":False}
    if x.get("user_hold") is True:return out("held","User requested scope/budget redesign; preserve incomplete work")
    if x.get("held_position") is True and x.get("material_risk_event") is True:return out("priority_risk_review","Existing-position risk cannot be screened away by price")
    if x.get("identity_verified") is not True:return out("data_repair","Verify security identity/corporate actions first")
    sr=x.get('scope_evidence_refs')
    if x.get("in_scope") is False and isinstance(sr,list) and sr and all(isinstance(r,str) and r.strip() for r in sr):return out("out_of_scope","Verified universe exclusion; not a business-quality verdict")
    if x.get("in_scope") is not True or x.get("quote_valid") is not True:return out("data_repair","Scope or price unverified")
    if x.get("explicit_full_request") is True:return out("full_review","Explicit deep research request; reuse verified stages")
    if x.get("baseline_valid") is not True or x.get("delta_scan_complete") is not True:return out("bounded_probe","Missing valid baseline or covered evidence interval")
    if x.get("regime_changed") is True:return out("full_review","Existing model structure no longer applicable")
    if x.get("material_new_evidence") is not False:return out("delta_review","Review material or uncertain evidence before reuse")
    if not evidenced(x,'baseline','delta_scan','quote','identity'):return out("bounded_probe","Missing provenance for baseline, covered source interval, quote or identity; cannot infer no change")
    if x.get("leveraged_fund") is True and (x.get("path_inputs_changed") is not False or not evidenced(x,'fund_path_inputs')):return out("fund_path_refresh","Refresh applicable daily-reset paths and costs")
    test=envelope_test(x)
    if x.get("optimistic_envelope_reviewed") is True and test and test['below_hurdle']:
        result=out("defer_price","Reviewed plausible optimistic envelope insufficient; reopen on price/event change")
        result['calculation']=test
        return result
    if x.get("decision_boundary_crossed") is True:return out("delta_review","Changed action boundary needs targeted verification")
    if x.get("price_or_time_changed") is True:return out("reprice","Only price/time changed; execute existing model")
    if x.get("price_or_time_changed") is False:return out("reuse","Verified unchanged baseline and evidence interval")
    return out("bounded_probe","Insufficient evidence to infer no change")
def main():
    p=argparse.ArgumentParser();p.add_argument("--input",required=True);p.add_argument("--output",required=True);a=p.parse_args()
    with open(a.input) as f:d=json.load(f)
    result={"policy":POLICY,"results":[route(x) for x in d["candidates"]],"savings_measured":False}
    with open(a.output,"w") as f:json.dump(result,f,indent=2)
if __name__=="__main__":main()
