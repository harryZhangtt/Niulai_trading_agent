#!/usr/bin/env python3
"""Atomic local registration of reviewed research; guarded remote save remains required.
Input: {run_id, items:[{completion_item:path, decision:path, task_id, lease_token,
input_revisions, baseline_refs:[], baseline_gap, analysis_date, evidence_ids?:{source_id:id}}]}.
No executor, implicit lease acquisition, source revision rewriting or remote writes.
"""
import argparse, hashlib, json, re
from datetime import datetime,timezone
from pathlib import Path
import research_store as store
import research_completion as completion
import task_queue as queue

class RegistrationError(ValueError): pass

def digest(value): return hashlib.sha256(store.encode(value).encode()).hexdigest()
def load(path): return json.loads(Path(path).read_text())
def merge(old,new): return dict(json.loads(old['payload']) if old else {}, **new)

def source_cutoff(source):
    """Preserve unknown publication dates; never parse dates from prose/filenames."""
    retrieved=store.instant(source.get('retrieved_at'))
    def parsed(value):
        store.text(value,'source date')
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        return store.instant(value)
    for key in ('data_asof','published_at'):
        if source.get(key) is not None and parsed(source[key])>retrieved:
            raise RegistrationError(key+' follows retrieval; source chronology invalid')
    if source.get('data_asof') is not None:return source['data_asof'],'explicit_data_asof'
    if source.get('published_at') is not None:return source['published_at'],'publication'
    return source['retrieved_at'],'retrieved_observation_publication_unknown'

