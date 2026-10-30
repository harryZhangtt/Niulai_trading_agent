import json,hashlib,sqlite3,tempfile,unittest,zipfile,os
from pathlib import Path
from unittest.mock import patch
import research_store as store
import task_queue as q
import queue_watch as w

class QueueWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'research.sqlite'
        db=sqlite3.connect(self.path);db.executescript('CREATE TABLE securities(symbol TEXT);CREATE TABLE artifacts(id TEXT);CREATE TABLE job_runs(id TEXT,kind TEXT,status TEXT,payload TEXT);');db.close()
        self.db=store.connect(self.path)
        self.req={'run_id':'run','session':'2026-10-19','config_revision':9,'input_hash':'frozen','tasks':[{'ticker':'AAA','payload':{}}]}
        q.enqueue(self.db,self.req,now=100)
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def run_status(self,now):return w.watch(self.db,now)['runs'][0]
    def test_heartbeat_cannot_hide_stall(self):
        job=q.claim(self.db,'owner',lease_seconds=10000,now=101)[0]
        q.mutate(self.db,job['id'],job['token'],'heartbeat',lease_seconds=10000,now=3700)
        status=self.run_status(3800)
        self.assertTrue(status['stalled']);self.assertEqual(status['valid_leases'],1)
        self.assertIsNone(status['last_material_progress_at']);self.assertFalse(status['orphaned'])
    def test_expired_running_is_visible_and_not_mutated(self):
        job=q.claim(self.db,'owner',lease_seconds=60,now=101)[0]
        before=hashlib.sha256(self.path.read_bytes()).hexdigest();status=self.run_status(200)
        self.assertEqual(status['expired_running'],1);self.assertEqual(status['valid_leases'],0)
        self.assertTrue(status['orphaned']);self.assertEqual(status['resume_candidates'][0]['action'],'reclaim_expired_task')
        self.assertEqual(q.read(self.db,job['id'])['state'],'running')
        self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())
    def test_pending_without_valid_lease_is_orphaned(self):
        status=self.run_status(101)
        self.assertTrue(status['orphaned']);self.assertFalse(status['stalled']);self.assertTrue(status['requires_status_notification'])
    def test_partial_completed_is_not_certified(self):
        job=q.claim(self.db,'owner',now=101)[0]
        q.mutate(self.db,job['id'],job['token'],'finish',{'research_status':'partial'},now=102)
        status=self.run_status(103)
        self.assertEqual(status['queue_completed'],1);self.assertEqual(status['certified_assessments'],0)
        self.assertEqual(status['unfinished'],1);self.assertEqual(status['issues'][0]['reason'],'completed_attempt_has_incomplete_research')
        self.assertEqual(status['last_progress_kind'],'finish')
    def test_narrow_frozen_identity_full_result_uses_full_auditor(self):
        job={'payload':{'phase':'targeted_followup'},'result':{'research_status':'complete'}}
        with patch.object(w,'certified',return_value=(False,'full evidence missing')) as check:
            self.assertEqual(w.phase_certified(self.db,job,[]),(False,'full evidence missing'))
            check.assert_called_once_with(self.db,job)
    def test_all_cancelled_run_excluded(self):
        job=q.read(self.db)[0];q.cancel(self.db,job['id'],'superseded by new frozen run',now=105)
        result=w.watch(self.db,200)
        self.assertEqual(result['runs'],[]);self.assertEqual(result['excluded_runs'][0]['reason'],'all_tasks_cancelled')
    def test_repeated_clock_only_checkpoint_not_material_progress(self):
        job=q.claim(self.db,'owner',lease_seconds=10000,now=101)[0]
        q.mutate(self.db,job['id'],job['token'],'checkpoint',{'stage':'model','timestamp':200},now=200)
        q.mutate(self.db,job['id'],job['token'],'checkpoint',{'stage':'model','timestamp':3700},now=3700)
        status=self.run_status(3900)
        self.assertTrue(status['stalled']);self.assertEqual(status['last_material_progress_at'],w.stamp(200))
    def test_new_checkpoint_is_material_progress(self):
        job=q.claim(self.db,'owner',lease_seconds=10000,now=101)[0]
        q.mutate(self.db,job['id'],job['token'],'checkpoint',{'stage':'review','artifact_hash':'new'},now=3700)
        self.assertFalse(self.run_status(3800)['stalled'])
    def test_all_certified_still_requires_full_audit(self):
        with patch.object(w,'certified',return_value=(True,None)):
            status=self.run_status(101)
        self.assertEqual(status['health'],'await_final_completion_audit')
        self.assertNotEqual(status['health'],'COMPLETE')
    def supersede(self,tickers,expected=None):
        if tickers:
            q.enqueue(self.db,{**self.req,'run_id':'successor','tasks':[{'ticker':t,'payload':{}} for t in tickers]},now=101)
        item={'superseded_run_id':'run','successor_run_id':'successor','expected_tickers':expected or ['AAA'],
              'predecessor_is_complete':False,'finished_at':w.stamp(102),'successor_covers_all_expected':True}
        self.db.execute('INSERT INTO job_runs VALUES(?,?,?,?)',('inherit','research_run_supersession','skipped',json.dumps(item)))
        self.db.commit()
    def test_explicit_full_supersession_preserves_history_not_completion(self):
        self.supersede(['AAA','BBB'])
        result=w.watch(self.db,200)
        self.assertEqual([r['run_id'] for r in result['runs']],['successor'])
        old=result['excluded_runs'][0]
        self.assertEqual(old['reason'],'explicitly_superseded');self.assertFalse(old['predecessor_is_complete'])
        self.assertTrue(old['history_only']);self.assertEqual(old['resume_candidates'],[])
    def test_partial_successor_coverage_does_not_hide_predecessor(self):
        self.supersede(['BBB'])
        result=w.watch(self.db,200)
        self.assertIn('run',[r['run_id'] for r in result['runs']]);self.assertTrue(result['warnings'])
        self.assertEqual(result['excluded_runs'],[])
    def test_partial_expected_roster_cannot_hide_predecessor(self):
        self.supersede(['AAA','BBB'],expected=['BBB'])
        result=w.watch(self.db,200)
        self.assertIn('run',[r['run_id'] for r in result['runs']]);self.assertTrue(result['warnings'])
    def test_missing_successor_does_not_hide_predecessor(self):
        self.supersede([])
        result=w.watch(self.db,200)
        self.assertEqual(result['runs'][0]['run_id'],'run');self.assertTrue(result['warnings'])

    def test_cli_reader_uses_readonly_connection(self):
        with store.connect(self.path,readonly=True) as db:
            self.assertEqual(w.watch(db,101)['runs'][0]['pending'],1)
            with self.assertRaises(sqlite3.OperationalError):db.execute('DELETE FROM taskq_jobs')

