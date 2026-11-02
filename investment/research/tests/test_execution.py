import copy
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from investment.research.execution import PhaseError, run, proposal_schema
from shared.actions import ActionError, resolve
from shared.research_sources.artifacts import SOURCE_STATE, SourceError, read, save
from shared.research_sources.fetch import document_receipt
from shared.research_sources.store import Store


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.source = document_receipt(self.directory, provider='official_document', url='https://www.sec.gov/synthetic',
            identifier='synthetic', published_at='2026-01-01T00:00:00Z',
            raw=('<h1>Explicit synthetic fixture</h1><p>' + 'This source is synthetic. ' * 20 + '</p>').encode())

    def config(self, phases=None):
        return {'schema_version': 1, 'pipeline_id': 'test', 'pipeline_version': '1.0.0',
                'budget': {'max_actions': 3, 'max_model_turns': 3, 'deadline_seconds': 10},
                'phases': phases or [{'id': 'read', 'objective': 'Read the exact bounded passage.', 'mode': 'action',
                    'action': 'evidence.read@1', 'arguments': {'source_ref': {'$bind': 'request.source_ref'}, 'max_chars': 60},
                    'gate': 'action_success'}]}

    def finalizer(self, context):
        return save(self.directory, {'scope': 'test-component', 'phases': context['phase_refs']})

    def agent_phase(self):
        return {'id': 'interpret', 'objective': 'Explain the stated source limitations.', 'mode': 'agent',
            'inputs': {'source': {'$bind': 'phases.read.data.source_ref'}}, 'permitted_actions': ['evidence.read@1'],
            'output_schema': {'type': 'object', 'additionalProperties': False, 'required': ['finding'],
                              'properties': {'finding': {'type': 'string', 'minLength': 1, 'maxLength': 200}}},
            'gate': 'structured_output'}

    def result(self, **kwargs):
        return run(self.config(), {'source_ref': self.source}, output_directory=self.directory,
                   finalizer=self.finalizer, **kwargs)

    def test_real_worker_binding_and_immutable_phase_receipts(self):
        result = self.result()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['counts'], {'actions': 1, 'model_turns': 0})
        self.assertEqual(result['phases']['read']['data']['source_ref'], self.source)
        receipt = read(result['phase_refs']['read'])
        self.assertEqual(receipt['status'], 'accepted')
        self.assertEqual(read(result['input_manifest']['request_ref']), {'source_ref': self.source})
        self.assertTrue(result['report_ref'])
        record = result['action_records'][0]
        self.assertEqual(record['call_id'], 'read:direct')
        self.assertEqual(read(record['arguments_ref'])['source_ref'], self.source)
        self.assertEqual(read(record['outcome_ref'])['data'], result['phases']['read']['data'])
        self.assertEqual(read(record['record_ref'])['execution_ref'], record['execution_ref'])
        self.assertTrue(all(row['occurred_at'] and row['run_id'] == result['run_id'] for row in result['events']))

    def test_missing_and_forward_bindings_block_before_action(self):
        config = self.config(); config['phases'][0]['arguments']['source_ref'] = {'$bind': 'request.missing'}
        with patch('investment.research.execution.invoke') as execute:
            result = run(config, {}, output_directory=self.directory, finalizer=self.finalizer)
            self.assertEqual(result['reason'], 'PIPELINE_BOUND_INPUT_MISSING'); execute.assert_not_called()
        config['phases'][0]['arguments']['source_ref'] = {'$bind': 'phases.future.data.source_ref'}
        result = run(config, {}, output_directory=self.directory, finalizer=self.finalizer)
        self.assertEqual(result['reason'], 'PIPELINE_FORWARD_BINDING')

    def test_invalid_agent_arguments_are_repaired_before_effect_intent(self):
        phases = self.config()['phases'] + [self.agent_phase()]
        calls = []
        def model(prompt, schema):
            context = json.loads(prompt); calls.append(context)
            if len(calls) == 1:
                return {'kind': 'call_action', 'call_id': 'bad_args', 'action': 'evidence.read@1',
                        'arguments': {'source_ref': self.source, 'max_chars': 0}, 'data': None}
            if len(calls) == 2:
                self.assertEqual(context['observations'][-1]['outcome']['error']['code'], 'PIPELINE_ACTION_ARGUMENTS_INVALID')
                return {'kind': 'call_action', 'call_id': 'fixed_args', 'action': 'evidence.read@1',
                        'arguments': {'source_ref': self.source, 'max_chars': 40}, 'data': None}
            return {'kind': 'phase_result', 'call_id': 'done', 'action': None, 'arguments': None,
                    'data': {'finding': 'The explicitly synthetic source was read after correcting the bounded input.'}}
        result = run(self.config(phases), {'source_ref': self.source}, output_directory=self.directory,
                     model_callback=model, finalizer=self.finalizer)
        self.assertEqual(result['status'], 'completed', result.get('reason'))
        self.assertEqual(result['counts'], {'actions': 2, 'model_turns': 3})
        self.assertEqual(len(result['action_records']), 2)
        self.assertNotIn('bad_args', [row['call_id'] for row in result['action_records']])
        self.assertIsNone(read(result['checkpoint_ref'])['pending'])

    def test_action_budget_and_mandatory_finalizer(self):
        config = self.config(); config['budget']['max_actions'] = 0
        result = run(config, {'source_ref': self.source}, output_directory=self.directory, finalizer=self.finalizer)
        self.assertEqual(result['reason'], 'PIPELINE_ACTION_BUDGET')
        with patch('investment.research.execution.invoke') as execute:
            result = run(self.config(), {'source_ref': self.source}, output_directory=self.directory)
            self.assertEqual(result['reason'], 'PIPELINE_FINALIZER_REQUIRED'); execute.assert_not_called()

    def test_agent_callback_and_exact_call_id_results(self):
        phases = self.config()['phases'] + [self.agent_phase()]
        prompts = []
        def model(prompt, schema):
            value = json.loads(prompt); prompts.append(value)
            if not value['observations']:
                return {'kind': 'call_action', 'call_id': 'read_again', 'action': 'evidence.read@1',
                        'arguments': {'source_ref': self.source, 'max_chars': 40}, 'data': None}
            self.assertEqual(value['observations'][0]['call_id'], 'read_again')
            return {'kind': 'phase_result', 'call_id': 'finish', 'action': None, 'arguments': None,
                    'data': {'finding': 'Explicitly synthetic; no business inference.'}}
        result = run(self.config(phases), {'source_ref': self.source}, output_directory=self.directory,
                     finalizer=self.finalizer, model_callback=model)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['counts'], {'actions': 2, 'model_turns': 2})
        self.assertTrue(all(prompt['run_id'] == result['run_id'] for prompt in prompts))
        self.assertEqual(set(prompts[0]['permitted_actions']), {'evidence.read@1'})
        self.assertEqual([r['call_id'] for r in result['action_records']], ['read:direct', 'read_again'])

    def test_provider_schema_closes_real_action_types_and_nullable_optionals(self):
        phase = self.agent_phase()
        schema = proposal_schema(phase, {'evidence.read@1': resolve('evidence.read@1')})
        def inspect(node):
            if isinstance(node, dict):
                if node.get('type') == 'object':
                    self.assertIs(node['additionalProperties'], False)
                    self.assertEqual(set(node['required']), set(node['properties']))
                self.assertNotIn('$ref', node)
                for child in node.values(): inspect(child)
            elif isinstance(node, list):
                for child in node: inspect(child)
        inspect(schema)
        count = []
        def model(prompt, response_schema):
            value = json.loads(prompt)
            self.assertIsInstance(value['permitted_actions']['evidence.read@1']['input_schema'], dict)
            self.assertNotIn('release_manifest', json.dumps(value['permitted_actions']))
            count.append(1)
            if len(count) == 1:
                return {'kind': 'call_action', 'call_id': 'r', 'action': 'evidence.read@1',
                        'arguments': {'source_ref': self.source, 'start': None, 'max_chars': None}, 'data': None}
            self.assertEqual(value['observations'][0]['outcome']['status'], 'success')
            return {'kind': 'phase_result', 'call_id': 'done', 'action': None, 'arguments': None,
                    'data': {'finding': 'Bounded synthetic context.'}}
        result = run(self.config(self.config()['phases'] + [phase]), {'source_ref': self.source},
                     output_directory=self.directory, finalizer=self.finalizer, model_callback=model)
        self.assertEqual(result['status'], 'completed')

    def test_finalizer_receives_actual_action_receipts_not_agent_claims(self):
        observed = []
        def finalizer(context):
            records = context['action_records']
            self.assertEqual(len(records), 1)
            record = read(records[0]['record_ref'])
            args = read(record['arguments_ref']); outcome = read(record['outcome_ref'])
            execution = read(record['execution_ref'])
            self.assertEqual(args['source_ref'], self.source)
            self.assertEqual(outcome['status'], 'success')
            self.assertEqual(execution['action_id'], 'evidence.read')
            observed.append(record['call_id'])
            return self.finalizer(context)
        result = run(self.config(), {'source_ref': self.source}, output_directory=self.directory, finalizer=finalizer)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(observed, ['read:direct'])

    def test_final_result_may_reuse_label_but_action_ids_cannot_repeat(self):
        phases = self.config()['phases'] + [self.agent_phase()]
        def model(prompt, schema):
            observations = json.loads(prompt)['observations']
            if not observations:
                return {'kind': 'call_action', 'call_id': 'same_label', 'action': 'evidence.read@1',
                        'arguments': {'source_ref': self.source, 'max_chars': 40}, 'data': None}
            return {'kind': 'phase_result', 'call_id': 'same_label', 'action': None, 'arguments': None,
                    'data': {'finding': 'Read source with explicit limitations.'}}
        result = run(self.config(phases), {'source_ref': self.source}, output_directory=self.directory,
                     finalizer=self.finalizer, model_callback=model)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['counts']['model_turns'], 2)
        repeat = lambda *args: {'kind': 'call_action', 'call_id': 'same_label', 'action': 'evidence.read@1',
                               'arguments': {'source_ref': self.source, 'max_chars': 40}, 'data': None}
        blocked = run(self.config(phases), {'source_ref': self.source}, output_directory=self.directory,
                      finalizer=self.finalizer, model_callback=repeat)
        self.assertEqual(blocked['reason'], 'PIPELINE_MODEL_BUDGET')
        self.assertEqual(blocked['counts']['actions'], 2)  # direct read + one agent action
        self.assertIn('PIPELINE_CALL_ID_REUSED', [e.get('code') for e in blocked['events']])

    def test_invalid_agent_result_bounded_repair_and_missing_callback(self):
        phases = self.config()['phases'] + [self.agent_phase()]
        config = self.config(phases)
        result = run(config, {'source_ref': self.source}, output_directory=self.directory, finalizer=self.finalizer)
        self.assertEqual(result['reason'], 'PIPELINE_MODEL_CALLBACK_REQUIRED')
        bad = lambda *args: {'kind': 'phase_result', 'call_id': 'same', 'action': None, 'arguments': None,
                             'data': {'finding': 12}}
        result = run(config, {'source_ref': self.source}, output_directory=self.directory,
                     finalizer=self.finalizer, model_callback=bad)
        self.assertEqual(result['reason'], 'PIPELINE_MODEL_BUDGET')
        self.assertEqual(result['counts']['model_turns'], 3)
        self.assertNotIn('interpret', result['phases'])

    def test_numeric_computation_requires_critical_guard(self):
        config = self.config([{'id': 'compare', 'objective': 'Compare critical inputs.', 'mode': 'action',
            'action': 'evidence.compare_numeric@1', 'arguments': {'packet_ref': {'$bind': 'request.packet_ref'}},
            'gate': 'action_success'}])
        for guard, expected in [(None, 'PIPELINE_CRITICAL_GUARD_REQUIRED'),
                                (lambda *args: {'status': 'restricted'}, 'PIPELINE_CRITICAL_INPUT_BLOCKED')]:
            with patch('investment.research.execution.invoke') as execute:
                result = run(config, {'packet_ref': save(self.directory, {})}, output_directory=self.directory,
                             finalizer=self.finalizer, critical_guard=guard)
                self.assertEqual(result['reason'], expected); execute.assert_not_called()

    def test_lifecycle_change_at_final_gate_blocks_publication(self):
        store = Store(self.directory / 'store')
        old = store.create('create', 'obs', {'source_ref': self.source, 'entity': 'AAA', 'metric': 'revenue'})
        def finalizer(context):
            store.withdraw('withdraw', 'obs', expected_revision=old['revision'], reason='Test publication race')
            current = store.read('obs', include_withdrawn=True)
            if current['lifecycle_revision'] != old['lifecycle_revision']:
                raise SourceError('PUBLISH_LIFECYCLE_CHANGED')
            return self.finalizer(context)
        result = run(self.config(), {'source_ref': self.source}, output_directory=self.directory, finalizer=finalizer)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['reason'], 'PUBLISH_LIFECYCLE_CHANGED')
        self.assertIsNone(result['final_ref'])
        self.assertEqual(store.read('obs', revision=1)['revision'], 1)

    def test_external_output_schema_and_unknown_phase_fields_rejected(self):
        phases = self.config()['phases'] + [self.agent_phase()]
        phases[1]['output_schema']['$ref'] = 'https://example.com/untrusted'
        result = run(self.config(phases), {'source_ref': self.source}, output_directory=self.directory,
                     finalizer=self.finalizer, model_callback=lambda *args: {})
        self.assertEqual(result['reason'], 'PIPELINE_EXTERNAL_SCHEMA_FORBIDDEN')
        config = self.config(); config['phases'][0]['shell'] = 'false'
        with self.assertRaisesRegex(PhaseError, 'PIPELINE_CONFIG_INVALID'):
            run(config, {}, output_directory=self.directory, finalizer=self.finalizer)

    def test_checkpoint_resume_skips_completed_phase_and_preserves_run(self):
        second = dict(self.config()['phases'][0], id='read2')
        config = self.config(self.config()['phases'] + [second])
        first = run(config, {'source_ref': self.source}, output_directory=self.directory,
                    finalizer=self.finalizer, pause_after_phase='read')
        self.assertEqual(first['status'], 'paused')
        self.assertEqual(first['counts']['actions'], 1)
        checkpoint = read(first['checkpoint_ref'])
        self.assertIsNone(checkpoint['pending'])
        from investment.research import execution
        actual_invoke = execution.invoke
        with patch('investment.research.execution.invoke', wraps=actual_invoke) as called:
            resumed = run(config, {'source_ref': self.source}, output_directory=self.directory,
                          finalizer=self.finalizer, checkpoint_ref=first['checkpoint_ref'])
        self.assertEqual(resumed['status'], 'completed', resumed['reason'])
        self.assertEqual(resumed['run_id'], first['run_id'])
        self.assertEqual(resumed['counts'], {'actions': 2, 'model_turns': 0})
        self.assertEqual(called.call_count, 1)
        self.assertEqual(called.call_args.args[0]['request_id'], first['run_id'] + ':read2:direct')
        self.assertEqual(resumed['phase_refs']['read'], first['phase_refs']['read'])
        self.assertEqual(read(resumed['checkpoint_ref'])['deadline_at'], checkpoint['deadline_at'])

    def test_resume_input_config_and_directory_changes_are_rejected(self):
        first = run(self.config(), {'source_ref': self.source}, output_directory=self.directory,
                    finalizer=self.finalizer, pause_after_phase='read')
        for config, request, directory, reason in [
                (dict(self.config(), pipeline_version='1.0.1'), {'source_ref': self.source}, self.directory, 'PIPELINE_CHECKPOINT_INPUT_CHANGED'),
                (self.config(), {'source_ref': self.source, 'extra': True}, self.directory, 'PIPELINE_CHECKPOINT_INPUT_CHANGED'),
                (self.config(), {'source_ref': self.source}, self.directory / 'other', 'PIPELINE_CHECKPOINT_SUPERSEDED')]:
            with patch('investment.research.execution.invoke') as invoked:
                result = run(config, request, output_directory=directory, checkpoint_ref=first['checkpoint_ref'], finalizer=self.finalizer)
            self.assertEqual(result['reason'], reason); invoked.assert_not_called()

    def test_resume_rejects_tampered_accepted_output_before_dispatch(self):
        first = run(self.config(), {'source_ref': self.source}, output_directory=self.directory,
                    finalizer=self.finalizer, pause_after_phase='read')
        Path(first['phase_refs']['read']['path']).write_text('{}')
        with patch('investment.research.execution.invoke') as invoked:
            resumed = run(self.config(), {'source_ref': self.source}, output_directory=self.directory,
                          checkpoint_ref=first['checkpoint_ref'], finalizer=self.finalizer)
        self.assertEqual(resumed['reason'], 'ARTIFACT_HASH_MISMATCH'); invoked.assert_not_called()

    def test_resume_uses_frozen_release_after_current_catalog_retires_it(self):
        from shared.actions import runtime
        phases = self.config()['phases'] + [dict(self.config()['phases'][0], id='read2')]
        config = self.config(phases)
        first = run(config, {'source_ref': self.source}, output_directory=self.directory,
                    finalizer=self.finalizer, pause_after_phase='read')
        pinned = read(first['checkpoint_ref'])['descriptors']['evidence.read@1']
        self.assertIn('release_ref', pinned)
        retired = dict(runtime.SPECS['evidence.read'], lifecycle='retired')
        with patch.dict(runtime.SPECS, {'evidence.read': retired}), patch.object(runtime, 'manifest', side_effect=AssertionError('Mutable release consulted')):
            resumed = run(config, {'source_ref': self.source}, output_directory=self.directory,
                          finalizer=self.finalizer, checkpoint_ref=first['checkpoint_ref'])
        self.assertEqual(resumed['status'], 'completed', resumed['reason'])
        self.assertEqual(read(resumed['action_records'][1]['request_ref'])['release_ref'], pinned['release_ref'])

    def test_resume_preserves_deadline_and_action_model_budgets(self):
        second = dict(self.config()['phases'][0], id='read2')
        config = self.config(self.config()['phases'] + [second]); config['budget']['max_actions'] = 1
        first = run(config, {'source_ref': self.source}, output_directory=self.directory,
                    finalizer=self.finalizer, pause_after_phase='read')
        with patch('investment.research.execution.invoke') as invoked:
            resumed = run(config, {'source_ref': self.source}, output_directory=self.directory,
                          finalizer=self.finalizer, checkpoint_ref=first['checkpoint_ref'])
        self.assertEqual(resumed['reason'], 'PIPELINE_ACTION_BUDGET'); self.assertEqual(resumed['counts']['actions'], 1)
        invoked.assert_not_called()
        # A separate paused run expires using its original absolute deadline.
        first = run(self.config(), {'source_ref': self.source}, output_directory=self.directory,
                    finalizer=self.finalizer, pause_after_phase='read')
        end = datetime.fromisoformat(read(first['checkpoint_ref'])['deadline_at']).timestamp()
        with patch('investment.research.execution.time.time', return_value=end + 1), patch('investment.research.execution.invoke') as invoked:
            expired = run(self.config(), {'source_ref': self.source}, output_directory=self.directory,
                          finalizer=self.finalizer, checkpoint_ref=first['checkpoint_ref'])
        self.assertEqual(expired['reason'], 'PIPELINE_DEADLINE'); invoked.assert_not_called()
        phase = self.agent_phase(); phase['id'] = 'agent1'; phase['inputs'] = {}
        phase2 = dict(phase, id='agent2')
        config = self.config([phase, phase2]); config['budget']['max_model_turns'] = 1
        model = lambda *args: {'kind': 'phase_result', 'call_id': 'done', 'action': None, 'arguments': None, 'data': {'finding': 'Explicit fixture'}}
        first = run(config, {}, output_directory=self.directory, finalizer=self.finalizer,
                    model_callback=model, pause_after_phase='agent1')
        with patch('investment.research.execution.invoke') as invoked:
            resumed = run(config, {}, output_directory=self.directory, finalizer=self.finalizer,
                          model_callback=model, checkpoint_ref=first['checkpoint_ref'])
        self.assertEqual(resumed['reason'], 'PIPELINE_MODEL_BUDGET'); self.assertEqual(resumed['counts']['model_turns'], 1)
        invoked.assert_not_called()

    def test_pending_action_is_fenced_and_older_checkpoint_cannot_bypass(self):
        phases = self.config()['phases'] + [dict(self.config()['phases'][0], id='read2')]
        config = self.config(phases)
        first = run(config, {'source_ref': self.source}, output_directory=self.directory,
                    finalizer=self.finalizer, pause_after_phase='read')
        with patch('investment.research.execution.invoke', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                run(config, {'source_ref': self.source}, output_directory=self.directory,
                    finalizer=self.finalizer, checkpoint_ref=first['checkpoint_ref'])
        head = json.loads((self.directory / '.pipeline' / first['run_id'] / 'head.json').read_text())
        self.assertEqual(read(head['checkpoint_ref'])['pending']['kind'], 'action')
        for ref, expected in [(first['checkpoint_ref'], 'PIPELINE_CHECKPOINT_SUPERSEDED'),
                              (head['checkpoint_ref'], 'PIPELINE_CHECKPOINT_UNCERTAIN')]:
            with patch('investment.research.execution.invoke') as invoked:
                blocked = run(config, {'source_ref': self.source}, output_directory=self.directory,
                              finalizer=self.finalizer, checkpoint_ref=ref)
            self.assertEqual(blocked['reason'], expected); invoked.assert_not_called()

    def test_pending_model_is_fenced_and_finalizer_rechecks_after_pause(self):
        config = self.config(self.config()['phases'] + [self.agent_phase()])
        first = run(config, {'source_ref': self.source}, output_directory=self.directory,
                    finalizer=self.finalizer, model_callback=lambda *args: None, pause_after_phase='read')
        with self.assertRaises(KeyboardInterrupt):
            run(config, {'source_ref': self.source}, output_directory=self.directory,
                finalizer=self.finalizer, model_callback=lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()),
                checkpoint_ref=first['checkpoint_ref'])
        head = json.loads((self.directory / '.pipeline' / first['run_id'] / 'head.json').read_text())
        self.assertEqual(read(head['checkpoint_ref'])['pending']['kind'], 'model')
        called = []
        resumed = run(config, {'source_ref': self.source}, output_directory=self.directory,
                      finalizer=self.finalizer, model_callback=lambda *args: called.append(True), checkpoint_ref=head['checkpoint_ref'])
        self.assertEqual(resumed['reason'], 'PIPELINE_CHECKPOINT_UNCERTAIN'); self.assertFalse(called)
        store = Store(self.directory / 'store')
        record = store.create('create-resume', 'obs-resume', {'source_ref': self.source})
        requirement = save(self.directory, {'id': 'critical'})
        finalizer = lambda context: save(self.directory, store.commit_snapshot('publish-resume', requirement,
            [{'observation_id': record['id'], 'revision': record['revision'], 'lifecycle_revision': record['lifecycle_revision']}]))
        first = run(self.config(), {'source_ref': self.source}, output_directory=self.directory,
                    finalizer=finalizer, pause_after_phase='read')
        store.withdraw('withdraw-resume', record['id'], record['revision'], 'Changed while paused')
        resumed = run(self.config(), {'source_ref': self.source}, output_directory=self.directory,
                      finalizer=finalizer, checkpoint_ref=first['checkpoint_ref'])
        self.assertEqual(resumed['reason'], 'SNAPSHOT_DEPENDENCY_CHANGED')
        self.assertEqual(resumed['counts']['actions'], 1)

    def test_completed_resume_is_read_only_and_lock_blocks_competing_resume(self):
        first = self.result()
        with patch('investment.research.execution.invoke') as invoked, patch.object(self, 'finalizer') as finalizer:
            resumed = run(self.config(), {'source_ref': self.source}, output_directory=self.directory,
                          finalizer=finalizer, checkpoint_ref=first['checkpoint_ref'])
        self.assertEqual(resumed['status'], 'completed'); invoked.assert_not_called(); finalizer.assert_not_called()
        fd = os.open(self.directory / '.pipeline' / first['run_id'] / 'lock', os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            busy = run(self.config(), {'source_ref': self.source}, output_directory=self.directory,
                       finalizer=self.finalizer, checkpoint_ref=first['checkpoint_ref'])
        finally: os.close(fd)
        self.assertEqual(busy['reason'], 'PIPELINE_RUN_BUSY')

    def test_unknown_action_exception_stops_agent_repair_loop(self):
        phase = self.agent_phase(); phase['inputs'] = {}
        calls = []
        def model(*args):
            calls.append(True)
            return {'kind': 'call_action', 'call_id': 'uncertain', 'action': 'evidence.read@1',
                    'arguments': {'source_ref': self.source}, 'data': None}
        with patch('investment.research.execution.invoke', side_effect=ActionError('SIMULATED_ACTION_UNKNOWN')) as invoked:
            result = run(self.config([phase]), {}, output_directory=self.directory,
                         model_callback=model, finalizer=self.finalizer)
        self.assertEqual(result['reason'], 'SIMULATED_ACTION_UNKNOWN')
        self.assertEqual(len(calls), 1); self.assertEqual(invoked.call_count, 1)
        self.assertEqual(read(result['checkpoint_ref'])['pending']['kind'], 'action')
        resumed = run(self.config([phase]), {}, output_directory=self.directory,
                      model_callback=model, finalizer=self.finalizer, checkpoint_ref=result['checkpoint_ref'])
        self.assertEqual(resumed['reason'], 'PIPELINE_CHECKPOINT_UNCERTAIN')
        self.assertEqual(len(calls), 1)

    def test_accepted_numeric_guard_rechecked_before_finalization_after_resume(self):
        row = {'subject': 'AAA', 'metric': 'revenue', 'definition': 'reported revenue', 'unit': 'USD millions',
            'basis': 'reported', 'period': {'start': '2026-01-01', 'end': '2026-03-31'}, 'value': '100',
            'observed_at': '2026-03-31T00:00:00Z', 'available_at': '2026-04-15T00:00:00Z',
            'source': {'origin': 'issuer', 'provider': 'filing', 'upstream_family': 'issuer',
                       'ref': 'explicit-synthetic-fixture', 'sha256': 'a' * 64}}
        packet = {'version': '2026-10-24-evidence-crosscheck-1', 'as_of': '2026-04-30T00:00:00Z',
            'comparison_kind': 'numeric', 'max_age_seconds': 10000000, 'max_time_skew_seconds': 0,
            'absolute_tolerance': '0', 'relative_tolerance': '0', 'require_source_hashes': True,
            'observations': [row, copy.deepcopy(row)]}
        request = {'packet_ref': save(self.directory, packet)}
        config = self.config([{'id': 'compare', 'objective': 'Compare exact synthetic critical inputs.', 'mode': 'action',
            'action': 'evidence.compare_numeric@1', 'arguments': {'packet_ref': {'$bind': 'request.packet_ref'}},
            'gate': 'action_success'}])
        guards = []
        def guard(action, arguments, context):
            guards.append(action)
            return {'status': 'supported', 'receipt_ref': save(self.directory, {'synthetic': True, 'check': len(guards)})}
        first = run(config, request, output_directory=self.directory, finalizer=self.finalizer,
                    critical_guard=guard, pause_after_phase='compare')
        self.assertEqual(first['status'], 'paused'); self.assertEqual(len(guards), 1)
        with patch('investment.research.execution.invoke') as invoked, patch.object(self, 'finalizer') as finalizer:
            resumed = run(config, request, output_directory=self.directory, finalizer=finalizer,
                          critical_guard=lambda *args: {'status': 'restricted'}, checkpoint_ref=first['checkpoint_ref'])
        self.assertEqual(resumed['reason'], 'PIPELINE_CRITICAL_INPUT_BLOCKED')
        self.assertEqual(resumed['counts']['actions'], 1); invoked.assert_not_called(); finalizer.assert_not_called()
        complete = run(config, request, output_directory=self.directory, finalizer=self.finalizer, critical_guard=guard)
        self.assertEqual(complete['status'], 'completed', complete['reason'])
        self.assertEqual(len(guards), 3)
        self.assertEqual(len([e for e in complete['events'] if e['event_type'] == 'critical_input_rechecked']), 1)


if __name__ == '__main__': unittest.main()
