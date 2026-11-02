---
name: design-taste-frontend
description: "Apply Taste v2 art direction, source-backed composition and visual linting when Taste is named or chosen as the UI router's visual authority for public pages or app-screen styling. Use the separate state/performance skills for nonvisual behavior defects."
license: MIT
---

# Taste in this workspace

This selective adapter retains Leonxlnx's complete implementation in
[UPSTREAM-SKILL.md](UPSTREAM-SKILL.md), scripts, research library and assets. It is
an alternative visual authority to Hallmark, OpenDesign and frontend-design;
apply one authority per task and preserve the target design system. Do not load
the entire research library or every style procedure at startup.

## Select the current decision

For public pages, read the relevant steps of the upstream workflow: inventory
real subject material, write claims and their evidence, deal a direction, build
the static hero, then a useful interaction. Do not invent customers, reviews,
logos or business statistics. User constraints supersede template/style bans.
Reuse the supplied brief; do not repeat permission questions under standing
user authorization.

For dashboards, settings or admin work, read
[app screens](references/app-screens.md) and use `draw.mjs --app` rather than the
marketing-page defaults. Add only the current reference:
[copy](references/copy.md), [layout](references/layout.md),
[type](references/type.md), [colour](references/colour.md),
[imagery](references/imagery.md), [motion](references/motion.md), or
[critique](references/critique.md). Read [scenes](references/scenes.md) only when
scroll choreography is actually requested. The directory `library/` is queried
through the scripts, not loaded in full.

## Local commands

Run from the target's dedicated directory under `ui/runtime/` for experiments.
Use explicit output paths for real application work. Keep `TASTE_SKILL_HISTORY`,
`TASTE_SKILL_TMP` and `TMPDIR` within that workspace-owned task directory; patched
defaults also keep history and browser profiles below task-local `.taste-skill/`.
Never repurpose HOME or change global packages/settings.

- `node "<skill>/scripts/draw.mjs" --list sectors` discovers valid sectors.
- `node "<skill>/scripts/draw.mjs" --sector <sector> --brief "<brief>"
  --sections <real-section-roles> --options 3` prints direction options without
  writing a full sheet. Choose for the subject rather than rerolling for comfort.
- Run the same command without `--options`, with `--direction <id> --out
  <task-output>`, to write a direction sheet. Use `--keep palette,type` for a
  fixed brand; record any justified redraw. `--show --out <task-output>` reads it.
- `node "<skill>/scripts/lint.mjs" <explicit-source-path> --json` runs static
  aesthetic checks; `--app` applies app-screen rules. These do not establish
  concurrency safety, performance, accessibility or actual rendering quality.
- `inspect.mjs <local-file-or-url> --out <task-output> --widths 1440,390 --json`
  is the native browser inspector. It needs Node 22+ and explicit `CHROME_PATH`
  to a workspace-local browser. Its temporary profiles are owned and cleaned up.
  If unavailable, disclose the missing tier and verify via the Playwright route.

All scripts retain their pinned upstream provenance with narrowly documented
local state/dependency adaptations. Asset-network searches are optional; inspect
source rights and credits before reuse. Never imply an API or browser tool ran
from a successful static lint. Verify the real rendered page and its interaction,
record observed problems and preserve raw outcomes when judging quality.
