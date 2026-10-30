"""Synthetic only: model-selection binding, not actual dividends or quotes."""
import copy, hashlib, json, tempfile, unittest
from pathlib import Path
from datetime import timedelta
import options_evidence as g
import options_american_checks as a
import options_surface_checks as surf
from test_options_evidence import Fixture
from test_options_surface_checks import fixture as surface_fixture

class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.f=Fixture(self.t.name);self.b=self.f.record['options_evidence']
 def tearDown(self):self.t.cleanup()
 def pin(self):
  self.f.review['path_probability_finding']='Conditional synthetic scenarios; no calibrated probability claim.'
  self.f.review['model_selection_sha256']=g.selection_digest(self.b['model_selection'])
  sel=self.b['model_selection'];ex=sel['exercise'];sf=sel['surface']
  self.f.review['checks']['exercise_and_carry']['artifact_refs']=['carry','carry-source']
  refs=['report']
  for ref in ex.get('cases',[]) if ex['route']=='american_fd' else []:refs += [ref['input_artifact_id'],ref['output_artifact_id']]
  if sf['route']=='diagnostic':refs += [sf['input_artifact_id'],sf['output_artifact_id']]
  self.f.review['checks']['model_adequacy']['artifact_refs']=refs
  self.f.refresh()
 def prepare(self):
  self.f.put('carry-source',{'synthetic':'issuer dividend policy and benchmark curve only'})
  self.f.put('carry',{'subject':self.f.packet['subject'],'verification':'source_verified','available_at':self.f.packet['as_of'],
    'valid_through':'2027-06-18','rate':.05,'yield':0,'dividends':[],'finding':'Synthetic verified no-dividend assumption and curve; future changes remain a risk.',
    'source_artifact_ids':['carry-source']})
  self.b['model_selection']={'version':g.MODEL_SELECTION_VERSION,'exercise':{'route':'analytical_equivalence','carry_artifact_id':'carry','equivalence_rationale':'Zero dividend call with nonnegative rates.'},'surface':{'route':'not_used','reason':'Bounded flat-IV stress is sufficient; no smile-derived valuation claimed.'},'path_review':{'route':'conditional_scenarios','probability_basis':'conditional_scenarios_not_calibrated','quantitative_probabilities':None,'reason':'Conditional stress cases only, no empirical probability asserted.'}}
  self.f.put('report',Path(self.f.arts['report']['path']).read_text().replace('</body>','<p>Probability basis: conditional_scenarios_not_calibrated</p></body>'))
  self.pin()
 def reject(self,pattern,**kw):
  with self.assertRaisesRegex(ValueError,pattern):g.validate(self.f.record,**kw)
 def american(self):
  self.prepare();cases=[]
  for case in self.b['scenario_cases']:
   base=self.f.get(case['input_artifact_id']);cid=case['contract_id'];leg=next(l for l in self.b['contracts'] if l['contract_id']==cid)
   p={'version':1,'contract_id':cid,'kind':'call','exercise':'american','as_of':g.stamp(self.f.packet['as_of']).date().isoformat(),'expiry':leg['expiry'],
      **{k:base[k] for k in ('spot','strike','rate','yield','volatility')},'dividends':[],
      'units':{'price':'USD_per_share','rate':'annual_continuous_decimal','yield':'annual_continuous_decimal','volatility':'annual_decimal'},
      'scenarios':[{'id':r['id'],'as_of':(g.stamp(self.f.packet['as_of'])+timedelta(days=r['elapsed_days'])).date().isoformat(),'spot':r['spot'],'volatility':r['volatility']} for r in base['scenarios']]}
   cases.append({'contract_id':cid,**self.f.pair(cid+'-fd',p,a)})
  self.b['model_selection']['exercise'].update(route='american_fd',method_sha256=hashlib.sha256(Path(a.__file__).read_bytes()).hexdigest(),cases=cases)
  self.f.put('report',Path(self.f.arts['report']['path']).read_text().replace('</body>','<p>American model: date-level FD diagnostic, not an executable quote</p><p>American FD IV: European quote-implied proxy or stated assumption; not American-calibrated IV</p></body>'));self.pin()
 def diagnostic(self):
  self.prepare();p=surface_fixture();old=p['symbol'];p['symbol']=self.f.packet['subject'];p['valuation_at']=self.f.packet['as_of']
  for row in p['contracts']:row['contract_id']=row['contract_id'].replace(old,p['symbol'],1)
  self.b['model_selection']['surface']={'route':'diagnostic','use':'diagnostic_only','limitations':'Historical data; not current or executable.',
     'method_sha256':hashlib.sha256(Path(surf.__file__).read_bytes()).hexdigest(),**self.f.pair('surface',p,surf)}
  self.f.put('report',Path(self.f.arts['report']['path']).read_text().replace('</body>','<p>Surface use: historical diagnostic only; not executable</p></body>'));self.pin()
 def test_historical_unchanged(self):self.assertEqual(g.validate(self.f.record)['status'],'validated')
 def test_new_publication_requires_selection(self):self.reject('model_selection',observed_publication_times=[g.MODEL_SELECTION_EFFECTIVE_AT])
 def test_path_route_mandatory(self):
  self.prepare();self.b['model_selection'].pop('path_review');self.pin();self.reject('path_review required')
 def test_conditional_numeric_probability_rejects(self):
  self.prepare();self.b['model_selection']['path_review']['quantitative_probabilities']={'profit':.8};self.pin();self.reject('cannot claim')
 def test_conditional_calibrated_claim_rejects(self):
  self.prepare();self.b['model_selection']['path_review']['probability_basis']='calibrated';self.pin();self.reject('cannot claim')
 def test_probability_visible_label_required(self):
  self.prepare();p=Path(self.f.arts['report']['path']).read_text().replace('Probability basis: conditional_scenarios_not_calibrated','');self.f.put('report',p);self.pin();self.reject('visible report lacks')
 def test_probability_independent_finding_required(self):
  self.prepare();self.f.review.pop('path_probability_finding');self.f.refresh();self.reject('explanation')
 def test_analytical_valid(self):self.prepare();self.assertEqual(g.validate(self.f.record)['status'],'validated')
 def test_no_assumed_carry(self):
  self.prepare();p=self.f.get('carry');p['verification']='assumed';self.f.put('carry',p);self.pin();self.reject('source-verified')
 def test_no_bool_verification(self):
  self.prepare();p=self.f.get('carry');p['verification']=True;self.f.put('carry',p);self.pin();self.reject('source-verified')
 def test_carry_through_expiry(self):
  self.prepare();p=self.f.get('carry');p['valid_through']='2026-10-24';self.f.put('carry',p);self.pin();self.reject('through expiry')
 def test_bad_carry_date(self):
  self.prepare();p=self.f.get('carry');p['valid_through']='zzzz';self.f.put('carry',p);self.pin();self.reject('horizon date')
 def test_nonzero_dividend_not_equivalent(self):
  self.prepare();p=self.f.get('carry');p['dividends']=[{'date':'2027-01-01','cash_per_share':1}];self.f.put('carry',p);self.pin();self.reject('equivalence requires')
 def test_carry_match_scenario(self):
  self.prepare();p=self.f.get('carry');p['rate']=.06;self.f.put('carry',p);self.pin();self.reject('carry differs')
 def test_source_required(self):
  self.prepare();p=self.f.get('carry');p['source_artifact_ids']=[];self.f.put('carry',p);self.pin();self.reject('source snapshots')
 def test_source_review_hash(self):
  self.prepare();self.f.review['artifact_hashes'].pop('carry-source');self.f.refresh(repin=False);self.reject('review hash')
 def test_carry_semantic_review_ref(self):
  self.prepare();self.f.review['checks']['exercise_and_carry']['artifact_refs']=['report'];self.f.refresh();self.reject('explicitly review carry')
 def test_advanced_semantic_review_ref(self):
  self.american();self.f.review['checks']['model_adequacy']['artifact_refs']=['report'];self.f.refresh();self.reject('advanced input/output')
 def test_selection_review_hash(self):
  self.prepare();self.b['model_selection']['surface']['reason']='Changed after review';self.reject('model_selection binding')
 def test_omitted_surface_reason(self):
  self.prepare();self.b['model_selection']['surface']['reason']='';self.pin();self.reject('explanation')
 def test_american_valid(self):self.american();self.assertEqual(g.validate(self.f.record)['status'],'validated')
 def test_american_iv_proxy_disclosure(self):
  self.american();v=Path(self.f.arts['report']['path']).read_text().replace('American FD IV: European quote-implied proxy or stated assumption; not American-calibrated IV','');self.f.put('report',v);self.pin();self.reject('visible report lacks')
 def test_american_missing_leg(self):
  self.american();self.b['model_selection']['exercise']['cases']=[];self.pin();self.reject('every exact leg')
 def test_american_stale_method(self):
  self.prepare();self.b['model_selection']['exercise'].update(route='american_fd',method_sha256='x');self.pin();self.reject('American method')
 def test_american_fake_output(self):
  self.american();ref=self.b['model_selection']['exercise']['cases'][0];p=self.f.get(ref['output_artifact_id']);p['base']['price']=0;self.f.put(ref['output_artifact_id'],p);self.pin();self.reject('recomputation')
 def test_american_wrong_spot(self):
  self.american();ref=self.b['model_selection']['exercise']['cases'][0];p=self.f.get(ref['input_artifact_id']);p['spot']=101;ref.update(self.f.pair('wrong-fd',p,a));self.pin();self.reject('inputs differ')
 def test_american_wrong_date(self):
  self.american();ref=self.b['model_selection']['exercise']['cases'][0];p=self.f.get(ref['input_artifact_id']);p['as_of']='2026-10-22';ref.update(self.f.pair('wrong-fd',p,a));self.pin();self.reject('identity/date')
 def test_surface_valid_diagnostic(self):self.diagnostic();self.assertEqual(g.validate(self.f.record)['status'],'validated')
 def test_surface_cannot_execute(self):
  self.diagnostic();self.b['model_selection']['surface']['use']='executable';self.pin();self.reject('cannot be executable')
 def test_surface_output_recompute(self):
  self.diagnostic();r=self.b['model_selection']['surface'];p=self.f.get(r['output_artifact_id']);p['nodes']=[];self.f.put(r['output_artifact_id'],p);self.pin();self.reject('recomputation')
 def test_surface_method_hash(self):
  self.diagnostic();self.b['model_selection']['surface']['method_sha256']='x';self.pin();self.reject('surface method')
 def test_surface_visible_historical_label(self):
  self.diagnostic();p=Path(self.f.arts['report']['path']).read_text().replace('Surface use: historical diagnostic only; not executable','Surface is live!');self.f.put('report',p);self.pin();self.reject('visible report lacks')

if __name__=='__main__':unittest.main()
