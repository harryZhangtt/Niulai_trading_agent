# Durable research TaskQ

Version `2026-10-20-taskq-1`. This is a SQLite state queue for the existing native orchestrator, not an SMQ external service, agent executor, daemon, scheduler or message sender.

Use `scripts/task_queue.py` on the restored `research.sqlite`; missing/wrong databases are rejected. It adds `taskq_jobs`, `taskq_events` and `taskq_policy` without changing existing research tables. Only the parent orchestrator writes the shared database. Children return artifacts and checkpoint information to the parent. Local leases coordinate one shared SQLite instance, not independent remote database copies. Retain remote Library versions; reconcile conflicting saves rather than overwriting newer state.

## Interface

- `enqueue --db PATH --file REQUEST.json`: request `{run_id,session,config_revision,input_hash,tasks:[{ticker,payload,dependencies:[],max_attempts:3}]}`. IDs hash frozen context plus ticker. Identical retries are no-ops; same identity with changed payload is rejected. Dependencies use task IDs returned by enqueue or computed by `task_id(request,ticker)` for the same atomic batch. Unknown dependencies and cycles reject the whole transaction.
- `configure --db PATH --max-active 3`: set the persisted global active-lease cap, range 1–8. Default 3. The parent must set it to the validated saved orchestration limit; lowering does not cancel existing jobs, and blocks further claims until capacity returns.
- `claim --db PATH --owner PARENT --run-id CURRENT_RUN --limit 3 --lease-seconds 900 --output claims.json`: atomically leases ready jobs. Scheduled claims MUST specify the exact current frozen run ID; this excludes historical replay or other-run backlog. The API permits an omitted filter only for explicit administrative use. Active leases across all runs still count toward the global cap. Claims have unique fencing tokens, attempts and checkpoints. Pending dependencies block dispatch; failed/cancelled dependencies remain visibly blocked.
- `heartbeat --db PATH --id ID --token TOKEN --lease-seconds 900`: renew before expiry.
- `checkpoint --db PATH --id ID --token TOKEN --file CHECKPOINT.json`: structured checkpoint requires `stage` and should include artifact identities/hashes and unresolved gaps. Checkpoints survive retries/reclaims.
- `finish --db PATH --id ID --token TOKEN --file RESULT.json`: complete the work attempt with structured result.
- `fail --db PATH --id ID --token TOKEN --error TEXT [--permanent] [--retry-seconds 30]`: transient failures retry with bounded exponential backoff until max attempts; permanent failures stop immediately. Expired leases are reclaimed during the next claim or become failed at the attempt limit.
- `cancel --db PATH --id ID --reason TEXT`: explicitly invalidate pending/running work, fencing old workers.
- `status --db PATH [--id ID]`: read-only state. All commands accept `--output PATH` for retained JSON.

Persist and read back after enqueue, checkpoints and terminal transitions. Store actual evidence/assessment revisions through `research_store.py`; queue results hold references, not duplicate unverifiable reports. `taskq_events` is append-only. Neither enqueue nor claim means research has executed.

## Completion, recovery and freshness

A queue state of **completed means this attempt finished**, not that the ticker has a complete investment recommendation. Store `result.research_status` separately (`complete`, `partial`, `failed`, etc.), plus coverage, evidence/model gates and saved artifact references. A partial attempt can finish safely while remaining a research backlog item. Continue it in an explicitly linked follow-up run with a new frozen identity and inherited checkpoints; do not silently relabel it complete or change immutable enqueue inputs.

Before resume/publication, the parent revalidates configuration, rules, source/model revisions, quote cutoff and evidence dependencies. Historical frozen runs may resume only with an explicit historical label. Today's changed inputs require a new task identity and a supersession/rebase record; cancel obsolete pending work when appropriate. Never claim an old historical pilot merely because it remains pending; reuse requires explicit rebase with current inputs, not removal of the run filter. The queue does not certify freshness, evidence truth, source support or arithmetic/model validity.

Lease tokens fence stale worker completions after expiry, reclaim or cancellation. They do not ensure exactly-once external side effects. Use deterministic research-store request IDs, version guards and publication deduplication. A lost finish acknowledgement may be reconciled by readback; do not repeat a trade/message or invent delivery acknowledgement. There is no automatic trading or sending in this helper.

## Test scope

`NIULAI_TEST_RESEARCH_DB=/absolute/restored/research.sqlite python -m unittest discover -s scripts -p test_task_queue.py` checks concurrency cap, duplicate/conflicting enqueue, atomic rollback, dependency cycle/failure, lease expiry and stale-token fencing, heartbeat, checkpoint recovery, retries/permanent failure, cancellation and real-database-copy preservation. Synthetic tasks are fixtures only, never market evidence.


## Production completion and continuation gate

