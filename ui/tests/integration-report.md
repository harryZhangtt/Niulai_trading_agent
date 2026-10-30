# UI integration verification — 2026-10-30

The separate `ui/` category contains a selective router, six pinned imported
skills, one local async-state skill and pinned local CLI/test tools. No active
MCP entry or global installation was added. Native search and primary-source
opening worked. No account authentication was required. Reproduction is in the
[frontend runbook](../../docs/deployment/frontend.md).

The atomic capability is a local tool invocation with explicit workspace-owned
state paths and an entity-scoped React editor contract. The narrow rendered E2E
passes the selected entity and immutable payload through Save to success and
exactly one recorded synthetic business operation. Failure checks extend this
same small path. Mentor supervision, UI guidance and actual app state stay in
their separate components; the fixture is not the investment application.

| Check | Observed result | Allowed claim |
| --- | --- | --- |
| Source/resource gate | `UI_BUNDLE_OK` | Imported hashes, reviewed pins/licenses and local resource links match this snapshot. |
| Gate mutation tests | 5/5 passed | Corruption, path escape, missing dependency and unpinned resource fail; valid snapshot passes. |
| TypeScript/React production build | Passed | This fixture typechecks and builds with the pinned graph. |
| Full Chromium rendered suite | 8/8 passed, zero skipped/failed/flaky in final run | The synthetic contracts hold for this fixture and host. |
| Pinned Playwright CLI | Open/route/reload/eval/snapshot/close passed; final browser list empty | The CLI inspected the actual rendered local fixture beyond startup evidence. |
| shadcn CLI | Real `info --json` passed after alias fix; later `docs button` passed and returned sources were verified | Project inspection and documentation retrieval work for the tested query; no rendered shadcn component acceptance claim. |
| UIUX search | Relevant focus-state and unobscured-focus guidance returned | Local search/dataset integration works for this query. |
| Semantic routing | Separate fresh-worker screen passed 8/8 | Basic routing in that bounded screen, separate from token accounting. |

The eight browser tests cover exact save entity/payload/count; late A after
switching to B; duplicate Save; suppression of a synthetic secret canary in UI
and console; accepted write with lost response and read-only reconciliation;
immutable pending draft while another entity stays editable; client and server
validation draft retention; and keyboard focus, empty state, 360px layout and
reduced motion. Related assertions share tests. The narrow screenshot was
inspected: content fits and the keyboard focus indicator is visible. This is
functional verification, not full accessibility conformance or a comparative
design-quality benchmark.

Review found an async-state risk: allowing a newer edit during a pending write
could mark that newer draft saved when the old operation completed. The fixture
now disables that entity's input while saving/uncertain; a delayed-write and
entity-switch regression verifies this narrow contract. The late-response test
waits for A's handler to settle before checking B, preventing a premature pass.

Preserved failures:

1. Sandbox localhost `EPERM` prevented startup and ran zero tests:
   `ui/runtime/attempts/01-sandbox-startup/`.
2. Headless-shell GPU subprocesses crashed with ICU data errors. One test passed,
   seven failed; receipt/traces are in `ui/runtime/attempts/02-headless-shell-crash/`.
   The final config uses full Chromium from the same stable runner/browser revision.
3. First CLI smoke used `--idle-timeout=30`, interpreted as milliseconds by this
   pinned source, so the session closed before navigation. Receipt:
   `ui/runtime/attempts/03-cli-idle-timeout/`. Corrected to 30,000 ms; the scoped
   rerun passed and explicitly closed the owned session.
4. Initial `shadcn docs button` hit sandbox DNS failure. That attempt remains
   historical failure evidence; a later bounded retry under changed execution
   permissions succeeded as recorded below.

## Documentation lookup follow-up

On 2026-10-30 the pinned local command `python3 ui/tools/run.py shadcn docs button`
exited 0 in 1.285 seconds without authentication. Its returned
[official documentation](https://ui.shadcn.com/docs/components/radix/button)
opened through the native web tool. The returned
[code example](https://ui.shadcn.com/code/apps/v4/registry/bases/radix/examples/button-example.tsx)
could not be opened by that tool; direct HTTPS retrieval followed its public
GitHub redirect and returned HTTP 200, 31,900 bytes of TSX with Button imports
and exports, rather than an HTML fallback. This verifies the returned source;
it does not demonstrate native search health or rendered component integration.

The command output, error capture, receipt, retrieved example and SHA-256 record
are under ignored `ui/runtime/attempts/04-shadcn-docs-unrestricted/`. The prior
failure is preserved. No runtime implementation, dependency version, routing
policy, active MCP configuration or existing browser-test result changed in this
follow-up.

Passing browser results are `ui/runtime/playwright-results.json`; CLI receipts
are `ui/runtime/cli-smoke-receipts.json`, the post-close list is
`ui/runtime/cli-list-after-close.json`, and the narrow screenshot is
`ui/runtime/narrow-reduced-motion.png`. These paths are ignored. Daemon state was
observed in `ui/runtime/daemon/`; the wrapper sets the pinned macOS-specific
`PWTEST_DAEMON_SESSION_DIR` override instead of changing HOME or global settings.
The smoke helper's server cleanup completed. No personal browser was used.

The parent-owned `tuning/evals/ui-routing-screen/` keeps the semantic requests and
tokenizer proxies. Full skill/playbook loads can be substantial; fewer entrypoints
alone do not prove lower cumulative context. No billed-token, latency, dollar,
general reliability or skill-efficacy advantage is claimed.

API responses and secret canaries are synthetic. Actual backend idempotency,
cross-tab/restart crash recovery, private authentication, application integration
and broader visual quality require their owning components' acceptance. Motion
and Magic UI remain optional references; neither MCP is active. This is
provisional procedural integration with scoped repeatable checks, not an
installed CI/release lock or an independently running UI supervisor.
