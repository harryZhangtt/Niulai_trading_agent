from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from shared.job_runtime.provider_contract import ProviderResultV1
from shared.job_runtime.providers.codex_cli import (
    CAPABILITIES, MAX_EVENT_BYTES, NORMALIZED_SCHEMA, PRODUCTION_TRANSLATION,
    FinalOutputResolver, NormalizedCodexRunnerEvidenceV1, run_one_shot,
)
from shared.job_runtime.retry_policy import RetryPolicyV2, decide_retry
from shared.job_runtime.model import (
    CODEX_TRANSLATION_CAPABILITY, ModelError, translate_codex_jsonl,
)


FIXTURES = Path(__file__).parent / "fixtures" / "codex_cli"
NOW = datetime(2026, 11, 6, 0, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 11, 6, 0, 0, 1, tzinfo=timezone.utc)
DEADLINE = datetime(2026, 11, 6, 0, 0, 5, tzinfo=timezone.utc)
MODEL = "gpt-6.1-sol"
OPERATION = "infra/codex/slot-1"


def digest(value):
    return hashlib.sha256(value).hexdigest()


def classification(category="none", authority="none", *, http_status=None,
                   retry=None, retry_after=None, retry_source=None):
    return {
        "category": category, "authority": authority, "http_status": http_status,
        "provider_should_retry": retry, "retry_after": retry_after,
        "retry_after_source": retry_source,
    }


def observed_success_events():
    rows = [json.loads(line) for line in (FIXTURES / "success.jsonl").read_text().splitlines()]
    rows[0]["model"] = MODEL
    return b"".join(json.dumps(row, separators=(",", ":")).encode() + b"\n" for row in rows)


def evidence(events=None, *, process_phase="submitted", exit_code=0, signal=None,
             final=True, stderr=None):
    if events is None:
        events = observed_success_events()
    return NormalizedCodexRunnerEvidenceV1(
        schema=NORMALIZED_SCHEMA, process_phase=process_phase,
        exit_code=exit_code, signal=signal, events_jsonl=events,
        events_ref="opaque/events-1", events_sha256=digest(events),
        final_output_ref="final.bin" if final else None,
        final_output_sha256=digest(b'{"ok":true}') if final else None,
        final_output_size=len(b'{"ok":true}') if final else None,
        started_at=NOW, ended_at=END, deadline_at=DEADLINE,
        stderr_classification=stderr or classification(),
    )


class CountingRunner:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.value


class CodexCliProviderAdapterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        os.chmod(self.root, 0o700)
        self.final = self.root / "final.bin"
        self.final.write_bytes(b'{"ok":true}')
        os.chmod(self.final, 0o600)
        self.resolver = FinalOutputResolver(self.root)

    def normalize(self, value, *, resolver=True, nonclaim=False):
        runner = CountingRunner(value)
        chosen_resolver = self.resolver if resolver is True else resolver or None
        result = run_one_shot(operation_id=OPERATION, expected_model=MODEL,
                              invocation_runner=runner, file_resolver=chosen_resolver,
                              configured_model_nonclaim=nonclaim)
        self.assertEqual(runner.calls, 1)
        self.assertIsInstance(result, ProviderResultV1)
        self.assertFalse(result.receipt["automatic_retry"])
        return result

    def test_success_requires_completed_exit_zero_and_bounded_final_hash(self):
        result = self.normalize(evidence())
        self.assertEqual((result.status.value, result.phase.value,
                          result.submission.value, result.terminal_proof.value),
                         ("succeeded", "terminal", "definitely_submitted", "verified"))
        self.assertEqual(result.operation_id, OPERATION)
        self.assertEqual(result.code, "MODEL_TURN_COMPLETED")
        self.assertTrue(result.receipt["observed_model_verified"])
        self.assertTrue(result.receipt["final_custody_verified"])
        self.assertEqual(dict(CAPABILITIES), {
            "contract_ready": True, "runner_translation_verified": False,
            "runtime_unverified": True,
        })
        self.assertEqual(result.receipt["normalized_schema"], NORMALIZED_SCHEMA)
        self.assertEqual(result.receipt["normalized_version"], 1)
        rendered = repr(dict(result.receipt))
        for forbidden in ("synthetic-thread", '{"ok":true}', "opaque/", "/Users/"):
            self.assertNotIn(forbidden, rendered)


    def test_configured_model_nonclaim_allows_protocol_success_without_provider_model(self):
        events=(FIXTURES/'success.jsonl').read_bytes()
        result=self.normalize(evidence(events),nonclaim=True)
        self.assertEqual((result.status.value,result.code),("succeeded","MODEL_TURN_COMPLETED"))
        self.assertFalse(result.receipt["observed_model_verified"])
        self.assertEqual(result.receipt["model_binding_source"],"configured_cli_argument")
        self.assertFalse(result.receipt["provider_reported_model"])

    def test_source_bound_0167_translator_is_model_nonclaim_and_collab_closed(self):
        rows=[
            {"type":"thread.started","thread_id":"private-thread"},
            {"type":"turn.started"},
            {"type":"item.completed","item":{"id":"a","type":"agent_message","text":"private"}},
            {"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}},
        ]
        raw=b''.join(json.dumps(row,separators=(",",":")).encode()+b"\n" for row in rows)
        normalized=[json.loads(line) for line in translate_codex_jsonl(raw,MODEL).splitlines()]
        self.assertEqual([row["type"] for row in normalized],["invocation.started","invocation.completed"])
        self.assertTrue(all("model" not in row for row in normalized))
        collab=rows[:2]+[
            {"type":"item.started","item":{"id":"c","type":"collab_tool_call","tool":"spawn","status":"running"}},
            {"type":"item.completed","item":{"id":"c","type":"collab_tool_call","tool":"spawn","status":"completed"}},
            rows[-1],
        ]
        raw=b''.join(json.dumps(row,separators=(",",":")).encode()+b"\n" for row in collab)
        kinds=[json.loads(line) for line in translate_codex_jsonl(raw,MODEL).splitlines()]
        self.assertEqual(kinds[1],{"type":"activity.observed","activity":{"kind":"collaboration"}})
        self.assertFalse(CODEX_TRANSLATION_CAPABILITY["production_translation_verified"])
        bad=rows[:2]+[{"type":"item.completed","item":{"id":"c","type":"collab_agent_tool_call","tool":"x","status":"done"}},rows[-1]]
        raw=b''.join(json.dumps(row,separators=(",",":")).encode()+b"\n" for row in bad)
        with self.assertRaisesRegex(ModelError,"CODEX_CAPTURE_ITEM_UNSUPPORTED"):
            translate_codex_jsonl(raw,MODEL)

    def test_direct_preconnect_probe_maps_to_safe_not_started_retry(self):
        value = evidence(
            b"", process_phase="not_started", exit_code=None, final=False,
            stderr=classification("connection", "not_submitted"))
        result = self.normalize(value)
        self.assertEqual(
            (result.phase.value, result.submission.value, result.status.value,
             result.failure_kind.value, result.code, result.safe_retry_candidate),
            ("not_started", "not_submitted", "retryable", "connection",
             "CODEX_CONNECT_RETRY_CANDIDATE", True))

    def test_direct_pre_submit_http_502_probe_is_safe_retry_candidate(self):
        value = evidence(
            b"", process_phase="connecting", exit_code=None, final=False,
            stderr=classification("http", "not_submitted", http_status=502))
        result = self.normalize(value)
        self.assertEqual(
            (result.phase.value, result.submission.value, result.status.value,
             result.failure_kind.value, result.http_status,
             result.safe_retry_candidate),
            ("connecting", "not_submitted", "retryable", "http", 502, True))

    def test_prelaunch_429_retry_after_and_real_retry_policy(self):
        value = evidence(b"", process_phase="connecting", exit_code=None, final=False,
                         stderr=classification("http", "not_submitted", http_status=429,
                                               retry=True, retry_after=3,
                                               retry_source="retry-after-seconds"))
        result = self.normalize(value)
        self.assertEqual((result.status.value, result.phase.value, result.submission.value,
                          result.http_status), ("retryable", "connecting", "not_submitted", 429))
        self.assertEqual(result.retry_after_at, datetime(2026, 11, 6, 0, 0, 4, tzinfo=timezone.utc))
        decision = decide_retry(result, RetryPolicyV2(3, 1, 10), slot_id="slot-1",
                                attempt=1, now=END)
        self.assertEqual(decision.disposition, "retry")

    def test_prelaunch_529_connect_dns_and_tls_are_retry_candidates(self):
        cases = [
            classification("http", "not_submitted", http_status=529, retry=True),
            classification("http", "not_submitted", http_status=503, retry=True),
            classification("http", "not_submitted", http_status=400, retry=True),
            classification("connection", "not_submitted", retry=True),
            classification("dns", "not_submitted", retry=True),
            classification("tls", "not_submitted", retry=True),
        ]
        for envelope in cases:
            with self.subTest(category=envelope["category"]):
                result = self.normalize(evidence(b"", process_phase="not_started",
                                           exit_code=None, final=False, stderr=envelope))
                self.assertTrue(result.safe_retry_candidate)

    def test_prelaunch_rejects_any_launch_or_output_evidence(self):
        base = evidence(b"", process_phase="connecting", exit_code=None, final=False,
                        stderr=classification("http", "not_submitted", http_status=429,
                                              retry=True))
        submitted_events = (FIXTURES / "success.jsonl").read_bytes()
        cases = [
            replace(base, events_jsonl=submitted_events,
                    events_sha256=digest(submitted_events)),
            replace(base, final_output_ref="opaque/final",
                    final_output_sha256="a" * 64, final_output_size=1),
            replace(base, signal=9),
            replace(base, exit_code=1),
        ]
        for value in cases:
            with self.subTest(value=value):
                result = self.normalize(value)
                self.assertEqual((result.status.value, result.code,
                                  result.safe_retry_candidate),
                                 ("unknown", "CODEX_PRELAUNCH_EVIDENCE_CONFLICT", False))

    def test_explicit_retry_denial_wins_for_typed_transients(self):
        for envelope in (
            classification("http", "not_submitted", http_status=429, retry=False),
            classification("http", "not_submitted", http_status=503, retry=False),
            classification("connection", "not_submitted", retry=False),
        ):
            result = self.normalize(evidence(
                b"", process_phase="connecting", exit_code=None, final=False,
                stderr=envelope))
            self.assertEqual((result.status.value, result.safe_retry_candidate),
                             ("failed", False))

    def test_direct_prelaunch_auth_probe_is_terminal_without_retry(self):
        value = evidence(
            b"", process_phase="connecting", exit_code=None, final=False,
            stderr=classification("auth", "not_submitted", retry=False))
        result = self.normalize(value)
        self.assertEqual(
            (result.phase.value, result.submission.value,
             result.terminal_proof.value, result.status.value,
             result.failure_kind.value, result.code,
             result.provider_should_retry, result.safe_retry_candidate),
            ("connecting", "not_submitted", "absent", "failed", "auth",
             "MODEL_AUTH_REQUIRED", False, False))

    def test_direct_verified_terminal_auth_probe_is_distinct(self):
        value = evidence(
            (FIXTURES / "turn_failed.jsonl").read_bytes(),
            exit_code=1, final=False,
            stderr=classification("auth", "verified_terminal", retry=False))
        result = self.normalize(value)
        self.assertEqual(
            (result.phase.value, result.submission.value,
             result.terminal_proof.value, result.status.value,
             result.failure_kind.value, result.code,
             result.provider_should_retry, result.safe_retry_candidate),
            ("terminal", "definitely_submitted", "verified", "failed",
             "auth", "MODEL_AUTH_REQUIRED", False, False))

    def test_quota_exhausted_is_terminal_and_distinct_from_429_retry_after(self):
        quota = self.normalize(evidence(
            b"", process_phase="connecting", exit_code=None, final=False,
            stderr=classification(
                "quota_exhausted", "not_submitted", retry=False)))
        self.assertEqual(
            (quota.phase.value, quota.submission.value, quota.status.value,
             quota.failure_kind.value, quota.code, quota.http_status,
             quota.retry_after_at, quota.provider_should_retry,
             quota.safe_retry_candidate),
            ("connecting", "not_submitted", "failed", "quota_exhausted",
             "MODEL_QUOTA_EXHAUSTED", None, None, False, False))
        quota_decision = decide_retry(
            quota, RetryPolicyV2(3, 1, 10), slot_id="slot-1",
            attempt=1, now=END)
        self.assertEqual(
            (quota_decision.disposition, quota_decision.reason),
            ("terminal_failed", "PROVIDER_QUOTA_EXHAUSTED"))

        rate_limit = self.normalize(evidence(
            b"", process_phase="connecting", exit_code=None, final=False,
            stderr=classification(
                "http", "not_submitted", http_status=429, retry=True,
                retry_after=3, retry_source="retry-after-seconds")))
        self.assertEqual(
            (rate_limit.status.value, rate_limit.failure_kind.value,
             rate_limit.http_status, rate_limit.retry_after_at,
             rate_limit.safe_retry_candidate),
            ("retryable", "http", 429,
             datetime(2026, 11, 6, 0, 0, 4, tzinfo=timezone.utc), True))

    def test_auth_model_config_policy_need_prelaunch_or_verified_terminal(self):
        expected = {
            "auth": "MODEL_AUTH_REQUIRED", "model": "MODEL_UNAVAILABLE",
            "config": "MODEL_CONFIGURATION_REJECTED", "policy": "MODEL_POLICY_VIOLATION",
        }
        for category, code in expected.items():
            with self.subTest(category=category, boundary="prelaunch"):
                result = self.normalize(evidence(
                    b"", process_phase="connecting", exit_code=None, final=False,
                    stderr=classification(category, "not_submitted", retry=False)))
                self.assertEqual((result.status.value, result.code), ("failed", code))
            with self.subTest(category=category, boundary="verified-terminal"):
                result = self.normalize(evidence(
                    (FIXTURES / "turn_failed.jsonl").read_bytes(), exit_code=1, final=False,
                    stderr=classification(category, "verified_terminal", retry=False)))
                self.assertEqual((result.status.value, result.code,
                                  result.terminal_proof.value), ("failed", code, "verified"))
            with self.subTest(category=category, boundary="unverified-postlaunch"):
                result = self.normalize(evidence(
                    (FIXTURES / "turn_failed.jsonl").read_bytes(), exit_code=1, final=False,
                    stderr=classification(category, "none", retry=False)))
                self.assertEqual(result.status.value, "unknown")

    def test_completed_stream_and_verified_permanent_failure_are_contradictory(self):
        for category in ("auth", "model", "config", "policy"):
            with self.subTest(category=category):
                result = self.normalize(evidence(
                    stderr=classification(category, "verified_terminal", retry=False)))
                self.assertEqual((result.status.value, result.phase.value,
                                  result.terminal_proof.value, result.code),
                                 ("unknown", "terminal", "contradictory",
                                  "CODEX_TERMINAL_EVIDENCE_CONTRADICTORY"))

    def test_direct_streaming_reset_probe_is_unknown_and_fenced(self):
        value = evidence(
            exit_code=1, final=False,
            stderr=classification("connection_reset", "none"))
        result = self.normalize(value)
        self.assertEqual(
            (result.phase.value, result.submission.value,
             result.terminal_proof.value, result.status.value,
             result.failure_kind.value, result.code,
             result.provider_should_retry, result.safe_retry_candidate),
            ("streaming", "definitely_submitted", "absent", "unknown",
             "connection_reset", "CODEX_CONNECTION_RESET", False, False))
        decision = decide_retry(
            result, RetryPolicyV2(3, 1, 10), slot_id="slot",
            attempt=1, now=END)
        self.assertEqual(
            (decision.disposition, decision.reason),
            ("unknown", "PROVIDER_OUTCOME_UNKNOWN"))

    def test_postlaunch_timeout_reset_signal_are_unknown_and_never_retried(self):
        cases = [
            (classification("timeout", "none"), None, "timeout"),
            (classification("connection_reset", "none"), None, "connection_reset"),
            (classification(), 9, "partial_response"),
        ]
        for envelope, signal_number, kind in cases:
            with self.subTest(kind=kind):
                value = evidence(exit_code=None if signal_number else 1,
                                 signal=signal_number, final=False, stderr=envelope)
                result = self.normalize(value)
                self.assertEqual((result.status.value, result.failure_kind.value,
                                  result.phase.value),
                                 ("unknown", kind, "streaming"))
                decision = decide_retry(result, RetryPolicyV2(3, 1, 10), slot_id="slot",
                                        attempt=1, now=END)
                self.assertEqual(decision.disposition, "unknown")

    def test_partial_malformed_duplicate_missing_terminal_and_eof_are_unknown(self):
        valid_start = b'{"type":"invocation.started"}\n'
        cases = {
            "partial": valid_start + b'{"type":',
            "malformed": valid_start + b'not-json\n',
            "duplicate": valid_start + b'{"type":"invocation.completed","type":"error"}\n',
            "missing": valid_start,
            "eof": valid_start + b'{"type":"invocation.completed"}',
            "empty": b"",
        }
        for name, events in cases.items():
            with self.subTest(name=name):
                result = self.normalize(evidence(events, exit_code=1, final=False))
                self.assertEqual(result.status.value, "unknown")
                self.assertEqual(result.phase.value, "submitted" if name == "empty" else "streaming")
                self.assertFalse(result.safe_retry_candidate)

    def test_exactly_one_start_terminal_and_no_event_after_terminal(self):
        cases = [
            b'{"type":"invocation.started"}\n{"type":"invocation.started"}\n{"type":"invocation.completed"}\n',
            b'{"type":"invocation.started"}\n{"type":"invocation.completed"}\n{"type":"runner.error"}\n',
            b'{"type":"invocation.started"}\n{"type":"invocation.completed"}\n{"type":"activity.observed"}\n',
            b'{"type":"invocation.completed"}\n',
        ]
        for events in cases:
            with self.subTest(events=events):
                result = self.normalize(evidence(events, exit_code=1, final=False))
                self.assertEqual(result.status.value, "unknown")

    def test_model_mismatch_and_tool_activity_are_contained(self):
        mismatch = (b'{"type":"invocation.started","model":"other-model"}\n'
                    b'{"type":"invocation.completed"}\n')
        result = self.normalize(evidence(mismatch))
        self.assertEqual((result.status.value, result.code),
                         ("unknown", "CODEX_MODEL_MISMATCH"))
        tool = self.normalize(evidence((FIXTURES / "tool.jsonl").read_bytes()))
        self.assertEqual((tool.status.value, tool.code, tool.failure_kind.value),
                         ("failed", "MODEL_TOOL_POLICY_VIOLATION", "policy"))

    def test_oversize_secret_and_private_path_never_escape_receipt(self):
        oversized = b"x" * (MAX_EVENT_BYTES + 1)
        value = replace(evidence(b"", exit_code=1, final=False),
                        events_jsonl=oversized, events_sha256=digest(oversized))
        result = self.normalize(value)
        self.assertEqual(result.status.value, "unknown")

        nested = None
        for _ in range(20):
            nested = {"nested": nested}
        deep_events = (json.dumps({"type": "invocation.started", "payload": nested}) + "\n" +
                       json.dumps({"type": "invocation.completed"}) + "\n").encode()
        deep = self.normalize(evidence(deep_events, exit_code=1, final=False))
        self.assertEqual((deep.status.value, deep.code), ("unknown", "CODEX_EVENT_BOUNDS"))

        secret = "SYNTHETIC-SECRET-CANARY"
        private_path = "/Users/example/private/output.txt"
        events = (json.dumps({"type": "invocation.started", "opaque_identity": secret,
                              "model": MODEL}) + "\n" +
                  json.dumps({"type": "invocation.completed", "usage": {
                      "input_tokens": 2, private_path: 7, secret: 9}}) + "\n").encode()
        sanitized = self.normalize(evidence(events))
        rendered = repr(dict(sanitized.receipt))
        self.assertNotIn(secret, rendered)
        self.assertNotIn(private_path, rendered)
        self.assertEqual(dict(sanitized.receipt["usage"]), {"input_tokens": 2})

    def test_success_requires_observed_model_and_descriptor_custody(self):
        missing_model = self.normalize(evidence((FIXTURES / "success.jsonl").read_bytes()))
        self.assertEqual((missing_model.status.value, missing_model.code),
                         ("unknown", "MODEL_IDENTITY_UNVERIFIED"))
        no_resolver = self.normalize(evidence(), resolver=False)
        self.assertEqual((no_resolver.status.value, no_resolver.code),
                         ("unknown", "CODEX_FINAL_CUSTODY_UNVERIFIED"))

    def test_closed_normalized_event_and_activity_grammar_rejects_future_shapes(self):
        future_event = (json.dumps({"type": "invocation.started", "model": MODEL}) + "\n" +
                        json.dumps({"type": "future.event"}) + "\n").encode()
        result = self.normalize(evidence(future_event, exit_code=1, final=False))
        self.assertEqual((result.status.value, result.code),
                         ("unknown", "CODEX_EVENT_TYPE"))
        future_activity = (json.dumps({"type": "invocation.started", "model": MODEL}) + "\n" +
                           json.dumps({"type": "activity.observed",
                                       "activity": {"kind": "future_tool"}}) + "\n" +
                           json.dumps({"type": "invocation.completed"}) + "\n").encode()
        result = self.normalize(evidence(future_activity))
        self.assertEqual((result.status.value, result.code),
                         ("unknown", "CODEX_NORMALIZED_ACTIVITY_UNSUPPORTED"))
        extra_field = (json.dumps({"type": "invocation.started", "model": MODEL,
                                   "future": True}) + "\n" +
                       json.dumps({"type": "invocation.completed"}) + "\n").encode()
        result = self.normalize(evidence(extra_field))
        self.assertEqual((result.status.value, result.code),
                         ("unknown", "CODEX_EVENT_FIELDS"))

    def test_verified_and_unverified_terminal_error_proofs_are_distinct(self):
        events = (FIXTURES / "error.jsonl").read_bytes()
        verified = self.normalize(evidence(
            events, exit_code=1, final=False,
            stderr=classification("provider", "verified_terminal", retry=False)))
        self.assertEqual((verified.status.value, verified.phase.value,
                          verified.terminal_proof.value),
                         ("failed", "terminal", "verified"))
        unverified = self.normalize(evidence(
            events, exit_code=1, final=False,
            stderr=classification("provider", "none", retry=False)))
        self.assertEqual((unverified.status.value, unverified.phase.value,
                          unverified.terminal_proof.value),
                         ("unknown", "streaming", "absent"))

    def test_final_resolver_rejects_symlink_insecure_race_drift_and_zero_hash(self):
        self.final.unlink()
        target = self.root / "target.bin"
        target.write_bytes(b'{"ok":true}'); os.chmod(target, 0o600)
        self.final.symlink_to(target)
        symlinked = self.normalize(evidence())
        self.assertEqual((symlinked.status.value, symlinked.code),
                         ("unknown", "CODEX_FINAL_PATH_UNSAFE"))

        self.final.unlink(); target.unlink()
        self.final.write_bytes(b'{"ok":true}'); os.chmod(self.final, 0o644)
        insecure = self.normalize(evidence())
        self.assertEqual((insecure.status.value, insecure.code),
                         ("unknown", "CODEX_FINAL_PATH_UNSAFE"))

        os.chmod(self.final, 0o600)
        drifted = replace(evidence(), final_output_sha256=digest(b"different"))
        drift = self.normalize(drifted)
        self.assertEqual((drift.status.value, drift.code),
                         ("unknown", "CODEX_FINAL_BINDING_MISMATCH"))

        zero = replace(evidence(), final_output_sha256="0" * 64)
        rejected = self.normalize(zero)
        self.assertEqual((rejected.status.value, rejected.code),
                         ("unknown", "CODEX_FINAL_HASH"))

        class RacingResolver(FinalOutputResolver):
            def _after_open(inner_self, path, _descriptor):
                path.unlink()
                path.write_bytes(b"replacement")
                os.chmod(path, 0o600)
        raced = self.normalize(evidence(), resolver=RacingResolver(self.root))
        self.assertEqual((raced.status.value, raced.code),
                         ("unknown", "CODEX_FINAL_CHANGED"))

    def test_host_cancellation_is_not_swallowed(self):
        class Cancelled:
            def __call__(self):
                raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            run_one_shot(operation_id=OPERATION, expected_model=MODEL,
                         invocation_runner=Cancelled(), file_resolver=self.resolver)

    def test_result_detaches_runner_mutations_and_operation_id_is_stable(self):
        mutable_classification = classification()
        value = evidence(stderr=mutable_classification)
        runner = CountingRunner(value)
        result = run_one_shot(operation_id=OPERATION, expected_model=MODEL,
                              invocation_runner=runner, file_resolver=self.resolver)
        original_hash = result.canonical_sha256
        mutable_classification["category"] = "auth"
        self.assertEqual(result.canonical_sha256, original_hash)
        self.assertEqual(result.operation_id, OPERATION)

    def test_runner_exception_is_sanitized_unknown_and_no_nested_retry(self):
        class Broken:
            calls = 0
            def __call__(self):
                self.calls += 1
                raise RuntimeError("SYNTHETIC-SECRET-CANARY /private/path")
        runner = Broken()
        result = run_one_shot(operation_id=OPERATION, expected_model=MODEL,
                              invocation_runner=runner)
        self.assertEqual(runner.calls, 1)
        self.assertEqual((result.status.value, result.submission.value),
                         ("unknown", "possibly_submitted"))
        self.assertNotIn("CANARY", repr(dict(result.receipt)))

    def test_normalized_evidence_type_and_schema_are_mandatory(self):
        missing = self.normalize({"process_phase": "submitted"})
        self.assertEqual((missing.status.value, missing.code),
                         ("unknown", "CODEX_NORMALIZED_EVIDENCE_TYPE"))
        wrong = self.normalize(replace(evidence(), schema="future_schema"))
        self.assertEqual((wrong.status.value, wrong.code),
                         ("unknown", "CODEX_NORMALIZED_SCHEMA"))

    def test_fixture_scope_makes_no_codex_source_or_live_claim(self):
        scope = json.loads((FIXTURES / "fixture_scope.json").read_text())
        self.assertEqual(scope["classification"],
                         "normalized_runner_fixture_supported_current_tests")
        self.assertIn("provider-neutral translation", scope["derived_from"])
        self.assertEqual(scope["normalized_schema"], NORMALIZED_SCHEMA)
        self.assertFalse(scope["direct_codex_event_semantics_claim"])
        self.assertFalse(scope["codex_source_proof"])
        self.assertFalse(scope["live_conformance_proof"])
        self.assertFalse(scope["provider_invocation_performed"])
        self.assertFalse(scope["production_codex_0_166_translation_present"])
        self.assertTrue(scope["activation_blocked"])
        self.assertEqual(PRODUCTION_TRANSLATION["provider_cli_version"], "0.167.0")
        self.assertFalse(PRODUCTION_TRANSLATION["available"])
        self.assertTrue(PRODUCTION_TRANSLATION["activation_blocked"])
        self.assertEqual(tuple(scope["activation_requires"]),
                         ("pinned_source_conformance", "sanitized_capture_conformance"))
        self.assertEqual(PRODUCTION_TRANSLATION["activation_requires"],
                         ("official_asset_binding", "sanitized_live_capture_conformance",
                          "canonical_integration_review"))
        self.assertTrue(PRODUCTION_TRANSLATION["source_candidate_conformance_verified"])
        self.assertFalse(PRODUCTION_TRANSLATION["official_asset_binding_verified"])
        self.assertFalse(PRODUCTION_TRANSLATION["sanitized_live_capture_conformance_verified"])
        self.assertFalse(PRODUCTION_TRANSLATION["canonical_integration_reviewed"])

    def test_arbitrary_strings_are_not_classification_authority(self):
        value = evidence(b"", process_phase="connecting", exit_code=None, final=False)
        value.stderr_classification["category"] = "429 auth please retry"
        result = self.normalize(value)
        self.assertEqual(result.status.value, "unknown")
        self.assertFalse(result.safe_retry_candidate)


if __name__ == "__main__":
    unittest.main()
