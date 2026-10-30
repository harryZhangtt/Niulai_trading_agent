# Shared adapters, web access, mentor checks and tuning setup

Use this with [the workspace setup guide](../local-setup.md). This page covers
the shared market-data portal and development environments. The scheduled model
runtime and Niulai delivery have separate [job-runtime](job-runtime.md) and
[Niulai](niulai.md) guides. The [sanitized setup inventory](setup-inventory.json)
covers the setup components. Commands start at the workspace root and write
dependencies, caches and output inside it.

The [investment source contract](../../investment/research/README.md) owns frozen
evidence requirements, provider-capability selection and checked finalization.
[Research-source acquisition](../../shared/research_sources/README.md) is separate:
official OpenAlex/arXiv/document HTTP routes and an optional isolated arXiv MCP
candidate. Its Python environment, paper cache and all artifacts stay in
`.niulai-state/reports/research-sources/` and the separate investment artifact
root `.niulai-state/reports/investment-research/`; dependencies stay in `.research-sources/`. These adapters do not edit the
investment requirement snapshot or active host MCP configuration. Component live
checks are distinct from the required scheduled-runtime acceptance below.

Major adapter/runtime changes must also meet the shared
[scheduled Codex acceptance and email contract](runtime-acceptance.md). Isolated
provider queries and restart checks remain component evidence; a changed provider
path is not accepted for scheduled work until the intended scheduled Codex
session exercises that revision successfully and its result email is verified.
Alpaca/Massive adapter and strike-schema expansion passed isolated-live checks;
their scheduled-acceptance status remains unverified until the corresponding
run and verified email evidence exist.

Tiger queries have a [shared gateway runbook](../../shared/tiger/README.md). They
reuse the portal core with one attempt and an isolated Python worker, the existing
Niulai SDK environment and owner-private credential store. Fresh native Sites
context travels through hidden stdin/private pipes. No Tiger entry is added to
active Codex configuration or `manage.py` provider registration.

## Configuration that is actually loaded

`.codex/config.toml` currently contains only `web_search = "live"`. It is a
workspace-wide Codex setting. Project trust and higher-priority runtime policy
still apply; the setting does not prove that native search works. After moving
to another device, open a fresh trusted session, perform a native search and
open one returned primary source. Follow [web-search-routing.md](../web-search-routing.md)
if either operation has a transport failure. A successful HTTP request or a
submitted browser prompt is not evidence of native-search recovery.

The market-data MCP servers are **not registered in this active config**.
`shared/market_data_mcp/codex.disabled.example.toml` is a disabled candidate.
Do not copy it into the running workspace config during setup. Read
[mcp-stability.md](../mcp-stability.md) before any later rollout: the user reported
a host crash after active registrations were added, and its root cause remains
unconfirmed. An isolated MCP handshake cannot establish host stability.

## Market-data portal prerequisites and paths

The source declares Node.js **22 or newer** and Python **3.9 or newer**. Both
`node` and `python3` must resolve in the actual host's launch environment, not
only in an interactive terminal. Node/npm provisioning is an explicit device
prerequisite; this repository does not install or upgrade Node automatically.
If supplying a project-local Node distribution, keep it beneath the ignored
`.market-data-mcp/runtime/` and explicitly include its `bin` in the launch PATH.
Do not rely on a shell profile being loaded by a background host.

| Concern | Location |
| --- | --- |
| Source, public schemas and offline tests | `shared/market_data_mcp/` |
| Exact npm dependency graph | `shared/market_data_mcp/package-lock.json` |
| npm cache | `.cache/market-data-mcp/npm/` |
| OAuth registrations/tokens and optional provider credentials | `.market-data-mcp/` |
| Downloaded Schwab binary and release metadata | `.market-data-mcp/bin/`, `.market-data-mcp/runtime/` |
| Temporary files and optional Node compile cache | `.market-data-mcp/tmp/` |
| Isolated live-query reports | `.market-data-mcp/reports/` |

The current direct npm pins are `@modelcontextprotocol/sdk` 1.32.2 and
`mcp-remote` 0.15.2; use the lockfile rather than updating these during deployment.
`mcp-remote` is used only for explicit TradingView login. The final query adapter
uses the official MCP SDK directly. `manage.py` selects the pinned Schwab
v0.2.3 release for macOS/Linux and arm64/amd64, downloads it into private state,
and checks its release checksum. Unsupported platforms fail explicitly.

Bootstrap and run offline checks:

