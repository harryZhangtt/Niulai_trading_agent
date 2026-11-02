"""Synthetic scheduling boundary checks; no launchd registration or model call."""
from datetime import datetime, timedelta
import copy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ui.portable.runtime_verification import scheduled as subject


class SchedulerFixture:
    def setUp(self):
        owner = subject.ROOT / 'ui/runtime/harry-ui-persistence-20261102/acceptance-plan'
        owner.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=owner)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        private = root / '.job-runtime/acceptance/harry-ui-persistence-20261102'
        private.mkdir(parents=True)
        config = root / '.job-runtime/config/runtime.json'
        config.parent.mkdir()
        config.write_text(json.dumps({'python_bin': '/synthetic/local/python', 'allocation_files': [], 'model_profiles': {}}))
        for name, value in [('ROOT', root), ('PRIVATE', private), ('PUBLIC', root / 'ui/runtime/probes'), ('CONFIG', config)]:
            fixture = patch.object(subject, name, value)
            fixture.start()
            self.addCleanup(fixture.stop)
        fixture = patch.object(subject, 'fingerprint', return_value={'synthetic': 'candidate-a'})
        self.fingerprint = fixture.start()
        self.addCleanup(fixture.stop)
        fixture = patch.object(subject, 'environment', return_value={'gui_domain_accessible': True, 'runtime_python_available': True})
        fixture.start()
        self.addCleanup(fixture.stop)

    def staged(self, due=False):
        staged = subject.stage('fixture', delay_seconds=60)
        path = Path(staged['record'])
        if due:
            record = json.loads(path.read_text())
            record['jobs'][0]['schedule']['at'] = (subject.now() - timedelta(seconds=1)).isoformat()
            path.write_text(json.dumps(record))
        return staged, path


