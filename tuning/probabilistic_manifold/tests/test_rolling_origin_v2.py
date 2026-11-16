from __future__ import annotations
import hashlib,json,math,shutil,tempfile,unittest
from pathlib import Path
from unittest import mock
import tuning.probabilistic_manifold.rolling_origin as r
from tuning.probabilistic_manifold.rolling_outcomes import exact_targets
HERE=Path(__file__).resolve().parents[1]; ART=HERE/'artifacts'

def config(): return r.load_v2_config(HERE)
def copy_receipts(root:Path):
 for name in ('source-manifest.v2.json','session-roster.v1.json','development-split.v7.json','development-features.v3.json','development-support.v3.json','rolling-preregistration.v7.json','protected-split.v7.json'): shutil.copy2(ART/name,root/name)
 # Unit runs start from canonical genesis, never from the legitimate consumed ledger.
 ledger=json.loads((ART/'rolling-attempt-ledger.v7.json').read_text()); ledger['events']=[]; ledger['head_hash']=ledger['genesis_hash']
 (root/'rolling-attempt-ledger.v7.json').write_bytes(r.canonical_json_bytes(ledger))
def dev_rows(root:Path): return json.loads((root/'development-split.v7.json').read_text())['groups']['primary']
def features(root:Path,support='inside'):
 names=config()['features']['price_path_base']; return {row['origin_id']:{**{name:(i+1)*.001*(j+1) for j,name in enumerate(names)},'support_status':support,'qqq_path_126':[100*(1.0002**k) for k in range(127)]} for i,row in enumerate(dev_rows(root))}
def labels_for(ids):
 return {item:{'return':(.02 if i%2 else -.01),'max_drawdown':(-.3 if i%3==0 else -.1),'relative_qqq':(.01 if i%2 else -.02),'material_loss':int(i%3==0),'qqq_3x_path_drawdown':-.1} for i,item in enumerate(ids)}

class ConfigOutcomeTests(unittest.TestCase):
 def test_blocked_hashes_changed_and_v2_rules_frozen(self):
  c=config(); self.assertNotEqual(hashlib.sha256((HERE/'rolling-config.v2.json').read_bytes()).hexdigest(),'6821f2f01ec5e98f647b51241e98e05d1147b79e505cd3698587a7d6dd78d687'); self.assertNotEqual(hashlib.sha256((HERE/'rolling_origin.py').read_bytes()).hexdigest(),'3ae0f1228a4ab397232480d413b4ad5160c3bc351aae886fb0f14e85a70adff9'); self.assertEqual(c['rolling']['primary']['minimum_training_origins'],18); self.assertEqual(c['decision']['minimum_retained_n'],5); self.assertFalse(c['targets']['secondary_252']['execute_in_initial_runner'])
 def test_exact_outcomes_126_and_252(self):
  t=[100.0]*300; q=[100.0]*300; t[50]=70; a=exact_targets(t,q,0,126); b=exact_targets(t,q,0,252); self.assertEqual((a['threshold'],b['threshold']),(-.25,-.40)); self.assertEqual(a['material_loss'],1); self.assertEqual(b['horizon'],252)
 def test_outcomes_reject_nonfinite_and_incomplete(self):
  with self.assertRaises(r.RollingError): exact_targets([100,float('nan')],[100,100],0,126)
  with self.assertRaises(r.RollingError): exact_targets([100]*10,[100]*10,0,126)
 def test_retired_minus_point_three_is_excluded(self): self.assertEqual(config()['retired_contracts']['status'],'not_part_of_protocol_v2')

