# Claude Code workspace instructions

@AGENTS.md

## Skill discovery in this CLI

Claude Code uses `.claude/skills/` for this project and `~/.claude/skills/` for
user-scope skills. The `.agents/skills/` links and `.codex/hooks.json` remain
Codex configuration, not evidence of Claude discovery or hook execution.

User authorization on 2026-11-04 extends to exposing all 30 maintained repository
skills plus the Claude-specific `harry-ui-skill-set` and `mentor-skill-set`
entrypoints through user-scope Claude skill links. This exception permits these
links to this checkout, not edits to unrelated user skills, shell profiles,
browsers, packages or credentials. The user separately explicitly authorized one
UserPromptSubmit command hook in user settings for leading `$skill-name` aliases;
native `/skill-name` remains unchanged. Preserve all other settings and hooks.
Keep project links too so discovery does not rely on user state.

Read `docs/deployment/claude-skills.md` for installation, checks and limits.
Use mentor and UI selective routing; do not load all bodies every turn.
`harry-ui-skill-set` here routes the canonical UI experts without running Codex
thread helpers. Its installation does not establish Claude-native durable
activation/disable persistence. `mentor-skill-set` routes six specialists and
installs no watchdog. Project `.claude/settings.json` now registers only the
nonblocking mentor SessionStart loader. The user reverted the receipt gates on
2026-11-05 after they locked prompt submission. No mentor receipt is required to
submit prompts or use tools; do not re-enable the candidate guard without a
separately reviewed and explicitly authorized rollout.

Only a current actual `MENTOR_INIT_OK` host event proves initialization ran;
source/config tests or another host's output do not. If the marker is absent,
disclose unverified initialization and read the policies/routers directly as the
fallback required by `AGENTS.md`. Preserve prompt submission, task notifications
and recovery access during future hook changes. See the staged rollout procedure
in `docs/deployment/claude-skills.md`.
