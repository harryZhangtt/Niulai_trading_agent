# Selective UI routing

Keep these invariants without loading the full suite: preserve the incumbent
design system; use semantic controls and explicit loading/empty/error states;
keep secrets out of client bundles and diagnostics; verify the rendered result.
Select by the unresolved decision, not a keyword. Reuse already-loaded resources.

| Decision | Skill/resource to load |
| --- | --- |
| New visual direction, page or substantial redesign | `skills/frontend-design/SKILL.md`; `skills/impeccable/SKILL.md` and `reference/new-work.md` |
| Existing UI polish, accessibility audit, hardening or copy | `skills/impeccable/SKILL.md` and only the matching playbook (`polish`, `audit`, `harden`, `clarify`) |
| Specific layout, typography, accessibility or platform question | `skills/ui-ux-pro-max/SKILL.md`; run one focused local search, then inspect the matching result |
| shadcn component/API/composition or a `components.json` project | `skills/shadcn/SKILL.md` plus only applicable rule files; inspect actual project configuration with the pinned CLI |
| React/Next data flow, rendering, subscriptions or bundle performance | `skills/vercel-react-best-practices/SKILL.md` plus relevant rules; do not load the compiled full `AGENTS.md` by default |
| Entity switching, drafts, async mutations, retries or uncertain writes | `skills/async-state-reliability/SKILL.md`; add Impeccable hardening for the visible state design |
| Rendered behavior, browser reproduction, screenshots, keyboard or network failure testing | `skills/playwright-cli/SKILL.md`; load only the needed testing/mock/tracing reference |
| Purposeful React animation | Impeccable `reference/animate.md`; read [Motion accessibility](https://motion.dev/docs/react-accessibility) only when Motion is used |
| Backend-only, investment evidence, prose-only summary | No UI skill; route to its owning category if needed |

Skills can overlap: a shadcn form with lost-write recovery needs shadcn,
async-state-reliability and Playwright, while an isolated React waterfall can
need only Vercel. Do not load all six imported packages for every UI request.
Frontend-design and UIUX are available for their decisions, not mandatory full
loads for a nonvisual code fix. Local files remove a global-install dependency.

Motion is an optional application dependency, not an installed skill or MCP.
Magic UI MCP is reference-only: no concrete requirement here justifies activating
another server. Shadcn and Playwright use pinned local CLIs. Any future MCP must
pass the root stability/isolated-query/rollback rules before activation.

