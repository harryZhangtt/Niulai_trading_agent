# Research web access candidate

Native search discovers sources; native open reads ordinary pages; a configured
EgoLite reader handles approved rendered/session-dependent pages; existing PDF
handling stays separate. `policy.Session` owns per-task circuit/deadline/read
state. The host must actually invoke native tools and record their outcomes.
This package does not intercept Codex tools or change browser defaults.

`candidate.json` is disabled. `egolite.read` executes only the pinned, authored
navigation/snapshot script and returns immutable private observation references.
Rendered extracts are not promoted to full-document evidence. Browser/network
containment remains a separate boundary; see the explicit limits in the runbook.

Use [deployment/recovery guidance](../../docs/deployment/web-access.md) and the
[matched A/B protocol](../../tuning/evals/browser_cooperation/README.md). Component
checks use a fake local CLI; a live browser result is still required before
adoption. No new action registry, MCP entry or package installation is supplied.

## Quota-aware discovery coordination

`policy.Session` now also provides an inert host-owned discovery coordinator for
fan-out research. Share one Session across the task, pass the exact query to
`plan(operation="discover", query=...)`, and record the terminal result with
`record_discovery`. It deduplicates concurrent exact queries, caps native search
reservations, bounds transient retries, treats shared quota exhaustion as
nonretryable, and plans authorized browser discovery as the fallback.

The coordinator does not call WebSearch or EgoLite, persist provider output, or
intercept arbitrary agents. The host saves the result and supplies its SHA-256.
No browser, hook, daemon, MCP server, credential, or user setting is activated by
this source change.
