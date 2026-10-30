#!/usr/bin/env python3
"""Offline selection and arithmetic gates, not an agent executor or evidence verifier.

Plan inputs are a restored configuration, rules, and a final-session price_watch
snapshot. Results preserve every selected ticker, including explicit partials.
Use plan_id + ticker as checkpoint key; an unchanged plan is byte-stable.
"""
import argparse
import hashlib
import json
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path

from niulai_state import validate_config
from price_watch import gate, instant, session, validate_rules
from research_store import read_ticker_current

VERSION = '2026-10-20-triggered-research-1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def number(value, minimum=None, maximum=None):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a number')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValueError('Invalid decimal') from None
    if not result.is_finite() or (minimum is not None and result < minimum) or (maximum is not None and result > maximum):
        raise ValueError('Number outside valid range')
    return result


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def baselines(database, symbols):
    """Read all related sections, not merely the latest price-only update.

    Metadata locates the documents; it does not certify that a model is usable.
    Supporting-model relations can exist when model_revisions is empty.
    """
    path = Path(database).resolve()
    if not path.is_file():
        raise ValueError('Restore research.sqlite first; never initialize empty state')
    output = {}
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Research database integrity failure')
        for symbol in symbols:
            updates = read_ticker_current(db, symbol)
            row = db.execute('SELECT payload FROM securities WHERE symbol=?', (symbol,)).fetchone()
            if not row:
                output[symbol] = {'status': 'not_catalogued', 'gaps': ['No mapped research baseline'], 'sections': [], 'artifacts': [], 'model_candidates': [], 'incremental_records': updates}
                continue
            security = json.loads(row[0])
            relations = [json.loads(r[0]) for r in db.execute('SELECT payload FROM security_artifact_relations WHERE security_symbol=? ORDER BY artifact_id,section_id,relationship', (symbol,))]
            section_ids = {r[0] for r in db.execute('SELECT section_id FROM security_artifact_relations WHERE security_symbol=?', (symbol,))}
            section_ids.update(security.get('latest_analysis_section_ids', []))
            sections = []
            artifact_ids = {r[0] for r in db.execute('SELECT artifact_id FROM security_artifact_relations WHERE security_symbol=?', (symbol,))}
            for sid in sorted(s for s in section_ids if s):
                section = db.execute('SELECT artifact_id,payload FROM research_sections WHERE id=?', (sid,)).fetchone()
                if section:
                    artifact_ids.add(section[0]); sections.append(json.loads(section[1]))
            artifacts = []
            for aid in sorted(artifact_ids):
                artifact = db.execute('SELECT payload FROM artifacts WHERE library_file_id=?', (aid,)).fetchone()
                if artifact:
                    artifacts.append(json.loads(artifact[0]))
            models = [json.loads(r[0]) for r in db.execute('SELECT payload FROM model_revisions WHERE symbol=? ORDER BY id', (symbol,))]
            candidates = [r for r in relations if r.get('relationship') in ('supporting_model', 'reproducibility')]
            output[symbol] = {'status': security.get('status', 'unknown'), 'security': security,
                              'sections': sections, 'artifacts': artifacts, 'relations': relations,
                              'model_candidates': models + candidates,
                              'model_availability': 'must_open_artifacts_and_verify_not_inferred_from_catalog',
                              'gaps': security.get('gaps', []), 'documents_read_by_planner': False,
                              'incremental_records': updates}
    return output


