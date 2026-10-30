#!/usr/bin/env python3
"""Optional, date-level QuantLib American/European FD diagnostics; not quotes.

Only QuantLib==1.44 is supported by this tested adapter. Lazy import keeps the
core stdlib workflow independent. Continuous rates/yields and decimal annual
volatility are explicit; prices are USD/share. Flat-vol conditional scenarios
are not a fitted surface, calibrated jump process, probability or trade signal.
QuantLib evaluation-date state is restored; call through this adapter serially
or in separate worker processes (unrelated QuantLib threads are not protected).
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
from options_payoff_checks import parse_contract_id

VERSION = '2026-10-24-american-fd-1'
PIN = '1.44'
_LOCK = threading.RLock()
LIMITATIONS = [
    'Date-level ACT/365F valuation; no intraday expiry/cutoff modeling.',
    'Flat-volatility BSM diffusion with early exercise, not a calibrated smile or jump model.',
    'Scenario spot and IV shocks are conditional assumptions, not probabilities.',
    'No executable quote, contract deliverable verification, borrow forecast, fees or spread costs.',
    'Convergence is a numerical stability check, not proof that market assumptions are correct.',
    'Delta/gamma/theta are local engine diagnostics; only price grid convergence is certified.'
]

class ModelError(ValueError):
    pass


def num(value, name, lo, hi):
    if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
        raise ModelError(name + ': expected finite JSON number in supported domain')
    return float(value)


def date(value, name):
    if not isinstance(value, str) or len(value) != 10:
        raise ModelError(name + ': expected YYYY-MM-DD')
    try:
        result = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ModelError(name + ': invalid date') from exc
    if result.isoformat() != value or not 1901 <= result.year <= 2099:
        raise ModelError(name + ': outside supported date domain')
    return result


def keys(value, allowed, required, name):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ModelError(name + ': missing or unsupported fields')


def validate(packet):
    allowed = {'version','contract_id','kind','strike','exercise','as_of','expiry','spot','rate','yield',
               'volatility','units','dividends','grids','tolerance_per_share','scenarios'}
    required = allowed - {'contract_id','dividends','grids','tolerance_per_share','scenarios'}
    keys(packet, allowed, required, 'packet')
    p = copy.deepcopy(packet)
    if p['version'] != 1 or type(p['version']) is not int:
        raise ModelError('version must be 1')
    if p['kind'] not in ('call', 'put') or p['exercise'] not in ('american','european'):
        raise ModelError('unsupported kind/exercise')
    if p['units'] != {'price':'USD_per_share','rate':'annual_continuous_decimal',
                      'yield':'annual_continuous_decimal','volatility':'annual_decimal'}:
        raise ModelError('units must be explicitly USD/share and annual decimal')
    a, e = date(p['as_of'],'as_of'), date(p['expiry'],'expiry')
    if not 0 <= (e-a).days <= 3653:
        raise ModelError('expiry must be from valuation date through 10 years')
    for field, lo, hi in [('spot',.01,1e6),('strike',.01,1e6),('rate',-.2,.5),
                          ('yield',0,.5),('volatility',.001,5)]:
        p[field] = num(p[field],field,lo,hi)
    if p.get('contract_id') is not None:
        c = parse_contract_id(p['contract_id'])
        if c['expiry'] != e or c['right'] != p['kind'] or float(c['strike']) != p['strike']:
            raise ModelError('contract_id does not bind strike, expiry and option kind')
    ds = p.setdefault('dividends',[])
    if not isinstance(ds,list) or len(ds)>100:
        raise ModelError('dividends must be a bounded list')
    seen = set()
    for d in ds:
        keys(d,{'date','cash_per_share'},{'date','cash_per_share'},'dividend')
        day = date(d['date'],'dividend.date')
        if not a < day < e or day in seen:
            raise ModelError('cash dividends require unique ex-dates strictly between valuation and expiry')
        seen.add(day)
        d['cash_per_share'] = num(d['cash_per_share'],'cash dividend',.000001,p['spot'])
    if ds and (p['yield'] != 0 or sum(d['cash_per_share'] for d in ds) >= p['spot']):
        raise ModelError('discrete dividends require yield=0 and cash sum below spot; no double count')
    grids = p.setdefault('grids',[100,200,400])
    if (not isinstance(grids,list) or len(grids)!=3 or
            any(type(g) is not int or not 50<=g<=1600 for g in grids) or
            grids[1] != 2*grids[0] or grids[2] != 2*grids[1]):
        raise ModelError('grids require three doubling integer levels within 50..1600')
    p['tolerance_per_share'] = num(p.get('tolerance_per_share',.005),'tolerance',.000001,.01)
    ss = p.setdefault('scenarios',[])
    if not isinstance(ss,list) or len(ss)>40:
        raise ModelError('scenarios must be a bounded list')
    names = set()
    for s in ss:
        keys(s,{'id','as_of','spot','volatility'},{'id','as_of','spot','volatility'},'scenario')
        if not isinstance(s['id'],str) or not s['id'].strip() or s['id'] in names:
            raise ModelError('scenario IDs must be unique and nonempty')
        names.add(s['id'])
        if not a<=date(s['as_of'],'scenario.as_of')<=e:
            raise ModelError('scenario date outside contract life')
        s['spot'] = num(s['spot'],'scenario spot',.01,1e6)
        s['volatility'] = num(s['volatility'],'scenario volatility',.001,5)
        if any(d['date']==s['as_of'] for d in ds):
            raise ModelError('ex-dividend-day scenario convention unsupported')
    return p


def _quantlib():
    try:
        import QuantLib as ql
    except ImportError as exc:
        raise ModelError('optional dependency unavailable; install requirements-options-american.txt') from exc
    if ql.__version__ != PIN:
        raise ModelError('unvalidated QuantLib version; expected '+PIN)
    return ql


def _price(p, grid, exercise):
    ql = _quantlib()
    a,e = date(p['as_of'],'as_of'),date(p['expiry'],'expiry')
    if a == e:
        return {'price':max(p['spot']-p['strike'],0) if p['kind']=='call' else max(p['strike']-p['spot'],0),
                'delta':None,'gamma':None,'theta_per_calendar_day':None}
    qdate = lambda d: ql.Date(d.day,d.month,d.year)
    today, maturity = qdate(a),qdate(e)
    with _LOCK:
        settings = ql.Settings.instance()
        old_date = settings.evaluationDate
        try:
            settings.evaluationDate = today
            dc=ql.Actual365Fixed()
            process=ql.BlackScholesMertonProcess(ql.QuoteHandle(ql.SimpleQuote(p['spot'])),
                ql.YieldTermStructureHandle(ql.FlatForward(today,p['yield'],dc)),
                ql.YieldTermStructureHandle(ql.FlatForward(today,p['rate'],dc)),
                ql.BlackVolTermStructureHandle(ql.BlackConstantVol(today,ql.NullCalendar(),p['volatility'],dc)))
            payoff=ql.PlainVanillaPayoff(ql.Option.Call if p['kind']=='call' else ql.Option.Put,p['strike'])
            ex=ql.AmericanExercise(today,maturity) if exercise=='american' else ql.EuropeanExercise(maturity)
            option=ql.VanillaOption(payoff,ex)
            dividends=[ql.FixedDividend(d['cash_per_share'],qdate(date(d['date'],'dividend.date'))) for d in p['dividends']]
            # Spot cash-dividend model; no continuous yield when this schedule exists.
            engine=(ql.FdBlackScholesVanillaEngine(process,dividends,grid,grid,2) if dividends
                    else ql.FdBlackScholesVanillaEngine(process,grid,grid,2))
            option.setPricingEngine(engine)
            result={'price':option.NPV(),'delta':option.delta(),'gamma':option.gamma(),
                    'theta_per_calendar_day':option.theta()/365.0}
            if any(not math.isfinite(x) for x in result.values()):
                raise ModelError('non-finite model output')
            return result
        except RuntimeError as exc:
            raise ModelError('QuantLib engine failure: '+str(exc)) from exc
        finally:
            settings.evaluationDate = old_date


def _checked(p):
    values=[_price(p,g,p['exercise']) for g in p['grids']]
    fine=values[-1]
    residual=abs(values[-1]['price']-values[-2]['price'])
    previous=abs(values[-2]['price']-values[-3]['price'])
    tol=p['tolerance_per_share']
    if residual>tol:
        raise ModelError('grid refinement failed: residual '+str(residual)+' exceeds '+str(tol))
    intrinsic=max(p['spot']-p['strike'],0) if p['kind']=='call' else max(p['strike']-p['spot'],0)
    T=(date(p['expiry'],'expiry')-date(p['as_of'],'as_of')).days/365
    upper=p['spot'] if p['kind']=='call' else p['strike']*max(1,math.exp(-p['rate']*T))
    if fine['price']>upper+tol:
        raise ModelError('model violates option upper bound')
    eu=_price(p,p['grids'][-1],'european')['price']
    if fine['price'] < -tol or (p['exercise']=='american' and fine['price']<max(intrinsic,eu)-tol):
        raise ModelError('model violates exercise/European lower bound')
    if p['exercise']=='american' and p['kind']=='call' and not p['dividends'] and p['yield']==0 and p['rate']>=0 and abs(fine['price']-eu)>tol:
        raise ModelError('nondividend American-call/European identity failed')
    return dict(fine,european_reference=eu,early_exercise_premium=fine['price']-eu,
                grid_prices=[{'grid':g,'price':v['price']} for g,v in zip(p['grids'],values)],
                refinement_residual_per_share=residual,prior_refinement_residual_per_share=previous,
                tolerance_per_share=tol,greeks_status='local_diagnostics_not_grid_certified',status='numerically_checked_model_only')


def calculate(packet):
    p=validate(packet)
    base=_checked(p)
    scenarios=[]
    for s in p['scenarios']:
        x=copy.deepcopy(p)
        x.update({k:s[k] for k in ('as_of','spot','volatility')})
        x['scenarios']=[]
        # User supplies the scenario spot after past cash events; never subtract twice.
        x['dividends']=[d for d in x['dividends'] if d['date']>s['as_of']]
        validate(x)
        result=_checked(x)
        scenarios.append(dict(s,model=result,model_value_change_per_share=result['price']-base['price']))
    canonical=json.dumps(p,sort_keys=True,separators=(',',':'),allow_nan=False)
    return {'version':VERSION,'quantlib_version':PIN,'input_sha256':hashlib.sha256(canonical.encode()).hexdigest(),
            'inputs':p,'base':base,'scenarios':scenarios,'limitations':LIMITATIONS,
            'quote_or_trade_recommendation':False,'probabilities':None}


def decode_packet(text):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:
                raise ModelError('duplicate JSON key: '+key)
            result[key]=value
        return result
    return json.loads(text,object_pairs_hook=unique,parse_constant=lambda x: (_ for _ in ()).throw(ModelError('nonfinite JSON')))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',required=True); ap.add_argument('--output',required=True)
    args=ap.parse_args()
    try:
        raw=decode_packet(Path(args.input).read_text())
        result=calculate(raw)
        code=0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        result={'version':VERSION,'status':'blocked','error':str(exc),'quote_or_trade_recommendation':False}
        code=2
    target=Path(args.output); target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',dir=target.parent,delete=False) as f:
        json.dump(result,f,indent=2,allow_nan=False); f.write('\n'); temp=f.name
    os.replace(temp,target)
    return code

if __name__=='__main__':
    raise SystemExit(main())
