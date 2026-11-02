import copy
import importlib.util
from pathlib import Path
import unittest

P=Path(__file__).resolve().parents[1]/'references/niulai-workflow/scripts/entry_policy_ev.py'
spec=importlib.util.spec_from_file_location('entry_policy_ev',P);M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

def fixture():
    def obs(t,p,d=0,invalid=False):return {'time_years':t,'price':p,'dividend_per_share':d,'invalidated':invalid}
    return {'budget':100,'horizon_years':2,'cash_rate':0,'fee_fraction':0,'price_basis':'split_adjusted_price_only','invalidation_action':'hold_no_new','probability_basis':'judgment',
      'policies':[{'id':'now','kind':'now','starter_fraction':1},{'id':'starter','kind':'staged','starter_fraction':.25,'limit_price':80},{'id':'wait','kind':'wait','starter_fraction':0,'limit_price':80}],
      'scenarios':[{'id':'rise','probability':.5,'observations':[obs(0,100),obs(1,110),obs(2,140)]},{'id':'dip','probability':.5,'observations':[obs(0,100),obs(1,80),obs(2,120)]}]}

class EntryPolicyTests(unittest.TestCase):
    def test_equal_budget_and_nonfills(self):
        o=M.compare(fixture());self.assertEqual(o['scenarios']['rise']['wait']['terminal_wealth'],100)
        self.assertEqual(o['scenarios']['rise']['starter']['terminal_wealth'],110)
        self.assertEqual(o['scenarios']['dip']['wait']['terminal_wealth'],150)
        self.assertEqual(o['policies']['now']['expected_terminal_wealth'],130)
        self.assertEqual(o['policies']['wait']['expected_terminal_wealth'],125)
        pair=next(x for x in o['paired_comparisons'] if x['a']=='now' and x['b']=='wait')
        self.assertAlmostEqual(pair['break_even_first_scenario_probability'],3/7)

    def test_cash_carry_on_unfilled_and_cash_dividends(self):
        d=fixture();d['cash_rate']=.1;d['scenarios'][0]['observations'][1]['dividend_per_share']=10
        o=M.compare(d);self.assertAlmostEqual(o['scenarios']['rise']['wait']['terminal_wealth'],121)
        self.assertAlmostEqual(o['scenarios']['rise']['now']['terminal_wealth'],151)

    def test_no_dividend_capture_on_fill_observation(self):
        d=fixture();d['scenarios'][1]['observations'][1]['dividend_per_share']=20
        o=M.compare(d);self.assertEqual(o['scenarios']['dip']['wait']['terminal_wealth'],150)
        self.assertEqual(o['scenarios']['dip']['now']['terminal_wealth'],140)

    def test_invalidation_prevents_fill_and_can_liquidate(self):
        d=fixture();d['invalidation_action']='liquidate';d['scenarios'][1]['observations'][1]['invalidated']=True
        o=M.compare(d);self.assertEqual(o['scenarios']['dip']['wait']['terminal_wealth'],100)
        self.assertEqual(o['scenarios']['dip']['now']['terminal_wealth'],80)

    def test_no_lookahead(self):
        a=fixture();b=copy.deepcopy(a);b['scenarios'][1]['observations'][-1]['price']=1000
        x=M.compare(a);y=M.compare(b)
        self.assertEqual(x['scenarios']['dip']['starter']['events'][:-1],y['scenarios']['dip']['starter']['events'][:-1])

    def test_terminal_touch_is_not_entry(self):
        d=fixture();d['scenarios'][0]['observations'][-1]['price']=70
        o=M.compare(d);self.assertFalse(o['scenarios']['rise']['wait']['remainder_filled'])

    def test_unknown_probabilities_no_fabricated_ev(self):
        d=fixture();d['probability_basis']='unknown'
        for s in d['scenarios']:s.pop('probability')
        self.assertNotIn('expected_terminal_wealth',M.compare(d)['policies']['now'])

    def test_negative_carry_partial_fill_is_not_full(self):
        d=fixture();d['cash_rate']=-.1
        r=M.compare(d)['scenarios']['dip']['wait']
        self.assertTrue(r['remainder_triggered'])
        self.assertFalse(r['remainder_filled'])
        self.assertAlmostEqual(r['original_budget_spent'],90)
        self.assertGreaterEqual(r['cash'],0)

    def test_fee_both_sides(self):
        d=fixture();d['fee_fraction']=.01
        self.assertAlmostEqual(M.compare(d)['scenarios']['rise']['now']['terminal_wealth'],100/101*140*.99)

    def test_reject_total_return_prices_bad_weights_and_clocks(self):
        for mutate in [lambda d:d.update(price_basis='adjusted_close'),lambda d:d['scenarios'][0].update(probability=.6),lambda d:d['scenarios'][1]['observations'][-1].update(time_years=3),lambda d:d['scenarios'][1]['observations'][0].update(price=90),lambda d:d.update(cash_rate=float('nan'))]:
            d=fixture();mutate(d)
            with self.assertRaises(ValueError):M.compare(d)

if __name__=='__main__':unittest.main()
