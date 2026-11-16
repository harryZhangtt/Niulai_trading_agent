"""Execute all 60 independently frozen HOLD semantic cases at pure boundaries."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from investment.portfolio.snapshot import SnapshotError, analyze_snapshot, digest
from tuning.langchain_pilot.holdings import Events, graph, project
from tuning.langchain_pilot.holdings_contract_fixtures import canonical

CASE_PATH = Path(__file__).parent / 'tests' / 'atomic_contract_cases.json'
CASE_SHA256 = 'bffd7b0217b07b6c0c5c7a2384d5afcb1cd7ca455f0cca27951f929f7c5e1d78'
CONTRACT = json.loads(CASE_PATH.read_text())
FROZEN_CASES = [case for case in CONTRACT['cases'] if case['id'].startswith('HOLD-')]


def analyze(value):
    return analyze_snapshot(value['envelope'], value['receipt'], value['taxonomy'], as_of=value['as_of'])


REJECT = {2: 'SNAPSHOT_READ_INCOMPLETE', 3: 'SNAPSHOT_TYPE_COVERAGE_INCOMPLETE',
          4: 'SNAPSHOT_RECEIPT_UNCONFIRMED', 8: 'SNAPSHOT_TYPE_COVERAGE_INCOMPLETE',
          9: 'SNAPSHOT_TYPE_COUNT_MISMATCH', 12: 'SNAPSHOT_ACCOUNT_MISMATCH',
          13: 'SNAPSHOT_ACCOUNT_UNVERIFIED', 14: 'SNAPSHOT_ACCOUNT_MISMATCH',
          21: 'SNAPSHOT_POSITION_IDENTITY_INVALID', 22: 'SNAPSHOT_POSITION_IDENTITY_INVALID',
          38: 'SNAPSHOT_QUOTE_TIME_FUTURE', 39: 'SNAPSHOT_TIME_INVALID',
          52: 'SNAPSHOT_CHECKPOINT_UNCONFIRMED', 53: 'SNAPSHOT_CHECKPOINT_UNCONFIRMED',
          54: 'SNAPSHOT_CHECKPOINT_MISMATCH', 55: 'SNAPSHOT_CHECKPOINT_UNCONFIRMED'}


class FrozenHoldingsTests(unittest.TestCase):
    def test_independent_artifact_hash_and_case_completeness(self):
        self.assertEqual(hashlib.sha256(CASE_PATH.read_bytes()).hexdigest(), CASE_SHA256)
        self.assertEqual([case['id'] for case in FROZEN_CASES], [f'HOLD-{i:02d}' for i in range(1, 61)])

    def exercise(self, spec):
        number = int(spec['id'].split('-')[1])
        value = canonical(spec['id'])
        before = deepcopy(value)
        # A socket at this pure boundary would be an unauthorized provider call.
        with patch('socket.socket', side_effect=AssertionError('HOLDINGS_NETWORK_FORBIDDEN')):
            self._exercise(number, spec, value)
        self.assertEqual(value, before, spec['id'] + ': fixture mutated')

    def _exercise(self, number, spec, value):
        if number in REJECT:
            with patch('investment.portfolio.snapshot.build') as arithmetic:
                with self.assertRaises(SnapshotError) as caught:
                    analyze(value)
            self.assertEqual(str(caught.exception), REJECT[number])
            arithmetic.assert_not_called()
            if number in (3, 8):
                expected_missing = ['OPT', 'FUT', 'FUND'] if number == 3 else ['OPT']
                self.assertEqual(list(caught.exception.missing_security_types), expected_missing)
            if number == 55:
                for _ in range(2):
                    with self.assertRaisesRegex(SnapshotError, '^SNAPSHOT_CHECKPOINT_UNCONFIRMED$'):
                        graph().invoke({'inputs': value})
            return
        if number in (56, 58):
            for _ in range(2 if number == 56 else 1):
                with patch('investment.portfolio.snapshot.build', side_effect=ValueError('private-canary')):
                    with self.assertRaisesRegex(SnapshotError, '^SNAPSHOT_ANALYTICS_INPUT_INVALID$'):
                        graph().invoke({'inputs': value})
            return
        result = analyze(value)
        self.assertEqual(result['status'], 'analyzed')
        accounts = result['analysis']['accounts']
        account, metric = accounts[0], accounts[0]['metrics']
        provenance = result['provenance']
        if number in (1, 5):
            self.assertEqual(metric['positions_value'], '0')
            self.assertEqual(account['quality']['row_count'], 0)
            self.assertFalse(account['quality']['whole_portfolio_verified'])
        elif number == 6:
            self.assertEqual([p['positionCount'] for p in provenance['type_reads']], [1, 2, 0, 1])
            self.assertEqual(provenance['position_count'], 4)
            self.assertEqual(provenance['successful_security_types'], ['STK', 'OPT', 'FUT', 'FUND'])
        elif number in (7, 60):
            self.assertEqual(provenance['requested_security_types'], ['STK'])
            self.assertEqual(provenance['successful_security_types'], ['STK'])
            self.assertFalse(account['quality']['whole_portfolio_verified'])
            if number == 60:
                self.assertEqual(graph().invoke({'inputs': value})['result'], result)
        elif number == 10:
            self.assertEqual(Fraction(metric['cash']), 300)
            self.assertEqual(account['quality']['row_count'], 0)
            self.assertNotIn('CASH', provenance['requested_security_types'])
        elif number in (11, 15):
            self.assertEqual(account['accountRef'], 'SYNTHETIC-A')
            self.assertFalse(provenance['source_authentication_verified'])
            self.assertFalse(provenance['live_read_verified'])
        elif number == 16:
            self.assertEqual(account['currency'], 'USD')
            self.assertEqual(Fraction(metric['positions_value']), 100)
            self.assertEqual(Fraction(metric['nav']), 1000)
        elif number in (17, 20):
            self.assertEqual(account['currency'], 'HKD')
            self.assertEqual(Fraction(metric['positions_value']), 100)
            self.assertIsNone(metric['nav'])
            self.assertIsNone(metric['positions_nav_pct'])
        elif number == 18:
            self.assertEqual(account['currency'], '币种未知')
            self.assertIsNone(metric['positions_value'])
            self.assertIsNone(metric['nav'])
            self.assertFalse(account['quality']['market_value_complete'])
        elif number == 19:
            self.assertEqual([a['currency'] for a in accounts], ['USD', 'HKD'])
            self.assertEqual([Fraction(a['metrics']['positions_value']) for a in accounts], [10, 20])
            self.assertIsNone(accounts[1]['metrics']['nav'])
            self.assertNotIn('positions_value', result['analysis'])
        elif number in (23, 24, 25):
            expected_count = 3 if number == 24 else 2
            self.assertEqual(account['quality']['row_count'], expected_count)
            self.assertEqual(Fraction(metric['positions_value']), 100 * expected_count)
        elif number == 26:
            self.assertEqual(Fraction(metric['positions_value']), 0)
            self.assertTrue(account['quality']['market_value_complete'])
        elif 27 <= number <= 31:
            self.assertIsNone(metric['positions_value'])
            self.assertIsNone(metric['gross_positions_value'])
            self.assertIsNone(metric['hhi'])
            self.assertFalse(account['quality']['market_value_complete'])
        elif number == 32:
            self.assertEqual(Fraction(metric['nav']), 0)
            self.assertIsNone(metric['cash_pct'])
            self.assertIsNone(metric['gross_nav_multiple'])
        elif number == 33:
            for field, output in [('netLiquidation', 'nav'), ('cash', 'cash')]:
                missing = deepcopy(value)
                missing['envelope']['data']['assets']['summary']['amounts'].pop(field)
                self.assertIsNone(analyze(missing)['analysis']['accounts'][0]['metrics'][output])
            for field in ('quantity', 'latestPrice'):
                missing = deepcopy(value)
                missing['envelope']['data']['holdings']['positions'][0].pop(field, None)
                row_output = analyze(missing)['analysis']['accounts'][0]['holdings'][0]
                self.assertNotIn(field, row_output)
                self.assertEqual(Fraction(metric['positions_value']), 100)
        elif 34 <= number <= 37:
            quote = provenance['quote_observation']
            self.assertEqual(quote['freshness'], {34: 'stale', 35: 'unknown',
                36: 'at_or_after_cutoff', 37: 'stale'}[number])
            self.assertEqual(account['quality']['quote_time'], value['envelope']['quote_observation']['quote_at'])
            self.assertEqual(result['analysis']['source_times']['quote_time'], quote['quote_at'])
            self.assertEqual(quote['cutoff_policy'], 'inclusive')
        elif number in (40, 41, 42):
            expected = spec['expected']
            mapped = {'netExposure': 'positions_value', 'grossExposure': 'gross_positions_value',
                      'grossExposureOverNAV': 'gross_nav_multiple'}
            for key, metric_key in mapped.items():
                if key in expected:
                    self.assertEqual(Fraction(metric[metric_key]), Fraction(expected[key]))
            if number == 40:
                self.assertEqual(Fraction(metric['positions_nav_pct']) / 100, Fraction(expected['netExposureOverNAV']))
                self.assertEqual(Fraction(metric['cash_pct']) / 100, Fraction(expected['cashOverNAV']))
        elif number == 43:
            self.assertEqual(Fraction(metric['positions_value']), -250)
            self.assertEqual(Fraction(metric['gross_positions_value']), 250)
            self.assertEqual(account['holdings'][0]['quantity'], '-2')
        elif number == 44:
            self.assertEqual(Fraction(metric['cash']), -50)
            self.assertEqual(Fraction(metric['cash_pct']) / 100, Fraction('-0.05'))
        elif number in (45, 46):
            self.assertEqual(Fraction(metric['gross_nav_multiple']), Fraction('1.5' if number == 45 else '0.6'))
        elif 47 <= number <= 50:
            self.assertIsNone(metric['daily_pnl'])
            self.assertEqual(metric['daily_pnl_status'], 'unavailable')
            self.assertEqual(account['daily_top_gainers'], [])
            self.assertNotIn('orders', result)
            self.assertNotIn('recommendations', result)
            if number == 48:
                self.assertEqual(Fraction(metric['unrealized_pnl']), 123)
        elif number == 51:
            self.assertEqual(provenance['receipt_sha256'], digest(value['receipt']))
            self.assertEqual(provenance['gateway_attempt_id'], 'SYNTHETIC-CHECKPOINT-1')
        elif number == 57:
            traced = graph().invoke({'inputs': value})['result']
            self.assertEqual(traced, result)
        elif number == 59:
            self.assertEqual(digest(value), digest(deepcopy(value)))
            self.assertEqual(provenance['snapshot_sha256'], digest(value['envelope']))
            self.assertEqual(provenance['receipt_sha256'], digest(value['receipt']))
        else:
            self.fail('Frozen case has no executed semantic oracle: ' + spec['id'])


def frozen_test(spec):
    def test(self):
        self.exercise(spec)
    test.__doc__ = spec['title'] + ' (' + spec['criterion'] + ')'
    return test


for spec in FROZEN_CASES:
    name = 'test_' + spec['id'].replace('-', '_') + '_' + spec['criterion'].replace('-', '_')
    setattr(FrozenHoldingsTests, name, frozen_test(spec))


if __name__ == '__main__':
    unittest.main()
