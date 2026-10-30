"""Synthetic arithmetic/guard tests, not empirical calibration evidence."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import adoption_checks as a

STAMP = '2026-10-23T23:00:00Z'


def example_packet():
    """Complete synthetic interface; replace every assumption for research."""
    def money(value):
        return {'value': str(value), 'basis': 'assumed', 'refs': ['synthetic:assumption'],
                'available_at': STAMP, 'note': 'Synthetic annual cash-equivalent assumption.'}
    costs = {'status_quo': [1000, 0, 0, 100, 0, 0],
             'simple_alternative': [1100, 50, 20, 50, 0, 10],
             'proposed_technology': [1400, 200, 100, 150, 100, 50]}
    return {'version': a.VERSION, 'subject': 'SYNTHETIC', 'as_of': STAMP,
            'customer_economics': {'status': 'available', 'job': 'Complete one fixed annual workload.',
                'service_requirement': 'Same verified correctness, latency and legal requirements.',
                'money_unit': 'currency:USD', 'annual_period': {'start': '2027-01-01', 'end': '2027-12-31'},
                'cost_allocation': 'Disjoint costs; integration and switching amortized one year; savings monetizable, not raw saved minutes.',
                'alternatives': [{'role': role, 'name': role, 'qualification': 'meets',
                                  'qualification_refs': ['synthetic:test'], 'qualification_available_at': STAMP,
                                  'money': {key: money(value) for key, value in zip(a.MONEY_FIELDS, values)}}
                                 for role, values in costs.items()]},
            'scenarios': {'joint_partition': 'Mutually exclusive year-five abandonment, niche and broad adoption split by supplier rent retention.',
                          'weight_basis': 'unestimated', 'basis_refs': ['synthetic:scenario-design'], 'available_at': STAMP,
                          'cases': [{'family': key, 'mechanism': 'Synthetic competing outcome mechanism.', 'refs': ['synthetic:scenario-design'], 'weight': None}
                                    for key in sorted(a.FAMILIES)]},
            'reference_class': {'status': 'available', 'selection_rule': 'All ten synthetic entrants in cohort fixed independently of outcomes.',
                'selection_recorded_at': '2020-01-01T00:00:00Z', 'coverage': 'declared_complete',
                'outcome_definition': 'Success: broad paid adoption with positive supplier profit after five years; niche/failure separate.',
                'horizon_months': 60, 'denominator': 10, 'counts': {'success': 2, 'niche': 2, 'failure': 3, 'pending': 1, 'unknown': 2},
                'refs': ['synthetic:cohort'], 'available_at': STAMP}}


class AdoptionTests(unittest.TestCase):
    def setUp(self): self.p = example_packet()
    def alt(self, role='proposed_technology'):
        return next(row for row in self.p['customer_economics']['alternatives'] if row['role'] == role)
    def rejection(self, code):
        with self.assertRaises(a.AdoptionCheckError) as caught: a.calculate(self.p)
        self.assertEqual(caught.exception.code, code)
    def test_headline_gain_loses_after_costs(self):
        r = a.calculate(self.p)['customer_economics']
        self.assertEqual(r['alternatives']['proposed_technology']['annual_net_benefit'], '800')
        self.assertEqual(r['qualified_best_roles'], ['simple_alternative'])
        self.assertEqual(r['proposed_max_recurring_fee_to_match_best_qualified_other'], '30')
    def test_real_advantage_can_win(self):
        self.alt()['money']['gross_monetizable_benefit']['value'] = '2000'
        r = a.calculate(self.p)['customer_economics']
        self.assertEqual(r['qualified_best_roles'], ['proposed_technology'])
        self.assertEqual(r['proposed_max_recurring_fee_to_match_best_qualified_other'], '630')
    def test_free_service_cannot_fix_bad_economics(self):
        self.alt()['money']['expected_error_cost']['value'] = '1000'
        r = a.calculate(self.p)['customer_economics']
        self.assertEqual(r['proposed_max_recurring_fee_to_match_best_qualified_other'], '-870')
        self.assertFalse(r['nonnegative_fee_feasible'])
    def test_quality_failure_excluded(self):
        self.alt()['qualification'] = 'does_not_meet'
        self.alt()['money']['gross_monetizable_benefit']['value'] = '100000'
        r = a.calculate(self.p)['customer_economics']
        self.assertEqual(r['qualified_best_roles'], ['simple_alternative'])
        self.assertIsNone(r['proposed_max_recurring_fee_to_match_best_qualified_other'])
    def test_unknown_comparator_blocks_best_claim(self):
        self.alt('simple_alternative')['qualification'] = 'unknown'
        r = a.calculate(self.p)['customer_economics']
        self.assertIsNone(r['qualified_best_roles'])
        self.assertIsNone(r['proposed_max_recurring_fee_to_match_best_qualified_other'])
    def test_all_unqualified_no_best(self):
        for row in self.p['customer_economics']['alternatives']: row['qualification'] = 'does_not_meet'
        self.assertEqual(a.calculate(self.p)['customer_economics']['qualified_best_roles'], [])
    def test_unknown_economics_not_fabricated(self):
        self.p['customer_economics'] = {'status': 'unavailable', 'gap': 'No paid implementation costs.',
            'attempted_refs': ['synthetic:search'], 'next_observation': 'Obtain cohort study.'}
        self.assertEqual(a.calculate(self.p)['customer_economics']['status'], 'unavailable')
    def test_missing_alternative(self):
        self.p['customer_economics']['alternatives'].pop(); self.rejection('shape')
    def test_duplicate_role(self):
        self.alt()['role'] = 'status_quo'; self.rejection('alternatives')
    def test_future_input(self):
        self.alt()['money']['supervision_cost']['available_at'] = '2026-10-24T00:00:00Z'; self.rejection('lookahead')
    def test_future_qualification(self):
        self.alt()['qualification_available_at'] = '2026-10-24T00:00:00Z'; self.rejection('lookahead')
    def test_future_selection(self):
        self.p['reference_class']['selection_recorded_at'] = '2026-10-24T00:00:00Z'; self.rejection('lookahead')
    def test_strict_timestamp_bounds(self):
        for invalid in ['2026-10-23T23:00:00+00:99', '2026-10-23T23:00:00+24:00', '2026-10-23T24:00:00Z', '2026-10-23T23:60:00Z', '2026-10-23T23:00:60Z', '2026-02-30T23:00:00Z', '2026-10-23T23:00:00', '2026-10-23T23:00:00-00:99']:
            with self.subTest(invalid=invalid):
                self.p['as_of'] = invalid; self.rejection('timestamp')
    def test_offset_cutoff_compares_actual_instant(self):
        self.p['as_of'] = '2026-10-23T22:30:00-01:00'
        self.assertEqual(a.calculate(self.p)['status'], 'calculated')
        self.p['as_of'] = '2026-10-23T23:30:00+01:00'
        self.rejection('lookahead')
    def test_nonannual_period(self):
        self.p['customer_economics']['annual_period']['end'] = '2027-06-30'; self.rejection('period')
    def test_wrong_unit(self):
        self.p['customer_economics']['money_unit'] = 'USD/share'; self.rejection('unit')
    def test_missing_cost(self):
        del self.alt()['money']['supervision_cost']; self.rejection('shape')
    def test_invalid_money(self):
        for value in [1.25, True, float('nan'), 'NaN', '1e3', '-1']:
            with self.subTest(value=value):
                self.alt()['money']['recurring_fee']['value'] = value; self.rejection('decimal')
    def test_exact_decimal_arithmetic(self):
        for row in self.p['customer_economics']['alternatives']:
            for key in a.MONEY_FIELDS: row['money'][key]['value'] = '0.1'
        self.assertEqual(a.calculate(self.p)['customer_economics']['alternatives']['status_quo']['annual_net_benefit'], '-0.4')
    def test_four_outcomes_required(self):
        self.p['scenarios']['cases'][0]['family'] = self.p['scenarios']['cases'][1]['family']; self.rejection('scenario')
    def test_unknown_weights(self):
        r = a.calculate(self.p)['scenarios']
        self.assertEqual(r['status'], 'unestimated')
        self.assertTrue(all(v is None for v in r['weights'].values()))
        self.assertFalse(r['calibration_verified'])
    def test_normalization_not_calibration(self):
        self.p['scenarios']['weight_basis'] = 'judgment'
        for row in self.p['scenarios']['cases']: row['weight'] = '0.25'
        r = a.calculate(self.p)['scenarios']
        self.assertEqual(r['status'], 'normalized_input_weights'); self.assertFalse(r['calibration_verified'])
    def test_partial_weights(self):
        self.p['scenarios']['cases'][0]['weight'] = '0.25'; self.rejection('weights')
    def test_sum_weights(self):
        self.p['scenarios']['weight_basis'] = 'judgment'
        for row in self.p['scenarios']['cases']: row['weight'] = '0.2'
        self.rejection('weights')
    def test_unestimated_with_weights(self):
        for row in self.p['scenarios']['cases']: row['weight'] = '0.25'
        self.rejection('weights')
    def test_unresolved_not_discarded(self):
        r = a.calculate(self.p)['reference_class']
        self.assertEqual(r['success_rate_bounds'], ['0.2', '0.5'])
        self.assertEqual(r['resolved'], 7); self.assertEqual(r['unresolved'], 3)
        self.assertFalse(r['population_success_rate_estimable'])
    def test_denominator_reconciliation(self):
        self.p['reference_class']['counts']['unknown'] = 0; self.rejection('denominator')
    def test_boolean_not_count(self):
        self.p['reference_class']['counts']['unknown'] = True; self.rejection('count')
    def test_missing_denominator(self):
        self.p['reference_class'] = {'status': 'unavailable', 'gap': 'Only famous successes documented.',
            'attempted_refs': ['synthetic:search'], 'next_observation': 'Enumerate all entrants.'}
        r = a.calculate(self.p)['reference_class']
        self.assertEqual(r['status'], 'not_estimable'); self.assertIsNone(r['success_rate_bounds'])
    def test_winner_only_warned(self):
        self.p['reference_class']['counts'] = {'success': 10, 'niche': 0, 'failure': 0, 'pending': 0, 'unknown': 0}
        r = a.calculate(self.p)['reference_class']
        self.assertTrue(any('Winner-only' in w for w in r['warnings'])); self.assertFalse(r['population_success_rate_estimable'])
    def test_partial_sample(self):
        self.p['reference_class']['coverage'] = 'partial'
        self.assertTrue(any('Incomplete' in w for w in a.calculate(self.p)['reference_class']['warnings']))
    def test_strict_json(self):
        for raw in [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":0.2}', b'[]', b'\xff', b'{"n":' + b'9' * 5000 + b'}']:
            with self.subTest(raw=raw), self.assertRaises(a.AdoptionCheckError): a.decode_packet(raw)
    def test_cli_missing_input_is_structured(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'error.json'
            run = subprocess.run([sys.executable, a.__file__, '--input', str(Path(tmp) / 'absent'), '--output', str(output)], capture_output=True)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(json.loads(output.read_text())['error']['code'], 'input_io')
    def test_hash_stability(self):
        r = a.calculate(self.p)
        self.assertEqual(r, a.calculate(dict(reversed(list(self.p.items())))))
        self.alt()['money']['recurring_fee']['value'] = '201'
        self.assertNotEqual(r['input_sha256'], a.calculate(self.p)['input_sha256'])
    def test_unknown_field(self):
        self.p['future_success_guaranteed'] = True; self.rejection('shape')
    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp, output = Path(tmp) / 'input.json', Path(tmp) / 'result.json'
            inp.write_text(json.dumps(self.p))
            args = [sys.executable, a.__file__, '--input', str(inp), '--output', str(output)]
            run = subprocess.run(args, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr.decode())
            self.assertEqual(json.loads(output.read_text()), a.calculate(self.p))
            self.p['scenarios']['cases'].pop(); inp.write_text(json.dumps(self.p))
            run = subprocess.run(args, capture_output=True)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(json.loads(output.read_text())['status'], 'error')


if __name__ == '__main__': unittest.main()