class AdapterReceiptTests(unittest.TestCase):
 def test_from_receipts_derives_allowlist_and_is_lazy(self):
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); copy_receipts(root); adapter=r.V2DevelopmentDataAdapter.from_receipts(HERE,root,HERE.parents[1]); self.assertEqual(adapter._label_loader.__class__.__name__,'ConcreteDevelopmentLabelLoader'); self.assertEqual(len(adapter.allowed),26)
 def test_receipt_mismatch_forged_ids_and_wrong_labels_fail(self):
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); copy_receipts(root); pre=json.loads((root/'rolling-preregistration.v7.json').read_text()); pre['bindings']['calendar_roster_sha256']='0'*64; (root/'rolling-preregistration.v7.json').write_text(json.dumps(pre))
   with self.assertRaises(r.RollingError): r.V2DevelopmentDataAdapter.from_receipts(HERE,root,HERE.parents[1])
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); copy_receipts(root); adapter=r.V2DevelopmentDataAdapter.from_receipts(HERE,root,HERE.parents[1]); adapter._label_loader.load=lambda ids:{}; one=next(iter(adapter.allowed))
   with self.assertRaises(r.RollingError): adapter.load_labels([one])

class FiniteBaselineTests(unittest.TestCase):
 def test_crps_residual_matched_empty_and_nonfinite_fail(self):
  with self.assertRaises(r.RollingError): r.empirical_crps(1,1,[float('nan')])
  with self.assertRaises(r.RollingError): r.residual_quantiles([1,float('inf')],[1,2],[.05,.5,.95])
  with self.assertRaises(r.RollingError): r.matched_retained_ids({}, {'x':{}})
  with self.assertRaises(r.RollingError): r.matched_retained_ids({'a':1},{'x':{'a':float('nan')}})
 def test_all_abstain_null_and_inconclusive(self):
  x=r.binary_metrics([0,1],[None,None],1e-6); self.assertEqual((x['status'],x['abstention_rate'],x['brier']),('inconclusive',1.0,None))
 def test_qqq_drawdown_is_daily_path_based(self):
  path=[100,90,99]; result=r.qqq_daily_3x_path_drawdown(path); self.assertLess(result,-.29); self.assertGreater(result,-.31)
 def test_honest_trend_names_and_matched_scoring(self):
  c=config(); self.assertIn('linear_trend_volatility_score',c['baselines']['return']); self.assertIn('qqq_daily_3x_path_drawdown',c['baselines']['max_drawdown']); self.assertEqual(r.matched_retained_ids({'a':1,'b':0},{'candidate':{'a':.2,'b':None},'baseline':{'a':.3,'b':.4}}),['a'])

