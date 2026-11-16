# Scheduler/provider retry source ledger

## Purpose, evidence class, and nonclaims

This is a source-only research ledger for the provider-neutral scheduler retry
candidate. It records previously researched official/GitHub source pins and their
licenses, then separates those upstream observations from the workspace's
source-live provider-free contract. This documentation update made no web request,
provider call, repository download, email delivery, runtime or setup change.

A source entry establishes only what the named revision implements. It does not
show that the workspace uses that SDK, that a provider accepted or rejected any
request, that a scheduled job is idempotent, or that retrying an operation is
safe. The accompanying JSON examples are `synthetic_not_live_evidence`, not live
captures or Codex event evidence.

## Workspace candidate derived from, not proved by, the sources

The current workspace candidate is implemented in
`shared/job_runtime/provider_contract.py`, `retry_policy.py`, `config.py`,
`engine.py`, `model.py`, `service.py`, `dashboard.py` and
`providers/{codex_cli.py,claude_host.py}`. It defines typed provider results,
deterministic retry decisions, explicit replay/reconciliation authority, schema-8
immutable ledgers and scoped circuits. Focused and adjacent Python checks, a
provider-free campaign and scheduler UI checks are source evidence only. They do
not prove an installed migration, provider behavior, host availability, persistent
restart behavior in the intended service, Gmail delivery or runtime acceptance.

The provider-free campaign deliberately covers these failure classes without a
provider: preconnect and typed 408/409/429/529/5xx decisions; valid, past,
malformed and over-bound `Retry-After`; permanent auth/config/model/policy;
provider retry true/false; post-submit timeout/reset/partial/missing-terminal
unknown fences; attempt exhaustion/deadline; restart and injected crash points;
circuit open/half-open/close/reopen, generation and scope isolation; single-use
reconciliation; immutability; cancellation/shutdown/contenders; config drift and
v1 compatibility. Synthetic providers, clocks, owner proofs and external-effect
sentinels with temporary SQLite are not live-provider evidence.

The Codex normalized fixture is sanitized, synthetic structural input only. It
contains no raw Codex output and establishes no Codex event names, retry semantics,
provider identity or production translator conformance. The normalized structural
translator remains activation-blocked until pinned-source and sanitized-capture
conformance are independently verified; the service code gate blocks it. The
Claude source validates sealed local custody evidence but provides no host bridge,
remote attestation or installed-runtime proof. Both paths remain runtime-unverified.

No source hash or test total is pinned here because the candidate is still
settling. A future acceptance record must capture fresh source, schema,
configuration, profile and translator/bridge fingerprints for the exact scheduled
candidate it runs.

## Primary pinned SDK sources

### Anthropic Python SDK v2.5.0

