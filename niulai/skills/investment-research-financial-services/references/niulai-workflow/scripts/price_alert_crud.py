#!/usr/bin/env python3
"""Offline stdlib CRUD. JSON remains monitor authority; SQLite is audit/mirror.
Remote publication needs separate fresh Library version guards. No price fetch/send.
"""
import argparse, copy, datetime as dt, decimal, hashlib, json, os, re, sqlite3, tempfile
from pathlib import Path

def encode(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, allow_nan=False)

def digest(x):
    return hashlib.sha256(encode(x).encode()).hexdigest()

def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def instant(x):
    t=dt.datetime.fromisoformat(x.replace('Z','+00:00'))
    if t.tzinfo is None: raise ValueError('Timezone required')
    return t

def number(x):
    if isinstance(x,bool): raise ValueError('Boolean is not a price')
    n=decimal.Decimal(str(x))
    if not n.is_finite() or n<=0: raise ValueError('Price must be finite and positive')
    return n

def validate(doc):
    if doc.get('_meta',{}).get('canonical_source')!='niulai_saved_json_sqlite':
        raise ValueError('Wrong rule authority')
    ids=set()
    for r in doc['alerts']:
        if not isinstance(r['id'],str) or not r['id'] or r['id'] in ids: raise ValueError('Duplicate/empty ID')
        ids.add(r['id']); number(r['threshold'])
        if not re.fullmatch(r'[A-Z0-9.^=-]{1,20}',r['ticker']): raise ValueError('Invalid symbol')
        if r['direction'] not in ('above','below') or type(r['enabled']) is not bool: raise ValueError('Invalid direction/enabled')
        instant(r['createdAt']); instant(r['updatedAt'])
        if r.get('effective_from'): instant(r['effective_from'])
        if r.get('expires_at') and instant(r['expires_at'])<=instant(r.get('effective_from',r['updatedAt'])): raise ValueError('Invalid expiry')
        if 'buffer_fraction' in r:
            b=decimal.Decimal(str(r['buffer_fraction']))
            if not b.is_finite() or not 0<=b<=decimal.Decimal('.05'): raise ValueError('Invalid buffer')
        if 'review_range' in r:
            lo,hi=map(number,(r['review_range']['lower'],r['review_range']['upper']))
            if lo>hi or r['direction']!='below' or hi!=number(r['threshold']): raise ValueError('Review range requires below upper edge')
    return doc

def write_atomic(path,doc):
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.alerts-')
    try:
        with os.fdopen(fd,'w') as f:
            f.write(json.dumps(doc,ensure_ascii=False,indent=2)+'\n');f.flush();os.fsync(f.fileno())
        # Preserve Library metadata through atomic replacement.
        if path.exists() and hasattr(os,'listxattr'):
            for k in os.listxattr(path): os.setxattr(tmp,k,os.getxattr(path,k))
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def connect(path):
    if not path.is_file(): raise ValueError('Restore existing SQLite; never initialize empty database')
    db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=15)
    if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('DB integrity failure')
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='alerts'").fetchone(): raise ValueError('Not alerts database')
    return db

def recover(db,path):
    row=db.execute('SELECT request_id,before_sha,after_sha,snapshot FROM alert_crud_journal WHERE exported=0').fetchone()
    if not row:return
    rid,before,after,snapshot=row
    current=digest(json.loads(path.read_text()))
    if current not in (before,after): raise ValueError('Recovery conflict: JSON changed; reconcile, do not overwrite')
    write_atomic(path,json.loads(snapshot))
    db.execute('UPDATE alert_crud_journal SET exported=1 WHERE request_id=?',(rid,));db.commit()

