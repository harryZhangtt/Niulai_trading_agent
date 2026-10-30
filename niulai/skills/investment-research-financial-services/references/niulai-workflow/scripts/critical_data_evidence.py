#!/usr/bin/env python3
"""Risk-tiered data gate for new full research, not a second data-fetching service.

Checks the declared critical-input inventory, exact model input values, saved
comparison calculations or documented primary-source exceptions, and independent
review bindings. It cannot discover every economically important omitted input,
authenticate a source, or reproduce an arbitrary valuation engine. Those remain
explicit independent-review responsibilities. No extra fetch is performed.
"""
import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

import evidence_crosscheck as comparison
from rationale_guard import publication_times

VERSION = '2026-10-24-critical-data-1'
EFFECTIVE_AT = '2026-10-24T00:10:31Z'
SCOPES = {'company_full', 'fund_full', 'crypto_full'}
ACTIONS = {'buy', 'add', 'hold', 'wait', 'no_buy', 'reduce', 'exit'}


def fail(message):
    raise ValueError('Critical data: ' + message)


def text(value):
    if not isinstance(value, str) or not value.strip(): fail('nonempty explanation required')
    return value


def number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        fail('finite numeric model input required')
    try:
        n = Decimal(str(value))
        if not n.is_finite(): raise ValueError()
        return n
    except (InvalidOperation, ValueError): fail('finite numeric model input required')


def stamp(value):
    try:
        t = comparison._time(value)
        if t is None: raise ValueError()
        return t
    except ValueError: fail('timezone-aware timestamp required')


def applies(record, observed_publication_times=()):
    if record.get('scope') not in SCOPES: return False
    if 'critical_data_evidence' in record or 'critical_data' in record.get('policy_versions', {}): return True
    dates = list(observed_publication_times) + publication_times(record.get('persistence', {}))
    dates += [record.get('subject', {}).get('cutoff')] if record.get('subject', {}).get('cutoff') else []
    return any(stamp(t) >= stamp(EFFECTIVE_AT) for t in dates)


def pointer(document, path):
    if not isinstance(path, str) or not path.startswith('/'):
        fail('absolute JSON pointer required')
    node = document
    try:
        for token in path[1:].split('/'):
            if re.search(r'~(?![01])', token): fail('invalid JSON pointer escape')
            token = token.replace('~1', '/').replace('~0', '~')
            if isinstance(node, list):
                if not re.fullmatch(r'0|[1-9][0-9]*', token): fail('invalid array index')
                node = node[int(token)]
            elif isinstance(node, dict): node = node[token]
            else: fail('JSON pointer crosses scalar')
    except (KeyError, IndexError): fail('model input pointer missing')
    return node


