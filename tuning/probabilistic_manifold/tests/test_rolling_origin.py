from __future__ import annotations
import datetime as dt, hashlib, inspect, json, math, tempfile, unittest
from pathlib import Path
import tuning.probabilistic_manifold.rolling_origin as r

HERE=Path(__file__).resolve().parents[1]
CONFIG=HERE/'rolling-config.v1.json'
def cfg(): return r.load_rolling_config(HERE,CONFIG.name)
def roster(c=None): return r.load_session_roster(HERE/'artifacts','session-roster.v1.json',c or cfg())

class ConfigAndIdentityTests(unittest.TestCase):
 def bad(self,mutator):
  value=json.loads(CONFIG.read_text()); mutator(value)
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); (root/'bad.json').write_text(json.dumps(value))
   with self.assertRaises(r.RollingError): r.load_rolling_config(root,'bad.json')
 def test_config_source_calendar_anchor_and_basis_are_frozen(self):
  c=cfg(); self.assertEqual(c['source_contract']['owned_source_manifest_v2_sha256'],'5ca62dc8cf180203b71e5e1e232d53d934285baa7242e54e72786abaa9b8436f'); self.assertEqual(c['calendar']['session_roster_sha256'],'f2b0358d1dfa9f44d34c62947eb52a6dacdaec314931b405a4390a77fdceabb8'); self.assertEqual((c['calendar']['calendar_id'],c['calendar']['calendar_version'],c['calendar']['fixed_origin_anchor_date']),('XNYS','observed-yahoo-session-roster-v1','2010-08-12'))
 def test_config_mutations_all_fail(self):
  muts=[lambda c:c.update(extra=1),lambda c:c['source_contract'].update(owned_source_manifest_v2_sha256='0'*64),lambda c:c['calendar'].update(session_roster_sha256='0'*64),lambda c:c['calendar'].update(fixed_origin_anchor_index=127),lambda c:c['price_basis'].update(adjustment_vintage='other'),lambda c:c['targets']['primary_126'].update(material_loss_threshold=-.2),lambda c:c['targets']['secondary_252'].update(material_loss_threshold=-.3),lambda c:c['rolling']['primary'].update(embargo_sessions=0),lambda c:c['rolling']['secondary'].update(purge_sessions=126),lambda c:c['rolling'].update(protected_origin_start='2024-01-31'),lambda c:c['target_baselines']['material_loss'].__setitem__(0,'mean'),lambda c:c['decision_policy'].update(diagnostic_selection_allowed=True),lambda c:c['models'].update(probability_clip=.5),lambda c:c.update(variant_budget=3)]
  for m in muts:
   with self.subTest(m=m): self.bad(m)
 def test_session_roster_is_metadata_only_and_embargo_derives_protected_start(self):
  c=cfg(); dates=roster(c); self.assertEqual(len(dates),4211); self.assertEqual(dates[126],dt.date(2010,8,12)); ci=dates.index(dt.date(2023,12,29)); self.assertEqual(dates[ci+22],dt.date(2024,2,1))
 def test_roster_tamper_fails(self):
  c=cfg(); value=json.loads((HERE/'artifacts/session-roster.v1.json').read_text()); value['sessions'][0]='2010-02-12'
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); (root/'roster.json').write_text(json.dumps(value))
   with self.assertRaises(r.RollingError): r.load_session_roster(root,'roster.json',c)

