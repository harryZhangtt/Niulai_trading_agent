"""Independent raw-evidence oracle for cumulative broker P&L recovery."""
import copy,json,unittest
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).parent

def rows_by_ny_date(v):
 return {datetime.fromtimestamp(int(r['date'])/1000,timezone.utc).astimezone(ZoneInfo('America/New_York')).date().isoformat():r for r in v['history']}

class EvidenceRecoveryTests(unittest.TestCase):
 @classmethod
 def setUpClass(c):c.raw=json.loads((ROOT/'history_variants_evidence.json').read_text());c.v={x['variant']:x for x in c.raw}
 def test_exact_timestamp_to_trading_date(self):
  self.assertIn('2026-10-21',rows_by_ny_date(self.v['explicit_extended']));self.assertIn('2026-10-22',rows_by_ny_date(self.v['explicit_extended']))
 def test_rebased_values_differ_daily_difference_same(self):
  a=rows_by_ny_date(self.v['explicit_extended']);b=rows_by_ny_date(self.v['defaults']);self.assertNotEqual(a['2026-10-22']['pnl'],b['2026-10-22']['pnl'])
  for v in (a,b):self.assertEqual(D(v['2026-10-22']['pnl'])-D(v['2026-10-21']['pnl']),D('-6217.72'))
 def test_nav_matches_daily_pnl_all_three_variants(self):
  for name in ('explicit_extended','defaults','all_segments'):
   with self.subTest(variant=name):
    r=rows_by_ny_date(self.v[name]);p,c=r['2026-10-21'],r['2026-10-22'];self.assertEqual(D(c['asset'])-D(p['asset']),D(c['pnl'])-D(p['pnl']));self.assertEqual(D(c['deposit']),0);self.assertEqual(D(c['withdrawal']),0)
 def test_explicit_all_and_security_segment_agree(self):
  a,b=self.v['explicit_extended'],self.v['all_segments'];self.assertEqual(a['accountRef'],b['accountRef']);self.assertEqual(a['parameters']['currency'],'USD');self.assertEqual(b['parameters']['currency'],'USD');self.assertEqual(a['history'],b['history'])
 def test_one_day_zero_is_rebase(self):
  r=self.v['daily_window'];self.assertEqual(len(r['history']),1);self.assertEqual(r['history'][0]['pnl'],'0');self.assertEqual(r['history'][0]['asset'],'127026.73');self.assertNotEqual(D(r['history'][0]['pnl']),D('-6217.72'))
 def test_prior_nav_denominator(self):
  r=rows_by_ny_date(self.v['all_segments']);prior=D(r['2026-10-21']['asset']);result=(D(r['2026-10-22']['asset'])-prior)/prior*100;self.assertEqual(result,D('-6217.72')/D('133244.45')*100);self.assertNotEqual(result,D(r['2026-10-22']['pnlPercentage']))

class HistoryGuardTests(unittest.TestCase):
 def fixture(self):return copy.deepcopy(json.loads((ROOT/'analytics_latest.json').read_text())['accountResults'][0])
 def calculate(self,x):
  from daily_performance import history_daily_points
  return history_daily_points(x,['2026-10-23','2026-10-22','2026-10-21','2026-10-20','2026-10-19'])
 def test_valid_thursday_recovery(self):
  r=self.calculate(self.fixture())['2026-10-22'];self.assertEqual(r['pnl'],D('-6217.72'));self.assertEqual(r['prior_date'],'2026-10-21')
 def test_missing_exact_previous_session_rejected(self):
  x=self.fixture();x['history']=[r for r in x['history'] if r['dateEpochMs']!='1792555200000'];self.assertNotIn('2026-10-22',self.calculate(x))
 def test_missing_flow_rejected(self):
  x=self.fixture();x['history'][-1]['deposit']=None;self.assertNotIn('2026-10-22',self.calculate(x))
 def test_nonzero_flow_not_assumed(self):
  x=self.fixture();x['history'][-1]['deposit']='100';self.assertNotIn('2026-10-22',self.calculate(x))
 def test_duplicate_date_rejected(self):
  x=self.fixture();x['history'].append(copy.deepcopy(x['history'][-1]));self.assertNotIn('2026-10-22',self.calculate(x))
 def test_pnl_nav_mismatch_rejected(self):
  x=self.fixture();x['history'][-1]['pnl']='-2200';self.assertNotIn('2026-10-22',self.calculate(x))
 def test_nonfinite_rejected(self):
  x=self.fixture();x['history'][-1]['asset']='NaN';self.assertNotIn('2026-10-22',self.calculate(x))
 def test_failed_source_rejected(self):
  x=self.fixture();x['ok']=False;self.assertNotIn('2026-10-22',self.calculate(x))
 def test_partial_source_rejected(self):
  x=self.fixture();x['sourceReadStatus']='partial';self.assertNotIn('2026-10-22',self.calculate(x))
 def test_absent_identity_rejected(self):
  x=self.fixture();x['accountRef']=None;self.assertNotIn('2026-10-22',self.calculate(x))

class HistoryIntegrationTests(unittest.TestCase):
 def fixture(self):
  from analytics import build
  h=json.loads((ROOT/'holdings_latest.json').read_text());a=json.loads((ROOT/'assets_latest.json').read_text());t=json.loads((ROOT/'taxonomy.json').read_text());history=json.loads((ROOT/'analytics_latest.json').read_text());r=build(h,a,t);r['latest_completed_session']='2026-10-23';return r,h,a,history
 def run_case(self,r,h,a,history):
  from daily_performance import enrich_daily
  return enrich_daily(r,h,a,history,now=datetime.fromisoformat('2026-10-25T19:00:00+00:00'))['accounts'][0]['daily_performance']
 def test_latest_available_thursday_not_friday_relabel(self):
  r,h,a,hist=self.fixture();d=self.run_case(r,h,a,hist);self.assertEqual(d['session'],'2026-10-22');self.assertEqual(d['preferred_session'],'2026-10-23');self.assertEqual(d['aggregate_pnl'],D('-6217.72'));self.assertEqual(d['coverage']['verified'],0)
 def test_preferred_dated_aggregate_has_priority(self):
  r,h,a,hist=self.fixture();a['accountResults'][0]['summary']['amounts'].update(reportedTodayPnl='12',dailyPnlEvidence={'session':'2026-10-23','basis':'regular_session','source_ref':'test:official','source_field':'reportedTodayPnl'});d=self.run_case(r,h,a,hist);self.assertEqual(d['session'],'2026-10-23');self.assertEqual(d['aggregate_pnl'],12)
 def test_frozen_preferred_no_future_upgrade(self):
  r,h,a,hist=self.fixture();r['latest_completed_session']='2026-10-22';x=copy.deepcopy(hist['accountResults'][0]['history'][-1]);x.update(dateEpochMs='1792728000000',asset='128026.73',pnl='-1207.88');hist['accountResults'][0]['history'].append(x);d=self.run_case(r,h,a,hist);self.assertEqual(d['session'],'2026-10-22');self.assertEqual(d['aggregate_pnl'],D('-6217.72'))
 def test_mixed_currency_history_rejected(self):
  r,h,a,hist=self.fixture();hist['accountResults'][0]['currency']='HKD';self.assertIsNone(self.run_case(r,h,a,hist)['aggregate_pnl'])
 def test_duplicate_history_account_rejected(self):
  r,h,a,hist=self.fixture();hist['accountResults'].append(copy.deepcopy(hist['accountResults'][0]));self.assertIsNone(self.run_case(r,h,a,hist)['aggregate_pnl'])

if __name__=='__main__':unittest.main()
