"""Post-result regression for the demonstrated Q04 measurement defect.

This is separate from the frozen grading tests and is not fresh efficacy evidence.
"""
import unittest

from summarize import comparison


class MeasurementReviewTests(unittest.TestCase):
    def test_known_measurement_defect_cannot_create_a_skill_advantage(self):
        cases = [{'id': 'Q01', 'severity': 'critical'}, {'id': 'Q04', 'severity': 'major'}]
        general = {'Q01': {'passed': True}, 'Q04': {'passed': False}}
        routed = {'Q01': {'passed': True}, 'Q04': {'passed': True}}
        result = comparison(cases, general, routed, {'Q04': {'reason': 'demonstrated false failure'}})
        self.assertEqual(result['implementation_quality_advantage'], 'inconclusive')
        self.assertEqual(result['general_valid_passed'], result['routed_valid_passed'])


if __name__ == '__main__':
    unittest.main()
