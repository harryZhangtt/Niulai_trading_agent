# UI skill router

Interpret the requested UI decision, then select only the needed guides. Respect the target repository's AGENTS.md, product, existing tokens/components, stack and user choices. Backend, investment analysis or prose without UI work => `backend-only` (no UI guides). Clarify materially ambiguous scope or conflicting visual authorities; do not invent a page, framework or redesign. An explicit visual style replaces default visual-direction.

Decision => expert(s):
- `visual-direction` (new visual world) => frontend-design + impeccable (new-work)
- `hallmark-design` => hallmark
- `taste-design` => design-taste-frontend
- `cinematic` (explicit film/storyboard) => cinematic-ui
- `design-brief` (brief/tokens/system/wireframe/prototype/deck artifacts) => opendesign, selected internal specialist only
- `landing-page` (conversion/marketing TSX) => landing-page-generator
- `hardening` (existing audit/polish/errors/clarity) => impeccable, matching playbook only
- `layout` (focused typography/layout/accessibility) => ui-ux-pro-max, one focused search
- `components` (shadcn APIs/components) => shadcn
- `react-performance` (React/Next rendering/data/bundle) => vercel-react-best-practices
- `async-state` (entity drafts/races/retries/unknown writes) => async-state-reliability + impeccable (harden)
- `browser` (behavior/screenshots/keyboard/network verification) => playwright-cli
- `pencil-design` (.pen editing) => pencilplaybook
- `design-md` (rendered-reference token extraction) => design-md-chrome
- `backend-only` => none
- `gsap-core` => gsap-core
- `gsap-frameworks` => gsap-frameworks
- `gsap-performance` => gsap-performance
- `gsap-plugins` => gsap-plugins
- `gsap-react` => gsap-react
- `gsap-scrolltrigger` => gsap-scrolltrigger
- `gsap-timeline` => gsap-timeline
- `gsap-utils` => gsap-utils

Choose at most ONE visual authority: frontend-design, hallmark, design-taste-frontend, cinematic-ui. Multiple authorities require clarification or separate variants. Engineering, artifacts, layout and verification can complement that authority. GSAP specialists require gsap-core; animation is optional, not a replacement for accessible states, cleanup or rendered checks. Existing UI fixes do not imply a new visual authority. Do not load every expert or every reference.

Canonical names accept these aliases:
ui-ux-pro-max: uiux, ui-ux-promax, ui-ux-pro-max-skill;
opendesign: open-design;
design-taste-frontend: taste, taste-skill;
landing-page-generator: landing-page;
cinematic-ui: cinematic, cinemaic-ui;
pencilplaybook: pencil, pencil-playbook;
design-md-chrome: design-md, design-md-chrome-extension;
gsap-core: gsap.

Tool prerequisites are separate from intent. Pencil editing/screenshots require actual Pencil tools; missing Pencil blocks execution, but guidance-only may read its guide. Browser/Chrome extraction, image services and optional UI libraries require available target-environment capabilities. Caller-declared availability is not a successful tool operation. Do not substitute an installed skill for a missing app, claim a hook/watchdog, auto-install tools, enable MCP, or edit global config. Workspace-specific `ui/tools/run.py` is not assumed in another repository. Use only verified target-repo tools/dependencies and target-repo-owned runtime/artifact paths; bundled helpers are guidance unless their prerequisites are met.
