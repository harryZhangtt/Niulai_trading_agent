"""Independent Decimal snapshot oracles and adversarial fail-closed regressions."""
import copy,json,unittest
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path
from analytics import build
from daily_performance import enrich_daily,verified_value
from test_analytics import fixture
ROOT=Path(__file__).parent
class SnapshotStrict(unittest.TestCase):
 @classmethod
 def setUpClass(c):
  c.h=json.loads((ROOT/'holdings_latest.json').read_text());c.a=json.loads((ROOT/'assets_latest.json').read_text());c.t=json.loads((ROOT/'taxonomy.json').read_text());c.r=build(c.h,c.a,c.t);c.raw=c.h['accountResults'][0]['positions'];c.o=c.r['accounts'][0]
 def test_saved_analytics_matches_computed_snapshot(self):
  saved=json.loads((ROOT/'analytics.json').read_text())
  for expected,actual in zip(self.r['accounts'],saved['accounts']):
   self.assertEqual(expected['accountRef'],actual['accountRef'])
   for k,v in expected['metrics'].items():
    if k in ('daily_pnl','daily_pnl_status'):continue  # Tested by session/history integration suite.
    with self.subTest(account=expected['label'],metric=k):self.assertEqual(float(v) if isinstance(v,D) else v,actual['metrics'][k])
 def test_all_contract_value_arithmetic(self):
  self.assertEqual(len(self.raw),45)
  for r in self.raw:
   with self.subTest(symbol=r['symbol']):self.assertEqual(D(r['quantity'])*D(r['marketPrice'])*D(r['multiplier']),D(r['marketValue']))
 def test_totals_denominators_and_residual(self):
  a=self.a['accountResults'][0]['summary']['amounts'];m=self.o['metrics'];v=sum(D(r['marketValue']) for r in self.raw);cash=D(a['cash']);nav=D(a['netLiquidation'])
  for k,n in {'positions_value':v,'gross_positions_value':v,'cash':cash,'nav':nav,'other_net_assets':nav-cash-v,'cash_pct':cash/nav*100,'positions_nav_pct':v/nav*100,'unrealized_pnl':sum(D(r['unrealizedPnl']) for r in self.raw)}.items():
   with self.subTest(metric=k):self.assertEqual(m[k],n)
 def test_all_weights_exposure(self):
  rows={r['symbol']:r for r in self.o['holdings']};total=sum(abs(D(r['marketValue'])) for r in self.raw);nav=self.o['metrics']['nav']
  for r in self.raw:
   with self.subTest(symbol=r['symbol']):
    v=D(r['marketValue']);o=rows[r['symbol']];self.assertEqual(o['weight_pct'],abs(v)/total*100);self.assertEqual(o['nav_weight_pct'],v/nav*100);self.assertEqual(o['proxy_exposure'],v*D(str(self.t['positions'][r['symbol']]['daily_leverage'])))
 def test_concentration(self):
  vals=sorted([abs(D(r['marketValue'])) for r in self.raw],reverse=True);total=sum(vals);q=sum((v/total)**2 for v in vals);m=self.o['metrics'];self.assertEqual(m['hhi'],q*10000);self.assertEqual(m['effective_n'],1/q)
  for n in (1,5,10):self.assertEqual(m['top'+str(n)+'_pct'],sum(v/total for v in vals[:n])*100)
 def test_all_group_arithmetic(self):
  tm=self.t['positions'];gross=sum(abs(D(r['marketValue'])) for r in self.raw)
  for output,field,multi in [('sector_breakdown','primary_sector',False),('subindustry_breakdown','subindustry',False),('themes','themes',True),('underlying_exposure','underlying',False)]:
   exp=defaultdict(lambda:D(0));counts=defaultdict(int)
   for r in self.raw:
    meta=tm[r['symbol']];v=abs(D(r['marketValue']));v*=abs(D(str(meta['daily_leverage']))) if output=='underlying_exposure' else 1
    for group in set(meta[field] if multi else [meta[field]]):exp[group]+=v;counts[group]+=1
   denominator=sum(exp.values()) if output=='underlying_exposure' else gross;actual={r['name']:r for r in self.o[output]};self.assertEqual(set(exp),set(actual))
   for name,v in exp.items():
    with self.subTest(view=output,group=name):self.assertEqual(actual[name]['value'],v);self.assertEqual(actual[name]['count'],counts[name]);self.assertAlmostEqual(actual[name]['pct'],v/denominator*100,places=20)
 def test_leverage_metrics(self):
  pairs=[(abs(D(r['marketValue'])),D(str(self.t['positions'][r['symbol']]['daily_leverage']))) for r in self.raw];gross=sum(v for v,l in pairs);proxy=sum(v*abs(l) for v,l in pairs);m=self.o['metrics'];self.assertEqual(m['known_proxy_gross_exposure'],proxy);self.assertEqual(m['embedded_gross_nav_multiple'],proxy/m['nav']);self.assertEqual(m['embedded_multiple_on_holdings'],proxy/gross);self.assertEqual(m['leveraged_capital_pct'],sum(v for v,l in pairs if abs(l)>1)/gross*100);self.assertEqual(m['leverage_coverage_pct'],100)
 def test_account_ref_join_not_order(self):
  r=build(self.h,{'accountResults':list(reversed(self.a['accountResults']))},self.t);self.assertEqual(r['accounts'][0]['metrics']['nav'],self.o['metrics']['nav']);self.assertEqual(r['accounts'][1]['account_type'],'PAPER');self.assertEqual(r['accounts'][1]['metrics']['positions_value'],0);self.assertEqual(r['accounts'][1]['metrics']['cash'],D('1000000'))
 def test_all_taxonomy_provenance(self):
  tm=self.t['positions'];self.assertTrue({r['symbol'] for r in self.raw}<=set(tm))
  for symbol,m in tm.items():
   with self.subTest(symbol=symbol):
    self.assertEqual(m['symbol'],symbol)
    for k in ('primary_sector','subindustry','instrument_type','underlying','exposure_basis','lookthrough_status','confidence'):self.assertTrue(m[k])
    self.assertEqual(len(m['themes']),len(set(m['themes'])));self.assertTrue(m['sources'])
    for ref in m['sources']:self.assertTrue(ref['url'].startswith('https://'));self.assertTrue(ref['claim']);self.assertTrue(ref['retrieved_at'])
 def test_high_risk_mapping_regression(self):
  t=self.t['positions'];self.assertEqual(t['SOXL']['underlying'],'NYSE Semiconductor Index');self.assertEqual(t['SOXL']['daily_leverage'],3);self.assertEqual(t['TQQQ']['daily_leverage'],3);self.assertEqual(t['DRAL']['underlying'],'DRAM');self.assertEqual(t['DRAL']['daily_leverage'],2);self.assertEqual(t['CRWG']['underlying'],'CRWV');self.assertEqual(t['DCFCQ']['primary_sector'],'特殊情形');self.assertNotEqual(t['METU']['confidence'],'high')
 def test_returned_scope_not_whole_portfolio(self):
  self.assertFalse(self.o['quality']['whole_portfolio_verified']);self.assertFalse(self.o['quality']['pagination_completeness_verified']);self.assertEqual(self.o['quality']['row_count'],45)
 def test_actual_daily_missing_not_zero(self):
  r=copy.deepcopy(self.r);r['latest_completed_session']='2026-10-23';enrich_daily(r,self.h,self.a)
  for a in r['accounts']:self.assertIsNone(a['metrics']['daily_pnl']);self.assertTrue(all(x['dailyPnl'] is None for x in a['holdings']));self.assertEqual(a['daily_performance']['coverage']['verified'],0)
