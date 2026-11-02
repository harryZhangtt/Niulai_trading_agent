import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from shared.research_sources.artifacts import SOURCE_STATE, SourceError, save
from shared.research_sources.runtime_validation import verify


class RuntimeValidationTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)

    def fixture(self, *, cache_started='2026-10-31T03:30:01+00:00', wrong_binding=False):
        receipt = save(self.out, {'retrieved_at': '2026-10-31T03:30:01+00:00'})
        source = save(self.out, {'manifest_ref': save(self.out, {'explicit': 'synthetic'}), 'status': 'partial',
            'observability': {'operation_count': 1, 'max_operations': 11},
            'attempts': [{'status': 'returned', 'case_id': 'official_document.nvidia_release', 'source_ref': receipt}],
            'routes': [{'case_id': 'official_document.nvidia_release', 'status': 'pass'}]})
        cache = save(self.out, {'started_at': cache_started,
            'manifest_ref': save(self.out, {'source_matrix_ref': receipt if wrong_binding else source})})
        return save(self.out, {'kind': 'source_cache_agent_workload', 'source': {'report_ref': source}, 'cache': {'report_ref': cache}})

    @patch('shared.research_sources.cache_matrix.verify', return_value={'verified': True})
    @patch('shared.research_sources.runtime_validation.inspect', return_value={'status': 'pass'})
    def test_rejects_older_cache_and_cross_run_source_binding(self, *_):
        with self.assertRaisesRegex(SourceError, 'RUNTIME_CACHE_NOT_FRESH'):
            verify(self.fixture(cache_started='2026-10-30T03:30:01+00:00'), not_before='2026-10-31T03:30:00+00:00')
        with self.assertRaisesRegex(SourceError, 'RUNTIME_CACHE_SOURCE_BINDING'):
            verify(self.fixture(wrong_binding=True), not_before='2026-10-31T03:30:00+00:00')

    @patch('shared.research_sources.cache_matrix.verify', return_value={'verified': False})
    @patch('shared.research_sources.runtime_validation.inspect', return_value={'status': 'pass'})
    def test_cache_failure_and_partial_source_coverage_stay_visible(self, *_):
        result = verify(self.fixture(), not_before='2026-10-31T03:30:00+00:00')
        self.assertFalse(result['verified'])
        self.assertEqual(result['source_coverage_status'], 'partial')
        self.assertEqual(result['distinct_usable_cases'], ['official_document.nvidia_release'])


if __name__ == '__main__': unittest.main()
