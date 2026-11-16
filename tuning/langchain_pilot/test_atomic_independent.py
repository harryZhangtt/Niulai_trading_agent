"""Independent discriminating contract tests; no provider/server/cloud writes.

Cloud clients are in-memory fakes. Temporary state is workspace-owned. Test
oracles are requirement-derived exact arithmetic and frozen roster values.
"""
from __future__ import annotations

import asyncio
from contextlib import nullcontext, contextmanager
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from fractions import Fraction
import hashlib
import inspect
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid5
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.load.dump import dumpd
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from langsmith import Client
from langsmith.run_trees import RunTree

from tuning.langchain_pilot import atomic, atomic_cloud, graph, observability
from tuning.langchain_pilot import serve
from tuning.langchain_pilot.session_engine import respond, pending
from tuning.langchain_pilot.session_model import (
    SessionChatModel, SessionModelError, canonical, configure, private_read,
    private_write, response_message)
from tuning.langchain_pilot.smoke import CASE

ROOT = Path(__file__).resolve().parents[2]
TEMP = ROOT / '.langchain-pilot/tmp'
CANARY = 'independent-private-canary-DO-NOT-EXPORT'


def receipt_state(**changes):
    result = {'case_id': CASE['case_id'], 'enterprise_pv': '100',
              'equity_pv': '100', 'nonoperating_pv': '0', 'per_share': '10'}
    result.update(changes)
    tool_id = 'independent-tool'
    artifact = {'schema_version': 2, 'case_sha256': hashlib.sha256(canonical(CASE).encode()).hexdigest(),
                'tool_call_id': tool_id, 'execution_thread_id': 'independent-thread'}
    return {'case': deepcopy(CASE), 'receipt_version': 2,
            'execution_thread_id': 'independent-thread', 'messages': [
                AIMessage(content='', tool_calls=[{'name': 'calculate_valuation', 'args': {}, 'id': tool_id}]),
                ToolMessage(content=json.dumps(result), name='calculate_valuation',
                            tool_call_id=tool_id, artifact=artifact),
                AIMessage(content=json.dumps({'per_share': result['per_share'], 'synthetic': True}))]}


class Capture(BaseCallbackHandler):
    def __init__(self): self.rows = []
    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kw):
        self.rows.append(('chain', str(run_id), str(parent_run_id) if parent_run_id else None, kw.get('name'), inputs))
    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kw):
        self.rows.append(('model', str(run_id), str(parent_run_id) if parent_run_id else None, None, messages))
    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kw):
        self.rows.append(('tool', str(run_id), str(parent_run_id) if parent_run_id else None, serialized.get('name'), input_str))
    def on_tool_error(self, error, *, run_id, **kw):
        self.rows.append(('tool_error', str(run_id), None, None, str(error)))


class ArithmeticReceiptTests(unittest.TestCase):
    """AC-003/004/006/007: matching text cannot substitute for exact evidence."""
    def test_exact_receipt_positive_control(self):
        self.assertEqual(graph.verify(receipt_state())['result']['per_share'], '10')

    def test_near_correct_receipt_is_rejected_exactly(self):
        with self.assertRaises(ValueError):
            graph.verify(receipt_state(per_share='10.000000000001'))

    def test_wrong_enterprise_value_with_correct_per_share_is_rejected(self):
        with self.assertRaises(ValueError):
            graph.verify(receipt_state(enterprise_pv='999'))

    def test_wrong_equity_value_with_correct_per_share_is_rejected(self):
        with self.assertRaises(ValueError):
            graph.verify(receipt_state(equity_pv='999'))

    def test_extra_receipt_monetary_claim_is_rejected(self):
        with self.assertRaises(ValueError):
            graph.verify(receipt_state(daily_pnl='123'))

    def test_forged_case_hash_is_rejected(self):
        state = receipt_state()
        state['messages'][1].artifact['case_sha256'] = '0' * 64
        with self.assertRaises(ValueError): graph.verify(state)

    def test_extra_final_claim_is_rejected(self):
        state = receipt_state()
        state['messages'][-1].content = '{"per_share":"10","synthetic":true,"equity":"999"}'
        with self.assertRaises(ValueError): graph.verify(state)

    def test_calculator_gate_rejects_sub_tolerance_wrong_result(self):
        wrong = {'case_id': CASE['case_id'], 'enterprise_pv': '100',
                 'equity_pv': '100', 'nonoperating_pv': '0', 'per_share': '10.000000000001'}
        with patch.object(observability, 'calculate', return_value=wrong):
            with self.assertRaises(ValueError): observability.checked_calculation(CASE)

    def test_frozen_calculator_cases_use_independent_fraction_oracle(self):
        for row in atomic.fixtures('calculator'):
            case = row['inputs']['case']
            if row['outputs']['status'] != 'passed': continue
            with self.subTest(case_id=row['id']):
                actual = graph.calculate(case)
                discount = 1 + Fraction(case['rate'])
                ev = sum(Fraction(v) / discount ** i for i, v in enumerate(case['fcff'], 1))
                ev += Fraction(case['terminal_ev']) / discount ** len(case['fcff'])
                self.assertEqual(Fraction(actual['enterprise_pv']), ev)
                self.assertEqual(Fraction(actual['equity_pv']), ev - Fraction(case['net_debt']))
                self.assertEqual(Fraction(actual['per_share']), (ev - Fraction(case['net_debt'])) / Fraction(case['shares']))


