# UI capability category

This category owns frontend guidance, local UI tools and an isolated verification
fixture. It is parallel to `mentor/`; mentor supervision and tuning evaluation
remain there. Read `ROUTING.md` for a UI decision, then only the selected skills.
Preserve the target application's design system, stack and behavior. The
verification fixture is synthetic and is not the investment application.

All tools, browser binaries, caches, sessions, screenshots and traces stay below
`ui/` or another explicitly declared workspace-local component path. Invoke the
pinned tools through `python3 ui/tools/run.py` from the workspace root. The user
authorized the separate `harry-ui-skill-set` user-scope package; its portable
helpers use the target repository's tools and state. No global tool installation,
background monitor or active MCP registration is supplied.

The local SessionStart loader validates the catalogued canonical skills/discovery links
and supplies only this policy and `ROUTING.md`. Require `UI_INIT_OK` from the
latest actual hook output before claiming automatic UI initialization. Report
`UI_INIT_FAILED` with its source/link code before substantive UI work. Missing
output or skipped/untrusted hooks mean unverified; read these two files directly
as a disclosed fallback. A direct script test is not proof that the hook ran.
The synchronous loader is not a background UI supervisor or quality gate.

An actual successful hook attests that routing resources are ready, not that a
durable opt-in exists. Explicit `$harry-ui-skill-set` activation writes a private
native-thread receipt below the target's `.ui-skill-runtime/harry-ui-sessions/`.
On later UI turns the implicitly selectable wrapper restores that receipt before
routing. Compaction/resume retain the same thread's state; another thread does
not inherit it. Disabled/unknown state never becomes implicitly enabled. Only
actual activation/restore success permits an enabled-mode claim. Manual
activation does not attest an automatic SessionStart event.

For architecture or integration decisions also apply the root mentor routing;
do not load mentor research/evidence skills for an ordinary spacing fix.

