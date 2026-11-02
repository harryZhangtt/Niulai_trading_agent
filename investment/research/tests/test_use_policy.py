import copy
from datetime import datetime, timezone
import unittest

from shared.research_sources.artifacts import SourceError, digest
from investment.research.routing import compatibility
from investment.research.use_policy import classify, resolve, schedule_check

NOW = '2026-10-31T00:00:00Z'


def requirement(**changes):
    return {**{'id': 'revenue', 'entity': 'AAA', 'metric': 'revenue', 'definition': 'reported revenue',
        'period': 'FY2026Q3', 'unit': 'USD millions', 'basis': 'GAAP', 'cutoff': NOW,
        'mode': 'current', 'criticality': 'critical', 'max_age_seconds': 3600,
        'refresh_after_seconds': 600, 'decision_deadline': '2026-10-31T00:10:00Z',
        'absolute_tolerance': '1', 'relative_tolerance': '0'}, **changes}


def observation(name='one', lineage='issuer', **changes):
    r = requirement()
    payload = {k: r[k] for k in ('entity', 'metric', 'definition', 'period', 'unit', 'basis')}
    payload.update(value='100', available_at='2026-10-30T23:30:00Z', source_time='2026-10-30T23:30:00Z',
                   last_checked_at='2026-10-30T23:59:00Z', upstream_lineage=lineage, source_role='primary')
    payload.update(changes)
    return {'id': name, 'revision': 1, 'lifecycle_revision': 1, 'state': 'active', 'payload': payload}


