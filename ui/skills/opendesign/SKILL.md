---
name: opendesign
description: "Use the portable OpenDesign skill workflow when named or selected for design-system intake, HTML mockups, wireframes and clickable prototypes. This is manalkaff/opendesign's Markdown suite, not the unrelated nexu-io desktop/daemon application."
license: MIT
---

# Portable OpenDesign in this workspace

This adapter packages the pinned manalkaff/opendesign suite without a desktop
app, daemon or active MCP. [UPSTREAM-SKILL.md](UPSTREAM-SKILL.md) preserves the full
original. The name is ambiguous; this is the portable skill-suite interpretation,
not a claim that the nexu-io/open-design application is installed.

Use this as one visual workflow authority, alongside the incumbent design system.
Do not combine its defaults with Hallmark/Taste defaults for the same surface.
Honor the user's supplied brief and standing autonomy. Infer noncritical style
choices and state them; ask only for genuinely missing required information,
not routine confirmation, ten mandatory questions or previously granted permission.

## Artifact workflow

Choose a task directory under `ui/runtime/` for experiments and run relative
`./opendesign/` artifact paths from there. Inspect existing design systems in
that task/project before generating new tokens; preserve supplied system names,
content, routes and behavior. No system is a legitimate one-off prototype mode,
not a reason to block authorized work.

Load only the matching bundled specialist, by its local path:

| Decision | Internal resource |
| --- | --- |
| Extract or create a reusable visual system | [create-design-system](references/specialists/create-design-system/GUIDE.md) |
| Working clickable UI/state demonstration | [interactive-prototype](references/specialists/interactive-prototype/GUIDE.md) |
| Low-fidelity flow and layout | [wireframe](references/specialists/wireframe/GUIDE.md) |
| Artifact-specific presentation work | [make-a-deck](references/specialists/make-a-deck/GUIDE.md) |
| Expose controlled prototype variations | [make-tweakable](references/specialists/make-tweakable/GUIDE.md) |
| First local viewer setup | [setup-opendesign](references/specialists/setup-opendesign/GUIDE.md) |
| Bounded local preview | [run-opendesign](references/specialists/run-opendesign/GUIDE.md) |
| Explicit implementation handoff | [handoff-to-claude-code](references/specialists/handoff-to-claude-code/GUIDE.md) |

These are internal references, not independently registered broad skills. The
suite's own original frontend-design reference is retained at
[its internal path](references/specialists/frontend-design/GUIDE.md); use the
project's installed frontend guidance when that separate decision arises.

Create one atomic mockup/capability, then a narrow E2E through the viewer or target
application. Write mockups below `opendesign/mockups/<slug>/`, reusable tokens below
`opendesign/design-systems/<name>/`, and rebuild `opendesign/manifest.json` from
actual files using the schema in the upstream workflow. Copy local `viewer.html`
from this pinned skill for `opendesign/index.html`; do not fetch mutable main.

## Verification and containment

The workspace instructions override unsafe upstream setup/preview defaults:
serve only the dedicated artifact root on 127.0.0.1 with an owned ephemeral port,
bound the lifecycle, and stop only the process you started. Never expose the
repository root, kill a port occupant, install unpinned npx packages, or claim
preview success from a bound port alone. Verify viewer manifest loading and an
actual mockup interaction with the Playwright route.

Prototype simplification does not permit losing drafts, leaking credentials,
ignoring dangerous duplicate effects or shipping known fatal failures. Use the
workspace async-state and performance routes for those mechanisms. Independent
review may be useful; do not launch an unattended verifier, end the turn before
required checks, or infer success from silence. Inspect the reviewer outcome and
report exact limitations before completion. Synthetic local browser evidence is
not scheduled host/runtime acceptance.
