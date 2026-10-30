import json, sqlite3, tempfile, unittest
from pathlib import Path
import task_queue as q

class Admission(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'workflow.json').write_text(json.dumps({'research':{'triage':{'admission_required':True}}}))
        self.db=sqlite3.connect(self.root/'test.sqlite');self.db.row_factory=sqlite3.Row
        self.request=dict(run_id='fixture',session='2026-10-20',config_revision=1,input_hash='fixture')
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def add(self,payload):return q.enqueue(self.db,dict(self.request,tasks=[{'ticker':'TEST','payload':payload}]),now=1)
    def test_bypass_denied(self):
        with self.assertRaises(q.QueueError):self.add({'phase':'full_review'})
    def test_probe_claim_and_idempotency(self):
        p={'phase':'bounded_triage','max_new_primary_documents':2,'no_fresh_recommendation':True}
        self.assertFalse(self.add(p)[0]['duplicate']);self.assertTrue(self.add(p)[0]['duplicate'])
        self.assertEqual(len(q.claim(self.db,'test',now=2,run_id='fixture')),1)
    def test_old_unfiltered_job_blocked_at_claim(self):
        (self.root/'workflow.json').write_text('{}')
        self.add({'phase':'full_review'})
        (self.root/'workflow.json').write_text(json.dumps({'research':{'triage':{'admission_required':True}}}))
        with self.assertRaises(q.QueueError):q.claim(self.db,'test',now=2,run_id='fixture')
        self.assertEqual(q.read(self.db)[0]['state'],'pending')
    def test_reuse_cannot_launch_full(self):
        p={'phase':'full_review','triage_input':{},'triage_route':'data_repair'}
        with self.assertRaises(q.QueueError):self.add(p)
    def test_invalid_parent_card(self):
        with self.assertRaises(q.QueueError):self.add({'phase':'targeted_followup','card_path':str(self.root/'missing'),'card_hash':'fake','parent_run_id':'parent','next_action':'repair','reopening_condition':'new evidence','new_primary_document_budget':2})

if __name__=='__main__':unittest.main()
