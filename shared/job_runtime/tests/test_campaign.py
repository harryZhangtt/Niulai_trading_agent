"""Campaign guards use virtual time; actual process/host proof is separate."""
from datetime import datetime, timezone
import copy
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import json
import uuid

from shared.job_runtime.campaign import decision, apply_result, digest_sources, protected_sources, sources, step_progress, execute
from shared.job_runtime.model import _terminate

ROOT = Path(__file__).resolve().parents[3]


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.config = {'expires_at': 43200, 'max_calls': 16, 'max_model_seconds': 7200, 'max_tokens': 500000}
        self.state = {'status': 'active', 'calls': 0, 'model_seconds': 0, 'tokens': 0, 'no_progress': 0,
                      'same_failure': 0, 'active_attempt': None, 'last_tick': 0,
                      'seen_sources': [digest_sources({'a': 'original'})]}

    def test_full_window_and_expiry_no_catchup(self):
        for second in range(0, 43200, 900):
            self.assertIsNone(decision(self.config, self.state, datetime.fromtimestamp(second, timezone.utc)))
            self.state['last_tick'] = second
        for second in (43200, 90000, 1000000):
            self.assertEqual(decision(self.config, self.state, datetime.fromtimestamp(second, timezone.utc)), 'expired')

    def test_every_budget_independently_stops(self):
        for field, maximum in [('calls', 16), ('model_seconds', 7200), ('tokens', 500000)]:
            state = copy.deepcopy(self.state); state[field] = maximum
            self.assertEqual(decision(self.config, state, datetime.fromtimestamp(10, timezone.utc)), 'stopped_budget')

    def test_active_crash_is_unknown_and_clock_rollback_stops(self):
        self.state['active_attempt'] = 'orphan'
        self.assertEqual(decision(self.config, self.state, datetime.fromtimestamp(10, timezone.utc)), 'unknown')
        self.state['active_attempt'] = None; self.state['last_tick'] = 100
        self.assertEqual(decision(self.config, self.state, datetime.fromtimestamp(90, timezone.utc)), 'unknown')

    def test_two_noops_stop_even_when_model_claims_success(self):
        result = {'status': 'succeeded', 'code': 'OK'}
        for _ in range(2):
            self.assertFalse(apply_result(self.state, result, {'a': 'original'}, {'a': 'original'}, True))
        self.assertEqual(self.state['status'], 'stopped_stalled')

    def test_failed_checks_do_not_count_as_progress_and_cycles_stop(self):
        self.assertFalse(apply_result(self.state, {'code': 'CHECK_BAD'}, {'a': 'original'}, {'a': 'new'}, False))
        self.assertFalse(apply_result(self.state, {'code': 'CHECK_BAD'}, {'a': 'new'}, {'a': 'other'}, False))
        self.assertEqual(self.state['status'], 'stopped_stalled')
        self.state = {'seen_sources': [digest_sources({'a': 'original'})], 'no_progress': 0, 'same_failure': 0}
        self.assertTrue(apply_result(self.state, {}, {'a': 'original'}, {'a': 'new'}, True))
        self.assertFalse(apply_result(self.state, {}, {'a': 'new'}, {'a': 'original'}, True))
        self.assertEqual(self.state['status'], 'stopped_stalled')

    def test_real_crossprocess_lock_and_release_after_death(self):
        parent = ROOT / '.job-runtime/tests'; parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temp:
            path = Path(temp) / 'lock'
            script = "import fcntl,sys,time; f=open(sys.argv[1],'w'); fcntl.flock(f,fcntl.LOCK_EX); print('locked',flush=True); time.sleep(30)"
            p = subprocess.Popen([sys.executable, '-c', script, str(path)], stdout=subprocess.PIPE, text=True, start_new_session=True)
            try:
                self.assertEqual(p.stdout.readline().strip(), 'locked')
                with path.open() as stream:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    _terminate(p)
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                _terminate(p); p.stdout.close()

    def test_protected_sources_ignore_private_output_but_detect_code_change(self):
        parent = ROOT / '.job-runtime/tests'; parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temp:
            work = Path(temp); (work / 'AGENTS.md').write_text('policy')
            before = protected_sources(work)
            (work / '.niulai-state').mkdir(); (work / '.niulai-state/output.json').write_text('{}')
            self.assertEqual(before, protected_sources(work))
            (work / 'AGENTS.md').write_text('changed')
            self.assertNotEqual(before, protected_sources(work))

    def test_checkpoint_and_report_churn_are_not_implementation(self):
        parent = ROOT / '.job-runtime/tests'; parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temp:
            work = Path(temp); (work / 'docs').mkdir()
            (work / 'investment/runtime').mkdir(parents=True)
            (work / 'shared/research_sources/reports').mkdir(parents=True)
            before = sources(work)
            for step in 'ABCDEF':
                (work / 'docs/campaign-progress.json').write_text(json.dumps({'step': step, 'completed': True}))
                (work / 'docs/design.json').write_text(json.dumps({'phase': step}))
                (work / 'investment/runtime/status.py').write_text('state = ' + repr(step))
                (work / 'shared/research_sources/reports/output.json').write_text(json.dumps({'phase': step}))
                after = sources(work)
                self.assertEqual(before, after)
                self.assertFalse(apply_result(self.state, {'code': 'OK'}, before, after, True))
            self.assertEqual(self.state['status'], 'stopped_stalled')

    def test_step_contract_requires_its_own_changed_code_and_artifacts(self):
        parent = ROOT / '.job-runtime/tests'; parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temp:
            work = Path(temp); (work / 'shared/research_sources/tests').mkdir(parents=True)
            before = sources(work)
            (work / 'shared/research_sources/store.py').write_text('class Store: pass\n')
            after = sources(work)
            self.assertFalse(step_progress('B', work, before, after)['passed'])
            (work / 'shared/research_sources/tests/test_store.py').write_text('import unittest\n')
            after = sources(work)
            contract = step_progress('B', work, before, after)
            self.assertTrue(contract['passed'])
            self.assertFalse(step_progress('D', work, before, after)['passed'])
            self.assertTrue(apply_result(self.state, {'code': 'OK'}, before, after, contract['passed']))

    def test_pilot_contract_rejects_empty_or_unrelated_json(self):
        parent = ROOT / '.job-runtime/tests'; parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temp:
            work = Path(temp); directory = work / 'investment/research/examples'; directory.mkdir(parents=True)
            before = sources(work); path = directory / 'pilot.json'
            path.write_text('{"completed":true}')
            self.assertFalse(step_progress('A', work, before, sources(work))['passed'])
            path.write_text(json.dumps({'schema_version': 1, 'case_id': 'fact', 'source_url': 'https://example.test/fact',
                'entity': 'AAA', 'metric': 'revenue', 'observations': [{'value': '1'}], 'comparison': {'tolerance': '0'}}))
            self.assertTrue(step_progress('A', work, before, sources(work))['passed'])

    def test_checkpoint_only_execute_stops_after_two_real_baseline_checks(self):
        parent = ROOT / '.job-runtime/tests'; parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temp:
            base = Path(temp); work = base / 'work'; work.mkdir(); (work / 'docs').mkdir()
            for relative in ('investment/research/tests', 'shared/research_sources/tests'):
                directory = work / relative; directory.mkdir(parents=True)
                (directory / 'test_existing.py').write_text('import unittest\nclass Existing(unittest.TestCase):\n def test_baseline(self): self.assertEqual(2+2,4)\n')
            at = datetime.now(timezone.utc)
            config = {**self.config, 'expires_at': at.timestamp() + 600, 'slice_seconds': 30,
                      'worktree': str(work), 'research_python': sys.executable}
            state = {**self.state, 'step': 0, 'seen_sources': [digest_sources(sources(work))]}
            def fake_turn(*args):
                (work / 'docs/campaign-progress.json').write_text(json.dumps({'step': 'A', 'completed': True,
                    'blocker': None, 'next_action': str(state['calls'])}))
                return {'status': 'succeeded', 'code': 'DEVELOPMENT_TURN_COMPLETED',
                        'receipt': {'elapsed_seconds': 0.01, 'usage': {'input_tokens': 1, 'output_tokens': 0}}}
            with patch('shared.job_runtime.campaign.production_busy', return_value=False), \
                 patch('mentor.session_init.initialize', return_value={'hookSpecificOutput': {'additionalContext': 'MENTOR_INIT_OK\nsynthetic test'}}), \
                 patch('shared.job_runtime.campaign.development_turn', side_effect=fake_turn) as model:
                for _ in range(2):
                    result = execute(config, state, ROOT, base, {'attempt_id': str(uuid.uuid4())})
                    self.assertEqual(result['status'], 'succeeded')
                self.assertEqual(state['step'], 0)
                self.assertEqual(state['status'], 'stopped_stalled')
                self.assertEqual(state['calls'], 2)
                result = execute(config, state, ROOT, base, {'attempt_id': str(uuid.uuid4())})
                self.assertEqual(result['code'], 'CAMPAIGN_GUARD_STOP')
                self.assertEqual(model.call_count, 2)


if __name__ == '__main__':
    unittest.main()
