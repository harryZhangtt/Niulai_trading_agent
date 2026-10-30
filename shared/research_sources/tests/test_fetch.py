from contextlib import nullcontext
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError

from shared.research_sources import fetch as f
from shared.research_sources.artifacts import ROOT, SOURCE_STATE, SourceError, read, save


class FetchTests(unittest.TestCase):
    def setUp(self):
        directory = SOURCE_STATE / 'tmp'; directory.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=directory); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def test_url_and_redirect_guards_before_io(self):
        opener = Mock()
        for url in ['http://arxiv.org/x', 'https://127.0.0.1/x', 'file:///etc/passwd',
                    'https://user:secret@arxiv.org/x', 'https://arxiv.org:443/x', 'https://arxiv.org/x#fragment']:
            with self.assertRaises(SourceError): f.get(url, opener=opener)
        opener.open.assert_not_called()
        self.assertIsNone(f.NoRedirect().redirect_request(None, None, None, None, None, None))

    def test_auth_and_redirect_failures_not_retried_or_echoed(self):
        for code in (302, 401, 403, 429):
            opener = Mock(); opener.open.side_effect = HTTPError('url', code, 'synthetic-secret', {}, None)
            with self.assertRaisesRegex(SourceError, '^SOURCE_HTTP_' + str(code) + '$'):
                f.get('https://arxiv.org/x', opener=opener)
            self.assertEqual(opener.open.call_count, 1)

    def test_html_challenge_or_empty_document_is_not_evidence(self):
        for raw in [b'<h1>Just a moment</h1>' + b'x' * 300, b'<p>tiny</p>']:
            with self.assertRaisesRegex(SourceError, 'SOURCE_DOCUMENT_INVALID'):
                f.document_receipt(self.directory, provider='official_document', url='https://docs.nvidia.com/x',
                                   raw=raw, identifier='synthetic')

    def test_unversioned_paper_rejected_before_network(self):
        getter = Mock()
        for value in ['2407.08608', '../escape', '2407.08608v0']:
            with self.assertRaisesRegex(SourceError, 'VERSIONED_ARXIV_ID_REQUIRED'):
                f.fetch_arxiv(value, self.directory, getter=getter, budget=nullcontext)
        getter.assert_not_called()

    def test_revision_availability_and_document_identity(self):
        atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2407.08608v2</id><title>Synthetic</title><published>2024-07-11T00:00:00Z</published><updated>2024-07-12T00:00:00Z</updated></entry></feed>'''
        html = b'<h1>Synthetic 2407.08608v2</h1><p>' + b'document text ' * 60 + b'</p>'
        getter = Mock(side_effect=[(atom, 'application/atom+xml'), (html, 'text/html')])
        ref = f.fetch_arxiv('2407.08608v2', self.directory, getter=getter, budget=nullcontext)
        self.assertEqual(read(ref)['available_at'], '2024-07-12T00:00:00Z')
        self.assertEqual(read(ref)['source_version'], '2')
        self.assertLessEqual(len(f.passages(ref, max_chars=35)['text']), 35)
        with self.assertRaises(SourceError): f.passages(ref, max_chars=12001)

    def test_arxiv_identity_mismatch_rejected(self):
        atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2407.08608v1</id></entry></feed>'
        getter = Mock(return_value=(atom, 'application/atom+xml'))
        with self.assertRaisesRegex(SourceError, 'ARXIV_VERSION_MISMATCH'):
            f.fetch_arxiv('2407.08608v2', self.directory, getter=getter, budget=nullcontext)
        self.assertEqual(getter.call_count, 1)

    def test_output_containment_and_immutable_hashes(self):
        with self.assertRaises(SourceError): save(ROOT / 'niulai-private', {'synthetic': True})
        ref = save(self.directory, {'synthetic': True}); Path(ref['path']).write_text('{}')
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_HASH_MISMATCH'): read(ref)

    def test_mcp_section_requires_matching_primary_version(self):
        primary = save(self.directory, {'provider': 'arxiv', 'upstream_id': '2407.08608v2',
            'source_url': 'https://arxiv.org/html/2407.08608v2', 'source_version': '2',
            'available_at': '2024-07-12T00:00:00Z', 'published_at': '2024-07-12T00:00:00Z',
            'availability_basis': 'provider_publication'})
        content = 'Synthetic bounded methods and limitations section.'
        report = {'queried': True, 'version': '0.8.2', 'process_cleanup_verified': True,
            'section': {'status': 'success', 'versioned_id': '2407.08608v2', 'content': content,
                        'returned_chars': len(content), 'section': {'title': 'Methods'}}}
        ref = f.ingest_mcp_section(save(self.directory, report), primary, self.directory)
        self.assertEqual(f.passages(ref)['text'], content)
        report['section']['versioned_id'] = '2407.08608v1'
        with self.assertRaisesRegex(SourceError, 'MCP_PRIMARY_IDENTITY_MISMATCH'):
            f.ingest_mcp_section(save(self.directory, report), primary, self.directory)