def plan(config, rules, snapshot, expected_session, research_db, allow_replay=False, allow_legacy_snapshot=False):
    validate_config(config)
    validate_rules(rules)
    if config['alert_authority'] != 'niulai_saved_json_sqlite':
        raise ValueError('Standalone authority required')
    if snapshot.get('status') not in ('completed', 'partial'):
        raise ValueError('Load actual snapshot, not a skip/duplicate receipt')
    if snapshot.get('mode') != 'live' and not allow_replay:
        raise ValueError('Retrospective snapshot requires --allow-replay')
    for key, value in [('rules_sha256', rules), ('config_sha256', config)]:
        if snapshot.get(key) is None:
            if not (allow_legacy_snapshot and allow_replay and snapshot.get('mode') == 'replay'):
                raise ValueError('Snapshot fingerprint missing: ' + key)
        elif snapshot[key] != digest(value):
            raise ValueError('Snapshot fingerprint mismatch: ' + key)
    if snapshot.get('config_revision') != config['config_revision']:
        raise ValueError('Configuration revision mismatch')
    market = session(instant(snapshot['as_of']))
    if not market or snapshot.get('session') != expected_session or market['date'] != expected_session:
        raise ValueError('Snapshot is not the requested XNYS session')
    if instant(snapshot['as_of']) < market['close']:
        raise ValueError('Final session snapshot required')
    batch_size = config.get('research', {}).get('daily_triggered_review', {}).get('batch_size', 3)
    if type(batch_size) is not int or not 1 <= batch_size <= 8:
        raise ValueError('batch_size must be an integer from 1 to 8')
    active = {r['id']: r for r in rules if r['enabled']}
    seen, grouped, errors = set(), {}, []
    for row in snapshot.get('results', []):
        rid = row['rule_id']
        if rid in seen or rid not in active:
            raise ValueError('Duplicate or non-enabled snapshot rule')
        seen.add(rid)
        rule = active[rid]
        if (row['ticker'], row['direction'], number(row['threshold'])) != (rule['ticker'], rule['direction'], number(rule['threshold'])):
            raise ValueError('Snapshot rule differs from current rule')
        if row.get('session') != expected_session or instant(row['quote_time']) != market['close']:
            raise ValueError('Missing or stale final-session quote')
        if instant(rule.get('effective_from', rule['updatedAt'])) > market['open'] or instant(rule['updatedAt']) > instant(snapshot['as_of']):
            raise ValueError('Rule revision not valid for snapshot')
        if rule.get('expires_at') and instant(rule['expires_at']) <= instant(snapshot['as_of']):
            raise ValueError('Expired rule in snapshot')
        for field in ('zone_reached', 'threshold_reached', 'currently_in_zone'):
            if type(row.get(field)) is not bool:
                raise ValueError('Missing boolean classification')
        low, high, close = (number(row[k], Decimal('0.000000000001')) for k in ('low', 'high', 'close'))
        if not low <= close <= high:
            raise ValueError('Invalid price range')
        threshold, edge = number(row['threshold']), number(row['zone_edge'])
        below = row['direction'] == 'below'
        leverage = abs(number(config['price_monitor'].get('leverage_multipliers', {}).get(row['ticker'], 1)))
        buffer = number(rule.get('buffer_fraction', number(config['price_monitor']['buffer_fraction']) * leverage), Decimal(0), Decimal('.05'))
        if number(row.get('daily_leverage_multiplier', 1)) != leverage or number(row['buffer_fraction']) != buffer:
            raise ValueError('Snapshot leverage/buffer differs from current policy')
        if edge != threshold * (1 + buffer if below else 1 - buffer):
            raise ValueError('Snapshot zone edge differs from current policy')
        extreme = low if below else high
        expected = [extreme <= edge, extreme <= threshold, close <= edge] if below else [extreme >= edge, extreme >= threshold, close >= edge]
        if expected != [row[k] for k in ('zone_reached', 'threshold_reached', 'currently_in_zone')]:
            raise ValueError('Classification inconsistent with prices')
        if row['zone_reached']:
            item = grouped.setdefault(row['ticker'], {'ticker': row['ticker'], 'rules': [], 'status': 'pending', 'close': str(close)})
            if number(item['close']) != close:
                raise ValueError('Conflicting quotes for ticker')
            item['rules'].append({**row, 'rule_updated_at': rule['updatedAt'],
                                  'attainment': 'threshold' if row['threshold_reached'] else 'approach_only',
                                  'location': 'in_zone' if row['currently_in_zone'] else 'rebounded_outside_zone'})
    for error in snapshot.get('errors', []):
        rid = error['rule_id']
        if rid in seen or rid not in active or error.get('ticker') != active[rid]['ticker']:
            raise ValueError('Invalid or duplicate error coverage')
        seen.add(rid)
        errors.append(error)
    if seen != set(active):
        raise ValueError('Snapshot silently omits enabled rules')
    coverage = snapshot.get('coverage', {})
    expected_counts = {'enabled_rules': len(active), 'valid_rules': len(snapshot.get('results', [])),
                       'failed_rules': len(errors), 'symbols': len({r['ticker'] for r in active.values()})}
    if any(coverage.get(k) != v for k, v in expected_counts.items()):
        raise ValueError('Coverage counts mismatch')
    if bool(errors) != (snapshot['status'] == 'partial'):
        raise ValueError('Snapshot status contradicts coverage')
    items = [grouped[ticker] for ticker in sorted(grouped)]
    inherited = baselines(research_db, [item['ticker'] for item in items])
    for item in items:
        item['rules'].sort(key=lambda r: r['rule_id'])
        item['research_profile'] = 'leveraged_fund' if any(number(r.get('daily_leverage_multiplier', 1)) != 1 for r in item['rules']) else 'resolve_security_type'
        item['baseline'] = inherited[item['ticker']]
    identity = {'version': VERSION, 'session': expected_session, 'config_hash': digest(config),
                'rules_hash': digest(sorted(rules, key=lambda r: r['id'])), 'snapshot_hash': digest(snapshot), 'baseline_hash': digest(inherited)}
    plan_id = digest(identity)
    for item in items:
        item['checkpoint_key'] = plan_id + ':' + item['ticker']
    return {**identity, 'plan_id': plan_id, 'config_revision': config['config_revision'],
            'snapshot_id': snapshot['id'], 'retrospective': snapshot.get('mode') != 'live',
            'coverage': expected_counts, 'coverage_errors': errors,
            'status': 'partial_coverage' if errors else 'planned', 'items': items,
            'batches': [[item['ticker'] for item in items[i:i + batch_size]] for i in range(0, len(items), batch_size)],
            'automatic_trading': False, 'automatic_alert_edits': False}


