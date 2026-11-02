# UI skill expansion, 2026-11-02

Fifteen entrypoints were added to the seven existing UI skills. All **22** are
workspace-local, catalogued and discoverable in a fresh isolated Codex catalog
from the root, `ui/`, and `ui/verification/`. UI/UX Pro Max was checked in place,
not installed twice. No global settings, personal browser extension or active
MCP configuration changed. Skills become discoverable to the host on its next
catalog reload/turn; current manual calls use their canonical local paths.

## Requested sources and independent evidence

All imported sources have pinned 40-character revisions, retained MIT or
Apache-2.0 licenses, and upstream/local SHA-256 records in
[sources.lock.json](../upstream/sources.lock.json). The three `expansion-*.json`
receipts retain source-specific adaptations and exact commands/evidence paths.

| Requested name | Source / installed entrypoint | Exercised scope and limits |
| --- | --- | --- |
| Hallmark | [Nutlope/hallmark](https://github.com/Nutlope/hallmark), `hallmark` | Theme dealing, all 50 themes, token scaffolding, static lint and invalid/missing input. Native rendered lint reports missing local Puppeteer; it was not passed off as tested. |
| OpenDesign | [manalkaff/opendesign](https://github.com/manalkaff/opendesign), `opendesign` | Portable brief/design-system workflow and local viewer: manifest loading, keyboard navigation, one Save, missing-artifact/private-root rejection and cleanup. This mapping excludes the similarly named desktop/daemon application. Nine helpers are internal `GUIDE.md` references. |
| UI/UX Pro Max | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill), existing `ui-ux-pro-max` | All 73 locked resources unchanged; three focused layout/reduced-motion/focus searches succeeded. |
| Taste | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill), `design-taste-frontend` | Page/app direction, local history, static lint and real Chromium inspector. A real mobile-overflow false negative was repaired and covered by regression tests. Primitive inspector fixtures still produce unrelated aesthetic flags; raw failures remain. |
| GSAP skills | [greensock/gsap-skills](https://github.com/greensock/gsap-skills), eight `gsap-*` entrypoints | Eight real-browser capability cases plus reduced motion: core, React, Vue/framework lifecycle, ScrollTrigger, timelines, plugins/Flip, utils and performance setters. No FPS or production performance claim. |
| Pencil Playbook | [stevembarclay/pencilplaybook](https://github.com/stevembarclay/pencilplaybook), `pencilplaybook` | Seven preset/source invariants and selective guidance route. **Live `.pen` editing/rendering is blocked:** no Pencil tools are available. [Pencil setup](https://www.pencil.dev/) is the relevant next dependency, not a proven OAuth requirement. |
| Design MD Chrome | [bergside/design-md-chrome](https://github.com/bergside/design-md-chrome), local `design-md-chrome` adapter | Upstream extension has no source skill. The clearly authored adapter executes pinned extraction/normalization/generation modules in existing local Playwright: real computed styles, output generation, privacy/credential-URL rejection and sanitized page failure. Three local cases and upstream tests passed. Personal Chrome extension UI was not installed/tested. |
| Landing Page Generator | [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills/tree/main/product-team/skills/landing-page-generator), `landing-page-generator` | Scaffolding, JSX/config validation, hostile literal text, links, keyboard controls, narrow grids and CTA hitboxes. Joint page suite: four Python, ten Chromium cases and six static-server checks. |
| Cinematic UI | [akseolabs-seo/cinematic-ui](https://github.com/akseolabs-seo/cinematic-ui), `cinematic-ui` | Local primitives, deterministic type frames, normal/reduced motion, cleanup and desktop/mobile screening. Film-research, video rendering, optional media APIs and comparative cinematic quality remain unverified. |

These checks needed no login. Optional imagery/media providers, full Hallmark
native rendering, and Pencil application operations retain their actual
prerequisites. Sources and tests do not establish those integrations.

## Router and composed implementation

[catalog.json](../catalog.json), [route.py](../route.py) and the compact
[routing contract](../ROUTING.md) provide the same public route to workers and
tests. Explicit decisions/aliases resolve canonical paths, deduplicate compatible
dependencies and reject competing visual authorities. `UI_ROUTE_OK` means
selection/source checks passed. Missing app tools return `UI_ROUTE_BLOCKED`;
invalid selection/resources return `UI_ROUTE_FAILED`. Caller-declared tool
availability is labelled and never described as a successful operation.

A fresh worker, without expected route answers, interpreted nine realistic
prompts and invoked the public CLI. Replay against the frozen development rubric
passed **9/9**, including existing React race/render/overflow work without visual
page workflows, backend-only exclusion, and Pencil's missing-tool status.
Raw prompts/results and graded replay: `ui/runtime/expansion-20261102/router-screen/`.

The same independent worker built an original React landing page for fictional
Northlight Observatory with landing-page, Cinematic UI, GSAP core/React/
ScrollTrigger and browser procedures. Its **16** browser checks passed. A separate
parent-authored browser harness, frozen before inspecting that implementation,
passed **7/7**: real GSAP/ScrollTrigger, keyboard focus, 320px and hostile long
heading reflow, reduced-motion visibility/stability, no retained tweens of removed
targets, no disconnected triggers, and stable trigger counts after remount.
Screenshots were inspected. This is an integration mechanism fixture, not a
researched film treatment or proof of general design superiority.

The incumbent async-state fixture also passed **8/8**, including stale reads,
duplicate/unknown writes, validation/draft retention, keyboard and narrow layout.
Final Python source/router/startup/scaffolder suite passed **38/38**. All 22
official skill metadata validations and the full provenance/resource gate pass.

Concrete repairs found during this work include Taste's `innerWidth` overflow
false negative, JSX interpolation/unsafe-link handling, narrow-grid and CTA
hitbox defects, global cache/browser fallbacks, unintended nested skill
discovery, and verifier/router file-handling defects. Independent review found
FIFO blocking, unbounded pre-rejection reads and unsafe Markdown/manifest
reads. Canonical bounded nonblocking regular-file readers, rejection without
opening escaped resources, and regression tests address those mechanisms.
Earlier failed probes and instrument corrections remain in the ignored receipts.

## Context cost and claim limits

Using the existing optional `tiktoken` environment, `o200k_base` counts are:

| Instruction artifact | Tokenizer proxy |
| --- | ---: |
| All 22 entrypoint bodies | 63,152 |
| Direct startup policy/router payload | 1,509 |
| Hallmark / OpenDesign / Taste individual entrypoints | 768 / 866 / 797 |
| Composed landing/cinematic/React/scroll/browser route | 24,650 |
| Existing React race/render/overflow route | 7,368 |
| Backend-only route | 0 |

Startup remains below the configured 2,000-token threshold in this proxy. The
complex composition still has substantial context cost. These are full-entrypoint
instruction proxies, **not actual billed tokens**, complete reference-load cost,
model latency or a matched quality/ROI benchmark. No baseline comparison here
establishes that installing more skills improves implementation quality.

Fresh catalog checks show the UI SessionStart hook remains **untrusted**; no
actual successful hook event was observed. Direct loader `UI_INIT_OK` is source
protocol evidence only. Automatic host initialization and real future-triggered
scheduled execution remain unverified. The manual supervisor acceptance notice
was emailed to the validated configured owner; exact recipient, subject and HTML
readback were verified. Notification does not turn unverified execution into
acceptance. The private change record
is `.job-runtime/acceptance/ui-skill-expansion-20261102/record.json`; the workspace
acceptance policy governs its owner notification and permitted claim.

## Reproduction and ownership

See [the frontend runbook](../../docs/deployment/frontend.md) and
[the preregistered development checks](expansion-protocol.md). Source tests live
alongside UI; mentor supervision and tuning ownership remain separate. Local
dependencies, generated examples, browser binaries, raw failures and screenshots
remain under ignored `ui/runtime/` or the existing verification dependency tree.
No raw model outputs, credentials, state or generated sites enter source control.

Primary raw receipts are under `ui/runtime/expansion-20261102/`: installer
subdirectories, `router-screen/grade-v2.json`, `composed-e2e/`,
`composed-grading-v1/results.json`, `review/` and `final-checks/`. Fresh catalog
receipt: `ui/runtime/init-verification/ui-expansion-20261102-v2.json`.
Source copying does not recreate independent model outputs; create a new named
run to repeat that experiment, preserve failures, and rerun the same criteria.
