# Gmail delivery boundary

`niulai_runtime.delivery` is a transport-neutral outbox, not a Gmail OAuth client
or an installed scheduler. The caller supplies the currently verified Gmail
profile and the recipient from validated private configuration. It rejects CC,
BCC, alternate recipients/senders, unfetched attachments, and payloads without
one HTML body and two distinct actual PDF attachments. PDF signature/end markers
are structural checks, not a PDF renderer or a guarantee of semantic correctness.

Store the database only under workspace `.niulai-state/`. Directories are 0700
and database files 0600. This database contains complete private email payloads;
exclude the entire state directory from Git and backups that are not approved
for private account data. The module never stores credentials or raw transport
errors. Keep runtime artifacts separate from the immutable migration archives.

## Caller sequence

1. Obtain scheduler admission and the stable per-channel delivery key. Manual
   tests use their own request key; never reuse or complete a production slot.
2. Materialize complete source HTML and both PDF bytes. For an exact-content
   migration test, call `assert_content_parity(source, candidate, recipient,
   profile_email)`. This compares exact subject and MIME content hashes. Setting
   `same_subject=False` explicitly allows a test subject prefix while preserving
   every body and attachment byte. Nothing is semantically summarized.
3. Call `Outbox.prepare(key, message, recipient=..., profile_email=...)`. Reusing
   the same key with changed content fails. Repeating identical preparation is
   idempotent and never resets an existing status.
4. Call `claim(key, attempt_id)` once, then send its returned immutable payload
   using the connected Gmail tool. Only a newly successful claim permits sending.
5. Call `accepted(key, attempt_id, message_id)` with the actual Gmail response ID.
   On a timeout or ambiguous failure call `unknown(key, attempt_id)`. Do not
   retry. A crash after claim leaves `sending`, which also cannot be resent.
6. Independently read the exact Gmail message and both attachments, check the
   sender and recipient, normalize it to the send-payload shape, validate/hash it,
   and call `reconcile_accepted(key, message_id=..., verified_digest=...)`. This
   marks readback verification. A search snippet alone is insufficient.
   Exclude the original source message and older same-content messages; verify
   the candidate's immutable Gmail ID, sender/recipient and send timestamp
   against this attempt. The replay CLI requires `--source-message-id` and only
   verifies the newly accepted message ID; it cannot resolve an ambiguous send.

`dispatch_once` wraps steps 4–5 for a callable transport that returns a Gmail
message ID. Its failure message is sanitized. It never automatically retries.
Outbox acceptance proves only transport acceptance. Verified readback proves
the message exists with the expected content; neither proves phone push or that
the user read it. The connector and permission checks still apply at send time.

There is no reset/release/retry operation for ambiguous sends. If independent
readback cannot establish what happened, leave the item unresolved. A human
request for a correction must use a distinct auditable request key. The caller
must retain same-slot ledger ownership across scheduler cutover; this module
does not synchronize an old cloud sender automatically.

## Offline tests

From the workspace root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=niulai-runtime python3 -m unittest discover -s niulai-runtime/tests -p test_delivery.py -v
```

Tests use synthetic bodies/PDF bytes and temporary files under `.niulai-state/`.
They cover recipient confinement, exact byte parity, concurrent claims, immutable
preparation, crash/timeout reconciliation, manual/production separation, and
private path/permission enforcement. They do not send emails.