def validate_results(planned, payload):
    """Structural and arithmetic checks only; independent evidence review is still required.

    Each result: ticker, status (complete|partial), evidence_delta
    (changed|no_new_edge|unavailable), checked_sources, gaps, action, plus complete
    results' baseline_id, causal_chain, market_expectations, counter_evidence,
    catalyst, invalidation, confidence and model. model scenarios contain
    probability and terminal_wealth_per_share (net costs, dividends included).
    This computes horizon return, never substitutes it for a corporate DCF or
    path-based leveraged model. Those must be referenced and checked upstream.
    """
    if payload.get('plan_id') != planned['plan_id']:
        raise ValueError('Plan revision mismatch')
    expected = {i['ticker'] for i in planned['items']}
    by_ticker = {i['ticker']: i for i in planned['items']}
    seen, output = set(), []
    for item in payload.get('items', []):
        ticker = item['ticker']
        if ticker not in expected or ticker in seen:
            raise ValueError('Unexpected/duplicate research result')
        seen.add(ticker)
        if item.get('status') not in ('complete', 'partial') or item.get('evidence_delta') not in ('changed', 'no_new_edge', 'unavailable'):
            raise ValueError('Invalid research status')
        if not isinstance(item.get('gaps'), list) or not isinstance(item.get('checked_sources'), list):
            raise ValueError('Explicit sources and gaps required')
        for source in item['checked_sources']:
            if not all(nonempty(source.get(k)) for k in ('url', 'claim', 'published_at', 'retrieved_at')):
                raise ValueError('Source provenance incomplete')
            instant(source['published_at']); instant(source['retrieved_at'])
        result = {'ticker': ticker, 'status': item['status'], 'evidence_delta': item['evidence_delta']}
        if item['status'] == 'partial':
            if not item['gaps'] or item.get('action') not in ('pending_research', 'no_recommendation') or item.get('model') is not None or item.get('position_proposal') is not None:
                raise ValueError('Partial result cannot certify numerical recommendation')
            output.append(result)
            continue
        if item['evidence_delta'] == 'unavailable' or not item['checked_sources']:
            raise ValueError('Complete result requires observed evidence review')
        for field in ('baseline_id', 'market_expectations', 'counter_evidence', 'catalyst', 'invalidation', 'confidence', 'independent_review_ref'):
            if not nonempty(item.get(field)):
                raise ValueError('Missing complete-result field: ' + field)
        baseline = by_ticker[ticker]['baseline']
        sections = {s['id']: s for s in baseline['sections']}
        if sections:
            if item['baseline_id'] not in sections:
                raise ValueError('Baseline ID must identify an inherited section')
            read_refs = item.get('documents_read_refs', [])
            if not isinstance(read_refs, list) or not read_refs:
                raise ValueError('Prior document read references required')
            known_artifacts = {s.get('artifact_id') for s in baseline['sections']}
            if any(ref not in known_artifacts for ref in read_refs) or sections[item['baseline_id']].get('artifact_id') not in read_refs:
                raise ValueError('Document read references do not match inherited artifacts')
        elif item['baseline_id'] != 'new_baseline' or not nonempty(item.get('baseline_reconstruction_ref')):
            raise ValueError('Missing inherited baseline requires explicit new-baseline reconstruction')
        if item.get('action') not in ('buy', 'add', 'hold', 'wait', 'reduce', 'exit', 'no_recommendation'):
            raise ValueError('Invalid analytical action')
        chain = item.get('causal_chain', {})
        for field in ('evidence', 'business_driver', 'owner_profit', 'valuation', 'market_gap', 'falsifier'):
            if not nonempty(chain.get(field)):
                raise ValueError('Incomplete causal chain: ' + field)
        if item['evidence_delta'] == 'no_new_edge' and item.get('alpha_claim') is True:
            raise ValueError('Cannot claim new alpha without new edge')
        model = item['model']
        if not nonempty(model.get('artifact_ref')) or model.get('checks_passed') is not True or not nonempty(model.get('probability_basis')):
            raise ValueError('Model provenance/checks missing')
        if by_ticker[ticker]['research_profile'] == 'leveraged_fund':
            if model.get('model_type') != 'leveraged_path_model' or not nonempty(model.get('path_model_ref')):
                raise ValueError('Leveraged security requires reviewed path-model provenance')
        initial = number(model['entry_price'], Decimal('0.000000000001'))
        years = number(model['horizon_years'], Decimal('0.000000000001'))
        scenarios = model['scenarios']
        if len(scenarios) < 2:
            raise ValueError('At least two scenarios required')
        probabilities = [number(s['probability'], Decimal(0), Decimal(1)) for s in scenarios]
        if sum(probabilities) != 1:
            raise ValueError('Probabilities must sum exactly to 1')
        values = [number(s['terminal_wealth_per_share'], Decimal(0)) for s in scenarios]
        expected_wealth = sum(p * v for p, v in zip(probabilities, values))
        result.update(expected_terminal_wealth=str(expected_wealth), expected_horizon_return=str(expected_wealth / initial - 1), horizon_years=str(years))
        # This is explicitly CAGR of expected wealth, not expected CAGR/log growth.
        result['cagr_of_expected_wealth'] = str((expected_wealth / initial) ** (Decimal(1) / years) - 1)
        result['loss_probability'] = str(sum(p for p, v in zip(probabilities, values) if v < initial))
        position = item.get('position_proposal')
        if position is None and (item['action'] in ('buy', 'add', 'reduce', 'exit') or not nonempty(item.get('position_proposal_reason'))):
            raise ValueError('Action requires sizing or an explicit no-sizing reason')
        if position is not None:
            if position.get('conditional') is not True and not nonempty(position.get('verified_holdings_ref')):
                raise ValueError('Unverified holdings require conditional sizing')
            target = number(position['target_weight'], Decimal(0), Decimal(1))
            current_key = 'assumed_current_weight' if position.get('conditional') is True else 'current_weight'
            current = number(position[current_key], Decimal(0), Decimal(1))
            tranches = position.get('tranches', [])
            total = sum((number(t['portfolio_weight'], Decimal(0), Decimal(1)) for t in tranches), Decimal(0))
            capacity = max(Decimal(0), target - current) if item['action'] in ('buy', 'add') else max(Decimal(0), current - target) if item['action'] in ('reduce', 'exit') else Decimal(0)
            if total > capacity:
                raise ValueError('Tranche changes exceed target minus existing position')
            for tranche in tranches:
                if not nonempty(tranche.get('condition')):
                    raise ValueError('Every tranche needs an explicit condition')
        ranges = item.get('alert_range_proposals')
        if not isinstance(ranges, list):
            raise ValueError('Explicit alert range proposal list required')
        if not ranges and not nonempty(item.get('alert_range_proposal_reason')):
            raise ValueError('No alert range changes requires a reason')
        for tier in ranges:
            low = number(tier['lower'], Decimal('0.000000000001'))
            high = number(tier['upper'], low)
            if not nonempty(tier.get('condition')) or not nonempty(tier.get('model_ref')):
                raise ValueError('Proposed range needs model basis and condition')
        if item.get('automatic_alert_edits', False) or item.get('automatic_trading', False):
            raise ValueError('Proposals cannot execute trades or alert edits')
        output.append(result)
    if seen != expected:
        raise ValueError('Missing selected tickers; record explicit partials')
    return {'valid': True, 'plan_id': planned['plan_id'], 'items': output,
            'all_research_complete': all(i['status'] == 'complete' for i in output),
            'coverage_complete': not planned['coverage_errors'],
            'semantic_truth_verified': False,
            'limitation': 'Structure/arithmetic only; inspect evidence and run full research harness before recommendations.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan')
    for key in ('config', 'rules', 'snapshot', 'session', 'research-db', 'output'):
        p.add_argument('--' + key, required=True)
    p.add_argument('--allow-replay', action='store_true')
    p.add_argument('--allow-legacy-snapshot', action='store_true')
    p = sub.add_parser('due')
    for key in ('config', 'as-of', 'automation-id', 'output'):
        p.add_argument('--' + key, required=True)
    p = sub.add_parser('validate')
    for key in ('plan', 'results', 'output'):
        p.add_argument('--' + key, required=True)
    args = parser.parse_args()
    load = lambda path: json.loads(Path(path).read_text())
    if args.command == 'plan':
        rules = load(args.rules)
        result = plan(load(args.config), rules['alerts'], load(args.snapshot), args.session, args.research_db, args.allow_replay, args.allow_legacy_snapshot)
    elif args.command == 'validate':
        result = validate_results(load(args.plan), load(args.results))
    else:
        config = load(args.config)
        validate_config(config)
        role = 'daily_triggered_research'
        schedule = next((s for s in config['schedules'] if s['role'] == role), None)
        if schedule and schedule.get('automation_id') != args.automation_id:
            raise ValueError('Automation identity mismatch')
        due, reason, market = gate(config, role, instant(args.as_of))
        result = {'due': due, 'reason': reason, 'session': market['date'] if market else None}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': args.output, 'plan_id': result.get('plan_id'), 'status': result.get('status'), 'valid': result.get('valid')}))


if __name__ == '__main__':
    main()
