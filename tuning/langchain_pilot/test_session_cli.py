"""CLI journal/recovery boundaries with real graphs and an in-process SDK seam.

No server/provider effects. This does not prove live Agent Server durability.
"""
from contextlib import redirect_stdout
import asyncio
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tuning.langchain_pilot.graph import make_graph
from tuning.langchain_pilot.session_engine import advance, pending, report, respond
from tuning.langchain_pilot.session_model import (
    SessionChatModel, SessionModelError, configure, load_binding, private_read, private_write)
from tuning.langchain_pilot.smoke import CASE


class GraphClient:
    """Public SDK-shaped seam; tool execution and checkpoints use the real graph."""
    def __init__(self, graph, thread):
        self.graph = graph
        self.thread = thread
        self.config = {'configurable': {'thread_id': thread}}
        self.before_dispatch = None
        self.runs = SimpleNamespace(stream=self.stream, get=lambda *args: self.run)
        self.threads = SimpleNamespace(get_state=self.state)
        self.sequence = 0

    def state(self, thread, subgraphs=True):
        snapshot = self.graph.get_state(self.config, subgraphs=True)
        def tasks(value):
            return [{'interrupts': [{'value': i.value} for i in task.interrupts],
                     'tasks': tasks(task.state) if hasattr(task.state, 'tasks') else []}
                    for task in value.tasks]
        return {'values': snapshot.values, 'tasks': tasks(snapshot),
                'checkpoint': snapshot.config['configurable']}

    def stream(self, thread, graph_id, **kwargs):
        self.sequence += 1
        self.run = {'run_id': 'run-' + str(self.sequence), 'thread_id': thread, 'status': 'success'}
        kwargs['on_run_created'](self.run)
        if self.before_dispatch:
            action, self.before_dispatch = self.before_dispatch, None
            action()
        try:
            value = (Command(resume=kwargs['command']['resume']) if kwargs['command']
                     else kwargs['input'])
            output = asyncio.run(self.graph.ainvoke(value, self.config))
            if '__interrupt__' in output:
                output = {**output, '__interrupt__': [{'value': i.value} for i in output['__interrupt__']]}
            yield SimpleNamespace(event='values', data=output)
        except Exception:
            self.run['status'] = 'error'
            yield SimpleNamespace(event='error', data={'error': 'synthetic graph failure'})


class SessionCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='.langchain-pilot/tmp')
        self.state = Path(self.temp.name)
        self.binding = configure('session-A', state=self.state)
        graph = make_graph(SessionChatModel(state_directory=str(self.state)),
                           checkpointer=InMemorySaver())
        self.client = GraphClient(graph, 'cli-contract-thread')
        asyncio.run(graph.ainvoke({'case': CASE}, self.client.config))

    def tearDown(self):
        self.temp.cleanup()

    def answer(self, message=None):
        request = pending(self.client, self.client.thread, state_directory=self.state)['request']
        return {'request_id': request['request_id'], 'binding': load_binding(self.state),
                'message': message or {'tool_calls': [{'name': 'calculate_valuation', 'args': {}}]}}

    def send(self, envelope):
        return respond(self.client, self.client.thread, envelope,
                       session_id=envelope['binding']['session_id'],
                       revision=envelope['binding']['revision'], state_directory=self.state)

    def test_rebind_after_prevalidation_keeps_rejection_nonconsuming(self):
        first = self.answer()
        self.client.before_dispatch = lambda: configure('session-B', state=self.state)
        rejected = self.send(first)
        self.assertEqual(rejected['response_status'], 'rejected')
        self.assertEqual(rejected['state']['request']['request_id'], first['request_id'])
        self.assertEqual(rejected['state']['request']['response_error'], 'SESSION_BINDING_STALE')
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            report(rejected)
        accepted = self.send(self.answer())
        self.assertEqual(accepted['response_status'], 'processed')
        receipts = [private_read(p) for p in (self.state / 'responses' / first['request_id']).glob('*.json')]
        self.assertCountEqual([r['status'] for r in receipts], ['rejected', 'processed'])
        tools = [m for m in accepted['state']['request']['messages'] if m['type'] == 'tool']
        self.assertEqual(len(tools), 1)

    def test_error_stream_and_run_are_visible_failure_with_nonzero_report(self):
        self.send(self.answer())
        failed = self.send(self.answer({'content': '{"per_share":"999","synthetic":true}'}))
        self.assertEqual(failed['outcome'], 'failed')
        self.assertEqual(failed['response_status'], 'failed')
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as error:
            report(failed)
        self.assertEqual(error.exception.code, 1)
        self.assertIn('SESSION_GRAPH_RUN_FAILED', output.getvalue())

    def test_unknown_dispatch_remains_fenced(self):
        envelope = self.answer()
        with patch('tuning.langchain_pilot.session_engine.advance', side_effect=TimeoutError):
            with self.assertRaises(TimeoutError): self.send(envelope)
        with self.assertRaisesRegex(SessionModelError, 'RECONCILE_BEFORE_REPLAY'):
            self.send(envelope)
        receipts = list((self.state / 'responses' / envelope['request_id']).glob('*.json'))
        self.assertEqual(private_read(receipts[0])['status'], 'unknown')

    def test_legacy_accepted_receipt_remains_fenced(self):
        envelope = self.answer()
        private_write(self.state / 'responses' / (envelope['request_id'] + '.json'), {
            'request_id': envelope['request_id'], 'thread_id': self.client.thread, 'status': 'processed'})
        with self.assertRaisesRegex(SessionModelError, 'RECONCILE_BEFORE_REPLAY'):
            self.send(envelope)

    def test_exact_run_readback_checks_error_nonterminal_and_identity(self):
        for status, same_identity, expected in (
                ('error', True, 'failed'), ('running', True, 'unknown'),
                ('success', False, 'unknown')):
            run = {'run_id': 'exact' if same_identity else 'another',
                   'thread_id': self.client.thread, 'status': status}
            def stream(*args, **kwargs):
                kwargs['on_run_created']({'run_id': 'exact'})
                return iter([])
            client = SimpleNamespace(threads=self.client.threads,
                                     runs=SimpleNamespace(stream=stream, get=lambda *args: run))
            result = advance(client, self.client.thread, state_directory=self.state)
            self.assertEqual(result['outcome'], expected)

    def test_latest_thread_success_cannot_replace_own_empty_stream_result(self):
        def stream(*args, **kwargs):
            kwargs['on_run_created']({'run_id': 'own-run'})
            return iter([SimpleNamespace(event='values', data={'result': {}})])
        projection = {'values': {'result': {'status': 'passed', 'case_id': 'another-case'}},
                      'tasks': [], 'checkpoint': {}}
        client = SimpleNamespace(
            threads=SimpleNamespace(get_state=lambda *args, **kwargs: projection),
            runs=SimpleNamespace(stream=stream, get=lambda *args: {
                'run_id': 'own-run', 'thread_id': self.client.thread, 'status': 'success'}))
        result = advance(client, self.client.thread, state_directory=self.state)
        self.assertEqual(result['outcome'], 'failed')
        self.assertEqual(result['error'], 'SESSION_GRAPH_RESULT_MISSING')


if __name__ == '__main__':
    unittest.main()
