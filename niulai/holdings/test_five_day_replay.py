import unittest,json
from pathlib import Path
from decimal import Decimal as D
from collections import defaultdict
from datetime import datetime
P=Path(__file__).parent/'five_day_daily'
class FiveDayTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.summary=json.loads((P/'summary.json').read_text());cls.cases=json.loads((P/'inputs.json').read_text());cls.sources=json.loads((P/'sources.json').read_text())
 def test_exact_five_sessions(self):self.assertEqual([s['session'] for s in self.summary['sessions']],['2026-10-19','2026-10-20','2026-10-21','2026-10-22','2026-10-23'])
 def test_all_14_executions_counted_once(self):
  self.assertEqual(sum(s['execution_count'] for s in self.summary['sessions']),14)
  ids=[f['source_ref'] for c in self.cases for f in c['executions']];self.assertEqual(len(ids),14);self.assertEqual(len(set(ids)),14)
 def test_independent_per_case_price_attribution(self):
  for c in self.cases:
   with self.subTest(contract=c['contract_id'],date=c['closing']['session']):
    oq,op,cq,cp=[D(r[k]) for r,k in [(c['opening'],'quantity'),(c['opening'],'price'),(c['closing'],'quantity'),(c['closing'],'price')]]
    fills=c['executions'];direct=cq*cp-oq*op+sum(((1 if f['side']=='SELL' else -1)*D(f['quantity'])*D(f['price']) for f in fills),D(0))
    oracle=oq*(cp-op)+sum(((1 if f['side']=='BUY' else -1)*D(f['quantity'])*(cp-D(f['price'])) for f in fills),D(0))
    self.assertEqual(direct,oracle)
 def test_week_telescope_common_contracts(self):
  groups=defaultdict(list)
  for c in self.cases:groups[c['contract_id']].append(c)
  for contract,cases in groups.items():
   if len(cases)!=5:continue
   cases.sort(key=lambda c:c['closing']['session']);day_total=D(0)
   for c in cases:
    day_total+=D(c['opening']['quantity'])*(D(c['closing']['price'])-D(c['opening']['price']))+sum(((1 if f['side']=='BUY' else -1)*D(f['quantity'])*(D(c['closing']['price'])-D(f['price'])) for f in c['executions']),D(0))
   first,last=cases[0],cases[-1];week=D(last['closing']['quantity'])*D(last['closing']['price'])-D(first['opening']['quantity'])*D(first['opening']['price'])+sum(((1 if f['side']=='SELL' else -1)*D(f['quantity'])*D(f['price']) for c in cases for f in c['executions']),D(0));self.assertEqual(day_total,week)
 def test_order_percent_and_totals(self):
  for s in self.summary['sessions']:
   r=json.loads((P/s['session']/'result.json').read_text())['rows'];known=[x for x in r if x['pnl'] is not None];v=[D(x['pnl']) for x in known];self.assertEqual(v,sorted(v,reverse=True));self.assertEqual(sum(v),D(s['gross_pnl']))
   den=sum(D(x['return_denominator']) for x in known);self.assertEqual(sum(v)/den*100,D(s['capital_return_pct']))
 def test_friday_regression(self):self.assertEqual(D(self.summary['sessions'][-1]['gross_pnl']),D('300.4181'))
 def test_no_false_broker_match(self):
  self.assertTrue(all(s['broker_stock_pnl_crosscheck']=='UNAVAILABLE' for s in self.summary['sessions']));self.assertIsNone(self.summary['sessions'][-1]['account_analysis_pnl'])
 def test_no_current_risk_leakage_to_friday(self):
  x=json.loads((P/'2026-10-23'/'viewport.json').read_text());self.assertIsNone(x['accounts'][0]['metrics']['nav']);self.assertIsNone(x['accounts'][0]['metrics']['cash_pct'])
if __name__=='__main__':unittest.main()
