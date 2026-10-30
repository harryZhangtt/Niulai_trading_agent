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

For mentoring or tuning this investment agent, read `mentor/AGENTS.md`. For
designing or reviewing evaluations, benchmarks, grading, or promotion criteria,
also read `mentor/skills/evaluation-design/SKILL.md`. These are workspace-local
instructions; do not assume they are globally installed or auto-discovered skills.

# Frontend design

For frontend design work, consult and apply the installed `frontend-design`,
`ui-ux-pro-max`, and `impeccable` skills as appropriate to the task, while
preserving the project's design system and instructions.

# Web search reliability

For live web research, follow `docs/web-search-routing.md`. A native transport
failure opens a session-scoped circuit breaker: do not repeatedly call the same
broken route. Use the user-authorized ChatGPT Work browser fallback, verify
returned sources, and disclose the route. Never treat a submitted prompt or a
successful curl request as proof that native search works.
