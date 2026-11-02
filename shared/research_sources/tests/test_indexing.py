import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from shared.research_sources.artifacts import ROOT, SOURCE_STATE, SourceError, read
from shared.research_sources.indexing import RecordIndex


def record(**changes):
    return {'namespace': 'synthetic-catalog', 'record_id': 'r1', 'entity': 'SYNTH',
        'kind': 'catalog_metadata', 'title': 'Synthetic capacity report', 'source_family': 'issuer-1',
        'available_at': None, 'content_access': 'metadata_only',
        'content': {'pointer': '/unavailable/report.pdf'}, **changes}


class IndexTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / 'index'
        self.index = RecordIndex(self.directory)

    def selection(self, **changes):
        return self.index.select(entity='SYNTH', baseline_hash='a'*64, requirement_id='capacity',
            cutoff='2026-10-31T12:00:00Z', **changes)

    def test_roundtrip_idempotency_and_content_level(self):
        a = self.index.put(record()); b = self.index.put(record())
        self.assertEqual((a['route'], b['route']), ('created', 'reused'))
        self.assertEqual(a['binding'], b['binding'])
        self.assertEqual(len(self.index.store.events()), 1)
        row = self.index.store.read(a['binding']['observation_id'])
        source = read(row['payload']['source_ref'])
        self.assertEqual(json.loads(read(source['raw'], json_value=False)), record()['content'])
        candidate = self.selection()['candidates'][0]
        self.assertIn('original_document_not_present', candidate['limitations'])
        self.assertIn('availability_unknown', candidate['limitations'])

    def test_rejects_mislabeling_and_malformed_data(self):
        for changes in [{'content_access': 'document'}, {'available_at': '2026-10-31'},
                        {'entity': ' '}, {'content': {}}, {'extra': True},
                        {'content': 'x'*(1024*1024+1)}]:
            with self.assertRaises(SourceError): self.index.put(record(**changes))
        self.assertEqual(self.index.store.find(), [])

    def test_revision_cas_and_changed_baseline(self):
        first = self.index.put(record())
        second = self.index.put(record(content={'pointer': 'corrected'}), expected_revision=1)
        self.assertEqual(second['binding']['revision'], 2)
        with self.assertRaisesRegex(SourceError, 'INDEX_REVISION_CONFLICT'):
            self.index.put(record(), expected_revision=1)
        old = self.index.store.read(first['binding']['observation_id'], 1)
        self.assertEqual(old['payload']['content'], record()['content'])
        one = self.selection()
        two = self.index.select(entity='SYNTH', baseline_hash='b'*64,
            requirement_id='capacity', cutoff='2026-10-31T12:00:00Z')
        self.assertNotEqual(one['context'], two['context'])

    def test_future_unknown_deferral_and_terms(self):
        for i in range(5): self.index.put(record(record_id=str(i)))
        self.index.put(record(record_id='future', available_at='2099-01-01T00:00:00Z'))
        result = self.selection(limit=2)
        self.assertEqual((len(result['candidates']),len(result['deferred']),len(result['excluded'])), (2,3,1))
        self.assertEqual(result['excluded'][0]['reason'], 'available_after_cutoff')
        self.assertEqual(self.selection(terms=['not present'])['candidates'], [])
        self.assertFalse(result['auto_commit_research'])

    def test_snapshot_race_and_historical_readback(self):
        first = self.index.put(record()); selected = self.selection()
        snapshot = self.index.checkpoint('snap1', selected)
        self.assertEqual(self.index.store.read_snapshot(snapshot['snapshot_id'])['manifest']['bindings'],
                         [first['binding']])
        self.index.put(record(content={'pointer': 'new version'}))
        with self.assertRaisesRegex(SourceError, 'SNAPSHOT_DEPENDENCY_CHANGED'):
            self.index.checkpoint('stale-snapshot', selected)
        self.assertEqual(self.index.store.read_snapshot(snapshot['snapshot_id'])['manifest']['bindings'][0]['revision'],1)

    def test_corrupt_payload_cannot_be_reused_or_selected(self):
        first = self.index.put(record())
        row = self.index.store.read(first['binding']['observation_id'])
        raw = read(row['payload']['source_ref'])['raw']; Path(raw['path']).write_bytes(b'corrupted')
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_HASH_MISMATCH'): self.index.put(record())
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_HASH_MISMATCH'): self.selection()

    def test_withdrawal_not_revived(self):
        first = self.index.put(record()); oid = first['binding']['observation_id']
        self.index.store.withdraw('withdraw', oid, 1, 'Synthetic correction')
        self.assertEqual(self.selection()['candidates'], [])
        with self.assertRaisesRegex(SourceError, 'OBSERVATION_WITHDRAWN'): self.index.put(record())

    def test_multi_asset_keeps_one_underlying_source(self):
        a=self.index.put(record()); b=self.index.put(record(entity='OTHER'))
        aa=self.index.store.read(a['binding']['observation_id'])['payload']
        bb=self.index.store.read(b['binding']['observation_id'])['payload']
        self.assertEqual(aa['source_ref'],bb['source_ref'])
        self.assertNotEqual(a['binding']['observation_id'],b['binding']['observation_id'])

    def test_four_process_duplicate_creates_one_observation(self):
        script='''import json,sys
from shared.research_sources.indexing import RecordIndex
print(json.dumps(RecordIndex(sys.argv[1]).put(json.loads(sys.argv[2]))))'''
        children=[subprocess.Popen([sys.executable,'-c',script,str(self.directory),json.dumps(record())],
            cwd=ROOT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True) for _ in range(4)]
        routes=[]
        for child in children:
            out,err=child.communicate(timeout=30);self.assertEqual(child.returncode,0,err)
            route=json.loads(out)['route'];routes.append(route)
            self.assertIn(route,{'created','reused','reused_after_race'})
        self.assertEqual(routes.count('created'),1)
        self.assertEqual(len(self.index.store.find(entity='SYNTH')),1)
        self.assertEqual(len(self.index.store.events()),1)


if __name__=='__main__': unittest.main()
