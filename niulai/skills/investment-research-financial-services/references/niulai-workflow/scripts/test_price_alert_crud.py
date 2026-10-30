import unittest,tempfile,sqlite3,json
from pathlib import Path
from price_alert_crud import apply,digest,validate,recover
class CRUDTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name);self.j=self.p/'alerts.json';self.d=self.p/'alerts.sqlite'
  self.j.write_text(json.dumps({'_meta':{'canonical_source':'niulai_saved_json_sqlite'},'alerts':[]}))
  c=sqlite3.connect(self.d);c.execute('create table alerts(id text primary key,ticker text,direction text,threshold text,enabled integer,payload text)');c.execute('create table preserved(x)');c.execute('insert into preserved values(9)');c.commit();c.close()
 def tearDown(self):self.tmp.cleanup()
 def req(self,ops,key='test'):
  import hashlib
  evidence=self.p/'evidence';evidence.write_text('test evidence')
  ref={'path':str(evidence),'sha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}
  old={r['id']:r for r in json.loads(self.j.read_text())['alerts']};bands=[]
  for op in ops:
   r=dict(old.get(op['id'],{}));r.update(op.get('rule',op.get('patch',{})))
   if r.get('threshold'):bands.append({'threshold':r['threshold'],'direction':r['direction'],'conditions':['test condition'],'invalidation':['test invalidation'],'calculation':ref})
  decision=self.p/'decision.json';decision.write_text(json.dumps({'ticker':'INTC','now_action':'wait','as_of':'2026-10-22T00:00:00+00:00','valid_until':'2100-01-01T00:00:00+00:00','horizon_days':365,'required_return':.15,'bands':bands}))
  dr={'path':str(decision),'sha256':hashlib.sha256(decision.read_bytes()).hexdigest()}
  return {'request_id':key,'expected_sha256':digest(json.loads(self.j.read_text())),'operations':ops,'reviews':{'INTC':{'purpose':'research_review','security_type':'company','entry_basis':'reviewed_company_model','author':'a','reviewer':'b','reviewed_at':'2026-10-22T00:00:00+00:00','model':ref,'review':ref,'decision':dr}}}
 def create(self,id='a',price='38'):
  return {'op':'create','id':id,'rule':{'ticker':'INTC','direction':'below','threshold':price,'enabled':True}}
 def test_retry_conflict_delete_and_history(self):
  q=self.req([self.create()]);apply(self.j,self.d,q);self.assertEqual(apply(self.j,self.d,q)['status'],'already_applied')
  r=json.loads(self.j.read_text())['alerts'][0]
  q2=self.req([{'op':'update','id':'a','expected_rule_sha256':digest(r),'patch':{'threshold':'33'}}],'u');apply(self.j,self.d,q2)
  r=json.loads(self.j.read_text())['alerts'][0];apply(self.j,self.d,self.req([{'op':'delete','id':'a','expected_rule_sha256':digest(r)}],'d'))
  self.assertFalse(json.loads(self.j.read_text())['alerts'][0]['enabled'])
  c=sqlite3.connect(self.d);self.assertEqual(c.execute('select x from preserved').fetchone()[0],9);self.assertEqual(c.execute('select count(*) from alert_crud_journal').fetchone()[0],3)
 def test_atomic_invalid_batch(self):
  old=self.j.read_bytes()
  with self.assertRaises(ValueError):apply(self.j,self.d,self.req([self.create(),self.create('b','NaN')]))
  self.assertEqual(old,self.j.read_bytes());self.assertEqual(sqlite3.connect(self.d).execute('select count(*) from alerts').fetchone()[0],0)
 def test_stale_and_equivalent(self):
  stale=self.req([self.create('b','33')],'stale');apply(self.j,self.d,self.req([self.create()]))
  with self.assertRaises(ValueError):apply(self.j,self.d,stale)
  with self.assertRaises(ValueError):apply(self.j,self.d,self.req([self.create('b')],'dup'))
 def test_crash_export_recovery(self):
  from unittest.mock import patch
  with patch('price_alert_crud.write_atomic',side_effect=OSError('simulated crash')):
   with self.assertRaises(OSError):apply(self.j,self.d,self.req([self.create()]))
  c=sqlite3.connect(self.d);c.execute('begin immediate');recover(c,self.j);c.close()
  self.assertEqual(json.loads(self.j.read_text())['alerts'][0]['threshold'],'38')
 def test_dry_run(self):
  old=self.j.read_bytes();self.assertEqual(apply(self.j,self.d,self.req([self.create()]),True)['status'],'dry_run');self.assertEqual(old,self.j.read_bytes())
 def test_missing_or_changed_review_rejected(self):
  q=self.req([self.create()]);q.pop('reviews')
  with self.assertRaises(ValueError):apply(self.j,self.d,q)
  q=self.req([self.create()]);(self.p/'evidence').write_text('changed')
  with self.assertRaises(ValueError):apply(self.j,self.d,q)
 def test_leverage_generic_warning_not_enough(self):
  q=self.req([self.create()]);q['reviews']['INTC']['security_type']='leveraged_fund'
  with self.assertRaises(ValueError):apply(self.j,self.d,q)
 def test_legacy_cannot_create_or_reprice(self):
  q=self.req([self.create()]);q['reviews']['INTC'].update(purpose='legacy_price_only',buy_recommendation=False)
  with self.assertRaises(ValueError):apply(self.j,self.d,q)
 def test_same_author_rejected(self):
  q=self.req([self.create()]);q['reviews']['INTC']['reviewer']='a'
  with self.assertRaises(ValueError):apply(self.j,self.d,q)
 def test_no_decision_rejected(self):
  q=self.req([self.create()]);q['reviews']['INTC'].pop('decision')
  with self.assertRaises(ValueError):apply(self.j,self.d,q)
 def test_unmodeled_threshold_rejected(self):
  q=self.req([self.create()]);q['operations'][0]['rule']['threshold']='99'
  with self.assertRaises(ValueError):apply(self.j,self.d,q)
 def test_leveraged_expiry_and_mapping(self):
  import hashlib
  q=self.req([self.create()]);m=q['reviews']['INTC'];m.update(security_type='leveraged_fund',entry_basis='underlying_value_and_path_and_cost',covered=['reset','benchmark','cost_ledger','favorable_trend','chop_and_crash','unlevered_comparison','mean_median_tail','probability_status','entry_conditions'])
  d=json.loads((self.p/'decision.json').read_text());d['bands'][0].update(underlying_condition={'symbol':'BASE','lte':40},anchor={'fund':50,'underlying':50},pre_entry_path_assumption='dated explicit paths')
  (self.p/'decision.json').write_text(json.dumps(d));m['decision']['sha256']=hashlib.sha256((self.p/'decision.json').read_bytes()).hexdigest()
  with self.assertRaises(ValueError):apply(self.j,self.d,q)
  q['operations'][0]['rule']['expires_at']='2099-01-01T00:00:00+00:00'
  self.assertEqual(apply(self.j,self.d,q)['status'],'applied')
if __name__=='__main__':unittest.main()
