"""Synthetic production-mail projection; never claim, send, or mutate an outbox."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from niulai_runtime.scheduler_view import describe
from shared.job_runtime.dashboard import ROOT, next_tick


class SchedulerViewTests(unittest.TestCase):
    def setUp(self):
        parent=ROOT/'ui/runtime/scheduler-20261103/tests';parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);state=self.root/'.niulai-state';(state/'databases').mkdir(parents=True)
        (state/'policy.json').write_text(json.dumps({'recipient':'owner@example.test','automation_id':'synthetic'}))
        self.job={'enabled':True,'id':'synthetic','schedule':{'kind':'daily','timezone':'America/New_York','times':['13:00','19:00']},'adapter_config':{'target':'schedule','policy':'.niulai-state/policy.json'}}
        self.path=state/'databases/outbox.sqlite';self.at=datetime(2026,11,2,16,tzinfo=timezone.utc)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE digest_work(logical_key TEXT,meta TEXT,initial_key TEXT,correction_key TEXT)')
            db.execute('CREATE TABLE outbox(key TEXT,status TEXT,prepared_at TEXT,updated_at TEXT,verified_at TEXT,payload TEXT)')
            for purpose,auto,who in [('production','synthetic','owner'),('test','synthetic','owner'),('production','other','owner'),('production','synthetic','other')]:
                key=f'portfolio-email:{auto}:{purpose}:{who}'
                db.execute('INSERT INTO digest_work VALUES(?,?,?,NULL)',(key,json.dumps({'purpose':purpose,'recipient':who+'@example.test'}),key))
                payload={'to':who+'@example.test','subject':'Saved '+key,'payload':{'mime_type':'multipart/mixed','parts':[{'mime_type':'text/html','body':{'content':'<h1>Saved report</h1><p>api_key=SYNTHETIC_CANARY</p>'}},{'mime_type':'application/pdf','filename':'report.pdf','body':{'base64_url_content':'SYNTHETIC_PDF'}}]}}
                db.execute('INSERT INTO outbox VALUES(?,?,?,?,?,?)',(key,'accepted',self.at.isoformat(),self.at.isoformat(),self.at.isoformat(),json.dumps(payload)))

    def get(self,**kw):return describe(self.root,self.job,self.at,next_tick=next_tick,detail=True,**kw)

    def test_actual_calendar_next_send_and_independent_conditional_recovery(self):
        result=self.get();self.assertEqual(result['delivery']['next_send_at'],'2026-11-02T18:00:00+00:00')
        self.job['adapter_config']['target']='recovery';result=self.get()
        self.assertIsNone(result['delivery']['next_send_at']);self.assertEqual(result['delivery']['mode'],'conditional')

    def test_only_matching_production_policy_outputs_appear_and_raw_state_stays_unchanged(self):
        before=self.path.read_bytes();value=self.get()
        self.assertEqual(len(value['outputs']),1);self.assertTrue(value['outputs'][0]['verified'])
        self.assertNotIn('owner@example.test',json.dumps(value));self.assertEqual(before,self.path.read_bytes())

    def test_preview_is_id_bound_and_excludes_pdf_payloads_and_credentials(self):
        identity=hashlib.sha256(b'portfolio-email:synthetic:production:owner').hexdigest()
        value=self.get(output_id=identity)['output'];self.assertIn('<h1>Saved report</h1>',value['html'])
        self.assertNotIn('SYNTHETIC_CANARY',json.dumps(value));self.assertNotIn('SYNTHETIC_PDF',json.dumps(value))
        self.assertEqual(value['attachments'][0]['name'],'report.pdf')
        with self.assertRaises(ValueError):self.get(output_id='a'*64)


if __name__=='__main__':unittest.main()
