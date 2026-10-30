import copy
import datetime as dt
import importlib.util
import unittest
from unittest.mock import patch
import options_american_checks as m
from options_scenario_checks import bsm


def fixture(**updates):
    p={'version':1,'kind':'call','strike':65,'exercise':'american','as_of':'2026-10-23',
       'expiry':'2027-04-16','spot':54.24,'rate':.04,'yield':0,'volatility':.90,
       'units':{'price':'USD_per_share','rate':'annual_continuous_decimal',
                'yield':'annual_continuous_decimal','volatility':'annual_decimal'}}
    p.update(updates)
    return p


class Validation(unittest.TestCase):
    def test_nonfinite_types_units(self):
        for x in (True,'0.9',float('nan'),float('inf'),90,-1,0):
            with self.subTest(x=x), self.assertRaises(m.ModelError):
                m.validate(fixture(volatility=x))
        with self.assertRaises(m.ModelError): m.validate(fixture(units={}))
    def test_dates_and_unsupported(self):
        for x in ('2026-02-30','20261023','2026-10-23T16:00:00Z','2028-01-01'):
            with self.subTest(x=x), self.assertRaises(m.ModelError): m.validate(fixture(as_of=x))
        with self.assertRaises(m.ModelError): m.validate(fixture(borrow=0.02))
    def test_identity_binding(self):
        m.validate(fixture(contract_id='CRWV270416C00065000'))
        for x in ('CRWV270416C00070000','CRWV270416P00065000','CRWV270423C00065000'):
            with self.subTest(x=x), self.assertRaises(m.ModelError): m.validate(fixture(contract_id=x))
    def test_dividend_validation(self):
        good=[{'date':'2027-01-15','cash_per_share':1}]
        m.validate(fixture(dividends=good))
        for p in (fixture(dividends=good,**{'yield':.01}),fixture(dividends=good+good),
                  fixture(dividends=[{'date':'2026-10-23','cash_per_share':1}]),
                  fixture(dividends=[{'date':'2027-01-15','cash_per_share':60}])):
            with self.subTest(p=p), self.assertRaises(m.ModelError): m.validate(p)
    def test_scenario_dates_identity(self):
        for s in ({'id':'x','as_of':'2028-01-01','spot':60,'volatility':.8},
                  {'id':'x','as_of':'2026-12-01','spot':60,'volatility':.8,'probability':.8}):
            with self.assertRaises(m.ModelError):m.validate(fixture(scenarios=[s]))
    def test_duplicate_json_keys(self):
        for text in ('{"strike":65,"strike":70}', '{"units":{"price":"USD","price":"cents"}}'):
            with self.assertRaisesRegex(m.ModelError,'duplicate JSON key'): m.decode_packet(text)
    def test_upper_bound_rejects(self):
        def bad(p,g,e):return {'price':1e9,'delta':0,'gamma':0,'theta_per_calendar_day':0}
        with patch.object(m,'_price',side_effect=bad),self.assertRaisesRegex(m.ModelError,'upper bound'):
            m.calculate(fixture())
    def test_grids(self):
        for x in ([100,200,300],[50,100,True],[100,200],[1000,2000,4000]):
            with self.assertRaises(m.ModelError): m.validate(fixture(grids=x))
    def test_lazy_dependency(self):
        import builtins
        original=builtins.__import__
        def missing(name,*args,**kwargs):
            if name=='QuantLib': raise ImportError('fixture unavailable')
            return original(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=missing),self.assertRaisesRegex(m.ModelError,'optional dependency unavailable'):
            m.calculate(fixture())
    def test_failed_convergence_rejects(self):
        def unstable(p,g,e):return {'price':g/100,'delta':0,'gamma':0,'theta_per_calendar_day':0}
        with patch.object(m,'_price',side_effect=unstable),self.assertRaisesRegex(m.ModelError,'refinement failed'):
            m.calculate(fixture())
    def test_bound_failure_rejects(self):
        def bad(p,g,e):return {'price':0,'delta':0,'gamma':0,'theta_per_calendar_day':0}
        with patch.object(m,'_price',side_effect=bad),self.assertRaisesRegex(m.ModelError,'lower bound'):
            m.calculate(fixture(spot=90))


