from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import copy
import json
import sqlite3
from pathlib import Path
import tempfile
import unittest

from tuning.evals.information_fetch.live_e2e.email_sync import (
    AcceptanceArtifactStore,
    AcceptanceOutbox,
    EmailSyncError,
    GmailRuntimeAttestation,
    build_gmail_claim,
    build_host_summary,
    build_summary,
    build_verified_combined_summary,
    claim_host_delivery,
    host_notification_key,
    host_payload_digest,
    mark_host_delivery_unknown,
    message_digest,
    notification_key,
    reconcile_codex_host_delivery,
    reconcile_readback,
    send_once,
    verify_codex_business_receipt,
    verify_readback,
)


class FakeOutbox:
    def __init__(self):
        self.rows = {}
        self.payloads = {}
        self.claims = 0

    def get(self, key):
        row = self.rows.get(key)
        return dict(row) if row else None

    def prepare(self, key, message, *, recipient, profile_email,
                payload_digest=None):
        assert recipient == message["to"]
        assert "@" in profile_email
        digest = payload_digest or message_digest(message)
        if key in self.rows:
            if self.rows[key]["digest"] != digest:
                raise ValueError("IMMUTABLE_PAYLOAD_CONFLICT")
        else:
            self.payloads[key] = dict(message)
            self.rows[key] = {"key": key, "status": "prepared", "digest": digest,
                              "attempt_id": None, "message_id": None,
                              "verified_digest": None}
        return self.get(key)

    def claim(self, key, attempt_id):
        row = self.rows[key]
        if row["status"] != "prepared":
            raise ValueError("OUTBOX_NOT_SENDABLE")
        row.update(status="sending", attempt_id=attempt_id)
        self.claims += 1
        return dict(self.payloads[key])

    def accepted(self, key, attempt_id, message_id):
        row = self.rows[key]
        if row["status"] != "sending" or row["attempt_id"] != attempt_id:
            raise ValueError("ATTEMPT_MISMATCH")
        row.update(status="accepted", message_id=message_id)
        return self.get(key)

    def unknown(self, key, attempt_id):
        row = self.rows[key]
        if row["status"] != "sending" or row["attempt_id"] != attempt_id:
            raise ValueError("UNKNOWN_TRANSITION_REJECTED")
        row["status"] = "unknown"
        return self.get(key)

    def reconcile_accepted(self, key, *, message_id, verified_digest):
        row = self.rows[key]
        if row["status"] not in {"sending", "unknown", "accepted"}:
            raise ValueError("RECONCILIATION_REJECTED")
        if row["digest"] != verified_digest:
            raise ValueError("READBACK_DIGEST_MISMATCH")
        row.update(status="accepted", message_id=message_id,
                   verified_digest=verified_digest)
        return self.get(key)


class FakeGmail:
    def __init__(self, *, ready=True, outcome="deadbeef"):
        self.ready = ready
        self.outcome = outcome
        self.calls = []

    def oauth_ready(self):
        return self.ready

    def send(self, message):
        self.calls.append(dict(message))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def result(status="passed", *, provider="codex"):
    return {
        "execution_status": status,
        "scheduled_at": "2026-11-05T10:00:00Z",
        "actual_timing": "started 10:00:03Z; ended 10:00:18Z",
        "job_id": f"{provider}-job-1",
        "session_id": f"{provider}-session-1",
        "verified_outputs": ["provider live response verified"],
        "coverage": "one future scheduled live case as of 2026-11-05",
        "failure_codes": [] if status == "passed" else ["PROVIDER_TIMEOUT"],
        "recovery": "no rollback needed" if status == "passed" else "candidate held",
        "evidence_refs": [f"acceptance:{provider}:run-1"],
    }


def summary(codex_status="passed", claude_status="passed", sender="codex_supervisor"):
    return build_summary(
        change_id="providers-live-1", scope="Live provider acquisition acceptance",
        sender=sender, codex=result(codex_status, provider="codex"),
        claude=result(claude_status, provider="claude"),
    )


