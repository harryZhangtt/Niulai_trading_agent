import copy
import datetime as dt
import json
import math
import unittest
import numpy as np
import exchange_calendars as xc
import options_path_checks as m
from test_options_payoff_checks import example_packet


def fixture(kind='long_call'):
    payoff=example_packet(kind);payoff['as_of']='2026-10-23T21:00:00Z';payoff['mode']='historical';payoff['budget']['amount']='1100'
    for key in ('long_leg','short_leg'):
        if payoff['strategy'][key]:
            leg=payoff['strategy'][key];leg['expiry']='2027-04-16';leg['contract_id']=leg['contract_id'].replace('270618','270416')
    return {'version':1,'payoff_packet':payoff,'start_session':'2026-10-23','spot':100.,'clock':'XNYS_close_to_close_252','position_mode':'one_contract',
            'simulation':{'method':'gbm','paths':1000,'seed':123,'annual_trading_days':252,'annual_arithmetic_drift':.2,'sigma':.4,
                          'drift_treatment':'explicit_gbm_arithmetic','assumption_source_ref':'synthetic:assumption-not-forecast','block_size':None},'history':None}


def boot():
    p=fixture();c=xc.get_calendar('XNYS');dates=c.sessions_in_range('2025-10-01','2026-10-23')
    p['simulation'].update(method='stationary_bootstrap',sigma=None,drift_treatment='center_marginal_to_assumed_arithmetic',block_size=5)
    p['history']={'source_ref':'synthetic:returns','observed_at':'2026-10-23T20:01:00Z',
                  'returns':[{'session':d.date().isoformat(),'log_return':.02*math.sin(i)+.001} for i,d in enumerate(dates)]}
    return p

class Paths(unittest.TestCase):
    def test_seed_reproducible_horizon(self):
        p=fixture();a=m.calculate(p);b=m.calculate(p)
        self.assertEqual(a,b);self.assertEqual(a['calendar']['trading_steps'],119)
        self.assertEqual(a['illustrative_paths']['stock_prices'][0][-1],a['terminal_stock_prices'][0])
        self.assertEqual(len(a['daily_stock_fan']),120)
    def test_arithmetic_not_log_drift(self):
        p=fixture();p['simulation']['sigma']=0;r=m.calculate(p)
        expected=100*math.exp(.2*119/252)
        self.assertAlmostEqual(r['terminal_stock_prices'][0],expected,places=10)
        self.assertAlmostEqual(r['fitted_inputs']['gbm_one_year_expected_simple_return'],math.expm1(.2))
    def test_full_loss_and_fee_units(self):
        p=fixture();p['simulation'].update(sigma=0,annual_arithmetic_drift=0)
        r=m.calculate(p)['budget_cases']['requested']
        self.assertEqual(r['modeled_contracts'],1);self.assertEqual(r['options']['opening_debit'],501)
        self.assertEqual(r['options']['probability_full_debit_loss']['probability'],1)
        self.assertEqual(r['options']['expected_pnl'],-501)
        self.assertEqual(r['shares']['expected_pnl'],0)
    def test_max_contracts_vs_one(self):
        p=fixture();p['position_mode']='max_affordable';r=m.calculate(p)['budget_cases']['requested']
        self.assertEqual(r['modeled_contracts'],2);self.assertEqual(r['options']['opening_debit'],1002)
    def test_spread_cap_and_no_position(self):
        p=fixture('bull_call_debit_spread');p['simulation'].update(sigma=0,annual_arithmetic_drift=2)
        r=m.calculate(p)['budget_cases']['requested']
        self.assertAlmostEqual(r['options']['expected_pnl'],1000-302)
        p['payoff_packet']['budget']['amount']='1';r=m.calculate(p)['budget_cases']['requested']
        self.assertEqual(r['options']['status'],'no_position');self.assertIsNone(r['options']['probability_profit']);self.assertIsNone(r['probability_option_outperforms_same_budget_shares'])
    def test_touch_not_terminal_profit(self):
        r=m.calculate(fixture())['budget_cases']['requested']
        self.assertGreaterEqual(r['sampled_touch_expiry_breakeven']['probability'],r['options']['probability_profit']['probability'])
        self.assertIn('NOT actual option profit',r['first_sampled_touch']['condition'])
    def test_monte_carlo_mean_and_drawdown(self):
        p=fixture();p['simulation']['paths']=10000;r=m.calculate(p)
        values=np.asarray(r['terminal_stock_prices']);expected=100*math.exp(.2*119/252)
        self.assertLess(abs(values.mean()-expected),4*values.std()/math.sqrt(len(values)))
        self.assertTrue(all(v<=1e-12 for v in r['max_drawdown_percentiles'].values()))
    def test_bootstrap_seed_and_centering(self):
        p=boot();a=m.calculate(p);b=m.calculate(p);self.assertEqual(a,b)
        raw=np.array([x['log_return'] for x in p['history']['returns']]);shift=a['fitted_inputs']['per_step_log_shift']
        self.assertAlmostEqual(float(np.mean(np.exp(raw+shift))),math.exp(.2/252),places=12)
        self.assertFalse(a['model_uncertainty']['calibrated'])
    def test_bootstrap_raw_mean_and_lag(self):
        p=boot();p['simulation'].update(drift_treatment='raw_empirical',annual_arithmetic_drift=None)
        p['history']['returns'].pop();p['history']['max_gap_sessions']=1
        r=m.calculate(p);self.assertEqual(r['fitted_inputs']['history_gap_sessions'],1);self.assertEqual(r['fitted_inputs']['per_step_log_shift'],0)
        del p['history']['max_gap_sessions']
        with self.assertRaises(m.PathError):m.calculate(p)
    def test_bad_history_and_lookahead(self):
        for mutation in ('future','unsorted','missing','observedfuture'):
            p=boot()
            if mutation=='future':p['history']['returns'][-1]['session']='2026-10-26'
            if mutation=='unsorted':p['history']['returns'].reverse()
            if mutation=='missing':p['history']['returns'].pop(10)
            if mutation=='observedfuture':p['history']['observed_at']='2026-10-24T00:00:00Z'
            with self.subTest(mutation=mutation),self.assertRaises(m.PathError):m.calculate(p)
    def test_spot_origin_mapping(self):
        for field,value in [('spot',101),('start_session','2026-10-22')]:
            p=fixture();p[field]=value
            with self.assertRaises(m.PathError):m.calculate(p)
        p=fixture();p['payoff_packet']['as_of']='2026-10-23T19:00:00Z'
        with self.assertRaises(m.PathError):m.calculate(p)
    def test_reject_malformed_units_scope(self):
        for field,value in [('paths',True),('paths',100000),('annual_trading_days',365),('sigma',float('nan')),('method','risk_neutral'),('annual_arithmetic_drift',20)]:
            p=fixture();p['simulation'][field]=value
            with self.subTest(field=field),self.assertRaises(m.PathError):m.calculate(p)
        with self.assertRaises(m.PathError):m.decode_packet('{"spot":1,"spot":2}')
    def test_wilson_boundary_not_certainty(self):
        a=m.wilson(np.zeros(1000,dtype=bool));b=m.wilson(np.ones(1000,dtype=bool))
        self.assertGreater(a['mc_95pct_wilson'][1],0);self.assertLess(b['mc_95pct_wilson'][0],1)

if __name__=='__main__':unittest.main()
