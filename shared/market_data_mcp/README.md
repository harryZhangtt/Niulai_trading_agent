# Market-data MCP query portals

TradingView and Finnhub are validated providers of a shared, read-only MCP
portal. Finnhub uses a small project-local MCP adapter for its official REST API,
authenticated with the user's separately stored API key. This is distinct from
Finnhub's official hosted MCP, which requires OAuth. Schwab remains staged
pending Developer app credentials. Market Data's AAPL options demo passed the
isolated E2E. Alpaca and Massive credentials are privately configured; their
REST-backed MCP paths passed 51 broad isolated-live cases. Scheduled-session
acceptance remains unverified. Tradier is omitted at the user's request.

Tiger account reads reuse this portal through a dedicated isolated entry point:
[`../tiger/README.md`](../tiger/README.md). `positions`, `assets` and `snapshot`
use the existing leased OAuth store; Tiger credentials never enter normal
provider configuration. Launch `python -m shared.tiger` at the workspace root
with the local SDK environment. This is separate from `manage.py serve` and needs
fresh native service context through hidden stdin for each invocation.

**Active Codex registration is off.** Adding active entries caused a
user-reported host crash on 2026-10-30; the cause is unconfirmed. The original
workspace `.codex/config.toml` was restored. See
[`../../docs/mcp-stability.md`](../../docs/mcp-stability.md) before any rollout.

## Responsibilities

| Module | Responsibility |
| --- | --- |
| `server.mjs` | MCP protocol, local schema discovery, status, graceful shutdown |
| `core/portal.mjs` | Bounded queue, deadlines, retries, reconnects, circuit breaker |
| `core/errors.mjs` | Error classification, embedded error detection, safe public errors |
| `core/observations.mjs` | Small per-operation timing summaries and bounded warm-query budgets |
| `core/rest-adapter.mjs` | Shared bounded REST IO, private key reads, redaction and local MCP boundary |
| `providers.mjs` | Provider capability allowlists and tool-name mapping |
| `adapters/tradingview.mjs` | Official Streamable HTTP transport and trusted endpoints |
| `adapters/finnhub.mjs` | Four read-only MCP tools backed by official Finnhub REST endpoints |
| `adapters/marketdata.mjs`, `alpaca.mjs`, `massive.mjs` | Provider-owned options paths, free-compatible scope and provenance |
| `auth/local-oauth.mjs` | Workspace OAuth cache and atomic token refresh writes |
| `auth/credential_store.py` | Atomic mode-0600 API key replacement in a mode-0700 directory |
| `manage.py` | Explicit login, hidden credential input, pinned Schwab installation |
| `schemas/` | Public tool schemas, versioned separately from runtime state |
| `client.mjs`, `query.mjs` | Reusable isolated client and command-line query interface |
| `tests/`, `e2e.mjs` | Failure injection, process isolation and real query checks |

No mentor, tuning or investment-policy code is coupled to these adapters. An
investment agent can use `withPortal(provider, async client => ...)` from
`client.mjs`, or connect an MCP client to `manage.py serve PROVIDER`.

## Installation and use

Requires Node.js >=22 and Python >=3.9. No global packages are installed. From the
workspace root:

```sh
npm ci --prefix shared/market_data_mcp --cache .cache/market-data-mcp/npm --ignore-scripts --no-audit --no-fund
node shared/market_data_mcp/query.mjs tradingview portal_status
node shared/market_data_mcp/query.mjs tradingview search_symbols '{"query":"AAPL","type_filter":"stock"}'
node shared/market_data_mcp/query.mjs tradingview get_ohlcv '{"symbol":"NASDAQ:AAPL","interval":"1D","count":5}'
node shared/market_data_mcp/query.mjs tradingview get_symbol_data '{"symbol":"NASDAQ:AAPL","columns":["close","volume","update_mode"]}'
node shared/market_data_mcp/query.mjs finnhub quote '{"symbol":"AAPL"}'
```

`portal_status` reports local state and does not contact the provider. A listed
tool schema is **not** evidence of current connectivity, successful login or
real-time entitlements. Price responses retain the provider's feed notices and
metadata; the portal does not fabricate, cache or substitute prices.

TradingView tool aliases use underscores (`get_ohlcv`); the adapter maps them to
the live server's prefixed names (`mcp-tv-get-ohlcv`). Only the 19 explicitly
allowed data/research tools are exposed. Watchlist operations, alert changes,
account access and order tools are excluded.

## Authentication

Finnhub's key is stored in `.market-data-mcp/credentials/finnhub.json`, with
file mode 0600 inside a mode-0700 directory. It is excluded from Git. The adapter
reads it only for API requests and sends it as `X-Finnhub-Token` to
`https://finnhub.io/api/v1/`; it never places the key in URLs, tool arguments,
process arguments, source configuration or reports. Redirects are rejected.
To replace it through a hidden prompt:

