#!/usr/bin/env python3
"""Discrete, supplied-scenario entry comparison. Not a price simulator/backtest."""
import argparse
import json
import math
from pathlib import Path

VERSION = '2026-10-23-entry-policy-1'

def finite(x, name, lower=None):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError(name + ' must be a finite number')
    if lower is not None and x < lower:
        raise ValueError(name + ' below lower bound')
    return x

def validate(d):
    budget = finite(d['budget'], 'budget', 0)
    horizon = finite(d['horizon_years'], 'horizon', 0)
    rate = finite(d['cash_rate'], 'cash_rate')
    fee = finite(d['fee_fraction'], 'fee_fraction', 0)
    if budget <= 0 or horizon <= 0 or rate <= -1 or fee >= 1:
        raise ValueError('Invalid budget/horizon/cash rate/fee')
    if d.get('price_basis') != 'split_adjusted_price_only':
        raise ValueError('Separate price-only observations and cash dividends required')
    if d.get('invalidation_action') not in ('liquidate', 'hold_no_new'):
        raise ValueError('Explicit invalidation action required')
    ps = d['policies']; ss = d['scenarios']
    if not ps or not ss or {p['kind'] for p in ps} != {'now','staged','wait'}:
        raise ValueError('Compare now, staged and wait policies on same scenarios')
    if len({p['id'] for p in ps}) != len(ps) or len({s['id'] for s in ss}) != len(ss):
        raise ValueError('Unique policy and scenario IDs required')
    for p in ps:
        fraction = finite(p['starter_fraction'], 'starter_fraction', 0)
        if fraction > 1 or (p['kind']=='now' and fraction!=1) or (p['kind']=='wait' and fraction!=0) or (p['kind']=='staged' and not 0<fraction<1):
            raise ValueError('Starter fraction inconsistent with policy')
        if p['kind'] != 'now' and finite(p['limit_price'],'limit_price',0)<=0:
            raise ValueError('Positive limit required')
    basis=d['probability_basis']
    if basis not in ('unknown','judgment','calibrated'):
        raise ValueError('Explicit probability basis required')
    if basis=='calibrated' and not d.get('calibration_evidence'):
        raise ValueError('Calibration evidence required; tool does not authenticate it')
    if basis=='unknown':
        if any('probability' in s for s in ss): raise ValueError('Unknown probabilities must omit weights')
    elif abs(sum(finite(s['probability'],'probability',0) for s in ss)-1)>1e-10:
        raise ValueError('Probabilities must sum to one')
    initial_prices=[]
    for s in ss:
        obs=s['observations']
        if len(obs)<2 or obs[0]['time_years']!=0 or obs[-1]['time_years']!=horizon:
            raise ValueError('All paths need common start and horizon observations')
        times=[]
        for o in obs:
            times.append(finite(o['time_years'],'time',0))
            finite(o['price'],'price',0); finite(o['dividend_per_share'],'dividend',0)
            if type(o['invalidated']) is not bool: raise ValueError('Invalidation must be boolean')
        if any(b<=a for a,b in zip(times,times[1:])): raise ValueError('Strictly increasing observations required')
        if obs[0]['price']<=0 or obs[0]['dividend_per_share']!=0 or obs[0]['invalidated']:
            raise ValueError('Positive valid common current state required')
        initial_prices.append(obs[0]['price'])
    if len(set(initial_prices))!=1: raise ValueError('Scenarios must share current observed price')

