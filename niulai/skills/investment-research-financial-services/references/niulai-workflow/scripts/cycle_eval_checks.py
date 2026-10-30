#!/usr/bin/env python3
"""Small frozen-origin forecast evaluation; no cycle classifier or alpha certificate.

Use the adjacent test's example_packet(). Reuses vintage selection and the existing
proper-score implementation. One series/unit/forecast functional per packet.
Candidate forecasts are supplied frozen observations, not fitted by this helper.
"""
import argparse
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import sys

import cycle_vintage_checks as vintage
import rationale_guard as rationale

VERSION = '2026-10-24-cycle-evaluation-1'


class EvaluationError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise EvaluationError(message)


def obj(value, keys, label):
    require(type(value) is dict and set(value) == set(keys), label + ': exact fields required')


def rows(value, label, minimum=0):
    require(type(value) is list and minimum <= len(value) <= 10000, label + ': bounded list required')
    return value


def text(value):
    require(type(value) is str and value.strip() == value and bool(value) and len(value) <= 2048,
            'bounded nonempty text required')
    return value


def number(value):
    try:
        return Decimal(vintage._value(value))
    except (ValueError, TypeError) as exc:
        raise EvaluationError('finite decimal string required') from exc


def stamp(value):
    try:
        return vintage._time(value)
    except (ValueError, TypeError) as exc:
        raise EvaluationError('timezone-aware timestamp required') from exc


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def decode_packet(raw):
    return vintage.decode_packet(raw)


