import itertools,unittest
from decimal import Decimal as D
from options_decision_bounds import calculate,expectation_bounds,VERSION
from test_options_payoff_checks import example_packet

def fixture():
 p=example_packet();p['mode']='historical'
 return {'version':VERSION,'payoff_packet':p,'valuation_horizon':p['strategy']['long_leg']['expiry'],'contracts':1,'scenarios':[{'id':'down','expiry_stock_price':'40','probability_lower':'0','probability_upper':'1'},{'id':'up','expiry_stock_price':'100','probability_lower':'0','probability_upper':'1'}],'horizon_return_hurdle':'0.1','closing_fee_reserve':'2','model_error_reserve':'10','assumption_source_refs':['explicit_test_assumptions']}
class BoundsTests(unittest.TestCase):
 def test_known_interval(self):
  a=expectation_bounds(list(map(D,['0','100','300'])),list(map(D,['0.1','0.2','0.1'])),list(map(D,['0.5','0.6','0.5'])))
  self.assertEqual(a[0],D(70));self.assertEqual(a[1],D(190))
 def test_full_ignorance(self):
  self.assertEqual(expectation_bounds([D(0),D(300)],[D(0),D(0)],[D(1),D(1)])[:2],(D(0),D(300)))
 def test_exact_probabilities(self):
  self.assertEqual(expectation_bounds([D(5),D(15)],[D('.4'),D('.6')],[D('.4'),D('.6')])[:2],(D(11),D(11)))
 def test_wrong_horizon(self):
  p=fixture();p['valuation_horizon']='2030-01-01'
  with self.assertRaises(ValueError):calculate(p)
 def test_nonfinite_intervals(self):
  for x in ('NaN','Infinity'):
   with self.assertRaises(ValueError):expectation_bounds([D(x)],[D(1)],[D(1)])
 def test_infeasible(self):
  for lo,hi in [(['.6','.6'],['1','1']),(['0','0'],['.4','.4']),(['.7','0'],['.5','1'])]:
   with self.assertRaises(ValueError):expectation_bounds([D(0),D(1)],list(map(D,lo)),list(map(D,hi)))
 def test_ignorance_cannot_approve(self):
  r=calculate(fixture());self.assertIsNone(r['budget_capped_worst_case_limit']);self.assertFalse(r['current_debit_meets_worst_case_hurdle'])
 def test_cost_hurdle_formula(self):
  p=fixture();p['scenarios']=[{'id':'up','expiry_stock_price':'100','probability_lower':'1','probability_upper':'1'}]
  r=calculate(p);intr=D(r['expected_intrinsic_cash_bounds'][0]);fee=D(r['opening_fees'])
  self.assertAlmostEqual(D(r['max_premium_debit_for_hurdle_bounds'][0]),(intr-D(12))/D('1.1')-fee)
 def test_fee_reserve_monotone(self):
  p=fixture();a=calculate(p);p['closing_fee_reserve']='12';b=calculate(p)
  self.assertLess(D(b['max_premium_debit_for_hurdle_bounds'][0]),D(a['max_premium_debit_for_hurdle_bounds'][0]))
 def test_contract_count_funding(self):
  p=fixture();a=calculate(p);p['contracts']=2;b=calculate(p)
  self.assertEqual(D(b['funding']['long_exercise_purchase_cash']),2*D(a['funding']['long_exercise_purchase_cash']));self.assertIsNone(b['funding']['margin_requirement'])
 def test_bad_identity_rejected(self):
  p=fixture();p['payoff_packet']['strategy']['long_leg']['contract_id']='CRWV270416C00065000'
  with self.assertRaises(ValueError):calculate(p)
 def test_duplicates(self):
  p=fixture();p['scenarios'][1]['id']='down'
  with self.assertRaises(ValueError):calculate(p)
 def test_bruteforce_probability_vertices(self):
  vals=[D(2),D(7),D(21)];lo=[D('.1')]*3;hi=[D('.7')]*3;a=expectation_bounds(vals,lo,hi);brute=[]
  for i,j in itertools.product(range(1,8),repeat=2):
   x=D(i)/10;y=D(j)/10;z=1-x-y
   if lo[2]<=z<=hi[2]:brute.append(x*2+y*7+z*21)
  self.assertEqual(a[0],min(brute));self.assertEqual(a[1],max(brute))
if __name__=='__main__':unittest.main()
