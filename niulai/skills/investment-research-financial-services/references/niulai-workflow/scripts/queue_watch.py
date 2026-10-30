#!/usr/bin/env python3
"""Read-only research queue health. No dispatch, lease renewal, DB write or notification.
The whole-roster research_completion auditor remains the final completion authority.
"""
import argparse,json,hashlib,os,zipfile
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
import research_store as store
import research_completion as completion
import task_queue as queue


def stamp(value):
    return datetime.fromtimestamp(value,timezone.utc).isoformat() if value is not None else None


def checkpoint_content(value):
    # Clock-only checkpoint rewrites must not conceal a stopped pipeline.
    volatile={'timestamp','updated_at','observed_at','heartbeat_at','lease_until','checked_at'}
    if isinstance(value,dict):return {k:checkpoint_content(v) for k,v in value.items() if k not in volatile}
    if isinstance(value,list):return [checkpoint_content(v) for v in value]
    return value


def certified(db,job):
    if job['state']!='completed':return False,'queue_attempt_not_completed'
    if (job.get('result') or {}).get('research_status')!='complete':return False,'completed_attempt_has_incomplete_research'
    assessment=store.read(db,job['run_id']+':'+job['ticker']+':assessment')
    if not assessment or assessment['state']!='active' or assessment['payload'].get('status')!='completed':
        return False,'completed_assessment_missing_or_inactive'
    payload=assessment['payload']
    if job['result'].get('assessment_revision')!=assessment['revision']:return False,'assessment_revision_differs_from_queue_result'
    for ref in payload.get('evidence_refs',[]):
        evidence=store.read(db,ref['id'])
        if not evidence or evidence['state']!='active' or evidence['revision']!=ref['revision']:
            return False,'assessment_evidence_dependency_stale'
    item=payload.get('completion_item')
    if not item:return False,'completion_item_missing'
    try:completion.inspect_record(item,job['run_id'])
    except Exception as exc:return False,'completion_evidence_unverified: '+type(exc).__name__+': '+str(exc)
    return True,None


