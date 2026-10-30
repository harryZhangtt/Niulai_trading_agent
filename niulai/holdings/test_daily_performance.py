import copy, unittest
from decimal import Decimal
from analytics import build
from daily_performance import enrich_daily, verified_value

SESSION='2026-10-23'
def evidence(session=SESSION):
 return {'session':session,'basis':'regular_session','source_ref':'frozen-broker-statement:test','source_field':'reportedTodayPnl'}
def fixture():
 rows=[{'symbol':'AAA','contractId':'1','currency':'USD','securityType':'STK','quantity':'10','marketValue':'120','unrealizedPnl':'99','reportedTodayPnl':'5','dailyPnlEvidence':evidence()}, {'symbol':'BBB','contractId':'2','currency':'USD','securityType':'STK','quantity':'2','marketValue':'40','reportedTodayPnl':'-2','dailyPnlEvidence':evidence()}]
 h={'accountResults':[{'accountRef':'a','accountIdentityChecked':True,'ok':True,'sourceReadStatus':'complete','positions':rows}]}
 a={'accountResults':[{'accountRef':'a','accountIdentityChecked':True,'ok':True,'sourceReadStatus':'complete','summary':{'currency':'USD','amounts':{'netLiquidation':'200','cash':'40','reportedTodayPnl':'2.50','dailyPnlEvidence':evidence()}}}]}
 return h,a

def run(h,a):
 d=build(h,a,{'securities':{'AAA':{'primary_sector':'Tech'},'BBB':{'primary_sector':'Tech'}}});d['latest_completed_session']=SESSION
 return enrich_daily(d,h,a)['accounts'][0]

class DailyTests(unittest.TestCase):
 def test_exact_dated_rows_and_account(self):
  d=run(*fixture());self.assertEqual(d['daily_performance']['aggregate_pnl'],Decimal('2.50'));self.assertEqual(d['daily_performance']['position_contribution_total'],Decimal('3'));self.assertEqual(d['daily_performance']['sectors'][0]['pnl'],3)
 def test_no_inferred_account_from_holdings_sum(self):
  h,a=fixture();a['accountResults'][0]['summary']['amounts'].pop('reportedTodayPnl');d=run(h,a);self.assertIsNone(d['metrics']['daily_pnl']);self.assertEqual(d['daily_performance']['position_contribution_total'],3)
 def test_undated_counter_rejected(self):
  h,a=fixture();h['accountResults'][0]['positions'][0].pop('dailyPnlEvidence');d=run(h,a);self.assertEqual(d['daily_performance']['coverage']['verified'],1);self.assertIsNone(d['daily_performance']['sectors'][0]['pnl'])
 def test_wrong_session_rejected(self):
  self.assertIsNone(verified_value({'reportedTodayPnl':5,'dailyPnlEvidence':evidence('2026-10-22')},SESSION))
 def test_nonfinite_rejected(self):
  for v in ('NaN','Infinity',True,None):self.assertIsNone(verified_value({'reportedTodayPnl':v,'dailyPnlEvidence':evidence()},SESSION))
 def test_partial_asset_rejected(self):
  h,a=fixture();a['accountResults'][0]['sourceReadStatus']='partial';self.assertIsNone(run(h,a)['metrics']['daily_pnl'])
 def test_verified_zero_is_valid(self):
  self.assertEqual(verified_value({'reportedTodayPnl':'0','dailyPnlEvidence':evidence()},SESSION),0)
 def test_duplicate_holding_rejected(self):
  h,a=fixture();h['accountResults'][0]['positions'].append(copy.deepcopy(h['accountResults'][0]['positions'][0]));d=run(h,a);self.assertIsNone(next(r for r in d['daily_performance']['positions'] if r['symbol']=='AAA')['pnl'])
 def test_alias_duplicate_contract_rejected(self):
  h,a=fixture();r=copy.deepcopy(h['accountResults'][0]['positions'][0]);r['symbol']='ALIAS';h['accountResults'][0]['positions'].append(r);d=run(h,a);self.assertIsNone(next(v for v in d['daily_performance']['positions'] if v['symbol']=='AAA')['pnl'])
 def test_duplicate_asset_ref_rejected(self):
  h,a=fixture();a['accountResults'].append(copy.deepcopy(a['accountResults'][0]));self.assertIsNone(run(h,a)['metrics']['daily_pnl'])
 def test_account_mismatch_rejected(self):
  h,a=fixture();a['accountResults'][0]['accountRef']='other';self.assertIsNone(run(h,a)['metrics']['daily_pnl'])
 def test_currency_mismatch_rejected(self):
  h,a=fixture();a['accountResults'][0]['summary']['currency']='HKD';self.assertIsNone(run(h,a)['metrics']['daily_pnl'])
 def test_incomplete_source_rejected(self):
  h,a=fixture();h['accountResults'][0]['sourceReadStatus']='partial';self.assertEqual(run(h,a)['daily_performance']['coverage']['verified'],0)
 def test_identity_unverified_rejected(self):
  h,a=fixture();h['accountResults'][0]['accountIdentityChecked']=False;self.assertEqual(run(h,a)['daily_performance']['coverage']['verified'],0)
 def test_weekend_same_close_and_afterhours_trap(self):
  for latest,last in [('83.56','83.56'),('83.23','83.56')]:
   h,a=fixture();r=h['accountResults'][0]['positions'][0];r.pop('dailyPnlEvidence');r.pop('reportedTodayPnl');r.update(marketPrice=latest,reportedLastClosePrice=last,unrealizedPnl='999',dailyPnl='456')
   d=run(h,a);self.assertIsNone(next(x for x in d['holdings'] if x['symbol']=='AAA')['dailyPnl'])
 def test_no_source_binding_rejected(self):
  e=evidence();e.pop('source_ref');self.assertIsNone(verified_value({'reportedTodayPnl':2,'dailyPnlEvidence':e},SESSION))
 def test_different_contracts_same_ticker_sum(self):
  h,a=fixture();r=copy.deepcopy(h['accountResults'][0]['positions'][0]);r['contractId']='3';h['accountResults'][0]['positions'].append(r)
  self.assertEqual(next(p for p in run(h,a)['daily_performance']['positions'] if p['symbol']=='AAA')['pnl'],10)
if __name__=='__main__':unittest.main()
