"""Subprocess regressions for loaded-code receipts; synthetic jobs never dispatch."""
import hashlib
import json
import os
from pathlib import Path
import py_compile
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[3]
PRIVATE = ROOT / '.job-runtime' / 'tests'
PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)


def write_private(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    path.chmod(0o600)


def wait_json(path, predicate=lambda value: True, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = json.loads(path.read_text())
            if predicate(value):
                return value
        except (OSError, ValueError):
            pass
        time.sleep(0.05)
    raise AssertionError('synthetic service receipt timed out: ' + path.name)


class ServiceGenerationProcessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PRIVATE)
        self.addCleanup(self.temp.cleanup)
        self.scratch = Path(self.temp.name)
        self.code = self.scratch / 'code'
        (self.code / 'shared').mkdir(mode=0o700, parents=True)
        (self.code / 'shared' / '__init__.py').write_text('')
        shutil.copy2(ROOT / 'shared/exact_source.py', self.code / 'shared/exact_source.py')
        for package in ('job_runtime', 'research_sources'):
            shutil.copytree(ROOT / 'shared' / package, self.code / 'shared' / package,
                            ignore=shutil.ignore_patterns('__pycache__', 'tests'))
        self.workspace = self.scratch / 'workspace'
        self.state = self.workspace / '.job-runtime'
        self.state.mkdir(mode=0o700, parents=True)
        auth = self.state / 'auth'
        auth.mkdir(mode=0o700)
        prompt = self.workspace / 'synthetic.txt'
        prompt.write_text('No dispatch: allocation is disabled.')
        jobs = {'schema_version': 1, 'jobs': [{
            'id': 'disabled.synthetic', 'enabled': False, 'replay_safe': True,
            'schedule': {'kind': 'interval', 'seconds': 60},
            'model_profile': 'fixture', 'prompt_file': 'synthetic.txt',
        }]}
        write_private(self.workspace / 'jobs.json', jobs)
        self.config = self.state / 'runtime.json'
        write_private(self.config, {
            'schema_version': 1, 'tick_seconds': 1, 'heartbeat_seconds': 1,
            'stale_seconds': 30, 'max_workers': 1,
            'retry': {'max_attempts': 1, 'backoff_seconds': 1, 'max_backoff_seconds': 1},
            'model_profiles': {'fixture': {'auth_home': str(auth), 'timeout_seconds': 1}},
            'allocation_files': ['jobs.json'], 'source_paths': [],
        })
        self.processes = []
        self.addCleanup(self.stop_all)

    def start(self, *, wait_status=True, legacy_module=False, service_label=None):
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(self.code),
               'PYTHONDONTWRITEBYTECODE': '1', 'HOME': str(self.scratch)}
        if legacy_module:
            command = [sys.executable, '-m', 'shared.job_runtime.service']
        else:
            command = [sys.executable, '-B', '-m', 'shared.job_runtime.launcher']
        arguments = [*command, '--workspace', str(self.workspace), '--config', str(self.config)]
        if service_label is not None:
            arguments += ['--service-label', service_label]
        process = subprocess.Popen(
            arguments,
            cwd=self.workspace, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.processes.append(process)
        try:
            generation = wait_json(self.state / 'service-generation.json',
                                   lambda value: value.get('pid') == process.pid)
        except AssertionError:
            if process.poll() is not None:
                raise AssertionError(f'synthetic service exited early: {process.communicate()}') from None
            raise
        if wait_status:
            wait_json(self.state / 'status.json', lambda value: value.get('pid') == process.pid)
        return process, generation

    def stop(self, process):
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=8)
        self.assertEqual(process.returncode, 0, process.communicate())

    def stop_all(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


    def test_launcher_binds_executed_service_and_business_sources(self):
        process, generation = self.start()
        service_source = self.code / 'shared' / 'job_runtime' / 'service.py'
        business_source = self.code / 'shared' / 'job_runtime' / 'business.py'
        self.assertEqual(
            generation['service']['source_sha256'],
            hashlib.sha256(service_source.read_bytes()).hexdigest())
        self.assertEqual(
            generation['implementations']['business'],
            hashlib.sha256(business_source.read_bytes()).hexdigest())
        self.stop(process)

    def test_launcher_accepts_valid_custom_label_without_changing_state_root(self):
        label='com.local.trading-agent.job-runtime.schema9-canary-process'
        process,generation=self.start(service_label=label)
        self.assertEqual(generation['pid'],process.pid)
        self.assertTrue((self.state/'engine'/'schedule.sqlite').is_file())
        self.stop(process)

    def test_sigterm_reaps_long_lived_model_process_group(self):
        binary = self.state / 'fake-codex'
        ticks = self.state / 'grandchild-ticks'
        child_pid = self.state / 'grandchild.pid'
        argv_path = self.state / 'codex-argv.json'
        child = (
            'from pathlib import Path;import os,time;'
            f'p=Path({str(ticks)!r});Path({str(child_pid)!r}).write_text(str(os.getpid()));'
            '\nwhile True:p.write_text(str(time.time()));time.sleep(.02)'
        )
        binary.write_text(
            '#!/usr/bin/python3\nimport json,subprocess,sys,time\n'
            f'open({str(argv_path)!r},"w").write(json.dumps(sys.argv))\n'
            f'subprocess.Popen([sys.executable,"-c",{child!r}])\n'
            'time.sleep(60)\n'
        )
        binary.chmod(0o700)
        auth = self.state / 'auth'
        write_private(auth / 'auth.json', {'synthetic': True})
        write_private(self.workspace / 'jobs.json', {'schema_version': 1, 'jobs': [{
            'id': 'enabled.synthetic', 'enabled': True, 'replay_safe': False,
            'schedule': {'kind': 'interval', 'seconds': 60},
            'model_profile': 'fixture', 'prompt_file': 'synthetic.txt',
        }]})
        value = json.loads(self.config.read_text())
        value['model_profiles']['fixture'].update({
            'codex_bin': str(binary), 'model': 'synthetic-model', 'effort': 'low',
            'timeout_seconds': 60,
        })
        write_private(self.config, value)

        process, _generation = self.start(wait_status=False)
        try:
            deadline = time.monotonic() + 8
            while (not ticks.exists() or not child_pid.exists()) and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(ticks.exists(), 'synthetic grandchild never started')
            argv=json.loads(argv_path.read_text())
            self.assertIn('request_max_retries=0',argv)
            self.assertIn('stream_max_retries=0',argv)
            grandchild = int(child_pid.read_text())
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=8)
            self.assertEqual(process.returncode, 0, process.communicate())
            before = ticks.read_text()
            time.sleep(.15)
            self.assertEqual(ticks.read_text(), before)
            with self.assertRaises(ProcessLookupError):
                os.kill(grandchild, 0)
        finally:
            if process.poll() is None:
                self.stop(process)

    def test_legacy_module_entrypoint_remains_compatible(self):
        process, generation = self.start(legacy_module=True)
        source = self.code / 'shared' / 'job_runtime' / 'service.py'
        self.assertEqual(generation['service']['source_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
        self.stop(process)

    def test_sighup_keeps_loaded_generation_and_fresh_process_loads_changed_source(self):
        source = self.code / 'shared' / 'job_runtime' / 'service.py'
        process, original = self.start()
        self.assertEqual(original['service']['protocol_version'], 2)
        self.assertEqual(original['service']['source_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())

        changed = source.read_text().replace('SERVICE_PROTOCOL_VERSION = 2', 'SERVICE_PROTOCOL_VERSION = 3', 1)
        self.assertNotEqual(changed, source.read_text())
        before = source.stat()
        py_compile.compile(str(source), doraise=True)
        source.write_text(changed)
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(source.stat().st_size, before.st_size)
        changed_digest = hashlib.sha256(source.read_bytes()).hexdigest()
        process.send_signal(signal.SIGHUP)
        reload_receipt = wait_json(
            self.state / 'reload-status.json',
            lambda value: value.get('accepted') is True and value.get('service_generation', {}).get('pid') == process.pid)
        self.assertEqual(reload_receipt['service_generation'], original)
        self.assertNotEqual(original['service']['source_sha256'], changed_digest)

        database = self.state / 'engine' / 'schedule.sqlite'
        with sqlite3.connect(database) as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES('synthetic_preserve','yes')")
        self.stop(process)
        self.assertFalse((self.state / 'service.lock').is_symlink())
        with sqlite3.connect(database) as db:
            self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='synthetic_preserve'").fetchone()[0], 'yes')

        fresh, current = self.start()
        self.assertEqual(current['service']['protocol_version'], 3)
        self.assertEqual(current['service']['source_sha256'], changed_digest)
        self.assertEqual(current['pid'], fresh.pid)
        self.assertNotEqual((current['pid'], current['started_at']),
                            (original['pid'], original['started_at']))
        with sqlite3.connect(database) as db:
            self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='synthetic_preserve'").fetchone()[0], 'yes')
        self.stop(fresh)


if __name__ == '__main__':
    unittest.main()
