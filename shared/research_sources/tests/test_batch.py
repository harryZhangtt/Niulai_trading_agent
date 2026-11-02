"""Local batch contracts; fixture fetchers do not establish live-provider access."""
from copy import deepcopy
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from shared.research_sources import batch
from shared.research_sources.artifacts import SOURCE_STATE, SourceError, read, save

URL = 'https://nvidianews.nvidia.com/news/synthetic-fixture'


class BatchTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name); self.calls = []; self.lock = threading.Lock()
        raw = save(self.directory, b'Synthetic current capture of an old public statement.', suffix='txt')
        self.source = save(self.directory, {'schema_version': 1, 'provider': 'official_document',
            'source_url': URL, 'upstream_id': URL, 'source_version': None, 'access_level': 'document',
            'raw': raw, 'text': raw, 'retrieved_at': '2026-11-01T01:00:00Z',
            'available_at': '2026-11-01T01:00:00Z', 'published_at': '2025-01-01', 'availability_basis': 'first_observed'})
        self.item = {'id': 'issuer', 'subject': 'NVDA', 'access': 'document',
            'routes': [{'capability': 'official_document.read', 'parameters': {'url': URL}}],
            'max_attempts': 1, 'cache_max_age_seconds': 3600, 'timeout_seconds': 5}
        self.config = {'schema_version': 1, 'batch_id': 'public-fixture', 'query': 'Acquire original source bytes.',
            'requirements': [self.item], 'budget': {'deadline_seconds': 10, 'max_workers': 2, 'max_provider_calls': 4}}

    def fetch(self, route, directory, timeout, request_id):
        with self.lock: self.calls.append(request_id)
        return self.source

    def run_batch(self, config=None, **kwargs):
        return batch.run_batch(config or self.config, state_directory=self.directory / 'executions',
            cache_directory=self.directory / 'cache', fetcher=kwargs.pop('fetcher', self.fetch), **kwargs)

    def test_cold_warm_separate_execution_snapshots_and_same_uuid_replay(self):
        first = self.run_batch(); second = self.run_batch()
        self.assertNotEqual(first['execution_id'], second['execution_id'])
        self.assertEqual((first['counts']['provider_calls'], second['counts']['provider_calls']), (1, 0))
        self.assertEqual(second['counts']['cache_hits'], 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(first['source_refs'], second['source_refs'])
        self.assertEqual(read(first['source_refs'][0])['retrieved_at'], '2026-11-01T01:00:00Z')
        replay = self.run_batch(execution_id=first['execution_id'])
        self.assertTrue(replay['idempotent_replay']); self.assertEqual(replay['report_ref'], first['report_ref'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(read(first['report_ref'])['retention']['snapshots'], 'retain_until_explicit_gc')
        self.assertEqual(read(first['requirement_result_refs'][0])['execution_id'], first['execution_id'])

    def test_changed_query_batch_and_worker_budget_reuse_acquisition_but_uuid_config_conflict_remains(self):
        first = self.run_batch()
        changed = deepcopy(self.config); changed['query'] = 'Another question using the same source'
        changed['batch_id'] = 'another-batch'; changed['budget']['max_workers'] = 1
        changed['budget']['max_provider_calls'] = 2
        second = self.run_batch(changed)
        self.assertNotEqual(first['config_sha256'], second['config_sha256'])
        self.assertEqual((second['counts']['provider_calls'], second['counts']['cache_hits']), (0, 1))
        self.assertEqual(len(self.calls), 1)
        with self.assertRaisesRegex(SourceError, 'BATCH_EXECUTION_CONFLICT'):
            self.run_batch(changed, execution_id=first['execution_id'])

    def test_snapshot_trace_survives_discarding_the_hot_cache(self):
        result = self.run_batch()
        row = read(result['requirement_result_refs'][0]); attempt = read(row['attempt_refs'][0])
        self.assertTrue(attempt['cache_attempt_refs'])
        self.assertTrue(all(str(self.directory / 'cache') not in ref['path'] for ref in attempt['cache_attempt_refs']))
        shutil.rmtree(self.directory / 'cache')
        self.assertEqual(read(result['report_ref'])['status'], 'completed')
        for ref in attempt['cache_attempt_refs']: self.assertEqual(read(ref)['source_ref'], self.source)
        self.assertEqual(read(row['selected_source_ref'])['source_url'], URL)

    def test_concurrent_same_key_singleflight_and_atomic_provider_budget(self):
        config = deepcopy(self.config); config['requirements'] += [{**deepcopy(self.item), 'id': 'duplicate'}]
        result = self.run_batch(config)
        self.assertEqual((result['counts']['provider_calls'], len(self.calls), result['counts']['cache_hits']), (1, 1, 1))
        # The provider-budget subcase is a separate cold cohort.
        shutil.rmtree(self.directory / 'cache')
        config = deepcopy(self.config); config['budget']['max_provider_calls'] = 1
        config['requirements'] += [{**deepcopy(self.item), 'id': 'other',
            'routes': [{'capability': 'official_document.read', 'parameters': {'url': URL + '-other'}}]}]
        def matching(route, directory, timeout, request_id):
            self.fetch(route, directory, timeout, request_id)
            target = route['parameters']['url']
            return save(self.directory, {**read(self.source), 'source_url': target, 'upstream_id': target})
        result = self.run_batch(config, fetcher=matching)
        self.assertEqual(result['status'], 'partial'); self.assertEqual(result['counts']['provider_calls'], 1)
        self.assertEqual(len(result['requirement_result_refs']), 2)
        reasons = [reason for ref in result['requirement_result_refs'] for reason in read(ref)['reasons']]
        self.assertIn('BATCH_PROVIDER_BUDGET', reasons)

    def test_same_execution_cannot_dispatch_concurrently(self):
        execution_id = str(uuid.uuid4()); entered = threading.Event(); release = threading.Event(); outcomes = []
        def waiting(*args):
            entered.set()
            if not release.wait(3): raise TimeoutError
            return self.fetch(*args)
        def runner(): outcomes.append(self.run_batch(execution_id=execution_id, fetcher=waiting))
        thread = threading.Thread(target=runner); thread.start()
        try:
            self.assertTrue(entered.wait(3))
            with self.assertRaisesRegex(SourceError, 'BATCH_EXECUTION_BUSY'): self.run_batch(execution_id=execution_id)
        finally:
            release.set(); thread.join(5)
        self.assertFalse(thread.is_alive()); self.assertEqual(outcomes[0]['status'], 'completed')
        self.assertEqual(len(self.calls), 1)

    def test_explicit_fallback_and_transient_retry_are_separate_receipts(self):
        config = deepcopy(self.config)
        config['requirements'][0]['routes'].insert(0, {'capability': 'arxiv_mcp_candidate.read', 'parameters': {'paper_id': '2407.08608v2'}})
        result = self.run_batch(config); row = read(result['requirement_result_refs'][0])
        self.assertEqual((result['status'], row['route'], row['counts']['fallbacks']), ('completed', 'official_document.read', 1))
        self.assertEqual(read(row['attempt_refs'][0])['reasons'], ['BATCH_EXTERNAL_CAPABILITY_REQUIRED'])
        self.assertEqual(read(read(row['attempt_refs'][0])['intent_ref'])['execution_id'], result['execution_id'])
        # Retry must be exercised cold; config changes now correctly reuse data.
        shutil.rmtree(self.directory / 'cache')
        config = deepcopy(self.config); config['requirements'][0]['max_attempts'] = 2
        attempts = []
        def transient(*args):
            attempts.append(1)
            if len(attempts) == 1: raise SourceError('SOURCE_NETWORK_FAILED')
            return self.source
        result = self.run_batch(config, fetcher=transient)
        self.assertEqual((result['status'], result['counts']['provider_calls'], result['counts']['retries']), ('completed', 2, 1))
        self.assertEqual(len(read(result['requirement_result_refs'][0])['attempt_refs']), 2)

    def test_unknown_timeout_stops_retries_and_fallbacks(self):
        config = deepcopy(self.config); config['requirements'][0]['max_attempts'] = 2
        config['requirements'][0]['routes'] *= 2
        calls = []
        def timed_out(*args): calls.append(1); raise TimeoutError('SYNTHETIC_SECRET')
        result = self.run_batch(config, fetcher=timed_out)
        self.assertEqual((result['status'], len(calls), result['counts']['unknown']), ('unknown', 1, 1))
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(result))
        again = self.run_batch(config, fetcher=timed_out, execution_id=result['execution_id'])
        self.assertEqual(again['status'], 'unknown'); self.assertEqual(len(calls), 1)
        self.assertFalse(again['idempotent_replay'])

    def test_unexpected_callback_failure_is_unknown_not_permission_to_dispatch_fallback(self):
        config = deepcopy(self.config); config['requirements'][0]['routes'] *= 2; calls = []
        def failed_after_dispatch(*args): calls.append(1); raise RuntimeError('SYNTHETIC_SECRET')
        result = self.run_batch(config, fetcher=failed_after_dispatch)
        self.assertEqual((result['status'], len(calls)), ('unknown', 1))
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(result))

    def test_interrupted_intent_is_fenced_and_config_conflict_is_rejected(self):
        execution_id = str(uuid.uuid4()); calls = []
        def interrupted(*args): calls.append(1); raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt): self.run_batch(execution_id=execution_id, fetcher=interrupted)
        result = self.run_batch(execution_id=execution_id)
        self.assertEqual(result['status'], 'unknown'); self.assertEqual(result['reason'], 'BATCH_EXECUTION_UNCERTAIN')
        self.assertIsNone(result['report_ref']); self.assertEqual(len(calls), 1); self.assertEqual(self.calls, [])
        changed = deepcopy(self.config); changed['query'] = 'Changed configuration'
        with self.assertRaisesRegex(SourceError, 'BATCH_EXECUTION_CONFLICT'): self.run_batch(changed, execution_id=execution_id)

    def test_observer_failure_never_changes_authoritative_status(self):
        def broken(ref): raise RuntimeError('SYNTHETIC_SECRET /Users/private')
        result = self.run_batch(observer=broken)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(read(result['report_ref'])['status'], 'completed')
        self.assertEqual(result['observability']['code'], 'BATCH_OBSERVER_UNAVAILABLE')
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(result))

    def test_registered_document_action_is_inside_cache_callback(self):
        release_ref = save(self.directory, {'synthetic': 'release'})
        action_ref = save(self.directory, {'synthetic': 'execution'})
        release = {'release_ref': release_ref, 'release_sha256': 'a' * 64}
        with patch.object(batch, 'freeze_release', return_value=release), patch.object(batch, 'invoke',
                return_value={'status': 'success', 'error': None, 'data': {'source_ref': self.source}, 'execution_ref': action_ref}) as invoked:
            first = self.run_batch(fetcher=None); second = self.run_batch(fetcher=None)
        self.assertEqual(invoked.call_count, 1)
        row = read(read(first['requirement_result_refs'][0])['attempt_refs'][0])
        self.assertEqual(row['action_execution_ref'], action_ref)
        self.assertEqual(second['counts']['provider_calls'], 0)

    def test_discovery_known_permanent_error_is_not_rewritten_as_unknown_worker_failure(self):
        original = subprocess.Popen
        def rejected(*args, **kwargs):
            return original([sys.executable, '-c',
                'import json,sys;print(json.dumps({"status":"failed","code":"SOURCE_HTTP_403"}));sys.exit(1)'], **kwargs)
        with patch.object(batch.subprocess, 'Popen', side_effect=rejected):
            with self.assertRaisesRegex(SourceError, '^SOURCE_HTTP_403$'):
                batch._acquire({'capability': 'openalex.discover', 'parameters': {'query': 'synthetic'}},
                    self.directory, 2, 'synthetic-request', None)

    def test_discovery_worker_hard_timeout_cleans_owned_process(self):
        original = subprocess.Popen; children = []
        def sleeping(*args, **kwargs):
            process = original([sys.executable, '-c', 'import time;time.sleep(30)'], **kwargs)
            children.append(process); return process
        with patch.object(batch.subprocess, 'Popen', side_effect=sleeping):
            with self.assertRaisesRegex(SourceError, 'BATCH_DISCOVERY_TIMEOUT'):
                batch._acquire({'capability': 'openalex.discover', 'parameters': {'query': 'synthetic'}},
                    self.directory, .08, 'synthetic-request', None)
        self.assertIsNotNone(children[0].returncode)

    def test_secret_parameters_unknown_capabilities_and_unsafe_execution_paths_rejected(self):
        for changes in [ {'capability': 'not.registered', 'parameters': {'url': URL}},
                         {'capability': 'official_document.read', 'parameters': {'url': 'https://user:password@example.com/q'}},
                         {'capability': 'official_document.read', 'parameters': {'api_key': 'SYNTHETIC_SECRET'}} ]:
            config = deepcopy(self.config); config['requirements'][0]['routes'] = [changes]
            with self.assertRaises(SourceError): self.run_batch(config)
        with self.assertRaisesRegex(SourceError, 'BATCH_EXECUTION_ID_INVALID'): self.run_batch(execution_id='../outside')


if __name__ == '__main__': unittest.main()
