"""Independent host checks plus an explicit, evidence-bound source review.

Mechanical checks are not a semantic truth oracle. The final verdict requires a
review of the actual answer/passages under the predeclared case rubric.
"""
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

from shared.actions import resolve
from shared.actions.runtime import validate as validate_action
from shared.research_sources.artifacts import ROOT, digest, read, require


def _text(answer):
    return (answer['answer'] + ' ' + ' '.join(answer['limitations']) + ' ' + ' '.join(answer['unresolved']) + ' ' +
            ' '.join(str(value or '') for claim in answer['claims'] for value in claim.values() if not isinstance(value, dict))).lower()


def _number(text, value):
    tokens = re.findall(r'(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?(?![0-9.])', text)
    return any(Decimal(token.replace(',', '')) == Decimal(value) for token in tokens)


def _period_label(value):
    text = (value or '').lower().replace('first quarter', 'q1').replace('quarter 1', 'q1')
    text = text.replace('fiscal year', 'fy').replace('fiscal', 'fy')
    return re.sub(r'[^a-z0-9]', '', text)


def _period_matches(actual, expected):
    canonical = re.fullmatch(r'fy(\d{4})q([1-4])', _period_label(expected))
    if not canonical: return _period_label(actual) == _period_label(expected)
    year, quarter = canonical.groups()
    aliases = (f'fy{year}q{quarter}', f'q{quarter}fy{year}',
               f'fy{year[-2:]}q{quarter}', f'q{quarter}fy{year[-2:]}')
    return any(re.search(re.escape(alias) + r'(?!\d)', _period_label(actual)) for alias in aliases)


def _eps_value_matches(claim, fact):
    if not _period_matches(claim['period'], fact['period']): return False
    basis = (claim['basis'] or '').lower(); value = (claim['value'] or '').lower()
    adjusted = fact['id'] == 'adjusted_eps'
    direct_basis = (('non' in basis and 'gaap' in basis) or 'adjusted' in basis) if adjusted else ('gaap' in basis and 'non' not in basis)
    if direct_basis and _number(value, fact['value']): return True
    # A neutral claim may contain several explicitly labelled facts. Parse their
    # labels rather than require one serialization style or infer from position.
    label = r'non[\s\-‑–]*gaap|gaap|adjusted'
    patterns = [r'\b(' + label + r')\b[^0-9;]{0,64}([+-]?\d+(?:\.\d+)?)',
                r'([+-]?\d+(?:\.\d+)?)[^0-9;]{0,32}?\b(' + label + r')\b']
    for index, pattern in enumerate(patterns):
        for match in re.finditer(pattern, value):
            tag, number = match.groups() if index == 0 else tuple(reversed(match.groups()))
            tag = re.sub(r'[^a-z]', '', tag)
            is_adjusted = tag in ('nongaap', 'adjusted')
            if is_adjusted == adjusted and Decimal(number) == Decimal(fact['value']): return True
    return False


