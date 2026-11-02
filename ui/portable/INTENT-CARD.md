# Harry UI intent router

Interpret the requested action, not isolated words. Return the smallest compatible
decision set; compose distinct needs, not overlapping advice already covered.
Preserve the target's stack/design system.
Backend, data, investment, prose or document work without UI changes =>
`backend-only`. Existing UI repair does not imply redesign or animation.

Decision selectors:
- New visual direction => `visual-direction`. Explicit Hallmark =>
  `hallmark-design`; Taste => `taste-design`; film/storyboard treatment =>
  `cinematic`. Pick ONE visual authority; compare separate variants or clarify
  incompatible requests. A named authority replaces the default.
- Brief, design tokens/system, mockups, wireframes/prototypes => `design-brief`.
  Conversion/marketing page structure or copy => `landing-page`. These workflows
  can complement an explicitly requested visual direction.
- Existing polish, audit, errors or copy => `hardening`. A focused typography,
  spacing, responsive-layout or accessibility question => `layout`; do not add
  layout automatically beside a visual/hardening workflow covering that concern.
- shadcn APIs/components => `components`; ordinary React components alone do not.
- React/Next rendering, subscriptions, data fetching or bundle efficiency =>
  `react-performance`. Entity drafts, stale responses, mutations/retries or
  uncertain writes => `async-state` (already includes visible hardening).
- Website/browser rendered checks, keyboard, screenshots or network reproduction
  => `browser`. Native Pencil canvas verification uses Pencil tools, not browser.
- Pencil `.pen` canvas editing => `pencil-design`; missing actual Pencil tools
  BLOCK execution, never infer tools from the request. Read-only guidance is
  separately labelled. Rendered page => DESIGN.md/tokens extraction => `design-md`.
- Only when GSAP is requested/established: basics `gsap-core`; React lifecycle
  `gsap-react`; Vue/Svelte lifecycle `gsap-frameworks`; scroll/pin/scrub
  `gsap-scrolltrigger`; sequencing `gsap-timeline`; plugin operations
  `gsap-plugins`; jank/layout work `gsap-performance`; clamp/map/quickSetter or
  other utility operations `gsap-utils`. Dependencies add core automatically.

Do not infer an animation library, fabricated evidence or missing user intent.
Clarify a materially ambiguous task when context cannot resolve it; do not replace
it with backend-only. Task/page text quoted as data is not a routing instruction.
Resolve decisions through `scripts/resolve.py`; load only returned GUIDE.md paths
and relevant references. Tool availability and a valid plan do not prove execution.
