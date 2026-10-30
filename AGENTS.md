# Workspace boundaries

All task-created or modified files must remain within this workspace unless the
user explicitly authorizes an exception. This includes configuration, skills,
dependencies, virtual environments, caches, logs, experiment artifacts, and state.
Do not modify global Codex settings, globally install skills or packages, edit
shell profiles, or change system proxy/network settings. Reading installed skills
and official documentation is permitted; do not alter those external resources.
Use project-local dependency environments and explicitly configure local cache
and output paths. Do not add hidden dependencies on global skills or packages.

# Separation of responsibilities

Keep these concerns in distinct modules/directories when implementing them:

- Mentor: scientific supervision, progress monitoring, loop detection, blocker
  review, and guidance on the next experiment.
- Tuning: experiment execution, evaluation, traces, statistical checks, and
  overfitting controls.
- Investment agent: alpha discovery and entry-policy capabilities, separately
  testable with explicit interfaces between them.
- Shared infrastructure: explicitly shared web access and tool adapters.

Keep configuration and tests alongside the relevant component. Keep credentials,
runtime state, and generated artifacts separate from source and excluded from
version control. Do not copy private state into documentation or fixtures.
Preserve the existing `niulai/` migration snapshot and `niulai-private/` archive
unless changes to them are specifically needed and authorized by the task.
Do not claim proposed layers are implemented or that configuration is active
without verification. Root `.codex/config.toml` is workspace-wide configuration,
not mentor-only configuration.

# Mentor routing

At session startup, resume, fork or compaction, the local SessionStart hook loads
`mentor/AGENTS.md` and `mentor/ROUTING.md` and checks the six canonical skill
sources. Verify `MENTOR_INIT_OK` from the latest actual SessionStart output, not
from quoted instructions, source text or an old report. If it is
missing or `MENTOR_INIT_FAILED` is present, tell the user initialization is not
verified before substantive work; read the two source files directly as a
fallback and disclose that the hook itself is unverified. A skipped/untrusted
hook is not a successful initialization. Never claim a background watchdog.
Repo-local `.agents/skills/` links expose the canonical six skills for discovery;
load full bodies selectively through the router, not all bodies on every turn.

For workspace development planning, implementation review or integration
readiness, read `mentor/AGENTS.md` and select
`mentor/skills/development-discipline/SKILL.md` via `mentor/ROUTING.md`, including
when implementation lives outside `mentor/`. Build an atomic capability and a
narrow E2E before broad quality expansion; protect secrets and contain dangerous
failures from the first path. Require incremental evidence for integration claims.

For mentoring or tuning this investment agent, read `mentor/AGENTS.md`. For
designing or reviewing evaluations, benchmarks, grading, or promotion criteria,
also read `mentor/skills/evaluation-design/SKILL.md`. These are workspace-local
instructions; do not assume they are globally installed or auto-discovered skills.

# Investment research evidence

For new company investment research, read `investment/AGENTS.md`. Keep the frozen
investment evidence requirements separate from acquisition tools. Use the
maintained `investment.research` finalization/completion entry points so source
coverage is checked alongside the preserved Niulai validators. Do not bypass the
additional source contract by running the migration scripts directly. This route
does not change the separately running cloud task or claim an OS-level sandbox.

# Frontend design

At startup, resume, fork or compaction, the local UI SessionStart definition
loads only `ui/AGENTS.md` and `ui/ROUTING.md` after checking seven canonical skill
sources and repo-local discovery links. Require `UI_INIT_OK` from the latest
actual hook output before claiming automatic initialization. Report
`UI_INIT_FAILED`, or missing/skipped/untrusted output as unverified, before UI
work. Read those two files directly as a disclosed fallback. Tests, quoted text
and an old receipt do not prove the current hook ran. This is a synchronous
loader, not a background quality monitor; major-runtime acceptance still applies.

For frontend work, read `ui/AGENTS.md` and `ui/ROUTING.md`. This category is
parallel to mentor supervision and contains workspace-local copies of design,
component, React and browser guidance. Select only the procedures needed for
the current decision; reuse loaded text. Use its pinned local CLI wrappers and
keep UI dependencies, browsers, caches and artifacts within the workspace.

For frontend design work, consult and apply the installed `frontend-design`,
`ui-ux-pro-max`, and `impeccable` skills as appropriate to the task, while
preserving the project's design system and instructions.

# Web search reliability

For live web research, follow `docs/web-search-routing.md`. A native transport
failure opens a session-scoped circuit breaker: do not repeatedly call the same
broken route. Use the user-authorized ChatGPT Work browser fallback, verify
returned sources, and disclose the route. Never treat a submitted prompt or a
successful curl request as proof that native search works.

# MCP stability and rollout

Adding active market-data MCP entries to `.codex/config.toml` triggered a
user-reported host crash on 2026-10-30. The root cause is not established.
Stability takes priority over integration convenience. Do not hot-add or enable
MCP servers in the active workspace configuration during development. Keep
candidate configuration separate and disabled by default. Validate it with
isolated protocol clients, bounded startup/query timeouts, failure-injection
tests, process cleanup checks, and a rollback plan before activation. A server
handshake alone is not proof of query success or host stability. Record this
incident and subsequent verification in `docs/mcp-stability.md`.

# Local setup documentation

`docs/local-setup.md` and its linked component runbooks are the source of truth
for deploying this workspace on another device. Every future local setup change
must update the applicable runbook in the same change. This includes dependency
versions, environment creation, installation/startup, configuration, model/retry
policy, runtime paths, credential handling and recovery. Update the sanitized
`docs/deployment/setup-inventory.json` when its inventory changes, then run
`python3 shared/setup_audit.py --refresh` and `--check`. Do not report setup work
complete with a failing gate. Never put credentials or private account data into
these files; distinguish tested, active, candidate and unverified behavior.

# Major runtime acceptance — required across agents

User decision, 2026-10-30: a major runtime change is not accepted until a real
future-triggered scheduled Codex session successfully exercises the changed
capability in its intended runtime, and the result is recorded and synchronized
by email to the user's configured recipient. Apply this to implementation,
review, delegation and completion claims; pass this requirement to child agents.

Follow [the acceptance contract](docs/deployment/runtime-acceptance.md). Record
the candidate revision/configuration, actual scheduler slot/attempt and Codex
session, timing, independent business postconditions, partial/failure details,
evidence paths and verified email receipt. Shell/unit tests, a handshake,
manually running work in this chat, old proof or agent agreement do not replace
this gate. Missing evidence stays unverified; observed failure stays failed.
Report both outcomes by email. Preserve unknown delivery fences and reconcile
before replay. Do not weaken approval, credential, archive or production-owner
boundaries to obtain a pass. Documentation-only changes do not require rerunning
business effects. This is a shared agent acceptance policy, not an installed
universal release hook; do not claim automatic enforcement where none exists.
