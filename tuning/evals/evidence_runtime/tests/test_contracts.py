"""Development conformance for the contract mechanism; not a blind benchmark."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from shared.research_sources.artifacts import ROOT, SOURCE_STATE, SourceError, read, save
from tuning.evals.evidence_runtime import contracts as c


def host_grade(case_id, inputs, expected, output):
    matched = output['observed'] == expected['value']
    return {'passed': matched, 'metrics': {'correct': matched, 'tokens': None},
            'reasons': [] if matched else ['OBSERVATION_MISMATCH']}


def missing_metric(case_id, inputs, expected, output):
    return {'passed': True, 'metrics': {'correct': True}, 'reasons': []}


def crashing_grade(case_id, inputs, expected, output):
    raise RuntimeError('synthetic-private-exception')


def exit_grade(case_id, inputs, expected, output):
    os._exit(71)


class ContractTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.spec_path = self.directory / 'cases.json'
        self.grader_path = self.directory / 'grader.py'
        self.grader_path.write_text('# Explicit second grader dependency.\n')
        self.pins = {'baseline': 'a' * 64, 'candidate': 'b' * 64}
        self.spec = {'id': 'contract-development', 'version': 1, 'split': 'development',
            'blindness': 'answers_withheld', 'metrics': ['correct', 'tokens'],
            'budget': {'seconds': 10, 'calls': 2},
            'cases': [{'id': 'ordinary', 'input': {'kind': 'ordinary'}, 'expected': {'value': 10}, 'critical': False},
                      {'id': 'critical', 'input': {'kind': 'critical'}, 'expected': {'value': 20}, 'critical': True}]}
        self.write_spec()
        self.ref = self.seal()

    def write_spec(self):
        self.spec_path.write_text(json.dumps(self.spec))

    def seal(self):
        return c.seal(self.spec_path, [self.grader_path, Path(__file__)], self.pins, self.directory / 'sealed-eval')

    def begin(self, attempt_id='attempt', arm='candidate', **kwargs):
        return c.begin(self.ref, self.directory / 'runs', attempt_id, arm=arm,
            budget=kwargs.pop('budget', self.spec['budget']), fingerprint=kwargs.pop('fingerprint', self.pins[arm]), **kwargs)

    def submissions(self, *, critical=20):
        return [{'id': key, 'output_ref': save(self.directory / 'outputs', {'observed': value})}
                for key, value in (('ordinary', 10), ('critical', critical))]

    def finish(self, attempt_id='attempt', **kwargs):
        return read(c.finish(self.ref, self.directory / 'runs', attempt_id,
            submissions=kwargs.pop('submissions', self.submissions()),
            usage=kwargs.pop('usage', {'seconds': 1, 'calls': 2}), grade=kwargs.pop('grade', host_grade), **kwargs))

    def test_seal_idempotent_separate_packets_and_unknown_metrics(self):
        self.assertEqual(self.ref, self.seal())
        contract = c.validate(self.ref, candidate_fingerprints=self.pins)
        self.assertNotEqual(contract['cases'][0]['input_ref'], contract['cases'][0]['expected_ref'])
        packet = c.worker_packet(self.ref)
        self.assertNotIn('expected_ref', json.dumps(packet))
        self.assertEqual(packet['blindness_enforcement'], 'packet_separation_only_no_os_isolation')
        self.begin()
        result = self.finish()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['unknown_metrics'], [{'case_id': 'ordinary', 'metric': 'tokens'}, {'case_id': 'critical', 'metric': 'tokens'}])
        self.assertFalse(result['superiority_established'])

    def test_expected_artifact_and_current_spec_tamper_rejected(self):
        contract = c.validate(self.ref)
        expected_path = Path(contract['cases'][0]['expected_ref']['path'])
        original = expected_path.read_bytes()
        expected_path.write_bytes(b'{}')
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_HASH_MISMATCH'):
            c.validate(self.ref)
        expected_path.write_bytes(original)
        self.spec['cases'][0]['expected']['value'] = 11
        self.write_spec()
        with self.assertRaisesRegex(SourceError, 'EVAL_SOURCE_CHANGED'):
            c.validate(self.ref)
        with self.assertRaisesRegex(SourceError, 'EVAL_VERSION_CONFLICT'):
            self.seal()

    def test_changed_grader_or_candidate_pin_rejected(self):
        self.grader_path.write_text('# Modified grader dependency.\n')
        with self.assertRaisesRegex(SourceError, 'EVAL_SOURCE_CHANGED'):
            self.begin()
        self.grader_path.write_text('# Explicit second grader dependency.\n')
        with self.assertRaisesRegex(SourceError, 'EVAL_PIN_CHANGED'):
            c.validate(self.ref, candidate_fingerprints={**self.pins, 'candidate': 'c' * 64})
        with self.assertRaisesRegex(SourceError, 'EVAL_PIN_CHANGED'):
            self.begin(fingerprint='c' * 64)

    def test_exact_roster_no_omission_unknown_duplicate_or_self_reported_pass(self):
        original = self.submissions()
        variants = [(original[:1], 'EVAL_CASE_ROSTER_MISMATCH'),
                    (original + [original[0]], 'EVAL_DUPLICATE_SUBMISSION'),
                    ([original[0], {**original[1], 'id': 'unknown'}], 'EVAL_CASE_ROSTER_MISMATCH'),
                    ([{**original[0], 'passed': True}, original[1]], 'EVAL_SUBMISSION_SCHEMA')]
        for index, (submissions, expected) in enumerate(variants):
            attempt = 'roster-' + str(index)
            self.begin(attempt)
            result = self.finish(attempt, submissions=submissions)
            self.assertEqual(result['status'], 'failed')
            self.assertIn(expected, result['errors'])

    def test_critical_failure_cannot_be_averaged_into_success(self):
        self.begin()
        result = self.finish(submissions=self.submissions(critical=-1))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['critical_failures'], ['critical'])
        self.assertTrue(result['cases'][0]['passed'])
        self.assertFalse(result['cases'][1]['passed'])

    def test_fixed_arm_budgets_and_observed_usage_limits(self):
        with self.assertRaisesRegex(SourceError, 'EVAL_BUDGET_MISMATCH'):
            self.begin(budget={'seconds': 20, 'calls': 2})
        self.begin('baseline', arm='baseline')
        self.begin('candidate')
        self.assertEqual(self.finish('baseline')['status'], 'passed')
        result = self.finish('candidate', usage={'seconds': 11, 'calls': 2})
        self.assertEqual(result['status'], 'failed')
        self.assertIn('EVAL_BUDGET_EXCEEDED', result['errors'])

    def test_attempt_cannot_be_overwritten_and_failed_run_survives(self):
        first = self.begin()
        with self.assertRaisesRegex(SourceError, 'EVAL_ATTEMPT_EXISTS'):
            self.begin()
        result = self.finish(grade=crashing_grade)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errors'], ['EVAL_GRADER_FAILED'])
        self.assertNotIn('synthetic-private-exception', json.dumps(result))
        self.assertEqual(read(first)['state'], 'started')
        with self.assertRaisesRegex(SourceError, 'EVAL_ATTEMPT_FINISHED'):
            self.finish()

    def test_unknown_finish_after_process_death_cannot_replay(self):
        self.begin()
        submissions = self.submissions()
        code = '''
import json,sys
from tuning.evals.evidence_runtime.contracts import finish
from tuning.evals.evidence_runtime.tests.test_contracts import exit_grade
finish(json.loads(sys.argv[1]),sys.argv[2],'attempt',submissions=json.loads(sys.argv[3]),
       usage={'seconds':1,'calls':2},grade=exit_grade)
'''
        child = subprocess.run([sys.executable, '-c', code, json.dumps(self.ref), str(self.directory / 'runs'), json.dumps(submissions)],
            cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), capture_output=True, text=True, timeout=5)
        self.assertEqual(child.returncode, 71, child.stderr)
        with self.assertRaisesRegex(SourceError, 'EVAL_ATTEMPT_OUTCOME_UNKNOWN'):
            self.finish()
        with self.assertRaisesRegex(SourceError, 'EVAL_ATTEMPT_EXISTS'):
            self.begin()

    def test_nonblocking_claim_lock_and_required_metrics(self):
        root = self.directory / 'runs/attempts' / self.ref['sha256']
        root.mkdir(parents=True)
        with (root / 'claim.lock').open('w') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            started = time.monotonic()
            with self.assertRaisesRegex(SourceError, 'EVAL_CLAIM_BUSY'):
                self.begin()
            self.assertLess(time.monotonic() - started, .1)
        self.begin()
        result = self.finish(grade=missing_metric)
        self.assertIn('EVAL_REQUIRED_METRIC_MISSING', result['errors'])

    def test_duplicate_cases_and_undeclared_schema_rejected(self):
        forged = read(self.ref)
        forged['passed'] = True
        with self.assertRaisesRegex(SourceError, 'EVAL_CONTRACT_INVALID'):
            c.validate(save(self.directory / 'forged', forged))
        self.spec['cases'].append(self.spec['cases'][0])
        self.write_spec()
        with self.assertRaisesRegex(SourceError, 'EVAL_DUPLICATE_CASE'):
            self.seal()
        self.spec['cases'].pop()
        self.spec['self_reported_pass'] = True
        self.write_spec()
        with self.assertRaisesRegex(SourceError, 'EVAL_SPEC_SCHEMA'):
            self.seal()


if __name__ == '__main__':
    unittest.main()