```sh
umask 077
node --version
python3 --version
mkdir -p .cache/market-data-mcp/npm .market-data-mcp/tmp
TMPDIR="$PWD/.market-data-mcp/tmp" \
  npm ci --prefix shared/market_data_mcp \
  --cache "$PWD/.cache/market-data-mcp/npm" \
  --ignore-scripts --no-audit --no-fund
TMPDIR="$PWD/.market-data-mcp/tmp" \
  npm test --prefix shared/market_data_mcp \
  --cache "$PWD/.cache/market-data-mcp/npm"
node shared/market_data_mcp/query.mjs tradingview portal_status
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s shared/market_data_mcp/tests -p 'test_*.py' -v
```

`portal_status` is local and network-free. Its success proves startup/status only.
It does not establish provider login, a successful query or live entitlements.

### Explicit provider authentication

Authenticate on the target device through the supported flow; do not copy a
credential file into source, documentation, a fixture or an ordinary artifact
archive. Do not paste keys, tokens, authorization codes or raw auth responses
into chat. Keep one deliberate owner for each refresh cache.

TradingView login is an explicit foreground command:

```sh
python3 shared/market_data_mcp/manage.py auth tradingview
```

The current helper uses the loopback callback
`http://127.0.0.1:18273/oauth/callback`. Keep it running while completing the
provider's authorization. Query commands do not start an OAuth browser; they
return an authentication error when explicit recovery is needed.

Schwab remains staged. Before the following commands, provision an approved
provider Developer app with a callback matching the locally selected value.
The helper uses `https://127.0.0.1:8182/callback` as its default and asks for the
app key and secret through hidden local prompts:

```sh
python3 shared/market_data_mcp/manage.py install-schwab
python3 shared/market_data_mcp/manage.py credentials schwab
python3 shared/market_data_mcp/manage.py auth schwab
```

The helper forces trading and market orders off. Its current staged schema
discovery exposes only local status until provider data schemas and live access
are validated. Tradier is intentionally omitted.

Finnhub and the three options adapters use hidden local API-key prompts:

```sh
python3 shared/market_data_mcp/manage.py credentials finnhub
python3 shared/market_data_mcp/manage.py credentials marketdata
python3 shared/market_data_mcp/manage.py credentials alpaca
python3 shared/market_data_mcp/manage.py credentials massive
```

Run these in an interactive terminal. Alpaca additionally asks for the API secret.
API keys are atomically stored with mode 0600 in the mode-0700 ignored
`.market-data-mcp/credentials/` directory; existing valid files survive rejected
input. New options readers reject symlinks, oversized files and insecure modes.
Only fixed official HTTPS GET endpoints receive header credentials. No purchase,
arbitrary API execution, redirects or automatic pagination is exposed.

