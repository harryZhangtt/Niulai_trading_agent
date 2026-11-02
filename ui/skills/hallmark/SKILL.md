---
name: hallmark
description: "Apply Hallmark art direction, theme dealing and visual linting when Hallmark is named or selected as the UI router's visual authority for a new page. Existing-design overhaul requires an explicit Hallmark request; ordinary behavior fixes use the owning engineering skill."
license: MIT
---

# Hallmark in this workspace

This is a selective adapter for the pinned Nutlope Hallmark implementation. The
complete original is [UPSTREAM-SKILL.md](UPSTREAM-SKILL.md); retain its material
and evidence discipline without loading every genre or reference by default.
Use one visual authority per task. User instructions and the incumbent design
system take precedence over theme defaults. Reuse answers already supplied;
standing authorization is not a reason to repeat permission/intake questions.

## First useful path

Read the target's design tokens, package configuration, real content and relevant
component. For a new page, select only these resources as their decision arises:

- Read [flow](references/flow.md), the preflight and harness sections, to establish
  material, audience, one visitor action and tone. Infer noncritical omissions
  when the user has authorized autonomous work; never invent facts or proof.
- Deal directions with `node "<skill>/scripts/theme.mjs" deal --genre <genre>
  --prompt "<brief>" --json`, from a task directory under `ui/runtime/`. Inspect
  only the returned theme's Markdown and picture. A locked design system wins.
- Select the job in [anatomy](references/anatomy.md), one
  [layout](references/layout.md) decision, and the matching theme; consult
  [imagery](references/imagery.md) or [craft](references/craft.md) when needed.
- Scaffold tokens with `node "<skill>/scripts/theme.mjs" scaffold <slug>
  --dir <task-output>`, build the hero, then one useful interaction. Keep controls
  semantic, focus visible, content resilient and reduced motion supported.
- For an explicitly requested existing-page redesign/audit, read
  [redesign](references/redesign.md) first. Preserve content, routes and wiring.
- Apply the relevant [gates](references/gates.md) after the first narrow E2E;
  [patterns](references/patterns.md) provides control and failure-state examples.

## Execution and verification

All generated `.hallmark/` logs, assets and captures stay in the task directory
under `ui/runtime/`; do not run bundled `install.mjs`, `install-hook.mjs` or host
configuration installers. These retained scripts are upstream distribution
resources, not activated workspace hooks.

Run static lint with `node "<skill>/scripts/sloplint.mjs" <explicit-file-or-dir>
--json`. Use `--scope app` or `--scope component` where appropriate; inspect
findings rather than treating a count as an application-safety grade. Native
`--render` requires a workspace-local Puppeteer dependency root via
`HALLMARK_PUPPETEER`, an explicit local `CHROME_PATH`, and a local `TMPDIR`.
Missing render dependencies must be reported as not run. Use the installed
Playwright route to verify the visible result independently; it does not make
Hallmark's native render tier pass.

Do not activate Inspo/MCP or Together image generation merely because the skill
mentions them. Imagery requiring an API key is optional and unverified without a
successful authorized call. Browser checks must exercise actual output and
interaction, including narrow layout and relevant failure states. Await any
independent reviewer and inspect its evidence before claiming success; a silent
or unfinished reviewer is not a pass. Publish the result and concrete limitations.
