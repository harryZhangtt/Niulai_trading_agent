"""Synthetic subprocess tests. No live model calls or real auth material."""
from pathlib import Path
import fcntl
import json
import os
import stat
import signal
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

from shared.job_runtime.model import run_codex


ROOT = Path(__file__).resolve().parents[3]
TESTS = ROOT / '.job-runtime' / 'tests'
TESTS.mkdir(parents=True, exist_ok=True)


FAKE = '''#!/usr/bin/python3
import json,os,sys,time,subprocess
from pathlib import Path
args=sys.argv[1:]
final=Path(args[args.index('--output-last-message')+1]);root=final.parent
prompt=sys.stdin.read()
(root/'probe.json').write_text(json.dumps({'args':args,'prompt':prompt,'env':dict(os.environ)}))
SCENARIO
'''


SUCCESS = '''final.write_text('{"ok":true}')
print(json.dumps({'type':'thread.started','thread_id':'synthetic-thread'}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':11,'output_tokens':3}}))
'''


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TESTS)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'auth'
        self.home.mkdir(mode=0o700)
        # The workspace policy requires .job-runtime containment.
        self.auth = self.home / 'auth.json'
        self.auth.write_text('{"synthetic_fixture":true}')
        self.auth.chmod(0o600)
        self.binary = self.base / 'fake-codex'
        self.profile = {'codex_bin': str(self.binary), 'model': 'gpt-6.1-sol',
                        'effort': 'low', 'timeout_seconds': 3, 'auth_home': str(self.home)}

    def fake(self, body):
        self.binary.write_text(FAKE.replace('SCENARIO', body))
        self.binary.chmod(0o700)

    def run_model(self, **kwargs):
        return run_codex(self.profile, 'SYNTHETIC PROMPT', ROOT, self.base / 'run', **kwargs)

    def test_success_requires_cli_completion_and_records_usage(self):
        self.fake(SUCCESS)
        result = self.run_model()
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['receipt']['usage']['input_tokens'], 11)
        self.assertEqual(result['receipt']['requested_model'], 'gpt-6.1-sol')
        self.assertIsNone(result['receipt']['observed_model'])
        self.assertFalse(result['receipt']['fallback_used'])

    def test_explicit_model_safe_flags_local_paths_and_no_prompt_in_argv(self):
        self.fake(SUCCESS)
        with patch.dict(os.environ, {'OPENAI_API_KEY':'SYNTHETIC-DO-NOT-INHERIT',
                                     'CODEX_UNRELATED_SECRET':'SYNTHETIC-DO-NOT-INHERIT'}):
            result = self.run_model()
        self.assertEqual(result['status'], 'succeeded')
        probe = json.loads((self.base/'run/probe.json').read_text())
        self.assertNotIn('SYNTHETIC PROMPT', ' '.join(probe['args']))
        self.assertEqual(probe['prompt'], 'SYNTHETIC PROMPT')
        self.assertEqual(probe['env']['CODEX_HOME'], str(self.home))
        self.assertNotIn('OPENAI_API_KEY', probe['env'])
        self.assertNotIn('CODEX_UNRELATED_SECRET', probe['env'])
        for flag in ('--ignore-user-config', '--ephemeral', '--strict-config', '--sandbox'):
            self.assertIn(flag, probe['args'])
        self.assertIn('features.shell_tool=false', probe['args'])
        self.assertIn('apps._default.enabled=false', probe['args'])
        self.assertIn('web_search="disabled"', probe['args'])
        for key in ('TMPDIR','XDG_CACHE_HOME','CODEX_SQLITE_HOME'):
            self.assertTrue(Path(probe['env'][key]).is_relative_to(ROOT/'.job-runtime'))
        self.assertEqual(stat.S_IMODE((self.base/'run/events.jsonl').stat().st_mode), 0o600)

    def test_known_auth_failure_is_permanent_and_sanitized(self):
        self.fake("print(json.dumps({'type':'error','message':'invalid_grant SYNTHETIC SECRET'}));sys.exit(1)")
        result = self.run_model()
        self.assertEqual((result['status'],result['code']),('failed','MODEL_AUTH_REQUIRED'))
        self.assertNotIn('SECRET', json.dumps(result))

    def test_transient_failure_is_classified_without_retry(self):
        self.fake("print(json.dumps({'type':'error','message':'429 rate limit'}));sys.exit(1)")
        result = self.run_model()
        self.assertEqual((result['status'],result['code']),('retryable','MODEL_TRANSIENT_FAILURE'))
        self.assertFalse(result['receipt']['automatic_retry'])

    def test_exit_zero_without_turn_receipt_is_unknown(self):
        self.fake("final.write_text('I succeeded');print(json.dumps({'type':'thread.started'}))")
        result = self.run_model()
        self.assertEqual(result['status'],'unknown')

    def test_tool_activity_and_model_mismatch_fail(self):
        for event, code in (({'type':'item.completed','item':{'type':'command_execution'}},'MODEL_TOOL_POLICY_VIOLATION'),
                            ({'type':'thread.started','model':'different-model'},'MODEL_IDENTITY_MISMATCH')):
            self.fake(SUCCESS+"\nprint("+repr(json.dumps(event))+")")
            run = self.base / code
            result=run_codex(self.profile,'synthetic',ROOT,run)
            self.assertEqual(result['code'],code)

    def test_timeout_kills_child_process_group(self):
        child = "from pathlib import Path;import time; p=Path("+repr(str(self.base/'ticks'))+");\nwhile True:p.write_text(str(time.time()));time.sleep(.02)"
        self.fake("subprocess.Popen([sys.executable,'-c',"+repr(child)+"]);time.sleep(60)")
        self.profile['timeout_seconds']=2
        result=self.run_model()
        self.assertEqual(result['code'],'MODEL_DEADLINE_EXCEEDED')
        p=self.base/'ticks';before=p.read_text();time.sleep(.15)
        self.assertEqual(p.read_text(),before)

    def test_output_limit_is_bounded(self):
        self.fake("print('x'*4000)")
        self.profile['max_output_bytes']=1024
        result=self.run_model()
        self.assertEqual(result['code'],'MODEL_OUTPUT_LIMIT_EXCEEDED')

    def test_auth_lock_prevents_parallel_cache_refresh(self):
        self.fake(SUCCESS)
        with (self.home/'runtime.lock').open('w') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result=self.run_model()
        self.assertEqual(result['code'],'MODEL_AUTH_CACHE_BUSY')
        self.assertFalse((self.base/'run').exists())

    def test_child_keeps_auth_lock_if_model_parent_is_killed(self):
        self.fake("(root/'child.pid').write_text(str(os.getpid()));time.sleep(60)")
        code = ('from shared.job_runtime.model import run_codex;from pathlib import Path;'
                'run_codex('+repr(self.profile)+',"synthetic",Path('+repr(str(ROOT))+'),Path('
                +repr(str(self.base/'run'))+'))')
        worker = subprocess.Popen([sys.executable,'-c',code],cwd=ROOT,
                                  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        child = None
        try:
            ready=self.base/'run/child.pid';deadline=time.monotonic()+5
            while not ready.exists() and time.monotonic()<deadline:
                time.sleep(.02)
            self.assertTrue(ready.exists())
            child=int(ready.read_text())
            worker.kill();worker.wait(timeout=2)
            result=run_codex(self.profile,'synthetic',ROOT,self.base/'second')
            self.assertEqual(result['code'],'MODEL_AUTH_CACHE_BUSY')
        finally:
            if worker.poll() is None:
                worker.kill();worker.wait(timeout=2)
            if child is not None:
                try:os.killpg(child,signal.SIGKILL)
                except ProcessLookupError:pass

    def test_cancelled_service_does_not_launch_model(self):
        self.fake(SUCCESS);cancel=threading.Event();cancel.set()
        result=self.run_model(context={'cancel_event':cancel})
        self.assertEqual(result['code'],'MODEL_CANCELLED_BEFORE_START')
        self.assertFalse((self.base/'run/probe.json').exists())

    def test_missing_auth_does_not_fallback_to_global(self):
        self.fake(SUCCESS);self.auth.unlink()
        self.assertEqual(self.run_model()['code'],'MODEL_AUTH_REQUIRED')
        self.assertFalse((self.base/'run').exists())

    def test_path_and_permission_rejection_precede_process(self):
        self.fake(SUCCESS);self.auth.chmod(0o644)
        self.assertEqual(self.run_model()['code'],'MODEL_AUTH_FILE_UNSAFE')
        self.auth.chmod(0o600)
        result=run_codex(self.profile,'synthetic',ROOT,ROOT/'niulai-private/forbidden-model-output')
        self.assertEqual(result['code'],'MODEL_PATH_OUTSIDE_STATE')
        self.assertFalse((ROOT/'niulai-private/forbidden-model-output').exists())

    def test_existing_run_is_not_overwritten(self):
        self.fake(SUCCESS);(self.base/'run').mkdir()
        self.assertEqual(self.run_model()['code'],'MODEL_RUN_DIRECTORY_EXISTS')


if __name__ == '__main__':
    unittest.main()
