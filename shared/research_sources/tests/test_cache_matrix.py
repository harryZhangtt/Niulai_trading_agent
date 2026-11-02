from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlencode

from shared.research_sources import cache_matrix as m
from shared.research_sources import source_matrix as s
from shared.research_sources.artifacts import SOURCE_STATE, read, save
from shared.research_sources.tests import test_source_matrix as source_fixtures


class CacheMatrixTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.factory = source_fixtures.SourceMatrixTests()
        self.factory.directory = self.directory / 'source-fixtures'
        self.calls = []

    def source(self, case_id):
        source = read(self.factory.source(case_id))
        if source['access_level'] == 'document':
            source.setdefault('upstream_id', s.CASES[case_id]['target'])
            source.setdefault('source_version', None)
            source.setdefault('available_at', source['retrieved_at'])
            source.setdefault('metadata', {})
        elif case_id == 'openalex.discover':
            source['source_url'] = 'https://api.openalex.org/works?' + urlencode({'search': s.CASES[case_id]['target']})
        elif case_id == 'arxiv.discover':
            source['source_url'] = 'https://export.arxiv.org/api/query?' + urlencode({'search_query': s.CASES[case_id]['target']})
        if case_id == 'official_document.nvidia_blackwell':
            # Preserve the real live matrix's failed tensor requirement as a
            # negative eligibility case rather than making every replay pass.
            source['text'] = save(self.directory / 'source-fixtures',
                ('Synthetic Blackwell memory thread constraints. ' * 10).encode(), suffix='txt')
        return save(self.directory / 'source-fixtures', source)

    def executor(self, case_id, directory, primary_ref=None, *, timeout):
        self.calls.append(case_id)
        return {'ok': True, 'source_ref': self.source(case_id),
                'http_attempts': [{'url': s.ISSUER_URL, 'status': 'returned'}]}

    def captures(self):
        return save(self.directory, {'kind': 'bounded_source_runtime_matrix',
            'attempts': [{'case_id': case_id, 'source_ref': self.source(case_id)} for case_id in s.CASES]})

    def workload(self):
        return m.run(self.directory / 'workload', self.captures(), executor=self.executor)

    def test_cold_warm_replay_and_retained_concurrency_postconditions(self):
        result = self.workload()
        report = read(result['report_ref'])
        self.assertEqual(result['status'], 'pass', result['verification'])
        self.assertEqual(self.calls, [m.ISSUER_CASE])
        self.assertTrue(m.verify(result['report_ref'], allow_fixture=True)['verified'])
        incomplete = read(result['report_ref'])
        incomplete['live']['warm']['outcome']['attempt_refs'] = []
        ref = save(Path(result['report_ref']['path']).parent, incomplete)
        verdict = m.verify(ref, allow_fixture=True)
        self.assertEqual(verdict['assessment'], 'incomplete_verification_evidence')
        self.assertFalse(verdict['acquisition_rejected'])
        self.assertEqual(m.verify(result['report_ref'])['reason'], 'FIXTURE_NOT_LIVE_RUNTIME_EVIDENCE')
        self.assertEqual(len(report['replays']), len(s.CASES))
        replay = next(r for r in report['replays'] if r['case_id'] == 'official_document.nvidia_blackwell')
        self.assertEqual(replay['integrity_warm']['outcome']['route'], 'cache_hit')
        self.assertEqual(replay['claim_coverage']['status'], 'failed')
        self.assertIsNone(replay['decision_eligible_warm']['outcome']['source_ref'])
        self.assertEqual(result['verification']['five_process_callbacks'], 1)
        self.assertEqual(result['verification']['five_process_cache_hits'], 4)
        self.assertEqual(result['verification']['hundred_warm_hits'], 100)

    def test_verifier_rejects_mutated_call_count_roster_and_receipt_claim(self):
        result = self.workload()
        report = read(result['report_ref'])
        changes = [
            lambda r: r['live'].update(callback_count_after_warm=2),
            lambda r: r['replays'].pop(),
            lambda r: r['live']['warm']['outcome'].update(route='fetch')]
        for change in changes:
            variant = read(result['report_ref'])
            change(variant)
            ref = save(Path(result['report_ref']['path']).parent, variant)
            self.assertFalse(m.verify(ref, allow_fixture=True)['verified'])
        self.assertTrue(m.verify(result['report_ref'], allow_fixture=True)['verified'])

    def test_independent_verifier_reads_original_bytes_and_actual_counter(self):
        result = self.workload()
        report = read(result['report_ref'])
        counter = Path(report['stress']['five_process']['counter_path'])
        counter.write_text('2')
        verdict = m.verify(result['report_ref'], allow_fixture=True)
        self.assertFalse(verdict['verified'])
        self.assertEqual(verdict['reason'], 'CACHE_SINGLEFLIGHT_COUNTER_INVALID')
        counter.write_text('1')
        source = read(report['live']['cold']['outcome']['source_ref'])
        Path(source['text']['path']).write_bytes(b'Injected corruption of owned fixture')
        verdict = m.verify(result['report_ref'], allow_fixture=True)
        self.assertFalse(verdict['verified'])
        self.assertEqual(verdict['reason'], 'ARTIFACT_HASH_MISMATCH')

    def test_failed_cold_does_not_repeat_provider_and_cannot_pass_with_old_capture(self):
        def failure(case_id, directory, primary_ref=None, *, timeout):
            self.calls.append(case_id)
            return {'ok': False, 'error': 'SOURCE_HTTP_403',
                    'http_attempts': [{'url': s.ISSUER_URL, 'status': 'failed', 'error': 'SOURCE_HTTP_403'}]}

        result = m.run(self.directory / 'workload', self.captures(), executor=failure)
        report = read(result['report_ref'])
        self.assertEqual(self.calls, [m.ISSUER_CASE])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['verification']['reason'], 'LIVE_COLD_NOT_OBSERVED')
        self.assertIsNone(report['live']['warm']['outcome']['source_ref'])


if __name__ == '__main__':
    unittest.main()
