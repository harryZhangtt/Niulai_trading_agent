"""Temporary future-slot native-slash acceptance using the existing Engine.

Allocation/verification stays here; PTY/model mechanics stay in job_runtime and
the closed browser capability stays in skill_bridge. No production allocation
or recurring executor is replaced. Model assertions cannot satisfy this gate.
"""
import argparse
from datetime import datetime,timedelta,timezone
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import sqlite3
import subprocess
import uuid

from shared.job_runtime.engine import Engine
from shared.job_runtime.service import atomic
from shared.job_runtime.skill_tui import run,sha,history_completion
from shared.research_sources.artifacts import ROOT,read,require,digest
from .skill_bridge import Host,CLIENT,HOST
from .egolite import _execute
from .policy import load_config

HERE=ROOT/'.job-runtime/acceptance/egolite-slash-20261102'
CONFIG=ROOT/'.job-runtime/config/runtime.json'
PROFILE='research-source-acceptance'


def fingerprint():
    paths=list((ROOT/'shared/web_access').glob('*.py'))+list((ROOT/'shared/web_access').glob('*.js'))
    paths += [ROOT/'shared/job_runtime'/name for name in ('skill_tui.py','model.py','business.py','engine.py','service.py','config.py')]
    paths += [ROOT/'shared/research_sources/artifacts.py',ROOT/'.research-sources/web-access/config/egolite-installed.json']
    paths += [ROOT/name for name in ('AGENTS.md','mentor/AGENTS.md','mentor/ROUTING.md','.codex/config.toml')]
    files={str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)}
    return {'files':files,'sha256':digest(files)}


def profile(client_root):
    source=json.loads(CONFIG.read_text())['model_profiles'][PROFILE]
    p={k:source[k] for k in ('codex_bin','model','effort','auth_home','max_output_bytes','approval_mode')}
    return {**p,'timeout_seconds':180,'writable_roots':[str(client_root.relative_to(ROOT))]}


def prompt(operation):
    python=ROOT/'.research-sources/.venv/bin/python'
    helper=load_config(ROOT/'.research-sources/web-access/config/egolite-installed.json')['egolite']['executable']
    return f'''RUNTIME_SKILL_PROBE {operation}. Apply the slash-selected ego-browser skill for this scheduled public-only test.
First execute {shlex.quote(helper)} skill and read the complete matching guide, including its end marker. Request enough output to read it fully. Do this in a separate tool call before the client command.
Then execute exactly once: cd {shlex.quote(str(ROOT))} && {shlex.quote(str(python))} -B -m shared.web_access.skill_client --operation {operation}
The closed client submits one fixed public vendor-guide read to the host-owned EgoLite capability. The host owns URL, version pins, budgets and authoritative receipts. Do not run nodejs inside the model sandbox, use another browser, substitute curl/search, batch the guide and client into one call, modify source/configuration, trust hooks, import accounts, choose another operation ID, send email, or retry. If blocked, stop. End with status and result reference. The supervisor independently verifies the actual native slash, skill injection, completed turn, source and cleanup; your final text does not establish success.'''


def history_checks(receipt,home,skill,text,operation):
    path=Path(receipt['native_history_path'])
    binding=history_completion(path,home,skill,text,receipt['thread_id'])
    require(binding is not None,'SLASH_NATIVE_COMPLETION_MISSING')
    guide=False;client=[]
    for line in path.read_text().splitlines():
        p=json.loads(line).get('payload',{})
        if p.get('type')=='custom_tool_call_output' and '[ego-browser:skill] end of guide v2.2.0' in str(p.get('output','')):guide=True
        if p.get('type')=='custom_tool_call' and 'shared.web_access.skill_client' in p.get('input','') and operation in p.get('input',''):
            client.append(guide)
    require(guide and client==[True],'SLASH_GUIDE_AND_CLIENT_ORDER_INVALID')
    return binding


