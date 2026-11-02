from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

from shared.research_sources import source_matrix as m
from shared.research_sources.artifacts import SOURCE_STATE, SourceError, read, save


class SourceMatrixTests(unittest.TestCase):
    def setUp(self):
        directory = SOURCE_STATE / 'tmp'
        directory.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=directory)
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def source(self, case_id, *, text=None, changes=None, retrieved_at=None):
        case = m.CASES[case_id]
        base = {'schema_version': 1, 'provider': case['provider'],
                'source_url': 'https://arxiv.org/html/' + m.PAPER_ID if case_id.startswith('arxiv') and case['capability'] == 'read' else case['target'],
                'retrieved_at': retrieved_at or datetime.now(timezone.utc).isoformat(),
                'access_level': case['expected_access'], 'raw': save(self.directory, b'Synthetic raw response', suffix='txt')}
        if case['expected_access'] == 'metadata':
            base.update(candidates=[{'id': 'https://arxiv.org/abs/2407.08608v2' if case_id.startswith('arxiv') else 'https://openalex.org/W000000001',
                                     'title': 'Synthetic FlashAttention discovery case'}])
        else:
            texts = {
                'arxiv.read': 'Synthetic FlashAttention-3. We use asynchronous GPU pipelining and FP8 GEMM. ',
                'arxiv_mcp_candidate.read': 'Synthetic experiments measure GPU FP8 GEMM performance with asynchronous pipelining. ',
                'official_document.nvidia_release': 'Synthetic NVIDIA First Quarter Fiscal 2025. May 22, 2024. Quarter ended April 28, 2024. ($ in millions, except earnings per share) Q1 FY25 Revenue $26,044. ',
                'official_document.nvidia_blackwell': 'Synthetic Blackwell tuning guide: Tensor operations and memory thread constraints. ',
                'official_document.amd_rocm': 'Synthetic ROCm is an open-source software stack for GPU compute. ',
                'official_document.google_tpu': 'Synthetic Tensor Processing Units. Each TensorCore has a matrix-multiply unit (MXU). ',
                'official_document.mlcommons': 'Synthetic MLPerf Inference: Datacenter. Scenarios & Metrics. Latency and throughput require a quality target. '}
            body = text if text is not None else texts[case_id] * 5
            base.update(text=save(self.directory, body.encode(), suffix='txt'), headings=['Synthetic case heading'])
            if case_id.startswith('arxiv'):
                base.update(upstream_id=m.PAPER_ID, source_version='2', available_at='2024-07-12T00:00:00Z')
            if case_id.startswith('arxiv_mcp'):
                base.update(read_scope='bounded extracted section', metadata={
                    'primary_identity_receipt': save(self.directory, {'upstream_id': m.PAPER_ID})})
        base.update(changes or {})
        return save(self.directory, base)

    def executor(self, case_id, directory, primary_ref=None, *, timeout):
        self.assertGreater(timeout, 0)
        return {'ok': True, 'source_ref': self.source(case_id), 'http_attempts': []}

    def test_metadata_requires_relevant_identifier_and_stays_discovery(self):
        accepted = m.inspect('openalex.discover', self.source('openalex.discover'))
        self.assertEqual(accepted['status'], 'pass')
        self.assertEqual(accepted['access_level'], 'metadata')
        self.assertNotIn('observation', accepted['evidence'])
        for candidates in ([], [{'id': 'https://openalex.org/W1', 'title': 'Completely unrelated paper'}],
                           [{'id': None, 'title': 'FlashAttention'}]):
            result = m.inspect('openalex.discover', self.source('openalex.discover', changes={'candidates': candidates}))
            self.assertEqual(result['status'], 'failed')

    def test_paper_requires_exact_revision_and_substantive_topic(self):
        self.assertEqual(m.inspect('arxiv.read', self.source('arxiv.read'))['status'], 'pass')
        for changes in ({'source_version': '1'}, {'upstream_id': '2407.08608v1'},
                        {'source_url': 'https://arxiv.org/html/2407.08608v1'}, {'access_level': 'metadata'}):
            self.assertEqual(m.inspect('arxiv.read', self.source('arxiv.read', changes=changes))['status'], 'failed')
        unrelated = self.source('arxiv.read', text='Synthetic unrelated navigation. ' * 20)
        self.assertEqual(m.inspect('arxiv.read', unrelated)['status'], 'failed')

    def test_table_of_contents_keywords_do_not_satisfy_document_read_quality(self):
        toc = '\n'.join(['FlashAttention-3', 'Background: GPU characteristics',
                         'Asynchronous pipelining', 'FP8 GEMM', 'Experiments', 'References'] * 12)
        result = m.inspect('arxiv.read', self.source('arxiv.read', text=toc))
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['checks']['substantive_methods_or_results'])
        self.assertIsNone(result['evidence']['passage'])
        toc = '\n'.join(['Blackwell', 'Tensor', 'Thread Block Clusters', 'Memory System'] * 20)
        result = m.inspect('official_document.nvidia_blackwell', self.source('official_document.nvidia_blackwell', text=toc))
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['checks']['substantive_topic_passage'])

    def test_reported_fact_rejects_wrong_period_units_and_value(self):
        correct = read(self.source('official_document.nvidia_release'))
        text = read(correct['text'], json_value=False).decode()
        result = m.inspect('official_document.nvidia_release', self.source('official_document.nvidia_release'))
        self.assertEqual(result['evidence']['observation']['value'], 26044)
        for before, after in [('millions', 'billions'), ('26,044', '26,440'), ('April 28', 'April 29'),
                              ('Fiscal 2025', 'Fiscal 2026'), ('Q1 FY25', 'Q1 FY26')]:
            invalid = m.inspect('official_document.nvidia_release',
                                self.source('official_document.nvidia_release', text=text.replace(before, after)))
            self.assertEqual(invalid['status'], 'failed')
            self.assertNotIn('observation', invalid['evidence'])

    def test_each_technical_family_requires_topic_passage(self):
        for case_id in m.CASES:
            if case_id.startswith('official_document.') and case_id != 'official_document.nvidia_release':
                with self.subTest(case=case_id):
                    self.assertEqual(m.inspect(case_id, self.source(case_id))['status'], 'pass')
                    failed = m.inspect(case_id, self.source(case_id, text='Synthetic index links and navigation. ' * 20))
                    self.assertEqual(failed['status'], 'failed')

    def test_fixed_fact_cache_retains_observation_time_and_rejects_old_future(self):
        now = datetime.now(timezone.utc)
        original = (now - timedelta(seconds=60)).isoformat()
        ref = self.source('official_document.nvidia_release', retrieved_at=original)
        result = m.cached_fixed_fact(ref, now=now.isoformat())
        self.assertEqual(result['status'], 'qualified')
        self.assertEqual(result['original_observed_at'], original)
        for age in (m.FIXED_FACT_CACHE_SECONDS + 1, -1):
            ref = self.source('official_document.nvidia_release', retrieved_at=(now - timedelta(seconds=age)).isoformat())
            with self.assertRaisesRegex(SourceError, 'FIXED_FACT_CACHE_NOT_ELIGIBLE'):
                m.cached_fixed_fact(ref, now=now.isoformat())

    def test_fault_handler_executes_once_after_injection(self):
        calls = []
        value, scenario = m._controlled_fallback('arxiv.read', lambda: calls.append('actual recovery') or 'result')
        self.assertEqual(calls, ['actual recovery'])
        self.assertEqual(value, 'result')
        self.assertTrue(scenario['fault_injected'])
        self.assertFalse(scenario['natural_outage_observed'])
        self.assertEqual(scenario['injected_error'], 'INJECTED_PRIMARY_TRANSPORT_FAILURE')

    def test_full_fixture_matrix_keeps_missing_fallback_and_host_gaps_visible(self):
        result = m.run(self.directory, executor=self.executor)
        report = read(result['report_ref'])
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(len(report['attempts']), m.MAX_OPERATIONS)
        self.assertEqual(len(report['routes']), len(m.CASES) + 2)
        self.assertEqual(report['observability']['automatic_retries'], 0)
        self.assertIsNone(report['observability']['cost'])
        rows = {r['case_id']: r for r in report['routes']}
        self.assertEqual(rows['arxiv.read']['status'], 'pass')
        self.assertEqual(rows['arxiv_mcp_candidate.read']['status'], 'pass')
        self.assertTrue(rows['arxiv.read']['fallback']['same_upstream'])
        self.assertEqual(rows['official_document.nvidia_release']['status'], 'qualified')
        self.assertEqual(rows['official_document.amd_rocm']['status'], 'qualified')
        self.assertEqual(rows['official_document.sec_filing']['status'], 'blocked')
        self.assertEqual(rows['web_search.discover']['status'], 'blocked')
        # Reusing the arXiv discovery call is explicit; it is not invented call volume.
        self.assertEqual(rows['openalex.discover']['fallback']['alternative_attempt_id'], rows['arxiv.discover']['primary_attempt_id'])
        self.assertEqual(read(report['manifest_ref'])['cases'], m.CASES)

    def test_permanent_failure_is_not_retried_and_independent_work_continues(self):
        calls = []

        def unavailable(case_id, directory, primary_ref=None, *, timeout):
            calls.append(case_id)
            if case_id == 'openalex.discover':
                return {'ok': False, 'error': 'SOURCE_HTTP_403', 'http_attempts': [{'status': 'failed'}]}
            return self.executor(case_id, directory, primary_ref, timeout=timeout)

        report = read(m.run(self.directory, executor=unavailable)['report_ref'])
        self.assertEqual(calls.count('openalex.discover'), 1)
        self.assertIn('official_document.mlcommons', calls)
        blocked = [a for a in report['attempts'] if a.get('error') == 'KNOWN_ACCESS_FAILURE_NOT_RETRIED']
        self.assertEqual(len(blocked), 1)
        rows = {r['case_id']: r for r in report['routes']}
        self.assertEqual(rows['openalex.discover']['status'], 'qualified')
        self.assertEqual(rows['openalex.discover']['fallback']['status'], 'pass')

    def test_payload_failure_and_unknown_errors_remain_visible_without_exception_text(self):
        def broken(case_id, directory, primary_ref=None, *, timeout):
            if case_id == 'openalex.discover':
                return {'ok': True, 'source_ref': self.source(case_id, changes={'candidates': []})}
            if case_id == 'official_document.google_tpu':
                raise RuntimeError('synthetic-secret-that-must-not-be-logged')
            return self.executor(case_id, directory, primary_ref, timeout=timeout)

        report = read(m.run(self.directory, executor=broken)['report_ref'])
        self.assertTrue(any(a.get('error') == 'SOURCE_PAYLOAD_COVERAGE_FAILED' for a in report['attempts']))
        self.assertTrue(any(a.get('error') == 'SOURCE_OPERATION_FAILED' for a in report['attempts']))
        self.assertNotIn('synthetic-secret', str(report))

    def test_deadline_stops_io_without_losing_roster(self):
        ticks = iter([0, 500] + [500] * 20)
        calls = []

        def must_not_call(*args, **kwargs):
            calls.append(args)
            raise AssertionError('budget must block I/O')

        report = read(m.run(self.directory, executor=must_not_call, clock=lambda: next(ticks))['report_ref'])
        self.assertFalse(calls)
        self.assertEqual(len(report['routes']), len(m.CASES) + 2)
        self.assertTrue(all(a['error'] == 'SOURCE_MATRIX_BUDGET_EXHAUSTED' for a in report['attempts']))

    def test_single_flight_lock_rejects_concurrent_matrix(self):
        with m._lock():
            with self.assertRaisesRegex(SourceError, 'SOURCE_MATRIX_ALREADY_RUNNING'):
                with m._lock():
                    self.fail('second lock must fail')

    def test_worker_timeout_is_bounded_and_process_group_is_cleaned(self):
        result = m._process([sys.executable, '-c', 'import time; time.sleep(20)'], .05)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'SOURCE_OPERATION_TIMEOUT')
        self.assertEqual(result['cleanup'], 'process_group_killed')


if __name__ == '__main__':
    unittest.main()
