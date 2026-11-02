"""Host checks source/state directly; worker pass labels are not authoritative."""
from collections import Counter
import hashlib
from pathlib import Path
import sqlite3

from shared.research_sources.artifacts import digest, read
from shared.research_sources.indexing import RecordIndex

CASES=['roster_complete','raw_roundtrip','entity_retrieval','access_level_preserved',
       'replay_idempotent','twenty_thousand_replays','concurrent_writes','snapshot_revision_race',
       'future_and_unknown_time','source_unchanged']


def grade(case_id, inputs, expected, output):
    result=read(output['result_ref']);roster=read(inputs['roster_ref']);records=roster['records']
    idx=RecordIndex(result['index_directory'])
    rows=idx.store.find(limit=1000)
    if case_id=='roster_complete':
        ok=len(rows)==len(records)==len(result['initial']) and {r['payload']['record_hash'] for r in rows}=={digest(r) for r in records}
        imported=read(result['import_result_ref'])
        ok=ok and read(imported['roster_ref'])==roster and imported['indexed']==len(records)
    elif case_id=='raw_roundtrip':
        ok=all(read(read(r['payload']['source_ref'])['raw'])==r['payload']['content'] for r in rows)
    elif case_id=='entity_retrieval':
        ok=len(result['queries'])==len({r['entity'] for r in records})
        for q in result['queries']:
            selected=read(q['selection_ref']);wanted={digest(r) for r in records if r['entity']==q['entity']}
            ok=ok and {r['record_hash'] for r in selected['candidates']}==wanted
            snapshot=idx.store.read_snapshot(q['snapshot_id'])['manifest']
            ok=ok and snapshot['bindings']==[r['binding'] for r in selected['candidates']]
    elif case_id=='access_level_preserved':
        ok=all(r['payload']['content_access'] in {'metadata_only','secondary_note'} and
               r['payload']['semantic_verification']=='not_performed' and r['payload']['available_at'] is None for r in rows)
    elif case_id=='replay_idempotent':
        ok=all(r['route']=='reused' for r in result['replay']) and all(r['revision']==1 for r in rows)
        with sqlite3.connect(idx.store.path.resolve().as_uri()+'?mode=ro',uri=True) as db:
            ok=ok and db.execute('SELECT count(*) FROM observations').fetchone()[0]==len(records)
    elif case_id=='twenty_thousand_replays':
        ok=result['stress']['operations']==20000 and result['stress']['routes']=={'reused':20000} and all(r['revision']==1 for r in rows)
    elif case_id=='concurrent_writes':
        c=result['concurrent'];wanted=read(c['expected_records_ref']);ci=RecordIndex(c['directory'])
        actual=ci.store.find(limit=1000)
        ok=len(c['children'])==4 and all(r['returncode']==0 and not r['stderr_present'] for r in c['children'])
        ok=ok and len(actual)==len(wanted) and all(r['revision']==1 for r in actual)
        ok=ok and sum(r['routes'].get('created',0) for r in c['children'])==len(wanted)
        ok=ok and sum(sum(r['routes'].values()) for r in c['children'])==4*len(wanted)
        with sqlite3.connect(ci.store.path.resolve().as_uri()+'?mode=ro',uri=True) as db:
            ok=ok and db.execute('SELECT count(*) FROM observations').fetchone()[0]==len(wanted)
    elif case_id=='snapshot_revision_race':
        p=result['revision_probe'];pi=RecordIndex(p['directory'])
        snapshot=pi.store.read_snapshot(p['original_snapshot']['snapshot_id'])['manifest']
        oid=p['first']['binding']['observation_id']
        ok=p['stale_error']=='SNAPSHOT_DEPENDENCY_CHANGED' and snapshot['bindings'][0]['revision']==1 and pi.store.read(oid)['revision']==2
        with sqlite3.connect(pi.store.path.resolve().as_uri()+'?mode=ro',uri=True) as db:
            ok=ok and db.execute('SELECT count(*) FROM snapshots').fetchone()[0]==1
    elif case_id=='future_and_unknown_time':
        s=result['revision_probe']['temporal_selection']
        ok=len(s['excluded'])==1 and s['excluded'][0]['reason']=='available_after_cutoff' and len(s['candidates'])==1
        ok=ok and 'availability_unknown' in s['candidates'][0]['limitations']
    elif case_id=='source_unchanged':
        ok=result['source_sha256_before']==result['source_sha256_after']==hashlib.sha256(Path(result['source_path']).read_bytes()).hexdigest()
    else:raise ValueError('unknown case')
    return {'passed':bool(ok),'metrics':{'checks_passed':int(bool(ok)),
        'indexed_records':len(records),'elapsed_seconds':result['elapsed_seconds'],
        'peak_rss_bytes':result['peak_rss_bytes'],'model_tokens':None,'model_cost':None},
        'reasons':[] if ok else ['CATALOG_INDEX_POSTCONDITION_FAILED']}
