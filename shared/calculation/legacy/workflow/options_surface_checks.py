#!/usr/bin/env python3
"""Small European IV/total-variance surface diagnostic; never execution clearance.

Reuses checked BSM inversion. Piecewise linear total variance in forward log
moneyness and time, strictly within common support. No fitted SVI parameters,
extrapolation, American adjustment or real-world probability is invented.
Node and sampled checks detect some static inconsistencies, not arbitrage freedom.
"""
import argparse, hashlib, json, math, re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import options_scenario_checks as b
from options_payoff_checks import parse_contract_id, stamp as strict_stamp
VERSION='2026-10-24-options-surface-1'
LIMITATION='European continuous-carry diagnostic. Missing/unsynchronized quotes and American exercise prevent market calibration. Sampled checks are not a proof of arbitrage freedom; no recommendation or physical probability.'

def stamp(v):return strict_stamp(v,'$.timestamp')

def num(v,label,lo=0,hi=1e10):return b.number(v,label,lo,hi)

def line(xs,ys,x):
    if not xs or x<xs[0] or x>xs[-1]:return None
    for i,a in enumerate(xs):
        if x==a:return ys[i]
        if x<a:
            w=(x-xs[i-1])/(a-xs[i-1]);return ys[i-1]*(1-w)+ys[i]*w
    return ys[-1]

def surface(slices,T,k,field='variance_mid'):
    """None outside both bracketing smiles; no extrapolation across gaps."""
    times=sorted(slices)
    if not times or T<times[0] or T>times[-1]:return None
    def at(t):
        rows=slices[t];return line([r['log_moneyness'] for r in rows],[r[field] for r in rows],k)
    if T in slices:return at(T)
    for j,t in enumerate(times):
        if t>T:
            a,z=at(times[j-1]),at(t)
            if a is None or z is None:return None
            w=(T-times[j-1])/(t-times[j-1]);return a*(1-w)+z*w
    return None

def price_checks(rows,discount,tolerance=1e-8):
    failures=[];slopes=[]
    for a,z in zip(rows,rows[1:]):
        slope=(z['mid']-a['mid'])/(z['strike']-a['strike']);slopes.append(slope)
        if slope>tolerance:failures.append('call_price_increases_with_strike')
        if slope < -discount-tolerance:failures.append('vertical_spread_exceeds_discounted_width')
    if any(z<a-tolerance for a,z in zip(slopes,slopes[1:])):failures.append('negative_discrete_butterfly')
    return sorted(set(failures))

