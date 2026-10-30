import copy
import json
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
import task_queue as q

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'research.sqlite'
        db=sqlite3.connect(self.path)
        db.executescript('CREATE TABLE securities(symbol TEXT);CREATE TABLE artifacts(id TEXT);CREATE TABLE job_runs(id TEXT);');db.close()
        self.db=q.connect(self.path)
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def req(self,*tickers):return {'run_id':'run1','session':'2026-10-19','config_revision':9,'input_hash':'abc','tasks':[{'ticker':t,'payload':{'scope':'test','phase':'bounded_triage','max_new_primary_documents':2,'no_fresh_recommendation':True}} for t in tickers]}
    def put(self,*tickers):return q.enqueue(self.db,self.req(*tickers),now=100)
    def lease(self):self.put('AAA');return q.claim(self.db,'parent',now=101,lease_seconds=10)[0]
    def monitoring_config(self):
        c={'config_revision':1,'alert_authority':'niulai_saved_json_sqlite',
           'price_monitor':{'studio_dependency':False,'engine':'scripts/price_watch.py','buffer_fraction':'0.005'},
           '_meta':{'user_timezone':'Asia/Shanghai','session_timezone':'America/New_York'},
           'schedules':[{'role':'research_queue_continuation','enabled':True,'automation_id':'test-watch'}],
           'notifications':{'policies':{'research_queue_continuation':{'enabled':True}}},
           'research':{'triage':{'admission_required':True},'monitoring_contract':{'required':True,'scope':'all_current_and_future_runs',
                        'scheduler_readback_verified':True,'automation_id':'test-watch'}}}
        self.write_monitoring(c);return c
    def write_monitoring(self,c):
        (self.path.parent/'workflow.json').write_text(json.dumps(c))
    def test_monitoring_enable_requires_verified_config(self):
        with self.assertRaisesRegex(q.QueueError,'missing'):q.configure_monitoring(self.db)
        c=self.monitoring_config();c['research']['monitoring_contract']['scheduler_readback_verified']=False;self.write_monitoring(c)
        with self.assertRaisesRegex(q.QueueError,'unverified'):q.configure_monitoring(self.db)
        self.assertEqual(q.read(self.db),[])
    def test_monitoring_missing_after_enable_blocks_enqueue_claim(self):
        self.monitoring_config();q.configure_monitoring(self.db);self.put('AAA')
        (self.path.parent/'workflow.json').unlink()
        with self.assertRaisesRegex(q.QueueError,'missing'):self.put('BBB')
        with self.assertRaisesRegex(q.QueueError,'missing'):q.claim(self.db,'parent',now=101)
        self.assertEqual([(j['ticker'],j['state']) for j in q.read(self.db)],[('AAA','pending')])
    def test_monitoring_disabled_or_wrong_identity_blocks_claim(self):
        c=self.monitoring_config();q.configure_monitoring(self.db);self.put('AAA')
        for location,key,value in [('schedule','enabled',False),('policy','enabled',False),('schedule','automation_id','wrong')]:
            bad=copy.deepcopy(c)
            target=bad['schedules'][0] if location=='schedule' else bad['notifications']['policies']['research_queue_continuation']
            target[key]=value;self.write_monitoring(bad)
            with self.assertRaises(q.QueueError):q.claim(self.db,'parent',now=101)
        self.assertEqual(q.read(self.db)[0]['state'],'pending')
    def test_monitoring_valid_all_runs_and_screening_hold(self):
        c=self.monitoring_config();c['research']['triage']={'held_run_ids':['full-run'],'admission_required':True};self.write_monitoring(c)
        q.configure_monitoring(self.db)
        for name,ticker in [('full-run','AAA'),('screen-run','BBB'),('future-run','CCC')]:
            r=self.req(ticker);r['run_id']=name;q.enqueue(self.db,r,now=100)
        self.assertEqual(q.claim(self.db,'p',now=101,run_id='full-run'),[])
        self.assertEqual(len(q.claim(self.db,'p',now=101,run_id='screen-run')),1)
        self.assertEqual(len(q.claim(self.db,'p',now=101,run_id='future-run')),1)
    def test_monitoring_migrates_legacy_policy_and_persists(self):
        self.db.execute('CREATE TABLE taskq_policy(singleton INTEGER PRIMARY KEY,max_active INTEGER NOT NULL)')
        self.db.execute('INSERT INTO taskq_policy VALUES(1,2)');self.db.commit()
        self.monitoring_config();q.configure_monitoring(self.db)
        self.assertEqual(tuple(self.db.execute('SELECT max_active,monitoring_required FROM taskq_policy').fetchone()),(2,1))
        self.db.close();self.db=q.connect(self.path)
        c=self.monitoring_config();c['research']['monitoring_contract']['scheduler_readback_verified']=False;self.write_monitoring(c)
        with self.assertRaises(q.QueueError):self.put('AAA')

    def test_missing_db_rejected(self):
        with self.assertRaises(ValueError):q.connect(Path(self.tmp.name)/'missing.sqlite')
    def test_read_empty_has_no_schema_sideeffect(self):
        self.assertEqual(q.read(self.db),[])
        self.assertIsNone(self.db.execute("SELECT 1 FROM sqlite_master WHERE name='taskq_jobs'").fetchone())
    def test_duplicate_and_conflicting_enqueue_atomic(self):
        r=self.req('AAA');a=q.enqueue(self.db,r,now=100)
        self.assertTrue(q.enqueue(self.db,r,now=101)[0]['duplicate'])
        bad=self.req('BBB','AAA');bad['tasks'][1]['payload']={'different':True}
        with self.assertRaises(q.QueueError):q.enqueue(self.db,bad,now=102)
        self.assertEqual([j['ticker'] for j in q.read(self.db)],['AAA'])
    def test_concurrent_claims_global_cap(self):
        self.put('AAA','BBB','CCC','DDD','EEE','FFF')
        def worker(i):
            db=q.connect(self.path)
            try:return q.claim(db,str(i),now=101)
            finally:db.close()
        with ThreadPoolExecutor(max_workers=4) as p:results=list(p.map(worker,range(4)))
        ids=[j['id'] for batch in results for j in batch]
        self.assertEqual(len(ids),3);self.assertEqual(len(set(ids)),3)
    def test_expiry_reclaim_fencing_and_checkpoint(self):
        first=self.lease();tid=first['id']
        q.mutate(self.db,tid,first['token'],'checkpoint',{'stage':'evidence','artifact':'ref'},now=102)
        second=q.claim(self.db,'parent2',now=111)[0]
        self.assertNotEqual(first['token'],second['token']);self.assertEqual(second['checkpoint']['stage'],'evidence')
        with self.assertRaises(q.QueueError):q.mutate(self.db,tid,first['token'],'finish',{},now=112)
        q.mutate(self.db,tid,second['token'],'finish',{'review':'partial'},now=112)
        self.assertEqual(q.read(self.db,tid)['state'],'completed')
    def test_heartbeat_requires_live_lease(self):
        j=self.lease();q.mutate(self.db,j['id'],j['token'],'heartbeat',lease_seconds=30,now=110)
        self.assertEqual(q.read(self.db,j['id'])['lease_until'],140)
        with self.assertRaises(q.QueueError):q.mutate(self.db,j['id'],j['token'],'heartbeat',now=140)
    def test_retry_backoff_and_max_attempts(self):
        r=self.req('AAA');r['tasks'][0]['max_attempts']=2;q.enqueue(self.db,r,now=100)
        j=q.claim(self.db,'p',now=101)[0];q.mutate(self.db,j['id'],j['token'],'fail','temporary',retry_seconds=5,now=102)
        self.assertEqual(q.claim(self.db,'p',now=106),[])
        j=q.claim(self.db,'p',now=107)[0];q.mutate(self.db,j['id'],j['token'],'fail','still failing',now=108)
        self.assertEqual(q.read(self.db,j['id'])['state'],'failed');self.assertEqual(q.claim(self.db,'p',now=500),[])
    def test_permanent_failure_no_retry(self):
        j=self.lease();q.mutate(self.db,j['id'],j['token'],'fail','invalid identity',now=102,retryable=False)
        self.assertEqual(q.read(self.db,j['id'])['state'],'failed')
    def test_dependencies_release_after_completion(self):
        r=self.req('AAA','BBB');aid=q.task_id(r,'AAA');r['tasks'][1]['dependencies']=[aid];q.enqueue(self.db,r,now=100)
        j=q.claim(self.db,'p',now=101);self.assertEqual(len(j),1);self.assertEqual(j[0]['ticker'],'AAA')
        q.mutate(self.db,aid,j[0]['token'],'finish',{},now=102)
        self.assertEqual(q.claim(self.db,'p',now=103)[0]['ticker'],'BBB')
    def test_failed_dependency_blocks(self):
        r=self.req('AAA','BBB');aid=q.task_id(r,'AAA');r['tasks'][1]['dependencies']=[aid];q.enqueue(self.db,r,now=100)
        q.cancel(self.db,aid,'rebase stale inputs',now=101)
        self.assertEqual(q.claim(self.db,'p',now=102),[])
        b=q.read(self.db,q.task_id(r,'BBB'));self.assertEqual(b['state'],'blocked');self.assertEqual(b['error'],'dependency_failed')
    def test_cycles_unknown_dependencies_rollback(self):
        r=self.req('AAA','BBB');r['tasks'][0]['dependencies']=[q.task_id(r,'BBB')];r['tasks'][1]['dependencies']=[q.task_id(r,'AAA')]
        with self.assertRaises(q.QueueError):q.enqueue(self.db,r,now=100)
        self.assertEqual(q.read(self.db),[])
        r=self.req('AAA');r['tasks'][0]['dependencies']=['missing']
        with self.assertRaises(q.QueueError):q.enqueue(self.db,r,now=100)
    def test_cancellation_fences_worker(self):
        j=self.lease();q.cancel(self.db,j['id'],'cancelled by orchestrator',now=102)
        with self.assertRaises(q.QueueError):q.mutate(self.db,j['id'],j['token'],'finish',{},now=103)
    def test_expired_last_attempt_fails(self):
        r=self.req('AAA');r['tasks'][0]['max_attempts']=1;q.enqueue(self.db,r,now=100)
        j=q.claim(self.db,'p',lease_seconds=1,now=101)[0]
        self.assertEqual(q.claim(self.db,'p',now=102),[]);self.assertEqual(q.read(self.db,j['id'])['state'],'failed')
    def test_policy_limits_and_no_preemption(self):
        self.put('AAA','BBB','CCC','DDD');q.configure(self.db,2)
        self.assertEqual(len(q.claim(self.db,'p',limit=8,now=101)),2)
        q.configure(self.db,1);self.assertEqual(q.claim(self.db,'p',now=102),[])
        with self.assertRaises(q.QueueError):q.configure(self.db,9)
    def test_audit_immutable(self):
        self.put('AAA')
        with self.assertRaises(sqlite3.IntegrityError):self.db.execute('DELETE FROM taskq_events')
        self.db.rollback();self.assertEqual(self.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
    def test_claim_run_filter_preserves_global_capacity(self):
        old=self.req('OLD','OLDB');old['run_id']='historical';q.enqueue(self.db,old,now=100)
        current=self.req('NEW','NEWB','NEWC');current['run_id']='current';q.enqueue(self.db,current,now=101)
        old_claim=q.claim(self.db,'historical-parent',limit=1,now=102,run_id='historical')
        self.assertEqual(len(old_claim),1)
        new_claim=q.claim(self.db,'current-parent',limit=3,now=103,run_id='current')
        self.assertEqual(len(new_claim),2)
        self.assertTrue(all(j['run_id']=='current' for j in new_claim))
        self.assertEqual(q.claim(self.db,'wrong-parent',now=104,run_id='missing'),[])
        remaining=[j for j in q.read(self.db) if j['run_id']=='historical' and j['state']=='pending']
        self.assertEqual(len(remaining),1)

    def test_user_hold_does_not_claim_or_complete(self):
        self.put('AAA')
        (self.path.parent/'workflow.json').write_text(json.dumps({'research':{'triage':{'held_run_ids':['run1']}}}))
        self.assertEqual(q.claim(self.db,'parent',now=101,run_id='run1'),[])
        self.assertEqual(q.read(self.db)[0]['state'],'pending')

    def test_real_db_copy_original_untouched(self):
        source=os.environ.get('NIULAI_TEST_RESEARCH_DB')
        if not source:self.skipTest('Set NIULAI_TEST_RESEARCH_DB')
        original=Path(source);before=hashlib.sha256(original.read_bytes()).hexdigest()
        clone=Path(self.tmp.name)/'actual.sqlite'
        src=sqlite3.connect(original.as_uri()+'?mode=ro',uri=True);dst=sqlite3.connect(clone);src.backup(dst);src.close();dst.close()
        db=q.connect(clone)
        try:
            counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['securities','artifacts','job_runs']}
            q.configure_monitoring(db,False)  # Isolated fixture clone, never production.
            q.configure(db,8)  # Isolated clone may retain three live production leases.
            q.enqueue(db,self.req('MRVL'),now=100);j=q.claim(db,'test',now=101,run_id='run1')[0]
            q.mutate(db,j['id'],j['token'],'checkpoint',{'stage':'review'},now=102)
            q.mutate(db,j['id'],j['token'],'finish',{'status':'partial'},now=103)
            self.assertEqual(counts,{t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in counts})
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        finally:db.close()
        self.assertEqual(before,hashlib.sha256(original.read_bytes()).hexdigest())

if __name__=='__main__':unittest.main()
