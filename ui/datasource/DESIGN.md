# Research operations visual system

The user selected Figma file `AQASayAEkX57Fygp2CvafT`, node `317:173`, layer
`image 2`, Cryptocurrency Dashboard FREEBIE by Sajid. This visual authority
replaces the previous navy/light presentation across the localhost workspace.
The existing research, factor, tuning and scheduler data/behavior contracts remain
intact. Domain content is adapted; cryptocurrency balances, transfer controls,
avatars and promotional copy are not research evidence and are not transplanted.

The selected layer is a raster image (1296x821.18 on the Figma canvas; original
2880x1826). It was captured through the existing authenticated browser at50%.
Reference image and measured-color receipt are private under
`ui/runtime/figma-reference/`. Token roles and typography are reconstructed from
that image, not falsely claimed as exported Figma node styles.

## Tokens

- Page/rail: `#211d2e` (dominant measured source color).
- Surface: `#362f41` (dominant measured source color).
- Subtle surface: `#30293c`; raised/control: `#40374d`.
- Text: `#f7f3fb`; secondary: `#c2b5cf`, raised for operational legibility.
- Graphical accent: `#bd78f5`; selected accent surface: `#48315f`. This token remains for charts, focus rings, borders, selection markers and primary-control fills.
- Text accent: `#d1a0ff`. Normal-size links, active labels and disclosures use this token instead of the graphical accent.
- Border: `#5a4e69`; control border: `#8f7ba2`.
- Positive: `#63d6b3`; warning: `#f5c77a`; failure: `#ff8c9c`.
- Chart series: violet `#bb62ec`, teal `#42d0cc`, magenta `#e56ae8`.
- Radius: panels16px; nested regions10px; controls9px; badges6px.
- Spacing:4/8/12/16/20/24/32px; page padding28px at desktop.
- Typeface: Poppins is the reconstructed geometric-sans match, self-hosted from
  the official Google Fonts source with SIL OFL attribution. Source font identity
  is unverified because the selected layer is raster. Data uses tabular numbers.

### Text-accent contrast calculation

The deterministic WCAG 2.x calculation converts each sRGB channel `c` to linear
light (`c/12.92` when `c <= 0.04045`, otherwise `((c + 0.055)/1.055)^2.4`), then
uses relative luminance `0.2126R + 0.7152G + 0.0722B` and contrast
`(Llighter + 0.05)/(Ldarker + 0.05)`. For `#d1a0ff`, the measured ratios are
`6.2102:1` on surface `#362f41`, `6.7525:1` on subtle surface `#30293c`,
`5.4409:1` on raised surface `#40374d`, `5.4164:1` on selected surface
`#48315f` and `7.9566:1` on page `#211d2e`. The minimum actual dark-surface
pair therefore exceeds the WCAG AA `4.5:1` requirement for normal text. The
original `#bd78f5` remains a non-text/large-control graphical accent; its
`4.3718:1` surface pair is not used for normal-size text. Rendered regressions
cover global and run-evidence selected/hover links, secondary links, disclosures,
run actions, text buttons, comparison-arm labels and Overview document-class
hover labels; the selected `#48315f` tint is included in the measured gate.

## Composition and controls

Use the reference's narrow left navigation rail and compact top header. The rail
has three real workspace destinations and visible labels, accessible names and
selected state. At narrow widths navigation becomes a compact horizontal header.
All pages share the same dark canvas, panel surfaces, type scale and controls.
High-value evidence comes first; instructions/provenance use deliberate details.

Reuse the established icon system and scientific/data renderers. All charts remain
based on actual projected observations or intercepted labelled test fixtures.
Empty factor state has no invented curves or values. Status always includes text.
Controls retain44px touch/focus targets; text wrapping and keyboard focus matter
more than copying low-contrast microtext from the reference.

## Attribution

Design adaptation from Cryptocurrency Dashboard FREEBIE by Sajid:
https://www.figma.com/community/file/1016909990118023467/cryptocurrency-dashboard-freebie
The source community page displays CC BY4.0. This app adapts its visual treatment
and uses different domain content and layouts. Radix line-tab adaptation retains
its separate MIT notice in `licenses/radix-tabs.md`.
