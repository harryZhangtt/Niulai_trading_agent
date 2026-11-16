# Harry UI and mentor skills: installation handoff

Verified on 2026-11-04 in the Trading Agent workspace. This is a handoff of
existing installations and evidence, not an instruction to reinstall them.

## Current state

| Category | Maintained source | Discovery/install location | Verified scope |
| --- | --- | --- | --- |
| Harry UI | `ui/skills/`, `ui/catalog.json`, `ui/route.py`, `ui/portable/` | Self-contained user package at `~/.agents/skills/harry-ui-skill-set`; repository expert links under `.agents/skills/` | One user entrypoint, 22 internal experts, 23 selectors; package integrity and actual native-thread persistence verified |
| Mentor | `mentor/skills/`, `mentor/AGENTS.md`, `mentor/ROUTING.md` | Six repository-local `.agents/skills/` links to canonical mentor sources | Six skills and 62 imported-file hashes verified; selective routing is a provisional procedural default |

Mentor has no separate global wrapper or Harry-style durable activation receipt.
Do not describe it as globally installed or assume UI activation enables it.
Harry UI is available to this user's repositories; each target owns its own
dependencies, caches and session state.

The installed Harry UI package version is `portable-candidate-2.0.0`; its manifest
SHA-256 is:

```text
407d03cdf6ca4cc7d166953370c31d435c1cf91bf8243cec3a754702cb02a0e4
```

There is exactly one discoverable `SKILL.md` in that portable package. Its 22
experts are internal `GUIDE.md` files. It is a copy, not a link to this checkout.
Both the six mentor links and the 22 repository UI links currently resolve.

The last local commit observed is `3afeb6d`, the previously pushed installation
wave. Later scheduler UI and Claude/Ferry documentation changes remain in the
worktree. Preserve them; inspect current Git status before committing anything.

## Claude Code CLI addition — 2026-11-04

The user subsequently requested installation in this Claude Code CLI across
projects, with both `/skill-name` and `$skill-name` independent of Claude/GPT model
selection. All 30 maintained repository skills and two Claude-specific routers
are now linked under both `.claude/skills/` and `~/.claude/skills/`. The actual
running CLI discovered all 32; native Skill loads of Harry and the mentor router
succeeded from their personal paths. Canonical source/bundle checks still pass.

The separately user-authorized `UserPromptSubmit` hook in personal Claude settings
loads leading dollar aliases through `shared/claude_skills/prompt_alias.py` without
a classifier/model request. Seventeen local tests and the exact registered-command
stdin test pass. The next actual host dollar-alias event remains unobserved;
review `/hooks` and verify `CLAUDE_SKILL_ALIAS_OK` on a real prompt before claiming
that execution. Full inference parity across gateway models is not claimed.

Claude Harry uses the canonical 22 UI experts and resolver, **not** the unchanged
Codex `CODEX_THREAD_ID` persistence wrapper. No Claude durable activation receipt
or automatic mentor/UI startup is claimed. User links depend on this checkout
remaining in place. The original Codex installation and prior failed/passing
histories are unchanged. This new explicit authorization is limited to these
Claude links and one alias hook, not unrelated global configuration.

See [Claude CLI skill runbook](../deployment/claude-skills.md) for the complete
inventory, use, verification, portability and targeted rollback procedures.
The Codex instructions and evidence below continue to describe Codex, not Claude.

## Using Harry UI

Invoke once in the desired Codex conversation and target project:

```text
$harry-ui-skill-set
```

Successful explicit activation emits `HARRY_UI_SESSION_ENABLED` and a meaningful
enabled message. It writes a private target-local record under
`.ui-skill-runtime/harry-ui-sessions/`, bound to the native `CODEX_THREAD_ID`,
target project and bundle fingerprint. Directories/files are private and the
runtime subtree owns its ignore rule. Do not transfer these records to another
thread, project or device.

Later UI requests need no repeated skill mention. The wrapper can be selected
implicitly and must restore the current receipt before routing:

```sh
python3 -B "$HOME/.agents/skills/harry-ui-skill-set/scripts/session.py" restore --project "$PWD"
python3 -B "$HOME/.agents/skills/harry-ui-skill-set/scripts/resolve.py" \
  --decision async-state --decision react-performance --decision browser
```

Read only the returned guides and necessary references. The current model
interprets the compact intent card; the Python resolver validates explicit
selectors. There is no extra classifier-model request on each normal turn.

- `HARRY_UI_SESSION_ACTIVE`: restore succeeded; route and use relevant guides.
- `HARRY_UI_SESSION_INACTIVE`: no opt-in in this thread/project; do not auto-enable.
- `HARRY_UI_SESSION_DISABLED`: honor the user's stop until explicit re-enable.
- `HARRY_UI_SESSION_FAILED`: disclose the sanitized error and preserve unknown state.
- Backend/prose-only work requires no Harry helper, resolver or expert load.

Compaction and restart/resume can recover the same native thread's receipt.
Reload needed guide bodies after compaction. A new/forked thread starts without
inherited opt-in. `CODEX_SESSION_ID` is deliberately not the identity key because
forked threads can share a session-tree root. Native thread-ID availability was
observed in local Codex0.166.0; it is not a cross-version API guarantee.