def payoff(d, policy, scenario):
    cash=d['budget']; shares=0.; prev=0.; spent=0.; filled=False; invalid=False; events=[]
    for i,o in enumerate(scenario['observations']):
        t=o['time_years']; cash*=(1+d['cash_rate'])**(t-prev); prev=t
        dividend=shares*o['dividend_per_share']; cash+=dividend
        invalid=invalid or o['invalidated']
        event={'time_years':t,'cash_dividend':dividend,'bought_shares':0.,'sold_shares':0.}
        if invalid and d['invalidation_action']=='liquidate' and shares:
            event['sold_shares']=shares;cash+=shares*o['price']*(1-d['fee_fraction']);shares=0.
        # At terminal observation only value/receive distributions: no meaningless new entry.
        if not invalid and t<d['horizon_years']:
            allocation=policy['starter_fraction'] if i==0 else 0.
            if policy['kind']!='now' and not filled and o['price']>0 and o['price']<=policy['limit_price']:
                allocation+=1-policy['starter_fraction'];filled=True
            desired=d['budget']*allocation
            # Fixed original-budget tranche; any cash shortfall reduces fill, never borrows.
            amount=min(cash,desired)
            if amount>0 and o['price']>0:
                buy=amount/(o['price']*(1+d['fee_fraction']));shares+=buy;cash-=amount;spent+=amount
                event['bought_shares']=buy
        event.update(cash=cash,shares=shares,invalidated=invalid);events.append(event)
    equity=shares*scenario['observations'][-1]['price']*(1-d['fee_fraction'])
    wealth=cash+equity
    return {'terminal_wealth':wealth,'total_return':wealth/d['budget']-1,'cash':cash,'liquidation_equity':equity,'original_budget_spent':spent,'remainder_triggered':filled,'remainder_filled':filled and math.isclose(spent,d['budget'],rel_tol=1e-10),'events':events}

def compare(d):
    validate(d)
    matrix={s['id']:{p['id']:payoff(d,p,s) for p in d['policies']} for s in d['scenarios']}
    summaries={}
    for p in d['policies']:
        pid=p['id'];values=[matrix[s['id']][pid]['terminal_wealth'] for s in d['scenarios']]
        v={'wealth_bounds_over_supplied_scenarios':[min(values),max(values)],'worst_regret':max(max(v['terminal_wealth'] for v in matrix[s['id']].values())-matrix[s['id']][pid]['terminal_wealth'] for s in d['scenarios'])}
        if d['probability_basis']!='unknown':
            v['expected_terminal_wealth']=sum(s['probability']*matrix[s['id']][pid]['terminal_wealth'] for s in d['scenarios'])
            v['loss_probability']=sum(s['probability'] for s in d['scenarios'] if matrix[s['id']][pid]['terminal_wealth']<d['budget'])
        summaries[pid]=v
    pairs=[]
    for i,a in enumerate(d['policies']):
        for b in d['policies'][i+1:]:
            diffs=[matrix[s['id']][a['id']]['terminal_wealth']-matrix[s['id']][b['id']]['terminal_wealth'] for s in d['scenarios']]
            x={'a':a['id'],'b':b['id'],'paired_wealth_difference_bounds':[min(diffs),max(diffs)],'a_weakly_dominates_supplied_scenarios':min(diffs)>=0,'a_strictly_better_in_some':max(diffs)>0}
            if d['probability_basis']!='unknown': x['expected_difference']=sum(s['probability']*v for s,v in zip(d['scenarios'],diffs))
            if len(diffs)==2 and diffs[0]!=diffs[1]:
                q=-diffs[1]/(diffs[0]-diffs[1]);x['break_even_first_scenario_probability']=q if 0<=q<=1 else None
            pairs.append(x)
    return {'version':VERSION,'probability_basis':d['probability_basis'],'horizon_years':d['horizon_years'],'budget':d['budget'],'policies':summaries,'paired_comparisons':pairs,'scenarios':matrix,'limitations':['Supplied discrete paths only; not calibrated by this tool or proof of executable historical fills.','No intraperiod ordering inferred; dividends credited before same-observation purchases.','Scenario bounds and loss probabilities depend on coverage; not worst possible losses.','Terminal wealth includes liquidation fees; taxes must be embedded consistently in inputs/costs or separately audited.']}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    result=compare(json.loads(a.input.read_text()));a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'version':VERSION,'policies':result['policies'],'paired_comparisons':result['paired_comparisons']}))

if __name__=='__main__':main()
