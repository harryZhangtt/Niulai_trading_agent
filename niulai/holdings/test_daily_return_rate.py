import unittest,json
from decimal import Decimal as D
from pathlib import Path
from daily_return_rate import daily_return_rate
from render_portfolio import daily_view
class RatesTests(unittest.TestCase):
 def case(self,q='10',p='100',fills=None):return {'opening':{'quantity':q,'price':p},'executions':fills or []}
 def fill(self,side,q,p):return {'side':side,'quantity':q,'price':p,'timestamp':'2026-10-23T12:00:00Z'}
 def test_no_trade(self):self.assertEqual(D(daily_return_rate(self.case(),'50')['percent']),D('5'))
 def test_new_buy(self):self.assertEqual(D(daily_return_rate(self.case('0',fills=[self.fill('BUY','2','100')]),'10')['percent']),D('5'))
 def test_add(self):self.assertEqual(D(daily_return_rate(self.case(fills=[self.fill('BUY','10','100')]),'100')['denominator']),D('2000'))
 def test_sell_does_not_shrink_denominator(self):self.assertEqual(D(daily_return_rate(self.case(fills=[self.fill('SELL','5','110')]),'100')['denominator']),D('1000'))
 def test_zero_is_unknown(self):self.assertIsNone(daily_return_rate(self.case('0'),'0'))
 def test_short_is_unsupported(self):self.assertIsNone(daily_return_rate(self.case('-1'),'1'))
 def test_crossing_short_is_unsupported(self):self.assertIsNone(daily_return_rate(self.case(fills=[self.fill('SELL','11','100')]),'10'))
 def test_nan_is_unknown(self):self.assertIsNone(daily_return_rate(self.case(),'NaN'))
 def test_real_crwv(self):
  r=daily_return_rate(self.case('0',fills=[self.fill('BUY','18','55.3')]),'-19.17');self.assertEqual(D(r['percent']),D('-19.17')/D('995.4')*100)
 def test_snapshot_sorted_and_weighted(self):
  x=json.loads(Path(__file__).with_name('daily_viewport.json').read_text());a=next(a for a in x['accounts'] if a['account_type']=='STANDARD');v=daily_view(x,a);rows=v['rows'];values=[D(z['value']) for z in rows if z['value'] is not None];self.assertEqual(values,sorted(values,reverse=True));self.assertEqual(rows[-1]['name'],'DCFCQ');self.assertIsNone(rows[-1]['pnl_pct'])
  d=a['daily_performance'];den=sum(D(z['return_denominator']) for z in d['positions'] if z['return_denominator'] is not None);self.assertEqual(D(d['capital_return_pct']),D('300.4181')/den*100)
if __name__=='__main__':unittest.main()