@unittest.skipUnless(importlib.util.find_spec('QuantLib'),'optional QuantLib not installed')
class Numerical(unittest.TestCase):
    def test_call_identity_and_independent_bsm(self):
        p=fixture(); result=m.calculate(p)['base']
        euro=bsm('call',54.24,65,(dt.date(2027,4,16)-dt.date(2026,10,23)).days/365,.04,0,.9)['price']
        self.assertAlmostEqual(result['price'],euro,delta=.005)
        self.assertAlmostEqual(result['early_exercise_premium'],0,delta=.005)
    def test_put_exercise_premium(self):
        r=m.calculate(fixture(kind='put',spot=60,strike=65,volatility=.3))['base']
        self.assertGreater(r['price'],r['european_reference'])
        self.assertGreaterEqual(r['price'],5-.005)
    def test_published_ju_reference(self):
        # Official QuantLib americanoption.cpp juValues citing Ju (1999),
        # Exhibit 3 short-dated put: K=S40 q0 r.0488 T.0833 sigma.2 value.851.
        # This is an approximation reference, not exact FD truth. T=30/360
        # is mapped to ACT365 by scaling integrated rate and variance.
        p=fixture(kind='put',strike=40,spot=40,rate=.0488*365/360,
                  volatility=.2*(365/360)**.5,as_of='2025-01-01',expiry='2025-01-31')
        result=m.calculate(p)['base']
        self.assertAlmostEqual(result['price'],.851,delta=.003)
    def test_independent_crr_put(self):
        # Separate stdlib recombining CRR implementation; not another QL engine.
        import math
        n=2000; S=36; K=40; r=.06; vol=.2; T=1.; step=T/n
        u=math.exp(vol*math.sqrt(step)); down=1/u
        probability=(math.exp(r*step)-down)/(u-down); disc=math.exp(-r*step)
        values=[max(K-S*u**j*down**(n-j),0) for j in range(n+1)]
        for t in range(n-1,-1,-1):
            values=[max(K-S*u**j*down**(t-j),disc*(probability*values[j+1]+(1-probability)*values[j])) for j in range(t+1)]
        actual=m.calculate(fixture(kind='put',spot=S,strike=K,rate=r,volatility=vol,as_of='2025-01-01',expiry='2026-01-01'))['base']['price']
        self.assertAlmostEqual(actual,values[0],delta=.003)
    def test_discrete_dividend_prices(self):
        p=fixture(spot=100,strike=80,volatility=.2,dividends=[{'date':'2027-01-15','cash_per_share':10}])
        r=m.calculate(p)['base']; no=m.calculate(fixture(spot=100,strike=80,volatility=.2))['base']
        self.assertGreater(r['price'],r['european_reference']+.1)
        self.assertLess(r['price'],no['price'])
        self.assertGreaterEqual(r['price'],20-.005)
    def test_expiry_and_state_restore(self):
        import QuantLib as ql
        old=ql.Settings.instance().evaluationDate
        p=fixture(as_of='2027-04-16',spot=80)
        r=m.calculate(p)['base']
        self.assertEqual(r['price'],15); self.assertIsNone(r['delta'])
        m.calculate(fixture())
        self.assertEqual(old,ql.Settings.instance().evaluationDate)
    def test_conditional_event_and_time(self):
        p=fixture(scenarios=[{'id':'after30_IVcrush','as_of':'2026-11-22','spot':54.24,'volatility':.60},
                            {'id':'gap_down','as_of':'2026-11-22','spot':40,'volatility':1.10}])
        r=m.calculate(p)
        self.assertIsNone(r['probabilities'])
        for s in r['scenarios']:self.assertLess(s['model_value_change_per_share'],0)
    def test_cash_event_consumed_once(self):
        p=fixture(dividends=[{'date':'2026-11-15','cash_per_share':1}],
                  scenarios=[{'id':'post_div','as_of':'2026-11-16','spot':53.24,'volatility':.9}])
        r=m.calculate(p)['scenarios'][0]['model']['price']
        x=m.calculate(fixture(as_of='2026-11-16',spot=53.24))['base']['price']
        self.assertAlmostEqual(r,x,places=9)

if __name__=='__main__':unittest.main()
