"""One isolated future allocation: actual NOW agent, scripts, review and snapshot.

Uses the existing Engine/launchd pattern. No production job or active MCP changes.
This is scoped captured-source replay, not fresh-provider acceptance or alpha.
"""
from datetime import datetime,timedelta,timezone
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from investment.research.contribution_run import run_case
from investment.research.contribution import checkpoint_review,validate_proposal,calculate_scenario
from shared.job_runtime.engine import Engine
from shared.job_runtime.service import atomic
from shared.research_sources.artifacts import ROOT,SOURCE_STATE,digest,read,require,save,SourceError
from shared.research_sources.store import Store
from tuning.evals.now_contribution.review import review_pair

STUDY=SOURCE_STATE/'runtime/now-contribution-e2e-20261031/round-v1.0.1'


def fingerprint():
    study=json.loads((STUDY/'record.json').read_text())
    files={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in study['pins']['candidate']['files']}
    for p in [Path(__file__),ROOT/'shared/job_runtime/engine.py']:
        files[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
    profile=json.loads((ROOT/'.job-runtime/config/runtime.json').read_text())['model_profiles']['default']
    toolchain={'python_sha256':hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest(),
               'codex_sha256':hashlib.sha256(Path(profile['codex_bin']).resolve().read_bytes()).hexdigest(),
               'profile_sha256':digest(profile)}
    return {'files':files,'toolchain':toolchain,'sha256':digest([files,toolchain])}


def setup(change):
    require(change.replace('-','').isalnum() and len(change)<65,'NOW_ACCEPTANCE_ID')
    base=ROOT/'.job-runtime/acceptance'/change
    require(not base.exists(),'NOW_ACCEPTANCE_EXISTS');base.mkdir(parents=True,mode=0o700)
    study=json.loads((STUDY/'record.json').read_text())
    require(study['stage']=='host_graded','NOW_STUDY_NOT_GRADED')
    due=datetime.now(timezone.utc)+timedelta(seconds=45)
    label='com.local.trading-agent.now-handoff.'+change
    record={'change_id':change,'candidate':fingerprint(),'case_id':'margin_counterevidence',
        'inputs':{'manifest_ref':study['manifest_ref'],
                  'baseline_case_result_ref':study['cases']['margin_counterevidence']['B']},
        'label':label,'execution':{'status':'pending'},'email':{'status':'pending'},
        'criteria':{'max_seconds':420,'max_start_lateness_seconds':180,
            'scope':'captured-source NOW contribution -> host checks -> fresh independent model review -> snapshot; no forecast/trade promotion'},
        'job':{'id':change,'enabled':True,'replay_safe':False,
            'schedule':{'kind':'once','at':due.isoformat(),'grace_seconds':180}}}
    atomic(base/'record.json',record)
    spec={'Label':label,'ProgramArguments':[str(ROOT/'.research-sources/.venv/bin/python'),'-B','-m',
        'tuning.evals.now_contribution_acceptance','tick','--record',str(base/'record.json')],
        'WorkingDirectory':str(ROOT),'EnvironmentVariables':{'PYTHONPATH':str(ROOT),'PYTHONDONTWRITEBYTECODE':'1',
            'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','HOME':str(Path.home()),'TMPDIR':str(SOURCE_STATE/'tmp')},
        'StartInterval':15,'RunAtLoad':False,'ProcessType':'Background','Umask':0o077,
        'StandardOutPath':str(base/'stdout.log'),'StandardErrorPath':str(base/'stderr.log')}
    plist=base/'once.plist';plist.write_bytes(plistlib.dumps(spec));plist.chmod(0o600)
    result=subprocess.run(['/bin/launchctl','bootstrap','gui/%d'%os.getuid(),str(plist)],capture_output=True,timeout=15)
    require(result.returncode==0,'NOW_ACCEPTANCE_BOOTSTRAP')
    return {'record':str(base/'record.json'),'due':due.isoformat(),'label':label}


def verify(execution,scheduled_at,inputs=None):
    result=read(execution['case_result_ref']);require(result['status']=='completed','NOW_ACCEPTANCE_INCOMPLETE')
    if inputs is not None:
        manifest=read(inputs['manifest_ref'])
        case=next(c for c in manifest['cases'] if c['id']==result['case_id'])
        require(result['case_id']=='margin_counterevidence' and result['packet_ref']==case['packet_ref'] and
                result['validation_context_ref']==case['validation_context_ref'],'NOW_ACCEPTANCE_INPUT_BINDING')
    reviewer=read(execution['review_ref']);receipt=read(reviewer['execution_ref'])
    executions=[read(ref) for ref in result['model_execution_refs']]+[receipt]
    threads=[]
    for model in executions:
        r=model['receipt'];require(model['status']=='succeeded' and r['turn_completed'] and r['exit_code']==0,'NOW_ACCEPTANCE_TRANSPORT')
        require(datetime.fromisoformat(r['started_at'])>=datetime.fromisoformat(scheduled_at),'NOW_ACCEPTANCE_OLD_EXECUTION')
        require(hashlib.sha256((ROOT/r['response_path']).read_bytes()).hexdigest()==r['response_sha256'],'NOW_ACCEPTANCE_RESPONSE_HASH')
        require(hashlib.sha256((ROOT/r['run_directory']/'events.jsonl').read_bytes()).hexdigest()==r['event_stream_sha256'],'NOW_ACCEPTANCE_EVENT_HASH')
        threads.append(r['thread_id'])
    require(len(set(threads))==len(threads),'NOW_ACCEPTANCE_THREADS')
    final=read(execution['accepted_ref']);context=read(result['validation_context_ref'])
    store=Store(context['store_directory']);snapshot=store.read_snapshot(final['snapshot']['snapshot_id'])
    for b in snapshot['manifest']['bindings']:
        row=store.read(b['observation_id']);require(row['revision']==b['revision'] and row['lifecycle_revision']==b['lifecycle_revision'],'NOW_ACCEPTANCE_DEPENDENCY')
    require(execution['fault_code']=='CONTRIBUTION_EVIDENCE_UNKNOWN_OR_DUPLICATE','NOW_ACCEPTANCE_FAULT_NOT_REJECTED')
    require(execution['scenario']['finite_horizon_fcff_pv_usd']=='20000','NOW_ACCEPTANCE_ARITHMETIC')
    return {'verified':True,'threads':threads,'snapshot_id':final['snapshot']['snapshot_id'],
        'scope':'scheduled actual agent/host/reviewer handoff on captured source; no fresh data-provider or alpha claim'}


def tick(path):
    path=Path(path);base=path.parent
    fd=os.open(base/'tick.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        record=json.loads(path.read_text())
        if record['execution']['status']!='pending':
            subprocess.run(['/bin/launchctl','bootout','gui/%d/%s'%(os.getuid(),record['label'])],capture_output=True,timeout=10);return
        if datetime.now(timezone.utc)>datetime.fromisoformat(record['job']['schedule']['at'])+timedelta(seconds=600):
            record['execution']={'status':'unverified','code':'NOW_ACCEPTANCE_WINDOW_EXPIRED'}
            atomic(path,record);return
        def dispatch(job,context):
            evidence={}
            try:
                require(fingerprint()==record['candidate'],'NOW_ACCEPTANCE_SOURCE_CHANGED')
                manifest=read(record['inputs']['manifest_ref'])
                case=next(c for c in manifest['cases'] if c['id']==record['case_id'])
                out=SOURCE_STATE/'runtime/now-contribution-e2e-20261031/scheduled'/record['change_id']/context['attempt_id']
                result=run_case(case,'A',out/'author');result_ref=save(out,result)
                evidence['case_result_ref']=result_ref
                require(result['status']=='completed','NOW_ACCEPTANCE_PROPOSAL')
                proposal=read(result['proposal_ref']);baseline=read(read(record['inputs']['baseline_case_result_ref'])['proposal_ref'])
                require(bool(proposal['observed_facts']),'NOW_ACCEPTANCE_SOURCE_FACT_REQUIRED')
                protocol=json.loads((ROOT/'tuning/evals/now_contribution/protocol.json').read_text())
                pair={'research_packet':read(case['packet_ref']),'rubric':protocol['review_dimensions_0_to_2'],
                    'critical_failures':protocol['critical_failures'],'proposals':[
                        {'label':'X','proposal':proposal,'proposal_ref':save(out/'blind',proposal)},
                        {'label':'Y','proposal':baseline,'proposal_ref':save(out/'blind',baseline)}]}
                reviewed=review_pair(save(out/'blind',pair),out/'reviewer');reviewed_ref=save(out,reviewed)
                evidence['review_ref']=reviewed_ref
                judgment=next(x for x in reviewed['response']['assessments'] if x['label']=='X')
                require(judgment['critical_error_count']==0 and judgment['unsupported_inferences']==0 and
                    judgment['unsupported_forecast_revision']==0 and judgment['false_novelty']==0,'NOW_ACCEPTANCE_REVIEW_NOT_SUPPORTED')
                checked=read(result['final_ref'])
                accepted=checkpoint_review(read(case['validation_context_ref']),result['proposal_ref'],checked['mechanical_ref'],
                    save(out,judgment),reviewed['response_ref'],reviewed['execution_ref'],result['model_execution_refs'][-1],out/'accepted')
                bad=json.loads(json.dumps(proposal));bad['observed_facts'][0]['evidence_id']='invented-runtime-evidence'
                try:validate_proposal(bad,read(case['validation_context_ref']));fault=None
                except SourceError as exc:fault=str(exc)
                scenario=calculate_scenario({'billed_units':'1000','annual_net_price_usd':'120','incremental_margin':'0.25',
                    'cash_conversion':'0.8','years':1,'wacc':'0.2'})
                execution={'case_result_ref':result_ref,'review_ref':reviewed_ref,'accepted_ref':accepted,
                    'fault_code':fault,'scenario':scenario,'context':context}
                proof=verify(execution,context['scheduled_at'],record['inputs'])
                require(fingerprint()==record['candidate'],'NOW_ACCEPTANCE_SOURCE_CHANGED')
                require((datetime.now(timezone.utc)-datetime.fromisoformat(context['scheduled_at'])).total_seconds()<=420,'NOW_ACCEPTANCE_TIMEOUT')
                record['execution']={'status':'passed',**execution,'postcondition':proof,'verified_at':datetime.now(timezone.utc).isoformat()}
                atomic(path,record);return {'status':'succeeded','code':'NOW_HANDOFF_VERIFIED','receipt':record['execution']}
            except Exception as exc:
                record['execution']={'status':'failed','code':str(exc) if isinstance(exc,SourceError) else type(exc).__name__,
                    'context':context,**evidence,'recorded_at':datetime.now(timezone.utc).isoformat()}
                atomic(path,record);return {'status':'failed','code':'NOW_HANDOFF_FAILED','receipt':record['execution']}
        engine=Engine(base/'engine',[record['job']],{'max_attempts':1,'backoff_seconds':30,'max_backoff_seconds':30},dispatch,workspace_root=ROOT,max_workers=1)
        print(json.dumps(engine.tick(datetime.now(timezone.utc))))
    finally:os.close(fd)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['setup','tick']);p.add_argument('--change');p.add_argument('--record')
    args=p.parse_args();result=setup(args.change) if args.command=='setup' else tick(args.record)
    if result is not None:print(json.dumps(result))
