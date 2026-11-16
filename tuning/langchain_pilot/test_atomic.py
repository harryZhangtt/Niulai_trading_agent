"""Requirement-derived public ingress, arithmetic, tracing and fence controls."""
import asyncio
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from langsmith import Client, tracing_context
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from langgraph.errors import EmptyInputError

from tuning.langchain_pilot.atomic import fixtures, make_public_graph
from tuning.langchain_pilot.atomic_cloud import PublicTracer, bootstrap, evaluator, local_profile, FEEDBACK
from tuning.langchain_pilot.graph import calculate, make_graph, MAX_NUMERIC_DIGITS, verify
from tuning.langchain_pilot.session_model import SessionChatModel, SessionModelError, configure, load_binding, private_write
from tuning.langchain_pilot.test_graph import model

ROOT = Path(__file__).resolve().parents[2]
PACKET = json.loads((Path(__file__).parent / 'tests/atomic_contract_cases.json').read_text())


def computed(spec, name='contract'):
    out = calculate({'case_id': name, **spec})
    return {'ev': Fraction(out['enterprise_pv']), 'equity': Fraction(out['equity_pv']),
            'per_share': Fraction(out['per_share'])}


class CalculatorContractTests(unittest.IsolatedAsyncioTestCase):
    pass


def arithmetic_case(case):
    async def test(self):
        given, expected = case['given'], case['expected']
        if case['id'] == 'CAL-17':
            given = {'fcff': ['1' * (MAX_NUMERIC_DIGITS + 1)], 'rate': '0',
                     'terminal_ev': '0', 'net_debt': '0', 'shares': '1'}
        if not isinstance(expected, dict):
            fake = model()
            with self.assertRaises(ValueError):
                await make_graph(fake).ainvoke({'case': {'case_id': case['id'], **given}})
            self.assertEqual(fake.calls, 0)
            return
        if 'fcff' in given:
            actual = computed(given, case['id'])
            for key, number in expected.items(): self.assertEqual(actual[key], Fraction(number))
            discount = 1 + Fraction(given['rate'])
            oracle = sum(Fraction(v) / discount ** (i + 1) for i, v in enumerate(given['fcff']))
            oracle += Fraction(given['terminal_ev']) / discount ** len(given['fcff'])
            self.assertEqual(actual['ev'], oracle)
            self.assertEqual(actual['equity'], oracle - Fraction(given['net_debt']))
            return
        outputs = {k: computed(v, case['id']) for k, v in given.items()}
        for key, number in expected.items():
            if key == 'ev_scale': actual = outputs['transformed']['ev'] / outputs['base']['ev']
            elif key == 'ev_delta': actual = outputs['transformed']['ev'] - outputs['base']['ev']
            elif key == 'per_share_delta': actual = outputs['transformed']['per_share'] - outputs['base']['per_share']
            else:
                prefix, metric = next((p, key[len(p)+1:]) for p in outputs if key.startswith(p + '_'))
                actual = outputs[prefix][metric]
            self.assertEqual(actual, Fraction(number))
    return test


for case in PACKET['cases']:
    if case['id'].startswith('CAL-'):
        setattr(CalculatorContractTests, 'test_' + case['id'].replace('-', '_'), arithmetic_case(case))


