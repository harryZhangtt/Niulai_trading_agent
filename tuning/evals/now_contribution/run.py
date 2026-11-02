"""Preregister, execute and preserve one matched source-bound NOW development A/B."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import time

from investment.research.contribution_run import run_case
from investment.research.contribution import checkpoint_review,validate_proposal,PROPOSAL_SCHEMA
from jsonschema import Draft202012Validator
from shared.job_runtime.service import atomic
from shared.research_sources.artifacts import ROOT,SOURCE_STATE,digest,read,require,save
from tuning.evals.evidence_runtime import contracts
from .grade import grade,DIMENSIONS
from .review import review_pair

STUDY_ROOT=SOURCE_STATE/'runtime/now-contribution-e2e-20261031'
BASE=STUDY_ROOT/'round-v1.0.1'
MANIFEST={'path':str(STUDY_ROOT/'prepared-v1/inputs/d4c35aa76dcbcf394884174aef0bb0785b7519d0bf3ea814423c81dd3c7319c0.json'),
          'sha256':'d4c35aa76dcbcf394884174aef0bb0785b7519d0bf3ea814423c81dd3c7319c0'}


def setup():
    require(not (BASE/'record.json').exists(),'NOW_STUDY_ALREADY_REGISTERED')
    manifest=read(MANIFEST);protocol=json.loads((Path(__file__).parent/'protocol.json').read_text())
    paths=['AGENTS.md','investment/research/contribution.py','investment/research/contribution_run.py',
        'investment/research/execution.py','shared/research_sources/artifacts.py','shared/research_sources/store.py',
        'shared/research_sources/indexing.py','shared/actions/runtime.py','shared/actions/contracts.json',
        'shared/actions/releases.py','shared/job_runtime/model.py','shared/job_runtime/service.py',
        'shared/calculation/operators/valuation.py','tuning/evals/evidence_runtime/contracts.py',
        '.job-runtime/config/runtime.json']
    paths.extend(str(p.relative_to(ROOT)) for p in Path(__file__).parent.glob('*.py'))
    paths.append('tuning/evals/now_contribution/protocol.json')
    files={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sorted(set(paths))}
    basepin={'files':files,'sha256':digest(files)}
    pins={name:{**basepin,'workflow':workflow} for name,workflow in
        [('candidate','typed_contribution_and_host_gate'),('baseline','generic_structured_analysis')]}
    spec={'id':protocol['id'],'version':protocol['version'],'split':'development','blindness':'answers_withheld',
        'cases':[{'id':case['id'],'input':{'packet_ref':case['packet_ref']},
            'expected':{'reference_policy_sha256':hashlib.sha256((Path(__file__).parent/'protocol.json').read_bytes()).hexdigest(),
                'source_boundaries':'Source support, known-versus-new, meter/billing distinction, forecast type and historical cutoff.'},'critical':True} for case in manifest['cases']],
        'metrics':[*DIMENSIONS,'critical_error_count','unsupported_inferences','false_novelty',
            'unsupported_forecast_revision','supported_facts','total_facts','model_turns','tokens','cost'],
        'budget':{'model_turns':16,'wall_seconds':1920,'provider_source_calls':0}}
    spec_path=Path(save(BASE/'contract-input',spec)['path'])
    contract=contracts.seal(spec_path,paths,pins,BASE/'ledger')
    claims={}
    for arm,name in [('A','candidate'),('B','baseline')]:
        claims[arm]=contracts.begin(contract,BASE/'ledger','now-'+arm,arm=name,budget=spec['budget'],fingerprint=pins[name])
    rng=random.Random(20261031);order={};mapping={}
    for case in manifest['cases']:
        arms=['A','B'];rng.shuffle(arms);order[case['id']]=arms
        labels=['A','B'];rng.shuffle(labels);mapping[case['id']]=dict(zip(['X','Y'],labels))
    record={'id':protocol['id'],'version':protocol['version'],'manifest_ref':MANIFEST,'contract_ref':contract,
        'claims':claims,'pins':pins,'case_order':order,'blind_mapping':mapping,'cases':{},'review':{},
        'arm_seconds':{'A':0,'B':0},'stage':'sealed_before_model_outputs','email':{'status':'pending'}}
    atomic(BASE/'record.json',record)
    return {'contract_ref':contract,'cases':len(manifest['cases']),'stage':record['stage']}


def execute():
    record=json.loads((BASE/'record.json').read_text());contracts.validate(record['contract_ref'])
    manifest=read(record['manifest_ref']);require(not record['cases'],'NOW_NO_AUTOMATIC_REPLAY')
    for case in manifest['cases']:
        record['cases'][case['id']]={}
        for arm in record['case_order'][case['id']]:
            record.update(stage='running_models',current_case=case['id'],current_arm=arm)
            atomic(BASE/'record.json',record);t=time.perf_counter()
            result=run_case(case,arm,BASE/'arms'/arm/case['id'])
            record['arm_seconds'][arm]+=time.perf_counter()-t
            record['cases'][case['id']][arm]=save(BASE/'results',result)
            atomic(BASE/'record.json',record)
            print(json.dumps({'case':case['id'],'arm':arm,'status':result['status'],'reason':result['reason']}),flush=True)
    record['stage']='research_outputs_complete_pending_review';atomic(BASE/'record.json',record)


def reviews():
    record=json.loads((BASE/'record.json').read_text());manifest=read(record['manifest_ref'])
    protocol=json.loads((Path(__file__).parent/'protocol.json').read_text())
    require(record['stage']=='research_outputs_complete_pending_review','NOW_RESEARCH_NOT_COMPLETE')
    for case in manifest['cases']:
        cid=case['id'];proposals=[]
        for label,arm in record['blind_mapping'][cid].items():
            result=read(record['cases'][cid][arm]);require(result['proposal_ref'] is not None,'NOW_PROPOSAL_MISSING')
            proposal=read(result['proposal_ref']);ref=save(BASE/'blind/proposals',proposal)
            proposals.append({'label':label,'proposal_ref':ref,'proposal':proposal})
        pair={'research_packet':read(case['packet_ref']),'proposals':proposals,
              'rubric':protocol['review_dimensions_0_to_2'],'critical_failures':protocol['critical_failures']}
        record['review'][cid]={'passes':[]};record.update(stage='source_review',current_case=cid)
        atomic(BASE/'record.json',record)
        for reverse in [False,True]:
            presented={**pair,'proposals':list(reversed(proposals)) if reverse else proposals}
            ref=save(BASE/'blind/packets',presented)
            result=review_pair(ref,BASE/'blind/reviews'/cid/str(reverse))
            require(len(result['response']['assessments'])==2,'NOW_REVIEW_ROSTER')
            record['review'][cid]['passes'].append(save(BASE/'blind/reviews',result))
            atomic(BASE/'record.json',record)
            print(json.dumps({'review_case':cid,'reversed':reverse,'status':'completed'}),flush=True)
    record['stage']='reviews_complete_pending_host_grade';atomic(BASE/'record.json',record)


def finalize():
    record=json.loads((BASE/'record.json').read_text());contracts.validate(record['contract_ref'])
    require(record['stage']=='reviews_complete_pending_host_grade','NOW_REVIEW_INCOMPLETE')
    manifest=read(record['manifest_ref']);submissions={'A':[],'B':[]};turns=Counter();comparisons=[]
    for case in manifest['cases']:
        cid=case['id'];passes=[read(r) for r in record['review'][cid]['passes']]
        first,second=passes
        mapped_preferences=[record['blind_mapping'][cid].get(p['response']['pairwise_preference'],p['response']['pairwise_preference']) for p in passes]
        comparisons.append({'case_id':cid,'preferences':mapped_preferences,'order_consistent':len(set(mapped_preferences))==1})
        for label,arm in record['blind_mapping'][cid].items():
            result=read(record['cases'][cid][arm]);turns[arm]+=len(result['model_execution_refs'])
            reviews=[next(x for x in p['response']['assessments'] if x['label']==label) for p in passes]
            assessment=reviews[0];review_ref=save(BASE/'assessments',assessment)
            output=save(BASE/'submissions',{'case_result_ref':record['cases'][cid][arm],'review_ref':review_ref,
                                           'reversed_review_ref':save(BASE/'assessments',reviews[1])})
            submissions[arm].append({'id':cid,'output_ref':output})
            if arm=='A' and result['status']=='completed' and all(r['critical_error_count']==0 for r in reviews):
                final=read(result['final_ref'])
                try:
                    accepted=checkpoint_review(read(case['validation_context_ref']),result['proposal_ref'],final['mechanical_ref'],
                        review_ref,first['response_ref'],first['execution_ref'],result['model_execution_refs'][-1],BASE/'accepted'/cid)
                    record.setdefault('accepted',{})[cid]=accepted
                except ValueError as exc:record.setdefault('acceptance_gaps',{})[cid]=str(exc)
    record['host_results']={}
    for arm in ['A','B']:
        ref=contracts.finish(record['contract_ref'],BASE/'ledger','now-'+arm,submissions=submissions[arm],
            usage={'model_turns':turns[arm],'wall_seconds':record['arm_seconds'][arm],'provider_source_calls':0},grade=grade)
        record['host_results'][arm]=ref
    record.update(stage='host_graded',comparisons=comparisons)
    atomic(BASE/'record.json',record)
    return {'host_status':{a:read(r)['status'] for a,r in record['host_results'].items()},
            'accepted_information_snapshots':len(record.get('accepted',{})),'acceptance_gaps':record.get('acceptance_gaps',{})}


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['setup','execute','reviews','finalize'])
    args=p.parse_args();value=globals()[args.command]()
    if value is not None:print(json.dumps(value))


if __name__=='__main__':main()
