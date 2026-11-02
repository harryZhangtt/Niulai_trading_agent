"""Actual model -> structured contribution -> host validation, using existing phases."""
import json
import hashlib
import uuid

from shared.job_runtime.model import run_codex
from shared.research_sources.artifacts import ROOT, digest, read, require, save
from .contribution import PROPOSAL_SCHEMA, CANDIDATE_OBJECTIVE, BASELINE_OBJECTIVE, candidate_finalizer
from .execution import run


def model_callback(directory):
    config=json.loads((ROOT/'.job-runtime/config/runtime.json').read_text())
    profile=config['model_profiles']['default']
    root=ROOT/'.job-runtime/runs'/('now-contribution-'+uuid.uuid4().hex)
    receipts=[]
    def call(prompt,schema):
        remaining=float(json.loads(prompt).get('remaining_seconds',profile['timeout_seconds']))
        result=run_codex(dict(profile,timeout_seconds=min(remaining,profile['timeout_seconds'])),
            prompt,ROOT,root/str(len(receipts)),context={'response_schema':schema})
        receipts.append(save(directory,result))
        require(result['status']=='succeeded',result['code'])
        path=ROOT/result['receipt']['response_path']
        require(hashlib.sha256(path.read_bytes()).hexdigest()==result['receipt']['response_sha256'],
                'CONTRIBUTION_MODEL_RESPONSE')
        return json.loads(path.read_text())
    return call,receipts


def run_case(case,arm,directory):
    require(arm in {'A','B'},'CONTRIBUTION_ARM_INVALID')
    packet=read(case['packet_ref']);context=read(case['validation_context_ref'])
    objective=CANDIDATE_OBJECTIVE if arm=='A' else BASELINE_OBJECTIVE
    objective+=' Keep narrative concise (at most 900 words); do not omit material uncertainty.'
    config={'schema_version':1,'pipeline_id':'now_information_contribution','pipeline_version':'1.0.0',
        'budget':{'max_actions':0,'max_model_turns':2,'deadline_seconds':240},
        'phases':[{'id':'contribution','objective':objective,'mode':'agent','gate':'structured_output',
            'permitted_actions':[],'inputs':{'packet':{'$bind':'request.packet'}},'output_schema':PROPOSAL_SCHEMA}]}
    callback,receipts=model_callback(directory)
    if arm=='A':finalizer=candidate_finalizer(directory)
    else:
        def finalizer(run_context):
            # Competent generic phase baseline: structure is enforced in both arms.
            # This is not the old full-company finalizer, and claims no admission.
            proposal=run_context['phases']['contribution']['data']
            return save(directory,{'proposal_ref':save(directory,proposal),
                'completion_scope':'generic_structured_analysis_only','auto_commit_research':False})
    report=run(config,{'packet':packet,'validation_context':context},output_directory=directory,
        model_callback=callback,finalizer=finalizer)
    proposal=report.get('phases',{}).get('contribution',{}).get('data')
    return {'case_id':case['id'],'arm':arm,'pipeline_report_ref':report['report_ref'],
        'status':report['status'],'reason':report.get('reason'),
        'proposal_ref':save(directory,proposal) if proposal else None,'model_execution_refs':list(receipts),
        'baseline_ref':context['baseline_ref'],'packet_ref':case['packet_ref'],
        'validation_context_ref':case['validation_context_ref'],'final_ref':report.get('final_ref'),
        'completion_scope':'foreground_source_bound_development_not_full_research'}