def inspect_case(case, *, not_before):
    """Reopen real transport/action/source bytes, and return host observations."""
    from datetime import datetime
    from shared.job_runtime.model import _parse
    require(case['status'] == 'completed' and case['answer_ref'], 'ATOMIC_CASE_NOT_COMPLETED')
    report, source = read(case['report_ref']), read(case['source_ref'])
    validate_action('SourceReceipt', source)
    require(datetime.fromisoformat(source['retrieved_at']) >= datetime.fromisoformat(not_before), 'ATOMIC_OLD_SOURCE_CAPTURE')
    read(source['raw'], json_value=False); source_text = read(source['text'], json_value=False).decode()
    acquired = read(case['acquisition_outcome_ref']); request = read(case['acquisition_request_ref'])
    require(acquired['status'] == 'success' and acquired['data']['source_ref'] == case['source_ref'], 'ATOMIC_ACQUISITION_BINDING')
    acquisition_receipt = read(acquired['execution_ref'])
    require(acquisition_receipt['request_sha256'] == digest(request) and acquisition_receipt['data_sha256'] == digest(acquired['data']), 'ATOMIC_ACQUISITION_RECEIPT')
    require(resolve(request['action'], release_ref=request['release_ref'])['release_sha256'] == request['expected_release_sha256'], 'ATOMIC_ACQUISITION_RELEASE')
    inputs = read(case['input_ref']); source_spec = inputs['source_identity']
    require(read(report['input_manifest']['request_ref'])['input'] == inputs, 'ATOMIC_EXECUTED_INPUT_BINDING')
    require(source['source_url'] == (source_spec.get('url') or source_spec['target']), 'ATOMIC_SOURCE_IDENTITY')
    if source_spec['provider'] == 'arxiv':
        require(source.get('source_version') == source_spec['target'].rsplit('v', 1)[1]
                and source.get('upstream_id') == source_spec['target'], 'ATOMIC_SOURCE_REVISION')
    read_ranges, read_locators, comparisons, packet_complete, threads, tokens = [], {}, {}, {}, [], 0
    for model_ref in report['model_execution_refs']:
        model = read(model_ref); receipt = model['receipt']
        require(model['status'] == 'succeeded' and receipt['turn_completed'] and receipt['thread_id'], 'ATOMIC_MODEL_TRANSPORT')
        events = ROOT / receipt['run_directory'] / 'events.jsonl'; response = ROOT / receipt['response_path']
        require(hashlib.sha256(events.read_bytes()).hexdigest() == receipt['event_stream_sha256']
                and hashlib.sha256(response.read_bytes()).hexdigest() == receipt['response_sha256'], 'ATOMIC_MODEL_BYTES')
        parsed = _parse(events)
        require(parsed['completed'] and not parsed['failures'] and not parsed['parse_errors'], 'ATOMIC_MODEL_EVENT')
        threads.append(receipt['thread_id'])
        usage = receipt.get('usage')
        tokens = None if tokens is None or not usage else tokens + usage.get('input_tokens', 0) + usage.get('output_tokens', 0)
    require(bool(threads), 'ATOMIC_REAL_MODEL_REQUIRED')
    for row in report['action_records']:
        canonical, outcome, receipt = read(row['request_ref']), read(row['outcome_ref']), read(row['execution_ref'])
        require(canonical['arguments'] == read(row['arguments_ref']) and canonical['action'] == row['action']
                and canonical['request_id'] == report['run_id'] + ':' + row['call_id'], 'ATOMIC_ACTION_RECORD_BINDING')
        require(receipt['request_sha256'] == digest(canonical) and receipt['data_sha256'] == digest(outcome['data'])
                and receipt['status'] == outcome['status'] and receipt['error'] == outcome['error'], 'ATOMIC_ACTION_BINDING')
        selected = resolve(canonical['action'], release_ref=canonical['release_ref'])
        require(receipt['release_sha256'] == canonical['expected_release_sha256'] == selected['release_sha256'], 'ATOMIC_ACTION_RELEASE')
        if outcome['status'] != 'success': continue
        validate_action(selected['output_schema'], outcome['data'])
        if row['action'].startswith('evidence.read@'):
            require(outcome['data']['source_ref'] == case['source_ref'], 'ATOMIC_FOREIGN_SOURCE')
            passage = outcome['data']['passage']
            require(passage['text'] == source_text[passage['start']:passage['end']], 'ATOMIC_READ_CONTENT')
            read_ranges.append((passage['start'], passage['end']))
            read_locators[passage['locator']] = (passage['start'], passage['end'])
        if row['action'].startswith('evidence.compare_numeric@'):
            ref = read(row['arguments_ref'])['packet_ref']
            role = next((role for role, expected_ref in inputs['comparison_packets'].items() if expected_ref == ref), None)
            require(role is not None and role not in comparisons, 'ATOMIC_PACKET_ROLE')
            comparisons[role] = outcome['data']
            packet = read(ref)
            packet_complete[role] = all(observation.get('period') and observation['period'].get('start')
                                        and observation['period'].get('end') for observation in packet['observations'])
    require(read_ranges, 'ATOMIC_READ_REQUIRED')
    answer = read(case['answer_ref'])
    require(answer == report['phases']['research']['data'], 'ATOMIC_ANSWER_BINDING')
    for claim in answer['claims']:
        require(claim['source_ref'] == case['source_ref'] and claim['passage_locator'] in read_locators, 'ATOMIC_CITATION_NOT_ISSUED')
    return {'answer': answer, 'source': source, 'text': source_text, 'read_ranges': read_ranges, 'comparisons': comparisons,
        'packet_complete': packet_complete, 'inputs': inputs, 'read_locators': read_locators,
        'threads': threads, 'tokens': tokens, 'counts': {'actions': report['counts']['actions'] + 1,
        'model_turns': report['counts']['model_turns'], 'read_calls': len(read_ranges)}}


