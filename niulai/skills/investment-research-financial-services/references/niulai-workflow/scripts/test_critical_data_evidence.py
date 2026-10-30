import copy,hashlib,json,tempfile,unittest
from pathlib import Path
import critical_data_evidence as g
import evidence_crosscheck as c
from test_evidence_crosscheck import example
STAMP='2026-10-24T00:11:00Z'
class Fixture:
 def __init__(self,d,primary=False):
  self.d=Path(d);self.arts={};self.put('model',{'price':'100'});self.put('source_a',{'price':'100','publisher':'a'});self.put('source_b',{'price':'100','publisher':'b'})
  p=example();p['as_of']=STAMP
  for o,aid in zip(p['observations'],('source_a','source_b')):
   o.update(observed_at='2026-10-24T00:10:00Z',available_at='2026-10-24T00:10:01Z');o['source']['sha256']=self.arts[aid]['sha256']
  self.put('cmp_in',p);self.put('cmp_out',c.calculate(p))
  row={'key':'price','input':{'artifact_id':'model','pointer':'/price'},'value':'100','definition':p['observations'][0]['definition'],'unit':'USD/share','decision_relevance':'Entry depends on price.','route':'crosscheck','tolerance_and_freshness_rationale':'Fixed synthetic policy before results.','comparison':{'input_artifact_id':'cmp_in','output_artifact_id':'cmp_out','selected_observation':0,'source_artifact_ids':['source_a','source_b']}}
  self.needs={'model','ledger','cmp_in','cmp_out','source_a','source_b'}
  if primary:
   self.put('attempt',{'result':'Synthetic provider unavailable.'});self.put('calc',{'formula':'200-input','outcomes':[110,100,90]})
   self.put('sens',{'input_key':'price','unit':'USD/share','lower':'90','base':'100','upper':'110','cases':[{'input_value':str(x),'decision_metric':'synthetic','decision_metric_value':str(200-x),'action':'wait'} for x in (90,100,110)],'conclusion_action':'wait','limitations':'Synthetic range only.','calculation_method':'200-input','calculation_artifact_ids':['calc']})
   row.update(route='primary_only',exception={'reason':'No second comparable source.','alternative_attempt':'Synthetic provider error retained.','authority_rationale':'Original issuer.','source_id':'issuer','passage_id':'p1','attempt_artifact_id':'attempt','sensitivity_artifact_id':'sens'})
   self.needs={'model','ledger','source_a','attempt','sens','calc'}
  self.ledger={'version':g.VERSION,'subject':'SYNTHETIC','cutoff':STAMP,'decision_action':'wait','model_input_artifact_ids':['model'],'critical_keys':['price'],'items':[row]}
  self.r={'scope':'company_full','status':'complete','subject':{'ticker':'SYNTHETIC','cutoff':STAMP},'model':{'input_artifact_ids':['model']},'critical_data_evidence':{'version':g.VERSION,'status':'reviewed','ledger_artifact_id':'ledger','review_artifact_id':'review'},'sources':[{'id':'issuer','source_type':'primary','snapshot_artifact_id':'source_a','retrieved_at':'2026-10-24T00:10:10Z','passages':[{'id':'p1','text':'Synthetic100.'}]}],'audit':{'author_id':'author','independent_review':{'reviewer_id':'critic','reviewed_artifact_ids':['ledger','review']}}}
  self.refresh()
 def put(self,aid,value):
  p=self.d/(aid+'.json');p.write_text(json.dumps(value,sort_keys=True));self.arts[aid]={'id':aid,'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
 def get(self,aid):return json.loads(Path(self.arts[aid]['path']).read_text())
 def refresh(self):
  self.put('ledger',self.ledger)
  self.review={'version':g.VERSION,'status':'approved_critical_data','reviewer_id':'critic','subject':'SYNTHETIC','cutoff':STAMP,'critical_keys':copy.deepcopy(self.ledger['critical_keys']),'model_input_artifact_ids':['model'],'coverage_finding':'Independently inspected all model inputs and declared critical keys.','items':[{'key':x['key'],'route':x['route'],'status':'reviewed','source_lineage_finding':'Original provenance checked.','definition_and_extraction_finding':'Price extracted and model mapping checked.','decision_impact_finding':'No buy supported.','sensitivity_calculation_finding':'Independently checked200-input.','range_adequacy_finding':'Explicit synthetic range.'} for x in self.ledger['items']],'artifact_hashes':{a:self.arts[a]['sha256'] for a in sorted(self.needs)}}
  self.review['source_record_hashes']={x['id']:hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest() for x in self.r['sources']} if any(x['route']=='primary_only' for x in self.ledger['items']) else {}
  self.save_review()
 def save_review(self):self.put('review',self.review);self.r['artifacts']=list(self.arts.values())
 def run(self,**kw):return g.validate(self.r,**kw)
 def recompare(self,p):self.put('cmp_in',p);self.put('cmp_out',c.calculate(p));self.refresh()
class Tests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.f=Fixture(self.t.name)
 def tearDown(self):self.t.cleanup()
 def test_pass(self):self.assertEqual(self.f.run()['status'],'validated');self.assertFalse(self.f.run()['semantic_truth_verified'])
 def test_scopes(self):
  for scope in ('company_full','fund_full','crypto_full'):self.f.r['scope']=scope;self.assertEqual(self.f.run()['status'],'validated')
 def test_narrow(self):self.f.r['scope']='narrow';self.assertEqual(self.f.run()['status'],'historical_or_narrow_exempt')
 def test_history_and_actual_publication(self):
  self.f.r.pop('critical_data_evidence');self.f.r['subject']['cutoff']='2026-10-23T00:00:00Z';self.assertEqual(self.f.run()['status'],'historical_or_narrow_exempt')
  with self.assertRaisesRegex(ValueError,'versioned'):self.f.run(observed_publication_times=[STAMP])
 def test_missing_block(self):
  self.f.r.pop('critical_data_evidence')
  with self.assertRaisesRegex(ValueError,'versioned'):self.f.run()
 def test_pending(self):
  self.f.r['critical_data_evidence']['status']='pending'
  with self.assertRaisesRegex(ValueError,'pending'):self.f.run()
  self.f.r['status']='partial';self.assertEqual(self.f.run()['status'],'pending')
 def test_missing_critical(self):
  self.f.ledger['critical_keys'].append('debt');self.f.refresh()
  with self.assertRaisesRegex(ValueError,'omitted'):self.f.run()
 def test_missing_model_inventory(self):
  self.f.r['model']['input_artifact_ids'].append('missing')
  with self.assertRaisesRegex(ValueError,'inventory'):self.f.run()
 def test_bool_value(self):
  self.f.put('model',{'price':True});self.f.refresh()
  with self.assertRaisesRegex(ValueError,'numeric'):self.f.run()
 def test_actual_value_mismatch(self):
  self.f.put('model',{'price':'101'});self.f.refresh()
  with self.assertRaisesRegex(ValueError,'differs'):self.f.run()
 def test_stale_bytes(self):
  Path(self.f.arts['model']['path']).write_text('{}')
  with self.assertRaisesRegex(ValueError,'hash'):self.f.run()
 def test_false_output(self):
  x=self.f.get('cmp_out');x['status']='unverified';self.f.put('cmp_out',x);self.f.refresh()
  with self.assertRaisesRegex(ValueError,'reproducible'):self.f.run()
 def test_disagreement(self):
  p=self.f.get('cmp_in');p['observations'][1]['value']='90';self.f.recompare(p)
  with self.assertRaisesRegex(ValueError,'discrepancy'):self.f.run()
 def test_stale_quote(self):
  p=self.f.get('cmp_in');p['max_age_seconds']=10;self.f.recompare(p)
  with self.assertRaisesRegex(ValueError,'unavailable'):self.f.run()
 def test_shared_upstream(self):
  p=self.f.get('cmp_in');p['observations'][1]['source']['upstream_family']=p['observations'][0]['source']['upstream_family'];self.f.recompare(p);self.assertEqual(self.f.run()['status'],'validated')
 def test_hash_required(self):
  p=self.f.get('cmp_in');p['require_source_hashes']=False;self.f.recompare(p)
  with self.assertRaisesRegex(ValueError,'hashes mandatory'):self.f.run()
 def test_payload_hash(self):
  self.f.put('source_a',{'different':1});self.f.refresh()
  with self.assertRaisesRegex(ValueError,'payload hash'):self.f.run()
 def test_fake_boolean_review(self):
  self.f.review['coverage_finding']=True;self.f.save_review()
  with self.assertRaisesRegex(ValueError,'explanation'):self.f.run()
 def test_same_reviewer(self):
  self.f.r['audit']['author_id']='team/critic'
  with self.assertRaisesRegex(ValueError,'independent'):self.f.run()
 def test_missing_review(self):
  self.f.review['items']=[];self.f.save_review()
  with self.assertRaisesRegex(ValueError,'every critical'):self.f.run()
 def test_stale_review(self):
  self.f.review['artifact_hashes']['model']='a'*64;self.f.save_review()
  with self.assertRaisesRegex(ValueError,'exact current'):self.f.run()
 def test_action_mismatch(self):
  with self.assertRaisesRegex(ValueError,'published action'):self.f.run(decision_action='buy')
 def test_primary(self):
  f=Fixture(self.t.name,True);self.assertEqual(f.run()['primary_only_exceptions'],['price'])
 def test_primary_missing_attempt(self):
  f=Fixture(self.t.name,True);f.ledger['items'][0]['exception'].pop('attempt_artifact_id');f.refresh()
  with self.assertRaisesRegex(ValueError,'missing artifact'):f.run()
 def test_primary_record(self):
  f=Fixture(self.t.name,True);f.r['sources'][0]['source_type']='secondary'
  with self.assertRaisesRegex(ValueError,'primary source'):f.run()
 def test_primary_metadata_mutation(self):
  f=Fixture(self.t.name,True);f.r['sources'][0]['passages'][0]['text']='Altered after review'
  with self.assertRaisesRegex(ValueError,'metadata'):f.run()
 def test_duplicate_source(self):
  f=Fixture(self.t.name,True);f.r['sources'].append(copy.deepcopy(f.r['sources'][0]))
  with self.assertRaisesRegex(ValueError,'duplicate source'):f.run()
 def test_sensitivity_bounds(self):
  f=Fixture(self.t.name,True);v=f.get('sens');v.update(lower='100',upper='100');f.put('sens',v);f.refresh()
  with self.assertRaisesRegex(ValueError,'nondegenerate'):f.run()
 def test_switch_wait_or_reject(self):
  f=Fixture(self.t.name,True);v=f.get('sens');v['cases'][0]['action']='buy';f.put('sens',v);f.refresh();self.assertEqual(f.run()['status'],'validated')
  v['conclusion_action']='buy';f.put('sens',v);f.refresh()
  with self.assertRaisesRegex(ValueError,'uncertainty'):f.run()
 def test_primary_review_math_required(self):
  f=Fixture(self.t.name,True);f.review['items'][0].pop('sensitivity_calculation_finding');f.save_review()
  with self.assertRaisesRegex(ValueError,'explanation'):f.run()
 def test_json_pointer(self):
  self.assertEqual(g.pointer({'a/b':{'~x':10}},'/a~1b/~0x'),10)
  with self.assertRaises(ValueError):g.pointer({'a':1},'/a~9')
if __name__=='__main__':unittest.main()
