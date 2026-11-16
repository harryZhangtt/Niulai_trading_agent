import base64
from concurrent.futures import ThreadPoolExecutor
import copy
from pathlib import Path
import tempfile
import json
import unittest

from niulai_runtime.delivery import (DeliveryError, Outbox, assert_content_parity,
                                    dispatch_once, gmail_claim, validate_payload)

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
        display=message();display['to']='Owner <OWNER@example.test>';display['from_address']='Sender <owner@EXAMPLE.test>'
        self.assertEqual(validate_payload(display,'Recipient <owner@example.test>','Profile <OWNER@example.test>')['sender'],RECIPIENT)
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

    def test_pre_send_claim_binds_execution_sender_and_all_canonical_components(self):
        payload=message();execution={'job_id':'job.synthetic','slot_id':'slot.synthetic','attempt_id':'attempt.synthetic'}
        claim=gmail_claim(payload,profile_email=RECIPIENT,execution=execution,
                          host='a'*64,run='b'*64,candidate='c'*64)
        self.assertEqual(set(claim),{'schema_version','job_id','slot_id','attempt_id','host','run','candidate','mode',
            'delivery_payload_sha256','recipient_sha256','subject_sha256','sender_identity_sha256',
            'profile_identity_sha256','html_sha256','attachments_sha256','payload_sha256'})
        import json,hashlib
        bound={k:v for k,v in claim.items() if k!='payload_sha256'}
        self.assertEqual(claim['payload_sha256'],hashlib.sha256(json.dumps(bound,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest())
        changed=message();changed['payload']['parts'][2]['body']['base64_url_content']=base64.urlsafe_b64encode(b'%PDF-1.4 changed %%EOF').decode()
        self.assertNotEqual(gmail_claim(changed,profile_email=RECIPIENT,execution=execution,
                            host='a'*64,run='b'*64,candidate='c'*64)['payload_sha256'],claim['payload_sha256'])

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

    def test_manual_cli_reconciles_unknown_exact_readback_without_accept_or_resend(self):
        from email.message import EmailMessage
        from email import policy
        from types import SimpleNamespace
        from unittest.mock import patch
        from niulai_runtime import e2e_delivery
        from niulai_runtime.replay import from_raw
        import io
        root=Path(self.tmp.name);state=root/'.niulai-state';state.mkdir()
        raw=EmailMessage(policy=policy.SMTP)
        raw['From']=RECIPIENT;raw['To']=RECIPIENT;raw['Subject']='Synthetic exact readback'
        raw.set_content('<html>Complete report</html>',subtype='html')
        raw.add_attachment(b'%PDF-1.4 synthetic %%EOF',maintype='application',subtype='pdf',filename='report.pdf')
        raw.add_attachment(b'%PDF-1.4 prices %%EOF',maintype='application',subtype='pdf',filename='prices.pdf')
        encoded=base64.urlsafe_b64encode(raw.as_bytes()).decode()
        payload=from_raw(encoded,RECIPIENT)
        path=state/'payload.json';path.write_text(json.dumps(payload))
        readback=state/'raw.b64';readback.write_text(encoded)
        config=SimpleNamespace(mode='manual_test',production_enabled=False,scheduler_owner='synthetic',recipient=RECIPIENT,state_root=state)
        outbox=Outbox(state/'databases/outbox.sqlite',root);key='manual:synthetic'
        prepared=outbox.prepare(key,payload,recipient=RECIPIENT,profile_email=RECIPIENT)
        outbox.claim(key,'attempt-synthetic');outbox.unknown(key,'attempt-synthetic')
        args=['e2e_delivery','reconcile','--workspace',str(root),'--config','synthetic','--request-id','synthetic',
              '--payload',str(path),'--message-id','a123456789abcdef','--readback',str(readback)]
        with patch('sys.argv',args),patch.object(e2e_delivery,'load_config',return_value=config), \
             patch.object(e2e_delivery,'admit',return_value=SimpleNamespace(allowed=True,delivery_key=key)), \
             patch('niulai_runtime.e2e_guard.validate'),patch.object(Outbox,'claim',side_effect=AssertionError('no resend')), \
             patch.object(Outbox,'accepted',side_effect=AssertionError('no acceptance prerequisite')),patch('sys.stdout',io.StringIO()):
            altered=dict(payload);altered['subject']='mismatch';path.write_text(json.dumps(altered))
            with self.assertRaises(DeliveryError):e2e_delivery.main()
            self.assertEqual(outbox.get(key)['status'],'unknown')
            path.write_text(json.dumps(payload));e2e_delivery.main()
        self.assertEqual(outbox.get(key)['status'],'accepted')
        self.assertEqual(outbox.get(key)['digest'],prepared['digest'])
        self.assertIsNotNone(outbox.get(key)['verified_at'])



class DailyClaimCallerTests(unittest.TestCase):
    def test_production_prepare_builds_bound_claim_and_reserves_once(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from niulai_runtime import daily_job
        from shared.job_runtime.business import _validate_gmail_claim, _consume_gmail_claim
        parent=ROOT/'.job-runtime/tests';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temp:
            root=Path(temp);directory=root/'.niulai-state/daily' / ('a'*32) / 'mail/initial'
            directory.mkdir(parents=True)
            (directory/'payload.json').write_text(json.dumps(message()))
            outbox=Outbox(root/'.niulai-state/outbox.sqlite',root)
            work=SimpleNamespace(outbox=outbox)
            context={'job_id':'daily.synthetic','slot_id':'slot.synthetic','attempt_id':'attempt-synthetic'}
            from shared.job_runtime.business import IMPLEMENTATION_SHA256 as business_digest
            from niulai_runtime.delivery import IMPLEMENTATION_SHA256 as delivery_digest
            generation={'service':{'source_sha256':'a'*64},'pid':123,
                        'implementations':{'business':business_digest,'delivery':delivery_digest}}
            runtime={'version':3,'service_generation':generation,'adapter_generation':{'source_sha256':'c'*64}}
            prepared={'work_id':'work.synthetic','output_directory':str(directory)}
            meta={'policy':'fixture','purpose':'production','recipient':RECIPIENT,'authorization':'fixture'}
            policy=SimpleNamespace(recipient=RECIPIENT,mode='production',production_enabled=True)
            result=SimpleNamespace(returncode=0,stdout=json.dumps(prepared))
            with patch.object(daily_job.subprocess,'run',return_value=result), \
                 patch.object(daily_job,'plan',return_value={'status':'composed','directory':str(directory),'key':'delivery.synthetic'}), \
                 patch.object(daily_job,'load_work',return_value=(work,{'initial_key':'delivery.synthetic','correction_key':None},meta,directory)), \
                 patch.object(daily_job,'load_config',return_value=policy), \
                 patch.object(daily_job,'authorization') as authorization:
                with patch.object(daily_job,'atomic',side_effect=OSError('synthetic write failure')):
                    failed=daily_job.prepare({},root,context,runtime)
                    self.assertEqual(failed['status'],'retryable')
                    self.assertEqual(outbox.get('delivery.synthetic')['status'],'prepared')
                    self.assertFalse((directory/'gmail_claim.json').exists())
                value=daily_job.prepare({},root,context,runtime)
                claim=value['gmail_claim']
                self.assertEqual(_validate_gmail_claim(claim,job_id=context['job_id'],context=context),claim)
                self.assertEqual(json.loads((directory/'gmail_claim.json').read_text()),claim)
                self.assertEqual(outbox.get('delivery.synthetic')['status'],'prepared')
                self.assertEqual(daily_job.prepare({},root,context,runtime)['gmail_claim'],claim)
                self.assertEqual(authorization.call_count,3)
                self.assertIsNone(_consume_gmail_claim(root,claim,'business'))
                self.assertEqual(_consume_gmail_claim(root,claim,'business'),'RUNTIME_GMAIL_CLAIM_REPLAY')
                self.assertEqual(outbox.get('delivery.synthetic')['status'],'prepared')
                daily_job.commit_dispatch({},root,context,claim)
                self.assertEqual(outbox.get('delivery.synthetic')['status'],'sending')
                with self.assertRaisesRegex(DeliveryError,'OUTBOX_NOT_SENDABLE'):
                    daily_job.commit_dispatch({},root,context,claim)

    def test_unexposed_work_lease_releases_but_sending_stays_fenced(self):
        from datetime import datetime,timedelta,timezone
        from niulai_runtime.daily_work import Work
        from niulai_runtime.daily_job import release_not_dispatched
        with tempfile.TemporaryDirectory(dir=ROOT/'.job-runtime/tests') as temp:
            root=Path(temp);work=Work(root);now=datetime.now(timezone.utc)
            row=work.create('synthetic-work',{'scheduled_at':now.isoformat(),'deadline':(now+timedelta(hours=1)).isoformat()})
            work.outbox.prepare('synthetic-key',message(),recipient=RECIPIENT,profile_email=RECIPIENT)
            work.bind_delivery(row['id'],'synthetic-key')
            self.assertTrue(work.claim(row['id'],'attempt-first',now))
            release_not_dispatched({},root,{'attempt_id':'foreign-owner'})
            self.assertEqual(work.get(row['id'])['lease_owner'],'attempt-first')
            release_not_dispatched({},root,{'attempt_id':'attempt-first'})
            self.assertIsNone(work.get(row['id'])['lease_owner'])
            self.assertEqual(work.get(row['id'])['tries'],0)
            self.assertTrue(work.claim(row['id'],'attempt-second',now))
            work.outbox.claim('synthetic-key','attempt-second')
            release_not_dispatched({},root,{'attempt_id':'attempt-second'})
            self.assertEqual(work.get(row['id'])['lease_owner'],'attempt-second')
            self.assertEqual(work.outbox.get('synthetic-key')['status'],'sending')

    def test_initializer_timeout_json_and_schema_are_not_dispatched(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import subprocess
        from niulai_runtime import daily_job
        with tempfile.TemporaryDirectory(dir=ROOT/'.job-runtime/tests') as temp:
            for output in ('{','[]','null','{}','{"work_id":3}', '{"status":"failed"}'):
                with patch.object(daily_job.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=output)),patch.object(daily_job,'plan') as plan:
                    result=daily_job.prepare({},Path(temp),{},{});
                    self.assertEqual(result['status'],'failed');self.assertEqual(result['receipt']['dispatch_phase'],'not_dispatched');plan.assert_not_called()
            with patch.object(daily_job.subprocess,'run',side_effect=subprocess.TimeoutExpired('synthetic',30)):
                result=daily_job.prepare({},Path(temp),{},{})
                self.assertEqual(result['status'],'retryable');self.assertEqual(result['receipt']['dispatch_phase'],'not_dispatched')


if __name__ == "__main__":
    unittest.main()
