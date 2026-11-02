"""Regrade the full captured A/B after content-identity binding repair.

Original failed ledgers remain failed. No author/reviewer answer is regenerated.
This seals a new, unblinded grading-only round, not a new reasoning experiment.
"""
import hashlib
import json
from pathlib import Path
import time

from shared.research_sources.artifacts import ROOT,SOURCE_STATE,read,require,save,digest
from shared.job_runtime.service import atomic
from tuning.evals.evidence_runtime import contracts
from tuning.evals.now_contribution.grade import grade as semantic_grade,DIMENSIONS

BASE=SOURCE_STATE/'runtime/now-contribution-e2e-20261031/round-v1.0.1'
OUT=BASE/'captured-regrade-1.0.2'


def grade(case_id,inputs,expected,output):
    original=read(output['case_result_ref'])
    require(original['packet_ref']==inputs['packet_ref'],'NOW_REGRADE_PACKET')
    assessment=read(output['review_ref']);reviewed=read(output['actual_review_ref'])
    execution=read(reviewed['execution_ref'])
    require(execution['status']=='succeeded' and execution['receipt']['turn_completed'],'NOW_REGRADE_REVIEW_TRANSPORT')
    raw=read(reviewed['response_ref'],json_value=False)
    require(hashlib.sha256(raw).hexdigest()==execution['receipt']['response_sha256'],'NOW_REGRADE_REVIEW_HASH')
    require(assessment in json.loads(raw)['assessments'],'NOW_REGRADE_REVIEW_MEMBERSHIP')
    for ref in original['model_execution_refs']:
        model=read(ref);r=model['receipt'];require(model['status']=='succeeded','NOW_REGRADE_AUTHOR_TRANSPORT')
        require(hashlib.sha256((ROOT/r['response_path']).read_bytes()).hexdigest()==r['response_sha256'],'NOW_REGRADE_AUTHOR_HASH')
    return semantic_grade(case_id,inputs,expected,output)


def run():
    require(not (OUT/'record.json').exists(),'NOW_REGRADE_ALREADY_CLAIMED')
    study=json.loads((BASE/'record.json').read_text());require(study['stage']=='host_graded','NOW_REGRADE_NOT_READY')
    original=read(study['contract_ref']);cases=[];outputs={'A':[],'B':[]}
    for case in original['cases']:
        cid=case['id'];cases.append({'id':cid,'input':read(case['input_ref']),
            'expected':read(case['expected_ref']),'critical':case['critical']})
        first=read(study['review'][cid]['passes'][0]);second=read(study['review'][cid]['passes'][1])
        for label,arm in study['blind_mapping'][cid].items():
            review=next(a for a in first['response']['assessments'] if a['label']==label)
            reverse=next(a for a in second['response']['assessments'] if a['label']==label)
            value={'case_result_ref':study['cases'][cid][arm],'review_ref':save(OUT/'assessments',review),
                'actual_review_ref':study['review'][cid]['passes'][0],
                'reversed_review_ref':save(OUT/'assessments',reverse)}
            outputs[arm].append({'id':cid,'output_ref':save(OUT/'submissions',value)})
    spec={'id':'now_captured_quality_regrade','version':'1.0.2','split':'development','blindness':'unblinded',
          'cases':cases,'metrics':original['metrics'],'budget':{'model_turns':0,'provider_source_calls':0,'wall_seconds':60}}
    paths=['tuning/evals/now_contribution/grade.py','tuning/evals/now_contribution/protocol.json',
        'tuning/evals/evidence_runtime/contracts.py','shared/research_sources/artifacts.py',
        'shared/job_runtime/service.py',str(Path(__file__).relative_to(ROOT))]
    files={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    pins={name:{'files':files,'sha256':digest(files),'original_contract_ref':study['contract_ref'],
                 'captured_submissions':outputs[arm]} for arm,name in [('A','candidate'),('B','baseline')]}
    contract=contracts.seal(Path(save(OUT/'spec',spec)['path']),paths,pins,OUT/'ledger')
    claims={arm:contracts.begin(contract,OUT/'ledger','captured-'+arm,arm=name,budget=spec['budget'],fingerprint=pins[name])
            for arm,name in [('A','candidate'),('B','baseline')]}
    record={'contract_ref':contract,'claims':claims,'original_contract_ref':study['contract_ref'],
            'scope':'captured-only grading repair, all 16 answers and 16 reviews unchanged; no new model run',
            'stage':'claimed','results':{}}
    atomic(OUT/'record.json',record)
    for arm in ['A','B']:
        started=time.perf_counter()
        record['results'][arm]=contracts.finish(contract,OUT/'ledger','captured-'+arm,submissions=outputs[arm],
            usage={'model_turns':0,'provider_source_calls':0,'wall_seconds':time.perf_counter()-started},grade=grade)
        atomic(OUT/'record.json',record)
    record['stage']='host_graded';atomic(OUT/'record.json',record)
    return {arm:read(ref)['status'] for arm,ref in record['results'].items()}


if __name__=='__main__':print(json.dumps(run()))
