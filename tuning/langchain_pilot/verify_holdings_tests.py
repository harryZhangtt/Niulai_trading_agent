"""Bounded provider-free test evidence and in-memory deliberate-break controls.

Mutations are temporary mocks of enforcing boundaries. No source or analytics
archive is edited; every patch is restored before the next control.
"""
from contextlib import ExitStack, redirect_stderr
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch
from uuid import uuid4

from investment.portfolio import snapshot
from tuning.langchain_pilot import holdings
from tuning.langchain_pilot.holdings_contract_fixtures import canonical
from tuning.langchain_pilot.test_holdings_boundaries import HoldingsBoundaryTests
from tuning.langchain_pilot.test_holdings_frozen_contract import FrozenHoldingsTests, CASE_PATH

ROOT = Path(__file__).resolve().parents[2]
MODULES = ('tuning.langchain_pilot.test_holdings', 'tuning.langchain_pilot.test_holdings_boundaries',
           'tuning.langchain_pilot.test_holdings_frozen_contract')


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


def execute(suite):
    identities = [test.id() for test in flatten(suite)]
    output = io.StringIO()
    with redirect_stderr(output):
        result = unittest.TextTestRunner(stream=output, verbosity=1).run(suite)
    return dict(executed=result.testsRun, skipped=len(result.skipped),
        failed=len(result.failures), errors=len(result.errors), passed=result.wasSuccessful(),
        test_ids=identities, failing_ids=[test.id() for test, _ in result.failures + result.errors],
        output=output.getvalue())


def targeted(test_class, name):
    return unittest.TestSuite([test_class(name)])


def modified_build(change, *, prepare=None):
    original = snapshot.build
    def broken(holdings_input, assets, taxonomy):
        if prepare:
            holdings_input = deepcopy(holdings_input)
            prepare(holdings_input)
        result = original(holdings_input, assets, taxonomy)
        if change:
            change(result)
        return result
    return broken


def ignore_require(*codes):
    original = snapshot.require
    def broken(condition, code):
        if code not in codes:
            original(condition, code)
    return broken


def controls():
    class DuplicatePublicOutcomeTest(unittest.TestCase):
        def test_same_currency_duplicate_remains_rejected(self):
            value = canonical('HOLD-21')
            with self.assertRaisesRegex(snapshot.SnapshotError, '^SNAPSHOT_POSITION_IDENTITY_INVALID$'):
                snapshot.analyze_snapshot(value['envelope'], value['receipt'], value['taxonomy'], as_of=value['as_of'])
    def abs_net(result):
        for account in result['accounts']:
            amount = account['metrics']['positions_value']
            if amount is not None:
                account['metrics']['positions_value'] = abs(amount)
    def fake_daily(result):
        for account in result['accounts']:
            account['metrics']['daily_pnl'] = account['metrics']['unrealized_pnl']
    def missing_zero(value):
        for account in value['accountResults']:
            for row in account['positions']:
                if row.get('marketValue') is None:
                    row['marketValue'] = '0'
    def unique_contracts(value):
        for account in value['accountResults']:
            for index, row in enumerate(account['positions']):
                row['contractId'] = f'mutated-unique-{index}'
    original_admit = snapshot.admit_snapshot
    def query_as_quote(*args, **kwargs):
        admitted = original_admit(*args, **kwargs)
        admitted['provenance']['quote_observation']['quote_at'] = admitted['provenance']['query_completed_at']
        return admitted
    baseline = snapshot.analyze_snapshot(holdings.cases()[0]['inputs']['envelope'],
        holdings.cases()[0]['inputs']['receipt'], holdings.cases()[0]['inputs']['taxonomy'],
        as_of=holdings.cases()[0]['inputs']['as_of'])
    def suppress_analytics(admitted: dict, taxonomy: dict):
        """Deliberately return an old success instead of executing analysis."""
        return deepcopy(baseline)
    def bypass_tool(self, input, config=None, **kwargs):
        return self.func(**input)
    mutations = [
        ('MUT-015', 'failed_empty_as_success', FrozenHoldingsTests, 'test_HOLD_02_AC_015',
         [('investment.portfolio.snapshot.require', ignore_require('SNAPSHOT_READ_INCOMPLETE', 'SNAPSHOT_ACCOUNT_UNVERIFIED'))]),
        ('MUT-016', 'ignore_type_count_mismatch', FrozenHoldingsTests, 'test_HOLD_09_AC_016',
         [('investment.portfolio.snapshot.require', ignore_require('SNAPSHOT_TYPE_COUNT_MISMATCH'))]),
        ('MUT-017', 'skip_account_match', FrozenHoldingsTests, 'test_HOLD_12_AC_017',
         [('investment.portfolio.snapshot.require', ignore_require('SNAPSHOT_ACCOUNT_MISMATCH'))]),
        ('MUT-019', 'remove_only_adapter_duplicate_identity', DuplicatePublicOutcomeTest, 'test_same_currency_duplicate_remains_rejected',
         [('investment.portfolio.snapshot.position_identity', lambda row: ('wrong-identity', id(row)))]),
        ('MUT-019', 'remove_duplicate_invariant_at_both_layers', DuplicatePublicOutcomeTest, 'test_same_currency_duplicate_remains_rejected',
         [('investment.portfolio.snapshot.position_identity', lambda row: ('wrong-identity', id(row))),
          ('investment.portfolio.snapshot.build', modified_build(None, prepare=unique_contracts))]),
        ('MUT-020', 'default_missing_value_to_zero', FrozenHoldingsTests, 'test_HOLD_28_AC_020',
         [('investment.portfolio.snapshot.build', modified_build(None, prepare=missing_zero))]),
        ('MUT-021', 'query_completion_as_quote_time', FrozenHoldingsTests, 'test_HOLD_35_AC_021',
         [('investment.portfolio.snapshot.admit_snapshot', query_as_quote)]),
        ('MUT-022', 'absolute_value_of_net', HoldingsBoundaryTests, 'test_AC_022_negative_net_exposure_preserves_sign',
         [('investment.portfolio.snapshot.build', modified_build(abs_net))]),
        ('MUT-022', 'default_decimal_precision_rounds_money', HoldingsBoundaryTests,
         'test_AC_022_large_exact_decimal_sum_survives_projection',
         [('investment.portfolio.snapshot.arithmetic_precision', lambda value: 28)]),
        ('MUT-023', 'unrealized_as_daily_pnl', FrozenHoldingsTests, 'test_HOLD_48_AC_023',
         [('investment.portfolio.snapshot.build', modified_build(fake_daily))]),
        ('MUT-024', 'accept_unknown_checkpoint', FrozenHoldingsTests, 'test_HOLD_52_AC_024',
         [('investment.portfolio.snapshot.require', ignore_require('SNAPSHOT_CHECKPOINT_UNCONFIRMED'))]),
        ('MUT-025', 'suppress_analytics_error_with_old_success', HoldingsBoundaryTests,
         'test_AC_012_tool_error_is_traced_and_cannot_be_success',
         [('tuning.langchain_pilot.holdings.analyze_admitted', suppress_analytics)]),
        ('MUT-011', 'bypass_native_tool_callbacks', HoldingsBoundaryTests,
         'test_AC_011_native_tool_span_belongs_to_portfolio_node',
         [('langchain_core.tools.StructuredTool.invoke', bypass_tool)]),
        ('MUT-013', 'allow_arbitrary_public_selector', HoldingsBoundaryTests,
         'test_AC_013_invalid_public_selector_is_fenced_before_callback',
         [('tuning.langchain_pilot.holdings.public_case', lambda value: holdings.cases()[0])]),
    ]
    records = []
    for criterion, name, test_class, method, replacements in mutations:
        with ExitStack() as stack:
            for target, replacement in replacements:
                stack.enter_context(patch(target, replacement))
            record = execute(targeted(test_class, method))
        survived = record['passed']
        record.update(criterion=criterion, mutation=name, survived=survived,
            classification=('invariant_enforced_at_maintained_analytics_and_post_build_gate'
                if name == 'remove_only_adapter_duplicate_identity' and survived else
                ('finding_survived' if survived else 'killed')))
        records.append(record)
    return records


