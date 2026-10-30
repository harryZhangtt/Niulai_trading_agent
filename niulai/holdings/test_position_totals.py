import unittest,json,copy
from pathlib import Path
from decimal import Decimal as D
from position_totals import attach_totals
P=Path(__file__).parent/'five_day_daily'
class PositionTotalsTests(unittest.TestCase):
 def setUp(self):
  self.s=json.loads((P/'sources.json').read_text());self.v=json.loads((P/'2026-10-23'/'viewport.json').read_text());self.r=json.loads((P/'2026-10-23'/'result.json').read_text())['rows']
 def test_full_snapshot_not_close_subtotal(self):
  t=attach_totals(self.v,self.s,self.r)['accounts'][0]['position_totals']
  self.assertEqual(D(t['snapshot_net']),D('79291.082601'));self.assertEqual(t['snapshot_count'],45)
  self.assertEqual(D(t['close_known_net']),D('79491.9081'));self.assertEqual(t['close_known_count'],44)
  self.assertFalse(t['snapshot_price_timestamp_verified'])
 def test_unknown_not_zero(self):
  self.s['evidence']['holdings']['result']['positions'][0]['marketValue']=None
  self.assertIsNone(attach_totals(self.v,self.s,self.r)['accounts'][0]['position_totals']['snapshot_net'])
 def test_reject_currency_mix(self):
  self.s['evidence']['holdings']['result']['positions'][0]['currency']='HKD'
  with self.assertRaises(AssertionError):attach_totals(self.v,self.s,self.r)
 def test_reject_duplicate(self):
  h=self.s['evidence']['holdings']['result'];h['positions'].append(h['positions'][0])
  with self.assertRaises(AssertionError):attach_totals(self.v,self.s,self.r)
 def test_reject_wrong_account(self):
  self.s['account_ref']='untrusted';self.s['evidence']['holdings']['result']['accountRef']='wrong'
  with self.assertRaises(AssertionError):attach_totals(self.v,self.s,self.r)
 def test_negative_position_net_vs_gross(self):
  p=self.s['evidence']['holdings']['result']['positions'][0];old=D(p['marketValue']);p['marketValue']=str(-old)
  t=attach_totals(self.v,self.s,self.r)['accounts'][0]['position_totals']
  self.assertEqual(D(t['snapshot_gross'])-D(t['snapshot_net']),2*old)
 def test_nav_cash_and_residual(self):
  a={'ok':True,'sourceReadStatus':'complete','accountIdentityChecked':True,'accountRef':self.v['accounts'][0]['accountRef'],'queryCompletedAt':'2026-10-25T21:33:40Z','summary':{'currency':'USD','amounts':{'netLiquidation':'127119.82','cash':'47828.22','buyingPower':'309507.73'}}}
  self.s['evidence']['current_assets']={'ok':True,'result':a}
  t=attach_totals(self.v,self.s,self.r)['accounts'][0]['position_totals']
  self.assertEqual(D(t['snapshot_nav']),D('127119.82'));self.assertEqual(D(t['snapshot_cash']),D('47828.22'))
  self.assertEqual(D(t['snapshot_nav'])-D(t['snapshot_cash'])-D(t['snapshot_net']),D(t['snapshot_residual']))
  self.assertEqual(D(t['snapshot_residual']),D('.517399'))
