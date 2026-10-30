---
name: impeccable
description: "Design, critique, audit, polish, harden or animate a frontend using the pinned Impeccable playbooks while preserving the target design system. Local manual-context adaptation; no engine, hooks or global installs."
metadata:
  upstream-version: "4.8.0"
---

# Impeccable: workspace adaptation

Preserve the requested scope and existing product truth. Operate-mode dashboards
and editors prioritize scanability and familiar interaction; marketing and
portfolio surfaces can carry a stronger visual direction. Inspect the actual
rendered incumbent before refining it. New work uses deliberate typography,
layout and palette grounded in its real subject. Verify by looking at the render
at the sizes it ships at, batching fixes between checks.

Read the target project's existing PRODUCT.md and DESIGN.md when present, plus
its tokens/components. Absence of a document does not prove greenfield design.
This package intentionally replaces the upstream engine's context command with
manual context inspection. No engine binary, hook, live annotation, automatic
update, pinning or doctor installation is enabled. Do not invoke those commands
from retained reference examples. For browser work use the local Playwright route.

Load only the playbook for the current decision:

| Decision | Playbook |
| --- | --- |
| New surface or replacement visual world | [new-work](reference/new-work.md) |
| Existing task-oriented interface | [operate](reference/operate.md) |
| Technical audit | [audit](reference/audit.md) |
| Errors, input extremes, network and concurrent state | [harden](reference/harden.md) |
| Final refinement | [polish](reference/polish.md) |
| Purposeful motion | [animate](reference/animate.md) |
| Layout, typography or copy | [layout](reference/layout.md), [typeset](reference/typeset.md), or [clarify](reference/clarify.md) |

Read [craft-floor](reference/craft-floor.md) immediately before actual UI edits.
For unknown async writes, drafts or entity races also use the separate local
async-state-reliability skill. Heuristic audits and playbooks do not establish
application correctness, full accessibility conformance or reliability; verify
observable behavior with the component's executable checks.
