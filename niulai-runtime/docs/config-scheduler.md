# Configuration and scheduling boundary

`niulai_runtime.config` validates a private, versioned JSON policy. Start from
`config/runtime.example.json`, replace its placeholders using verified account
and existing automation metadata, and save it below workspace `.niulai-state/`.
The example is deliberately not runnable. Private directories require mode 0700
and configuration files mode 0600. Neither archive is modified.

`load_config(path, workspace_root)` rejects unknown fields, duplicate JSON keys,
unsafe permissions, path escapes, alternate timezones, changed slots, and invalid
recipient values. `assert_recipient(config, observed_gmail_email, payload_to)`
must run immediately before sending using a fresh authenticated Gmail profile.
The delivery adapter must independently reject Cc, Bcc, and additional recipients.

`scheduler.admit(config, now, calendar, actor_id, manual_request_id=None,
completed_keys=(), cutover=None)` is a pure admission function. It installs no
timer and claims no scheduler activation. Pass actual timezone-aware time.
The `calendar` dependency must implement `name == 'XNYS'` and
`is_session(datetime.date) -> bool`, with coverage failures raised rather than
converted into weekday assumptions. Tests use an explicitly synthetic inventory,
not a claim to test the real exchange calendar or installed scheduler.

- `dry_run` evaluates real due slots but never authorizes email.
- `manual_test` requires a unique, user-authorized request ID and uses a separate
  deduplication namespace. The same request ID remains the same key across dates.
- `production` defaults disabled. It requires matching scheduler ownership and
  caller-verified references for old-sender disablement and delivery-ledger import
  in `CutoverEvidence`. These references are not automatically verified by this
  module. The orchestration layer must inspect the actual evidence; filling strings
  is not a cutover verification procedure.

Production preserves `America/New_York`, XNYS session dates, 13:00 and 19:00 slots,
and an inclusive 60-minute grace window. It does not currently authorize late
historical catch-up beyond that window. Such an extension needs explicit review
of the source engine's existing retrospective policy and publication ledger.

Production email keys retain the source format:
`portfolio-email:{automation_id}:{NY_date}:{slot}:{recipient}`. Revisions never
reset them. The caller must import prior records and atomically claim the key in
the durable delivery ledger before sending. An in-memory completed-key check is
only an early guard; it is not cross-process duplicate protection. Dry runs must
never mark that key sent or complete. Manual tests use `manual-email:` keys.

Offline checks from the workspace:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=niulai-runtime python3 -m unittest discover -s niulai-runtime/tests -p test_config_scheduler.py -v
```

These checks establish policy/admission behavior only. Actual OAuth access,
mailbox receipt, exchange-calendar installation, and unattended execution require
separate live evidence before production cutover.
