# Radix Themes tab rendering attribution

The scheduler detail-view navigation adapts the Radix Themes base tab-list
rendering treatment into the application's own CSS and existing native button
controls. It does not import Radix Themes, its theme provider, build directives,
or runtime keyboard/navigation primitives.

Source repository: https://github.com/radix-ui/themes

Pinned revision: `1faff10ac26ae17f09944d418c6949b93fc6b566`.

Original CSS: [base-tab-list.css](https://github.com/radix-ui/themes/blob/1faff10ac26ae17f09944d418c6949b93fc6b566/packages/radix-ui-themes/src/components/_internal/base-tab-list.css).

The adapted pattern is a shared baseline for peer views, a restrained active
underline, consistent trigger dimensions and label weight to avoid selection
reflow, and a visible focus treatment. The original active selectors are
`.rt-BaseTabListTrigger[data-state='active']` and `.rt-TabNavLink[data-active]`;
the application's native controls express selection with `aria-pressed`.
The original `.rt-BaseTabListTriggerInnerHidden` reserves selected-label geometry;
the application may use fixed font weight instead of duplicating labels.

The application's existing navy/blue tokens, 44px control minimum, mobile wrapping,
native button keyboard behavior and reduced-motion rules take precedence. No
claim of Radix roving-focus behavior is made for the existing button navigation.

Pinned source downloads and SHA-256 receipt are kept in ignored
`ui/runtime/scheduler-refactor/sources/`. The pinned package declares React and
React DOM 19 as supported peer versions, which matches this application's React
19.2.0. This declaration does not replace local integration/browser validation.

## MIT license

MIT License

Copyright (c) 2023 WorkOS

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