def calculate(p):
    required={'version','symbol','valuation_at','spot','rate','yield','mode','policy','contracts'}
    if type(p) is not dict or set(p)!=required or p['version']!=VERSION:raise ValueError('Exact versioned fields required')
    if p['mode'] not in ('historical_diagnostic','eligible_quote_diagnostic'):raise ValueError('Explicit diagnostic mode required')
    if not isinstance(p['symbol'],str) or not re.fullmatch('[A-Z.]{1,8}',p['symbol']):raise ValueError('Invalid symbol')
    cutoff=stamp(p['valuation_at']);S=num(p['spot'],'spot',1e-8);r=num(p['rate'],'rate',-1,1);q=num(p['yield'],'yield',-1,1)
    pol=p['policy']
    if type(pol) is not dict or set(pol)!={'max_age_seconds','max_skew_seconds','max_relative_spread'}:raise ValueError('Exact quote policy required')
    agecap=num(pol['max_age_seconds'],'age cap',0,86400);skewcap=num(pol['max_skew_seconds'],'skew cap',0,86400);spreadcap=num(pol['max_relative_spread'],'spread cap',0,2)
    if skewcap>agecap:raise ValueError('Quote skew cap must not exceed age cap')
    if not isinstance(p['contracts'],list) or not 1<=len(p['contracts'])<=10000:raise ValueError('One to 10000 contracts required')
    nodes=[];rejected=[];seen=set();quote_times=[]
    fields={'contract_id','expiry_at','strike','bid','ask','quote_at','source_ref'}
    for c in p['contracts']:
        if type(c) is not dict or set(c)!=fields:raise ValueError('Exact contract fields required')
        cid=c['contract_id']
        if not isinstance(cid,str) or cid in seen:raise ValueError('Unique contract id required')
        canonical=parse_contract_id(cid)['canonical_id']
        if canonical in seen:raise ValueError('Duplicate canonical contract id')
        seen.add(canonical);exp=stamp(c['expiry_at']);K=num(c['strike'],'strike',1e-8)
        parsed=parse_contract_id(cid)
        if parsed['root']!=p['symbol'] or parsed['right']!='call' or parsed['expiry']!=exp.date() or parsed['strike']!=Decimal(str(c['strike'])):raise ValueError('Exact canonical call symbol must match expiry/strike')
        if not isinstance(c['source_ref'],str) or not c['source_ref'].strip():raise ValueError('Source reference required')
        bid=num(c['bid'],'bid');ask=num(c['ask'],'ask');T=(exp-cutoff).total_seconds()/(365*86400)
        reason=[];issues=[]
        if T<=0:reason.append('expired')
        if bid<=0 or ask<=0 or ask<bid:reason.append('nonpositive_or_crossed_quote')
        mid=(bid+ask)/2
        if mid>0 and (ask-bid)/mid>spreadcap:reason.append('spread_above_predeclared_limit')
        if c['quote_at'] is None:issues.append('quote_time_unknown')
        else:
            qt=stamp(c['quote_at']);age=(cutoff-qt).total_seconds()
            if age<0:reason.append('future_quote_relative_to_valuation')
            if age>agecap:issues.append('stale_quote')
            quote_times.append(qt)
        if p['mode']=='eligible_quote_diagnostic':reason+=issues
        if reason:rejected.append({'contract_id':cid,'reasons':reason});continue
        try:
            inv=b.iv_interval('call',S,K,T,r,q,bid,ask);vol=b.implied_vol('call',S,K,T,r,q,mid)
            if inv['bid_iv']<=0:raise ValueError('Boundary IV unidentified')
        except (ValueError,OverflowError) as e:
            rejected.append({'contract_id':cid,'reasons':['inversion_failed: '+str(e)]});continue
        F=S*math.exp((r-q)*T)
        nodes.append({'contract_id':cid,'expiry_at':c['expiry_at'],'years':T,'strike':K,'bid':bid,'ask':ask,'mid':mid,'forward':F,'log_moneyness':math.log(K/F),
                      'iv_bid':inv['bid_iv'],'iv_mid':vol,'iv_ask':inv['ask_iv'],'variance_bid':inv['bid_iv']**2*T,'variance_mid':vol**2*T,'variance_ask':inv['ask_iv']**2*T,
                      'quote_issues':issues,'source_ref':c['source_ref'],'model':'European BSM; assumed rate/yield/spot/time'})
    skew=(max(quote_times)-min(quote_times)).total_seconds() if len(quote_times)>1 else 0
    if p['mode']=='eligible_quote_diagnostic' and skew>skewcap:raise ValueError('Cross-contract quote skew above policy')
    slices={}
    for n in nodes:slices.setdefault(n['years'],[]).append(n)
    for rows in slices.values():
        rows.sort(key=lambda x:x['strike'])
        if len({n['strike'] for n in rows})!=len(rows):raise ValueError('Duplicate expiry/strike')
    smilechecks=[];holdouts=[]
    for T,rows in sorted(slices.items()):
        errors=price_checks(rows,math.exp(-r*T))
        smilechecks.append({'years':T,'nodes':len(rows),'midpoint_violations':errors,'meaning':'Midpoint inconsistency is not executable arbitrage; bid/ask and exercise may explain it.'})
        for i,n in enumerate(rows[1:-1],1):
            other=rows[:i]+rows[i+1:];var=surface({T:other},T,n['log_moneyness']);iv=math.sqrt(var/T)
            pred=b.bsm('call',S,n['strike'],T,r,q,iv)['price']
            holdouts.append({'contract_id':n['contract_id'],'predicted_iv':iv,'mid_iv_error_points':100*(iv-n['iv_mid']),'predicted_price':pred,'mid_price_error':pred-n['mid'],'within_displayed_bid_ask':n['bid']-1e-8<=pred<=n['ask']+1e-8})
    calendar=[];times=sorted(slices)
    for t1,t2 in zip(times,times[1:]):
        lo=max(slices[t1][0]['log_moneyness'],slices[t2][0]['log_moneyness']);hi=min(slices[t1][-1]['log_moneyness'],slices[t2][-1]['log_moneyness'])
        if lo>=hi:calendar.append({'from':t1,'to':t2,'status':'no_common_support'});continue
        grid=[hi if i==100 else lo+(hi-lo)*i/100 for i in range(101)]
        mins=min(surface(slices,t2,k)-surface(slices,t1,k) for k in grid)
        calendar.append({'from':t1,'to':t2,'samples':101,'minimum_total_variance_change':mins,'status':'sampled_violation' if mins< -1e-10 else 'sampled_pass'})
    # Piecewise variance can create local butterflies even when original nodes look valid.
    dense=[]
    testtimes=sorted(set(times+[(a+z)/2 for a,z in zip(times,times[1:])]))
    for T in testtimes:
        relevant=[T] if T in slices else [max(t for t in times if t<T),min(t for t in times if t>T)]
        lo=max(slices[t][0]['log_moneyness'] for t in relevant);hi=min(slices[t][-1]['log_moneyness'] for t in relevant)
        if lo>=hi:continue
        F=S*math.exp((r-q)*T);rr=[]
        for i in range(201):
            k=hi if i==200 else lo+(hi-lo)*i/200;K=F*math.exp(k);iv=math.sqrt(surface(slices,T,k)/T)
            rr.append({'strike':K,'mid':b.bsm('call',S,K,T,r,q,iv)['price']})
        dense.append({'years':T,'samples':201,'violations':price_checks(rr,math.exp(-r*T),1e-7)})
    raw=json.dumps(p,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return {'version':VERSION,'input_sha256':hashlib.sha256(raw).hexdigest(),'status':'historical_assumption_surface' if p['mode']=='historical_diagnostic' else 'eligible_quote_european_diagnostic',
            'nodes':nodes,'rejected':rejected,'coverage':{'input':len(p['contracts']),'numeric_nodes':len(nodes),'rejected':len(rejected)},'quote_skew_seconds_if_known':skew,'unknown_quote_times':sum(c['quote_at'] is None for c in p['contracts']),
            'smile_checks':smilechecks,'calendar_checks':calendar,'sampled_interpolated_strike_checks':dense,'interior_strike_holdouts':holdouts,
            'holdout_summary':{'count':len(holdouts),'mae_premium':sum(abs(z['mid_price_error']) for z in holdouts)/len(holdouts) if holdouts else None,'within_bid_ask_count':sum(z['within_displayed_bid_ask'] for z in holdouts)},
            'arbitrage_free_certified':False,'executable':False,'forecast_probability':None,
            'surface_valuation_approved':False,'static_diagnostic_pass':bool(nodes) and not rejected and all(not x['midpoint_violations'] for x in smilechecks) and all(x.get('status')=='sampled_pass' for x in calendar) and all(not x['violations'] for x in dense),
            'approved_use':'historical quote diagnostics and explicitly assumed sensitivity illustrations only','limitation':LIMITATION}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    try:out=calculate(b.decode_packet(Path(a.input).read_bytes()));code=0
    except (ValueError,TypeError,KeyError,OverflowError,OSError) as e:out={'status':'rejected','error':str(e),'version':VERSION};code=2
    Path(a.output).write_text(json.dumps(out,indent=2,allow_nan=False)+'\n');print(json.dumps({k:v for k,v in out.items() if k in ('status','coverage','error')}));return code
if __name__=='__main__':raise SystemExit(main())
