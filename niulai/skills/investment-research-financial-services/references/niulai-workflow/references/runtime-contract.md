# Runtime contract

Version: 2026-10-20-workflow-3

For configuration revision7 onward, the current contract is [Standalone price monitor](standalone-price-monitor.md). It overrides the archived Studio-dependent daily, summary and authority requirements below. Saved alerts.json and alerts.sqlite are authoritative; no Studio tools, secrets, dashboard, rules service or quote gateway are used. The existing research database and reports retain their identities and history. Preserve prior records; the following text documents the pre-migration system only.

## Archived pre-migration contract (not active for revision7+)

# Runtime contract

Archived version: 2026-10-18-workflow-2

## Authorities

Research records: latest saved research.sqlite; reports: exact Library file IDs/versions.
Alerts and crossings: existing private Price Alert Studio D1; SQLite/JSON exports are mirrors.
Schedules: actual automation receipts and peek readback; workflow.json controls applied schedule and per-role message policy. The user authorized migration of the remaining Site-specific summary to configuration-managed native output on2026-10-18.
Methodology: installed financial-services adapter; upstream clone is a reviewed reference.

Use references/state-locations.json for persistent identities. Editing a JSON does not itself alter backend rules or schedules. Apply a validated user-authorized change through tools and reread state.

Theme tags describe research context and do not certify a company's direct exposure. Preserve section-level distinctions. Use record-run/get-run for immutable final execution records. A completed record proves evaluation, not native notification receipt; store delivery state separately.

## Revisions and recovery

Record schema/config/input revisions, source cutoff, actual skill git commit, policy versions, reviewed upstream pin, run ID and idempotency key. Use SQLite transactions/foreign keys and Decimal threshold text. Preserve unknown metadata, historical report versions and dated section supersession. Duplicate imports are no-ops; stale or conflicting revisions require reconciliation.

On a new machine, resolve the registry, materialize latest configuration/research DB with the Library skill, obtain current alerts from D1, import/export mirrors and check integrity. A local path alone is not durable storage. Save updates with retained version guards. Keep runtime data and credentials outside Skills git.

## Alert changes

Read live definitions, retain the exported observed_fingerprint, and run plan-alert-sync against fresh observations. Reject stale fingerprints and ambiguous IDs. Upsert only user-authorized changes and reread exact IDs/thresholds/enabled states. Never infer delete from omission or weaken unsupported expiry/session/one-shot restrictions. Research prices do not automatically become alerts.

S&P 500 index points differ from SPY/VOO ETF dollars. Missing index thresholds/provider symbols remain disabled drafts; never guess a live rule.

## Daily check

The watcher wakes at 12:55 and 15:55 America/New_York on weekdays. The XNYS gate permits evaluation only within ten minutes before the actual session close, or at most 120 seconds just after close with provider freshness still required. Normal days use 15:55; early-close days use 12:55; holidays skip. No local daemon is installed.

Read enabled unique symbols from D1 each run; do not freeze today's counts. Batch with bounded concurrency and retain every error. No Tiger refresh is needed. Stale/unsupported quotes are coverage failures, not zero triggers. Classify baseline, new crossing, no event, source failure and delivery unconfirmed.

Notify through native scheduled-task output. No direct chat-send receipt API is currently exposed, so do not invent delivery IDs or call D1 claim/ack for that output. Leave old claimed/unconfirmed items for reconciliation. The existing summaries may show pending events as pending. Do not automatically replay historical notifications.

Reuse the existing read-only summary at the latest configured times and timezone identity as a configuration-managed native ChatGPT task. Do not retain its obsolete direct-Site prompt or create a duplicate sender. Preserve the legacy hourly-monitor identity even when absent from the accessible task inventory. This newly requested daily watcher is the configured fallback; shared D1 evaluations deduplicate crossings. Daily checks are not continuous or ten-minute monitoring.

## Research and skill maintenance

Register new research artifacts after publication. A price watcher does not run a full DCF. Enable additional research schedules only after their actual automation receipt is saved. The weekly top/bottom20% review is now user-authorized; read weekly-review.md for its execution contract. Use pinned source versions and meaningful checks before promotion; changes in evidence, modeling corrections and investment judgment require separate attribution. Never fit scenario weights to obtain a buy.

Configuration saved, scheduled evaluation observed, native notification accepted and device receipt are separate acceptance gates. Report missing proof plainly.

## Configuration-managed notifications

Every reachable role loads and validates the latest saved configuration before external calls. Resolve its exact schedule role/automation identity and notifications.policies role. Missing/disabled roles or disabled message policies stop quietly. Missing/invalid configuration produces a scoped failure, never fallback to an old direct-Site prompt. Enforce configured due slots; daily uses XNYS close gating. The weekly and summary slots allow at most the saved60minute grace. A JSON cadence change still requires scheduler update and readback to add wakeups.

Policies are per role: daily suppresses quiet success; the existing summary reports quiet days if configured; weekly reports reviewed scope even without a material change. The old Site is the source of rules, quotes and crossing history plus optional dashboard, not an independent message controller. Do not change77 alert definitions during this notification migration.

The existing summary is read-only. Use pinned asOf snapshot pagination and full aggregates for configured today/3d/7d/10d windows; keep source, coverage and holdings age visible. Unavailable/stale source is not zero events. Historical pending events in a digest are not new crossing sends. Deduplicate immediate alerts by event/rule revision, and summary runs by date in the configured schedule timezone plus slot; record config revision separately so an edit does not resend the same completed slot. A completed record does not prove delivery. Never fabricate D1claim/ack or device receipts from native output.

Summary timezone follows schedules[existing_summary].timezone (currently America/New_York) and its DST rules, independently of the user display timezone and weekly review clock. The Site snapshot today boundary is fixed to Asia/Shanghai: label that source window explicitly instead of calling it a New York market-day count.
