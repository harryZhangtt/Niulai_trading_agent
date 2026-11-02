"""Arm-blind source review using an actual fresh model invocation, no outcomes."""
import hashlib
import json
from pathlib import Path
import uuid

from investment.research.contribution import obj,array,TEXT,ID
from shared.job_runtime.model import run_codex
from shared.research_sources.artifacts import ROOT,read,require,save

SCORES=('fact_support','baseline_novelty','mechanism_calibration','unproved_links','counterevidence','forecast_discipline')
COUNT={'type':'integer','minimum':0,'maximum':100}
REF=obj({'path':{'type':'string'},'sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'}})
ASSESSMENT=obj({'case_id':ID,'label':{'enum':['X','Y']},'proposal_ref':REF,
    'reviewer_role':{'const':'arm_label_blinded_source_review'},
    'source_checks':array(obj({'fact_index':{'type':'integer','minimum':0,'maximum':11},
        'claim':TEXT,'evidence_id':ID,'finding':TEXT,'support':{'enum':['supported','qualified','unsupported']}}),24),
    'scores':obj({k:({'anyOf':[{'type':'integer','minimum':0,'maximum':2},{'type':'null'}]}
                    if k=='forecast_discipline' else {'type':'integer','minimum':0,'maximum':2}) for k in SCORES}),
    'critical_error_count':COUNT,'critical_errors':array(TEXT),
    'unsupported_inferences':COUNT,'false_novelty':COUNT,'unsupported_forecast_revision':COUNT,
    'supported_facts':COUNT,'total_facts':COUNT,'missed_material_contributions':COUNT,'rationale':TEXT})
SCHEMA=obj({'assessments':array(ASSESSMENT,2),
    'pairwise_preference':{'enum':['X','Y','tie','inconclusive']},'comparison_reason':TEXT})


def review_pair(packet_ref,directory):
    packet=read(packet_ref)
    prompt={'objective':'Independently review the two anonymous proposals against the frozen baseline and supplied original-source excerpts. Evidence before scores. Do not reward eloquence, source count, optimism, conservatism or a trade change.',
        'instructions':['Check each material fact and economic link; a correct quote does not prove the proposed inference.',
            'Distinguish known/refined/new mechanism, a meter versus paid units/net pricing/revenue, launch versus adoption, ACV versus recognized revenue, guidance versus consensus, and company-wide effects versus product causality.',
            'A legitimate conditional hypothesis can be useful without a numeric forecast revision. No-change is not automatically correct; evaluate its rationale.',
            'Historical-vintage and missing-body limitations matter. The review has no later outcomes. Do not supply them from memory.',
            'Scores are ordinal development observations. Give concrete source checks and missing/rival links. Do not invent a priced-in conclusion.',
            'Assess source support before scoring. Compare in the given order and return mapped X/Y labels. The host repeats in a separate fresh invocation with reversed order. Agreement is not calibrated confidence.',
            'Count unsupported inferences, false novelty and unjustified forecast revisions separately. Missing applicable insight also matters; abstention must not game quality.',
            'Return one source_checks entry per observed fact using its zero-based fact_index and identical evidence_id. Multiple distinct claims can legitimately cite the same evidence ID. Put mechanism criticism in the rationale and counts. total_facts equals the proposal fact-list length; supported_facts counts fully supported fact checks. An empty fact list permits an empty check list.'],
        'rubric':packet['rubric'],'critical_failures':packet['critical_failures'],
        'research_packet':packet['research_packet'],'anonymous_proposals':packet['proposals']}
    profile=json.loads((ROOT/'.job-runtime/config/runtime.json').read_text())['model_profiles']['default']
    result=run_codex(profile,json.dumps(prompt),ROOT,
        ROOT/'.job-runtime/runs'/('now-review-'+uuid.uuid4().hex),context={'response_schema':SCHEMA})
    execution_ref=save(directory,result)
    require(result['status']=='succeeded',result['code'])
    path=ROOT/result['receipt']['response_path'];raw=path.read_bytes()
    require(hashlib.sha256(raw).hexdigest()==result['receipt']['response_sha256'],'NOW_REVIEW_RESPONSE_HASH')
    response_ref=save(directory,raw)
    return {'execution_ref':execution_ref,'response_ref':response_ref,'response':json.loads(raw)}