class LedgerCASTests(unittest.TestCase):
 def event(self,ledger,status='registered',attempt='a1',candidate='price_path_base',role='primary_selectable',result=None,error=None): return {'sequence':len(ledger['events'])+1,'attempt_id':attempt,'candidate_id':candidate,'target_id':'primary_126.material_loss','role':role,'status':status,'error_code':error,'run_digest':'1'*64,'evidence_digest':'2'*64,'result_digest':result,'protected_outcomes_accessed':False}
 def test_authority_legal_map_genesis_and_append_validation(self):
  c=config(); ledger=json.loads((ART/'rolling-attempt-ledger.v7.json').read_text()); r.validate_v2_ledger(ledger,c,ledger['authority_bindings']); bad=dict(ledger); bad['legal_transitions']={'none':[]}
  with self.assertRaises(r.RollingError): r.validate_v2_ledger(bad,c)
  tamper=dict(ledger); tamper['genesis_hash']='0'*64
  with self.assertRaises(r.RollingError): r.append_v2_event(tamper,self.event(tamper),c,tamper['authority_bindings'])
 def test_cas_stale_head_and_no_budget_reset(self):
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); copy_receipts(root); c=config(); ledger=json.loads((root/'rolling-attempt-ledger.v7.json').read_text()); auth=ledger['authority_bindings']
   with self.assertRaisesRegex(r.RollingError,'stale'): r.cas_update_v2_ledger(root,'rolling-attempt-ledger.v7.json','0'*64,self.event(ledger),c,auth)
   for attempt,candidate,role in (('a1','price_path_base','primary_selectable'),('a2','price_path_plus_macro','exploratory_ablation')):
    ledger=r.cas_update_v2_ledger(root,'rolling-attempt-ledger.v7.json',ledger['head_hash'],self.event(ledger,attempt=attempt,candidate=candidate,role=role),c,auth); ledger=r.cas_update_v2_ledger(root,'rolling-attempt-ledger.v7.json',ledger['head_hash'],self.event(ledger,'failed',attempt,candidate,role,error='NUMERIC_FAILURE'),c,auth)
   with self.assertRaises(r.RollingError): r.append_v2_event(ledger,self.event(ledger,attempt='a3'),c,auth)
 def test_nonempty_ledger_prereg_reset_refused(self):
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); copy_receipts(root); c=config(); ledger=json.loads((root/'rolling-attempt-ledger.v7.json').read_text()); auth=ledger['authority_bindings']; ledger=r.append_v2_event(ledger,self.event(ledger),c,auth); (root/'rolling-attempt-ledger.v7.json').write_text(json.dumps(ledger))
   with self.assertRaisesRegex(r.RollingError,'nonempty'): r.preregister_v2(HERE,root,HERE.parents[1])
 def test_lock_symlink_rejected(self):
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); copy_receipts(root); (root/'.rolling-attempt-ledger.v7.json.lock').symlink_to(root/'target'); ledger=json.loads((root/'rolling-attempt-ledger.v7.json').read_text())
   with self.assertRaises(Exception): r.cas_update_v2_ledger(root,'rolling-attempt-ledger.v7.json',ledger['head_hash'],self.event(ledger),config(),ledger['authority_bindings'])
 def test_malformed_rehashed_history_rejected(self):
  c=config(); ledger=json.loads((ART/'rolling-attempt-ledger.v7.json').read_text()); event=self.event(ledger); event['role']='exploratory_ablation'; payload={**event,'previous_hash':ledger['head_hash'],'authority_bindings':ledger['authority_bindings']}; payload['event_hash']=hashlib.sha256(r.canonical_json_bytes(payload)).hexdigest(); ledger['events']=[payload]; ledger['head_hash']=payload['event_hash']
  with self.assertRaises(r.RollingError): r.validate_v2_ledger(ledger,c)
 def test_unknown_write_fence(self):
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); copy_receipts(root); c=config(); ledger=json.loads((root/'rolling-attempt-ledger.v7.json').read_text()); auth=ledger['authority_bindings']
   with mock.patch.object(r,'write_canonical_json',side_effect=OSError('before write')):
    with self.assertRaisesRegex(r.RollingError,'UNKNOWN_WRITE'): r.cas_update_v2_ledger(root,'rolling-attempt-ledger.v7.json',ledger['head_hash'],self.event(ledger),c,auth)

class DevelopmentRunnerTests(unittest.TestCase):
 def test_runner_registers_before_labels_min18_retained5_secondary_skipped(self):
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); copy_receipts(root); seen=[]
   def loader(ids):
    ledger=json.loads((root/'rolling-attempt-ledger.v7.json').read_text()); seen.append(ledger['events'][-1]['status']); return labels_for(ids)
   adapter=r.V2DevelopmentDataAdapter.from_receipts(HERE,root,HERE.parents[1]); adapter._label_loader.load=loader; adapter.support={key:{'status':'inside'} for key in adapter.allowed}; result=r.run_v2_development(adapter,root,'synthetic-run'); self.assertTrue(seen and seen[0]=='registered'); self.assertGreaterEqual(result['evaluated_n'],5); self.assertGreaterEqual(result['retained_n'],5); self.assertEqual(result['candidate_id'],'price_path_base'); self.assertEqual(result['exploratory']['secondary_252']['status'],'not_executed_preregistered_exploratory'); self.assertIn(result['primary']['decision']['decision'],{'adopt','reject','tie','inconclusive'})
 def test_runner_below_retained5_forces_inconclusive_and_diagnostic_cannot_select(self):
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); copy_receipts(root); feats=features(root,'outside'); ids=[row['origin_id'] for row in dev_rows(root)];
   for item in ids[-4:]: feats[item]['support_status']='inside'
   adapter=r.V2DevelopmentDataAdapter.from_receipts(HERE,root,HERE.parents[1]); adapter._label_loader.load=labels_for; adapter.support={key:{'status':('inside' if key in ids[-4:] else 'outside')} for key in adapter.allowed}; result=r.run_v2_development(adapter,root,'low-retained'); self.assertLess(result['retained_n'],5); self.assertEqual(result['primary']['decision']['decision'],'inconclusive'); self.assertFalse(config()['rolling']['diagnostic']['selection_allowed'])
 def test_runner_rejects_nonfinite_feature_and_records_failure(self):
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); copy_receipts(root); feats=features(root); last=dev_rows(root)[-1]['origin_id']; feats[last]['tqqq_return_21']=float('nan'); adapter=r.V2DevelopmentDataAdapter.from_receipts(HERE,root,HERE.parents[1]); adapter._label_loader.load=labels_for; mutable={key:dict(value) for key,value in adapter.features.items()}; mutable[last]['tqqq_return_21']=float('nan'); adapter.features=mutable
   with self.assertRaises(r.RollingError): r.run_v2_development(adapter,root,'bad-feature')
   ledger=json.loads((root/'rolling-attempt-ledger.v7.json').read_text()); self.assertEqual(ledger['events'][-1]['status'],'failed')
 def test_no_protected_cli_or_real_execution_receipt(self):
  source=inspect.getsource(r.main_dispatch) if False else Path(r.__file__).read_text(); self.assertNotIn('--protected',source); self.assertFalse(json.loads((ART/'rolling-preregistration.v7.json').read_text())['real_outcomes_executed'])

