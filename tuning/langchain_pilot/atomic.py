"""Isolated Studio graphs with closed public-fixture ingress.

The original server keeps its graph/configuration. These graphs expose a
deterministic calculator, the real cooperative calculator, and pure holdings.
Global tracing stays off; exporting callbacks are attached only after admission.
"""
from __future__ import annotations

import os
import json
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from pydantic_core import core_schema
from pydantic import RootModel
from pydantic import ValidationError
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import StructuredTool
from investment.portfolio.snapshot import SnapshotError

from .graph import CALCULATOR_PROMPT, make_graph
from . import holdings, observability
from .session_model import canonical, require
from .session_model import SessionChatModel

KINDS = {'calculator', 'calculator_session', 'holdings'}


def fixtures(kind):
    require(kind in KINDS, 'ATOMIC_KIND_INVALID')
    if kind == 'holdings': return holdings.cases()
    rows = observability.cases()
    contract = json.loads((observability.ROOT / 'tuning/langchain_pilot/tests/atomic_contract_cases.json').read_text())
    cases = {c['id']: c for c in contract['cases']}
    for item in contract['public_synthetic_roster']:
        if not item['case'].startswith('CAL-'): continue
        source = cases[item['case']]
        case = {'case_id': item['selector'], **source['given']}
        output = {'status': 'passed', 'per_share': source['expected']['per_share']} if isinstance(
            source['expected'], dict) else {'status': 'invalid_input'}
        rows.append({'id': item['selector'], 'inputs': {'case': case}, 'outputs': output})
    return rows


def calculator_runnable():
    prompt = ChatPromptTemplate.from_messages([('system', CALCULATOR_PROMPT)])
    validate = RunnableLambda(lambda v: observability.ValuationCase.model_validate(
        v['case']).model_dump(mode='json')).with_config(run_name='validate_calculation')
    calculator = StructuredTool.from_function(observability.checked_calculation,
        name='calculate_atomic_valuation', description='Existing exact arithmetic with an independent oracle.')
    def invoke(inputs, config):
        prompt.invoke({}, config=config)
        try: case = validate.invoke(inputs, config=config)
        except ValidationError: return {'status': 'invalid_input'}
        return calculator.invoke({'case': case}, config=config)
    return RunnableLambda(invoke).with_config(run_name='calculator_atomic')


def admit(value, kind):
    try:
        require(len(canonical(value)) <= 4096, 'ATOMIC_REQUEST_SIZE_LIMIT')
    except (TypeError, ValueError, RecursionError):
        raise ValueError('ATOMIC_REQUEST_INVALID') from None
    require(isinstance(value, dict) and set(value) == {'request'}
            and isinstance(value['request'], dict)
            and set(value['request']) == {'case_id'}, 'ATOMIC_CLOSED_REQUEST_REQUIRED')
    case_id = value['request']['case_id']
    require(isinstance(case_id, str), 'ATOMIC_PUBLIC_CASE_REQUIRED')
    selected = next((c for c in fixtures(kind) if c['id'] == case_id), None)
    require(selected is not None, 'ATOMIC_PUBLIC_CASE_REQUIRED')
    return selected


def input_type(kind):
    class PublicInput(dict):
        @classmethod
        def __get_pydantic_core_schema__(cls, source, handler):
            return core_schema.typed_dict_schema({
                'request': core_schema.typed_dict_field(core_schema.typed_dict_schema({
                    'case_id': core_schema.typed_dict_field(core_schema.literal_schema(
                        [c['id'] for c in fixtures(kind)]))}, extra_behavior='forbid'))
            }, extra_behavior='forbid')
    PublicInput.__name__ = kind.title().replace('_', '') + 'PublicInput'
    return PublicInput


def make_public_graph(kind, *, cloud_runner=None, model=None):
    # Root dict channel retains every supplied key until explicit admission;
    # TypedDict-only projection could silently drop an unknown/private field.
    child = make_graph(model if model is not None else SessionChatModel(public_fixture_responses=True)) if kind == 'calculator_session' else (
        holdings.graph() if kind == 'holdings' else calculator_runnable())

    def prepare(state):
        selected = admit(state, kind)
        return {'request': {'case_id': selected['id']}, 'fixture_id': selected['id']}

    async def execute(state, config):
        selected = next(c for c in fixtures(kind) if c['id'] == state['fixture_id'])
        async def invoke(safe_config):
            if kind == 'holdings':
                output = await child.ainvoke({'inputs': selected['inputs']}, config=safe_config)
                return holdings.project(output['result'])
            if kind == 'calculator_session':
                output = await child.ainvoke(selected['inputs'], config=safe_config)
                return output['result']
            return await child.ainvoke(selected['inputs'], config=safe_config)

        runner = cloud_runner
        if runner is None and os.environ.get('ATOMIC_CLOUD_TRACING') == '1':
            from .atomic_cloud import traced_call
            runner = traced_call
        try:
            if runner:
                result, trace = await runner(kind, selected, config, invoke)
                return {'request': state['request'], 'result': result, 'trace': trace}
            return {'request': state['request'], 'result': await invoke(config),
                    'trace': {'status': 'disabled'}}
        except SnapshotError as error:
            return {'request': state['request'], 'result': holdings.rejection(error),
                    'trace': {'status': 'controlled_failure' if runner else 'disabled'}}
        except ValidationError:
            return {'request': state['request'], 'result': {'status': 'invalid_input'},
                    'trace': {'status': 'controlled_failure' if runner else 'disabled'}}

    builder = StateGraph(dict)
    builder.add_node('admit_public_fixture', prepare)
    builder.add_node('execute_atomic_capability', execute)
    builder.add_edge(START, 'admit_public_fixture')
    builder.add_edge('admit_public_fixture', 'execute_atomic_capability')
    builder.add_edge('execute_atomic_capability', END)
    graph = builder.compile(name=kind)
    # A root-value graph keeps the full envelope for explicit validation. The
    # retained builder publishes the schema even after Agent Server copies the
    # compiled graph. Compiled channels still keep the original complete input.
    schema = RootModel[input_type(kind)]
    schema.model_config['title'] = kind + ' public synthetic test'
    builder.input_schema = schema
    return graph


from .atomic_cloud import fingerprints
LOADED_SOURCES = fingerprints()

calculator_graph = make_public_graph('calculator')
session_graph = make_public_graph('calculator_session')
holdings_graph = make_public_graph('holdings')