def register(db,request,now=None,_fault=None):
    run=store.text(request.get('run_id'),'run_id')
    if not request.get('items'): raise RegistrationError('Nonempty items required')
    prepared=[];seen=set()
    for spec in request['items']:
        item=load(spec['completion_item']);ticker=item['ticker']
        if ticker in seen: raise RegistrationError('Duplicate ticker')
        seen.add(ticker)
        checked=completion.inspect_record(item,run)
        rec=load(item['record']['path']);decision=load(spec['decision'])
        if decision.get('ticker')!=ticker or decision.get('action')!=item.get('action'):
            raise RegistrationError('Audited decision identity/action differs from completion item')
        decision_hash=hashlib.sha256(Path(spec['decision']).read_bytes()).hexdigest()
        if not any(a.get('sha256')==decision_hash for a in rec['artifacts']):
            raise RegistrationError('Decision is not an unchanged audited artifact; renewed review/supersession required')
        reports=[a for a in rec['artifacts'] if a.get('kind')=='report']
        report_ids={a['id'] for a in reports}
        publications=[p for p in item['persistence_readbacks'] if p['artifact_id'] in report_ids]
        if len(publications)!=1: raise RegistrationError('Exactly one verified report publication required')
        pub=publications[0]
        prepared.append((spec,item,rec,decision,checked,pub))
    db.execute('BEGIN IMMEDIATE');tx=db;out=[]
    try:
        for spec,item,rec,decision,checked,pub in prepared:
            ticker=item['ticker'];sid=run+':'+ticker;rid=sid+':assessment'
            job=queue.read(tx,spec['task_id'])
            if not job or job['run_id']!=run or job['ticker']!=ticker or job['id']!=queue.task_id(dict(request,input_hash=item['input_hash']),ticker):
                raise RegistrationError('Queue identity/input mismatch')
            # Freeze semantic registration input independently of lease token and time.
            fingerprint=digest({'item':item,'decision':decision,'baseline_refs':spec.get('baseline_refs',[]),
                'baseline_gap':spec.get('baseline_gap'),'input_revisions':spec['input_revisions'],
                'analysis_date':spec['analysis_date'],'evidence_ids':spec.get('evidence_ids',{})})
            if job['state']=='completed':
                prior=job.get('result') or {}
                if prior.get('registration_fingerprint')!=fingerprint:
                    raise RegistrationError('Completed task differs or is legacy-unbound; explicit supersession/new task required')
                assessment=store.read(tx,rid)
                if not assessment or assessment['revision']!=prior['assessment_revision'] or assessment['state']!='active':
                    raise RegistrationError('Completed task assessment has changed; explicit supersession required')
                for ref in assessment['payload']['evidence_refs']:
                    ev=store.read(tx,ref['id'])
                    if not ev or ev['state']!='active' or ev['revision']!=ref['revision']:
                        raise RegistrationError('Completed task evidence superseded; new research task required')
                aid=pub['file_id']
                artifact=tx.execute('SELECT version FROM artifacts WHERE library_file_id=?',(aid,)).fetchone()
                section=tx.execute('SELECT artifact_id,payload FROM research_sections WHERE id=?',(sid,)).fetchone()
                relationship=tx.execute('SELECT 1 FROM security_artifact_relations WHERE security_symbol=? AND artifact_id=? AND section_id=? AND relationship=?',(ticker,aid,sid,'research')).fetchone()
                if (not artifact or str(artifact['version'])!=str(pub['version']) or not section or
                    section['artifact_id']!=aid or ticker not in json.loads(section['payload']).get('symbols',[]) or not relationship):
                    raise RegistrationError('Completed task catalog is missing or inconsistent; explicit reconciliation required')
                out.append({'ticker':ticker,'idempotent_replay':True,'assessment_revision':assessment['revision']});continue
            # Check fencing before any writes, again at finish.
            if job['state']!='running' or job['token']!=spec['lease_token'] or job['lease_until']<=queue.clock(now):
                raise RegistrationError('Invalid or expired queue lease')
            refs=[];operations=[]
            for source in rec['sources']:
                eid=spec.get('evidence_ids',{}).get(source['id'],sid+':source:'+source['id'])
                prior=store.read(tx,eid)
                if prior:
                    if prior['kind']!='evidence' or prior['ticker']!=ticker or prior['state']!='active' or prior['payload'].get('source_record')!=source:
                        raise RegistrationError('Existing evidence does not match reviewed source; explicit evidence CRUD required')
                    revision=prior['revision']
                else:
                    cutoff,cutoff_basis=source_cutoff(source)
                    payload={'claim':'\n'.join(p['text'] for p in source['passages']),'source_url':source['url'],
                        'source_cutoff':cutoff,'source_cutoff_basis':cutoff_basis,
                        'published_at':source.get('published_at'),'retrieved_at':source['retrieved_at'],
                        'source_type':source.get('source_type'),'library_file_id':pub['file_id'],'library_version':pub['version'],
                        'source_record':source,'price_cutoff':rec['subject']['quote_timestamp']}
                    operations.append({'id':eid,'ticker':ticker,'kind':'evidence','expected_revision':0,'action':'put','payload':payload})
                    revision=1
                refs.append({'id':eid,'revision':revision})
            payload={'status':'completed','baseline_refs':spec.get('baseline_refs',[]),'baseline_gap':spec.get('baseline_gap'),
                'input_revisions':spec['input_revisions'],'evidence_refs':refs,'decision':decision,'research_record':rec,
                'independent_checks':checked,'report_library_file_id':pub['file_id'],'report_version':pub['version'],
                'report_archive_member':pub.get('archive_member'),'completion_item':item}
            prior=store.read(tx,rid)
            if prior and prior['payload']!=payload:
                raise RegistrationError('Existing assessment differs; explicit supersession required')
            if not prior: operations.append({'id':rid,'ticker':ticker,'kind':'assessment','expected_revision':0,'action':'put','payload':payload})
            if operations: store.commit(tx,{'request_id':sid+':register:'+fingerprint,'run_id':run,'operations':operations},manage_transaction=False)
            if _fault: _fault('after_assessment',ticker)
            aid=pub['file_id'];artold=tx.execute('SELECT * FROM artifacts WHERE library_file_id=?',(aid,)).fetchone()
            artifact=merge(artold,{'id':aid,'library_file_id':aid,'version_id':pub['version'],'name':Path(pub['content']['path']).name,
                'status':'complete','canonical_bytes_sha256':pub['content']['sha256']})
            artifact['research_section_ids']=sorted(set(artifact.get('research_section_ids',[])+[sid]))
            tx.execute('INSERT INTO artifacts VALUES(?,?,?,?,?) ON CONFLICT(library_file_id) DO UPDATE SET version=excluded.version,filename=excluded.filename,status=excluded.status,payload=excluded.payload',
                (aid,pub['version'],artifact['name'],'complete',store.encode(artifact)))
            tx.execute('INSERT OR IGNORE INTO securities VALUES(?,?,?)',(ticker,None,store.encode({'symbol':ticker,'security_type':rec['subject']['security_type']})))
            for old in tx.execute('SELECT id,payload FROM research_sections WHERE id<>?',(sid,)).fetchall():
                p=json.loads(old['payload'])
                if ticker in p.get('current_for_symbols',[]):
                    p['current_for_symbols']=[t for t in p['current_for_symbols'] if t!=ticker]
                    p.setdefault('superseded_by_for_symbols',{})[ticker]=sid
                    tx.execute('UPDATE research_sections SET payload=? WHERE id=?',(store.encode(p),old['id']))
            old=tx.execute('SELECT payload FROM research_sections WHERE id=?',(sid,)).fetchone()
            section=merge(old,{'id':sid,'artifact_id':aid,'symbols':[ticker],'current_for_symbols':[ticker],
                'analysis_date':spec['analysis_date'],'status':'complete','source_cutoff_utc':rec['subject']['cutoff'],
                'market_price_cutoff_utc':rec['subject']['quote_timestamp'],'archive_member':pub.get('archive_member'),
                'policy_version':rec['policy_versions'],'limitations':rec['model'].get('limitations',[]),'full_run_id':run})
            tx.execute('INSERT INTO research_sections VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET artifact_id=excluded.artifact_id,payload=excluded.payload',(sid,aid,store.encode(section)))
            for old in tx.execute('SELECT rowid,payload FROM security_artifact_relations WHERE security_symbol=?',(ticker,)).fetchall():
                p=json.loads(old['payload']);p.update(is_latest_analysis_for_security=False,superseded_by_section=sid)
                tx.execute('UPDATE security_artifact_relations SET payload=? WHERE rowid=?',(store.encode(p),old['rowid']))
            old=tx.execute('SELECT payload FROM security_artifact_relations WHERE security_symbol=? AND artifact_id=? AND section_id=? AND relationship=?',(ticker,aid,sid,'research')).fetchone()
            rel=merge(old,{'artifact_id':aid,'section_id':sid,'security_id':'security:'+ticker,'relationship':'research','is_latest_analysis_for_security':True})
            rel.pop('superseded_by_section',None)
            tx.execute('INSERT INTO security_artifact_relations VALUES(?,?,?,?,?) ON CONFLICT(security_symbol,artifact_id,section_id,relationship) DO UPDATE SET payload=excluded.payload',(ticker,aid,sid,'research',store.encode(rel)))
            old=tx.execute('SELECT payload FROM securities WHERE symbol=?',(ticker,)).fetchone()
            security=merge(old,{'latest_analysis_section_ids':[sid],'research_status':'complete','status':'researched',
                'valuation_completed':True,'current_valuation_verified':False,'latest_research_date':spec['analysis_date']})
            security.setdefault('id','security:'+ticker)
            tx.execute('UPDATE securities SET payload=? WHERE symbol=?',(store.encode(security),ticker))
            if _fault: _fault('after_registry',ticker)
            revision=store.read(tx,rid)['revision']
            queue.mutate(tx,job['id'],spec['lease_token'],'finish',{'research_status':'complete','completion_item':item,
                'checked':checked,'assessment_revision':revision,'registration_fingerprint':fingerprint},now=now,manage_transaction=False)
            if _fault: _fault('after_queue',ticker)
            out.append({'ticker':ticker,'idempotent_replay':False,'assessment_revision':revision})
        db.commit()
        return {'records':out,'durability':'local_sqlite_only_requires_guarded_library_writeback'}
    except BaseException:
        db.rollback();raise

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',required=True);p.add_argument('--request',required=True)
    a=p.parse_args()
    with store.connect(a.db) as db: print(json.dumps(register(db,load(a.request)),ensure_ascii=False,indent=2))
if __name__=='__main__': main()