Free accounts are available through [Market Data](https://www.marketdata.app/signup/),
[Alpaca](https://app.alpaca.markets/) and [Massive](https://massive.com/dashboard/).
Market Data AAPL demo works without a key; other symbols require one. The price
adapter forces historical mode and bounds each chain to one expiration/side and
at most ten strikes. Alpaca forces indicative data and bounds each page; its
modified quotes are not NBBO. Massive exposes only daily contract reference and
bounded historical daily bars. These are REST-backed local MCP adapters, separate
from official hosted MCP products. See [options-data-sources.md](../options-data-sources.md)
and the [component README](../../shared/market_data_mcp/README.md) for exact scopes.
No additional dependencies were added. Provider quotas remain authoritative;
independent portal processes do not coordinate credits across sessions.

Alpaca and Massive keys are now configured in the designated private files and
both passed their first live query/restarts. Optional `strike_min`/`strike_max`
filters map to official provider query parameters, reject reversed/nonpositive
bounds, and keep the existing result limits. Massive's current-day exclusion uses
America/New_York, including the UTC-midnight boundary. No dependency, paid feed,
account/trading endpoint or active MCP registration was added.

### Isolated acceptance before any host registration

```sh
node shared/market_data_mcp/e2e.mjs tradingview
node shared/market_data_mcp/e2e.mjs schwab
node shared/market_data_mcp/e2e.mjs finnhub
node shared/market_data_mcp/e2e.mjs marketdata
node shared/market_data_mcp/e2e.mjs alpaca
node shared/market_data_mcp/e2e.mjs massive
node shared/market_data_mcp/options-verify.mjs
python3 shared/market_data_mcp/manage.py print-config
```

The live checks make real read-only provider requests and save private reports.
Exit 0 means the script's checks passed, 1 is failure and 2 is blocked
authentication. Inspect the final report for the exact source/transport being
deployed. On 2026-10-30 the final TradingView transport passed the narrow E2E
and all 53 broad-suite cases across its 19 allowed tools; a transient timeout
recovered through the bounded retry path. Finnhub's four REST-backed tools and
three clean restarts passed. Schwab remained authentication-blocked. These are
isolated-live results, separate from host activation, quote accuracy and
continuous availability. Perform new acceptance on the target device.

The Market Data AAPL demo additionally passed real expiration, two-contract
historical-chain and returned-contract quote checks with clean restarts. The
first run recovered one real connection loss; the final rerun passed without
retries. It returned provider Greeks with unverified calculation times; the
adapter labels that limitation. Alpaca and Massive were initially `blocked_auth`;
after keys were supplied, the broad suite passed 51 real-data/negative cases
with 56 distinct snapshot contracts and six daily histories. Supplemental reads
retained quote/trade ages and field availability. All six providers passed
network-free startup/write-rejection checks in the 52-test Node suite; two atomic
credential-store checks also passed. See [the options verification report](../options-verification.md)
for exact source/as-of limits and why this does not certify quote/Greek accuracy.
Active host market MCP configuration remains unchanged; scheduled Codex/email
acceptance for this change is still unverified.

`print-config` only prints a disabled candidate with absolute workspace paths.
Regenerate it after moving the checkout. Verify both the Python launch path and
Node PATH in the intended host. The template uses `/usr/bin/python3`; change a
**separate candidate** if that is not the verified target interpreter. Preserve
the original active config in ignored private state. Later activation requires
the sequence in `mcp-stability.md`, one provider in a separate host launch, and
an observed rollback check. No active-config writer is provided.

## Shared Tiger gateway and compatibility imports

The leased credential lifecycle now belongs to `shared/tiger/`. Its Node
adapter and isolated entry point reuse `shared/market_data_mcp/` without adding
an active MCP registration. `niulai-runtime/niulai_runtime/tiger.py` remains a
compatibility entry point for the direct `verify` and report-producing `run`
modes. The compatibility shim imports `shared.tiger.bridge`; it is not a second
credential store or refresh owner.

Prepare the existing `.niulai-state/.venv` with the pinned Tiger dependencies,
and the Node/npm environment described above. The shared query worker currently
selects that checkout-local Python path explicitly. Do not substitute an
unrelated global SDK or active token cache. Use the placeholder-only template
`shared/tiger/config/tiger.example.json` to understand the policy shape, then
provision verified target metadata privately as described in the gateway and
Niulai runbooks.

From a directory outside the checkout, explicitly provide both Python module
roots for compatibility or scheduled-E2E commands:

```sh
TRADING_AGENT_ROOT="/absolute/path/to/checkout"
PYTHONPATH="$TRADING_AGENT_ROOT:$TRADING_AGENT_ROOT/niulai-runtime" \
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$TRADING_AGENT_ROOT/.niulai-state/tmp" \
  "$TRADING_AGENT_ROOT/.niulai-state/.venv/bin/python" \
  -m niulai_runtime.tiger --workspace "$TRADING_AGENT_ROOT" \
  --policy "$TRADING_AGENT_ROOT/.niulai-state/config/tiger.json" \
  --out "$TRADING_AGENT_ROOT/.niulai-state/reports/UNIQUE-ATTEMPT" --mode verify
```

Replace the output directory with a new attempt identity. For the isolated
read-only portal, use `-m shared.tiger --tool snapshot` with the same explicit
policy and fresh output paths. Wait for the hidden-input readiness message and
supply the fresh native Sites result through supported host tool memory, never
in shell arguments, environment, a saved JSON file or ordinary logs.

The new portal exposes only `positions`, `assets` and `snapshot`; it does not
expose account IDs, arbitrary endpoints, orders, quotes, bars or transaction
history as tools. Report compatibility mode uses the existing privately staged
holdings pipeline under the same lease and has separate source/coverage gates.
Interactive query success does not establish unattended service authentication,
complete portfolio coverage or automatic report delivery. Inspect the exact
deployed source and actual receipt before making any such claim.

## Mentor startup and selective skill discovery

The project hook file now also contains a separate UI SessionStart definition.
The mentor catalog verifier selects its own status message rather than assuming
the file contains only one handler. UI sources, tests, status and activation
limits live in the [frontend runbook](frontend.md); mentor sources and its
existing handler are preserved. Neither catalog discovery nor an untrusted
handler establishes automatic startup execution.

`.agents/skills/` contains six relative symlinks to canonical `mentor/skills/`
directories. Preserve symlinks when checking out or copying source. These expose
metadata for automatic discovery; specialist bodies load selectively through
`mentor/ROUTING.md`. No global skill installation is needed.

The project-local `.codex/hooks.json` defines a synchronous `SessionStart` hook
for startup, resume, clear, compact and fork. `mentor/session_init.py` loads both
`mentor/AGENTS.md` and `mentor/ROUTING.md`, checks all six skill sources and links,
and returns `MENTOR_INIT_OK` with the two full core documents. It uses Python
standard library, git for locating the checkout, no network/provider access,
bounded reads, a 12,000-byte core-context cap and a three-second host timeout.
Source/input failures return `MENTOR_INIT_FAILED`, a visible warning and an
instruction for the model to tell the user. Interpreter/process failures and
timeouts are host hook errors; the root instructions require disclosure and
direct-source fallback when a current initialization marker is missing.

**Activation requires one-time human review.** Open `/hooks` in a local Codex
session, inspect the project SessionStart command, and trust that exact definition.
Codex skips untrusted/changed hooks. Do not bypass this review or claim activation
from a direct script invocation. No global settings or hook-trust records were
modified here. See [official hook documentation](https://learn.chatgpt.com/docs/hooks).
Local command hooks are unsupported under cloud orchestration; root instructions
provide a disclosed direct-read fallback, not an automatic-execution guarantee.

Reproduce the local checks (Codex CLI is an explicit prerequisite for discovery):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest mentor.tests.test_session_init -v
PYTHONDONTWRITEBYTECODE=1 python3 -m mentor.tests.verify_session_discovery
```

The verifier uses only an isolated `mentor/runtime/init-verification/codex-home/`
and local temporary directory, makes no model call, changes no active host
configuration and never grants hook trust. With Codex CLI 0.166.0, six skills were
enabled with canonical paths and no discovery errors in the root, `mentor/` and
`shared/market_data_mcp/`. The hook was found in all three with `trustStatus:
untrusted`. Five loader tests passed, including missing-router and broken-link
failures. Direct command execution passed from the root and nested directory;
8,131 bytes of context included both core sources. `codex debug prompt-input`
also confirmed root fallback instructions and all six skill names. Automatic
host hook execution remains unverified pending review and a fresh session.

## Mentor validation environment

The mentor skills and their source/provenance checks live in `mentor/`; they
are local repository resources rather than globally installed skills. Routine
executable checks use the standard library and do not require a global Skill
Creator installation:

```sh
umask 077
mkdir -p mentor/runtime/test-tmp
TMPDIR="$PWD/mentor/runtime/test-tmp" PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s mentor/tests -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 mentor/tests/verify_skill_bundle.py
```

The prior check ran on Python 3.9.6, while the imported upstream hypothesis
tools declare Python 3.11+. For a new deployment, select an explicitly verified
interpreter compatible with that upstream requirement; the earlier passing
cases are not a blanket compatibility promise for older Python versions.

`mentor/tests/requirements.txt` pins PyYAML 6.0.2 only for the optional Skill
Creator frontmatter-validator check. If that optional validation is needed,
use its own environment and local pip cache:

```sh
umask 077
mkdir -p mentor/runtime/test-tmp .cache/mentor-validation/pip
TMPDIR="$PWD/mentor/runtime/test-tmp" \
  python3 -m venv mentor/runtime/validation-env
TMPDIR="$PWD/mentor/runtime/test-tmp" \
PIP_CACHE_DIR="$PWD/.cache/mentor-validation/pip" \
PIP_DISABLE_PIP_VERSION_CHECK=1 \
  mentor/runtime/validation-env/bin/python -m pip install \
  -r mentor/tests/requirements.txt
```

An external installed validator is an optional development tool, not an implicit
runtime dependency. Record its exact source/version if it is used. Keep upstream
source pins, licenses and adaptation hashes with the repository. Reproduce the
local bundle verifier before claiming a copied skill bundle is complete.

### Local development-discipline skill and verification

`mentor/skills/development-discipline/` is workspace-authored; it is the sixth
mentor procedure alongside five pinned imported skills. Root `AGENTS.md` routes
development decisions across components through `mentor/ROUTING.md`; routine
summaries and grader-only work do not load this skill. No global installation,
daemon, CI hook, active MCP registration or background release enforcement was
added. The root safety constraints apply even on the first narrow E2E. Component
tests remain responsible for actual runtime atomicity, exception containment and
secret handling.

The matched decision/routing screen is under
`tuning/evals/development-discipline/`. Its standard-library gate is regression
tested by the mentor test command above. It validates complete response/grade
artifacts, critical failure gates and route stability; it does not establish that
self-reported architectural claims are true. Captured model responses provide
separate, bounded behavioral evidence. The optional context tokenizer is pinned
in that evaluation's `requirements.txt`; install it in the project-local eval
environment using the local pip/cache recipe below. The current development
verification used the already-present `mentor/runtime/validation-env/bin/python`
with PyYAML 6.0.2 and tiktoken 0.12.0; neither is a production dependency.

For a new, reviewed experiment identity, `prepare.py` freezes packets and refuses
an existing manifest. Its current identity is `development-discipline-v1`; preserve
that run. Once responses and independently reviewed grades have been captured,
revalidate them from the workspace root:

```sh
TIKTOKEN_CACHE_DIR="$PWD/tuning/runtime/tokenizer-cache" \
PYTHONDONTWRITEBYTECODE=1 \
  tuning/runtime/eval-env/bin/python \
  tuning/evals/development-discipline/summarize.py
```

Tokenizer vocabulary downloads, raw packets, responses and grading records stay
under ignored `tuning/runtime/`. Serialized instruction/output token counts are
proxies; provider billing and reasoning telemetry are unavailable in this screen.
The report distinguishes per-decision selective loads from cumulative session
context. See its frozen `protocol.md`, case-level `results.json` and `report.md`
for quality, routing, cost and limitations rather than inferring effectiveness
from schema validation or token savings alone.

## Tuning environments and frozen experiments

Tuning code/configuration belongs in `tuning/evals/`; generated packets,
responses, grades, caches and private execution state belong in ignored
`tuning/runtime/`. Its protocols define experiment-specific model/effort,
tool/isolation restrictions, stopping rules and interpretation. They are not
production scheduler allocations. Read the current protocol before running
anything; copying reports to another device does not reproduce a model result.

The tokenizer dependency is pinned in
`tuning/evals/mentor-routing/requirements.txt` to `tiktoken==0.12.0`. Its counts
are a context-size proxy, not billed model telemetry. `mentor-gates-complex`
also imports this tokenizer. A reproducible local environment can be prepared
without a global package installation:

```sh
umask 077
mkdir -p tuning/runtime/test-tmp tuning/runtime/tokenizer-cache .cache/tuning/pip
TMPDIR="$PWD/tuning/runtime/test-tmp" \
  python3 -m venv tuning/runtime/eval-env
TMPDIR="$PWD/tuning/runtime/test-tmp" \
PIP_CACHE_DIR="$PWD/.cache/tuning/pip" PIP_DISABLE_PIP_VERSION_CHECK=1 \
  tuning/runtime/eval-env/bin/python -m pip install \
  -r tuning/evals/mentor-routing/requirements.txt
```

For a deliberately authorized fresh packet freeze, set cache/output boundaries
explicitly before invoking a builder:

```sh
TMPDIR="$PWD/tuning/runtime/test-tmp" \
TIKTOKEN_CACHE_DIR="$PWD/tuning/runtime/tokenizer-cache" \
PYTHONDONTWRITEBYTECODE=1 \
  tuning/runtime/eval-env/bin/python tuning/evals/mentor-routing/build_packets.py
```

The builders currently target named versioned directories such as
`mentor-routing-v1` and `mentor-gates-complex-v1` and refuse to overwrite an
existing manifest. Preserve existing evidence. A new experiment needs a reviewed
new run identity/output path; do not delete frozen manifests to force a rerun.
Packet preparation does not call a model. Worker execution, response capture,
grading and acceptance need their own recorded evidence and permissions.

## Moving to another device and future setup changes

Copy reviewed source, manifests and lockfiles. Rebuild dependency environments
and regenerate absolute launch paths on the new device. Supply credentials and
any authorized private data through their separate secure procedures. Do not
copy `node_modules`, virtual environments, ignored runtime directories or live
refresh caches as if they were portable source.

Update this page, [setup-inventory.json](setup-inventory.json), the affected
component's runbook and the workspace setup consistency record whenever a local
dependency, environment variable, path, credential mechanism, launch command or
activation state changes. Distinguish configured intent, local tests, live
provider acceptance and actual host activation; none substitutes for the next.
