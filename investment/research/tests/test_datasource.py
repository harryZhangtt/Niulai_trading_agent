from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared.research_sources.artifacts import INVESTMENT_STATE, SourceError, save
from investment.research import datasource as ds
from investment.research.information_labels import annotate_source, classify


class DatasourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=INVESTMENT_STATE, prefix='test-datasource-')
        self.addCleanup(self.temp.cleanup); self.folder = Path(self.temp.name)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        for name, value in [('CATALOG', self.folder / 'no-catalog'), ('NOW', self.folder / 'no-now'),
                            ('INVESTMENT_STATE', self.folder / 'no-audit'), ('REGISTRY', self.folder / 'no-registry'),
                            ('LABEL_DIRECTORY', self.folder / 'labels')]:
            self.stack.enter_context(patch.object(ds, name, value))
        raw = save(self.folder, b'Synthetic capture; no current investment claim.', suffix='txt')
        self.source = save(self.folder, {'provider': 'synthetic', 'source_url': 'https://example.com/report?api_key=SYNTHETIC_SECRET',
            'upstream_id': 'synthetic', 'source_version': '1', 'raw': raw, 'text': raw,
            'title': 'Study /Users/synthetic/private.txt secret=SYNTHETIC_SECRET', 'retrieved_at': '2026-10-31T01:00:00Z',
            'available_at': None, 'published_at': None, 'access_level': 'document', 'private_account': 'NEVER_RETURN'})
        config = save(self.folder, {'phases': [{'id': 'read', 'mode': 'agent', 'objective': 'PROMPT_SHOULD_NOT_APPEAR'}], 'private': 'NEVER_RETURN'})
        self.report = save(self.folder, {'schema_version': 1, 'run_id': 'example-run', 'pipeline_id': 'synthetic', 'pipeline_version': '1.0.0',
            'completion_scope': 'synthetic_test', 'input_manifest': {'config_ref': config}, 'status': 'completed',
            'started_at': '2026-10-31T01:00:00+00:00', 'finished_at': '2026-10-31T01:00:01+00:00',
            'phases': {'read': {'raw_prompt': 'PROMPT_SHOULD_NOT_APPEAR'}}, 'counts': {'actions': 0, 'model_turns': 1}, 'source_ref': self.source})
        self.registry = save(self.folder, {'schema_version': 1, 'source_refs': [{'source_ref': self.source, 'subject': 'TST'}],
            'report_refs': [{'subject': 'TST', 'report_ref': self.report, 'query': 'TST test@example.com token=SYNTHETIC_SECRET',
                             'source_sha256s': [self.source['sha256'], self.source['sha256']]}]})

    def project(self, **kwargs):
        return ds.snapshot(subject='TST', registry_ref=self.registry, **kwargs)

    def batch_manifest(self):
        config = save(self.folder, {'schema_version': 1, 'batch_id': 'synthetic-batch',
            'query': 'TST source acquisition secret=SYNTHETIC_SECRET /Users/private/data',
            'requirements': [{'id': rid, 'subject': 'TST', 'access': 'document',
                'routes': [{'capability': 'official_document.read', 'parameters': {'url': 'https://example.com/public'}}],
                'max_attempts': 1, 'cache_max_age_seconds': 600, 'timeout_seconds': 10} for rid in ['available', 'missing']],
            'budget': {'deadline_seconds': 30, 'max_workers': 2, 'max_provider_calls': 4},
            'raw_prompt': 'NEVER_RETURN'})
        attempts = []
        results = []
        for ordinal, rid in enumerate(['available', 'missing']):
            available = rid == 'available'
            attempt = save(self.folder, {'kind': 'acquisition_attempt', 'execution_id': 'batch-execution',
                'requirement_id': rid, 'ordinal': 1, 'capability': 'official_document.read', 'fetch_key_sha256': 'f' * 64,
                'status': 'available' if available else 'unavailable', 'route': 'cache_hit' if available else 'unresolved',
                'source_ref': self.source if available else None, 'fetch_executed': not available, 'cache_hit': available,
                'reasons': [], 'started_at': '2026-11-01T01:00:00Z', 'finished_at': '2026-11-01T01:00:01Z',
                'action_execution_ref': None, 'private': 'NEVER_RETURN'})
            attempts.append(attempt)
            results.append(save(self.folder, {'kind': 'acquisition_requirement_result', 'execution_id': 'batch-execution',
                'requirement_id': rid, 'subject': 'TST', 'status': 'available' if available else 'unavailable',
                'selected_source_ref': self.source if available else None, 'attempt_refs': [attempt],
                'route': 'official_document.read' if available else None, 'cache_hit': available, 'reasons': [], 'elapsed_seconds': 1}))
        manifest = {'kind': 'acquisition_batch', 'schema_version': 1, 'version': '1.0.0',
            'execution_id': 'batch-execution', 'batch_id': 'synthetic-batch', 'subjects': ['TST'],
            'query': json.loads(Path(config['path']).read_text())['query'], 'config_ref': config, 'config_sha256': config['sha256'],
            'capability_catalog_sha256': 'c' * 64, 'script_versions': [{'id': 'shared.research_sources.batch', 'sha256': 'd' * 64}],
            'status': 'partial', 'started_at': '2026-11-01T01:00:00Z', 'finished_at': '2026-11-01T01:00:01Z',
            'requirement_result_refs': results, 'source_refs': [self.source], 'observation_refs': [],
            'counts': {'requirements': 2, 'fulfilled': 1, 'unavailable': 1, 'unknown': 0, 'provider_calls': 1, 'cache_hits': 1, 'fallbacks': 0, 'retries': 0},
            'elapsed_seconds': 1, 'counting_unit': 'adapter_dispatch', 'http_requests': None,
            'retention': {'snapshots': 'retain_until_explicit_gc', 'cache_is_disposable_index': True},
            'scope': 'acquisition_only_not_semantic_admission', 'private': 'NEVER_RETURN'}
        return manifest, results, attempts

    def batch_registry(self, ref):
        registry = json.loads(Path(self.registry['path']).read_text())
        registry['batch_refs'] = [{'batch_ref': ref, 'subject': 'TST'}]
        return save(self.folder, registry)

    def test_acquisition_execution_projection_keeps_cache_retention_and_pipeline_identities_separate(self):
        manifest, _, _ = self.batch_manifest(); ref = save(self.folder, manifest)
        registry = self.batch_registry(ref)
        before = {p: p.stat().st_mtime_ns for p in self.folder.rglob('*') if p.is_file()}
        value = ds.snapshot(subject='TST', registry_ref=registry)
        self.assertEqual(value['pagination']['total_batches'], 1)
        self.assertEqual(len(value['runs']), 1)
        batch = value['batches'][0]
        self.assertEqual(batch['execution_id'], 'batch-execution')
        self.assertEqual(batch['manifest_sha256'], ref['sha256'])
        self.assertEqual(batch['status'], 'partial')
        self.assertEqual(batch['metrics']['fulfilled'], 1)
        self.assertEqual(batch['counting_unit'], 'adapter_dispatch')
        self.assertIsNone(batch['http_requests'])
        self.assertTrue(batch['requirements'][0]['cache_hit'])
        self.assertFalse(batch['requirements'][0]['attempts'][0]['fetch_executed'])
        self.assertEqual(batch['requirements'][1]['status'], 'unavailable')
        self.assertEqual(batch['retention']['attempt_receipts'], 2)
        self.assertEqual(batch['retention']['source_receipts'], 1)
        self.assertEqual(value['aggregates']['retention_counts']['manifest_receipts'], 1)
        self.assertEqual(batch['sources'][0]['id'], value['sources'][0]['id'])
        self.assertEqual(batch['sources'][0]['batch_ids'], [batch['id']])
        self.assertEqual(len(value['sources'][0]['run_ids']), 1)
        self.assertEqual(batch['sources'][0]['labels']['annotation_status'], 'provisional')
        cohort = next(row for row in value['aggregates']['cohorts'] if row['id'].startswith('acquisition_batches:'))
        self.assertEqual(cohort['metrics']['cost']['unknown'], 1)
        for secret in ['NEVER_RETURN', 'SYNTHETIC_SECRET', '/Users/', str(self.folder)]: self.assertNotIn(secret, json.dumps(value))
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in self.folder.rglob('*') if p.is_file()})

    def test_batch_bindings_and_missing_receipts_fail_closed_without_hiding_other_runs(self):
        manifest, results, attempts = self.batch_manifest()
        wrong_result = {**json.loads(Path(results[0]['path']).read_text()), 'execution_id': 'different-execution'}
        wrong = {**manifest, 'requirement_result_refs': [save(self.folder, wrong_result), results[1]]}
        with self.assertRaisesRegex(SourceError, 'PROJECTION_BATCH_RESULT_BINDING_INVALID'):
            ds.batch_dto(ds.Reader(), save(self.folder, wrong), subject='TST')
        with self.assertRaisesRegex(SourceError, 'PROJECTION_BATCH_CONFIG_BINDING_INVALID'):
            ds.batch_dto(ds.Reader(), save(self.folder, {**manifest, 'config_sha256': 'a' * 64}), subject='TST')
        missing = {**manifest, 'source_refs': []}
        with self.assertRaisesRegex(SourceError, 'PROJECTION_BATCH_SELECTED_SOURCE_INVALID'):
            ds.batch_dto(ds.Reader(), save(self.folder, missing), subject='TST')
        ref = save(self.folder, manifest); registry = self.batch_registry(ref)
        Path(attempts[0]['path']).unlink()
        value = ds.snapshot(subject='TST', registry_ref=registry)
        self.assertEqual(value['batches'], [])
        self.assertEqual(len(value['runs']), 1)
        self.assertEqual(value['aggregates']['batch_counts']['unavailable_batches'], 1)
        self.assertIn('BATCH_UNAVAILABLE', [warning['code'] for warning in value['warnings']])
        self.assertEqual(value['status'], 'partial')

    def test_batch_ref_is_not_a_pipeline_or_cross_subject_association(self):
        value = ds.snapshot(subject='TST', registry_ref=self.batch_registry(self.report))
        self.assertEqual(value['batches'], [])
        self.assertEqual(len(value['runs']), 1)
        manifest, _, _ = self.batch_manifest()
        with self.assertRaisesRegex(SourceError, 'PROJECTION_BATCH_SUBJECT_INVALID'):
            ds.batch_dto(ds.Reader(), save(self.folder, manifest), subject='OTHER')

    def test_duplicate_batch_refs_do_not_invent_failures_but_conflicting_terminals_are_unavailable(self):
        manifest, _, _ = self.batch_manifest(); ref = save(self.folder, manifest)
        registry = json.loads(Path(self.batch_registry(ref)['path']).read_text())
        registry['batch_refs'] *= 2
        value = ds.snapshot(subject='TST', registry_ref=save(self.folder, registry))
        self.assertEqual(value['aggregates']['batch_counts']['registered'], 1)
        self.assertEqual(value['aggregates']['batch_counts']['unavailable_batches'], 0)
        changed = save(self.folder, {**manifest, 'finished_at': '2026-11-01T01:00:02Z'})
        registry['batch_refs'] = [{'batch_ref': ref, 'subject': 'TST'}, {'batch_ref': changed, 'subject': 'TST'}]
        value = ds.snapshot(subject='TST', registry_ref=save(self.folder, registry))
        self.assertEqual(value['batches'], [])
        self.assertEqual(value['aggregates']['batch_counts']['unavailable_batches'], 2)
        self.assertTrue(all(not source.get('batch_ids') for source in value['sources']))
        self.assertIn('BATCH_EXECUTION_CONFLICT', [warning['code'] for warning in value['warnings']])

    def test_actual_batch_writer_cold_and_warm_contract_projects_without_reclassifying_acquisition(self):
        from shared.research_sources.batch import run_batch
        public_url = 'https://nvidianews.nvidia.com/news/synthetic-projection-test'
        raw = save(self.folder, b'Synthetic public batch contract fixture.', suffix='txt')
        source = save(self.folder, {'schema_version': 1, 'provider': 'official_document', 'source_url': public_url,
            'upstream_id': public_url, 'source_version': None, 'access_level': 'document', 'raw': raw, 'text': raw,
            'retrieved_at': '2026-11-01T01:00:00Z', 'available_at': '2026-11-01T01:00:00Z',
            'published_at': '2025-01-01', 'availability_basis': 'first_observed'})
        config = {'schema_version': 1, 'batch_id': 'writer-contract', 'query': 'TST local acquisition contract.',
            'requirements': [{'id': 'issuer', 'subject': 'TST', 'access': 'document',
                'routes': [{'capability': 'official_document.read', 'parameters': {'url': public_url}}],
                'max_attempts': 1, 'cache_max_age_seconds': 3600, 'timeout_seconds': 5}],
            'budget': {'deadline_seconds': 10, 'max_workers': 1, 'max_provider_calls': 2}}
        calls = []
        def fixture_fetch(*args): calls.append(1); return source
        results = [run_batch(config, state_directory=self.folder / 'batch-executions',
            cache_directory=self.folder / 'batch-cache', fetcher=fixture_fetch) for _ in range(2)]
        projected = [ds.batch_dto(ds.Reader(), result['report_ref'], subject='TST')[0] for result in results]
        self.assertEqual(len(calls), 1)
        self.assertEqual([row['metrics']['provider_calls'] for row in projected], [1, 0])
        self.assertEqual(projected[1]['metrics']['cache_hits'], 1)
        self.assertEqual(projected[1]['requirements'][0]['attempts'][0]['route'], 'cache_hit')
        self.assertEqual(projected[0]['scope'], 'acquisition_only_not_semantic_admission')
        self.assertNotEqual(projected[0]['execution_id'], projected[1]['execution_id'])

    def test_public_dto_is_read_only_sanitized_and_preserves_unknowns(self):
        before = {p: p.stat().st_mtime_ns for p in self.folder.rglob('*') if p.is_file()}
        value = self.project(); payload = json.dumps(value)
        for secret in ['SYNTHETIC_SECRET', 'NEVER_RETURN', 'PROMPT_SHOULD_NOT_APPEAR', '/Users/', 'test@example.com', str(self.folder)]:
            self.assertNotIn(secret, payload)
        after = {p: p.stat().st_mtime_ns for p in self.folder.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(value['pagination']['total_sources'], 1)
        self.assertIsNone(value['sources'][0]['url'])
        self.assertEqual(value['sources'][0]['temporal']['status'], 'not_evaluated')
        self.assertEqual(len(value['runs'][0]['source_ids']), 1)
        self.assertEqual(value['runs'][0]['metrics']['elapsed_seconds'], 1)
        self.assertIsNone(value['runs'][0]['metrics']['tokens'])
        metric = value['aggregates']['cohorts'][0]['metrics']['tokens']
        self.assertEqual((metric['known'], metric['unknown'], metric['denominator']), (0, 1, 1))
        self.assertIsNone(metric['sum']); self.assertIsNone(metric['mean'])

    def test_persisted_labels_are_used_only_after_capture_validation(self):
        annotate_source(self.source, self.folder / 'labels')
        value = self.project()
        self.assertEqual(value['sources'][0]['labels']['persistence'], 'immutable_sidecar')
        self.assertEqual(value['aggregates']['source_counts']['persisted_labels'], 1)

    def test_claim_estimate_does_not_relabel_the_whole_document(self):
        annotate_source(self.source, self.folder / 'labels')
        claim_ref = save(self.folder, {'claim': 'A management target'})
        source = json.loads(Path(self.source['path']).read_text())
        label = classify(source, self.source, claim_ref=claim_ref)
        label['epistemic_status'] = 'management_target'
        annotate_source(self.source, self.folder / 'labels', label=label)
        value = self.project()
        self.assertEqual(value['sources'][0]['labels']['scope'], 'document')
        self.assertNotEqual(value['sources'][0]['labels']['epistemic_status'], 'management_target')

    def test_snapshot_pagination_and_changed_snapshot_rejection(self):
        value = self.project(limit=1)
        again = self.project(limit=1, snapshot_id=value['snapshot_id'])
        self.assertEqual(value['snapshot_id'], again['snapshot_id'])
        self.assertEqual(self.project(offset=1)['sources'], [])
        with self.assertRaisesRegex(SourceError, 'PROJECTION_SNAPSHOT_CHANGED'):
            self.project(snapshot_id='a' * 64)
        for subject in ['../private', 'TST?password=secret']:
            with self.assertRaises(SourceError): ds.snapshot(subject=subject)

    def test_malformed_ref_cannot_open_arbitrary_or_symlinked_files(self):
        registry = save(self.folder, {'source_refs': [{'path': '/etc/passwd', 'sha256': 'a' * 64}]})
        value = ds.snapshot(subject='TST', registry_ref=registry)
        self.assertEqual(value['sources'], [])
        self.assertIn('SOURCE_RECEIPT_UNAVAILABLE', [x['code'] for x in value['warnings']])
        self.assertNotIn('/etc/passwd', json.dumps(value))
        link = self.folder / 'linked.json'; link.symlink_to(self.source['path'])
        registry = save(self.folder, {'source_refs': [{'path': str(link), 'sha256': self.source['sha256']}]})
        self.assertEqual(ds.snapshot(subject='TST', registry_ref=registry)['sources'], [])

    def test_read_budget_and_changed_mutable_head_are_explicit_failures(self):
        reader = ds.Reader(); reader.file(self.registry['path'])
        Path(self.registry['path']).write_text('{}')
        with self.assertRaisesRegex(SourceError, 'PROJECTION_SNAPSHOT_CHANGED'): reader.coherent()
        with patch.object(ds, 'MAX_READS', 0), self.assertRaisesRegex(SourceError, 'PROJECTION_READ_BUDGET'):
            ds.Reader().ref(self.source)

    def test_temporal_receipts_are_required_and_diagnostic_fields_are_allowlisted(self):
        diagnostic = save(self.folder, {'view': 'reviewer_diagnostic', 'sources': [{
            'source_sha256': self.source['sha256'], 'cutoff': '2025-01-01T00:00:00Z', 'status': 'blocked',
            'reason_codes': ['OBSERVED_AFTER_CUTOFF'], 'worker_visible': False, 'basis': 'observed_capture',
            'source_ref': self.source, 'private': 'NEVER_RETURN'}]})
        registry = save(self.folder, {**json.loads(Path(self.registry['path']).read_text()), 'temporal_diagnostic_refs': [diagnostic]})
        value = ds.snapshot(subject='TST', registry_ref=registry)
        self.assertEqual(value['sources'][0]['temporal']['status'], 'blocked')
        self.assertFalse(value['sources'][0]['temporal']['worker_visible'])
        self.assertNotIn('NEVER_RETURN', json.dumps(value))

    def test_recognized_query_output_is_hash_bound_bounded_and_allowlisted(self):
        catalog = save(self.folder, {'proposal': {'questions': [{'id': 'economics', 'facet': 'unit_economics',
            'question': 'What source resolves the remaining economics question?', 'priority': 'required',
            'private_prompt': 'NEVER_RETURN'}]}, 'private_prompt': 'NEVER_RETURN'})
        quote = 'Public quoted statement secret=SYNTHETIC_SECRET /Users/private/x'
        observation = save(self.folder, {'kind': 'datasource_query_observation', 'source_ref': self.source,
            'observation': {'source_id': self.source['sha256'], 'quote': quote, 'claim': quote,
                'epistemic_status': 'unknown', 'topics': ['business.model'], 'private_prompt': 'NEVER_RETURN'}})
        final = {'kind': 'datasource_query_snapshot', 'execution_id': 'example-run', 'catalog_ref': catalog,
            'observation_refs': [observation], 'source_refs': [self.source], 'raw_prompt': 'NEVER_RETURN'}
        report = {**json.loads(Path(self.report['path']).read_text()), 'final_ref': save(self.folder, final)}
        output = ds.query_output(ds.Reader(), report)
        self.assertEqual(output['catalog_sha256'], catalog['sha256'])
        self.assertEqual(output['questions'][0]['priority'], 'required')
        self.assertEqual(output['observations'][0]['source_sha256'], self.source['sha256'])
        self.assertEqual(output['annotation_status'], 'provisional')
        self.assertEqual(output['scope'], 'not_semantic_admission')
        for value in ['NEVER_RETURN', 'SYNTHETIC_SECRET', '/Users/', str(self.folder)]: self.assertNotIn(value, json.dumps(output))
        projected = ds.pipeline_dto(ds.Reader(), save(self.folder, report), subject='TST')
        self.assertEqual(projected['output'], output)
        wrong = {**report, 'final_ref': save(self.folder, {**final, 'execution_id': 'another-run'})}
        with self.assertRaisesRegex(SourceError, 'PROJECTION_QUERY_OUTPUT_RUN_MISMATCH'):
            ds.query_output(ds.Reader(), wrong)
        oversized = save(self.folder, {'proposal': {'questions': [{'priority': 'required', 'question': 'Synthetic'}] * 7}})
        with self.assertRaisesRegex(SourceError, 'PROJECTION_QUERY_QUESTION_LIMIT'):
            ds.query_output(ds.Reader(), {**report, 'final_ref': save(self.folder, {**final, 'catalog_ref': oversized})})
        generic = {**report, 'final_ref': save(self.folder, {'kind': 'generic', 'raw_prompt': 'NEVER_RETURN'})}
        self.assertIsNone(ds.query_output(ds.Reader(), generic))

    def test_two_cutoffs_do_not_retroactively_guard_an_old_run(self):
        def diagnostic(cutoff, status):
            return save(self.folder, {'schema_version': 1, 'guard_version': 'synthetic',
                'view': 'reviewer_diagnostic', 'cutoff': cutoff, 'sources': [{
                'source_sha256': self.source['sha256'], 'source_ref': self.source,
                'cutoff': cutoff, 'status': status, 'worker_visible': status == 'eligible',
                'reason_codes': ['SYNTHETIC_DECISION'], 'basis': 'synthetic_test'}]})
        old = diagnostic('2025-01-01T00:00:00Z', 'blocked')
        current = diagnostic('2026-11-01T00:00:00Z', 'eligible')
        final = save(self.folder, {'execution_id': 'new-guarded-run',
            'source_refs': [self.source], 'temporal_diagnostic_ref': current})
        report = save(self.folder, {**json.loads(Path(self.report['path']).read_text()),
            'run_id': 'new-guarded-run', 'final_ref': final})
        registry = json.loads(Path(self.registry['path']).read_text())
        registry['temporal_diagnostic_refs'] = [old, current]
        registry['report_refs'].append({'report_ref': report, 'subject': 'TST',
            'source_sha256s': [self.source['sha256']], 'temporal_diagnostic_ref': current})
        value = ds.snapshot(subject='TST', registry_ref=save(self.folder, registry))
        source = value['sources'][0]
        self.assertEqual([row['status'] for row in source['temporal_checks']], ['blocked', 'eligible'])
        self.assertEqual(source['temporal']['semantics'], 'source_version_at_displayed_cutoff')
        self.assertEqual(source['temporal']['cutoff'], '2026-11-01T00:00:00Z')
        older = next(row for row in value['runs'] if row['execution_id'] == 'example-run')
        self.assertEqual(older['temporal']['status'], 'not_evaluated')
        self.assertEqual(older['temporal']['source_decisions'], [])
        newer = next(row for row in value['runs'] if row['execution_id'] == 'new-guarded-run')
        self.assertEqual(newer['temporal']['status'], 'guarded')
        self.assertEqual(newer['temporal']['execution_id'], 'new-guarded-run')
        self.assertEqual(newer['temporal']['report_sha256'], report['sha256'])
        self.assertEqual(newer['temporal']['diagnostic_sha256'], current['sha256'])
        self.assertEqual(newer['temporal']['source_decisions'][0]['source_sha256'], self.source['sha256'])
        self.assertEqual(newer['temporal']['source_decisions'][0]['status'], 'eligible')
        # A registry pointer by itself cannot retrofit the unguarded old report.
        registry['report_refs'][0]['temporal_diagnostic_ref'] = current
        again = ds.snapshot(subject='TST', registry_ref=save(self.folder, registry))
        older = next(row for row in again['runs'] if row['execution_id'] == 'example-run')
        self.assertEqual(older['temporal']['status'], 'unverified')
        self.assertEqual(older['temporal']['source_decisions'], [])

    def test_wrong_run_or_diagnostic_binding_cannot_claim_a_guarded_run(self):
        diagnostic = save(self.folder, {'view': 'reviewer_diagnostic', 'cutoff': '2026-11-01T00:00:00Z',
            'sources': [{'source_ref': self.source, 'source_sha256': self.source['sha256'],
                         'status': 'eligible', 'worker_visible': True}]})
        for final in [{'execution_id': 'another-run', 'temporal_diagnostic_ref': diagnostic, 'source_refs': [self.source]},
                      {'execution_id': 'example-run', 'temporal_diagnostic_ref': self.source, 'source_refs': [self.source]}]:
            report = save(self.folder, {**json.loads(Path(self.report['path']).read_text()), 'final_ref': save(self.folder, final)})
            with self.assertRaisesRegex(SourceError, 'PROJECTION_RUN_TEMPORAL_BINDING_MISMATCH'):
                ds.run_temporal(ds.Reader(), report, diagnostic, [self.source['sha256']])

    def test_narrative_diff_reads_only_public_bound_proposal_fields(self):
        proposal = save(self.folder, {'entity': 'NOW', 'case_id': 'case_0',
            'incremental_contribution': {'explanation': 'Incremental secret=SYNTHETIC_SECRET /Users/private/x'},
            'economic_inference': 'A meter may lead to paid adoption.',
            'unproved_links': ['Incremental purchase is unverified.'], 'raw_prompt': 'NEVER_RETURN'})
        case = save(self.folder, {'case_id': 'case_0', 'proposal_ref': proposal})
        output = save(self.folder, {'case_result_ref': case})
        summary = ds.proposal_summary(ds.Reader(), output, 'case_0')
        self.assertEqual(summary['economic_inference'], 'A meter may lead to paid adoption.')
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(summary))
        self.assertNotIn('/Users/', json.dumps(summary))
        self.assertNotIn('NEVER_RETURN', json.dumps(summary))
        with self.assertRaisesRegex(SourceError, 'PROJECTION_SUMMARY_CASE_MISMATCH'):
            ds.proposal_summary(ds.Reader(), output, 'wrong_case')

    def test_active_preparing_audit_does_not_break_completed_projection(self):
        audit_folder = self.folder / 'no-audit/executions/active'
        audit_folder.mkdir(parents=True)
        state = save(self.folder, {'status': 'preparing', 'result': None, 'query': 'TST currently running'})
        (audit_folder / 'latest.json').write_text(json.dumps(state))
        value = self.project()
        self.assertEqual(len(value['runs']), 1)
        self.assertEqual(value['runs'][0]['status'], 'completed')

    def test_original_failure_and_repaired_eight_case_comparison_stay_separate(self):
        original = save(self.folder, {'status': 'failed', 'cases': [], 'errors': ['REVIEW_BINDING'], 'usage': {'model_turns': 8}})
        repaired = save(self.folder, {'status': 'passed', 'cases': [{'id': 'case_' + str(i), 'passed': True,
            'metrics': {'supported_facts': i, 'cost': None}} for i in range(8)]})
        original_record = self.folder / 'original.json'; original_record.write_text(json.dumps({'host_results': {'A': original, 'B': original}}))
        repair_record = self.folder / 'repair.json'; repair_record.write_text(json.dumps({'results': {'A': repaired, 'B': repaired}}))
        a, _ = ds.comparison_dto(ds.Reader(), original_record, name='original', scope='failed_grader')
        b, cohorts = ds.comparison_dto(ds.Reader(), repair_record, name='repair', scope='captured_only')
        self.assertEqual(a['status'], 'failed'); self.assertEqual(a['rows'], [])
        self.assertEqual(len(b['rows']), 8); self.assertFalse(b['superiority_established'])
        self.assertEqual(cohorts[0]['metrics']['cost']['unknown'], 8)
        self.assertEqual(b['rows'][0]['differences']['supported_facts'], 0)
        self.assertIsNone(b['rows'][0]['differences']['cost'])

    def test_review_pass_does_not_hide_exact_bound_pipeline_block_or_order_disagreement(self):
        cid = 'synthetic_case'
        proposal = {'entity': 'NOW', 'case_id': cid, 'incremental_contribution': {'explanation': 'Synthetic refinement.'},
                    'economic_inference': 'Synthetic conditional inference.', 'unproved_links': []}
        proposal_ref = save(self.folder, proposal); packet = {'case_id': cid, 'entity': 'NOW', 'evidence': []}
        packet_ref = save(self.folder, packet); request_ref = save(self.folder, {'packet': packet})
        cases = {}; submissions = {}
        for arm in ['A', 'B']:
            status = 'blocked' if arm == 'A' else 'completed'
            report = {**json.loads(Path(self.report['path']).read_text()), 'run_id': 'synthetic-' + arm,
                'status': status, 'reason': 'SYNTHETIC_HOST_BLOCK' if arm == 'A' else None,
                'input_manifest': {**json.loads(Path(self.report['path']).read_text())['input_manifest'], 'request_ref': request_ref},
                'phases': {'contribution': {'data': proposal}}}
            case_ref = save(self.folder, {'case_id': cid, 'status': status, 'packet_ref': packet_ref,
                'proposal_ref': proposal_ref, 'pipeline_report_ref': save(self.folder, report)})
            cases[arm] = case_ref; submissions[arm] = save(self.folder, {'case_result_ref': case_ref})
        passes = []
        for index, preference in enumerate(['X', 'Y']):
            response = {'pairwise_preference': preference, 'assessments': [{'case_id': cid, 'label': blind,
                'proposal_ref': proposal_ref, 'scores': {'baseline_novelty': 2, 'unproved_links': 2 - index if blind == 'X' else 2}}
                for blind in ['X', 'Y']]}
            response_ref = save(self.folder, response)
            execution_ref = save(self.folder, {'status': 'succeeded', 'receipt': {'turn_completed': True,
                'response_sha256': response_ref['sha256']}})
            passes.append(save(self.folder, {'response': response, 'response_ref': response_ref, 'execution_ref': execution_ref}))
        contract_ref = save(self.folder, {'cases': [cid]})
        study = {'contract_ref': contract_ref, 'blind_mapping': {cid: {'X': 'A', 'Y': 'B'}},
                 'review': {cid: {'passes': passes}}, 'cases': {cid: cases}}
        record = {'original_contract_ref': contract_ref, 'results': {arm: save(self.folder, {'status': 'passed',
            'cases': [{'id': cid, 'passed': True, 'output_ref': submissions[arm], 'metrics': {'baseline_novelty': 2}}]}) for arm in ['A', 'B']}}
        path = self.folder / 'captured-review.json'; path.write_text(json.dumps(record))
        before = path.read_bytes()
        value, _ = ds.comparison_dto(ds.Reader(), path, name='captured', scope='synthetic_test', review_study=study)
        row = value['rows'][0]
        self.assertEqual(value['status'], 'passed')  # Immutable review gate retained.
        self.assertEqual(row['A']['review_status'], 'passed')
        self.assertEqual(row['A']['pipeline_status'], 'blocked')
        self.assertEqual(row['A']['pipeline_reason'], 'SYNTHETIC_HOST_BLOCK')
        self.assertEqual(row['B']['runtime_status'], 'completed')
        self.assertEqual(row['review_order']['preferences'], ['A', 'B'])
        self.assertFalse(row['review_order']['preference_consistent'])
        self.assertEqual(row['review_order']['score_disagreements'], ['unproved_links'])
        self.assertEqual(value['conclusion']['status'], 'limited')
        self.assertEqual(value['conclusion']['noncompleted_executions'], 1)
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(ds.METRICS['unproved_links'][1], 'rubric_0_2')


if __name__ == '__main__': unittest.main()
