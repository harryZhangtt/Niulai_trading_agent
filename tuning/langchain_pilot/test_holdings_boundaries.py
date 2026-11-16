"""Requirement-derived synthetic holdings boundaries; no historical fixtures or I/O.

AC IDs are the frozen ATOMIC_ACCEPTANCE.md criteria. Numeric expectations use
literal values/Fraction, never the maintained analytics as an oracle.
"""
from copy import deepcopy
from decimal import Decimal, getcontext
from fractions import Fraction
import unittest
from unittest.mock import patch

from investment.portfolio.snapshot import (
    SnapshotError, admit_snapshot, analyze_admitted, analyze_snapshot, digest)
from tuning.langchain_pilot.holdings import Events, cases, graph, project, public_case, run_case


def fixture():
    return deepcopy(cases()[0]['inputs'])


def analyze(value, **policy):
    return analyze_snapshot(value['envelope'], value['receipt'], value['taxonomy'],
                            as_of=value['as_of'], **policy)


def metrics(value):
    return analyze(value)['analysis']['accounts'][0]['metrics']


def recount(value, security_types=None):
    envelope = value['envelope']
    holding = envelope['data']['holdings']
    types = security_types or envelope['request']['arguments']['security_types']
    envelope['request']['arguments']['security_types'] = list(types)
    holding['coverage'].update(requestedSecurityTypes=list(types),
        successfulSecurityTypes=list(types), failedSecurityTypes=[],
        positionCount=len(holding['positions']))
    holding['typeReads'] = [dict(securityType=kind, ok=True,
        positionCount=sum(row['securityType'] == kind for row in holding['positions'])) for kind in types]
    return value


def set_path(value, path, replacement):
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = deepcopy(replacement)


