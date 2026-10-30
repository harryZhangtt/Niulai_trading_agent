#!/usr/bin/env python3
"""Crypto-specific evidence bindings and supply arithmetic; not forecast certification."""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

VERSION = '2026-10-23-crypto-1'
TOPICS = ('identity_rights', 'baseline_thesis_delta', 'user_jobs_substitution',
          'protocol_delivery_security', 'layered_value_capture', 'supply_staking',
          'regional_adoption_regulation', 'rates_liquidity', 'valuation_reverse',
          'technical_market_structure', 'portfolio_execution')

def text(v, label):
    if not isinstance(v, str) or not v.strip(): raise ValueError(label+' required')
    return v

def number(v, label):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(label+' must be finite numeric')
    return v

def read(a):
    p=Path(text(a.get('path'), 'artifact path'))
    if not p.is_absolute() or not p.is_file(): raise ValueError('Crypto artifact missing/nonabsolute')
    raw=p.read_bytes()
    if not raw or hashlib.sha256(raw).hexdigest()!=a.get('sha256'): raise ValueError('Crypto artifact stale/empty')
    return raw

def validate(rec):
    if rec.get('scope')!='crypto_full': return {'status':'not_applicable'}
    if rec.get('subject',{}).get('security_type')!='cryptoasset': raise ValueError('Crypto instrument classification required')
    if rec.get('policy_versions',{}).get('crypto')!=VERSION: raise ValueError('Crypto policy version missing/stale')
    b=rec.get('crypto_evidence',{})
    if b.get('version')!=VERSION: raise ValueError('Crypto evidence block required')
    if rec.get('status')!='complete':
        if b.get('status') not in ('pending','limited','reviewed'): raise ValueError('Crypto progress status required')
        return {'status':'incomplete_not_certified'}
    if b.get('status')!='reviewed': raise ValueError('Crypto review incomplete')
    arts={a['id']:a for a in rec.get('artifacts',[])}
    if len(arts)!=len(rec.get('artifacts',[])):raise ValueError('Duplicate crypto artifact ID')
    aid,rid=b.get('assessment_artifact_id'),b.get('review_artifact_id')
    if aid not in arts or rid not in arts or aid==rid: raise ValueError('Distinct crypto assessment/review required')
    assessment=json.loads(read(arts[aid])); review=json.loads(read(arts[rid]))
    ticker=rec['subject']['ticker']
    if assessment.get('ticker')!=ticker or assessment.get('version')!=VERSION:raise ValueError('Crypto assessment identity/version mismatch')
    source_ids={s['id'] for s in rec.get('sources',[])}
    if len(source_ids)!=len(rec.get('sources',[])):raise ValueError('Duplicate crypto source ID')
    pinned={aid:arts[aid]['sha256']}
    observed=0
    for name in TOPICS:
        topic=assessment.get('topics',{}).get(name,{})
        status=topic.get('status')
        if status not in ('evidenced','limited','not_applicable'):raise ValueError(name+': status required')
        text(topic.get('finding'),name+' finding')
        refs=topic.get('artifact_refs')
        if not isinstance(refs,list) or not refs or any(i not in arts for i in refs):raise ValueError(name+': unresolved artifacts')
        for i in refs:read(arts[i]);pinned[i]=arts[i]['sha256']
        sids=topic.get('source_ids',[])
        if not isinstance(sids,list) or any(s not in source_ids for s in sids):raise ValueError(name+': unresolved sources')
        if status=='evidenced':
            if not sids:raise ValueError(name+': evidence requires sources')
            observed+=1
        else:
            text(topic.get('limitations'),name+' limitations')
            text(topic.get('decision_impact'),name+' decision impact')
    if observed<1:raise ValueError('Crypto assessment has no evidenced topic')
    for key in ('fee_beneficiaries','issuance_treatment','burn_treatment','monetary_premium_overlap'):
        text(assessment.get('accounting',{}).get(key),'Crypto accounting '+key)
    comparators=assessment.get('comparators',[])
    if not comparators:raise ValueError('Functional and economic comparators required')
    if assessment.get('stablecoin_or_l2_exposure') is not False and assessment.get('stablecoin_or_l2_exposure') is not True:
        raise ValueError('Stablecoin/L2 exposure classification required')
    names={x.get('id') for x in comparators}
    kinds=set()
    for c in comparators:
        text(c.get('id'),'Comparator id');text(c.get('job'),'Comparator job')
        text(c.get('capture'),'Comparator value capture');text(c.get('tradeoff'),'Comparator tradeoff')
        if c.get('kind') not in ('crypto','equity','noncrypto'):raise ValueError('Comparator kind invalid')
        kinds.add(c['kind'])
        sids=c.get('source_ids',[])
        if not sids or any(i not in source_ids for i in sids):raise ValueError('Comparator source binding missing')
    if not {'crypto','noncrypto'}<=kinds:raise ValueError('Crypto and noncrypto substitutes required')
    if assessment['stablecoin_or_l2_exposure'] and not {'COIN','CRCL'}<=names:
        raise ValueError('Stablecoin/L2 capture requires COIN and CRCL comparison')
    supply=assessment.get('supply_reconciliation',{})
    if supply.get('status')=='reconciled':
        for k in ('opening','issuance','burn','other_net_change','closing','tolerance'):number(supply.get(k),'supply '+k)
        if min(supply['opening'],supply['issuance'],supply['burn'],supply['closing'],supply['tolerance'])<0:raise ValueError('Negative gross supply amounts/tolerance')
        text(supply.get('unit'),'Supply unit');text(supply.get('period'),'Supply period')
        text(supply.get('tolerance_basis'),'Supply tolerance precision basis')
        # At most one part per million of stock; rounded dashboards with lower
        # precision require an explicit unavailable/limited reconciliation instead.
        cap=max(1e-8,max(supply['opening'],supply['closing'])*1e-6)
        if supply['tolerance']>cap:raise ValueError('Supply tolerance exceeds precision cap')
        if abs(supply['opening']+supply['issuance']-supply['burn']+supply['other_net_change']-supply['closing'])>supply['tolerance']:
            raise ValueError('Supply roll-forward fails')
        sids=supply.get('source_ids',[])
        if not sids or any(i not in source_ids for i in sids):raise ValueError('Supply sources unresolved')
    elif supply.get('status')=='unavailable':
        text(supply.get('reason'),'Unavailable supply reason');text(supply.get('decision_impact'),'Supply decision impact')
    else:raise ValueError('Supply reconciliation status required')
    author=text(rec.get('audit',{}).get('author_id'),'Author identity')
    reviewer=text(review.get('reviewer_id'),'Crypto reviewer identity')
    if author.split('/')[-1]==reviewer.split('/')[-1]:raise ValueError('Crypto reviewer equals author')
    if review.get('ticker')!=ticker or review.get('status')!='approved_crypto_evidence':raise ValueError('Crypto independent review not approved')
    for i,h in pinned.items():
        if review.get('artifact_hashes',{}).get(i)!=h:raise ValueError('Crypto review missing/stale artifact '+i)
    for k in ('source_review','accounting_review','substitution_review'):
        if review.get(k)!='complete':raise ValueError('Crypto '+k+' incomplete')
    return {'status':'crypto_evidence_verified','ticker':ticker,'checked_artifacts':len(pinned),
            'policy_version':VERSION,'forecast_accuracy_certified':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--record',required=True);a=p.parse_args()
    print(json.dumps(validate(json.loads(Path(a.record).read_text()))))
if __name__=='__main__':main()
