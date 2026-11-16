# Independent reconciliation verification

The bounded read-only diagnostic is verified for its intended narrow use. The **original checkpoint remains unconfirmed** after the actual409 acknowledgement probe, and the original uncertainty fence remains in place. This report does not authorize retiring that fence, reading a profile, replaying acquire, or running another Tiger query.

## Frozen scope and source

Independent criteria were frozen at `trading-reconciliation-v1.0` in ACCEPTANCE.md before inspecting the recovered worker body or proposed client. The owner's client-only packet is `shared/tiger/reconciliation-acceptance.md`, OR-01–06. Both stayed unchanged during independent client execution.

- Exact worker file SHA256: `ed1b7a20b85b2444dd30039c94e67cc9594e6a7923c00b689b312b9193172ac0`; supplied and locally verified checkout HEAD: `ce58b639c137abda72f0bdea65118300355f4478`.
- Exact current client SHA256: `21c3ebe85c25d9c77afa66137ba6ff3e0b0b4e18c5f589df0245e02ed60dbd9f`.
- Selected level: Balanced, limited to exact offline Worker boundary, injected client transport/custody/CLI failures and deliberate breaks. No whole Trading Agent certification, credentials, actual private policy/fence, private plan, broker, deployment, orders, email, scheduler or global changes were accessed/performed by the verifier.

## Executed evidence

| Layer | Executed | Passed | Failed | Skipped | Deliberate breaks detected |
| --- | ---: | ---: | ---: | ---: | ---: |
| Exact Worker fixture cases | 26 | 24 | 2 | 0 | 4 separately executed |
| Independent client unittest cases | 27 | 27 | 0 | 0 | 8 included in27 |

The client total is19 ordinary cases plus8 mutation-control cases, not35 cases. The Worker handler was invoked 42 times across fixture/repeat/mutation controls. Mutations were in-memory only; recovered and production source files were not edited.

Worker no-write scope **PASS**: GET health and minimal checkpoint bodies without profile/release attempted no storage writes and preserved independently compared durable state. Tests exercised empty/active/expired/exact-expiry/opaque-profile states, matching and nonmatching commits, malformed/missing values, read failure, repeat/concurrent reads, wrong origin and methods. Four wrong implementations were detected: write on health, write before missing-profile rejection, false commit acknowledgement, and permanent deduplication of expired acquire. An initial harness configuration omitted URL; positive controls prevented acceptance, and that setup was corrected before the published execution receipt. No successful proof is claimed from the aborted harness attempt.

The **two Worker failures are retained**, not weakened or called passing holdouts: wrong/missing lease_id still receives an idempotent acknowledgement when commit_id matches. The frozen REC-W-003 tuple inverse therefore fails. This is a limit of the recovered service's existing semantics, not an implementation edit requested by this task. The diagnostic client correctly limits its claim to latest-commit recognition and never marks lease release verified.

The client checks include nominal,409,timeout, malformed/secret-bearing JSON, exact64KiB boundary, duplicate keys/nonfinite/deep/invalid UTF-8, scalar/type/status limits, source/deployment/owner/audience/origin failures before dispatch, private-file/symlink guards, existing lock contention and lock held through transport, no profile read, immutable original fence and drift detection, exact routes/body/original IDs, response/error closure, no retries, and unique private CLI success/failure files. Canary credentials/provider errors did not appear in diagnostic output. Eight deliberate breaks detected removed source/deployment/lock/fence gates, added release to body, removed byte cap, exported raw error, and invented lease-release verification.

## Criterion mapping

| Criterion | Independent executed controls / limit |
| --- | --- |
| REC-W-001 | W-HEALTH-*; no-write/state comparisons, including expiry |
| REC-W-002 | W-MATCH-*, W-REPEAT-CONCURRENT; exact matching response with no writes |
| REC-W-003 | W-REJECT-* pass; W-TUPLE-wrong_lease/missing_lease FAIL retained |
| REC-W-004 | W-READ-FAILURE/CROSS-ORIGIN/METHOD; platform authentication intentionally NOT RUN because it is enforced outside this Worker |
| REC-W-005 | W-EXPIRED-ACQUIRE-WRITES and active control; acquire exclusion required |
| REC-W-006 | Exact hash/HEAD/real handler/in-memory bucket, source stability and4 breaks |
| OR-01 / REC-C-001 / REC-C-007 | Pinned source/deployment, existing policy loader, context extra/owner/audience/origin, before-dispatch inverses |
| OR-02 / REC-C-002 | Fence shape/permissions/symlink, actual local lock during transport, original-ID body, no profile read or mutation |
| OR-03 / REC-C-003 / REC-C-004 | Exact2 allowed routes/body,1attempt each/15s configured timeout, redirect rejection,64KiB exact boundary and response close |
| OR-04 / REC-C-005 | Closed predefined health/ack scalar fields, nested private data rejection, sanitized HTTP statuses/errors, CLI no-canary output |
| OR-05 / REC-C-006 |409/timeout/uninitialized cases remain unconfirmed/not_run; fence retirement and lease-release verification remain false |
| OR-06 | Lock release on error/drift, resource closure, source gates, private unique success/failure files, no earlier report overwrite |