if __name__=='__main__': unittest.main()

class FinalInputBindingTests(unittest.TestCase):
 def test_arbitrary_maps_and_loader_removed_from_authorized_constructor(self):
  import inspect
  params=list(inspect.signature(r.V2DevelopmentDataAdapter.from_receipts).parameters)
  self.assertEqual(params,['config_root','state_root','source_root'])
 def test_feature_support_artifacts_are_outcome_free_and_bound(self):
  f=json.loads((ART/'development-features.v3.json').read_text()); s=json.loads((ART/'development-support.v3.json').read_text()); self.assertFalse(f['contains_outcomes']); self.assertFalse(s['contains_outcomes']); self.assertFalse(f['protected_outcomes_accessed']); self.assertEqual({x['origin_id'] for x in f['records']},{x['origin_id'] for x in s['records']})
 def test_feature_or_support_tamper_fails_adapter(self):
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); copy_receipts(root); value=json.loads((root/'development-support.v3.json').read_text()); value['records'][0]['status']='inside'; (root/'development-support.v3.json').write_text(json.dumps(value))
   with self.assertRaises(r.RollingError): r.V2DevelopmentDataAdapter.from_receipts(HERE,root,HERE.parents[1])
 def test_state_root_split_rejected(self):
  with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as other:
   root=Path(raw); copy_receipts(root); adapter=r.V2DevelopmentDataAdapter.from_receipts(HERE,root,HERE.parents[1])
   with self.assertRaises(r.RollingError): r.run_v2_development(adapter,Path(other),'split-root')
 def test_post_adapter_split_replacement_does_not_change_snapshot(self):
  with tempfile.TemporaryDirectory() as raw:
   root=Path(raw); copy_receipts(root); adapter=r.V2DevelopmentDataAdapter.from_receipts(HERE,root,HERE.parents[1]); before=adapter.split_rows_digest; (root/'development-split.v7.json').write_text('{}'); self.assertEqual(adapter.split_rows_digest,before); self.assertEqual(len(adapter.primary_rows),26)
 def test_source_hash_mismatch_builder_fails(self):
  from tuning.probabilistic_manifold.development_inputs import compute_development_inputs
  c=config(); bad=json.loads(json.dumps(c)); bad['input_sources']['tqqq_sha256']='0'*64; dev=json.loads((ART/'development-split.v7.json').read_text()); roster=json.loads((ART/'session-roster.v1.json').read_text())
  with self.assertRaises(r.RollingError): compute_development_inputs(bad,dev,HERE.parents[1],roster,{})
 def test_proxy_floor_fails(self):
  with self.assertRaises(r.RollingError): r.qqq_daily_3x_path_drawdown([100,60])
