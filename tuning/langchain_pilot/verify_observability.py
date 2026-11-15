"""Read back exact cloud evidence; never execute or replay the target."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import time

from .observability import AGENT, CALCULATOR_PROMPT, SCOPE, STATE, cases, client, credential
from .session_model import canonical, private_read, private_write, require


def target_inputs(value):
    # SDK's Target wrapper records its arguments, rather than the case directly.
    if isinstance(value, dict) and set(value) == {'input', 'config'} and value['config'] is None:
        return value['input']
    return value


def check(c, config, evaluation, trace):
    agent = c.agents.retrieve(AGENT)
    local = next(e for e in agent.environments if e.environment == 'LOCAL')
    require(local.tracer_session_id == config['project_id'], 'OBS_AGENT_ENVIRONMENT_MISMATCH')
    prompt = c.pull_prompt(config['prompt_name'] + ':' + config['prompt_commit'], skip_cache=True)
    require(prompt.invoke({}).to_messages()[0].content == CALCULATOR_PROMPT,
            'OBS_PROMPT_READBACK_MISMATCH')
    examples = {str(x.id): x for x in c.list_examples(
        dataset_id=config['dataset_id'], as_of=config['dataset_as_of'])}
    require(len(examples) == len(cases()), 'OBS_FROZEN_DATASET_ROSTER')
    projected = list(c.list_runs(project_id=evaluation['experiment_id'], is_root=True, limit=10))
    require(len(projected) == len(examples), 'OBS_REMOTE_EVALUATION_ROSTER')
    # Projections may omit fields; retrieve each exact run from its exact project.
    runs = [c.read_run(r.id, project_id=evaluation['experiment_id'])
            for r in projected]
    require({str(r.reference_example_id) for r in runs} == set(examples),
            'OBS_REMOTE_CASE_BINDING')
    for run in runs:
        example = examples[str(run.reference_example_id)]
        require(target_inputs(run.inputs) == example.inputs and run.outputs == example.outputs
                and not run.error, 'OBS_REMOTE_RESULT_MISMATCH')
    feedback = [x for x in c.list_feedback(run_ids=[r.id for r in runs])
                if x.key == 'atomic_contract']
    require(len(feedback) == len(runs) and all(x.score == 1 for x in feedback)
            and {str(x.run_id) for x in feedback} == {str(r.id) for r in runs},
            'OBS_REMOTE_FEEDBACK_MISSING')
    positive = c.read_run(trace['run_id'], project_id=config['project_id'], load_child_runs=True)
    negative = c.read_run(trace['failure_run_id'], project_id=config['project_id'])
    require(positive.outputs == cases()[1]['outputs'] and not positive.error
            and bool(positive.child_runs) and bool(negative.error), 'OBS_REMOTE_TRACE_MISMATCH')
    require(any(x.run_type == 'tool' for x in positive.child_runs), 'OBS_REMOTE_TOOL_SPAN')
    roots = list(c.list_runs(project_id=config['project_id'], is_root=True, limit=100))
    stats = c.read_project(project_id=config['project_id'], include_stats=True)
    # This isolated synthetic project currently contains only owned canaries.
    require(stats.run_count == len(roots) and len(roots) >= 2, 'OBS_MONITOR_COUNT_MISMATCH')
    expected_errors = sum(bool(r.error) for r in roots) / len(roots)
    require(stats.error_rate is not None and abs(stats.error_rate - expected_errors) < 1e-9,
            'OBS_MONITOR_ERROR_RATE_MISMATCH')
    payload = [r.model_dump(mode='json') for r in runs + [positive, negative]]
    payload += [x.model_dump(mode='json') for x in feedback]
    require(credential() not in json.dumps(payload, default=str), 'OBS_SECRET_IN_REMOTE_READBACK')
    record = {'status': 'passed_atomic_calculator_only', 'scope': SCOPE,
              'agent_id': AGENT, 'remote_runs': len(runs), 'remote_scores': [x.score for x in feedback],
              'reference_examples_bound': True, 'known_monitoring_root_runs': stats.run_count,
              'known_controlled_error_rate': stats.error_rate, 'credential_absent_from_readback': True,
              'prompt_commit': config['prompt_commit'], 'dataset_id': config['dataset_id'],
              'experiment_id': evaluation['experiment_id'], 'trace_run_id': trace['run_id'],
              'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'main_agent_server_tracing': 'unchanged/off', 'model_session_tracing': 'unverified',
              'holdings_live_acceptance': 'unverified', 'research_pipeline': 'TBD',
              'at_ns': time.time_ns()}
    return record


def main():
    logging.disable(logging.CRITICAL)
    config = private_read(STATE / 'config.json')
    evaluations = sorted(STATE.glob('evaluation-*.json'))
    traces = sorted(STATE.glob('trace-[0-9]*.json'))
    require(bool(evaluations) and bool(traces), 'OBS_ACCEPTANCE_INPUTS_MISSING')
    c = client()
    try:
        record = check(c, config, private_read(evaluations[-1]), private_read(traces[-1]))
        private_write(STATE / 'remote-acceptance.json', record, replace=True)
        print(canonical(record))
    except Exception as error:
        print(canonical({'status': 'failed_or_unknown', 'error_type': type(error).__name__,
                         'message': str(error) if str(error).startswith('OBS_') else 'OBS_READBACK_FAILED'}))
        raise SystemExit(1) from None
    finally:
        c.close()


if __name__ == '__main__':
    main()
