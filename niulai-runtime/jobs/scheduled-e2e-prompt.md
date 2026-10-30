Run this explicitly user-authorized ONE-TIME FULL scheduled Niulai E2E test.
The trusted scheduler context supplies workspace, request_id, output_directory,
session, recipient, delivery_policy and tiger_policy. Use those exact values.
Do the real work; a completed model turn is not success. Do not invoke any GPT
Work conversation/task, Price Alert Studio, or old production sender. No trading,
new consent, changed app permissions, root MCP settings, production slots or rules.
Root source and both migration archives are read-only. All writes stay in the
private output directory or the validated private runtime paths.

1. Verify Gmail's actual current get_profile equals the context recipient. Do
   not infer connection from the tool list. Stop on mismatch.
2. Read the source commands in niulai-runtime/docs/operator.md and the local
   e2e_prepare/e2e_delivery/tiger module interfaces. Use the job-local Python at
   WORKSPACE/.niulai-state/.venv/bin/python,
   PYTHONPATH=WORKSPACE:WORKSPACE/niulai-runtime,
   PYTHONDONTWRITEBYTECODE=1 and TMPDIR=WORKSPACE/.niulai-state/tmp. Do not use the
   generic infrastructure Python for the business dependencies.
3. Read tiger_policy (non-secret metadata only), then call native Sites get_site
   for its EXACT project_id. Keep its entire structured response only in tool
   memory. Never print/log/persist service bearer or broker credential values.
   Run `python -m niulai_runtime.tiger --workspace WORKSPACE --policy TIGER_POLICY
   --out OUTPUT/holdings --mode run` in a TTY. Wait for hidden stdin readiness,
   then pass the fresh Sites structured response as JSON through write_stdin.
   The bridge validates private audience, obtains the shared lease, reads real
   Tiger holdings/assets and checkpoints tokens. No force-refresh or login.
   A failed/unconfirmed credential operation is a blocker; do not delete fences,
   reauthorize, reuse stale profiles or repeat it. Preserve exact sanitized codes.
4. Independently run `python -m niulai_runtime.e2e_prepare --workspace WORKSPACE
   --workflow WORKSPACE/.niulai-state/e2e/source/workflow.json
   --rules WORKSPACE/.niulai-state/e2e/source/alerts.json
   --dbclone WORKSPACE/.niulai-state/e2e/source/alerts.sqlite
   --out OUTPUT/prices --session SESSION`. This fetches public price sources now
   and evaluates the last completed session in a second private cloned DB. It
   must preserve the source DB, all live signals and production records. It is
   historical/replay, never current live pricing. Do not change rules or clock.
   Both this stage and holdings stage can run independently, with bounded waits.
5. Require fresh holdings daily.json/daily.pdf, a confirmed Tiger checkpoint, and
   prices preparation_receipt.json, price_view/price_view.json, price.pdf and
   price_message.txt. Report partial coverage precisely; unknown values are not
   zero. Never use files from component tests or earlier runs as fresh output.
6. Compose ONE email using the deterministic `e2e_delivery compose` command
   described below. It reads only this run's fresh files, invokes the preserved
   complete composer, inserts a fixed provenance/partial-coverage banner, and
   validates the two PDF bytes and source lineage. Do not manually modify its
   subject, body, recipients or attachments. The guard rechecks the canonical
   payload before preparation, claim and mailbox verification.
7. Email delivery uses `python -m niulai_runtime.e2e_delivery ACTION
   --workspace WORKSPACE --config DELIVERY_POLICY --request-id REQUEST_ID
   --payload OUTPUT/email_payload.json [--attempt-id ATTEMPT] [--message-id ID]
   [--readback OUTPUT/gmail_readback.b64]`. Use a unique attempt identifier of
   letters/digits/hyphens at least8 characters. Feed actual current get_profile
   structured JSON on stdin for prepare and claim. Prepare saves an immutable
   payload. Claim must succeed exactly ONCE. Consume claim stdout in tool memory
   and call native Gmail send_email exactly once with that full MIME payload.
   If outcome is uncertain, mark unknown and reconcile; NEVER blindly resend.
   Record accepted using the exact real send response message ID immediately.
8. Native Gmail read_email(format='raw') MUST read that exact new send ID. Save
   its base64url raw field to OUTPUT/gmail_readback.b64 (email data only; never
   service/broker credentials). Run e2e_delivery verify with that message ID.
   This compares subject, full HTML and decoded PDF bytes and persists readback.
   Require actual INBOX/SENT mailbox evidence; do not claim device receipt.
   This corrected test uses Codex automatic approval review. If send requests
   approval, let that configured reviewer evaluate the exact authorized
   self-addressed report. Do not change app permissions, request a bypass or
   call send twice. On denial record the real failure and leave delivery unverified.
9. Return ONLY a small JSON object using these keys: status='sent' only after
   verified delivery, code='FULL_E2E_VERIFIED', message_id, gmail_verified=true,
   delivery_verified=true, price_status, holdings_status, report_directory,
   source_dates=[SESSION], error_codes. If any necessary stage fails return
   status='failed' or 'blocked', delivery_verified=false and safe error_codes.
   Allowed status values include partial/completed/rendered/rendered_partial.
   Include no account identifiers, credential values, raw tool output or P&L.