class PublicBoundaryTests(unittest.IsolatedAsyncioTestCase):
    """AC-001/005/013/026: test actual graph values, not schema projection."""
    async def test_raw_unknown_fields_fail_before_export_runner(self):
        exported = []
        async def runner(kind, selected, config, invoke):
            exported.append(selected)
            return await invoke(config), {'status': 'test'}
        value = atomic.make_public_graph('calculator', cloud_runner=runner)
        bad = [{'request': {'case_id': 'nominal'}, 'private': CANARY},
               {'request': {'case_id': 'nominal', 'account': CANARY}},
               {'request': {'case_id': {'path': CANARY}}},
               {'request': {'case_id': 'unknown'}},
               {'request': {'case_id': 'nominal'}, 'metadata': {'nested': CANARY}},
               {'request': {'case_id': 'nominal'}, 'payload': 'x' * 4096}]
        for request in bad:
            with self.subTest(request_shape=list(request)):
                with self.assertRaises(ValueError): await value.ainvoke(request)
        self.assertEqual(exported, [])

    async def test_valid_selector_positive_control_reaches_native_tool(self):
        sink = Capture()
        output = await atomic.make_public_graph('calculator').ainvoke(
            {'request': {'case_id': 'nominal'}}, config={'callbacks': [sink]})
        self.assertEqual(output['result'], {'status': 'passed', 'per_share': '10'})
        self.assertEqual(len([r for r in sink.rows if r[0] == 'tool']), 1)
        self.assertFalse(any(r[0] == 'model' for r in sink.rows))
        self.assertEqual(output['trace']['status'], 'disabled')

    async def test_invalid_fixture_has_no_model_or_tool_call(self):
        sink = Capture()
        output = await atomic.make_public_graph('calculator').ainvoke(
            {'request': {'case_id': 'invalid-shares'}}, config={'callbacks': [sink]})
        self.assertEqual(output['result'], {'status': 'invalid_input'})
        self.assertFalse(any(r[0] in ('model', 'tool') for r in sink.rows))

    async def test_schema_has_closed_outer_and_inner_envelopes(self):
        for kind in atomic.KINDS:
            schema = atomic.make_public_graph(kind).get_input_jsonschema()
            self.assertEqual(schema.get('additionalProperties'), False)
            inner = schema['properties']['request']
            self.assertEqual(inner.get('additionalProperties'), False)
            self.assertEqual(set(inner['properties']), {'case_id'})

    async def test_cooperative_native_model_and_tool_parentage(self):
        TEMP.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP, prefix='independent-session-') as directory:
            binding = configure('independent-host', state=directory)
            value = graph.make_graph(SessionChatModel(state_directory=directory,
                public_fixture_responses=True), checkpointer=InMemorySaver())
            sink = Capture()
            config = {'configurable': {'thread_id': 'independent-native'}, 'callbacks': [sink]}
            pending = await value.ainvoke({'case': CASE}, config=config)
            first = pending['__interrupt__'][0].value
            self.assertEqual(first['binding'], binding)
            tool_reply = {'request_id': first['request_id'], 'binding': binding,
                          'message': {'content': '', 'tool_calls': [{'name': 'calculate_valuation', 'args': {}}]}}
            after_tool = await value.ainvoke(Command(resume=tool_reply), config=config)
            second = after_tool['__interrupt__'][0].value
            self.assertNotEqual(first['request_id'], second['request_id'])
            result = await value.ainvoke(Command(resume={
                'request_id': second['request_id'], 'binding': binding,
                'message': {'content': '{"per_share":"10","synthetic":true}'}}), config=config)
            self.assertEqual(result['result']['status'], 'passed')
            tools = [r for r in sink.rows if r[0] == 'tool']
            self.assertEqual(len(tools), 1)
            nodes = {r[1]: r for r in sink.rows if r[0] in ('chain', 'model', 'tool')}
            self.assertIn(tools[0][2], nodes)
            self.assertTrue(any(r[0] == 'model' for r in sink.rows))
            for row in sink.rows:
                if row[0] in ('tool', 'model'):
                    self.assertIn(row[2], nodes)
            self.assertEqual(value.get_state(config).values['result']['per_share'], '10')

    async def test_tool_failure_diagnostic_does_not_export_private_exception(self):
        sink = Capture()
        # The actual registered tool catches and replaces the private exception.
        from tuning.langchain_pilot.test_graph import model
        with patch.object(graph, 'equity_value', side_effect=RuntimeError(CANARY)):
            with self.assertRaises(Exception):
                await graph.make_graph(model()).ainvoke({'case': CASE}, config={'callbacks': [sink]})
        errors = [r for r in sink.rows if r[0] == 'tool_error']
        self.assertTrue(errors)
        self.assertNotIn(CANARY, repr(errors))

    async def test_deterministic_tool_failure_has_closed_diagnostic(self):
        with patch.object(graph, 'equity_value', side_effect=RuntimeError(CANARY)):
            try:
                result = await atomic.make_public_graph('calculator').ainvoke(
                    {'request': {'case_id': 'nominal'}})
            except Exception as error:
                self.assertNotIn(CANARY, str(error))
            else:
                self.assertNotIn(CANARY, repr(result))
                self.assertNotEqual(result['result']['status'], 'passed')

    async def test_cooperative_model_loop_is_capped_at_three_requests(self):
        TEMP.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP, prefix='independent-cap-') as directory:
            binding = configure('independent-cap-host', state=directory)
            value = graph.make_graph(SessionChatModel(state_directory=directory,
                public_fixture_responses=True), checkpointer=InMemorySaver())
            config = {'configurable': {'thread_id': 'independent-cap'}}
            output = await value.ainvoke({'case': CASE}, config=config)
            requests = []
            for index in range(3):
                request = output['__interrupt__'][0].value
                requests.append(request['request_id'])
                command = Command(resume={'request_id': request['request_id'], 'binding': binding,
                    'message': {'content': '', 'tool_calls': [{'name': 'calculate_valuation', 'args': {}}]}})
                if index < 2:
                    output = await value.ainvoke(command, config=config)
                else:
                    with self.assertRaises(Exception) as caught:
                        await value.ainvoke(command, config=config)
                    self.assertIn('limit', str(caught.exception).lower())
            self.assertEqual(len(set(requests)), 3)


class SessionConcurrencyTests(unittest.TestCase):
    """AC-009: force two same-request admissions at the owning lock boundary."""
    def test_two_simultaneous_replies_admit_one_and_keep_case_unchanged(self):
        from tuning.langchain_pilot.test_session_cli import GraphClient
        TEMP.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP, prefix='independent-concurrent-') as directory:
            state = Path(directory)
            binding = configure('independent-concurrent-host', state=state)
            value = graph.make_graph(SessionChatModel(state_directory=directory,
                public_fixture_responses=True), checkpointer=InMemorySaver())
            client = GraphClient(value, 'independent-concurrent')
            asyncio.run(value.ainvoke({'case': CASE}, config=client.config))
            request = pending(client, client.thread, state_directory=state)['request']
            envelope = {'request_id': request['request_id'], 'binding': binding,
                        'message': {'content': '', 'tool_calls': [{'name': 'calculate_valuation', 'args': {}}]}}
            entered = threading.Event(); release = threading.Event()
            original = client.runs.stream
            def stream(*a, **kw):
                entered.set()
                if not release.wait(timeout=5): raise RuntimeError('bounded barrier timed out')
                yield from original(*a, **kw)
            client.runs.stream = stream
            outcomes = []
            def invoke():
                try:
                    outcomes.append(respond(client, client.thread, envelope,
                        session_id=binding['session_id'], revision=binding['revision'], state_directory=state))
                except Exception as error: outcomes.append(error)
            first = threading.Thread(target=invoke)
            first.start()
            self.assertTrue(entered.wait(timeout=5))
            second = threading.Thread(target=invoke)
            second.start(); second.join(timeout=5)
            self.assertFalse(second.is_alive())
            release.set(); first.join(timeout=5)
            self.assertFalse(first.is_alive())
            self.assertEqual(len([x for x in outcomes if isinstance(x, BlockingIOError)]), 1)
            self.assertEqual(len([x for x in outcomes if isinstance(x, dict)]), 1)
            latest = value.get_state(client.config).values
            self.assertEqual(latest['case'], CASE)
            latest_request = pending(client, client.thread, state_directory=state)['request']
            self.assertEqual(len([m for m in latest_request['messages'] if m['type'] == 'tool']), 1)


class NativeTraceTests(unittest.IsolatedAsyncioTestCase):
    """Capture real PublicTracer RunTrees at post/patch; networking is replaced."""
    async def exercise(self, *, delivery_unknown=False):
        selected = atomic.fixtures('calculator')[0]
        captures = []
        client = Client(api_key='synthetic-never-dispatched', auto_batch_tracing=False,
                        omit_traced_runtime_info=True)
        profile = {'project_id': str(uuid4()), 'project_name': 'independent-no-network',
                   'examples': {'nominal': str(uuid4())}, 'roster_sha256': 'synthetic',
                   'prompt_commit': 'synthetic', 'prompt_sha256': 'synthetic',
                   'sources': atomic_cloud.fingerprints()}
        thread = str(uuid4())
        invoked = []
        async def invoke(config):
            invoked.append(1)
            return await atomic.calculator_runnable().ainvoke(selected['inputs'], config=config)
        def post(run, *a, **kw):
            captures.append({'id': str(run.id), 'parent': str(run.parent_run_id) if run.parent_run_id else None,
                             'name': run.name, 'type': run.run_type, 'inputs': deepcopy(run.inputs),
                             'outputs': deepcopy(run.outputs), 'error': run.error, 'tags': run.tags,
                             'extra': deepcopy(run.extra)})
            if delivery_unknown: raise TimeoutError(CANARY)
        def update(run, *a, **kw):
            captures.append({'update': True, 'id': str(run.id), 'parent': str(run.parent_run_id) if run.parent_run_id else None,
                             'name': run.name, 'type': run.run_type, 'inputs': deepcopy(run.inputs),
                             'outputs': deepcopy(run.outputs), 'error': run.error, 'tags': run.tags,
                             'extra': deepcopy(run.extra)})
        TEMP.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP, prefix='independent-native-tree-') as directory:
            state = Path(directory)
            with patch.object(atomic_cloud, 'state_root', return_value=state), \
                 patch.object(atomic_cloud, 'local_profile', return_value=profile), \
                 patch.object(observability, 'client', return_value=client), \
                 patch.object(RunTree, 'post', post), patch.object(RunTree, 'patch', update):
                result, trace = await atomic_cloud.traced_call('calculator', selected,
                    {'configurable': {'thread_id': thread}}, invoke)
                receipts = [private_read(p) for p in (state / 'calculator/traces').glob('*.json')]
                self.assertEqual(len(receipts), 1)
                self.assertEqual(result, {'status': 'passed', 'per_share': '10'})
                receipt = receipts[0]
                if delivery_unknown:
                    self.assertEqual(trace['status'], 'unknown')
                    self.assertEqual(receipt['status'], 'unknown')
                    self.assertEqual(receipt['execution_outcome'], 'completed')
                    before = deepcopy(receipt)
                    with self.assertRaisesRegex(ValueError, 'RECONCILE_BEFORE_RESUME'):
                        await atomic_cloud.traced_call('calculator', selected,
                            {'configurable': {'thread_id': thread}}, invoke)
                    self.assertEqual(invoked, [1])
                    self.assertEqual(private_read(next((state / 'calculator/traces').glob('*.json'))), before)
                else:
                    self.assertEqual(trace['status'], 'recorded_pending_readback')
                    self.assertEqual(receipt['status'], 'completed')
                self.assertNotIn(CANARY, repr(captures))
                return captures, receipt, trace

    async def test_native_deterministic_root_tool_and_receipt_ids_are_consistent(self):
        rows, receipt, trace = await self.exercise()
        starts = [r for r in rows if not r.get('update')]
        roots = [r for r in starts if r['parent'] is None]
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]['id'], trace['run_id'])
        self.assertEqual(roots[0]['name'], 'calculator')
        identities = {r['id'] for r in starts}
        self.assertEqual(set(receipt['native_run_ids']), identities)
        self.assertEqual(len([r for r in starts if r['type'] == 'tool']), 1)
        self.assertFalse(any(r['type'] == 'llm' for r in starts))
        for row in starts:
            if row['parent'] is not None: self.assertIn(row['parent'], identities)
            self.assertEqual(row['extra']['metadata']['graph_thread_id'], receipt['graph_thread_id'])
            self.assertEqual(row['extra']['metadata']['model_identity'], 'no_model_call')

    async def test_unknown_native_export_fences_repeat_execution(self):
        await self.exercise(delivery_unknown=True)


