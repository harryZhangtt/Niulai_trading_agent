"""Real boundary and malformed-request regressions; no accounts or live services."""
import json
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

from shared.calculation.validation import client, runner, acceptance, worker


class BridgeBoundaryTests(unittest.TestCase):
    def setUp(self):
        folder=runner.STATE/'tests';folder.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=folder);self.addCleanup(self.temp.cleanup)
        self.state=Path(self.temp.name)
        self.attempt='12345678-1234-1234-1234-123456789abc'
        self.change='synthetic-only'
        self.when='2026-10-31T00:00:00+00:00'
        self.patch=patch.object(client,'STATE',self.state);self.patch.start();self.addCleanup(self.patch.stop)
        p=patch.object(acceptance,'STATE',self.state);p.start();self.addCleanup(p.stop)
        self.folder=self.state/'bridge'/self.attempt;self.folder.mkdir(parents=True)
        self.inbox=self.state/'client'/self.attempt;self.inbox.mkdir(parents=True)
        self.ready={'change_id':self.change,'attempt_id':self.attempt,'scheduled_at':self.when,'candidate_sha256':'0'*64}
        (self.folder/'ready.json').write_text(json.dumps(self.ready))

    def test_context_mismatch_never_creates_request(self):
        with self.assertRaises(ValueError):client.request('other',self.attempt,self.when)
        self.assertFalse((self.inbox/'request.json').exists())

    def test_conflicting_request_is_not_replayed(self):
        (self.inbox/'request.json').write_text('{}')
        with self.assertRaises(ValueError):client.request(self.change,self.attempt,self.when)

    def test_oversized_ready_is_rejected_before_parse(self):
        (self.folder/'ready.json').write_text('x'*3000)
        with self.assertRaises(ValueError):client.request(self.change,self.attempt,self.when)

    def test_symlinked_ready_is_rejected(self):
        original=self.folder/'ready.json';data=original.read_bytes();original.unlink()
        target=self.state/'public.json';target.write_bytes(data);original.symlink_to(target)
        with self.assertRaises(ValueError):client.request(self.change,self.attempt,self.when)

    def test_atomic_state_write_rejects_symlink_parent(self):
        link=self.state/'link';target=self.state/'target';target.mkdir();link.symlink_to(target)
        with self.assertRaises(ValueError):runner.atomic(link/'result.json',{})
        self.assertFalse((target/'result.json').exists())

    def test_host_reads_valid_request_through_fixed_dirfds(self):
        (self.inbox/'request.json').write_text(json.dumps(self.ready))
        acceptance.read_request(self.attempt,self.ready,1)

    def test_host_rejects_symlink_and_hardlinked_request(self):
        source=self.state/'public-request.json';source.write_text(json.dumps(self.ready))
        path=self.inbox/'request.json';path.symlink_to(source)
        with self.assertRaises(OSError):acceptance.read_request(self.attempt,self.ready,1)
        path.unlink();os.link(source,path)
        with self.assertRaises(ValueError):acceptance.read_request(self.attempt,self.ready,1)

    def test_host_rejects_fifo_without_blocking(self):
        os.mkfifo(self.inbox/'request.json')
        with self.assertRaises(ValueError):acceptance.read_request(self.attempt,self.ready,1)

    def test_host_rejects_symlinked_attempt_directory(self):
        self.inbox.rmdir();other=self.state/'other';other.mkdir();self.inbox.symlink_to(other)
        with self.assertRaises(OSError):acceptance.read_request(self.attempt,self.ready,1)

    def test_mutated_diagnostic_policy_cannot_remove_launched_network_deny(self):
        profile=runner.sandbox_profile(self.state)
        (self.state/'worker.sb').write_text('(version 1)(allow default)')
        code="import socket\ntry:\n s=socket.socket();s.connect(('127.0.0.1',9));print(False)\nexcept PermissionError:print(True)"
        value=runner.child([str(runner.STATE/'.venv/bin/python'),'-B','-c',code],profile,runner.environment(),5)
        self.assertEqual(value['exit_code'],0);self.assertEqual(value['stdout'].strip(),'True')

    def test_worker_audit_probe_denies_native_process_escape_and_applies_limits(self):
        profile=runner.sandbox_profile(self.state)
        env=runner.environment(self.state/'probe-state')
        command=[str(runner.STATE/'.venv/bin/python'),'-B','-m',
                 'shared.calculation.validation.worker','--security-probe']
        value=runner.child(command,profile,env,10)
        self.assertEqual(value['exit_code'],0,value.get('stderr_tail'))
        observed=json.loads(value['stdout'])
        self.assertTrue(all(observed['checks'].values()),observed)
        for name in ('RLIMIT_FSIZE','RLIMIT_NOFILE','RLIMIT_NPROC'):
            self.assertTrue(observed['resource_limits'][name]['applied'],observed)
        address=observed['resource_limits']['RLIMIT_AS']
        self.assertTrue(address['available'],observed)
        if sys.platform=='darwin':
            self.assertFalse(address['supported'],observed)
            self.assertFalse(address['required'],observed)
            self.assertEqual(address['error_type'],'ValueError')
        else:
            self.assertTrue(address['applied'],observed)
        self.assertRegex(observed['audit_policy_sha256'],r'^[0-9a-f]{64}$')

    def test_sandboxed_worker_really_denies_fork_family(self):
        profile=runner.sandbox_profile(self.state)
        env=runner.environment(self.state/'fork-probe-state')
        command=[str(runner.STATE/'.venv/bin/python'),'-B','-m',
                 'shared.calculation.validation.worker','--security-probe']
        value=runner.child(command,profile,env,10)
        self.assertEqual(value['exit_code'],0,value.get('stderr_tail'))
        checks=json.loads(value['stdout'])['checks']
        self.assertTrue(checks['fork_denied'],checks)
        self.assertTrue(checks['forkpty_event_denied'],checks)
        self.assertFalse(worker.process_event_allowed('os.fork',(),None,None))
        self.assertFalse(worker.process_event_allowed('os.forkpty',(),None,None))

    def test_process_allowlist_is_exact_and_limited_to_pinned_python(self):
        output=self.state/'output';output.mkdir()
        scratch=self.state/'scratch';scratch.mkdir()
        env={'CALCULATION_WORKER_SCRATCH':str(scratch)}
        command=[worker.INTERPRETER,'-B','-m','unittest','test_execution_pnl_independent']
        child_env={'PYTHONDONTWRITEBYTECODE':'1','PYTHONHASHSEED':'0',
                   'PYTHONPATH':str(runner.ROOT/'shared/calculation/legacy/holdings'),
                   'TMPDIR':str(runner.STATE/'tmp')}
        with patch.dict(os.environ,env,clear=False):
            self.assertTrue(worker.process_event_allowed(
                'subprocess.Popen',(worker.INTERPRETER,command,output,child_env),'contracts',output))
            self.assertFalse(worker.process_event_allowed(
                'subprocess.Popen',(worker.INTERPRETER,command,output,{}),'contracts',output))
            self.assertFalse(worker.process_event_allowed(
                'subprocess.Popen',('/bin/cat',['/bin/cat','/dev/null'],None,None),'contracts',output))
            self.assertFalse(worker.process_event_allowed(
                'os.exec',(worker.INTERPRETER,command,child_env),'contracts',output))

    def test_worker_state_bounds_remove_excess_and_scratch(self):
        output=self.state/'bounded-output';scratch=self.state/'bounded-scratch'
        output.mkdir();scratch.mkdir()
        (output/'one').write_bytes(b'1234');(scratch/'two').write_bytes(b'5678')
        with patch.object(runner,'MAX_WORKER_STATE_BYTES',7), patch.object(runner,'MAX_WORKER_STATE_FILES',2):
            observed=runner.finalize_worker_state(output,scratch,retain_output=True)
        self.assertFalse(observed['within_limits'])
        self.assertFalse(output.exists());self.assertFalse(scratch.exists())
        self.assertTrue(observed['scratch_cleaned']);self.assertFalse(observed['output_retained'])

    def test_worker_file_count_bound_removes_output_and_scratch(self):
        output=self.state/'count-output';scratch=self.state/'count-scratch'
        output.mkdir();scratch.mkdir()
        (output/'one').write_bytes(b'1');(scratch/'two').write_bytes(b'2')
        with patch.object(runner,'MAX_WORKER_STATE_BYTES',100), patch.object(runner,'MAX_WORKER_STATE_FILES',1):
            observed=runner.finalize_worker_state(output,scratch,retain_output=True)
        self.assertFalse(observed['within_limits'])
        self.assertFalse(output.exists());self.assertFalse(scratch.exists())
        self.assertEqual(observed['usage']['files'],2)

    def test_worker_state_bounds_retain_valid_output_but_clean_scratch(self):
        output=self.state/'valid-output';scratch=self.state/'valid-scratch'
        output.mkdir();scratch.mkdir()
        (output/'one').write_bytes(b'1234');(scratch/'two').write_bytes(b'5678')
        observed=runner.finalize_worker_state(output,scratch,retain_output=True)
        self.assertTrue(observed['within_limits'])
        self.assertTrue(output.exists());self.assertFalse(scratch.exists())
        self.assertTrue(observed['output_retained'])


if __name__=='__main__':unittest.main()
