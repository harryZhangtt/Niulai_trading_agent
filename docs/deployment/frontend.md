# Frontend skills and local verification

Use with [local setup](../local-setup.md). `ui/` is a separate capability category
parallel to `mentor/`. Read [ui/AGENTS.md](../../ui/AGENTS.md) and its selective
[router](../../ui/ROUTING.md). Six pinned imported skill packages and one local
async-state skill are repository-local. Pins/licenses/adaptations are in
`ui/upstream/`. The React/TypeScript verification fixture is synthetic; it is
not a production investment UI or application deployment.

## Startup, discovery and visible status

The project-local `.codex/hooks.json` has a separate synchronous UI SessionStart
entry alongside the unchanged mentor entry. It calls
`python3 -B "$(git rev-parse --show-toplevel)/ui/session_init.py"` for startup,
resume, clear, compact and fork, with a three-second timeout and a 2,000-token
additional-context threshold. The standard-library loader validates seven
canonical skill entrypoints and their relative `.agents/skills/` discovery links,
then supplies only `ui/AGENTS.md` and `ui/ROUTING.md`. It does not preload full
skill bodies, install tools, browse, inspect credentials or start a monitor.

`UI_INIT_OK` means the loader validated those resources and emitted compact
context. `UI_INIT_FAILED` is a visible warning with sanitized canonical
source/link codes and actionable fallback. Require the latest **actual
SessionStart output** before claiming automatic initialization. A quoted marker,
direct script invocation, catalog listing, skipped hook or missing output is
not that evidence. If output is missing/untrusted, disclose initialization as
unverified and read the two compact files directly for the requested UI task.

