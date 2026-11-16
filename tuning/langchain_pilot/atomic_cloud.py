"""Opt-in synthetic tracing/evaluation with owned immutable attempt receipts."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import time
from fractions import Fraction
from uuid import UUID, uuid4, uuid5

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_core.tracers import LangChainTracer
from langgraph.errors import GraphBubbleUp
from langsmith import tracing_context

from . import observability as obs
from .session_model import ROOT, canonical, private_read, private_write, require

SCOPE = 'public_synthetic_atomic_v1'
FEEDBACK = 'atomic_contract_correct'
SOURCES = ('tuning/langchain_pilot/atomic.py', 'tuning/langchain_pilot/atomic_cloud.py',
           'tuning/langchain_pilot/graph.py', 'tuning/langchain_pilot/session_model.py',
           'tuning/langchain_pilot/holdings.py', 'investment/portfolio/snapshot.py',
           'niulai/holdings/analytics.py', 'tuning/langchain_pilot/requirements.lock.txt',
           'tuning/langchain_pilot/ATOMIC_ACCEPTANCE.md', 'tuning/langchain_pilot/observability.py',
           'tuning/langchain_pilot/tests/atomic_contract_cases.json',
           'tuning/langchain_pilot/holdings_contract_fixtures.py',
           'tuning/langchain_pilot/serve.py', 'tuning/langchain_pilot/atomic-langgraph.json',
           'tuning/langchain_pilot/strict_cli.py',
           'tuning/langchain_pilot/rate_policy.py', 'tuning/langchain_pilot/cloud-read-policy.json',
           'shared/calculation/legacy/valuation/valuation_core.py')


def fingerprints():
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES}


def state_root():
    return ROOT / '.langchain-pilot/runtime/atomic' / obs.digest(fingerprints())[:16]


def prompt_text(kind):
    return ('Use only admitted synthetic account/currency/scope evidence. Preserve missing values, '
            'unknown quote time and daily PnL. This deterministic portfolio adapter invokes no model.'
            if kind == 'holdings' else obs.CALCULATOR_PROMPT)


def roster(kind):
    from .atomic import fixtures
    return [{'id': c['id'], 'inputs': {'request': {'case_id': c['id']}}, 'outputs': c['outputs'],
             'fixture_sha256': obs.digest(c['inputs'])}
            for c in fixtures(kind)]


def local_profile(kind):
    value = private_read(state_root() / kind / 'profile.json')
    require(value['sources'] == fingerprints() and value['roster_sha256'] == obs.digest(roster(kind))
            and value['prompt_sha256'] == obs.digest(prompt_text(kind)), 'ATOMIC_PROFILE_DRIFT')
    return value


def bootstrap(c, kind, *, reconcile=False, tag_value_ids=None):
    directory = state_root() / kind
    if (directory / 'profile.json').exists(): return local_profile(kind)
    claim = directory / 'bootstrap.json'
    suffix = state_root().name + '-' + kind
    names = {'project_name': 'atomic-test-' + suffix, 'dataset_name': 'atomic-cases-' + suffix,
             'prompt_name': 'atomic-prompt-' + suffix}
    rows = roster(kind)
    identity = {'scope': SCOPE, 'kind': kind, 'candidate': state_root().name,
                'candidate_sha256': obs.digest(fingerprints()),
                'roster_sha256': obs.digest(rows), 'agent_id': obs.AGENT}
    if reconcile:
        require(claim.exists(), 'ATOMIC_NO_BOOTSTRAP_TO_RECONCILE')
    else:
        require(not claim.exists(), 'ATOMIC_BOOTSTRAP_UNKNOWN_RECONCILE_BEFORE_REPLAY')
        private_write(claim, {**identity, **names, 'status': 'creating'})
    try:
        if hasattr(c, 'warmup'): c.warmup()
        if reconcile:
            saved = private_read(claim)
            require(bool(saved.get('project_id')) and bool(saved.get('dataset_id')),
                    'ATOMIC_BOOTSTRAP_RESOURCE_IDS_UNKNOWN')
            project = c.read_project(project_id=saved['project_id'])
            dataset = c.read_dataset(dataset_id=saved['dataset_id'])
            require(str(project.id) == saved['project_id'] and str(dataset.id) == saved['dataset_id'],
                    'ATOMIC_BOOTSTRAP_RESOURCE_ID_MISMATCH')
        else:
            project = c.create_project(names['project_name'], metadata=identity,
                                       tag_value_ids=tag_value_ids)
            private_write(claim, {**identity, **names, 'status': 'creating',
                                 'project_id': str(project.id)}, replace=True)
            dataset = c.create_dataset(names['dataset_name'], metadata=identity, tag_value_ids=tag_value_ids,
                description='Owned public synthetic atomic fixtures retained for user testing.')
            private_write(claim, {**identity, **names, 'status': 'creating',
                'project_id': str(project.id), 'dataset_id': str(dataset.id)}, replace=True)
            c.push_prompt(names['prompt_name'], object=ChatPromptTemplate.from_messages(
                [('system', prompt_text(kind))]), is_public=False)
            c.create_examples(dataset_id=dataset.id, examples=[
                {'id': str(uuid5(UUID(str(dataset.id)), row['id'])), 'inputs': row['inputs'],
                 'reference_outputs': row['outputs'], 'metadata': {**identity, 'case_id': row['id'],
                                                            'fixture_sha256': row['fixture_sha256']}}
                for row in rows], max_concurrency=1)
        require(all(project.extra.get('metadata', {}).get(k) == v for k, v in identity.items()),
                'ATOMIC_PROJECT_IDENTITY')
        require(all((dataset.metadata or {}).get(k) == v for k, v in identity.items()),
                'ATOMIC_DATASET_IDENTITY')
        commit = c.pull_prompt_commit(names['prompt_name'], skip_cache=True)
        prompt = c.pull_prompt(names['prompt_name'] + ':' + commit.commit_hash, skip_cache=True)
        require(prompt.invoke({}).to_messages()[0].content == prompt_text(kind), 'ATOMIC_PROMPT_DRIFT')
        examples = list(c.list_examples(dataset_id=dataset.id, limit=len(rows) + 1))
        expected = {str(uuid5(UUID(str(dataset.id)), row['id'])): row for row in rows}
        require(len(examples) == len(expected) and {str(x.id) for x in examples} == set(expected),
                'ATOMIC_ROSTER_MISMATCH')
        for example in examples:
            row = expected[str(example.id)]
            require(example.inputs == row['inputs'] and example.outputs == row['outputs']
                    and example.metadata.get('fixture_sha256') == row['fixture_sha256'],
                    'ATOMIC_EXAMPLE_DRIFT')
        as_of = max(x.modified_at for x in examples).isoformat()
        value = {**identity, **names, 'project_id': str(project.id), 'dataset_id': str(dataset.id),
            'dataset_as_of': as_of, 'prompt_commit': commit.commit_hash,
            'prompt_sha256': obs.digest(prompt_text(kind)), 'sources': fingerprints(),
            'examples': {r['id']: str(uuid5(UUID(str(dataset.id)), r['id'])) for r in rows}}
        private_write(directory / 'profile.json', value)
        private_write(claim, {**value, 'status': 'verified'}, replace=True)
        return value
    except BaseException:
        saved = private_read(claim)
        private_write(claim, {**saved, 'status': 'unknown'}, replace=True)
        raise


class PublicTracer(LangChainTracer):
    """Keep real native callbacks/parentage, strip runtime paths and raw errors."""
    run_inline = False  # Async callback manager keeps slow exports off the API event loop.
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.delivery_errors = []
        self.native_run_ids = []

    def copy_with_metadata_defaults(self, *, metadata=None, tags=None):
        # Native callback managers clone tracers while propagating metadata.
        # Delivery is one attempt across those clones, like their shared run_map.
        copied = super().copy_with_metadata_defaults(metadata=metadata, tags=tags)
        copied.delivery_errors = self.delivery_errors
        copied.native_run_ids = self.native_run_ids
        return copied

    def _start_trace(self, run):
        # Only this explicitly admitted callback may export. Ambient traceable
        # middleware must stay disabled: it otherwise creates additional spans
        # outside this attempt's identity ledger and sanitization boundary.
        super()._start_trace(run)
        run.extra.pop('__disabled', None)

    def _clean(self, run):
        run.serialized = {'name': run.name}
        meta = run.extra.get('metadata', {})
        allowed = {'scope', 'kind', 'agent_id', 'fixture_id', 'graph_thread_id', 'cloud_attempt_id',
                   'candidate', 'candidate_sha256', 'roster_sha256', 'prompt_commit', 'prompt_sha256',
                   'model_identity', 'fixture_sha256', 'host_wait_seconds', 'ls_model_type', 'ls_model_name', 'ls_provider'}
        run.extra = {'metadata': {k: v for k, v in meta.items() if k in allowed}}
        run.tags = [SCOPE]
        if run.error:
            run.error = ('ATOMIC_COOPERATIVE_WAIT' if run.error == 'ATOMIC_COOPERATIVE_WAIT'
                         or 'GraphInterrupt' in run.error
                         else 'ATOMIC_CONTROLLED_ERROR')
        run.ls_client = self.client

    def _persist_run_single(self, run):
        if run.extra.get('__disabled'): return
        self._clean(run)
        self.native_run_ids.append(str(run.id))
        try: run.post()
        except Exception:
            self.delivery_errors.append(str(run.id))

    def _update_run_single(self, run):
        if run.extra.get('__disabled'): return
        self._clean(run)
        try: run.patch(exclude_inputs=True)
        except Exception:
            self.delivery_errors.append(str(run.id))


async def traced_call(kind, selected, config, invoke):
    profile = local_profile(kind)
    from .atomic import LOADED_SOURCES
    require(LOADED_SOURCES == profile['sources'] == fingerprints(), 'ATOMIC_ACTIVE_SOURCE_DRIFT')
    thread = config.get('configurable', {}).get('thread_id')
    try:
        require(isinstance(thread, str) and str(UUID(thread)) == thread, 'ATOMIC_THREAD_ID_REQUIRED')
    except (ValueError, TypeError, AttributeError):
        raise ValueError('ATOMIC_THREAD_ID_REQUIRED') from None
    prior = [private_read(path) for path in (state_root() / kind / 'traces').glob('*.json')]
    prior = [x for x in prior if x.get('graph_thread_id') == thread]
    require(all(x['status'] not in {'unknown', 'dispatching'} for x in prior),
            'ATOMIC_TRACE_UNKNOWN_RECONCILE_BEFORE_RESUME')
    previous = max(prior, key=lambda x: x['created_at_ns']) if prior else None
    run_id = uuid4()
    attempt = state_root() / kind / 'traces' / (str(run_id) + '.json')
    intent = {'status': 'dispatching', 'scope': SCOPE, 'kind': kind, 'fixture_id': selected['id'],
        'run_id': str(run_id), 'graph_thread_id': thread, 'project_id': profile['project_id'],
        'created_at_ns': time.time_ns(), 'candidate': state_root().name}
    intent['candidate_sha256'] = obs.digest(profile['sources'])
    if previous:
        intent['previous_trace_run_id'] = previous['run_id']
    private_write(attempt, intent)
    c = obs.client()
    tracer = PublicTracer(client=c, project_name=profile['project_name'],
                          example_id=UUID(profile['examples'][selected['id']]))
    safe_config = {**config, 'callbacks': [tracer], 'run_id': run_id, 'tags': [SCOPE],
        'run_name': kind,
        'metadata': {**{k: intent[k] for k in ('scope', 'kind', 'fixture_id', 'graph_thread_id', 'candidate')},
            'cloud_attempt_id': str(run_id), 'roster_sha256': profile['roster_sha256'],
            'agent_id': obs.AGENT,
            'candidate_sha256': intent['candidate_sha256'],
            'fixture_sha256': obs.digest(selected['inputs']),
            'prompt_commit': profile['prompt_commit'], 'prompt_sha256': profile['prompt_sha256'],
            'model_identity': 'host_session_declared_not_attested' if kind == 'calculator_session'
                              else 'no_model_call'}}
    if previous:
        safe_config['metadata']['host_wait_seconds'] = max(0, (
            intent['created_at_ns'] - previous.get('ended_at_ns', intent['created_at_ns'])) / 1e9)
    outcome = 'unknown'; result = None
    trace_info = {'status': 'recorded_pending_readback', 'run_id': str(run_id),
                  'kind': kind, 'candidate': state_root().name}
    try:
        if hasattr(c, 'warmup'): c.warmup()
        with tracing_context(enabled=False, client=c, project_name=profile['project_name']):
            result = await invoke(safe_config)
        outcome = 'completed'
        return result, trace_info
    except GraphBubbleUp:
        outcome = 'waiting'
        raise
    except BaseException:
        outcome = 'failed'
        raise
    finally:
        try:
            tracer.wait_for_futures()
            execution_outcome = outcome
            if tracer.delivery_errors:
                outcome = 'unknown'; trace_info['status'] = 'unknown'
            private_write(attempt, {**intent, 'status': outcome, 'result': result,
                'execution_outcome': execution_outcome, 'native_run_ids': list(dict.fromkeys(tracer.native_run_ids)),
                'delivery_errors': tracer.delivery_errors, 'ended_at_ns': time.time_ns()}, replace=True)
        finally: c.close()


def _model_evidence(run):
    """Read native generation data without invoking a deserializer or model."""
    rows = (run.outputs or {}).get('generations')
    require(isinstance(rows, list) and rows and all(isinstance(batch, list) and batch for batch in rows),
            'ATOMIC_TRACE_MODEL_OUTPUT_MISSING')
    calls, answers = [], []
    for batch in rows:
        for generation in batch:
            message = generation.get('message', {})
            require(message.get('lc') == 1 and message.get('type') == 'constructor'
                    and message.get('id', [])[-1:] == ['AIMessage'], 'ATOMIC_TRACE_MODEL_MESSAGE')
            body = message.get('kwargs', {})
            selected_calls = body.get('tool_calls', [])
            if selected_calls:
                require(body.get('content') == '', 'ATOMIC_TRACE_MODEL_MESSAGE')
                for call in selected_calls:
                    require(call.get('name') == 'calculate_valuation' and call.get('args') == {}
                            and isinstance(call.get('id'), str), 'ATOMIC_TRACE_MODEL_TOOL_CALL')
                    calls.append(call['id'])
            else:
                try: answer = json.loads(body.get('content', ''))
                except (ValueError, TypeError): raise ValueError('ATOMIC_TRACE_MODEL_MESSAGE') from None
                require(isinstance(answer, dict) and set(answer) == {'per_share', 'synthetic'}
                        and answer['synthetic'] is True and isinstance(answer['per_share'], str),
                        'ATOMIC_TRACE_MODEL_MESSAGE')
                answers.append(answer)
    return calls, answers


def _tool_evidence(run, kind, fixture, selected, thread):
    require(isinstance(run.outputs, dict) and set(run.outputs) == {'output'},
            'ATOMIC_TRACE_TOOL_OUTPUT_MISSING')
    output = run.outputs['output']
    if kind == 'calculator':
        require(run.name == 'calculate_atomic_valuation' and run.inputs == fixture['inputs']
                and output == selected['outputs'], 'ATOMIC_TRACE_TOOL_RESULT')
        return None
    if kind == 'holdings':
        from investment.portfolio.snapshot import admit_snapshot
        from .holdings import project
        value = fixture['inputs']
        admitted = admit_snapshot(value['envelope'], value['receipt'], as_of=value['as_of'])
        require(run.name == 'portfolio_analysis_tool'
                and run.inputs == {'admitted': admitted, 'taxonomy': value['taxonomy']}
                and project(output) == selected['outputs'], 'ATOMIC_TRACE_TOOL_RESULT')
        return None
    from .graph import ValuationCase
    if hasattr(output, 'model_dump'): output = output.model_dump(mode='json')
    require(isinstance(output, dict) and output.get('type') == 'tool'
            and output.get('name') == 'calculate_valuation' and output.get('status') == 'success'
            and run.inputs == {}, 'ATOMIC_TRACE_TOOL_RECEIPT')
    case = ValuationCase.model_validate(fixture['inputs']['case']).model_dump(mode='json')
    artifact = output.get('artifact')
    call_id = output.get('tool_call_id')
    require(isinstance(call_id, str) and artifact == {'schema_version': 2,
        'case_sha256': hashlib.sha256(canonical(case).encode()).hexdigest(),
        'tool_call_id': call_id, 'execution_thread_id': thread}, 'ATOMIC_TRACE_TOOL_RECEIPT')
    try:
        amount = json.loads(output['content'])
        discount = 1 + Fraction(case['rate'])
        enterprise = sum(Fraction(x) / discount ** i for i, x in enumerate(case['fcff'], 1))
        enterprise += Fraction(case['terminal_ev']) / discount ** len(case['fcff'])
        equity = enterprise - Fraction(case['net_debt'])
        correct = (set(amount) == {'case_id', 'enterprise_pv', 'nonoperating_pv', 'equity_pv', 'per_share'}
                   and amount['case_id'] == case['case_id'] and Fraction(amount['enterprise_pv']) == enterprise
                   and Fraction(amount['equity_pv']) == equity and Fraction(amount['nonoperating_pv']) == 0
                   and Fraction(amount['per_share']) == equity / Fraction(case['shares']))
    except (ValueError, TypeError, KeyError, ZeroDivisionError): correct = False
    require(correct, 'ATOMIC_TRACE_TOOL_RESULT')
    return call_id


def check_trace(c, kind, attempt_name, *, _visited=None):
    require(isinstance(attempt_name, str) and re.fullmatch(r'[0-9a-f-]{36}\.json', attempt_name),
            'ATOMIC_TRACE_ATTEMPT_REQUIRED')
    profile = local_profile(kind)
    visited = set() if _visited is None else set(_visited)
    require(attempt_name not in visited and len(visited) < 32,
            'ATOMIC_TRACE_SEGMENT_CHAIN_INVALID')
    visited.add(attempt_name)
    path = state_root() / kind / 'traces' / attempt_name
    saved = private_read(path)
    require(saved['project_id'] == profile['project_id'] and saved['kind'] == kind
            and saved['scope'] == SCOPE and saved['candidate'] == profile['candidate']
            and saved['candidate_sha256'] == profile['candidate_sha256'],
            'ATOMIC_TRACE_PROJECT_MISMATCH')
    selected = next((row for row in roster(kind) if row['id'] == saved['fixture_id']), None)
    require(selected is not None, 'ATOMIC_TRACE_FIXTURE_MISMATCH')
    root = obs.read_exact_run(c, saved['run_id'], project_id=profile['project_id'], children=True)
    require(root.parent_run_id is None, 'ATOMIC_TRACE_ROOT_PARENT_MISMATCH')
    require(root.run_type == 'chain' and root.name == kind
            and str(root.reference_example_id) == profile['examples'][saved['fixture_id']],
            'ATOMIC_TRACE_ROOT_BINDING')
    from .atomic import fixtures
    fixture = next(row for row in fixtures(kind) if row['id'] == saved['fixture_id'])
    expected_inputs = {'inputs': fixture['inputs']} if kind == 'holdings' else fixture['inputs']
    require(root.inputs == expected_inputs, 'ATOMIC_TRACE_INPUT_MISMATCH')
    nodes = []
    seen = set()
    def visit(run, parent=None):
        require(str(run.id) not in seen and len(seen) < 512, 'ATOMIC_TRACE_TREE_INVALID')
        require((str(run.parent_run_id) if run.parent_run_id else None) == parent,
                'ATOMIC_TRACE_PARENT_MISMATCH')
        seen.add(str(run.id))
        nodes.append(run)
        for child in run.child_runs or []: visit(child, str(run.id))
    visit(root)
    ids = {str(run.id) for run in nodes}
    require(ids == set(saved['native_run_ids']) and str(root.id) == saved['run_id'],
            'ATOMIC_TRACE_ID_OR_CHILD_MISMATCH')
    expected_meta = {'scope': SCOPE, 'kind': kind, 'agent_id': obs.AGENT,
        'graph_thread_id': saved['graph_thread_id'], 'fixture_id': saved['fixture_id'],
        'candidate': profile['candidate'], 'candidate_sha256': profile['candidate_sha256'],
        'cloud_attempt_id': saved['run_id'], 'roster_sha256': profile['roster_sha256'],
        'fixture_sha256': selected['fixture_sha256'], 'prompt_commit': profile['prompt_commit'],
        'prompt_sha256': profile['prompt_sha256'],
        'model_identity': 'host_session_declared_not_attested' if kind == 'calculator_session'
                          else 'no_model_call'}
    allowed_meta = set(expected_meta) | {'host_wait_seconds', 'ls_model_type', 'ls_model_name',
        'ls_provider', 'ls_run_depth'} | {'ls_example_' + key for key in (
            'scope', 'kind', 'candidate', 'candidate_sha256', 'roster_sha256', 'agent_id',
            'case_id', 'fixture_sha256', 'dataset_split')}
    model_calls, model_answers, tool_receipts = [], [], []
    for run in nodes:
        meta = (run.extra or {}).get('metadata', {})
        require(set(run.extra or {}) <= {'metadata'} and set(meta) <= allowed_meta
                and run.tags == [SCOPE] and not run.attachments
                and run.serialized in (None, {'name': run.name}), 'ATOMIC_TRACE_PRIVATE_ENVELOPE')
        require(run.error is None or run.error in {'ATOMIC_COOPERATIVE_WAIT', 'ATOMIC_CONTROLLED_ERROR'},
                'ATOMIC_TRACE_RAW_ERROR')
        require(run.end_time is not None and run.start_time is not None
                and run.end_time >= run.start_time, 'ATOMIC_TRACE_SEGMENT_NOT_TERMINAL')
        require(str(run.session_id) == profile['project_id']
                and all(meta.get(key) == value for key, value in expected_meta.items()),
                'ATOMIC_TRACE_EXECUTION_BINDING')
        if str(run.id) != saved['run_id']:
            require(str(run.parent_run_id) in ids, 'ATOMIC_TRACE_PARENT_MISMATCH')
        if not run.error and run.run_type == 'llm':
            calls, answers = _model_evidence(run)
            model_calls.extend(calls); model_answers.extend(answers)
        if not run.error and run.run_type == 'tool':
            call_id = _tool_evidence(run, kind, fixture, selected, saved['graph_thread_id'])
            if call_id: tool_receipts.append(call_id)
    outcome = saved.get('execution_outcome', saved['status'])
    successful = [(run.run_type, run.name) for run in nodes if not run.error]
    aggregate = list(successful)
    if kind == 'calculator_session' and saved.get('previous_trace_run_id'):
        previous_name = saved['previous_trace_run_id'] + '.json'
        previous_saved = private_read(state_root() / kind / 'traces' / previous_name)
        require(previous_saved['graph_thread_id'] == saved['graph_thread_id']
                and previous_saved['fixture_id'] == saved['fixture_id']
                and previous_saved['created_at_ns'] < saved['created_at_ns'],
                'ATOMIC_TRACE_SEGMENT_BINDING')
        previous = check_trace(c, kind, previous_name, _visited=visited)
        aggregate.extend(tuple(item) for item in previous['successful_native_spans'])
        model_calls.extend(previous['model_tool_call_ids'])
        tool_receipts.extend(previous['tool_receipt_ids'])
    require(set(tool_receipts) <= set(model_calls), 'ATOMIC_TRACE_TOOL_SELECTION_MISSING')
    if kind in {'calculator', 'holdings'}:
        require(not any(run.run_type == 'llm' for run in nodes), 'ATOMIC_TRACE_UNEXPECTED_MODEL')
    if outcome == 'waiting':
        require(root.error == 'ATOMIC_COOPERATIVE_WAIT', 'ATOMIC_TRACE_WAIT_MISMATCH')
    elif outcome == 'failed':
        require(bool(root.error), 'ATOMIC_TRACE_FAILURE_MISSING')
    else:
        require(outcome == 'completed' and root.error is None, 'ATOMIC_TRACE_OUTCOME_MISMATCH')
        if kind == 'holdings':
            from .holdings import project
            actual = project(root.outputs['result'])
        elif kind == 'calculator_session': actual = root.outputs['result']
        else: actual = root.outputs
        require(actual == saved['result'], 'ATOMIC_TRACE_RESULT_MISMATCH')
        if kind == 'calculator_session':
            require(actual.get('status') == selected['outputs']['status']
                    and actual.get('per_share') == selected['outputs'].get('per_share')
                    and actual.get('answer') == {'per_share': selected['outputs'].get('per_share'),
                                                  'synthetic': True},
                    'ATOMIC_TRACE_FROZEN_RESULT_MISMATCH')
        else:
            require(actual == selected['outputs'], 'ATOMIC_TRACE_FROZEN_RESULT_MISMATCH')
        if kind == 'calculator' and actual.get('status') == 'passed':
            require(('tool', 'calculate_atomic_valuation') in successful, 'ATOMIC_TRACE_TOOL_MISSING')
        elif kind == 'holdings' and actual.get('status') == 'analyzed':
            require(('tool', 'portfolio_analysis_tool') in successful, 'ATOMIC_TRACE_TOOL_MISSING')
        elif kind == 'calculator_session' and actual.get('status') == 'passed':
            require(any(run_type == 'llm' for run_type, _ in successful), 'ATOMIC_TRACE_MODEL_MISSING')
            require(('tool', 'calculate_valuation') in aggregate, 'ATOMIC_TRACE_TOOL_MISSING')
            require(actual['answer'] in model_answers, 'ATOMIC_TRACE_FINAL_MODEL_ANSWER_MISSING')
    payload = [run.model_dump(mode='json') for run in nodes]
    require(obs.credential() not in canonical(payload), 'ATOMIC_SECRET_IN_TRACE')
    record = {**saved, 'status': outcome, 'readback_verified': True,
              'run_url': c.get_run_url(run=root), 'run_types': [x.run_type for x in nodes],
              'successful_native_spans': aggregate,
              'model_tool_call_ids': model_calls, 'tool_receipt_ids': tool_receipts,
              'verified_at_ns': time.time_ns()}
    private_write(path, record, replace=True)
    return record


def evaluator(run, example):
    actual = (run.outputs or {}).get('result')
    return {'key': FEEDBACK, 'score': actual == example.outputs,
            'comment': 'Frozen public atomic contract; independent arithmetic/integrity tests are separate.'}


def admitted_examples(c, kind, profile):
    """Remote data is untrusted until the entire frozen roster is checked.

    This runs before constructing an exporting target or creating an experiment.
    A dictionary alone would erase duplicate remote rows and hide contradictions.
    """
    rows = list(c.list_examples(dataset_id=profile['dataset_id'], as_of=profile['dataset_as_of']))
    frozen = {profile['examples'][row['id']]: row for row in roster(kind)}
    require(len(rows) == len(frozen) and {str(x.id) for x in rows} == set(frozen),
            'ATOMIC_FROZEN_EXAMPLE_ROSTER')
    from .atomic import admit
    for actual in rows:
        expected = frozen[str(actual.id)]
        admit(actual.inputs, kind)
        require(actual.inputs == expected['inputs'] and actual.outputs == expected['outputs']
                and actual.metadata.get('fixture_sha256') == expected['fixture_sha256'],
                'ATOMIC_FROZEN_EXAMPLE_DRIFT')
        require(set(actual.metadata or {}) <= {'scope', 'kind', 'candidate', 'candidate_sha256',
                'roster_sha256', 'agent_id', 'case_id', 'fixture_sha256', 'dataset_split'}
                and actual.metadata.get('dataset_split', ['base']) == ['base']
                and not getattr(actual, 'attachments', None), 'ATOMIC_EXAMPLE_METADATA_NOT_PUBLIC')
    return rows


def evaluate(c, kind):
    if hasattr(c, 'warmup'): c.warmup()
    require(kind != 'calculator_session', 'ATOMIC_COOPERATIVE_EVALUATION_REQUIRES_HOST')
    profile = local_profile(kind)
    claim = state_root() / kind / 'evaluation.json'
    require(not claim.exists(), 'ATOMIC_EVALUATION_UNKNOWN_RECONCILE_BEFORE_REPLAY')
    examples = admitted_examples(c, kind, profile)
    identity = {'scope': SCOPE, 'kind': kind, 'candidate': state_root().name,
                'roster_sha256': profile['roster_sha256']}
    name = 'atomic-evaluation-' + state_root().name + '-' + kind
    private_write(claim, {**identity, 'status': 'creating', 'experiment_name': name})
    try:
        experiment = c.create_project(name, reference_dataset_id=profile['dataset_id'], metadata=identity)
        private_write(claim, {**identity, 'status': 'dispatching', 'experiment_name': name,
                             'experiment_id': str(experiment.id)}, replace=True)
        from .atomic import make_public_graph
        graph = make_public_graph(kind)
        tracer = PublicTracer(client=c, project_name=experiment.name)
        # Async graph nodes require async invocation; SDK accepts async targets.
        async def async_target(inputs, config):
            result = await graph.ainvoke(inputs, config=config)
            return {'result': result['result']}
        runnable = RunnableLambda(async_target).with_config(callbacks=[tracer], metadata=identity)
        async def run_evaluation():
            results = await c.aevaluate(runnable, data=examples, evaluators=[evaluator], experiment=experiment,
                max_concurrency=1, num_repetitions=1, blocking=True)
            return [row async for row in results]
        rows = asyncio.run(run_evaluation())
        require(len(rows) == len(roster(kind)), 'ATOMIC_EVALUATION_ROSTER')
        ids = [str(row['run'].id) for row in rows]
        tracer.wait_for_futures()
        require(not tracer.delivery_errors, 'ATOMIC_EVALUATION_TRACE_UNKNOWN')
        private_write(claim, {**identity, 'status': 'submitted', 'experiment_name': name,
            'experiment_id': str(experiment.id), 'run_ids': ids}, replace=True)
        return check_evaluation(c, kind)
    except BaseException:
        private_write(claim, {**private_read(claim), 'status': 'unknown'}, replace=True)
        raise


def check_evaluation(c, kind):
    profile = local_profile(kind)
    claim = state_root() / kind / 'evaluation.json'
    value = private_read(claim)
    require(bool(value.get('experiment_id')), 'ATOMIC_EVALUATION_ID_UNKNOWN')
    examples = {str(x.id): x for x in admitted_examples(c, kind, profile)}
    projections = list(c.list_runs(project_id=value['experiment_id'], is_root=True, limit=len(examples) + 1))
    runs = []
    for projection in projections:
        actual = c.read_run(projection.id, project_id=value['experiment_id'])
        require(str(actual.id) == str(projection.id) and str(actual.session_id) == value['experiment_id']
                and actual.parent_run_id is None, 'ATOMIC_REMOTE_PROJECT_OR_ROOT_MISMATCH')
        runs.append(actual)
    require(len(runs) == len(roster(kind)) == len(examples)
            and {str(x.reference_example_id) for x in runs} == set(examples),
            'ATOMIC_REMOTE_ROSTER_OR_BINDING')
    if value.get('run_ids') is not None:
        require(len(value['run_ids']) == len(runs)
                and set(value['run_ids']) == {str(x.id) for x in runs},
                'ATOMIC_OWNED_RUN_ID_MISMATCH')
    for run in runs:
        expected = examples[str(run.reference_example_id)]
        inputs = run.inputs
        if set(inputs) == {'input', 'config'} and inputs['config'] is None: inputs = inputs['input']
        require(inputs == expected.inputs and run.outputs == {'result': expected.outputs}
                and not run.error, 'ATOMIC_REMOTE_RESULT_FAILED')
    feedback = [x for x in c.list_feedback(run_ids=[r.id for r in runs]) if x.key == FEEDBACK]
    require(len(feedback) == len(runs) and all(x.score == 1 for x in feedback)
            and {str(x.run_id) for x in feedback} == {str(r.id) for r in runs}, 'ATOMIC_REMOTE_FEEDBACK')
    payload = [r.model_dump(mode='json') for r in runs] + [x.model_dump(mode='json') for x in feedback]
    require(obs.credential() not in canonical(payload), 'ATOMIC_SECRET_IN_READBACK')
    record = {**value, 'status': 'verified', 'scores': [x.score for x in feedback],
              'run_ids': [str(r.id) for r in runs], 'verified_at_ns': time.time_ns()}
    private_write(claim, record, replace=True)
    return record


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=['bootstrap', 'reconcile-bootstrap', 'evaluate', 'check-evaluation', 'check-trace'])
    p.add_argument('--kind', required=True, choices=['calculator', 'calculator_session', 'holdings'])
    p.add_argument('--attempt')
    args = p.parse_args()
    logging.disable(logging.CRITICAL)
    c = obs.client()
    try:
        if args.operation in ('bootstrap', 'reconcile-bootstrap'):
            agent = c.agents.retrieve(obs.AGENT)
            require(agent.id == obs.AGENT and agent.source_type == 'EXTERNAL', 'ATOMIC_AGENT_IDENTITY')
            tags = [agent.tag_value_id] if agent.tag_value_id else None
            record = bootstrap(c, args.kind, reconcile=args.operation.startswith('reconcile'), tag_value_ids=tags)
        elif args.operation == 'evaluate': record = evaluate(c, args.kind)
        elif args.operation == 'check-trace': record = check_trace(c, args.kind, args.attempt)
        else: record = check_evaluation(c, args.kind)
        print(canonical(record))
    except Exception as error:
        print(canonical({'status': 'failed_or_unknown', 'error_type': type(error).__name__,
            'message': str(error) if str(error).startswith('ATOMIC_') else 'ATOMIC_REMOTE_OPERATION_FAILED'}))
        raise SystemExit(1) from None
    finally: c.close()


if __name__ == '__main__': main()
