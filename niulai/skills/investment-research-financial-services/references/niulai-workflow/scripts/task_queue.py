#!/usr/bin/env python3
"""Durable SQLite work state for a native orchestrator, not an agent executor.
Only use a restored Niulai research DB; persist it with a remote version guard.
Leases prevent duplicate local dispatch, not exactly-once external side effects.
"""
import argparse
import hashlib
import json
import sqlite3
import time
import uuid
from research_store import connect, encode, text

VERSION = '2026-10-20-taskq-1'
MAX_ACTIVE = 3
DDL = [
'''CREATE TABLE IF NOT EXISTS taskq_policy(singleton INTEGER PRIMARY KEY CHECK(singleton=1),max_active INTEGER NOT NULL CHECK(max_active BETWEEN 1 AND 8))''',
'''INSERT OR IGNORE INTO taskq_policy(singleton,max_active) VALUES(1,3)''',
'''CREATE TABLE IF NOT EXISTS taskq_jobs(
 id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, run_id TEXT NOT NULL,
 ticker TEXT NOT NULL, payload TEXT NOT NULL, dependencies TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','running','blocked','completed','failed','cancelled')),
 attempts INTEGER NOT NULL, max_attempts INTEGER NOT NULL, available_at REAL NOT NULL,
 owner TEXT, token TEXT, lease_until REAL, checkpoint TEXT, result TEXT, error TEXT,
 created_at REAL NOT NULL, updated_at REAL NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS taskq_events(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
 event TEXT NOT NULL, payload TEXT NOT NULL, occurred_at REAL NOT NULL)''',
'''CREATE TRIGGER IF NOT EXISTS taskq_events_immutable_update BEFORE UPDATE ON taskq_events
 BEGIN SELECT RAISE(ABORT,'Queue audit is immutable'); END''',
'''CREATE TRIGGER IF NOT EXISTS taskq_events_immutable_delete BEFORE DELETE ON taskq_events
 BEGIN SELECT RAISE(ABORT,'Queue audit is immutable'); END''']

class QueueError(ValueError): pass


def integer(value, name, low=1, high=100):
    if type(value) is not int or not low <= value <= high:
        raise QueueError(name + ' outside allowed integer range')
    return value


def clock(now):
    value = time.time() if now is None else now
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < 1e12:
        raise QueueError('Invalid clock')
    return value


def begin(db):
    db.execute('BEGIN IMMEDIATE')
    for sql in DDL: db.execute(sql)
    columns={r[1] for r in db.execute('PRAGMA table_info(taskq_policy)')}
    if 'monitoring_required' not in columns:
        db.execute('ALTER TABLE taskq_policy ADD COLUMN monitoring_required INTEGER NOT NULL DEFAULT 0 CHECK(monitoring_required IN (0,1))')


def monitoring_config(db):
    """Validate saved monitoring admission evidence, not live scheduler uptime."""
    from pathlib import Path
    from niulai_state import validate_config
    db_path = next((row[2] for row in db.execute('PRAGMA database_list') if row[1] == 'main'), '')
    path = Path(db_path).parent / 'workflow.json' if db_path else None
    if path is None or not path.is_file():
        raise QueueError('Monitoring admission: adjacent workflow.json is missing')
    try:
        config=json.loads(path.read_text())
        validate_config(config)
        contract=config.get('research',{}).get('monitoring_contract',{})
        if contract.get('required') is not True or contract.get('scope')!='all_current_and_future_runs':
            raise QueueError('Monitoring admission: all-run monitoring contract missing')
        if contract.get('scheduler_readback_verified') is not True:
            raise QueueError('Monitoring admission: scheduler readback unverified')
        identity=contract.get('automation_id')
        if not isinstance(identity,str) or not identity.strip():
            raise QueueError('Monitoring admission: automation identity missing')
        role='research_queue_continuation'
        matches=[s for s in config['schedules'] if s.get('role')==role]
        if len(matches)!=1 or matches[0].get('enabled') is not True or matches[0].get('automation_id')!=identity:
            raise QueueError('Monitoring admission: continuation schedule disabled or identity differs')
        if config.get('notifications',{}).get('policies',{}).get(role,{}).get('enabled') is not True:
            raise QueueError('Monitoring admission: continuation notification policy disabled')
        return config
    except QueueError:
        raise
    except (ValueError,TypeError,KeyError,AttributeError,OSError) as exc:
        raise QueueError('Monitoring admission: invalid configuration: '+str(exc)) from exc