class Dump(SimpleNamespace):
    def model_dump(self, **kw):
        def encode(value):
            if isinstance(value, (UUID, datetime)): return str(value)
            if isinstance(value, Dump): return value.model_dump(**kw)
            if isinstance(value, list): return [encode(v) for v in value]
            if isinstance(value, dict): return {k: encode(v) for k, v in value.items()}
            return value
        return {k: encode(v) for k, v in vars(self).items()}


class NativeSessionTransportTests(unittest.IsolatedAsyncioTestCase):
    """Observe actual cooperative model callbacks; RunTree networking is replaced."""
    async def capture_pending_segment(self):
        TEMP.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEMP, prefix='independent-session-transport-') as directory:
            state = Path(directory)
            binding_path = state / (CANARY + '-session')
            configure('independent-transport-host', state=binding_path)
            kind = 'calculator_session'
            selected = atomic.fixtures(kind)[0]
            profile = {'project_id': str(uuid4()), 'project_name': 'independent-session-no-network',
                       'candidate': state.name, 'candidate_sha256': observability.digest(atomic_cloud.fingerprints()),
                       'examples': {'nominal': str(uuid4())}, 'roster_sha256': observability.digest(atomic_cloud.roster(kind)),
                       'prompt_commit': 'synthetic-pinned', 'prompt_sha256': observability.digest(atomic_cloud.prompt_text(kind)),
                       'sources': atomic_cloud.fingerprints()}
            client = Client(api_key='synthetic-never-dispatched', auto_batch_tracing=False,
                            omit_traced_runtime_info=True)
            posted = []
            def post(run, *args, **kw):
                posted.append({'id': str(run.id), 'parent': str(run.parent_run_id) if run.parent_run_id else None,
                               'name': run.name, 'run_type': run.run_type, 'error': run.error,
                               'serialized': deepcopy(run.serialized), 'extra': deepcopy(run.extra),
                               'trace_id': str(getattr(run, 'trace_id', None)),
                               'inputs_repr': repr(run.inputs), 'outputs_repr': repr(run.outputs)})
            async def runner(kind, selected, config, invoke):
                return await atomic_cloud.traced_call(kind, selected, config, invoke)
            value = atomic.make_public_graph(kind, cloud_runner=runner,
                model=SessionChatModel(state_directory=str(binding_path), public_fixture_responses=True))
            value.checkpointer = InMemorySaver()
            config = {'configurable': {'thread_id': str(uuid4())}}
            with patch.object(atomic_cloud, 'state_root', return_value=state), \
                 patch.object(atomic_cloud, 'local_profile', return_value=profile), \
                 patch.object(observability, 'client', return_value=client), \
                 patch.object(RunTree, 'post', post), patch.object(RunTree, 'patch', post):
                output = await value.ainvoke({'request': {'case_id': selected['id']}}, config=config)
            self.assertTrue(output['__interrupt__'])
            receipts = [private_read(path) for path in (state / kind / 'traces').glob('*.json')]
            self.assertEqual(len(receipts), 1)
            self.assertEqual(receipts[0]['execution_outcome'], 'waiting')
            return posted, receipts[0]

    async def test_actual_pending_session_export_ids_equal_native_receipt(self):
        posted, saved = await self.capture_pending_segment()
        self.assertEqual({row['id'] for row in posted}, set(saved['native_run_ids']))

    async def test_actual_pending_session_exports_no_private_model_path(self):
        posted, saved = await self.capture_pending_segment()
        self.assertNotIn(CANARY, canonical(posted))
        errors = [row['error'] for row in posted if row['error']]
        self.assertTrue(errors)
        self.assertTrue(all(error in ('ATOMIC_COOPERATIVE_WAIT', 'ATOMIC_CONTROLLED_ERROR') for error in errors))

    async def test_actual_native_model_parent_belongs_to_owned_tree(self):
        posted, saved = await self.capture_pending_segment()
        nodes = {row['id']: row for row in posted}
        models = [row for row in nodes.values() if row['run_type'] == 'llm']
        self.assertTrue(models)
        for model in models:
            self.assertEqual(model['trace_id'], saved['run_id'])
            self.assertIn(model['parent'], nodes)
            seen = set(); current = model
            while current['id'] != saved['run_id']:
                self.assertNotIn(current['id'], seen)
                seen.add(current['id'])
                self.assertIn(current['parent'], nodes)
                current = nodes[current['parent']]
            self.assertIsNone(current['parent'])


class FakeCloud:
    """Only in-memory state; enough SDK shape for the boundary under test."""
    def __init__(self, kind='calculator'):
        self.kind = kind
        self.project_id = UUID('11111111-1111-1111-1111-111111111111')
        self.dataset_id = UUID('22222222-2222-2222-2222-222222222222')
        self.calls = []
        self.identity = None
        self.fail_prompt = False
        self.rows = deepcopy(atomic_cloud.roster(kind))
    def create_project(self, name, metadata, **kw):
        self.calls.append('create_project'); self.identity = metadata
        return self.read_project(project_name=name)
    def read_project(self, **kw):
        self.calls.append('read_project')
        return Dump(id=self.project_id, extra={'metadata': self.identity}, name=kw.get('project_name'))
    def create_dataset(self, name, metadata, **kw):
        self.calls.append('create_dataset'); self.identity = metadata
        return self.read_dataset(dataset_name=name)
    def read_dataset(self, **kw):
        self.calls.append('read_dataset')
        return Dump(id=self.dataset_id, metadata=self.identity)
    def push_prompt(self, *a, **kw):
        self.calls.append('push_prompt')
        if self.fail_prompt: raise TimeoutError('unknown synthetic acknowledgement')
    def create_examples(self, **kw): self.calls.append('create_examples')
    def pull_prompt_commit(self, *a, **kw): return Dump(commit_hash='pinned-commit')
    def pull_prompt(self, *a, **kw):
        return ChatPromptTemplate.from_messages([('system', atomic_cloud.prompt_text(self.kind))])
    def list_examples(self, **kw):
        return [Dump(id=uuid5(self.dataset_id, row['id']), inputs=deepcopy(row['inputs']),
                     outputs=deepcopy(row['outputs']), metadata={'fixture_sha256': row['fixture_sha256']},
                     modified_at=datetime(2026, 11, 15, tzinfo=timezone.utc)) for row in self.rows]