def phase_certified(db,job,archives):
    """Verify narrow stages against recovered Library archives.

    Prefer the exact saved version. A bounded-triage card may also be recovered
    from a later cumulative version of the same Library file, but only when the
    immutable card and review hashes match the frozen queue result. Targeted
    stages retain exact-version and whole-archive bindings. Accepted stages
    never certify a full recommendation.
    """
    # An authorized continuation may finish full research under its frozen
    # narrow task identity. Require the full auditor, never rewrite that identity.
    if (job.get('result') or {}).get('research_status')=='complete':
        return certified(db,job)
    phase=job.get('payload',{}).get('phase')
    if phase not in ('bounded_triage','targeted_followup'):
        return certified(db,job)
    if job['state']!='completed':return False,'queue_attempt_not_completed'
    try:
        result=job.get('result') or {};bundle=result['bundle']
        store.instant(result['readback_confirmed_at'])
        if phase=='bounded_triage':
            if result.get('research_status')!='screened_not_full' or result.get('screening_complete') is not True:raise ValueError('screen status invalid')
            member=job['ticker']+'/card.json';review_member=job['ticker']+'/parent_review.json';hash_key='card_sha256'
        else:
            if result.get('research_status')!='targeted_partial_not_full' or result.get('targeted_stage_complete') is not True:raise ValueError('targeted status invalid')
            hash_key='result_sha256'
        exact=[];later=[]
        for path in archives:
            path=Path(path)
            try:
                identity=os.getxattr(path,'user.library-file-id').decode()
                version=int(os.getxattr(path,'user.library-file-version').decode())
            except (OSError,ValueError):continue
            if identity!=bundle['library_file_id']:continue
            if version==int(bundle['version']):exact.append(path)
            elif phase=='bounded_triage' and version>int(bundle['version']):later.append((version,path))
        if len(exact)==1:archive=exact[0]
        elif not exact and phase=='bounded_triage':
            matching=[]
            for version,path in later:
                try:
                    with zipfile.ZipFile(path) as candidate:
                        raw=candidate.read(member);review=json.loads(candidate.read(review_member))
                    h=hashlib.sha256(raw).hexdigest()
                    if h==result[hash_key] and review.get(hash_key)==h:matching.append((version,path))
                except (KeyError,ValueError,TypeError,OSError,zipfile.BadZipFile,json.JSONDecodeError):continue
            if matching:
                latest=max(v for v,_ in matching);selected=[p for v,p in matching if v==latest]
            else:selected=[]
            if len(selected)!=1:raise ValueError('exact-version or exact-member cumulative Library archive missing or ambiguous')
            archive=selected[0]
        else:raise ValueError('exact-version Library archive missing or ambiguous')
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        with zipfile.ZipFile(archive) as z:
            if phase=='bounded_triage':
                pass
            else:
                a=store.read(db,result['assessment_id'])
                if not a or a['state']!='active' or a['revision']!=result['assessment_revision']:raise ValueError('assessment revision inactive or stale')
                ap=a['payload'];pub=ap['publication']
                if a['run_id']!=job['run_id'] or a['ticker']!=job['ticker'] or ap['status']!='partial':raise ValueError('assessment scope invalid')
                if any(pub[k]!=bundle[k] for k in ('library_file_id','version')) or pub['archive_sha256']!=digest or pub['readback_confirmed_at']!=result['readback_confirmed_at']:raise ValueError('publication binding mismatch')
                if not ap.get('next_action') or not ap.get('reopening_condition'):raise ValueError('followup disposition missing')
                refs=ap.get('evidence_refs',[])
                if not refs:raise ValueError('evidence missing')
                evidence=[]
                for ref in refs:
                    e=store.read(db,ref['id'])
                    if not e or e['state']!='active' or e['revision']!=ref['revision'] or e['run_id']!=job['run_id'] or e['ticker']!=job['ticker']:raise ValueError('evidence dependency stale')
                    evidence.append(e['payload'])
                e=evidence[0];member=e['archive_member'];review_member=str(Path(member).parent/'parent_review.json');hash_key='result_sha256'
                if e['library_file_id']!=bundle['library_file_id'] or e['library_version']!=bundle['version'] or e[hash_key]!=result[hash_key]:raise ValueError('evidence publication mismatch')
            raw=z.read(member);card=json.loads(raw);review=json.loads(z.read(review_member));h=hashlib.sha256(raw).hexdigest()
            if h!=result[hash_key] or review.get(hash_key)!=h or review.get('accepted') is not True or not review.get('reviewer') or not review.get('checks'):raise ValueError('review binding missing or changed')
            store.instant(review['at'])
            if card.get('ticker')!=job['ticker'] or card.get('research_complete') is not False:raise ValueError('stage scope mismatch')
            if phase=='targeted_followup':
                if card!=e['result'] or review!=ap['review']:raise ValueError('saved evidence or review differs')
                if card.get('card_hash',card.get('parent_card_hash'))!=job['payload'].get('card_hash'):raise ValueError('parent card changed')
            required=('source_refs','baseline_status','route','reason','reopening_condition','remaining_gaps') if phase=='bounded_triage' else ('source_refs','next_action','reopening_condition','remaining_gaps')
            for field in required:
                if field not in card or card[field] is None:raise ValueError('missing '+field)
            if not card['source_refs']:raise ValueError('source evidence missing')
            for ref in card['source_refs']:
                if hashlib.sha256(Path(ref['path']).read_bytes()).hexdigest()!=ref['sha256']:raise ValueError('source hash mismatch')
            if phase=='bounded_triage' and card['route']!=result['route']:raise ValueError('route mismatch')
            verify_calculations(card.get('calculations') or {})
        return True,None
    except (KeyError,ValueError,TypeError,OSError,zipfile.BadZipFile) as exc:
        return False,'stage_evidence_unverified: '+str(exc)


def verify_calculations(calculations):
    if not isinstance(calculations,dict):return
    # Earlier saved reuse records named the same hashed artifact reused_path.
    # Accept that explicit alias without editing immutable evidence or skipping hashes.
    if calculations.get('path') and calculations.get('reused_path'):
        if Path(calculations['path']).resolve()!=Path(calculations['reused_path']).resolve():
            raise ValueError('ambiguous calculation artifact paths')
    for pathkey,hashkey in (('path','sha256'),('script_path','script_sha256'),('receipt_path','receipt_sha256')):
        if not calculations.get(hashkey):continue
        path=calculations.get(pathkey)
        if pathkey=='path' and not path:path=calculations.get('reused_path')
        if not path:raise ValueError('calculation artifact path missing')
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=calculations[hashkey]:
            raise ValueError('calculation artifact hash mismatch')


