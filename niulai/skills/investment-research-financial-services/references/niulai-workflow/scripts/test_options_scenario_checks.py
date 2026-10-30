"""Model arithmetic tests, not evidence of a forecast or trading advantage."""
import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import options_scenario_checks as o


def example_packet():
    return {'version':o.VERSION,'kind':'call','spot':100,'strike':100,'years':1,
            'rate':.05,'yield':0,'volatility':.2,'quotes':{'bid':10,'ask':11},
            'scenarios':[{'id':'delay_and_crush','spot':105,'elapsed_days':180,'volatility':.15},
                         {'id':'expiry_up','spot':120,'elapsed_days':365,'volatility':.2}]}


class OptionsTests(unittest.TestCase):
    def test_published_vollib_doctest_benchmark(self):
        # Official MIT-licensed source documentation's numerical examples:
        # https://vollib.org/documentation/1.0.3/_modules/py_vollib/black_scholes.html
        self.assertAlmostEqual(o.bsm('call',100,90,.5,.01,0,.2)['price'],12.111581435,places=6)
        self.assertAlmostEqual(o.bsm('put',100,90,.5,.01,0,.2)['price'],1.66270456231,places=6)
    def test_canonical_bsm_benchmark(self):
        # Standard S=K=100, r=.05, q=0, sigma=.2, T=1 benchmark.
        self.assertAlmostEqual(o.bsm('call',100,100,1,.05,0,.2)['price'],10.450583572185565,places=10)
        self.assertAlmostEqual(o.bsm('put',100,100,1,.05,0,.2)['price'],5.573526022256971,places=10)
    def test_put_call_parity(self):
        for q in (0,.02,.2):
            c=o.bsm('call',80,105,.7,.03,q,.4)['price']
            p=o.bsm('put',80,105,.7,.03,q,.4)['price']
            self.assertAlmostEqual(c-p,80*math.exp(-q*.7)-105*math.exp(-.03*.7),places=10)
    def test_greeks_finite_difference(self):
        for kind in ('call','put'):
            S,K,T,r,q,v=110,100,.8,.04,.02,.3
            b=o.bsm(kind,S,K,T,r,q,v)
            price=lambda S=S,T=T,r=r,v=v:o.bsm(kind,S,K,T,r,q,v)['price']
            h=.001
            self.assertAlmostEqual(b['delta'],(price(S=S+h)-price(S=S-h))/(2*h),places=7)
            self.assertAlmostEqual(b['gamma'],(price(S=S+h)-2*price()+price(S=S-h))/h**2,places=6)
            h=.00001
            self.assertAlmostEqual(b['vega_per_vol_point'],(price(v=v+h)-price(v=v-h))/(2*h)*.01,places=7)
            self.assertAlmostEqual(b['rho_per_rate_point'],(price(r=r+h)-price(r=r-h))/(2*h)*.01,places=7)
            self.assertAlmostEqual(b['theta_per_calendar_day'],-(price(T=T+h)-price(T=T-h))/(2*h)/365,places=7)
    def test_expiry(self):
        for kind,S,expected in [('call',120,20),('call',80,0),('put',80,20),('put',120,0)]:
            r=o.bsm(kind,S,100,0,.05,0,.2)
            self.assertEqual(r['price'],expected); self.assertIsNone(r['delta'])
    def test_iv_round_trip(self):
        for kind in ('call','put'):
            for sigma in (.1,.3,.8,2):
                p=o.bsm(kind,105,100,.6,.02,.01,sigma)['price']
                self.assertAlmostEqual(o.implied_vol(kind,105,100,.6,.02,.01,p),sigma,places=8)
    def test_iv_boundaries(self):
        self.assertEqual(o.implied_vol('call',80,100,1,.05,0,0),0)
        for p in (-1,100,101):
            with self.assertRaises(o.OptionError):o.implied_vol('call',100,100,1,.05,0,p)
        with self.assertRaises(o.OptionError):o.implied_vol('call',100,100,0,.05,0,0)
    def test_iv_interval(self):
        r=o.iv_interval('call',100,100,1,.05,0,10,11)
        self.assertLess(r['bid_iv'],.2); self.assertGreater(r['ask_iv'],.2)
        with self.assertRaises(o.OptionError):o.iv_interval('call',100,100,1,.05,0,11,10)
    def test_budget_is_not_implied_by_diagnostic(self):
        r=o.calculate(example_packet())
        self.assertFalse(r['trade_recommendation']); self.assertIn('American',r['limitation'])
    def test_scenario_delay_and_crush(self):
        r=o.calculate(example_packet())
        self.assertLess(r['scenarios'][0]['model_price_change'],0)
        self.assertEqual(r['scenarios'][1]['price'],20)
        self.assertIsNone(r['scenarios'][1]['theta_per_calendar_day'])
    def test_positive_vega_negative_call_theta_standard_case(self):
        r=o.bsm('call',100,100,1,.05,0,.2)
        self.assertGreater(r['vega_per_vol_point'],0); self.assertLess(r['theta_per_calendar_day'],0)
    def test_monotonicity_and_convexity(self):
        for kind in ('call','put'):
            prices=[o.bsm(kind,S,100,.5,.02,.01,.3)['price'] for S in (90,100,110)]
            self.assertGreaterEqual(prices[0]+prices[2]-2*prices[1],0)
            self.assertEqual(prices,sorted(prices,reverse=kind=='put'))
    def test_bad_domains(self):
        for key,value in [('spot',0),('strike',0),('years',-1),('volatility',0),('rate',float('nan')),('yield',True),('spot','100')]:
            p=example_packet();p[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(o.OptionError):o.calculate(p)
    def test_precision_boundaries_and_large_integer(self):
        for key,value in [('spot',10**1000),('spot',1e-300),('years',1e-300),('volatility',1e-300)]:
            p=example_packet();p[key]=value
            with self.subTest(key=key),self.assertRaises(o.OptionError):o.calculate(p)
    def test_scenario_after_expiry_rejected(self):
        p=example_packet();p['scenarios'][0]['elapsed_days']=366
        with self.assertRaises(o.OptionError):o.calculate(p)
    def test_machine_roundoff_at_exact_expiry(self):
        for years,days in [(3/365,3),(.0033,1.2045),(175/365,175)]:
            p=example_packet();p['years']=years;p['quotes']=None
            p['scenarios']=[{'id':'exact_expiry','spot':120,'elapsed_days':days,'volatility':.2}]
            r=o.calculate(p)['scenarios'][0]
            self.assertEqual(r['remaining_years'],0)
            self.assertEqual(r['status'],'expired_payoff_only')
            self.assertEqual(r['price'],20)
    def test_real_postexpiry_and_nonfinite_days_rejected(self):
        for days in [3+1e-8,float('inf'),float('nan'),True]:
            p=example_packet();p['years']=3/365;p['quotes']=None
            p['scenarios']=[{'id':'past','spot':120,'elapsed_days':days,'volatility':.2}]
            with self.subTest(days=days),self.assertRaises(o.OptionError):o.calculate(p)
    def test_duplicate_scenario_rejected(self):
        p=example_packet();p['scenarios'][1]['id']=p['scenarios'][0]['id']
        with self.assertRaises(o.OptionError):o.calculate(p)
    def test_duplicate_json_nonfinite(self):
        for raw in ('{"a":1,"a":2}','{"a":NaN}'):
            with self.assertRaises(o.OptionError):o.decode_packet(raw)
    def test_deterministic(self):
        p=example_packet()
        self.assertEqual(o.calculate(p),o.calculate(copy.deepcopy(p)))
    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input.json';out=Path(d)/'output.json';p.write_text(json.dumps(example_packet()))
            r=subprocess.run([sys.executable,o.__file__,'--input',str(p),'--output',str(out)],capture_output=True)
            self.assertEqual(r.returncode,0);self.assertEqual(json.loads(out.read_text())['version'],o.VERSION)
            p.write_text('{"x":NaN}')
            r=subprocess.run([sys.executable,o.__file__,'--input',str(p),'--output',str(out)],capture_output=True)
            self.assertEqual(r.returncode,2);self.assertEqual(json.loads(out.read_text())['status'],'rejected')


if __name__=='__main__':unittest.main()
