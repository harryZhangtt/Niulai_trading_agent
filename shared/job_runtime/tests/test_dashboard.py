"""Read-only dashboard boundaries and actual next-slot calculations; no dispatch."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import patch

from shared.job_runtime import dashboard as view
from shared.job_runtime.config import ConfigError, load


class DashboardTests(unittest.TestCase):
    def setUp(self):
        parent = view.ROOT / 'ui/runtime/scheduler-20261103/tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.job-runtime/config').mkdir(parents=True, mode=0o700)
        (self.root / '.job-runtime').chmod(0o700)
        self.at = datetime(2026, 11, 2, 16, tzinfo=timezone.utc)
        self.job = {'id': 'synthetic.job', 'enabled': True, 'replay_safe': True, 'model_profile': 'default',
                    'prompt_file': 'task.md', 'schedule': {'kind': 'daily', 'timezone': 'America/New_York',
                    'times': ['13:00', '19:00'], 'grace_seconds': 3600}}
        self.config = {'schema_version': 1, 'tick_seconds': 5, 'heartbeat_seconds': 5, 'stale_seconds': 90,
                       'max_workers': 2, 'retry': {}, 'source_paths': [], 'allocation_files': ['.job-runtime/config/jobs.json'],
                       'model_profiles': {'default': {'auth_home': str(self.root / '.job-runtime/auth'), 'model': 'synthetic'}}}
        self.write('.job-runtime/config/runtime.json', self.config)
        self.write('.job-runtime/config/jobs.json', {'schema_version': 1, 'jobs': [self.job]})
        (self.root / 'task.md').write_text('A synthetic job. api_key=SYNTHETIC_CANARY\nBearer SYNTHETIC_BEARER')
        self.write('.job-runtime/heartbeat.json', {'at': self.at.isoformat(), 'pid': os.getpid()})
        self.write('.job-runtime/watchdog.json', {'checked_at': self.at.isoformat(), 'healthy': True})

    def write(self, name, data):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        p.write_text(json.dumps(data)); p.chmod(0o600)

    def project(self, **kw):
        return view.project(self.root, at=self.at, **kw)

    def test_detail_is_scoped_scrubbed_and_does_not_copy_auth_configuration(self):
        result = self.project(job_id=self.job['id'])
        self.assertEqual(result['health']['state'], 'healthy')
        self.assertEqual(result['jobs'][0]['next_run_at'], '2026-11-02T18:00:00+00:00')
        body = json.dumps(result)
        self.assertNotIn('SYNTHETIC_CANARY', body); self.assertNotIn('SYNTHETIC_BEARER', body)
        self.assertNotIn('auth_home', body); self.assertNotIn(str(self.root), body)
        self.assertNotIn('content', result['jobs'][0])
        self.assertEqual(result['jobs'][0]['prompt_custody'], {'status': 'unavailable', 'attempts_bound': 0})

    def test_prompt_projection_exposes_no_body_path_basename_or_digest(self):
        nested = self.root / 'tasks' / 'nested' / 'instructions.md'
        nested.parent.mkdir(parents=True)
        nested.write_text('Synthetic nested prompt.')
        changed = {**self.job, 'prompt_file': 'tasks/nested/instructions.md'}
        self.write('.job-runtime/config/jobs.json', {'schema_version': 1, 'jobs': [changed]})
        result = self.project(job_id=self.job['id'])
        body = json.dumps(result)
        self.assertNotIn('content', result['jobs'][0])
        self.assertNotIn('instructions.md', body)
        self.assertNotIn('tasks/nested', body)
        self.assertNotIn(hashlib.sha256(nested.read_bytes()).hexdigest(), body)

    def test_new_allocation_appears_without_a_ui_job_list_and_disabled_has_no_next_run(self):
        other = {**self.job, 'id': 'another.job', 'enabled': False}
        self.write('.job-runtime/config/jobs.json', {'schema_version': 1, 'jobs': [self.job, other]})
        jobs = self.project()['jobs']
        self.assertEqual([j['id'] for j in jobs], ['synthetic.job', 'another.job'])
        self.assertIsNone(jobs[1]['next_run_at'])

    def test_dst_boundary_and_calendar_filter(self):
        before = datetime(2026, 10, 30, 15, tzinfo=timezone.utc)
        self.assertEqual(view.next_tick(self.job['schedule'], before), '2026-10-30T17:00:00+00:00')
        self.assertEqual(view.next_tick(self.job['schedule'], self.at), '2026-11-02T18:00:00+00:00')
        sunday = datetime(2026, 11, 1, 0, tzinfo=timezone.utc)
        self.assertEqual(view.next_tick(self.job['schedule'], sunday, lambda d: d.weekday() < 5), '2026-11-02T18:00:00+00:00')
        self.assertEqual(view.next_tick({'kind': 'interval', 'seconds': 300}, self.at), '2026-11-02T16:05:00+00:00')
        self.assertIsNone(view.next_tick({'kind': 'once', 'at': '2020-01-01T00:00:00Z'}, self.at))

    def test_sequence_projects_next_run_for_list_and_detail_then_finishes(self):
        schedule = {'kind': 'sequence', 'timestamps': ['2026-11-02T15:00:00Z',
                    '2026-11-02T17:00:00Z', '2026-11-02T18:00:00+00:00'], 'grace_seconds': 60}
        sequence_job = {**self.job, 'schedule': schedule}
        self.write('.job-runtime/config/jobs.json', {'schema_version': 1, 'jobs': [sequence_job]})
        for result in (self.project(), self.project(job_id=self.job['id'])):
            self.assertEqual(result['jobs'][0]['schedule'], schedule)
            self.assertEqual(result['jobs'][0]['next_run_at'], '2026-11-02T17:00:00+00:00')
        exhausted = {**sequence_job, 'schedule': {**schedule, 'timestamps': ['2026-11-02T15:00:00Z']}}
        self.write('.job-runtime/config/jobs.json', {'schema_version': 1, 'jobs': [exhausted]})
        self.assertIsNone(self.project()['jobs'][0]['next_run_at'])
        self.assertIsNone(self.project(job_id=self.job['id'])['jobs'][0]['next_run_at'])

    def test_bad_identity_and_symlink_prompt_projection_is_metadata_only(self):
        with self.assertRaises(ValueError): self.project(job_id='../auth')
        with self.assertRaises(ValueError): self.project(job_id='missing')
        with self.assertRaises(ValueError): self.project(output_id='a' * 64)
        outside = self.root / 'auth.json'
        secret = 'SYNTHETIC_PRIVATE_SYMLINK_BODY'
        outside.write_text(secret)
        prompt = self.root / 'task.md'
        prompt.unlink(); prompt.symlink_to(outside)

        result = self.project(job_id=self.job['id'])
        encoded = json.dumps(result)
        self.assertEqual(result['jobs'][0]['id'], self.job['id'])
        for forbidden in (secret, 'task.md', 'auth.json', str(prompt), str(outside),
                          hashlib.sha256(secret.encode()).hexdigest()):
            self.assertNotIn(forbidden, encoded)
        with self.assertRaisesRegex(ConfigError, 'SYMLINK_REJECTED|PROMPT_INVALID'):
            load(self.root / '.job-runtime/config/runtime.json', self.root)

    def test_fifo_prompt_projection_does_not_open_body_but_admission_rejects_it(self):
        prompt = self.root / 'task.md'
        prompt.unlink(); os.mkfifo(prompt)

        result = self.project(job_id=self.job['id'])
        encoded = json.dumps(result)
        self.assertEqual(result['jobs'][0]['id'], self.job['id'])
        for forbidden in ('task.md', str(prompt), 'SYNTHETIC_FIFO_BODY'):
            self.assertNotIn(forbidden, encoded)
        with self.assertRaisesRegex(ConfigError, 'PROMPT_INVALID'):
            load(self.root / '.job-runtime/config/runtime.json', self.root)

    def test_history_reads_do_not_mutate_ledger_or_leak_receipts(self):
        path = self.root / '.job-runtime/engine/schedule.sqlite'; path.parent.mkdir(mode=0o700)
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE slots(slot_id TEXT,job_id TEXT,scheduled_at REAL,status TEXT,attempts INTEGER,code TEXT,updated_at REAL)')
            db.execute('INSERT INTO slots VALUES(?,?,?,?,?,?,?)', ('slot:secret', self.job['id'], self.at.timestamp(), 'succeeded', 1, 'DAILY_NOT_DUE', self.at.timestamp()))
        before = path.read_bytes()
        result = self.project(job_id=self.job['id'])
        self.assertEqual(result['jobs'][0]['history'][0]['code'], 'DAILY_NOT_DUE')
        self.assertNotIn('slot:secret', json.dumps(result))
        self.assertEqual(path.read_bytes(), before)
        with view.database(self.root, path) as db:
            with self.assertRaises(sqlite3.OperationalError): db.execute('DELETE FROM slots')

    def test_stale_heartbeat_is_not_healthy(self):
        self.write('.job-runtime/heartbeat.json', {'at': '2026-11-01T00:00:00Z', 'pid': os.getpid()})
        self.assertEqual(self.project()['health']['state'], 'stale')

    def test_quoted_json_fields_and_multiline_private_keys_are_scrubbed(self):
        text='{"access_token": "SYNTHETIC_JSON", "password": "SYNTHETIC_PASSWORD"}\n-----BEGIN PRIVATE KEY-----\nSYNTHETIC_KEY\n-----END PRIVATE KEY-----'
        result=view.scrub(text)
        for secret in ('SYNTHETIC_JSON','SYNTHETIC_PASSWORD','SYNTHETIC_KEY'):
            self.assertNotIn(secret,result)

    def test_generic_job_cannot_open_an_arbitrary_saved_output(self):
        with self.assertRaises(ValueError): self.project(job_id=self.job['id'], output_id='a' * 64)

    def test_only_exact_mentor_adapter_uses_mentor_discriminator(self):
        mentor = {**self.job, 'adapter': 'mentor.scheduler.job_adapter:prepare'}
        result = view.domain(self.root, mentor, self.at)
        self.assertEqual(result['job_type'], 'mentor')
        self.assertEqual(result['mentor'], {'status': 'unavailable'})
        impostor = {**self.job, 'adapter': 'mentor.scheduler.job_adapter:other'}
        self.assertNotIn('job_type', view.domain(self.root, impostor, self.at))

    def test_full_mentor_projection_suppresses_generic_prompt_history_and_outputs(self):
        mentor = {
            'work_order': {'id': 'synthetic-order', 'logical_session_id': 'synthetic-order',
                           'starts_at': self.at.isoformat(), 'ends_at': self.at.isoformat(),
                           'window_state': 'expired', 'acceptance_criteria_total': 1,
                           'required_event_kinds': ['provider_thread', 'cycle']},
            'scheduler': {'status': 'failed', 'code': 'OPERATOR_RECONCILED', 'attempts': 1,
                          'dispatch': 'definitely_not_dispatched'},
            'session': {'status': 'active', 'revision': 0},
            'progress': {'cycles': {'used': 0, 'limit': 2}, 'provider_threads': {'used': 0, 'limit': 2},
                         'variants': {'used': 0, 'limit': 1}, 'interventions': {'used': 0, 'limit': 0},
                         'reused_evaluations': {'used': 0, 'limit': 0}, 'pending_effects': 0},
            'safeguards': {'provider_thread_mode': 'ephemeral_threads', 'record_all_variants': True,
                           'worker_holdout_access': False, 'require_no_pending_effects': True,
                           'configured_replay_safe': True, 'replay_authorization': 'not_authorized'},
            'gates': {'future_wake': 'verified', 'profile_binding': 'not_verified',
                      'stop_propagation': 'not_verified', 'model_turn': 'failed',
                      'journal_cycle_postcondition': 'not_verified', 'no_duplicate_dispatch': 'verified'},
            'evaluation': {'attempt_ledger_preserved': True, 'baseline': 'pending',
                           'ablation': 'not_required', 'holdout': 'unverified', 'promotion': 'inconclusive'},
            'runtime_acceptance': {'execution': 'failed', 'acceptance': 'failed',
                                   'model_turn': 'not_started', 'email': 'pending'},
            'recovery_timeline': [],
        }
        provider = {'job_type': 'mentor', 'title': 'Mentor scheduler acceptance',
                    'description': 'Read-only mentor scheduler status.',
                    'delivery': {'mode': 'acceptance', 'next_send_at': None, 'note': 'Synthetic.'},
                    'outputs': [], 'mentor': mentor}
        with patch.object(view, 'domain', return_value=provider):
            result = self.project(job_id=self.job['id'])
        job = result['jobs'][0]
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(job['mentor'], mentor)
        self.assertEqual(job['history'], [])
        self.assertEqual(job['outputs'], [])
        self.assertNotIn('content', job)
        self.assertNotIn('SYNTHETIC_CANARY', json.dumps(result))

    def test_mentor_unavailable_marks_outer_projection_partial_with_sanitized_warning(self):
        with patch.object(view, 'domain', return_value={
            'job_type': 'mentor', 'title': 'Mentor scheduler acceptance',
            'description': 'Read-only mentor scheduler status.',
            'delivery': {'mode': 'acceptance', 'next_send_at': None, 'note': 'Synthetic.'},
            'outputs': [], 'mentor': {'status': 'unavailable'},
        }):
            result = self.project()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['jobs'][0]['job_type'], 'mentor')
        self.assertEqual(result['jobs'][0]['mentor'], {'status': 'unavailable'})
        self.assertEqual(result['warnings'], [{'job_id': self.job['id'], 'code': 'JOB_DETAILS_UNAVAILABLE'}])
        self.assertNotIn('Synthetic.', json.dumps(result['warnings']))

    def test_failed_mentor_timeline_marks_partial_without_hiding_unrelated_job(self):
        other = {**self.job, 'id': 'unrelated.job'}
        self.write('.job-runtime/config/jobs.json', {'schema_version': 1, 'jobs': [self.job, other]})
        unavailable = {'job_type': 'mentor', 'title': 'Mentor scheduler acceptance',
                       'description': 'Read-only mentor scheduler status.',
                       'delivery': {'mode': 'acceptance', 'next_send_at': None, 'note': 'Synthetic.'},
                       'outputs': [], 'mentor': {'status': 'unavailable'}}
        generic = {'title': 'unrelated.job', 'description': 'Scheduled Codex task',
                   'delivery': {'mode': 'unspecified', 'next_send_at': None,
                                'note': 'This job does not declare a message delivery schedule.'},
                   'outputs': []}
        with patch.object(view, 'domain', side_effect=lambda _root, job, _at, **_kw:
                          unavailable if job['id'] == self.job['id'] else generic):
            result = self.project()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['jobs'][0]['mentor'], {'status': 'unavailable'})
        self.assertEqual(result['jobs'][1]['id'], 'unrelated.job')
        self.assertEqual(result['warnings'], [{'job_id': self.job['id'], 'code': 'JOB_DETAILS_UNAVAILABLE'}])

    def test_exact_niulai_adapter_regression_uses_fixed_provider(self):
        expected = {'job_type': 'niulai', 'title': 'Synthetic Niulai', 'description': 'Synthetic',
                    'delivery': {'mode': 'test', 'next_send_at': None, 'note': 'Synthetic'}, 'outputs': []}
        niulai = {**self.job, 'adapter': 'niulai_runtime.daily_job:prepare'}
        package = types.ModuleType('niulai_runtime')
        provider = types.ModuleType('niulai_runtime.scheduler_view')
        package.scheduler_view = provider
        with patch.dict('sys.modules', {
                'niulai_runtime': package, 'niulai_runtime.scheduler_view': provider}), \
                patch.object(provider, 'describe', return_value=expected, create=True) as describe:
            self.assertEqual(view.domain(self.root, niulai, self.at), expected)
        describe.assert_called_once()


if __name__ == '__main__':
    unittest.main()