class CloudIntegrityTests(unittest.TestCase):
    """AC-029/030/031/032: readback must reject plausible favorable substitutions."""
    def setUp(self):
        TEMP.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=TEMP, prefix='independent-cloud-')
        self.root = Path(self.directory.name)
        self.patcher = patch.object(atomic_cloud, 'state_root', return_value=self.root)
        self.patcher.start()
    def tearDown(self): self.patcher.stop(); self.directory.cleanup()

    def test_bootstrap_nominal_identity_positive_control(self):
        cloud = FakeCloud()
        profile = atomic_cloud.bootstrap(cloud, 'calculator')
        self.assertEqual(profile['project_id'], str(cloud.project_id))
        self.assertEqual(profile['dataset_id'], str(cloud.dataset_id))
        self.assertEqual(private_read(self.root / 'calculator/bootstrap.json')['status'], 'verified')

    def test_unknown_bootstrap_blocks_repeat_write(self):
        cloud = FakeCloud(); cloud.fail_prompt = True
        with self.assertRaises(TimeoutError): atomic_cloud.bootstrap(cloud, 'calculator')
        before = cloud.calls[:]
        with self.assertRaisesRegex(SessionModelError, 'RECONCILE_BEFORE_REPLAY'):
            atomic_cloud.bootstrap(cloud, 'calculator')
        self.assertEqual(cloud.calls, before)
        self.assertEqual(private_read(self.root / 'calculator/bootstrap.json')['status'], 'unknown')

    def test_reconcile_rejects_same_name_metadata_wrong_saved_resource_ids(self):
        cloud = FakeCloud(); cloud.fail_prompt = True
        with self.assertRaises(TimeoutError): atomic_cloud.bootstrap(cloud, 'calculator')
        cloud.fail_prompt = False
        cloud.project_id = UUID('33333333-3333-3333-3333-333333333333')
        cloud.dataset_id = UUID('44444444-4444-4444-4444-444444444444')
        before = cloud.calls[:]
        with self.assertRaises(ValueError): atomic_cloud.bootstrap(cloud, 'calculator', reconcile=True)
        self.assertFalse(any(c.startswith('create_') or c == 'push_prompt' for c in cloud.calls[len(before):]))

    def test_missing_reconciliation_target_remains_unknown_without_recreation(self):
        cloud = FakeCloud(); cloud.fail_prompt = True
        with self.assertRaises(TimeoutError): atomic_cloud.bootstrap(cloud, 'calculator')
        cloud.fail_prompt = False; cloud.rows = []
        before = cloud.calls[:]
        with self.assertRaisesRegex(ValueError, 'ROSTER_MISMATCH'):
            atomic_cloud.bootstrap(cloud, 'calculator', reconcile=True)
        self.assertFalse(any(c.startswith('create_') or c == 'push_prompt' for c in cloud.calls[len(before):]))
        self.assertFalse((self.root / 'calculator/profile.json').exists())
        self.assertEqual(private_read(self.root / 'calculator/bootstrap.json')['status'], 'unknown')

    def evaluation_fixture(self, *, drift=False, foreign_run=False, feedback_score=1):
        row = deepcopy(atomic_cloud.roster('calculator')[0])
        profile = {'dataset_id': '22222222-2222-2222-2222-222222222222',
                   'dataset_as_of': '2026-11-15T00:00:00+00:00',
                   'examples': {row['id']: 'example-1'}, 'project_id': 'trace-project'}
        private_write(self.root / 'calculator/evaluation.json',
                      {'status': 'unknown', 'experiment_id': 'owned-experiment', 'run_ids': ['owned-run']})
        expected = deepcopy(row['outputs'])
        if drift: expected['per_share'] = '999'
        example = Dump(id='example-1', inputs=row['inputs'], outputs=expected,
                       metadata={'fixture_sha256': row['fixture_sha256']})
        run = Dump(id='foreign-run' if foreign_run else 'owned-run', inputs=row['inputs'],
                   outputs={'result': expected}, reference_example_id='example-1', error=None,
                   session_id='owned-experiment', parent_run_id=None)
        feedback = Dump(run_id=run.id, key=atomic_cloud.FEEDBACK, score=feedback_score)
        cloud = SimpleNamespace(list_examples=lambda **kw: [example], list_runs=lambda **kw: [run],
            read_run=lambda *a, **kw: run, list_feedback=lambda **kw: [feedback])
        return cloud, profile, [row]

    def check(self, cloud, profile, rows):
        with patch.object(atomic_cloud, 'local_profile', return_value=profile), \
             patch.object(atomic_cloud, 'roster', return_value=rows), \
             patch.object(observability, 'credential', return_value=CANARY):
            return atomic_cloud.check_evaluation(cloud, 'calculator')

    def test_exact_evaluation_readback_positive_control(self):
        self.assertEqual(self.check(*self.evaluation_fixture())['status'], 'verified')

    def test_remote_expected_output_drift_is_rejected_even_if_run_and_grade_match(self):
        with self.assertRaises(ValueError): self.check(*self.evaluation_fixture(drift=True))

    def test_foreign_favorable_run_ids_cannot_replace_owned_attempt(self):
        with self.assertRaises(ValueError): self.check(*self.evaluation_fixture(foreign_run=True))

    def test_correct_outputs_in_foreign_project_are_rejected(self):
        cloud, profile, rows = self.evaluation_fixture()
        cloud.read_run('owned-run').session_id = 'foreign-experiment'
        with self.assertRaises(ValueError): self.check(cloud, profile, rows)

    def test_child_run_cannot_be_accepted_as_evaluation_root(self):
        cloud, profile, rows = self.evaluation_fixture()
        cloud.read_run('owned-run').parent_run_id = 'foreign-parent'
        with self.assertRaises(ValueError): self.check(cloud, profile, rows)

    def test_duplicate_remote_example_rows_are_rejected(self):
        cloud, profile, rows = self.evaluation_fixture()
        example = cloud.list_examples()[0]
        cloud.list_examples = lambda **kw: [example, example]
        with self.assertRaises(ValueError): self.check(cloud, profile, rows)

    def test_remote_raw_payload_is_admitted_before_evaluation_callbacks(self):
        row = deepcopy(atomic_cloud.roster('calculator')[0])
        profile = {'dataset_id': '22222222-2222-2222-2222-222222222222',
                   'dataset_as_of': '2026-11-15T00:00:00+00:00',
                   'examples': {row['id']: 'example-1'}, 'project_id': 'trace-project',
                   'roster_sha256': observability.digest([row])}
        example = Dump(id='example-1', inputs={'request': {'case_id': 'nominal'}, 'private': CANARY},
                       outputs=row['outputs'], metadata={'fixture_sha256': row['fixture_sha256']})
        dispatch = AsyncMock(side_effect=RuntimeError('DISALLOWED_BEFORE_ADMISSION_CALL'))
        cloud = SimpleNamespace(create_project=lambda *a, **kw: Dump(id='owned-experiment', name='owned'),
                                list_examples=lambda **kw: [example], aevaluate=dispatch)
        with patch.object(atomic_cloud, 'local_profile', return_value=profile), \
             patch.object(atomic_cloud, 'roster', return_value=[row]), \
             patch.object(atomic_cloud, 'PublicTracer'):
            try: atomic_cloud.evaluate(cloud, 'calculator')
            except Exception: pass
        dispatch.assert_not_awaited()

    def test_wrong_feedback_inverse_control(self):
        with self.assertRaisesRegex(ValueError, 'REMOTE_FEEDBACK'):
            self.check(*self.evaluation_fixture(feedback_score=0))

    def test_grader_inverse_control(self):
        expected = Dump(outputs={'status': 'passed', 'per_share': '10'})
        correct = Dump(outputs={'result': deepcopy(expected.outputs)})
        wrong = Dump(outputs={'result': {'status': 'passed', 'per_share': '11'}})
        self.assertTrue(atomic_cloud.evaluator(correct, expected)['score'])
        self.assertFalse(atomic_cloud.evaluator(wrong, expected)['score'])

    def test_trace_cleaning_strips_metadata_paths_tags_and_raw_exception(self):
        tracer = object.__new__(atomic_cloud.PublicTracer)
        tracer.client = object()
        run = Dump(name='synthetic-span', serialized={'private_path': CANARY},
                   extra={'metadata': {'scope': atomic_cloud.SCOPE, 'private_path': CANARY}},
                   tags=[CANARY], error='RuntimeError(' + CANARY + ')', ls_client=None)
        tracer._clean(run)
        self.assertNotIn(CANARY, repr(vars(run)))

    def split_fixture(self, split):
        row = deepcopy(atomic_cloud.roster('calculator')[0])
        profile = {'dataset_id': str(uuid4()), 'dataset_as_of': '2026-11-16T00:00:00+00:00',
                   'examples': {row['id']: 'synthetic-example'},
                   'roster_sha256': observability.digest([row])}
        metadata = {'fixture_sha256': row['fixture_sha256']}
        if split is not ...: metadata['dataset_split'] = split
        example = Dump(id='synthetic-example', inputs=row['inputs'], outputs=row['outputs'], metadata=metadata)
        cloud = SimpleNamespace(list_examples=lambda **kw: [example],
                                create_project=unittest.mock.Mock(), aevaluate=AsyncMock())
        return cloud, profile, [row]

    def test_service_base_and_absent_dataset_split_are_accepted(self):
        for split in (..., ['base']):
            with self.subTest(split=repr(split)):
                cloud, profile, rows = self.split_fixture(split)
                with patch.object(atomic_cloud, 'roster', return_value=rows):
                    self.assertEqual(len(atomic_cloud.admitted_examples(cloud, 'calculator', profile)), 1)
                cloud.create_project.assert_not_called(); cloud.aevaluate.assert_not_awaited()

    def test_foreign_private_or_malformed_split_rejects_before_evaluation(self):
        for split in (['test'], ['base', 'private'], [CANARY], None, 'base', []):
            with self.subTest(split=repr(split)):
                cloud, profile, rows = self.split_fixture(split)
                with patch.object(atomic_cloud, 'local_profile', return_value=profile), \
                     patch.object(atomic_cloud, 'roster', return_value=rows):
                    with self.assertRaisesRegex(ValueError, 'EXAMPLE_METADATA_NOT_PUBLIC'):
                        atomic_cloud.evaluate(cloud, 'calculator')
                cloud.create_project.assert_not_called(); cloud.aevaluate.assert_not_awaited()
                self.assertFalse((self.root / 'calculator/evaluation.json').exists())