class ScheduledTests(SchedulerFixture, unittest.TestCase):
    def primary(self, jobs, slots=()):
        allocation = subject.CONFIG.parent / 'primary-jobs.json'
        allocation.write_text(json.dumps({'jobs': jobs}))
        config = json.loads(subject.CONFIG.read_text())
        config['allocation_files'] = [str(allocation.relative_to(subject.ROOT))]
        subject.CONFIG.write_text(json.dumps(config))
        path = subject.ROOT / '.job-runtime/engine/schedule.sqlite'
        path.parent.mkdir(exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS slots(job_id TEXT,status TEXT)')
            db.execute('DELETE FROM slots')
            db.executemany('INSERT INTO slots VALUES(?,?)', slots)
        return path

    def test_idle_interval_does_not_starve_and_disabled_unknown_fence_is_unchanged(self):
        interval = {'id': 'primary.interval', 'enabled': True, 'schedule': {'kind': 'interval', 'seconds': 300}}
        path = self.primary([interval], [('disabled.fixture-fault', 'unknown')])
        before = path.read_bytes()
        self.assertFalse(subject.production_busy(1800, subject.now()))
        self.assertEqual(path.read_bytes(), before)

    def test_current_enabled_claims_and_any_running_primary_keep_first_admission(self):
        for enabled in (True, False):
            for status in ('ready', 'retry_wait', 'unknown', 'running'):
                with self.subTest(enabled=enabled, status=status):
                    interval = {'id': 'primary.interval', 'enabled': enabled, 'schedule': {'kind': 'interval', 'seconds': 300}}
                    path = self.primary([interval], [('primary.interval', status)])
                    before = path.read_bytes()
                    self.assertEqual(subject.production_busy(1800, subject.now()), enabled or status == 'running')
                    self.assertEqual(path.read_bytes(), before)

    def test_imminent_daily_primary_remains_protected(self):
        at = datetime.fromisoformat('2026-11-02T05:00:00+00:00')
        daily = {'id': 'primary.daily', 'enabled': True, 'schedule': {'kind': 'daily', 'timezone': 'UTC', 'times': ['05:10']}}
        self.primary([daily])
        self.assertTrue(subject.production_busy(1800, at))
        daily['schedule']['times'] = ['06:00']
        self.primary([daily])
        self.assertFalse(subject.production_busy(1800, at))

    def test_stage_is_future_private_and_never_bootstraps(self):
        with patch.object(subject.subprocess, 'run') as command:
            staged, path = self.staged()
        command.assert_not_called()
        record = json.loads(path.read_text())
        spec = plistlib.loads(Path(staged['plist']).read_bytes())
        self.assertFalse(spec['RunAtLoad'])
        self.assertNotIn('KeepAlive', spec)
        self.assertFalse(staged['registered'])
        self.assertFalse(record['jobs'][0]['replay_safe'])
        self.assertEqual(record['protocol'], 'candidate-v3')
        self.assertEqual(record['retry']['max_attempts'], 1)
        self.assertGreater((datetime.fromisoformat(staged['due']) - subject.now()).total_seconds(), 58)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(subject.ScheduledError):
            subject.stage('bad-delay', delay_seconds=59)

    def test_real_engine_future_tick_starts_no_harness(self):
        _, path = self.staged()
        with patch.object(subject.harness, 'run') as model:
            output = subject.tick(path)
        model.assert_not_called()
        self.assertEqual(output['status'], 'pending')
        with sqlite3.connect(path.parent / 'engine/schedule.sqlite') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM attempts').fetchone()[0], 0)

    def test_completed_slot_is_not_replayed_and_next_tick_unloads_only_own_label(self):
        staged, path = self.staged(due=True)
        with patch.object(subject.harness, 'run', return_value={'status': 'pass'}) as model, \
                patch.object(subject, 'postconditions', return_value={'verified': True}), \
                patch.object(subject.subprocess, 'run') as command:
            self.assertEqual(subject.tick(path)['status'], 'passed')
            self.assertEqual(subject.tick(path)['status'], 'passed')
        self.assertEqual(model.call_count, 1)
        self.assertEqual(model.call_args.args[0].protocol, subject.PROTOCOL_NAME)
        self.assertEqual(command.call_args.args[0], ['/bin/launchctl', 'bootout', 'gui/' + str(os.getuid()) + '/' + staged['label']])
        with sqlite3.connect(path.parent / 'engine/schedule.sqlite') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM attempts').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT status FROM slots').fetchone()[0], 'succeeded')

    def test_candidate_drift_fails_before_model(self):
        _, path = self.staged(due=True)
        self.fingerprint.return_value = {'synthetic': 'candidate-b'}
        with patch.object(subject.harness, 'run') as model:
            self.assertEqual(subject.tick(path)['status'], 'failed')
        model.assert_not_called()
        self.assertEqual(json.loads(path.read_text())['attempts'][0]['failure_code'], 'UI_SCHEDULE_CANDIDATE_CHANGED')

    def test_unknown_transport_is_held_and_private_exception_text_is_not_copied(self):
        _, path = self.staged(due=True)
        with patch.object(subject.harness, 'run', side_effect=RuntimeError('SYNTHETIC_PRIVATE_CANARY')) as model, \
                patch.object(subject.subprocess, 'run'):
            self.assertEqual(subject.tick(path)['status'], 'unverified')
            subject.tick(path)
        self.assertEqual(model.call_count, 1)
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', path.read_text())
        with sqlite3.connect(path.parent / 'engine/schedule.sqlite') as db:
            self.assertEqual(db.execute('SELECT status FROM slots').fetchone()[0], 'unknown')

    def test_observed_conformance_failure_stays_failed(self):
        _, path = self.staged(due=True)
        with patch.object(subject.harness, 'run', return_value={'status': 'conformance_failed'}):
            self.assertEqual(subject.tick(path)['status'], 'failed')
        self.assertEqual(json.loads(path.read_text())['attempts'][0]['failure_code'], 'UI_CONFORMANCE_FAILED')

    def test_primary_admission_yields_without_consuming_attempt(self):
        _, path = self.staged(due=True)
        with patch.object(subject, 'production_busy', return_value=True), patch.object(subject.harness, 'run') as model:
            self.assertEqual(subject.tick(path)['status'], 'yielded_primary')
        model.assert_not_called()
        self.assertFalse((path.parent / 'engine').exists())

    def test_model_pass_claim_without_native_completed_turn_is_rejected(self):
        name = 'synthetic-readback'
        public = subject.PUBLIC / name
        public.mkdir(parents=True)
        protocol = subject.ROOT / subject.PROTOCOL
        protocol.parent.mkdir(parents=True)
        protocol.write_text(json.dumps({'cases': [{'id': 'activate'}]}))
        at = subject.now().isoformat()
        result = {'status': 'pass', 'stage': 'scheduled', 'protocol_sha256': 'p', 'harness_sha256': 'h',
                  'protocol_file': subject.PROTOCOL,
                  'bundle_manifest_sha256': 'm', 'bundle_unchanged_during_run': True,
                  'started_at': at, 'ended_at': at, 'model_turns': 1,
                  'cases': [{'id': 'activate', 'passed': True, 'turn_id': 'synthetic-turn'}]}
        (public / 'result.json').write_text(json.dumps(result))
        record = {'candidate': {'source_files': {subject.PROTOCOL: 'p',
                                                'ui/portable/runtime_verification/run.py': 'h'}, 'global_manifest_sha256': 'm'},
                  'criteria': {'max_start_lateness_seconds': 60, 'completion_timeout_seconds': 1800}}
        with self.assertRaisesRegex(subject.ScheduledError, 'UI_NATIVE_TURN_COMPLETION_MISSING'):
            subject.postconditions(result, {'scheduled_at': at}, record, name)


