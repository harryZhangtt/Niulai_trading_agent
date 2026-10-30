#!/usr/bin/env python3
"""Small deterministic adoption diagnostics; no source authentication or valuation.

Public API: decode_packet(bytes) -> dict; calculate(dict) -> JSON-safe dict.
Money and weights are plain decimal strings. Counts/months are JSON integers.
See test_adoption_checks.example_packet() for the complete synthetic interface.

Packet: version, subject, as_of, customer_economics, scenarios, reference_class.
Available customer_economics declares one job, service_requirement, currency unit,
annual period, cost_allocation and three alternatives (status_quo,
simple_alternative, proposed_technology). Each alternative has qualification and
six sourced/assumed money items. Gross benefit is monetizable value for the SAME
job, not revenue plus avoided cost for that same value. Integration and switching
are annualized separately, without duplication in recurring/supervision costs.
Unavailable economics instead requires gap, attempted_refs and next_observation.

Scenarios require all four families and either all-null weights or a normalized
joint partition. Weights are analyst inputs, never estimated by this script.
Known reference-class denominator must equal success+niche+failure+pending+unknown;
its rate bounds describe that declared cohort only, never a population forecast.
Unavailable denominator cannot produce a success rate. All input availability
and selection timestamps must be at or before as_of; forecasts may cover a future
annual period. Semantic equivalence, source quality, selection bias, independence,
cohort inclusion, causal inference and appropriate assumptions require review.
"""
import argparse
from datetime import date, datetime, timezone
from decimal import Context, Decimal, localcontext
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

VERSION = '2026-10-23-adoption-economics-1'
ROLES = {'status_quo', 'simple_alternative', 'proposed_technology'}
FAMILIES = {'abandonment', 'niche', 'broad_weak_capture', 'broad_strong_capture'}
OUTCOMES = {'success', 'niche', 'failure', 'pending', 'unknown'}
MONEY_FIELDS = ('gross_monetizable_benefit', 'recurring_fee', 'integration_annualized_cost',
                'supervision_cost', 'expected_error_cost', 'switching_annualized_cost')
