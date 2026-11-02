"""Hosted portal fixtures; no native web/provider is called by these tests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

from shared.research_sources.artifacts import SOURCE_STATE, SourceError, read, save
from shared.research_sources.host_web import HostWeb, freeze_config

URL = 'https://newsroom.servicenow.com/synthetic-issuer-release'
BODY = 'Synthetic public issuer statement defines a meter but does not establish purchased units or recognized revenue.'
RAW = f'Synthetic issuer ({URL})\nSource: open\nL0: {BODY}\nL1: A bounded captured passage with a known scope.'


class HostWebTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)
        self.clock = [datetime(2026, 11, 2, 1, tzinfo=timezone.utc)]
        self.baseline = save(self.root, {'scope': 'synthetic prior context'})
        self.config = {'schema_version': 1, 'execution_id': str(uuid.uuid4()), 'arm': 'A', 'question': 'What new economic information is disclosed?',
            'baseline_ref': self.baseline, 'cutoff': '2026-11-02T01:10:00Z', 'model_sha256': 'a' * 64,
            'backend': 'native_tools.web__run', 'cohort': 'cold', 'cache_enabled': True, 'cache_max_age_seconds': 3600,
            'max_fallbacks': 2, 'requirement_ids': ['pricing', 'adoption'],
            'budget': {'search_items': 6, 'open_items': 6, 'provider_items': 12, 'wall_seconds': 600}}
        self.portal = self.make(self.config)

    def make(self, config, directory=None):
        return HostWeb(directory or self.root / config['execution_id'], config=config,
            cache_directory=self.root / 'cache', now=lambda: self.clock[0].isoformat())

    def open(self, operation='read', portal=None):
        portal = portal or self.portal; args = {'open': [{'ref_id': URL}], 'response_length': 'long'}
        prepared = portal.prepare(operation, args, requirement_ids=['pricing'])
        if prepared['dispatch']:
            result = portal.capture(operation, {'actual_arguments': args, 'raw_result': RAW, 'status': 'returned'})
            return prepared, result
        return prepared, None

    def test_prepare_reserves_items_before_dispatch_and_exact_arguments_bind_capture(self):
        args = {'search_query': [{'q': 'synthetic pricing'}, {'q': 'synthetic adoption'}], 'response_length': 'long'}
        prepared = self.portal.prepare('search', args, requirement_ids=['pricing', 'adoption'])
        self.assertTrue(prepared['dispatch'])
        state = read(self.portal._head()); self.assertEqual(state['usage']['provider_items'], 2)
        self.assertEqual(self.portal.prepare('search', args, requirement_ids=['pricing', 'adoption'])['status'], 'pending')
        with self.assertRaisesRegex(SourceError, 'HOST_WEB_TOOL_ARGUMENT_MISMATCH'):
            self.portal.capture('search', {'actual_arguments': {'search_query': [{'q': 'other'}]}, 'raw_result': 'Synthetic', 'status': 'returned'})
        self.assertEqual(read(self.portal._head())['usage']['provider_items'], 2)
        result = self.portal.capture('search', {'actual_arguments': args, 'raw_result': f'Synthetic search result ({URL}) turn99search0', 'status': 'returned'})
        self.assertEqual(result['packet']['urls'], [URL])
        self.assertIn('turn99search0', result['packet']['search_text'])
        self.assertIn('session-only', result['packet']['native_reference_warning'])
        source = read(result['source_refs'][0]); self.assertEqual(source['access_level'], 'metadata')
        self.assertEqual(read(source['raw']), f'Synthetic search result ({URL}) turn99search0')
        operation = read(result['operation_ref']); self.assertEqual(operation['provider_items'], 2)
        self.assertEqual(operation['requirement_ids'], ['pricing', 'adoption'])

    def test_search_preserves_rare_non_url_discovery_clue_as_metadata(self):
        args = {'search_query': [{'q': 'synthetic pricing'}], 'response_length': 'long'}
        self.portal.prepare('rare', args, requirement_ids=['pricing'])
        raw = f'Rare economically relevant title ({URL})\nSnippet: pneumonoultramicroscopic license-meter change. turn9search0'
        result = self.portal.capture('rare', {'actual_arguments': args, 'raw_result': raw, 'status': 'returned'})
        packet = result['packet']; source = read(result['source_refs'][0])
        self.assertEqual(packet['search_text'], raw)
        self.assertNotIn('pneumonoultramicroscopic', URL)
        self.assertIn('pneumonoultramicroscopic', packet['search_text'])
        self.assertEqual(packet['scope'], 'current_search_metadata_only')
        self.assertFalse(packet['search_text_truncated'])
        self.assertEqual(read(source['text'], json_value=False).decode(), packet['search_text'])
        self.assertEqual(read(source['raw']), raw); self.assertEqual(source['access_level'], 'metadata')
        self.assertEqual(source['available_at'], self.clock[0].isoformat())
        self.assertFalse(source['metadata']['semantic_admission']); self.assertFalse(source['metadata']['historical_backdating'])

    def test_search_text_truncation_is_explicit_and_late_search_is_not_exposed(self):
        from shared.research_sources.host_web import MAX_SEARCH_TEXT
        args = {'search_query': [{'q': 'synthetic pricing'}]}
        self.portal.prepare('large-search', args, requirement_ids=['pricing'])
        raw = f'Synthetic title ({URL})\n' + 'x' * 50000
        result = self.portal.capture('large-search', {'actual_arguments': args, 'raw_result': raw, 'status': 'returned'})
        self.assertTrue(result['packet']['search_text_truncated'])
        self.assertEqual(len(result['packet']['search_text']), MAX_SEARCH_TEXT)
        self.assertEqual(result['packet']['search_text_total_chars'], len(raw))
        self.assertEqual(read(read(result['source_refs'][0])['raw']), raw)
        self.portal.prepare('late-search', {'search_query': [{'q': 'different'}]}, requirement_ids=['pricing'])
        self.clock[0] += timedelta(minutes=11)
        result = self.portal.capture('late-search', {'actual_arguments': {'search_query': [{'q': 'different'}]}, 'raw_result': raw, 'status': 'returned'})
        self.assertEqual(result['status'], 'failed'); self.assertEqual(result['code'], 'HOST_WEB_DEADLINE')
        self.assertEqual(result['packet'], {}); self.assertEqual(result['source_refs'], [])

    def test_native_search_schema_rejects_five_and_short_or_implicit_four_before_reservation(self):
        for args in [{'search_query': [{'q': 'query'}] * 5},
                     {'search_query': [{'q': 'query'}] * 4, 'response_length': 'short'},
                     {'search_query': [{'q': 'query'}] * 4}]:
            with self.assertRaises(SourceError): self.portal.prepare('bad-schema', args, requirement_ids=['pricing'])
        self.assertEqual(read(self.portal._head())['usage']['provider_items'], 0)
        for response_length in ['medium', 'long']:
            portal = self.make({**self.config, 'execution_id': str(uuid.uuid4())})
            self.assertTrue(portal.prepare('four', {'search_query': [{'q': 'query'}] * 4,
                'response_length': response_length}, requirement_ids=['pricing'])['dispatch'])

    def test_native_string_open_observed_now_and_screened_before_exposure(self):
        _, result = self.open(); self.assertEqual(result['status'], 'returned')
        source = read(result['source_refs'][0]); self.assertEqual(source['provider'], 'native_open_primary_capture')
        self.assertEqual(source['retrieved_at'], self.clock[0].isoformat()); self.assertEqual(source['available_at'], source['retrieved_at'])
        self.assertIn(BODY, read(source['text'], json_value=False).decode()); self.assertEqual(read(source['raw']), RAW)
        run = self.portal.finish()['run']; guard = read(run['exposure_ref']); event = read(guard['event_refs'][0])
        self.assertEqual(event['kind'], 'acquisition_operation_exposure')
        self.assertEqual(event['requirement_ids'], ['pricing'])
        self.assertLessEqual(source['retrieved_at'], event['screened_at']); self.assertLessEqual(event['screened_at'], event['exposed_at'])
        self.assertEqual(guard['exposure_mode'], 'per_operation_host_screened')
        self.assertEqual(run['usage']['provider_items'], 1)

    def test_find_is_metadata_locator_charged_to_read_budget_and_followed_by_document_open(self):
        config = deepcopy(self.config); config['execution_id'] = str(uuid.uuid4()); config['budget']['open_items'] = 2
        portal = self.make(freeze_config(config)); args = {'find': [{'ref_id': URL, 'pattern': 'approval'}], 'response_length': 'long'}
        prepared = portal.prepare('locate', args, requirement_ids=['pricing'])
        self.assertEqual(read(prepared['intent_ref'])['native_verb'], 'find')
        raw = f'Synthetic locator ({URL})\nL600: approval requirement appears in a documented section.'
        result = portal.capture('locate', {'actual_arguments': args, 'raw_result': raw, 'status': 'returned'})
        receipt = read(result['operation_ref']); source = read(result['source_refs'][0])
        self.assertEqual((receipt['operation'], receipt['native_verb'], receipt['provider_items']), ('open', 'find', 1))
        self.assertEqual(source['access_level'], 'metadata'); self.assertEqual(source['provider'], 'native_web_find')
        self.assertEqual(result['packet']['line_hints'], [600]); self.assertEqual(result['packet']['find_text'], raw)
        self.assertEqual(result['packet']['scope'], 'current_locator_metadata_only'); self.assertNotIn('documents', result['packet'])
        self.assertEqual(read(source['raw']), raw); self.assertEqual(read(source['text'], json_value=False).decode(), raw)
        _, opened = self.open('document', portal=portal)
        self.assertEqual(read(opened['source_refs'][0])['access_level'], 'document')
        with self.assertRaisesRegex(SourceError, 'HOST_WEB_ITEM_BUDGET'):
            portal.prepare('over-budget', {'find': [{'ref_id': URL, 'pattern': 'another'}]}, requirement_ids=['pricing'])
        run = portal.finish()['run']; self.assertEqual(run['usage']['open_items'], 2); self.assertEqual(run['usage']['provider_items'], 2)
        self.assertEqual(len(run['cache_attempt_refs']), 2)  # document miss/publication only; find has no cache
        self.assertEqual(receipt['code_provenance']['pin_status'], 'verified')
        self.assertEqual(run['code_provenance']['pin_status'], 'verified')

    def test_find_validation_and_unknown_fence_are_not_bypassed(self):
        for args in [{'find': [{'ref_id': 'turn0search0', 'pattern': 'x'}]},
                     {'find': [{'ref_id': URL, 'pattern': 'x' * 401}]},
                     {'find': [{'ref_id': URL, 'pattern': ''}]}, {'find': [{'ref_id': URL, 'pattern': 'x'}], 'open': [{'ref_id': URL}]}]:
            with self.assertRaises(SourceError): self.portal.prepare('invalid', args, requirement_ids=['pricing'])
        args = {'find': [{'ref_id': URL, 'pattern': 'approval'}]}
        self.portal.prepare('unknown-find', args, requirement_ids=['pricing'])
        self.portal.capture('unknown-find', {'actual_arguments': args, 'raw_result': 'Synthetic uncertain outcome',
            'status': 'unknown', 'code': 'HOST_WEB_RESULT_UNKNOWN'})
        self.assertFalse(self.portal.prepare('other-find', {'find': [{'ref_id': URL, 'pattern': 'tools'}]}, requirement_ids=['pricing'])['dispatch'])

    def test_frozen_code_file_change_during_pending_archives_raw_without_exposure_and_blocks_cache(self):
        import shared.research_sources.host_web as module
        code_root = self.root / 'code-fixture'
        for name in module.CODE_FILES:
            path = code_root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('synthetic public code fixture\n')
        with patch.object(module, 'ROOT', code_root):
            config = freeze_config({**self.config, 'execution_id': str(uuid.uuid4())})
            portal = self.make(config); self.open('prime', portal=portal)
            args = {'find': [{'ref_id': URL, 'pattern': 'approval'}]}; portal.prepare('pending', args, requirement_ids=['pricing'])
            (code_root / module.CODE_FILES[0]).write_text('changed synthetic code fixture\n')
            raw = f'Synthetic locator ({URL}) L600: approval'
            result = portal.capture('pending', {'actual_arguments': args, 'raw_result': raw, 'status': 'returned'})
            self.assertEqual((result['status'], result['code']), ('failed', 'HOST_WEB_SOURCE_CHANGED'))
            self.assertEqual(result['packet'], {}); self.assertEqual(result['source_refs'], [])
            receipt = read(result['operation_ref']); self.assertEqual(read(receipt['response_ref']), raw)
            self.assertEqual(receipt['code_provenance']['pin_status'], 'changed')
            with self.assertRaisesRegex(SourceError, 'HOST_WEB_SOURCE_CHANGED'): self.open('cached-after-change', portal=portal)
            final = portal.finish(); self.assertEqual(final['run']['code_provenance']['pin_status'], 'changed')
            self.assertEqual(len(read(final['run']['exposure_ref'])['event_refs']), 1)
            self.assertEqual(HostWeb(portal.directory).finish()['run_ref'], final['run_ref'])

    def test_code_pins_reject_arbitrary_paths_and_legacy_is_explicitly_unverified(self):
        pinned = freeze_config(self.config); self.assertEqual(len(pinned['code_pins']['files']), 5)
        bad = deepcopy(pinned); bad['code_pins']['files']['../private'] = 'a' * 64
        with self.assertRaisesRegex(SourceError, 'HOST_WEB_CODE_PINS_INVALID'): self.make(bad)
        prepared, result = self.open(); self.assertEqual(read(prepared['intent_ref'])['code_provenance']['pin_status'], 'unverified')
        self.assertEqual(read(result['operation_ref'])['code_provenance']['pin_status'], 'unverified')
        self.assertEqual(self.portal.finish()['run']['code_provenance']['pin_status'], 'unverified')

    def test_a_cache_cross_run_uses_portable_url_and_b_cache_off_dispatches(self):
        _, captured = self.open(); ref = captured['source_refs'][0]; self.portal.finish()
        config = {**self.config, 'execution_id': str(uuid.uuid4()), 'question': 'Different query same source', 'cohort': 'warm_cache'}
        second = self.make(config); prepared, result = self.open(portal=second)
        self.assertEqual(prepared['status'], 'cache_hit'); self.assertIsNone(result)
        self.assertEqual(prepared['packet']['documents'][0]['source_ref'], ref)
        self.assertEqual(second.finish()['run']['usage']['provider_items'], 0)
        config = {**config, 'execution_id': str(uuid.uuid4()), 'arm': 'B', 'cache_enabled': False}
        third = self.make(config); prepared, _ = self.open(portal=third)
        self.assertTrue(prepared['dispatch']); self.assertEqual(third.finish()['run']['cache_attempt_refs'], [])

    def test_cached_open_consumes_same_logical_budget_and_cannot_repeat_past_cap(self):
        self.open(); self.portal.finish()
        config = deepcopy(self.config); config['execution_id'] = str(uuid.uuid4()); config['cohort'] = 'warm_cache'
        config['budget']['open_items'] = 1
        portal = self.make(config)
        prepared, _ = self.open('cached-one', portal=portal)
        self.assertEqual(prepared['status'], 'cache_hit')
        with self.assertRaisesRegex(SourceError, 'HOST_WEB_ITEM_BUDGET'):
            self.open('cached-two', portal=portal)
        self.assertEqual(read(portal._head())['usage']['open_items'], 1)
        self.assertEqual(read(portal._head())['usage']['provider_items'], 0)

    def test_partial_batch_cache_is_unused_and_has_one_exact_exposure(self):
        self.open(); self.portal.finish()
        config = {**self.config, 'execution_id': str(uuid.uuid4()), 'cohort': 'warm_cache'}
        portal = self.make(config); other = URL + '-other'
        args = {'open': [{'ref_id': URL}, {'ref_id': other}], 'response_length': 'long'}
        self.assertTrue(portal.prepare('mixed', args, requirement_ids=['pricing'])['dispatch'])
        raw = RAW + '\n' + RAW.replace(URL, other)
        result = portal.capture('mixed', {'actual_arguments': args, 'raw_result': raw, 'status': 'returned',
            'documents': [{'url': URL, 'text': BODY}, {'url': other, 'text': BODY}]})
        run = portal.finish()['run']; guard = read(run['exposure_ref'])
        self.assertEqual(len(guard['event_refs']), 1)
        self.assertEqual({ref['sha256'] for ref in read(guard['event_refs'][0])['exposed_source_refs']},
                         set(read(result['operation_ref'])['source_sha256s']))
        attempts = [read(ref) for ref in run['cache_attempt_refs']]
        self.assertTrue(any(row.get('lookup_hit') and row['reasons'] == ['CACHE_PARTIAL_BATCH_NOT_USED'] for row in attempts))
        self.assertFalse(any(row['cache_hit'] for row in attempts))
        self.assertEqual(run['usage']['open_items'], 2); self.assertEqual(run['usage']['provider_items'], 2)

    def test_transport_circuit_still_allows_eligible_cache_body_without_dispatch(self):
        self.open(); self.portal.finish()
        portal = self.make({**self.config, 'execution_id': str(uuid.uuid4()), 'cohort': 'warm_cache'})
        args = {'search_query': [{'q': 'synthetic'}]}; portal.prepare('failed', args, requirement_ids=['adoption'])
        portal.capture('failed', {'actual_arguments': args, 'raw_result': 'Synthetic connection failed',
            'status': 'failed', 'code': 'NATIVE_TRANSPORT_FAILED'})
        prepared, _ = self.open('cached-fallback', portal=portal)
        self.assertEqual(prepared['status'], 'cache_hit')
        self.assertEqual(portal.finish()['run']['usage']['provider_items'], 1)

    def test_cli_stdin_and_result_json_preserve_real_string_shape(self):
        directory = self.root / 'cli'; config = deepcopy(self.config)
        config['execution_id'] = str(uuid.uuid4()); config['cutoff'] = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        def cli(command, payload, *options):
            result = subprocess.run([sys.executable, '-m', 'shared.research_sources.host_web', command,
                '--directory', str(directory), *options], input=json.dumps(payload), text=True,
                capture_output=True, cwd=Path(__file__).resolve().parents[3], timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)
        cli('init', {'config': config, 'cache_directory': str(self.root / 'cli-cache')})
        args = {'open': [{'ref_id': URL}], 'response_length': 'long'}
        prepared = cli('prepare', {'operation_id': 'read', 'arguments': args, 'requirement_ids': ['pricing']})
        self.assertEqual(prepared['arguments'], args)
        captured = cli('capture', {'operation_id': 'read', 'capture': {'actual_arguments': args, 'status': 'returned'}},
            '--result-json', json.dumps(RAW))
        source = read(captured['source_refs'][0]); self.assertEqual(read(source['raw']), RAW)
        run = cli('finish', {})['run']; event = read(read(run['exposure_ref'])['event_refs'][0])
        operation = read(run['open_receipt_refs'][0])
        self.assertLessEqual(operation['finished_at'], event['screened_at'])

    def test_real_portal_receipts_satisfy_acquisition_gate(self):
        from tuning.evals.information_fetch.acquisition import validate_run
        args = {'search_query': [{'q': 'synthetic pricing'}]}
        self.portal.prepare('search', args, requirement_ids=['pricing'])
        self.portal.capture('search', {'actual_arguments': args, 'raw_result': f'Synthetic search ({URL})', 'status': 'returned'})
        self.open(); final = self.portal.finish(); run = final['run']
        frozen = {key: run[key] for key in ['cohort', 'question_sha256', 'baseline_sha256', 'cutoff', 'model_sha256', 'backend']}
        frozen.update({'arm_config_sha256': {'A': run['config_sha256']}, 'cache_required_arms': ['A'],
                       'resource_limits': {'search_items': 6, 'open_items': 6, 'provider_items': 12, 'wall_seconds': 600, 'tokens': None, 'cost': None}})
        checked = validate_run(final['run_ref'], frozen)
        self.assertEqual(checked[3:5], (1, 1))

    def test_failure_no_identical_retry_and_explicit_fallback_budgeted(self):
        args = {'open': [{'ref_id': URL}]}; self.portal.prepare('one', args, requirement_ids=['pricing'])
        self.portal.capture('one', {'actual_arguments': args, 'raw_result': 'Synthetic forbidden response', 'status': 'failed', 'code': 'SOURCE_HTTP_403'})
        self.assertEqual(self.portal.prepare('again', args, requirement_ids=['pricing'])['status'], 'not_retry')
        other = {'open': [{'ref_id': URL + '-other'}]}
        prepared = self.portal.prepare('fallback', other, fallback_of='one', requirement_ids=['pricing'])
        self.assertTrue(prepared['dispatch']); self.assertEqual(read(self.portal._head())['usage']['provider_items'], 2)

    def test_transport_circuit_and_genuine_unknown_do_not_dispatch_again(self):
        for code, status in [('NATIVE_TRANSPORT_FAILED', 'failed'), ('HOST_WEB_RESULT_UNKNOWN', 'unknown')]:
            config = {**self.config, 'execution_id': str(uuid.uuid4())}; portal = self.make(config)
            args = {'search_query': [{'q': 'synthetic'}]}; portal.prepare('first', args, requirement_ids=['adoption'])
            portal.capture('first', {'actual_arguments': args, 'raw_result': 'Synthetic failure', 'status': status, 'code': code})
            self.assertFalse(portal.prepare('next', {'search_query': [{'q': 'different'}]}, requirement_ids=['adoption'])['dispatch'])
        args = {'open': [{'ref_id': URL}]}; self.portal.prepare('read', args, requirement_ids=['pricing'])
        captured = self.portal.capture('read', {'actual_arguments': args, 'raw_result': 'not a source body', 'status': 'returned'})
        self.assertEqual(captured['status'], 'failed'); self.assertEqual(captured['packet'], {})
        self.assertEqual(captured['code'], 'HOST_WEB_BODY_UNPARSEABLE')
        self.assertEqual(read(read(captured['operation_ref'])['response_ref']), 'not a source body')
        self.assertEqual(self.portal.prepare('same', args, requirement_ids=['pricing'])['status'], 'not_retry')
        other = {'open': [{'ref_id': URL + '-alternate'}]}
        self.assertTrue(self.portal.prepare('alternate', other, fallback_of='read', requirement_ids=['pricing'])['dispatch'])
        result = self.portal.capture('alternate', {'actual_arguments': other, 'raw_result': RAW.replace(URL, URL + '-alternate'), 'status': 'returned'})
        self.assertEqual(result['status'], 'returned'); self.assertEqual(self.portal.finish()['run']['status'], 'partial')

    def test_future_publication_and_late_response_never_exposed(self):
        args = {'open': [{'ref_id': URL}]}; self.portal.prepare('future', args, requirement_ids=['pricing'])
        result = self.portal.capture('future', {'actual_arguments': args, 'raw_result': RAW, 'status': 'returned',
            'documents': [{'url': URL, 'text': BODY, 'published_at': '2027-01-01'}]})
        self.assertEqual(result['code'] if 'code' in result else read(result['operation_ref'])['code'], 'HOST_WEB_FUTURE_EXPOSURE')
        self.assertEqual(result['packet'], {})
        portal = self.make({**self.config, 'execution_id': str(uuid.uuid4())})
        portal.prepare('late', args, requirement_ids=['pricing']); self.clock[0] += timedelta(minutes=11)
        result = portal.capture('late', {'actual_arguments': args, 'raw_result': RAW, 'status': 'returned'})
        self.assertEqual(result['status'], 'failed'); self.assertEqual(read(result['operation_ref'])['code'], 'HOST_WEB_DEADLINE')
        self.assertEqual(result['packet'], {})

    def test_ephemeral_refs_secrets_budget_and_observer_failure_are_contained(self):
        for value in ['turn0search0', 'https://user:password@example.com/a', 'https://127.0.0.1/a', 'https://example.com:8443/a']:
            with self.assertRaises((SourceError, ValueError)): self.portal.prepare('bad', {'open': [{'ref_id': value}]})
        args = {'search_query': [{'q': 'query'}] * 7}
        with self.assertRaisesRegex(SourceError, 'HOST_WEB_ITEMS_INVALID'): self.portal.prepare('large', args, requirement_ids=['pricing'])
        self.open(); args = {'open': [{'ref_id': URL + '-observer'}]}; self.portal.prepare('observer', args, requirement_ids=['pricing'])
        raw = RAW.replace(URL, URL + '-observer')
        def broken(ref): raise RuntimeError('SYNTHETIC_SECRET')
        result = self.portal.capture('observer', {'actual_arguments': args, 'raw_result': raw, 'status': 'returned'}, observer=broken)
        self.assertEqual(result['status'], 'returned'); self.assertEqual(result['warning'], 'HOST_WEB_OBSERVER_UNAVAILABLE')
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(result))

    def test_portal_reopen_retains_cache_path_and_frozen_config(self):
        self.open(); same = HostWeb(self.portal.directory, now=lambda: self.clock[0].isoformat())
        self.assertEqual(same.cache_directory, self.root / 'cache')
        changed = {**self.config, 'question': 'Changed frozen question'}
        with self.assertRaisesRegex(SourceError, 'HOST_WEB_CONFIG_CONFLICT'): self.make(changed, directory=self.portal.directory)


if __name__ == '__main__': unittest.main()
