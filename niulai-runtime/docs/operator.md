# Codex operator procedure

This procedure uses native authenticated tools. Do not implement it by scraping
browser cookies, saving service bearer tokens or reconstructing undocumented
private APIs.

## Manual Tiger verification

For the shared MCP portal use `python -m shared.tiger --tool snapshot --out
PRIVATE_FRESH_OUTPUT` from the workspace root and the same native-context handoff
below. After success, use `--tool assets` in a second fresh process to test cold
restoration. See the [shared runbook](../../shared/tiger/README.md) for deadlines,
arguments and private artifacts.

1. Read private `config/tiger.json` under `.niulai-state/` and obtain a fresh Sites
   result for that exact project. Never print the bearer or full response.
2. Start `python -m niulai_runtime.tiger --workspace WORKSPACE --policy POLICY
   --out PRIVATE_FRESH_OUTPUT --mode verify` with a TTY and workspace-local
   temporary directories. Wait for the hidden-input readiness message.
3. Pass the fresh structured Sites response through tool memory to stdin. The
   bridge validates owner identity, private audience and origin before access.
4. Inspect the sanitized result. Success requires a real holdings/assets read
   and confirmed checkpoint/release. Only after success may a second independent
   process test cold restoration. No forced rotation is necessary.
5. On uncertain refresh/commit outcomes, preserve the private recovery material
   and stop. An ambiguous result is not evidence that the grant expired. Do not
   delete the crash fence to retry. The old cloud task does not consult the local
   crash fence; coordinate any recovery with the shared remote credential owner.

`--mode run` uses the existing calculation/report pipeline and private taxonomy.
It does not send email. A partial report remains partial.

## Exact-content Gmail migration test

1. Read the selected original Gmail message in raw form. Decode the complete
   body and actual attachments into a private send payload. Preserve source ID
   separately; never substitute excerpts, links or attachment names for bytes.
2. Read Gmail's current profile. The private runtime policy, live profile and
   payload recipient must agree. Set manual-test mode; keep production disabled.
3. Use `niulai_runtime.replay prepare` with a unique authorized request ID,
   source-message ID, private source payload and the live profile JSON on stdin.
   It records an immutable payload and full-content fingerprints.
4. Immediately before send, recheck the profile and call `replay claim` with a
   unique attempt ID. Consume stdout privately in tool memory. A repeated claim
   fails. Call the connected Gmail send tool exactly once with this payload.
5. Persist its returned real message ID using `replay accepted`. If the outcome
   is uncertain, mark `unknown` and reconcile; never repeat the send automatically.
6. Read that exact new Gmail ID in raw form and store it privately. Run `replay
   verify` against the original payload. Verification requires the accepted
   response ID, rejects the source ID, and compares subject, HTML and both PDFs.
7. Verify Gmail's mailbox labels independently. An Inbox record proves mailbox
   arrival, not phone push delivery or that the user read the email.

The CLI's profile/site arguments are evidence supplied by the authenticated host,
not independent account verification by local Python. Keep production scheduling
off until an actual unattended execution has verified these capabilities.
