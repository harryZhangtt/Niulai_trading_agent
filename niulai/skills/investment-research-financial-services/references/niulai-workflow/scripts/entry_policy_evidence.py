#!/usr/bin/env python3
"""Opt-in company-bound entry evidence admission; not a forecast-truth oracle."""
import argparse
import hashlib
import json
import math
from pathlib import Path

VERSION = '2026-10-23-entry-policy-2'

def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ' required')
    return value

def _number(value, label, lo=None, hi=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + ' must be finite numeric')
    if lo is not None and value < lo or hi is not None and value > hi:
        raise ValueError(label + ' outside bounds')
    return value

def _hashed(a):
    p=Path(_text(a.get('path'), 'artifact path'))
    if not p.is_absolute() or not p.is_file():
        raise ValueError('Entry artifact missing or nonabsolute')
    raw=p.read_bytes()
    if not raw or hashlib.sha256(raw).hexdigest()!=a.get('sha256'):
        raise ValueError('Entry artifact empty or stale hash')
    return raw

def validate(rec):
    """Legacy records opt out by omission; new entry runs must pin this policy."""
    declared=rec.get('policy_versions', {}).get('entry_policy')
    if declared is None or rec.get('scope') not in ('company_full', 'fund_full', 'crypto_full'):
        return {'status':'not_applicable_or_legacy'}
    if declared != VERSION:
        raise ValueError('Unsupported entry policy version')
    block=rec.get('entry_policy_evidence')
    if not isinstance(block, dict) or block.get('version')!=VERSION:
        raise ValueError('Required company entry_policy_evidence missing or stale')
    if rec.get('status')!='complete':
        if block.get('status') not in ('pending','limited','compared'):
            raise ValueError('Entry evidence progress status required')
        return {'status':'incomplete_not_certified'}
    expected_basis='crypto_bound' if rec.get('scope')=='crypto_full' else 'company_bound'
    if block.get('status')!='compared' or block.get('basis')!=expected_basis:
        raise ValueError('Completed entry review requires company-bound comparison, not synthetic or limited')
    basis=block.get('probability_basis')
    if basis not in ('judgment','calibrated'):
        raise ValueError('Completed entry ranking requires explicit probability model; unknown remains incomplete')
    if basis=='calibrated' and not block.get('calibration_artifact_ids'):
        raise ValueError('Calibrated probability needs calibration artifacts')
    _text(block.get('limitations'), 'Model and probability limitations')
    _text(block.get('information_cutoff'), 'Information cutoff')
    horizon=_number(block.get('common_horizon_years'), 'common horizon', 0)
    budget=_number(block.get('initial_budget'), 'initial budget', 0)
    if horizon==0 or budget==0:raise ValueError('Positive horizon and budget required')
    arts={a['id']:a for a in rec.get('artifacts', [])}
    if len(arts)!=len(rec.get('artifacts', [])):raise ValueError('Duplicate entry artifact ID')
    baseline=block.get('baseline_artifact_ids')
    evidence=block.get('source_evidence_artifact_ids')
    if not isinstance(baseline,list) or not baseline or not isinstance(evidence,list) or not evidence:
        raise ValueError('Company baseline and source evidence artifacts required')
    ids=baseline+evidence+[block.get(k) for k in ('input_artifact_id','output_artifact_id','review_artifact_id')]+block.get('calibration_artifact_ids',[])
    if any(not isinstance(i,str) or i not in arts for i in ids):raise ValueError('Entry artifact reference unresolved')
    if len({block[k] for k in ('input_artifact_id','output_artifact_id','review_artifact_id')})!=3:
        raise ValueError('Entry input/output/review must be distinct artifacts')
    for i in set(ids):_hashed(arts[i])
    inp=json.loads(_hashed(arts[block['input_artifact_id']]))
    out=json.loads(_hashed(arts[block['output_artifact_id']]))
    review=json.loads(_hashed(arts[block['review_artifact_id']]))
    ticker=rec['subject']['ticker']
    for label,doc in [('input',inp),('output',out)]:
        if doc.get('ticker')!=ticker or doc.get('basis')!=expected_basis:
            raise ValueError('Entry '+label+' not bound to actual company')
        if doc.get('probability_basis')!=basis or doc.get('common_horizon_years')!=horizon or doc.get('initial_budget')!=budget:
            raise ValueError('Entry comparison probability/budget/horizon mismatch')
    pinned={i:arts[i]['sha256'] for i in baseline+evidence}
    if inp.get('baseline_artifact_hashes')!=pinned:
        raise ValueError('Entry input baseline/evidence hash binding mismatch')
    if out.get('input_sha256')!=arts[block['input_artifact_id']]['sha256']:
        raise ValueError('Entry output not bound to current input')
    policies=out.get('policies',{})
    if not isinstance(policies,dict) or not {'now','staged','wait'}<=set(policies):
        raise ValueError('Numeric now/staged/wait comparison required')
    for name in ('now','staged','wait'):
        values=policies[name]
        _number(values.get('expected_terminal_wealth'),name+' expected wealth',0)
        _number(values.get('loss_probability'),name+' loss probability',0,1)
        _number(values.get('nonfill_probability'),name+' nonfill probability',0,1)
    decision=block.get('decision',{})
    if decision.get('change') not in ('changed','unchanged'):
        raise ValueError('Explicit changed/unchanged entry decision required')
    if decision.get('selected_policy') not in ('now','staged','wait'):
        raise ValueError('Explicit entry direction required')
    _text(decision.get('rationale'),'Numeric comparison decision rationale')
    if out.get('decision')!=decision:raise ValueError('Decision differs from computed/reviewed output')
    if not isinstance(out.get('sensitivity'),list) or not out['sensitivity']:
        raise ValueError('Decision sensitivity required')
    author=rec.get('audit',{}).get('author_id')
    reviewer=_text(review.get('reviewer_id'),'Entry independent reviewer')
    if not author or reviewer.split('/')[-1]==author.split('/')[-1]:
        raise ValueError('Entry reviewer equals author or author missing')
    if review.get('status')!=('approved_crypto_entry' if rec.get('scope')=='crypto_full' else 'approved_company_entry') or review.get('ticker')!=ticker:
        raise ValueError('Company entry review not approved')
    reviewed=review.get('artifact_hashes',{})
    for i in baseline+evidence+[block['input_artifact_id'],block['output_artifact_id']]:
        if reviewed.get(i)!=arts[i]['sha256']:raise ValueError('Entry review stale or missing artifact hash')
    count=review.get('numerical_check_count')
    if isinstance(count,bool) or not isinstance(count,int) or count<1:
        raise ValueError('Entry review has no numerical checks')
    return {'status':('crypto_entry_evidence_verified' if rec.get('scope')=='crypto_full' else 'company_entry_evidence_verified'),'ticker':ticker,'policy_version':VERSION,
            'forecast_accuracy_certified':False,'checked_artifacts':len(set(ids))}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--record',required=True);a=p.parse_args()
    print(json.dumps(validate(json.loads(Path(a.record).read_text()))))
if __name__=='__main__':main()