def postconditions(host,transport,context,record,text):
    r=transport['receipt'];require(transport['status']=='succeeded' and r['turn_completed'] is True
        and r['skill_selected'] is True and r['native_skill_attachment_verified'] is True
        and r['exit_code']==0 and r['process_cleanup_verified'] is True,'SLASH_TRANSPORT_NOT_VERIFIED')
    native=history_checks(r,record['auth_home'],record['skill'],text,host.operation)
    started=datetime.fromtimestamp(native['native_started_at'],timezone.utc)
    lateness=(started-datetime.fromisoformat(context['scheduled_at'])).total_seconds()
    require(0<=lateness<=record['criteria']['max_start_lateness_seconds'],'SLASH_START_LATE')
    v=host.verify();require(v['verified'],'SLASH_SOURCE_NOT_VERIFIED')
    o=read(v['observation_ref'])
    require(datetime.fromisoformat(o['started_at'])>=started,'SLASH_STALE_BROWSER_EVIDENCE')
    query='console.log(JSON.stringify({operation_id:'+json.dumps(host.operation)+',remaining:(await listTaskSpaces()).filter(x=>x.name==='+json.dumps(v['task_space'])+').length}))'
    raw=_execute([host.config['egolite']['executable'],'nodejs'],query,8,16384,host.out)
    cleanup=json.loads(raw.decode().strip())
    require(cleanup=={'operation_id':host.operation,'remaining':0},'SLASH_BROWSER_CLEANUP_UNVERIFIED')
    return {**v,'verified':True,'native':native,'native_start_lateness_seconds':lateness,
            'independent_task_absent':True,'context':context}


def stage(name='scheduled-v1'):
    require(re.fullmatch('[a-z0-9-]{1,40}',name),'SLASH_ACCEPTANCE_NAME_INVALID')
    base=HERE/name;require(not base.exists(),'SLASH_ACCEPTANCE_EXISTS');base.mkdir(mode=0o700)
    central=json.loads(CONFIG.read_text());source=central['model_profiles'][PROFILE]
    skillpath=Path.home()/'.agents/skills/ego-browser/SKILL.md'
    skill={'name':'ego-browser','path':str(skillpath),'sha256':sha(skillpath)}
    created=datetime.now(timezone.utc);jobs=[];operations={}
    for number,delay in enumerate((60,180,300),1):
        operation=str(uuid.uuid4());host=Host(operation)
        id='egolite.native-slash.20261102.'+name+'.'+str(number)
        jobs.append({'id':id,'enabled':True,'replay_safe':True,
            '_resource_key':str(Path(source['auth_home']).resolve()),
            'schedule':{'kind':'once','at':(created+timedelta(seconds=delay)).isoformat(),'grace_seconds':120}})
        operations[id]=operation
    record={'schema_version':1,'change_id':'egolite-native-slash-20261102-'+name,'created_at':created.isoformat(),
        'criteria':{'required_future_runs':3,'max_start_lateness_seconds':60,'completion_timeout_seconds':180,
            'provider_path':'literal native /skills selector -> ego-browser injection -> matching guide -> closed host EgoLite read',
            'critical':'Every run must pass; no CLI-only or idle-text substitution; unknowns held, no automatic browser replay'},
        'candidate':fingerprint(),'cli_sha256':sha(source['codex_bin']),'skill':skill,'auth_home':source['auth_home'],
        'central_profile_sha256':digest(source),'retry':central['retry'],'jobs':jobs,'operations':operations,
        'attempts':[],'execution_status':'pending','email_status':'pending',
        'label':'com.local.trading-agent.egolite-native-slash-20261102-'+name}
    atomic(base/'record.json',record)
    env={'PYTHONPATH':str(ROOT),'PYTHONDONTWRITEBYTECODE':'1','PATH':'/usr/bin:/bin:/usr/sbin:/sbin',
         'HOME':str(Path.home()),'TMPDIR':str(ROOT/'.job-runtime/tmp')}
    spec={'Label':record['label'],'ProgramArguments':[str(ROOT/'.research-sources/.venv/bin/python'),'-B','-m',
        'shared.web_access.skill_acceptance','tick','--record',str(base/'record.json')],'WorkingDirectory':str(ROOT),'EnvironmentVariables':env,
        'StartInterval':10,'RunAtLoad':False,'ProcessType':'Background','Umask':0o077,
        'StandardOutPath':str(base/'stdout.log'),'StandardErrorPath':str(base/'stderr.log')}
    path=base/'once.plist';path.write_bytes(plistlib.dumps(spec));path.chmod(0o600)
    return {'record':str(base/'record.json'),'plist':str(path),'due':[j['schedule']['at'] for j in jobs],
            'registered':False,'label':record['label']}


