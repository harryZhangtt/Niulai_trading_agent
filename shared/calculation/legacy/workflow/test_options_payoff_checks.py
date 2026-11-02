"""Synthetic option arithmetic tests. No actual quotes or recommendations."""
import copy
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import options_payoff_checks as o


def example_packet(kind='long_call'):
    def quote(bid, ask, size=100):
        return {'bid': str(bid), 'ask': str(ask), 'bid_size': size, 'ask_size': size,
                'timestamp': '2026-10-23T18:59:30Z', 'feed_status': 'realtime',
                'feed_id': 'SYNTHETIC-test-only', 'source_ref': 'synthetic:fixture-not-market-data'}
    def leg(strike, bid, ask):
        return {'underlying': 'SYNTH', 'contract_id': 'SYNTH270618C' + f'{strike * 1000:08d}',
                'right': 'call', 'strike': str(strike), 'expiry': '2027-06-18', 'exercise_style': 'american',
                'multiplier': 100, 'standard_deliverable_confirmed': True, 'quote': quote(bid, ask)}
    return {'version': o.VERSION, 'subject': 'SYNTH', 'as_of': '2026-10-23T19:00:00Z',
            'mode': 'live', 'quote_policy': {'max_age_seconds': 60, 'max_quote_skew_seconds': 10},
            'budget': {'amount': '1000', 'currency': 'USD', 'idle_cash_return': '0'},
            'fees': {'option_per_contract_per_leg': '1', 'option_fixed_per_leg': '0',
                     'stock_per_share': '0', 'stock_fixed': '0'},
            'strategy': {'kind': kind, 'long_leg': leg(100, '4.5', '5'),
                         'short_leg': leg(110, '2', '2.5') if kind == 'bull_call_debit_spread' else None},
            'underlying_quote': {'symbol': 'SYNTH', 'quote': quote('99', '100', 10000)},
            'share_comparison': {'fractional': False, 'increment': '1'},
            'expiry_assumption': o.EXPIRY_ASSUMPTION,
            'expiry_stock_prices': ['0', '90', '100', '103.02', '105.01', '110', '120', '1000']}


