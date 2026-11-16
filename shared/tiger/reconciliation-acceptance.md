# Read-only Tiger owner readback — frozen client contract

Revision: owner-readback-v1, 2026-11-16. This extends diagnostics only; it does
not retire an uncertainty fence or recover credentials. Independent exact-source
verification is required before live use. Selected level: balanced with security,
no-write and deliberate-break controls; all injected failures stay offline.

Observed problem: the original checkpoint acknowledgement is unknown, and the
normal gateway correctly denies another lease. Expected benefit: distinguish an
exact latest-commit acknowledgement from insufficient historical evidence.
Owner: shared/tiger. Diagnostic source is inert/local until manually invoked.
Live invocation is bounded active service access to the existing sole-owner Site;
there are no broker calls, credential writes, deployments or host registrations.

| ID | Precondition and action | Required result | Forbidden result |
| --- | --- | --- | --- |
| OR-01 | Read current source, fresh native Site/version/deployment and private policy | Exact pinned source SHA/commit, project, successful deployment and sole-owner origin match before HTTP | Calling an unverified source, owner, audience, origin or deployment |
| OR-02 | Inspect original checkpoint fence while holding existing local lock | Original attempt/commit identities and fence SHA bind both readback calls | New operation identities, lease acquire/release, profile read or fence/profile mutation |
| OR-03 | Call health and original checkpoint acknowledgement probe | Only GET /health then POST /lease/checkpoint with exactly commit_id and lease_id; one attempt each, no redirects, 15s timeout, 64KiB cap | Profile/release in body, retry, OAuth/broker calls, arbitrary path |
| OR-04 | Inject malformed, secret-bearing or unsuccessful responses | Closed scalar output/error schema; HTTP status may be reported; token/raw error/URL never printed | Raw nested response, provider exception text, credential in stdout/env/argv/report |
| OR-05 | Lost response, rejected old commit, later commit or expired lease | Preserve fence; classify matching acknowledgement versus unconfirmed/history unavailable | Health/revision/lease expiry treated as proof of old commit or automatic fallback |
| OR-06 | Timeout, lock contention, source drift, interruption or result writing | Bounded termination, lock released, original fence hash checked; unique private result path | Shared source/owner/server changes, orphan processes, replacing an earlier report |

The source currently retains only `last_commit`, not a historical commit journal.
An idempotent acknowledgement establishes that exact latest commit only. A 409
or 400 does not prove the old checkpoint never committed. No response returned
by this diagnostic authorizes clearing the original fence automatically.

Acceptance requires exact Worker no-write tests, independent client verification,
sanitized execution counts and a frozen source fingerprint before the two live
readback requests. Existing Trading Agent criteria and old baselines remain intact.
