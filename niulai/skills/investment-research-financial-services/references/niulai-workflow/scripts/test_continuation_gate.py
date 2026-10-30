import hashlib,json,tempfile,unittest
from pathlib import Path
from continuation_gate import inspect_jobs

class ContinuationGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.job={'id':'task1','ticker':'AAA','fingerprint':'frozen','state':'completed','payload':{'phase':'targeted_followup'},'result':{'next_action':{'route':'targeted_delta','action':'build profit model'}}}
        self.req={'task_ids':['task1']}
    def tearDown(self):self.tmp.cleanup()
    def check(self,accepted=True):return inspect_jobs([self.job],self.req,100,lambda j:(accepted,None))[0]
    def put(self,obj,name='d.json'):
        p=self.root/name;p.write_text(json.dumps(obj));return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    def disposition(self,kind,**extra):
        d={'task_id':'task1','task_fingerprint':'frozen','recorded_at':'1970-01-01T00:00:50+00:00','kind':kind,'reason':'specific reason','reopening_condition':'specific trigger',**extra}
        self.req['dispositions']={'task1':self.put(d)}
    def test_accepted_stage_must_continue(self):
        r=self.check();self.assertTrue(r['must_continue']);self.assertEqual(r['disposition'],'execute_next_stage')
    def test_full_audit_not_replaced_by_stage_check(self):
        self.job['payload']['phase']='full_research';self.assertEqual(self.check()['disposition'],'run_full_completion_audit')
    def test_narrow_frozen_task_full_result_requires_full_audit(self):
        self.job['result']['research_status']='complete'
        self.assertEqual(self.check()['disposition'],'run_full_completion_audit')
    def test_live_lease_does_not_allow_end(self):
        self.job.update(state='running',lease_until=1000);self.assertTrue(self.check(False)['must_continue'])
    def test_missing_evidence_requires_recovery(self):self.assertEqual(self.check(False)['disposition'],'restore_or_repair_evidence')
    def test_canceled_scope_preserved(self):
        self.job['state']='cancelled';self.assertFalse(self.check()['must_continue'])
    def test_user_hold_requires_specific_record(self):
        self.disposition('user_hold',user_instruction='Only analyze BBB',scope='AAA');self.assertFalse(self.check()['must_continue'])
    def test_persisted_job_fingerprint_without_input_hash(self):
        self.assertNotIn('input_hash',self.job)
        self.disposition('user_hold',user_instruction='Pause AAA',scope='AAA')
        self.assertFalse(self.check()['must_continue'])
    def test_pending_is_not_reason_to_stop(self):
        self.disposition('pending')
        with self.assertRaises(ValueError):self.check()
    def test_event_wait_requires_no_independent_work(self):
        self.disposition('event_wait',independent_work_remaining=True,evidence_refs=[],recheck_at='1970-01-02T00:00:00+00:00')
        with self.assertRaises(ValueError):self.check()
    def test_due_event_wait_reopens(self):
        e=self.put({'event':'earnings'},'source.json')
        self.disposition('event_wait',independent_work_remaining=False,evidence_refs=[e],recheck_at='1970-01-01T00:01:00+00:00')
        self.assertTrue(self.check()['must_continue'])
    def test_future_evidenced_event_can_wait(self):
        e=self.put({'event':'earnings'},'source.json')
        self.disposition('event_wait',independent_work_remaining=False,evidence_refs=[e],recheck_at='1970-01-02T00:00:00+00:00')
        self.assertFalse(self.check()['must_continue'])
    def test_external_block_requires_actual_attempt(self):
        self.disposition('external_blocked',independent_work_remaining=False,attempts=[])
        with self.assertRaises(ValueError):self.check()
    def test_hash_change_rejected(self):
        self.disposition('user_hold',user_instruction='Stop',scope='AAA');(self.root/'d.json').write_text('{}')
        with self.assertRaises(ValueError):self.check()
    def test_empty_or_missing_scope_rejected(self):
        self.req['task_ids']=[]
        with self.assertRaises(ValueError):self.check()
        self.req['task_ids']=['absent']
        with self.assertRaises(ValueError):self.check()
if __name__=='__main__':unittest.main()
