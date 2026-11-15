"""Opt-in LangSmith prerequisite canary for a public synthetic atomic capability.

No model/provider calls, account data, Agent Server mutation or scheduler effects.
This traces the existing calculator through real LangChain Runnables. It does
not certify the cooperative model engine's native traces or full agent readiness.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import logging
import os
from pathlib import Path
import stat
import time
from uuid import UUID, uuid4, uuid5

from dotenv import dotenv_values
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_core.tracers import LangChainTracer
from langchain_core.tools import StructuredTool
from langsmith import Client, tracing_context
from langsmith.utils import LangSmithNotFoundError
from pydantic import ValidationError
from urllib3.util.retry import Retry

from .graph import CALCULATOR_PROMPT, ValuationCase, calculate
from .session_model import ROOT, canonical, private_read, private_write, require
from .smoke import CASE

API = 'https://api.smith.langchain.com'
STATE = ROOT / '.langchain-pilot/runtime/langsmith-bootstrap'
KEY_FILE = ROOT / '.langchain-pilot/langsmith.env'
AGENT = 'trading-agent'
PROMPT_NAME = 'trading-agent-calculator-v1'
DATASET_NAME = 'trading-agent-atomic-calculator-v1'
SCOPE = 'public_synthetic_atomic_calculator_v1'


def credential(path=KEY_FILE):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW)) as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= 16384,
                'OBS_PRIVATE_CONFIG_REQUIRED')
        values = dotenv_values(stream=stream, interpolate=False)
    require(set(values) == {'LANGSMITH_API_KEY'} and bool(values['LANGSMITH_API_KEY']),
            'OBS_PLATFORM_KEY_REQUIRED')
    return values['LANGSMITH_API_KEY']


def client():
    return Client(api_key=credential(), api_url=API, timeout_ms=(5000, 15000),
                  retry_config=Retry(total=0), auto_batch_tracing=False,
                  omit_traced_runtime_info=True, disable_prompt_cache=True)


def cases():
    nominal = {**CASE, 'case_id': 'public-nominal'}
    debt = {**nominal, 'case_id': 'public-debt', 'fcff': ['220'], 'net_debt': '50'}
    invalid = {**nominal, 'case_id': 'public-invalid-shares', 'shares': '0'}
    return [
        {'id': 'nominal', 'inputs': {'case': nominal},
         'outputs': {'status': 'passed', 'per_share': '10'}},
        {'id': 'debt', 'inputs': {'case': debt},
         'outputs': {'status': 'passed', 'per_share': '15'}},
        {'id': 'invalid-shares', 'inputs': {'case': invalid},
         'outputs': {'status': 'invalid_input'}},
    ]


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def source_fingerprints():
    names = ['tuning/langchain_pilot/observability.py', 'tuning/langchain_pilot/graph.py',
             'tuning/langchain_pilot/session_model.py', 'tuning/langchain_pilot/smoke.py',
             'shared/calculation/legacy/valuation/valuation_core.py',
             'tuning/langchain_pilot/requirements.lock.txt']
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def checked_calculation(case):
    result = calculate(case)
    # Independent exact arithmetic. The calculator implementation is not an oracle.
    discount = 1 + Fraction(case['rate'])
    enterprise = sum(Fraction(x) / discount ** i for i, x in enumerate(case['fcff'], 1))
    enterprise += Fraction(case['terminal_ev']) / discount ** len(case['fcff'])
    expected = (enterprise - Fraction(case['net_debt'])) / Fraction(case['shares'])
    require(abs(float(Fraction(result['per_share']) - expected)) <= 1e-10,
            'OBS_INDEPENDENT_ARITHMETIC_FAILED')
    return {'status': 'passed', 'per_share': result['per_share']}


def atomic_runnable(prompt):
    validate = RunnableLambda(lambda value: ValuationCase.model_validate(
        value['case']).model_dump(mode='json')).with_config(run_name='validate_case')
    calculator = StructuredTool.from_function(
        checked_calculation, name='existing_calculator',
        description='Calculate the validated public synthetic case and check independent arithmetic.')

    def invoke(inputs, config):
        # CLI callers supply only frozen public examples. This rejects drift
        # before validation/tools, but callbacks may record input before this body.
        # Do not reuse this runnable with private data as a pre-trace privacy guard.
        require(any(inputs == c['inputs'] for c in cases()), 'OBS_PUBLIC_FIXTURE_ONLY')
        prompt.invoke({}, config=config)
        try:
            case = validate.invoke(inputs, config=config)
        except ValidationError:
            return {'status': 'invalid_input'}
        return calculator.invoke({'case': case}, config=config)

    return RunnableLambda(invoke).with_config(run_name='atomic_calculator')


def evaluator(run, example):
    expected = example.outputs or {}
    actual = run.outputs or {}
    return {'key': 'atomic_contract', 'score': actual == expected,
            'comment': 'Frozen synthetic contract; numerical output also checked independently.'}


def freeze_config(c, agent, local, commit_hash, dataset, reopened):
    expected = {str(uuid5(UUID(str(dataset.id)), item['id'])): item for item in cases()}
    require(len(reopened) == len(expected), 'OBS_DATASET_ROSTER_MISMATCH')
    for example in reopened:
        require(str(example.id) in expected, 'OBS_DATASET_ID_MISMATCH')
        item = expected[str(example.id)]
        require(example.inputs == item['inputs'] and example.outputs == item['outputs'],
                'OBS_DATASET_CONTENT_MISMATCH')
    # SDK requires exactly one of as_of/tag. Pin the actual verified roster time.
    as_of = max(example.modified_at for example in reopened)
    version = c.read_dataset_version(dataset_id=dataset.id, as_of=as_of)
    config = {'scope': SCOPE, 'agent_id': AGENT, 'environment': 'local',
              'project_name': local.tracer_session_name,
              'project_id': local.tracer_session_id,
              'prompt_name': PROMPT_NAME, 'prompt_commit': commit_hash,
              'prompt_sha256': hashlib.sha256(CALCULATOR_PROMPT.encode()).hexdigest(),
              'dataset_id': str(dataset.id), 'dataset_name': DATASET_NAME,
              'dataset_as_of': as_of.isoformat(),
              'dataset_version': version.model_dump(mode='json'),
              'cases_sha256': digest(cases()),
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    private_write(STATE / 'config.json', config)
    private_write(STATE / 'bootstrap-claim.json', {'status': 'verified', 'scope': SCOPE}, replace=True)
    return config


def bootstrap(c, *, reconcile=False):
    agent = c.agents.retrieve(AGENT)
    require(agent.id == AGENT and agent.source_type == 'EXTERNAL', 'OBS_AGENT_IDENTITY')
    local = next(e for e in agent.environments if e.environment == 'LOCAL')
    fingerprint = digest(cases())
    claim = STATE / 'bootstrap-claim.json'
    if (STATE / 'config.json').exists():
        saved = private_read(STATE / 'config.json')
        require(saved['cases_sha256'] == fingerprint, 'OBS_FIXTURE_DRIFT')
        return saved
    if reconcile:
        # Read back all prior effects; this branch never pushes or creates data.
        require(claim.exists(), 'OBS_NO_BOOTSTRAP_TO_RECONCILE')
        commit = c.pull_prompt_commit(PROMPT_NAME, skip_cache=True)
        loaded = c.pull_prompt(PROMPT_NAME + ':' + commit.commit_hash, skip_cache=True)
        require(loaded.invoke({}).to_messages()[0].content == CALCULATOR_PROMPT,
                'OBS_PROMPT_READBACK_MISMATCH')
        dataset = c.read_dataset(dataset_name=DATASET_NAME)
        require((dataset.metadata or {}).get('cases_sha256') == fingerprint,
                'OBS_DATASET_OWNER_MISMATCH')
        rows = list(c.list_examples(dataset_id=dataset.id, limit=10))
        return freeze_config(c, agent, local, commit.commit_hash, dataset, rows)
    require(not claim.exists(), 'OBS_BOOTSTRAP_UNKNOWN_RECONCILE_BEFORE_REPLAY')
    private_write(claim, {'status': 'creating', 'scope': SCOPE, 'cases_sha256': fingerprint})
    try:
        # Prompts stay private to the workspace; this contains no user payload.
        prompt = ChatPromptTemplate.from_messages([('system', CALCULATOR_PROMPT)])
        c.push_prompt(PROMPT_NAME, object=prompt, is_public=False,
                      description='Public synthetic calculator prerequisite; no model invocation.')
        commit = c.pull_prompt_commit(PROMPT_NAME, skip_cache=True)
        loaded = c.pull_prompt(PROMPT_NAME + ':' + commit.commit_hash, skip_cache=True)
        require(loaded.invoke({}).to_messages()[0].content == CALCULATOR_PROMPT,
                'OBS_PROMPT_READBACK_MISMATCH')
        dataset = c.create_dataset(
            DATASET_NAME, description='Three public synthetic atomic cases. Not investment quality evidence.',
            metadata={'scope': SCOPE, 'cases_sha256': fingerprint, 'agent_id': AGENT},
            tag_value_ids=[agent.tag_value_id] if agent.tag_value_id else None)
        examples = [{'id': str(uuid5(UUID(str(dataset.id)), item['id'])),
                     'inputs': item['inputs'], 'reference_outputs': item['outputs'],
                     'metadata': {'case_id': item['id'], 'scope': SCOPE}}
                    for item in cases()]
        c.create_examples(dataset_id=dataset.id, examples=examples, max_concurrency=1)
        reopened = list(c.list_examples(dataset_id=dataset.id, limit=10))
        require(len(reopened) == len(examples), 'OBS_DATASET_ROSTER_MISMATCH')
        return freeze_config(c, agent, local, commit.commit_hash, dataset, reopened)
    except BaseException:
        private_write(claim, {'status': 'unknown', 'scope': SCOPE}, replace=True)
        raise


def target(c, config):
    require(config['cases_sha256'] == digest(cases()), 'OBS_FIXTURE_DRIFT')
    prompt = c.pull_prompt(config['prompt_name'] + ':' + config['prompt_commit'], skip_cache=True)
    require(prompt.invoke({}).to_messages()[0].content == CALCULATOR_PROMPT,
            'OBS_PROMPT_DRIFT')
    return atomic_runnable(prompt).with_config(metadata={
        'scope': SCOPE, 'agent_id': AGENT, 'prompt_commit': config['prompt_commit'],
        'prompt_sha256': config['prompt_sha256'], 'dataset_id': config['dataset_id'],
        'cases_sha256': config['cases_sha256'], 'bootstrap_source_sha256': config['source_sha256'],
        'source_fingerprints': source_fingerprints()})


def read_exact_run(c, run_id, *, project_id, children=False):
    # Ingestion acknowledgement precedes query visibility. Retry reads only;
    # never run the capability again to compensate for a missing trace read.
    deadline = time.monotonic() + 30
    while True:
        try:
            return c.read_run(run_id, load_child_runs=children, project_id=project_id)
        except LangSmithNotFoundError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)


def verify_trace(c, config, evidence):
    intent = private_read(evidence)
    run_id = intent['run_id']; failure_id = intent['failure_run_id']
    positive = read_exact_run(c, run_id, project_id=config['project_id'], children=True)
    negative = read_exact_run(c, failure_id, project_id=config['project_id'])
    answer = cases()[1]['outputs']
    require(str(positive.id) == run_id and str(negative.id) == failure_id,
            'OBS_TRACE_IDENTITY_MISMATCH')
    require(str(positive.session_id) == config['project_id'] and positive.error is None
            and positive.outputs == answer, 'OBS_TRACE_READBACK')
    require(bool(positive.child_runs) and bool(negative.error), 'OBS_CHILD_OR_FAILURE_MISSING')
    require(str(negative.session_id) == config['project_id']
            and 'SYNTHETIC_CONTROLLED_FAILURE' in negative.error, 'OBS_FAILURE_IDENTITY')
    require(any(r.run_type == 'tool' for r in positive.child_runs), 'OBS_TOOL_SPAN_MISSING')
    require(all(str(r.parent_run_id) == run_id for r in positive.child_runs),
            'OBS_CHILD_PARENT_MISMATCH')
    project = c.read_project(project_id=config['project_id'], include_stats=True)
    record = {'scope': SCOPE, 'run_id': run_id, 'failure_run_id': failure_id,
              'child_run_names': [run.name for run in positive.child_runs],
              'result': answer, 'run_count': getattr(project, 'run_count', None),
              'error_rate': getattr(project, 'error_rate', None),
              'run_url': c.get_run_url(run=positive),
              'project_id': config['project_id'], 'prompt_commit': config['prompt_commit']}
    private_write(STATE / ('trace-' + str(time.time_ns()) + '.json'), record)
    private_write(evidence, {**intent, 'status': 'verified', 'record': record}, replace=True)
    return record


def trace_canary(c, config):
    runnable = target(c, config)
    tracer = LangChainTracer(client=c, project_name=config['project_name'])
    run_id = uuid4()
    failure_id = uuid4()
    evidence = STATE / ('trace-attempt-' + str(time.time_ns()) + '.json')
    intent = {'status': 'dispatching', 'run_id': str(run_id), 'failure_run_id': str(failure_id),
              'scope': SCOPE, 'source_fingerprints': source_fingerprints()}
    private_write(evidence, intent)
    # Global tracing stays off. Explicit context enables only this allowlisted canary.
    try:
        with tracing_context(enabled=True, client=c, project_name=config['project_name']):
            answer = runnable.invoke(cases()[1]['inputs'], config={'callbacks': [tracer],
                                    'run_id': run_id, 'tags': [SCOPE]})
            require(answer == cases()[1]['outputs'], 'OBS_TARGET_RESULT')
            def fail(_): raise RuntimeError('SYNTHETIC_CONTROLLED_FAILURE')
            try:
                RunnableLambda(fail).with_config(run_name='controlled_failure').invoke(
                    {'scope': SCOPE}, config={'callbacks': [tracer], 'run_id': failure_id})
            except RuntimeError:
                pass
        tracer.wait_for_futures()
    except BaseException:
        private_write(evidence, {**intent, 'status': 'unknown'}, replace=True)
        raise
    return verify_trace(c, config, evidence)


def evaluate_canary(c, config):
    require(evaluator(type('Run', (), {'outputs': {'status': 'passed', 'per_share': '999'}})(),
                      type('Example', (), {'outputs': cases()[0]['outputs']})())['score'] is False,
            'OBS_GRADER_NEGATIVE_CONTROL')
    agent = c.agents.retrieve(AGENT)
    experiment = c.create_project(
        'atomic-prerequisite-' + str(time.time_ns()), reference_dataset_id=config['dataset_id'],
        metadata={'scope': SCOPE, 'agent_id': AGENT, 'prompt_commit': config['prompt_commit'],
                  'cases_sha256': config['cases_sha256']},
        tag_value_ids=[agent.tag_value_id] if agent.tag_value_id else None)
    results = c.evaluate(target(c, config), data=c.list_examples(
                             dataset_id=config['dataset_id'], as_of=config['dataset_as_of']),
                         evaluators=[evaluator], experiment=experiment, max_concurrency=1,
                         num_repetitions=1, blocking=True, error_handling='log',
                         metadata={'scope': SCOPE, 'prompt_commit': config['prompt_commit']})
    rows = list(results)
    require(len(rows) == len(cases()), 'OBS_EVALUATION_ROSTER')
    scores = []
    for row in rows:
        require(row.get('run') is not None, 'OBS_EVALUATION_RUN_MISSING')
        feedback = row['evaluation_results']['results']
        require(len(feedback) == 1 and feedback[0].key == 'atomic_contract', 'OBS_FEEDBACK_MISSING')
        scores.append(bool(feedback[0].score))
    require(all(scores), 'OBS_EVALUATION_FAILED')
    record = {'scope': SCOPE, 'experiment_id': str(experiment.id),
              'experiment_name': experiment.name, 'dataset_id': config['dataset_id'],
              'rows': len(rows), 'scores': scores, 'prompt_commit': config['prompt_commit'],
              'limitations': ['atomic calculator only', 'no model calls',
                              'not native session-engine tracing', 'not holdings or research acceptance']}
    private_write(STATE / ('evaluation-' + str(time.time_ns()) + '.json'), record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['bootstrap', 'reconcile-bootstrap', 'trace',
                                            'reconcile-trace', 'evaluate'])
    parser.add_argument('--attempt', help='Owned trace-attempt-*.json filename for read-only reconciliation')
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)  # Never print SDK response/header diagnostics.
    c = client()
    try:
        if args.operation in {'bootstrap', 'reconcile-bootstrap'}:
            result = bootstrap(c, reconcile=args.operation == 'reconcile-bootstrap')
        else:
            config = private_read(STATE / 'config.json')
            if args.operation == 'reconcile-trace':
                require(args.attempt and Path(args.attempt).name == args.attempt
                        and args.attempt.startswith('trace-attempt-') and args.attempt.endswith('.json'),
                        'OBS_ATTEMPT_REQUIRED')
                result = verify_trace(c, config, STATE / args.attempt)
            else:
                result = trace_canary(c, config) if args.operation == 'trace' else evaluate_canary(c, config)
        print(canonical(result))
    except Exception as error:
        print(canonical({'status': 'failed_or_unknown', 'error_type': type(error).__name__,
                         'message': str(error) if str(error).startswith('OBS_') else 'OBS_REMOTE_OPERATION_FAILED'}))
        raise SystemExit(1) from None
    finally:
        c.close()


if __name__ == '__main__':
    main()
