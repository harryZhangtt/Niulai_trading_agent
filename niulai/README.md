# Niulai local migration export — 2026-10-30

This is an audited source/configuration handoff, **not a completed standalone deployment**. It exports the existing implementation without silently activating Shadow experiments. No broker refresh, trade, email send, scheduler change or model research was performed for this migration.

## Start here

1. Read `docs/LOCAL_HANDOFF.md` and `docs/SECURITY.md`.
2. Keep this source repository private initially. The accompanying **private state backup** must stay outside Git, including private Git repositories.
3. Restore your original `workflow.json`, `alerts.json`, databases and checkpoint from the private backup into a local private directory. Do not initialize empty databases as a substitute.
4. Install the existing pinned dependency sets in separate virtual environments. Run offline checks before connecting broker/model/mail credentials.
5. Replace the explicitly identified host interfaces; validate the first local end-to-end run and dedup before switching schedules.

## Contents

| Area | Location | Status |
|---|---|---|
| Price rules, market calendar, source checks, event/dedup logic | `skills/investment-research-financial-services/references/niulai-workflow/` | Existing deterministic engine exported |
| Holdings reader, transaction reconstruction, P&L, charts, PDF, MIME | `holdings/` | Existing code exported; scheduled auth wrapper remains host-dependent |
| Full investment skill, eight workflows, DCF/three-statement, options/crypto, guards, schemas | `skills/investment-research-financial-services/` | Installed source snapshot, not a standalone model server |
| Shadow policies/experiments | `shadow/` if present; full historical evidence in private backup | Experimental, not active production defaults |
| Audit receipts and dependency inventory | `docs/audits/`, `MANIFEST.json` | Original pass/fail/unknown distinctions retained |

Original production settings are preserved in the private archive. Owner email and credential-store integration identifiers in exported documentation/code are replaced with placeholders; `docs/redactions.json` records exact changed-file hashes. Original source remains in the private archive for provenance. Upstream license and pinned manifests are preserved.

## What is not an executable guarantee

There is no proven exported standalone `financial-agent` model dispatcher, native browsing connector, Gmail OAuth sender, or ChatGPT scheduler/Library service. Prompt instructions do not implement those services. Actual backend model/effort/usage receipts were unavailable in the original research experiments; no efficiency or Alpha gain is claimed here.

The protected AerCap holdout is retained by reference only. It must not be opened for development. Historical research reports referenced by the research database are indexed; not every company report is embedded in this source repository.

## Local provenance check

Run `python3 tools/verify_export.py` to verify the export's per-file SHA256 manifest. Run `python3 tools/security_scan.py . --output /tmp/niulai-security.json` for bounded accidental-secret/private-file checks (see its command help if arguments differ). These checks do not replace credential management or prove production runtime correctness.

Existing cloud automations have **not** been disabled. Do not enable a second automatic sender before the cutover checklist passes.
