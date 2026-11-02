"""Fault coverage of the boundary, separate from natural A/B semantic quality."""
from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from investment.research.contribution import PROPOSAL_SCHEMA,validate_proposal,calculate_scenario
from shared.research_sources.artifacts import SOURCE_STATE,read,save

BASE=SOURCE_STATE/'runtime/now-contribution-e2e-20261031/round-v1.0.1'


def run():
    record=json.loads((BASE/'record.json').read_text())
    seeds={}
    for cid in ['meter_refinement','forecast_q2']:
        result=read(record['cases'][cid]['A'])
        proposal=read(result['proposal_ref']);context=read(result['validation_context_ref'])
        validate_proposal(proposal,context)
        seeds[cid]=(proposal,context,result['proposal_ref'])
    rows=[]
    mutations=[('evidence_id','not-a-real-evidence-id'),('revision',999),('lifecycle_revision',999),
        ('source_sha256','0'*64),('entity','CRM'),('period','FY2099Q1'),('currency','EUR'),
        ('unit','USD billions'),('basis','unsupported accounting basis'),
        ('quote','This quotation is not present in the captured issuer source.')]
    p,c,ref=seeds['meter_refinement']
    for key,value in mutations:
        changed=deepcopy(p);changed['observed_facts'][0][key]=value
        rows.append(check('wrong_'+key,changed,c,ref))
    changed=deepcopy(p);changed['baseline_sha256']='0'*64
    rows.append(check('stale_baseline',changed,c,ref))
    changed=deepcopy(p);changed['observed_facts'].append(deepcopy(changed['observed_facts'][0]))
    rows.append(check('duplicate_identical_claim',changed,c,ref))
    p,c,ref=seeds['forecast_q2']
    for key,value in [('period','FY2025Q3'),('currency','EUR'),('unit','USD billions'),('point','NaN')]:
        changed=deepcopy(p);changed['forecast'][key]=value
        rows.append(check('forecast_'+key,changed,c,ref))
    scenario=calculate_scenario({'billed_units':'1000','annual_net_price_usd':'120',
        'incremental_margin':'0.25','cash_conversion':'0.8','years':1,'wacc':'0.2'})
    result={'faults':rows,'count':len(rows),'generic_shape_acceptances':sum(r['generic_schema_accepts'] for r in rows),
        'typed_boundary_rejections':sum(r['typed_boundary_rejects'] for r in rows),'scenario':scenario,
        'scope':'deterministic proposal mutation coverage, not natural agent error rate or the old full-company gate',
        'production_or_source_mutated':False}
    return save(BASE/'fault-coverage',result)


def check(name,proposal,context,seed_ref):
    shape=Draft202012Validator(PROPOSAL_SCHEMA).is_valid(proposal)
    try:validate_proposal(proposal,context);rejected=False;code=None
    except ValueError as exc:rejected=True;code=str(exc)
    return {'name':name,'generic_schema_accepts':shape,'typed_boundary_rejects':rejected,
            'code':code,'seed_proposal_ref':seed_ref}


if __name__=='__main__':print(json.dumps(run()))
