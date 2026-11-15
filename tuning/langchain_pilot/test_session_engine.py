"""Session-engine contract controls. Scripted replies are not live host proof."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tuning.langchain_pilot.graph import default_model, make_graph
from tuning.langchain_pilot.session_model import (
    SessionChatModel, SessionModelError, configure, load_binding, response_message)
from tuning.langchain_pilot.smoke import CASE


class SessionEngineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='.langchain-pilot/tmp')
        self.state = Path(self.temp.name)
        self.binding = configure('session-A', state=self.state)
        self.graph = make_graph(SessionChatModel(state_directory=str(self.state)),
                                checkpointer=InMemorySaver())
        self.config = {'configurable': {'thread_id': 'contract-thread'}}

    def tearDown(self):
        self.temp.cleanup()

    def request(self, output):
        return output['__interrupt__'][0].value

    def answer(self, request, message, binding=None):
        return {'request_id': request['request_id'], 'binding': binding or self.binding,
                'message': message}

    async def begin(self):
        return self.request(await self.graph.ainvoke({'case': CASE}, self.config))

    async def use_tool(self, request):
        return await self.graph.ainvoke(Command(resume=self.answer(request, {
            'content': '', 'tool_calls': [{'name': 'calculate_valuation', 'args': {}}]})),
            self.config)

    async def test_default_requires_no_provider_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsInstance(default_model(), SessionChatModel)
            request = await self.begin()
        self.assertEqual(request['binding'], self.binding)
        self.assertEqual(request['tools'][0]['function']['name'], 'calculate_valuation')

    async def test_langchain_executes_tool_and_verifies_final_host_answer(self):
        first = await self.begin(); output = await self.use_tool(first)
        second = self.request(output)
        self.assertNotEqual(first['request_id'], second['request_id'])
        tools = [m for m in second['messages'] if m['type'] == 'tool']
        self.assertEqual(len(tools), 1)
        self.assertEqual(json.loads(tools[0]['content'])['per_share'], '10')
        done = await self.graph.ainvoke(Command(resume=self.answer(second, {
            'content': '{"per_share":"10","synthetic":true}'})), self.config)
        self.assertEqual(done['result']['status'], 'passed')
        self.assertEqual(done['result']['tool_calls'], 1)

    async def test_binding_change_rejects_old_session_then_accepts_new_session(self):
        request = await self.begin()
        replacement = configure('session-B', state=self.state)
        invalid = await self.graph.ainvoke(Command(resume=self.answer(request, {
            'tool_calls': [{'name': 'calculate_valuation', 'args': {}}]})), self.config)
        repeated = self.request(invalid)
        self.assertEqual(repeated['response_error'], 'SESSION_BINDING_STALE')
        self.assertEqual(repeated['request_id'], request['request_id'])
        valid = await self.graph.ainvoke(Command(resume=self.answer(repeated, {
            'tool_calls': [{'name': 'calculate_valuation', 'args': {}}]}, replacement)), self.config)
        next_request = self.request(valid)
        self.assertEqual(next_request['binding'], replacement)
        self.assertEqual(len([m for m in next_request['messages'] if m['type'] == 'tool']), 1)

    async def test_request_cannot_be_reused_for_another_turn(self):
        request = await self.begin(); later = self.request(await self.use_tool(request))
        with self.assertRaisesRegex(SessionModelError, 'REQUEST_MISMATCH'):
            response_message(self.answer(request, {'content': 'stale'}), later, self.binding)

    async def test_fabricated_tool_receipt_and_unknown_tool_are_rejected(self):
        request = await self.begin()
        for message in ({'role': 'tool', 'content': 'fabricated'},
                        {'tool_calls': [{'name': 'send_email', 'args': {}}]}):
            with self.assertRaises(SessionModelError):
                response_message(self.answer(request, message), request, self.binding)

    async def test_malformed_tool_name_remains_recoverable_in_persisted_thread(self):
        request = await self.begin()
        for name in ([], {}):
            invalid = await self.graph.ainvoke(Command(resume=self.answer(request, {
                'tool_calls': [{'name': name, 'args': {}}]})), self.config)
            request = self.request(invalid)
            self.assertEqual(request['response_error'], 'SESSION_TOOL_CALL_INVALID')
        next_request = self.request(await self.use_tool(request))
        self.assertEqual(len([m for m in next_request['messages'] if m['type'] == 'tool']), 1)

    async def test_nonfinite_and_non_json_arguments_remain_recoverable(self):
        request = await self.begin()
        for args in ({'unexpected': float('nan')}, {'unexpected': float('inf')},
                     {3: 'non-string-key'}):
            invalid = await self.graph.ainvoke(Command(resume=self.answer(request, {
                'tool_calls': [{'name': 'calculate_valuation', 'args': args}]})), self.config)
            request = self.request(invalid)
            self.assertEqual(request['response_error'], 'SESSION_ASSISTANT_MESSAGE_REQUIRED')
        next_request = self.request(await self.use_tool(request))
        self.assertEqual(len([m for m in next_request['messages'] if m['type'] == 'tool']), 1)

    async def test_invalid_case_never_reaches_session_engine(self):
        with self.assertRaises(ValueError):
            await self.graph.ainvoke({'case': {**CASE, 'shares': '0'}}, self.config)
        state = await self.graph.aget_state(self.config)
        self.assertFalse(any(task.interrupts for task in state.tasks))

    async def test_wrong_model_answer_still_fails_independent_result_gate(self):
        request = self.request(await self.use_tool(await self.begin()))
        with self.assertRaisesRegex(ValueError, 'differs'):
            await self.graph.ainvoke(Command(resume=self.answer(request, {
                'content': '{"per_share":"999","synthetic":true}'})), self.config)

    async def test_binding_configuration_is_durable_and_revisioned(self):
        next_binding = configure('another-native-thread', state=self.state)
        self.assertEqual(load_binding(self.state), next_binding)
        self.assertEqual(next_binding['revision'], 2)
        self.assertEqual(len(list((self.state / 'bindings').glob('*.json'))), 2)


if __name__ == '__main__':
    unittest.main()
