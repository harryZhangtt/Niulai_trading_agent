import base64
from email.message import EmailMessage
from email import policy
from pathlib import Path
import unittest

from niulai_runtime.delivery import DeliveryError, assert_content_parity
from niulai_runtime.replay import from_raw, private_file, require_replay_receipt

ROOT = Path(__file__).resolve().parents[2]
RECIPIENT = 'owner@example.test'


def raw_message():
    m = EmailMessage(policy=policy.SMTP)
    m['From'] = 'Synthetic Owner <' + RECIPIENT + '>'
    m['To'] = RECIPIENT
    m['Subject'] = 'Synthetic subject 中文'
    m.make_mixed()
    html = EmailMessage()
    # set_content intentionally appends a newline; exact bytes are taken from
    # the resulting message rather than stripping whitespace for comparison.
    html.set_content('<html><body>Complete synthetic 中文</body></html>', subtype='html', charset='utf-8')
    m.attach(html)
    for name in ('holdings.pdf', 'prices.pdf'):
        m.add_attachment(b'%PDF-1.4\n% synthetic '+name.encode()+b'\n%%EOF\n', maintype='application', subtype='pdf', filename=name)
    return m


def encode(m):
    return base64.urlsafe_b64encode(m.as_bytes()).decode()


class ReplayTest(unittest.TestCase):
    def test_raw_roundtrip_preserves_html_and_pdf_bytes(self):
        m = raw_message()
        candidate = from_raw(encode(m), RECIPIENT)
        leaves = list(m.iter_parts())
        # SMTP serializes CRLF, so parse the raw bytes before comparison.
        html = candidate['payload']['parts'][0]['body']['base64_url_content']
        source = {'to': RECIPIENT, 'subject': str(m['Subject']), 'payload': {
            'mime_type': 'multipart/mixed', 'parts': [
                {'mime_type': 'text/html', 'charset': 'utf-8', 'body': {'content': base64.urlsafe_b64decode(html).decode('utf-8')}},
                *[{'mime_type': 'application/pdf', 'filename': p.get_filename(), 'content_disposition': 'attachment',
                   'body': {'base64_url_content': base64.urlsafe_b64encode(p.get_payload(decode=True)).decode()}} for p in leaves[1:]]
            ]}}
        assert_content_parity(source, candidate, RECIPIENT, RECIPIENT)

    def test_address_expansion_or_spoofing_rejected(self):
        for header, value in [('To', RECIPIENT+', second@example.test'), ('From', 'other@example.test')]:
            m = raw_message()
            m.replace_header(header, value)
            with self.assertRaises(DeliveryError):
                from_raw(encode(m), RECIPIENT)
        m = raw_message()
        m['Cc'] = 'other@example.test'
        with self.assertRaisesRegex(DeliveryError, 'RAW_ADDRESS_HEADERS_INVALID'):
            from_raw(encode(m), RECIPIENT)

    def test_pdf_must_really_be_attachment_and_materialized(self):
        m = raw_message()
        list(m.iter_parts())[1].replace_header('Content-Disposition', 'inline; filename="holdings.pdf"')
        with self.assertRaisesRegex(DeliveryError, 'RAW_PDF_DISPOSITION_INVALID'):
            from_raw(encode(m), RECIPIENT)
        m = raw_message()
        m.set_payload(list(m.iter_parts())[:2])
        with self.assertRaisesRegex(DeliveryError, 'TWO_DISTINCT_PDFS_REQUIRED'):
            from_raw(encode(m), RECIPIENT)

    def test_unknown_or_nested_mime_not_silently_flattened(self):
        m = raw_message()
        m.add_attachment(b'unknown data', maintype='application', subtype='octet-stream', filename='unknown.bin')
        with self.assertRaisesRegex(DeliveryError, 'RAW_UNEXPECTED_MIME'):
            from_raw(encode(m), RECIPIENT)
        m = raw_message()
        nested = EmailMessage()
        nested.make_alternative()
        m.attach(nested)
        with self.assertRaisesRegex(DeliveryError, 'RAW_NESTED_MIME_REJECTED'):
            from_raw(encode(m), RECIPIENT)

    def test_original_email_cannot_be_reconciled_as_test_send(self):
        source, new = 'aaaaaaaaaaaaaaaa', 'bbbbbbbbbbbbbbbb'
        accepted = {'status': 'accepted', 'message_id': new}
        require_replay_receipt(accepted, new, source)
        with self.assertRaisesRegex(DeliveryError, 'REPLAY_SOURCE_IS_NOT_NEW_RECEIPT'):
            require_replay_receipt({'status': 'accepted', 'message_id': source}, source, source)
        for row in (None, {'status': 'sending', 'message_id': None}, {'status': 'unknown', 'message_id': None}, {'status': 'accepted', 'message_id': source}):
            with self.assertRaisesRegex(DeliveryError, 'REPLAY_ACCEPTED_RECEIPT_REQUIRED'):
                require_replay_receipt(row, new, source)

    def test_private_path_cannot_escape_by_dotdot(self):
        with self.assertRaisesRegex(DeliveryError, 'PRIVATE_PATH_INVALID'):
            private_file(ROOT / '.niulai-state' / '..' / 'niulai-private' / 'archive.json', ROOT)


if __name__ == '__main__':
    unittest.main()