def mechanical(case_id, expected, inspected):
    answer = inspected['answer']; text = _text(answer); failures = []
    def check(condition, code):
        if not condition: failures.append(code)
    check(bool(answer['claims']), 'NO_STRUCTURED_SOURCE_CLAIMS')
    if case_id == 'nvda_eps_basis_q1fy25':
        claims = answer['claims']
        for fact in expected['expected_facts']:
            check(any(_eps_value_matches(claim, fact) for claim in claims), 'EPS_VALUE_BASIS_PERIOD_' + fact['id'])
        check('split' in text, 'SHARE_BASIS_NOT_DISCLOSED')
    elif case_id == 'nvda_historical_vs_latest_period':
        check(any(word in text for word in ('guidance', 'forecast', 'outlook')), 'FORECAST_NOT_DISTINGUISHED')
        check(_number(text, '28.0') or _number(text, '28') or _number(text, '28000'), 'GUIDANCE_AMOUNT_MISSING')
        check('2024' in text and ('2025' in text or 'fy25' in text), 'HISTORICAL_PERIOD_MISSING')
        check(bool(answer['unresolved']) and any(word in ' '.join(answer['unresolved']).lower() for word in ('latest', 'current', 'newer')), 'LATEST_GAP_NOT_PRESERVED')
        check(_number(text, '26044') or _number(text.replace(',', ''), '26044') or _number(text, '26.0') or _number(text, '26.044'), 'HISTORICAL_REVENUE_MISSING')
    elif case_id == 'flashattention3_h100_scope':
        check('warp' in text and ('overlap' in text or 'asynchron' in text) and 'softmax' in text, 'METHOD_SCOPE_MISSING')
        compact = re.sub(r'\s+', '', text)
        check('h100' in compact and '80gb' in compact and 'sxm5' in compact, 'BENCHMARK_HARDWARE_MISSING')
        check(_number(text, '1830') and _number(text, '100') and ('averag' in text or 'mean timing' in text), 'BENCHMARK_TIMING_MISSING')
        limits = ' '.join(answer['limitations'] + answer['unresolved']).lower()
        check(('inference' in limits or 'end-to-end' in limits) and any(w in limits for w in ('demand', 'revenue', 'investment', 'economic')), 'EXTRAPOLATION_LIMIT_MISSING')
    elif case_id == 'nvda_revenue_units_periods':
        results = inspected['comparisons']
        for row in expected['comparison_expectations']:
            role = row['role']; actual = results.get(role)
            check(actual is not None, 'MISSING_COMPARISON_' + role)
            if actual is None: continue
            allowed = {row['complete_packet_expected_status']}
            if not inspected['packet_complete'][role] and row.get('incomplete_metadata_expected_status'):
                allowed.add(row['incomplete_metadata_expected_status'])
            check(actual['status'] in allowed, 'WRONG_COMPARISON_' + role)
        check(_number(text, '44') and _number(text, '50'), 'ROUNDING_DIFFERENCE_TOLERANCE_MISSING')
        check('independent' in text and any(w in text for w in ('same', 'one', 'single', 'shared')), 'SHARED_LINEAGE_MISSING')
    else: failures.append('UNKNOWN_CASE')
    return failures


def callback():
    def evaluate(case_id, inputs, expected, observation):
        case = observation['case']; require(case['case_id'] == case_id == inputs['id'], 'ATOMIC_CASE_ID_BINDING')
        if case['status'] != 'completed':
            return {'passed': False, 'metrics': {'correctness': False, 'action_calls': None, 'model_turns': None,
                'source_read_calls': None, 'elapsed_seconds': case.get('elapsed_seconds'), 'tokens': None, 'cost': None},
                'reasons': ['ATOMIC_CASE_NOT_COMPLETED', case.get('reason', 'UNKNOWN_CASE_FAILURE')]}
        inspected = inspect_case(case, not_before=observation['not_before'])
        require(inspected['inputs']['question'] == inputs['input_question']
                and inspected['inputs']['source_identity'] == inputs['public_sources'][0], 'ATOMIC_SEALED_QUESTION_BINDING')
        failures = mechanical(case_id, expected, inspected)
        review = read(observation['review_ref'])
        require(review['case_id'] == case_id and review['answer_ref'] == case['answer_ref']
            and review['source_ref'] == case['source_ref'] and review['oracle_sha256'] == observation['oracle_sha256']
            and review['reviewer'] == 'orchestrator_source_grounded', 'ATOMIC_REVIEW_BINDING')
        require(set(review['criteria']) == {row['id'] for row in expected['critical_criteria']}, 'ATOMIC_REVIEW_ROSTER')
        require(all(type(verdict) is bool for verdict in review['criteria'].values()), 'ATOMIC_REVIEW_SCHEMA')
        if review['status'] != 'passed': failures.append('SOURCE_GROUNDED_REVIEW_FAILED')
        if not all(review['criteria'].values()): failures.append('SOURCE_REVIEW_CRITICAL_CRITERION')
        return {'passed': not failures, 'metrics': {'correctness': not failures,
            'action_calls': inspected['counts']['actions'], 'model_turns': inspected['counts']['model_turns'],
            'source_read_calls': inspected['counts']['read_calls'], 'elapsed_seconds': case['elapsed_seconds'],
            'tokens': inspected['tokens'], 'cost': None}, 'reasons': failures}
    return evaluate
