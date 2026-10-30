import copy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from research_store import StoreError, commit, connect, export, read, read_ticker_current


def evidence(rid='ev:AAA', ticker='AAA'):
    return {'id': rid, 'ticker': ticker, 'kind': 'evidence', 'action': 'put', 'expected_revision': 0,
            'payload': {'claim': 'Fixture only', 'source_url': 'https://example.org/filing',
                        'source_cutoff': '2026-01-01', 'retrieved_at': '2026-01-02T12:00:00Z'}}


def assessment():
    return {'id': 'assessment:AAA', 'ticker': 'AAA', 'kind': 'assessment', 'action': 'put', 'expected_revision': 0,
            'payload': {'status': 'partial', 'evidence_refs': [{'id': 'ev:AAA', 'revision': 1}],
                        'baseline_refs': [], 'baseline_gap': 'Fixture has no prior model',
                        'input_revisions': {'config': 8}, 'unresolved': ['model unavailable']}}


def request(*ops, key='req1'):
    return {'request_id': key, 'run_id': 'run:test', 'operations': list(ops)}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'research.sqlite'
        db = sqlite3.connect(self.path)
        for table in ('securities', 'artifacts', 'job_runs'):
            db.execute('CREATE TABLE '+table+'(id TEXT PRIMARY KEY,payload TEXT)')
            db.execute('INSERT INTO '+table+' VALUES(?,?)', ('preserved', '{}'))
        db.commit(); db.close()
        self.db = connect(self.path)

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def test_create_and_retry(self):
        req = request(evidence())
        first = commit(self.db, req); again = commit(self.db, req)
        self.assertFalse(first['idempotent_replay']); self.assertTrue(again['idempotent_replay'])
        self.assertEqual(len(export(self.db)['records']), 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM artifacts').fetchone()[0], 1)

    def test_conflicting_idempotency_key(self):
        commit(self.db, request(evidence()))
        req = request(evidence()); req['operations'][0]['payload']['claim'] = 'different'
        with self.assertRaisesRegex(StoreError, 'different content'): commit(self.db, req)

    def test_revision_and_stale_cas(self):
        op = evidence(); commit(self.db, request(op))
        op['expected_revision'] = 1; op['reason'] = 'Correction'; op['payload']['claim'] = 'corrected'
        commit(self.db, request(op, key='req2'))
        self.assertEqual(read(self.db, op['id'], 1)['payload']['claim'], 'Fixture only')
        self.assertEqual(read(self.db, op['id'])['revision'], 2)
        with self.assertRaisesRegex(StoreError, 'Stale revision'): commit(self.db, request(op, key='req3'))

    def test_atomic_rollback(self):
        bad = evidence('ev:BBB','BBB'); bad['expected_revision'] = 9
        with self.assertRaises(StoreError): commit(self.db, request(evidence(), bad))
        self.assertIsNone(read(self.db, 'ev:AAA'))
        self.assertEqual(export(self.db)['requests'], [])

    def test_assessment_before_evidence(self):
        commit(self.db, request(assessment(), evidence()))
        self.assertTrue(all(r['eligible_for_reuse'] for r in read_ticker_current(self.db, 'AAA')))

    def test_missing_evidence_rolls_back(self):
        with self.assertRaisesRegex(StoreError,'missing'): commit(self.db, request(assessment()))
        self.assertIsNone(read(self.db,'assessment:AAA'))

    def test_retract_and_dependency_invalidation(self):
        commit(self.db, request(evidence(), assessment()))
        retract = {'id':'ev:AAA','ticker':'AAA','kind':'evidence','action':'retract','expected_revision':1,'reason':'Source withdrawn'}
        commit(self.db, request(retract,key='req2'))
        self.assertEqual(read(self.db,'ev:AAA',1)['state'],'active')
        rows=read_ticker_current(self.db,'AAA')
        self.assertFalse(any(r['eligible_for_reuse'] for r in rows))
        op=evidence();op['expected_revision']=2;op['reason']='Revive'
        with self.assertRaisesRegex(StoreError,'revived'):commit(self.db,request(op,key='req3'))

    def test_historical_tables_immutable(self):
        commit(self.db, request(evidence()))
        for sql in ('DELETE FROM research_store_revisions', "UPDATE research_store_revisions SET state='retracted'",'DELETE FROM research_store_requests'):
            with self.assertRaisesRegex(sqlite3.IntegrityError,'immutable'):self.db.execute(sql)
            self.db.rollback()

    def test_provenance_rejection(self):
        for field,value in [('source_url','bad'),('retrieved_at','2026-01-02'),('source_cutoff','2026-03-01')]:
            op=evidence();op['payload'][field]=value
            with self.assertRaises(StoreError):commit(self.db,request(op))

    def test_nonfinite_rejection(self):
        op=evidence();op['payload']['number']=float('nan')
        with self.assertRaises(ValueError):commit(self.db,request(op))

    def test_duplicate_operation_rejected(self):
        with self.assertRaisesRegex(StoreError,'Duplicate'):commit(self.db,request(evidence(),evidence()))

    def test_stable_identity(self):
        commit(self.db,request(evidence()))
        op=evidence(ticker='BBB');op['expected_revision']=1
        with self.assertRaisesRegex(StoreError,'identity'):commit(self.db,request(op,key='req2'))

    def test_cross_ticker_reference(self):
        a=assessment();a['ticker']='BBB'
        with self.assertRaisesRegex(StoreError,'Cross-ticker'):commit(self.db,request(evidence(),a))
        a['payload']['evidence_refs'][0]['cross_ticker_reason']='Shared industry input'
        commit(self.db,request(evidence(),a))

    def test_no_new_evidence_explicit(self):
        a=assessment();a['payload']['evidence_refs']=[];a['payload']['status']='no_new_edge'
        with self.assertRaises(StoreError):commit(self.db,request(a))
        a['payload']['no_new_evidence_reason']='Checked sources, no new evidence found'
        commit(self.db,request(a))

    def test_missing_or_wrong_database(self):
        missing=Path(self.tmp.name)/'missing.sqlite'
        with self.assertRaises(StoreError):connect(missing)
        self.assertFalse(missing.exists())
        empty=Path(self.tmp.name)/'empty.sqlite';sqlite3.connect(empty).close()
        with self.assertRaises(StoreError):connect(empty)

    def test_concurrent_cas_one_winner(self):
        commit(self.db,request(evidence()))
        def update(key):
            op=evidence();op.update(expected_revision=1,reason='Concurrent update')
            with connect(self.path) as db:
                try:commit(db,request(op,key=key));return 'won'
                except StoreError:return 'stale'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(update,['r2','r3']))
        self.assertEqual(sorted(results),['stale','won'])
        self.assertEqual(read(self.db,'ev:AAA')['revision'],2)

    def test_export_round_trip_and_integrity(self):
        commit(self.db,request(evidence(),assessment()))
        self.assertEqual(len(json.loads(json.dumps(export(self.db,'AAA')))['records']),2)
        self.assertEqual(self.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_superseded_evidence_invalidates_assessment(self):
        commit(self.db, request(evidence(),assessment()))
        op=evidence();op.update(expected_revision=1,reason='Source corrected')
        commit(self.db,request(op,key='req2'))
        row=next(r for r in read_ticker_current(self.db,'AAA') if r['kind']=='assessment')
        self.assertIn('evidence_not_current_active:ev:AAA',row['dependency_issues'])
        self.assertFalse(row['eligible_for_reuse'])

    def test_readonly_connection(self):
        with connect(self.path,readonly=True) as db:
            self.assertEqual(read_ticker_current(db,'AAA'),[])
            with self.assertRaises(sqlite3.OperationalError):commit(db,request(evidence()))

    def test_actual_copy_next_planner_inherits_updates(self):
        source=os.environ.get('NIULAI_TEST_RESEARCH_DB')
        if not source:self.skipTest('Set NIULAI_TEST_RESEARCH_DB for real-copy integration')
        from triggered_research import baselines
        target=Path(self.tmp.name)/'loop-copy.sqlite';shutil.copy2(source,target)
        before=baselines(target,['MRVL'])['MRVL']
        e=evidence('ev:MRVL','MRVL');a=assessment()
        a.update(id='assessment:MRVL',ticker='MRVL')
        a['payload']['evidence_refs']=[{'id':'ev:MRVL','revision':1}]
        with connect(target) as db:commit(db,request(e,a))
        after=baselines(target,['MRVL'])['MRVL']
        self.assertEqual(len(after['incremental_records']),2)
        self.assertEqual(before['artifacts'],after['artifacts'])
        e.update(expected_revision=1,reason='Correction')
        with connect(target) as db:commit(db,request(e,key='req2'))
        records=baselines(target,['MRVL'])['MRVL']['incremental_records']
        self.assertFalse(next(r for r in records if r['kind']=='assessment')['eligible_for_reuse'])

    def test_real_database_copy(self):
        source=os.environ.get('NIULAI_TEST_RESEARCH_DB')
        if not source:self.skipTest('Set NIULAI_TEST_RESEARCH_DB for real-copy integration')
        target=Path(self.tmp.name)/'actual-copy.sqlite';shutil.copy2(source,target)
        with connect(target) as db:
            before={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('securities','artifacts','security_artifact_relations','job_runs')}
            commit(db,request(evidence(),assessment()))
            after={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in before}
            self.assertEqual(before,after)
            self.assertEqual(len(read_ticker_current(db,'AAA')),2)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

if __name__=='__main__':unittest.main()