class LifecycleConfigTests(unittest.TestCase):
    """AC-026/027: in-memory launch decisions; no server is started or stopped."""
    def test_explicit_atomic_graph_ids_map_to_correct_capabilities(self):
        config = json.loads((ROOT / 'tuning/langchain_pilot/atomic-langgraph.json').read_text())
        self.assertEqual(config['graphs'], {
            'calculator': 'tuning.langchain_pilot.atomic:calculator_graph',
            'trading_pilot': 'tuning.langchain_pilot.atomic:session_graph',
            'holdings': 'tuning.langchain_pilot.atomic:holdings_graph'})

    def test_occupied_port_aborts_before_exec_with_no_fallback(self):
        probe = unittest.mock.MagicMock()
        probe.__enter__.return_value.bind.side_effect = OSError('occupied')
        with patch.object(serve.socket, 'socket', return_value=probe), \
             patch.object(serve.os, 'execve') as dispatch, \
             patch('sys.argv', ['serve', '--atomic', '--port', '2025']):
            with self.assertRaisesRegex(SystemExit, 'ATOMIC_PORT_OCCUPIED'):
                serve.main()
        dispatch.assert_not_called()
        probe.__enter__.return_value.bind.assert_called_once_with(('127.0.0.1', 2025))

    def test_invalid_port_aborts_before_socket_or_exec(self):
        for port in ('1023', '65536'):
            with self.subTest(port=port), patch.object(serve.socket, 'socket') as probe, \
                 patch.object(serve.os, 'execve') as dispatch, \
                 patch('sys.argv', ['serve', '--atomic', '--port', port]):
                with self.assertRaisesRegex(SystemExit, 'unprivileged port required'): serve.main()
                probe.assert_not_called(); dispatch.assert_not_called()

    def test_generic_cloud_tracing_without_closed_atomic_route_aborts(self):
        with patch.object(serve.os, 'execve') as dispatch, \
             patch('sys.argv', ['serve', '--cloud-tracing', '--port', '2025']):
            with self.assertRaisesRegex(SystemExit, 'closed atomic fixture'): serve.main()
        dispatch.assert_not_called()


