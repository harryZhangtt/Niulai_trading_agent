# Hallmark, Taste and portable OpenDesign integration

Verified on 2026-11-02. These are workspace-local skill resources and synthetic
local execution results. They do not establish automatic current-host hook
execution, scheduled acceptance, provider activation or comparative design
superiority.

| Requested name | Selected source and pin | Installed entrypoint |
| --- | --- | --- |
| Hallmark | [Nutlope/hallmark](https://github.com/Nutlope/hallmark/tree/4f6a46c6dc325d40ab268c93e25c7b96676ebccd), MIT | `ui/skills/hallmark/SKILL.md` |
| Taste skill | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill/tree/12af471f627f866411b4bd785b19646d3672784c), MIT; linked by the project's [installation documentation](https://www.tasteskill.dev/docs) | `ui/skills/design-taste-frontend/SKILL.md` |
| OpenDesign | [manalkaff/opendesign](https://github.com/manalkaff/opendesign/tree/cecd9bb6b59408cb96a3974449b8e6ef9f5b17bb), MIT | `ui/skills/opendesign/SKILL.md` |

OpenDesign is a disclosed source interpretation: the selected repository provides
portable Markdown skills. The separate [nexu-io/open-design](https://github.com/nexu-io/open-design)
project is a desktop/daemon application and was not installed. Other similarly
named Taste repositories were not substituted.

The three short entrypoints select one visual authority and the relevant phase;
complete upstream entrypoints remain beside them as `UPSTREAM-SKILL.md`. All
linked local resources are present. OpenDesign's nine specialists are internal
references, avoiding nine extra broad discovery entries. Existing design-system
and user instructions take precedence over their style and intake defaults.

Execution adaptations keep Taste history and temporary browser profiles local,
remove implicit system-browser and global npm discovery, and prohibit upstream
host installers from being treated as active hooks. OpenDesign setup copies the
pinned viewer, and its preview procedure serves only dedicated artifacts on
loopback with an owned bounded lifecycle. The manifest fragment records all 240
resources, upstream/local hashes and adaptations:
[`expansion-identity.json`](../upstream/expansion-identity.json).

| Independent check | Observed result |
| --- | --- |
| JavaScript syntax/load checks | 24 `.mjs` / `.js` resources parsed successfully |
| Hallmark theme checks | Upstream Node theme regression passed; all 50 theme files validated |
| Hallmark actual CLI calls | Theme deal returned JSON; scaffold emitted tokens/base CSS; malformed CSS returned findings; missing input returned exit 2 |
| Hallmark native render dependency failure | HTML input reported `not run: no workspace-local Puppeteer found`; native rendered lint is not claimed to pass |
| Taste actual CLI calls | Page direction options/write and finance app direction write succeeded; default histories stayed task-local; clean CSS passed and bad CSS/missing input were rejected |
| Taste browser inspector | Ran against local responsive/overflow HTML using pinned workspace Chromium; browser profiles removed afterward |
| OpenDesign viewer E2E | Copied pinned viewer loaded a real manifest; keyboard selection opened a mockup; Save changed its state once; no page errors; missing artifact and repository-root request returned 404 |
| OpenDesign cleanup | Owned server thread stopped and its port was closed |

The first Taste mobile run exposed a real false negative: a 1200px element expanded
`innerWidth` to 1200 at a 390px mobile viewport, causing the original comparison to
report zero horizontal overflow. Independent Playwright measurement showed root
client width 390 and scroll width 1200. The narrow patch measures overflow against
root client width; the full native inspector then reported 810px overflow and
retained zero overflow for the responsive control.

The repeatable [browser regression](taste_mobile_overflow.cjs) passes five cases:
responsive control, fixed-width mobile panel, a clipped wide child, a long
unbroken label and a desktop panel that fits (six Node test entries including the
parent). Run `node --test ui/tests/taste_mobile_overflow.cjs` after the documented
local frontend dependencies/browser are installed. It uses workspace-owned browser
and temporary paths.

Both raw native-inspector fixture runs still return an unrelated `off-centre`
aesthetic failure. That score is retained; these checks do not establish that
either fixture passes Taste's entire aesthetic rubric. Static style checks also
do not prove exception handling, races, unnecessary renders or application
correctness. The router's separate state, performance and Playwright routes remain
necessary for those decisions.

Raw commands, original failure, fixed result, screenshots and lifecycle receipts
are in ignored `ui/runtime/expansion-20261102/ui_catalog_identity/`. No credentials
were required for downloads, theme/direction/lint calls or these local browser
checks. Optional Together imagery, Inspo/MCP and the separate OpenDesign app remain
unactivated and unverified. Whole-router verification belongs to the parent
integration report.
