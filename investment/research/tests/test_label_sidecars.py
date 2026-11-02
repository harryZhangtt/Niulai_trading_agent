from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from shared.research_sources.artifacts import INVESTMENT_STATE, SourceError, digest, read, save
from investment.research import information_labels as labels


class LabelSidecarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=INVESTMENT_STATE, prefix='test-labels-')
        self.addCleanup(self.temp.cleanup); self.folder = Path(self.temp.name)
        self.raw = save(self.folder, b'Actual revenue is 4. Management targets 8.', suffix='txt')
        self.source = {'provider': 'synthetic', 'source_url': 'https://newsroom.servicenow.com/financial-results',
                       'upstream_id': 'synthetic', 'raw': self.raw, 'text': self.raw, 'source_version': 'v1'}
        self.ref = save(self.folder, self.source)

    def test_persisted_sidecar_binds_capture_policy_and_document_uncertainty(self):
        ref = labels.annotate_source(self.ref, self.folder / 'labels')
        stored = labels.read_sidecar(ref, source_ref=self.ref)
        self.assertEqual(labels.annotate_source(self.ref, self.folder / 'labels'), ref)
        self.assertEqual(stored['policy_sha256'], digest(stored['policy']))
        self.assertEqual(stored['label']['epistemic_status'], 'mixed')
        self.assertEqual(stored['label']['annotation']['status'], 'provisional')
        self.assertNotIn('verified', json.dumps(stored))
        self.assertEqual(read(self.ref), self.source)

    def test_claim_target_never_becomes_an_actual_from_issuer_origin(self):
        claim_ref = save(self.folder, {'claim': 'Management targets 8'})
        annotation = labels.classify(self.source, self.ref, claim_ref=claim_ref)
        annotation['epistemic_status'] = 'management_target'
        ref = labels.annotate_source(self.ref, self.folder / 'labels', label=annotation)
        self.assertEqual(labels.read_sidecar(ref)['label']['epistemic_status'], 'management_target')

    def test_community_host_does_not_establish_issuer_authorship(self):
        source = {**self.source, 'source_url': 'https://www.servicenow.com/community/a-user-post'}
        label = labels.classify(source, self.ref)
        self.assertEqual(label['publisher_kind'], 'unknown')
        self.assertEqual(label['document_type'], 'discussion')

    def test_tampered_capture_or_policy_cannot_keep_provenance(self):
        ref = labels.annotate_source(self.ref, self.folder / 'labels')
        envelope = read(ref); envelope['policy']['version'] = 'tampered'
        with self.assertRaisesRegex(SourceError, 'LABEL_POLICY_HASH_MISMATCH'):
            labels.read_sidecar(save(self.folder, envelope))
        Path(self.raw['path']).write_text('changed')
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_HASH_MISMATCH'):
            labels.read_sidecar(ref)

    def test_malformed_refs_paths_symlinks_and_unbound_review_fail(self):
        for ref in [None, {'path': '/etc/passwd', 'sha256': 'a' * 64},
                    {'path': str(self.folder / '../../../../../etc/passwd'), 'sha256': 'a' * 64}]:
            with self.subTest(ref=ref), self.assertRaises((SourceError, TypeError)):
                labels.annotate_source(ref, self.folder / 'labels')
        symlink = self.folder / 'linked.json'; symlink.symlink_to(self.ref['path'])
        with self.assertRaisesRegex(SourceError, 'SYMLINK'):
            labels.annotate_source({'path': str(symlink), 'sha256': self.ref['sha256']}, self.folder / 'labels')
        label = labels.classify(self.source, self.ref)
        label['annotation'].update(status='reviewed', review_ref=save(self.folder, {'decision': 'approved'}))
        with self.assertRaisesRegex(SourceError, 'LABEL_REVIEW_BINDING_INVALID'):
            labels.annotate_source(self.ref, self.folder / 'labels', label=label)

    def test_optional_observer_exception_has_no_effect_on_authoritative_result(self):
        result = {'status': 'completed', 'report_ref': self.ref}; before = deepcopy(result)
        def broken(ref): raise RuntimeError('synthetic secret=DO_NOT_EXPOSE')
        observed = labels.best_effort_observe(self.ref, observer=broken)
        self.assertEqual(result, before)
        self.assertEqual(observed, {'status': 'unavailable', 'code': 'OPTIONAL_OBSERVABILITY_FAILED'})
        self.assertNotIn('DO_NOT_EXPOSE', json.dumps(observed))

    def test_report_index_does_not_follow_string_paths_and_respects_maximum(self):
        self.assertEqual(labels.source_refs({'unsafe': '/etc/passwd'}), [])
        self.assertEqual(labels.source_refs({'source_ref': self.ref}, maximum=1), [self.ref])
        report = save(self.folder, {'source_ref': self.ref})
        self.assertEqual(len(labels.observe_report(report, directory=self.folder / 'labels')), 1)


if __name__ == '__main__': unittest.main()