## Exact recovered Worker response semantics

| Operation / state | Observed response and durable effect |
| --- | --- |
| GET /health |200: schema1, initialized=bool(cipher), revision, lease_busy=lease exists AND until>now, last_committed_at or null. No write. It does not expose last_commit or verify profile decryptability/release. |
| Minimal checkpoint with matching valid commit_id |200: committed=true, current revision, idempotent=true, released=!CURRENT lease. lease_id is ignored in this branch; no profile needed and no write. |
| Nonmatching commit, current matching active lease, no profile |400 INVALID_PROFILE; no write. |
| Nonmatching commit, absent/expired/wrong lease |409 LEASE_REJECTED; no write. |
| Invalid commit ID / malformed JSON |400 INVALID_COMMIT_ID / INVALID_JSON; no write. Null body or store read failure returns503 STORE_OPERATION_FAILED. |
| Old acquire after expiry, even original request_id |Creates another lease lifecycle with the same supplied ID, increments revision and gives another600000ms expiry. It is not permanently read-only/idempotent. This was exercised only against an isolated fake bucket. |

Only the latest scalar last_commit is retained; there is no historical commit journal or lease binding in the idempotent acknowledgement. The released flag cannot prove the old commit requested release or that the old lease was independently released. Local request identity/custody is validated by the client, without inventing remote historical attestation.

## Actual owner readback, reviewed from the permitted sanitized record

The first owner CLI attempt failed locally before HTTP because the recovered Git source file was0644. Its failure was retained. The owner then copied identical code into a new0600 diagnostic file (same Worker SHA), obtained fresh native context and completed the bounded readback. Neither original source/client/fence nor remote credential owner was changed for this preparation.

The permitted sanitized readback file hashes to `30729ec8c1567b5f0b99be7c06e920f6862efdb222b94148118aa041fda19509` and passes closed-output/outcome consistency checks. It records2HTTP attempts, no automatic retry,0broker calls and0credential writes. Health reports initialized=true, lease_busy=false, revision104 and last_committed_at2026-11-10T18:31:45.229Z. The original minimal checkpoint acknowledgement is409; the client reports `history_unavailable_or_unconfirmed`, `fence_retired=false` and `lease_release_verified=false`.

Under the pinned Worker semantics, that request did not enter the matching latest-commit acknowledgement branch. This does **not** prove whether the original checkpoint ever committed. An expired lease_busy=false does not prove a lease was released. The provided original fence hash `f944020d918f3e61abd18d4d03d836adfdc0c9bba90fadd8c7e0739cb5c6513a` matches the sanitized readback; the verifier did not read the actual private fence or plan. Actual preservation is supported by the pinned client's final byte comparison and owner-recorded readback, rather than a separate private-file inspection by this verifier.

## Human-readable outcome

| Input | Action | Result | Failure/stop behavior |
| --- | --- | --- | --- |
| Check whether the original unknown checkpoint is the service's latest commit | Verified source/owner/deployment, held the existing lock, then health plus original-ID acknowledgement probe | Service health is available; original commit history remains unconfirmed after409 | Original fence remains; no profile/acquire/release/retry or new Tiger query is authorized by this result |

Evidence files: `.runtime/worker-proof-1794838825545.json`, `.runtime/client-proof-1794839246712647000/client-proof.json` and its unittest.txt, `.runtime/actual-readback-review.json`. Test sources are verify_worker.mjs and test_independent_client.py. The reported15s is the configured HTTP transport timeout; CLI code has a40s alarm after native-context admission. No real timed-network/fault or platform-authentication test was performed by the verifier. Major future scheduled business-path/email acceptance remains UNVERIFIED; the full Tiger→Trading Agent integration is outside this subtask's verdict.
