# Repository skills in Claude Code

User-requested on 2026-11-04: install the maintained repository skills in this
Claude Code CLI, not only in Codex, and allow explicit invocation with either
`/skill-name` or `$skill-name` regardless of the selected Claude/GPT model.
The user separately authorized the one user-level prompt hook described below.

## Installed scope

There are **32 Claude entrypoints**: 30 maintained skills and two compact routers.
Each has a project link under `.claude/skills/` and a personal link under
`~/.claude/skills/`, pointing to this checkout. No existing user skill was replaced.
`CLAUDE.md` imports the existing root `AGENTS.md` for workspace instructions.

| Category | Names | Canonical source |
| --- | --- | --- |
| Harry UI router | `harry-ui-skill-set` | `shared/claude_skills/harry-ui-skill-set/` |
| Mentor router | `mentor-skill-set` | `shared/claude_skills/mentor-skill-set/` |
| Six mentor specialists | `development-discipline`, `research-supervisor`, `progress-and-recovery`, `experiment-design`, `evidence-and-overfitting`, `evaluation-design` | `mentor/skills/` |
| UI design/workflows | `frontend-design`, `hallmark`, `design-taste-frontend`, `cinematic-ui`, `ui-ux-pro-max`, `impeccable`, `opendesign`, `shadcn`, `landing-page-generator`, `pencilplaybook`, `design-md-chrome` | `ui/skills/` |
| UI engineering/verification | `async-state-reliability`, `vercel-react-best-practices`, `playwright-cli` | `ui/skills/` |
| Eight GSAP specialists | `gsap-core`, `gsap-frameworks`, `gsap-performance`, `gsap-plugins`, `gsap-react`, `gsap-scrolltrigger`, `gsap-timeline`, `gsap-utils` | `ui/skills/` |
| Research | `information-catalog`, `investment-research-financial-services` | `investment/research/skills/`, `niulai/skills/` |

These are user-scope **links**, not self-contained distributions. Keep this
checkout in place. Regenerate links and the hook's absolute script path after
moving it or deploying to another device. Runtime/vendor caches, archived
worktrees and upstream snapshots are not additional maintained entrypoints.