def calculate(packet):
    obj(packet, ('version','cohort_id','declared_at','as_of','series_id','unit','functional',
                 'minimum_training_periods','minimum_paired_cases','methods','expected_cases','cases'), 'packet')
    require(packet['version'] == VERSION, 'unsupported version')
    for k in ('cohort_id','series_id','unit'):text(packet[k])
    require(packet['functional'] in ('mean','median'), 'mean or median functional required')
    declared, now = stamp(packet['declared_at']), stamp(packet['as_of'])
    require(declared <= now, 'declaration after evaluation')
    for k in ('minimum_training_periods','minimum_paired_cases'):
        require(type(packet[k]) is int and 1 <= packet[k] <= 10000, k + ': positive bounded integer required')
    methods = {}
    for m in rows(packet['methods'], 'methods', 1):
        obj(m, ('id','specification_sha256','declared_at'), 'method')
        mid=text(m['id']);require(mid not in methods,'duplicate method')
        require(type(m['specification_sha256']) is str and len(m['specification_sha256'])==64 and
                all(c in '0123456789abcdef' for c in m['specification_sha256']), 'method hash required')
        require(stamp(m['declared_at']) <= declared, 'method must be predeclared with cohort')
        methods[mid]=m
    expected={}
    for e in rows(packet['expected_cases'],'expected_cases',1):
        obj(e, ('id','member_id','origin','target_period'), 'expected case')
        cid=text(e['id']);text(e['member_id']);require(cid not in expected,'duplicate expected case')
        origin=stamp(e['origin']);require(declared <= origin <= now,'origin outside frozen declaration/evaluation interval')
        obj(e['target_period'],('start','end'),'target period')
        a,b=(vintage._date(e['target_period'][k]) for k in ('start','end'))
        require(a<=b and a>origin.date(),'target must be strictly after decision date')
        expected[cid]=e
    cases={}
    for c in rows(packet['cases'],'cases',1):
        obj(c, ('id','training','candidate','abstention_reason','resolve_after','outcome',
                'candidate_cost_usd','baseline_cost_usd'), 'case')
        cid=text(c['id']);require(cid not in cases,'duplicate case');cases[cid]=c
    require(set(cases)==set(expected),'cases must exactly cover frozen expected roster')
    # Multiple observations from one entity are not independent. For this small
    # evaluator require nonoverlapping horizons; do not pretend to estimate SEs.
    prior={}; details=[]
    for e in sorted(expected.values(),key=lambda x:(stamp(x['origin']),x['id'])):
        member=e['member_id'];origin=stamp(e['origin']);cid=e['id'];c=cases[cid]
        resolution=stamp(c['resolve_after'])
        require(resolution.date() >= vintage._date(e['target_period']['end']), 'resolution precedes target period end')
        if member in prior:
            require(origin > prior[member], 'overlapping or unordered evaluation horizons for member')
        prior[member]=resolution
        tr=c['training'];require(type(tr) is dict,'training vintage packet required')
        require(stamp(tr.get('as_of'))==origin,'training snapshot cutoff must equal origin')
        require(tr.get('subject')==member,'training subject differs from frozen member')
        selected=vintage.calculate(tr)
        histories=[]
        for item in selected['selected_view']['rows']:
            require(item['series_id']==packet['series_id'] and item['unit']==packet['unit'], 'mixed series or units')
            require(vintage._date(item['period']['end']) <= origin.date(),'future declared training period')
            if item['status']=='selected':
                require(vintage._date(item['period']['end']) <= origin.date(),'future training period')
                histories.append(item)
        histories.sort(key=lambda x:(x['period']['end'],x['period']['start']))
        for previous,current in zip(histories,histories[1:]):
            require(previous['period']['end'] < current['period']['start'],'overlapping training periods')
        baseline=number(histories[-1]['observation']['value']) if histories else None
        candidate=c['candidate'];costs={}
        for key in ('candidate_cost_usd','baseline_cost_usd'):
            costs[key]=number(c[key]);require(costs[key]>=0,'negative computation cost')
        if candidate is None:
            text(c['abstention_reason']);prediction=None;mid=None
        else:
            obj(candidate,('method_id','prediction','issued_at','fit_cutoff','training_view_sha256'), 'candidate')
            mid=candidate['method_id'];require(mid in methods,'unregistered candidate method')
            issued,fit=stamp(candidate['issued_at']),stamp(candidate['fit_cutoff'])
            require(fit <= issued and declared <= issued <= origin,'fit/issue time leaks beyond origin or issue precedes declared protocol')
            require(all(stamp(x['observation']['available_at'])<=fit for x in histories),'training release unavailable at fit cutoff')
            require(candidate['training_view_sha256']==selected['selected_view_sha256'],'wrong/stale training vintage hash')
            prediction=number(candidate['prediction'])
            require(c['abstention_reason'] is None,'nonabstention must not contain abstention reason')
        outcome=c['outcome'];actual=None;category='unknown';source=None
        if outcome is not None:
            obj(outcome,('value','available_at','source_ref','category'),'outcome')
            actual=number(outcome['value']);source=text(outcome['source_ref'])
            require(outcome['category'] in ('success','niche','failure','other'),'unsupported outcome category')
            require(resolution <= stamp(outcome['available_at']) <= now, 'outcome premature or unavailable as of evaluation')
            category=outcome['category']
        status=('abstained' if prediction is None else 'insufficient_training' if len(histories)<packet['minimum_training_periods']
                else 'pending' if now<resolution else 'missing_outcome' if outcome is None else 'scored')
        frozen={'id':cid,'member_id':member,'origin':e['origin'],'target_period':e['target_period'],
                'method_id':mid,'method_specification_sha256':methods[mid]['specification_sha256'] if mid else None,
                'training_view_sha256':selected['selected_view_sha256'],'candidate_prediction':str(prediction) if prediction is not None else None,
                'naive_prediction':str(baseline) if baseline is not None else None}
        row={**frozen,'frozen_decision_sha256':digest(frozen),'status':status,'outcome_category':category,
             'training_periods':len(histories),'missing_training_periods':selected['coverage']['missing_as_of'],
             **{k:str(val) for k,val in costs.items()},'candidate_loss':None,'baseline_loss':None}
        if status=='scored':
            card={'version':rationale.VERSION,'cohort_id':packet['cohort_id'],'thesis_family':'cycle_shadow',
                  'origin':e['origin'],'forecasts':[{'id':label,'kind':packet['functional'],
                    'prediction':float(pred),'units':packet['unit'],'period':e['target_period'],
                    'resolve_after':c['resolve_after']} for label,pred in [('candidate',prediction),('naive',baseline)]]}
            h=digest(card)
            out={'card_sha256':h,'observations':[{'forecast_id':label,'actual':float(actual),
                'units':packet['unit'],'period':e['target_period'],'available_at':outcome['available_at'],'source':source}
                for label in ('candidate','naive')]}
            scored=rationale.score(card,out,as_of=packet['as_of'],card_sha256=h)
            metric='squared_error' if packet['functional']=='mean' else 'absolute_error'
            row.update(candidate_loss=scored['items'][0][metric],baseline_loss=scored['items'][1][metric])
        details.append(row)
    require(len({x['method_id'] for x in details if x['method_id'] is not None})<=1, 'evaluate one frozen candidate protocol per packet; do not pool winning variants')
    scored=[x for x in details if x['status']=='scored']; n=len(scored)
    loss=lambda name:sum(x[name] for x in scored)/n if n else None
    counts={key:sum(x['status']==key for x in details) for key in ('scored','abstained','pending','missing_outcome','insufficient_training')}
    categories={key:sum(x['outcome_category']==key for x in details) for key in ('success','niche','failure','other','unknown')}
    with localcontext() as context:
        context.prec=100
        total_costs={k:str(sum((Decimal(x[k]) for x in details),Decimal(0))) for k in ('candidate_cost_usd','baseline_cost_usd')}
    return {'version':VERSION,'input_sha256':digest(packet),'cohort_id':packet['cohort_id'],
        'status':'descriptive_only' if n>=packet['minimum_paired_cases'] else 'insufficient_history',
        'coverage':{'expected':len(expected),**counts,'outcome_categories':categories,'distinct_members':len(prior)},
        'comparison':{'functional':packet['functional'],'unit':packet['unit'],'paired_cases':n,
            'candidate_mean_loss':loss('candidate_loss'),'naive_mean_loss':loss('baseline_loss'),
            'candidate_better_on_paired_sample':loss('candidate_loss')<loss('baseline_loss') if n else None,
            'costs_usd_all_cases':total_costs,
            'costs_are_computation_not_trading_returns':True},
        'methods_declared':list(methods),'items':details,'automatic_promotion':False,'predictive_skill_certified':False,
        'limitations':['Frozen supplied metadata are not authenticated; review cohort coverage and all tried variants.',
          'Descriptive matched-case forecast losses only; no trading P&L, independent-wave count, uncertainty interval or causal proof.',
          'Abstentions and missing outcomes remain in the denominator; paired-only improvement can reflect selection.',
          'Naive last available value is a benchmark, not a claim of the best possible baseline.']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True);p.add_argument('--output',required=True)
    a=p.parse_args()
    try: result=calculate(decode_packet(Path(a.input).read_bytes()))
    except (ValueError,TypeError,KeyError,OverflowError) as exc:
        result={'version':VERSION,'status':'rejected','error':str(exc),'predictive_skill_certified':False}
        Path(a.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));return 2
    Path(a.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
