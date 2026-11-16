from pathlib import Path
from dataclasses import replace
import hashlib
import json
import tempfile
import unittest

from _loader import submodule


class CodexCandidateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = submodule("codex")
        cls.t = submodule("codex_contracts")
        cls.fx = Path(__file__).resolve().parents[2] / "fixtures" / "isolated_canary_q1"

    def plan(self, raw=b"hello"):
        prompt = self.t.PromptBytesV1.bind(raw)
        return self.c.build_invocation_plan(prompt=prompt, configured_model="gpt-test", effort="low", final_output_token="@output")

    def capture(self, rel, plan, *, output=b"private output", final=True, phase="terminal", retry=True):
        binding = self.t.FinalOutputBindingV1(hashlib.sha256(output).hexdigest(), len(output), True, output) if final else None
        return self.t.CaptureEnvelopeV1((self.fx / rel).read_bytes(), phase, 0, None, True, plan.stdin_sha256, plan.stdin_length, plan.stdin_length, plan.argv_sha256, retry, binding)

    def test_gate_is_closed_and_manifest_validation_is_exact(self):
        gate = self.c.capability_gate()
        self.assertFalse(gate.capability_open)
        self.assertFalse(gate.source_authority_verified)
        manifest = self.c.load_authority_manifest()
        self.assertFalse(manifest["source_authority_complete"])
        bad = dict(manifest); bad["extra"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-authority.json"
            path.write_text(json.dumps(bad))
            with self.assertRaisesRegex(self.t.CodexCandidateError, "^CODEX_Q1_AUTHORITY_INVALID$"):
                self.c.load_authority_manifest(path)

    def test_prompt_and_plan_are_redacted_self_validating_and_retry_zero(self):
        plan = self.plan(b"PRIVATE_PROMPT")
        self.assertEqual(plan.argv.count("request_max_retries=0"), 1)
        self.assertEqual(plan.argv.count("stream_max_retries=0"), 1)
        self.assertIn('model_reasoning_effort="low"', plan.argv)
        self.assertNotIn("PRIVATE_PROMPT", repr(plan))
        with self.assertRaisesRegex(self.t.CodexCandidateError, "^CODEX_Q1_PROMPT_BINDING_MISMATCH$"):
            self.t.PromptBytesV1("0" * 64, 1, b"hello")
        with self.assertRaisesRegex(self.t.CodexCandidateError, "^CODEX_Q1_PROMPT_BINDING_MISMATCH$"):
            self.t.PromptBytesV1(hashlib.sha256(b"x").hexdigest(), True, b"x")
        with self.assertRaisesRegex(self.t.CodexCandidateError, "^CODEX_Q1_PROMPT_BINDING_MISMATCH$"):
            replace(plan, argv=("codex", "exec", "-"))
        forged = ("evil",) + plan.argv[1:]
        with self.assertRaisesRegex(self.t.CodexCandidateError, "^CODEX_Q1_PROMPT_BINDING_MISMATCH$"):
            self.t.InvocationPlanV1(forged, plan.stdin_chunks, plan.stdin_sha256, plan.stdin_length, plan.configured_model, plan.effort, plan.final_output_token, hashlib.sha256(submodule("canonical").canonical_json_bytes(list(forged))).hexdigest())

    def test_nominal_binds_plan_process_and_last_agent_output(self):
        plan = self.plan()
        result = self.c.translate(self.capture("valid/codex-completed.jsonl", plan), plan)
        self.assertEqual((result.status, result.code), ("succeeded", "CODEX_Q1_COMPLETED"))
        self.assertTrue(result.retry_zero_verified)
        with self.assertRaisesRegex(TypeError, "CANARY_IMMUTABLE"):
            result.item_counts["agent_message"] = 9
        mismatch = self.c.translate(self.capture("valid/codex-completed.jsonl", plan, output=b"unrelated"), plan)
        self.assertEqual((mismatch.status, mismatch.code), ("unknown", "CODEX_Q1_PROCESS_CONTRADICTORY"))
        bad_launch = replace(self.capture("valid/codex-completed.jsonl", plan), launch_binding_sha256="d" * 64)
        self.assertEqual(self.c.translate(bad_launch, plan).status, "unknown")
        running = replace(self.capture("valid/codex-completed.jsonl", plan), process_phase="submitted")
        self.assertEqual(self.c.translate(running, plan).status, "unknown")

    def test_missing_terminal_tools_unfinished_model_and_bad_types(self):
        plan = self.plan()
        self.assertEqual(self.c.translate(self.capture("faults/codex-missing-terminal.jsonl", plan, final=False), plan).code, "CODEX_Q1_TERMINAL_MISSING")
        self.assertEqual(self.c.translate(self.capture("faults/codex-tool.jsonl", plan), plan).code, "CODEX_Q1_TOOL_POLICY_VIOLATION")
        self.assertEqual(self.c.translate(self.capture("faults/codex-tool-started.jsonl", plan), plan).status, "unknown")
        self.assertEqual(self.c.translate(self.capture("faults/codex-unfinished-item.jsonl", plan), plan).status, "unknown")
        self.assertEqual(self.c.translate(self.capture("faults/codex-model-field.jsonl", plan), plan).code, "CODEX_Q1_EVENT_UNSUPPORTED")
        raw = b'{"thread_id":"t","type":"thread.started"}\n{"type":"turn.started"}\n{"item":{"id":"i","text":7,"type":"agent_message"},"type":"item.completed"}\n{"type":"turn.completed"}\n'
        cap = replace(self.capture("valid/codex-completed.jsonl", plan), stdout_jsonl=raw)
        self.assertEqual(self.c.translate(cap, plan).status, "unknown")
        with self.assertRaisesRegex(self.t.CodexCandidateError, "^CODEX_Q1_PROCESS_CONTRADICTORY$"):
            replace(self.capture("valid/codex-completed.jsonl", plan), prompt_length=True)
        with self.assertRaisesRegex(self.t.CodexCandidateError, "^CODEX_Q1_PROCESS_CONTRADICTORY$"):
            replace(self.capture("valid/codex-completed.jsonl", plan), final_output=object())
        raw_surrogate = b'{"thread_id":"t","type":"thread.started"}\n{"type":"turn.started"}\n{"item":{"id":"i","text":"\\ud800","type":"agent_message"},"type":"item.completed"}\n{"type":"turn.completed"}\n'
        self.assertEqual(self.c.translate(replace(self.capture("valid/codex-completed.jsonl", plan), stdout_jsonl=raw_surrogate), plan).status, "unknown")
        with self.assertRaisesRegex(self.t.CodexCandidateError, "^CODEX_Q1_CAPABILITY_CLOSED$"):
            self.t.CapabilityGateV1(True, True, True, True, True, True, True, True)
        with self.assertRaisesRegex(self.t.CodexCandidateError, "^CODEX_Q1_CAPABILITY_CLOSED$"):
            self.t.CapabilityGateV1(True, True, True, True, True, True, True, False)
        with self.assertRaisesRegex(self.t.CodexCandidateError, "^CODEX_Q1_EVENT_FIELDS_INVALID$"):
            self.t.TranslationReceiptV1(1, "succeeded", "CODEX_Q1_COMPLETED", "streaming", "possibly_submitted", "anything", 0, {}, False, False, False, False, "configured_cli_argument", False, None, False, False)
        with self.assertRaisesRegex(self.t.CodexCandidateError, "^CODEX_Q1_EVENT_FIELDS_INVALID$"):
            self.t.TranslationReceiptV1(1, "failed", "CODEX_Q1_TURN_FAILED", "streaming", "possibly_submitted", "missing", 1, {}, False, False, False, False, "configured_cli_argument", False, None, False, False)
        with self.assertRaisesRegex(self.t.CodexCandidateError, "^CODEX_Q1_EVENT_FIELDS_INVALID$"):
            self.t.TranslationReceiptV1(1, "unknown", "CODEX_Q1_TURN_FAILED", "streaming", "possibly_submitted", "missing", 1, {}, False, False, False, False, "configured_cli_argument", False, None, False, False)
        with self.assertRaisesRegex(self.t.CodexCandidateError, "^CODEX_Q1_EVENT_FIELDS_INVALID$"):
            self.t.TranslationReceiptV1(1, "unknown", "CODEX_Q1_EVENT_ORDER_INVALID", "streaming", "possibly_submitted", "missing", 1, {}, False, True, False, False, "configured_cli_argument", False, None, False, False)
        with self.assertRaisesRegex(self.t.CodexCandidateError, "^CODEX_Q1_EVENT_FIELDS_INVALID$"):
            self.t.TranslationReceiptV1(1, "unknown", "CODEX_Q1_FORGED", "streaming", "possibly_submitted", "missing", 1, {}, False, False, False, False, "configured_cli_argument", False, None, False, False)
        with self.assertRaisesRegex(self.t.CodexCandidateError, "^CODEX_Q1_EVENT_FIELDS_INVALID$"):
            self.t.TranslationReceiptV1(1, "failed", "CODEX_Q1_TOOL_POLICY_VIOLATION", "terminal", "definitely_submitted", "turn.completed", 3, {}, False, True, True, True, "configured_cli_argument", False, None, False, False)
        retry_unknown = self.t.TranslationReceiptV1(1, "unknown", "CODEX_Q1_RETRY_ZERO_UNPROVEN", "streaming", "possibly_submitted", "missing", 0, {}, False, False, False, False, "configured_cli_argument", False, None, False, False)
        self.assertEqual(retry_unknown.status, "unknown")
        with self.assertRaisesRegex(self.t.CodexCandidateError, "^CODEX_Q1_EVENT_FIELDS_INVALID$"):
            self.t.TranslationReceiptV1(1, "unknown", "CODEX_Q1_CAPTURE_TRUNCATED", "terminal", "definitely_submitted", "turn.completed", 1, {}, False, False, False, False, "configured_cli_argument", False, None, False, False)

    def test_duplicate_key_is_unknown(self):
        plan = self.plan()
        raw = b'{"type":"thread.started","type":"thread.started"}\n'
        cap = self.t.CaptureEnvelopeV1(raw, "submitted", None, None, True, plan.stdin_sha256, plan.stdin_length, plan.stdin_length, plan.argv_sha256, True, None)
        self.assertEqual(self.c.translate(cap, plan).code, "CODEX_Q1_EVENT_DUPLICATE_KEY")


if __name__ == "__main__":
    unittest.main()