class TraceReadbackTests(unittest.TestCase):
    """AC-011/013: exact cloud verifier boundary with in-memory read results."""
    def setUp(self):
        TEMP.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=TEMP, prefix='independent-readback-')
        self.root = Path(self.directory.name)
    def tearDown(self): self.directory.cleanup()

    def fixture(self, kind='calculator'):
        selected = atomic.fixtures(kind)[0]
        run_id, thread, project = str(uuid4()), str(uuid4()), str(uuid4())
        profile = {'project_id': project, 'project_name': 'synthetic-owned',
                   'candidate': self.root.name,
                   'candidate_sha256': observability.digest(atomic_cloud.fingerprints()),
                   'sources': atomic_cloud.fingerprints(),
                   'examples': {'nominal': str(uuid4())}, 'prompt_commit': 'frozen-commit',
                   'prompt_sha256': observability.digest(atomic_cloud.prompt_text(kind)),
                   'roster_sha256': observability.digest(atomic_cloud.roster(kind))}
        if kind == 'calculator_session':
            result = {'status': 'passed', 'scope': 'synthetic_local_pilot',
                      'case_id': selected['inputs']['case']['case_id'], 'per_share': '10',
                      'tool_calls': 1, 'answer': {'per_share': '10', 'synthetic': True}}
        else: result = {'status': 'passed', 'per_share': '10'}
        saved = {'status': 'completed', 'execution_outcome': 'completed',
                 'scope': atomic_cloud.SCOPE, 'kind': kind, 'fixture_id': 'nominal',
                 'run_id': run_id, 'graph_thread_id': thread, 'project_id': project,
                 'candidate': self.root.name, 'result': result}
        saved['candidate_sha256'] = profile['candidate_sha256']
        saved['created_at_ns'] = 2
        meta = {'scope': atomic_cloud.SCOPE, 'kind': kind, 'agent_id': observability.AGENT,
                'fixture_id': 'nominal', 'graph_thread_id': thread,
                'cloud_attempt_id': run_id, 'candidate': self.root.name,
                'candidate_sha256': profile['candidate_sha256'],
                'roster_sha256': profile['roster_sha256'], 'prompt_commit': profile['prompt_commit'],
                'prompt_sha256': profile['prompt_sha256'],
                'fixture_sha256': observability.digest(selected['inputs']),
                'model_identity': 'host_session_declared_not_attested' if kind == 'calculator_session'
                                  else 'no_model_call'}
        root = Dump(id=run_id, parent_run_id=None, session_id=project,
                    reference_example_id=profile['examples']['nominal'],
                    child_runs=[], extra={'metadata': deepcopy(meta)}, run_type='chain',
                    name=kind, error=None, inputs=deepcopy(selected['inputs']),
                    outputs={'result': deepcopy(result)} if kind == 'calculator_session' else deepcopy(result))
        tool = Dump(id=str(uuid4()), parent_run_id=run_id, session_id=project,
                    child_runs=[], extra={'metadata': deepcopy(meta)}, run_type='tool',
                    name='calculate_valuation' if kind == 'calculator_session' else 'calculate_atomic_valuation',
                    error=None, inputs={} if kind == 'calculator_session' else deepcopy(selected['inputs']),
                    outputs={'output': deepcopy(result)})
        if kind == 'calculator_session':
            tool_call_id = 'synthetic-tool-call'
            case = graph.ValuationCase.model_validate(selected['inputs']['case']).model_dump(mode='json')
            arithmetic = {'case_id': case['case_id'], 'enterprise_pv': '100',
                          'equity_pv': '100', 'nonoperating_pv': '0', 'per_share': '10'}
            message = ToolMessage(name='calculate_valuation', tool_call_id=tool_call_id,
                content=json.dumps(arithmetic), artifact={'schema_version': 2,
                    'case_sha256': hashlib.sha256(canonical(case).encode()).hexdigest(),
                    'tool_call_id': tool_call_id, 'execution_thread_id': thread})
            tool.outputs = {'output': message.model_dump(mode='json')}
        root.child_runs = [tool]
        if kind == 'calculator_session':
            root.child_runs.append(Dump(id=str(uuid4()), parent_run_id=run_id, session_id=project,
                child_runs=[], extra={'metadata': deepcopy(meta)}, run_type='llm',
                name='SessionChatModel', error=None, outputs={'generations': [[{
                    'text': '{"per_share":"10","synthetic":true}',
                    'message': dumpd(AIMessage(content='{"per_share":"10","synthetic":true}'))}]]}))
            root.child_runs.insert(0, Dump(id=str(uuid4()), parent_run_id=run_id, session_id=project,
                child_runs=[], extra={'metadata': deepcopy(meta)}, run_type='llm',
                name='SessionChatModel', error=None, outputs={'generations': [[{
                    'text': '', 'message': dumpd(AIMessage(content='', tool_calls=[{
                        'name': 'calculate_valuation', 'args': {}, 'id': tool_call_id}]))}]]}))
        start = datetime(2026, 11, 16, tzinfo=timezone.utc)
        root.start_time = start
        root.end_time = start + timedelta(seconds=1)
        for node in [root, *root.child_runs]:
            node.serialized = {'name': node.name}
            node.tags = [atomic_cloud.SCOPE]
            node.attachments = {}
            if node is not root:
                node.start_time = start + timedelta(milliseconds=10)
                node.end_time = start + timedelta(milliseconds=20)
        saved['created_at_ns'] = int(start.timestamp() * 1e9) - 1000000
        saved['ended_at_ns'] = int(root.end_time.timestamp() * 1e9) + 1000000
        return root, profile, saved

    def check(self, root, profile, saved, previous=None):
        saved['native_run_ids'] = [str(root.id), *[str(x.id) for x in root.child_runs]]
        name = saved['run_id'] + '.json'
        path = self.root / saved['kind'] / 'traces' / name
        private_write(path, saved)
        by_id = {str(root.id): root}
        if previous:
            previous_root, previous_saved = previous
            previous_saved['native_run_ids'] = [str(previous_root.id), *[str(x.id) for x in previous_root.child_runs]]
            private_write(self.root / saved['kind'] / 'traces' / (previous_saved['run_id'] + '.json'), previous_saved)
            by_id[str(previous_root.id)] = previous_root
        cloud = SimpleNamespace(get_run_url=lambda **kw: 'synthetic-readback-url')
        with patch.object(atomic_cloud, 'state_root', return_value=self.root), \
             patch.object(atomic_cloud, 'local_profile', return_value=profile), \
             patch.object(observability, 'read_exact_run', side_effect=lambda c, run_id, **kw: by_id[run_id]), \
             patch.object(observability, 'credential', return_value='synthetic-configured-key-unrelated-to-private-canary'):
            return atomic_cloud.check_trace(cloud, saved['kind'], name)

    def test_valid_calculator_native_trace_positive_control(self):
        self.assertTrue(self.check(*self.fixture())['readback_verified'])

    def test_completed_calculator_root_parent_must_be_none(self):
        root, profile, saved = self.fixture()
        root.parent_run_id = str(uuid4())
        with self.assertRaises(ValueError): self.check(root, profile, saved)

    def test_completed_tool_parent_must_match_enclosing_root(self):
        root, profile, saved = self.fixture()
        root.child_runs[0].parent_run_id = root.child_runs[0].id
        with self.assertRaises(ValueError): self.check(root, profile, saved)

    def test_completed_valid_calculator_requires_native_tool(self):
        root, profile, saved = self.fixture()
        root.child_runs = []
        with self.assertRaises(ValueError): self.check(root, profile, saved)

    def test_completed_cooperative_trace_requires_actual_model(self):
        root, profile, saved = self.fixture('calculator_session')
        root.child_runs = [r for r in root.child_runs if r.run_type != 'llm']
        with self.assertRaises(ValueError): self.check(root, profile, saved)

    def test_completed_cooperative_without_current_or_prior_tool_rejects(self):
        root, profile, saved = self.fixture('calculator_session')
        root.child_runs = [r for r in root.child_runs if r.run_type == 'llm']
        with self.assertRaises(ValueError): self.check(root, profile, saved)

    def test_final_model_segment_with_exact_previous_waiting_tool_is_valid(self):
        root, profile, saved = self.fixture('calculator_session')
        tool = next(r for r in root.child_runs if r.run_type == 'tool')
        selection = next(r for r in root.child_runs if r.run_type == 'llm'
                         and r.outputs['generations'][0][0]['text'] == '')
        root.child_runs = [r for r in root.child_runs if r.run_type == 'llm' and r is not selection]
        previous_id = str(uuid4())
        previous = deepcopy(saved)
        previous.update(run_id=previous_id, status='waiting', execution_outcome='waiting',
                        result=None, created_at_ns=saved['created_at_ns'] - 2000000000,
                        ended_at_ns=saved['created_at_ns'] - 1000000000)
        saved['previous_trace_run_id'] = previous_id
        prior_meta = deepcopy(root.extra['metadata']); prior_meta['cloud_attempt_id'] = previous_id
        tool.parent_run_id = previous_id
        tool.extra = {'metadata': deepcopy(prior_meta)}
        selection.parent_run_id = previous_id
        selection.extra = {'metadata': deepcopy(prior_meta)}
        previous_root = Dump(id=previous_id, parent_run_id=None, session_id=profile['project_id'],
            reference_example_id=profile['examples']['nominal'], child_runs=[selection, tool],
            extra={'metadata': prior_meta}, run_type='chain', name='calculator_session',
            error='ATOMIC_COOPERATIVE_WAIT', outputs=None, inputs=deepcopy(root.inputs),
            serialized={'name': 'calculator_session'}, tags=[atomic_cloud.SCOPE], attachments={},
            start_time=root.start_time - timedelta(seconds=2), end_time=root.start_time - timedelta(seconds=1))
        tool.start_time = previous_root.start_time + timedelta(milliseconds=10)
        tool.end_time = previous_root.start_time + timedelta(milliseconds=20)
        selection.start_time = previous_root.start_time + timedelta(milliseconds=5)
        selection.end_time = previous_root.start_time + timedelta(milliseconds=9)
        self.assertTrue(self.check(root, profile, saved, previous=(previous_root, previous))['readback_verified'])

    def test_trace_metadata_must_match_exact_candidate_manifest(self):
        for field in ('scope', 'candidate', 'roster_sha256', 'prompt_sha256',
                      'fixture_sha256', 'cloud_attempt_id'):
            with self.subTest(field=field):
                root, profile, saved = self.fixture()
                root.extra['metadata'][field] = 'foreign-value'
                with self.assertRaises(ValueError): self.check(root, profile, saved)

    def test_foreign_actual_root_inputs_are_rejected(self):
        root, profile, saved = self.fixture()
        root.inputs = {'case': {'private': CANARY}}
        with self.assertRaises(ValueError): self.check(root, profile, saved)

    def test_foreign_reference_example_is_rejected(self):
        root, profile, saved = self.fixture()
        root.reference_example_id = str(uuid4())
        with self.assertRaises(ValueError): self.check(root, profile, saved)

    def test_wrong_frozen_result_cannot_be_verified_by_matching_saved_receipt(self):
        root, profile, saved = self.fixture()
        root.outputs['per_share'] = '999'; saved['result']['per_share'] = '999'
        with self.assertRaises(ValueError): self.check(root, profile, saved)

    def test_raw_error_stack_cannot_be_verified_as_controlled_failure(self):
        root, profile, saved = self.fixture()
        root.error = 'RAW_GRAPH_INTERRUPT_STACK ' + CANARY
        saved.update(status='failed', execution_outcome='failed', result=None)
        with self.assertRaises(ValueError): self.check(root, profile, saved)

    def test_wrong_child_tool_output_cannot_support_correct_root(self):
        root, profile, saved = self.fixture()
        root.child_runs[0].outputs['output']['per_share'] = '999'
        with self.assertRaises(ValueError): self.check(root, profile, saved)

    def test_unfinished_model_child_is_not_successful_inference(self):
        root, profile, saved = self.fixture('calculator_session')
        model = next(node for node in root.child_runs if node.run_type == 'llm')
        model.end_time = None; model.outputs = None
        with self.assertRaises(ValueError): self.check(root, profile, saved)

    def test_private_tags_are_not_an_accepted_sanitized_trace(self):
        root, profile, saved = self.fixture()
        root.tags = [CANARY]
        with self.assertRaises(ValueError): self.check(root, profile, saved)

    def test_private_extra_metadata_is_not_accepted(self):
        root, profile, saved = self.fixture()
        root.extra['metadata']['private'] = CANARY
        with self.assertRaises(ValueError): self.check(root, profile, saved)