class HoldingsBoundaryTests(unittest.TestCase):
    def assert_rejected(self, value, code):
        with patch('investment.portfolio.snapshot.build') as arithmetic:
            with self.assertRaises(SnapshotError) as caught:
                analyze(value)
            self.assertEqual(str(caught.exception), code)
        arithmetic.assert_not_called()

    def test_AC_015_complete_empty_and_failed_empty_are_distinct(self):
        value = public_case('declared-complete-empty')['inputs']
        account = analyze(value)['analysis']['accounts'][0]
        self.assertEqual(account['metrics']['positions_value'], '0')
        self.assertTrue(account['quality']['whole_portfolio_verified'])
        value['envelope']['data']['holdings']['ok'] = False
        self.assert_rejected(value, 'SNAPSHOT_ACCOUNT_UNVERIFIED')

    def test_AC_016_stock_option_cash_scope_counts_visible(self):
        value = public_case('declared-stock-option-cash-scope')['inputs']
        result = analyze(value)
        provenance = result['provenance']
        self.assertEqual(provenance['requested_security_types'], ['STK', 'OPT'])
        self.assertEqual(provenance['successful_security_types'], ['STK', 'OPT'])
        self.assertEqual(provenance['failed_security_types'], [])
        self.assertEqual(provenance['position_count'], 2)
        self.assertEqual([row['positionCount'] for row in provenance['type_reads']], [1, 1])
        self.assertEqual(result['analysis']['accounts'][0]['metrics']['cash'], '25')

    def test_AC_016_observed_type_outside_requested_scope_is_rejected(self):
        value = fixture()
        value['envelope']['data']['holdings']['positions'][1]['securityType'] = 'OPT'
        self.assert_rejected(value, 'SNAPSHOT_POSITION_SCOPE_MISMATCH')

    def test_AC_017_ambiguous_account_list_cannot_choose_first(self):
        value = fixture()
        value['envelope']['data']['holdings'] = [value['envelope']['data']['holdings']] * 2
        self.assert_rejected(value, 'SNAPSHOT_ACCOUNT_UNVERIFIED')

    def test_AC_017_matched_caller_identity_is_not_authentication(self):
        value = fixture()
        for item in value['envelope']['data'].values():
            item['accountRef'] = 'a-new-synthetic-identity'
        result = analyze(value)
        self.assertEqual(result['status'], 'analyzed')
        self.assertEqual(result['provenance']['source_authority'], 'caller_supplied_unverified')
        for field in ('source_authentication_verified', 'live_read_verified', 'lease_release_verified'):
            self.assertIs(result['provenance'][field], False)

    def test_AC_018_missing_position_currency_disables_aggregate(self):
        value = fixture()
        value['envelope']['data']['holdings']['positions'][0].pop('currency')
        account = analyze(value)['analysis']['accounts'][0]
        self.assertEqual(account['currency'], '币种未知')
        self.assertFalse(account['quality']['market_value_complete'])
        for key in ('positions_value', 'gross_positions_value', 'nav', 'cash', 'top1_pct',
                    'hhi', 'embedded_gross_nav_multiple', 'known_proxy_gross_exposure'):
            self.assertIsNone(account['metrics'][key])

    def test_AC_018_missing_summary_currency_does_not_assume_USD(self):
        value = fixture()
        value['envelope']['data']['assets']['summary'].pop('currency')
        account = analyze(value)['analysis']['accounts'][0]
        self.assertEqual(account['currency'], 'USD')
        self.assertIsNone(account['metrics']['nav'])
        self.assertEqual(account['metrics']['positions_value'], '100')

    def test_AC_018_mixed_currencies_never_have_one_combined_total(self):
        value = public_case('mixed-currency-unaggregated')['inputs']
        result = analyze(value)['analysis']
        self.assertEqual([a['currency'] for a in result['accounts']], ['USD', 'HKD'])
        self.assertEqual([a['metrics']['positions_value'] for a in result['accounts']], ['60', '40'])
        self.assertIsNone(result['accounts'][1]['metrics']['nav'])
        self.assertNotIn('positions_value', result)

    def test_AC_019_duplicate_contract_with_conflicting_value_rejects(self):
        value = fixture()
        rows = value['envelope']['data']['holdings']['positions']
        rows[1].update(contractId='synthetic-x', marketValue='999')
        self.assert_rejected(value, 'SNAPSHOT_POSITION_IDENTITY_INVALID')

    def test_AC_019_distinct_options_with_same_ticker_survive(self):
        value = fixture()
        rows = value['envelope']['data']['holdings']['positions']
        for index, row in enumerate(rows):
            row.pop('contractId')
            row.update(symbol='SYNTH_X', securityType='OPT', expiry='2027-01-15',
                       strike=str(100 + index), putCall='CALL')
        recount(value, ['OPT'])
        account = analyze(value)['analysis']['accounts'][0]
        self.assertEqual(account['quality']['row_count'], 2)
        self.assertEqual(account['metrics']['positions_value'], '100')

    def test_AC_019_equivalent_option_strike_and_right_are_duplicate(self):
        value = fixture()
        rows = value['envelope']['data']['holdings']['positions']
        for row in rows:
            row.pop('contractId')
            row.update(symbol='SYNTH_X', securityType='OPT', expiry='2027-01-15',
                       strike='100', putCall='CALL')
        rows[1].update(strike='100.00', putCall='C')
        recount(value, ['OPT'])
        self.assert_rejected(value, 'SNAPSHOT_POSITION_IDENTITY_INVALID')

    def test_AC_019_stock_and_option_with_same_ticker_are_distinct(self):
        value = fixture()
        rows = value['envelope']['data']['holdings']['positions']
        for row in rows:
            row.pop('contractId')
            row['symbol'] = 'SYNTH_X'
        rows[1].update(securityType='OPT', expiry='2027-01-15', strike='100', putCall='PUT')
        recount(value, ['STK', 'OPT'])
        self.assertEqual(metrics(value)['positions_value'], '100')

    def test_AC_020_zero_market_value_is_valid_and_not_missing(self):
        value = fixture()
        for row in value['envelope']['data']['holdings']['positions']:
            row['marketValue'] = '0'
        account = analyze(value)['analysis']['accounts'][0]
        self.assertTrue(account['quality']['market_value_complete'])
        self.assertEqual(account['metrics']['positions_value'], '0')
        self.assertEqual(account['metrics']['gross_positions_value'], '0')
        self.assertIsNone(account['metrics']['hhi'])

    def test_AC_020_missing_market_value_disables_complete_metrics(self):
        value = fixture()
        value['envelope']['data']['holdings']['positions'][0].pop('marketValue')
        account = analyze(value)['analysis']['accounts'][0]
        self.assertFalse(account['quality']['market_value_complete'])
        for key in ('positions_value', 'gross_positions_value', 'top1_pct', 'hhi',
                    'embedded_gross_nav_multiple'):
            self.assertIsNone(account['metrics'][key])

    def test_AC_020_zero_nav_retains_zero_and_denominators_unavailable(self):
        value = public_case('zero-nav-denominator')['inputs']
        actual = metrics(value)
        self.assertEqual(actual['nav'], '0')
        for key in ('cash_pct', 'positions_nav_pct', 'gross_nav_multiple',
                    'embedded_gross_nav_multiple', 'embedded_net_nav_multiple'):
            self.assertIsNone(actual[key])

    def test_AC_020_negative_nav_never_creates_risk_ratio(self):
        value = fixture()
        value['envelope']['data']['assets']['summary']['amounts']['netLiquidation'] = '-125'
        actual = metrics(value)
        self.assertEqual(actual['nav'], '-125')
        self.assertIsNone(actual['cash_pct'])
        self.assertIsNone(actual['embedded_gross_nav_multiple'])

    def test_AC_020_quantity_and_price_cannot_manufacture_market_value(self):
        value = fixture()
        value['envelope']['data']['holdings']['positions'][0].update(
            marketValue=None, quantity='1000', latestPrice='1')
        self.assertIsNone(metrics(value)['positions_value'])

    def test_AC_021_query_age_at_cutoff_is_valid(self):
        value = fixture()
        value['as_of'] = '2026-11-15T12:05:00Z'
        self.assertEqual(analyze(value)['status'], 'analyzed')

    def test_AC_021_query_one_microsecond_past_cutoff_is_stale(self):
        value = fixture()
        value['as_of'] = '2026-11-15T12:05:00.000001Z'
        self.assert_rejected(value, 'SNAPSHOT_QUERY_STALE_OR_FUTURE')

    def test_AC_021_equivalent_timezone_preserves_query_age(self):
        value = fixture()
        value['as_of'] = '2026-11-15T04:01:00-08:00'
        self.assertEqual(metrics(value)['positions_value'], '100')

    def test_AC_021_zero_query_age_policy_has_exact_boundary(self):
        value = fixture()
        value['as_of'] = '2026-11-15T12:00:00Z'
        self.assertEqual(analyze(value, max_age_seconds=0)['status'], 'analyzed')
        value['as_of'] = '2026-11-15T12:00:00.000001Z'
        with self.assertRaisesRegex(SnapshotError, '^SNAPSHOT_QUERY_STALE_OR_FUTURE$'):
            analyze(value, max_age_seconds=0)

    def test_AC_021_fresh_query_does_not_rejuvenate_quote_time(self):
        value = fixture()
        value['envelope']['data']['holdings']['positions'][0]['quoteTime'] = '2020-01-01T00:00:00Z'
        result = analyze(value)['analysis']
        self.assertIsNone(result['source_times']['quote_time'])
        self.assertIsNone(result['accounts'][0]['quality']['quote_time'])

    def test_AC_022_negative_net_exposure_preserves_sign(self):
        value = fixture()
        value['envelope']['data']['holdings']['positions'][1]['marketValue'] = '-80'
        actual = metrics(value)
        self.assertEqual(Fraction(actual['positions_value']), -20)
        self.assertEqual(Fraction(actual['gross_positions_value']), 140)
        self.assertEqual(Fraction(actual['embedded_net_nav_multiple']), Fraction(40, 125))

    def test_AC_022_negative_cash_is_not_clamped(self):
        actual = metrics(public_case('negative-cash')['inputs'])
        self.assertEqual(Fraction(actual['cash']), -25)
        self.assertEqual(Fraction(actual['cash_pct']), -20)

    def test_AC_022_leverage_can_exceed_NAV(self):
        actual = metrics(fixture())
        self.assertEqual(Fraction(actual['embedded_gross_nav_multiple']), Fraction(32, 25))
        self.assertGreater(Fraction(actual['embedded_gross_nav_multiple']), 1)

    def test_AC_022_inverse_leverage_changes_proxy_sign(self):
        value = fixture()
        value['taxonomy']['positions']['SYNTH_X']['daily_leverage'] = -2
        actual = metrics(value)
        self.assertEqual(Fraction(actual['known_proxy_net_exposure']), -80)
        self.assertEqual(Fraction(actual['known_proxy_gross_exposure']), 160)
        self.assertEqual(Fraction(actual['embedded_net_nav_multiple']), Fraction(-16, 25))

    def test_AC_022_unknown_leverage_is_partial_exposure(self):
        value = public_case('unknown-leverage')['inputs']
        account = analyze(value)['analysis']['accounts'][0]
        self.assertEqual(Fraction(account['metrics']['leverage_coverage_pct']), 40)
        self.assertFalse(account['quality']['exposure_complete'])
        self.assertIsNone(account['metrics']['embedded_gross_nav_multiple'])
        self.assertEqual(account['metrics']['positions_value'], '100')

    def test_AC_022_large_exact_decimal_sum_survives_projection(self):
        value = fixture()
        large = '10000000000000000000000000000.01'
        rows = value['envelope']['data']['holdings']['positions']
        rows[0]['marketValue'] = large
        rows[1]['marketValue'] = '0.02'
        expected = Fraction(large) + Fraction('0.02')
        result = analyze(value)
        self.assertEqual(Fraction(result['analysis']['accounts'][0]['metrics']['positions_value']), expected)
        self.assertEqual(Fraction(project(result)['accounts'][0]['metrics']['positions_value']), expected)

    def test_AC_022_currency_scaling_preserves_ratios_and_scales_money(self):
        original = fixture()
        scaled = fixture()
        for row in scaled['envelope']['data']['holdings']['positions']:
            for key in ('marketValue', 'unrealizedPnl'):
                row[key] = str(Decimal(row[key]) * Decimal('7.25'))
        for key in ('netLiquidation', 'cash', 'buyingPower'):
            amounts = scaled['envelope']['data']['assets']['summary']['amounts']
            amounts[key] = str(Decimal(amounts[key]) * Decimal('7.25'))
        before, after = metrics(original), metrics(scaled)
        for key in ('cash_pct', 'top1_pct', 'hhi', 'embedded_gross_nav_multiple'):
            self.assertEqual(Fraction(before[key]), Fraction(after[key]))
        for key in ('positions_value', 'gross_positions_value', 'nav', 'cash', 'unrealized_pnl'):
            self.assertEqual(Fraction(after[key]), Fraction(before[key]) * Fraction('7.25'))

    def test_AC_022_permutation_keeps_all_summary_metrics(self):
        original = fixture()
        reordered = fixture()
        reordered['envelope']['data']['holdings']['positions'].reverse()
        self.assertEqual(metrics(original), metrics(reordered))

    def test_AC_022_split_position_preserves_sums_but_changes_concentration(self):
        original = fixture()
        split = fixture()
        rows = split['envelope']['data']['holdings']['positions']
        row = deepcopy(rows[0])
        row.update(contractId='synthetic-x-split', marketValue='30', unrealizedPnl='2.5')
        rows[0].update(marketValue='30', unrealizedPnl='2.5')
        rows.append(row)
        recount(split)
        before, after = metrics(original), metrics(split)
        for key in ('positions_value', 'gross_positions_value', 'unrealized_pnl',
                    'embedded_gross_nav_multiple'):
            self.assertEqual(Fraction(before[key]), Fraction(after[key]))
        self.assertEqual(Fraction(after['hhi']), 3400)
        self.assertEqual(Fraction(after['top1_pct']), 40)

    def test_AC_023_supplied_daily_fields_cannot_replace_missing_contract(self):
        value = fixture()
        value['envelope']['data']['holdings']['positions'][0]['dailyPnl'] = '999'
        value['envelope']['data']['assets']['summary']['amounts']['reportedTodayPnl'] = '888'
        account = analyze(value)['analysis']['accounts'][0]
        self.assertIsNone(account['metrics']['daily_pnl'])
        self.assertEqual(account['metrics']['daily_pnl_status'], 'unavailable')
        self.assertEqual(account['daily_top_gainers'], [])
        self.assertEqual(account['daily_top_losers'], [])
        self.assertTrue(all(row['dailyPnl'] is None for row in account['holdings']))

    def test_AC_024_repeated_unknown_checkpoint_never_replays(self):
        events = Events()
        for _ in range(2):
            self.assertEqual(run_case('unknown-checkpoint', callbacks=[events]),
                {'status': 'rejected', 'error': 'SNAPSHOT_RECEIPT_UNCONFIRMED'})
        self.assertFalse(any(row['event'] == 'tool_start' for row in events.rows))

    def test_AC_025_analytics_exception_stays_closed_and_input_unchanged(self):
        value = fixture()
        before = deepcopy(value)
        with patch('investment.portfolio.snapshot.build', side_effect=ValueError('private-canary')):
            with self.assertRaises(SnapshotError) as caught:
                analyze(value)
        self.assertEqual(str(caught.exception), 'SNAPSHOT_ANALYTICS_INPUT_INVALID')
        self.assertEqual(value, before)

    def test_AC_025_analytics_reuses_maintained_build_once(self):
        from niulai.holdings.analytics import build
        value = fixture()
        with patch('investment.portfolio.snapshot.build', wraps=build) as arithmetic:
            result = analyze(value)
        arithmetic.assert_called_once()
        self.assertEqual(result['status'], 'analyzed')

    def test_AC_025_decimal_context_is_restored_after_analysis(self):
        precision = getcontext().prec
        analyze(fixture())
        self.assertEqual(getcontext().prec, precision)

    def test_AC_020_numeric_expansion_is_bounded(self):
        value = fixture()
        value['envelope']['data']['holdings']['positions'][0]['marketValue'] = '1e999999'
        self.assert_rejected(value, 'SNAPSHOT_AMOUNT_SIZE_LIMIT')

    def test_AC_020_JSON_nonfinite_number_is_not_exportable(self):
        value = fixture()
        value['envelope']['data']['holdings']['positions'][0]['marketValue'] = float('nan')
        self.assert_rejected(value, 'SNAPSHOT_JSON_INVALID')

    def test_AC_013_unencodable_unicode_has_closed_diagnostic(self):
        value = fixture()
        value['receipt']['extra'] = '\ud800'
        self.assert_rejected(value, 'SNAPSHOT_JSON_INVALID')

    def test_AC_013_cyclic_input_has_closed_diagnostic(self):
        value = fixture()
        value['receipt']['extra'] = value['receipt']
        self.assert_rejected(value, 'SNAPSHOT_JSON_INVALID')

    def test_AC_013_oversized_input_rejected_before_analytics(self):
        value = fixture()
        value['receipt']['extra'] = 'synthetic-data-' * 150000
        self.assert_rejected(value, 'SNAPSHOT_SIZE_LIMIT')

    def test_AC_021_age_policy_is_typed_and_bounded(self):
        for policy in (True, -1, 86401, '300', None):
            with self.assertRaisesRegex(SnapshotError, '^SNAPSHOT_AGE_POLICY_INVALID$'):
                analyze(fixture(), max_age_seconds=policy)

    def test_AC_025_malformed_taxonomy_has_closed_diagnostic(self):
        value = fixture()
        value['taxonomy'] = {'positions': {'SYNTH_X': ['private-canary']}}
        with self.assertRaises(SnapshotError) as caught:
            analyze(value)
        self.assertEqual(str(caught.exception), 'SNAPSHOT_ANALYTICS_INPUT_INVALID')

    def test_AC_025_unexpected_analytics_failure_has_closed_diagnostic(self):
        with patch('investment.portfolio.snapshot.build', side_effect=RuntimeError('private-canary')):
            with self.assertRaises(SnapshotError) as caught:
                analyze(fixture())
        self.assertEqual(str(caught.exception), 'SNAPSHOT_ANALYTICS_INPUT_INVALID')

    def test_AC_025_unadmitted_object_cannot_claim_success(self):
        with self.assertRaisesRegex(SnapshotError, '^SNAPSHOT_ANALYTICS_INPUT_INVALID$'):
            analyze_admitted({}, {})

    def test_AC_021_quote_after_query_cannot_claim_snapshot_quote(self):
        value = fixture()
        value['envelope']['quote_observation'] = dict(quote_at='2026-11-15T12:00:30Z', cutoff=None)
        self.assert_rejected(value, 'SNAPSHOT_QUOTE_TIME_FUTURE')

    def test_AC_030_original_eight_selectors_remain_in_order(self):
        self.assertEqual([case['id'] for case in cases()[:8]], ['nominal', 'empty-requested-scope',
            'missing-market-value', 'currency-mismatch', 'partial-read', 'unknown-checkpoint',
            'stale-query', 'account-mismatch'])

    def test_AC_021_project_rates_have_declared_rounding_and_money_stays_exact(self):
        result = run_case('public-holdings-long-short')['accounts'][0]['metrics']
        self.assertEqual(result['positions_value'], '700')
        self.assertEqual(result['gross_positions_value'], '1100')
        self.assertEqual(result['top1_pct'], '54.545454545455')
        self.assertEqual(result['hhi'], '4049.586776859504')

    def test_AC_011_native_tool_span_belongs_to_portfolio_node(self):
        events = Events()
        run_case('nominal', callbacks=[events])
        node = next(r for r in events.rows if r.get('name') == 'portfolio_analysis')
        tools = [r for r in events.rows if r['event'] == 'tool_start']
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]['name'], 'portfolio_analysis_tool')
        self.assertEqual(tools[0]['parent_run_id'], node['run_id'])
        self.assertTrue(any(r['event'] == 'tool_end' and r['run_id'] == tools[0]['run_id'] for r in events.rows))

    def test_AC_012_tool_error_is_traced_and_cannot_be_success(self):
        events = Events()
        with patch('investment.portfolio.snapshot.build', side_effect=ValueError('private-canary')):
            result = run_case('nominal', callbacks=[events])
        self.assertEqual(result, {'status': 'rejected', 'error': 'SNAPSHOT_ANALYTICS_INPUT_INVALID'})
        self.assertTrue(any(r['event'] == 'tool_error' for r in events.rows))
        self.assertNotIn('private-canary', str(events.rows))

    def test_AC_013_invalid_public_selector_is_fenced_before_callback(self):
        class Sink(Events):
            def on_chain_start(self, serialized, inputs, **kwargs):
                raise AssertionError('raw input reached callback')
        for value in ({'fixture': 'nominal', 'secret': 'private-canary'}, ['nominal'], None, True):
            with self.assertRaisesRegex(SnapshotError, '^PORTFOLIO_PUBLIC_CASE_ONLY$'):
                run_case(value, callbacks=[Sink()])


