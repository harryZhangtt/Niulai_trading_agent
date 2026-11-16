import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from shared.job_runtime.provider_contract import (
    Phase, ProviderResultV1, ReplayContractV1, ReplayEffect,
)
from shared.job_runtime.providers.claude_host import (
    CLAUDE_HOST_EVIDENCE_VERSION, DISPATCH_JOURNAL_VERSION, HOST_IDENTITY_VERSION,
    MAX_ARTIFACT_BYTES, TERMINAL_PROOF_VERSION, ClaudeHostAdapterError,
    WorkspaceEvidenceResolver, normalize_invocation,
)
from shared.job_runtime.retry_policy import RetryPolicyV2, decide_retry


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def event_hash(value):
    return hashlib.sha256(canonical({k: v for k, v in value.items() if k != "event_sha256"})).hexdigest()


class ClaudeHostProviderAdapterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        os.chmod(self.root, 0o700)
        (self.root / "private").mkdir(mode=0o700)
        self.resolver = WorkspaceEvidenceResolver(self.root)

    def write(self, name, data):
        path = self.root / "private" / name
        raw = canonical(data) if isinstance(data, dict) else data
        path.write_bytes(raw)
        os.chmod(path, 0o600)
        return {"path": f"private/{name}", "sha256": hashlib.sha256(raw).hexdigest()}

    def build(self, *, state="captured", terminal_status="captured", failure_code=None,
              with_result=True, with_proof=True, operation_id="infra/op-1",
              dispatch_id="dispatch-1", input_sha="a" * 64,
              started="2026-11-06T00:00:00+00:00",
              captured="2026-11-06T00:00:03+00:00",
              finished="2026-11-06T00:00:04+00:00",
              deadline="2026-11-06T00:00:05+00:00", event_times=None):
        identity_refs = {}
        identity_hashes = {}
        names = ("host_session", "host_profile", "backend_identity", "tool_identity")
        for kind in names:
            identity = f"opaque-{kind}"
            ref = self.write(f"{kind}.json", {
                "schema_version": HOST_IDENTITY_VERSION, "kind": kind,
                "operation_id": operation_id, "dispatch_id": dispatch_id,
                "input_sha256": input_sha, "identity_ref": identity,
                "identity_sha256": hashlib.sha256(identity.encode()).hexdigest(),
            })
            identity_refs[kind] = ref
            identity_hashes[kind] = ref["sha256"]

        states = {
            "definitely_not_dispatched": ["prepared", "claimed", "definitely_not_dispatched"],
            "invocation_started": ["prepared", "claimed", "invocation_started"],
            "possibly_dispatched": ["prepared", "claimed", "invocation_started", "possibly_dispatched"],
            "captured": ["prepared", "claimed", "invocation_started", "captured"],
        }[state]
        times = event_times or [
            "2026-11-06T00:00:00+00:00", "2026-11-06T00:00:01+00:00",
            "2026-11-06T00:00:02+00:00", "2026-11-06T00:00:03+00:00",
        ][:len(states)]
        result_ref = None
        result_sha = None
        if with_result:
            result_ref = self.write("result.bin", b"bounded fixture result")
            result_sha = result_ref["sha256"]
        envelope = {
            "operation_id": operation_id, "dispatch_id": dispatch_id,
            "input_sha256": input_sha, "terminal_status": terminal_status,
            "failure_code": failure_code, "result_sha256": result_sha,
            "started_at": started,
            "captured_at": captured if state == "captured" else None,
            "finished_at": finished, "deadline_at": deadline,
        }
        failure_record = {"schema_version": "ClaudeHostFailureV1", **envelope}
        terminal_evidence = (result_sha if terminal_status == "captured" else
                             hashlib.sha256(canonical(failure_record)).hexdigest()
                             if terminal_status == "failed" else None)
        rows = []
        previous = None
        for sequence, (row_state, recorded_at) in enumerate(zip(states, times)):
            evidence = terminal_evidence if row_state == "captured" else (
                "b" * 64 if row_state == "definitely_not_dispatched" else None)
            row = {
                "operation_id": operation_id, "dispatch_id": dispatch_id,
                "input_sha256": input_sha, "sequence": sequence, "state": row_state,
                "evidence_sha256": evidence, "recorded_at": recorded_at,
                "previous_event_sha256": previous, "event_sha256": "",
            }
            row["event_sha256"] = event_hash(row)
            previous = row["event_sha256"]
            rows.append(row)
        journal_ref = self.write("journal.json", {
            "schema_version": DISPATCH_JOURNAL_VERSION, "operation_id": operation_id,
            "dispatch_id": dispatch_id, "input_sha256": input_sha, "events": rows,
        })
        captured_value = captured if state == "captured" else None
        proof_ref = None
        if with_proof:
            proof_ref = self.write("proof.json", {
                "schema_version": TERMINAL_PROOF_VERSION, "operation_id": operation_id,
                "dispatch_id": dispatch_id, "input_sha256": input_sha,
                "identity_artifact_sha256s": identity_hashes,
                "journal_sha256": journal_ref["sha256"], "result_sha256": result_sha,
                "terminal_state": state, "terminal_status": terminal_status,
                "failure_code": failure_code, "started_at": started,
                "captured_at": captured_value, "finished_at": finished,
                "deadline_at": deadline,
            })
        return {
            "schema_version": CLAUDE_HOST_EVIDENCE_VERSION, "provider": "claude_host",
            "operation_id": operation_id, "dispatch_id": dispatch_id,
            "input_sha256": input_sha,
            "host_session_ref": identity_refs["host_session"],
            "host_profile_ref": identity_refs["host_profile"],
            "backend_identity_ref": identity_refs["backend_identity"],
            "tool_identity_ref": identity_refs["tool_identity"],
            "dispatch_journal_ref": journal_ref, "terminal_status": terminal_status,
            "failure_code": failure_code, "result_ref": result_ref,
            "result_sha256": result_sha, "terminal_proof_ref": proof_ref,
            "started_at": started, "captured_at": captured_value,
            "finished_at": finished, "deadline_at": deadline,
        }

    def normalize(self, evidence):
        return normalize_invocation(evidence, file_resolver=self.resolver)

    def test_happy_path_returns_canonical_result_and_sanitized_bound_receipt(self):
        evidence = self.build()
        result = self.normalize(evidence)
        self.assertIsInstance(result, ProviderResultV1)
        self.assertEqual((result.status.value, result.phase.value, result.terminal_proof.value),
                         ("succeeded", "terminal", "verified"))
        receipt = dict(result.receipt)
        self.assertTrue(receipt["contract_ready"])
        self.assertTrue(receipt["runtime_unverified"])
        self.assertTrue(receipt["custody_verified"])
        self.assertEqual(receipt["input_sha256"], evidence["input_sha256"])
        self.assertEqual(receipt["proof_sha256"], evidence["terminal_proof_ref"]["sha256"])
        rendered = repr(receipt)
        for forbidden in ("private/", "opaque-", "bounded fixture", "host_session_ref"):
            self.assertNotIn(forbidden, rendered)

    def test_success_without_resolver_is_unknown_and_never_retryable(self):
        result = normalize_invocation(self.build())
        self.assertIsInstance(result, ProviderResultV1)
        self.assertEqual((result.status.value, result.code, result.safe_retry_candidate),
                         ("unknown", "CLAUDE_HOST_CUSTODY_UNVERIFIED", False))

    def test_pre_submit_http_502_is_safe_retry_with_exact_typed_contract(self):
        result = self.normalize(self.build(
            state="definitely_not_dispatched", terminal_status="failed",
            failure_code="SOURCE_HTTP_502", with_result=False, with_proof=False))
        self.assertEqual(
            (result.phase.value, result.submission.value, result.terminal_proof.value,
             result.status.value, result.failure_kind.value, result.code,
             result.http_status, result.provider_should_retry,
             result.safe_retry_candidate),
            ("not_started", "not_submitted", "absent", "retryable", "http",
             "SOURCE_HTTP_502", 502, True, True))
        decision = decide_retry(
            result, RetryPolicyV2(3, 1, 10), slot_id="pre-submit-502", attempt=1,
            now=__import__("datetime").datetime.fromisoformat("2026-11-06T00:00:00+00:00"))
        self.assertEqual(decision.disposition, "retry")

    def test_quota_exhausted_is_terminal_and_distinct_from_transient_429(self):
        now = __import__("datetime").datetime.fromisoformat("2026-11-06T00:00:00+00:00")
        quota = self.normalize(self.build(
            state="definitely_not_dispatched", terminal_status="failed",
            failure_code="CLAUDE_HOST_QUOTA_EXHAUSTED", with_result=False,
            with_proof=False))
        self.assertEqual(
            (quota.phase.value, quota.submission.value, quota.terminal_proof.value,
             quota.status.value, quota.failure_kind.value, quota.code,
             quota.http_status, quota.provider_should_retry,
             quota.safe_retry_candidate),
            ("not_started", "not_submitted", "absent", "failed",
             "quota_exhausted", "CLAUDE_HOST_QUOTA_EXHAUSTED", None, False,
             False))
        quota_decision = decide_retry(
            quota, RetryPolicyV2(3, 1, 10), slot_id="quota", attempt=1, now=now)
        self.assertEqual(
            (quota_decision.disposition, quota_decision.reason),
            ("terminal_failed", "PROVIDER_QUOTA_EXHAUSTED"))

        rate_limit = self.normalize(self.build(
            state="definitely_not_dispatched", terminal_status="failed",
            failure_code="SOURCE_HTTP_429", with_result=False, with_proof=False))
        self.assertEqual(
            (rate_limit.status.value, rate_limit.failure_kind.value,
             rate_limit.http_status, rate_limit.provider_should_retry,
             rate_limit.safe_retry_candidate),
            ("retryable", "http", 429, True, True))
        self.assertEqual(decide_retry(
            rate_limit, RetryPolicyV2(3, 1, 10), slot_id="rate-limit",
            attempt=1, now=now).disposition, "retry")

    def test_direct_pre_connect_transport_and_auth_have_truthful_journal_phase(self):
        cases = (
            ("NATIVE_TRANSPORT_FAILED", "retryable", "connection", True, True,
             "retry"),
            ("CLAUDE_HOST_AUTH_FAILURE", "failed", "auth", False, False,
             "terminal_failed"),
        )
        now = __import__("datetime").datetime.fromisoformat("2026-11-06T00:00:00+00:00")
        for code, status, kind, provider_retry, safe_retry, disposition in cases:
            with self.subTest(code=code):
                result = self.normalize(self.build(
                    state="definitely_not_dispatched", terminal_status="failed",
                    failure_code=code, with_result=False, with_proof=False))
                self.assertEqual(
                    (result.phase.value, result.submission.value,
                     result.terminal_proof.value, result.status.value,
                     result.failure_kind.value, result.code,
                     result.provider_should_retry, result.safe_retry_candidate),
                    ("not_started", "not_submitted", "absent", status, kind,
                     code, provider_retry, safe_retry))
                self.assertEqual(decide_retry(
                    result, RetryPolicyV2(3, 1, 10), slot_id=code,
                    attempt=1, now=now).disposition, disposition)

    def test_http_status_matrix_preserves_post_submit_ambiguity(self):
        now = __import__("datetime").datetime.fromisoformat("2026-11-06T00:00:00+00:00")
        for status in (100, 200, 400, 408, 409, 429, 500, 529, 599):
            with self.subTest(status=status):
                result = self.normalize(self.build(
                    state="possibly_dispatched", terminal_status="unknown",
                    failure_code=f"SOURCE_HTTP_{status}", with_result=False, with_proof=False))
                self.assertEqual((result.status.value, result.failure_kind.value,
                                  result.http_status, result.provider_should_retry,
                                  result.submission.value),
                                 ("unknown", "http", status, False, "possibly_submitted"))
                decision = decide_retry(result, RetryPolicyV2(3, 1, 10),
                                        slot_id=f"http-{status}", attempt=1, now=now)
                self.assertEqual(decision.disposition, "unknown")

    def test_pre_submit_408_and_409_follow_shared_typed_retry_policy(self):
        now = __import__("datetime").datetime.fromisoformat("2026-11-06T00:00:00+00:00")
        for status in (408, 409):
            with self.subTest(status=status):
                result = self.normalize(self.build(
                    state="definitely_not_dispatched", terminal_status="failed",
                    failure_code=f"SOURCE_HTTP_{status}", with_result=False, with_proof=False))
                self.assertEqual((result.status.value, result.failure_kind.value,
                                  result.provider_should_retry), ("retryable", "http", True))
                self.assertEqual(decide_retry(
                    result, RetryPolicyV2(3, 1, 10), slot_id=f"pre-{status}",
                    attempt=1, now=now).disposition, "retry")

    def test_post_dispatch_timeout_and_restart_are_unknown(self):
        for code in ("HOST_WEB_DEADLINE", "ACQ_RUNNER_RESTART_OUTCOME_UNKNOWN"):
            with self.subTest(code=code):
                result = self.normalize(self.build(
                    state="possibly_dispatched", terminal_status="unknown", failure_code=code,
                    with_result=False, with_proof=False))
                self.assertEqual((result.status.value, result.submission.value),
                                 ("unknown", "possibly_submitted"))
                self.assertEqual(decide_retry(
                    result, RetryPolicyV2(3, 1, 10), slot_id="s", attempt=1,
                    now=__import__("datetime").datetime.fromisoformat("2026-11-06T00:00:00+00:00")).disposition,
                    "unknown")

    def test_post_dispatch_connection_reset_is_unknown_and_requires_reconciliation(self):
        expected = {
            "invocation_started": ("submitted", "possibly_submitted"),
            "possibly_dispatched": ("streaming", "possibly_submitted"),
        }
        now = __import__("datetime").datetime.fromisoformat("2026-11-06T00:00:00+00:00")
        replay = ReplayContractV1(
            ReplayEffect.RECONCILE_BEFORE_REPLAY, (Phase.NOT_STARTED,),
            "scope/claude-host-reset", "owner/claude-host-reconciliation")
        self.assertEqual(replay.effect, ReplayEffect.RECONCILE_BEFORE_REPLAY)
        for state, (phase, submission) in expected.items():
            with self.subTest(state=state):
                result = self.normalize(self.build(
                    state=state, terminal_status="unknown",
                    failure_code="CLAUDE_HOST_CONNECTION_RESET", with_result=False,
                    with_proof=False))
                self.assertEqual(
                    (result.phase.value, result.submission.value,
                     result.terminal_proof.value, result.status.value,
                     result.failure_kind.value, result.code,
                     result.provider_should_retry, result.safe_retry_candidate),
                    (phase, submission, "absent", "unknown", "connection_reset",
                     "CLAUDE_HOST_CONNECTION_RESET", False, False))
                decision = decide_retry(
                    result, RetryPolicyV2(3, 1, 10), slot_id=state,
                    attempt=1, now=now)
                self.assertEqual(
                    (decision.disposition, decision.reason),
                    ("unknown", "PROVIDER_OUTCOME_UNKNOWN"))
                self.assertNotIn(result.phase, replay.automatic_phases)

    def test_fabricated_terminal_and_partial_late_mismatch_remain_unknown(self):
        fabricated = self.normalize(self.build(with_proof=False))
        self.assertEqual((fabricated.status.value, fabricated.terminal_proof.value),
                         ("unknown", "absent"))
        for code in ("CLAUDE_HOST_PARTIAL_RESULT", "CLAUDE_HOST_TRUNCATED_RESULT",
                     "CLAUDE_HOST_LATE_RESULT", "CLAUDE_HOST_IDENTITY_MISMATCH"):
            with self.subTest(code=code):
                result = self.normalize(self.build(
                    state="possibly_dispatched", terminal_status="unknown", failure_code=code,
                    with_result=False, with_proof=False))
                self.assertEqual(result.status.value, "unknown")
                self.assertFalse(result.safe_retry_candidate)

    def test_post_dispatch_permanent_code_is_unknown_without_verified_terminal(self):
        result = self.normalize(self.build(
            state="possibly_dispatched", terminal_status="unknown",
            failure_code="CLAUDE_HOST_AUTH_FAILURE", with_result=False, with_proof=False))
        self.assertEqual((result.status.value, result.failure_kind.value), ("unknown", "unknown"))

    def test_verified_terminal_permanent_failure_is_failed(self):
        result = self.normalize(self.build(
            terminal_status="failed", failure_code="CLAUDE_HOST_AUTH_FAILURE",
            with_result=False, with_proof=True))
        self.assertEqual((result.status.value, result.failure_kind.value,
                          result.terminal_proof.value), ("failed", "auth", "verified"))

    def test_identity_journal_and_proof_semantic_bindings_are_enforced(self):
        cases = ("identity", "journal", "proof")
        for case in cases:
            with self.subTest(case=case):
                evidence = self.build()
                if case == "identity":
                    path = self.root / evidence["host_profile_ref"]["path"]
                    value = json.loads(path.read_text()); value["dispatch_id"] = "other"
                    evidence["host_profile_ref"] = self.write("host_profile.json", value)
                elif case == "journal":
                    path = self.root / evidence["dispatch_journal_ref"]["path"]
                    value = json.loads(path.read_text()); value["operation_id"] = "other"
                    evidence["dispatch_journal_ref"] = self.write("journal.json", value)
                else:
                    path = self.root / evidence["terminal_proof_ref"]["path"]
                    value = json.loads(path.read_text()); value["result_sha256"] = "f" * 64
                    evidence["terminal_proof_ref"] = self.write("proof.json", value)
                with self.assertRaisesRegex(ClaudeHostAdapterError, "BINDING"):
                    self.normalize(evidence)

    def test_journal_event_identity_and_hash_chain_are_original_authority(self):
        evidence = self.build()
        path = self.root / evidence["dispatch_journal_ref"]["path"]
        journal = json.loads(path.read_text())
        journal["events"][2]["operation_id"] = "forged/op"
        journal["events"][2]["event_sha256"] = event_hash(journal["events"][2])
        evidence["dispatch_journal_ref"] = self.write("journal.json", journal)
        with self.assertRaisesRegex(ClaudeHostAdapterError, "JOURNAL_CHAIN"):
            self.normalize(evidence)

    def test_empty_oversize_and_insecure_ancestor_evidence_rejected(self):
        evidence = self.build()
        proof = self.root / evidence["terminal_proof_ref"]["path"]
        proof.write_bytes(b""); os.chmod(proof, 0o600)
        evidence["terminal_proof_ref"]["sha256"] = hashlib.sha256(b"").hexdigest()
        with self.assertRaisesRegex(ClaudeHostAdapterError, "EVIDENCE_SIZE"):
            self.normalize(evidence)

        evidence = self.build()
        result = self.root / evidence["result_ref"]["path"]
        result.write_bytes(b"x" * (MAX_ARTIFACT_BYTES + 1)); os.chmod(result, 0o600)
        evidence["result_ref"]["sha256"] = hashlib.sha256(result.read_bytes()).hexdigest()
        evidence["result_sha256"] = evidence["result_ref"]["sha256"]
        with self.assertRaisesRegex(ClaudeHostAdapterError, "EVIDENCE_SIZE"):
            self.normalize(evidence)

        evidence = self.build()
        result = self.root / evidence["result_ref"]["path"]
        result.write_bytes(b"x" * (MAX_ARTIFACT_BYTES - 1)); os.chmod(result, 0o600)
        evidence["result_ref"]["sha256"] = hashlib.sha256(result.read_bytes()).hexdigest()
        evidence["result_sha256"] = evidence["result_ref"]["sha256"]
        with self.assertRaisesRegex(ClaudeHostAdapterError, "AGGREGATE_SIZE"):
            self.normalize(evidence)

        evidence = self.build(); os.chmod(self.root / "private", 0o755)
        with self.assertRaisesRegex(ClaudeHostAdapterError, "EVIDENCE_PRIVACY"):
            self.normalize(evidence)

    def test_descriptor_replacement_reads_original_open_inode_without_reopen(self):
        evidence = self.build()
        target = self.root / evidence["host_session_ref"]["path"]

        class ReplacingResolver(WorkspaceEvidenceResolver):
            swapped = False
            def _after_open(inner_self, path, descriptor):
                if path == target and not inner_self.swapped:
                    inner_self.swapped = True
                    moved = path.with_suffix(".moved")
                    path.rename(moved)
                    path.write_bytes(b'{"forged":true}')
                    os.chmod(path, 0o600)

        result = normalize_invocation(evidence, file_resolver=ReplacingResolver(self.root))
        self.assertEqual(result.status.value, "succeeded")

    def test_transient_ancestor_swap_uses_held_directory_descriptor(self):
        evidence = self.build()
        expected = evidence["host_session_ref"]["sha256"]
        private = self.root / "private"
        moved = self.root / "private.sealed"

        class SwappingResolver(WorkspaceEvidenceResolver):
            swapped = False
            def _after_open_directory(inner_self, path, descriptor):
                if path == private and not inner_self.swapped:
                    inner_self.swapped = True
                    private.rename(moved)
                    private.mkdir(mode=0o700)
                    forged = private / "host_session.json"
                    forged.write_bytes(b'{"forged":true}')
                    os.chmod(forged, 0o600)

        snapshot = SwappingResolver(self.root).read("private/host_session.json")
        self.assertEqual(snapshot.sha256, expected)

    def test_workspace_root_symlink_is_rejected_before_resolution(self):
        with tempfile.TemporaryDirectory() as parent_name:
            parent = Path(parent_name)
            os.chmod(parent, 0o700)
            real = parent / "real"
            real.mkdir(mode=0o700)
            link = parent / "link"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(ClaudeHostAdapterError, "PATH|PRIVACY|OPEN"):
                WorkspaceEvidenceResolver(link)

    def test_symlink_and_result_drift_are_rejected(self):
        evidence = self.build()
        path = self.root / evidence["host_profile_ref"]["path"]
        moved = path.with_suffix(".target"); path.rename(moved); path.symlink_to(moved)
        with self.assertRaisesRegex(ClaudeHostAdapterError, "PRIVACY|PATH"):
            self.normalize(evidence)
        path.unlink(); moved.rename(path); os.chmod(path, 0o600)
        evidence = self.build()
        path = self.root / evidence["result_ref"]["path"]
        path.write_bytes(b"drift"); os.chmod(path, 0o600)
        with self.assertRaisesRegex(ClaudeHostAdapterError, "DRIFT"):
            self.normalize(evidence)

    def test_timestamp_deadline_and_captured_event_binding(self):
        cases = [
            dict(finished="2026-11-06T00:00:06+00:00"),
            dict(captured="2026-11-06T00:00:02+00:00"),
            dict(event_times=["2026-11-05T23:59:59+00:00", "2026-11-06T00:00:01+00:00",
                              "2026-11-06T00:00:02+00:00", "2026-11-06T00:00:03+00:00"]),
        ]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaisesRegex(
                    ClaudeHostAdapterError, "TIME|DEADLINE"):
                self.normalize(self.build(**changes))
        evidence = self.build(); evidence["deadline_at"] = "naive"
        with self.assertRaisesRegex(ClaudeHostAdapterError, "DEADLINE"):
            self.normalize(evidence)

    def test_terminal_proof_authenticates_every_mutable_invocation_field(self):
        mutations = {
            "failure_code": "CLAUDE_HOST_AUTH_FAILURE",
            "started_at": "2026-11-05T23:59:59+00:00",
            "captured_at": "2026-11-06T00:00:03.500000+00:00",
            "finished_at": "2026-11-06T00:00:04.500000+00:00",
            "deadline_at": "2026-11-06T00:00:05.500000+00:00",
        }
        for field, changed in mutations.items():
            with self.subTest(field=field):
                evidence = self.build()
                evidence[field] = changed
                with self.assertRaisesRegex(ClaudeHostAdapterError, "BINDING"):
                    self.normalize(evidence)

    def test_terminal_failure_event_hash_is_canonical_failure_record(self):
        evidence = self.build(terminal_status="failed", failure_code="CLAUDE_HOST_AUTH_FAILURE",
                              with_result=False)
        journal_path = self.root / evidence["dispatch_journal_ref"]["path"]
        journal = json.loads(journal_path.read_text())
        journal["events"][-1]["evidence_sha256"] = "f" * 64
        journal["events"][-1]["event_sha256"] = event_hash(journal["events"][-1])
        evidence["dispatch_journal_ref"] = self.write("journal.json", journal)
        proof_path = self.root / evidence["terminal_proof_ref"]["path"]
        proof = json.loads(proof_path.read_text())
        proof["journal_sha256"] = evidence["dispatch_journal_ref"]["sha256"]
        evidence["terminal_proof_ref"] = self.write("proof.json", proof)
        with self.assertRaisesRegex(ClaudeHostAdapterError, "TERMINAL_EVIDENCE"):
            self.normalize(evidence)

    def test_failure_grammar_http_bounds_and_unknown_codes_are_closed(self):
        evidence = self.build(state="definitely_not_dispatched", terminal_status="failed",
                              failure_code="SOURCE_HTTP_600", with_result=False, with_proof=False)
        with self.assertRaisesRegex(ClaudeHostAdapterError, "HTTP_STATUS"):
            self.normalize(evidence)
        evidence = self.build(); evidence["failure_code"] = "bad prose"
        with self.assertRaisesRegex(ClaudeHostAdapterError, "FAILURE_CODE"):
            self.normalize(evidence)
        evidence = self.build(); evidence["failure_code"] = "UNRECOGNIZED_UPPERCASE_CODE"
        with self.assertRaisesRegex(ClaudeHostAdapterError, "CLAUDE_HOST_FAILURE_CODE_UNKNOWN"):
            self.normalize(evidence)

    def test_duplicate_deep_extra_and_factory_bypass_are_rejected(self):
        with self.assertRaisesRegex(ClaudeHostAdapterError, "JSON_INVALID"):
            normalize_invocation('{"schema_version":"x","schema_version":"y"}')
        evidence = self.build(); evidence["raw_input"] = "forbidden"
        with self.assertRaisesRegex(ClaudeHostAdapterError, "EVIDENCE_FIELDS"):
            self.normalize(evidence)
        deep = self.build(); cursor = {}; deep["extra"] = cursor
        for _ in range(20): cursor["x"] = {}; cursor = cursor["x"]
        with self.assertRaisesRegex(ClaudeHostAdapterError, "JSON_DEPTH"):
            self.normalize(deep)
        with self.assertRaises(TypeError):
            normalize_invocation(self.build(), file_resolver=self.resolver,
                                 result_factory=lambda value: value)


if __name__ == "__main__":
    unittest.main()
