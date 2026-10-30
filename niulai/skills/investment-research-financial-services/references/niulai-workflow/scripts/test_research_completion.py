"""Synthetic fixtures validate gates, never actual investment conclusions."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile
import research_completion as c
import task_queue as q

spec=importlib.util.spec_from_file_location('existing_fixture',c.ROOT/'tests/test_research_run_schema.py');fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)

class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.dbpath=self.root/'research.sqlite'
        db=sqlite3.connect(self.dbpath);db.executescript('CREATE TABLE securities(symbol TEXT);CREATE TABLE artifacts(id TEXT);CREATE TABLE job_runs(id TEXT);');db.close()
        self.db=q.connect(self.dbpath)
        req={'run_id':'run1','session':'2026-10-19','config_revision':9,'input_hash':'inputs','tasks':[{'ticker':'AAA','payload':{}}]}
        q.enqueue(self.db,req,now=100);j=q.claim(self.db,'p',now=101)[0];q.mutate(self.db,j['id'],j['token'],'finish',{'research_status':'complete'},now=102)
        self.rec=fixtures.fixture();self.rec['run_id']='run1:AAA';self.rec['subject']['ticker']='AAA'
        for a in self.rec['artifacts']:
            content={'command':'python synthetic.py','exit_code':0,'output':'Synthetic check passed'} if a['id']=='cmd' else {'synthetic_fixture':a['id']}
            a.update(self.write(a['id']+'.json',content))
        report=next(a for a in self.rec['artifacts'] if a['id']=='report')
        self.rec['stages']['persistence']={'status':'complete','evidence_refs':['synthetic-receipt']}
        self.rec['result']['publication_status']='saved'
        self.rec['persistence']={'status':'saved','receipts':[{'artifact_id':'report','file_id':'libfile_synthetic','version':1,'confirmed_at':fixtures.STAMP,'sha256':report['sha256']}]}
        receipt=self.write('receipt.json',{'status':'succeeded','library_file_id':'libfile_synthetic','current_version_number':1})
        self.item={'ticker':'AAA','status':'complete','input_hash':'inputs','action':'no_buy','record':self.write('record.json',self.rec),'persistence_readbacks':[{'artifact_id':'report','file_id':'libfile_synthetic','version':1,'content':{'path':report['path'],'sha256':report['sha256']},'receipt':receipt}]}
        self.manifest={'run_id':'run1','input_hash':'inputs','expected_tickers':['AAA'],'queue_db':str(self.dbpath),'items':[self.item]}
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def write(self,name,data):
        p=self.root/name;p.write_text(json.dumps(data));return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    def update(self):self.item['record']=self.write('record.json',self.rec)
    def status(self):return c.audit(self.manifest)
    def test_complete_no_buy_valid(self):
        out=self.status();self.assertEqual(out['status'],'COMPLETE');self.assertFalse(out['semantic_truth_verified'])
    def test_equity_options_profile_without_evidence_remains_incomplete(self):
        self.rec['instrument_profile']='equity_options';self.update()
        self.assertEqual(self.status()['status'],'IN_PROGRESS')
    def test_research_only_options_cannot_claim_complete(self):
        self.rec['instrument_profile']='equity_options'
        self.rec['options_evidence']={'version':'2026-10-24-options-evidence-1','status':'research_only','blockers':['Synthetic missing quote']}
        self.update();self.assertEqual(self.status()['status'],'IN_PROGRESS')
    def test_new_publication_requires_visual_dependency_cycle_evidence(self):
        self.rec['valuation_evidence']={'version':'2026-10-20-valuation-evidence-1',**{k:{'status':'evidenced','finding':'Synthetic fixture only.','artifact_refs':['outputs']} for k in ['business_values','forecast_validation','probability_basis','professional_research','technical_confirmation']}}
        self.rec['persistence']['receipts'][0]['confirmed_at']='2026-10-24T00:00:00Z'
        self.update();out=self.status();self.assertEqual(out['status'],'IN_PROGRESS')
        self.assertTrue(any('rationale policy' in issue for issue in out['items'][0]['issues']))
    def test_actual_new_save_timestamp_prevents_backdated_legacy_bypass(self):
        self.item['persistence_readbacks'][0]['receipt']=self.write('new_receipt.json',{'status':'succeeded','library_file_id':'libfile_synthetic','current_version_number':1,'modified_at':'2026-10-24T00:00:00Z'})
        out=self.status();self.assertEqual(out['status'],'IN_PROGRESS')
        self.assertTrue(any('rationale policy' in issue for issue in out['items'][0]['issues']))
    def test_actual_new_save_requires_critical_input_evidence(self):
        self.item['persistence_readbacks'][0]['receipt']=self.write('new_receipt.json',{'status':'succeeded','library_file_id':'libfile_synthetic','current_version_number':1,'modified_at':'2026-10-24T00:11:00Z'})
        out=self.status();self.assertEqual(out['status'],'IN_PROGRESS')
        self.assertTrue(any('Critical data' in issue for issue in out['items'][0]['issues']))
    def test_saved_archive_member_readback(self):
        report=next(a for a in self.rec['artifacts'] if a['id']=='report')
        archive=self.root/'saved.zip'
        with zipfile.ZipFile(archive,'w') as z:z.write(report['path'],'reports/report.json')
        rb=self.item['persistence_readbacks'][0]
        rb['content']={'path':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
        rb['archive_member']='reports/report.json'
        self.assertEqual(self.status()['status'],'COMPLETE')
        rb['archive_member']='reports/missing.json'
        self.assertEqual(self.status()['status'],'IN_PROGRESS')
    def test_actual_stdout_execution_receipt(self):
        cmd=next(a for a in self.rec['artifacts'] if a['id']=='cmd')
        cmd.update(self.write('cmd.json',{'command':['python','synthetic.py'],'exit_code':0,'stdout':'Synthetic successful execution'}))
        self.update();self.assertEqual(self.status()['status'],'COMPLETE')

    def test_missing_ticker_stays_in_progress(self):
        self.manifest['expected_tickers'].append('BBB');out=self.status();self.assertEqual(out['status'],'IN_PROGRESS');self.assertEqual(out['complete'],1)
    def test_completed_attempt_partial_requires_continuation(self):
        self.item['status']='partial';self.item.pop('record');out=self.status()
        self.assertEqual(out['status'],'IN_PROGRESS');self.assertTrue(out['continuation_actions'][0]['completed_attempt_is_not_completed_research'])
    def test_unsaved_research_not_complete(self):
        self.rec['persistence']={'status':'unsaved'};self.update();self.assertEqual(self.status()['status'],'IN_PROGRESS')
    def test_fake_completion_flags_without_artifacts_fail(self):
        self.item['record']=self.write('record.json',{'status':'complete','model_passed':True,'review_passed':True,'saved':True})
        self.assertEqual(self.status()['status'],'IN_PROGRESS')
    def test_unreferenced_receipt_fails(self):
        self.item['persistence_readbacks'][0]['receipt']=self.write('wrong_receipt.json',{'status':'succeeded','library_file_id':'libfile_other','current_version_number':1})
        self.assertEqual(self.status()['status'],'IN_PROGRESS')
    def test_zero_checked_review_fails(self):
        self.rec['audit']['factual_samples']=[];self.update();self.assertEqual(self.status()['status'],'IN_PROGRESS')
    def test_fake_passed_arithmetic_fails(self):
        self.rec['audit']['numerical_checks'][0]['actual']=5;self.update();self.assertEqual(self.status()['status'],'IN_PROGRESS')
    def test_same_author_review_fails(self):
        self.rec['audit']['independent_review']['reviewer_id']='author';self.update();self.assertEqual(self.status()['status'],'IN_PROGRESS')
    def test_stale_artifact_fails(self):
        Path(self.rec['artifacts'][0]['path']).write_text('changed');self.assertEqual(self.status()['status'],'IN_PROGRESS')
    def test_old_input_or_record_fails(self):
        self.item['input_hash']='old';self.assertEqual(self.status()['status'],'IN_PROGRESS');self.item['input_hash']='inputs'
        self.rec['run_id']='old:AAA';self.update();self.assertEqual(self.status()['status'],'IN_PROGRESS')
    def test_external_blocker_requires_attempt_artifact(self):
        self.item.update(status='blocked',blockers=[{'kind':'external','reason':'No access','attempts':[]}])
        self.assertEqual(self.status()['status'],'IN_PROGRESS')
        self.item['blockers'][0]['attempts']=[self.write('attempt.json',{'obstacle_type':'access_denied','attempted_at':fixtures.STAMP,'detail':'Synthetic permission refusal','source':'https://example.invalid'})]
        self.assertEqual(self.status()['status'],'BLOCKED')
        self.item['blockers'].append({'kind':'fixable','reason':'Model not yet run'})
        self.assertEqual(self.status()['status'],'IN_PROGRESS')
    def test_pending_queue_blocks_even_full_record(self):
        self.db.execute("UPDATE taskq_jobs SET state='pending'");self.db.commit();self.assertEqual(self.status()['status'],'IN_PROGRESS')
    def test_unknown_receipt_version_fails(self):
        self.item['persistence_readbacks'][0]['version']=2;self.assertEqual(self.status()['status'],'IN_PROGRESS')
    def test_unknown_claim_or_dependency_fails(self):
        self.rec['claims'][0]['evidence_refs'][0]['passage_id']='missing';self.update();self.assertEqual(self.status()['status'],'IN_PROGRESS')

if __name__=='__main__':unittest.main()
