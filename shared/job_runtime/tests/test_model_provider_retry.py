from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest.mock import patch

from shared.job_runtime import model
from shared.job_runtime.provider_contract import ProviderResultV1


FIXTURES = Path(__file__).with_name('fixtures') / 'codex_runner'


class ModelProviderRetryTests(unittest.TestCase):
    def v2_fixture(self, directory, *, terminal=True, raw_canary=None):
        workspace=Path(directory).resolve();state=workspace/'.job-runtime';auth=state/'auth'
        auth.mkdir(parents=True,mode=0o700);auth.chmod(0o700)
        (auth/'auth.json').write_text('{}');(auth/'auth.json').chmod(0o600)
        binary=state/'fake-codex'
        terminal_code = "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':3}}))" if terminal else ""
        raw_code = ''
        if raw_canary is not None:
            numbers=','.join(str(value) for value in raw_canary)
            raw_code=(f"raw=bytes([{numbers}]).decode();sys.stderr.write(raw);"
                      "print(json.dumps({'type':'item.completed','item':{'id':'synthetic-item','type':'agent_message','text':raw}}))\n")
        binary.write_text("""#!/usr/bin/python3
import hashlib,json,os,sys
from pathlib import Path
args=sys.argv[1:];data=sys.stdin.buffer.read()
final=Path(args[args.index('--output-last-message')+1])
(final.parent/'probe.json').write_text(json.dumps({'args':args,'cwd':os.getcwd(),'env':dict(os.environ),'sha256':hashlib.sha256(data).hexdigest(),'length':len(data)}))
final.write_bytes(b'{\"ok\":true}\\n')
print(json.dumps({'type':'thread.started','thread_id':'synthetic-thread'}))
print(json.dumps({'type':'turn.started'}))
"""+raw_code+terminal_code+"\n")
        binary.chmod(0o700)
        profile={'codex_bin':str(binary),'model':'gpt-test','effort':'medium',
                 'timeout_seconds':10,'auth_home':str(auth),'max_output_bytes':4096}
        return workspace,profile,state/'runs'/'attempt'

    def test_sanitized_fixture_provenance_is_exact_and_does_not_claim_source_binding(self):
        raw = (FIXTURES / 'sanitized_structural_fixture.jsonl').read_bytes()
        provenance = json.loads(
            (FIXTURES / 'sanitized_structural_fixture.provenance.json').read_text())
        self.assertEqual(provenance['fixture_kind'], 'sanitized_structural_fixture')
        self.assertEqual(provenance['fixture_output_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(provenance['source_capture_status'], 'unverified')
        self.assertFalse(provenance['source_capture_verified'])
        self.assertFalse(provenance['source_conformance_verified'])
        self.assertEqual(provenance['production_translation'], 'runtime_unverified')
        self.assertTrue(provenance['activation_blocked'])
        self.assertEqual(set(provenance['synthetic_fields']),
                         {'thread_id', 'item.id', 'item.text', 'usage'})

    def test_sanitized_structural_fixture_translates_closed_success_shape(self):
        raw = (FIXTURES / 'sanitized_structural_fixture.jsonl').read_bytes()
        translated = model.translate_codex_jsonl(raw, 'gpt-test')
        events = [json.loads(line) for line in translated.splitlines()]
        self.assertEqual([event['type'] for event in events],
                         ['invocation.started', 'invocation.completed'])
        self.assertNotIn('model',events[0])
        self.assertNotIn('text', translated.decode())

    def test_malformed_capture_is_rejected_without_raw_text(self):
        with self.assertRaisesRegex(model.ModelError, '^CODEX_CAPTURE_MALFORMED$'):
            model.translate_codex_jsonl(
                (FIXTURES / 'synthetic-malformed.jsonl').read_bytes(), 'gpt-test')

    def test_one_process_result_is_typed_and_model_binding_is_a_nonclaim(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            state = workspace / '.job-runtime'
            auth = state / 'auth'
            auth.mkdir(parents=True, mode=0o700)
            auth.chmod(0o700)
            (auth / 'auth.json').write_text('{}')
            (auth / 'auth.json').chmod(0o600)
            run_dir = state / 'runs' / 'attempt-1'
            calls = []

            def fake_run(profile, prompt, workspace_arg, run_arg, context=None, legacy=False):
                calls.append((profile, prompt, context, legacy))
                run_arg.mkdir(parents=True, mode=0o700)
                run_arg.chmod(0o700)
                raw = (FIXTURES / 'sanitized_structural_fixture.jsonl').read_bytes()
                final = b'{"ok":true}\n'
                final_path = run_arg / 'last-message.txt'
                final_path.write_bytes(final); final_path.chmod(0o600)
                return {'status':'succeeded','code':'MODEL_TURN_COMPLETED','receipt':{
                    'turn_completed':True,'exit_code':0,'process_started':True},
                    '_events':raw,'_final_bytes':final,
                    '_artifacts':{'final_path':final_path,
                                  'final_ref':f'{run_arg.name}/last-message.txt'}}

            profile = {'codex_bin':'/bin/true','model':'gpt-test','effort':'medium',
                       'timeout_seconds':10,'auth_home':str(auth)}
            with patch.object(model, '_run_codex', side_effect=fake_run):
                result = model.run_codex_one_shot(
                    profile, b'synthetic prompt', workspace, run_dir, 'attempt/one')
            self.assertIsInstance(result, ProviderResultV1)
            self.assertEqual(result.status.value, 'succeeded')
            self.assertEqual(len(calls), 1)
            self.assertEqual(result.receipt['model_binding_source'],
                             'configured_cli_argument')
            self.assertFalse(result.receipt['provider_reported_model'])
            self.assertNotIn('observed_model_verified', result.receipt)

    def test_past_absolute_deadline_makes_zero_runner_or_process_calls(self):
        deadline=datetime.now(timezone.utc)-timedelta(seconds=1)
        with tempfile.TemporaryDirectory() as directory:
            workspace=Path(directory).resolve()
            with patch.object(model,'normalize_codex_one_shot') as runner, \
                    patch.object(model,'_run_codex') as process:
                result=model.run_codex_one_shot(
                    {},b'x',workspace,workspace/'.job-runtime'/'runs'/'past',
                    'attempt/past',{'deadline_at':deadline})
        runner.assert_not_called(); process.assert_not_called()
        self.assertEqual(result.status.value,'failed')
        self.assertEqual(result.phase.value,'not_started')
        self.assertEqual(result.submission.value,'not_submitted')
        self.assertEqual(result.code,'MODEL_DEADLINE_EXCEEDED')
        self.assertEqual(result.failure_kind.value,'timeout')
        self.assertFalse(result.provider_should_retry)
        self.assertEqual(result.receipt['deadline_at'],deadline.isoformat())

    def test_deadline_crossed_during_one_run_is_unknown_with_original_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace=Path(directory).resolve(); state=workspace/'.job-runtime'
            state.mkdir(mode=0o700); deadline=datetime.now(timezone.utc)+timedelta(milliseconds=30)
            run_dir=state/'runs'/'late'; calls=[]; evidence=[]
            def fake_run(profile,prompt,workspace_arg,run_arg,context=None,legacy=False):
                calls.append((profile,prompt,workspace_arg,run_arg,context,legacy))
                run_arg.mkdir(parents=True,mode=0o700)
                raw=(FIXTURES/'sanitized_structural_fixture.jsonl').read_bytes()
                final=run_arg/'last-message.txt';final.write_text('{"ok":true}\n');final.chmod(0o600)
                time.sleep(.08)
                return {'status':'succeeded','code':'MODEL_TURN_COMPLETED','receipt':{
                    'turn_completed':True,'exit_code':0,'process_started':True},
                    '_events':raw,'_final_bytes':final.read_bytes(),
                    '_artifacts':{'final_path':final,'final_ref':f'{run_arg.name}/last-message.txt'}}
            def fake_normalizer(**kwargs):
                evidence.append(kwargs['invocation_runner']())
                return ProviderResultV1(
                    provider='codex_cli',operation_id='attempt/late',phase='terminal',
                    submission='definitely_submitted',terminal_proof='verified',
                    status='succeeded',code='MODEL_TURN_COMPLETED',failure_kind='none')
            with patch.object(model,'_run_codex',side_effect=fake_run), \
                    patch.object(model,'normalize_codex_one_shot',side_effect=fake_normalizer) as runner:
                result=model.run_codex_one_shot(
                    {'model':'gpt-test','timeout_seconds':10},b'x',workspace,run_dir,
                    'attempt/late',{'deadline_at':deadline})
        self.assertEqual(len(calls),1); self.assertEqual(runner.call_count,1)
        self.assertEqual(len(evidence),1)
        self.assertEqual(evidence[0].deadline_at,deadline)
        self.assertGreater(evidence[0].ended_at,deadline)
        self.assertEqual(result.status.value,'unknown')
        self.assertEqual(result.phase.value,'submitted')
        self.assertEqual(result.submission.value,'possibly_submitted')
        self.assertEqual(result.code,'MODEL_DEADLINE_EXCEEDED')
        self.assertEqual(result.failure_kind.value,'timeout')
        self.assertFalse(result.provider_should_retry)
        self.assertEqual(result.receipt['deadline_at'],deadline.isoformat())

    def test_cancel_before_launch_is_retryable_without_process(self):
        import threading
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            auth = workspace / '.job-runtime' / 'auth'
            auth.mkdir(parents=True, mode=0o700); auth.chmod(0o700)
            (auth/'auth.json').write_text('{}'); (auth/'auth.json').chmod(0o600)
            stop = threading.Event(); stop.set()
            profile={'codex_bin':'/bin/true','model':'gpt-test','effort':'medium',
                     'timeout_seconds':10,'auth_home':str(auth)}
            with patch.object(model, '_run_codex') as runner:
                result=model.run_codex_one_shot(profile,b'x',workspace,
                    workspace/'.job-runtime'/'runs'/'cancelled','attempt/cancel',
                    {'cancel_event':stop})
            runner.assert_not_called()
            self.assertEqual(result.status.value,'retryable')
            self.assertEqual(result.phase.value,'not_started')

    def test_v2_bytes_use_only_pipes_and_clean_known_terminal_output(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace,profile,run_dir=self.v2_fixture(directory)
            canary=b'PIPE-ONLY-PRIVATE-CANARY'
            source=canary
            result=model.run_codex_one_shot(profile,source,workspace,run_dir,'attempt/multi')
            self.assertEqual(result.status.value,'succeeded')
            probe=json.loads((run_dir/'probe.json').read_text())
            self.assertEqual(probe['sha256'],hashlib.sha256(canary).hexdigest())
            self.assertEqual(probe['length'],len(canary))
            self.assertIn('history.persistence="none"',probe['args'])
            self.assertNotIn(canary.decode(),json.dumps(probe))
            self.assertFalse((run_dir/'prompt.txt').exists())
            self.assertFalse((run_dir/'events.jsonl').exists())
            self.assertFalse((run_dir/'stderr.log').exists())
            self.assertFalse((run_dir/'last-message.txt').exists())
            self.assertNotIn(canary.decode(),repr(result.receipt))
            for path in workspace.rglob('*'):
                if path.is_file():self.assertNotIn(canary,path.read_bytes())

    def test_v2_raw_event_and_stderr_canary_are_never_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_canary=b'RAW-EVENT-STDERR-CANARY'
            workspace,profile,run_dir=self.v2_fixture(directory,raw_canary=raw_canary)
            result=model.run_codex_one_shot(
                profile,b'clean prompt',workspace,run_dir,'attempt/raw-canary')
            self.assertEqual(result.status.value,'succeeded')
            self.assertNotIn(raw_canary.decode(),repr(result.receipt))
            for path in workspace.rglob('*'):
                if path.is_file():self.assertNotIn(raw_canary,path.read_bytes())

    def test_v2_bytes_have_no_public_non_success_artifact_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace,profile,run_dir=self.v2_fixture(directory,terminal=False)
            result=model.run_codex_one_shot(profile,b'bound bytes',workspace,run_dir,'attempt/non-success')
            self.assertEqual(result.status.value,'unknown')
            self.assertEqual(result.receipt['output_disposition'],'retained_unknown')
            encoded=repr(result.receipt).lower()
            for token in ('path','ref','sha256','digest'):
                self.assertNotIn(token,encoded)
            self.assertTrue((run_dir/'last-message.txt').is_file())
            self.assertEqual(stat.S_IMODE((run_dir/'last-message.txt').stat().st_mode),0o600)

    def test_v2_unknown_retains_only_private_final_custody(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace,profile,run_dir=self.v2_fixture(directory,terminal=False)
            canary=b'RAW-STREAM-CANARY'
            lease=canary
            result=model.run_codex_one_shot(profile,lease,workspace,run_dir,'attempt/unknown')
            self.assertEqual(result.status.value,'unknown')
            self.assertEqual(result.receipt['output_disposition'],'retained_unknown')
            self.assertTrue((run_dir/'last-message.txt').is_file())
            self.assertFalse((run_dir/'events.jsonl').exists())
            self.assertFalse((run_dir/'stderr.log').exists())
            self.assertNotIn(canary,(run_dir/'last-message.txt').read_bytes())
            encoded=json.dumps(dict(result.receipt),sort_keys=True).lower()
            self.assertFalse(any(token in encoded for token in ('path','ref','sha256','digest')))

    def test_strict_prelaunch_does_not_create_run_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace,profile,run_dir=self.v2_fixture(directory)
            profile['strict_process_tree_containment']=True
            lease=b'never opened'
            result=model.run_codex_one_shot(profile,lease,workspace,run_dir,'attempt/strict')
            self.assertEqual(result.status.value,'failed')
            self.assertFalse(run_dir.exists())


if __name__ == '__main__':
    unittest.main()
