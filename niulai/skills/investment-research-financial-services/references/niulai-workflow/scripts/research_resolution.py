#!/usr/bin/env python3
"""Bounded research-gap ledger, decision sensitivity and information-value arithmetic.

No LLM, network, scheduler, broker or source-authenticity claim. Utilities must use
one common currency/horizon/budget. EVPI is conditional on supplied probabilities,
not a prediction of alpha or the value of a proposed experiment.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
from fractions import Fraction
import json
import math
from pathlib import Path

VERSION = '2026-10-24-active-resolution-1'
STATUSES = {'open', 'resolved', 'assumption_bound', 'external_blocker', 'research_wait'}


def fail(message):
    raise ValueError(message)


def text(value):
    if not isinstance(value, str) or not value.strip():
        fail('nonempty text required')
    return value


def number(value):
    if isinstance(value, bool): fail('boolean is not a number')
    try: result = Decimal(str(value))
    except InvalidOperation: fail('invalid number')
    if not result.is_finite() or not math.isfinite(float(result)) or (result and float(result)==0): fail('nonfinite or out-of-range number')
    return result


def outnum(value):
    f=float(value)
    if not math.isfinite(f) or (value and f==0): fail('derived numerical overflow/underflow')
    return f


def timestamp(value):
    try: d = datetime.fromisoformat(text(value).replace('Z', '+00:00'))
    except ValueError: fail('invalid timestamp')
    if d.utcoffset() is None: fail('timezone required')
    return d.astimezone(timezone.utc)


def decode(raw):
    def pairs(items):
        d = {}
        for k, v in items:
            if k in d: fail('duplicate JSON key: ' + k)
            d[k] = v
        return d
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda x: fail('nonfinite JSON'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def decision_metrics(matrix):
    # Float-representable input exponents fit safely inside this precision.
    with localcontext() as context:
        context.prec=1000
        return _decision_metrics(matrix)


def _decision_metrics(matrix):
    """Finite declared scenario utility, dominance, minimax regret, optional EVPI."""
    states = matrix['states']; actions = matrix['actions']
    if not isinstance(states, list) or len(states) < 2 or len(set(states)) != len(states): fail('at least two unique states required')
    if not isinstance(actions, dict) or len(actions) < 2: fail('at least two actions required')
    for state in states: text(state)
    for a in actions: text(a)
    values = {}
    for action, row in actions.items():
        if len(row) != len(states): fail('utility/state mismatch')
        values[action] = [number(v) for v in row]
    text(matrix['utility_unit']); text(matrix['horizon']); text(matrix['budget_basis'])
    best = [max(row[i] for row in values.values()) for i in range(len(states))]
    regret = {a: max(best[i] - row[i] for i in range(len(states))) for a, row in values.items()}
    minimax = min(regret.values())
    robust = [a for a, r in regret.items() if r == 0]
    result = {'robust_actions': sorted(robust), 'decision_sensitive': not bool(robust),
              'maximum_regret_by_action': {a: outnum(v) for a, v in regret.items()},
              'minimax_regret_actions': sorted(a for a, v in regret.items() if v == minimax),
              'minimax_regret': outnum(minimax), 'expected_utility': None,
              'expected_value_perfect_information_upper_bound': None,
              'probability_basis': 'not_supplied_no_probability_claim'}
    probs = matrix.get('probabilities')
    if probs is not None:
        if len(probs) != len(states): fail('probability/state mismatch')
        probs = [number(p) for p in probs]
        if any(p < 0 or p > 1 for p in probs) or sum(Fraction(p) for p in probs) != 1: fail('invalid probability distribution')
        text(matrix['probability_basis']); text(matrix['probability_source_ref'])
        expected = {a: sum(p*v for p,v in zip(probs,row)) for a,row in values.items()}
        evpi = sum(p*v for p,v in zip(probs,best)) - max(expected.values())
        result.update(expected_utility={a:outnum(v) for a,v in expected.items()},
                      expected_value_perfect_information_upper_bound=outnum(max(evpi,Decimal(0))),
                      probability_basis=matrix['probability_basis'])
    return result


def calculate(packet, *, base_dir=None):
    if packet.get('version') != 1 or type(packet.get('version')) is not int: fail('version must be integer1')
    cutoff = timestamp(packet['as_of']); author=text(packet['author_id'])
    subject=text(packet['subject']); proposed_action=text(packet['proposed_action'])
    budget=number(packet['remaining_minutes'])
    if budget < 0: fail('negative time budget')
    root=Path(base_dir or '.').resolve(); artifacts={}
    for a in packet['artifacts']:
        aid=text(a['id'])
        if aid in artifacts: fail('duplicate artifact identity')
        path=(root/text(a['path'])).resolve()
        if not path.is_file(): fail('missing artifact: '+aid)
        actual=hashlib.sha256(path.read_bytes()).hexdigest()
        if a.get('sha256') != actual: fail('artifact hash mismatch: '+aid)
        if timestamp(a['available_at']) > cutoff: fail('future artifact: '+aid)
        artifacts[aid]=a
    def refs(ids):
        if not isinstance(ids,list) or not ids or len(set(ids)) != len(ids): fail('nonempty unique evidence refs required')
        if any(i not in artifacts for i in ids): fail('unregistered evidence')
    expected=packet['expected_question_ids']
    if not isinstance(expected,list) or not expected or len(set(expected))!=len(expected): fail('frozen expected question roster required')
    for qid in expected: text(qid)
    seen=set(); rows=[]
    for q in packet['questions']:
        qid=text(q['id'])
        if qid in seen: fail('duplicate question')
        seen.add(qid);text(q['question']);text(q['owner']);text(q['decision_link']);text(q['reopening_condition'])
        refs(q['baseline_artifact_ids'])
        hs=q['hypotheses']
        if len(hs)<2 or len({h['id'] for h in hs})!=len(hs): fail('focal and rival hypotheses required')
        for h in hs:
            text(h['mechanism']);text(h['falsifier']);refs(h['source_artifact_ids'])
        metrics=decision_metrics(q['decision_matrix'])
        if proposed_action not in q['decision_matrix']['actions']: fail('proposed action missing from decision matrix')
        refs(q['decision_matrix']['source_artifact_ids'])
        attempts=q['attempts']; signatures=set()
        if len(attempts)>q['attempt_budget'] or type(q['attempt_budget']) is not int or q['attempt_budget']<1: fail('invalid/exceeded bounded attempts')
        for a in attempts:
            signature=text(a['method'])+'|'+text(a['target'])
            if signature in signatures: fail('identical failed call repeated; change method/target')
            signatures.add(signature)
            if timestamp(a['at'])>cutoff: fail('future attempt')
            if a['outcome'] not in {'evidence_obtained','negative_result','transient_error','access_blocked','not_available'}: fail('unknown outcome')
            text(a['finding']);refs(a['result_artifact_ids'])
        required=q['required_for_actions']
        if not isinstance(required,list) or not required or len(set(required))!=len(required): fail('required_for_actions must be unique nonempty list')
        for action in required: text(action)
        status=q['status']
        if status not in STATUSES: fail('unknown question status')
        blockers=q.get('hard_access_blocker_artifact_ids',[])
        if blockers: refs(blockers)
        if status!='open' and not attempts and not blockers: fail('unresolved closure requires actual recovery attempt or evidenced hard access blocker')
        if status in {'resolved','assumption_bound','external_blocker','research_wait'}:
            review=q['review'];refs(review['artifact_ids'])
            if text(review['reviewer_id']).split('/')[-1]==author.split('/')[-1]: fail('independent reviewer required')
            text(review['finding'])
        if status=='resolved':
            refs(q['resolution_artifact_ids'])
            if not attempts or not any(a['outcome']=='evidence_obtained' for a in attempts): fail('resolved requires actual obtained evidence')
        if status=='assumption_bound':
            text(q['assumption_limits'])
            if proposed_action not in metrics['robust_actions']: fail('assumption_bound requires proposed action robust across declared states')
        if status=='external_blocker':
            text(q['blocker']);text(q['recovery_action'])
            if not blockers and not any(a['outcome'] in {'access_blocked','not_available'} for a in attempts): fail('external blocker not evidenced')
        if status=='research_wait':
            if proposed_action not in metrics['robust_actions']: fail('research_wait needs proposed-action robust bounds; otherwise remain open/external_blocker')
            text(q['wait_reason'])
        cost=number(q['next_experiment']['minutes'])
        if cost<=0: fail('positive experiment cost required')
        text(q['next_experiment']['discriminating_observation']);text(q['next_experiment']['target_source'])
        text(q['next_experiment']['expected_action_change']);text(q['next_experiment']['stop_condition'])
        # No pseudo-EVSI: priority compares declared decision-loss ranges per minute.
        priority=outnum(number(metrics['minimax_regret'])/cost)
        rows.append({'id':qid,'status':status,'attempts':len(attempts),'remaining_attempts':q['attempt_budget']-len(attempts),
                     'required_for_actions':required,'decision_metrics':metrics,'unit':q['decision_matrix']['utility_unit'],
                     'horizon':q['decision_matrix']['horizon'],'budget_basis':q['decision_matrix']['budget_basis'],
                     'next_experiment':q['next_experiment'],'can_fit_time_budget':cost<=budget,
                     'priority_loss_units_per_minute':priority,'priority_kind':'declared_minimax_regret_per_minute_not_EVSI'})
    if seen != set(expected): fail('question scope differs from frozen expected roster')
    if not rows: fail('empty expected question scope')
    # A sorted list is valid only when budget/horizon/utilities are commensurate.
    groups={}
    for row in rows:
        key=(row['unit'],row['horizon'],row['budget_basis'])
        groups.setdefault(key,[]).append(row)
    ordered=[]
    for group,items in sorted(groups.items()):
        ordered.extend(sorted(items,key=lambda r:(r['status']!='open',-r['priority_loss_units_per_minute'],r['id'])))
    return {'version':VERSION,'status':'resolution_ledger_checked_not_research_completion',
            'input_sha256':digest(packet),'subject':subject,'as_of':packet['as_of'],'proposed_action':proposed_action,'expected_question_ids':expected,'expected_questions':len(rows),'questions':ordered,
            'unresolved_ids':[r['id'] for r in rows if r['status'] in {'open','external_blocker'}],
            'limitations':['Artifacts are hash/availability checked; content truth and sufficiency need substantive independent review.',
                           'Scenario coverage and utilities are declared assumptions, not verified completeness or calibrated forecasts.',
                           'EVPI uses supplied probabilities and is an ideal-information upper bound, not experiment EVSI or expected alpha.',
                           'Priority is not comparable across different unit/horizon/budget groups; no automatic dispatch or completion.']}


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True)
    args=p.parse_args(); source=Path(args.input)
    result=calculate(decode(source.read_text()),base_dir=source.parent)
    Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')


if __name__=='__main__': main()
