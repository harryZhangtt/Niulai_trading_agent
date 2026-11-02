#!/usr/bin/env python3
"""Bounded physical-assumption stock paths and cash-equivalent expiry option P&L.

Optional numpy/exchange_calendars; arch 8.0.0 only for stationary bootstrap.
Not a calibrated forecast, option-pricing engine or trade signal. GBM mu is
annual arithmetic dS/S drift; bootstrap recentering matches its *marginal*
one-step expected gross return, not multi-step mean under serial dependence.
Existing payoff checker binds exact OCC terms, costs, budget and deliverables.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from options_payoff_checks import calculate as payoff_calculate, stamp, day

VERSION='2026-10-24-options-path-1'

class PathError(ValueError): pass

def shape(x, fields, label):
    if type(x) is not dict or set(x)!=set(fields):raise PathError(label+': incorrect fields')
def finite(x,label,lo,hi):
    if type(x) not in (int,float) or not math.isfinite(x) or not lo<=x<=hi:raise PathError(label+': invalid finite numeric domain')
    return float(x)
def integer(x,label,lo,hi):
    if type(x) is not int or not lo<=x<=hi:raise PathError(label+': invalid integer domain')
    return x

def decode_packet(raw):
    def unique(items):
        result={}
        for k,v in items:
            if k in result:raise PathError('duplicate JSON key: '+k)
            result[k]=v
        return result
    return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda x: (_ for _ in ()).throw(PathError('nonfinite JSON')))

def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def wilson(mask):
    import numpy as np
    n=int(len(mask));k=int(np.count_nonzero(mask));p=k/n;z=1.959963984540054
    denom=1+z*z/n; center=(p+z*z/(2*n))/denom
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/denom
    return {'probability':p,'successes':k,'paths':n,'mc_95pct_wilson':[max(0,center-half),min(1,center+half)],
            'interval_meaning':'Monte_Carlo_sampling_only_conditional_on_fixed_model_and_history'}

def percentiles(values):
    import numpy as np
    return {str(q):float(np.percentile(values,q)) for q in (1,5,25,50,75,95,99)}

def summary(pnl,debit,budget):
    import numpy as np
    if debit==0:return {'status':'no_position','probability_profit':None,'probability_half_debit_loss':None,'probability_full_debit_loss':None,'pnl_percentiles':percentiles(pnl),'expected_pnl':float(np.mean(pnl))}
    return {'status':'conditional_model_only','probability_profit':wilson(pnl>1e-8),
            'probability_half_debit_loss':wilson(pnl<=-.5*debit),
            'probability_full_debit_loss':wilson(pnl<=-debit+1e-8),
            'pnl_percentiles':percentiles(pnl),'ending_wealth_percentiles':percentiles(budget+pnl),
            'expected_pnl':float(np.mean(pnl)),'opening_debit':debit}

def calculate(p):
    import numpy as np
    import exchange_calendars as xc
    shape(p,('version','payoff_packet','start_session','spot','clock','position_mode','simulation','history'),'packet')
    if type(p['version']) is not int or p['version']!=1:raise PathError('version must be1')
    if p['clock']!='XNYS_close_to_close_252':raise PathError('only XNYS close-to-close trading252 clock supported')
    if p['position_mode'] not in ('one_contract','max_affordable'):raise PathError('invalid position mode')
    spot=finite(p['spot'],'spot',.01,1e6)
    payoff=payoff_calculate(p['payoff_packet'])
    if spot!=float(payoff['stock_ask']):raise PathError('path spot must exactly bind payoff stock ask; explicit dated hypothetical quote packet required for overrides')
    s=p['simulation']
    shape(s,('method','paths','seed','annual_trading_days','annual_arithmetic_drift','sigma','drift_treatment','assumption_source_ref','block_size'),'simulation')
    n=integer(s['paths'],'paths',1000,100000);seed=integer(s['seed'],'seed',0,2**32-1)
    if type(s['annual_trading_days']) is not int or s['annual_trading_days']!=252:raise PathError('annual trading days must explicitly252')
    if not isinstance(s['assumption_source_ref'],str) or not s['assumption_source_ref'].strip():raise PathError('assumption provenance required')
    start=day(p['start_session'],'start_session');expiry=day(payoff['expiry'],'expiry');cutoff=stamp(payoff['as_of'],'cutoff')
    if not start<expiry or (expiry-start).days>740:raise PathError('require positive horizon <=2years')
    calendar=xc.get_calendar('XNYS',start=(start-dt.timedelta(days=4000)).isoformat(),end=(expiry+dt.timedelta(days=10)).isoformat())
    if not calendar.is_session(start.isoformat()) or not calendar.is_session(expiry.isoformat()):raise PathError('start/expiry must be actual XNYS session; nonstandard expiry unsupported')
    if calendar.session_close(start.isoformat()).to_pydatetime()>cutoff:raise PathError('start session close unavailable at cutoff')
    if (cutoff.date()-start).days>5:raise PathError('start must be latest completed XNYS session at cutoff')
    possible=calendar.sessions_in_range(start.isoformat(),cutoff.date().isoformat())
    completed=[d for d in possible if calendar.session_close(d).to_pydatetime()<=cutoff]
    if not completed or completed[-1].date()!=start:raise PathError('start must be latest completed XNYS session at cutoff')
    sessions=calendar.sessions_in_range(start.isoformat(),expiry.isoformat())[1:]
    steps=len(sessions)
    if n*steps>5_000_000:raise PathError('simulation exceeds5million pathsteps')
    if s['method']=='gbm':
        if s['drift_treatment']!='explicit_gbm_arithmetic' or s['block_size'] is not None or p['history'] is not None:raise PathError('GBM requires explicit arithmetic drift, null history/block')
        mu=finite(s['annual_arithmetic_drift'],'arithmetic drift',-1,2);sigma=finite(s['sigma'],'sigma',0,3)
        generator=np.random.default_rng(seed)
        increments=generator.normal((mu-.5*sigma*sigma)/252,sigma/math.sqrt(252),size=(n,steps))
        fitted={'annual_arithmetic_sde_drift_assumed':mu,'gbm_one_year_expected_simple_return':math.expm1(mu),'annual_vol_assumed':sigma,'per_step_log_mean':(mu-.5*sigma*sigma)/252,'history_sha256':None}
    elif s['method']=='stationary_bootstrap':
        import arch
        from arch.bootstrap import StationaryBootstrap
        if arch.__version__!='8.0.0':raise PathError('unvalidated arch version; require8.0.0')
        if s['sigma'] is not None:raise PathError('bootstrap sigma must be null; empirical returns determine distribution')
        h=p['history'];shape(h,('source_ref','observed_at','returns')+(('max_gap_sessions',) if isinstance(h,dict) and 'max_gap_sessions' in h else ()),'history')
        maxgap=integer(h.get('max_gap_sessions',0),'history max gap sessions',0,5)
        if not isinstance(h['source_ref'],str) or not h['source_ref'].strip():raise PathError('history source required')
        if stamp(h['observed_at'],'history observed_at')>cutoff:raise PathError('history was unavailable at forecast cutoff')
        if type(h['returns']) is not list or not max(60,steps)<=len(h['returns'])<=5000:raise PathError('history requires >=60returns and >=horizonsteps, <=5000')
        dates=[];values=[]
        for row in h['returns']:
            shape(row,('session','log_return'),'return')
            d=day(row['session'],'return.session')
            if d>start:raise PathError('lookahead history after origin')
            dates.append(d);values.append(finite(row['log_return'],'daily log return',-2,2))
        expected=[x.date() for x in calendar.sessions_in_range(dates[0].isoformat(),dates[-1].isoformat())]
        if dates!=expected:raise PathError('history must be sorted contiguous XNYS returns')
        gap=len(calendar.sessions_in_range(dates[-1].isoformat(),start.isoformat()))-1
        if gap>maxgap:raise PathError('history gap exceeds explicit allowed sessions')
        raw=np.asarray(values);block=integer(s['block_size'],'block size',1,min(60,len(raw)//3))
        if s['drift_treatment']=='raw_empirical':
            if s['annual_arithmetic_drift'] is not None:raise PathError('raw empirical drift requires null override')
            shift=0.
        elif s['drift_treatment']=='center_marginal_to_assumed_arithmetic':
            mu=finite(s['annual_arithmetic_drift'],'arithmetic drift',-1,2)
            shift=mu/252-math.log(float(np.mean(np.exp(raw))))
        else:raise PathError('unsupported bootstrap drift treatment')
        bs=StationaryBootstrap(block,raw,seed=seed)
        increments=np.empty((n,steps))
        for i,(pos,kw) in enumerate(bs.bootstrap(n)):increments[i]=pos[0][:steps]+shift
        fitted={'history_sha256':digest(h),'history_returns':len(raw),'mean_block_length':block,
                'history_last_session':dates[-1].isoformat(),'history_gap_sessions':gap,'history_gap_limit':maxgap,'history_gap_limitation':('Latest history lags assumed forecast origin; missing returns were not invented.' if gap else None),
                'raw_annual_log_mean':float(np.mean(raw))*252,'raw_annual_vol':float(np.std(raw,ddof=1))*math.sqrt(252),
                'per_step_log_shift':shift,'serial_dependence_caveat':'marginal drift centering does not fix multi-step expected arithmetic return under dependent blocks'}
    else:raise PathError('unsupported physical path method')
    logpaths=np.cumsum(increments,axis=1)
    if not np.all(np.isfinite(logpaths)) or np.max(np.abs(logpaths))>50:raise PathError('path exponential domain exceeded')
    stock=spot*np.exp(logpaths);terminal=stock[:,-1]
    startcol=np.full((n,1),spot);all_stock=np.concatenate((startcol,stock),axis=1)
    running_peak=np.maximum.accumulate(all_stock,axis=1)
    drawdown=np.min(all_stock/running_peak-1,axis=1)
    terms=p['payoff_packet']['strategy'];lo=float(terms['long_leg']['strike']);hi=None if terms['short_leg'] is None else float(terms['short_leg']['strike'])
    intrinsic=np.maximum(terminal-lo,0)-(np.maximum(terminal-hi,0) if hi is not None else 0)
    budgets={}
    for name,c in payoff['budget_cases'].items():
        budget=float(c['budget']);oc=c['options'];sc=c['shares'];max_n=oc['modeled_contracts'];count=min(max_n,1) if p['position_mode']=='one_contract' else max_n
        legs=1 if hi is None else 2;fees=p['payoff_packet']['fees']
        debit=(float(payoff['conservative_debit_per_share'])*100*count+legs*(float(fees['option_fixed_per_leg'])+float(fees['option_per_contract_per_leg'])*count)) if count else 0
        option_pnl=intrinsic*100*count-debit
        share_n=float(sc['modeled_shares']);share_cost=float(sc['opening_cash_required']);share_pnl=terminal*share_n-share_cost
        be=lo+debit/(100*count) if count else None
        reachable=be is not None and (hi is None or be<hi)
        touch=None if not reachable else wilson(np.any(all_stock>=be,axis=1))
        first=None
        if reachable:
            hit=all_stock>=be;indices=np.argmax(hit,axis=1);ever=np.any(hit,axis=1)
            first={'condition':'first sampled close at/above expiry breakeven; NOT actual option profit or intraday touch','conditional_trading_step_percentiles':percentiles(indices[ever]) if np.any(ever) else None}
        budgets[name]={'budget':budget,'position_mode':p['position_mode'],'modeled_contracts':count,'max_affordable_depth_capped_contracts':max_n,
                       'options':summary(option_pnl,debit,budget),'shares':dict(summary(share_pnl,share_cost,budget),modeled_shares=share_n),
                       'cash':{'pnl':0,'ending_wealth':budget,'return_assumption':0},'expiry_breakeven':be,
                       'sampled_touch_expiry_breakeven':touch,'first_sampled_touch':first,'probability_option_outperforms_same_budget_shares':wilson(option_pnl>share_pnl+1e-8) if count else None}
    return {'version':VERSION,'status':'conditional_assumption_not_calibrated','input_sha256':digest(p),'payoff_input_sha256':payoff['input_sha256'],
            'payoff_result':payoff,'method':s['method'],'fitted_inputs':fitted,'simulation':s,'start_session':start.isoformat(),'expiry':expiry.isoformat(),
            'calendar':{'name':'XNYS','library_version':xc.__version__,'future_sessions':[x.date().isoformat() for x in sessions],'trading_steps':steps,'annual_steps':252,'calendar_days':(expiry-start).days,'clock':'close_to_close_no_intraday_or_weekend_path'},
            'versions':{'numpy':np.__version__,'arch':'8.0.0' if s['method']=='stationary_bootstrap' else None},
            'terminal_stock_prices':terminal.tolist(),'terminal_stock_percentiles':percentiles(terminal),'max_drawdown_percentiles':percentiles(drawdown),'drawdown_basis':'underlying sampled close-to-close peak-to-trough, not option drawdown',
            'daily_stock_fan':[{'session':start.isoformat(),'percentiles':percentiles(startcol[:,0])}]+[{'session':d.date().isoformat(),'percentiles':percentiles(stock[:,i])} for i,d in enumerate(sessions)],
            'illustrative_paths':{'selection':'first5seededpaths_not_representative_scenarios','stock_prices':all_stock[:5].tolist()},
            'budget_cases':budgets,'model_uncertainty':{'calibrated':False,'interval':None,'sensitivity_required':'compare plausible drifts/vols/block lengths and methods; MC interval excludes parameter/model error'},
            'limitations':['Physical assumptions, not risk-neutral pricing or calibrated probabilities.','Daily closes omit intraday touches and extreme jumps absent from assumed/history distribution.','P&L is expiry cash-equivalent; exercise funding, interim option valuation, assignment, closing fees and tax excluded.','Bootstrap assumes historical stationarity, cannot invent unseen regimes, and a short listing history limits evidence.','Input provenance/freshness/standard deliverable declarations are not source authentication.','Shares exclude dividends and idle cash earns zero.']}

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--input',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
    try:result=calculate(decode_packet(Path(a.input).read_bytes()));code=0
    except (ValueError,TypeError,KeyError,OSError,ImportError) as e:result={'version':VERSION,'status':'blocked','error':str(e)};code=2
    target=Path(a.output);target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',dir=target.parent,delete=False) as f:json.dump(result,f,indent=2,allow_nan=False);f.write('\n');tmp=f.name
    os.replace(tmp,target);return code

if __name__=='__main__':raise SystemExit(main())