def decision_gate(m, rule):
    """Require a decision artifact and bind the edited threshold to its calculation."""
    ref=m.get('decision',{});path=Path(ref.get('path',''))
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=ref.get('sha256'): raise ValueError('Missing/changed actionable decision')
    d=json.loads(path.read_text())
    if d.get('ticker')!=rule['ticker'] or d.get('now_action') not in ('buy','wait','avoid','reduce'): raise ValueError('Decision identity/action missing')
    for key in ('as_of','valid_until'): instant(d[key])
    if instant(d['valid_until'])<=instant(d['as_of']): raise ValueError('Invalid decision validity')
    if instant(d['valid_until'])<=dt.datetime.now(dt.timezone.utc): raise ValueError('Decision expired')
    if number(d['horizon_days'])<=0 or number(d['required_return'])<=0: raise ValueError('Decision horizon/hurdle missing')
    matches=[b for b in d.get('bands',[]) if number(b['threshold'])==number(rule['threshold']) and b.get('direction')==rule['direction']]
    if len(matches)!=1: raise ValueError('Alert not backed by exactly one calculated entry band')
    b=matches[0]
    if not b.get('conditions') or not b.get('invalidation'): raise ValueError('Entry conditions/invalidation required')
    calc=b.get('calculation',{});f=Path(calc.get('path',''))
    if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest()!=calc.get('sha256'): raise ValueError('Entry calculation absent/changed')
    if m['security_type']=='leveraged_fund':
        if not b.get('underlying_condition') or not b.get('anchor') or not b.get('pre_entry_path_assumption'): raise ValueError('Leveraged price requires underlying and dated path mapping')
        if not rule.get('expires_at') or instant(rule['expires_at'])>instant(d['valid_until']): raise ValueError('Leveraged nominal alert must expire within decision validity')
    return True

def review_gate(request, doc):
    """Evidence-presence/identity guard, never proof of forecast truth."""
    manifests=request.get('reviews')
    if not isinstance(manifests,dict): raise ValueError('Per-ticker reviews required')
    existing={r['id']:r for r in doc['alerts']}
    for op in request['operations']:
        old=existing.get(op['id'],{})
        r=dict(old); r.update(op.get('rule',op.get('patch',{})))
        if op['op']=='delete' or not r.get('enabled'): continue
        t=r['ticker']; m=manifests.get(t,{})
        if m.get('purpose') not in ('research_review','legacy_price_only'): raise ValueError('Explicit alert purpose required: '+t)
        if not m.get('author') or not m.get('reviewer') or m['author']==m['reviewer']: raise ValueError('Independent reviewer required: '+t)
        for key in ('model','review'):
            ref=m.get(key,{})
            path=Path(ref.get('path',''))
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=ref.get('sha256'): raise ValueError('Missing/changed evidence '+t+': '+key)
        instant(m['reviewed_at'])
        if m.get('security_type') not in ('company','leveraged_fund'): raise ValueError('Classify security: '+t)
        if m['security_type']=='leveraged_fund':
            required={'reset','benchmark','cost_ledger','favorable_trend','chop_and_crash','unlevered_comparison','mean_median_tail','probability_status','entry_conditions'}
            if not required.issubset(set(m.get('covered',[]))): raise ValueError('Leveraged workflow incomplete: '+t)
            if m['purpose']=='research_review' and m.get('entry_basis')!='underlying_value_and_path_and_cost': raise ValueError('Nominal fund price cannot establish an entry')
        if m['purpose']=='legacy_price_only':
            if op['op']!='update' or r['threshold']!=old.get('threshold') or r['direction']!=old.get('direction'): raise ValueError('Legacy-only review cannot create/reprice entry')
            if m.get('buy_recommendation') is not False: raise ValueError('Legacy line must not imply buy')
        else:
            if m.get('entry_basis') not in ('reviewed_company_model','underlying_value_and_path_and_cost'): raise ValueError('Unsupported entry basis')
            decision_gate(m,r)
    return True

