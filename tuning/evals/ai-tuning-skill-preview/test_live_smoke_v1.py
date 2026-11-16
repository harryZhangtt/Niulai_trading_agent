"""Provider-free adapter tests; fixtures never count as native evidence."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('smoke', HERE / 'live_smoke_v1.py')
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


def packet():
    material = s.runtime.verify_candidate()
    projected, _ = s.projection()
    request = s.runtime.solve_request(projected['cases'][0], s.runtime.MODELS[0], material, 'O0', [], .5)
    return s.runtime.provider_packet(request)


def native(p):
    return {'subtype': 'success', 'is_error': False, 'terminal_reason': 'completed',
            'session_id': 'fixture-session', 'structured_output': {'fixture': True},
            'total_cost_usd': .1, 'modelUsage': {p['id']: {
                'canonicalModel': p['id'], 'provider': 'firstParty', 'webSearchRequests': 0,
                'inputTokens': 10, 'outputTokens': 10, 'cacheReadInputTokens': 0,
                'cacheCreationInputTokens': 0, 'costUSD': .1}}}


class SmokeTests(unittest.TestCase):
    def setUp(self):
        s.STATE.mkdir(exist_ok=True, mode=0o700)
        self.temp = tempfile.TemporaryDirectory(prefix='test-', dir=s.STATE)
        self.state = Path(self.temp.name)
        self.p = packet()

    def tearDown(self):
        self.temp.cleanup()

    def test_projection_excludes_gold_and_preserves_hash(self):
        projected, provenance = s.projection()
        case = projected['cases'][0]
        self.assertEqual(set(case), {'case_id', 'case_material'})
        self.assertEqual(s.runtime.digest(case['case_material'].encode()), provenance['original_prompt_sha256'])
        self.assertFalse(provenance['gold_transmitted'])

    def test_command_reuses_maintained_transport(self):
        command = s.cli_command(self.p)
        self.assertIn('--safe-mode', command)
        self.assertIn('--restricted', command)
        self.assertEqual(command[command.index('--tools') + 1], '')
        self.assertEqual(command[command.index('--permission-prompts') + 1], 'none')
        self.assertEqual(command[command.index('--effort') + 1], 'high')
        self.assertNotIn('--fallback-model', command)
        self.assertNotIn('--dangerously-skip-permissions', command)
        self.assertNotIn('host', command[-1])

    def test_native_exact_identity_and_complete_usage(self):
        self.assertEqual(s.validate_native(native(self.p), self.p)['cost_usd'], .1)

    def test_fail_closed_native_variants(self):
        for field, value in [('canonicalModel', 'different'), ('provider', 'different'),
                             ('webSearchRequests', 1), ('inputTokens', None), ('costUSD', .2)]:
            with self.subTest(field=field):
                raw = native(self.p)
                raw['modelUsage'][self.p['id']][field] = value
                with self.assertRaises(ValueError):
                    s.validate_native(raw, self.p)
        for field, value in [('permission_denials', ['denied']), ('total_cost_usd', float('nan')),
                             ('terminal_reason', 'max_tokens'), ('session_id', '')]:
            with self.subTest(field=field):
                raw = native(self.p)
                raw[field] = value
                with self.assertRaises(ValueError):
                    s.validate_native(raw, self.p)

    def test_reservation_precedes_dispatch_and_env_is_local(self):
        prior = s.reconcile()
        def run(command, **kwargs):
            self.assertTrue((self.state / 'native/01.intent.json').exists())
            self.assertEqual(kwargs['env'].get('CLAUDECODE'), os.environ.get('CLAUDECODE'))
            for key in ('HOME', 'CLAUDE_CONFIG_DIR', 'TMPDIR', 'XDG_CACHE_HOME'):
                self.assertTrue(Path(kwargs['env'][key]).is_relative_to(self.state))
            return subprocess.CompletedProcess(command, 0, json.dumps(native(self.p)), '')
        adapter = s.Adapter(self.state, prior, run)
        self.assertEqual(adapter(self.p, 1)['status'], 'success')
        self.assertEqual(s.runtime.strict_load(self.state / 'native/01.terminal.json')['cost_debit_usd'], .1)

    def test_timeout_immutable_terminal_and_no_retry(self):
        calls = []
        def fail(*args, **kwargs):
            calls.append(1)
            raise subprocess.TimeoutExpired('claude', 1)
        adapter = s.Adapter(self.state, s.reconcile(), fail)
        with self.assertRaises(subprocess.TimeoutExpired):
            adapter(self.p, 1)
        terminal = self.state / 'native/01.terminal.json'
        original = terminal.read_bytes()
        with self.assertRaisesRegex(ValueError, 'NATIVE_TERMINAL_FENCED'):
            adapter(self.p, 1)
        self.assertEqual(terminal.read_bytes(), original)
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads(original)['cost_debit_usd'], .5)

    def test_existing_unknown_blocks_dispatch(self):
        s.runtime.exclusive_json(self.state / 'native/01.intent.json', {'reserved_usd': .5})
        with self.assertRaisesRegex(ValueError, 'NATIVE_UNKNOWN_FENCED'):
            s.Adapter(self.state, s.reconcile(), lambda *a, **k: self.fail('called'))(self.p, 1)

    def test_candidate_budget_blocks_before_dispatch(self):
        prior = s.reconcile()
        prior['prior_candidate_debit_usd'] = 24.6
        with patch.object(s, 'reconcile', return_value=prior):
            with self.assertRaisesRegex(ValueError, 'AGGREGATE_BUDGET_EXHAUSTED'):
                s.Adapter(self.state, prior, lambda *a, **k: self.fail('called'))(self.p, 1)
        self.assertFalse((self.state / 'native').exists())

    def test_six_call_limit(self):
        prior = s.reconcile()
        adapter = s.Adapter(self.state, prior, lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, json.dumps(native(self.p)), ''))
        for _ in range(6):
            adapter(self.p, 1)
        with self.assertRaisesRegex(ValueError, 'CALL_COUNT_CAP'):
            adapter(self.p, 1)

    def test_prior_unknown_fences(self):
        (self.state / 'o0/campaign').mkdir(parents=True)
        (self.state / 'o0/campaign/solve.intent.json').write_text('{}')
        (self.state / 'baseline-budget.json').write_text('{"recorded_spend_usd":0,"candidate_version":"fixture"}')
        with self.assertRaisesRegex(ValueError, 'PRIOR_UNKNOWN'):
            s.reconcile(self.state)

    def test_six_call_provider_free_campaign_composition(self):
        projected, _ = s.projection()
        cases = self.state / 'cases.json'
        cases.write_text(json.dumps(projected))
        def run(command, **kwargs):
            p = copy.deepcopy(self.p)
            p['id'] = command[command.index('--model') + 1]
            raw = native(p)
            if 'options' in json.loads(command[-1]):
                raw['structured_output'] = {'outcome': 'MATCH', 'selected_options': [1],
                    'clarification': '', 'rationale': 'The measurement constraint applies.'}
            else:
                raw['structured_output'] = {'decision': 'Use the bounded local change.',
                    'next_actions': ['Run the bounded provider-free check.'],
                    'evidence_basis': [{'kind': 'engineering_principle',
                        'statement': 'Validate the smallest reversible path first.'}],
                    'allowed_claim': 'Only the synthetic fixture path was checked.'}
            return subprocess.CompletedProcess(command, 0, json.dumps(raw), '')
        adapter = s.Adapter(self.state, s.reconcile(), run)
        for arm in ('O0', 'O1'):
            manifest = s.runtime.run_campaign(arm, cases, adapter,
                state_root=self.state / 'campaigns', hard_cap_usd=3, allow_test_state=True)
            self.assertTrue(manifest['complete'])
        records = list((self.state / 'native').glob('*.terminal.json'))
        self.assertEqual(len(records), 6)
        self.assertAlmostEqual(sum(json.loads(p.read_text())['cost_debit_usd'] for p in records), .6)

    def test_permission_denial_no_retry(self):
        calls = []
        def denied(command, **kwargs):
            calls.append(1)
            return subprocess.CompletedProcess(command, 1, '', 'permission denied')
        adapter = s.Adapter(self.state, s.reconcile(), denied)
        with self.assertRaisesRegex(ValueError, 'CLI_NONZERO_EXIT'):
            adapter(self.p, 1)
        with self.assertRaisesRegex(ValueError, 'NATIVE_TERMINAL_FENCED'):
            adapter(self.p, 1)
        self.assertEqual(len(calls), 1)

    def test_frozen_identity_leak_gate(self):
        material = s.runtime.verify_candidate()
        with self.assertRaises(ValueError):
            s.runtime.validate_model_view_privacy({'text': 'KC-EVIDENCE-001'}, material['cards'], material['catalog'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
