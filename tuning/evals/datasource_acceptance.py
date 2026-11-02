"""One future live datasource batch/query acceptance; no production jobs.

Reuses the existing Engine, model/auth owner and temporary once-label pattern.
The supervising agent independently verifies browser rendering and owner email.
"""
import argparse
from datetime import datetime,timedelta,timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from urllib.request import urlopen

from investment.research.datasource_query import run_query,FACETS
from investment.research.execution import proposal_schema
from investment.research.information_labels import read_sidecar,best_effort_observe,annotate_source
from shared.research_sources.batch import run_batch
from shared.job_runtime.engine import Engine
from shared.job_runtime.service import atomic
from shared.research_sources.artifacts import ROOT,SOURCE_STATE,INVESTMENT_STATE,digest,read,require,save,SourceError

STUDY=SOURCE_STATE/'runtime/datasource-observability-20261101'
SOURCE_MANIFEST={'path':str(SOURCE_STATE/'runtime/now-contribution-e2e-20261031/prepared-v1/inputs/d4c35aa76dcbcf394884174aef0bb0785b7519d0bf3ea814423c81dd3c7319c0.json'),'sha256':'d4c35aa76dcbcf394884174aef0bb0785b7519d0bf3ea814423c81dd3c7319c0'}
ROSTER={'path':str(SOURCE_STATE/'runtime/information-fetch-next-20261101/inputs/8e5f4e4cbfef8a7f5d061fe8d7c43d32a2e0642fe40503c63feceec06a5948e0.json'),'sha256':'8e5f4e4cbfef8a7f5d061fe8d7c43d32a2e0642fe40503c63feceec06a5948e0'}
VERSION='datasource-ordered-query-acceptance-2.0.0'


def candidate_paths():
    # Explicit closure for official_document batch -> ordered read/catalog -> API.
    # HostWeb, native acquisition grading and skill-TUI are separate paths.
    paths=['AGENTS.md','package.json','pnpm-lock.yaml','pnpm-workspace.yaml','.npmrc',
        '.job-runtime/config/runtime.json','investment/research/examples/datasource-query.pipeline.json',
        'investment/research/skills/information-catalog/SKILL.md','tuning/evals/datasource_acceptance.py',
        'investment/research/information-labels.schema.json','investment/research/information-taxonomy.json',
        'shared/research_sources/catalog.json','shared/research_sources/requirements.txt',
        'shared/research_sources/examples/batch-now.json','shared/actions/contracts.json',
        'niulai/skills/investment-research-financial-services/references/niulai-workflow/scripts/evidence_crosscheck.py']
    paths += ['investment/research/'+name+'.py' for name in ['__init__','datasource_query','execution','contribution_run',
        'contribution','information_catalog','information_labels','datasource','document_preview','acquisition_projection']]
    paths += ['shared/research_sources/'+name+'.py' for name in ['__init__','artifacts','fetch','batch','cache','store','temporal','indexing']]
    paths += ['shared/job_runtime/'+name+'.py' for name in ['__init__','engine','service','business','model']]
    paths += ['shared/calculation/'+name for name in ['__init__.py','operators/__init__.py','operators/valuation.py']]
    # The action release itself deliberately includes every packaged action file.
    for pattern in ['shared/actions/*.py','ui/datasource/*.mjs','ui/datasource/*.json','ui/datasource/src/*']:
        paths.extend(str(p.relative_to(ROOT)) for p in ROOT.glob(pattern) if p.is_file())
    return sorted(set(paths))


def fingerprint():
    files={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in candidate_paths()}
    node=os.environ.get('DATASOURCE_ACCEPTANCE_NODE') or shutil.which('node')
    require(node is not None,'DATASOURCE_ACCEPTANCE_NODE_MISSING')
    return {'files':files,'sha256':digest(files),'python_sha256':hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest(),
        'node_binary':str(Path(node).resolve()),'node_sha256':hashlib.sha256(Path(node).resolve().read_bytes()).hexdigest()}


