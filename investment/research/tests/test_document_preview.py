import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared.research_sources.artifacts import INVESTMENT_STATE, SourceError, read, save
from investment.research import datasource as ds, document_preview as preview


class DocumentPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=INVESTMENT_STATE, prefix='test-document-preview-')
        self.addCleanup(self.temp.cleanup); self.folder = Path(self.temp.name)
        self.reports = self.folder / 'reports'; self.reports.mkdir()
        self.path = self.reports / 'Synthetic_Research_Checkpoint.json'
        raw = json.dumps({'company': 'TST', 'business_model': {'subscription_revenue': 'Synthetic research content'},
            'api_key': 'PRIVATE_CANARY_123', 'nested': {'private_key': 'PRIVATE_KEY_CANARY', 'account_number': 123456789},
            'notes': '/Users/private/research.json', 'markup': '<img src=x onerror=alert(1)>'}).encode()
        self.path.write_bytes(raw)
        self.row = {'entity': 'TST', 'kind': 'catalog_metadata', 'record_id': 'artifacts:synthetic',
            'title': self.path.name, 'content_access': 'metadata_only', 'available_at': None,
            'content': {'catalog_record': {'local_working_copy': {'path': str(self.path),
                'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}, 'status': 'published'}}}
        self.roster_ref = save(self.folder, {'records': [self.row]})

    def test_real_json_body_is_frozen_bounded_and_redacted_without_changing_original(self):
        original = self.path.read_bytes()
        ref = preview.freeze(self.roster_ref, self.row, directory=self.folder / 'previews', allowed_roots=(self.reports,))
        with patch.object(preview, 'DIRECTORY', self.folder / 'previews'):
            result = ds.catalog_dto(self.row, self.roster_ref, ds.Reader())
        body = result['local_preview']; payload = json.dumps(result)
        self.assertEqual(body['status'], 'available')
        self.assertIn('Synthetic research content', body['text'])
        self.assertIn('[redacted]', body['text'])
        for value in ['PRIVATE_CANARY_123', 'PRIVATE_KEY_CANARY', '123456789', '/Users/', str(self.folder)]:
            self.assertNotIn(value, payload)
        self.assertEqual(body['preview_sha256'], ref['sha256'])
        self.assertIsNone(result['timestamps']['available_at'])
        self.assertEqual(result['temporal']['status'], 'unknown')
        self.assertFalse(body['canonical_byte_identity_verified'])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertLessEqual(len(body['text']), preview.MAX_PREVIEW_CHARS + 64)

    def test_missing_body_shows_actual_catalog_json_instead_of_empty_success(self):
        self.path.unlink()
        ref = preview.freeze(self.roster_ref, self.row, directory=self.folder / 'previews', allowed_roots=(self.reports,))
        body = preview.public_preview(read(ref), preview_sha256=ref['sha256'])
        self.assertEqual(body['status'], 'missing')
        self.assertIn('catalog_record', body['text'])
        self.assertEqual(body['content_scope'], 'catalog_metadata_not_document_body')
        self.assertIsNone(body['document_sha256'])
        self.assertTrue(body['reason_codes'])

    def test_path_escape_and_final_or_parent_symlinks_are_not_read(self):
        with self.assertRaisesRegex(SourceError, 'DOCUMENT_PREVIEW_PATH_NOT_ALLOWED'):
            preview.read_local_json('/tmp/arbitrary.json', allowed_roots=(self.reports,))
        link = self.reports / 'Link.json'; link.symlink_to(self.path)
        with self.assertRaises(SourceError): preview.read_local_json(str(link), allowed_roots=(self.reports,))
        directory_link = self.reports / 'linked'; directory_link.symlink_to(self.reports, target_is_directory=True)
        with self.assertRaises(SourceError): preview.read_local_json(str(directory_link / self.path.name), allowed_roots=(self.reports,))
        with self.assertRaises(SourceError): preview.read_local_json(str(self.reports / '..' / self.path.name), allowed_roots=(self.reports,))

    def test_hash_mismatch_and_oversized_or_truncated_content_are_explicit(self):
        self.path.write_text('{"different":"PRIVATE_CANARY_123"}')
        ref = preview.freeze(self.roster_ref, self.row, directory=self.folder / 'previews', allowed_roots=(self.reports,))
        body = preview.public_preview(read(ref))
        self.assertEqual(body['status'], 'missing')
        self.assertEqual(body['reason_codes'], ['DOCUMENT_PREVIEW_SOURCE_HASH_MISMATCH'])
        self.assertNotIn('PRIVATE_CANARY_123', body['text'])
        self.path.write_bytes(b'x' * (preview.MAX_FILE_BYTES + 1))
        with self.assertRaisesRegex(SourceError, 'DOCUMENT_PREVIEW_FILE_SIZE_INVALID'):
            preview.read_local_json(str(self.path), allowed_roots=(self.reports,))
        value = preview.metadata_preview(self.roster_ref, self.row)
        value['content'] = {'large': ['Synthetic paragraph ' * 300] * 100}
        body = preview.public_preview(value)
        self.assertTrue(body['truncated'])
        self.assertLessEqual(len(body['text']), preview.MAX_PREVIEW_CHARS + 64)


if __name__ == '__main__': unittest.main()
