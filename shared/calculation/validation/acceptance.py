"""Scheduled calculation exercise; owner email is independently sent by supervisor."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import time

from .runner import ROOT, STATE, fingerprint, run, atomic, sha, environment_snapshot, state_path, json_digest

BROKER_RESULTS = {}


def read_request(attempt, expected, timeout=120):
    """Read untrusted inbox through anchored no-follow directory descriptors."""
    base=state_path(STATE/'client')
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
    rootfd=os.open(base,flags)
    try:
        directory=os.open(attempt,flags,dir_fd=rootfd)
        try:
            deadline=time.monotonic()+timeout
            while True:
                try:fd=os.open('request.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
                except FileNotFoundError:
                    if time.monotonic()>deadline:raise TimeoutError('CALCULATION_REQUEST_TIMEOUT')
                    time.sleep(.2);continue
                try:
                    info=os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_size>2048 or info.st_nlink!=1 or info.st_uid!=os.getuid():
                        raise ValueError('CALCULATION_REQUEST_FILE_INVALID')
                    raw=os.read(fd,2049)
                    if len(raw)>2048 or json.loads(raw)!=expected:raise ValueError('CALCULATION_REQUEST_INVALID')
                    return
                finally:os.close(fd)
        finally:os.close(directory)
    finally:os.close(rootfd)


def prepare(options, workspace, context):
    """One attempt-scoped bridge hosted outside Codex's shell sandbox.

    Codex requests the fixed calculation through the client. This host executes
    the same offline OS-restricted worker graph, with no network listener or
    persistent extra daemon. The in-memory host digest cannot be edited by the
    model's calculator-state write grant.
    """
    change=options.get('change_id','');attempt=context.get('attempt_id','')
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,95}',change) or not re.fullmatch('[0-9a-f-]{36}',attempt):
        return {'status':'failed','code':'CALCULATION_BRIDGE_CONTEXT_INVALID'}
    declared=json.loads((ROOT/'.job-runtime/acceptance'/change/'record.json').read_text())
    pin=declared['candidate']['source_fingerprint']
    if fingerprint()['sha256']!=pin:return {'status':'failed','code':'CALCULATION_BRIDGE_CANDIDATE_CHANGED'}
    folder=state_path(STATE/'bridge'/attempt);folder.mkdir(parents=True,exist_ok=False,mode=0o700)
    inbox=state_path(STATE/'client'/attempt);inbox.mkdir(parents=True,exist_ok=False,mode=0o700)
    request={'change_id':change,'attempt_id':attempt,'scheduled_at':context['scheduled_at'],'candidate_sha256':pin}
    atomic(folder/'ready.json',request)
    def serve():
        try:
            read_request(attempt,request)
            value=exercise(change,attempt,context['scheduled_at'])
            atomic(folder/'response.json',value)
        except Exception as exc:
            BROKER_RESULTS[attempt]={'completed':False,'error_type':type(exc).__name__}
            atomic(folder/'response.json',{'status':'blocked','code':'CALCULATION_BRIDGE_FAILED',
                  'error_type':type(exc).__name__})
    threading.Thread(target=serve,name='calculation-'+attempt,daemon=True).start()
    return {'calculation_bridge_directory':str(folder),
            'calculation_execution_boundary':'existing scheduler host -> offline OS-restricted workers; requested by Codex client'}


def exercise(change_id, attempt_id, scheduled_at):
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,95}',change_id):raise ValueError('CHANGE_ID_INVALID')
    if not re.fullmatch('[0-9a-f-]{36}',attempt_id):raise ValueError('ATTEMPT_ID_INVALID')
    folder=ROOT/'.job-runtime/acceptance'/change_id
    declared=json.loads((folder/'record.json').read_text())
    if fingerprint()['sha256']!=declared['candidate']['source_fingerprint']:
        raise ValueError('VALIDATION_CANDIDATE_CHANGED')
    if environment_snapshot()['sha256']!=declared['candidate']['environment_fingerprint']:
        raise ValueError('VALIDATION_ENVIRONMENT_CHANGED')
    if datetime.now(timezone.utc)<datetime.fromisoformat(scheduled_at):
        raise ValueError('VALIDATION_BEFORE_DUE')
    report,path=run('scheduled-'+attempt_id)
    digest=json_digest(report)
    index={'attempt_id':attempt_id,'scheduled_at':scheduled_at,
           'report_path':str(path.relative_to(ROOT)),'report_sha256':digest,
           'candidate_sha256':report['fingerprint']['sha256']}
    atomic(path.parent/'acceptance-index.json',index)
    BROKER_RESULTS[attempt_id]={'report_sha256':digest,'completed':report['status']=='completed'}
    return {'status':'completed' if report['status']=='completed' else 'blocked',
            'code':'CALCULATION_VALIDATION_EXERCISED','report_directory':str(path.parent),
            'delivery_verified':False,'error_codes':[] if report['status']=='completed' else ['VALIDATION_RUN_BLOCKED']}


def verify(options,workspace,context,result):
    try:
        folder=ROOT/'.job-runtime/acceptance'/options['change_id']
        declared=json.loads((folder/'record.json').read_text())
        index=json.loads((STATE/'runs'/('scheduled-'+context['attempt_id'])/'acceptance-index.json').read_text())
        path=ROOT/index['report_path']
        if not path.resolve().is_relative_to(STATE/'runs') or path.is_symlink():return {'verified':False}
        if sha(path)!=index['report_sha256']:return {'verified':False}
        report=json.loads(path.read_text());pin=declared['candidate']['source_fingerprint']
        host=BROKER_RESULTS.get(context['attempt_id'],{})
        if not host.get('completed') or host.get('report_sha256')!=index['report_sha256']:
            return {'verified':False}
        if report['fingerprint']['sha256']!=pin or fingerprint()['sha256']!=pin:return {'verified':False}
        if report['run_id']!='scheduled-'+context['attempt_id']:return {'verified':False}
        env_pin=declared['candidate']['environment_fingerprint']
        if not report['environment_unchanged'] or report['environment']['sha256']!=env_pin or environment_snapshot()['sha256']!=env_pin:
            return {'verified':False}
        if index['attempt_id']!=context['attempt_id'] or index['scheduled_at']!=context['scheduled_at']:return {'verified':False}
        due=datetime.fromisoformat(context['scheduled_at'])
        with sqlite3.connect('file:'+str(ROOT/'.job-runtime/engine/schedule.sqlite')+'?mode=ro',uri=True) as db:
            started=db.execute('SELECT started_at,slot_id FROM attempts WHERE attempt_id=?',
                               (context['attempt_id'],)).fetchone()
        if not started or started[1]!=context['slot_id']:return {'verified':False}
        lateness=started[0]-due.timestamp()
        if not 0<=lateness<=declared['criteria']['max_start_lateness_seconds']:return {'verified':False}
        if datetime.fromisoformat(report['started_at'])<due:return {'verified':False}
        if (datetime.fromisoformat(report['completed_at'])-due).total_seconds()>declared['criteria']['completion_timeout_seconds']:return {'verified':False}
        if report['status']!='completed' or not report['candidate_unchanged'] or not report['security']['passed']:return {'verified':False}
        if set(report['suites'])!={'valuation','options','paths','contracts'}:return {'verified':False}
        for name,suite in report['suites'].items():
            if not suite['completed']:return {'verified':False}
            ref=ROOT/suite['receipt']['result_path']
            if not ref.resolve().is_relative_to(STATE/'validation') or ref.is_symlink() or sha(ref)!=suite['receipt']['sha256']:
                return {'verified':False}
            expected=STATE/'validation'/name/'aggregate'/report['run_id']/'worker-result.json'
            if ref.resolve()!=expected.resolve() or json.loads(ref.read_text())!=suite['result'] or ref.stat().st_mtime<due.timestamp():
                return {'verified':False}
        receipt=result.get('receipt',{})
        if not receipt.get('turn_completed') or receipt.get('exit_code')!=0:return {'verified':False}
        if not any('command_execution' in name or 'exec_command' in name
                   for name in receipt.get('tool_names',[])):
            return {'verified':False}
        return {'verified':True,'scope':'Scheduled offline validation harness and retained findings; numerical verdicts remain separate.',
                'report_path':index['report_path'],'report_sha256':index['report_sha256'],
                'candidate_sha256':pin,'security_probes_passed':True,
                'environment_sha256':env_pin,'start_lateness_seconds':lateness}
    except (KeyError,ValueError,OSError,TypeError,sqlite3.Error):
        return {'verified':False}


if __name__=='__main__':
    os.umask(0o077)
    p=argparse.ArgumentParser();p.add_argument('--change-id',required=True)
    p.add_argument('--attempt-id',required=True);p.add_argument('--scheduled-at',required=True)
    a=p.parse_args()
    print(json.dumps(exercise(a.change_id,a.attempt_id,a.scheduled_at)))