To disable, ask Codex to disable Harry UI or run:

```sh
python3 -B "$HOME/.agents/skills/harry-ui-skill-set/scripts/session.py" disable --project "$PWD"
```

Known-disabled work may stay quiet without a helper call; if uncertain state is
checked, DISABLED must remain off. Re-enable explicitly. Do not delete a disabled
receipt to simulate activation.

## UI catalog and boundaries

| Need | Canonical experts |
| --- | --- |
| Visual authority: choose one | `frontend-design`, `hallmark`, `design-taste-frontend`, `cinematic-ui` |
| UX, hardening and design-system artifacts | `ui-ux-pro-max`, `impeccable`, `opendesign` |
| Components and React performance | `shadcn`, `vercel-react-best-practices` |
| Async state correctness | `async-state-reliability` |
| Rendered/browser verification | `playwright-cli` |
| Specialized workflows | `landing-page-generator`, `pencilplaybook`, `design-md-chrome` |
| GSAP, selected only when relevant | `gsap-core`, `gsap-frameworks`, `gsap-performance`, `gsap-plugins`, `gsap-react`, `gsap-scrolltrigger`, `gsap-timeline`, `gsap-utils` |

The canonical repository router is `ui/ROUTING.md`. The portable package uses
`INTENT-CARD.md` plus `scripts/resolve.py`. Do not load all experts to solve a
small repair. Preserve the target design system. The existing React
race/render/overflow route is async-state + React performance + browser;
ordinary repairs do not need a new page-design workflow.

`UI_ROUTE_OK` validates selections/resources, not actual tool success.
`UI_ROUTE_BLOCKED` identifies missing prerequisites; `UI_ROUTE_FAILED` identifies
invalid selections/resources. Declared tool availability is not runtime proof.

Pencil guidance is installed, but live `.pen` operations remain dependent on real
Pencil tools. Design MD is a pinned local extraction adapter, not an installed
personal Chrome extension. Optional media services, full Hallmark native
rendering, Motion and app animation packages retain their prerequisites. No
active MCP, global browser/package installation or background quality service
was added by the skill package.

Provenance and licenses: `ui/upstream/sources.lock.json`, the expansion source
receipts, `ui/upstream/ADAPTATIONS.md` and retained licenses. Keep original
upstream pins and record local adaptations explicitly.

## Mentor routing

Read `mentor/AGENTS.md` and `mentor/ROUTING.md`. Select the full specialist for the
decision; reuse loaded text rather than loading every body each turn.

| Decision | Skill |
| --- | --- |
| Boundaries, reuse/scaling, ROI, implementation order, failures/secrets, integration readiness | `development-discipline` |
| Recover task state, preserve deliverables, verify completion | `research-supervisor` |
| Diagnose stalls, repeated failures and blockers | `progress-and-recovery` |
| Design falsifiable interventions/experiments | `experiment-design` |
| Check evidence, leakage, correlated sources and overfitting claims | `evidence-and-overfitting` |
| Cases, graders, metrics, splits, budgets and promotion gates | `evaluation-design` |

`development-discipline` applies to workspace engineering outside `mentor/` too.
It is authored locally; the other five retain pinned upstream implementations
and their local investment context. Its practical priorities are:

1. Encapsulate capabilities; separate responsibilities and reuse demonstrated needs.
2. Balance useful results against engineering, maintenance and evaluation cost.
3. Contain dangerous failures and handle exceptions at actual I/O boundaries.
4. Keep credentials private and verify that diagnostics cannot leak them.
5. Publish validated persistent results atomically or leave the prior state intact.
6. Build an atomic capability and narrow E2E before broad polish; retain essential
   failure/secret protection from the first path.
7. Evaluate incremental value, correlated inputs and overfitting with matched
   evidence; installing or combining more skills is not proof of better results.

Mentor supervision, tuning execution, investment capabilities and shared tool
adapters remain separate. These skills are guidance, not an autonomous watchdog
or installed universal release lock. Provenance lives in `mentor/upstream/`.

## Startup hooks: definition versus actual execution

`.codex/hooks.json` declares SessionStart loaders for startup/resume/clear/
compact/fork. Mentor supplies only its policy/router after checking six sources;
UI supplies only its policy/router after checking the 22 sources and links.

Automatic hook execution remains **unverified**. Require `MENTOR_INIT_OK` and
`UI_INIT_OK` from the latest actual host hook output before making that claim.
Script tests, quoted source or old reports do not establish it. If missing,
disclose the missing verification and read the respective policy/router directly.
Do not bypass hook trust. `UI_INIT_OK` means resources are ready, not that Harry
UI has an enabled receipt. Explicit Harry activation does not prove a hook ran.

## Evidence and performance

- **Harry UI durable runtime:** the real future-scheduled v3 sequence passed
  10/10 task turns and 13/13 cases, including two actual compactions, new-PID
  same-thread resume, backend exclusion, disable/re-enable and fresh-thread
  isolation. Four unnamed enabled UI turns each restored ACTIVE before routing
  with zero reactivations. Raw events, receipts, outputs and cleanup were
  independently checked; the configured-owner summary has exact email readback.
  See [current persistence report](../../ui/portable/runtime_verification/report.md).
