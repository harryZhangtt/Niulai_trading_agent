import base64
from concurrent.futures import ThreadPoolExecutor
import copy
from pathlib import Path
import tempfile
import unittest

from niulai_runtime.delivery import (DeliveryError, Outbox, assert_content_parity,
                                    dispatch_once, validate_payload)

ROOT = Path(__file__).resolve().parents[2]
RECIPIENT = "owner@example.test"


def message():
    # Intentionally minimal, synthetic PDF bytes; no private report fixtures.
    def pdf(name, text):
        return {"mime_type": "application/pdf", "filename": name,
                "content_disposition": "attachment", "body": {
                    "base64_url_content": base64.urlsafe_b64encode(
                        b"%PDF-1.4\n% synthetic " + text + b"\n%%EOF\n").decode()}}
    return {"to": RECIPIENT, "subject": "Synthetic combined digest",
            "payload": {"mime_type": "multipart/mixed", "parts": [
                {"mime_type": "text/html", "charset": "UTF-8",
                 "body": {"content": "<html><body>FULL synthetic report</body></html>"}},
                pdf("holdings.pdf", b"holdings"), pdf("prices.pdf", b"prices")]}}


class DeliveryTest(unittest.TestCase):
    def setUp(self):
        (ROOT / ".niulai-state").mkdir(exist_ok=True, mode=0o700)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / ".niulai-state", prefix="delivery-test-")
        self.path = Path(self.tmp.name) / "outbox.sqlite"
        self.outbox = Outbox(self.path, ROOT)

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self, key="manual:test-request-123"):
        return self.outbox.prepare(key, message(), recipient=RECIPIENT, profile_email=RECIPIENT)

    def test_profile_recipient_and_extra_envelope_rejected(self):
        with self.assertRaisesRegex(DeliveryError, "PROFILE_RECIPIENT_MISMATCH"):
            validate_payload(message(), RECIPIENT, "other@example.test")
        for field in ("cc", "bcc", "reply_to"):
            candidate = message()
            candidate[field] = "elsewhere@example.test"
            with self.assertRaisesRegex(DeliveryError, "UNEXPECTED_MESSAGE_FIELD"):
                validate_payload(candidate, RECIPIENT, RECIPIENT)

    def test_html_truncation_and_pdf_byte_change_fail_exact_parity(self):
        source = message()
        candidate = copy.deepcopy(source)
        candidate["payload"]["parts"][0]["body"]["content"] = "<html>short</html>"
        with self.assertRaisesRegex(DeliveryError, "CONTENT_PARITY_FAILED"):
            assert_content_parity(source, candidate, RECIPIENT, RECIPIENT)
        candidate = message()
        candidate["payload"]["parts"][1]["body"]["base64_url_content"] = base64.urlsafe_b64encode(b"%PDF-1.4\nchanged\n%%EOF").decode()
        with self.assertRaisesRegex(DeliveryError, "CONTENT_PARITY_FAILED"):
            assert_content_parity(source, candidate, RECIPIENT, RECIPIENT)

    def test_subject_label_may_be_explicitly_excluded_from_content_parity(self):
        source, candidate = message(), message()
        candidate["subject"] = "[TEST] " + candidate["subject"]
        with self.assertRaisesRegex(DeliveryError, "CONTENT_PARITY_FAILED"):
            assert_content_parity(source, candidate, RECIPIENT, RECIPIENT)
        assert_content_parity(source, candidate, RECIPIENT, RECIPIENT, same_subject=False)

    def test_base64_padding_is_not_a_content_change(self):
        source, candidate = message(), message()
        for p in candidate["payload"]["parts"][1:]:
            p["body"]["base64_url_content"] = p["body"]["base64_url_content"].rstrip("=")
        assert_content_parity(source, candidate, RECIPIENT, RECIPIENT)

    def test_missing_fake_or_unfetched_attachment_rejected(self):
        candidate = message()
        candidate["payload"]["parts"].pop()
        with self.assertRaisesRegex(DeliveryError, "TWO_DISTINCT_PDFS_REQUIRED"):
            validate_payload(candidate, RECIPIENT, RECIPIENT)
        candidate = message()
        candidate["payload"]["parts"][1]["body"] = {"content": "https://example.test/report.pdf"}
        with self.assertRaisesRegex(DeliveryError, "ACTUAL_PDF_REQUIRED"):
            validate_payload(candidate, RECIPIENT, RECIPIENT)
        candidate["payload"]["parts"][1]["body"] = {"attachment_id": "remote-id"}
        with self.assertRaisesRegex(DeliveryError, "UNMATERIALIZED_MIME_BODY"):
            validate_payload(candidate, RECIPIENT, RECIPIENT)

    def test_prepare_is_idempotent_but_content_immutable(self):
        self.prepare()
        self.prepare()
        candidate = message()
        candidate["subject"] += " changed"
        with self.assertRaisesRegex(DeliveryError, "IMMUTABLE_PAYLOAD_CONFLICT"):
            self.outbox.prepare("manual:test-request-123", candidate, recipient=RECIPIENT, profile_email=RECIPIENT)

    def test_only_one_concurrent_claim_can_send(self):
        key = "manual:test-request-123"
        self.prepare(key)
        def claim(i):
            try:
                Outbox(self.path, ROOT).claim(key, "attempt-" + str(i))
                return True
            except DeliveryError:
                return False
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(claim, range(4))), 1)

    def test_ambiguous_send_never_retries_and_error_is_sanitized(self):
        key = "manual:test-request-123"
        self.prepare(key)
        calls = []
        def sender(payload):
            calls.append(payload)
            raise RuntimeError("secret network error")
        with self.assertRaisesRegex(DeliveryError, "SEND_OUTCOME_UNKNOWN_RECONCILE_REQUIRED"):
            dispatch_once(self.outbox, key, "attempt-123", sender, recipient=RECIPIENT, profile_email=RECIPIENT)
        self.assertEqual(self.outbox.get(key)["status"], "unknown")
        with self.assertRaisesRegex(DeliveryError, "OUTBOX_NOT_SENDABLE"):
            dispatch_once(self.outbox, key, "attempt-456", sender, recipient=RECIPIENT, profile_email=RECIPIENT)
        self.assertEqual(len(calls), 1)

    def test_crash_after_claim_requires_readback(self):
        key = "manual:test-request-123"
        prepared = self.prepare(key)
        self.outbox.claim(key, "attempt-123")
        reopened = Outbox(self.path, ROOT)
        with self.assertRaisesRegex(DeliveryError, "OUTBOX_NOT_SENDABLE"):
            reopened.claim(key, "attempt-456")
        with self.assertRaisesRegex(DeliveryError, "READBACK_DIGEST_MISMATCH"):
            reopened.reconcile_accepted(key, message_id="a123456789abcdef", verified_digest="wrong")
        result = reopened.reconcile_accepted(key, message_id="a123456789abcdef", verified_digest=prepared["digest"])
        self.assertEqual(result["status"], "accepted")
        self.assertIsNotNone(result["verified_at"])

    def test_acceptance_is_not_verification_and_preserves_id(self):
        key = "manual:test-request-123"
        self.prepare(key)
        result = dispatch_once(self.outbox, key, "attempt-123", lambda _: "a123456789abcdef", recipient=RECIPIENT, profile_email=RECIPIENT)
        self.assertEqual(result["status"], "accepted")
        self.assertIsNone(result["verified_at"])
        with self.assertRaisesRegex(DeliveryError, "MESSAGE_ID_CONFLICT"):
            self.outbox.accepted(key, "attempt-123", "b123456789abcdef")

    def test_manual_test_does_not_complete_production_key(self):
        self.prepare("manual:test-request-123")
        self.prepare("portfolio-email:automation:2026-10-30:13:00:owner@example.test")
        dispatch_once(self.outbox, "manual:test-request-123", "attempt-123", lambda _: "a123456789abcdef", recipient=RECIPIENT, profile_email=RECIPIENT)
        self.assertEqual(self.outbox.get("portfolio-email:automation:2026-10-30:13:00:owner@example.test")["status"], "prepared")

    def test_paths_and_permissions(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        with self.assertRaisesRegex(DeliveryError, "OUTBOX_OUTSIDE_PRIVATE_STATE"):
            Outbox(ROOT / "outside.sqlite", ROOT)
        with self.assertRaisesRegex(DeliveryError, "OUTBOX_PATH_ESCAPE"):
            Outbox(ROOT / ".niulai-state" / ".." / "outside.sqlite", ROOT)
        with self.assertRaisesRegex(DeliveryError, "OUTBOX_PATH_ESCAPE"):
            Outbox(ROOT / ".niulai-state" / ".." / ".niulai-state" / "outside.sqlite", ROOT)
        link = Path(self.tmp.name) / "link.sqlite"
        link.symlink_to(self.path)
        with self.assertRaisesRegex(DeliveryError, "OUTBOX_SYMLINK_REJECTED"):
            Outbox(link, ROOT)


if __name__ == "__main__":
    unittest.main()
