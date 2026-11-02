"""Meaningful negative checks for the frozen host grading boundary."""
import unittest
from grade import grade


class GradeBoundary(unittest.TestCase):
    def fixture(self, required, *, clarify=False, status='UI_ROUTE_OK', variants=None):
        return {'required_decisions': required, 'optional_decisions': [],
                'clarify': clarify, 'status': status, 'variants': variants}

    def evaluate(self, expected, plans, *, clarify=False, tools=()):
        return grade('check', {'available_tools': list(tools)}, expected,
                     {'id': 'check', 'needs_clarification': clarify,
                      'plans': [{'decisions': plan} for plan in plans]})

    def test_unneeded_frontend_body_fails_backend(self):
        result = self.evaluate(self.fixture(['backend-only']), [['visual-direction']])
        self.assertFalse(result['passed'])
        self.assertIn('UNNECESSARY_SKILL_LOADED', result['reasons'])

    def test_missing_async_safety_not_hidden_by_perf(self):
        result = self.evaluate(self.fixture(['async-state', 'react-performance']), [['react-performance']])
        self.assertFalse(result['passed'])
        self.assertIn('REQUIRED_SKILL_MISSING', result['reasons'])

    def test_blocked_pencil_is_expected_not_fake_success(self):
        expected = self.fixture(['pencil-design'], status='UI_ROUTE_BLOCKED')
        self.assertTrue(self.evaluate(expected, [['pencil-design']])['passed'])
        self.assertFalse(self.evaluate(expected, [['pencil-design']], tools=['pencil'])['passed'])

    def test_conflict_requires_clarification_and_no_plans(self):
        expected = self.fixture([], clarify=True)
        self.assertTrue(self.evaluate(expected, [], clarify=True)['passed'])
        self.assertFalse(self.evaluate(expected, [['hallmark-design', 'taste-design']], clarify=True)['passed'])

    def test_variant_union_cannot_hide_partition_failure(self):
        expected = self.fixture([], variants=[['hallmark-design'], ['taste-design']])
        self.assertTrue(self.evaluate(expected, [['taste-design'], ['hallmark-design']])['passed'])
        self.assertFalse(self.evaluate(expected, [['taste-design', 'hallmark-design']])['passed'])


if __name__ == '__main__':
    unittest.main()