def supersessions(db,groups,now):
    """Only explicit, verified full-roster inheritance suppresses old work."""
    valid={};warnings=[]
    columns={r[1] for r in db.execute('PRAGMA table_info(job_runs)')}
    if not {'kind','status','payload'}<=columns:return valid,warnings
    for row in db.execute("SELECT payload FROM job_runs WHERE kind='research_run_supersession' AND status='skipped'"):
        try:
            item=json.loads(row['payload']);old=item['superseded_run_id'];new=item['successor_run_id']
            expected=item['expected_tickers']
            if not isinstance(expected,list) or not expected or any(not isinstance(t,str) or not t for t in expected):
                raise ValueError('invalid expected roster')
            if old==new or old not in groups or new not in groups:raise ValueError('missing or identical successor')
            if item.get('predecessor_is_complete') is not False:raise ValueError('supersession must not assert completion')
            if store.instant(item['finished_at']).timestamp()>now:raise ValueError('future supersession')
            predecessor={j['ticker'] for j in groups[old]}
            successor={j['ticker'] for j in groups[new] if j['state']!='cancelled'}
            if not predecessor<=set(expected)<=successor:raise ValueError('successor does not cover full expected predecessor roster')
            if old in valid and valid[old]['successor_run_id']!=new:raise ValueError('conflicting successors')
            valid[old]={'run_id':old,'reason':'explicitly_superseded','successor_run_id':new,
                'history_only':True,'predecessor_is_complete':False,'tasks':len(groups[old]),'resume_candidates':[]}
        except (KeyError,TypeError,ValueError) as exc:
            warnings.append({'reason':'invalid_supersession','detail':str(exc)})
    # Reject cycles rather than hiding every member of a circular inheritance claim.
    cyclic=set()
    for start in valid:
        seen=set();cursor=start
        while cursor in valid:
            if cursor in seen:cyclic.update(seen);break
            seen.add(cursor);cursor=valid[cursor]['successor_run_id']
    for run_id in cyclic:
        del valid[run_id];warnings.append({'reason':'invalid_supersession','run_id':run_id,'detail':'cyclic inheritance'})
    return valid,warnings


def watch(db,now=None,stall_seconds=3600,phase_archives=()):
    # A read transaction gives all queries one consistent SQLite snapshot.
    owns_snapshot=not db.in_transaction
    if owns_snapshot:db.execute('BEGIN')
    try:return _watch(db,now,stall_seconds,phase_archives)
    finally:
        if owns_snapshot:db.rollback()


