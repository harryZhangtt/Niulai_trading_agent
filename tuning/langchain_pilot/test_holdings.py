"""Synthetic contract, parity, privacy and callback controls; zero provider I/O."""
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import unittest
from unittest.mock import patch

from investment.portfolio.snapshot import SnapshotError, analyze_snapshot, digest
from tuning.langchain_pilot.holdings import (
    AS_OF, Events, cases, project, run_case, verify_local)


class HoldingsTests(unittest.TestCase):
    def fixture(self): return deepcopy(cases()[0]['inputs'])

    def analyze(self, value):
        return analyze_snapshot(value['envelope'], value['receipt'], value['taxonomy'],
                                as_of=value['as_of'])

    def test_frozen_graph_roster_matches_direct_and_expected_results(self):
        evidence = verify_local()
        self.assertEqual(evidence['case_count'], 26)
        self.assertTrue(all(r['direct_parity'] for r in evidence['records']))
        self.assertEqual((evidence['broker_calls'], evidence['model_calls'], evidence['cloud_calls']), (0, 0, 0))

    def test_independent_exact_concentration_and_leverage(self):
        metric = self.analyze(self.fixture())['analysis']['accounts'][0]['metrics']
        weights = (Fraction(3, 5), Fraction(2, 5))
        self.assertEqual(Fraction(metric['hhi']), sum(w * w for w in weights) * 10000)
        self.assertEqual(Fraction(metric['embedded_gross_nav_multiple']), Fraction(160, 125))
        self.assertEqual(Fraction(metric['cash_pct']), Fraction(25, 125) * 100)
        self.assertIsNone(metric['daily_pnl'])

    def test_signed_short_is_net_and_absolute_is_gross(self):
        value = self.fixture()
        value['envelope']['data']['holdings']['positions'][1]['marketValue'] = '-40'
        metric = self.analyze(value)['analysis']['accounts'][0]['metrics']
        self.assertEqual(Decimal(metric['positions_value']), 20)
        self.assertEqual(Decimal(metric['gross_positions_value']), 100)
        self.assertEqual(Decimal(metric['embedded_net_nav_multiple']), Decimal('.64'))

    def test_inputs_unchanged_and_provenance_binds_both_evidence_objects(self):
        value = self.fixture(); before = deepcopy(value)
        result = self.analyze(value)
        self.assertEqual(value, before)
        self.assertEqual(result['provenance']['snapshot_sha256'], digest(value['envelope']))
        self.assertEqual(result['provenance']['receipt_sha256'], digest(value['receipt']))
        self.assertEqual(result['analysis']['generated_at'], AS_OF)
        self.assertFalse(result['provenance']['lease_release_verified'])

    def test_single_type_empty_scope_never_becomes_whole_portfolio(self):
        result = run_case('empty-requested-scope')['accounts'][0]
        self.assertEqual(result['metrics']['positions_value'], '0')
        self.assertFalse(result['whole_portfolio_verified'])
        self.assertIsNone(result['quote_time'])

    def test_unconfirmed_receipt_rejected_before_analytics(self):
        for field, replacement in [('committed', False), ('release_requested', False),
                                    ('reconciliation_required', True), ('status', 'unknown')]:
            with self.subTest(field=field):
                value = self.fixture(); value['receipt'][field] = replacement
                with patch('investment.portfolio.snapshot.build') as arithmetic:
                    with self.assertRaisesRegex(SnapshotError, '^SNAPSHOT_RECEIPT_UNCONFIRMED$'):
                        self.analyze(value)
                arithmetic.assert_not_called()

    def test_failed_read_with_empty_positions_is_rejected(self):
        value = self.fixture()
        value['envelope']['data']['holdings'].update(positions=[], ok=False, sourceReadStatus='failed')
        with self.assertRaisesRegex(SnapshotError, 'ACCOUNT_UNVERIFIED'): self.analyze(value)

    def test_partial_type_or_count_does_not_pass(self):
        for mutation, error in [
            (lambda h: h['coverage'].update(successfulSecurityTypes=[]), 'TYPE_COVERAGE_INCOMPLETE'),
            (lambda h: h['typeReads'][0].update(positionCount=999), 'TYPE_COUNT_MISMATCH'),
            (lambda h: h['coverage'].update(positionCount=True), 'POSITIONS_INVALID')]:
            value = self.fixture(); mutation(value['envelope']['data']['holdings'])
            with self.assertRaisesRegex(SnapshotError, error): self.analyze(value)

    def test_duplicate_contract_across_currencies_rejected(self):
        value = self.fixture(); rows = value['envelope']['data']['holdings']['positions']
        rows[1].update(contractId=rows[0]['contractId'], currency='HKD')
        with self.assertRaisesRegex(SnapshotError, 'POSITION_IDENTITY_INVALID'): self.analyze(value)

    def test_wrong_position_type_and_arbitrary_account_request_rejected(self):
        value = self.fixture()
        value['envelope']['data']['holdings']['positions'][0]['securityType'] = 'OPT'
        with self.assertRaisesRegex(SnapshotError, 'POSITION_SCOPE_MISMATCH'): self.analyze(value)
        value = self.fixture(); value['envelope']['request']['arguments']['account_id'] = 'synthetic-other'
        with self.assertRaisesRegex(SnapshotError, 'REQUEST_INVALID'): self.analyze(value)

    def test_prime_assets_without_summary_keeps_nav_unknown(self):
        value = self.fixture(); value['envelope']['data']['assets']['summary'] = None
        result = project(self.analyze(value))['accounts'][0]
        self.assertIsNone(result['metrics']['nav'])
        self.assertEqual(result['metrics']['positions_value'], '100')

    def test_multi_currency_is_partitioned_and_has_no_fx_inference(self):
        value = self.fixture(); value['envelope']['data']['holdings']['positions'][1]['currency'] = 'HKD'
        result = {a['currency']: a for a in self.analyze(value)['analysis']['accounts']}
        self.assertEqual(set(result), {'USD', 'HKD'})
        self.assertIsNone(result['HKD']['metrics']['nav'])
        self.assertEqual(Decimal(result['HKD']['metrics']['positions_value']), 40)

    def test_future_naive_and_stale_query_are_rejected(self):
        for as_of, error in [('2026-11-15T11:59:00+00:00', 'STALE_OR_FUTURE'),
                             ('2026-11-15T12:01:00', 'TIME_INVALID'),
                             ('2026-11-15T12:10:00+00:00', 'STALE_OR_FUTURE')]:
            value = self.fixture(); value['as_of'] = as_of
            with self.assertRaisesRegex(SnapshotError, error): self.analyze(value)

    def test_private_payload_and_unknown_id_rejected_before_callback(self):
        for candidate in (self.fixture(), 'not-a-public-case'):
            events = Events()
            with self.assertRaisesRegex(SnapshotError, 'PUBLIC_CASE_ONLY'):
                run_case(candidate, callbacks=[events])
            self.assertEqual(events.rows, [])

    def test_real_graph_callback_parentage_and_error_prevent_downstream(self):
        success = Events(); run_case('nominal', callbacks=[success])
        starts = [r for r in success.rows if r['event'] == 'start']
        root = next(r for r in starts if r['parent_run_id'] is None)
        nodes = {r['name']: r for r in starts if r['name'] in ('snapshot_admission', 'portfolio_analysis')}
        self.assertEqual(set(nodes), {'snapshot_admission', 'portfolio_analysis'})
        self.assertTrue(all(r['parent_run_id'] == root['run_id'] for r in nodes.values()))
        failed = Events(); run_case('unknown-checkpoint', callbacks=[failed])
        self.assertTrue(any(r['event'] == 'error' for r in failed.rows))
        self.assertFalse(any(r.get('name') == 'portfolio_analysis' for r in failed.rows))

    def test_error_diagnostic_omits_supplied_secret_fields(self):
        value = self.fixture(); value['receipt'].update(status='synthetic-secret-value')
        with self.assertRaises(SnapshotError) as caught: self.analyze(value)
        self.assertEqual(str(caught.exception), 'SNAPSHOT_RECEIPT_UNCONFIRMED')


if __name__ == '__main__': unittest.main()
