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