class MutationControls(unittest.TestCase):
    """Patch executable functions in memory; never edit candidate source files."""
    controls = []

    def changed_function(self, module, name, old, new):
        original = getattr(module, name)
        source = inspect.getsource(original)
        self.assertIn(old, source, 'mutation target must match actual enforcing layer')
        namespace = dict(vars(module))
        exec(compile(source.replace(old, new, 1), '<independent-in-memory-mutation>', 'exec'), namespace)
        return namespace[name]

    def kill(self, name, module, attribute, changed, target):
        original = getattr(module, attribute)
        with patch.object(module, attribute, changed):
            result = unittest.TestResult()
            target.run(result)
        self.assertIs(getattr(module, attribute), original, 'patch must be restored')
        count = len(result.failures) + len(result.errors)
        self.controls.append({'id': name, 'test': target.id(), 'executed': result.testsRun,
                              'killed': count > 0, 'failure_count': len(result.failures),
                              'error_count': len(result.errors), 'restored': True})
        self.assertEqual(result.testsRun, 1)
        self.assertGreater(count, 0, name + ': surviving mutation')

    def test_MUT003_tolerant_arithmetic_receipt_gate_is_killed(self):
        changed = self.changed_function(graph, 'verify',
            'any(Fraction(Decimal(tool_result[k])) != v for k, v in expected_fields.items())',
            'any(abs(float(Fraction(Decimal(tool_result[k])) - v)) > 1e-10 for k, v in expected_fields.items())')
        self.kill('MUT-003', graph, 'verify', changed,
                  ArithmeticReceiptTests('test_near_correct_receipt_is_rejected_exactly'))

    def test_MUT006_forged_receipt_gate_is_killed(self):
        changed = self.changed_function(graph, 'verify', 'if artifact != expected_artifact:', 'if False:')
        self.kill('MUT-006', graph, 'verify', changed,
                  ArithmeticReceiptTests('test_forged_case_hash_is_rejected'))

    def test_MUT007_extra_receipt_claim_gate_is_killed(self):
        changed = self.changed_function(graph, 'verify',
            "set(tool_result) != {'case_id', *expected_fields}", 'False')
        self.kill('MUT-007', graph, 'verify', changed,
                  ArithmeticReceiptTests('test_extra_receipt_monetary_claim_is_rejected'))

    def test_MUT001_unknown_outer_key_admission_is_killed(self):
        changed = self.changed_function(atomic, 'admit',
            "set(value) == {'request'}", "set(value) >= {'request'}")
        self.kill('MUT-001', atomic, 'admit', changed,
                  PublicBoundaryTests('test_raw_unknown_fields_fail_before_export_runner'))

    def test_MUT031_always_pass_grader_is_killed(self):
        changed = self.changed_function(atomic_cloud, 'evaluator', 'actual == example.outputs', 'True')
        self.kill('MUT-031', atomic_cloud, 'evaluator', changed,
                  CloudIntegrityTests('test_grader_inverse_control'))

    def test_MUT013_preserving_private_tags_is_killed(self):
        original = atomic_cloud.PublicTracer._clean
        source = inspect.getsource(original)
        import textwrap
        namespace = dict(vars(atomic_cloud))
        exec(compile(textwrap.dedent(source).replace('run.tags = [SCOPE]', 'run.tags = run.tags'),
                     '<independent-in-memory-mutation>', 'exec'), namespace)
        self.kill('MUT-013', atomic_cloud.PublicTracer, '_clean', namespace['_clean'],
                  CloudIntegrityTests('test_trace_cleaning_strips_metadata_paths_tags_and_raw_exception'))

    def test_MUT011_missing_model_parent_context_is_killed(self):
        self.kill('MUT-011', graph, 'tracing_context', lambda **kw: nullcontext(),
                  NativeSessionTransportTests('test_actual_native_model_parent_belongs_to_owned_tree'))


