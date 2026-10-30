import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import evidence_crosscheck as e


def example():
    row = {'subject': 'SYNTHETIC', 'metric': 'price', 'definition': 'USD per common share unadjusted',
           'period': {'start': '2026-10-23', 'end': '2026-10-23'}, 'unit': 'USD/share', 'basis': 'quote',
           'value': '100', 'observed_at': '2026-10-23T17:00:00Z', 'available_at': '2026-10-23T17:00:01Z',
           'source': {'origin': 'publisher-a', 'provider': 'provider-a', 'upstream_family': 'family-a',
                      'ref': 'synthetic fixture A', 'sha256': 'a' * 64}}
    other = copy.deepcopy(row)
    other['source'] = {k: ('b' * 64 if k == 'sha256' else v.replace('-a', '-b')) for k, v in other['source'].items()}
    other['source']['ref'] = 'synthetic fixture B'
    return {'version': e.VERSION, 'as_of': '2026-10-23T17:01:00Z', 'comparison_kind': 'numeric',
            'max_age_seconds': 120, 'max_time_skew_seconds': 10, 'absolute_tolerance': '0.1',
            'relative_tolerance': '0.001', 'require_source_hashes': True, 'observations': [row, other]}


class CrosscheckTests(unittest.TestCase):
    def setUp(self): self.p = example()
    def run_packet(self): return e.calculate(self.p)
    def test_distinct_source_agreement_is_not_truth(self):
        result = self.run_packet()
        self.assertEqual(result['status'], 'corroborated'); self.assertFalse(result['semantic_truth_verified'])
    def test_each_shared_origin_downgrades(self):
        for key in ('origin', 'provider', 'upstream_family'):
            with self.subTest(key=key):
                self.p = example(); self.p['observations'][1]['source'][key] = self.p['observations'][0]['source'][key]
                self.assertEqual(self.run_packet()['status'], 'shared_upstream_corroboration')
    def test_same_feed_can_disagree(self):
        self.p['observations'][1]['source'] = copy.deepcopy(self.p['observations'][0]['source'])
        self.p['observations'][1]['value'] = '90'
        self.assertEqual(self.run_packet()['status'], 'disagreement')
    def test_mismatched_normalization_never_averages(self):
        for key, value in [('subject', 'OTHER'), ('metric', 'NAV'), ('definition', 'adjusted price'), ('unit', 'EUR/share'), ('basis', 'last'), ('period', {'start': '2026-10-22', 'end': '2026-10-22'})]:
            with self.subTest(key=key):
                self.p = example(); self.p['observations'][1][key] = value
                result = self.run_packet(); self.assertEqual(result['status'], 'not_comparable'); self.assertNotIn('average', result)
    def test_unknown_fields_and_values_are_unverified(self):
        for key in ['value', 'definition', 'observed_at', 'period']:
            with self.subTest(key=key):
                self.p = example(); self.p['observations'][1][key] = None
                self.assertEqual(self.run_packet()['status'], 'unverified')
    def test_absent_metadata_is_unverified(self):
        del self.p['observations'][1]['definition']
        self.assertEqual(self.run_packet()['status'], 'unverified')
    def test_unknown_source_independence_not_assumed(self):
        self.p['observations'][1]['source']['upstream_family'] = None
        self.assertEqual(self.run_packet()['status'], 'unverified')
    def test_hash_policy_explicit(self):
        del self.p['observations'][1]['source']['sha256']
        self.assertEqual(self.run_packet()['status'], 'unverified')
        self.p['require_source_hashes'] = False
        self.assertEqual(self.run_packet()['status'], 'corroborated')
    def test_invalid_hash_rejected_even_if_optional(self):
        self.p['require_source_hashes'] = False; self.p['observations'][0]['source']['sha256'] = 'bad'
        with self.assertRaises(e.CrosscheckError): self.run_packet()
    def test_stale_data_unverified(self):
        self.p['max_age_seconds'] = 59
        self.assertEqual(self.run_packet()['status'], 'unverified')
        self.p['max_age_seconds'] = 60
        self.assertEqual(self.run_packet()['status'], 'corroborated')
    def test_time_skew_boundary(self):
        self.p['observations'][1]['observed_at'] = '2026-10-23T16:59:50Z'
        self.assertEqual(self.run_packet()['status'], 'corroborated')
        self.p['observations'][1]['observed_at'] = '2026-10-23T16:59:49Z'
        self.assertEqual(self.run_packet()['status'], 'not_comparable')
    def test_equivalent_timezones(self):
        self.p['observations'][1]['observed_at'] = '2026-10-23T13:00:00-04:00'
        self.assertEqual(self.run_packet()['status'], 'corroborated')
    def test_future_or_naive_time_rejected(self):
        for key, value in [('observed_at', '2026-10-23T18:00:00Z'), ('available_at', '2026-10-23T18:00:00Z'), ('observed_at', '2026-10-23T17:00:00')]:
            with self.subTest(key=key, value=value), self.assertRaises(e.CrosscheckError):
                self.p = example(); self.p['observations'][0][key] = value; self.run_packet()
    def test_release_cannot_precede_observation(self):
        self.p['observations'][0]['available_at'] = '2026-10-23T16:59:00Z'
        with self.assertRaises(e.CrosscheckError): self.run_packet()
    def test_absolute_tolerance_boundary(self):
        self.p['relative_tolerance'] = '0'; self.p['observations'][1]['value'] = '100.1'
        self.assertEqual(self.run_packet()['status'], 'corroborated')
        self.p['observations'][1]['value'] = '100.10000001'
        self.assertEqual(self.run_packet()['status'], 'disagreement')
    def test_relative_tolerance_symmetric_and_zero_safe(self):
        self.p['absolute_tolerance'] = '0'; self.p['relative_tolerance'] = '0.01'
        self.p['observations'][1]['value'] = '99'
        r = self.run_packet(); self.assertEqual(r['status'], 'corroborated'); self.assertEqual(r['allowed_difference'], '1')
        self.p['observations'].reverse(); self.assertEqual(self.run_packet()['status'], 'corroborated')
        for row in self.p['observations']: row['value'] = '0'
        self.assertEqual(self.run_packet()['allowed_difference'], '0')
    def test_no_implicit_percent_conversion(self):
        self.p['observations'][0]['value'] = 100.0
        with self.assertRaises(e.CrosscheckError): self.run_packet()
    def test_invalid_tolerances_rejected(self):
        for value in ['NaN', 'Infinity', '-0.1', '1e-3', True, None]:
            with self.subTest(value=value), self.assertRaises(e.CrosscheckError):
                self.p = example(); self.p['absolute_tolerance'] = value; self.run_packet()
    def test_time_limits_require_nonnegative_integer(self):
        for value in [True, -1, 0.5, '60']:
            with self.subTest(value=value), self.assertRaises(e.CrosscheckError):
                self.p = example(); self.p['max_age_seconds'] = value; self.run_packet()
    def test_option_contract_and_side_required(self):
        self.p['comparison_kind'] = 'option_quote'
        self.assertEqual(self.run_packet()['status'], 'unverified')
        for row in self.p['observations']: row.update(contract_key='SYNTHETIC|2027-01-15|100|C|USD|100|standard', side='bid')
        self.assertEqual(self.run_packet()['status'], 'corroborated')
        self.p['observations'][1]['side'] = 'ask'
        self.assertEqual(self.run_packet()['status'], 'not_comparable')
    def test_option_adjusted_deliverable_mismatch(self):
        self.p['comparison_kind'] = 'option_quote'
        for row in self.p['observations']: row.update(contract_key='SYNTHETIC|2027-01-15|100|C|USD|100|standard', side='bid')
        self.p['observations'][1]['contract_key'] += '|adjusted'
        self.assertEqual(self.run_packet()['status'], 'not_comparable')
    def test_invalid_option_side_rejected(self):
        self.p['comparison_kind'] = 'option_quote'
        self.p['observations'][0].update(contract_key='synthetic-option', side='unknown-side')
        with self.assertRaises(e.CrosscheckError): self.run_packet()
    def test_invalid_source_shape_rejected(self):
        for source in [[], False, 0, '']:
            with self.subTest(source=source), self.assertRaises(e.CrosscheckError):
                self.p = example(); self.p['observations'][0]['source'] = source; self.run_packet()
    def test_duplicate_json_keys_and_nonfinite_constants(self):
        for raw in ['{"value":1,"value":2}', '{"value":NaN}']:
            with self.subTest(raw=raw), self.assertRaises(e.CrosscheckError): e.decode_packet(raw)
    def test_two_sources_exactly(self):
        self.p['observations'].pop()
        with self.assertRaises(e.CrosscheckError): self.run_packet()
    def test_cli_success_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / 'in.json', Path(tmp) / 'out.json'
            src.write_text(json.dumps(self.p)); cmd = [sys.executable, e.__file__, '--input', str(src), '--output', str(dst)]
            p = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr); self.assertEqual(json.loads(dst.read_text()), self.run_packet())
            src.write_text('{bad}')
            p = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(p.returncode, 2); self.assertEqual(json.loads(dst.read_text())['status'], 'error')


if __name__ == '__main__': unittest.main()