For every production research run, batch size is only a concurrency bound, never a cap on the total selected roster. The parent must drain all selected ticker pipelines and resolve fixable partial results in the same active workflow. A completed attempt returning partial research must produce a continuation/retry/rebase action; it must not terminate the run merely because three pilots or one batch finished. A supported `no_buy`, `hold` or `wait` is a valid completed decision; positive alpha is not required.

Run `scripts/research_completion.py --manifest MANIFEST.json --output COMPLETION.json`. It reuses the existing `schemas/research-run.schema.json` and pinned `schemas/requirements.txt`; it is not another executor. Manifest fields:

- `run_id`, frozen `input_hash`, `queue_db` (restored real or explicitly isolated test DB), and `expected_tickers` containing the entire selection.
- `items`: one per ticker, with `ticker`, `input_hash`, `status`, `action` and a hashed `record:{path,sha256}` pointing to that ticker's full research-harness record. Its `run_id` is `parent_run_id:TICKER` or it explicitly records `parent_run_id`. Full company/fund records are required for completed investment decisions. Partial items can omit the record but cannot pass.
- Each complete item's `persistence_readbacks`: `{artifact_id,file_id,version,content:{path,sha256},receipt:{path,sha256}}`. The receipt is the actual retained save response; the content is a materialized readback. For a bundled report, add `archive_member`; the downloaded archive is hashed and that member's bytes must match the report artifact. Do not invent receipt or version fields.
- For irreducible external blockage, item `status:'blocked'` plus `blockers:[{kind:'external',reason,attempts:[{path,sha256}]}]`. Each actual attempt artifact records `obstacle_type` (`access_denied`, `source_not_disclosed` or `upstream_unavailable`), `attempted_at`, `source` and `detail`. Fixable issues remain `IN_PROGRESS`; no unperformed retry may be recorded. Mixed fixable/external gaps require continued work on fixable portions.

The audit returns `COMPLETE` only when every expected ticker has a completed applicable research record, supported decision, nonempty independent factual/numeric checks, resolved artifact/source/dependency links, successful model execution receipts, saved/read-back evidence and a completed queue attempt. It checks finite arithmetic and probability sums; booleans and unchecked-review labels are insufficient. `BLOCKED` is distinct from complete, and a structured action list is emitted for all unfinished tickers. The parent executes those actions with native subagents, bounded parallelism and checkpoints. On runtime interruption, preserve explicit unfinished state and resume; do not call a checkpoint the completed research delivery.

Do not endlessly repeat identical searches. Use bounded retriable-error backoff and try relevant independent recovery paths; document concrete external impediments with actual attempts. Exhausted retries or undisclosed data do not become fabricated model inputs. Report blocked scope honestly and preserve it for reconciliation.

Artifact, schema, reference and arithmetic checks do **not** prove economic reasoning or authenticate self-authored receipt JSON. The parent/reviewer must inspect real tool receipts and actual evidence/model artifacts. Numerical assumptions remain labeled and independently reviewed.

Completion is role-specific: weekly thesis research drains all selected tails; daily reached-price research drains all selected reached names. Price-watch and price-summary roles require their own full rule/symbol coverage, valid data and persisted results, not unnecessary company DCFs. A coverage failure is a failure/blocked scope, never a quiet complete run. Preserve each role's notification policy.

## Deterministic finalization of real review and publication

Use `scripts/finalize_research.py --request REQUEST.json --output-directory FINALIZED [--manifest ALL_SELECTED_MANIFEST.json]`. It only assembles existing author artifacts, independent review/bindings and actual Library save/readback proof; it does not run research, change models, write the database or manufacture a review. The output remains partial without publication proof. The all-selected manifest is preserved; a three-ticker batch cannot make a 28-ticker run complete.

Each request item supplies absolute `record`, `item`, `review`, `bindings`, `run_id`, `input_hash`, and `publications`. Each publication has `artifact_id`, `receipt`, `readback`, optional `archive_member`, and a **fixed actual `confirmed_at`** from the original readback confirmation. Never regenerate this timestamp on retries: that would change the record hash and create needless immutable assessment revisions. Keep the output directory stable when submitting the completion item to the store. Same inputs and fixed confirmation timestamps produce byte-identical output.

Reviewer bindings pin `reviewer_id`, `review_sha256`, explicit `artifact_aliases`, every factual sample's `index/claim_id/source_id/passage_id`, a hashed `review_command_receipt`, and any `extra_artifacts`. Do not guess semantic mappings from prose labels. A stale author artifact is rejected rather than silently rehashed. Resolve it at its producer and rerun affected review if substantive inputs changed. Genuine execution receipts may use `output` or `stdout`; both require successful exit, actual command and nonempty recorded output.