class PublicIngressTests(unittest.IsolatedAsyncioTestCase):
    async def test_AC026_copied_server_graph_retains_closed_schema_and_execution(self):
        graph = make_public_graph('calculator').with_config({'metadata': {'caller': 'test'}})
        self.assertFalse(graph.get_input_jsonschema()['additionalProperties'])
        result = await graph.ainvoke({'request': {'case_id': 'debt'}})
        self.assertEqual(result['result']['per_share'], '15')
        with self.assertRaises(ValueError):
            await graph.ainvoke({'request': {'case_id': 'nominal'}, 'private': 'canary'})
    async def test_AC001_unknown_private_extra_nested_and_oversized_before_export(self):
        bad = [None, [], {'request': {'case_id': True}}, {'request': {'case_id': 'not-public'}},
               {'request': {'case_id': 'nominal', 'account': 'synthetic-private-canary'}},
               {'request': {'case_id': 'nominal'}, 'private_path': 'synthetic-private-canary'},
               {'request': {'case_id': 'nominal'}, 'metadata': {'token': 'synthetic-private-canary'}},
               {'request': {'case_id': 'x' * 4097}}]
        for kind in ('calculator', 'calculator_session', 'holdings'):
            runner = AsyncMock()
            graph = make_public_graph(kind, cloud_runner=runner)
            for value in bad:
                with self.subTest(kind=kind, value_type=type(value).__name__):
                    with self.assertRaises((ValueError, EmptyInputError)): await graph.ainvoke(value)
            runner.assert_not_called()

    async def test_AC026_schema_enum_and_every_public_deterministic_selector(self):
        for kind in ('calculator', 'holdings'):
            graph = make_public_graph(kind)
            schema = graph.get_input_jsonschema()
            self.assertFalse(schema['additionalProperties'])
            self.assertEqual(schema['properties']['request']['properties']['case_id']['enum'],
                             [c['id'] for c in fixtures(kind)])
            for case in fixtures(kind):
                with self.subTest(kind=kind, case=case['id']):
                    out = await graph.ainvoke({'request': {'case_id': case['id']}})
                    self.assertEqual(out['result'], case['outputs'])
                    self.assertEqual(out['trace'], {'status': 'disabled'})

    async def test_AC006_public_session_remains_a_real_tool_loop(self):
        out = await make_public_graph('calculator_session', model=model('15')).ainvoke(
            {'request': {'case_id': 'debt'}})
        self.assertEqual(out['result']['per_share'], '15')
        self.assertEqual(out['result']['tool_calls'], 1)

    async def test_AC009_response_privacy_guard_never_admits_private_content(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.langchain-pilot/tmp') as directory:
            configure('synthetic-host', state=Path(directory))
            m = SessionChatModel(state_directory=directory, public_fixture_responses=True)
            g = make_graph(m, checkpointer=InMemorySaver())
            config = {'configurable': {'thread_id': 'privacy-test'}}
            first = await g.ainvoke({'case': fixtures('calculator')[0]['inputs']['case']}, config)
            request = first['__interrupt__'][0].value
            for message in ({'content': 'synthetic-private-canary'},
                            {'content': '{"per_share":"10","synthetic":true,"private":"synthetic-private-canary"}'},
                            {'content': 'synthetic-private-canary', 'tool_calls': [
                                {'name': 'calculate_valuation', 'args': {}}]}):
                response = {'request_id': request['request_id'], 'binding': load_binding(Path(directory)),
                            'message': message}
                state = await g.ainvoke(Command(resume=response), config)
                request = state['__interrupt__'][0].value
                self.assertEqual(request['response_error'], 'ATOMIC_ASSISTANT_SCHEMA')
                self.assertNotIn('synthetic-private-canary', json.dumps(request))


class TraceAndCloudContractTests(unittest.TestCase):
    def test_AC013_native_trace_strips_serialized_paths_metadata_and_error_stack(self):
        captured = []
        client = Client(api_key='synthetic-not-dispatched', auto_batch_tracing=False)
        tracer = PublicTracer(client=client, project_name='synthetic-only')
        run = SimpleNamespace(id=uuid4(), name='actual-native-step',
            serialized={'kwargs': {'state_directory': 'synthetic-private-canary'}},
            extra={'metadata': {'scope': 'public_synthetic_atomic_v1', 'private': 'synthetic-private-canary'}},
            tags=['synthetic-private-canary'], error='raw stack synthetic-private-canary',
            post=lambda: captured.append(run.__dict__.copy()), patch=lambda **kw: None)
        tracer._persist_run_single(run)
        self.assertNotIn('synthetic-private-canary', json.dumps(captured, default=str))
        self.assertEqual(run.error, 'ATOMIC_CONTROLLED_ERROR')
        client.close()

    def test_AC014_export_ack_failure_is_unknown_and_does_not_retry(self):
        client = Client(api_key='synthetic-not-dispatched', auto_batch_tracing=False)
        tracer = PublicTracer(client=client, project_name='synthetic-only')
        post = Mock(side_effect=TimeoutError('synthetic-private-canary'))
        run = SimpleNamespace(id=uuid4(), name='step', serialized={}, extra={}, tags=[], error=None,
                             post=post)
        tracer._persist_run_single(run)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(tracer.delivery_errors, [str(run.id)])
        client.close()

    def test_AC031_grader_rejects_wrong_missing_or_foreign_output(self):
        expected = SimpleNamespace(outputs={'status': 'passed', 'per_share': '10'})
        for actual in ({}, {'result': {'status': 'passed', 'per_share': '999'}},
                       {'result': {'per_share': '10'}}, {'result': {'status': 'passed', 'per_share': '15'}}):
            self.assertFalse(evaluator(SimpleNamespace(outputs=actual), expected)['score'])
        result = evaluator(SimpleNamespace(outputs={'result': expected.outputs}), expected)
        self.assertTrue(result['score']); self.assertEqual(result['key'], FEEDBACK)

    def test_AC030_profile_source_and_fixture_drift_fails_before_execution(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.langchain-pilot/tmp') as directory:
            p = Path(directory); private_write(p / 'calculator/profile.json',
                {'sources': {}, 'roster_sha256': 'wrong', 'prompt_sha256': 'wrong'})
            with patch('tuning.langchain_pilot.atomic_cloud.state_root', return_value=p):
                with self.assertRaisesRegex(SessionModelError, 'PROFILE_DRIFT'): local_profile('calculator')

    def test_AC032_unknown_bootstrap_rejects_blind_replay(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.langchain-pilot/tmp') as directory:
            p = Path(directory); private_write(p / 'calculator/bootstrap.json', {'status': 'unknown'})
            remote = Mock()
            with patch('tuning.langchain_pilot.atomic_cloud.state_root', return_value=p):
                with self.assertRaisesRegex(SessionModelError, 'RECONCILE_BEFORE_REPLAY'):
                    bootstrap(remote, 'calculator')
            self.assertEqual(remote.mock_calls, [])


if __name__ == '__main__': unittest.main()
