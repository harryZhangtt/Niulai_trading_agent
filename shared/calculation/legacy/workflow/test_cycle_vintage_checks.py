import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cycle_vintage_checks as v


def example():
    expected = {'series_id': 'industry_shipments', 'period': {'start': '2026-01-01', 'end': '2026-03-31'}, 'unit': 'quantity:units'}
    return {'version': v.VERSION, 'subject': 'synthetic', 'as_of': '2026-05-01T00:00:00Z',
            'expected': [expected], 'observations': [{**copy.deepcopy(expected), 'value': '100',
                'available_at': '2026-04-15T12:00:00Z', 'vintage_id': 'first',
                'source_ref': 'synthetic fixture, not real evidence'}]}


class VintageTests(unittest.TestCase):
    def setUp(self):
        self.p = example()

    def test_selects_latest_available_not_latest_downloaded(self):
        self.p['observations'] += [{**self.p['observations'][0], 'value': '110', 'vintage_id': 'second', 'available_at': '2026-04-25T00:00:00Z'},
                                  {**self.p['observations'][0], 'value': '130', 'vintage_id': 'third', 'available_at': '2026-05-15T00:00:00Z'}]
        r = v.calculate(self.p)
        self.assertEqual(r['selected_view']['rows'][0]['observation']['value'], '110')
        self.assertEqual(r['status'], 'complete')

    def test_future_tail_does_not_change_any_output(self):
        before = v.calculate(self.p)
        self.p['observations'].append({**self.p['observations'][0], 'value': '10000', 'vintage_id': 'future', 'available_at': '2027-01-01T00:00:00Z'})
        self.assertEqual(before, v.calculate(self.p))

    def test_future_existence_does_not_change_missing_status(self):
        observation = self.p['observations'].pop()
        before = v.calculate(self.p)
        observation['available_at'] = '2027-01-01T00:00:00Z'
        self.p['observations'].append(observation)
        self.assertEqual(before, v.calculate(self.p))
        self.assertEqual(before['coverage']['missing_as_of'], 1)

    def test_pending_period_never_selected_as_forecast(self):
        self.p['expected'][0]['period']['end'] = '2027-03-31'
        self.p['observations'] = []
        result = v.calculate(self.p)
        self.assertEqual(result['coverage']['pending_period'], 1)
        self.assertEqual(result['status'], 'partial')

    def test_reported_future_period_rejected(self):
        self.p['observations'][0]['available_at'] = '2026-03-01T00:00:00Z'
        with self.assertRaisesRegex(v.VintageError, 'forecasts'):
            v.calculate(self.p)

    def test_same_timestamp_timezone_equivalent(self):
        before = v.calculate(self.p)
        self.p['as_of'] = '2026-04-30T20:00:00-04:00'
        self.p['observations'][0]['available_at'] = '2026-04-15T08:00:00-04:00'
        self.assertEqual(before, v.calculate(self.p))

    def test_exact_cutoff_is_available(self):
        self.p['observations'][0]['available_at'] = self.p['as_of']
        self.assertEqual(v.calculate(self.p)['coverage']['selected'], 1)

    def test_same_identity_same_payload_deduplicated(self):
        before = v.calculate(self.p)
        self.p['observations'].append(copy.deepcopy(self.p['observations'][0]))
        self.assertEqual(before, v.calculate(self.p))

    def test_conflicting_identity_rejected_even_if_future(self):
        self.p['observations'].append({**self.p['observations'][0], 'value': '123', 'available_at': '2027-01-01T00:00:00Z'})
        with self.assertRaisesRegex(v.VintageError, 'conflicting duplicate'):
            v.calculate(self.p)

    def test_distinct_latest_vintages_same_timestamp_rejected(self):
        self.p['observations'].append({**self.p['observations'][0], 'vintage_id': 'other'})
        with self.assertRaisesRegex(v.VintageError, 'ambiguous latest'):
            v.calculate(self.p)

    def test_output_order_independent(self):
        other = copy.deepcopy(self.p['expected'][0]); other['series_id'] = 'inventory'
        self.p['expected'].append(other)
        self.p['observations'].append({**other, 'value': '10', 'available_at': '2026-04-15T00:00:00Z', 'vintage_id': 'first', 'source_ref': 'fixture'})
        before = v.calculate(self.p)
        self.p['expected'].reverse(); self.p['observations'].reverse()
        self.assertEqual(before, v.calculate(self.p))

    def test_duplicate_scope_rejected(self):
        self.p['expected'].append(copy.deepcopy(self.p['expected'][0]))
        with self.assertRaisesRegex(v.VintageError, 'duplicate expected'):
            v.calculate(self.p)

    def test_units_cannot_be_silently_changed(self):
        self.p['observations'][0]['unit'] = 'millions of units'
        with self.assertRaisesRegex(v.VintageError, 'unit differs'):
            v.calculate(self.p)

    def test_unknown_scope_rejected(self):
        self.p['observations'][0]['series_id'] = 'different series'
        with self.assertRaisesRegex(v.VintageError, 'outside declared'):
            v.calculate(self.p)

    def test_values_strict_finite_decimal_strings(self):
        for value in [True, 1.1, 'NaN', 'Infinity', '1e309', '', ' 1', '01']:
            with self.subTest(value=value), self.assertRaises(v.VintageError):
                p = example(); p['observations'][0]['value'] = value; v.calculate(p)

    def test_numeric_spelling_canonicalized(self):
        before = v.calculate(self.p)
        self.p['observations'][0]['value'] = '+100.000'
        self.assertEqual(before, v.calculate(self.p))

    def test_bad_time_rejected(self):
        for time in ['2026-05-01', '2026-05-01T00:00:00', '2026-05-01T00:00:00+01:99', '2026-02-30T00:00:00Z']:
            with self.subTest(time=time), self.assertRaises(v.VintageError):
                p = example(); p['as_of'] = time; v.calculate(p)

    def test_reversed_period_rejected(self):
        self.p['expected'][0]['period']['start'] = '2026-04-01'
        with self.assertRaisesRegex(v.VintageError, 'end precedes'):
            v.calculate(self.p)

    def test_missing_source_rejected(self):
        self.p['observations'][0]['source_ref'] = ''
        with self.assertRaisesRegex(v.VintageError, 'source_ref'):
            v.calculate(self.p)

    def test_duplicate_json_and_nan_rejected(self):
        for raw in ['{"version":1,"version":2}', '{"x":NaN}', '{invalid}']:
            with self.subTest(raw=raw), self.assertRaises(v.VintageError):
                v.decode_packet(raw)

    def test_coverage_all_expected_accounted_for(self):
        missing = copy.deepcopy(self.p['expected'][0]); missing['series_id'] = 'missing'
        pending = copy.deepcopy(missing); pending['series_id'] = 'future'; pending['period']['end'] = '2027-03-31'
        self.p['expected'] += [missing, pending]
        self.assertEqual(v.calculate(self.p)['coverage'], {'expected': 3, 'selected': 1, 'missing_as_of': 1, 'pending_period': 1})

    def test_cli_valid_and_invalid_outputs_atomic_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / 'input.json', Path(tmp) / 'output.json'
            src.write_text(json.dumps(self.p))
            cmd = [sys.executable, v.__file__, '--input', str(src), '--output', str(dst)]
            process = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(dst.read_text()), v.calculate(self.p))
            src.write_text('{bad json}')
            process = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(process.returncode, 2)
            self.assertEqual(json.loads(dst.read_text())['status'], 'error')


if __name__ == '__main__':
    unittest.main()