class SplitAndAdapterTests(unittest.TestCase):
 def test_development_origin_counts_and_membership(self):
  c=cfg(); dates=roster(c); self.assertEqual(len(r.build_origins(dates,c,'primary')),26); self.assertEqual(len(r.build_origins(dates,c,'secondary')),13); self.assertEqual(len(r.build_origins(dates,c,'diagnostic')),155); self.assertTrue(all(o.maturity_date<=dt.date(2023,12,29) for f in ('primary','secondary','diagnostic') for o in r.build_origins(dates,c,f)))
 def test_primary_and_secondary_purge_plus_embargo(self):
  c=cfg(); dates=roster(c)
  for family in ('primary','secondary'):
   origins=r.build_origins(dates,c,family); spec=c['rolling'][family]; evaluation=origins[-1]; training=r.expanding_training_origins(origins,evaluation,spec['purge_sessions'],spec['embargo_sessions'],1); self.assertTrue(all(o.maturity_index<=evaluation.origin_index-spec['purge_sessions']-21 for o in training))
 def test_diagnostic_is_nonselective(self): self.assertFalse(cfg()['rolling']['diagnostic']['selection_allowed']); self.assertFalse(cfg()['decision_policy']['diagnostic_selection_allowed'])
 def test_adapter_is_lazy_and_allowlisted(self):
  c=cfg(); calls=[]; meta={'source_manifest_v2_sha256':c['source_contract']['owned_source_manifest_v2_sha256'],'calendar_id':'XNYS','calendar_version':c['calendar']['calendar_version'],'session_roster_sha256':c['calendar']['session_roster_sha256'],'protected_outcomes_accessed':False}; allowed={'dev1':'2023-12-29'}
  adapter=r.DevelopmentDataAdapter(meta,{'dev1':{'x':1.0}},allowed,lambda ids:(calls.append(tuple(ids)) or {'dev1':{'return':.1}}),c); self.assertEqual(calls,[]); self.assertEqual(adapter.load_labels(['dev1'])['dev1']['return'],.1); self.assertEqual(calls,[('dev1',)])
 def test_adapter_rejects_protected_ids_and_mismatched_loader(self):
  c=cfg(); meta={'source_manifest_v2_sha256':c['source_contract']['owned_source_manifest_v2_sha256'],'calendar_id':'XNYS','calendar_version':c['calendar']['calendar_version'],'session_roster_sha256':c['calendar']['session_roster_sha256'],'protected_outcomes_accessed':False}; adapter=r.DevelopmentDataAdapter(meta,{}, {'dev1':'2023-12-29'},lambda ids:{},c)
  with self.assertRaisesRegex(r.RollingError,'PROTECTED_ACCESS_DENIED'): adapter.load_labels(['protected'])
  with self.assertRaisesRegex(r.RollingError,'SPLIT_VIOLATION'): adapter.load_labels(['dev1'])
 def test_development_split_has_ids_only_and_protected_has_none(self):
  dev=json.loads((HERE/'artifacts/development-split.v1.json').read_text()); protected=json.loads((HERE/'artifacts/protected-split.v1.json').read_text()); self.assertFalse(dev['contains_outcomes']); self.assertFalse(dev['protected_outcomes_accessed']); self.assertEqual(protected['origin_ids'],[]); self.assertFalse(protected['contains_outcomes'])

class ModelsAndValidationTests(unittest.TestCase):
 def test_past_feature_leakage(self):
  t=[100*1.001**i for i in range(400)]; q=[100*1.0004**i for i in range(400)]; a=r.past_price_features(t,q,250); changed=t[:251]+[v*9 for v in t[251:]]; self.assertEqual(a,r.past_price_features(changed,q,250))
 def test_ridge_validation_and_determinism(self):
  x=[[float(i)] for i in range(-4,5)]; y=[2+3*v[0] for v in x]; m=r.fit_ridge(x,y,.1); self.assertEqual(m,r.fit_ridge(x,y,.1)); self.assertAlmostEqual(r.predict_ridge(m,[2]),8,places=1)
  for bad in (0,-1,float('nan')):
   with self.assertRaises(r.RollingError): r.fit_ridge(x,y,bad)
  with self.assertRaises(r.RollingError): r.fit_ridge([[1],[float('nan')]],[1,2],1)
 def test_logistic_strict_validation(self):
  x=[[-2.],[-1.],[1.],[2.]]; y=[0,0,1,1]; m=r.fit_logistic(x,y,1,.05,100,1e-6); self.assertLess(r.predict_logistic(m,[-2]),.5); self.assertGreater(r.predict_logistic(m,[2]),.5)
  for args in ((0,.05,100,1e-6),(1,0,100,1e-6),(1,.05,0,1e-6),(1,.05,100,.5)):
   with self.assertRaises(r.RollingError): r.fit_logistic(x,y,*args)
  with self.assertRaises(r.RollingError): r.fit_logistic(x,[0,2,1,1],1,.05,100,1e-6)
 def test_quantile_and_residual_validation(self):
  self.assertEqual(r.residual_quantiles([1,2],[0,2],[.05,.5,.95]),r.residual_quantiles([1,2],[0,2],[.05,.5,.95]))
  for probs in ((.5,.05),(-.1,.5),(.5,.5)):
   with self.assertRaises(r.RollingError): r.residual_quantiles([1,2],[0,2],probs)
 def test_equal_length_interval_and_binary_validation(self):
  with self.assertRaises(r.RollingError): r.regression_metrics([1],[1,2],[0],[2],[0],0)
  with self.assertRaises(r.RollingError): r.regression_metrics([1],[1],[2],[0],[0],0)
  with self.assertRaises(r.RollingError): r.binary_metrics([0,1],[.2],1e-6)
  with self.assertRaises(r.RollingError): r.binary_metrics([0,2],[.2,.8],1e-6)

