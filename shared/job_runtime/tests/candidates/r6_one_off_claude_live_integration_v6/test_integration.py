from __future__ import annotations
from datetime import datetime, timezone
import copy
import hashlib
import inspect
import json
import os
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock
import sys

ROOT = pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v6 import (
    LocalOnlyProcessEffect, p0_output, run,
)
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v6 import authority as authmod
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v6 import process as processmod
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v6 import runner as runmod
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v6 import state as statemod
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v6.contracts import (
    BINARY_DESCRIPTOR, BINARY_REF, GRANT_REVIEW_SHA256, GRANT_SHA256, PROVIDER,
    REGISTRY_REVIEW_SHA256, REGISTRY_SHA256, SCOPE_SHA256, canonical_bytes,
    validate_seal,
)

FIX = ROOT / "shared/job_runtime/tests/fixtures/r6_one_off_claude_live_integration_v1"
NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)


class NeverEffect:
    def execute(self, *args, **kwargs):
        raise AssertionError("second provider-shaped effect")


class IntegrationV6Tests(unittest.TestCase):
    def case(self, scenario="nominal"):
        temp = tempfile.TemporaryDirectory(dir=FIX)
        self.addCleanup(temp.cleanup)
        base = pathlib.Path(temp.name)
        root = base / "run"
        seal = run(root, effect=LocalOnlyProcessEffect(True), scenario=scenario)
        return seal, root

    def test_public_api_has_no_authority_verifier_clock_or_live_default(self):
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            self.assertEqual(run(pathlib.Path(temp))['code'],
                             'PINNED_AUTHORITY_AND_EFFECT_REQUIRED')
        self.assertEqual(set(inspect.signature(run).parameters), {'root','effect','scenario'})
        self.assertEqual(set(inspect.signature(authmod.load_pinned).parameters), set())
        for keyword in ('authority','registry','grant','review','now','clock'):
            with self.assertRaises(TypeError):
                run(pathlib.Path('x'), **{keyword: object()})

    def test_all_exact_external_authority_files_hash_read_and_bind(self):
        expected = {authmod.REGISTRY_REF: REGISTRY_SHA256,
            authmod.REGISTRY_REVIEW_REF: REGISTRY_REVIEW_SHA256,
            authmod.GRANT_REF: GRANT_SHA256,
            authmod.GRANT_REVIEW_REF: GRANT_REVIEW_SHA256,
            authmod.SCOPE_REF: SCOPE_SHA256}
        for ref, digest in expected.items():
            raw = (ROOT / ref[0]).read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                             (ref[1], digest))
        authority = authmod.load_pinned()
        self.assertEqual(authority.grant['binary_ref'], BINARY_REF)
        self.assertEqual(authority.grant['binary'], BINARY_DESCRIPTOR)

    def test_authority_drift_stops_before_generation_and_effect(self):
        held = [authmod._held(ref) for ref in (authmod.REGISTRY_REF,
            authmod.REGISTRY_REVIEW_REF, authmod.GRANT_REF,
            authmod.GRANT_REVIEW_REF, authmod.SCOPE_REF)]
        stale = copy.deepcopy(held[2])
        stale.update(not_before='2024-01-01T00:00:00+00:00',
                     expires_at='2025-01-01T00:00:00+00:00')
        held[2] = stale
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            effect = mock.Mock()
            with mock.patch.object(authmod, '_held', side_effect=held), \
                 mock.patch.object(authmod, '_trusted_utc_now', return_value=NOW):
                seal = run(pathlib.Path(temp), effect=effect)
        self.assertEqual((seal['status'], seal['code']),
                         ('STOP','GRANT_STALE_OR_NOT_YET_VALID'))
        effect.execute.assert_not_called()

    def test_nominal_projection_promotes_authority_and_second_run_no_replay(self):
        seal, root = self.case()
        self.assertEqual((seal['version'],seal['status'],seal['engine']['provider']),
                         (6,'PASS','claude_host'))
        self.assertEqual(seal['state_authority']['state'], 'PASS')
        marker_path = root / 'public' / runmod.PUBLIC_NAME
        pending_path = root / 'public' / runmod.PUBLIC_PENDING_NAME
        marker = json.loads(marker_path.read_text())
        self.assertEqual((marker['state'],marker['authoritative'],marker['seal']),
                         ('COMMITTED_PROJECTION',False,seal))
        self.assertEqual(marker['pending_sha256'],
                         hashlib.sha256(pending_path.read_bytes()).hexdigest())
        record = statemod.read(root)
        self.assertEqual((record.state, record.terminal), ('PASS',seal))
        self.assertEqual(run(root,effect=NeverEffect()), seal)
        self.assertEqual(p0_output(seal)['schema'],
                         'r6-one-off-claude-live-integration-v6')
        database = root/'engine/.job-runtime/r6-one-off-evidence-v1/engine/schedule.sqlite'
        with sqlite3.connect(database) as connection:
            self.assertEqual(connection.execute('select provider from slots').fetchone()[0],
                             'claude_host')

    def _compound_projection_failure(self, scenario: str, target_name: str,
                                     failure: str, quarantine_fault: str):
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            root = pathlib.Path(temp)/'run'
            real_read = runmod._read_held
            real_unlink = pathlib.Path.unlink
            calls = {'unlink':0,'rename':0,'quarantine_write':0,
                     'quarantine_fsync':0,'parent_fsync':0,'readback':0}
            readback_started = [False]
            def fail_read(path):
                if pathlib.Path(path).name == target_name and failure == 'readback':
                    readback_started[0] = True
                    calls['readback'] += 1
                    raise OSError('persistent readback')
                return real_read(path)
            def fail_unlink(path, *args, **kwargs):
                if pathlib.Path(path).name == target_name:
                    calls['unlink'] += 1
                    raise OSError('persistent unlink')
                return real_unlink(path, *args, **kwargs)
            def fail_rename(src, dst, *args, **kwargs):
                if pathlib.Path(src).name == target_name:
                    calls['rename'] += 1
                    raise OSError('persistent rename')
                return os.rename(src,dst,*args,**kwargs)
            real_quarantine_write = runmod._quarantine_write
            real_quarantine_fsync = runmod._quarantine_fsync
            def quarantine_write(fd, raw):
                calls['quarantine_write'] += 1
                if quarantine_fault == 'write':
                    raise OSError('persistent quarantine write')
                return real_quarantine_write(fd, raw)
            def quarantine_fsync(fd):
                calls['quarantine_fsync'] += 1
                if quarantine_fault == 'fsync':
                    raise OSError('persistent quarantine fsync')
                return real_quarantine_fsync(fd)
            target_path = root / ('public' if target_name == runmod.PUBLIC_NAME else '') / target_name
            real_parent = runmod._fsync_directory
            def fail_parent(path):
                should_fail = (os.path.lexists(target_path) and
                    (failure == 'parent_fsync' or readback_started[0]))
                if should_fail:
                    calls['parent_fsync'] += 1
                    raise OSError('persistent parent fsync')
                return real_parent(path)
            effect = mock.Mock(wraps=LocalOnlyProcessEffect(True))
            with mock.patch.object(runmod,'_read_held',side_effect=fail_read), \
                 mock.patch.object(pathlib.Path,'unlink',autospec=True,side_effect=fail_unlink), \
                 mock.patch.object(runmod.os,'rename',side_effect=fail_rename), \
                 mock.patch.object(runmod,'_quarantine_write',side_effect=quarantine_write), \
                 mock.patch.object(runmod,'_quarantine_fsync',side_effect=quarantine_fsync), \
                 mock.patch.object(runmod,'_fsync_directory',side_effect=fail_parent):
                first = run(root,effect=effect,scenario=scenario)
                second = run(root,effect=NeverEffect(),scenario=scenario)
            self.assertEqual((first['status'],first['unknown_fence']['durability'],
                              first['state_authority']['state']),
                             ('UNKNOWN','DURABLE','UNKNOWN'))
            self.assertEqual(second, first)
            self.assertTrue(os.path.lexists(root / ('public' if target_name == runmod.PUBLIC_NAME else '') / target_name))
            required = {'unlink','rename','quarantine_write','parent_fsync'}
            if quarantine_fault == 'fsync': required.add('quarantine_fsync')
            if failure == 'readback': required.add('readback')
            self.assertTrue(all(calls[key] > 0 for key in required), calls)
            projection = runmod._read_commit(
                root / ('public' if target_name == runmod.PUBLIC_NAME else '') /
                    (runmod.PUBLIC_PENDING_NAME if target_name == runmod.PUBLIC_NAME else runmod.FENCE_PENDING_NAME),
                target_path,
                'PASS' if target_name == runmod.PUBLIC_NAME else 'UNKNOWN_FENCE')
            self.assertEqual(projection['status'],
                             'PASS' if target_name == runmod.PUBLIC_NAME else 'UNKNOWN')
            self.assertEqual(effect.execute.call_count, 1)
            self.assertEqual(statemod.read(root).state, 'UNKNOWN')
            return root

    def test_pass_projection_compound_failure_survives_but_authority_blocks_stale_acceptance(self):
        for failure in ('parent_fsync','readback'):
            for quarantine_fault in ('write','fsync'):
                with self.subTest(failure=failure,quarantine_fault=quarantine_fault):
                    self._compound_projection_failure('nominal', runmod.PUBLIC_NAME,
                                                      failure, quarantine_fault)

    def test_unknown_projection_compound_failure_survives_but_authority_blocks_stale_acceptance(self):
        for failure in ('parent_fsync','readback'):
            for quarantine_fault in ('write','fsync'):
                with self.subTest(failure=failure,quarantine_fault=quarantine_fault):
                    self._compound_projection_failure('timeout', runmod.FENCE_NAME,
                                                      failure, quarantine_fault)

    def test_second_run_readback_failure_poison_dominates_previous_pass(self):
        seal, root = self.case()
        self.assertEqual(seal['status'], 'PASS')
        real = runmod._read_held
        def fail_projection(path):
            if pathlib.Path(path).name == runmod.PUBLIC_NAME:
                raise OSError('persistent second-run readback')
            return real(path)
        with mock.patch.object(runmod,'_read_held',side_effect=fail_projection):
            second = run(root,effect=NeverEffect())
        self.assertEqual((second['status'],second['state_authority']['state']),
                         ('UNKNOWN','POISONED'))
        self.assertEqual(run(root,effect=NeverEffect()), second)
        self.assertEqual(statemod.read(root).state, 'POISONED')

    def test_recovery_precedes_generic_freshness_collision(self):
        first, root = self.case('timeout')
        with mock.patch.object(runmod,'materialize_provider_free_case',
                               side_effect=AssertionError('WORKSPACE_MUST_BE_FRESH')) as materialize:
            second = run(root,effect=NeverEffect())
        self.assertEqual(second, first)
        materialize.assert_not_called()

    def test_marker_pair_hash_mismatch_poisoned_without_replay(self):
        seal, root = self.case()
        pending_path = root/'public'/runmod.PUBLIC_PENDING_NAME
        pending = json.loads(pending_path.read_text())
        pending['candidate_seal_sha256'] = 'f'*64
        pending_path.write_bytes(canonical_bytes(pending))
        recovered = run(root,effect=NeverEffect())
        self.assertEqual((recovered['status'],recovered['state_authority']['state']),
                         ('UNKNOWN','POISONED'))

    def test_projection_without_authority_never_accepted(self):
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            root=pathlib.Path(temp); (root/'public').mkdir()
            (root/'public'/runmod.PUBLIC_NAME).write_text('{}')
            first=run(root,effect=NeverEffect())
            second=run(root,effect=NeverEffect())
        self.assertEqual((first['status'],first['unknown_fence']['durability']),
                         ('UNKNOWN','NON_DURABLE'))
        self.assertEqual(second, first)

    def test_write_short_zero_and_no_replace_publication_primitives(self):
        raw=b'{"provider_free":true}'
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            path=pathlib.Path(temp)/'short.json'; real=runmod.os.write
            with mock.patch.object(runmod.os,'write',side_effect=lambda fd,v:real(fd,v[:7])):
                self.assertEqual(runmod._publish_verified(path,raw),raw)
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            path=pathlib.Path(temp)/'zero.json'
            with mock.patch.object(runmod.os,'write',return_value=0), self.assertRaises(OSError):
                runmod._publish_verified(path,raw)
            self.assertFalse(os.path.lexists(path))

    def test_pid_reuse_and_parent_exit_resistant_cleanup(self):
        expected='a'*64
        with mock.patch.object(processmod,'_token_sha',return_value='b'*64):
            self.assertFalse(processmod._same_process(4242,expected))
        seal,_=self.case('parent_exit_resistant')
        self.assertEqual(seal['status'],'PASS')
        self.assertTrue(seal['process']['descendants_reaped'])
        with self.assertRaises(ProcessLookupError):
            os.kill(seal['process']['child_pid'],0)

    def test_runtime_rejects_authority_and_pass_contradictions(self):
        seal,_=self.case()
        mutations=[]
        for path,value in ((('process','descendants_reaped'),False),
            (('publication','readback_verified'),False),
            (('cleanup','exception_count'),1),
            (('state_authority','state'),'UNKNOWN')):
            bad=copy.deepcopy(seal); bad[path[0]][path[1]]=value; mutations.append(bad)
        bad=copy.deepcopy(seal); bad['state_authority']['extra']=True; mutations.append(bad)
        for bad in mutations:
            with self.assertRaises(Exception): validate_seal(bad)


if __name__ == '__main__':
    unittest.main()
