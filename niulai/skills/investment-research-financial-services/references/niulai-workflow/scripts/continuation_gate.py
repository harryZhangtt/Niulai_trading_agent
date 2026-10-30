#!/usr/bin/env python3
"""Read-only pre-return gate. Stage completion is not completion of the user's goal.
Exit 2 means keep working. This script neither dispatches agents nor controls runtime.
"""
import argparse, hashlib, json
from pathlib import Path
import research_store as store
import task_queue as queue
import queue_watch
import research_completion


def disposition(ref, job, now):
    """Check durable task-bound reasons; an arbitrary 'pending' label is insufficient."""
    if not ref:
        return None
    raw=Path(ref['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ref['sha256']:
        raise ValueError('disposition evidence changed')
    d=json.loads(raw)
    if d.get('task_id')!=job['id'] or d.get('task_fingerprint')!=job['fingerprint']:
        raise ValueError('disposition identity mismatch')
    if not d.get('reason') or not d.get('reopening_condition'):
        raise ValueError('disposition lacks reason/reopening condition')
    if store.instant(d['recorded_at']).timestamp()>now:
        raise ValueError('future disposition')
    kind=d.get('kind')
    if kind=='user_hold':
        if not d.get('user_instruction') or not d.get('scope'):
            raise ValueError('user hold needs explicit instruction and scope')
    elif kind=='event_wait':
        if not d.get('evidence_refs') or d.get('independent_work_remaining') is not False:
            raise ValueError('event wait cannot hide independent work')
        for evidence in d['evidence_refs']:
            if hashlib.sha256(Path(evidence['path']).read_bytes()).hexdigest()!=evidence['sha256']:
                raise ValueError('event evidence changed')
        if store.instant(d['recheck_at']).timestamp()<=now:
            return None
    elif kind=='external_blocked':
        if d.get('independent_work_remaining') is not False or not d.get('attempts'):
            raise ValueError('external block needs attempts and no independent remaining work')
        for ref in d['attempts']:
            a=json.loads(research_completion.hashed(ref))
            if a.get('obstacle_type') not in ('access_denied','source_not_disclosed','upstream_unavailable','runtime_limit') or not a.get('detail'):
                raise ValueError('unsupported external attempt')
            if store.instant(a['attempted_at']).timestamp()>now:
                raise ValueError('future attempt')
    else:
        raise ValueError('pending/budget/uncertainty is not a stop disposition')
    return kind


def inspect_jobs(jobs, request, now, phase_check):
    expected=request.get('task_ids')
    if not isinstance(expected,list) or not expected or len(expected)!=len(set(expected)):
        raise ValueError('nonempty unique explicit task_ids required')
    by_id={j['id']:j for j in jobs}
    if any(i not in by_id for i in expected):raise ValueError('selected task missing')
    rows=[]
    for identifier in expected:
        j=by_id[identifier]
        if j['state']=='cancelled':
            rows.append({'task_id':identifier,'ticker':j['ticker'],'disposition':'cancelled','must_continue':False});continue
        stop=disposition(request.get('dispositions',{}).get(identifier),j,now)
        if stop:
            rows.append({'task_id':identifier,'ticker':j['ticker'],'disposition':stop,'must_continue':False});continue
        accepted,reason=phase_check(j)
        narrow=j.get('payload',{}).get('phase') in ('bounded_triage','targeted_followup') and (j.get('result') or {}).get('research_status')!='complete'
        action=('execute_next_stage' if accepted and narrow else 'run_full_completion_audit' if accepted else
                'restore_or_repair_evidence' if j['state']=='completed' else 'continue_or_recover_selected_work')
        rows.append({'task_id':identifier,'ticker':j['ticker'],'assigned_stage_verified':accepted,
            'disposition':action,'must_continue':True,'reason':reason,
            'next_action':(j.get('result') or {}).get('next_action'),
            'lease_is_not_worker_proof':True})
    return rows


def gate(db,request,archives=(),now=None):
    now=queue.clock(now)
    rows=inspect_jobs(queue.read(db),request,now,lambda j:queue_watch.phase_certified(db,j,archives))
    # Only the existing full auditor can certify a recommendation. Bind its roster
    # to this selection; an unrelated successful manifest cannot clear the gate.
    manifest=request.get('completion_manifest')
    full=None
    if manifest:
        full=json.loads(Path(manifest).read_text())
        selected={r['ticker'] for r in rows if r['disposition']!='cancelled'}
        if set(full.get('expected_tickers',[]))!=selected:raise ValueError('completion roster mismatch')
        selected_jobs=[j for j in queue.read(db) if j['id'] in request['task_ids'] and j['state']!='cancelled']
        if any(j['run_id']!=full.get('run_id') for j in selected_jobs):raise ValueError('completion run mismatch')
        if Path(full['queue_db']).resolve()!=Path(db.execute('PRAGMA database_list').fetchone()[2]).resolve():
            raise ValueError('completion database mismatch')
        result=research_completion.audit(full)
        if result.get('status')=='COMPLETE':
            for row in rows:row.update(must_continue=False,disposition='full_research_complete')
    pending=[r for r in rows if r['must_continue']]
    return {'status':'CONTINUE_REQUIRED' if pending else 'SAFE_TO_RETURN',
        'may_end_turn':not pending,'selected':len(rows),'actionable':len(pending),'items':rows,
        'semantics':'SAFE_TO_RETURN can mean documented wait/block/cancellation, not research complete. No runtime or delivery guarantee.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',required=True);p.add_argument('--request',required=True)
    p.add_argument('--phase-archive',action='append',default=[]);p.add_argument('--output');a=p.parse_args()
    request=json.loads(Path(a.request).read_text())
    with store.connect(a.db,readonly=True) as db:r=gate(db,request,a.phase_archive)
    text=json.dumps(r,ensure_ascii=False,indent=2)+'\n'
    if a.output:Path(a.output).write_text(text)
    print(text,end='');raise SystemExit(0 if r['may_end_turn'] else 2)
if __name__=='__main__':main()