Claude officially supports personal/project directory symlinks and native slash
invocation: [skills documentation](https://code.claude.com/docs/en/skills.md).
The CLI discovered all 32 entries in this actual running session. Both routers
were successfully loaded with the native Skill tool from their personal paths.
This is actual CLI discovery/loading, not just filesystem presence.

## Invocation and model independence

Examples in the Claude prompt box:

```text
/harry-ui-skill-set fix the responsive layout
$harry-ui-skill-set fix the responsive layout
/mentor-skill-set review the implementation boundary
$mentor-skill-set review the implementation boundary
/development-discipline review this change
$development-discipline review this change
```

`/` is native Claude Code skill syntax. `$` is a bounded compatibility adapter,
not a new native Claude syntax or shell command. One user-level
`UserPromptSubmit` command hook calls `shared/claude_skills/prompt_alias.py`.
It recognizes leading `$name` tokens for these 32 skills and injects their exact
maintained entrypoint bodies and resource directories as `additionalContext`.
Consecutive leading names are supported and deduplicated. Put the invocation at
the start of the prompt; quoted/code examples, shell variables, path traversal,
ordinary prose and native slash invocations are left untouched.

The parser/loading occurs in the CLI hook before inference. No model choice,
model call, classifier request, shell evaluation of user input or extra permission
grant is involved. This establishes model-independent **instruction loading**,
not a guarantee that every model follows instructions or performs a task equally
well. `$` supports the maintained set, not unrelated built-in/plugin skills or
all future personal skills automatically. Native slash precedence remains owned
by Claude Code; the `$` adapter loads this maintained checkout's version.

The successful hook emits `CLAUDE_SKILL_ALIAS_OK <names>`. Failures emit a sanitized
`CLAUDE_SKILL_ALIAS_FAILED` warning; use native slash syntax until reconciled.
It logs no prompt, credentials, session identity or runtime receipts. Normal
prompts produce an empty JSON result and do not read the skill set. The hook has
a three-second timeout and grants no tools or permissions.

The exact registered hook command passed a direct stdin/JSON protocol test from
outside the checkout. **The next actual host UserPromptSubmit event has not yet
been observed.** Review `/hooks` and submit a `$mentor-skill-set` prompt to check
for the actual marker; restart if the CLI has not reloaded the changed user
configuration. Settings validation and a pipe test are not proof that the host
hook fired. A managed hooks restriction can still prevent execution; do not bypass
it. The hook is independent of which model is selected through `/model`.

## Claude mentor loader and receipt-gate rollback

On 2026-11-05 the user requested rollback after the mentor receipt gates repeatedly
blocked prompt submission with `MENTOR_GUARD_LOCKED E_RECEIPT` and
`E_RECEIPT_STALE`. Removing only a registration can leave an existing host using a
cached command. The rollback therefore removes all seven mentor-guard event
registrations and makes the guard CLI return `{}` when no registration referencing
`mentor/mentor_guard.py` remains in the project hook settings. This does not issue
a receipt or report initialization success. The underlying candidate contract
still fails closed when explicitly registered, and its tests remain available.

Project `.claude/settings.json` restores only the nonblocking
`mentor/session_init.py` SessionStart loader for
`startup|resume|clear|compact|fork`. It checks the mentor core, six specialists and
both discovery catalogs and emits actual `MENTOR_INIT_OK` or a visible failure
with the direct-read fallback. No mentor receipt is required for prompt submission
or tool use. The separate user-level dollar-alias hook is untouched. Email approval,
credential handling, immutable acceptance records and unknown-delivery fences stay
with their business components.

Owner-private rollback copies and their hash receipt are retained under ignored
`mentor/runtime/guard-rollback-20261105T030704Z/`. Existing session/business state
is preserved. Guard source and `mentor/enforcement-lock.json` are disabled
candidates, not active host enforcement. Tests of removal and cached invocation
are local protocol evidence; only an actual user submission proves the running
Claude session accepted the rollback.

## Future host-hook and runtime configuration rollout

1. Stage the candidate configuration separately and disabled. Preserve an exact
   owner-private backup of only the files being changed and retain unrelated
   settings. Do not hot-enable a blocking hook in a working session.
2. Keep user prompts, automated task notifications and recovery commands usable.
   Missing mentor initialization produces a visible diagnostic and direct-read
   fallback. A future action gate belongs at the specific risky effect; it must
   preserve read-only diagnosis and recovery, rather than gate every tool.
3. Before activation, test the candidate in a disposable native Claude session
   with isolated workspace-local state, bounded timeouts and synthetic side effects.
   Cover startup, resume, clear, compaction, subagent lifecycle, missing/stale
   receipts, source/config drift, hook exceptions/timeouts, cached commands and
   rollback. Verify an ordinary prompt and a diagnostic command still work during
   failure, then verify the targeted risky effect is contained. Unit tests and
   submitted prompts alone do not establish actual host success.
4. Review the concrete configuration, evidence, known limits and rollback, then
   obtain explicit user authorization for activation. Change one owned component
   at a time. Do not enable candidate MCP servers or replace global settings as
   part of hook work. Major runtime acceptance still requires its independent
   scheduled business postconditions and email receipt.
5. If the host becomes unusable, restore the owned configuration from outside the
   affected session and verify both fresh and cached hook invocations. Do not keep
   asking the user to resubmit a prompt the gate rejects. Preserve unknown external
   effects and reconcile them before replay.

The active configuration regression test rejects mentor prompt/tool/compaction
gates and requires the nonblocking loader. This procedure and that test do not
install a watchdog, prevent direct same-user edits or claim universal enforcement.

## Install and check on another device

No dependencies or marketplace plugins are required for discovery. From the
maintained checkout, with an explicitly authorized personal install:

```sh
python3 -B shared/claude_skills/manage.py --scope project --install
python3 -B shared/claude_skills/manage.py --scope user --install
python3 -B shared/claude_skills/manage.py --scope project --check
python3 -B shared/claude_skills/manage.py --scope user --check
python3 -B -m unittest discover -s shared/claude_skills/tests -v
```

Expected: `CLAUDE_SKILLS_OK`, 32 verified per scope, and 17 passing tests. The
manager preflights all destinations, creates links exclusively, preserves matching
links on repeat installs and rejects foreign directories/broken links. A failed
install rolls back only its newly created unchanged links; concurrent user edits
are preserved. Publication of the entire catalog is not a single atomic exchange.

For `$` support, explicitly authorize merging the following group into the
existing user settings' `hooks.UserPromptSubmit` array. Replace the script path
with the actual checkout path; do not replace unrelated settings or hooks:

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "python3",
      "args": ["-B", "<absolute-checkout>/shared/claude_skills/prompt_alias.py"],
      "timeout": 3,
      "statusMessage": "Loading explicitly requested skill"
    }
  ]
}
```

See [hooks reference](https://code.claude.com/docs/en/hooks) and the current
installed CLI schema for exec-form `command` + `args`. Ordinary personal skills
in an already-watched directory reload automatically; `/reload-skills` or a
restart is the fallback when a new top-level skill directory was not watched.
Already-loaded skill bodies do not retroactively refresh.

## Boundaries and rollback

The original self-contained Codex Harry package at
`~/.agents/skills/harry-ui-skill-set` is unchanged and still integrity-verified.
Claude Harry routes the same canonical 22 UI experts through `ui/route.py`, but
does **not** run the `CODEX_THREAD_ID` helpers or create a native durable enable/
disable receipt. Codex's scheduled compaction/resume acceptance is not Claude
acceptance. Mentor routes six specialists, not a watchdog. Existing Codex startup
hooks remain unchanged and their automatic execution remains unverified.

Only the explicitly approved Claude skill links and prompt-alias hook were added
at user scope. The original settings fields were preserved by an exact in-place
edit; a proposed full-settings backup was denied and was not copied. The first
hook edit was also denied; it succeeded only after the user's separate explicit
hook authorization. No model, gateway/auth fields, permissions, browsers, package
installations, MCP registrations, scheduler allocations or production behavior
were changed. Scripts/tests create scratch files only in ignored `ui/runtime/`.

In another project, use that project's instructions and local runtime/toolchain.
Source-relative references/helpers belong to this checkout; never mistake it for
the target or assume installing guidance installs executable research/browser
capabilities. Tools, private data and persistent writes require their own existing
authorization and evidence. Imported provenance/licenses remain unchanged.

To disable `$`, remove only the matching `UserPromptSubmit` hook via `/hooks` or a
reviewed targeted settings edit; keep unrelated groups/keys. To remove a skill
link, first verify it is still a symlink resolving to the expected canonical
source, then unlink only that entry. Never recursively delete a skill directory,
restore an old whole-settings file over later edits, or edit the immutable Codex
package to roll back Claude integration.

Local tests cover all 32 dollar aliases against both Claude/GPT model metadata,
model-independent output, outside-checkout execution, negative parsing, secret-
safe failures, conflict preservation, repeat installs and interrupted rollback.
They do not run inference on every advertised gateway model or establish future-
scheduled business/runtime/email acceptance. No such acceptance is claimed by
this configuration-only installation.

## Explicit AI tuning preview

The project-local `/ai-tuning` entrypoint resolves to
`mentor/entrypoints/ai-tuning/SKILL.md`. It supports user and assistant invocation
(`disable-model-invocation: false`) and is not added to the maintained global
32-link catalog or dollar-alias hook. No user settings, SessionStart hook,
Mentor specialist count, scheduler, or production configuration changes.

Example invocation from this checkout:

```text
/ai-tuning Our RAG answers miss relevant sources. Design the smallest baseline/candidate experiment without executing paid calls.
```

The skill loads the existing Mentor router and only relevant engineering cards,
then produces diagnosis, guidance, experiment, measurement, acceptance/stop rules,
and an immediate next action. It defaults to advisory experiment design. Protected
benchmark quality, automatic runtime adoption and production activation remain
separate, unverified gates. Explicit invocation does not claim those gates passed.

Validation:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest mentor.tests.test_ai_tuning_entrypoint -v
```

Project discovery-link resolution, resource references and the instruction
contract are tested. Native slash-command execution in a new host turn remains
unverified until the host lists and loads this new entrypoint. If the current
session has not refreshed its skill catalog, start a new session in this checkout.
Rollback removes only `.claude/skills/ai-tuning`; the source and evidence may stay.
