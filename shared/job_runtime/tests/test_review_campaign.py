"""Finite review guards and deterministic progress; no real model/provider calls."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid

from shared.job_runtime import review_campaign as rc
from shared.research_sources.artifacts import ROOT, SOURCE_STATE, save, digest
from shared.job_runtime.service import atomic


class ReviewCampaignTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / '.job-runtime/tests'; parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); (self.base / 'queue').mkdir()
        self.inputs = tempfile.TemporaryDirectory(dir=SOURCE_STATE / 'runtime'); self.addCleanup(self.inputs.cleanup)
        self.study = Path(self.inputs.name)
        self.patch = patch.object(rc, 'STUDY', self.study); self.patch.start(); self.addCleanup(self.patch.stop)
        self.at = datetime.now(timezone.utc)
        self.config = {'expires_at': self.at.timestamp() + 21600, 'slice_seconds': 60, 'max_calls': 6,
            'max_model_seconds': 1800, 'max_tokens': 400000, 'pins': rc.pins(ROOT), 'profile_sha256': digest(rc.profile(ROOT))}
        self.state = {'status': 'active', 'calls': 0, 'model_seconds': 0, 'tokens': 0, 'no_progress': 0,
            'same_failure': 0, 'last_failure': None, 'active_attempt': None, 'work': {}, 'seen_outputs': [], 'last_tick': self.at.timestamp()}

    def work(self, suffix='one', expected=1):
        source = save(self.study / 'continuation/public-inputs', {'count': expected, 'quote': 'A real scoped fixture passage.'})
        policy = save(self.study / 'continuation/policies', {'owner': 'root:review_campaign_v1', 'checks': [
            {'op': 'equals_input', 'output_pointer': '/count', 'input_name': 'trace', 'input_pointer': '/count'},
            {'op': 'equals_input', 'output_pointer': '/quote', 'input_name': 'trace', 'input_pointer': '/quote'}]})
        value = {'schema_version': 1, 'work_id': 'work-' + suffix, 'kind': 'trace_diagnosis', 'role': 'independent trace diagnosis',
            'objective': 'Diagnose actual trace facts, not timestamps.', 'input_refs': [{'name': 'trace', 'ref': source}],
            'postcondition_ref': policy, 'output_schema': {'type': 'object', 'additionalProperties': False,
                'properties': {'work_id': {'type': 'string'}, 'count': {'type': 'integer'}, 'quote': {'type': 'string'}},
                'required': ['work_id', 'count', 'quote']}}
        ref = save(self.study / 'continuation/work', value); rc.enqueue(ROOT, self.base, ref)
        return value

    def fake_model(self, wrong=False, usage=True, unknown=False):
        def call(profile, prompt, workspace, directory, context):
            value = json.loads(prompt); directory.mkdir(parents=True)
            output = {'work_id': value['work_id'], 'count': 0 if wrong else value['inputs']['trace']['count'],
                      'quote': value['inputs']['trace']['quote']}
            path = directory / 'last-message.txt'; path.write_text(json.dumps(output))
            return {'status': 'unknown' if unknown else 'succeeded', 'code': 'MODEL_RUN_OUTCOME_UNCONFIRMED' if unknown else 'MODEL_TURN_COMPLETED',
                'receipt': {'response_path': str(path.relative_to(ROOT)), 'response_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                    'thread_id': 'synthetic-thread', 'turn_completed': True,
                    'usage': {'input_tokens': 20, 'output_tokens': 5} if usage else None}}
        return call

    def dispatch(self):
        return rc.dispatch(ROOT, self.base, self.config, self.state, {'attempt_id': str(uuid.uuid4()), 'scheduled_at': self.at.isoformat()})

    def test_absolute_six_hour_window_all_budgets_and_crash_fence(self):
        self.assertEqual(rc.decision(self.config, self.state, self.at + timedelta(hours=6)), 'expired')
        for field, limit in [('calls', 6), ('model_seconds', 1800), ('tokens', 400000)]:
            state = deepcopy(self.state); state[field] = limit
            self.assertEqual(rc.decision(self.config, state, self.at), 'stopped_budget')
        self.state['active_attempt'] = 'interrupted'
        self.assertEqual(rc.decision(self.config, self.state, self.at), 'unknown')
        self.state['active_attempt'] = None
        self.assertEqual(rc.decision(self.config, self.state, self.at - timedelta(seconds=10)), 'unknown')

    def test_create_has_finite_once_roster_and_no_production_changes(self):
        name = 'test-review-' + uuid.uuid4().hex
        before = (ROOT / '.job-runtime/config/runtime.json').read_bytes()
        base = rc.create(ROOT, name); self.addCleanup(shutil.rmtree, base)
        config = rc.load(base / 'config.json')
        self.assertEqual(len(config['jobs']), 12)
        self.assertTrue(all(job['schedule']['kind'] == 'once' and not job['replay_safe'] for job in config['jobs']))
        self.assertEqual(config['expires_at'] - datetime.fromisoformat(config['created_at']).timestamp(), 21600)
        self.assertEqual(before, (ROOT / '.job-runtime/config/runtime.json').read_bytes())

    def test_direct_artifact_dependency_mutation_stops_before_dispatch(self):
        root = self.base / 'isolated-root'
        for name in rc.pins(ROOT):
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('initial fixture')
        (root / '.job-runtime/config').mkdir(parents=True)
        atomic(root / '.job-runtime/config/runtime.json', {'model_profiles': {'default': {}}})
        base = rc.create(root, 'dependency-probe')
        self.assertIn('shared/research_sources/artifacts.py', rc.load(base / 'config.json')['pins'])
        (root / 'shared/research_sources/artifacts.py').write_text('changed fixture')
        with patch.object(rc, 'run_codex') as model, patch.object(rc, 'Engine') as engine, patch.object(rc.subprocess, 'run'):
            result = rc.tick(root, base)
            model.assert_not_called(); engine.assert_not_called()
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['calls'], 0)

    def test_replacement_inherits_original_expiry_and_global_usage(self):
        name = 'test-lineage-' + uuid.uuid4().hex
        previous = rc.create(ROOT, name); self.addCleanup(shutil.rmtree, previous)
        original = rc.load(previous / 'config.json'); state = rc.load(previous / 'state.json')
        state.update(status='stopped_manual', calls=1, model_seconds=33.77561925002374, tokens=27714)
        atomic(previous / 'state.json', state)
        later = datetime.fromisoformat(original['created_at']) + timedelta(hours=1)
        with patch.object(rc, 'now', return_value=later): replacement = rc.create(ROOT, name + '-v2', previous)
        self.addCleanup(shutil.rmtree, replacement)
        config = rc.load(replacement / 'config.json'); inherited = rc.load(replacement / 'state.json')
        self.assertEqual(config['expires_at'], original['expires_at'])
        self.assertEqual({key: inherited[key] for key in ['calls', 'model_seconds', 'tokens']},
                         {'calls': 1, 'model_seconds': 33.77561925002374, 'tokens': 27714})
        self.assertTrue(all(datetime.fromisoformat(job['schedule']['at']).timestamp() < original['expires_at'] for job in config['jobs']))
        self.assertEqual(config['lineage']['state_sha256'], rc.fingerprint(previous / 'state.json'))
        self.assertEqual(inherited['work'], {})

    def test_empty_queue_never_starts_model_and_valid_result_is_not_replayed(self):
        with patch.object(rc, 'production_priority', return_value={'busy': False}), patch.object(rc, 'run_codex', side_effect=self.fake_model()) as model:
            self.assertEqual(self.dispatch()['code'], 'REVIEW_QUEUE_EMPTY'); self.assertEqual(model.call_count, 0)
            self.work(); self.assertEqual(self.dispatch()['code'], 'REVIEW_RESULT_VERIFIED')
            self.assertEqual(self.dispatch()['code'], 'REVIEW_QUEUE_EMPTY'); self.assertEqual(model.call_count, 1)
        self.assertEqual(self.state['calls'], 1)
        self.assertEqual(next(iter(self.state['work'].values()))['status'], 'verified')

    def test_timestamp_only_or_wrong_facts_do_not_progress_and_two_failures_stop(self):
        with patch.object(rc, 'production_priority', return_value={'busy': False}), patch.object(rc, 'run_codex', side_effect=self.fake_model(wrong=True)) as model:
            self.work('one', 1); self.assertEqual(self.dispatch()['status'], 'failed')
            self.work('two', 2); self.assertEqual(self.dispatch()['status'], 'failed')
            self.assertEqual(self.state['status'], 'stopped_stalled')
            self.assertEqual(self.dispatch()['code'], 'REVIEW_CAMPAIGN_GUARD_STOP'); self.assertEqual(model.call_count, 2)

    def test_unknown_usage_or_outcome_fences_future_model_starts(self):
        for known_usage, unknown in [(False, False), (True, True)]:
            for queued in (self.base / 'queue').glob('*.json'): queued.unlink()
            self.state = {**self.state, 'status': 'active', 'calls': 0, 'active_attempt': None, 'work': {}, 'seen_outputs': []}
            self.work('unknown-' + str(known_usage), 3)
            with patch.object(rc, 'production_priority', return_value={'busy': False}), patch.object(rc, 'run_codex', side_effect=self.fake_model(usage=known_usage, unknown=unknown)) as model:
                self.dispatch(); self.assertEqual(self.state['status'], 'unknown')
                self.dispatch(); self.assertEqual(model.call_count, 1)

    def test_auth_busy_yields_without_reserving_a_model_start(self):
        self.work()
        with patch.object(rc, 'production_priority', return_value={'busy': False}), patch.object(rc, 'run_codex', return_value={'status': 'retryable', 'code': 'MODEL_AUTH_CACHE_BUSY', 'receipt': {}}):
            self.assertEqual(self.dispatch()['code'], 'REVIEW_CAMPAIGN_YIELDED_AUTH')
        self.assertEqual(self.state['calls'], 0); self.assertEqual(self.state['work'], {})

    def test_source_span_postcondition_reopens_hash_bound_original_bytes(self):
        text = save(self.study / 'continuation/public-inputs', b'Prefix. Exact actual passage. Suffix.', suffix='txt')
        source = save(self.study / 'continuation/public-inputs', {'text': text})
        schema = {'type': 'object', 'additionalProperties': False, 'properties': {'work_id': {'type': 'string'},
            'source_quote': {'type': 'string'}, 'source_sha256': {'type': 'string'}}, 'required': ['work_id', 'source_quote', 'source_sha256']}
        value = {'work_id': 'source-check', 'output_schema': schema}
        policy = {'owner': 'root:review_campaign_v1', 'checks': [{'op': 'source_span', 'output_pointer': '/source_quote',
            'source_sha_output_pointer': '/source_sha256', 'source_ref': source, 'text_ref': text, 'start': 8, 'end': 29}]}
        output = {'work_id': 'source-check', 'source_quote': 'Exact actual passage.', 'source_sha256': source['sha256']}
        self.assertTrue(rc.verify(value, {}, policy, output)['verified'])
        with self.assertRaisesRegex(Exception, 'REVIEW_SOURCE_QUOTE_MISMATCH'):
            rc.verify(value, {}, policy, {**output, 'source_quote': 'Invented passage.'})

    def test_repeated_output_cycle_stops_even_if_packet_identity_changes(self):
        value = self.work('same', 0)
        with patch.object(rc, 'production_priority', return_value={'busy': False}), patch.object(rc, 'run_codex', side_effect=self.fake_model()):
            self.assertEqual(self.dispatch()['code'], 'REVIEW_RESULT_VERIFIED')
            replacement = save(self.study / 'continuation/public-inputs', {'count': 0, 'quote': 'A real scoped fixture passage.', 'new_trace_identity': 'different'})
            value['input_refs'][0]['ref'] = replacement
            rc.enqueue(ROOT, self.base, save(self.study / 'continuation/work', value))
            self.assertEqual(self.dispatch()['code'], 'REVIEW_OUTPUT_CYCLE')
        self.assertEqual(self.state['status'], 'stopped_stalled')

    def test_interval_alone_does_not_starve_but_enabled_unknown_and_running_jobs_yield(self):
        fake = self.base / 'fake-root'; (fake / '.job-runtime/config').mkdir(parents=True); (fake / '.job-runtime/engine').mkdir()
        atomic(fake / '.job-runtime/config/runtime.json', {'allocation_files': ['allocation.json']})
        atomic(fake / 'allocation.json', {'jobs': [{'id': 'recovery', 'enabled': True, 'schedule': {'kind': 'interval', 'seconds': 300}},
            {'id': 'historical.fault', 'enabled': False, 'schedule': {'kind': 'once'}}]})
        path = fake / '.job-runtime/engine/schedule.sqlite'
        with sqlite3.connect(path) as db: db.execute('CREATE TABLE slots(job_id TEXT,status TEXT)'); db.execute("INSERT INTO slots VALUES('historical.fault','unknown')")
        before = path.read_bytes()
        self.assertFalse(rc.production_priority(fake, 180)['busy']); self.assertEqual(before, path.read_bytes())
        with sqlite3.connect(path) as db: db.execute("INSERT INTO slots VALUES('recovery','unknown')")
        self.assertTrue(rc.production_priority(fake, 180)['busy'])
