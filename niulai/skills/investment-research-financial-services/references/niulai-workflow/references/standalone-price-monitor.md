# Standalone price monitor

Policy: 2026-10-20-session-range-1. User authorized full migration and larger leveraged-fund buffers. Daily operation has zero dependency on Price Alert Studio. Do not deploy or modify that Site. Keep historical records; never infer no market hits from missing evaluation records.

## Inputs and execution

Resolve latest workflow.json, alerts.json, alerts.sqlite and research.sqlite from state-locations.json, retaining each actual Library version. Alias names containing mirror are legacy registry keys; the saved alert JSON and SQLite are now authoritative. Read actual configuration enabled gates and exact role identity before execution. `price_watch.py` validates input before network calls. Install pinned requirements.txt only if needed. It uses Python stdlib plus exchange-calendars4.11.2.

Run: `python3 scripts/price_watch.py --config <workflow.json> --rules <alerts.json> --db <alerts.sqlite> --role daily_price_watch|existing_summary --mode live --output <result.json>`.
Do not supply historical --as-of for live mode. Daily wake times remain12:55/15:55 New York and evaluate in the actual XNYS last ten minutes or120seconds after close. Summary slots remain13:00/19:00 New York, allowing saved60minute grace. If retry_after_seconds is returned, wait in increments at most60seconds and rerun using actual time, at most120seconds total. This handles a slightly early task without moving the market gate. Otherwise skip non-due/holiday/weekend quietly. Report calendar failure, never replace it with weekdays.

Summary now collects/evaluates direct prices itself, so a missed near-close wake cannot silently turn the19:00 report into an empty-history report. During market hours use completed5minute regular-session bars with maximum20minute lag. After close use the exact completed session daily range and close; distinguish a session close from a live after-hours quote. Never use later-day prices at an earlier cutoff. Split events after rule revision require threshold review, not automatic alteration.

## Signal meaning

Base approach band is0.5% of threshold, multiplied by the configured absolute daily leverage:2x=1%,3x=1.5%. Per-rule buffer_fraction overrides this. This is a transparent monitoring heuristic, not calibrated volatility or an investment entry recommendation. Verify leverage from issuer sources before changing the map. Preserve the underlying threshold; report threshold_reached separately from zone_reached.

For below100 and0.5% band, prices at or below100.50 reach the approach zone; at or below100 reach the original threshold. Above uses99.50 as the approach edge. Overshoots and gaps qualify; exact equality is included. A verified previous-session close outside the zone or an observed regular-session opening outside followed by a reached range supports directional entry. A daily high and low alone cannot establish order, crossing time or repeated crossings. An already-in-zone first observation is a separately labeled level condition, not a fabricated new crossing. Repeated samples are deduplicated per session, rule revision and signal classification. Daily re-notification is intentional; no intraday oscillation/rearm alerts.

Rule edits apply only when effective for the entire evaluated session; otherwise report the partial-session eligibility gap. Disabled rules are excluded. Preserve original timestamps and notes. Expired rules are not eligible. Do not infer leverage, adjust thresholds for splits, activate disabled research drafts or substitute ETF proxies.

## Persistence and notification

price_runs stores execution/results; price_sources retains retrieved raw data/URLs/timestamps; price_signals stores deterministic event IDs and unconfirmed delivery. Replay never inserts price_signals. Existing alerts and research tables remain intact. Save updated alerts.sqlite to its SAME Library identity with the retained version guard. Record this run in research.sqlite with niulai_state record-run and persist it guarded. Do not rebuild an old database over a newer file. A save failure is a material coverage/state failure even if prices were fetched successfully.

Daily: only new zone/directional signals or material failures; distinguish approach-only, threshold reached, and already in-zone. Summary: show session, coverage, applicable levels, current close/quote and whether still in-zone; include zero only for checked scope. Rolling counts are stored live signals since migration, not complete historical market crossings; label missing pre-migration coverage. No account IDs or delivery receipts are invented. Native output is unconfirmed delivery, never a phone receipt. Dashboard links are not required.

## Historical correction

Run `--mode replay --as-of <original UTC cutoff>` with a separate output and replay ledger key. Current source data reconstructs past session ranges, not what the provider showed at original send time. Retain original report unchanged and label correction. Use archived rule revision or disclose current-rule reconstruction. Report missing/invalid symbols explicitly. No fabricated original notification or exact crossing time.


## Resilience implementation 2026-10-22