class DurableReadbackTests(SchedulerFixture, unittest.TestCase):
    """Forged report fields cannot replace native-scoped archived receipt bytes."""

    def setUp(self):
        super().setUp()
        self.bundle = subject.ROOT / 'installed-bundle'
        self.bundle.mkdir()
        (self.bundle / 'manifest.json').write_text('{}\n')
        for module in (subject, subject.harness):
            fixture = patch.object(module, 'BUNDLE', self.bundle)
            fixture.start()
            self.addCleanup(fixture.stop)
        self.name = 'synthetic-durable'
        self.public = subject.PUBLIC / self.name
        self.cwd = self.public / 'fixture'
        self.cwd.mkdir(parents=True)
        self.main, self.fresh = 'native-original-thread', 'native-fresh-thread'
        (self.cwd / 'identity.json').write_text(json.dumps({'CODEX_THREAD_ID': self.main}))
        self.snapshots = subject.PRIVATE / self.name / 'state-snapshots'
        self.snapshots.mkdir(parents=True, mode=0o700)
        self.record = {'candidate': {'global_manifest_sha256': subject.sha(self.bundle / 'manifest.json')}}
        self.protocol = {'durable_receipt_postconditions': True, 'fresh_thread_same_project': True, 'cases': [
            {'id': 'activate', 'session_check': 'enable', 'receipt_expected': 'enabled', 'attach_skill': True},
            {'id': 'unnamed_layout', 'session_check': 'active', 'receipt_expected': 'enabled'},
            {'id': 'backend_diversion', 'session_check': 'none', 'receipt_expected': 'enabled'},
            {'id': 'disable', 'session_check': 'disable', 'receipt_expected': 'disabled'},
            {'id': 'compact_disabled', 'operation': 'compact'},
            {'id': 'unnamed_disabled_after_compaction', 'session_check': 'disabled_optional', 'receipt_expected': 'disabled'},
            {'id': 'reenable', 'session_check': 'enable', 'receipt_expected': 'enabled', 'attach_skill': True},
            {'id': 'fresh_thread', 'operation': 'fresh_thread', 'session_check': 'inactive_optional', 'receipt_expected': 'absent'}]}
        self.cases, self.segments = [], {}
        for frozen in self.protocol['cases']:
            case = {'id': frozen['id'], 'passed': True}
            self.cases.append(case)
            if frozen.get('operation') == 'compact':
                continue
            identifier = 'turn-' + frozen['id']
            case['turn_id'] = identifier
            mode = frozen['session_check']
            messages = []
            if mode in ('active', 'disabled'):
                status = 'HARRY_UI_SESSION_ACTIVE' if mode == 'active' else 'HARRY_UI_SESSION_DISABLED'
                messages.append(self.helper_event('restore', status))
            elif mode == 'disable':
                messages.append(self.helper_event('disable', 'HARRY_UI_SESSION_DISABLED'))
            if mode == 'active':
                messages.append(self.event('python3 ' + str(self.bundle / 'scripts/resolve.py'), 'UI_ROUTE_OK'))
            self.segments[identifier] = messages
            case['session_trace_postcondition'] = subject.harness.session_trace_postcondition(frozen, messages)
            case['disabled_receipt_consulted'] = case['session_trace_postcondition']['disabled_receipt_consulted']
            thread = self.fresh if frozen['id'] == 'fresh_thread' else self.main
            scope = subject.receipt_scope(self.cwd, thread)
            expected = frozen['receipt_expected']
            receipt = {**scope, 'passed': True, 'expected_state': expected, 'observed_state': expected}
            case['receipt_postcondition'] = receipt
            if expected == 'absent':
                receipt['original_thread_receipt_unchanged'] = True
                continue
            value = {'schema_version': 1, 'thread_key': scope['native_thread_key'], 'project_key': scope['project_key'],
                     'state': expected, 'bundle_fingerprint': self.record['candidate']['global_manifest_sha256'],
                     'created_at': '2026-11-02T00:00:00+00:00',
                     'updated_at': '2026-11-02T00:02:00+00:00' if frozen['id'] == 'reenable' else '2026-11-02T00:00:00+00:00'}
            path = self.snapshots / (frozen['id'] + '.json')
            raw = (json.dumps(value, sort_keys=True) + '\n').encode()
            path.write_bytes(raw)
            path.chmod(0o600)
            receipt.update(snapshot_ref=str(path.relative_to(subject.ROOT)), owner_mode_verified=True,
                           content_sha256=hashlib.sha256(raw).hexdigest())
            if frozen.get('attach_skill'):
                receipt['native_identity_verified'] = True
            if frozen['id'] == 'unnamed_disabled_after_compaction':
                receipt['unchanged_from_disable'] = True
        scope = subject.receipt_scope(self.cwd, self.main)
        live = self.cwd / scope['record_ref']
        live.parent.mkdir(mode=0o700, parents=True)
        live.write_bytes((self.snapshots / 'reenable.json').read_bytes())
        live.chmod(0o600)

    def event(self, command, output):
        return {'method': 'item/completed', 'params': {'item': {'type': 'commandExecution', 'id': 'command-' + command,
                'command': command, 'exitCode': 0, 'status': 'completed', 'aggregatedOutput': output}}}

    def helper_event(self, action, status):
        return self.event('python3 -B ' + str(self.bundle / 'scripts/session.py') + ' ' + action,
                          json.dumps({'status': status}))

    def check(self):
        return subject.durable_postconditions(self.protocol, self.cases, self.segments, self.public,
                                              self.record, self.name, self.main, self.fresh)

    def case(self, name):
        return next(case for case in self.cases if case['id'] == name)

    def replace_snapshot(self, name, change):
        path = self.snapshots / (name + '.json')
        value = json.loads(path.read_text())
        change(value)
        raw = (json.dumps(value, sort_keys=True) + '\n').encode()
        path.write_bytes(raw)
        self.case(name)['receipt_postcondition']['content_sha256'] = hashlib.sha256(raw).hexdigest()

    def test_valid_archives_retain_disabled_tombstone_while_final_thread_is_enabled(self):
        verified = self.check()
        self.assertTrue(verified['verified'])
        self.assertTrue(verified['disabled_tombstone_unchanged'])
        self.assertTrue(verified['fresh_thread_receipt_absent'])
        self.assertFalse(verified['disabled_receipt_consulted'])

    def test_known_disabled_helper_consultation_is_optional_and_reported_separately(self):
        case = self.case('unnamed_disabled_after_compaction')
        frozen = next(case for case in self.protocol['cases'] if case['id'] == 'unnamed_disabled_after_compaction')
        messages = [self.helper_event('restore', 'HARRY_UI_SESSION_DISABLED')]
        self.segments[case['turn_id']] = messages
        case['session_trace_postcondition'] = subject.harness.session_trace_postcondition(frozen, messages)
        case['disabled_receipt_consulted'] = True
        self.assertTrue(self.check()['disabled_receipt_consulted'])

    def test_independent_snapshot_read_does_not_count_as_worker_consultation(self):
        self.case('unnamed_disabled_after_compaction')['disabled_receipt_consulted'] = True
        with self.assertRaisesRegex(subject.ScheduledError, 'UI_DISABLED_CONSULTATION_DIAGNOSTIC_MISMATCH'):
            self.check()

    def test_known_disabled_wrong_status_or_failed_helper_cannot_claim_optional_success(self):
        case = self.case('unnamed_disabled_after_compaction')
        wrong_status = self.helper_event('restore', 'HARRY_UI_SESSION_ACTIVE')
        failed = self.helper_event('restore', 'HARRY_UI_SESSION_DISABLED')
        failed['params']['item']['exitCode'] = 1
        for event in (wrong_status, failed):
            with self.subTest(event=event):
                self.segments[case['turn_id']] = [event]
                with self.assertRaisesRegex(subject.ScheduledError, 'UI_DURABLE_RAW_HELPER_EVIDENCE_INVALID'):
                    self.check()

    def test_v2_disabled_consultation_remains_strict(self):
        self.assertFalse(subject.harness.session_trace_postcondition({'session_check': 'disabled'}, [])['passed'])

    def test_omitted_restore_or_forged_success_cannot_replace_actual_helper(self):
        self.segments['turn-unnamed_layout'] = self.segments['turn-unnamed_layout'][1:]
        with self.assertRaisesRegex(subject.ScheduledError, 'UI_DURABLE_RAW_HELPER_EVIDENCE_INVALID'):
            self.check()

    def test_helper_from_another_source_path_does_not_count(self):
        item = self.segments['turn-unnamed_layout'][0]['params']['item']
        item['command'] = item['command'].replace(str(self.bundle), str(subject.ROOT / 'unapproved-bundle'))
        with self.assertRaisesRegex(subject.ScheduledError, 'UI_DURABLE_RAW_HELPER_EVIDENCE_INVALID'):
            self.check()

    def test_restore_after_resolver_or_with_wrong_status_cannot_claim_active(self):
        original = copy.deepcopy(self.segments['turn-unnamed_layout'])
        wrong_status = self.helper_event('restore', 'HARRY_UI_SESSION_INACTIVE')
        for messages in (list(reversed(original)), [wrong_status, original[1]]):
            with self.subTest(messages=messages):
                self.segments['turn-unnamed_layout'] = messages
                with self.assertRaisesRegex(subject.ScheduledError, 'UI_DURABLE_RAW_HELPER_EVIDENCE_INVALID'):
                    self.check()

    def test_forged_snapshot_scope_or_manifest_is_rejected_even_with_matching_digest(self):
        path = self.snapshots / 'unnamed_layout.json'
        original = path.read_bytes()
        receipt = copy.deepcopy(self.case('unnamed_layout')['receipt_postcondition'])
        for field in ('thread_key', 'project_key', 'bundle_fingerprint'):
            with self.subTest(field=field):
                self.replace_snapshot('unnamed_layout', lambda value: value.update({field: '0' * 64}))
                with self.assertRaisesRegex(subject.ScheduledError, 'UI_RECEIPT_SCOPE_OR_STATE_INVALID'):
                    self.check()
                path.write_bytes(original)
                self.case('unnamed_layout')['receipt_postcondition'] = copy.deepcopy(receipt)

    def test_missing_reported_receipt_proof_is_rejected(self):
        self.case('backend_diversion').pop('receipt_postcondition')
        with self.assertRaisesRegex(subject.ScheduledError, 'UI_DURABLE_RECEIPT_PROOF_MISSING'):
            self.check()

    def test_nonprivate_snapshot_cannot_claim_owner_mode_verified(self):
        (self.snapshots / 'unnamed_layout.json').chmod(0o644)
        with self.assertRaisesRegex(subject.ScheduledError, 'UI_RECEIPT_FILE_UNSAFE'):
            self.check()

    def test_report_cannot_redirect_snapshot_to_another_case(self):
        self.case('unnamed_layout')['receipt_postcondition']['snapshot_ref'] = str((self.snapshots / 'activate.json').relative_to(subject.ROOT))
        with self.assertRaisesRegex(subject.ScheduledError, 'UI_DURABLE_SNAPSHOT_REF_INVALID'):
            self.check()

    def test_rewritten_disabled_tombstone_is_rejected_despite_valid_state_and_digest(self):
        self.replace_snapshot('unnamed_disabled_after_compaction', lambda value: value.update(updated_at='2026-11-02T00:01:00+00:00'))
        with self.assertRaisesRegex(subject.ScheduledError, 'UI_DISABLED_TOMBSTONE_CHANGED'):
            self.check()

    def test_fresh_thread_cannot_inherit_own_receipt_in_same_project(self):
        fresh = self.cwd / subject.receipt_scope(self.cwd, self.fresh)['record_ref']
        fresh.write_bytes((self.snapshots / 'reenable.json').read_bytes())
        fresh.chmod(0o600)
        with self.assertRaisesRegex(subject.ScheduledError, 'UI_FRESH_THREAD_RECEIPT_NOT_ABSENT'):
            self.check()

    def test_fresh_thread_cannot_rewrite_original_enabled_receipt(self):
        live = self.cwd / subject.receipt_scope(self.cwd, self.main)['record_ref']
        value = json.loads(live.read_text())
        value['updated_at'] = '2026-11-02T00:03:00+00:00'
        live.write_text(json.dumps(value))
        with self.assertRaisesRegex(subject.ScheduledError, 'UI_FRESH_THREAD_CHANGED_ORIGINAL_RECEIPT'):
            self.check()

    def test_invalid_receipt_timestamp_is_an_observed_validation_failure(self):
        self.replace_snapshot('unnamed_layout', lambda value: value.update(updated_at='forged-not-a-time'))
        with self.assertRaisesRegex(subject.ScheduledError, 'UI_RECEIPT_TIMESTAMP_INVALID'):
            self.check()


if __name__ == '__main__':
    unittest.main()
