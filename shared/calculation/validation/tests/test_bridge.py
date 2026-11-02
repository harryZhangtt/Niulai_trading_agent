"""Real boundary and malformed-request regressions; no accounts or live services."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared.calculation.validation import client, runner, acceptance


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


if __name__=='__main__':unittest.main()