def validate(record, *, observed_publication_times=(), decision_action=None):
    if not applies(record, observed_publication_times):
        return {'status': 'historical_or_narrow_exempt', 'semantic_truth_verified': False}
    block = record.get('critical_data_evidence')
    if not isinstance(block, dict) or block.get('version') != VERSION:
        fail('versioned critical_data_evidence required')
    if block.get('status') == 'pending':
        if record.get('status') == 'complete': fail('pending verification cannot be complete')
        return {'status': 'pending', 'semantic_truth_verified': False}
    if block.get('status') != 'reviewed': fail('reviewed critical-data evidence required')
    artifacts = {a['id']: a for a in record.get('artifacts', [])}
    if len(artifacts) != len(record.get('artifacts', [])): fail('duplicate artifact IDs')
    needed = set()
    def raw(aid):
        if aid not in artifacts: fail('missing artifact ' + str(aid))
        a = artifacts[aid]; p = Path(a.get('path', ''))
        if not p.is_absolute() or not p.is_file(): fail('artifact missing or nonabsolute')
        data = p.read_bytes()
        if not data or hashlib.sha256(data).hexdigest() != a.get('sha256'): fail('artifact hash mismatch')
        needed.add(aid); return data
    def load(aid): return comparison.decode_packet(raw(aid))
    ledger = load(block.get('ledger_artifact_id'))
    if ledger.get('version') != VERSION or ledger.get('subject') != record['subject']['ticker'] or ledger.get('cutoff') != record['subject']['cutoff']:
        fail('ledger version/subject/cutoff mismatch')
    cutoff = stamp(ledger['cutoff'])
    if ledger.get('decision_action') not in ACTIONS or (decision_action is not None and ledger['decision_action'] != decision_action):
        fail('critical-data conclusion differs from published action')
    model_ids = record.get('model', {}).get('input_artifact_ids', [])
    if not model_ids or len(set(model_ids)) != len(model_ids) or ledger.get('model_input_artifact_ids') != model_ids:
        fail('ledger must cover exact full model-input artifact inventory')
    for aid in model_ids: raw(aid)
    keys = ledger.get('critical_keys')
    if not isinstance(keys, list) or not keys or len(keys) != len(set(keys)) or any(not isinstance(k,str) or not k.strip() for k in keys):
        fail('nonempty unique declared critical-key inventory required')
    items = ledger.get('items')
    if not isinstance(items, list) or len(items) != len(keys) or {x.get('key') for x in items} != set(keys):
        fail('declared critical input omitted or duplicated')
    sources = {s['id']: s for s in record.get('sources', [])}
    if len(sources) != len(record.get('sources', [])): fail('duplicate source IDs')
    source_metadata = {}
    exceptions = []; routes = {}
    for item in items:
        key = item['key']; target = item.get('input', {})
        aid = target.get('artifact_id')
        if aid not in model_ids: fail('critical target is not an active model input')
        value = number(pointer(load(aid), target.get('pointer')))
        if value != number(item.get('value')): fail('ledger value differs from active model input')
        for field in ('definition', 'unit', 'decision_relevance'): text(item.get(field))
        route = item.get('route'); routes[key] = route
        if route == 'crosscheck':
            pair = item.get('comparison', {})
            packet = load(pair.get('input_artifact_id'))
            actual = comparison.calculate(packet)
            if load(pair.get('output_artifact_id')) != actual: fail('comparison output not reproducible')
            if actual['status'] not in {'corroborated', 'shared_upstream_corroboration'}:
                fail('unresolved material source discrepancy or unavailable comparison')
            if not packet.get('require_source_hashes'): fail('source hashes mandatory for critical comparison')
            if stamp(packet['as_of']) != cutoff: fail('comparison cutoff differs from research cutoff')
            text(item.get('tolerance_and_freshness_rationale'))
            index = pair.get('selected_observation')
            if type(index) is not int or index not in (0,1): fail('selected observation must be 0 or 1')
            observation = packet['observations'][index]
            if number(observation['value']) != value or observation['subject'] != ledger['subject'] or observation['unit'] != item['unit'] or observation['definition'] != item['definition']:
                fail('comparison identity/value/unit/definition does not bind active input')
            refs = pair.get('source_artifact_ids')
            if not isinstance(refs, list) or len(refs) != 2: fail('two saved source artifacts required')
            for ref, obs in zip(refs, packet['observations']):
                raw(ref)
                if artifacts[ref]['sha256'] != obs['source']['sha256']: fail('comparison source payload hash mismatch')
        elif route == 'primary_only':
            exception = item.get('exception', {})
            for field in ('reason', 'alternative_attempt', 'authority_rationale'): text(exception.get(field))
            sid = exception.get('source_id')
            if sid not in sources or sources[sid].get('source_type') != 'primary': fail('exception needs an actual primary source record')
            src = sources[sid]; raw(src.get('snapshot_artifact_id'))
            source_metadata[sid] = hashlib.sha256(json.dumps(src,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
            if stamp(src.get('retrieved_at')) > cutoff: fail('primary evidence unavailable at cutoff')
            pid = exception.get('passage_id')
            if pid not in {p.get('id') for p in src.get('passages', [])}: fail('primary passage locator unresolved')
            raw(exception.get('attempt_artifact_id'))
            sens = load(exception.get('sensitivity_artifact_id'))
            if sens.get('input_key') != key or sens.get('unit') != item['unit']: fail('sensitivity targets wrong input')
            lo, base, hi = (number(sens.get(k)) for k in ('lower','base','upper'))
            if not lo < hi or not lo <= value <= hi or base != value: fail('nondegenerate sensitivity must bracket active input')
            cases = sens.get('cases')
            if not isinstance(cases,list) or len(cases) < 3 or not {lo,base,hi}.issubset({number(c.get('input_value')) for c in cases}):
                fail('lower/base/upper sensitivity outcomes required')
            for case in cases:
                number(case.get('decision_metric_value')); text(case.get('decision_metric'))
                if case.get('action') not in ACTIONS: fail('sensitivity action missing')
            chosen = sens.get('conclusion_action')
            actions = {c['action'] for c in cases}
            if chosen not in ACTIONS or (len(actions)>1 and chosen not in {'wait','no_buy'}) or (len(actions)==1 and chosen not in actions):
                fail('material action-changing uncertainty must remain wait/no_buy or be resolved')
            if chosen != ledger['decision_action']: fail('exception sensitivity conclusion differs from published action')
            text(sens.get('limitations')); text(sens.get('calculation_method'))
            refs = sens.get('calculation_artifact_ids')
            if not isinstance(refs,list) or not refs: fail('sensitivity calculation evidence required')
            for ref in refs: raw(ref)
            # Independent semantic review, not this generic validator, checks
            # the source extraction, arbitrary-model math and range adequacy.
            exceptions.append(key)
        else: fail('critical input requires crosscheck or primary_only route')
    reviewer_id = block.get('review_artifact_id'); review = load(reviewer_id)
    main = record.get('audit', {}).get('independent_review', {})
    author = record.get('audit', {}).get('author_id')
    if not author or review.get('reviewer_id') != main.get('reviewer_id') or review['reviewer_id'].split('/')[-1] == author.split('/')[-1]:
        fail('genuinely independent main reviewer identity required')
    if review.get('version') != VERSION or review.get('status') != 'approved_critical_data' or review.get('subject') != ledger['subject'] or review.get('cutoff') != ledger['cutoff']:
        fail('critical-data review status/identity mismatch')
    if review.get('critical_keys') != keys or review.get('model_input_artifact_ids') != model_ids:
        fail('independent critical inventory must match ledger and model')
    if review.get('source_record_hashes', {}) != source_metadata: fail('review source metadata hashes missing/stale')
    text(review.get('coverage_finding'))
    reviewed = review.get('items')
    if not isinstance(reviewed,list) or len(reviewed)!=len(keys) or {x.get('key') for x in reviewed}!=set(keys): fail('every critical item needs independent review')
    for row in reviewed:
        if row.get('status') != 'reviewed' or row.get('route') != routes[row['key']]: fail('unreviewed critical input')
        for field in ('source_lineage_finding','definition_and_extraction_finding','decision_impact_finding'): text(row.get(field))
        if row['key'] in exceptions:
            text(row.get('sensitivity_calculation_finding')); text(row.get('range_adequacy_finding'))
    needed.discard(reviewer_id)
    if review.get('artifact_hashes') != {aid:artifacts[aid]['sha256'] for aid in sorted(needed)}:
        fail('independent review lacks exact current evidence/model hashes')
    if block['ledger_artifact_id'] not in main.get('reviewed_artifact_ids',[]) or reviewer_id not in main.get('reviewed_artifact_ids',[]):
        fail('main independent review omits critical-data evidence')
    return {'status':'validated','critical_inputs':len(keys),'primary_only_exceptions':exceptions,
            'semantic_truth_verified':False,'complete_economic_input_discovery_verified':False,
            'sensitivity_formula_verified_by_generic_gate':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--record',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    result=validate(json.loads(Path(a.record).read_text()));Path(a.output).write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':main()
