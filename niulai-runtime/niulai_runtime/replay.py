"""Controlled exact-content migration test, using a host-provided Gmail transport.

This CLI cannot send on its own. A Codex operator claims once, calls the Gmail
connector once with the immutable payload, then records and verifies its receipt.
It never admits a production slot or installs a recurring job.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
import json
import os
from pathlib import Path
import sys

from .config import load_config, assert_recipient
from .delivery import Outbox, DeliveryError, assert_content_parity, validate_payload
from .scheduler import admit


def from_raw(encoded: str, recipient: str) -> dict:
    """Normalize original/readback MIME without copying transport headers."""
    raw = base64.b64decode(encoded.strip() + '=' * (-len(encoded.strip()) % 4),
                           altchars=b'-_', validate=True)
    message = BytesParser(policy=policy.default).parsebytes(raw)
    if message.defects or len(message.get_all('To', [])) != 1:
        raise DeliveryError('RAW_MESSAGE_INVALID')
    if len(message.get_all('From', [])) != 1 or any(message.get_all(h) for h in ('Cc', 'Bcc')):
        raise DeliveryError('RAW_ADDRESS_HEADERS_INVALID')
    for header in ('From', 'To'):
        value = message[header]
        if getattr(value, 'defects', ()) or len(getaddresses([str(value)])) != 1:
            raise DeliveryError('RAW_ADDRESS_HEADERS_INVALID')
    if getaddresses([str(message['From'])])[0][1] != recipient or getaddresses([str(message['To'])])[0][1] != recipient:
        raise DeliveryError('RAW_IDENTITY_MISMATCH')
    if len(message.get_all('Subject', [])) != 1:
        raise DeliveryError('RAW_SUBJECT_INVALID')
    if message.get_content_type() != 'multipart/mixed' or not message.is_multipart():
        raise DeliveryError('RAW_MIXED_MESSAGE_REQUIRED')
    parts = []
    for part in message.iter_parts():
        if part.is_multipart():
            raise DeliveryError('RAW_NESTED_MIME_REJECTED')
        if part.defects:
            raise DeliveryError('RAW_PART_INVALID')
        mime = part.get_content_type()
        if mime == 'text/html':
            if part.get_content_disposition() not in (None, 'inline') or part.get_filename() or part.get('Content-ID'):
                raise DeliveryError('RAW_HTML_DISPOSITION_INVALID')
            charset = part.get_content_charset() or 'utf-8'
            data = part.get_payload(decode=True)
            if part.defects:
                raise DeliveryError('RAW_PART_INVALID')
            parts.append({'mime_type': mime, 'charset': charset,
                          'body': {'base64_url_content': base64.urlsafe_b64encode(data).decode()}})
        elif mime == 'application/pdf':
            if part.get_content_disposition() != 'attachment' or part.get('Content-ID'):
                raise DeliveryError('RAW_PDF_DISPOSITION_INVALID')
            data = part.get_payload(decode=True)
            if part.defects:
                raise DeliveryError('RAW_PART_INVALID')
            parts.append({'mime_type': mime, 'filename': part.get_filename(),
                          'content_disposition': 'attachment', 'body': {
                              'base64_url_content': base64.urlsafe_b64encode(data).decode()}})
        else:
            raise DeliveryError('RAW_UNEXPECTED_MIME')
    result = {'to': recipient, 'subject': str(message['Subject']),
              'payload': {'mime_type': 'multipart/mixed', 'parts': parts}}
    validate_payload(result, recipient, recipient)
    return result


def private_file(path, root):
    p = Path(path).absolute()
    state = root / '.niulai-state'
    if not p.is_relative_to(state) or not p.resolve().is_relative_to(state.resolve()) or any(x.is_symlink() for x in [p, *p.parents] if x.is_relative_to(state)):
        raise DeliveryError('PRIVATE_PATH_INVALID')
    return p


def require_replay_receipt(row, message_id: str, source_message_id: str):
    """Exact-content readback must be of the newly accepted send, not its source.

    The host must obtain raw bytes by reading this exact accepted message ID.
    MIME alone cannot attest Gmail's immutable API ID. Ambiguous-send recovery
    is deliberately a separate operator workflow, not this replay command.
    """
    if not source_message_id or not message_id or message_id == source_message_id:
        raise DeliveryError('REPLAY_SOURCE_IS_NOT_NEW_RECEIPT')
    if not row or row['status'] != 'accepted' or row['message_id'] != message_id:
        raise DeliveryError('REPLAY_ACCEPTED_RECEIPT_REQUIRED')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'claim', 'accepted', 'unknown', 'verify', 'status'])
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--source-message-id', required=True)
    parser.add_argument('--attempt-id')
    parser.add_argument('--message-id')
    parser.add_argument('--readback')
    args = parser.parse_args()
    os.umask(0o077)
    root = Path(args.workspace).resolve(strict=True)
    config = load_config(args.config, root)
    if config.mode != 'manual_test' or config.production_enabled:
        raise DeliveryError('MANUAL_TEST_POLICY_REQUIRED')
    admission = admit(config, datetime.now(timezone.utc), None, config.scheduler_owner,
                      manual_request_id=args.request_id)
    if not admission.allowed or not admission.send_allowed:
        raise DeliveryError(admission.reason)
    key = admission.delivery_key
    source = json.loads(private_file(args.source, root).read_text())
    outbox = Outbox(config.state_root / 'databases' / 'outbox.sqlite', root)
    if args.action in ('prepare', 'claim'):
        # Read the current get_profile structured result via stdin. This is a
        # host evidence handoff, not a network account check by the local CLI.
        profile = json.load(sys.stdin)
        assert_recipient(config, profile.get('email'), source.get('to'))
        fingerprint = assert_content_parity(source, source, config.recipient, profile['email'])
        if args.action == 'prepare':
            row = outbox.prepare(key, source, recipient=config.recipient, profile_email=profile['email'])
            print(json.dumps({'status': row['status'], 'fingerprint': fingerprint}))
        else:
            payload = outbox.claim(key, args.attempt_id)
            assert_content_parity(source, payload, config.recipient, profile['email'])
            # Payload is private. The host consumes stdout in memory; do not
            # print this result into the user transcript or persist public logs.
            print(json.dumps(payload, ensure_ascii=False))
    elif args.action == 'accepted':
        row = outbox.accepted(key, args.attempt_id, args.message_id)
        print(json.dumps({'status': row['status'], 'message_id': row['message_id']}))
    elif args.action == 'unknown':
        row = outbox.unknown(key, args.attempt_id)
        print(json.dumps({'status': row['status']}))
    elif args.action == 'verify':
        require_replay_receipt(outbox.get(key), args.message_id, args.source_message_id)
        actual = from_raw(private_file(args.readback, root).read_text(), config.recipient)
        fingerprint = assert_content_parity(source, actual, config.recipient, config.recipient)
        row = outbox.reconcile_accepted(key, message_id=args.message_id, verified_digest=fingerprint['digest'])
        print(json.dumps({'status': row['status'], 'message_id': row['message_id'],
                          'verified_at': row['verified_at'], 'exact_content_verified': True,
                          'fingerprint': fingerprint}))
    else:
        row = outbox.get(key)
        print(json.dumps({k: row[k] for k in ('status','message_id','verified_at')} if row else {'status':'absent'}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Never echo malformed private content or an arbitrary traceback.
        from .config import ConfigError
        code = str(exc) if isinstance(exc, (DeliveryError, ConfigError)) else 'REPLAY_OPERATION_FAILED'
        print(json.dumps({'status': 'failed', 'error': code}))
        raise SystemExit(2)