class OptionsTests(unittest.TestCase):
    def setUp(self): self.p = example_packet()
    def result(self): return o.calculate(self.p)
    def options(self): return self.result()['budget_cases']['requested']['options']
    def long(self): return self.p['strategy']['long_leg']
    def spread(self): self.p = example_packet('bull_call_debit_spread')
    def rejection(self, code):
        with self.assertRaises(o.OptionsCheckError) as caught: self.result()
        self.assertEqual(caught.exception.code, code)
    def test_occ_compact_and_padded_are_same_contract(self):
        compact = o.parse_contract_id(self.long()['contract_id'])
        self.long()['contract_id'] = 'SYNTH 270618C00100000'
        self.assertEqual(o.parse_contract_id(self.long()['contract_id']), compact)
        self.assertEqual(self.options()['opening_cash_required'], '501')
    def test_occ_exact_strike_thousandths(self):
        self.long().update(contract_id='SYNTH270618C00100125', strike='100.125')
        self.assertEqual(self.options()['breakeven_stock_price'], '105.135')
    def test_occ_single_character_identity_mutations(self):
        for contract_id, code in [('SYNTH270619C00100000', 'contract_identity'),
                                  ('SYNTH270618P00100000', 'contract_identity'),
                                  ('SYNTH270618C00100001', 'contract_identity'),
                                  ('SYNTH270618C00110000', 'contract_identity'),
                                  ('SYNTA270618C00100000', 'root_mapping')]:
            with self.subTest(contract_id=contract_id):
                self.p = example_packet(); self.long()['contract_id'] = contract_id
                self.rejection(code)
    def test_occ_malformed_symbol_and_invalid_dates(self):
        for symbol in ['SYNTH270230C00100000', 'SYNTH270000C00100000',
                       'SYNTH270618c00100000', 'synth270618C00100000',
                       'O:SYNTH270618C00100000', ' SYNTH270618C00100000',
                       'SYNTH  270618C00100000', 'SY NTH270618C00100000',
                       'SYNTH270618C0100000', 'SYNTH270618C00000000']:
            with self.subTest(symbol=symbol):
                self.p = example_packet(); self.long()['contract_id'] = symbol
                # Leading whitespace is rejected by shared strict text input.
                self.rejection('text' if symbol.startswith(' ') else 'contract_symbol')
    def test_occ_strike_scale_confusion_rejected(self):
        self.long()['contract_id'] = 'SYNTH270618C00000100'
        self.rejection('contract_identity')
    def test_occ_century_must_match_explicit_leg_date(self):
        self.long()['expiry'] = '2127-06-18'; self.rejection('contract_identity')
    def test_occ_numeric_root_unsupported_despite_standard_boolean(self):
        self.p['subject'] = self.long()['underlying'] = self.p['underlying_quote']['symbol'] = 'SYNTH1'
        self.long()['contract_id'] = 'SYNTH1270618C00100000'
        self.rejection('unsupported_root')
    def mapped_root(self):
        self.p['subject'] = self.long()['underlying'] = self.p['underlying_quote']['symbol'] = 'BRK/B'
        self.long()['contract_id'] = 'BRK.B270618C00100000'
        self.long()['root_mapping'] = {'root': 'BRK.B', 'underlying': 'BRK/B', 'verified': True,
                                      'source_ref': 'synthetic:contract-directory-not-market-data'}
    def test_occ_explicit_verified_distinct_root_mapping(self):
        self.mapped_root(); self.assertEqual(self.options()['opening_cash_required'], '501')
    def test_occ_distinct_root_mapping_cannot_be_assumed(self):
        self.mapped_root(); del self.long()['root_mapping']; self.rejection('root_mapping')
    def test_occ_mapping_values_must_bind_both_identities(self):
        for key, value in [('root', 'BRK.A'), ('underlying', 'BRK/A'), ('verified', False), ('verified', 1)]:
            with self.subTest(key=key, value=value):
                self.p = example_packet(); self.mapped_root(); self.long()['root_mapping'][key] = value
                self.rejection('root_mapping')
    def test_occ_mapping_source_required_and_shape_strict(self):
        self.mapped_root(); self.long()['root_mapping']['source_ref'] = ''; self.rejection('text')
        self.long()['root_mapping'] = None; self.rejection('shape')
    def test_put_symbol_and_fields_are_not_supported_by_call_calculator(self):
        self.long().update(contract_id='SYNTH270618P00100000', right='put'); self.rejection('contract')
    def test_multiplier_1000_rejected(self):
        self.long()['multiplier'] = 1000; self.rejection('deliverable')
    def test_long_call_budget_fee_boundary(self):
        r = self.options()
        self.assertEqual(r['max_affordable_contracts'], 1)
        self.assertEqual(r['opening_cash_required'], '501')
        self.assertEqual(r['unallocated_cash'], '499')
        self.assertEqual(r['breakeven_stock_price'], '105.01')
        self.assertEqual(r['max_loss_amount'], '501')
        self.assertIsNone(r['max_profit']); self.assertEqual(r['max_profit_kind'], 'unbounded')
    def test_budget_exact_boundary(self):
        self.p['budget']['amount'] = '1002'
        self.assertEqual(self.options()['modeled_contracts'], 2)
        self.p['budget']['amount'] = '1001.99'
        self.assertEqual(self.options()['modeled_contracts'], 1)
    def test_no_affordable_contract(self):
        self.p['budget']['amount'] = '500'
        r = self.options()
        self.assertEqual(r['modeled_contracts'], 0); self.assertEqual(r['max_loss_amount'], '0')
        self.assertIsNone(r['breakeven_stock_price']); self.assertEqual(r['max_profit_kind'], 'no_position')
        self.assertTrue(all(row['ending_wealth'] == '500' for row in r['grid']))
    def test_long_grid_boundary_and_breakeven(self):
        grid = {r['expiry_stock_price']: r for r in self.options()['grid']}
        self.assertEqual(grid['0']['pnl'], '-501'); self.assertEqual(grid['100']['pnl'], '-501')
        self.assertEqual(grid['105.01']['pnl'], '0'); self.assertEqual(grid['110']['pnl'], '499')
        self.assertEqual(grid['110']['ending_wealth'], '1499')
    def test_spread_conservative_execution(self):
        self.spread(); r = self.result(); position = r['budget_cases']['requested']['options']
        self.assertEqual(r['conservative_debit_per_share'], '3')
        self.assertEqual(position['modeled_contracts'], 3)
        self.assertEqual(position['opening_cash_required'], '906')
        self.assertEqual(position['max_profit'], '2094')
        self.assertEqual(position['breakeven_stock_price'], '103.02')
        grid = {row['expiry_stock_price']: row['pnl'] for row in position['grid']}
        self.assertEqual(grid['103.02'], '0'); self.assertEqual(grid['110'], '2094'); self.assertEqual(grid['1000'], '2094')
    def test_spread_topology(self):
        self.spread(); self.p['strategy']['short_leg'].update(strike='90', contract_id='SYNTH270618C00090000'); self.rejection('spread')
    def test_spread_different_expiry(self):
        self.spread(); self.p['strategy']['short_leg'].update(expiry='2027-07-16', contract_id='SYNTH270716C00110000'); self.rejection('spread')
    def test_naked_short_rejected(self):
        self.p['strategy']['long_leg'] = None; self.rejection('shape')
    def test_long_call_cannot_have_short(self):
        self.p['strategy']['short_leg'] = copy.deepcopy(self.long()); self.rejection('strategy')
    def test_spread_missing_short(self):
        self.p['strategy']['kind'] = 'bull_call_debit_spread'; self.rejection('strategy')
    def test_credit_or_zero_debit_rejected(self):
        for bid in ['5', '6']:
            with self.subTest(bid=bid):
                self.spread(); self.p['strategy']['short_leg']['quote'].update(bid=bid, ask='7'); self.rejection('debit')
    def test_debit_at_or_above_width_rejected(self):
        self.spread(); self.long()['quote'].update(bid='10', ask='12'); self.rejection('debit')
    def test_fee_dominated_spread_has_no_breakeven(self):
        self.spread(); self.p['fees']['option_per_contract_per_leg'] = '400'
        self.p['budget']['amount'] = '1100'
        r = self.options()
        self.assertEqual(r['max_profit'], '-100')
        self.assertIsNone(r['breakeven_stock_price']); self.assertFalse(r['positive_profit_possible_at_expiry'])
    def test_fixed_fee_applies_per_leg_not_per_contract(self):
        self.spread(); self.p['fees']['option_fixed_per_leg'] = '5'
        self.assertEqual(self.options()['opening_fees'], '16')
    def test_usd1000_case_independent_of_requested_budget(self):
        self.p['budget']['amount'] = '4000'
        r = self.result()['budget_cases']
        self.assertEqual(r['requested']['options']['max_affordable_contracts'], 7)
        self.assertEqual(r['usd_1000']['options']['max_affordable_contracts'], 1)
    def test_same_budget_shares(self):
        r = self.result()['budget_cases']['requested']['shares']
        self.assertEqual(r['modeled_shares'], '10'); self.assertEqual(r['opening_cash_required'], '1000')
        grid = {row['expiry_stock_price']: row for row in r['grid']}
        self.assertEqual(grid['0']['pnl'], '-1000'); self.assertEqual(grid['110']['pnl'], '100')
        self.assertEqual(grid['110']['ending_wealth'], '1100')
    def test_fractional_explicit(self):
        self.p['budget']['amount'] = '1050'; self.p['share_comparison'] = {'fractional': True, 'increment': '0.01'}
        self.assertEqual(self.result()['budget_cases']['requested']['shares']['modeled_shares'], '10.5')
    def test_fractional_implicit_rejected(self):
        self.p['share_comparison']['increment'] = '0.01'; self.rejection('fractional')
    def test_fractional_incompatible_increment_rejected(self):
        self.p['share_comparison'] = {'fractional': True, 'increment': '0.3'}; self.rejection('fractional')
    def test_stock_fees_in_budget(self):
        self.p['fees'].update(stock_per_share='1', stock_fixed='5')
        r = self.result()['budget_cases']['requested']['shares']
        self.assertEqual(r['modeled_shares'], '9'); self.assertEqual(r['opening_cash_required'], '914')
    def test_unknown_depth_is_research_only(self):
        self.long()['quote']['ask_size'] = None
        r = self.result(); self.assertTrue(r['research_only']); self.assertFalse(r['live_input_gate_passed'])
        self.assertIsNone(r['budget_cases']['requested']['options']['displayed_depth_capacity_contracts'])
    def test_depth_caps_modeled_contracts(self):
        self.p['budget']['amount'] = '10000'; self.long()['quote']['ask_size'] = 2
        r = self.options(); self.assertEqual(r['max_affordable_contracts'], 19); self.assertEqual(r['modeled_contracts'], 2)
    def test_spread_depth_uses_short_bid_size(self):
        self.spread(); self.p['strategy']['short_leg']['quote']['bid_size'] = 1
        self.assertEqual(self.options()['modeled_contracts'], 1)
    def test_partial_unknown_depth_retains_known_zero(self):
        self.spread(); self.long()['quote']['ask_size'] = 0
        self.p['strategy']['short_leg']['quote']['bid_size'] = None
        r = self.options()
        self.assertEqual(r['modeled_contracts'], 0)
        self.assertEqual(r['known_leg_depth_cap_contracts'], 0)
        self.assertIsNone(r['displayed_depth_capacity_contracts'])
        self.assertFalse(r['displayed_depth_complete'])
        self.assertTrue(self.result()['research_only'])
    def test_partial_unknown_depth_retains_known_positive_cap(self):
        self.spread(); self.long()['quote']['ask_size'] = None
        self.p['strategy']['short_leg']['quote']['bid_size'] = 1
        r = self.options()
        self.assertEqual(r['max_affordable_contracts'], 3)
        self.assertEqual(r['modeled_contracts'], 1)
        self.assertEqual(r['known_leg_depth_cap_contracts'], 1)
        self.assertIsNone(r['displayed_depth_capacity_contracts'])
        self.assertTrue(self.result()['research_only'])
    def test_zero_size_does_not_fill(self):
        self.long()['quote']['ask_size'] = 0
        self.assertEqual(self.options()['modeled_contracts'], 0); self.assertTrue(self.result()['research_only'])
    def test_adjusted_and_unknown_deliverables_rejected(self):
        for value in [False, None, 1, 'true']:
            with self.subTest(value=value):
                self.long()['standard_deliverable_confirmed'] = value; self.rejection('deliverable')
    def test_research_unverified_explicit_standard_assumption(self):
        self.p['mode'] = 'indicative'
        self.long().update(standard_deliverable_confirmed=False, deliverable_assumption='hypothetical_standard_100_shares', adjustment_status='unknown')
        r = self.result()
        self.assertTrue(r['research_only']); self.assertFalse(r['contract_deliverable_verified'])
        self.assertEqual(r['budget_cases']['requested']['options']['opening_cash_required'], '501')
        self.p['mode'] = 'live'; self.rejection('deliverable')
    def test_known_adjusted_never_supported(self):
        self.p['mode'] = 'indicative'
        self.long().update(standard_deliverable_confirmed=False, deliverable_assumption='hypothetical_standard_100_shares', adjustment_status='adjusted')
        self.rejection('deliverable')
    def test_verified_assumption_conflict(self):
        self.long().update(deliverable_assumption='hypothetical_standard_100_shares', adjustment_status='unknown')
        self.rejection('deliverable')
    def test_research_unknown_timestamp_not_replaced(self):
        self.p['mode'] = 'indicative'; self.long()['quote']['timestamp'] = None
        r = self.result()
        self.assertTrue(r['research_only']); self.assertEqual(r['quote_freshness'], 'unknown')
        self.assertIsNone(r['quote_skew_seconds'])
        self.assertIsNone(r['quote_provenance'][1]['timestamp']); self.assertIsNone(r['quote_provenance'][1]['age_seconds'])
        self.p['mode'] = 'live'; self.rejection('timestamp')
    def test_nonstandard_multiplier(self):
        for value in [10, 150, True, '100']:
            with self.subTest(value=value):
                self.long()['multiplier'] = value; self.rejection('deliverable')
    def test_underlying_identity(self):
        self.long()['underlying'] = 'OTHER'; self.rejection('underlying')
    def test_put_not_supported(self):
        self.long()['right'] = 'put'; self.rejection('contract')
    def test_stale_live_rejected(self):
        self.long()['quote']['timestamp'] = '2026-10-23T18:58:00Z'; self.rejection('stale_quote')
    def test_stale_historical_labelled(self):
        self.p['mode'] = 'historical'; self.long()['quote']['timestamp'] = '2026-10-23T18:58:00Z'
        r = self.result(); self.assertTrue(r['research_only']); self.assertFalse(r['live_input_gate_passed'])
        self.assertTrue(any('older' in w for w in r['warnings']))
    def test_future_quote_rejected_even_historical(self):
        for mode in ['live', 'historical']:
            with self.subTest(mode=mode):
                self.p['mode'] = mode; self.long()['quote']['timestamp'] = '2026-10-23T19:00:01Z'; self.rejection('future_quote')
    def test_delayed_feed_cannot_be_live(self):
        self.long()['quote']['feed_status'] = 'delayed'; self.rejection('feed')
    def test_indicative_labelled(self):
        self.p['mode'] = 'indicative'; self.long()['quote']['feed_status'] = 'indicative'
        self.assertTrue(self.result()['research_only'])
    def test_crossed_quote(self):
        self.long()['quote']['bid'] = '6'; self.rejection('crossed_quote')
    def test_quote_skew(self):
        self.long()['quote']['timestamp'] = '2026-10-23T18:59:59Z'; self.rejection('asynchronous_quotes')
    def test_expired_live_contract(self):
        self.long().update(expiry='2026-10-22', contract_id='SYNTH261022C00100000'); self.rejection('expired_quote')
    def test_expiry_day_not_live_eligible_without_session_check(self):
        self.long().update(expiry='2026-10-23', contract_id='SYNTH261023C00100000'); self.assertTrue(self.result()['research_only'])
    def test_timestamp_strict(self):
        for value in ['2026-10-23T19:00:00+00:99', '2026-10-23T24:00:00Z', '2026-10-23T19:60:00Z', '2026-10-23T19:00:60Z']:
            with self.subTest(value=value):
                self.p['as_of'] = value; self.rejection('timestamp')
    def test_subsecond_freshness_exact(self):
        self.p['as_of'] = '2026-10-23T19:00:30.000001Z'; self.rejection('stale_quote')
    def test_numeric_strict(self):
        for value in [5.0, True, 'NaN', 'Infinity', '1e4', '-1']:
            with self.subTest(value=value):
                self.long()['strike'] = value; self.rejection('number')
    def test_monotone_and_spread_cap(self):
        for kind in ['long_call', 'bull_call_debit_spread']:
            self.p = example_packet(kind)
            values = [Decimal(row['pnl']) for row in self.options()['grid']]
            self.assertEqual(values, sorted(values))
            if kind == 'bull_call_debit_spread': self.assertEqual(values[-1], Decimal(self.options()['max_profit']))
    def test_no_probability_or_recommendation(self):
        r = self.result(); self.assertIsNone(r['recommendation']); self.assertFalse(r['semantic_truth_verified'])
        self.assertNotIn('expected_return', r); self.assertNotIn('probability', r)
    def test_grid_duplicate(self):
        self.p['expiry_stock_prices'].append('100.0'); self.rejection('grid')
    def test_strict_json(self):
        for raw in [b'[]', b'null', b'{"a":NaN}', b'{"a":1.2}', b'{"a":1,"a":2}', b'{"a":' + b'9'*5000 + b'}']:
            with self.subTest(raw=raw), self.assertRaises(o.OptionsCheckError): o.decode_packet(raw)
    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp, output = Path(tmp)/'input.json', Path(tmp)/'output.json'; inp.write_text(json.dumps(self.p))
            args = [sys.executable, o.__file__, '--input', str(inp), '--output', str(output)]
            run = subprocess.run(args, capture_output=True); self.assertEqual(run.returncode, 0, run.stderr.decode())
            self.assertEqual(json.loads(output.read_text()), self.result())
            inp.unlink(); run = subprocess.run(args, capture_output=True)
            self.assertEqual(run.returncode, 2); self.assertEqual(json.loads(output.read_text())['error']['code'], 'input_io')


if __name__ == '__main__': unittest.main()