class ScoringDecisionTests(unittest.TestCase):
 def test_all_abstain_is_null_inconclusive(self):
  reg=r.regression_metrics([1,2],[None,None],[None,None],[None,None],[0],1); binary=r.binary_metrics([0,1],[None,None],1e-6); self.assertEqual((reg['status'],reg['abstention_rate'],reg['mae']),('inconclusive',1.0,None)); self.assertEqual((binary['status'],binary['abstention_rate'],binary['brier']),('inconclusive',1.0,None))
 def test_tail_threshold_uses_all_training_before_abstention(self): self.assertAlmostEqual(r.freeze_tail_threshold([0,1,2,3],.1),.3)
 def test_crps_and_regression_metrics(self):
  self.assertGreaterEqual(r.empirical_crps(1,1,[-1,0,1]),0); result=r.regression_metrics([0,1],[0,.8],[-.5,.5],[.5,1.1],[-.1,0,.1],.1); self.assertEqual(result['status'],'scored'); self.assertEqual(result['interval_coverage'],1)
 def test_target_specific_baselines_and_prevalence(self):
  f=[{'tqqq_return_63':.1,'realized_volatility_21':.2,'qqq_return_126':.05}]; self.assertEqual(r.baseline_predictions('material_loss',[0,1],f)['unconditional_training_prevalence'],[.5]); self.assertEqual(r.baseline_predictions('return',[.1,.3],f)['cash_zero'],[0.])
 def test_matched_retained_origins(self): self.assertEqual(r.matched_retained_ids({'a':1,'b':2},{'candidate':{'a':.1,'b':None},'baseline':{'a':.2,'b':.3}}),['a'])
 def test_primary_decision_adopt_reject_tie_inconclusive(self):
  self.assertEqual(r.paired_bootstrap_decision([.1,.1],[.3,.3],100,1)['decision'],'adopt'); self.assertEqual(r.paired_bootstrap_decision([.3,.3],[.1,.1],100,1)['decision'],'reject'); self.assertEqual(r.paired_bootstrap_decision([.2],[.2],100,1)['decision'],'tie'); self.assertEqual(r.paired_bootstrap_decision([.1,.3],[.2,.2],100,1)['decision'],'tie')
 def test_candidate_macro_only_ablation(self):
  c=cfg(); base=r.candidate_feature_names(c,'price_path_base'); plus=r.candidate_feature_names(c,'price_path_plus_macro'); self.assertEqual(set(plus)-set(base),r.MACRO_FEATURES)
  with self.assertRaises(r.RollingError): r.candidate_feature_names(c,'macro_only')

class LedgerAndReceiptTests(unittest.TestCase):
 def load_ledger(self): return json.loads((HERE/'artifacts/rolling-attempt-ledger.v1.json').read_text())
 def event(self,seq,attempt,candidate,status,error=None,target='primary_126.material_loss'): return {'sequence':seq,'attempt_id':attempt,'candidate_id':candidate,'target_id':target,'status':status,'error_code':error,'protected_outcomes_accessed':False}
 def test_empty_ledger_bindings_and_hash_validate(self): r.validate_ledger(self.load_ledger(),cfg()); self.assertEqual(self.load_ledger()['variant_budget'],2)
 def test_ledger_legal_transitions_and_chain(self):
  c=cfg(); ledger=self.load_ledger(); ledger=r.append_ledger_event(ledger,self.event(1,'a1','price_path_base','registered'),c); ledger=r.append_ledger_event(ledger,self.event(2,'a1','price_path_base','completed'),c); r.validate_ledger(ledger,c); self.assertEqual(ledger['events'][1]['previous_hash'],ledger['events'][0]['event_hash'])
 def test_failed_attempt_consumes_budget_no_reset(self):
  c=cfg(); ledger=self.load_ledger(); ledger=r.append_ledger_event(ledger,self.event(1,'a1','price_path_base','registered'),c); ledger=r.append_ledger_event(ledger,self.event(2,'a1','price_path_base','failed','NUMERIC_FAILURE'),c); ledger=r.append_ledger_event(ledger,self.event(3,'a2','price_path_plus_macro','registered'),c); ledger=r.append_ledger_event(ledger,self.event(4,'a2','price_path_plus_macro','failed','SUPPORT_ABSTENTION'),c)
  with self.assertRaises(r.RollingError): r.append_ledger_event(ledger,self.event(5,'a3','price_path_base','registered'),c)
 def test_ledger_rejects_protected_and_tamper(self):
  c=cfg(); ledger=self.load_ledger(); bad=self.event(1,'a','price_path_base','registered'); bad['protected_outcomes_accessed']=True
  with self.assertRaises(r.RollingError): r.append_ledger_event(ledger,bad,c)
  ledger=r.append_ledger_event(ledger,self.event(1,'a','price_path_base','registered'),c); ledger['events'][0]['status']='completed'
  with self.assertRaises(r.RollingError): r.validate_ledger(ledger,c)
 def test_prereg_is_self_contained_and_receipts_bound(self):
  pre=json.loads((HERE/'artifacts/rolling-preregistration.v1.json').read_text()); dev=json.loads((HERE/'artifacts/development-split.v1.json').read_text()); protected=json.loads((HERE/'artifacts/protected-split.v1.json').read_text()); self.assertIn('frozen_protocol',pre); self.assertFalse(pre['protected_outcomes_accessed']); self.assertFalse(dev['protected_outcomes_accessed']); self.assertFalse(protected['protected_outcomes_accessed'])
 def test_cli_has_no_real_run_or_protected_loader(self):
  source=inspect.getsource(r.main); self.assertIn('preregister',source); self.assertNotIn('real_run',source); self.assertNotIn('protected_path',inspect.getsource(r.DevelopmentDataAdapter))

if __name__=='__main__': unittest.main()