For registration recovery, use ordered idempotent phases: validated evidence/assessment commit, catalog registration transaction, fenced queue finish, guarded remote save/readback. If catalog registration fails after the immutable assessment commit, retry the same payload and skip the already-identical assessment; do not append a new revision simply to repair the catalog. A different substantive payload requires an explicit new revision. Use `INSERT ... ON CONFLICT DO UPDATE`, not `INSERT OR REPLACE`, for catalog parents to avoid deletion/cascade side effects. Preserve unknown security fields and update current-analysis pointers plus supersession consistently. If a lease expired before finish, reacquire valid current-run work and verify the preserved result before finishing; never bypass token fencing or mark an unreviewed task complete. A successful local registration still requires remote version-guarded persistence.

### Atomic batch registration after finalization

Use `scripts/register_research.py --db RESTORED_DB --request REQUEST.json` for a batch of finalized records. This is a local state writer, not another executor. The parent remains responsible for real independent review, remote bundle saves/readbacks and guarded database/catalog writeback.

Request fields: `run_id`, `session`, `config_revision`, `items`. Each item contains paths `completion_item` and `decision`, exact `task_id` and currently valid `lease_token`, `input_revisions`, `baseline_refs`, an explicit `baseline_gap` when none exist, and `analysis_date`. Optional `evidence_ids` maps author source IDs to already committed evidence IDs. The queue identity is recomputed from run/session/config/input hash/ticker. The completion item supplies actual successful report save receipts and readback bytes; the completion auditor rechecks these before writing.

All items in one invocation commit together. Existing evidence is reused at its actual active revision only when its stored source record exactly matches the reviewed source. Changed/retracted evidence requires explicit source CRUD and renewed review; it is never silently rewritten. Assessment, registry metadata and fenced queue completion are committed in one SQLite transaction. Unknown metadata is preserved; superseding a multi-ticker historical section removes only the current ticker from `current_for_symbols`.

For newly registered evidence, prefer an explicitly verified structured `data_asof`, otherwise the known `published_at`. When publication is unknown, preserve its null value and use `retrieved_at` as the observation cutoff with `source_cutoff_basis='retrieved_observation_publication_unknown'`. This does not assert when the page was published or when every displayed statistic became effective. Never infer a date from a filename or free-text reporting period. Known publication/data dates must not follow retrieval, and retrieval must not be in the future.

`research_store.commit(..., manage_transaction=False)` and `task_queue.mutate(..., manage_transaction=False)` explicitly require an active caller-owned transaction. They never commit or roll it back. Any error must propagate to the outer caller, which must roll back the whole transaction. Their default remains unchanged for existing callers. No database proxy intercepts their behavior.

Exact retries retain the immutable assessment revision. A completed queue task with changed semantic registration inputs (or legacy completion without the registration fingerprint) is rejected: create an explicitly superseding, input-aware task rather than silently revising completed work. Expired leases also reject the whole batch; reacquire through the native orchestrator. An error after any write phase rolls the entire invocation back. After local success, save the restored database and exported catalog with fresh Library version guards and verify readback. A remote conflict is not local registration completion: reconcile with the latest saved state and replay the same frozen request only after validating identities. Historical replay never certifies current-price actionability.

## Independent continuation health check

Use `scripts/queue_watch.py --db RESTORED_DB [--as-of TIMEZONE_AWARE_ISO] [--stall-minutes 60] [--output STATUS.json]` from the configured independent scheduled continuation role. It reads the saved queue, immutable progress events and research assessments; it neither changes the database nor starts agents, renews leases, creates schedules or sends messages. The native parent must separately apply due/role policy, recover files, claim and persist valid work before dispatch, and perform guarded writeback. A configured wake is not proof that a worker is running.

Report queue-completed attempts separately from currently verified complete assessments. A valid lease is only a lock, not agent-liveness evidence. Pending work with no valid lease or expired running work is orphaned; 60 minutes without a materially changed checkpoint, finish event or research registration is stalled. Heartbeats and repeated clock-only checkpoints do not reset that clock. Fully cancelled runs are excluded; mixed cancelled/partial runs require explicit supersession review, never automatic resurrection. Missing saved evidence prevents certification until recovery. Even when every recorded assessment passes, run the whole-roster `research_completion.py` audit before declaring the run complete.

Every unfinished research scheduled run must return a concise Chinese status under its configured notification policy; do not hide unfinished/failed coverage behind quiet-success. Use: `【研究未完成】已核验 X/Y；排队 P、有效租约 L（不代表正在运行）、过期 E、阻塞/失败 B。最近实质进展：北京时间 T；停滞 N 分钟。原因：具体缺口。后续：正在执行的恢复动作或明确外部阻塞。` Say an action is underway only after observing it. Keep native output, device delivery and research completion separate. Once all required work is complete, publish the actual result and counts; the health checker itself never claims completion or delivery.

