#!/usr/bin/env python3
"""Development-only CLI adapter; no host configuration or frozen source edits."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STATE = ROOT / '.research-sources/ai-tuning-skill-preview'
V2 = ROOT / 'tuning/evals/llm-engineering-guidance-v2'
V3 = ROOT / '.research-sources/llm-engineering-guidance-v3'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


runtime = module('smoke_frozen_runtime', V2 / 'candidate_runtime.py')
legacy = module('smoke_maintained_cli', ROOT / 'tuning/evals/llm-engineering-guidance/run_o0.py')
require = runtime.require


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def reconcile(root=V3):
    """Read only accounting artifacts, never protected case/custody payloads."""
    hashes, pending, terminals = {}, [], []
    spent = 0.0
    fixture_calls = 0
    for arm in ('o0', 'o1'):
        for path in sorted((root / arm).rglob('*.json')):
            require(not path.is_symlink(), 'ACCOUNTING_SYMLINK')
            hashes[str(path.relative_to(root))] = runtime.digest(path.read_bytes())
            value = runtime.strict_load(path)
            if path.name.endswith('.intent.json'):
                result = path.with_name(path.name.replace('.intent.json', '.result.json'))
                terminal = path.with_name(path.name.replace('.intent.json', '.terminal.json'))
                if not result.exists() and not terminal.exists():
                    pending.append(str(path.relative_to(root)))
            elif path.name.endswith('.terminal.json'):
                terminals.append(str(path.relative_to(root)))
            elif path.name.endswith('.result.json'):
                receipt = value.get('receipt', value)
                cost = receipt.get('cost_usd')
                require(number(cost), 'ACCOUNTING_COST_INVALID')
                spent += cost
                if receipt.get('usage', {}).get('fixture') is True:
                    require(cost == 0, 'FIXTURE_COST_INVALID')
                    fixture_calls += 1
    baseline = runtime.strict_load(root / 'baseline-budget.json')
    hashes['baseline-budget.json'] = runtime.digest((root / 'baseline-budget.json').read_bytes())
    require(not pending and not terminals, 'PRIOR_UNKNOWN_OR_TERMINAL_REQUIRES_RECONCILIATION')
    return {'artifact_hashes': hashes, 'prior_candidate_debit_usd': spent,
            'prior_fixture_calls': fixture_calls, 'unresolved_intents': pending,
            'terminal_fences': terminals, 'historical_sunk_usd': baseline['recorded_spend_usd'],
            'historical_candidate': baseline['candidate_version']}


def projection():
    path = V2 / 'development-cases.json'
    source = runtime.strict_load(path)
    record = source['cases'][0]
    require(record['split'] == 'development', 'NOT_DEVELOPMENT')
    require(runtime.digest(record['prompt'].encode()) == record['prompt_sha256'], 'ORIGINAL_PROMPT_HASH')
    projected = {'case_id': record['id'], 'case_material': record['prompt']}
    return {'schema_version': 1, 'kind': 'development_smoke_projection', 'cases': [projected]}, {
        'source_file_sha256': runtime.digest(path.read_bytes()),
        'source_record_sha256': runtime.digest(record),
        'original_prompt_sha256': record['prompt_sha256'],
        'projected_case_sha256': runtime.case_sha256(projected),
        'selected_index': 0, 'gold_transmitted': False}


def cli_command(packet):
    require(packet['id'] in runtime.MODELS, 'MODEL_NOT_AUTHORIZED')
    require(packet['settings'] == runtime.SOLVER_SETTINGS, 'SETTINGS_NOT_AUTHORIZED')
    # Reuse the maintained transport, replacing only its frozen-v1 contract.
    command = legacy.cli_command(packet['id'], runtime.canonical(packet['input']).decode(), 0.5)
    command[command.index('--system-prompt') + 1] = packet['system_prompt']
    command[command.index('--json-schema') + 1] = json.dumps(packet['output_schema'], separators=(',', ':'))
    return command


def validate_native(raw, packet):
    # The maintained validator includes the old output schema. Use its identity,
    # permission, served-model and spend checks without applying that old schema.
    identity = dict(raw)
    identity['structured_output'] = {'decision': 'contract checked separately',
                                    'next_actions': ['validate frozen contract'],
                                    'evidence_used': [], 'allowed_claim': 'development only'}
    _, cost, usage = legacy.validate_cli(identity, packet['id'], 0.5)
    require(number(cost), 'COST_INVALID')
    for key in ('inputTokens', 'outputTokens', 'cacheReadInputTokens', 'cacheCreationInputTokens'):
        require(type(usage.get(key)) is int and usage[key] >= 0, 'USAGE_INCOMPLETE')
    require(usage['inputTokens'] + usage['cacheReadInputTokens'] + usage['cacheCreationInputTokens'] > 0,
            'USAGE_EMPTY')
    require(usage['outputTokens'] > 0, 'USAGE_EMPTY')
    require(number(usage.get('costUSD')) and abs(usage['costUSD'] - cost) < 1e-8, 'USAGE_COST_MISMATCH')
    require(isinstance(raw.get('structured_output'), dict), 'OUTPUT_MISSING')
    require(isinstance(raw.get('session_id'), str) and raw['session_id'], 'SESSION_ID_MISSING')
    return {'status': 'success', 'request_sha256': runtime.digest(packet),
            'model': packet['id'], 'settings': packet['settings'],
            'output': raw['structured_output'], 'usage': usage, 'cost_usd': cost}


class Adapter:
    def __init__(self, state, prior, runner=subprocess.run):
        self.state, self.prior, self.runner = state, prior, runner

    def __call__(self, packet, timeout_seconds):
        require(reconcile() == self.prior, 'PRIOR_ACCOUNTING_CHANGED')
        intents = sorted((self.state / 'native').glob('*.intent.json'))
        debit = 0.0
        for intent in intents:
            terminal = intent.with_name(intent.name.replace('.intent.json', '.terminal.json'))
            require(terminal.exists(), 'NATIVE_UNKNOWN_FENCED')
            result = runtime.strict_load(terminal)
            require(result['status'] == 'success', 'NATIVE_TERMINAL_FENCED')
            debit += result['cost_debit_usd']
        require(len(intents) < 6, 'CALL_COUNT_CAP')
        require(debit + .5 <= 3 and self.prior['prior_candidate_debit_usd'] + debit + .5 <= 25,
                'AGGREGATE_BUDGET_EXHAUSTED')
        command = cli_command(packet)
        base = self.state / 'native' / f'{len(intents) + 1:02d}'
        # Independent reservation covers both frozen campaigns, including unknowns.
        runtime.exclusive_json(base.with_suffix('.intent.json'), {
            'request_sha256': runtime.digest(packet), 'model': packet['id'],
            'reserved_usd': .5, 'automatic_retry_allowed': False,
            'scope': 'development_smoke_only'})
        env = dict(os.environ)
        for name, relative in {'HOME': 'home', 'CLAUDE_CONFIG_DIR': 'config',
                               'XDG_CACHE_HOME': 'cache', 'XDG_CONFIG_HOME': 'xdg-config',
                               'XDG_STATE_HOME': 'xdg-state', 'TMPDIR': 'tmp'}.items():
            location = self.state / 'cli' / relative
            location.mkdir(parents=True, exist_ok=True, mode=0o700)
            env[name] = str(location)
        # Retain CLAUDECODE and all permission policy variables; never defeat a
        # nested-session or permission denial. Credentials stay in inherited env.
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        started = time.monotonic()
        evidence = {'status': 'unknown', 'cost_debit_usd': .5, 'actual_cost_usd': None,
                    'replay_allowed': False, 'request_sha256': runtime.digest(packet)}
        try:
            process = self.runner(command, cwd=self.state / 'cli', env=env,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, timeout=timeout_seconds)
            evidence['cli_exit_code'] = process.returncode
            # Retain hashes, not possibly credential-bearing CLI diagnostics.
            evidence['stdout_sha256'] = runtime.digest(process.stdout.encode())
            evidence['stderr_sha256'] = runtime.digest(process.stderr.encode())
            require(process.returncode == 0, 'CLI_NONZERO_EXIT')
            raw = runtime.strict_json_bytes(process.stdout)
            evidence['native'] = {k: raw.get(k) for k in (
                'subtype', 'is_error', 'terminal_reason', 'stop_reason', 'num_turns',
                'session_id', 'modelUsage', 'total_cost_usd')}
            if number(raw.get('total_cost_usd')):
                evidence['actual_cost_usd'] = raw['total_cost_usd']
                evidence['cost_debit_usd'] = max(.5, raw['total_cost_usd'])
            response = validate_native(raw, packet)
            evidence.update(status='success', cost_debit_usd=response['cost_usd'],
                            response=response)
            return response
        except Exception as error:
            evidence['error_type'] = type(error).__name__
            # Only locally generated fixed validation codes, never exception URLs.
            evidence['reason'] = str(error) if isinstance(error, ValueError) else 'TRANSPORT_UNKNOWN'
            raise
        finally:
            evidence['duration_seconds'] = round(time.monotonic() - started, 3)
            runtime.exclusive_json(base.with_suffix('.terminal.json'), evidence)


def main(live=False):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    require(not STATE.is_symlink(), 'STATE_SYMLINK')
    require(STATE.stat().st_mode & 0o077 == 0, 'STATE_NOT_PRIVATE')
    with runtime.campaign_lock(STATE):
        require(not (STATE / 'report-v1.json').exists(), 'RUN_ALREADY_TERMINAL')
        plan = runtime.strict_load(HERE / 'verification-plan.json')
        authorization = runtime.strict_load(HERE / 'scope-authorization-v1.json')
        require(plan['candidate_fingerprint'] == runtime.EXPECTED_FINGERPRINT
                and plan['models'] == list(runtime.MODELS)
                and plan['scope_budget_usd'] == 3 and plan['candidate_total_cap_usd'] == 25
                and plan['planned_calls'] == 6, 'FROZEN_PLAN_DRIFT')
        require(authorization['paid_development_smoke_authorized'] is True
                and authorization['scope'] == 'DEVELOPMENT SMOKE ONLY'
                and authorization['models'] == list(runtime.MODELS)
                and authorization['effort'] == 'high'
                and authorization['scope_cap_usd'] == 3
                and authorization['candidate_aggregate_cap_usd'] == 25
                and authorization['max_calls'] == 6
                and not any(authorization[k] for k in ('fallbacks_allowed', 'tools_allowed',
                    'web_allowed', 'protected_calls_authorized', 'production_activation_authorized')),
                'SCOPE_AUTHORIZATION_INVALID')
        prior = reconcile()
        projected, provenance = projection()
        material = runtime.verify_candidate()
        validator = module('smoke_evaluation_validator', V2 / 'validate_candidate_evaluation.py')
        evaluation = validator.validate()
        runtime.exclusive_json(STATE / 'projection-v1.json', projected)
        runtime.exclusive_json(STATE / 'preflight-v1.json', {
            'reconciliation': prior, 'projection': provenance,
            'authorization_sha256': runtime.digest((HERE / 'scope-authorization-v1.json').read_bytes()),
            'verification_plan_sha256': runtime.digest((HERE / 'verification-plan.json').read_bytes()),
            'candidate_fingerprint': material['candidate']['fingerprint'],
            'evaluation_validation': evaluation,
            'impact': 'one-off external model calls only; no host activation',
            'owner': 'ai-tuning-skill-preview', 'protected_custody': False})
        report = {'scope': 'development_smoke_only', 'live_requested': live,
                  'status': 'local_preflight_passed', 'historical_sunk_usd': prior['historical_sunk_usd'],
                  'prior_candidate_debit_usd': prior['prior_candidate_debit_usd'],
                  'production_acceptance': False, 'quality_lift_claim': False}
        try:
            if live:
                adapter = Adapter(STATE, prior)
                for arm in ('O0', 'O1'):
                    runtime.run_campaign(arm, STATE / 'projection-v1.json', adapter,
                                         state_root=STATE / 'campaigns', hard_cap_usd=3,
                                         allow_test_state=True)
                report['status'] = 'six_call_development_smoke_passed'
        except Exception as error:
            report.update(status='blocked_or_failed', reason=str(error))
        finally:
            records = [runtime.strict_load(p) for p in sorted((STATE / 'native').glob('*.terminal.json'))]
            report['native_cli_dispatches'] = len(records)
            report['verified_successful_model_calls'] = sum(r['status'] == 'success' for r in records)
            report['reported_actual_cost_usd'] = sum(r['actual_cost_usd'] or 0 for r in records)
            report['unknown_cost_calls'] = sum(r['actual_cost_usd'] is None for r in records)
            report['scope_conservative_debit_usd'] = sum(r['cost_debit_usd'] for r in records)
            report['candidate_conservative_debit_usd'] = prior['prior_candidate_debit_usd'] + report['scope_conservative_debit_usd']
            report['evidence_hashes'] = {str(p.relative_to(STATE)): runtime.digest(p.read_bytes())
                                       for p in sorted(STATE.rglob('*.json')) if 'cli' not in p.relative_to(STATE).parts}
            runtime.exclusive_json(STATE / 'report-v1.json', report)
        print(json.dumps(report, indent=2))
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    main(parser.parse_args().live)
