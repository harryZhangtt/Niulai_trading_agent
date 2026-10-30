"""Negative artifact controls, independent of any solver's implementation."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from grade import RUN, immutable_errors, parse_cases


def spec(cid, outcome='passed', **extra):
    return {'title': cid + ' scenario', 'tests': [{'results': [{'status': outcome, **extra}]}]}


class GradingTests(unittest.TestCase):
    def test_complete_pass_and_real_failed_case_remain_distinct(self):
        cases = parse_cases({'suites': [{'specs': [spec('Q01'), spec('Q02', 'failed')]}]}, ['Q01', 'Q02'])
        self.assertTrue(cases['Q01']['passed'])
        self.assertFalse(cases['Q02']['passed'])

    def test_missing_duplicate_extra_skipped_and_retried_cases_rejected(self):
        report = lambda entries: {'suites': [{'specs': entries}]}
        for entries in ([spec('Q01')], [spec('Q01'), spec('Q01')],
                        [spec('Q01'), spec('Q02'), spec('Q03')],
                        [spec('Q01'), spec('Q02', 'skipped')]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                parse_cases(report(entries), ['Q01', 'Q02'])
        retried = spec('Q02')
        retried['tests'][0]['results'].append({'status': 'passed'})
        with self.assertRaises(ValueError):
            parse_cases(report([spec('Q01'), retried]), ['Q01', 'Q02'])

    def test_global_start_failure_cannot_count_as_behavioral_pass(self):
        with self.assertRaises(ValueError):
            parse_cases({'suites': [{'specs': [spec('Q01')]}], 'errors': [{'message': 'server failed'}]}, ['Q01'])

    def test_immutable_change_and_symlink_escape_fail(self):
        parent = RUN / 'grader-tests'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            worker = Path(directory)
            (worker / 'app/vendor').mkdir(parents=True)
            source = worker / 'app/vendor/probe.ts'
            source.write_text('immutable observable probe')
            protected = {'app/vendor/probe.ts': hashlib.sha256(source.read_bytes()).hexdigest()}
            self.assertEqual(immutable_errors(worker, protected), [])
            source.write_text('deleted counter')
            self.assertTrue(immutable_errors(worker, protected))
            source.unlink()
            source.symlink_to(__file__)
            self.assertTrue(immutable_errors(worker, protected))


if __name__ == '__main__':
    unittest.main()
