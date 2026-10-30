import io,json,os,subprocess,sys,tempfile,unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import daily_compact_pipeline as d
import niulai_tiger as n

class ReadinessTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
 def token(self,scopes=n.QUOTE_SCOPES,remaining=60000,refresh=True):
  return NS(issuer=n.ISSUER,scope=' '.join(scopes),remaining_millis=lambda:remaining,has_refresh_token=lambda:refresh)
 def probe(self,token):
  with patch.object(n,'sdk_classes',return_value=(lambda **kw:NS(status=lambda:token),None)):
   return d.preflight(self.root)
 def test_missing_explicit_profile_never_created_or_silently_replaced(self):
  missing=self.root/'missing'
  with patch.dict(os.environ,{'NIULAI_PROFILE_DIR':str(self.root)}):
   with self.assertRaisesRegex(ValueError,'profile_missing'):d.existing_profile(str(missing))
  self.assertFalse(missing.exists())
 def test_environment_profile_used(self):
  with patch.dict(os.environ,{'NIULAI_PROFILE_DIR':str(self.root)}):self.assertEqual(d.existing_profile(),self.root)
 def test_symlink_rejected(self):
  path=self.root/'link';path.symlink_to(self.root)
  with self.assertRaisesRegex(ValueError,'profile_symlink_rejected'):d.existing_profile(str(path))
 def test_existing_directory_is_not_authorization(self):
  with self.assertRaisesRegex(n.ReadOnlyError,'LOGIN_REQUIRED'):self.probe(None)
 def test_valid_read_token_does_not_claim_persistent_mount(self):
  result=self.probe(self.token());self.assertTrue(result['ok']);self.assertFalse(result['cross_run_persistence_verified']);self.assertEqual(result['network_calls'],0)
 def test_quote_missing_does_not_hide_basic_holdings_grant(self):
  result=self.probe(self.token(n.SCOPES));self.assertTrue(result['ok']);self.assertFalse(result['quote_consent'])
 def test_expired_without_refresh_requires_consent(self):
  with self.assertRaisesRegex(n.ReadOnlyError,'REAUTHORIZATION_REQUIRED'):self.probe(self.token(remaining=-1,refresh=False))
 def test_expired_refreshable_is_not_mislabeled_logged_out(self):self.assertTrue(self.probe(self.token(remaining=-1))['ok'])
 def test_write_scope_rejected(self):
  with self.assertRaisesRegex(n.ReadOnlyError,'TOKEN_SCOPE_REJECTED'):self.probe(self.token(n.QUOTE_SCOPES|{'api.trade:write'}))
 def test_native_dependency_crash_produces_durable_specific_failure(self):
  out=self.root/'out';argv=['daily','--out',str(out),'--profile',str(self.root),'--local-bootstrap']
  with patch.object(sys,'argv',argv),patch.object(d.subprocess,'run',return_value=NS(returncode=-7,stdout='',stderr='not for logs')),redirect_stdout(io.StringIO()):self.assertEqual(d.main(),2)
  result=json.loads((out/'status.json').read_text());self.assertEqual(result['blocker'],'dependency_process_crash');self.assertFalse((out/'daily.json').exists())
 def test_child_error_preserved_without_raw_stderr(self):
  out=self.root/'out';argv=['daily','--out',str(out),'--profile',str(self.root),'--local-bootstrap']
  with patch.object(sys,'argv',argv),patch.object(d.subprocess,'run',return_value=NS(returncode=2,stdout='{"ok":false,"error":"LOGIN_REQUIRED"}',stderr='sensitive-test-value')),redirect_stdout(io.StringIO()):self.assertEqual(d.main(),2)
  self.assertEqual(json.loads((out/'status.json').read_text())['blocker'],'LOGIN_REQUIRED');self.assertNotIn('sensitive-test-value',(out/'status.json').read_text())
 def test_fresh_subprocess_missing_profile_regression(self):
  out=self.root/'run';missing=self.root/'not-created'
  cp=subprocess.run([sys.executable,str(Path(d.__file__)),'--profile',str(missing),'--out',str(out),'--local-bootstrap'],capture_output=True,text=True,timeout=15)
  self.assertEqual(cp.returncode,2);self.assertEqual(json.loads((out/'status.json').read_text())['blocker'],'profile_missing');self.assertFalse(missing.exists())
 def test_production_requires_private_store_not_local_fallback(self):
  out=self.root/'required';argv=['daily','--out',str(out),'--profile',str(self.root)]
  with patch.object(sys,'argv',argv),patch.dict(os.environ,{},clear=True),redirect_stdout(io.StringIO()):self.assertEqual(d.main(),2)
  self.assertEqual(json.loads((out/'status.json').read_text())['blocker'],'PRIVATE_STORE_REQUIRED')
 def test_first_login_account_mapping_initialized_and_stable(self):
  accounts=[NS(account='synthetic-account')];first=n.account_refs(self.root,accounts);self.assertEqual(first,n.account_refs(self.root,accounts));self.assertTrue(n.valid_ref(first['synthetic-account']))
 def test_duplicate_observed_account_rejected(self):
  with self.assertRaisesRegex(n.ReadOnlyError,'ACCOUNT_LIST_INVALID'):n.account_refs(self.root,[NS(account='same'),NS(account='same')])
 def test_missing_historical_ledger_preserves_verified_holdings_and_cash(self):
  import analytics,build_five_day,render_daily_pdf
  from decimal import Decimal
  h={'ok':True,'sourceReadStatus':'complete','accountIdentityChecked':True,'accountRef':'fixture-ref','queryCompletedAt':'2026-10-27T02:00:00Z','positions':[{'symbol':'TEST','contractId':'1','securityType':'STK','currency':'USD','quantity':'2','marketValue':'100'}]}
  assets={'ok':True,'sourceReadStatus':'complete','accountIdentityChecked':True,'accountRef':'fixture-ref','queryCompletedAt':'2026-10-27T02:00:01Z','summary':{'currency':'USD','amounts':{'netLiquidation':'125','cash':'25'}}}
  source={'query_at':'2026-10-27T02:00:00Z','sessions':[{'date':'2026-10-26'}],'evidence':{'holdings':{'result':h},'current_assets':{'result':assets}}}
  (self.root/'sources.json').write_text(json.dumps(source))
  with patch.object(build_five_day,'main',side_effect=KeyError('transactions')),patch.object(render_daily_pdf,'make'):
   result=d.build_report(self.root)
  v=json.loads((self.root/'daily.json').read_text());a=v['accounts'][0]
  self.assertEqual(result['status'],'rendered_partial');self.assertEqual(Decimal(a['position_totals']['snapshot_net']),Decimal(100));self.assertEqual(Decimal(a['position_totals']['snapshot_nav']),Decimal(125));self.assertEqual(Decimal(a['position_totals']['snapshot_cash']),Decimal(25));self.assertIsNone(a['daily_performance']['aggregate_pnl']);self.assertEqual(len(a['daily_performance']['positions']),1)

if __name__=='__main__':unittest.main()