def _watch(db,now=None,stall_seconds=3600,phase_archives=()):
    now=queue.clock(now)
    if isinstance(stall_seconds,bool) or not isinstance(stall_seconds,(int,float)) or stall_seconds<=0:
        raise ValueError('Positive stall interval required')
    jobs=queue.read(db);groups=defaultdict(list);by_id={j['id']:j for j in jobs}
    for job in jobs:groups[job['run_id']].append(job)
    progress=defaultdict(list);seen={}
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'taskq_events' in tables:
        for event in db.execute("SELECT task_id,event,payload,occurred_at FROM taskq_events WHERE event IN ('checkpoint','finish') ORDER BY seq"):
            job=by_id.get(event['task_id'])
            if not job or event['occurred_at']>now:continue
            if event['event']=='checkpoint':
                content=store.encode(checkpoint_content(json.loads(event['payload'])))
                if seen.get(event['task_id'])==content:continue
                seen[event['task_id']]=content
            progress[job['run_id']].append((event['occurred_at'],event['event']))
    if 'research_store_revisions' in tables:
        for row in db.execute('SELECT run_id,recorded_at FROM research_store_revisions'):
            moment=store.instant(row['recorded_at']).timestamp()
            if moment<=now:progress[row['run_id']].append((moment,'research_registration'))
    inherited,warnings=supersessions(db,groups,now)
    runs=[];excluded=[]
    for run_id,roster in sorted(groups.items()):
        if run_id in inherited:
            excluded.append(inherited[run_id]);continue
        states=Counter(j['state'] for j in roster)
        if states['cancelled']==len(roster):
            excluded.append({'run_id':run_id,'reason':'all_tasks_cancelled','tasks':len(roster)});continue
        selected=[j for j in roster if j['state']!='cancelled']
        active=[j for j in selected if j['state']=='running' and j.get('lease_until') is not None and j['lease_until']>now]
        expired=[j for j in selected if j['state']=='running' and (j.get('lease_until') is None or j['lease_until']<=now)]
        passed=[];full_passed=[];issues=[];candidates=[]
        phases={j.get('payload',{}).get('phase','full_research') for j in selected}
        narrow=bool(phases and phases <= {'bounded_triage','targeted_followup'})
        for job in selected:
            valid,reason=phase_certified(db,job,phase_archives)
            if valid:
                passed.append(job['ticker'])
                if (job.get('result') or {}).get('research_status')=='complete' or job.get('payload',{}).get('phase') not in ('bounded_triage','targeted_followup'):full_passed.append(job['ticker'])
                continue
            state=job['state']
            reason=reason if state=='completed' else 'expired_running_lease' if job in expired else job.get('error') or state
            issues.append({'ticker':job['ticker'],'reason':reason})
            if job not in active:
                action='reclaim_expired_task' if job in expired else 'claim_pending_task' if state=='pending' else 'resolve_dependency' if state=='blocked' else 'explicit_continuation_or_supersession'
                candidates.append({'ticker':job['ticker'],'task_id':job['id'],'state':state,'action':action,'automatic_dispatch':False})
        last=max(progress.get(run_id,[]),default=(None,None))
        created=min(j['created_at'] for j in selected)
        idle_since=last[0] if last[0] is not None else created
        unfinished=len(selected)-len(passed)
        orphaned=bool(unfinished and not active and (states['pending'] or expired))
        stalled=bool(unfinished and now-idle_since>=stall_seconds)
        health=('assigned_stage_verified' if narrow else 'await_final_completion_audit') if not unfinished else 'stalled' if stalled else 'orphaned' if orphaned else 'in_progress'
        runs.append({'run_id':run_id,'health':health,'total_tasks':len(roster),'selected_tasks':len(selected),
            'queue_completed':states['completed'],'certified_assessments':len(full_passed),'certified_tickers':full_passed,
            'stage_accepted':len(passed),'stage_accepted_tickers':passed,'phases':sorted(phases),'full_research_complete':False,
            'unfinished':unfinished,'pending':states['pending'],'valid_leases':len(active),'expired_running':len(expired),
            'blocked':states['blocked'],'failed':states['failed'],'cancelled':states['cancelled'],
            'orphaned':orphaned,'stalled':stalled,'last_material_progress_at':stamp(last[0]),'last_progress_kind':last[1],
            'idle_since':stamp(idle_since),'idle_minutes':round(max(0,now-idle_since)/60,2),'issues':issues,
            'resume_candidates':candidates,'requires_status_notification':bool(unfinished),
            'completion_authority':'exact-version narrow-stage evidence audit; not full research' if narrow else 'research_completion.py whole-roster audit','agent_liveness':'not_inferred_from_lease'})
    return {'as_of':stamp(now),'read_only':True,'runs':runs,'excluded_runs':excluded,'warnings':warnings,
        'semantics':'Lease is a lock, not proof of a live agent. This health check does not declare a full run COMPLETE.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',required=True);p.add_argument('--as-of');p.add_argument('--stall-minutes',type=float,default=60);p.add_argument('--output');p.add_argument('--phase-archive',action='append',default=[],help='Exact-version recovered Library ZIP with identity/version xattrs; repeat for each version');a=p.parse_args()
    now=store.instant(a.as_of).timestamp() if a.as_of else None
    with store.connect(a.db,readonly=True) as db:result=watch(db,now,a.stall_minutes*60,a.phase_archive)
    encoded=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if a.output:Path(a.output).write_text(encoded)
    print(encoded,end='')
if __name__=='__main__':main()
