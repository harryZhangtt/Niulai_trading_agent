# Niulai trading agent workspace

This workspace separates investment-agent source from mentor guidance and future
tuning experiments. It is an initial source import, not a deployed trading system.

- `mentor/`: local mentor instructions, skills, and supervision checks.
- `niulai/`: migrated investment research and holdings source, tests, and references.
- `docs/`: workspace setup and diagnostic notes.
- `.codex/config.toml`: workspace-local Codex configuration.

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
