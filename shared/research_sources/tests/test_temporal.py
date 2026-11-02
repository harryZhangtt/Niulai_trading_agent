"""Deterministic synthetic fault canaries; no historical authenticity claim."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared.research_sources.artifacts import SOURCE_STATE, SourceError, read, save
from shared.research_sources.store import Store
from shared.research_sources.temporal import prepare_corpus


OLD = '2026-04-01T00:00:00Z'
CUTOFF = '2026-05-01T00:00:00Z'
NOW = '2026-11-01T00:00:00Z'


class TemporalTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def source(self, *, text='Synthetic old evidence', title='Synthetic old title', **changes):
        raw = save(self.directory, ('<h1>' + title + '</h1>' + text).encode(), suffix='html')
        return save(self.directory, {'provider': 'synthetic_issuer', 'upstream_id': 'synthetic-report',
            'source_url': 'https://example.com/synthetic-report', 'source_version': '1',
            'access_level': 'document', 'access_scope': 'public', 'retrieved_at': OLD, 'available_at': OLD,
            'published_at': OLD, 'availability_basis': 'first_observed', 'metadata': {'title': title},
            'raw': raw, 'text': save(self.directory, text.encode(), suffix='txt'), **changes})

    def broker(self, *pins, cutoff=CUTOFF, **kwargs):
        return prepare_corpus(list(pins), cutoff=cutoff, **kwargs)

    def test_exact_hash_binding_and_same_packet_both_arms(self):
        ref = self.source()
        broker = self.broker(ref)
        baseline, candidate = broker.worker_packet(), broker.worker_packet()
        self.assertEqual(baseline, candidate)
        source = baseline['sources'][0]
        self.assertEqual(source['source_id'], ref['sha256'])
        self.assertEqual(source['text_sha256'], read(ref)['text']['sha256'])
        self.assertEqual(broker.open(source['source_id'])['text'], 'Synthetic old evidence')
        self.assertEqual(broker.search('old')['results'][0]['title'], 'Synthetic old title')
        receipt = broker.host_diagnostics()
        self.assertEqual(receipt['sources'][0]['status'], 'eligible')
        self.assertNotEqual(receipt['corpus_binding_sha256'], self.broker(ref, cutoff=NOW).host_diagnostics()['corpus_binding_sha256'])

    def test_future_canary_before_any_title_snippet_body_or_count(self):
        canary = 'FUTURE_ORACLE_Z9'
        future = self.source(title=canary, text=canary, retrieved_at=NOW, available_at=NOW)
        empty = self.broker()
        broker = self.broker(future)
        self.assertEqual(broker.worker_packet(), empty.worker_packet())
        self.assertEqual(broker.search(canary), empty.search(canary))
        self.assertNotIn(canary, str(broker.worker_packet()))
        with self.assertRaisesRegex(SourceError, '^TEMPORAL_SOURCE_UNAVAILABLE$'):
            broker.open(future['sha256'])
        self.assertEqual(broker.host_diagnostics()['sources'][0]['reason_codes'], ['TEMPORAL_VERSION_AFTER_CUTOFF'])

    def test_old_title_and_publication_cannot_admit_new_body(self):
        ref = self.source(text='Synthetic newly modified future result', retrieved_at=NOW,
            available_at=OLD, published_at=OLD, availability_basis='provider_publication')
        self.assertEqual(self.broker(ref).worker_packet()['sources'], [])
        self.assertEqual(len(self.broker(ref, cutoff=NOW).worker_packet()['sources']), 1)

    def test_later_declared_modified_or_version_available_time_blocks_old_observation(self):
        for field in ('modified_at', 'updated_at', 'version_available_at', 'available_at'):
            ref = self.source(**{field: NOW})
            self.assertEqual(self.broker(ref).worker_packet()['sources'], [], field)

    def test_unknown_observation_fails_closed_even_with_old_date_and_boolean(self):
        ref = self.source(retrieved_at=None, historical_provenance_verified=True)
        broker = self.broker(ref)
        self.assertEqual(broker.worker_packet()['sources'], [])
        self.assertEqual(broker.host_diagnostics()['sources'][0]['status'], 'unknown')

    def test_malformed_time_not_repaired_by_publication(self):
        for value in ('2026-04-01', 'bad', 42, False):
            ref = self.source(retrieved_at=value)
            self.assertEqual(self.broker(ref).worker_packet()['sources'], [])
            self.assertIn('TEMPORAL_TIMESTAMP_INVALID', self.broker(ref).host_diagnostics()['sources'][0]['reason_codes'])

    def test_choose_old_eligible_version_not_future_head(self):
        old = self.source()
        new = self.source(source_version='2', text='Synthetic future replacement', retrieved_at=NOW, available_at=NOW)
        broker = self.broker(new, old)
        self.assertEqual([row['source_id'] for row in broker.worker_packet()['sources']], [old['sha256']])
        self.assertEqual([row['source_id'] for row in self.broker(old, new, cutoff=NOW).worker_packet()['sources']], [new['sha256']])

    def test_reuse_cached_receipt_at_earlier_cutoff_does_not_relabel_availability(self):
        ref = self.source(retrieved_at=NOW, available_at=OLD)
        later = self.broker(ref, cutoff=NOW).worker_packet()
        self.assertEqual(len(later['sources']), 1)
        self.assertEqual(self.broker(ref).worker_packet()['sources'], [])
        # A worker packet from the later case is not accepted as a source pin.
        self.assertEqual(self.broker(later).worker_packet()['sources'], [])

    def test_corrupt_content_rechecked_at_exposure(self):
        ref = self.source()
        broker = self.broker(ref)
        self.assertEqual(len(broker.worker_packet()['sources']), 1)
        Path(read(ref)['text']['path']).write_bytes(b'Synthetic future tampering')
        self.assertEqual(broker.worker_packet()['sources'], [])
        self.assertEqual(broker.search('tampering'), {'results': []})
        self.assertEqual(broker.host_diagnostics()['sources'][0]['reason_codes'], ['ARTIFACT_HASH_MISMATCH'])

    def test_corrupt_receipt_and_invalid_ref_fail_closed(self):
        ref = self.source(); Path(ref['path']).write_bytes(b'{}')
        broker = self.broker(ref, {'path': 'untrusted', 'sha256': 'not-a-hash'})
        self.assertEqual(broker.worker_packet()['sources'], [])
        self.assertEqual(len(broker.host_diagnostics()['sources']), 2)

    def test_qualified_reconstruction_is_separate_and_never_exposed(self):
        ref = self.source(retrieved_at=NOW, available_at=OLD)
        pin = {'source_ref': ref, 'qualified_reconstruction': {'published_at': OLD,
            'rationale': 'Synthetic old issuer document acquired today; original bytes not attested.'}}
        broker = self.broker(pin)
        self.assertEqual(broker.worker_packet()['sources'], [])
        row = broker.host_diagnostics()['sources'][0]
        self.assertEqual(row['status'], 'qualified_reconstruction')
        self.assertFalse(row['worker_visible'])

    def test_scope_mismatch_and_metadata_snapshot_not_exposed(self):
        for ref in (self.source(access_scope='private'), self.source(access_level='metadata',
                candidates=[{'title': 'Synthetic future discovery canary'}])):
            self.assertEqual(self.broker(ref).worker_packet()['sources'], [])

    def test_store_old_revision_eligible_and_withdrawal_rechecked(self):
        store = Store(self.directory / 'store')
        old = self.source(); new = self.source(source_version='2', retrieved_at=NOW, available_at=NOW)
        with patch('shared.research_sources.store.stamp', return_value=OLD):
            first = store.create('synth-create', 'synth-report', {'source_ref': old})
        with patch('shared.research_sources.store.stamp', return_value=NOW):
            store.revise('synth-revise', 'synth-report', {'source_ref': new}, 1)
        pin = {'source_ref': old, 'observation': {'observation_id': first['id'],
            'revision': first['revision'], 'lifecycle_revision': first['lifecycle_revision']}}
        broker = self.broker(pin, store=store)
        self.assertEqual(len(broker.worker_packet()['sources']), 1)
        store.withdraw('synth-withdraw', 'synth-report', 2, 'Synthetic unsafe evidence')
        self.assertEqual(broker.worker_packet()['sources'], [])
        self.assertEqual(broker.host_diagnostics()['sources'][0]['reason_codes'], ['TEMPORAL_SOURCE_WITHDRAWN'])

    def test_relabelled_source_cannot_reuse_old_store_revision_binding(self):
        store = Store(self.directory / 'store')
        old = self.source()
        with patch('shared.research_sources.store.stamp', return_value=OLD):
            row = store.create('synth-old', 'synth-report', {'source_ref': old})
        forged = save(self.directory, {**read(old), 'text': save(self.directory, b'Synthetic new body'),
            'available_at': OLD})
        pin = {'source_ref': forged, 'observation': {'observation_id': row['id'], 'revision': 1, 'lifecycle_revision': 1}}
        broker = self.broker(pin, store=store)
        self.assertEqual(broker.worker_packet()['sources'], [])
        self.assertEqual(broker.host_diagnostics()['sources'][0]['reason_codes'], ['TEMPORAL_SOURCE_BINDING_MISMATCH'])

    def test_later_store_record_does_not_mint_historical_provenance(self):
        store = Store(self.directory / 'store'); ref = self.source()
        with patch('shared.research_sources.store.stamp', return_value=NOW):
            store.create('synth-late', 'synth-report', {'source_ref': ref})
        pin = {'source_ref': ref, 'observation': {'observation_id': 'synth-report', 'revision': 1, 'lifecycle_revision': 1}}
        self.assertEqual(self.broker(pin, store=store).worker_packet()['sources'], [])

    def test_caller_mutation_cannot_change_pin_or_worker_state(self):
        ref = self.source(); pin = {'source_ref': deepcopy(ref)}
        broker = self.broker(pin)
        pin['source_ref']['sha256'] = 'f' * 64
        packet = broker.worker_packet(); packet['sources'][0]['title'] = 'caller mutation'
        self.assertEqual(broker.worker_packet()['sources'][0]['title'], 'Synthetic old title')
        with self.assertRaises(AttributeError):
            broker.cutoff = NOW


if __name__ == '__main__':
    unittest.main()