REJECTIONS = [
    ('AC_024_receipt_status', ('receipt', 'status'), 'unknown', 'SNAPSHOT_RECEIPT_UNCONFIRMED'),
    ('AC_024_receipt_release', ('receipt', 'release_requested'), False, 'SNAPSHOT_RECEIPT_UNCONFIRMED'),
    ('AC_024_receipt_reconciliation', ('receipt', 'reconciliation_required'), True, 'SNAPSHOT_RECEIPT_UNCONFIRMED'),
    ('AC_024_receipt_assets', ('receipt', 'assets_read'), False, 'SNAPSHOT_RECEIPT_UNCONFIRMED'),
    ('AC_024_receipt_attempt', ('receipt', 'attempt_id'), '', 'SNAPSHOT_RECEIPT_UNCONFIRMED'),
    ('AC_015_envelope_partial', ('envelope', 'source_read_status'), 'partial', 'SNAPSHOT_READ_INCOMPLETE'),
    ('AC_015_cached_fallback', ('envelope', 'cached_fallback_used'), True, 'SNAPSHOT_READ_INCOMPLETE'),
    ('AC_017_missing_account', ('envelope', 'data', 'holdings', 'accountRef'), None, 'SNAPSHOT_ACCOUNT_MISMATCH'),
    ('AC_017_unchecked_identity', ('envelope', 'data', 'assets', 'accountIdentityChecked'), False, 'SNAPSHOT_ACCOUNT_UNVERIFIED'),
    ('AC_017_identity_mismatch', ('envelope', 'data', 'assets', 'accountRef'), 'synthetic-other', 'SNAPSHOT_ACCOUNT_MISMATCH'),
    ('AC_016_missing_type_result', ('envelope', 'data', 'holdings', 'typeReads'), [], 'SNAPSHOT_TYPE_COVERAGE_INCOMPLETE'),
    ('AC_016_wrong_type_count', ('envelope', 'data', 'holdings', 'typeReads', 0, 'positionCount'), 0, 'SNAPSHOT_TYPE_COUNT_MISMATCH'),
    ('AC_016_bool_position_count', ('envelope', 'data', 'holdings', 'coverage', 'positionCount'), True, 'SNAPSHOT_POSITIONS_INVALID'),
    ('AC_016_missing_type_coverage', ('envelope', 'data', 'holdings', 'coverage', 'successfulSecurityTypes'), [], 'SNAPSHOT_TYPE_COVERAGE_INCOMPLETE'),
    ('AC_016_duplicate_requested_type', ('envelope', 'request', 'arguments', 'security_types'), ['STK', 'STK'], 'SNAPSHOT_REQUEST_INVALID'),
    ('AC_018_nested_currency', ('envelope', 'data', 'holdings', 'positions', 0, 'currency'), {'secret': 'private-canary'}, 'SNAPSHOT_CURRENCY_INVALID'),
    ('AC_018_lowercase_currency', ('envelope', 'data', 'assets', 'summary', 'currency'), 'usd', 'SNAPSHOT_CURRENCY_INVALID'),
    ('AC_019_nested_contract', ('envelope', 'data', 'holdings', 'positions', 0, 'contractId'), {'secret': 'private-canary'}, 'SNAPSHOT_POSITION_IDENTITY_INVALID'),
    ('AC_019_bool_contract', ('envelope', 'data', 'holdings', 'positions', 0, 'contractId'), True, 'SNAPSHOT_POSITION_IDENTITY_INVALID'),
    ('AC_019_nested_symbol', ('envelope', 'data', 'holdings', 'positions', 0, 'symbol'), ['SYNTH_X'], 'SNAPSHOT_POSITION_IDENTITY_INVALID'),
    ('AC_020_invalid_summary', ('envelope', 'data', 'assets', 'summary'), [], 'SNAPSHOT_ASSET_SUMMARY_INVALID'),
    ('AC_020_invalid_amount_map', ('envelope', 'data', 'assets', 'summary', 'amounts'), None, 'SNAPSHOT_ASSET_SUMMARY_INVALID'),
    ('AC_021_naive_asof', ('as_of',), '2026-11-15T12:01:00', 'SNAPSHOT_TIME_INVALID'),
    ('AC_021_time_order', ('envelope', 'query_started_at'), '2026-11-15T12:00:01Z', 'SNAPSHOT_TIME_ORDER_INVALID'),
    ('AC_021_asset_outside_query', ('envelope', 'data', 'assets', 'queryCompletedAt'), '2026-11-15T12:00:01Z', 'SNAPSHOT_TIME_ORDER_INVALID'),
]


