# Tiger bridge

Credential ownership and reusable data reads now live in
[`shared/tiger/`](../../shared/tiger/README.md). The runtime module is a compatibility
entry point for `verify` and report `run` mode. For isolated portal queries
(`positions`, `assets`, `snapshot`), use the shared gateway. Deploy it and its tests
alongside this runtime and the preserved holdings source.

This adapter reuses the existing owner-private encrypted OAuth store and official
read-only SDK from the preserved migration source. It does not create a broker
grant, switch to RSA, seed credentials, broaden scopes, or force token rotation.

The private policy file under `.niulai-state/` contains `project_id`, `origin`
(exact HTTPS Site origin), `owner_email`, and optionally `taxonomy` (a private
absolute workspace path). No actual user/account values belong in source fixtures.
The supervisor obtains a **fresh native Sites get_site response**, validates its
owner-only audience, and passes the full structured result to hidden TTY stdin:

```sh
PYTHONPATH=niulai-runtime PYTHONDONTWRITEBYTECODE=1 \
TMPDIR="$PWD/.niulai-state/tmp" .niulai-state/.venv/bin/python -m niulai_runtime.tiger \
  --workspace "$PWD" --policy .niulai-state/config/tiger.json \
  --out "$PWD/.niulai-state/reports/tiger-check" --mode verify
```

`verify` performs actual read-only holdings and assets requests; `run` additionally
executes the existing report pipeline with a private taxonomy. Neither sends mail.
Verification now requires `sourceReadStatus == complete` for both requested
payloads; partial positions cannot pass just because `ok` is true.
The bearer exists only in process memory, never command arguments, environment,
source, logs, or persisted policy. The legacy SDK receives a non-secret environment
marker solely to enable its in-memory rotation checkpoint callback.

The adapter checks exact project/origin/owner, custom access, sole owner allowlist,
and absence of additional editors, groups, or external visitors. HTTPS redirects
are rejected. Private directories use 0700 and credential files 0600. Source code
is staged into the private run directory because the migrated report modules have
import-time output-directory creation; the original `niulai/` snapshot stays intact.

The existing remote lease remains the cross-runtime refresh authority. A local
nonblocking file lock prevents overlapping Codex processes. Acquisition and
checkpoint requests retry at most three times, with 15-second request timeouts and
1/2-second backoff. Retries reuse identical request/commit identifiers and bytes.
401/403, redirects, malformed responses, and non-idempotent release requests are
not retried. The CLI has a 600-second deadline; interruption leaves the crash fence.

No additional broker/OAuth retry is added around the SDK: the existing SDK's
refresh handling remains under the lease and profile lock. Every token persistence
immediately checkpoints to the same remote store. An unconfirmed checkpoint or
broker failure retains the private working profile and an `unresolved.json` fence;
subsequent local runs stop for reconciliation instead of recycling uncertain tokens.
The adapter does not remove this fence automatically or release an uncertain lease.
This is conservative and can require operator recovery even for a harmless failed
read. The separately running cloud task does not consult the local fence: remote
lease expiry and cross-runtime recovery must be reconciled before another attempt.

Successful final checkpoint requests release and records the server's committed
acknowledgment. The current protocol does not provide a separate lease-release
receipt or device-delivery evidence. A fresh second process must verify that the
same remote profile still supports real reads before claiming cross-run operation.
Offline tests establish guard behavior only, not live broker access.

Transient private-store access failures do not establish broker grant expiry.
Only verified broker rejection/expiry/revocation justifies reauthorization. Grant
lifetime remains a provider constraint; token refresh cannot make consent permanent.
An unattended scheduler must obtain its own supported fresh service access; this
interactive Codex bridge alone does not implement that scheduler integration.
