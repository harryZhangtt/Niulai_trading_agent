import copy,hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import register_research as reg
import research_store as store
import task_queue as q

class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.path=self.root/'test.sqlite'
        db=sqlite3.connect(self.path)
        db.executescript('''CREATE TABLE securities(symbol TEXT PRIMARY KEY,issuer_id TEXT,payload TEXT);
CREATE TABLE artifacts(library_file_id TEXT PRIMARY KEY,version INTEGER,filename TEXT,status TEXT,payload TEXT);
CREATE TABLE job_runs(id TEXT);CREATE TABLE research_sections(id TEXT PRIMARY KEY,artifact_id TEXT,payload TEXT);
CREATE TABLE security_artifact_relations(security_symbol TEXT,artifact_id TEXT,section_id TEXT,relationship TEXT,payload TEXT,PRIMARY KEY(security_symbol,artifact_id,section_id,relationship));''');db.close()
        self.db=store.connect(self.path)
        self.source={'id':'s1','url':'https://example.com/report','published_at':'2025-01-01','retrieved_at':'2025-01-02T00:00:00Z','passages':[{'id':'p1','text':'test evidence'}]}
        rec={'subject':{'ticker':'AAA','security_type':'equity','cutoff':'2025-01-02T00:00:00Z','quote_timestamp':'2025-01-02T00:00:00Z'},'sources':[self.source],'artifacts':[{'id':'r','kind':'report'}],'policy_versions':{},'model':{}}
        self.write('decision.json',{'ticker':'AAA','action':'wait'})
        rec['artifacts'].append({'id':'decision','kind':'other','sha256':hashlib.sha256((self.root/'decision.json').read_bytes()).hexdigest()})
        self.write('rec.json',rec)
        item={'ticker':'AAA','action':'wait','input_hash':'hash','record':{'path':str(self.root/'rec.json')},'persistence_readbacks':[{'artifact_id':'r','file_id':'libfile_test','version':0,'archive_member':'AAA/report.md','content':{'path':'report.zip','sha256':'test'}}]}
        self.write('item.json',item)
        self.req={'run_id':'run','session':'2025-01-02','config_revision':1,'items':[{'completion_item':str(self.root/'item.json'),'decision':str(self.root/'decision.json'),'input_revisions':{'config':1},'baseline_refs':[],'baseline_gap':'No prior','analysis_date':'2025-01-02'}]}
        task={'run_id':'run','session':'2025-01-02','config_revision':1,'input_hash':'hash','tasks':[{'ticker':'AAA','payload':{}}]}
        q.enqueue(self.db,task,now=100);job=q.claim(self.db,'test',now=101)[0]
        self.req['items'][0].update(task_id=job['id'],lease_token=job['token'])
        self.mock=patch.object(reg.completion,'inspect_record',return_value={'checked_numbers':1});self.mock.start()
    def tearDown(self):self.mock.stop();self.db.close();self.temp.cleanup()
    def write(self,name,v):(self.root/name).write_text(json.dumps(v))
    def count(self):return self.db.execute('SELECT count(*) FROM research_store_revisions').fetchone()[0]
    def test_repeat_is_noop(self):
        reg.register(self.db,self.req,now=102);n=self.count()
        self.assertTrue(reg.register(self.db,self.req,now=103)['records'][0]['idempotent_replay']);self.assertEqual(n,self.count())
    def test_completed_changed_content_rejected(self):
        reg.register(self.db,self.req,now=102);self.write('decision.json',{'ticker':'AAA','action':'wait','changed':'unreviewed'})
        with self.assertRaisesRegex(reg.RegistrationError,'supersession'):reg.register(self.db,self.req,now=103)
        self.assertEqual(self.count(),2)
    def test_decision_action_mismatch_rejected(self):
        item=json.loads((self.root/'item.json').read_text());item['action']='buy';self.write('item.json',item)
        with self.assertRaisesRegex(reg.RegistrationError,'identity/action'):reg.register(self.db,self.req,now=102)
        self.assertIsNone(store.read(self.db,'run:AAA:assessment'))
    def test_completed_catalog_corruption_not_silent_noop(self):
        reg.register(self.db,self.req,now=102)
        with self.db:self.db.execute("DELETE FROM security_artifact_relations WHERE security_symbol='AAA'")
        with self.assertRaisesRegex(reg.RegistrationError,'catalog'):reg.register(self.db,self.req,now=103)
    def test_every_write_phase_rolls_back_then_retry(self):
        for phase in ('after_assessment','after_registry','after_queue'):
            def crash(p,t):
                if p==phase:raise RuntimeError('crash')
            with self.assertRaisesRegex(RuntimeError,'crash'):reg.register(self.db,self.req,now=102,_fault=crash)
            self.assertIsNone(store.read(self.db,'run:AAA:assessment'))
            self.assertEqual(self.db.execute('SELECT count(*) FROM artifacts').fetchone()[0],0)
            self.assertEqual(q.read(self.db,self.req['items'][0]['task_id'])['state'],'running')
        reg.register(self.db,self.req,now=103)
        self.assertEqual(self.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
    def test_old_multiticker_and_unknown_preserved(self):
        with self.db:
            self.db.execute('INSERT INTO securities VALUES(?,?,?)',('AAA',None,json.dumps({'unknown':'keep'})))
            self.db.execute('INSERT INTO research_sections VALUES(?,?,?)',('old','oldfile',json.dumps({'current_for_symbols':['AAA','BBB'],'unknown':'keep'})))
        reg.register(self.db,self.req,now=102)
        old=json.loads(self.db.execute("SELECT payload FROM research_sections WHERE id='old'").fetchone()[0]);self.assertEqual(old['current_for_symbols'],['BBB']);self.assertEqual(old['unknown'],'keep')
        security=json.loads(self.db.execute("SELECT payload FROM securities WHERE symbol='AAA'").fetchone()[0]);self.assertEqual(security['unknown'],'keep')
    def test_actual_evidence_revision_used(self):
        payload={'claim':'a','source_url':self.source['url'],'source_cutoff':self.source['published_at'],'retrieved_at':self.source['retrieved_at'],'source_record':self.source}
        for rev in (0,1):
            store.commit(self.db,{'request_id':str(rev),'run_id':'run','operations':[{'id':'run:AAA:source:s1','ticker':'AAA','kind':'evidence','expected_revision':rev,'action':'put','reason':'test revision','payload':payload}]})
        reg.register(self.db,self.req,now=102)
        self.assertEqual(store.read(self.db,'run:AAA:assessment')['payload']['evidence_refs'][0]['revision'],2)
    def test_stale_lease_no_writes(self):
        with self.assertRaisesRegex(reg.RegistrationError,'lease'):reg.register(self.db,self.req,now=10000)
        self.assertIsNone(store.read(self.db,'run:AAA:assessment'))
    def set_source_fields(self,**fields):
        self.source.update(fields)
        rec=json.loads((self.root/'rec.json').read_text());rec['sources']=[self.source];self.write('rec.json',rec)
    def test_unknown_publication_uses_labeled_observation(self):
        self.set_source_fields(published_at=None)
        reg.register(self.db,self.req,now=102)
        payload=store.read(self.db,'run:AAA:source:s1')['payload']
        self.assertEqual(payload['source_cutoff'],self.source['retrieved_at'])
        self.assertEqual(payload['source_cutoff_basis'],'retrieved_observation_publication_unknown')
        self.assertIsNone(payload['published_at']);self.assertIsNone(payload['source_record']['published_at'])
    def test_explicit_data_asof_has_priority(self):
        self.set_source_fields(data_asof='2024-12-31')
        reg.register(self.db,self.req,now=102)
        payload=store.read(self.db,'run:AAA:source:s1')['payload']
        self.assertEqual(payload['source_cutoff'],'2024-12-31')
        self.assertEqual(payload['source_cutoff_basis'],'explicit_data_asof')
        self.assertEqual(payload['published_at'],'2025-01-01')
    def test_future_publication_cannot_hide_behind_data_asof(self):
        self.set_source_fields(data_asof='2024-12-31',published_at='2025-01-03')
        with self.assertRaisesRegex(reg.RegistrationError,'chronology'):reg.register(self.db,self.req,now=102)
        self.assertIsNone(store.read(self.db,'run:AAA:assessment'))
    def test_future_data_asof_rejected(self):
        self.set_source_fields(data_asof='2025-01-03',published_at=None)
        with self.assertRaisesRegex(reg.RegistrationError,'chronology'):reg.register(self.db,self.req,now=102)
        self.assertIsNone(store.read(self.db,'run:AAA:assessment'))
    def test_owned_transactions_require_active_transaction(self):
        with self.assertRaisesRegex(store.StoreError,'transaction'):store.commit(self.db,{'request_id':'x','run_id':'x','operations':[{}]},manage_transaction=False)
        with self.assertRaisesRegex(q.QueueError,'transaction'):q.mutate(self.db,'x','x','finish',{},manage_transaction=False)
    def test_completed_evidence_update_requires_new_research(self):
        reg.register(self.db,self.req,now=102);ev=store.read(self.db,'run:AAA:source:s1')
        store.commit(self.db,{'request_id':'new','run_id':'new','operations':[{'id':ev['id'],'ticker':'AAA','kind':'evidence','expected_revision':1,'action':'put','reason':'revision','payload':ev['payload']}]})
        with self.assertRaisesRegex(reg.RegistrationError,'evidence superseded'):reg.register(self.db,self.req,now=103)
if __name__=='__main__':unittest.main()