class EmailSyncTests(unittest.TestCase):
    def test_success_claims_before_one_send_and_records_receipt(self):
        outbox, gmail = FakeOutbox(), FakeGmail()
        report = summary()
        row = send_once(summary=report, recipient="owner@example.com",
                        profile_email="owner@example.com", attempt_id="attempt-001",
                        outbox=outbox, gmail=gmail)
        self.assertEqual(row["status"], "accepted")
        self.assertEqual(row["message_id"], "deadbeef")
        self.assertEqual(outbox.claims, 1)
        self.assertEqual(len(gmail.calls), 1)
        self.assertTrue(report.subject.startswith("[CODEX] Runtime acceptance | passed"))
        self.assertIn("Codex:", report.body)
        self.assertIn("Claude:", report.body)

    def test_failure_verdict_is_preserved_and_claude_sender_is_not_codex_branded(self):
        report = summary(codex_status="failed", sender="claude_supervisor")
        self.assertEqual(report.execution_status, "failed")
        self.assertFalse(report.subject.startswith("[CODEX]"))
        self.assertIn("Execution verdict: failed", report.body)
        self.assertIn("PROVIDER_TIMEOUT", report.body)
        with self.assertRaisesRegex(EmailSyncError, "CODEX_RESULT_INVALID"):
            bad = result()
            bad["raw_provider_response"] = "secret material"
            build_summary(change_id="providers-live-1", scope="scope",
                          sender="codex_supervisor", codex=bad,
                          claude=result(provider="claude"))

    def test_unknown_is_fenced_until_exact_readback_reconciles(self):
        outbox = FakeOutbox()
        failing = FakeGmail(outcome=TimeoutError("provider details must be hidden"))
        report = summary()
        with self.assertRaisesRegex(EmailSyncError,
                                    "SEND_OUTCOME_UNKNOWN_RECONCILE_REQUIRED"):
            send_once(summary=report, recipient="owner@example.com",
                      profile_email="owner@example.com", attempt_id="attempt-001",
                      outbox=outbox, gmail=failing)
        key = notification_key(report.change_id)
        self.assertEqual(outbox.get(key)["status"], "unknown")

        second = FakeGmail()
        with self.assertRaisesRegex(EmailSyncError, "RECONCILIATION_REQUIRED"):
            send_once(summary=report, recipient="owner@example.com",
                      profile_email="owner@example.com", attempt_id="attempt-002",
                      outbox=outbox, gmail=second)
        self.assertEqual(second.calls, [])

        expected = report.message("owner@example.com")
        actual = {**expected, "message_id": "cafebabe"}
        row = reconcile_readback(summary=report, recipient="owner@example.com",
                                 outbox=outbox, actual=actual)
        self.assertEqual(row["status"], "accepted")
        self.assertEqual(row["verified_digest"], message_digest(expected))

    def test_duplicate_accepted_receipt_suppresses_send(self):
        outbox, first = FakeOutbox(), FakeGmail()
        report = summary()
        send_once(summary=report, recipient="owner@example.com",
                  profile_email="owner@example.com", attempt_id="attempt-001",
                  outbox=outbox, gmail=first)
        duplicate = FakeGmail(ready=False)
        row = send_once(summary=report, recipient="owner@example.com",
                        profile_email="owner@example.com", attempt_id="attempt-002",
                        outbox=outbox, gmail=duplicate)
        self.assertEqual(row["status"], "accepted")
        self.assertEqual(duplicate.calls, [])
        self.assertEqual(outbox.claims, 1)

    def test_accepted_fast_path_rejects_recipient_subject_and_body_conflicts(self):
        outbox, first = FakeOutbox(), FakeGmail()
        report = summary()
        send_once(summary=report, recipient="owner@example.com",
                  profile_email="owner@example.com", attempt_id="attempt-001",
                  outbox=outbox, gmail=first)
        cases = (
            (report, "other@example.com", "other@example.com"),
            (replace(report, subject=report.subject + " changed"),
             "owner@example.com", "owner@example.com"),
            (replace(report, body=report.body + " changed"),
             "owner@example.com", "owner@example.com"),
        )
        for changed, recipient, profile in cases:
            duplicate = FakeGmail(ready=False)
            with self.subTest(recipient=recipient, subject=changed.subject[-16:]), \
                    self.assertRaisesRegex(EmailSyncError, "OUTBOX_PAYLOAD_CONFLICT"):
                send_once(summary=changed, recipient=recipient,
                          profile_email=profile, attempt_id="attempt-002",
                          outbox=outbox, gmail=duplicate)
            self.assertEqual(duplicate.calls, [])
        self.assertEqual(outbox.claims, 1)

    def test_missing_oauth_readiness_never_prepares_or_sends(self):
        outbox, gmail = FakeOutbox(), FakeGmail(ready=False)
        with self.assertRaisesRegex(EmailSyncError, "OAUTH_NOT_READY"):
            send_once(summary=summary(), recipient="owner@example.com",
                      profile_email="owner@example.com", attempt_id="attempt-001",
                      outbox=outbox, gmail=gmail)
        self.assertEqual(outbox.rows, {})
        self.assertEqual(gmail.calls, [])

    def test_readback_requires_exact_recipient_subject_and_body(self):
        expected = summary().message("owner@example.com")
        actual = {**expected, "message_id": "deadbeef"}
        digest = verify_readback(expected, actual)
        self.assertEqual(digest, message_digest(expected))
        for field, value, code in (
            ("to", "other@example.com", "READBACK_RECIPIENT_MISMATCH"),
            ("subject", "changed", "READBACK_SUBJECT_MISMATCH"),
            ("body", "changed", "READBACK_BODY_MISMATCH"),
        ):
            changed = dict(actual)
            changed[field] = value
            with self.assertRaisesRegex(EmailSyncError, code):
                verify_readback(expected, changed)



class DurableAcceptanceOutboxTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[4]
        parent = self.root / ".job-runtime" / "tests"
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.temp = tempfile.TemporaryDirectory(dir=parent, prefix="email-sync-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "outbox.sqlite"
        self.outbox = AcceptanceOutbox(self.path, self.root)
        self.message = {"to": "owner@example.com", "subject": "[CODEX] synthetic",
                        "body": "sanitized body"}
        self.key = "runtime-acceptance:host:" + "a" * 64
        self.digest = "b" * 64

    def prepare(self):
        return self.outbox.prepare(
            self.key, self.message, recipient="owner@example.com",
            profile_email="sender@example.com", payload_digest=self.digest)

    def test_reopen_idempotency_conflict_and_permissions(self):
        first = self.prepare()
        reopened = AcceptanceOutbox(self.path, self.root)
        second = reopened.prepare(
            self.key, self.message, recipient="owner@example.com",
            profile_email="sender@example.com", payload_digest=self.digest)
        self.assertEqual(first["digest"], second["digest"])
        with self.assertRaisesRegex(EmailSyncError, "OUTBOX_PAYLOAD_CONFLICT"):
            reopened.prepare(
                self.key, {**self.message, "body": "changed"},
                recipient="owner@example.com", profile_email="sender@example.com",
                payload_digest="c" * 64)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_only_one_concurrent_claim_and_unknown_never_resends(self):
        self.prepare()
        def claim(index):
            try:
                AcceptanceOutbox(self.path, self.root).claim(
                    self.key, f"attempt-{index:03d}")
                return index
            except EmailSyncError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            winners = [value for value in pool.map(claim, range(4))
                       if value is not None]
        self.assertEqual(len(winners), 1)
        winner = f"attempt-{winners[0]:03d}"
        self.outbox.unknown(self.key, winner)
        with self.assertRaisesRegex(EmailSyncError, "OUTBOX_NOT_SENDABLE"):
            AcceptanceOutbox(self.path, self.root).claim(self.key, "attempt-next")
        row = self.outbox.reconcile_accepted(
            self.key, message_id="abcdef1234567890",
            verified_digest=self.digest)
        self.assertEqual(row["status"], "accepted")
        self.assertEqual(row["verified_digest"], self.digest)

    def test_committed_acceptance_then_exception_is_reopened_safely(self):
        class CommitThenRaise(AcceptanceOutbox):
            def accepted(inner, key, attempt_id, message_id):
                super().accepted(key, attempt_id, message_id)
                raise OSError("synthetic post-commit failure")
        outbox = CommitThenRaise(self.path, self.root)
        gmail = FakeGmail()
        row = send_once(
            summary=summary(), recipient="owner@example.com",
            profile_email="owner@example.com", attempt_id="attempt-001",
            outbox=outbox, gmail=gmail)
        self.assertEqual(row["status"], "accepted")
        self.assertEqual(row["message_id"], "deadbeef")
        self.assertEqual(len(gmail.calls), 1)


class ResultValidationTests(unittest.TestCase):
    def test_passed_requires_outputs_evidence_and_no_failure_codes(self):
        for field, value in (("verified_outputs", []), ("evidence_refs", []),
                             ("failure_codes", ["PROVIDER_TIMEOUT"])):
            bad = result(provider="codex")
            bad[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                    EmailSyncError, "CODEX_RESULT_INVALID"):
                build_host_summary(
                    host="codex", run_id="run-001", candidate_id="candidate-001",
                    scope="scope", sender="codex_supervisor", mode="scheduled",
                    request_id="request-001", slot_id="slot-001", result=bad)

def host_summary(host="codex", *, run_id="run-001", candidate_id="candidate-001",
                 scope="Bounded live acquisition acceptance", status="passed"):
    return build_host_summary(
        host=host, run_id=run_id, candidate_id=candidate_id, scope=scope,
        sender="codex_supervisor", mode="scheduled", request_id=f"request-{host}",
        slot_id=f"slot-{host}", result=result(status, provider=host),
    )


def runtime_attestation(host="codex", *, attempt_id=None):
    return GmailRuntimeAttestation(
        job_id=f"job.{host}", slot_id=f"scheduler-slot.{host}",
        attempt_id=attempt_id or f"attempt-{host}",
        service_source_sha256="a" * 64,
        service_generation_sha256="b" * 64,
        adapter_source_sha256=("c" if host == "codex" else "d") * 64,
    )


def operational_receipt(report, attestation, recipient="owner@example.com", *,
                        profile_email="sender@example.com", namespaced=True,
                        extra_tools=()):
    claim = build_gmail_claim(
        report, recipient, profile_email=profile_email,
        runtime_attestation=attestation)
    evidence = {
        "message_id": "abcdef1234567890",
        "email_thread_id": "1234567890abcdef",
        "send_event_id": "send-event-0001",
        "read_event_id": "read-event-0001",
        "recipient_sha256": claim["recipient_sha256"],
        "subject_sha256": claim["subject_sha256"],
        "body_sha256": claim["body_sha256"],
        "delivery_payload_sha256": claim["delivery_payload_sha256"],
        "sender_identity_sha256": claim["sender_identity_sha256"],
        "profile_identity_sha256": claim["profile_identity_sha256"],
        "raw_readback_sha256": "e" * 64,
        "readback_verified_at": "2026-11-05T08:09:10+00:00",
    }
    prefix = "mcp__codex_apps__" if namespaced else ""
    names = sorted([prefix + "gmail_get_profile", prefix + "gmail_read_email",
                    prefix + "gmail_send_email"])
    final = {"status": "sent"}
    return {
        "thread_id": "codex-thread-001",
        "tool_names": sorted(["command_execution", *names, *extra_tools]),
        "gmail_tool_names": names,
        "final": final,
        "final_sha256": hashlib.sha256(
            json.dumps(final, sort_keys=True).encode()).hexdigest(),
        "final_evidence_trust": "trusted_operational_host_evidence",
        "gmail_operational_evidence": evidence,
        "gmail_claim": claim,
    }


def full_business_receipt(report, attestation, *, namespaced=True):
    """Final run_business success envelope with synthetic, sanitized values."""
    receipt = operational_receipt(report, attestation, namespaced=namespaced)
    return {
        "started_at": "2026-11-05T08:09:00+00:00",
        "requested_model": "gpt-synthetic",
        "observed_model": "gpt-synthetic",
        "automatic_retry": False,
        "fallback_used": False,
        "dispatch_phase": "exposed",
        "ended_at": "2026-11-05T08:09:20+00:00",
        "exit_code": 0,
        "phase": "business",
        "approval_mode": "never",
        "writable_roots": [".niulai-state/daily"],
        "run_directory": ".job-runtime/runs/attempt-synthetic",
        "usage": {"input_tokens": 10, "cached_input_tokens": 2,
                  "output_tokens": 5},
        "turn_completed": True,
        "tool_failures": [],
        "model_final_evidence_trust": "untrusted_model_output",
        **receipt,
    }


def persist_host_delivery(store, host, *, change_id="providers-live-1",
                          scope="Live provider acquisition acceptance"):
    host_result = result(provider=host)
    report = build_host_summary(
        host=host, run_id="run-001", candidate_id="candidate-001",
        scope="Bounded live acquisition acceptance", sender="codex_supervisor",
        mode="scheduled", request_id=f"request-{host}", slot_id=f"slot-{host}",
        result=host_result)
    attestation = runtime_attestation(host)
    receipt = full_business_receipt(report, attestation,
                                    namespaced=(host == "codex"))
    delivery_ref = store.record_verified_delivery(
        change_id=change_id, scope=scope, result=host_result, summary=report,
        recipient="owner@example.com", profile_email="sender@example.com",
        runtime_attestation=attestation, receipt=receipt)
    return {"delivery_ref": delivery_ref, "result": host_result,
            "summary": report, "attestation": attestation, "receipt": receipt}


class HostEmailBridgeTests(unittest.TestCase):
    recipient = "owner@example.com"
    sender = "sender@example.com"

    def claim(self, outbox, report, attestation):
        return claim_host_delivery(
            summary=report, recipient=self.recipient,
            profile_email=self.sender, attempt_id=attestation.attempt_id,
            runtime_attestation=attestation, outbox=outbox)

    def verify(self, report, attestation, receipt):
        return verify_codex_business_receipt(
            summary=report, recipient=self.recipient,
            profile_email=self.sender, runtime_attestation=attestation,
            receipt=receipt)

    def test_claim_separates_runtime_attestation_from_notification_identity(self):
        report = host_summary(run_id="acceptance-run", candidate_id="acceptance-candidate")
        attestation = runtime_attestation()
        claim = build_gmail_claim(
            report, self.recipient, profile_email=self.sender,
            runtime_attestation=attestation)
        self.assertEqual(set(claim), {
            "schema_version", "job_id", "slot_id", "attempt_id", "host", "run",
            "candidate", "mode", "delivery_payload_sha256", "recipient_sha256",
            "subject_sha256", "sender_identity_sha256", "profile_identity_sha256",
            "body_sha256", "payload_sha256",
        })
        self.assertEqual((claim["job_id"], claim["slot_id"], claim["attempt_id"]),
                         (attestation.job_id, attestation.slot_id,
                          attestation.attempt_id))
        self.assertEqual(
            (claim["host"], claim["run"], claim["candidate"]),
            (attestation.service_source_sha256,
             attestation.service_generation_sha256,
             attestation.adapter_source_sha256))
        self.assertNotEqual(report.host, claim["host"])
        self.assertNotEqual(report.run_id, claim["run"])
        self.assertNotEqual(report.candidate_id, claim["candidate"])
        self.assertEqual(claim["sender_identity_sha256"],
                         hashlib.sha256(self.sender.encode()).hexdigest())
        self.assertEqual(claim["profile_identity_sha256"],
                         claim["sender_identity_sha256"])
        payload = {"sender": self.sender, "recipient": self.recipient,
                   "subject": report.subject, "body": report.body}
        self.assertEqual(claim["delivery_payload_sha256"], hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode()).hexdigest())
        bound = {k: v for k, v in claim.items() if k != "payload_sha256"}
        self.assertEqual(claim["payload_sha256"], hashlib.sha256(
            json.dumps(bound, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode()).hexdigest())
        self.assertNotIn("raw_readback_sha256", claim)
        self.assertNotIn("raw_mime_sha256", claim)

    def test_per_host_notification_keys_are_distinct(self):
        outbox = FakeOutbox()
        codex, claude = host_summary("codex"), host_summary("claude")
        first = self.claim(outbox, codex, runtime_attestation("codex"))
        second = self.claim(outbox, claude, runtime_attestation("claude"))
        self.assertNotEqual(first["key"], second["key"])
        self.assertEqual(first["key"], host_notification_key(
            "codex", "run-001", "candidate-001"))
        self.assertNotEqual(first["gmail_claim"]["candidate"],
                            second["gmail_claim"]["candidate"])
        self.assertEqual(outbox.claims, 2)

    def test_same_notification_key_rejects_message_or_attestation_conflict(self):
        outbox = FakeOutbox()
        report, attestation = host_summary(), runtime_attestation()
        first = self.claim(outbox, report, attestation)
        self.assertEqual(first["payload_digest"], host_payload_digest(
            report.message(self.recipient), first["gmail_claim"]))
        with self.assertRaisesRegex(EmailSyncError, "OUTBOX_PAYLOAD_CONFLICT"):
            self.claim(outbox, host_summary(scope="Different sanitized scope"),
                       attestation)
        changed = runtime_attestation(attempt_id="attempt-codex-next")
        with self.assertRaisesRegex(EmailSyncError, "OUTBOX_PAYLOAD_CONFLICT"):
            self.claim(outbox, report, changed)
        self.assertEqual(outbox.claims, 1)

    def test_attempt_must_equal_scheduler_attempt_before_prepare(self):
        outbox = FakeOutbox()
        attestation = runtime_attestation()
        with self.assertRaisesRegex(EmailSyncError, "ATTEMPT_IDENTITY_MISMATCH"):
            claim_host_delivery(
                summary=host_summary(), recipient=self.recipient,
                profile_email=self.sender, attempt_id="different-attempt",
                runtime_attestation=attestation, outbox=outbox)
        self.assertEqual(outbox.rows, {})

    def test_unknown_fence_never_reclaims_or_resends(self):
        outbox = FakeOutbox()
        report, attestation = host_summary(), runtime_attestation()
        self.claim(outbox, report, attestation)
        mark_host_delivery_unknown(
            summary=report, attempt_id=attestation.attempt_id, outbox=outbox)
        with self.assertRaisesRegex(EmailSyncError, "RECONCILIATION_REQUIRED"):
            self.claim(outbox, report, attestation)
        self.assertEqual(outbox.claims, 1)

    def test_trusted_profile_bound_receipt_reconciles_exact_claim_once(self):
        outbox = FakeOutbox()
        report, attestation = host_summary(), runtime_attestation()
        prepared = self.claim(outbox, report, attestation)
        receipt = operational_receipt(report, attestation)
        result_row = reconcile_codex_host_delivery(
            summary=report, recipient=self.recipient, profile_email=self.sender,
            runtime_attestation=attestation, outbox=outbox, receipt=receipt)
        artifact = result_row["verification"]
        self.assertEqual(result_row["outbox"]["status"], "accepted")
        self.assertEqual(artifact["version"], 3)
        self.assertEqual(artifact["notification_host"], "codex")
        self.assertEqual(artifact["service_source_sha256"], "a" * 64)
        self.assertNotEqual(artifact["notification_candidate_id"],
                            artifact["adapter_source_sha256"])
        self.assertEqual(result_row["outbox"]["verified_digest"],
                         prepared["payload_digest"])
        duplicate = self.claim(outbox, report, attestation)
        self.assertEqual(duplicate["status"], "already_verified")
        self.assertEqual(outbox.claims, 1)

    def test_untrusted_partial_and_model_only_receipts_are_rejected(self):
        report, attestation = host_summary(), runtime_attestation()
        partial = operational_receipt(report, attestation)
        partial["gmail_operational_evidence"].pop("delivery_payload_sha256")
        for receipt in ({},
                        {**operational_receipt(report, attestation),
                         "final_evidence_trust": "untrusted_model_output"},
                        partial,
                        {"thread_id": "codex-thread-001", "tool_names": [],
                         "gmail_tool_names": [], "final": {"status": "sent"},
                         "final_sha256": "a" * 64,
                         "final_evidence_trust": "trusted_operational_host_evidence",
                         "gmail_operational_evidence": {}, "gmail_claim": {}}):
            with self.subTest(receipt=receipt):
                with self.assertRaises(EmailSyncError):
                    self.verify(report, attestation, receipt)

    def test_model_final_flags_are_not_delivery_authority(self):
        report, attestation = host_summary(), runtime_attestation()
        receipt = operational_receipt(report, attestation)
        self.assertEqual(receipt["final"], {"status": "sent"})
        artifact = self.verify(report, attestation, receipt)
        self.assertEqual(artifact["final_evidence_trust"],
                         "trusted_operational_host_evidence")

    def test_profile_tool_and_sender_provenance_are_mandatory(self):
        report, attestation = host_summary(), runtime_attestation()
        receipt = operational_receipt(report, attestation)
        profile_names = [name for name in receipt["gmail_tool_names"]
                         if name.endswith("gmail_get_profile")]
        self.assertEqual(len(profile_names), 1)

        missing = operational_receipt(report, attestation)
        missing["gmail_tool_names"] = [name for name in missing["gmail_tool_names"]
                                       if not name.endswith("gmail_get_profile")]
        missing["tool_names"] = [name for name in missing["tool_names"]
                                  if not name.endswith("gmail_get_profile")]
        with self.assertRaisesRegex(EmailSyncError,
                                    "CODEX_GMAIL_TOOL_NAMES_INVALID"):
            self.verify(report, attestation, missing)

        duplicate = operational_receipt(report, attestation)
        duplicate["gmail_tool_names"] = sorted(
            [*duplicate["gmail_tool_names"], "gmail_get_profile"])
        duplicate["tool_names"] = sorted(
            [*duplicate["tool_names"], "gmail_get_profile"])
        with self.assertRaisesRegex(EmailSyncError,
                                    "CODEX_GMAIL_TOOL_NAMES_INVALID"):
            self.verify(report, attestation, duplicate)

        mismatch = operational_receipt(report, attestation)
        mismatch["gmail_operational_evidence"]["profile_identity_sha256"] = "9" * 64
        with self.assertRaisesRegex(EmailSyncError,
                                    "GMAIL_PAYLOAD_DIGEST_MISMATCH"):
            self.verify(report, attestation, mismatch)

    def test_identity_event_digest_timestamp_and_tool_mismatches_fail(self):
        report, attestation = host_summary(), runtime_attestation()
        for field, value in (("thread_id", "bad"),
                             ("final_evidence_trust", "untrusted_model_output")):
            receipt = operational_receipt(report, attestation)
            receipt[field] = value
            with self.subTest(field=field), self.assertRaises(EmailSyncError):
                self.verify(report, attestation, receipt)
        for field, value in (("send_event_id", "same-event-001"),
                             ("read_event_id", "same-event-001"),
                             ("recipient_sha256", "9" * 64),
                             ("delivery_payload_sha256", "8" * 64),
                             ("sender_identity_sha256", "7" * 64),
                             ("raw_readback_sha256", "not-a-digest"),
                             ("readback_verified_at", "2026-11-05T08:09:10")):
            receipt = operational_receipt(report, attestation)
            if field in {"send_event_id", "read_event_id"}:
                receipt["gmail_operational_evidence"]["send_event_id"] = value
                receipt["gmail_operational_evidence"]["read_event_id"] = value
            else:
                receipt["gmail_operational_evidence"][field] = value
            with self.subTest(field=field), self.assertRaises(EmailSyncError):
                self.verify(report, attestation, receipt)

    def test_runtime_attestation_sender_and_claim_substitution_fail(self):
        report, attestation = host_summary(), runtime_attestation()
        receipt = operational_receipt(report, attestation)
        changed = runtime_attestation(attempt_id="attempt-codex-next")
        with self.assertRaisesRegex(EmailSyncError, "GMAIL_CLAIM_MISMATCH"):
            self.verify(report, changed, receipt)
        with self.assertRaisesRegex(EmailSyncError, "GMAIL_CLAIM_MISMATCH"):
            verify_codex_business_receipt(
                summary=report, recipient=self.recipient,
                profile_email="different-sender@example.com",
                runtime_attestation=attestation, receipt=receipt)
        receipt["gmail_claim"] = dict(receipt["gmail_claim"])
        receipt["gmail_claim"]["raw_readback_sha256"] = "e" * 64
        with self.assertRaisesRegex(EmailSyncError, "GMAIL_CLAIM_MISMATCH"):
            self.verify(report, attestation, receipt)

    def test_gmail_subset_and_closed_overall_tool_allowlist(self):
        report, attestation = host_summary(), runtime_attestation()
        allowed = ("mcp__codex_apps__sites_get_site", "metadata_search")
        artifact = self.verify(
            report, attestation,
            operational_receipt(report, attestation, extra_tools=allowed))
        for name in allowed:
            self.assertIn(name, artifact["tool_names"])

        conflicting = operational_receipt(report, attestation)
        conflicting["gmail_tool_names"] = sorted(
            ["gmail_get_profile", "gmail_send_email", "gmail_read_email"])
        with self.assertRaisesRegex(EmailSyncError, "CODEX_TOOL_NAMES_INVALID"):
            self.verify(report, attestation, conflicting)

        near_match = operational_receipt(report, attestation)
        near_match["gmail_tool_names"][-1] = "mcp__codex_apps__gmail_send_email_v2"
        near_match["gmail_tool_names"].sort()
        with self.assertRaisesRegex(EmailSyncError,
                                    "CODEX_GMAIL_TOOL_NAMES_INVALID"):
            self.verify(report, attestation, near_match)

        extra = operational_receipt(report, attestation)
        extra["tool_names"].append("mcp__codex_apps__sites_list_sites")
        extra["tool_names"].sort()
        with self.assertRaisesRegex(EmailSyncError, "CODEX_TOOL_NAMES_INVALID"):
            self.verify(report, attestation, extra)

    def test_secret_and_private_path_canaries_fail_without_output(self):
        for scope in ("bearer SYNTHETIC_CANARY", "/Users/private/result"):
            with self.subTest(scope=scope), self.assertRaises(EmailSyncError):
                host_summary(scope=scope)
        report, attestation = host_summary(), runtime_attestation()
        receipt = operational_receipt(report, attestation)
        receipt["gmail_operational_evidence"]["access_token"] = "SYNTHETIC_CANARY"
        with self.assertRaisesRegex(EmailSyncError,
                                    "GMAIL_OPERATIONAL_EVIDENCE_INVALID"):
            self.verify(report, attestation, receipt)

    def artifact_store(self):
        root = Path(__file__).resolve().parents[4]
        parent = root / ".job-runtime" / "tests"
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = tempfile.TemporaryDirectory(dir=parent, prefix="email-artifacts-")
        self.addCleanup(temp.cleanup)
        return AcceptanceArtifactStore(Path(temp.name) / "artifacts.sqlite", root)

    def test_combined_summary_accepts_only_nominal_store_issued_refs(self):
        store = self.artifact_store()
        codex = persist_host_delivery(store, "codex")
        claude = persist_host_delivery(store, "claude")
        combined = build_verified_combined_summary(
            change_id="providers-live-1",
            scope="Live provider acquisition acceptance",
            sender="codex_supervisor", store=store,
            codex_delivery_ref=codex["delivery_ref"],
            claude_delivery_ref=claude["delivery_ref"])
        self.assertEqual(combined.email_status, "verified")
        self.assertEqual(combined.delivery_refs,
                         (codex["delivery_ref"].ref, claude["delivery_ref"].ref))
        self.assertRegex(combined.verification_sha256, r"^[a-f0-9]{64}$")

        with self.assertRaisesRegex(EmailSyncError, "COMBINED_STORE_INVALID"):
            build_verified_combined_summary(
                change_id="providers-live-1",
                scope="Live provider acquisition acceptance",
                sender="codex_supervisor", store={},
                codex_delivery_ref=codex["delivery_ref"],
                claude_delivery_ref=claude["delivery_ref"])
        with self.assertRaisesRegex(EmailSyncError,
                                    "COMBINED_ARTIFACT_REF_INVALID"):
            build_verified_combined_summary(
                change_id="providers-live-1",
                scope="Live provider acquisition acceptance",
                sender="codex_supervisor", store=store,
                codex_delivery_ref=object(),
                claude_delivery_ref=claude["delivery_ref"])

    def test_combined_rejects_fresh_wrapper_and_cross_change_replay(self):
        store = self.artifact_store()
        codex = persist_host_delivery(store, "codex")
        claude = persist_host_delivery(store, "claude")
        root = Path(__file__).resolve().parents[4]
        fresh = AcceptanceArtifactStore(store.path, root)
        with self.assertRaisesRegex(EmailSyncError,
                                    "COMBINED_ARTIFACT_REF_INVALID"):
            build_verified_combined_summary(
                change_id="providers-live-1",
                scope="Live provider acquisition acceptance",
                sender="codex_supervisor", store=fresh,
                codex_delivery_ref=codex["delivery_ref"],
                claude_delivery_ref=claude["delivery_ref"])
        for change_id, scope in (
                ("different-change", "Live provider acquisition acceptance"),
                ("providers-live-1", "different scope")):
            with self.subTest(change_id=change_id, scope=scope), \
                    self.assertRaisesRegex(EmailSyncError,
                                            "COMBINED_DELIVERY_SCOPE_MISMATCH"):
                build_verified_combined_summary(
                    change_id=change_id, scope=scope,
                    sender="codex_supervisor", store=store,
                    codex_delivery_ref=codex["delivery_ref"],
                    claude_delivery_ref=claude["delivery_ref"])

    def test_record_path_is_immutable_and_reopens_exact_store_bytes(self):
        store = self.artifact_store()
        codex = persist_host_delivery(store, "codex")
        claude = persist_host_delivery(store, "claude")
        changed_result = result(provider="codex")
        changed_result["actual_timing"] = "different timing"
        changed_summary = build_host_summary(
            host="codex", run_id="run-001", candidate_id="candidate-001",
            scope="Bounded live acquisition acceptance", sender="codex_supervisor",
            mode="scheduled", request_id="request-codex", slot_id="slot-codex",
            result=changed_result)
        changed_receipt = operational_receipt(
            changed_summary, codex["attestation"])
        with self.assertRaisesRegex(EmailSyncError, "ACCEPTANCE_ARTIFACT_CONFLICT"):
            store.record_verified_delivery(
                change_id="providers-live-1",
                scope="Live provider acquisition acceptance", result=changed_result,
                summary=changed_summary, recipient=self.recipient,
                profile_email=self.sender,
                runtime_attestation=codex["attestation"], receipt=changed_receipt)

        with sqlite3.connect(store.path) as db:
            row = db.execute("SELECT payload FROM records WHERE ref=?",
                             (claude["delivery_ref"].ref,)).fetchone()
            payload = json.loads(row[0])
            payload["change_id"] = "forged-change"
            db.execute("UPDATE records SET payload=? WHERE ref=?",
                       (json.dumps(payload, sort_keys=True, separators=(",", ":")),
                        claude["delivery_ref"].ref))
        with self.assertRaisesRegex(EmailSyncError, "ACCEPTANCE_ARTIFACT_CORRUPT"):
            build_verified_combined_summary(
                change_id="providers-live-1",
                scope="Live provider acquisition acceptance",
                sender="codex_supervisor", store=store,
                codex_delivery_ref=codex["delivery_ref"],
                claude_delivery_ref=claude["delivery_ref"])

    def test_record_rebuilds_summary_and_rejects_forged_execution_status(self):
        store = self.artifact_store()
        failed_result = result("failed", provider="codex")
        canonical = build_host_summary(
            host="codex", run_id="run-001", candidate_id="candidate-001",
            scope="Bounded live acquisition acceptance", sender="codex_supervisor",
            mode="scheduled", request_id="request-codex", slot_id="slot-codex",
            result=failed_result)
        forged = replace(canonical, execution_status="passed")
        attestation = runtime_attestation("codex")
        receipt = full_business_receipt(forged, attestation)
        with self.assertRaisesRegex(EmailSyncError, "HOST_SUMMARY_MISMATCH"):
            store.record_verified_delivery(
                change_id="providers-live-1",
                scope="Live provider acquisition acceptance", result=failed_result,
                summary=forged, recipient=self.recipient,
                profile_email=self.sender, runtime_attestation=attestation,
                receipt=receipt)

    def test_persisted_record_is_fixed_hash_only_and_rejects_unsafe_final(self):
        store = self.artifact_store()
        codex = persist_host_delivery(store, "codex")
        with sqlite3.connect(store.path) as db:
            payload = db.execute("SELECT payload FROM records WHERE ref=?",
                                 (codex["delivery_ref"].ref,)).fetchone()[0]
        for forbidden in (self.recipient, self.sender, "provider live response verified",
                          "Bounded live acquisition acceptance", "[CODEX]",
                          "providers-live-1", "codex", "run-001",
                          "candidate-001", "gpt-synthetic"):
            self.assertNotIn(forbidden, payload)
            self.assertNotIn(forbidden, codex["delivery_ref"].ref)
        stored = json.loads(payload)
        self.assertEqual(set(stored), {
            "version", "change_id_sha256", "scope_sha256",
            "notification_host_sha256", "notification_run_id_sha256",
            "notification_candidate_id_sha256", "notification_key_sha256",
            "execution_status", "result_sha256", "summary_sha256",
            "runtime_attestation_sha256", "delivery_verification_sha256",
        })

        for final_change in (
                {"access_token": "SYNTHETIC_CANARY"},
                {"report_directory": "/Users/private/report"}):
            receipt = copy.deepcopy(codex["receipt"])
            receipt["final"].update(final_change)
            receipt["final_sha256"] = hashlib.sha256(
                json.dumps(receipt["final"], sort_keys=True).encode()).hexdigest()
            with self.subTest(final_change=final_change), \
                    self.assertRaisesRegex(EmailSyncError,
                                            "ACCEPTANCE_FINAL_FIELDS_UNSAFE"):
                store.record_verified_delivery(
                    change_id="different-change", scope="scope",
                    result=codex["result"], summary=codex["summary"],
                    recipient=self.recipient, profile_email=self.sender,
                    runtime_attestation=codex["attestation"], receipt=receipt)

        extra = copy.deepcopy(codex["receipt"])
        extra["access_token"] = "SYNTHETIC_CANARY"
        with self.assertRaisesRegex(EmailSyncError,
                                    "ACCEPTANCE_RECEIPT_FIELDS_UNSAFE"):
            store.record_verified_delivery(
                change_id="different-change", scope="scope",
                result=codex["result"], summary=codex["summary"],
                recipient=self.recipient, profile_email=self.sender,
                runtime_attestation=codex["attestation"], receipt=extra)


if __name__ == "__main__":
    unittest.main()
