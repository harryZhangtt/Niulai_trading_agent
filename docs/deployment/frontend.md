# Frontend skills and local verification

Use with [local setup](../local-setup.md). `ui/` is a separate capability category
parallel to `mentor/`. Read [ui/AGENTS.md](../../ui/AGENTS.md) and its selective
[router](../../ui/ROUTING.md). Twenty-two catalogued entrypoints are
repository-local: twenty imported/adapted entrypoints and two local
procedures/adapters. Pins/licenses/adaptations are in
`ui/upstream/`. The React/TypeScript verification fixture is synthetic; it is
not a production investment UI or application deployment.

## Startup, discovery and visible status

### User-scoped Harry UI wrapper

User authorization on 2026-11-02 permits the self-contained skill payload at
`~/.agents/skills/harry-ui-skill-set` for this account's repositories. Source,
packaging and tests remain in `ui/portable/`. Only its root `SKILL.md` is
discoverable; all 22 experts are internal `GUIDE.md` resources. This is an owned
copy, not a symlink to this checkout. The
[official skills documentation](https://learn.chatgpt.com/docs/build-skills)
describes this user-scope discovery location and explicit `$skill` invocation.

Invoke `$harry-ui-skill-set` once per conversation. Activation now writes a private,
atomic native-thread receipt under the target's
`.ui-skill-runtime/harry-ui-sessions/`, keyed by hashed `CODEX_THREAD_ID` and bound
to the target and bundle fingerprint. It stores no prompts, credentials or raw
account data; its own ignore file excludes runtime state from Git. The native ID
is observed in this Codex runtime, not a documented cross-version promise. If it
is unavailable, scope or integrity is unknown, activation fails visibly.

`agents/openai.yaml` now permits implicit selection on UI requests. This lets
Codex rediscover the wrapper after history compaction; it does not automatically
opt in a fresh thread. Enabled/uncertain UI routing calls `session.py restore`
before the resolver and actual guide reads. Fresh threads remain inactive until
explicit activation. Disable writes a tombstone; known-disabled work can stay
quiet without helper calls, and compaction/upgrades never silently re-enable it.
Same-thread resume restores the receipt; `CODEX_SESSION_ID` is not used because
different forked threads may share it. No global enable flag or hook is added.

The prior two-turn/context-only check did not establish durable persistence.
Actual runtime baseline lost bundle use after compaction and restart/resume.
The patched manual sequence recovered all enabled UI turns but scored 9/10 under
its original strict rule requiring even disabled work to call the helper. That
failure remains preserved. A prospective v3 aligns known-off behavior with the
user goal and retains every active/scope/privacy gate. See
[runtime persistence verification](../../ui/portable/runtime_verification/report.md)
for real tool traces and the passing fresh scheduled v3 sequence:10/10 task
turns,2 native compactions,new-PID resume,disabled/fresh-thread isolation and
independently verified cleanup. The configured-owner summary has exact recipient/subject/HTML raw readback;
remaining limits are recorded separately. Automatic
host-hook execution is a separate unverified claim.

The intent-card comparison ran before publication: final v2 matched the full
router on 12/12 fresh cases with zero extra guides, halving policy-token proxy
size while reducing reported input-plus-output by 2.13%. The failed v1 and all
four calls are preserved. See [the intent report](../../tuning/evals/ui-intent-lightweight/report.md)
and [session/global verification](../../ui/tests/harry-ui-session-report.md).
These are small classification screens, not universal accuracy or billing claims.

From the workspace root, build a new named candidate (existing destinations are
never overwritten), verify it, and exercise the portable tests:

Commit the maintained `ui/portable/` templates, scripts and tests. Generated
distribution copies in `ui/portable/candidate/`, `ui/portable/ui-skill-router/`
and `ui/runtime/` are ignored local artifacts; recreate them with the builder
instead of committing duplicate expert payloads.

```sh
python3 -B ui/portable/package.py --name harry-ui-skill-set \
  --output ui/runtime/<new-build>/harry-ui-skill-set
python3 -B ui/portable/verify.py ui/runtime/<new-build>/harry-ui-skill-set
UI_SKILL_BUNDLE="$PWD/ui/runtime/<new-build>/harry-ui-skill-set" \
UI_SKILL_TEST_RUNTIME="$PWD/ui/runtime/<new-tests>" \
  python3 -B -m unittest discover -s ui/portable/tests -p 'test_*.py' -v
```

Publication is a separate explicitly authorized operation; staging must exist,
be outside the discovery root and be on the same filesystem:

```sh
mkdir -p ui/runtime/<install-staging>
python3 -B ui/portable/manage.py install \
  --bundle "$PWD/ui/runtime/<new-build>/harry-ui-skill-set" \
  --skills-root "$HOME/.agents/skills" \
  --stage-parent "$PWD/ui/runtime/<install-staging>" \
  --allowed-root "$PWD" --allow-user-scope
```

The manager derives the validated package identity and publishes exclusively;
an existing target is preserved. Save its installation ID and manifest hash in
ignored machine receipts. Rollback removes only the unchanged payload with the
matching receipt:

```sh
python3 -B ui/portable/manage.py rollback --name harry-ui-skill-set \
  --skills-root "$HOME/.agents/skills" \
  --stage-parent "$PWD/ui/runtime/<install-staging>" \
  --allowed-root "$PWD" --allow-user-scope \
  --installation-id <ID-from-owned-install-receipt>
```

Changed/added files or a mismatched owner block removal; reconcile rather than
deleting user data. No global Codex settings, profiles, MCP, browsers, tools or
dependencies are installed. Target repositories own their runtime state and
toolchains. Standalone installed commands work from any working directory:

```sh
python3 -B "$HOME/.agents/skills/harry-ui-skill-set/scripts/activate.py" --project "$PWD"
python3 -B "$HOME/.agents/skills/harry-ui-skill-set/scripts/session.py" restore --project "$PWD"
python3 -B "$HOME/.agents/skills/harry-ui-skill-set/scripts/resolve.py" --decision async-state
```

To disable the current native thread, run `scripts/session.py disable --project
<target>` or ask Codex to disable the mode. Explicit re-enable uses `activate.py`.
Unknown/corrupt/foreign state is preserved, not overwritten. On a validated bundle
update, enabled state refreshes its fingerprint; disabled tombstones remain off.
The runtime directory is target-owned; installed resources remain immutable.

For an existing owned installation use `manage.py upgrade` with the current
`--installation-id` and a validated candidate. It atomically exchanges directories
and retains the exact previous payload/receipt at the reported workspace rollback
path. `restore-upgrade` requires both matching IDs and that retained path. Changed
or uncertain payloads are held for reconciliation; no gap or unowned overwrite
is accepted. Source tests cover interrupted/post-validation failure paths.

Runtime tests use real `codex app-server` threads, native tool events, actual
`thread/compact/start`, process restart/resume and independent artifacts/receipt
readback. They use nested Git roots with `project_doc_max_bytes=0` to exclude this
workspace's reinforcing instructions; no routing reminders are supplied on later
UI prompts. All model/auth/cache/log paths are local and the shared auth cache is
serialized without copying it. Use the existing job-runtime Python environment:

```sh
.job-runtime/.venv/bin/python -B -m unittest \
  ui.portable.runtime_verification.test_run \
  ui.portable.runtime_verification.test_scheduled -v
.job-runtime/.venv/bin/python -B -m ui.portable.runtime_verification.run \
  --record <new-record> --stage candidate --protocol candidate-v3
```

Future acceptance uses an isolated `once` Engine, unique GUI launchd label and a
workspace-private plist. Run local checks and the setup sync gate before staging:

```sh
.job-runtime/.venv/bin/python -B -m ui.portable.runtime_verification.scheduled \
  stage --name <unique-name> --delay-seconds 90
```

Bootstrap only the returned plist into `gui/$UID`. `RunAtLoad` is false; the
future scheduler tick claims the durable once slot and launches the actual
Codex sequence. It yields to actual active primary claims and imminent daily/once business work;
interval cadence alone does not permanently starve it. The shared auth cache
remains exclusively locked without copying credentials. It never retries unknown outcomes,
independently replays raw tool/state evidence and self-unloads its own label after
completion. Use its `status --record <record>` command for readback; manual cleanup
may `bootout` only that unique returned label. Primary scheduler allocations,
labels, database and global filesystem links remain untouched. Notifications
follow the configured-owner acceptance contract; an email is not runtime proof.

Fresh catalog discovery was observed from two independent Git roots and this
checkout. A two-turn client preserved activation and correctly excluded UI from
backend work without reinvocation. Native/browser helpers remain prerequisite-
gated; these checks do not prove execution in every repository or an OS sandbox.

### Repository startup definition

The project-local `.codex/hooks.json` has a separate synchronous UI SessionStart
entry alongside the unchanged mentor entry. It calls
`python3 -B "$(git rev-parse --show-toplevel)/ui/session_init.py"` for startup,
resume, clear, compact and fork, with a three-second timeout and a 2,000-token
additional-context threshold. The standard-library loader validates all
entrypoints in `ui/catalog.json` and their relative `.agents/skills/` discovery links,
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

### Expanded catalog, 2026-11-02

The [expansion report](../../ui/tests/expansion-report.md) maps each requested name
to its primary source and independent checks. The checked-in package copies,
licenses and `sources.lock.json` are the installation; no skill installer or
network download is needed after cloning. The fifteen added entrypoints comprise
Hallmark, portable OpenDesign, Taste, eight official GSAP skills, Pencil Playbook,
Landing Page Generator, Cinematic UI and a local Design MD Chrome adapter. The
existing UI/UX Pro Max copy remains pinned and was verified without replacement.

`ui/catalog.json` is the canonical selection/discovery inventory. The synchronous
loader validates its names, all 22 canonical sources and discovery links. It
still injects only the compact policy/router. An isolated fresh Codex catalog
check found all 22 in three working directories; the hook remains **untrusted**,
so actual automatic initialization and future-scheduled acceptance are
**unverified**. Do not mistake a direct `UI_INIT_OK` test for a current host event.

The public plan resolver takes explicit decisions interpreted by the agent:

```sh
python3 -B ui/route.py --decision landing-page --decision cinematic \
  --decision gsap-react --decision gsap-scrolltrigger --decision browser
python3 -B ui/route.py --skill taste
python3 -B ui/route.py --decision pencil-design --guidance-only
```

It emits `UI_ROUTE_OK`, `UI_ROUTE_BLOCKED` or `UI_ROUTE_FAILED`. Multiple flags
compose compatible procedures; a second visual authority fails visibly. Tool
availability is explicitly caller-declared, not tested by the resolver. Pencil
guidance can be read, but actual editing requires Pencil editor/MCP operations
and independent screenshot verification. No Pencil app/server or Chrome
extension was activated. OpenDesign is the portable `manalkaff/opendesign`
suite, not a similarly named desktop/daemon product. Local DESIGN.md extraction
uses the existing pinned Playwright and quarantines generated skill text as data.

Keep Hallmark/Taste history, temporary profiles, generated sites, extracted tokens
and screenshots under `ui/runtime/`. The adapted skills document their safe
commands. Hallmark static procedures work without Puppeteer; native rendered
lint remains gated by absent local Puppeteer, with the existing Playwright route
available for independent UI checks. Optional image/video/research APIs were not
provisioned. No authentication was needed for public-source/local-fixture checks.

GSAP packages are application dependencies, not installed production services.
Independent tests used an ignored isolated fixture with GSAP **3.15.0**,
`@gsap/react` **2.1.2**, React/DOM **19.2.0**, Vue **3.5.44**, and the existing
verification esbuild/Playwright. A target app must declare the packages it uses.
Do not depend on the test fixture's node_modules in production. Canonical UI
verification dependency pins below are unchanged.

Core source and routing checks are reproducible after the normal setup:

```sh
python3 -B -m unittest discover -s ui/tests -p 'test_*.py' -v
python3 -B ui/tests/verify_bundle.py
node --test ui/tests/taste_mobile_overflow.cjs
node ui/tests/page_skill_browser.mjs
node --test ui/skills/design-md-chrome/tests/local-extractor.test.mjs
PYTHONPATH="$PWD" python3 -B ui/tests/verify_session_discovery.py --record <new-run-name>
```

Generated independent-model artifacts and their raw browser receipts are ignored,
not portable source dependencies. Re-running the frozen route screen requires
fresh worker output under `ui/runtime/expansion-20261102/router-screen/`; the
protocol and original source-size measurements are in the expansion report.
`ui/tests/summarize_expansion.py` supports the existing optional tokenizer
environment from the tuning runbook. These are instruction-token proxies, not
actual billed usage or quality/ROI superiority. For a fresh generated combined
example, run `ui/tests/verify_expansion_behavior.mjs --site <built-fixture> --output
<new-evidence-directory>` with workspace-local paths. All browser/server resources
must close. Missing live tools block only their corresponding operational claim.

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