class StageProofTests(QueueWatchTests):
    def test_reused_calculation_alias_requires_actual_hash(self):
        p=Path(self.tmp.name)/'calculation.json';p.write_text('{"value":4}')
        c={'reused_path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        w.verify_calculations(c)
        p.write_text('{"value":5}')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):w.verify_calculations(c)
    def test_calculation_alias_cannot_hide_missing_or_ambiguous_path(self):
        with self.assertRaisesRegex(ValueError,'path missing'):w.verify_calculations({'sha256':'abc'})
        with self.assertRaisesRegex(ValueError,'ambiguous'):w.verify_calculations({'path':'a','reused_path':'b','sha256':'abc'})
    def screening(self):
        source=Path(self.tmp.name)/'source.txt';source.write_text('original issuer evidence')
        card={'ticker':'AAA','research_complete':False,'source_refs':[{'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}], 'baseline_status':'partial','route':'deferred_data','reason':'identity unresolved','reopening_condition':'verified class mapping','remaining_gaps':['mapping']}
        raw=json.dumps(card).encode();h=hashlib.sha256(raw).hexdigest()
        review={'accepted':True,'reviewer':'independent','at':w.stamp(102),'checks':[{'source_hash':True}],'card_sha256':h}
        archive=Path(self.tmp.name)/'readback.zip'
        with zipfile.ZipFile(archive,'w') as z:z.writestr('AAA/card.json',raw);z.writestr('AAA/parent_review.json',json.dumps(review))
        os.setxattr(archive,'user.library-file-id',b'lib-test');os.setxattr(archive,'user.library-file-version',b'2')
        job=q.read(self.db)[0];job['state']='completed';job['payload']['phase']='bounded_triage'
        job['result']={'bundle':{'library_file_id':'lib-test','version':2},'readback_confirmed_at':w.stamp(103),'screening_complete':True,'research_status':'screened_not_full','card_sha256':h,'route':'deferred_data'}
        return job,archive,source
    def test_narrow_stage_proof_does_not_require_full_dcf(self):
        job,a,_=self.screening();self.assertEqual(w.phase_certified(self.db,job,[a]),(True,None))
        self.assertFalse(w.certified(self.db,job)[0])
    def test_boolean_only_cannot_pass(self):
        job,_,_=self.screening();self.assertFalse(w.phase_certified(self.db,job,[])[0])
    def test_later_cumulative_screening_archive_can_recover_exact_members(self):
        job,a,_=self.screening();os.setxattr(a,'user.library-file-version',b'3')
        self.assertEqual(w.phase_certified(self.db,job,[a]),(True,None))
    def test_older_archive_version_fails(self):
        job,a,_=self.screening();os.setxattr(a,'user.library-file-version',b'1')
        self.assertFalse(w.phase_certified(self.db,job,[a])[0])
    def test_changed_source_fails(self):
        job,a,source=self.screening();source.write_text('changed')
        self.assertIn('source hash mismatch',w.phase_certified(self.db,job,[a])[1])
    def test_changed_review_hash_fails(self):
        job,a,_=self.screening()
        with zipfile.ZipFile(a) as z:raw=z.read('AAA/card.json');review=json.loads(z.read('AAA/parent_review.json'))
        review['card_sha256']='wrong'
        with zipfile.ZipFile(a,'w') as z:z.writestr('AAA/card.json',raw);z.writestr('AAA/parent_review.json',json.dumps(review))
        self.assertIn('review binding',w.phase_certified(self.db,job,[a])[1])

if __name__=='__main__':unittest.main()