- The original wrapper sometimes lost routing after compaction/resume. Manual
  v2 remains strict9/10 failed; its known-disabled turn correctly stayed off but
  omitted a then-required helper. V3 changed that criterion prospectively.
  A retired zero-attempt scheduler allocation remains unverified. Preserve all
  these histories instead of relabelling them as passing evidence.
- **UI intent screen:** final v2 matched baseline12/12 with no extra guides.
  Routing-card proxy1083→541 tokens; reported call input+output25072→24537
  (2.13% lower). V1's23/24 failure remains separate. This small classification
  screen excludes the later persistence wrapper and expert execution.
- **Current text proxies:** whole wrapper873, intent card541, local startup
  payload1737 (`o200k_base`). These are not complete-session or billing figures.
  The actual scheduled test's usage and compaction-accounting limits are in the
  persistence report; do not present541 as the cost of implementing a UI task.
- **Mentor screens:** historical selective routing scored7/7 routes, with a
  31.34% reduction in instruction proxies against its former routing. The
  separate sixth-skill screen scored6/6 routes, advisory quality32/32 versus30/32,
  with zero observed critical failures. General effectiveness remains
  inconclusive; these are small development screens, not investment-alpha or
  production-reliability proofs.

References: [UI intent report](../../tuning/evals/ui-intent-lightweight/report.md),
[mentor routing](../../tuning/evals/mentor-routing/report.md),
[development discipline](../../tuning/evals/development-discipline/report.md),
[UI capability expansion](../../ui/tests/expansion-report.md).
`ui/tests/harry-ui-session-report.md` is explicitly historical; use the current
persistence report for the installed wrapper, not its superseded context-only
activation description.

## Verify, rebuild and maintain

These read-only checks passed again while preparing this handoff:

```sh
python3 -B mentor/tests/verify_skill_bundle.py
python3 -B ui/tests/verify_bundle.py
python3 -B ui/portable/verify.py "$HOME/.agents/skills/harry-ui-skill-set"
python3 -B shared/setup_audit.py --check
```

Expected: six mentor skills/62 imported hashes verified, `UI_BUNDLE_OK`,
`UI_PORTABLE_OK`, and `SETUP_DOC_SYNC_OK`. Source checks are separate from actual
hook execution or model behavior.

Build a fresh named portable candidate and test it locally:

```sh
HARRY_UI_BUILD="ui/runtime/handoff-build-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$HARRY_UI_BUILD"
python3 -B ui/portable/package.py --name harry-ui-skill-set \
  --output "$HARRY_UI_BUILD/harry-ui-skill-set"
python3 -B ui/portable/verify.py "$HARRY_UI_BUILD/harry-ui-skill-set"
UI_SKILL_BUNDLE="$PWD/$HARRY_UI_BUILD/harry-ui-skill-set" \
UI_SKILL_TEST_RUNTIME="$PWD/$HARRY_UI_BUILD/tests" \
  python3 -B -m unittest discover -s ui/portable/tests -p 'test_*.py' -v
```

For a new user-scope installation, use `ui/portable/manage.py install` only when
the destination is absent. An existing owned installation uses `upgrade` with
its exact installation ID. Atomic exchange retains the old complete payload;
`restore-upgrade` requires both exact IDs and that retained path. Changed/user
files block destructive management. Consult the
[frontend runbook](../deployment/frontend.md) for complete publication/rollback
commands and the private receipts for this host's IDs. Do not hand-copy into or
directly edit the installed derived package.

Keep build/staging/rollback outputs under ignored `ui/runtime/`; the legacy
`ui/portable/candidate/` and `ui/portable/ui-skill-router/` generated copies are
also ignored. Do not commit distributions, session records, credentials or raw
model/email traces. The existing machine has explicit authorization for this
one global skill payload; that is not permission to alter global Codex settings,
hooks, other packages or browsers. The current managed sandbox may require its
supported runtime approval for an external write even when task authorization
already exists. Read-only inspection and workspace builds need no republishing.

Update applicable runbooks/inventory and run setup audit refresh/check for setup
changes. For a major runtime behavior change, apply the actual future-scheduled
execution and exact owner-email acceptance contract. Do not rerun model/browser
experiments merely to restate an already verified installation handoff.

## Ready-to-copy continuation prompt

> Read `AGENTS.md` and `docs/handoffs/skills-installation-20261104.md`. Verify the
> installed Harry UI bundle and canonical mentor/UI sources first. Harry UI is
> user-scope with native-thread/project opt-in; mentor is six repo-local skills.
> Automatic SessionStart execution remains unverified. Use selective routing and
> actual tool/output evidence; preserve prior failed attempts and current dirty
> work. Do not reinstall an unchanged package, edit global configuration, copy
> private runtime state or claim general quality/token savings from the small
> screens. For any requested change, define a narrow outcome, build the atomic
> capability and E2E, then verify relevant failures and update setup documentation.
