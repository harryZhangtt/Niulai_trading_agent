"""Provider-free controls for the synthetic-only LangSmith prerequisite path."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tracers import LangChainTracer
from langsmith import Client, tracing_context

from tuning.langchain_pilot.graph import CALCULATOR_PROMPT
from tuning.langchain_pilot.observability import (
    atomic_runnable, cases, checked_calculation, credential, digest, evaluator, target)
from tuning.langchain_pilot.session_model import SessionModelError
from tuning.langchain_pilot.verify_observability import target_inputs


class ObservabilityTests(unittest.TestCase):
    def test_public_roster_covers_values_and_invalid_input(self):
        runnable = atomic_runnable(ChatPromptTemplate.from_messages([('system', CALCULATOR_PROMPT)]))
        for case in cases():
            self.assertEqual(runnable.invoke(case['inputs']), case['outputs'])

    def test_unlisted_inputs_never_reach_calculator(self):
        runnable = atomic_runnable(ChatPromptTemplate.from_messages([('system', CALCULATOR_PROMPT)]))
        private_shape = {'case': {**cases()[0]['inputs']['case'], 'case_id': 'not-public'}}
        with patch('tuning.langchain_pilot.observability.calculate') as calculator:
            with self.assertRaisesRegex(SessionModelError, 'PUBLIC_FIXTURE_ONLY'):
                runnable.invoke(private_shape)
        calculator.assert_not_called()

    def test_bad_calculator_result_fails_independent_gate(self):
        with patch('tuning.langchain_pilot.observability.calculate', return_value={'per_share': '999'}):
            with self.assertRaisesRegex(SessionModelError, 'INDEPENDENT_ARITHMETIC'):
                checked_calculation(cases()[0]['inputs']['case'])

    def test_grader_rejects_wrong_answer_and_missing_status(self):
        example = SimpleNamespace(outputs=cases()[0]['outputs'])
        for output in ({'status': 'passed', 'per_share': '999'}, {'per_share': '10'}, {}):
            self.assertFalse(evaluator(SimpleNamespace(outputs=output), example)['score'])
        self.assertTrue(evaluator(SimpleNamespace(outputs=example.outputs), example)['score'])

    def test_sdk_target_input_mapping_preserves_unexpected_fields(self):
        original = cases()[0]['inputs']
        self.assertEqual(target_inputs({'input': original, 'config': None}), original)
        for value in ({'input': original, 'config': {'unexpected': True}},
                      {'input': original, 'config': None, 'extra': True}):
            self.assertEqual(target_inputs(value), value)

    def test_prompt_drift_is_rejected_before_target_execution(self):
        client = SimpleNamespace(pull_prompt=lambda *args, **kwargs:
                                 ChatPromptTemplate.from_messages([('system', 'different')]))
        config = {'cases_sha256': digest(cases()), 'prompt_name': 'test', 'prompt_commit': 'pinned'}
        with self.assertRaisesRegex(SessionModelError, 'PROMPT_DRIFT'):
            target(client, config)

    def test_explicit_context_enables_real_spans_while_global_tracing_is_off(self):
        seen = []
        class Recorder(LangChainTracer):
            def _persist_run_single(self, run):
                seen.append((run.name, bool(run.extra.get('__disabled'))))
            @staticmethod
            def _update_run_single(run): pass
        client = Client(api_key='synthetic-not-dispatched', auto_batch_tracing=False)
        tracer = Recorder(client=client, project_name='synthetic-only')
        with patch.dict(os.environ, {'LANGSMITH_TRACING': 'false'}):
            with tracing_context(enabled=True, client=client, project_name='synthetic-only'):
                runnable = atomic_runnable(ChatPromptTemplate.from_messages([('system', CALCULATOR_PROMPT)]))
                runnable.invoke(cases()[0]['inputs'], config={'callbacks': [tracer]})
        client.close()
        self.assertGreaterEqual(len(seen), 4)
        self.assertTrue(all(not disabled for _, disabled in seen))

    def test_credential_is_private_and_has_no_endpoint_override(self):
        with tempfile.TemporaryDirectory(dir='.langchain-pilot/tmp') as directory:
            path = Path(directory) / 'langsmith.env'
            path.write_text('LANGSMITH_API_KEY=synthetic-test-secret\n');path.chmod(0o600)
            self.assertEqual(credential(path), 'synthetic-test-secret')
            path.chmod(0o644)
            with self.assertRaisesRegex(SessionModelError, 'PRIVATE_CONFIG'):
                credential(path)
            path.chmod(0o600)
            path.write_text('LANGSMITH_API_KEY=synthetic-test-secret\nLANGSMITH_ENDPOINT=https://invalid.test\n')
            with self.assertRaisesRegex(SessionModelError, 'PLATFORM_KEY'):
                credential(path)

    def test_credential_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory(dir='.langchain-pilot/tmp') as directory:
            path = Path(directory) / 'key';path.write_text('LANGSMITH_API_KEY=synthetic\n');path.chmod(0o600)
            link = Path(directory) / 'link';link.symlink_to(path)
            with self.assertRaises(OSError): credential(link)


if __name__ == '__main__':
    unittest.main()