class RatePolicyTests(unittest.TestCase):
    """User 429 steering: bounded recorded reads, paced dispatch and single writes."""
    def setUp(self):
        from tuning.langchain_pilot import rate_policy
        self.rate = rate_policy
        TEMP.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=TEMP, prefix='independent-rate-')
        self.state = Path(self.directory.name)
        self.config = rate_policy.policy()
    def tearDown(self): self.directory.cleanup()

    @contextmanager
    def clock(self):
        class Clock:
            now = 0.0
            sleeps = []
            epoch = datetime(2026, 11, 16, 12, tzinfo=timezone.utc).timestamp()
            def sleep(self, delay):
                if delay < 0: raise AssertionError('negative delay')
                self.sleeps.append(delay); self.now += delay
        clock = Clock()
        with patch.object(self.rate.time, 'monotonic', side_effect=lambda: clock.now), \
             patch.object(self.rate.time, 'time', side_effect=lambda: clock.epoch + clock.now), \
             patch.object(self.rate.time, 'time_ns', side_effect=lambda: int((clock.epoch + clock.now) * 1e9)), \
             patch.object(self.rate.time, 'sleep', side_effect=clock.sleep):
            yield clock

    def client(self, config=None):
        return self.rate.RateAwareClient(api_key='synthetic-never-dispatched', auto_batch_tracing=False,
            omit_traced_runtime_info=True, rate_state=self.state, read_policy=config or self.config)

    def events(self):
        return [private_read(path) for path in (self.state / 'attempts').glob('*.json')]

    def rate_error(self, header=None):
        import requests
        from langsmith.utils import LangSmithRateLimitError
        response = requests.Response(); response.status_code = 429
        if header is not None: response.headers['Retry-After'] = header
        error = LangSmithRateLimitError(CANARY)
        error.__context__ = requests.HTTPError(response=response)
        return error

    def test_policy_rejects_invalid_overrides_before_dispatch(self):
        for change in ({'max_read_attempts': True}, {'max_read_attempts': 6},
                       {'read_budget_seconds': 0}, {'read_interval_seconds': -1},
                       {'query_interval_seconds': float('nan')}, {'warmup_delay_seconds': 61}):
            with self.subTest(change=repr(change)), patch.object(Client, 'request_with_retries') as send:
                with self.assertRaises(ValueError): self.client({**self.config, **change})
                send.assert_not_called()
        original = deepcopy(self.config)
        validated = self.rate.policy(original)
        validated['read_interval_seconds'] = 123
        self.assertEqual(original, self.config)

    def test_retry_after_numeric_date_past_and_invalid(self):
        from email.utils import format_datetime
        now = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
        self.assertEqual(self.rate.retry_after('1.5', now=now.timestamp()), 1.5)
        self.assertEqual(self.rate.retry_after(format_datetime(now + timedelta(seconds=75)), now=now.timestamp()), 75)
        self.assertEqual(self.rate.retry_after(format_datetime(now - timedelta(seconds=5)), now=now.timestamp()), 0)
        for value in (None, '-2', 'NaN', 'Infinity', 'private-invalid'):
            with self.subTest(value=value): self.assertIsNone(self.rate.retry_after(value, now=now.timestamp()))

    def test_server_retry_after_has_priority_over_backoff_cap(self):
        times = []
        with self.clock() as clock:
            def send(client, method, pathname, **kw):
                times.append(clock.now); self.assertEqual(kw['stop_after_attempt'], 1)
                if len(times) == 1: raise self.rate_error('120')
                return Dump(status_code=200)
            with patch.object(Client, 'request_with_retries', autospec=True, side_effect=send):
                client = self.client(); client.request_with_retries('GET', '/runs/owned'); client.close()
        self.assertEqual(times, [0, 120])
        self.assertTrue(any(row.get('retry_after_seconds') == 120 and row['delay_seconds'] == 120 for row in self.events()))

    def test_http_date_retry_after_controls_actual_dispatch(self):
        from email.utils import format_datetime
        times = []
        with self.clock() as clock:
            header = format_datetime(datetime.fromtimestamp(clock.epoch + 75, timezone.utc))
            def send(client, method, pathname, **kw):
                times.append(clock.now)
                if len(times) == 1: raise self.rate_error(header)
                return Dump(status_code=200)
            with patch.object(Client, 'request_with_retries', autospec=True, side_effect=send):
                client = self.client(); client.request_with_retries('GET', '/runs/owned'); client.close()
        self.assertEqual(times, [0, 75])

    def test_read_retry_cap_is_single_authority(self):
        from langsmith.utils import LangSmithRateLimitError
        calls = []
        with self.clock() as clock:
            def send(client, method, path, **kw):
                calls.append((clock.now, kw['stop_after_attempt'])); raise self.rate_error('0')
            with patch.object(Client, 'request_with_retries', autospec=True, side_effect=send):
                client = self.client()
                with self.assertRaises(LangSmithRateLimitError): client.request_with_retries('GET', '/runs/owned', stop_after_attempt=99)
                client.close()
        self.assertEqual(len(calls), self.config['max_read_attempts'])
        self.assertTrue(all(stop == 1 for _, stop in calls))

    def test_explicit_readonly_posts_retry_and_other_posts_write_once(self):
        from langsmith.utils import LangSmithRateLimitError
        for path, count in [('/runs/query', 3), ('/examples/query', 3), ('/feedback/query', 3), ('/runs', 1)]:
            with self.subTest(path=path), self.clock():
                calls = []
                def send(client, method, pathname, **kw): calls.append(kw['stop_after_attempt']); raise self.rate_error('0')
                with patch.object(Client, 'request_with_retries', autospec=True, side_effect=send):
                    client = self.client()
                    with self.assertRaises(LangSmithRateLimitError): client.request_with_retries('POST', path, stop_after_attempt=99)
                    client.close()
                self.assertEqual(calls, [1] * count)
        self.assertTrue(any(row.get('unknown_write') is True for row in self.events()))

    def test_fallback_backoff_is_bounded_and_recorded(self):
        times = []
        with self.clock() as clock:
            def send(client, method, pathname, **kw):
                times.append(clock.now)
                if len(times) < 3: raise self.rate_error('invalid')
                return Dump(status_code=200)
            with patch.object(Client, 'request_with_retries', autospec=True, side_effect=send):
                client = self.client(); client.request_with_retries('GET', '/runs/owned'); client.close()
        self.assertEqual(times, [0, 5, 15])

    def test_retry_after_over_budget_stops_without_second_call(self):
        from langsmith.utils import LangSmithRateLimitError
        with self.clock(), patch.object(Client, 'request_with_retries', side_effect=self.rate_error('181')) as send:
            client = self.client()
            with self.assertRaises(LangSmithRateLimitError): client.request_with_retries('GET', '/runs/owned')
            client.close(); self.assertEqual(send.call_count, 1)
        self.assertTrue(any(row['disposition'] == 'rate_limit_stopped' for row in self.events()))

    def test_pacing_budget_stop_is_recorded_without_dispatch(self):
        config = {**self.config, 'read_budget_seconds': 10}
        with self.clock(), patch.object(Client, 'request_with_retries', side_effect=self.rate_error('0')) as send:
            client = self.client(config)
            with self.assertRaisesRegex(ValueError, 'BUDGET'): client.request_with_retries('POST', '/runs/query')
            client.close(); self.assertEqual(send.call_count, 1)
        stops = [row for row in self.events() if 'budget' in row.get('disposition', '')
                 or 'BUDGET' in row.get('error_code', '')]
        self.assertTrue(stops, 'pacing budget abort must have its own recorded classification')

    def test_shared_state_pacing_write_cannot_reset_query_window(self):
        times = []
        with self.clock() as clock:
            def send(client, method, pathname, **kw): times.append((pathname, clock.now)); return Dump(status_code=200)
            with patch.object(Client, 'request_with_retries', autospec=True, side_effect=send):
                first, second = self.client(), self.client()
                first.request_with_retries('POST', '/runs/query')
                second.request_with_retries('POST', '/runs')
                second.request_with_retries('GET', '/runs/owned')
                first.request_with_retries('POST', '/runs/query')
                first.close(); second.close()
        self.assertEqual(times, [('/runs/query', 0), ('/runs', 0), ('/runs/owned', 0), ('/runs/query', 15)])

    def test_delayed_dispatch_cannot_burst_two_clients(self):
        times = []; blocked = threading.Event(); release = threading.Event()
        second_attempting = threading.Event(); second_done = threading.Event()
        with self.clock() as clock:
            def send(client, method, pathname, **kw): times.append(clock.now); return Dump(status_code=200)
            with patch.object(Client, 'request_with_retries', autospec=True, side_effect=send):
                first, second = self.client(), self.client()
                original = first._event
                def event(request_id, **value):
                    original(request_id, **value)
                    if value.get('disposition') == 'dispatching':
                        blocked.set()
                        if not release.wait(timeout=5): raise RuntimeError('bounded barrier')
                first._event = event
                failures = []
                def invoke():
                    try: first.request_with_retries('GET', '/runs/first')
                    except Exception as error: failures.append(type(error).__name__)
                def invoke_second():
                    second_attempting.set()
                    try: second.request_with_retries('GET', '/runs/second')
                    except Exception as error: failures.append(type(error).__name__)
                    finally: second_done.set()
                worker = threading.Thread(target=invoke); worker.start()
                self.assertTrue(blocked.wait(timeout=5))
                other = threading.Thread(target=invoke_second); other.start()
                self.assertTrue(second_attempting.wait(timeout=5))
                # A correct owner may hold the dispatch lease, so the second
                # request is allowed to remain blocked until the first releases.
                second_done.wait(timeout=0.5)
                release.set(); worker.join(timeout=5)
                other.join(timeout=5)
                self.assertFalse(worker.is_alive()); self.assertFalse(other.is_alive())
                self.assertEqual(failures, [])
                first.close(); second.close()
        self.assertEqual(len(times), 2)
        self.assertGreaterEqual(max(times) - min(times), self.config['read_interval_seconds'])

    def test_exception_releases_dispatch_lock_for_next_client(self):
        times = []
        with self.clock() as clock:
            def send(client, method, pathname, **kw):
                times.append(clock.now)
                if len(times) == 1: raise TimeoutError(CANARY)
                return Dump(status_code=200)
            with patch.object(Client, 'request_with_retries', autospec=True, side_effect=send):
                first, second = self.client(), self.client()
                with self.assertRaises(TimeoutError): first.request_with_retries('GET', '/runs/first')
                finished = []; worker = threading.Thread(target=lambda: finished.append(second.request_with_retries('GET', '/runs/second')))
                worker.start(); worker.join(timeout=5)
                self.assertFalse(worker.is_alive(), 'exception must release the cross-client dispatch lease')
                self.assertEqual(len(finished), 1)
                first.close(); second.close()
        self.assertEqual(times, [0, self.config['read_interval_seconds']])

    def test_warmup_is_once_per_client_and_failed_warmup_is_recorded(self):
        with self.clock(), patch.object(Client, 'request_with_retries', return_value=Dump(status_code=200)) as send:
            client = self.client(); client.warmup(); client.warmup(); client.close()
            self.assertEqual(send.call_count, 1); self.assertEqual(send.call_args.args[:2], ('GET', '/info'))
        with self.clock(), patch.object(Client, 'request_with_retries', side_effect=RuntimeError(CANARY)):
            client = self.client()
            with self.assertRaises(RuntimeError): client.warmup()
            self.assertFalse(client._warm); client.close()
        self.assertTrue(any(row['disposition'] == 'warmup_failed' for row in self.events()))

    def test_attempt_records_omit_payload_headers_query_and_exception(self):
        with self.clock(), patch.object(Client, 'request_with_retries', side_effect=TimeoutError(CANARY)):
            client = self.client()
            with self.assertRaises(TimeoutError):
                client.request_with_retries('POST', '/datasets/' + CANARY + '?key=' + CANARY,
                    headers={'Authorization': CANARY}, json={'private': CANARY})
            client.close()
        rows = self.events(); self.assertTrue(rows); self.assertNotIn(CANARY, canonical(rows))
        for path in (self.state / 'attempts').glob('*.json'):
            self.assertEqual(path.stat().st_mode & 0o077, 0)


if __name__ == '__main__': unittest.main()