class UsePolicyTests(unittest.TestCase):
    def test_compatibility_excludes_unimplemented_hosts_preserves_sec(self):
        provider = {'id': 'official_document', 'operations': [{'name': 'read', 'output_access': 'document'}]}
        result = compatibility({'minimum_access': 'document', 'allowed_hosts': ['sec.gov', 'www.fdic.gov', 'www.federalreserve.gov']}, provider)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['supported_hosts'], ['sec.gov'])
        self.assertEqual(result['excluded_hosts'], ['www.fdic.gov', 'www.federalreserve.gov'])
        self.assertEqual(result['readiness'], 'not_checked')
        self.assertFalse(compatibility({'minimum_access': 'document', 'allowed_hosts': ['www.fdic.gov']}, provider)['eligible'])

    def test_successful_old_refetch_does_not_rejuvenate(self):
        old = observation(source_time='2026-10-29T23:00:00Z', last_checked_at=NOW)
        self.assertIn('SOURCE_EXPIRED', classify(requirement(), old, NOW)['reasons'])
        self.assertEqual(resolve(requirement(), [old], NOW, remaining_attempts=0)['status'], 'restricted')

    def test_historical_fact_and_current_fact_have_distinct_eligibility(self):
        old = observation(source_time='2024-01-01T00:00:00Z', available_at='2024-01-02T00:00:00Z')
        self.assertEqual(classify(requirement(mode='historical', max_age_seconds=None), old, NOW)['status'], 'eligible')
        self.assertEqual(classify(requirement(), old, NOW)['status'], 'blocked')
        self.assertIn('SOURCE_EXPIRED', classify(requirement(mode='historical', cutoff='2024-01-02T00:00:00Z'), old, NOW)['reasons'])

    def test_soft_refresh_can_be_due_while_use_remains_eligible(self):
        result = classify(requirement(), observation(last_checked_at='2026-10-30T23:40:00Z'), NOW)
        self.assertEqual(result['status'], 'eligible')
        self.assertTrue(result['refresh_due'])

    def test_future_revision_and_unknown_time_fail_critical_use(self):
        for change, expected in [({'available_at': '2026-11-01T00:00:00Z'}, 'AVAILABLE_AFTER_CUTOFF'),
                                 ({'source_time': None}, 'SOURCE_TIME_UNKNOWN')]:
            self.assertIn(expected, classify(requirement(), observation(**change), NOW)['reasons'])

    def test_units_period_and_basis_are_not_silently_reconciled(self):
        for field in ('unit', 'period', 'basis'):
            self.assertIn('MISMATCH_' + field.upper(), classify(requirement(), observation(**{field: 'different'}), NOW)['reasons'])
        req = requirement(); req.pop('unit')
        result = resolve(req, [observation(), observation('two', 'independent', unit='USD')], NOW)
        self.assertEqual(result['reasons'], ['NOT_COMPARABLE'])

    def test_shared_upstream_is_not_independent_and_duplicate_is_rejected(self):
        result = resolve(requirement(), [observation(), observation('two')], NOW)
        self.assertEqual(result['status'], 'needs_check')
        self.assertEqual(result['reasons'], ['INSUFFICIENT_INDEPENDENT_LINEAGE'])
        with self.assertRaisesRegex(SourceError, 'POLICY_DUPLICATE_OBSERVATION'):
            resolve(requirement(), [observation(), observation()], NOW)

    def test_numeric_agreement_and_disagreement(self):
        rows = [observation(), observation('two', 'independent', value='100.5')]
        result = resolve(requirement(), rows, NOW)
        self.assertEqual(result['status'], 'supported')
        self.assertFalse(result['semantic_truth_verified'])
        rows[1]['payload']['value'] = '104'
        conflict = resolve(requirement(), rows, NOW)
        self.assertEqual(conflict['reasons'], ['CONFLICTING_VALUES'])
        self.assertEqual(resolve(requirement(), rows, '2026-10-31T00:10:00Z')['status'], 'restricted')

    def test_exception_is_scoped_to_exact_versions_and_requires_attempt_and_sensitivity(self):
        req, rows = requirement(), [observation()]
        bindings = [{'id': 'one', 'revision': 1, 'lifecycle_revision': 1}]
        review = {'kind': 'primary_only', 'requirement_sha256': digest(req), 'bindings': bindings,
                  'reason': 'Only original disclosure covers this observation; sensitivity reviewed.',
                  'review_ref': {'path': '/review', 'sha256': 'a' * 64},
                  'alternative_attempt_ref': {'path': '/attempt', 'sha256': 'b' * 64},
                  'sensitivity_ref': {'path': '/sensitivity', 'sha256': 'c' * 64}}
        self.assertEqual(resolve(req, rows, NOW, exception=review)['status'], 'supported')
        rows[0]['revision'] = 2
        self.assertEqual(resolve(req, rows, NOW, exception=review)['status'], 'needs_check')
        rows[0]['revision'] = 1; review.pop('sensitivity_ref')
        self.assertEqual(resolve(req, rows, NOW, exception=review)['status'], 'needs_check')

    def test_bounds_require_review_of_exact_conflict(self):
        req, rows = requirement(), [observation(), observation('two', 'independent', value='110')]
        bindings = [{k: row[k] for k in ('id', 'revision', 'lifecycle_revision')} for row in rows]
        review = {'kind': 'bounded_use', 'requirement_sha256': digest(req), 'bindings': bindings,
                  'reason': 'Both plausible observations were propagated into the reviewed model range.',
                  'review_ref': {'path': '/review', 'sha256': 'a' * 64},
                  'calculation_ref': {'path': '/calculation', 'sha256': 'b' * 64}, 'low': '100', 'high': '110'}
        result = resolve(req, rows, NOW, remaining_attempts=0, reviewed_bounds=review)
        self.assertEqual(result['status'], 'bounded')
        review['bindings'] = []
        self.assertEqual(resolve(req, rows, NOW, remaining_attempts=0, reviewed_bounds=review)['status'], 'restricted')

    def test_schedule_respects_access_dependencies_and_retry_after(self):
        self.assertEqual(schedule_check(requirement(), {'reasons': ['AUTH_REQUIRED']}, NOW)['resume_condition'], 'access_changed')
        self.assertEqual(schedule_check(requirement(), {'reasons': ['RATE_LIMITED'], 'retry_after_seconds': 700}, NOW)['resume_condition'], 'wait_exceeds_deadline')
        scheduled = schedule_check(requirement(), {'reasons': ['TIMEOUT']}, NOW)
        self.assertEqual(scheduled['next_check_at'], '2026-10-31T00:00:30+00:00')

    def test_postponement_never_moves_deadline_or_extends_data_age(self):
        req = requirement()
        for attempt in range(10):
            scheduled = schedule_check(req, {'reasons': ['TIMEOUT']}, NOW, attempt)
            self.assertEqual(scheduled['decision_deadline'], '2026-10-31T00:10:00+00:00')
        self.assertEqual(schedule_check(req, {}, '2026-10-31T00:10:00Z')['resume_condition'], 'deadline_expired')

    def test_nonfinite_numeric_and_missing_current_policy_fail_visibly(self):
        rows = [observation(), observation('two', 'independent', value='NaN')]
        with self.assertRaises(SourceError): resolve(requirement(), rows, NOW)
        self.assertIn('FRESHNESS_POLICY_REQUIRED', classify(requirement(max_age_seconds=None), observation(), NOW)['reasons'])

    def test_missing_required_value_and_expired_decision_cannot_be_supported(self):
        self.assertIn('MISSING_NUMERIC_VALUE', classify(requirement(value_kind='numeric'), observation(value=None), NOW)['reasons'])
        result = resolve(requirement(), [observation(), observation('two', 'independent')], '2026-10-31T00:10:00Z')
        self.assertEqual(result['status'], 'restricted')
        self.assertEqual(result['reasons'], ['DECISION_DEADLINE_EXPIRED'])


if __name__ == '__main__':
    unittest.main()
