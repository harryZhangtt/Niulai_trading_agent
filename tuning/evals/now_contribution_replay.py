"""Sealed mechanical repair replay: every captured answer, no regenerated model.

This is conformance, not another quality A/B or an independent reasoning sample.
The one unit-mismatched baseline answer must remain rejected after quote repair.
"""
import hashlib
import json
from pathlib import Path
import time

from investment.research.contribution import VERSION,validate_proposal
from shared.research_sources.artifacts import ROOT,SOURCE_STATE,read,require,save,digest
from shared.job_runtime.service import atomic
from tuning.evals.evidence_runtime import contracts
from tuning.evals.now_contribution_faults import run as fault_run

BASE=SOURCE_STATE/'runtime/now-contribution-e2e-20261031/round-v1.0.1'
OUT=BASE/'mechanical-replay-1.0.2'


def inspect(inputs):
    if inputs['kind']=='fault_matrix':
        ref=fault_run();data=read(ref)
        return {'fault_ref':ref,'valid':data['count']==16 and
                data['generic_shape_acceptances']==16 and data['typed_boundary_rejections']==16,
                'facts':0,'rejected_faults':data['typed_boundary_rejections']}
    result=read(inputs['case_result_ref'])
    try:
        receipt=validate_proposal(read(result['proposal_ref']),read(result['validation_context_ref']))
        checked=save(OUT/'receipts',receipt);code=None
    except ValueError as exc:checked=None;code=str(exc)
    return {'proposal_ref':result['proposal_ref'],'valid':code is None,'code':code,'receipt_ref':checked,
            'facts':len(read(result['proposal_ref'])['observed_facts']),'rejected_faults':0}


def grade(case_id,inputs,expected,output):
    observed=inspect(inputs)
    require(observed==output,'NOW_REPLAY_OUTPUT_BINDING')
    return {'passed':output['valid']==expected['valid'],
            'metrics':{'accepted':int(output['valid']),'facts':output['facts'],
                       'rejected_faults':output['rejected_faults']},
            'reasons':[] if output['valid']==expected['valid'] else ['NOW_REPLAY_UNEXPECTED_ADMISSION']}


def run():
    require(VERSION=='contribution-handoff-1.0.2','NOW_REPLAY_VERSION')
    require(not (OUT/'record.json').exists(),'NOW_REPLAY_ALREADY_CLAIMED')
    study=json.loads((BASE/'record.json').read_text())
    require(study['stage']=='host_graded','NOW_REPLAY_STUDY_NOT_GRADED')
    before_ref=json.loads((BASE/'old-boundary-ref.json').read_text());before=read(before_ref)
    require(len(before['rows'])==16,'NOW_REPLAY_COMPLETE_ROSTER')
    cases=[]
    for row in before['rows']:
        mismatch=row['case_id']=='usage_entitlements' and row['arm']=='B'
        require(row['failure_code']==('CONTRIBUTION_DIMENSIONS' if mismatch else
            'CONTRIBUTION_QUOTE_NOT_IN_SOURCE' if row['case_id']=='margin_counterevidence' and row['arm']=='A' else None),
            'NOW_REPLAY_BASELINE_CHANGED')
        cases.append({'id':row['case_id']+'-'+row['arm'],'critical':True,
            'input':{'kind':'captured_proposal','case_result_ref':row['case_result_ref']},
            'expected':{'valid':not mismatch,'reason':'Assist usage units must not become an entitlement-tier unit' if mismatch
                else 'Valid source-bound captured handoff; whitespace-only table quotation variance is permitted'}})
    cases.append({'id':'fault_matrix','critical':True,'input':{'kind':'fault_matrix'},
                  'expected':{'valid':True,'reason':'All 16 malformed handoffs remain rejected'}})
    spec={'id':'now_captured_handoff_repair','version':'1.0.2','split':'development','blindness':'unblinded',
          'cases':cases,'metrics':['accepted','facts','rejected_faults'],
          'budget':{'model_turns':0,'provider_source_calls':0,'wall_seconds':60}}
    paths=['investment/research/contribution.py','shared/research_sources/artifacts.py',
        'shared/research_sources/store.py','shared/calculation/operators/valuation.py',
        'shared/job_runtime/service.py',
        'tuning/evals/evidence_runtime/contracts.py','tuning/evals/now_contribution_faults.py',
        str(Path(__file__).relative_to(ROOT))]
    files={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    pin={'version':VERSION,'files':files,'sha256':digest(files)}
    contract=contracts.seal(Path(save(OUT/'spec',spec)['path']),paths,{'candidate':pin},OUT/'ledger')
    claim=contracts.begin(contract,OUT/'ledger','captured-output-replay',arm='candidate',budget=spec['budget'],fingerprint=pin)
    record={'contract_ref':contract,'claim_ref':claim,'before_ref':before_ref,'stage':'claimed'}
    atomic(OUT/'record.json',record);started=time.perf_counter();submissions=[]
    for case in cases:
        submissions.append({'id':case['id'],'output_ref':save(OUT/'outputs',inspect(case['input']))})
    result=contracts.finish(contract,OUT/'ledger','captured-output-replay',submissions=submissions,
        usage={'model_turns':0,'provider_source_calls':0,'wall_seconds':time.perf_counter()-started},grade=grade)
    record.update(stage='host_graded',result_ref=result,scope='mechanical captured-output conformance; no new quality-model run')
    atomic(OUT/'record.json',record)
    return {'result_ref':result,'status':read(result)['status']}


if __name__=='__main__':print(json.dumps(run()))