Non-managed hooks require review of the current definition using the supported
`/hooks` interface. New/changed definitions are skipped until trusted; the
catalog exposes that status. See the
[official hook documentation](https://learn.chatgpt.com/docs/hooks). This setup
does not write trust hashes or use a hook-trust bypass flag. Trust is scoped to
the actual Codex home/device; isolated test-home trust would not activate the
running user host.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ui/tests -p 'test_*.py' -v
PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 \
  python3 ui/tests/verify_session_discovery.py --record <fresh-run-name>
```

The verifier uses `ui/runtime/init-verification/codex-home/` and its local `tmp/`,
preserves prior named receipts, and never copies auth or changes hook trust. With
Codex CLI **0.166.0**, all seven canonical skills were discovered from root,
`ui/` and `ui/verification/`; the UI hook was **untrusted** in each. A real fresh
app-server thread was created without a model turn, but no successful UI hook
event was observed. The isolated interactive CLI stopped at its sign-in chooser
before `/hooks` was available; it was exited without authenticating. Automatic
hook execution remains **unverified**, and the current parent session has no
verified UI initialization event. Eleven loader/protocol/security tests passed;
these prove the source contract, not hook activation.

Startup/model-context changes also follow the
[major-runtime acceptance contract](runtime-acceptance.md). Actual future-triggered
scheduled Codex execution and verified configured-owner email synchronization
are pending and belong to the coordinating parent task. Direct/unit/catalog
checks do not satisfy that gate. See the [startup report](../../ui/tests/session-init-report.md).

## Versions and installation

Use explicitly provisioned Node **>=22.12**, npm and Python **>=3.9**. The tested
macOS arm64 host used Node **22.23.1**, npm **10.9.8** and Python **3.9.6**. This
category does not install Node, modify profiles or globally install CLIs.

`ui/verification/package.json` pins React/React DOM **19.2.0**, TypeScript
**5.9.3**, Vite **7.1.12**, shadcn **4.23.0**, `@playwright/test` **1.64.1** and
`@playwright/cli` **0.1.22**. The CLI depends on a pinned alpha Playwright engine;
`package-lock.json` records the exact npm graph. Use `npm ci`, not `@latest`.
No application state library is mandated or installed by the guidance.

From the workspace root:

```sh
mkdir -p ui/runtime/tmp ui/runtime/npm-cache ui/runtime/npm-logs
TMPDIR="$PWD/ui/runtime/tmp" \
  npm ci --prefix ui/verification --registry=https://registry.npmjs.org \
  --cache "$PWD/ui/runtime/npm-cache" --logs-dir "$PWD/ui/runtime/npm-logs" \
  --ignore-scripts --no-audit --no-fund
python3 ui/tools/run.py playwright install chromium
PYTHONDONTWRITEBYTECODE=1 python3 ui/tests/verify_bundle.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ui/tests -p 'test_*.py' -v
npm run build --prefix ui/verification \
  --cache "$PWD/ui/runtime/npm-cache" --logs-dir "$PWD/ui/runtime/npm-logs"
python3 ui/tools/run.py playwright test
PYTHONDONTWRITEBYTECODE=1 python3 ui/tests/cli_smoke.py
python3 ui/tools/run.py shadcn docs button
```

The public npm registry is explicit because this host's default pointed to an
unreachable internal registry. No global registry/proxy/network setting changed.
Browser download, localhost listening and browser launch need the appropriate
host execution permissions. A sandbox refusal is not application acceptance;
use the authorized execution path and preserve failed receipts.

## Local paths and lifecycle

| Concern | Workspace-local path |
| --- | --- |
| Vendored skills/resources and provenance | `ui/skills/`, `ui/upstream/` |
| Dependencies and Vite cache | `ui/verification/node_modules/` |
| npm cache/logs | `ui/runtime/npm-cache/`, `ui/runtime/npm-logs/` |
| Browser binaries and temporary profiles | `ui/runtime/browsers/`, `ui/runtime/tmp/` |
| CLI daemon registry/error logs | `ui/runtime/daemon/` |
| CLI snapshots/output/config | `ui/runtime/browser-session/`, `ui/runtime/browser-output/`, `ui/runtime/playwright-cli.json` |
| Build, traces and receipts | `ui/runtime/verification-dist/`, `ui/runtime/test-results/`, other `ui/runtime/` receipts |
| Preserved failed attempts | `ui/runtime/attempts/` |

`ui/tools/run.py` uses pinned local binaries and explicitly sets `TMPDIR`, XDG
paths, npm cache/log paths, `PLAYWRIGHT_BROWSERS_PATH`,
`PLAYWRIGHT_MCP_OUTPUT_DIR` and **`PWTEST_DAEMON_SESSION_DIR`**. The last is a
pinned implementation-specific override: this CLI ignores XDG cache location on
macOS and otherwise writes to the user's Library cache. Recheck the source
contract when upgrading. `CI=1` disables the CLI's update cache. No HOME override
or global repair is used.

The test suite uses the **full `chromium` channel**, headless. The downloaded
headless-shell variant crashed with ICU/GPU subprocess errors on this host; the
failure is preserved. The CLI wrapper generates local configuration pointing at
the full browser executable selected by the stable test runner. This avoids
assuming the alpha CLI and stable runner resolve the same default browser
revision. Regenerate this private absolute-path config on each device or move.

Sessions are ephemeral and isolated from personal browsers. The wrapper sets a
**30,000 millisecond idle timeout**. Close the named session explicitly:

```sh
python3 ui/tools/run.py playwright-cli -s=ui-smoke close
python3 ui/tools/run.py playwright-cli list --json
```

The smoke helper closes only its own `ui-smoke` session and stops its own Vite
server in `finally`. Wrapper commands have a 180-second limit and terminate their
owned process group on timeout; this is not a secure process sandbox. Do not use
global kill-all commands or private browser storage for this fixture.

## Verified scope and recovery

### Fresh implementation-quality comparison

The later `tuning/evals/ui-implementation-quality/` experiment compares fresh
general-engineering and selectively routed repairs of a new synthetic existing
app. It uses the same pinned React/TypeScript/Vite/Playwright graph and full
Chromium, with no package installation. Both repair workers are given matching
source/tools/budgets and no hidden grader. The frozen runner covers overflow,
races, drafts, unknown/duplicate writes, malformed data, diagnostic safety,
render-only preview and measured expensive rendering work. Its
[report](../../tuning/evals/ui-implementation-quality/report.md) distinguishes
implementation quality, routing and context proxies, including a discovered
false-failure assertion. General skill superiority remains inconclusive.

Raw implementations, author controls, receipts and screenshots stay under ignored
`tuning/runtime/ui-implementation-quality-v1/`. Source copying alone does not
reproduce model outputs. `prepare.py` refuses an existing manifest; preserve the
frozen run and use a reviewed new identity for future comparisons. Existing raw
evidence can be revalidated with the project-local tokenizer environment:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tuning/evals/ui-implementation-quality -p 'test_*.py' -v
TIKTOKEN_CACHE_DIR="$PWD/tuning/runtime/tokenizer-cache" \
PYTHONDONTWRITEBYTECODE=1 \
  mentor/runtime/validation-env/bin/python \
  tuning/evals/ui-implementation-quality/summarize.py
```

That environment must explicitly contain the pinned optional
`tuning/evals/ui-implementation-quality/requirements.txt`; alternatively use the
documented local tuning environment. `grade.py <repair-1|repair-2>` writes a new
evaluation directory and refuses overwrite. It uses `BENCH_APP`, `BENCH_OUTPUT`,
`BENCH_PORT`, `UI_TOOL_ROOT`, workspace-local temp/cache paths and the local full
Chromium binaries. Do not run the historical Q04 as an unqualified production
gate: its disabled-pristine-Save assertion was shown to be policy-dependent.
The separate diagnostic and original raw scores remain preserved. This harness
does not install a background reviewer or change production application behavior.

### Earlier profile fixture and CLI integration

On 2026-10-30, the profile fixture's full-browser suite passed **8/8** rendered tests, zero skipped
or flaky: exact save entity/payload/count; late A→B response isolation; duplicate
Save and synthetic diagnostic-canary suppression; lost write response followed
by read-only reconciliation; pending-draft immutability with entity switching;
client/server validation draft retention; and keyboard, empty-state, 360px layout
and reduced-motion behavior. The screenshot was inspected. Five provenance-gate
mutation checks and the production build passed.

The pinned Playwright CLI completed an actual open/route/reload/eval/snapshot/close
round trip on the local fixture. Its final `list --json` returned an empty browser
list. The helper's server cleanup completed. Shadcn `info --json` successfully
inspected the fixture configuration after an alias fix. An initial `docs button`
attempt encountered sandbox DNS failure. A bounded retry after the execution
restrictions changed passed on 2026-10-30 and returned the official
[Radix Button documentation](https://ui.shadcn.com/docs/components/radix/button)
and code-example URL. The documentation page opened through the native web tool;
the returned TSX example was verified by direct HTTPS retrieval after that file
format could not be opened by the web tool. This is source verification, not a
native-search health test. The receipt and example hash are preserved under
`ui/runtime/attempts/04-shadcn-docs-unrestricted/`. No rendered shadcn component
was added or tested. Details and raw artifact locations are in the
[verification report](../../ui/tests/integration-report.md).

Routing has its own fresh-worker screen in `tuning/evals/ui-routing-screen/`;
model routing accuracy and tokenizer proxies are separate from rendered behavior.
Mocks prove their scoped contracts, not actual backend idempotency or production
application reliability. This is not an installed CI/release lock, background UI
hook or comparative visual-quality benchmark.

Public sources/packages and these tests needed no account login, so no auth URL
is required. Private registries or a future target app may need their exact login
flow then. Never place tokens in commands, fixtures, screenshots or reports.
Use synthetic canaries. Motion and Magic UI remain optional references; no UI
MCP is active. Follow [MCP stability](../mcp-stability.md) before future rollout.

Preserve failed receipts before retrying. Distinguish dependency, browser launch,
server startup and application failures; change the relevant condition. On a new
device rebuild from lockfiles, regenerate local config and rerun checks. Do not
copy node_modules, sessions or private state as source. Update this runbook and
the sanitized setup inventory for future version/path/auth/activation changes,
then refresh and check the setup gate.