def catalog_transport_schema():
    config=json.loads((ROOT/'investment/research/examples/datasource-query.pipeline.json').read_bytes())
    schema=proposal_schema(config['phases'][1],{})
    def inspect(value):
        if isinstance(value,dict):
            require('uniqueItems' not in value,'DATASOURCE_ACCEPTANCE_TRANSPORT_SCHEMA_UNSUPPORTED')
            for item in value.values():inspect(item)
        elif isinstance(value,list):
            for item in value:inspect(item)
    inspect(schema)
    return schema


def execution_tree(directory):
    files=sorted(path for path in directory.rglob('*') if path.is_file())
    require(len(files)<=256 and not directory.is_symlink() and all(not path.is_symlink() and path.stat().st_size<=8*1024*1024 for path in files),
        'DATASOURCE_ACCEPTANCE_ARCHIVE_BOUND')
    return digest({str(path.relative_to(directory)):hashlib.sha256(path.read_bytes()).hexdigest() for path in files})


def api(query='health'):
    path='/api/datasource/health' if query=='health' else '/api/datasource?subject=NOW&refresh=1'
    with urlopen('http://127.0.0.1:7270'+path,timeout=12) as response:
        raw=response.read(2*1024*1024+1)
    require(len(raw)<=2*1024*1024,'DATASOURCE_ACCEPTANCE_API_SIZE')
    return json.loads(raw)


def probes(directory):
    result=[];markers=[]
    for name in ['future','unknown','reconstruction']:
        marker='SYNTHETIC_FUTURE_ORACLE_'+name.upper()+'_NOT_WORKER_INPUT'
        raw=save(directory,marker.encode(),suffix='txt');markers.append(marker)
        source={'schema_version':1,'provider':'official_document','source_url':'https://example.invalid/synthetic-'+name,
            'upstream_id':'synthetic-acceptance-'+name,'source_version':'synthetic-1',
            'raw':raw,'text':raw,'available_at':'2025-01-01T00:00:00Z',
            'retrieved_at':None if name=='unknown' else '2099-01-01T00:00:00Z',
            'access_level':'document','truth_or_independence_certified':False,
            'metadata':{'title':'Synthetic '+name+' leakage probe','synthetic':True},
            'limitations':['Synthetic acceptance fault, not an acquired external source.']}
        ref=save(directory,source)
        result.append({'source_ref':ref,'qualified_reconstruction':{'published_at':'2025-01-01T00:00:00Z',
            'rationale':'Synthetic post-cutoff capture cannot become strict worker evidence.'}} if name=='reconstruction' else ref)
    return result,markers


