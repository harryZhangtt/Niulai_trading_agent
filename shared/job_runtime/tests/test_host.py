"""Offline host boundary and watchdog lifecycle regression checks."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import plistlib
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from shared.job_runtime import config, host, service

ROOT = Path(__file__).resolve().parents[3]
PRIVATE = ROOT / '.job-runtime' / 'tests'
PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
UTC = timezone.utc


def write(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    path.chmod(0o600)


class HostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PRIVATE)
        self.addCleanup(self.temp.cleanup)
        self.scratch = Path(self.temp.name)
        self.root = self.scratch / 'workspace'
        self.root.mkdir(mode=0o700)
        self.state = self.root / '.job-runtime'
        self.state.mkdir(mode=0o700)
        self.path = self.state / 'infra.json'
        self.source = self.root / 'job-source'
        self.source.mkdir(mode=0o700)
        (self.source / 'prompt.txt').write_text('Synthetic read-only task.')
        binary = self.root / '.job-runtime' / '.venv' / 'bin' / 'python'
        binary.parent.mkdir(mode=0o700, parents=True)
        binary.write_text('synthetic test marker, never executed')
        binary.chmod(0o700)
        auth = self.state / 'auth'
        auth.mkdir(mode=0o700)
        write(auth / 'auth.json', {'synthetic': True})
        self.profile = {'codex_bin': str(binary), 'model': 'synthetic-model', 'effort': 'low',
                        'timeout_seconds': 120, 'auth_home': str(auth)}
        self.job = {'id': 'synthetic-job', 'enabled': True, 'replay_safe': True,
                    'schedule': {'kind': 'interval', 'seconds': 60},
                    'model_profile': 'default', 'prompt_file': 'job-source/prompt.txt'}
        write(self.root / 'jobs.json', {'schema_version': 1, 'jobs': [self.job]})
        self.value = {'schema_version': 1, 'tick_seconds': 5, 'heartbeat_seconds': 5,
                      'stale_seconds': 30, 'max_workers': 1,
                      'retry': {'max_attempts': 2, 'backoff_seconds': 5, 'max_backoff_seconds': 10},
                      'model_profiles': {'default': self.profile},
                      'allocation_files': ['jobs.json'], 'source_paths': ['job-source']}
        write(self.path, self.value)

    def test_generate_keeps_plists_and_output_paths_inside_workspace(self):
        paths = host.generate(self.root, self.path)
        self.assertEqual(len(paths), 2)
        for path in paths:
            self.assertTrue(path.resolve().is_relative_to(self.state))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            value = plistlib.loads(path.read_bytes())
            self.assertEqual(value['WorkingDirectory'], str(self.root))
            self.assertTrue(Path(value['StandardOutPath']).is_relative_to(self.state))
            self.assertTrue(Path(value['StandardErrorPath']).is_relative_to(self.state))
        daemon = plistlib.loads(paths[0].read_bytes())
        self.assertEqual(daemon['ProgramArguments'][:2], ['/usr/bin/caffeinate', '-i'])
        self.assertEqual(daemon['ProgramArguments'][3:6],
                         ['-B', '-m', 'shared.job_runtime.launcher'])
        self.assertNotIn('--service-label', daemon['ProgramArguments'])
        self.assertTrue(daemon['KeepAlive'])

    def test_generate_rejects_symlink_launchd_before_external_write(self):
        outside = self.scratch / 'outside'
        outside.mkdir()
        (self.state / 'launchd').symlink_to(outside, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            host.generate(self.root, self.path)
        self.assertEqual(list(outside.iterdir()), [])

    def test_atomic_json_and_plist_writes_hold_parent_across_symlink_swap(self):
        for writer, payload, filename in (
                (service.atomic, {'safe':True}, 'value.json'),
                (host._atomic_bytes, b'safe', 'value.plist')):
            with self.subTest(filename=filename):
                parent=self.scratch/('parent-'+filename);parent.mkdir()
                moved=self.scratch/('moved-'+filename)
                outside=self.scratch/('outside-'+filename);outside.mkdir()
                real_replace=os.replace
                swapped=[]
                def replace(source,target,**kwargs):
                    if not swapped:
                        parent.rename(moved);parent.symlink_to(outside,target_is_directory=True);swapped.append(True)
                    return real_replace(source,target,**kwargs)
                with patch.object(os,'replace',replace):
                    writer(parent/filename,payload)
                self.assertFalse((outside/filename).exists())
                self.assertTrue((moved/filename).is_file())

    def test_atomic_does_not_follow_predictable_temp_symlink(self):
        outside = self.scratch / 'outside-marker'
        outside.write_text('preserve')
        (self.state / 'heartbeat.tmp').symlink_to(outside)
        service.atomic(self.state / 'heartbeat.json', {'safe': True})
        self.assertEqual(outside.read_text(), 'preserve')
        self.assertEqual(json.loads((self.state / 'heartbeat.json').read_text()), {'safe': True})

    def test_config_rejects_parent_escape_and_duplicate_json(self):
        self.value['source_paths'] = ['../outside']
        write(self.path, self.value)
        with self.assertRaises(ValueError):
            config.load(self.path, self.root)
        self.path.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_JSON_KEY'):
            config.load(self.path, self.root)

    def test_config_rejects_private_runtime_unsafe_and_nonregular_prompts(self):
        outside = self.scratch / 'outside.txt'; outside.write_text('outside')
        private = self.state / 'private.txt'; private.write_text('private')
        runtime = self.root / 'runtime'; runtime.mkdir(); (runtime / 'task.txt').write_text('runtime')
        private_root = self.root / 'niulai-private'; private_root.mkdir(); (private_root / 'task.txt').write_text('private')
        oversized = self.source / 'oversized.txt'; oversized.write_bytes(b'x' * 65537)
        wrong_type = self.source / 'prompt.json'; wrong_type.write_text('{}')
        symlink = self.source / 'linked.txt'; symlink.symlink_to(outside)
        fifo = self.source / 'prompt-fifo.txt'; os.mkfifo(fifo)
        invalid = [str(outside), '.job-runtime/private.txt', 'runtime/task.txt', 'niulai-private/task.txt',
                   'job-source/oversized.txt', 'job-source/prompt.json', 'job-source/linked.txt',
                   'job-source/prompt-fifo.txt', '../outside.txt']
        for index, prompt in enumerate(invalid):
            with self.subTest(index=index, prompt=prompt):
                changed = dict(self.job, prompt_file=prompt)
                write(self.root / 'jobs.json', {'schema_version': 1, 'jobs': [changed]})
                with self.assertRaisesRegex(ValueError, 'PROMPT_INVALID|PATH_OUTSIDE_BOUNDARY|SYMLINK_REJECTED'):
                    config.load(self.path, self.root)

    def test_adapter_boundary_is_checked_before_module_code_executes(self):
        outside = self.scratch / 'external-module'
        outside.mkdir()
        marker = outside / 'import-executed'
        module = 'synthetic_external_job_adapter'
        (outside / (module + '.py')).write_text(
            'from pathlib import Path\n'
            + 'Path(' + repr(str(marker)) + ').write_text("executed")\n'
            + 'def prepare(*args): return {}\n')
        sys.path.insert(0, str(outside))
        self.addCleanup(lambda: sys.path.remove(str(outside)))
        self.addCleanup(lambda: sys.modules.pop(module, None))
        allocation = dict(self.job, adapter=module + ':prepare', adapter_config={})
        dispatch = service.dispatcher(self.value, self.root)
        with patch.object(service, 'run_codex') as run:
            try:
                dispatch(allocation, {'attempt_id': 'synthetic-attempt'})
            except ValueError:
                pass
            run.assert_not_called()
        self.assertFalse(marker.exists(), 'Out-of-workspace adapter ran before its boundary check')

    def test_watchdog_missing_heartbeat_gets_bounded_startup_grace(self):
        now = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
        calls = []
        def command(args):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls.current
        Clock.current = now
        with patch.object(host, 'command', command), patch.object(host, 'datetime', Clock):
            first = host.watchdog(self.root, self.path)
            self.assertFalse(first['healthy'])
            self.assertFalse(any(args[:2] == ['kill', 'SIGTERM'] for args in calls))
            Clock.current = now + timedelta(minutes=10)
            host.watchdog(self.root, self.path)
        self.assertTrue(any(args[:2] == ['kill', 'SIGTERM'] for args in calls))

    def test_watchdog_tick_threshold_accounts_for_queued_job_batches(self):
        now = datetime.now(UTC)
        jobs = []
        for i in range(5):
            value = dict(self.job, id='synthetic-' + str(i))
            jobs.append(value)
        write(self.root / 'jobs.json', {'schema_version': 1, 'jobs': jobs})
        write(self.state / 'heartbeat.json', {'at': now.isoformat(), 'pid': 123})
        write(self.state / 'status.json', {'last_tick': (now - timedelta(seconds=200)).isoformat()})
        calls = []
        def command(args):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch.object(host, 'command', command):
            result = host.watchdog(self.root, self.path)
        self.assertFalse(any(args[:2] == ['kill', 'SIGTERM'] for args in calls))
        self.assertTrue(result['healthy'])

    def test_state_reader_rejects_symlink_oversize_and_public_files(self):
        valid = self.state / 'service-generation.json'
        write(valid, {'pid': 1})
        self.assertEqual(host._read_state_json(valid), {'pid': 1})
        valid.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'HOST_STATE_FILE_INVALID'):
            host._read_state_json(valid)
        valid.chmod(0o600)
        outside = self.scratch / 'outside-state.json'
        write(outside, {'pid': 2})
        linked = self.state / 'reload-status.json'
        linked.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'HOST_STATE_FILE_INVALID'):
            host._read_state_json(linked)
        oversized = self.state / 'watchdog.json'
        oversized.write_bytes(b'x' * (host.MAX_STATE_BYTES + 1))
        oversized.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'HOST_STATE_FILE_INVALID'):
            host._read_state_json(oversized)

    def test_state_reader_rejects_symlinked_job_runtime_ancestor(self):
        workspace = self.scratch / 'symlink-workspace'
        workspace.mkdir(mode=0o700)
        real_state = self.scratch / 'real-state'
        real_state.mkdir(mode=0o700)
        write(real_state / 'status.json', {'pid': 1})
        (workspace / '.job-runtime').symlink_to(real_state, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'HOST_STATE_FILE_INVALID'):
            host._read_state_json(workspace / '.job-runtime' / 'status.json')

    def test_watchdog_future_or_malformed_state_is_stale_without_abort(self):
        now = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
        write(self.state / 'heartbeat.json', {'at': (now + timedelta(seconds=1)).isoformat()})
        write(self.state / 'status.json', {'last_tick': 'not-a-time'})
        calls = []
        def command(args):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return now
        with patch.object(host, 'command', command), patch.object(host, 'datetime', Clock):
            result = host.watchdog(self.root, self.path)
        self.assertFalse(result['healthy'])
        self.assertTrue(result['heartbeat_invalid'])
        self.assertTrue(result['tick_invalid'])
        self.assertTrue(any(args[:2] == ['kill', 'SIGTERM'] for args in calls))
        self.assertEqual(json.loads((self.state / 'watchdog.json').read_text())['healthy'], False)

    def test_custom_service_label_scopes_every_plist_and_lifecycle_target(self):
        label = 'com.local.trading-agent.job-runtime.schema9-canary-test'
        paths = host.generate(self.root, self.path, label)
        self.assertEqual([path.stem for path in paths], [label, label+'.watchdog'])
        daemon,watch = [plistlib.loads(path.read_bytes()) for path in paths]
        self.assertEqual((daemon['Label'],watch['Label']), (label,label+'.watchdog'))
        self.assertEqual(daemon['ProgramArguments'][-2:], ['--service-label',label])
        self.assertEqual(watch['ProgramArguments'][-2:], ['--service-label',label])
        self.assertIn(label, Path(daemon['StandardOutPath']).name)
        self.assertIn(label+'.watchdog', Path(watch['StandardOutPath']).name)
        with self.assertRaisesRegex(ValueError, 'HOST_SERVICE_LABEL_INVALID'):
            host.generate(self.root, self.path, host.LABEL)

    def test_custom_watchdog_never_targets_production_label(self):
        label = 'com.local.trading-agent.job-runtime.schema9-canary-watch'
        now = datetime.now(UTC)
        write(self.state / 'heartbeat.json', {'at': now.isoformat()})
        write(self.state / 'status.json', {'last_tick': now.isoformat()})
        calls=[]
        def command(args):
            calls.append(args);return SimpleNamespace(returncode=0,stdout='',stderr='')
        with patch.object(host,'command',command):
            host.watchdog(self.root,self.path,label)
        rendered=json.dumps(calls)
        self.assertIn(label,rendered)
        self.assertNotIn('gui/'+str(os.getuid())+'/'+host.LABEL+'"',rendered)


if __name__ == '__main__':
    unittest.main()