```sh
python3 shared/market_data_mcp/manage.py credentials finnhub
```

The local adapter supports `quote`, `company_profile`, `symbol_lookup` and
`basic_financials`. The official hosted OAuth alternative is documented at
[Finnhub's MCP setup page](https://finnhub.io/static/finnhub-how-to-connect-mcp-server.html).
It is not authenticated by the local API key or claimed active here.

TradingView uses its [official MCP server](https://www.tradingview.com/mcp/docs).
It requires Essential or higher, excluding trial plans. Authorization succeeded
in this session; its token is stored only in ignored local state. To authorize
again explicitly:

```sh
python3 shared/market_data_mcp/manage.py auth tradingview
```

This prints the OAuth URL and starts a callback listener on
`http://127.0.0.1:18273/oauth/callback`. Keep the command running while authorizing.
The callback listener is used only by the explicit login command. Query processes
never open a browser; refresh failure returns `auth_required`.

Schwab uses the **unofficial**
[`itsmostafa/schwab-mcp` v0.2.3](https://github.com/itsmostafa/schwab-mcp/tree/v0.2.3)
against the official Schwab Trader API. It does not automate the thinkorswim UI.
The downloaded macOS arm64 binary's release checksum was verified. To reproduce:

```sh
python3 shared/market_data_mcp/manage.py install-schwab
python3 shared/market_data_mcp/manage.py credentials schwab
python3 shared/market_data_mcp/manage.py auth schwab
```

First create an approved, **Ready For Use** app in the
[Schwab Developer Portal](https://developer.schwab.com/). Its registered callback
must match the configured callback, normally
`https://127.0.0.1:8182/callback`. Enter the app key and secret at the hidden local
prompts, never in chat. Only then can `auth schwab` generate the account-specific
authorization URL. The helper always forces trading and market orders off.
Until public schemas are verified for this adapter, its discovery exposes only
`portal_status`; its data connection is staged, not claimed operational.

Credentials, OAuth registrations/tokens, binaries, temporary files and reports
live under ignored `.market-data-mcp/`. Credential files use mode 0600 and state
directories use 0700. No global Codex config, credentials or shell settings are
changed. The helper's OAuth cache format is isolated in `auth/local-oauth.mjs`.

## Free-compatible options adapters

These are local MCP servers backed by official REST APIs, separate from the
providers' hosted/general-purpose MCP products. They share `QueryPortal`, expose
no trading/account routes and add no npm dependency. HTTP requests use fixed
provider origins, GET only, header credentials, manual redirects, a 20-second
deadline and a 1 MiB response limit. Input schemas reject arbitrary URLs, paid
feed overrides and extra properties. Pagination is never automatic.

| Provider | Tools and enforced scope | Current evidence |
| --- | --- | --- |
| Market Data | Expirations, single quote and one-expiration/one-side chain capped at 10 strikes; `mode=historical` for prices | AAPL demo: real expirations, two-contract chain, returned-contract quote and clean restarts passed |
| Alpaca | Chain capped at 20 snapshots or up to five contract snapshots; indicative feed and optional bounded strike window | Actual chain/snapshot matrix passed; Greek/IV availability varies by contract |
| Massive | Contract reference capped at 20 rows with optional strike window; daily bars capped at 31 days within two years and before today's New York date | Actual reference matrix and six historical series passed |

Free accounts: [Market Data](https://www.marketdata.app/signup/),
[Alpaca](https://app.alpaca.markets/), [Massive](https://massive.com/dashboard/).
Save account keys with hidden input in an interactive local terminal:

```sh
python3 shared/market_data_mcp/manage.py credentials marketdata
python3 shared/market_data_mcp/manage.py credentials alpaca
python3 shared/market_data_mcp/manage.py credentials massive
node shared/market_data_mcp/e2e.mjs marketdata
node shared/market_data_mcp/e2e.mjs alpaca
node shared/market_data_mcp/e2e.mjs massive
node shared/market_data_mcp/options-verify.mjs
```

Alpaca needs both key and secret. Other providers need one key. Files are private
under `.market-data-mcp/credentials/PROVIDER.json`; replacements are atomic. No
keys enter config, URLs or process arguments. Missing credentials are permanent
errors until explicitly supplied; no login browser or purchase runs implicitly.
Only Market Data's AAPL demo can query without a key. A missing file enables that
limited demo; malformed or insecure credentials fail rather than silently falling
back. Free quotas remain provider-owned; concurrent portal processes do not share
a rate/credit ledger. No plan upgrades or automatic paid-mode fallbacks exist.

Market Data free/trial requests use fully closed sessions, and explicit-date
history has no stored Greeks/IV. The tested demo returned Greeks despite a
historical-mode request; those values are preserved with
`greeks_timing_verified=false`. Alpaca's indicative quotes are modified and trades
are delayed. Massive's daily bars provide no current bid/ask or Greeks. Preserve
provider timestamps, contract identity and feed metadata when comparing sources.
No quote/Greek accuracy or real-time risk-monitoring claim follows from these tests.

## Failure policy

Every provider instance has one serialized upstream query lane and at most 16
pending requests. A query has a 65-second total budget, including queue time,
with at most three attempts and a 20-second hard attempt deadline. Retry delays use
capped exponential backoff with jitter. HTTP `Retry-After` is honored; if it
exceeds the remaining budget, the request fails without an early retry.

Cold connections retain the conservative deadline. After eight successful
samples, warm data-query budgets use the operation's latency EWMA plus four
deviations and 500 ms of padding, bounded to 3–20 seconds. A budget decreases by
at most 25% after each successful sample. This is a bounded heuristic, not a
proven tail-latency SLO. Queue wait, connection time and failed/censored attempts
are recorded separately; failures do not teach the portal that a longer timeout
is healthy. Histories expire after 24 hours and contain at most 64 operations.

Summaries contain no symbols, payloads or credentials. They save atomically on
clean shutdown under `.market-data-mcp/runtime/` and are bounded to 64 KiB on
load. Corrupt or unavailable diagnostics never block startup. Concurrent
processes use independent controls; summary writes are last-writer-wins, not a
distributed coordination mechanism. There is no background telemetry service.

A per-process retry quota starts with four tokens. Each retry consumes one;
each successful query restores one up to the cap. High queue pressure suppresses
retries. Initial requests retain access when retry tokens are exhausted.

Only explicitly allowed reads retry, and only for timeouts, connection failures,
HTTP 429 and transient server failures. Authentication, validation, unsupported
tools and capability mismatches do not retry. Cancellation stops queued requests
before dispatch and cancels an active SDK request. Connection loss or timeout
invalidates the upstream session before another attempt.

Three exhausted transient query failures open the circuit for 30 seconds. The
next eligible read probes recovery; successful data resets the circuit. This
circuit is **per process**, not a persistent cross-process quota system. The
HTTP adapter disables the SDK's additional SSE retry loop so the portal owns the
retry budget.

Errors return stable codes with `isError=true`. The portal also detects embedded
JSON errors from providers that incorrectly return `isError=false`. Diagnostics
contain event names, counts, durations and error categories, not raw tool
arguments, responses, tokens or upstream exception text. The TradingView adapter
permits HTTPS requests only to its two explicit provider hosts and rejects
redirects rather than forwarding credentials to another destination.

## Verification and rollout

```sh
npm test --prefix shared/market_data_mcp --cache .cache/market-data-mcp/npm
node shared/market_data_mcp/e2e.mjs tradingview
node shared/market_data_mcp/e2e.mjs schwab
node shared/market_data_mcp/e2e.mjs finnhub
node shared/market_data_mcp/tradingview-wide.mjs
python3 shared/market_data_mcp/manage.py print-config
```

Offline tests use real in-memory MCP transports and isolated subprocesses. They
cover rate limits, transient errors, dropped connections, timeouts, cancellation,
queue overload, circuit recovery, secret-safe errors, OAuth storage permissions,
trusted endpoints, malformed protocol input, SIGTERM, and process cleanup.

E2E checks require actual provider data, inspect returned symbols/bars/feed
metadata, and check clean restarts. Reports are written to
`.market-data-mcp/reports/PROVIDER-e2e.json`; exit codes are 0 for pass, 1 for
failure, and 2 for missing authentication. A failed final rerun is not a live-data
pass. Re-run it after the external blocker clears.

`print-config` only prints a **disabled** candidate with absolute workspace paths.
It does not modify active configuration. Before any host rollout, require an
up-to-date successful E2E run of the final code, verify Node is available in the
host launch environment, retain the original config, and validate one provider
in a separate launch. Host crash prevention cannot be claimed from the isolated
checks alone. Do not hot-edit the running host's MCP registrations.

On 2026-10-30, the final TradingView transport passed the core E2E suite and a
53-case broad suite covering all 19 allowed provider tools, queued reads, live
cancellation/recovery, pagination, alternate markets and negative cases. One
live timeout recovered through a bounded retry. Finnhub passed four real data
queries plus restart/cleanup checks. After the keyed options verification, all
52 Node checks and two credential-store checks passed. The broad real options
matrix passed 51 cases across 56 distinct contracts and six daily histories.
Reports stay
under `.market-data-mcp/reports/`; no host registration was enabled.

Options access and additional providers are assessed in
[`../../docs/options-data-sources.md`](../../docs/options-data-sources.md).
Exact coverage, observed timestamp/Greek gaps, retained evidence and the separate
scheduled-acceptance boundary are in
[`../../docs/options-verification.md`](../../docs/options-verification.md).
