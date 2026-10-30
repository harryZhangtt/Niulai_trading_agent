import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from research_resolution import calculate,VERSION
from research_resolution_evidence import validate,applies
from test_research_resolution import example_packet
class GateTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.ledger=example_packet(self.root);self.ledger['artifacts'][0]['path']=str(self.root/'evidence.txt')
  self.arts=[]
  self.register('src',self.root/'evidence.txt')
  self.write('report','<html><body>Synthetic diagnostic, not research.</body></html>',False)
  self.rec={'scope':'company_full','status':'complete','subject':{'ticker':'SYNTHETIC','cutoff':self.ledger['as_of']},'artifacts':self.arts,
    'audit':{'author_id':'author','independent_review':{'reviewer_id':'critic'}},'result':{'report_artifact_id':'report'},
    'research_resolution_evidence':{'version':VERSION,'status':'reviewed','expected_question_ids':['paid_capacity'],'ledger_artifact_id':'ledger','output_artifact_id':'output','review_artifact_id':'review','communication':{'route':'direct','reason':'Written directly with checked claims.'}}}
  self.build()
 def tearDown(self):self.tmp.cleanup()
 def register(self,aid,p):
  self.arts[:]=[a for a in self.arts if a['id']!=aid];self.arts.append({'id':aid,'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 def write(self,aid,value,structured=True):
  p=self.root/(aid+'.json' if structured else aid+'.html');p.write_text(json.dumps(value) if structured else value);self.register(aid,p)
 def build(self):
  self.write('ledger',self.ledger);self.write('output',calculate(self.ledger,base_dir=self.root))
  self.review={'reviewer_id':'critic','status':'approved_resolution_scope','subject':'SYNTHETIC','cutoff':self.ledger['as_of'],'proposed_action':self.ledger['proposed_action'],'reviewed_question_ids':['paid_capacity'],'reviewed_at':'2026-10-24T11:00:00Z','artifact_hashes':{a['id']:a['sha256'] for a in self.arts if a['id']!='review'},**{f:'Actual synthetic test review only.' for f in ['inventory_completeness_finding','attempt_sufficiency_finding','decision_bounds_finding','communication_finding']}}
  self.write('review',self.review)
 def test_progress_allows_recorded_open_buy_question(self):
  self.rec['status']='in_progress';self.assertEqual(validate(self.rec,decision_action='wait')['status'],'validated')
 def test_complete_cannot_hide_open_work_as_wait(self):
  with self.assertRaises(ValueError):validate(self.rec,decision_action='wait')
 def test_buy_cannot_skip_open_critical(self):
  self.ledger['proposed_action']='buy';self.build()
  with self.assertRaises(ValueError):validate(self.rec,decision_action='buy')
 def test_action_mismatch(self):
  with self.assertRaises(ValueError):validate(self.rec,decision_action='buy')
 def test_subject_mismatch(self):
  self.rec['subject']['ticker']='OTHER'
  with self.assertRaises(ValueError):validate(self.rec)
 def test_no_inventory(self):
  self.rec['research_resolution_evidence']['expected_question_ids']=[]
  with self.assertRaises(ValueError):validate(self.rec)
 def test_scope_omission(self):
  self.rec['research_resolution_evidence']['expected_question_ids'].append('funding')
  with self.assertRaises(ValueError):validate(self.rec)
 def test_new_actual_receipt_prevents_backdating(self):
  old=copy.deepcopy(self.rec);old.pop('research_resolution_evidence')
  self.assertFalse(applies(old));self.assertTrue(applies(old,['2026-10-25T00:00:00Z']))
  with self.assertRaises(ValueError):validate(old,observed_publication_times=['2026-10-25T00:00:00Z'])
 def test_narrow_exempt(self):
  self.rec['scope']='narrow';self.assertEqual(validate(self.rec)['status'],'historical_or_narrow_exempt')
 def test_future_cutoff_activates(self):
  r=copy.deepcopy(self.rec);r.pop('research_resolution_evidence');r['subject']['cutoff']='2026-10-25T00:00:00Z'
  with self.assertRaises(ValueError):validate(r)
 def test_changed_evidence(self):
  (self.root/'evidence.txt').write_text('changed')
  with self.assertRaises(ValueError):validate(self.rec)
 def test_stale_output(self):
  self.write('output',{'invented':'status'})
  with self.assertRaises(ValueError):validate(self.rec)
 def test_self_review(self):
  self.review['reviewer_id']='/other/author';self.write('review',self.review)
  with self.assertRaises(ValueError):validate(self.rec)
 def test_review_does_not_pin_report(self):
  self.review['artifact_hashes'].pop('report');self.write('review',self.review)
  with self.assertRaises(ValueError):validate(self.rec)
 def test_no_communication_route(self):
  self.rec['research_resolution_evidence'].pop('communication')
  with self.assertRaises(ValueError):validate(self.rec)
 def test_pending_not_complete(self):
  self.rec['research_resolution_evidence']['status']='pending'
  with self.assertRaises(ValueError):validate(self.rec)
 def test_pending_progress(self):
  self.rec['research_resolution_evidence']['status']='pending';self.rec['status']='in_progress';self.assertEqual(validate(self.rec)['status'],'pending')
if __name__=='__main__':unittest.main()
