#!/usr/bin/env python3
"""Offline paired evaluation of a frozen research-harness candidate.

Reads saved observations; never launches a model, executes candidate code or edits
production. JSONL metrics come from hash-bound verifiers, not a candidate's score.
"""
import argparse
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import math

VERSION='2026-10-24-offline-promotion-1'


def fail(s): raise ValueError(s)
def text(s):
    if not isinstance(s,str) or not s.strip(): fail('nonempty text required')
    return s

def stamp(s):
    try:d=datetime.fromisoformat(text(s).replace('Z','+00:00'))
    except ValueError:fail('invalid timestamp')
    if d.utcoffset() is None:fail('timezone required')
    return d

def decode(raw):
    def pairs(items):
        d={}
        for k,v in items:
            if k in d:fail('duplicate JSON key')
            d[k]=v
        return d
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda x:fail('nonfinite JSON'))

def hashjson(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def hashfile(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def finite(v):
    if isinstance(v,bool):fail('invalid numeric boolean')
    try:f=float(v)
    except (ValueError,TypeError):fail('invalid number')
    if not math.isfinite(f) or f<0 or (f==0 and Decimal(str(v))!=0):fail('nonfinite/negative/out-of-range metric')
    return f


def evaluate(manifest,rows,*,base_dir=None,expected_manifest_sha256):
    if hashjson(manifest) != expected_manifest_sha256: fail('manifest differs from independent frozen hash')
    if manifest.get('version')!=1 or type(manifest['version'])is not int:fail('integer version1 required')
    root=Path(base_dir or '.').resolve();frozen=stamp(manifest['frozen_at']);selected=stamp(manifest['candidate_selected_at'])
    if selected<frozen:fail('candidate selected before experiment freeze')
    if manifest['domain'] not in {'functional','research_quality','forecast_outcomes'}:fail('explicit domain required')
    text(manifest['protocol_id']);text(manifest['metric_definition']);text(manifest['independent_owner'])
    if manifest.get('holdout_exposures')!=1 or type(manifest['holdout_exposures'])is not int:fail('holdout opened repeatedly; need new sealed set')
    budget=manifest['max_trials']
    if type(budget)is not int or not 1<=budget<=100:fail('bounded1..100 trials required')
    artifacts={}
    for a in manifest['artifacts']:
        aid=text(a['id']);p=(root/text(a['path'])).resolve()
        if aid in artifacts or not p.is_file() or hashfile(p)!=a['sha256']:fail('artifact absent/stale/duplicate')
        artifacts[aid]=(p,a['sha256'])
    def actual(ref):
        if ref not in artifacts:fail('unregistered artifact')
        return artifacts[ref]
    baseline=actual(manifest['baseline_artifact_id'])[1];candidate=actual(manifest['candidate_artifact_id'])[1]
    if baseline==candidate:fail('unchanged candidate cannot claim improvement')
    cases={};splits={s:[] for s in ('train','dev','holdout')}
    for c in manifest['cases']:
        cid=text(c['id']);sp=c['split']
        if cid in cases or sp not in splits:fail('duplicate case or unknown split')
        origin=stamp(c['origin']);end=stamp(c['target_end'])
        if end<origin or stamp(c['source_available_at'])>origin:fail('lookahead or invalid horizon')
        actual(c['source_artifact_id']);text(c['expected_verifier'])
        cases[cid]=c;splits[sp].append(c)
    if any(not v for v in splits.values()):fail('train/dev/sealed holdout all required')
    for first,second in [('train','dev'),('dev','holdout')]:
        if max(stamp(c['target_end'])for c in splits[first])>=min(stamp(c['origin'])for c in splits[second]):fail('chronological split overlap')
    trials=set();pairs={};tested=set()
    for row in rows:
        trial=text(row['trial_id']);trials.add(trial)
        if len(trials)>budget:fail('trial budget exceeded')
        cid=row['case_id'];role=row['role']
        if cid not in cases or role not in {'baseline','candidate'}:fail('unexpected case/role')
        c=cases[cid];at=stamp(row['evaluated_at'])
        if at<frozen or at<stamp(c['target_end']):fail('evaluation before freeze or outcome matured')
        expected=baseline if role=='baseline' else candidate
        if row['variant_sha256']!=expected:fail('wrong candidate/baseline hash')
        if row['source_sha256']!=actual(c['source_artifact_id'])[1]:fail('source vintage differs')
        if c['split']=='holdout':
            if at<selected:fail('holdout evaluated before candidate selected')
            tested.add(trial)
        key=(cid,role)
        if key in pairs:fail('duplicate observation; immutable case metric required')
        p,_=actual(row['verifier_artifact_id']);v=decode(p.read_text())
        if v['case_id']!=cid or v['variant_sha256']!=expected or v['source_sha256']!=row['source_sha256']:fail('verifier identity mismatch')
        if v['trial_id']!=trial or stamp(v['evaluated_at'])!=at: fail('trial/time differs from hash-bound verifier')
        if v['verifier_id']!=c['expected_verifier'] or v['method'] not in {'deterministic','independently_verified'}:fail('candidate/self-LLM judge alone not admitted')
        if type(v['passed'])is not bool or type(v['complete'])is not bool:fail('boolean verifier outcomes required')
        if not isinstance(v['critical_errors'],list):fail('critical error list required')
        for error in v['critical_errors']:text(error)
        if finite(row['cost_usd']) != finite(v['cost_usd']) or finite(row['elapsed_seconds']) != finite(v['elapsed_seconds']): fail('cost/time differs from hash-bound verifier measurement')
        pairs[key]={'passed':v['passed'],'complete':v['complete'],'critical_errors':v['critical_errors'],
                    'cost_usd':finite(row['cost_usd']),'elapsed_seconds':finite(row['elapsed_seconds']),
                    'verifier_sha256':hashfile(p)}
    if len(tested)!=1:fail('one sealed holdout trial only')
    expected={(cid,role)for cid in cases for role in ('baseline','candidate')}
    if set(pairs)!=expected:fail('incomplete paired full roster coverage')
    summaries={}
    for sp,items in splits.items():
        out={}
        for role in ('baseline','candidate'):
            result=[pairs[(c['id'],role)]for c in items]
            out[role]={'expected':len(items),'passed':sum(r['passed']for r in result),'complete':sum(r['complete']for r in result),
                       'critical_errors':sum(len(r['critical_errors'])for r in result),
                       'cost_usd':finite(sum(r['cost_usd']for r in result)),'elapsed_seconds':finite(sum(r['elapsed_seconds']for r in result))}
        summaries[sp]=out
    reasons=[]
    for sp,out in summaries.items():
        b,c=out['baseline'],out['candidate']
        if c['critical_errors']:reasons.append(sp+':critical_error_veto')
        if c['complete']!=c['expected']:reasons.append(sp+':incomplete_candidate')
        if any(pairs[(case['id'],'baseline')]['passed'] and not pairs[(case['id'],'candidate')]['passed']for case in splits[sp]):reasons.append(sp+':paired_regression')
        if c['passed']<b['passed']:reasons.append(sp+':pass_count_regression')
    h=summaries['holdout'];b,c=h['baseline'],h['candidate']
    quality_gain=c['passed']>b['passed']
    equal_quality=c['passed']==b['passed']
    cost_gain=c['cost_usd']<b['cost_usd'] and c['elapsed_seconds']<=b['elapsed_seconds']
    if not(quality_gain or (equal_quality and cost_gain)):reasons.append('no_predeclared_holdout_quality_or_cost_gain')
    return {'version':VERSION,'protocol_id':manifest['protocol_id'],'manifest_sha256':hashjson(manifest),
            'observations_sha256':hashjson(rows),'domain':manifest['domain'],'trials':len(trials),
            'summary':summaries,'candidate_status':'reject'if reasons else'eligible_for_independent_offline_review',
            'reasons':reasons,'auto_promoted':False,
            'limitations':['Hash-bound verifiers and timestamps do not authenticate source meaning or truly sealed access.',
                           'Author-independent review must inspect task construction, rubric, failed cases and leakage.',
                           'Functional gains are not research alpha; research-quality gains are not realized investment returns.',
                           'One sealed evaluation and small samples give descriptive results, not calibrated significance.']}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--manifest',required=True);ap.add_argument('--observations',required=True);ap.add_argument('--output',required=True);ap.add_argument('--expected-manifest-sha256',required=True)
    a=ap.parse_args();p=Path(a.manifest)
    rows=[decode(line)for line in Path(a.observations).read_text().splitlines()if line.strip()]
    result=evaluate(decode(p.read_text()),rows,base_dir=p.parent,expected_manifest_sha256=a.expected_manifest_sha256)
    Path(a.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')

if __name__=='__main__':main()
