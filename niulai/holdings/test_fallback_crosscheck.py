import unittest,json
from pathlib import Path
from decimal import Decimal as D
from reconcile_daily_fallback import cross_check
class CrosscheckTests(unittest.TestCase):
 def pair(self):return dict(account_ref='A',contract_id='C',currency='USD',session='2026-10-23',basis='gross_close_to_close',value='1.00')
 def test_missing_is_not_zero(self):self.assertEqual(cross_check(None,self.pair())['status'],'unavailable')
 def test_missing_metadata_rejected(self):self.assertEqual(cross_check({'value':1},{'value':1})['status'],'not_comparable')
 def test_exact(self):self.assertEqual(cross_check(self.pair(),self.pair())['status'],'match')
 def test_rounding(self):
  p=self.pair();p['value']='1.01';self.assertEqual(cross_check(p,self.pair())['status'],'match')
 def test_mismatch(self):
  p=self.pair();p['value']='1.02';self.assertEqual(cross_check(p,self.pair())['status'],'mismatch')
 def test_nonfinite(self):
  p=self.pair();p['value']='NaN';self.assertEqual(cross_check(p,self.pair())['status'],'invalid')
 def test_dimension_mismatches(self):
  for key in ('account_ref','contract_id','currency','session','basis'):
   with self.subTest(key=key):
    p=self.pair();p[key]='other';self.assertEqual(cross_check(p,self.pair())['status'],'not_comparable')
 def test_actual_subtotal_and_scope(self):
  r=json.loads(Path(__file__).with_name('daily_fallback_result.json').read_text());rows=r['rows'];self.assertEqual(len(rows),45);self.assertEqual(sum(x['gross_pnl'] is not None for x in rows),44)
  self.assertEqual(sum((D(x['gross_pnl']) for x in rows if x['gross_pnl'] is not None),D(0)),D(r['computed_subtotal']))
  self.assertEqual([x['symbol'] for x in rows if x['gross_pnl'] is None],['DCFCQ'])
 def test_actual_trade_cases_manual(self):
  rows={r['symbol']:r for r in json.loads(Path(__file__).with_name('daily_fallback_result.json').read_text())['rows']}
  self.assertEqual(D(rows['CRWV']['gross_pnl']),D(18)*(D('54.235')-D('55.3')))
  self.assertEqual(D(rows['CRWG']['gross_pnl']),D(150)*(D('6.41')-D('6.68')))
 def test_no_false_broker_reconciliation(self):
  r=json.loads(Path(__file__).with_name('daily_fallback_result.json').read_text());self.assertEqual(r['broker_crosscheck'],'UNAVAILABLE');self.assertTrue(all(x['net_pnl'] is None for x in r['rows'] if 'net_pnl' in x))
if __name__=='__main__':unittest.main()
