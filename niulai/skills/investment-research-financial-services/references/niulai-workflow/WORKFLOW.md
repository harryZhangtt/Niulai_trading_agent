# 牛来 workflow

Use the installed investment-research-financial-services skill for methodology. Use this module for state and execution. Read [Runtime contract](references/runtime-contract.md) before database, schedule or alert changes. Read [State registry](references/state-locations.json) for current persistent identities and pins. The filesystem is a working copy, not a durability guarantee.

## Load current state

1. Resolve current configuration and research database from the exact Library identities in the registry. Read/materialize the latest version using the Library skill; never overwrite a newer local edit. Retain versions and source timestamps.
2. For config revision7 onward, saved alerts.json is the rule authority and alerts.sqlite holds detection runs, raw sources and signals. Do not call Price Alert Studio for scheduled monitoring or edits. Older Studio data is retained as an archive only. Saved rules, observed crossings, scheduled execution, chat acceptance and device receipt are separate facts.
3. Verify methodology from /root/.codex/skills/remote-skills/skill-6ac09cdd37548191878e9489037b0c52. Record actual git HEAD, policy versions, input cutoff and configuration revision for each research run. Preserve reviewed upstream pins; propose upgrades rather than pulling unreviewed main.

## Maintain records

Use scripts/niulai_state.py with --root /root/niulai/runtime or a task-specific recovered directory. It has no network, quote or send side effects.

- init, status, export: pass --root.
- import-research and import-alerts: pass --root and --file PATH.
- plan-alert-sync: pass --root, --desired alerts.json and --observed observed_alerts.json.
- record-run: pass --root and --file run.json for an immutable final run record; get-run accepts --root and --id. Repeated identical run IDs are no-ops; conflicting retries require distinct attempt IDs.
- validate-config: pass --root and --file workflow.json before applying configuration changes; validation never activates a schedule or alert.

After publishing stock research, register exact persistent file ID/version, security relationships, dated section/page range, source/price cutoff, model/policy revision, limitations and supersession. Old filenames or upload times are not research cutoffs. A mention is not completed research. Never turn research entry prices into enabled alerts without the user's instruction.

Preserve unknown versions/hashes as unknown. Reject stale versions, conflicting opaque versions and invalid relationships. Export editable JSON; obtain fresh app observations before alert edits. Omission does not mean deletion. Preserve disabled rules, UUIDs, notes and directions; use finite positive Decimal thresholds. Apply only the authorized diff through app tools, reread actual state and refresh mirrors. Editing JSON alone changes neither D1 nor a scheduler.

## Run scheduled checks

For the standalone monitor, read [Standalone price monitor](references/standalone-price-monitor.md). This supersedes earlier Studio-based daily/summary instructions for config revision7 onward. Use `scripts/price_watch.py` for deterministic evaluation. Load and validate the current saved workflow, alerts JSON and alerts SQLite by exact registry identities before running; recover their runtime filenames. Never create an empty database and call it restored.

The daily and existing summary roles use the same script and database. They fetch direct Yahoo chart data, use XNYS sessions, and persist source payloads and results without any Studio dependency. No secrets, trades or broker holdings refresh are needed. Keep native notification delivery unconfirmed; no separate message sender is used. Missing data is a coverage failure, not zero triggers. The script distinguishes approaching a threshold, reaching it, remaining in-zone and supported directional entry. Never relabel one as another.

Persist alerts SQLite and run records with retained Library version guards. On conflict, recover newer state and reconcile event IDs; never blindly overwrite it. Save rules JSON only for an authorized edit. Keep daily quiet-success and scheduled summary policies distinct. Do not send a duplicate completed slot. Replay is a separately labeled retrospective correction and inserts no live events.

## Weekly thesis, EV and bet review

For weekly top/bottom performer scans, read [Weekly review contract](references/weekly-review.md). Use scripts/weekly_scan.py for calendar-correct adjusted-close ranking and scripts/weekly_history_adapter.py for auditable public history collection. Freeze the saved research universe and run the selected names through evidence and model availability gates. Keep price-only, fundamentals, correction and judgment effects separate. BAT is a proposed bet/position action; never execute it or turn research entries into alert rules automatically.

## Daily reached-price research

For the `daily_triggered_research` role, read [Daily reached-price research](references/daily-triggered-research.md). Reuse `scripts/triggered_research.py` for deterministic selection, bounded batches and result checks, and the existing research harness for evidence, models and independent review. Review every reached enabled ticker, compare new evidence against its actual baseline and distinguish substantiated market-expectation differences from public narratives or no new edge. Keep slow research independent of price summaries. Proposed EV, entry tiers and tranche weights require the applicable model and portfolio gates; neither a reached alert nor a populated template authorizes a buy or rule edit.

## Manage versions and recovery

Keep code/instructions in private personal Skills git; validate, commit and push scoped changes. Keep private databases, research records, alert snapshots, run logs and credentials out of Skills git.

The full /root/ai-berkshire clone is a pinned upstream reference, not the active adapted package. Recover it at the locked commit if absent. Review upstream changes before promotion.

Save runtime updates to existing persistent file identities with retained version guards. Recover lost runtime from latest stored data, then reconcile alerts with live D1. Never initialize empty data and call it recovered. Report code tests, database integrity, saved configuration, saved automation, actual scheduled execution and device delivery separately.

## Mandatory earnings/probability/entry evidence extension

For each new or resumed full pipeline, execute [valuation evidence policy](../valuation-evidence-policy.md). Record `valuation_evidence` before finalization. Preserve old published records; do not claim they passed this newer policy. Reuse existing research and applicable fund mechanics; never force optimistic weights or technical confluence.

## Cost-aware entry override

For scheduled/batch candidate research, apply [research triage](../research-triage.md) before full-work claims. Harry's 2026-10-20 cost instruction supersedes full research on every reached-price candidate. Honor current `research.triage.held_run_ids` and preserve unfinished history. Route reuse, repricing, bounded probes and targeted deltas separately; only selected decision-relevant cases enter full research. Explicit deep-dive requests and completed recommendations retain full applicable gates. Do not claim 80% savings until measured.
