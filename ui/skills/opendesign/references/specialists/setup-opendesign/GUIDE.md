---
name: setup-opendesign
description: Initialize the pinned OpenDesign viewer and output folders within the dedicated workspace-owned artifact directory.
---

# Local viewer setup

Run from the task directory under `ui/runtime/`, or the explicitly selected
application artifact directory inside the workspace. Copy `viewer.html` from the
root of this installed `opendesign` skill to `./opendesign/index.html` after
creating the directory. Use the pinned local file; no download or npm install is
needed. Preserve existing output rather than replacing a user-modified viewer.

Create `./opendesign/mockups/` and `./opendesign/design-systems/` if absent. For a
new empty output tree write `manifest.json` with current ISO timestamp and the
two sections `mockups` / `Mockups` and `design-systems` / `Design Systems`, each
with `groups: []`. For existing output rebuild the manifest from actual files
using the schema in the suite's upstream workflow. Write a complete manifest
atomically via a sibling temporary file and replace only after JSON validation.

Use the local run-opendesign reference for a bounded preview, and verify that
its manifest and one artifact load. A copied viewer alone proves only setup.
The original upstream setup instructions are retained in UPSTREAM-SKILL.md;
their mutable-main download is not used by this workspace adapter.
