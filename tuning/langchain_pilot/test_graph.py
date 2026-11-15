"""Requirement-derived negative controls; these do not replace real inference."""
import json
import unittest
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage

from tuning.langchain_pilot.graph import calculate, make_graph, verify
from tuning.langchain_pilot.smoke import CASE


class ScriptedModel(FakeMessagesListChatModel):
    calls: int = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, *args, **kwargs):
        self.calls += 1
        return super()._generate(*args, **kwargs)


def model(answer="10"):
    return ScriptedModel(responses=[
        AIMessage(content="", tool_calls=[{"name": "calculate_valuation", "args": {}, "id": "calc-1"}]),
        AIMessage(content=json.dumps({"per_share": answer, "synthetic": True})),
    ])


class PilotTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_tool_public_graph_and_independent_answer(self):
        agent = model("15")
        result = await make_graph(agent).ainvoke({"case": {
            **CASE, "case_id": "debt-contrast", "fcff": ["220"], "net_debt": "50"}},
            context={"variant": "concise"})
        self.assertEqual(result["result"]["per_share"], "15")
        self.assertEqual(result["result"]["tool_calls"], 1)
        self.assertEqual(agent.calls, 2)

    async def test_invalid_input_prevents_model_call(self):
        agent = model()
        for bad in ({"shares": "0"}, {"rate": "-1"}, {"fcff": ["NaN"]}):
            with self.assertRaises(ValueError):
                await make_graph(agent).ainvoke({"case": {**CASE, **bad}})
        self.assertEqual(agent.calls, 0)

    async def test_studio_extra_case_wrapper_is_normalized_once(self):
        result = await make_graph(model()).ainvoke({'case': {'case': CASE}})
        self.assertEqual(result['result']['per_share'], '10')

    async def test_missing_case_has_actionable_error_before_model(self):
        agent = model()
        for value in ({}, {'case': None}):
            with self.assertRaisesRegex(ValueError, 'CASE_REQUIRED'):
                await make_graph(agent).ainvoke(value)
        self.assertEqual(agent.calls, 0)

    async def test_wrapper_does_not_hide_extra_fields_or_multiple_wrappers(self):
        agent = model()
        for value in ({'case': CASE, 'shares': '999'}, {'case': {'case': CASE}}):
            with self.assertRaises(ValueError):
                await make_graph(agent).ainvoke({'case': value})
        self.assertEqual(agent.calls, 0)

    async def test_hallucinated_answer_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "differs"):
            await make_graph(model("999")).ainvoke({"case": CASE})

    async def test_model_answer_without_tool_use_is_rejected(self):
        agent = ScriptedModel(responses=[AIMessage(content='{"per_share":"10","synthetic":true}')])
        with self.assertRaisesRegex(ValueError, "no successful"):
            await make_graph(agent).ainvoke({"case": CASE})

    async def test_tool_failure_is_visible_and_bounded(self):
        with patch("tuning.langchain_pilot.graph.equity_value", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(Exception):
                await make_graph(model()).ainvoke({"case": CASE}, {"recursion_limit": 12})

    async def test_orphan_tool_receipt_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not bound"):
            verify({"case": CASE, "messages": [
                ToolMessage(name="calculate_valuation", tool_call_id="orphan", content=json.dumps(calculate(CASE))),
                AIMessage(content='{"per_share":"10","synthetic":true}'),
            ]})


if __name__ == "__main__":
    unittest.main()
