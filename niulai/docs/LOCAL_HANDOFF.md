# Local execution and cutover

## Authoritative snapshot

Workflow revision30, alert JSON version7, alerts SQLite version18, research SQLite version197, portfolio bundle4, project checkpoint21 were recovered. The two SQLite files passed integrity checks. There are94 stored rules,87 enabled,7 disabled; the rule JSON and SQLite payloads match. The snapshot preserves expired DRAL rules rather than renewing them.

Read the exported current workflow before historical registry documentation. The installed state registry contains older scheduler IDs; `late_run_recovery.mode=explicit_replay_temp_db` is stale/non-operative. The actual engine uses same-database catchup. Worker count3 and quote freshness1200s are code constants; similarly named JSON fields do not make those values dynamically configurable.

## Price engine

```bash
python3 -m venv .venv-price
.venv-price/bin/pip install exchange-calendars==4.11.2 pandas==2.2.3
# Only after restoring original runtime files into an external private directory:
.venv-price/bin/python skills/investment-research-financial-services/references/niulai-workflow/scripts/price_watch.py \
  --config "$NIULAI_PRIVATE_DIR/workflow.json" \
  --rules "$NIULAI_PRIVATE_DIR/alerts.json" \
  --db "$NIULAI_PRIVATE_DIR/alerts.sqlite" \
  --role existing_summary --mode live --output "$NIULAI_PRIVATE_DIR/result.json"
```

The engine uses actual time and XNYS gating, does not send email, and does not install a scheduler. Do not override timestamps for live execution. `niulai_state.validate_config` still expects the native transport; a local transport requires an explicit reviewed adaptation, not pretending it is native.

## Holdings/report dependencies

```bash
python3 -m venv .venv-holdings
.venv-holdings/bin/pip install --no-cache-dir -r holdings/requirements.txt
```

The recorded direct pins are tigeropen3.8.0, exchange-calendars4.11.2, pandas2.2.3, reportlab4.4.9, cryptography50.0.2. This is **not a complete transitive hash lock**. The source contains the local read-only `niulai_tiger.py` adapter and file lock. The current production `private_profile.py --mode run` still requires native Sites owner validation and a service bearer; it is not a local scheduled entrypoint. Do not use `--local-bootstrap` as an undocumented production bypass. Select and validate a local profile backend explicitly before recurring use.

`price_summary_view.py`, `render_price_pdf.py`, `compose_digest.py` and fonts are under `holdings/`, not the price skill. Keep them together. The composer constructs a MIME tree, not a Gmail SMTP/API sender.

## Research

Read `skills/investment-research-financial-services/SKILL.md`, then the research harness, applicable financial policies and current checkpoint. Schemas use their own `schemas/requirements.txt`; optional option-model pins are in `references/niulai-workflow/requirements-options-*.txt`; DCF validation has its own requirements. Preserve upstream versions and licenses. Do not install every GitHub URL mentioned in methodology—many are references rather than runtime dependencies.

The current checkpoint is NOT_DONE and experimental production activation is DISABLED. Its top-level next action is the matched cash-completeness development probe, with no new case admissions. Nested older next-action fields are historical, not competing current commands. Keep native usage null until an actual model provider receipt exists.

## Interfaces still requiring local implementation/verification

| Interface | Existing behavior to preserve | Local acceptance |
|---|---|---|
| Scheduler | America/New_York13:00/19:00; actual XNYS;60-minute grace | DST/holiday/duplicate-slot tests; no second sender |
| Durable state | Version-guarded writes, immutable IDs, raw payloads | Single writer/lock, atomic SQLite backup, failed-send reconciliation |
| Broker auth | Read-only SDK, exclusive refresh, durable rotations | Two independent-process reads and refresh persistence |
| Gmail | Verified recipient, prepared then sent ledger, full body,2PDFs | Own OAuth adapter, ambiguous-send lookup, no blind retries |
| Research model/tools | Frozen instructions, source budgets, actual traces, review | Local provider+retrieval adapter; delivered settings/usage receipts |

## Cutover checklist

1. Verify manifests; restore private state outside Git; preserve original IDs.
2. Run offline regression suites on a fresh local environment; keep skips/failures explicit.
3. Run one manual read-only local dry run with sending disabled. Reconcile every rule and holding, source times and missing data.
4. Verify auth rotation in a second independent process, plus full email MIME offline rendering.
5. Test one explicitly labeled email and saved send receipt; do not mark a scheduled slot complete from a manual test.
6. Explicitly disable the old cloud sender immediately before enabling the new local schedule, carrying over dedup state. The migration export itself has changed neither.

No live local broker/model/mail execution was performed during this export. Successful unit tests are not evidence that these missing interfaces are deployed.
