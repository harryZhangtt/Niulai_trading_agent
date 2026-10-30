"""Independent close-mark plus fill-mark oracle, separate from cashflow implementation."""
import copy,unittest
from decimal import Decimal as D
from daily_performance import compute_close_to_close_pnl

def fixture(oq='10',cq='10',op='100',cp='105',fills=None):
 ident={'account_ref':'test-account','contract_id':'test-contract','currency':'USD'}
 def mark(q,p,s):return dict(ident,quantity=q,price=p,session=s,source_ref='test:'+s,price_basis='regular_session_close')
 return dict(ident,security_type='STK',multiplier='1',opening=mark(oq,op,'2026-10-21'),closing=mark(cq,cp,'2026-10-22'),executions=fills or [],ledger={'complete':True,'source_ref':'test:ledger','start_utc':'2026-10-21T20:00:00Z','end_utc':'2026-10-22T20:00:00Z'},corporate_actions={'status':'verified_none','source_ref':'test:actions'})
def fill(side,q,p,fee='1',identity='test:exec1',stamp='2026-10-22T15:00:00Z'):
 return dict(side=side,quantity=q,price=p,fee=fee,currency='USD',timestamp=stamp,source_ref=identity,account_ref='test-account',contract_id='test-contract')
def oracle(case):
 close=D(case['closing']['price']);gross=D(case['opening']['quantity'])*(close-D(case['opening']['price']))
 for r in case['executions']:gross+=(1 if r['side']=='BUY' else -1)*D(r['quantity'])*(close-D(r['price']))
 return gross,gross-sum(D(r['fee']) for r in case['executions'])

class ExecutionIndependentTests(unittest.TestCase):
 def check(self,c):
  r=compute_close_to_close_pnl(c);g,n=oracle(c);self.assertEqual(r['status'],'computed_gross_and_net');self.assertEqual(r['gross_pnl'],g);self.assertEqual(r['net_pnl'],n)
 def reject(self,c):self.assertEqual(compute_close_to_close_pnl(c)['status'],'blocked')
 def test_no_trade(self):self.check(fixture())
 def test_buy(self):self.check(fixture(cq='15',fills=[fill('BUY','5','102')]))
 def test_sell(self):self.check(fixture(cq='6',fills=[fill('SELL','4','103')]))
 def test_roundtrip(self):self.check(fixture(fills=[fill('BUY','5','102'),fill('SELL','5','104',identity='test:exec2')]))
 def test_short_open_and_cover(self):self.check(fixture(oq='-10',cq='-4',fills=[fill('BUY','6','102')]))
 def test_partial_fractional_fills(self):self.check(fixture(cq='10.75',fills=[fill('BUY','.25','102.4',fee='.01'),fill('BUY','.5','103.6',fee='.02',identity='test:exec2')]))
 def test_premarket_included_close_to_close(self):self.check(fixture(cq='12',fills=[fill('BUY','2','102',stamp='2026-10-22T12:00:00Z')]))
 def test_previous_afterhours_included(self):self.check(fixture(cq='12',fills=[fill('BUY','2','102',stamp='2026-10-21T22:00:00Z')]))
 def test_missing_fees_gross_only(self):
  c=fixture(cq='15',fills=[fill('BUY','5','102',fee=None)]);r=compute_close_to_close_pnl(c);self.assertEqual(r['status'],'computed_gross_only');self.assertEqual(r['gross_pnl'],D('65'));self.assertIsNone(r['net_pnl'])
 def test_quantity_reconciliation(self):self.reject(fixture(cq='999'))
 def test_duplicate_execution(self):
  f=fill('BUY','1','100');self.reject(fixture(cq='12',fills=[f,copy.deepcopy(f)]))
 def test_split_unverified(self):
  c=fixture();c['corporate_actions']['status']='split';self.reject(c)
 def test_missing_corporate_action_evidence(self):
  c=fixture();c['corporate_actions']['source_ref']=None;self.reject(c)
 def test_wrong_currency(self):
  c=fixture();c['closing']['currency']='HKD';self.reject(c)
 def test_incomplete_ledger(self):
  c=fixture();c['ledger']['complete']=False;self.reject(c)
 def test_fill_after_close_rejected(self):self.reject(fixture(cq='11',fills=[fill('BUY','1','100',stamp='2026-10-22T20:00:01Z')]))
 def test_naive_time_rejected(self):self.reject(fixture(cq='11',fills=[fill('BUY','1','100',stamp='2026-10-22T15:00:00')]))
 def test_nonfinite(self):self.reject(fixture(cp='NaN'))
 def test_unsupported_option(self):
  c=fixture();c['security_type']='OPT';self.reject(c)
 def test_wrong_account(self):
  c=fixture();c['closing']['account_ref']='other';self.reject(c)
 def test_wrong_contract(self):
  c=fixture(cq='11',fills=[fill('BUY','1','100')]);c['executions'][0]['contract_id']='other';self.reject(c)
 def test_not_session_close(self):
  c=fixture();c['ledger']['end_utc']='2026-10-22T16:00:00Z';self.reject(c)
 def test_nonconsecutive_sessions(self):
  c=fixture();c['opening']['session']='2026-10-20';c['ledger']['start_utc']='2026-10-20T20:00:00Z';self.reject(c)
 def test_unverified_close_basis(self):
  c=fixture();c['closing']['price_basis']='last_trade';self.reject(c)
 def test_non_unit_contract_multiplier_rejected(self):
  c=fixture();c['multiplier']='100';self.reject(c)
 def test_early_close_holiday_adjacent_sessions(self):
  c=fixture();c['opening']['session']='2026-11-25';c['closing']['session']='2026-11-27';c['ledger'].update(start_utc='2026-11-25T21:00:00Z',end_utc='2026-11-27T18:00:00Z');self.check(c)
 def test_dst_weekend_adjacent_closes(self):
  c=fixture();c['opening']['session']='2026-03-06';c['closing']['session']='2026-03-09';c['ledger'].update(start_utc='2026-03-06T21:00:00Z',end_utc='2026-03-09T20:00:00Z');self.check(c)
 def test_string_true_is_not_verified_complete(self):
  c=fixture();c['ledger']['complete']='true';self.reject(c)
 def test_negative_fee_not_hidden_rebate(self):self.reject(fixture(cq='11',fills=[fill('BUY','1','100',fee='-1')]))

if __name__=='__main__':unittest.main()
