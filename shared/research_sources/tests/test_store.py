"""Independent state/readback tests, including actual process death and races."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from shared.research_sources.artifacts import SOURCE_STATE, SourceError, digest, read, save
from shared.research_sources.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.store = Store(self.directory / 'store')
        raw = save(self.directory, b'Synthetic original issuer revenue table: USD millions, Q1, 123.', suffix='txt')
        self.source = save(self.directory, {'provider': 'synthetic_issuer', 'source_url': 'https://example.com/report',
            'upstream_id': 'synthetic-2025q1', 'raw': raw, 'text': raw, 'available_at': '2025-05-01T00:00:00Z'})
        self.payload = {'entity': 'SYNTHETIC', 'metric': 'revenue', 'definition': 'reported',
                        'period': '2025Q1', 'unit': 'USD millions', 'value': '123', 'source_ref': self.source}

    def child(self, code, *args):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        return subprocess.Popen([sys.executable, '-c', code, *map(str, args)], cwd=Path(__file__).resolve().parents[3],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def binding(self, row):
        return {k: row[k] for k in ('revision', 'lifecycle_revision')} | {'observation_id': row['id']}

    def test_idempotency_conflicts_and_history(self):
        first = self.store.create('request-1', 'revenue-1', self.payload)
        replay = self.store.create('request-1', 'revenue-1', self.payload)
        self.assertTrue(replay['idempotent_replay'])
        self.assertEqual(first['payload_ref'], replay['payload_ref'])
        with self.assertRaisesRegex(SourceError, 'STORE_REQUEST_CONFLICT'):
            self.store.create('request-1', 'revenue-1', {**self.payload, 'value': '124'})
        changed = self.store.revise('request-2', 'revenue-1', {**self.payload, 'value': '124'}, 1)
        self.assertEqual(changed['revision'], 2)
        self.assertEqual(self.store.read('revenue-1', 1)['payload']['value'], '123')
        self.assertEqual(self.store.find(entity='SYNTHETIC', metric='revenue')[0]['revision'], 2)
        with self.assertRaisesRegex(SourceError, 'STORE_REVISION_CONFLICT'):
            self.store.revise('stale', 'revenue-1', self.payload, 1)
        self.assertEqual(len(self.store.events()), 2)

    def test_withdrawal_blocks_new_use_preserves_history_and_snapshot(self):
        first = self.store.create('create', 'revenue', self.payload)
        requirement = save(self.directory, {'id': 'reported-q1', 'cutoff': '2025-05-02T00:00:00Z'})
        snapshot = self.store.commit_snapshot('publish', requirement, [self.binding(first)])
        self.store.withdraw('withdraw', 'revenue', 1, 'Synthetic corrected filing pending review')
        self.assertEqual(self.store.find(entity='SYNTHETIC'), [])
        with self.assertRaisesRegex(SourceError, 'OBSERVATION_WITHDRAWN'):
            self.store.read('revenue')
        self.assertEqual(self.store.read('revenue', 1)['payload']['value'], '123')
        self.assertEqual(self.store.read_snapshot(snapshot['snapshot_id'])['manifest']['bindings'][0]['revision'], 1)
        with self.assertRaisesRegex(SourceError, 'SNAPSHOT_DEPENDENCY_CHANGED'):
            self.store.commit_snapshot('late-publish', requirement, [self.binding(first)])
        with self.assertRaisesRegex(SourceError, 'OBSERVATION_WITHDRAWN'):
            self.store.revise('revive', 'revenue', self.payload, 2)

    def test_exact_snapshot_and_manifest_idempotency(self):
        row = self.store.create('create', 'x', self.payload)
        requirement = save(self.directory, {'id': 'q1'})
        first = self.store.commit_snapshot('snapshot', requirement, [self.binding(row)])
        replay = self.store.commit_snapshot('snapshot', requirement, [self.binding(row)])
        self.assertTrue(replay['idempotent_replay'])
        self.assertEqual(first['snapshot_id'], replay['snapshot_id'])
        self.assertEqual(len(self.store.events()), 2)
        self.assertEqual(self.store.events(after=1)[0]['event_type'], 'snapshot_committed')
        with self.assertRaisesRegex(SourceError, 'SNAPSHOT_BINDING_DUPLICATE'):
            self.store.commit_snapshot('bad', requirement, [self.binding(row), self.binding(row)])

    def test_bad_source_and_corruption_cannot_publish(self):
        with self.assertRaisesRegex(SourceError, 'OBSERVATION_SOURCE_REQUIRED'):
            self.store.create('missing', 'x', {'value': '1'})
        bad = save(self.directory, {'provider': 'x', 'source_url': 'https://example.com', 'upstream_id': 'x'})
        with self.assertRaises(SourceError):
            self.store.create('bad', 'x', {'source_ref': bad})
        row = self.store.create('good', 'x', self.payload)
        Path(row['payload_ref']['path']).write_text('{}')
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_HASH_MISMATCH'):
            self.store.commit_snapshot('snapshot', save(self.directory, {'requirement': 'x'}), [self.binding(row)])
        with sqlite3.connect(self.store.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM snapshots').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 1)

    def test_source_identity_is_stable(self):
        self.store.create('first', 'x', self.payload)
        source = save(self.directory, {'provider': 'another-provider', 'source_url': 'https://example.com/report',
                    'upstream_id': 'synthetic-2025q1', 'raw': read(self.source)['raw']})
        with self.assertRaisesRegex(SourceError, 'OBSERVATION_IDENTITY_CHANGED'):
            self.store.revise('change-provider', 'x', {**self.payload, 'source_ref': source}, 1)

    def test_snapshot_preserves_scoped_receipt_and_checks_original_bytes(self):
        row = self.store.create('first', 'x', self.payload)
        requirement = save(self.directory, {'id': 'q1'})
        use = save(self.directory, {'status': 'synthetic-qualified', 'claim': 'q1', 'observation_revision': 1})
        binding = {**self.binding(row), 'use_receipt_ref': use}
        snapshot = self.store.commit_snapshot('publish', requirement, [binding])
        self.assertEqual(self.store.read_snapshot(snapshot['snapshot_id'])['manifest']['bindings'][0]['use_receipt_ref'], use)
        raw = read(self.source)['raw']
        Path(raw['path']).write_bytes(b'changed original')
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_HASH_MISMATCH'):
            self.store.commit_snapshot('bad-publish', requirement, [binding])

    def test_concurrent_same_request_has_one_commit_and_event(self):
        code = "from shared.research_sources.store import Store; import sys,json; print(json.dumps(Store(sys.argv[1]).create('same','x',json.loads(sys.argv[2]))))"
        processes = [self.child(code, self.store.directory, json.dumps(self.payload)) for _ in range(5)]
        results = []
        for p in processes:
            out, err = p.communicate(timeout=15)
            self.assertEqual(p.returncode, 0, err)
            results.append(json.loads(out))
        self.assertEqual(sum(not x['idempotent_replay'] for x in results), 1)
        with sqlite3.connect(self.store.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM observations').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 1)

    def test_competing_expected_revision_updates_have_one_winner(self):
        self.store.create('create', 'x', self.payload)
        code = "from shared.research_sources.store import Store; from shared.research_sources.artifacts import SourceError; import sys,json\ntry: print(json.dumps(Store(sys.argv[1]).revise(sys.argv[3],'x',json.loads(sys.argv[2]),1)))\nexcept SourceError as e: print(str(e));sys.exit(3)"
        processes = [self.child(code, self.store.directory, json.dumps({**self.payload, 'value': str(i)}), 'revision-%d' % i) for i in range(3)]
        rows = [(*p.communicate(timeout=15), p.returncode) for p in processes]
        self.assertEqual(sum(row[2] == 0 for row in rows), 1, rows)
        self.assertTrue(all(row[2] == 0 or 'STORE_REVISION_CONFLICT' in row[0] for row in rows), rows)
        self.assertEqual(self.store.read('x')['revision'], 2)
        self.assertEqual(len(self.store.events()), 2)

    def test_process_death_before_commit_rolls_back_but_after_commit_replays(self):
        before = "from shared.research_sources.store import Store; import os,sys,json\nStore._finish=staticmethod(lambda *args: os._exit(71))\nStore(sys.argv[1]).create('crash-before','x',json.loads(sys.argv[2]))"
        p = self.child(before, self.store.directory, json.dumps(self.payload)); p.communicate(timeout=15)
        self.assertEqual(p.returncode, 71)
        with sqlite3.connect(self.store.path) as db:
            for table in ('observations', 'heads', 'requests', 'events'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)
        self.assertTrue(list(self.store.blobs.glob('*.json')))  # harmless orphan, never indexed
        after = "from shared.research_sources.store import Store; import os,sys,json\nStore(sys.argv[1]).create('crash-after','x',json.loads(sys.argv[2]));os._exit(72)"
        p = self.child(after, self.store.directory, json.dumps(self.payload)); p.communicate(timeout=15)
        self.assertEqual(p.returncode, 72)
        self.assertIsNotNone(self.store.receipt('crash-after'))
        self.assertTrue(self.store.create('crash-after', 'x', self.payload)['idempotent_replay'])
        self.assertEqual(len(self.store.events()), 1)

    def test_atomic_blob_concurrency_and_death_before_publication(self):
        code = "from shared.research_sources.artifacts import save; import sys; save(sys.argv[1],b'x'*1000000,suffix='txt')"
        processes = [self.child(code, self.directory) for _ in range(5)]
        for p in processes:
            _, err = p.communicate(timeout=15); self.assertEqual(p.returncode, 0, err)
        before = set(self.directory.glob('*.txt'))
        code = "from shared.research_sources import artifacts; import os,sys\nartifacts.os.link=lambda *args: os._exit(73)\nartifacts.save(sys.argv[1],b'unpublished-complete-bytes',suffix='txt')"
        p = self.child(code, self.directory); p.communicate(timeout=15)
        self.assertEqual(p.returncode, 73)
        self.assertEqual(set(self.directory.glob('*.txt')), before)
        self.assertTrue(list(self.directory.glob('.pending-*')))

    def test_suffix_escape_and_existing_blob_collision_rejected(self):
        for suffix in ('../escape', 'json/../../escape', ''):
            with self.assertRaisesRegex(SourceError, 'ARTIFACT_SUFFIX_INVALID'):
                save(self.directory, b'x', suffix=suffix)
        ref = save(self.directory, b'original', suffix='txt')
        Path(ref['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_COLLISION'):
            save(self.directory, b'original', suffix='txt')

    def test_damaged_payload_can_be_withdrawn_without_losing_tombstone(self):
        row = self.store.create('create', 'x', self.payload)
        Path(row['payload_ref']['path']).write_bytes(b'corrupt')
        withdrawn = self.store.withdraw('quarantine', 'x', 1, 'Damaged cached extraction')
        self.assertEqual(withdrawn['state'], 'withdrawn')
        self.assertIsNone(withdrawn['payload'])
        self.assertEqual(withdrawn['payload_error'], 'ARTIFACT_HASH_MISMATCH')
        self.assertEqual(self.store.read('x', include_withdrawn=True)['payload_error'], 'ARTIFACT_HASH_MISMATCH')
        with self.assertRaisesRegex(SourceError, 'OBSERVATION_WITHDRAWN'):
            self.store.read('x')
        self.assertEqual(self.store.events()[-1]['event_type'], 'observation_withdrawn')
        self.assertTrue(self.store.withdraw('quarantine', 'x', 1, 'Damaged cached extraction')['idempotent_replay'])

    def check_fixture(self, **changes):
        requirement = {'id': 'revenue-q1', 'criticality': 'critical', 'cutoff': '2025-05-02T00:00:00Z',
                       'decision_deadline': '2025-05-02T02:00:00Z', **changes}
        ref = save(self.directory, requirement)
        outcome = {'requirement_sha256': digest(requirement), 'policy_version': 'synthetic-policy-v1',
                   'next_check_at': '2025-05-02T01:00:00Z', 'decision_deadline': requirement['decision_deadline'],
                   'resume_condition': 'due', 'attempt': 0}
        return ref, outcome

    def test_due_check_roundtrip_idempotency_cas_and_restart(self):
        requirement, outcome = self.check_fixture()
        self.assertIsNone(self.store.read_check(requirement))
        saved = self.store.save_check('schedule', requirement, outcome)
        self.assertEqual(saved['generation'], 1)
        self.assertTrue(self.store.save_check('schedule', requirement, outcome)['idempotent_replay'])
        reopened = Store(self.store.directory)
        self.assertEqual(reopened.read_check(requirement)['generation'], 1)
        self.assertEqual(reopened.due_checks('2025-05-02T00:59:59Z'), [])
        self.assertFalse(reopened.due_checks('2025-05-02T01:00:00Z')[0]['deadline_expired'])
        self.assertTrue(reopened.due_checks('2025-05-02T02:01:00Z')[0]['deadline_expired'])
        waiting = {**outcome, 'next_check_at': None, 'resume_condition': 'access_changed', 'attempt': 1}
        with self.assertRaisesRegex(SourceError, 'CHECK_GENERATION_CONFLICT'):
            reopened.save_check('stale-generation', requirement, waiting, expected_generation=0)
        self.assertEqual(reopened.save_check('defer', requirement, waiting, expected_generation=1)['generation'], 2)
        self.assertEqual(reopened.due_checks('2025-05-03T00:00:00Z'), [])
        self.assertEqual(len([e for e in reopened.events() if e['event_type'] == 'requirement_check_saved']), 2)

    def test_due_check_cannot_change_requirement_deadline_or_timezone(self):
        requirement, outcome = self.check_fixture()
        cases = [({**outcome, 'requirement_sha256': '0' * 64}, 'CHECK_REQUIREMENT_MISMATCH'),
                 ({**outcome, 'decision_deadline': '2025-05-02T03:00:00Z'}, 'CHECK_DEADLINE_CHANGED'),
                 ({**outcome, 'next_check_at': '2025-05-02T03:00:00Z'}, 'CHECK_DUE_AFTER_DEADLINE'),
                 ({**outcome, 'next_check_at': '2025-05-02T01:00:00'}, 'CHECK_TIME_INVALID'),
                 ({**outcome, 'criticality': 'context'}, 'CHECK_OUTCOME_INVALID')]
        for i, (bad, code) in enumerate(cases):
            with self.assertRaisesRegex(SourceError, code):
                self.store.save_check('bad-%d' % i, requirement, bad)
        self.assertEqual(self.store.events(), [])

    def test_concurrent_due_check_cas_has_one_winner(self):
        requirement, outcome = self.check_fixture()
        self.store.save_check('initial', requirement, outcome)
        code = "from shared.research_sources.store import Store; from shared.research_sources.artifacts import SourceError; import sys,json\ntry: print(json.dumps(Store(sys.argv[1]).save_check(sys.argv[4],json.loads(sys.argv[2]),json.loads(sys.argv[3]),expected_generation=1)))\nexcept SourceError as e: print(str(e));sys.exit(3)"
        children = [self.child(code, self.store.directory, json.dumps(requirement), json.dumps(outcome), 'update-%d' % i) for i in range(3)]
        results = [(*p.communicate(timeout=15), p.returncode) for p in children]
        self.assertEqual(sum(x[2] == 0 for x in results), 1, results)
        self.assertTrue(all(x[2] == 0 or 'CHECK_GENERATION_CONFLICT' in x[0] for x in results), results)
        self.assertEqual(self.store.read_check(requirement)['generation'], 2)


if __name__ == '__main__':
    unittest.main()