Use the same `price_watch.py` live command and existing_summary role. When the saved
`price_monitor.late_run_recovery.enabled` is true, an outside-slot invocation on an
XNYS session catches up the latest elapsed summary slot on that same New York date.
Before the first slot and on non-session dates it remains quiet. This catch-up uses
actual current cutoff, the same date/slot dedup key, `delayed_catchup=true` and
`retrospective=true`, and inserts NO live signals. Label the actual source cutoff;
it does not reconstruct what prices were at the missed slot. A 19:00 summary does
not retroactively mark the missed 13:00 slot completed. This built-in path supersedes
the prior temporary-DB manual catch-up instructions; normal guarded saves persist
its clearly marked execution and sources in the authoritative DB.

Each HTTP operation retries only transport failures/408/429/5xx transient errors,
at most three attempts with 12-second socket timeouts and 1/2-second backoff.
Permanent HTTP failures and invalid financial data do not get validation bypasses.
Three source workers remain bounded. Each finished symbol's raw response/error is
committed immediately beside a `collecting` run, so another symbol or finalization
failure does not erase fetched evidence. A collecting run is NOT completed, is not
a publication receipt, and can be retried; never reuse stale intraday evidence.
Final CLI output is atomically replaced, with structured failure status on runtime
errors. Local checkpoints still require a guarded remote save to survive environment
loss; save partial DB/report on failure whenever access remains available.

Do not shut down the sole recurring summary for an isolated network or provider
failure. Publish explicit failed scope, retain partial state, and allow the next
existing wake to try again. Do not create another sender or retry indefinitely.
No code can guarantee scheduler execution or phone delivery. Keep persistence and
native-output/device-delivery status separate and never silently mark partials done.

## Authorized research alert edits

Use `scripts/price_alert_crud.py`, not ad-hoc JSON rewrites. Supply a `reviews` object keyed by ticker: purpose (`research_review` or unchanged `legacy_price_only`), security_type, author and distinct reviewer, reviewed_at, hashed `model`/`review` file references, entry_basis. Leveraged entries require covered reset/benchmark/cost_ledger/favorable_trend/chop_and_crash/unlevered_comparison/mean_median_tail/probability_status/entry_conditions and underlying_value_and_path_and_cost basis. Legacy-only updates preserve threshold/direction and explicitly set buy_recommendation=false. These fields validate evidence presence, not economic truth; inspect the artifacts. Preserve IDs/history and guarded Library JSON/SQLite writes; compare readback and untouched rules.

Price outputs retain rule notes, review range, research reference, entry conditions and expiry. Where `entry_conditions` is present, price-only evaluation reports `requires_research_recheck_not_evaluated_by_price_engine`; it does not claim companion fundamentals/benchmark conditions passed. Include those conditions in the notification. Entry decision artifacts must specify action, as_of/valid_until, horizon_days, required_return and bands matching the exact rule threshold/direction. Each band links a hashed calculation and lists conditions/invalidation; leveraged bands also record anchor, underlying_condition and pre_entry_path_assumption.

## Full colored reporting and quality fallback — 2026-10-23

Use scripts/price_report.py RESULT_JSON REPORT_HTML after every evaluated summary. Save/link the colored HTML (CSV optional). Include all satisfied rules in the native message, never a five-ticker cap. Separate actual new_signals, directionally supported entries, current in-zone without new crossing proof, approach-only, exited and invalid data. First observation cannot prove persistence; a replay has no new live events. Colors encode price status only: green satisfied, red not reached, amber incomplete range/approach/exited, gray unusable data. Preserve every rule and source/time/threshold/conditions; include quote-only coverage distinctly.

Malformed daily open outside range can degrade ONLY to actual corroborated close when low<=close<=high, same-provider regularMarketPrice agrees within half a cent and its regularMarketTime is between the actual close and close+10min, no later than cutoff. Do not synthesize extrema, repair open, claim full-day coverage or infer directional entry. Missing corroboration remains a failure. Keep raw source, null extrema, scope warning and partial status. This is a field-level fallback, not independent-vendor validation.

price_monitor.quote_only_symbols collects requested names without fabricating thresholds or buy signals. Quote-only coverage is not alert coverage. For names without a current reviewed alert, show that gap and their actual quote. Historical research tiers need dated validity/model/review checks before activation through CRUD. Use one native task conversation for desktop and mobile; publishing is not proof of either device receipt.
