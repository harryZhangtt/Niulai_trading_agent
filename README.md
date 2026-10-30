# Niulai trading agent workspace

For installation on another device and required documentation updates after
local setup changes, start with [the local setup guide](docs/local-setup.md).

This workspace separates investment-agent source from mentor guidance and future
tuning experiments. It is an initial source import, not a deployed trading system.

- `mentor/`: local mentor instructions, skills, and supervision checks.
- `ui/`: separate frontend skill routing, pinned local tools and synthetic React/browser verification.
- `niulai/`: migrated investment research and holdings source, tests, and references.
- `docs/`: workspace setup and diagnostic notes.
- `.codex/config.toml`: workspace-local Codex configuration.
- `niulai-runtime/`: controlled schedule-admission, Tiger and Gmail-delivery
  adapters around the preserved migration snapshot. See its README for current
  execution boundaries; this does not activate a recurring sender.

New runtime policies, environments, credentials and generated reports belong in
Git-ignored `.niulai-state/`. The `niulai-private/` archive remains a preserved
source of migration evidence, separate from mutable runtime state.

Read `AGENTS.md` before making changes. See `niulai/docs/LOCAL_HANDOFF.md` for
the migration's runtime limitations and `niulai/docs/SECURITY.md` for data handling.

Private archives, account state, credentials, runtime outputs, historical shadow
evidence, the account-derived holdings taxonomy, the private state-location registry,
and machine-specific diagnostics
are excluded from Git. Holdings workflows need a locally supplied taxonomy before
use. The original
export manifest and audit inventory remain local; export-provenance commands in
the migrated documentation require those original local artifacts. Upstream source
licenses are retained in their original directories.

Skill files describe behavior; their presence does not establish autonomous
monitoring, production readiness, or validated investment performance.