class AdversarialStrict(unittest.TestCase):
 def test_duplicate_position_invalidates(self):
  h,a,t=fixture();h['accountResults'][0]['positions'].append(copy.deepcopy(h['accountResults'][0]['positions'][0]));r=build(h,a,t)['accounts'][0];self.assertIsNone(r['metrics']['positions_value']);self.assertIsNone(r['metrics']['hhi']);self.assertTrue(r['quality']['integrity_errors']);self.assertEqual(r['sector_breakdown'],[])
 def test_conflicting_symbol_same_contract(self):
  h,a,t=fixture()
  for r in h['accountResults'][0]['positions']:r['contractId']='same-contract'
  self.assertIsNone(build(h,a,t)['accounts'][0]['metrics']['positions_value'])
 def test_duplicate_assets_no_last_wins(self):
  h,a,t=fixture();a['accountResults'].append(copy.deepcopy(a['accountResults'][0]));self.assertIsNone(build(h,a,t)['accounts'][0]['metrics']['nav'])
 def test_duplicate_holding_account_invalidates(self):
  h,a,t=fixture();h['accountResults'].append(copy.deepcopy(h['accountResults'][0]));self.assertTrue(all(x['metrics']['positions_value'] is None for x in build(h,a,t)['accounts']))
 def test_unverified_identity(self):
  h,a,t=fixture();h['accountResults'][0]['accountIdentityChecked']=False;self.assertIsNone(build(h,a,t)['accounts'][0]['metrics']['positions_value'])
 def test_duplicate_taxonomy(self):
  h,a,t=fixture();m={'symbol':'X',**t['positions']['X']};t['positions']=[m,copy.deepcopy(m)]
  with self.assertRaisesRegex(ValueError,'duplicate_taxonomy'):build(h,a,t)
 def test_nonfinite_mv(self):
  for bad in ('NaN','Infinity','-Infinity',True,None):
   with self.subTest(bad=bad):
    h,a,t=fixture();h['accountResults'][0]['positions'][0]['marketValue']=bad;r=build(h,a,t)['accounts'][0];self.assertIsNone(r['metrics']['positions_value']);self.assertIsNone(r['metrics']['hhi'])
 def test_unknown_taxonomy(self):
  h,a,t=fixture();t['positions'].pop('X');r=build(h,a,t)['accounts'][0];x=next(x for x in r['holdings'] if x['symbol']=='X');self.assertEqual(x['sector'],'未分类');self.assertIsNone(x['daily_leverage']);self.assertIsNone(r['metrics']['embedded_gross_nav_multiple'])
 def test_unknown_currency(self):
  h,a,t=fixture();h['accountResults'][0]['positions'][0]['currency']=None;r=build(h,a,t);u=next(x for x in r['accounts'] if x['currency']=='币种未知');self.assertIsNone(u['metrics']['positions_value']);self.assertIsNone(u['metrics']['known_proxy_gross_exposure'])
 def test_daily_provenance(self):
  b={'reportedTodayPnl':'5','dailyPnlEvidence':{'session':'2026-10-23','basis':'regular_session','source_ref':'fixture:only','source_field':'reportedTodayPnl'}};self.assertEqual(verified_value(b,'2026-10-23'),5)
  for k in ('session','basis','source_ref','source_field'):
   x=copy.deepcopy(b);x['dailyPnlEvidence'].pop(k);self.assertIsNone(verified_value(x,'2026-10-23'))
  self.assertIsNone(verified_value(b,'2026-10-22'))
 def test_aggregate_not_open_position_sum(self):
  h,a,t=fixture();r=build(h,a,t);r['latest_completed_session']='2026-10-23'
  for row in r['accounts'][0]['holdings']:row.update(reportedTodayPnl='5',dailyPnlEvidence={'session':'2026-10-23','basis':'regular_session','source_ref':'fixture:only','source_field':'reportedTodayPnl'})
  enrich_daily(r,h,a);d=r['accounts'][0]['daily_performance'];self.assertEqual(d['position_contribution_total'],10);self.assertIsNone(d['aggregate_pnl']);self.assertEqual(d['status'],'partial')
if __name__=='__main__':unittest.main()