def rejection_test(path, replacement, code):
    def test(self):
        value = fixture()
        set_path(value, path, replacement)
        self.assert_rejected(value, code)
    return test


for name, path, replacement, code in REJECTIONS:
    setattr(HoldingsBoundaryTests, 'test_' + name, rejection_test(path, replacement, code))


def unavailable_test(field, replacement):
    def test(self):
        value = fixture()
        if field == 'marketValue':
            value['envelope']['data']['holdings']['positions'][0][field] = replacement
            account = analyze(value)['analysis']['accounts'][0]
            self.assertFalse(account['quality']['market_value_complete'])
            self.assertIsNone(account['metrics']['positions_value'])
        else:
            value['envelope']['data']['assets']['summary']['amounts'][field] = replacement
            actual = metrics(value)
            key = 'nav' if field == 'netLiquidation' else 'cash'
            self.assertIsNone(actual[key])
            self.assertIsNone(actual['cash_pct'])
    return test


for field in ('marketValue', 'netLiquidation', 'cash'):
    for name, replacement in [('null', None), ('malformed', 'not-an-amount'),
                              ('boolean', True), ('nan_string', 'NaN'), ('infinite_string', 'Infinity')]:
        setattr(HoldingsBoundaryTests, f'test_AC_020_{field}_{name}', unavailable_test(field, replacement))


if __name__ == '__main__':
    unittest.main()
