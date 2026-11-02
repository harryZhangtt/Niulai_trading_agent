#!/usr/bin/env python3
"""Deterministic assumption-bound expiry debit limits; not forecasting or order routing.

Uses existing normalized payoff packet. Declared terminal-price probability
intervals are assumptions, not estimated/calibrated probabilities. Greedy mass
allocation finds the exact optimizer of this bounded probability-simplex linear problem.
Reported decimal quotients have finite precision; this does not calibrate inputs.
"""
import argparse,copy,hashlib,json
from decimal import Decimal,localcontext
from pathlib import Path
from options_payoff_checks import calculate as payoff,decode_packet,number,obj,out,text,count
VERSION='2026-10-24-decision-bounds-1'

def expectation_bounds(values,lower,upper):
    with localcontext() as ctx:
        ctx.prec=256
        return _expectation_bounds(values,lower,upper)

def _expectation_bounds(values,lower,upper):
    if not values or not len(values)==len(lower)==len(upper):raise ValueError('interval vector shape')
    for x in [*values,*lower,*upper]:
        if not isinstance(x,Decimal) or not x.is_finite() or len(x.as_tuple().digits)>160:raise ValueError('bounded finite Decimal inputs required')
    if any(l<0 or h>1 or l>h for l,h in zip(lower,upper)) or sum(lower)>1 or sum(upper)<1:raise ValueError('infeasible probability bounds')
    def extremum(reverse):
        weights=list(lower);remaining=Decimal(1)-sum(weights)
        for i in sorted(range(len(values)),key=lambda i:values[i],reverse=reverse):
            add=min(upper[i]-weights[i],remaining);weights[i]+=add;remaining-=add
        if remaining:raise ValueError('unallocated probability')
        return sum(v*w for v,w in zip(values,weights)),weights
    lo,lw=extremum(False);hi,hw=extremum(True)
    return lo,hi,lw,hw

def calculate(packet):
    with localcontext() as ctx:
        ctx.prec=256
        return _calculate(packet)

def _calculate(packet):
    obj(packet,'$',('version','payoff_packet','valuation_horizon','contracts','scenarios','horizon_return_hurdle','closing_fee_reserve','model_error_reserve','assumption_source_refs'))
    if packet['version']!=VERSION:raise ValueError('unsupported version')
    refs=packet['assumption_source_refs']
    if not isinstance(refs,list) or not refs:raise ValueError('reviewable assumption sources required')
    for r in refs:text(r,'$.assumption_source_refs')
    n=count(packet['contracts'],'$.contracts',1,100000)
    hurdle=number(packet['horizon_return_hurdle'],'$.horizon_return_hurdle')
    close=number(packet['closing_fee_reserve'],'$.closing_fee_reserve');reserve=number(packet['model_error_reserve'],'$.model_error_reserve')
    scenarios=packet['scenarios']
    if not isinstance(scenarios,list) or not 1<=len(scenarios)<=50000:raise ValueError('1..50000 scenarios required')
    prices=[];lo=[];hi=[];ids=[]
    for row in scenarios:
        obj(row,'$.scenarios',('id','expiry_stock_price','probability_lower','probability_upper'))
        ids.append(text(row['id'],'$.scenarios.id'));prices.append(number(row['expiry_stock_price'],'$.scenarios.expiry_stock_price'))
        lo.append(number(row['probability_lower'],'$.scenarios.probability_lower'));hi.append(number(row['probability_upper'],'$.scenarios.probability_upper'))
    if len(set(ids))!=len(ids):raise ValueError('duplicate scenario id')
    p=copy.deepcopy(packet['payoff_packet']);base=payoff(p)
    if packet['valuation_horizon'] != base['expiry']:raise ValueError('expiry-only model requires valuation_horizon equal exact contract expiry')
    long=p['strategy']['long_leg'];short=p['strategy']['short_leg'];k=Decimal(long['strike']);h=None if short is None else Decimal(short['strike'])
    vals=[100*n*(max(s-k,Decimal(0))-(max(s-h,Decimal(0)) if h is not None else 0)) for s in prices]
    mn,mx,lw,hw=expectation_bounds(vals,lo,hi)
    legs=1 if short is None else 2;fees=p['fees'];opening=legs*(n*Decimal(fees['option_per_contract_per_leg'])+Decimal(fees['option_fixed_per_leg']))
    current=Decimal(base['conservative_debit_per_share'])*100*n;b=Decimal(p['budget']['amount'])
    floor=(mn-close-reserve)/(1+hurdle)-opening;ceiling=(mx-close-reserve)/(1+hurdle)-opening;feasible=min(floor,b-opening)
    breakeven=k+(current+opening+close)/(100*n)
    if h is not None and current+opening+close>100*n*(h-k):breakeven=None
    longcash=100*n*k
    return {'version':VERSION,'status':'conditional_bound_not_trade_approval','probability_basis':'user_supplied_intervals_not_calibrated',
      'payoff_input_sha256':base['input_sha256'],'input_sha256':hashlib.sha256(json.dumps(packet,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),
      'contracts':n,'valuation_horizon':base['expiry'],'horizon_return_hurdle':out(hurdle),'opening_fees':out(opening),'current_premium_debit':out(current),'opening_cash':out(current+opening),
      'budget_cash_only_affordable':current+opening<=b,'expected_intrinsic_cash_bounds':[out(mn),out(mx)],
      'net_pnl_bounds_after_reserves':[out(mn-current-opening-close-reserve),out(mx-current-opening-close-reserve)],
      'max_premium_debit_for_hurdle_bounds':[out(floor),out(ceiling)],'budget_capped_worst_case_limit':None if feasible<=0 else out(feasible),
      'budget_capped_limit_per_share':None if feasible<=0 else out(feasible/(100*n)),'current_debit_meets_worst_case_hurdle':current<=feasible,
      'net_expiry_breakeven_stock_price':None if breakeven is None else out(breakeven),
      'extremal_assumption_weights':{'minimum':dict(zip(ids,map(out,lw))),'maximum':dict(zip(ids,map(out,hw)))},
      'funding':{'long_exercise_purchase_cash':out(longcash),'long_exercise_exceeds_budget':longcash>b,'short_assignment_delivery_shares':100*n if short else 0,
          'short_assignment_strike_proceeds':out(100*n*h) if h else '0','automatic_netting_assumed':False,'margin_requirement':None,
          'margin_reason':'Broker/account/borrow terms and timing required; strike proceeds are not a margin estimate.'},
      'limits':['Bounds apply only to declared scenario support and probability intervals, not all possible futures.',
          'No continuous-time mark, calibrated probability, fill assurance, or margin/assignment model.',
          'Close-fee/model-error reserves are assumptions. Negative cap means no positive premium satisfies that assumption set.',
          'Budget affordability is not market depth, exercise funding, broker approval or trade suitability.'],
      'underlying_payoff_warnings':base['warnings']}

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--input',required=True);a.add_argument('--output',required=True);args=a.parse_args()
    result=calculate(decode_packet(Path(args.input).read_bytes()));Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':main()