Explicit inheritance is read from saved `job_runs` entries with `kind=research_run_supersession`, `status=skipped`, `superseded_run_id`, `successor_run_id`, `expected_tickers`, `finished_at` and `predecessor_is_complete=false`. The checker verifies that the successor exists, every predecessor ticker is included in the expected roster, and every expected ticker exists in the successor noncancelled roster. A claimed coverage boolean is insufficient. Only a verified entry excludes the predecessor from resume candidates as historical/superseded; it never certifies that predecessor complete. Missing/partial coverage or cyclic inheritance stays visible as a warning and cannot suppress unfinished work. 通知中应说明“旧批次由新批次完整接续，旧批次保留未完成历史”，不可把继承描述成已完成。

Reviewer `artifact_hashes` keys should be canonical author artifact IDs, with the exact hash for that ID. An exact ID key is authoritative and is never reinterpreted as a filename if its hash fails. Legacy basename keys remain supported only when that basename identifies exactly one artifact across the author and extra-artifact sets. Duplicate basenames are rejected even if a hash happens to disambiguate them; pin each distinct ID explicitly. Every resolved `reviewed_artifact_ids` entry must itself be pinned, not merely share another artifact’s content hash.


## All-run monitoring admission

After an actual scheduler update and independent readback, set `research.monitoring_contract` to
`{required:true, scope:"all_current_and_future_runs", scheduler_readback_verified:true, automation_id:<readback identity>}`.
Keep the matching `research_queue_continuation` schedule and notification policy enabled. Call
`task_queue.configure_monitoring(db, required=True)` and persist the database with its version guard.
This setting is database-wide, covering future run IDs without ticker-specific rules. `enqueue` and
`claim` then reject missing/invalid adjacent workflow configuration, an unverified monitoring contract,
or a disabled/mismatched continuation role. Missing config cannot silently fall back to unmonitored work.
The compatibility migration defaults to disabled for existing generic/isolated fixture databases;
production enrollment is an explicit validated step. Full-research holds still apply only to their run
IDs; separate screening runs remain claimable. A saved readback assertion is admission evidence, not
an API check or guarantee of future scheduler uptime. The orchestrator must refresh real scheduler
state and report missed execution or stalled progress. This guard does not execute agents, send alerts,
or replace completion/persistence gates. Disabling the guard requires an explicit policy change.

## Pre-return continuation gate

Run `continuation_gate.py --db PATH --request SCOPE.json --phase-archive EXACT_ARCHIVE ... --output GATE.json` before ending each active research turn. Request `task_ids` explicitly covers the current user-selected work; preserve cancellations and frozen task identities. Supply the same recovered archives as queue_watch. Prefer exact saved versions. For bounded-triage only, a later cumulative version of the same Library file may recover an older card when the frozen card hash and independently accepted review hash match byte-for-byte; this does not relax targeted-stage whole-archive bindings or certify full research. Exit2 / CONTINUE_REQUIRED means the parent must execute the next action in this turn. Stage acceptance is not an end condition. A running worker or valid lease likewise is not permission to abandon the active workflow. Follow accepted cards into linked next-stage tasks with guarded claims before dispatch; keep the parent active through review and persistence. Never wait for the hourly monitor when independent work is executable now.

Only `completion_manifest` pointing to an actually passing research_completion manifest for the identical selected run/roster/database certifies full completion. Otherwise the optional `dispositions` mapping is keyed by task ID; each value is `{path,sha256}` for a durable JSON record with task_id, frozen task_fingerprint (from task_queue.read fingerprint), recorded_at, reason and reopening_condition. Allowed kinds:

- `user_hold`: exact user_instruction and scope; never infer it from a general full-run budget hold.
- `event_wait`: hashed evidence_refs, a future recheck_at, and independent_work_remaining=false. A due recheck is actionable again.
- `external_blocked`: hashed actual attempt JSONs with obstacle_type, attempted_at, detail, and independent_work_remaining=false. Preserve source/access/runtime facts; uncertainty or missing modeling effort is not external blockage.

A “pending”, token-saving, budget, or heartbeat label cannot clear the gate. SAFE_TO_RETURN for a wait/block/cancellation is explicitly not completed research. Validate dispositions semantically against real evidence; hashes only establish integrity. On a platform-forced interruption preserve the current checkpoint and precise remaining work, never manufacture a clear gate. This is an enforced workflow instruction and CLI exit status, not a platform lifecycle hook or daemon.

Observe native agent status before a handoff. `send_message` delivers context but does not restart a completed/idle agent; use `followup_task` for actual new work on such an agent, after the durable claim is saved. Do not count a message, dispatched name, or valid lease as an observed running worker. Recheck status/output and recover the handoff rather than waiting for a reply that cannot execute.
