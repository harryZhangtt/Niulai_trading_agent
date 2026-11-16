# Unified research-operations design QA

## Visual authority and normalization

The visual authority is Figma file `AQASayAEkX57Fygp2CvafT`, node `317:173`,
selected raster layer `image 2` from Sajid's Cryptocurrency Dashboard FREEBIE.
The community page displays CC BY 4.0. The captured reference is
`ui/runtime/figma-reference/selected-image-2.jpg`, SHA-256
`ebb70845535f25b7b92054937722e4a3c6fccf2865eb93b1a16f5fe5f4cbd757`.
It is a 648x410 JPEG captured at 50% from a 1296x821.18 canvas layer whose
original raster is 2880x1826. `source-receipt.json` records those identities.

The three comparison images place that same reference on the left and a
1296x821 implementation capture on the right:

- `evidence-comparison.jpg`
- `factor-comparison.jpg`
- `scheduler-comparison.jpg`

The comparison checks composition, surface hierarchy, rail proportions, color,
type rhythm and control treatment. It is not a pixel-similarity score. The
implementation intentionally replaces crypto balances, transfer controls,
rankings and decorative charts with real research evidence, factor provenance
and scheduler state.

## Reconstructed system

The source layer is raster, so token roles and typography are reconstructed
rather than claimed as exported Figma styles. Measured dominant colors became
the page `#211d2e` and panel `#362f41` tokens. Subtle and raised surfaces,
violet selection, teal/warning/failure semantics, 16/10/9px radius roles and the
4/8/12/16/20/24/32 spacing scale are recorded in `DESIGN.md`.

Poppins is an inferred geometric-sans match. Regular, Medium and SemiBold are
self-hosted from the recorded Google Fonts source with the SIL OFL notice and
source hashes under `src/assets/fonts/`. The app bundles those files directly;
the loopback server intentionally keeps `publicDir:false`.

## Iterations and evidence

1. Shared chrome established one rail/topbar and three real destinations while
   preserving separate Research, Factor mining and Scheduler request/state
   owners.
2. Research moved to Overview / Runs / Evidence / Comparisons, then fixed exact
   URL identity, stale-last-good disclosure, inspector/back focus, mobile source
   typography and 200% text wrapping. The mobile regression also sets an
   annotation badge's native `hidden` state and verifies its computed display
   remains `none` despite the responsive badge rule. Evidence is under
   `ui/runtime/research-mobile-audit/`.
3. Scheduler moved to Current / Needs attention / Recurring / All and separated
   execution, acceptance and email evidence. The mobile pass removes the
   unselected duplicate detail, nested list scrolling, undersized operational
   labels and live-green styling for historical stale health. Search changes
   clear the prior selection, mobile detail state and selected `job` URL identity;
   the regression verifies a filtered-out detail cannot remain rendered. Evidence
   is under `ui/runtime/scheduler-mobile-audit-20261105/`.
4. Factor mining preserves the real empty registry and exact performance,
   uncertainty, sample, baseline and provenance fields. The mobile pass raises
   operational text and converts the wide exact table into labelled narrow rows
   without dropping data. Evidence is under the agent-owned factor mobile audit
   directory in `ui/runtime/`.
5. Shared 320px and 200% text checks found overflow in the subject form, workspace
   navigation and a long aggregate cohort heading. The form now wraps only when
   needed, the rail uses an internal horizontal navigation scroller under text
   expansion, and long scientific identities wrap. Document width is 320px at a
   320px viewport with the root font raised from 15px to 30px.

## Review matrix

| Area | Evidence checked | Current result |
| --- | --- | --- |
| Visual fidelity | same-input reference/implementation composites | palette, rail, panel depth, radius and type rhythm align; domain content differs intentionally |
| Business truth | real empty factor state, source/run identities, scheduler evidence groups | preserved; no invented factor values, dispatch, acceptance or email state |
| Responsive | 1440/1296 desktop, 390x844 and 320x800 mobile | passed; final captures are under `ui/runtime/final-ui-acceptance-20261105/` |
| Text expansion | 320px with root font 15px -> 30px | passed; workspace navigation scrolls internally and the document remains within 320px |
| Keyboard/focus | navigation, selection, detail and Back return | focused page audits passing |
| Failure states | loading, empty, malformed, stale, partial and retained-last-good | focused page audits passing |
| Safety | console, external/non-GET requests and read-only boundaries | focused audits report zero page errors or write/external requests |
| Build/tests | TypeScript, Vite, Node server and full browser suite | 65/65 browser, 15/15 Node and 104-module production build passed |

## Limits

- The original font identity cannot be verified from the selected raster layer.
- Responsive checks use emulated Chromium viewports; a physical touch device and
  full screen-reader session are outside this local acceptance.
- The factor live registry is empty. Structured performance rendering is verified
  with labelled intercepted fixtures and does not prove real factor quality.
- This visual/read-only acceptance does not prove a future scheduler dispatch,
  mentor promotion, Gmail delivery or investment alpha.

After all fanout changes joined the shared worktree, the final 104-module build
and complete 65-case browser suite were rerun against the stable final UI hashes.
The final rendered pass also caught and repaired a legacy white Research loading
surface and a clipped final mobile view label. The handoff verification reran
TypeScript, all 15 Node server cases, all 21 scheduler browser cases and all 17
factor browser cases. Focused Research and scheduler cases passed: the Research
case derives the live CSS tokens and measures text-accent contrast at `6.2102:1`
on `--surface` and `5.4164:1` on `--blue-tint`, as well as computed `display:none`
for the hidden mobile annotation badge; the scheduler case proves search removes
the previously selected detail and stale `job` query identity. Focused source,
factor and scheduler audits plus the combined suite leave no open P0, P1 or P2
design findings. The follow-up contrast regression also renders representative
global links, RunEvidence selected/hover and secondary links, details/run-action/
text-button/text-arm labels, and Overview document-class hover text. Every measured
normal-text pair is at least `4.5:1`; the selected blue tint is asserted as the
actual rendered `rgb(72, 49, 95)` background.

**Final result: passed.**