_CONTEXT = Context(prec=256)
_NUMBER = re.compile(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z')
_TIME = re.compile(
    r'[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]'
    r'(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])\Z'
)


class AdoptionCheckError(ValueError):
    def __init__(self, code, path, message):
        self.code, self.path, self.message = code, path, message
        super().__init__(f'{code} at {path}: {message}')

    def as_dict(self):
        return {'version': VERSION, 'status': 'error', 'error': {
            'code': self.code, 'path': self.path, 'message': self.message}}


def fail(code, path, message):
    raise AdoptionCheckError(code, path, message)


def obj(value, path, keys):
    if type(value) is not dict or set(value) != set(keys):
        fail('shape', path, 'Expected exactly these object keys: ' + ', '.join(keys))
    return value


def text(value, path):
    if type(value) is not str or not value.strip() or len(value) > 8192 or value != value.strip() or any(ord(c) < 32 for c in value):
        fail('text', path, 'Expected bounded nonempty text without outer whitespace or controls')
    return value


def refs(value, path):
    if type(value) is not list or not 1 <= len(value) <= 100:
        fail('refs', path, 'At least one actual source/assumption reference required')
    for item in value:
        text(item, path)
    if len(value) != len(set(value)):
        fail('refs', path, 'Duplicate reference')


def stamp(value, path):
    if type(value) is not str or not _TIME.fullmatch(value):
        fail('timestamp', path, 'Expected RFC3339 timestamp with seconds and timezone')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        fail('timestamp', path, 'Invalid timestamp')


def available(value, cutoff, path):
    if stamp(value, path) > cutoff:
        fail('lookahead', path, 'Input was unavailable at the declared cutoff')


def decimal(value, path):
    if type(value) is not str or len(value) > 80 or not _NUMBER.fullmatch(value):
        fail('decimal', path, 'Expected nonnegative finite plain decimal string, no exponent')
    result = Decimal(value)
    if len(result.as_tuple().digits) > 72:
        fail('decimal', path, 'Too many decimal digits')
    return result


def out(value):
    if not value:
        return '0'
    result = format(value, 'f')
    return result.rstrip('0').rstrip('.') if '.' in result else result


def count(value, path, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= 10**9:
        fail('count', path, 'Expected bounded integer count' + (' greater than zero' if positive else ''))
    return value


def rows(value, path, size):
    if type(value) is not list or len(value) != size:
        fail('shape', path, f'Expected exactly {size} rows')
    return value


def money(item, cutoff, path):
    obj(item, path, ('value', 'basis', 'refs', 'available_at', 'note'))
    if item['basis'] not in ('observed', 'assumed'):
        fail('basis', path, 'Money basis must be observed or assumed')
    refs(item['refs'], path + '.refs')
    text(item['note'], path + '.note')
    available(item['available_at'], cutoff, path + '.available_at')
    return decimal(item['value'], path + '.value')


def economics(packet, cutoff):
    path = '$.customer_economics'
    if type(packet) is not dict:
        fail('shape', path, 'Expected an object')
    if packet.get('status') == 'unavailable':
        obj(packet, path, ('status', 'gap', 'attempted_refs', 'next_observation'))
        text(packet['gap'], path + '.gap')
        refs(packet['attempted_refs'], path + '.attempted_refs')
        text(packet['next_observation'], path + '.next_observation')
        return {'status': 'unavailable', 'gap': packet['gap'], 'next_observation': packet['next_observation'],
                'comparisons': None, 'warning': 'Missing economics is not evidence of economic advantage.'}
    obj(packet, path, ('status', 'job', 'service_requirement', 'money_unit', 'annual_period', 'cost_allocation', 'alternatives'))
    if packet['status'] != 'available':
        fail('status', path, 'Expected available or unavailable')
    for key in ('job', 'service_requirement', 'cost_allocation'):
        text(packet[key], path + '.' + key)
    if type(packet['money_unit']) is not str or not re.fullmatch(r'currency:[A-Z]{3}', packet['money_unit']):
        fail('unit', path, 'Expected common currency:CCC money unit')
    period = obj(packet['annual_period'], path + '.annual_period', ('start', 'end'))
    try:
        if not all(type(v) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}', v) for v in period.values()):
            raise ValueError()
        start, end = date.fromisoformat(period['start']), date.fromisoformat(period['end'])
    except (ValueError, TypeError):
        fail('period', path, 'Expected valid ISO dates')
    if (end - start).days + 1 not in (364, 365, 366, 371):
        fail('period', path, 'An annual comparison requires a 52/53-week or 365/366-day period')
    alternatives = rows(packet['alternatives'], path + '.alternatives', 3)
    result, costs = {}, {}
    for index, alt in enumerate(alternatives):
        apath = path + f'.alternatives[{index}]'
        obj(alt, apath, ('role', 'name', 'qualification', 'qualification_refs', 'qualification_available_at', 'money'))
        role = alt['role']
        if type(role) is not str or role not in ROLES or role in result:
            fail('alternatives', apath, 'Each of the three roles must appear exactly once')
        text(alt['name'], apath + '.name')
        if alt['qualification'] not in ('meets', 'does_not_meet', 'unknown'):
            fail('qualification', apath, 'Expected meets, does_not_meet or unknown')
        refs(alt['qualification_refs'], apath + '.qualification_refs')
        available(alt['qualification_available_at'], cutoff, apath + '.qualification_available_at')
        obj(alt['money'], apath + '.money', MONEY_FIELDS)
        amounts = {key: money(alt['money'][key], cutoff, apath + '.money.' + key) for key in MONEY_FIELDS}
        nonfee_cost = sum(amounts[key] for key in MONEY_FIELDS[2:])
        net = amounts['gross_monetizable_benefit'] - amounts['recurring_fee'] - nonfee_cost
        costs[role] = {'net': net, 'before_fee': amounts['gross_monetizable_benefit'] - nonfee_cost}
        result[role] = {'name': alt['name'], 'qualification': alt['qualification'],
                        'annual_net_benefit': out(net), 'annual_total_cost': out(amounts['recurring_fee'] + nonfee_cost),
                        'assumed_inputs': [key for key in MONEY_FIELDS if alt['money'][key]['basis'] == 'assumed']}
    baseline = costs['status_quo']['net']
    for role in ROLES:
        result[role]['delta_net_benefit_vs_status_quo'] = out(costs[role]['net'] - baseline)
    # Unknown comparators cannot be silently discarded from a best-alternative claim.
    determinate = all(alt['qualification'] != 'unknown' for alt in alternatives)
    eligible = [role for role in ROLES if result[role]['qualification'] == 'meets']
    benchmark_roles = [role for role in eligible if role != 'proposed_technology']
    max_fee = None
    if determinate and benchmark_roles and result['proposed_technology']['qualification'] == 'meets':
        best_other = max(costs[role]['net'] for role in benchmark_roles)
        max_fee = costs['proposed_technology']['before_fee'] - best_other
    return {'status': 'calculated', 'money_unit': packet['money_unit'], 'annual_period': period,
            'alternatives': result, 'qualified_best_roles': sorted(role for role in eligible if costs[role]['net'] == max((costs[r]['net'] for r in eligible), default=Decimal(0))) if determinate else None,
            'proposed_max_recurring_fee_to_match_best_qualified_other': None if max_fee is None else out(max_fee),
            'nonnegative_fee_feasible': None if max_fee is None else max_fee >= 0,
            'warning': 'Conditional arithmetic only. Qualification, monetizability, amortization and cost separation need independent review; this is not supplier profit or share value.'}


def scenarios(packet, cutoff):
    path = '$.scenarios'
    obj(packet, path, ('joint_partition', 'weight_basis', 'basis_refs', 'available_at', 'cases'))
    text(packet['joint_partition'], path + '.joint_partition')
    refs(packet['basis_refs'], path + '.basis_refs')
    available(packet['available_at'], cutoff, path + '.available_at')
    if packet['weight_basis'] not in ('unestimated', 'judgment', 'empirical'):
        fail('basis', path, 'Expected unestimated, judgment or empirical')
    weights = {}
    for index, case in enumerate(rows(packet['cases'], path + '.cases', 4)):
        cpath = path + f'.cases[{index}]'
        obj(case, cpath, ('family', 'mechanism', 'refs', 'weight'))
        family = case['family']
        if type(family) is not str or family not in FAMILIES or family in weights:
            fail('scenario', cpath, 'Every competing family must appear exactly once')
        text(case['mechanism'], cpath + '.mechanism')
        refs(case['refs'], cpath + '.refs')
        weights[family] = None if case['weight'] is None else decimal(case['weight'], cpath + '.weight')
    supplied = [value for value in weights.values() if value is not None]
    if supplied and len(supplied) != 4:
        fail('weights', path, 'Weights must be all absent or all supplied')
    if supplied and (sum(supplied) != 1 or any(value > 1 for value in supplied)):
        fail('weights', path, 'Joint scenario weights must sum exactly to one')
    if bool(supplied) == (packet['weight_basis'] == 'unestimated'):
        fail('weights', path, 'Unestimated requires all-null weights; estimated weights require a declared basis')
    return {'status': 'unestimated' if not supplied else 'normalized_input_weights',
            'weights': {key: None if value is None else out(value) for key, value in sorted(weights.items())},
            'weight_basis': packet['weight_basis'], 'calibration_verified': False,
            'warning': 'A complete scenario partition and normalized weights do not establish probability calibration or causal independence.'}


def cohort(packet, cutoff):
    path = '$.reference_class'
    if type(packet) is not dict:
        fail('shape', path, 'Expected an object')
    if packet.get('status') == 'unavailable':
        obj(packet, path, ('status', 'gap', 'attempted_refs', 'next_observation'))
        text(packet['gap'], path + '.gap')
        refs(packet['attempted_refs'], path + '.attempted_refs')
        text(packet['next_observation'], path + '.next_observation')
        return {'status': 'not_estimable', 'success_rate_bounds': None,
                'gap': packet['gap'], 'warning': 'Selected winners cannot supply a missing cohort denominator.'}
    obj(packet, path, ('status', 'selection_rule', 'selection_recorded_at', 'coverage', 'outcome_definition',
                      'horizon_months', 'denominator', 'counts', 'refs', 'available_at'))
    if packet['status'] != 'available' or packet['coverage'] not in ('declared_complete', 'partial', 'unknown'):
        fail('status', path, 'Expected available and a supported coverage declaration')
    for key in ('selection_rule', 'outcome_definition'):
        text(packet[key], path + '.' + key)
    available(packet['selection_recorded_at'], cutoff, path + '.selection_recorded_at')
    available(packet['available_at'], cutoff, path + '.available_at')
    refs(packet['refs'], path + '.refs')
    count(packet['horizon_months'], path + '.horizon_months', True)
    denominator = count(packet['denominator'], path + '.denominator', True)
    obj(packet['counts'], path + '.counts', OUTCOMES)
    counts = {key: count(value, path + '.counts.' + key) for key, value in packet['counts'].items()}
    if sum(counts.values()) != denominator:
        fail('denominator', path, 'All outcomes including pending and unknown must reconcile to the declared denominator')
    unresolved = counts['pending'] + counts['unknown']
    # No extrapolation to an unenumerated population when declared coverage is incomplete.
    bounds = [out(Decimal(counts['success']) / denominator), out(Decimal(counts['success'] + unresolved) / denominator)]
    warnings = ['Bounds apply only to the declared cohort; they are not calibrated future probabilities. Selection timing, horizon comparability and completeness are unverified.']
    if packet['coverage'] != 'declared_complete':
        warnings.append('Incomplete reference-class coverage: population success rate is not estimable.')
    if counts['success'] == denominator:
        warnings.append('Winner-only cohort: inspect selection and missing failures before using a base rate.')
    if unresolved:
        warnings.append('Unresolved outcomes retained in the denominator; do not report resolved-only success rates.')
    return {'status': 'cohort_bounds_only', 'denominator': denominator, 'resolved': denominator - unresolved,
            'unresolved': unresolved, 'success_rate_bounds': bounds,
            'population_success_rate_estimable': False, 'warnings': warnings}


def decode_packet(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail('duplicate_key', '$', 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def invalid(value):
        fail('json_number', '$', 'Floating JSON numbers/NaN/Infinity are forbidden; use decimal strings')
    def integer(value):
        if len(value) > 10:
            fail('json_number', '$', 'JSON integers are bounded counts, not financial values')
        return int(value)
    try:
        packet = json.loads(raw, object_pairs_hook=pairs, parse_float=invalid, parse_constant=invalid, parse_int=integer)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        fail('json', '$', 'Invalid UTF-8 JSON: ' + str(exc))
    if type(packet) is not dict:
        fail('shape', '$', 'Expected object')
    return packet


def calculate(packet):
    obj(packet, '$', ('version', 'subject', 'as_of', 'customer_economics', 'scenarios', 'reference_class'))
    if packet['version'] != VERSION:
        fail('version', '$.version', 'Unsupported packet version')
    text(packet['subject'], '$.subject')
    cutoff = stamp(packet['as_of'], '$.as_of')
    with localcontext(_CONTEXT):
        result = {'version': VERSION, 'status': 'calculated', 'subject': packet['subject'], 'as_of': packet['as_of'],
                  'customer_economics': economics(packet['customer_economics'], cutoff),
                  'scenarios': scenarios(packet['scenarios'], cutoff),
                  'reference_class': cohort(packet['reference_class'], cutoff),
                  'semantic_truth_verified': False}
    encoded = json.dumps(packet, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    result['input_sha256'] = hashlib.sha256(encoded).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        result = calculate(decode_packet(Path(args.input).read_bytes()))
        code = 0
    except AdoptionCheckError as exc:
        result, code = exc.as_dict(), 2
    except OSError as exc:
        result, code = AdoptionCheckError('input_io', '$', str(exc)).as_dict(), 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=output.name + '.', dir=output.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return code


if __name__ == '__main__':
    sys.exit(main())