def require_monitoring(db):
    columns={r[1] for r in db.execute('PRAGMA table_info(taskq_policy)')}
    if 'monitoring_required' in columns:
        row=db.execute('SELECT monitoring_required FROM taskq_policy WHERE singleton=1').fetchone()
        if row and row[0]:
            cfg=monitoring_config(db)
            if cfg.get('research',{}).get('triage',{}).get('admission_required') is not True:
                raise QueueError('Triage admission: production configuration must enable screening gate')


def configure_monitoring(db, required=True):
    if type(required) is not bool: raise QueueError('monitoring required must be boolean')
    # Fail before persisting an enabled guard if its recovery channel is unverified.
    if required: monitoring_config(db)
    begin(db)
    try:
        db.execute('UPDATE taskq_policy SET monitoring_required=? WHERE singleton=1',(int(required),))
        event(db,'queue_policy','monitoring_configured',{'monitoring_required':required},clock(None))
        db.commit();return {'monitoring_required':required}
    except BaseException:db.rollback();raise


def require_triage(db, payload):
    """Production admission: cheap stage or evidenced explicit stage routing."""
    from pathlib import Path
    dbpath=next((r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main'),'')
    path=Path(dbpath).parent/'workflow.json' if dbpath else None
    if not path or not path.exists(): return
    cfg=json.loads(path.read_text()).get('research',{}).get('triage',{})
    if cfg.get('admission_required') is not True:return
    phase=payload.get('phase')
    if phase=='bounded_triage':
        n=payload.get('max_new_primary_documents')
        if type(n) is int and 0<=n<=2 and payload.get('no_fresh_recommendation') is True:return
        raise QueueError('Triage admission: bounded probe needs document cap and no fresh recommendation')
    if phase=='targeted_followup':
        card=payload.get('card_path');digest=payload.get('card_hash')
        n=payload.get('new_primary_document_budget')
        if (payload.get('parent_run_id') and payload.get('next_action') and payload.get('reopening_condition')
            and type(n) is int and 0<=n<=2 and card and Path(card).is_file()
            and hashlib.sha256(Path(card).read_bytes()).hexdigest()==digest):
            parent=json.loads(Path(card).read_text())
            if parent.get('route') not in ('held','user_hold','out_of_scope') and parent.get('next_action')==payload['next_action'] and parent.get('reopening_condition')==payload['reopening_condition']:return
        raise QueueError('Triage admission: targeted stage requires exact parent card, question and bounded budget')
    from research_triage import route
    inputs=payload.get('triage_input')
    if not isinstance(inputs,dict):raise QueueError('Triage admission: missing screened inputs')
    actual=route(inputs)
    if payload.get('triage_route')!=actual['route']:raise QueueError('Triage admission: route differs from deterministic screen')
    allowed={'full_review':{'full_review','priority_risk_review'},'delta_review':{'delta_review','priority_risk_review'},'reprice':{'reprice','fund_path_refresh'}}
    if actual['route'] not in allowed.get(phase,set()):raise QueueError('Triage admission: waiting/reuse/unknown result cannot launch expensive stage')


def event(db, task_id, kind, payload, now):
    db.execute('INSERT INTO taskq_events(task_id,event,payload,occurred_at) VALUES(?,?,?,?)',
               (task_id, kind, encode(payload), now))


def unpack(row):
    if row is None: return None
    out = dict(row)
    for key in ('payload', 'dependencies', 'checkpoint', 'result'):
        if out[key] is not None: out[key] = json.loads(out[key])
    return out


def read(db, task_id=None):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='taskq_jobs'").fetchone():
        return None if task_id else []
    if task_id: return unpack(db.execute('SELECT * FROM taskq_jobs WHERE id=?',(task_id,)).fetchone())
    return [unpack(r) for r in db.execute('SELECT * FROM taskq_jobs ORDER BY created_at,id')]


def task_id(request, ticker):
    key = {k: request[k] for k in ('run_id', 'session', 'config_revision', 'input_hash')}
    key['ticker'] = ticker
    return 'taskq:' + hashlib.sha256(encode(key).encode()).hexdigest()


def enqueue(db, request, now=None):
    require_monitoring(db)
    now = clock(now)
    for k in ('run_id','session','input_hash'): text(request.get(k),k)
    integer(request.get('config_revision'),'config_revision',1,10**9)
    tasks = request.get('tasks')
    if not isinstance(tasks,list) or not tasks: raise QueueError('Nonempty tasks required')
    prepared={}
    for t in tasks:
        ticker=text(t.get('ticker'),'ticker')
        if len(ticker)>20 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.^=-' for c in ticker):raise QueueError('Invalid ticker')
        tid=task_id(request,ticker)
        if tid in prepared: raise QueueError('Duplicate ticker')
        payload=t.get('payload')
        if not isinstance(payload,dict):raise QueueError('Task payload must be object')
        require_triage(db,payload)
        deps=t.get('dependencies',[])
        if not isinstance(deps,list) or any(not isinstance(x,str) or not x for x in deps) or len(set(deps))!=len(deps):raise QueueError('Invalid dependencies')
        attempts=integer(t.get('max_attempts',3),'max_attempts',1,10)
        content={'payload':payload,'dependencies':sorted(deps),'max_attempts':attempts}
        prepared[tid]=(ticker,content,hashlib.sha256(encode(content).encode()).hexdigest())
    begin(db)
    try:
        graph={r['id']:r['dependencies'] for r in read(db)}
        graph.update({tid:v[1]['dependencies'] for tid,v in prepared.items()})
        for tid,deps in graph.items():
            if any(d not in graph for d in deps):raise QueueError('Unknown dependency')
        seen=set(); active=set()
        def visit(node):
            if node in active:raise QueueError('Dependency cycle')
            if node in seen:return
            active.add(node)
            for d in graph[node]:visit(d)
            active.remove(node);seen.add(node)
        for tid in graph:visit(tid)
        out=[]
        for tid,(ticker,content,fingerprint) in prepared.items():
            old=read(db,tid)
            if old:
                if old['fingerprint']!=fingerprint:raise QueueError('Task identity reused with changed payload')
                out.append({'id':tid,'duplicate':True});continue
            state='blocked' if content['dependencies'] else 'pending'
            db.execute('INSERT INTO taskq_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (tid,fingerprint,request['run_id'],ticker,encode(content['payload']),encode(content['dependencies']),state,0,content['max_attempts'],now,None,None,None,None,None,None,now,now))
            event(db,tid,'enqueued',{'state':state},now)
            out.append({'id':tid,'duplicate':False})
        db.commit();return out
    except BaseException:db.rollback();raise


def reap(db, now):
    for row in db.execute("SELECT * FROM taskq_jobs WHERE state='running' AND lease_until<=?",(now,)).fetchall():
        state='failed' if row['attempts']>=row['max_attempts'] else 'pending'
        db.execute('UPDATE taskq_jobs SET state=?,owner=NULL,token=NULL,lease_until=NULL,error=?,updated_at=? WHERE id=?',
                   (state,'lease_expired',now,row['id']))
        event(db,row['id'],'lease_expired',{'state':state,'attempts':row['attempts']},now)


def claim(db, owner, limit=3, lease_seconds=900, now=None, run_id=None):
    require_monitoring(db)
    # Explicit user hold is a dispatch boundary, not research completion.
    from pathlib import Path
    db_path = next((row[2] for row in db.execute('PRAGMA database_list') if row[1] == 'main'), '')
    config_path = Path(db_path).parent / 'workflow.json' if db_path else None
    if config_path and config_path.exists():
        config = json.loads(config_path.read_text())
        held = config.get('research', {}).get('triage', {}).get('held_run_ids', [])
        if not isinstance(held, list):
            raise ValueError('Invalid triage held_run_ids')
        if run_id in held or (run_id is None and held):
            return []
    now=clock(now);text(owner,'owner');integer(limit,'limit',1,8);integer(lease_seconds,'lease_seconds',1,86400)
    if run_id is not None:text(run_id,'run_id')
    begin(db)
    try:
        reap(db,now)
        active=db.execute("SELECT count(*) FROM taskq_jobs WHERE state='running'").fetchone()[0]
        maximum=db.execute('SELECT max_active FROM taskq_policy WHERE singleton=1').fetchone()[0]
        capacity=min(limit,max(0,maximum-active));out=[]
        rows=db.execute("SELECT * FROM taskq_jobs WHERE state IN ('pending','blocked') AND available_at<=? AND (? IS NULL OR run_id=?) ORDER BY created_at,id",(now,run_id,run_id)).fetchall()
        for row in rows:
            deps=json.loads(row['dependencies'])
            states=[read(db,d)['state'] for d in deps]
            if any(s!='completed' for s in states):
                reason='dependency_failed' if any(s in ('failed','cancelled') for s in states) else 'dependency_pending'
                db.execute("UPDATE taskq_jobs SET state='blocked',error=?,updated_at=? WHERE id=?",(reason,now,row['id']))
                continue
            if len(out)>=capacity:continue
            require_triage(db,json.loads(row['payload']))
            token=uuid.uuid4().hex
            db.execute("UPDATE taskq_jobs SET state='running',attempts=attempts+1,owner=?,token=?,lease_until=?,error=NULL,updated_at=? WHERE id=?",(owner,token,now+lease_seconds,now,row['id']))
            event(db,row['id'],'claimed',{'owner':owner,'attempt':row['attempts']+1,'lease_until':now+lease_seconds},now)
            out.append(read(db,row['id']))
        db.commit();return out
    except BaseException:db.rollback();raise


def mutate(db, task_id, token, action, payload=None, lease_seconds=900, retry_seconds=30, now=None, retryable=True, *, manage_transaction=True):
    now=clock(now)
    if action not in ('heartbeat','checkpoint','finish','fail'):raise QueueError('Invalid action')
    if action=='heartbeat':integer(lease_seconds,'lease_seconds',1,86400)
    if action=='fail':integer(retry_seconds,'retry_seconds',1,86400)
    if action in ('checkpoint','finish') and not isinstance(payload,dict):raise QueueError('Structured payload required')
    if action=='checkpoint':text(payload.get('stage'),'stage')
    if action=='fail':text(payload,'error')
    if manage_transaction: begin(db)
    elif not db.in_transaction: raise QueueError('Caller-owned transaction required')
    try:
        row=read(db,task_id)
        if not row or row['state']!='running' or row['token']!=token or row['lease_until']<=now:raise QueueError('Stale, expired or invalid lease')
        if action=='heartbeat':
            db.execute('UPDATE taskq_jobs SET lease_until=?,updated_at=? WHERE id=?',(now+lease_seconds,now,task_id))
        elif action=='checkpoint':
            db.execute('UPDATE taskq_jobs SET checkpoint=?,updated_at=? WHERE id=?',(encode(payload),now,task_id))
        elif action=='finish':
            db.execute("UPDATE taskq_jobs SET state='completed',result=?,owner=NULL,token=NULL,lease_until=NULL,updated_at=? WHERE id=?",(encode(payload),now,task_id))
        else:
            if type(retryable) is not bool:raise QueueError('retryable must be boolean')
            state='failed' if not retryable or row['attempts']>=row['max_attempts'] else 'pending'
            delay=min(86400,retry_seconds*(2**(row['attempts']-1)))
            db.execute('UPDATE taskq_jobs SET state=?,available_at=?,error=?,owner=NULL,token=NULL,lease_until=NULL,updated_at=? WHERE id=?',(state,now+delay,payload,now,task_id))
        event(db,task_id,action,{'payload':payload},now)
        if manage_transaction: db.commit()
        return read(db,task_id)
    except BaseException:
        if manage_transaction: db.rollback()
        raise


def cancel(db, task_id, reason, now=None):
    now=clock(now);text(reason,'reason');begin(db)
    try:
        row=read(db,task_id)
        if not row:raise QueueError('Unknown task')
        if row['state'] in ('completed','failed','cancelled'):raise QueueError('Terminal task cannot be cancelled')
        db.execute("UPDATE taskq_jobs SET state='cancelled',error=?,owner=NULL,token=NULL,lease_until=NULL,updated_at=? WHERE id=?",(reason,now,task_id))
        event(db,task_id,'cancelled',{'reason':reason},now);db.commit();return read(db,task_id)
    except BaseException:db.rollback();raise


def configure(db, max_active):
    integer(max_active,'max_active',1,8);begin(db)
    try:
        db.execute('UPDATE taskq_policy SET max_active=? WHERE singleton=1',(max_active,))
        event(db,'queue_policy','configured',{'max_active':max_active},clock(None))
        db.commit();return {'max_active':max_active}
    except BaseException:db.rollback();raise


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['enqueue','claim','heartbeat','checkpoint','finish','fail','cancel','status','configure'])
    p.add_argument('--db',required=True);p.add_argument('--file');p.add_argument('--id');p.add_argument('--token');p.add_argument('--owner');p.add_argument('--limit',type=int,default=3);p.add_argument('--lease-seconds',type=int,default=900);p.add_argument('--retry-seconds',type=int,default=30);p.add_argument('--error');p.add_argument('--reason');p.add_argument('--output');p.add_argument('--max-active',type=int,default=3);p.add_argument('--permanent',action='store_true');p.add_argument('--run-id')
    a=p.parse_args();db=connect(a.db,readonly=a.command=='status')
    try:
        payload=json.load(open(a.file)) if a.file else None
        if a.command=='configure':result=configure(db,a.max_active)
        elif a.command=='enqueue':result=enqueue(db,payload)
        elif a.command=='claim':result=claim(db,a.owner,a.limit,a.lease_seconds,run_id=a.run_id)
        elif a.command=='status':result=read(db,a.id)
        elif a.command=='cancel':result=cancel(db,a.id,a.reason)
        else:result=mutate(db,a.id,a.token,a.command,a.error if a.command=='fail' else payload,a.lease_seconds,a.retry_seconds,retryable=not a.permanent)
        output=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
        if a.output:
            from pathlib import Path
            Path(a.output).write_text(output)
        else:print(output,end='')
    finally:db.close()
if __name__=='__main__':main()