def register(result,probe_pins,batches=()):
    # Index document labels for discovery; the authoritative query already saved.
    # This optional side effect cannot rewrite or invalidate its business result.
    for ref in result['source_refs']:
        best_effort_observe(ref,observer=lambda value: annotate_source(value))
    directory=INVESTMENT_STATE/'datasource';directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(directory/'registry.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        path=directory/'registry.json';require(not path.is_symlink(),'DATASOURCE_REGISTRY_UNSAFE')
        value=json.loads(path.read_text()) if path.exists() else {'schema_version':1}
        for key in ['source_refs','report_refs','temporal_diagnostic_refs','batch_refs']:value.setdefault(key,[])
        for batch in batches:
            entry={'batch_ref':batch['report_ref'],'subject':'NOW'}
            if entry not in value['batch_refs']:value['batch_refs'].append(entry)
        for ref in [*result['source_refs'],result['original_capture_ref'],*[p.get('source_ref',p) for p in probe_pins]]:
            entry={'source_ref':ref,'subject':'NOW'}
            if entry not in value['source_refs']:value['source_refs'].append(entry)
        entry={'report_ref':result['pipeline_report_ref'],'subject':'NOW','query':'NOW source catalog and temporal guard',
            'source_sha256s':[r['sha256'] for r in result['source_refs']],
            'temporal_diagnostic_ref':result['temporal_diagnostic_ref']}
        if entry not in value['report_refs']:value['report_refs'].append(entry)
        if result['temporal_diagnostic_ref'] not in value['temporal_diagnostic_refs']:
            value['temporal_diagnostic_refs'].append(result['temporal_diagnostic_ref'])
        require(all(len(value[k])<=32 for k in ['source_refs','report_refs','temporal_diagnostic_refs','batch_refs']), 'DATASOURCE_REGISTRY_BUDGET')
        atomic(path,value)
    finally:os.close(fd)


def verify(result,scheduled_at,markers):
    require(result['status']=='completed','DATASOURCE_ACCEPTANCE_QUERY_BLOCKED')
    report=read(result['pipeline_report_ref']);final=read(result['final_ref']);catalog=read(result['catalog_ref'])
    require(report['run_id']==result['execution_id']==final['execution_id'],'DATASOURCE_ACCEPTANCE_RUN_BINDING')
    require(report['counts']['actions']==1 and report['counts']['model_turns']==1,'DATASOURCE_ACCEPTANCE_COUNTS')
    require(len(report['action_records'])==1,'DATASOURCE_ACCEPTANCE_ACTION')
    require({q['facet'] for q in catalog['proposal']['questions']}>=set(FACETS),'DATASOURCE_ACCEPTANCE_CATALOG')
    require(len(catalog['proposal']['questions'])<=6 and final['observation_refs'],'DATASOURCE_ACCEPTANCE_OUTPUT')
    threads=[]
    for ref in result['model_execution_refs']:
        model=read(ref);receipt=model['receipt']
        require(model['status']=='succeeded' and receipt['turn_completed'] and receipt['exit_code']==0,'DATASOURCE_ACCEPTANCE_MODEL')
        require(datetime.fromisoformat(receipt['started_at'])>=datetime.fromisoformat(scheduled_at),'DATASOURCE_ACCEPTANCE_OLD_MODEL')
        require(hashlib.sha256((ROOT/receipt['response_path']).read_bytes()).hexdigest()==receipt['response_sha256'],'DATASOURCE_ACCEPTANCE_MODEL_HASH')
        run=ROOT/receipt['run_directory'];prompt=(run/'prompt.txt').read_text()
        require(digest(json.loads((run/'response-schema.json').read_bytes()))==digest(catalog_transport_schema()),
            'DATASOURCE_ACCEPTANCE_TRANSPORT_SCHEMA_MISMATCH')
        require(not any(m in prompt for m in markers),'DATASOURCE_ACCEPTANCE_PROMPT_LEAK')
        require(hashlib.sha256((run/'events.jsonl').read_bytes()).hexdigest()==receipt['event_stream_sha256'],'DATASOURCE_ACCEPTANCE_EVENTS')
        threads.append(receipt['thread_id'])
    require(len(threads)==1,'DATASOURCE_ACCEPTANCE_MODEL_ROSTER')
    diagnostic=read(result['temporal_diagnostic_ref'])
    hidden=[s for s in diagnostic['sources'] if s['status'] in ['blocked','unknown','qualified_reconstruction']]
    require(len(hidden)>=3 and all(not s['worker_visible'] for s in hidden),'DATASOURCE_ACCEPTANCE_FUTURE_GATE')
    require(result['label_refs'] and all(read_sidecar(ref) for ref in result['label_refs']),'DATASOURCE_ACCEPTANCE_LABELS')
    def broken(_):raise RuntimeError('SYNTHETIC_OPTIONAL_OBSERVER_FAILURE')
    warning=best_effort_observe(result['report_ref'],observer=broken)
    require(warning['code']=='OPTIONAL_OBSERVABILITY_FAILED' and read(result['report_ref'])['status']=='completed',
            'DATASOURCE_ACCEPTANCE_OPTIONAL_LOG_BLOCKED')
    data=api('overview');row=next((r for r in data['runs'] if r['execution_id']==result['execution_id']),None)
    require(row is not None and row['temporal']['status']=='guarded','DATASOURCE_ACCEPTANCE_UI_PROJECTION')
    require(row['phases'] and row['script_versions'],'DATASOURCE_ACCEPTANCE_SCRIPT_PROJECTION')
    require(row.get('output') and row['output']['catalog_sha256']==result['catalog_ref']['sha256']
        and len(row['output']['questions'])>=5 and row['output']['observations'], 'DATASOURCE_ACCEPTANCE_CATALOG_PROJECTION')
    return {'verified':True,'threads':threads,'execution_id':result['execution_id'],
        'hidden_probe_count':len(hidden),'catalog_questions':len(catalog['proposal']['questions']),
        'labels':len(result['label_refs']),'source_records':data['pagination']['total_sources'],
        'pipeline_runs':data['pagination']['total_runs'],'api_snapshot_id':data['snapshot_id'],
        'scope':'live NOW batch acquisition/cache/replay, actual configured model/read/labels, before-exposure gate and localhost projection; no broad historical AB claim'}


def setup(change):
    require(change.replace('-','').isalnum() and len(change)<65,'DATASOURCE_ACCEPTANCE_ID')
    base=ROOT/'.job-runtime/acceptance'/change;require(not base.exists(),'DATASOURCE_ACCEPTANCE_EXISTS')
    base.mkdir(parents=True,mode=0o700);health=api();require(health.get('app')=='trading-agent-datasource' and health['status']=='ready','DATASOURCE_ACCEPTANCE_SERVER')
    due=datetime.now(timezone.utc)+timedelta(seconds=45);label='com.local.trading-agent.datasource.'+change
    config=json.loads((ROOT/'shared/research_sources/examples/batch-now.json').read_bytes())
    record={'change_id':change,'version':VERSION,'candidate':fingerprint(),'roster_ref':ROSTER,
        'acquisition_config_ref':save(STUDY/'scheduled-inputs'/change,config),'transport_schema_sha256':digest(catalog_transport_schema()),
        'label':label,'execution':{'status':'pending'},'email':{'status':'pending'},'server_identity':health,
        'criteria':{'max_seconds':420,'max_start_lateness_seconds':180,'one_attempt':True},
        'job':{'id':change,'enabled':True,'replay_safe':False,'schedule':{'kind':'once','at':due.isoformat(),'grace_seconds':180}}}
    atomic(base/'record.json',record)
    spec={'Label':label,'ProgramArguments':[str(ROOT/'.research-sources/.venv/bin/python'),'-B','-m',
        'tuning.evals.datasource_acceptance','tick','--record',str(base/'record.json')],'WorkingDirectory':str(ROOT),
        'EnvironmentVariables':{'PYTHONPATH':str(ROOT),'PYTHONDONTWRITEBYTECODE':'1','PATH':'/usr/bin:/bin:/usr/sbin:/sbin',
            'HOME':str(Path.home()),'DATASOURCE_ACCEPTANCE_NODE':str(Path(shutil.which('node')).resolve()),'TMPDIR':str(SOURCE_STATE/'tmp')},'StartInterval':15,'RunAtLoad':False,'ProcessType':'Background',
        'Umask':0o077,'StandardOutPath':str(base/'stdout.log'),'StandardErrorPath':str(base/'stderr.log')}
    path=base/'once.plist';path.write_bytes(plistlib.dumps(spec));path.chmod(0o600)
    r=subprocess.run(['/bin/launchctl','bootstrap','gui/%d'%os.getuid(),str(path)],capture_output=True,timeout=15)
    require(r.returncode==0,'DATASOURCE_ACCEPTANCE_BOOTSTRAP');return {'record':str(base/'record.json'),'due':due.isoformat()}


def tick(path):
    path=Path(path);base=path.parent;fd=os.open(base/'tick.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        record=json.loads(path.read_text())
        if record['execution']['status']!='pending':
            subprocess.run(['/bin/launchctl','bootout','gui/%d/%s'%(os.getuid(),record['label'])],capture_output=True,timeout=10);return
        if datetime.now(timezone.utc)>datetime.fromisoformat(record['job']['schedule']['at'])+timedelta(seconds=600):
            record['execution']={'status':'unverified','code':'DATASOURCE_ACCEPTANCE_WINDOW_EXPIRED'};atomic(path,record);return
        def dispatch(job,context):
            evidence={}
            try:
                require(fingerprint()==record['candidate'],'DATASOURCE_ACCEPTANCE_SOURCE_CHANGED')
                require(api()==record['server_identity'],'DATASOURCE_ACCEPTANCE_SERVER_CHANGED')
                out=STUDY/'scheduled'/record['change_id']/context['attempt_id'];pins,markers=probes(out/'probes')
                config=read(record['acquisition_config_ref'])
                cold=run_batch(config,cache_directory=out/'acquisition-cache')
                warm=run_batch(config,cache_directory=out/'acquisition-cache')
                archive=SOURCE_STATE/'runtime/batches'/cold['execution_id'];before=execution_tree(archive)
                replay=run_batch(config,execution_id=cold['execution_id'],cache_directory=out/'acquisition-cache')
                after=execution_tree(archive)
                evidence['batch_result_refs']=[save(out,cold),save(out,warm)]
                evidence['batch_replay_ref']=save(out,{'result':replay,'before_tree_sha256':before,'after_tree_sha256':after})
                require(cold['status']==warm['status']=='completed','DATASOURCE_ACCEPTANCE_BATCH_FAILED')
                require(cold['counts']['provider_calls']==1 and warm['counts']['provider_calls']==0 and
                        warm['counts']['cache_hits']==1 and cold['source_refs']==warm['source_refs'],
                        'DATASOURCE_ACCEPTANCE_CACHE')
                require(replay['report_ref']==cold['report_ref'] and replay['idempotent_replay'] and before==after,
                        'DATASOURCE_ACCEPTANCE_BATCH_REPLAY')
                # Live retrieval completes before freezing the model's input cutoff.
                # A scheduler due time is not the availability time of a new capture.
                query_cutoff=datetime.now(timezone.utc).isoformat()
                captured=read(cold['source_refs'][0])
                require(all(datetime.fromisoformat(captured[key])<=datetime.fromisoformat(query_cutoff)
                    for key in ['retrieved_at','available_at']), 'DATASOURCE_ACCEPTANCE_CUTOFF_PRECEDES_ACQUISITION')
                manifest=save(out,{'source_refs':{'S01':cold['source_refs'][0]}})
                result=run_query(source_manifest_ref=manifest,roster_ref=record['roster_ref'],
                    cutoff=query_cutoff,output_directory=out/'query',probe_pins=pins)
                evidence['query_result_ref']=save(out,result);evidence['markers']=markers
                require(result['status']=='completed','DATASOURCE_ACCEPTANCE_QUERY_BLOCKED')
                register(result,pins,[cold,warm]);proof=verify(result,context['scheduled_at'],markers)
                data=api('overview');batch_rows={b['execution_id']:b for b in data.get('batches',[])}
                require(all(b['execution_id'] in batch_rows for b in [cold,warm]),'DATASOURCE_ACCEPTANCE_BATCH_PROJECTION')
                proof['batch_execution_ids']=[cold['execution_id'],warm['execution_id']]
                proof['cold_provider_dispatches']=1;proof['warm_provider_dispatches']=0;proof['warm_cache_hits']=1
                proof['query_cutoff']=query_cutoff
                require(fingerprint()==record['candidate'],'DATASOURCE_ACCEPTANCE_SOURCE_CHANGED')
                require((datetime.now(timezone.utc)-datetime.fromisoformat(context['scheduled_at'])).total_seconds()<=420,'DATASOURCE_ACCEPTANCE_TIMEOUT')
                record['execution']={'status':'passed',**evidence,'context':context,'postcondition':proof,
                    'verified_at':datetime.now(timezone.utc).isoformat()};atomic(path,record)
                return {'status':'succeeded','code':'DATASOURCE_ACCEPTANCE_VERIFIED','receipt':record['execution']}
            except Exception as exc:
                record['execution']={'status':'failed',**evidence,'context':context,
                    'code':str(exc) if isinstance(exc,SourceError) else type(exc).__name__};atomic(path,record)
                return {'status':'failed','code':'DATASOURCE_ACCEPTANCE_FAILED','receipt':record['execution']}
        engine=Engine(base/'engine',[record['job']],{'max_attempts':1,'backoff_seconds':30,'max_backoff_seconds':30},dispatch,workspace_root=ROOT,max_workers=1)
        print(json.dumps(engine.tick(datetime.now(timezone.utc))))
    finally:os.close(fd)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['setup','tick']);p.add_argument('--change');p.add_argument('--record')
    args=p.parse_args();value=setup(args.change) if args.command=='setup' else tick(args.record)
    if value is not None:print(json.dumps(value))