def apply(path,dbpath,request,dry_run=False):
    db=connect(dbpath)
    try:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS alert_crud_journal(request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,before_sha TEXT NOT NULL,after_sha TEXT NOT NULL,snapshot TEXT NOT NULL,changes TEXT NOT NULL,exported INTEGER NOT NULL,created_at TEXT NOT NULL)')
        pending=db.execute('SELECT 1 FROM alert_crud_journal WHERE exported=0').fetchone()
        if pending: raise ValueError('Pending export: run recover before new edits')
        fp=digest(request)
        old=db.execute('SELECT fingerprint,after_sha FROM alert_crud_journal WHERE request_id=?',(request['request_id'],)).fetchone()
        if old:
            if old[0]!=fp: raise ValueError('Request ID reused with different payload')
            db.rollback();return {'status':'already_applied','after_sha':old[1]}
        doc=validate(json.loads(path.read_text()));review_gate(request,doc);before=digest(doc)
        if request['expected_sha256']!=before: raise ValueError('Stale JSON revision')
        new=copy.deepcopy(doc);byid={r['id']:r for r in new['alerts']};changes=[];seen=set();now=stamp()
        for op in request['operations']:
            rid=op['id'];kind=op['op']
            if rid in seen: raise ValueError('One operation per ID per request')
            seen.add(rid);previous=copy.deepcopy(byid.get(rid))
            if kind=='create':
                if previous: raise ValueError('ID exists')
                r=copy.deepcopy(op['rule'])
                if any(x['ticker']==r['ticker'] and x['direction']==r['direction'] and number(x['threshold'])==number(r['threshold']) and not x.get('deleted_at') for x in byid.values()): raise ValueError('Equivalent rule exists; update explicitly')
                r.update(id=rid,createdAt=now,updatedAt=now,effective_from=now);byid[rid]=r
            elif kind in ('update','delete'):
                if previous is None: raise ValueError('Unknown ID')
                if op['expected_rule_sha256']!=digest(previous): raise ValueError('Stale rule revision')
                patch=op.get('patch',{})
                if set(patch)&{'id','createdAt','updatedAt','effective_from','deleted_at'}: raise ValueError('Immutable field')
                if previous.get('deleted_at'): raise ValueError('Deleted rule: create new identity to restore')
                byid[rid].update(patch if kind=='update' else {'enabled':False,'deleted_at':now})
                byid[rid].update(updatedAt=now,effective_from=now)
            else: raise ValueError('Unknown operation')
            changes.append({'id':rid,'op':kind,'before':previous,'after':byid[rid]})
        new['alerts']=list(byid.values());new['_meta']['crud_revision']=int(new['_meta'].get('crud_revision',0))+1
        new['_meta']['last_edit_at']=now;new['_meta']['last_request_id']=request['request_id'];validate(new)
        after=digest(new)
        if dry_run: db.rollback();return {'status':'dry_run','before_sha':before,'changes':changes}
        for change in changes:
            r=change['after']
            db.execute('INSERT INTO alerts(id,ticker,direction,threshold,enabled,payload) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ticker=excluded.ticker,direction=excluded.direction,threshold=excluded.threshold,enabled=excluded.enabled,payload=excluded.payload',(r['id'],r['ticker'],r['direction'],str(r['threshold']),int(r['enabled']),encode(r)))
        db.execute('INSERT INTO alert_crud_journal VALUES(?,?,?,?,?,?,0,?)',(request['request_id'],fp,before,after,encode(new),encode(changes),now));db.commit()
        # Durable journal enables repair if the process dies before JSON export.
        db.execute('BEGIN IMMEDIATE');recover(db,path)
        actual=validate(json.loads(path.read_text()))
        if digest(actual)!=after:raise ValueError('Readback mismatch')
        return {'status':'applied','before_sha':before,'after_sha':after,'changes':changes,'remote_saved':False}
    finally:db.close()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['list','validate','apply','recover']);p.add_argument('--rules',required=True,type=Path);p.add_argument('--db',type=Path);p.add_argument('--request',type=Path);p.add_argument('--ticker');p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    if a.command in ('list','validate'):
        d=validate(json.loads(a.rules.read_text()));rows=[dict(r,rule_sha256=digest(r)) for r in d['alerts'] if not a.ticker or r['ticker']==a.ticker]
        out={'sha256':digest(d),'count':len(d['alerts']),'rules':rows if a.command=='list' else []}
    elif a.command=='apply':out=apply(a.rules.resolve(),a.db.resolve(),json.loads(a.request.read_text()),a.dry_run)
    else:
        db=connect(a.db.resolve());db.execute('BEGIN IMMEDIATE');recover(db,a.rules.resolve());db.close();out={'status':'recovered'}
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,TypeError,decimal.InvalidOperation,sqlite3.Error,OSError) as e:
        print(json.dumps({'status':'error','error':str(e)},ensure_ascii=False));raise SystemExit(2)