def tick(path):
    path=Path(path).resolve();require(path.is_relative_to(HERE.resolve()) and path.name=='record.json','SLASH_RECORD_PATH_INVALID')
    base=path.parent
    fd=os.open(base/'tick.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        record=json.loads(path.read_text())
        if record['execution_status']!='pending':
            subprocess.run(['/bin/launchctl','bootout','gui/'+str(os.getuid())+'/'+record['label']],capture_output=True,timeout=10)
            return
        def dispatch(job,context):
            if record['execution_status']!='pending':return {'status':'failed','code':'SLASH_CRITICAL_FAILURE_ABORT'}
            attempt={'context':context,'job_id':job['id']}
            try:
                require(fingerprint()==record['candidate'],'SLASH_CANDIDATE_CHANGED')
                current=json.loads(CONFIG.read_text())['model_profiles'][PROFILE]
                require(digest(current)==record['central_profile_sha256'],'SLASH_PROFILE_CHANGED')
                op=record['operations'][job['id']];host=Host(op,resume=True);p=profile(CLIENT/op);text=prompt(op)
                result=run(p,text,record['skill'],workspace=ROOT,run_directory=base/'runs'/context['attempt_id'],
                    expected_cli_sha256=record['cli_sha256'],host_tick=host.tick)
                attempt['transport']=result
                if result['status']=='retryable':
                    require(result['receipt']['turn_submitted'] is False,'SLASH_UNSAFE_RETRY')
                    attempt.update(status='retryable',code=result['code']);record['attempts'].append(attempt);atomic(path,record)
                    return result
                checked=postconditions(host,result,context,record,text)
                require(fingerprint()==record['candidate'],'SLASH_CANDIDATE_CHANGED')
                attempt.update(status='passed',postcondition=checked)
                record['attempts'].append(attempt)
                if len({a['job_id'] for a in record['attempts'] if a['status']=='passed'})==3:record['execution_status']='passed'
                atomic(path,record)
                return {'status':'succeeded','code':'SLASH_NATIVE_AND_BROWSER_VERIFIED','receipt':attempt}
            except Exception as error:
                from shared.research_sources.artifacts import SourceError
                code=str(error) if isinstance(error,SourceError) else 'SLASH_ACCEPTANCE_FAILED'
                attempt.update(status='failed',code=code);record['attempts'].append(attempt);record['execution_status']='failed';atomic(path,record)
                # Any submitted unverified operation stays held in the engine.
                submitted=attempt.get('transport',{}).get('receipt',{}).get('turn_submitted',False)
                return {'status':'unknown' if submitted else 'failed','code':code,'receipt':attempt}
        engine=Engine(base/'engine',record['jobs'],record['retry'],dispatch,workspace_root=ROOT,max_workers=1)
        engine.tick(datetime.now(timezone.utc))
    except Exception as error:
        # A broken controller is permanent for this candidate, not permission
        # for launchd to loop forever or replay an uncertain attempt.
        if 'record' in locals():
            record.update(execution_status='failed',controller_failure='SLASH_CONTROLLER_FAILED',
                          controller_failed_at=datetime.now(timezone.utc).isoformat())
            atomic(path,record)
        else:raise
    finally:os.close(fd)


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=('stage','tick'))
    p.add_argument('--name',default='scheduled-v1');p.add_argument('--record',type=Path);args=p.parse_args()
    if args.command=='stage':print(json.dumps(stage(args.name)))
    else:
        require(args.record is not None,'SLASH_RECORD_REQUIRED');tick(args.record)


if __name__=='__main__':main()
