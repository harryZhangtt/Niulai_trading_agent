"""Synthetic subprocess tests. No live model calls or real auth material."""
from pathlib import Path
import fcntl
import hashlib
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

import shared.job_runtime.model as model_adapter
from shared.job_runtime.model import ModelError, run_codex


ROOT = Path(__file__).resolve().parents[3]
TESTS = ROOT / '.job-runtime' / 'tests'
TESTS.mkdir(parents=True, exist_ok=True)


FAKE = '''#!/usr/bin/python3
import hashlib,json,os,signal,sys,time,subprocess
from pathlib import Path
args=sys.argv[1:]
final=Path(args[args.index('--output-last-message')+1]);root=final.parent
prompt=sys.stdin.buffer.read()
(root/'probe.json').write_text(json.dumps({'args':args,'prompt_sha256':hashlib.sha256(prompt).hexdigest(),'prompt_length':len(prompt),'env':dict(os.environ)}))
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
                        'effort': 'low', 'timeout_seconds': 10, 'auth_home': str(self.home)}

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

    def test_child_umask_hardens_future_outputs_without_rewriting_history(self):
        historical = self.base / 'historical-output.txt'
        historical.write_text('preserve mode')
        historical.chmod(0o640)
        historical_lock = self.home / 'runtime.lock'
        historical_lock.write_text('preserve lock mode')
        historical_lock.chmod(0o640)
        self.fake("""child_dir=root/'child-created-dir'
child_dir.mkdir()
(root/'child-created.txt').write_text('child')
(child_dir/'nested.txt').write_text('nested')
""" + SUCCESS)
        previous = os.umask(0o000)
        try:
            result = self.run_model()
        finally:
            os.umask(previous)
        self.assertEqual(result['status'], 'succeeded')
        run = self.base / 'run'
        for path in (run/'probe.json', run/'child-created.txt',
                     run/'child-created-dir/nested.txt', run/'last-message.txt'):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path)
        self.assertEqual(stat.S_IMODE((run/'child-created-dir').stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(historical.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(historical_lock.stat().st_mode), 0o640)

    def test_parent_created_outputs_are_exactly_private_for_all_outcomes(self):
        cases = (
            ('success', SUCCESS + "final.chmod(0o644)", 'succeeded'),
            ('failure', "final.write_text('{\"failed\":true}');final.chmod(0o644);"
                        "print(json.dumps({'type':'error','message':'invalid_grant synthetic'}));"
                        "sys.exit(1)", 'failed'),
            ('unknown', "final.write_text('{\"unknown\":true}');final.chmod(0o644);"
                        "print(json.dumps({'type':'thread.started'}))", 'unknown'),
        )
        previous = os.umask(0o000)
        try:
            for name, scenario, expected in cases:
                with self.subTest(outcome=name):
                    self.fake(scenario)
                    run = self.base / name
                    result = run_codex(
                        self.profile, 'synthetic', ROOT, run,
                        context={'response_schema':{'type':'object'}})
                    self.assertEqual(result['status'], expected)
                    self.assertEqual(stat.S_IMODE(run.stat().st_mode), 0o700)
                    for path in (run/'response-schema.json', run/'last-message.txt'):
                        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path)
        finally:
            os.umask(previous)

    def test_atomic_replacement_is_hardened_and_read_from_current_inode(self):
        body = """replacement=root/'replacement.tmp'
replacement.write_text('{\"atomic\":true}')
replacement.chmod(0o644)
os.replace(replacement,final)
print(json.dumps({'type':'thread.started','thread_id':'synthetic-thread'}))
print(json.dumps({'type':'turn.completed'}))
"""
        self.fake(body)
        result = self.run_model()
        self.assertEqual(result['status'], 'succeeded')
        final = self.base/'run/last-message.txt'
        expected = b'{"atomic":true}'
        self.assertEqual(final.read_bytes(), expected)
        self.assertEqual(stat.S_IMODE(final.stat().st_mode), 0o600)
        self.assertEqual(result['receipt']['response_sha256'], hashlib.sha256(expected).hexdigest())

    def test_unsafe_replacements_fail_closed_without_chmodding_hardlink_peer(self):
        cases = (
            ('symlink', "final.unlink();target=root/'target';target.write_text('x');"
                        "final.symlink_to(target)"),
            ('nonregular', "final.unlink();final.mkdir()"),
            ('hardlink', "final.unlink();target=root/'historical-peer';"
                         "target.write_text('x');target.chmod(0o644);os.link(target,final)"),
        )
        for name, body in cases:
            with self.subTest(kind=name):
                self.fake(body)
                run = self.base/name
                result = run_codex(self.profile, 'synthetic', ROOT, run)
                self.assertEqual((result['status'],result['code']),
                                 ('failed','MODEL_FINAL_OUTPUT_UNSAFE'))
                if name == 'hardlink':
                    peer = run/'historical-peer'
                    self.assertEqual(stat.S_IMODE(peer.stat().st_mode), 0o644)

    def test_descriptor_read_rejects_visible_atomic_replacement_race(self):
        run = self.base/'descriptor-race'
        run.mkdir(mode=0o700)
        final = run/'last-message.txt'
        original = b'{"original":true}'
        final.write_bytes(original)
        final.chmod(0o600)
        directory = os.open(run, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        real_read = os.read
        replaced = []
        def replace_after_open(descriptor, size):
            if not replaced:
                replacement = run/'replacement.tmp'
                replacement.write_bytes(b'{"replacement":true}')
                replacement.chmod(0o600)
                os.replace(replacement, final)
                replaced.append(True)
            return real_read(descriptor, size)
        try:
            with patch('shared.job_runtime.model.os.read', side_effect=replace_after_open):
                with self.assertRaisesRegex(ModelError, '^MODEL_FINAL_OUTPUT_UNSAFE$'):
                    model_adapter._read_private_output(
                        directory, run, final.name, 1024)
        finally:
            os.close(directory)
        self.assertTrue(replaced)
        self.assertEqual(final.read_bytes(), b'{"replacement":true}')

    def test_parent_fchmod_overrides_restrictive_umask(self):
        self.fake(SUCCESS)
        previous = os.umask(0o777)
        try:
            result = self.run_model(context={'response_schema':{'type':'object'}})
        finally:
            os.umask(previous)
        self.assertEqual(result['status'], 'succeeded')
        run = self.base / 'run'
        for path in (self.home/'runtime.lock', run/'response-schema.json',
                     run/'last-message.txt'):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path)

    def test_explicit_model_safe_flags_local_paths_and_no_prompt_in_argv(self):
        self.fake(SUCCESS)
        with patch.dict(os.environ, {'OPENAI_API_KEY':'SYNTHETIC-DO-NOT-INHERIT',
                                     'CODEX_UNRELATED_SECRET':'SYNTHETIC-DO-NOT-INHERIT'}):
            result = self.run_model()
        self.assertEqual(result['status'], 'succeeded')
        probe = json.loads((self.base/'run/probe.json').read_text())
        self.assertNotIn('SYNTHETIC PROMPT', ' '.join(probe['args']))
        self.assertEqual(probe['prompt_sha256'], hashlib.sha256(b'SYNTHETIC PROMPT').hexdigest())
        self.assertEqual(probe['prompt_length'], len(b'SYNTHETIC PROMPT'))
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
        self.assertIn('history.persistence="none"', probe['args'])
        self.assertFalse((self.base/'run/prompt.txt').exists())
        self.assertFalse((self.base/'run/events.jsonl').exists())
        self.assertFalse((self.base/'run/stderr.log').exists())

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
        self.profile['timeout_seconds']=5
        result=self.run_model()
        self.assertEqual(result['code'],'MODEL_DEADLINE_EXCEEDED')
        p=self.base/'ticks';before=p.read_text();time.sleep(.15)
        self.assertEqual(p.read_text(),before)

    def test_setsid_descendant_demonstrates_legacy_process_group_limit(self):
        ticks=self.base/'escaped-ticks';pid_path=self.base/'escaped.pid'
        escaped=(
            'from pathlib import Path;import os,time;'
            f'p=Path({str(ticks)!r});Path({str(pid_path)!r}).write_text(str(os.getpid()));'
            '\nwhile True:p.write_text(str(time.time()));time.sleep(.02)')
        self.fake(
            "subprocess.Popen([sys.executable,'-c',"+repr(escaped)+"],start_new_session=True);time.sleep(60)")
        # Establish bounded fixture readiness before the model deadline starts;
        # otherwise a loaded host can kill the parent before it spawns the child.
        self.profile['timeout_seconds']=5
        child=None;outcome={};worker_error=[]
        def invoke():
            try:outcome['result']=self.run_model()
            except BaseException as error:worker_error.append(error)
        worker=threading.Thread(target=invoke)
        worker.start()
        try:
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                if pid_path.is_file() and ticks.is_file() and ticks.stat().st_size:
                    break
                if not worker.is_alive():
                    break
                time.sleep(.02)
            ready=pid_path.is_file() and ticks.is_file() and bool(ticks.stat().st_size)
            if not ready:
                worker.join(timeout=10)
                detail=repr(worker_error[0]) if worker_error else repr(outcome.get('result'))
                self.fail('escaped child fixture did not become ready: '+detail)
            child=int(pid_path.read_text())
            worker.join(timeout=10)
            self.assertFalse(worker.is_alive(),'model fixture worker did not finish')
            if worker_error:raise worker_error[0]
            result=outcome['result']
            self.assertEqual(result['code'],'MODEL_DEADLINE_EXCEEDED')
            before=ticks.read_text();time.sleep(.15)
            self.assertNotEqual(ticks.read_text(),before)
        finally:
            if child is None and pid_path.is_file():
                try:child=int(pid_path.read_text())
                except (OSError,ValueError):pass
            if child is not None:
                try:os.killpg(child,signal.SIGKILL)
                except ProcessLookupError:pass

    def test_strict_process_tree_containment_fails_before_launch(self):
        self.fake(SUCCESS)
        cases=(
            ({**self.profile,'strict_process_tree_containment':True},{}),
            (self.profile,{'strict_process_tree_containment':True}),
        )
        for index,(profile,context) in enumerate(cases):
            run=self.base/('strict-'+str(index))
            result=run_codex(profile,'synthetic',ROOT,run,context=context)
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['code'],'MODEL_STRICT_PROCESS_TREE_CONTAINMENT_UNAVAILABLE')
            self.assertFalse(run.exists())

    def test_evaluation_evidence_root_requires_strict_containment_before_launch(self):
        self.fake(SUCCESS)
        run = ROOT / '.job-runtime' / 'evaluations' / 'synthetic-future-evidence'
        result = run_codex(self.profile, 'synthetic', ROOT, run)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(
            result['code'], 'MODEL_STRICT_PROCESS_TREE_CONTAINMENT_UNAVAILABLE')
        self.assertFalse(run.exists())

        alias = ROOT / '.job-runtime' / 'runs' / '..' / 'evaluations' / 'synthetic-alias-evidence'
        canonical = ROOT / '.job-runtime' / 'evaluations' / 'synthetic-alias-evidence'
        self.assertFalse(canonical.exists())
        aliased = run_codex(self.profile, 'synthetic', ROOT, alias)
        self.assertEqual(aliased['status'], 'failed')
        self.assertEqual(
            aliased['code'], 'MODEL_STRICT_PROCESS_TREE_CONTAINMENT_UNAVAILABLE')
        self.assertFalse(canonical.exists())

    def test_output_limit_is_bounded(self):
        self.fake("print('x'*4000)")
        self.profile['max_output_bytes']=1024
        result=self.run_model()
        self.assertEqual(result['code'],'MODEL_OUTPUT_LIMIT_EXCEEDED')

    def test_final_file_growth_is_killed_and_sanitized(self):
        self.fake("final.write_bytes(b'x'*4096);time.sleep(60)")
        self.profile['max_output_bytes']=1024
        result=self.run_model()
        self.assertEqual(result['code'],'MODEL_OUTPUT_LIMIT_EXCEEDED')
        self.assertNotIn('response_path',result['receipt'])
        self.assertLessEqual((self.base/'run/last-message.txt').stat().st_size,4096)

    def test_saturated_three_pipe_backpressure_completes(self):
        self.binary.write_text("""#!/usr/bin/python3
import json,sys
from pathlib import Path
args=sys.argv[1:];final=Path(args[args.index('--output-last-message')+1])
sys.stdout.write(' '*131072);sys.stdout.flush();sys.stderr.write(' '*131072);sys.stderr.flush()
data=sys.stdin.buffer.read();final.write_text('{\"ok\":true}')
print(json.dumps({'type':'thread.started','thread_id':'synthetic-thread'}))
print(json.dumps({'type':'turn.completed'}))
""")
        self.binary.chmod(0o700);self.profile['max_output_bytes']=1024*1024
        result=run_codex(self.profile,b'x'*(512*1024),ROOT,self.base/'run')
        self.assertEqual(result['status'],'succeeded')

    def test_term_ignoring_child_is_killed_and_reaped(self):
        self.fake("signal.signal(signal.SIGTERM,signal.SIG_IGN);(root/'ready').write_text('1');time.sleep(60)")
        self.profile['timeout_seconds']=1;observed=[]
        result=self.run_model(context={'process_observer':observed.append})
        self.assertEqual(result['code'],'MODEL_DEADLINE_EXCEEDED')
        with self.assertRaises(ProcessLookupError):os.kill(observed[0],0)

    def test_early_exit_closes_stdin_without_hanging(self):
        self.binary.write_text("#!/usr/bin/python3\nimport sys\nsys.exit(0)\n")
        self.binary.chmod(0o700)
        result=run_codex(self.profile,b'x'*(512*1024),ROOT,self.base/'run')
        self.assertEqual((result['status'],result['code']),
                         ('unknown','MODEL_PROMPT_DELIVERY_INCOMPLETE'))
        self.assertFalse((self.base/'run/prompt.txt').exists())

    def test_partial_pipe_writes_deliver_exact_legacy_bytes(self):
        self.fake(SUCCESS)
        real_write=os.write;calls=[0]
        def partial(descriptor,data):
            calls[0]+=1
            if calls[0]==1:raise BlockingIOError
            return real_write(descriptor,bytes(data[:2]))
        with patch('shared.job_runtime.pipe_transport.os.write',side_effect=partial):
            result=self.run_model()
        self.assertEqual(result['status'],'succeeded')
        probe=json.loads((self.base/'run/probe.json').read_text())
        self.assertEqual(probe['prompt_sha256'],hashlib.sha256(b'SYNTHETIC PROMPT').hexdigest())

    def test_cancel_during_pipe_pump_reaps_process(self):
        self.fake('time.sleep(60)')
        cancel=threading.Event();observed=[]
        def observer(pid):
            observed.append(pid);cancel.set()
        result=self.run_model(context={'cancel_event':cancel,'process_observer':observer})
        self.assertEqual(result['code'],'MODEL_CANCELLED')
        with self.assertRaises(ProcessLookupError):os.kill(observed[0],0)

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

    def test_trusted_process_observer_records_owned_process_and_failure_reaps_it(self):
        self.fake(SUCCESS); observed = []
        result = self.run_model(context={'process_observer': observed.append})
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(len(observed), 1)
        self.assertIs(type(observed[0]), int)
        self.fake('time.sleep(60)'); failed = []
        def observer(pid): failed.append(pid); raise ValueError('SYNTHETIC_PRIVATE_CANARY')
        result = run_codex(self.profile, 'synthetic', ROOT, self.base / 'observer-failed', context={'process_observer': observer})
        self.assertEqual(result['code'], 'MODEL_PROCESS_OBSERVER_FAILED')
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(result))
        with self.assertRaises(ProcessLookupError): os.kill(failed[0], 0)

    def test_process_control_exceptions_propagate_after_observer_cleanup(self):
        self.fake('time.sleep(60)')
        for index,exception in enumerate((KeyboardInterrupt,SystemExit,GeneratorExit)):
            observed=[]
            def observer(pid, exception=exception):
                observed.append(pid)
                raise exception('synthetic control flow')
            with self.subTest(exception=exception.__name__):
                with self.assertRaises(exception):
                    run_codex(self.profile,'synthetic',ROOT,self.base/f'control-{index}',
                              context={'process_observer':observer})
                self.assertEqual(len(observed),1)
                with self.assertRaises(ProcessLookupError):
                    os.kill(observed[0],0)

    def test_repeated_runs_do_not_leak_file_descriptors(self):
        self.fake(SUCCESS);before=len(os.listdir('/dev/fd'))
        for index in range(4):
            result=run_codex(self.profile,b'fd-check',ROOT,self.base/f'fd-{index}')
            self.assertEqual(result['status'],'succeeded')
        self.assertLessEqual(len(os.listdir('/dev/fd')),before+1)

    def test_process_observer_must_be_callable_before_any_launch(self):
        self.fake(SUCCESS)
        result = self.run_model(context={'process_observer': 'not callable'})
        self.assertEqual(result['code'], 'MODEL_PROCESS_OBSERVER_INVALID')
        self.assertFalse((self.base / 'run/probe.json').exists())


if __name__ == '__main__':
    unittest.main()