- Repository/tag: `anthropics/anthropic-sdk-python`, `v2.5.0`.
- Commit: `dd18a659419fe4d83aa9109bdcdcf9a35d5c8ddb`.
- License: MIT.
- Inspected source:
  - [`src/anthropic/_base_client.py`](https://github.com/anthropics/anthropic-sdk-python/blob/dd18a659419fe4d83aa9109bdcdcf9a35d5c8ddb/src/anthropic/_base_client.py): `_should_retry`, `_calculate_retry_timeout`, and the request retry loop.
  - `src/anthropic/_constants.py`: retry count and delay constants.
  - `src/anthropic/_exceptions.py`: typed connection/status errors.
  - `src/anthropic/_streaming.py`: stream iteration and terminal handling.
- Tests: not fully retrieved in the source-research run. No test name or test-level
  claim is inferred here; evidence is source-level inspection only.

Semantics recorded from the pin:

- Default `max_retries` is 2, meaning up to two retries after the initial request
  (at most three SDK attempts), unless the caller overrides it.
- Retry candidates are connection/timeout failures and HTTP 408, 409, 429, and
  5xx responses. `x-should-retry: true` forces eligibility and
  `x-should-retry: false` suppresses it before the status default is applied.
- A valid `Retry-After` delay is used only when it is positive and no more than
  60 seconds. The implementation recognizes the SDK's supported retry-delay
  header forms; malformed or out-of-range values fall back to local backoff.
- Default delay is capped exponential backoff: approximately
  `min(0.5 * 2^n, 8.0)` seconds for retry index `n`, multiplied by downward
  jitter in the range `[0.75, 1.0]`.
- SDK request retries are not evidence of application idempotency. A retry is safe
  only if the request body can be recreated/rewound and the operation's duplicate
  effect is prevented or reconciled. One-shot readers and already-consumed upload
  or streaming bodies require explicit proof, not an assumption.
- A stream that ends after partial output without its required terminal event is
  incomplete, not a successful response. Because output may already have escaped,
  the whole operation must not be blindly replayed or concatenated.

### Anthropic TypeScript SDK sdk-v1.5.0

- Repository/tag: `anthropics/anthropic-sdk-typescript`, `sdk-v1.5.0`.
- Commit: `3cde979dcebea3450c508f7afc71315be09bf99a`.
- License: MIT.
- Inspected source:
  - [`src/client.ts`](https://github.com/anthropics/anthropic-sdk-typescript/blob/3cde979dcebea3450c508f7afc71315be09bf99a/src/client.ts): `shouldRetry`, `calculateDefaultRetryTimeoutMillis`, and `retryRequest`.
  - `src/core/error.ts`: typed API and connection error boundary.
  - `src/core/streaming.ts`: stream parsing and completion behavior.
- Tests: not fully retrieved in the source-research run; no test names are claimed.

Semantics recorded from the pin match the Python policy at the contract level:
default two retries; connection failures and 408/409/429/5xx eligibility; explicit
`x-should-retry` true/false precedence; usable server delay only through 60 seconds;
and capped exponential delay beginning at 0.5 seconds, capped at 8 seconds, with
25% downward jitter. Reconstructing a request in `retryRequest` does not make an
arbitrary JavaScript body replayable: consumed `ReadableStream` and other one-shot
body sources remain a caller boundary. Partial stream output without terminal
completion is incomplete and is not an automatic whole-request retry signal.

### OpenAI Python SDK v3.46.0

- Repository/tag: `openai/openai-python`, `v3.46.0`.
- Commit: `ea5d1606f441d80dca1e9e7f99b74581f41408f8`.
- License: Apache-2.0.
- Inspected source:
  - [`src/openai/_base_client.py`](https://github.com/openai/openai-python/blob/ea5d1606f441d80dca1e9e7f99b74581f41408f8/src/openai/_base_client.py): `_should_retry`, `_calculate_retry_timeout`, request retry loop, idempotency handling, and body rewind path.
  - `src/openai/_constants.py`: retry count and delay constants.
  - `src/openai/_streaming.py`: stream parsing/completion boundary.
- Tests: not fully retrieved in the source-research run; no test names are claimed.

Semantics recorded from the pin:

- Default `max_retries` is 2: at most three SDK attempts including the initial one.
- Connection/timeout failures and HTTP 408, 409, 429, and 5xx are retry candidates;
  `x-should-retry` true/false overrides the status default.
- A valid positive `Retry-After` value no greater than 60 seconds is preferred;
  malformed, nonpositive, or longer values use the local schedule.
- Local delay is approximately `min(0.5 * 2^n, 8.0)` seconds with `[0.75, 1.0]`
  downward jitter.
- The retry path includes body rewind and idempotency support, but rewind capability
  is a mechanical precondition, not proof that the remote operation is safe to
  duplicate. A non-rewindable body must not be treated as replayable.
- EOF after partial stream data without protocol completion is an incomplete
  response. Once partial output has been observed, a higher layer must reconcile
  rather than assume a transparent retry preserves exactly-once behavior.

### OpenAI TypeScript SDK v7.51.0

- Repository/tag: `openai/openai-node`, `v7.51.0`.
- Tag commit: `738695092f2d8e9e092de7bd19f0994e0ba68e25`.
- License: Apache-2.0.
- Bounded source inspection used revision
  `2d5b81c729b6d0b4f7da453026aaca6dedb2fb7e`, which is **not** the tag
  target; no tag-parity claim is made for that inspection.
- Inspected source at that separate revision:
  - [`src/client.ts`](https://github.com/openai/openai-node/blob/2d5b81c729b6d0b4f7da453026aaca6dedb2fb7e/src/client.ts): retry classifier, delay calculation, retry request path, and body replay handling.
  - `src/core/streaming.ts`: stream parsing/completion boundary.
- Tests: not fully retrieved in the source-research run; no test names are claimed.

Semantics recorded from the pin are the same contract-level defaults: two retries
beyond the first attempt; connection failures and 408/409/429/5xx; explicit
`x-should-retry` precedence; server delay accepted only through 60 seconds; and
0.5-second exponential backoff capped at 8 seconds with downward jitter. The
implementation's body handling must still reject or specially handle consumed
one-shot streams. Missing stream termination after partial data is not success and
does not prove whole-request replay safety.

### OpenAI Codex Rust rust-v0.166.0

- Repository/release: `openai/codex`,
  [`rust-v0.166.0`](https://github.com/openai/codex/releases/tag/rust-v0.166.0).
- Annotated tag object: `593389380740f7b4762771573c447ccfdc59742f`;
  peeled release commit: [`6ff1e1ca3b30fc8b914720681fcf5fe62e95f856`](https://github.com/openai/codex/commit/6ff1e1ca3b30fc8b914720681fcf5fe62e95f856).
- The earlier `49f0c6022596c361fe676a5c4738fb2be34e3a93` reference is a pull-request
  head, not the release target, and is not used as the release pin.
- Repository license: Apache-2.0.
- Exact source files/functions/tests: not retrieved before the bounded source run
  timed out; a local `gh` client was also unavailable. Therefore this ledger makes
  **no exact-semantics claim** about Codex retry counts, statuses, backoff, event
  names, stream terminal markers, request replay, or scheduler integration.

The commit and release identify a revision, but they are not event conformance.
Before adding any Codex-specific fixture, pin and inspect the exact Rust source and
tests that define the event/retry semantics, or admit a sanitized actual capture
with provenance and redaction records. Do not infer or invent Codex event names
from Anthropic/OpenAI SDK concepts.

## Secondary sources

These are comparison sources, not selected runtime dependencies.

### urllib3 2.6.3

- Repository/version: `urllib3/urllib3`, `2.6.3`; license MIT.
- Source: [`src/urllib3/util/retry.py`](https://github.com/urllib3/urllib3/blob/2.6.3/src/urllib3/util/retry.py).
- Tests: [`test/test_retry.py`](https://github.com/urllib3/urllib3/blob/2.6.3/test/test_retry.py).
- Inspected concept: a mature separation of connect/read/status/redirect/other
  retry budgets; method and status allowlists; `Retry-After` handling; exponential
  backoff and jitter; and retry history.
- Limitation: HTTP transport retry policy does not classify a scheduler's business
  submission outcome or make a non-idempotent body safe. Its defaults and HTTP
  method assumptions are not copied wholesale.

### Kombu 5.7.0

- Repository/version: `celery/kombu`, `v5.7.0`; license BSD-3-Clause.
- Source: `kombu/transport/redis.py`, `kombu/transport/virtual/base.py`.
- Tests: `t/unit/transport/test_redis.py`.
- Inspected concept: broker reconnect/recovery and visibility/acknowledgement state
  are separate from ordinary HTTP request retry.
- Limitation: transport-specific broker delivery semantics are not provider API
  response semantics. No Kombu code or dependency is adopted.

### APScheduler v4 alpha

- Repository/version: `agronholm/apscheduler`, `4.0.0a6`; license MIT.
- Source: `src/apscheduler/datastores/sqlalchemy.py`.
- Tests: `tests/test_datastores.py`.
- Inspected concept: bounded datastore retry belongs at the persistence boundary,
  while schedule/job state remains explicit.
- Limitation: this alpha source is design input, not a stable API commitment. It
  does not define provider submission, stream completion, or replay safety. No
  APScheduler code or dependency is adopted.

### botocore (secondary, unpinned in this run)

Botocore was considered only as a secondary example of centralized retry modes,
quota/backoff, and service-model-aware classification. No exact botocore version,
commit, file, function, or test was pinned in the bounded source run, so it is not
an admissible conformance source and contributes no copied semantics. Pinning all
of those fields is required before relying on it.

## Concepts reused and rejected

Reused as provider-neutral design concepts:

1. Typed classification before delay calculation.
2. Explicit permanent auth/config rejection versus transient transport, rate-limit,
   conflict/timeout, and server/overload categories.
3. Server retry hints only when parseable, positive, and within a local bound;
   otherwise bounded exponential backoff with jitter.
4. Explicit body-replay state and a distinct unknown-outcome classification after
   submission may have occurred.
5. Terminal stream completion as a required success condition; EOF alone is not a
   terminal event.
6. Recorded attempt history and a hard retry budget.
7. Explicit server retry/no-retry override semantics where a pinned SDK defines
   them.

Rejected or deliberately not copied:

- No SDK/library is added as a dependency and no upstream implementation is copied.
- No provider-specific exception class crosses the future scheduler contract.
- No universal status-only retry rule overrides submission phase, body replay, or
  idempotency evidence.
- No unbounded `Retry-After`, endless reconnect, or retry-until-success behavior.
- No blind replay after post-submit reset, partial response, or missing terminal.
- No inferred Codex event names or Codex retry semantics.
- No claim that urllib3, Kombu, APScheduler alpha, or botocore defaults fit this
  workspace unchanged.

## Nested retry warning

Do not independently enable full retry loops in both an SDK and the scheduler.
With scheduler retry limit `S` and SDK retry limit `P`, a single logical operation
can make as many as `(S + 1) * (P + 1)` network attempts, while each layer adds
its own delays and may lose sight of body consumption or an unknown remote effect.
For the common SDK default `P = 2`, one initial scheduler attempt plus two
scheduler retries can become nine provider attempts.

Choose one owner for immediate network retries. The outer scheduler should own
persistent deferral, reconciliation, and unknown-outcome handling; it must account
for any inner attempts in the total budget. Permanent auth/config failures stop
immediately. Post-submit reset and partial-stream cases require idempotency evidence
or reconciliation before any replay.

## Remaining limitations

- Primary SDK tests were not fully retrieved, so this ledger does not fabricate
  test names or claim a test-level audit.
- Codex exact files, functions, tests, event names, and semantics remain unverified.
- Secondary source commits were not captured beyond the exact release tags named
  above; botocore is entirely unpinned.
- Source inspection is not execution evidence. No provider, scheduler, stream, or
  body-replay behavior was exercised.
- Synthetic fixtures specify expected classifications for a future harness only;
  they do not demonstrate that existing runtime code implements those results.
