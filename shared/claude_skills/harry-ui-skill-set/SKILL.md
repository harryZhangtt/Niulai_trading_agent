---
name: harry-ui-skill-set
description: "Harry UI for Claude Code: selectively route frontend implementation, React state/rendering, responsive layout, accessibility, visual polish, animation and browser verification to the maintained 22 UI experts. Excludes backend-only and prose work."
---

# Harry UI for Claude Code

This is the Claude Code entrypoint, not the installed Codex persistence wrapper.
It uses the same maintained UI experts and selective resolver in this checkout.
Invocation loads guidance; it does not create a native sticky mode, a Codex
receipt, an automatic hook or a background quality service.

## Locate source and target separately

Use the real directory containing this skill as `<skill-dir>` (resolve its
symlink). The maintained source checkout is three directory levels above it:

```sh
python3 -B -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve().parents[2])' "<skill-dir>"
```

Call that returned absolute path `<source>`. The project the user is working on
is `<target>`; do not confuse it with the source checkout when used elsewhere.
Read `<source>/ui/AGENTS.md` and `<source>/ui/ROUTING.md`, then select only the
procedures needed for the current task. Follow the target's instructions, stack,
design system and permission boundaries. Source policies about Codex hooks and
thread receipts describe Codex only, not this Claude session.

## Route the current UI decision

Use absolute paths; no classifier request or full-catalog load is needed:

```sh
python3 -B "<source>/ui/route.py" --decision async-state --decision react-performance --decision browser
```

Replace the example selectors with the actual decisions. The resolver returns
source-relative paths: read only `<source>/<returned-path>` and necessary
references, using absolute paths for reads. Choose one visual authority.
An ordinary race/render/overflow repair does not need a new-page workflow.
`UI_ROUTE_OK` verifies resources/selections, not actual browser or tool execution.
Missing tool prerequisites remain blocked; `--guidance-only` does not prove they
work. Resolve source-relative helper paths under `<source>` and direct all target
changes, dependencies, caches, screenshots and state to explicitly authorized
locations in `<target>`. Do not install global dependencies or activate MCP to
make a guide available. Checkout-specific tooling requires inspection before use
in another project; a skill installation does not install that project's tools.

## Live-browser debugging safety

**Scope: read-only applies while a browser probe inspects/debugs a live system.**
It prohibits that probe from changing live data, configuration, or other remote
state. It does not prohibit the user's requested local implementation, code edits,
refactoring, or local tests. Those remain governed by the task's authorization.
Local tests must not silently perform live writes; live write testing requires
separate explicit authorization. The no-credential-export and artifact-audit
requirements still apply to all evidence produced by the live probe.

- **Read-only means enforced, not promised.** Before navigating or interacting
  with a live page under a read-only request, install a fail-closed interception
  guard scoped to the agent's probe tab. Allow only inspected read endpoints and
  explicitly identified read operations. Block all unknown or write-capable
  requests, uploads, GraphQL mutations, and non-allowlisted RPCs. A GraphQL
  `query` or HTTP GET is not sufficient proof: compatibility roots such as
  `fetchRPCData` can dispatch writes, so inspect nested operation/config values
  and use an exact read-method allowlist. Keep the guard active throughout the
  probe; do not relax it simply to make the page load. If the browser cannot
  provide reliable interception, limit work to passive inspection and report
  that active read-only probing is not enforceable.
- Do not click Save, Confirm, Create, Delete, Import, Publish, or Favorite during
  read-only debugging. Opening a panel to inspect its layout/configuration is
  permitted only under the active guard. This limits the live probe, not local
  application development: continue authorized local code changes and tests
  without treating the probe's read-only restriction as a repository-wide freeze.
- Do not export, copy, or persist credentials, cookies, browser storage state,
  authenticated profiles, authorization headers, or signed session material
  into the target repository, including ignored directories and probe artifacts.
  Use the browser's existing authentication in place. This overrides the general
  workspace-local artifact rule above for sensitive authentication material.
  Do not save raw HARs, traces, request dumps, screenshots, or responses that may
  contain secrets; capture only allowlisted, sanitized evidence. Never print
  secret values in tool output, documentation, or logs.
- Stop for browser-owned approval prompts or returned user control; do not bypass
  them, retry without fresh authorization, or modify permission settings.
- **Double-check after the probe, before reporting completion.** Inspect the
  guard's allowed/blocked operation summary and all artifacts the probe created,
  including ignored/untracked files and any changed tracked files. Verify there
  were no forwarded write requests and no credential/cookie/storage exports or
  secret-bearing evidence. Use a value-suppressing scan: report paths/categories,
  not matched secrets. A marker scan is not proof by itself; also check what the
  capture tools actually persisted. Report the scope, results, and limits
  explicitly. If sensitive material is discovered, stop, report only its location
  and category, and obtain authorization for safe cleanup; never commit it.

For follow-ups, use ordinary Claude skill selection, reuse bodies still in context
and reload relevant bodies after compaction. There is no verified durable
opt-in/disable receipt here. Honor any user request not to use Harry; do not invent
recovery of a lost opt-out or claim Codex's persistence results apply to Claude.
Do not run the Codex `activate.py`/`session.py` helpers, manufacture
`CODEX_THREAD_ID`, or announce `HARRY_UI_SESSION_ENABLED` in this host.

After actual routing, briefly name the selected procedures and verification
limits. Backend-only, investment-only and prose-only work require no UI routing.