def main():
    if os.environ.get('LANGSMITH_TRACING', '').lower() != 'false':
        raise RuntimeError('HOLDINGS_TEST_TRACING_MUST_BE_DISABLED')
    normal = execute(unittest.defaultTestLoader.loadTestsFromNames(MODULES))
    mutation_records = controls()
    # Verify all in-memory patches have actually been restored.
    restored = execute(unittest.defaultTestLoader.loadTestsFromNames(MODULES))
    expected_survivor = 'remove_only_adapter_duplicate_identity'
    unexpected = [r['mutation'] for r in mutation_records if r['survived'] and r['mutation'] != expected_survivor]
    paths = ['investment/portfolio/snapshot.py', 'niulai/holdings/analytics.py',
        'tuning/langchain_pilot/holdings.py', 'tuning/langchain_pilot/holdings_contract_fixtures.py',
        'tuning/langchain_pilot/test_holdings.py', 'tuning/langchain_pilot/test_holdings_boundaries.py',
        'tuning/langchain_pilot/test_holdings_frozen_contract.py', 'tuning/langchain_pilot/verify_holdings_tests.py',
        'tuning/langchain_pilot/ATOMIC_ACCEPTANCE.md', 'tuning/langchain_pilot/tests/atomic_contract_cases.json']
    mapping = {}
    for identity in normal['test_ids']:
        found = re.search(r'AC_(\d{3})', identity)
        criterion = 'AC-' + found[1] if found else 'prototype_compatibility'
        mapping.setdefault(criterion, []).append(identity)
    evidence = dict(status='PASS' if normal['passed'] and restored['passed'] and not unexpected else 'FAIL',
        level='balanced_local_atomic_and_real_in_process_graph_with_deliberate_breaks',
        generated_at=datetime.now(timezone.utc).isoformat(), synthetic_only=True,
        network_calls=0, broker_calls=0, model_calls=0, cloud_calls=0,
        normal=normal, criterion_test_mapping=mapping, mutations=mutation_records,
        killed=sum(not r['survived'] for r in mutation_records),
        survivors=[r['mutation'] for r in mutation_records if r['survived']],
        unexpected_survivors=unexpected, restored=restored,
        frozen_case_ids=[f'HOLD-{i:02d}' for i in range(1, 61)],
        sources={path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths},
        not_run=['owned URL/Agent Server API', 'isolated synthetic cloud exact readback',
                 'independent verifier', 'real future scheduled runtime acceptance/email'],
        residual_risks=['All receipts, account labels and quote observations are caller-supplied and unauthenticated.',
            'Partial retrieval rejects with typed gaps rather than offering partial useful analytics.',
            'In-process graphs do not establish persistence/restart durability or provider freshness.',
            'This local trial does not establish investment quality, alpha or autonomous model dispatch.'])
    directory = ROOT / '.langchain-pilot/runtime/portfolio' / str(uuid4())
    directory.mkdir(parents=True, mode=0o700)
    output = directory / 'holdings-tests.json'
    output.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(dict(status=evidence['status'], executed=normal['executed'], skipped=normal['skipped'],
        killed=evidence['killed'], survivors=evidence['survivors'], restored=restored['passed'],
        evidence=str(output))))
    if evidence['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
