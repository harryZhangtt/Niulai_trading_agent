# MCP stability incident and rollout record

## Isolated research sources: 2026-10-30

The optional `arxiv-mcp-server==0.8.2` candidate was installed in a separate
workspace environment and exercised through isolated clients. A real versioned
paper download, 23-section outline and bounded benchmarking-section read succeeded;
query-process cleanup was verified. Downloads remain a distinct local-cache write;
the existing portal still filters tools annotated non-read-only. The first section
probe used an incorrect schema key and failed; the corrected query was verified.
OpenAlex official REST discovery and versioned arXiv HTML reads were also tested.
The authenticated OpenAlex MCP itself remains untested. No active host registration
was added; installation is not proof of scheduled acceptance or investment quality.
See [source setup](../shared/research_sources/README.md) and the separate
[investment source contract](../investment/research/README.md).

## Isolated Tiger gateway: 2026-10-30

Tiger now reuses the portal core through a dedicated in-memory MCP adapter and
one isolated SDK worker per query. No active host registration or HTTP listener
was added. The final path completed a live snapshot followed by an independent
fresh-process assets query; both committed credential checkpoints. Offline tests
cover denied writes, secret-free pipes/receipts, uncertain outcomes without retry,
malformed output and actual worker timeout/cleanup. This establishes the isolated
query path, not host registration safety or unattended authentication. See the
[Tiger runbook](../shared/tiger/README.md); private data and receipts remain in
ignored runtime state. Rollback is to stop using this launcher and use the runtime
compatibility entry point; preserve credentials, leases and uncertainty fences.

## Incident: 2026-10-30

The user reported a host crash after active TradingView/Schwab MCP entries were
added to the workspace `.codex/config.toml`. This establishes the triggering
change as reported by the user; it does not establish a root cause. No host
crash trace was available. Unsupported configuration, launch paths, startup IO
and host behavior remain unconfirmed possibilities, not diagnoses.

The active additions were removed and the original config restored. Global
Codex settings were not changed. A partially removed TradingView table header
was observed during rollback, so all integration additions were removed together
instead of leaving their keys at the TOML root. The root `AGENTS.md` now records
the incident and prohibits active registration during development.

## Current separation and containment

The integration lives in `shared/market_data_mcp/`. Protocol handling, resilience,
provider adapters, authentication and validation are separate modules. None are
loaded by the active Codex config. The candidate config is a separate file with
all candidates disabled and absolute paths generated on request.

MCP initialization, local tool discovery and `portal_status` perform no provider
network access. Data queries connect lazily. Writes are blocked before provider
IO. Deadlines, cancellation, queue limits, retry budgets and a process-local
circuit breaker bound failure behavior. Query execution does not launch OAuth
browser windows. Authentication is an explicit separate operation. Child
process shutdown is checked by the isolated client.

## Evidence and limits

- TradingView OAuth completed successfully, with state saved inside the ignored
  workspace state directory.
- At 2026-10-30 09:45 UTC, an earlier portal implementation using the pinned
  `mcp-remote` query transport returned a successful AAPL symbol search, five
  AAPL daily OHLCV bars, and symbol close/volume data from the official MCP.
  These were real queries, not documentation examples.
- The final portal uses the official MCP SDK directly for TradingView queries,
  retaining `mcp-remote` only for explicit login. Its live rerun at approximately
  10:00 UTC failed reaching TradingView (`connection_lost`, about 32.5 seconds).
  Independent Node and Python requests to its public OAuth metadata endpoint
  also timed out. The network path and/or provider was unavailable; the cause
  was not established. That rerun was recorded as a failure, not attributed to
  earlier success. Connectivity later recovered: the user-requested single-bar
  retry and the final core E2E suite passed at approximately 10:26 UTC.
- The subsequent final broad TradingView suite passed 53/53 checks, covering all
  19 exposed read tools, pagination, multiple markets, queueing, in-flight
  cancellation/recovery and invalid inputs. One real timeout recovered through
  the bounded retry path. This verifies observed recovery, not absence of future
  failures. The failed first broad run was investigated: two cases assumed all
  tools used the same response envelope; the screener requires a nonempty
  filter; the options search filter is unsupported. The corrected suite tests
  those actual contracts, including rejection of the unsupported filter.
- Offline tests cover failure recovery and network-free startup. They do not
  establish that the host application itself will remain stable after enabling
  the MCP registration.
- Schwab's staged adapter starts locally and contains missing-credential errors.
  Its live quote check reports `blocked_auth`. A Schwab Developer app and user
  authorization remain necessary. Tradier was skipped at the user's request.
- No independent quote-accuracy or latency benchmark was performed. Returned
  TradingView feed notices and update metadata remain authoritative for the
  data's delay/entitlement limitations.
- Finnhub's local read-only MCP adapter passed actual quote, profile, search and
  metrics queries and clean restarts. Its API key is in ignored workspace
  credentials with mode 0600 and is sent only as an HTTPS request header. No key
  is included in source, candidate config or test reports. The official hosted
  Finnhub MCP is a separate OAuth integration and is not claimed active.
- All 30 offline tests passed after Finnhub was added. Active host registration
  remains off despite these isolated passes; the original crash cause remains
  unconfirmed.
- The options additions share the existing portal and a small REST/MCP boundary,
  without new dependencies. Market Data's no-key AAPL demo passed real expiration,
  bounded two-contract historical-chain and returned-contract quote queries and
  clean restarts. The first run at approximately 11:05 UTC recovered one actual
  connection loss; the final 11:07 UTC rerun passed without retries. Provider
  Greeks were present, but their calculation time remains unverified and is
  labeled accordingly. Alpaca indicative snapshots/chains and Massive daily
  reference/history adapters passed offline checks; live tests reported
  `blocked_auth`. All 46 Node checks and two atomic credential-store checks passed.
  Fixed GET endpoints, header credentials, bounded response sizes, rejected
  redirects, strict schemas and no automatic pagination contain the new paths.
  These are local REST-backed MCP adapters, not claimed hosted-MCP connections.
- A real TradingView symbol search for the verified Market Data option contract
  `AAPL261120C00342500` returned no symbols. A different TradingView contract
  naming format remains unverified; website options availability is separate
  from an established chain/Greeks API.
- At 12:45 UTC the supplied Alpaca/Massive keys were privately configured and
  each provider passed its narrow E2E plus three restarts. After bounded strike
  filters and a New York date guard were added, the 12:55–12:59 UTC isolated
  broad run passed 51 cases with no failures/blocks: three underlyings, calls
  and puts, two expiries, 56 distinct contracts and six daily series. Both tool
  pairs were exercised through the portal. Supplemental reads verified actual
  timestamp/field gaps: near-money Greek/IV fields were available; twenty deep
  calls lacked them, and their oldest last trade was approximately sixty days
  old. Quote ages remained prior-session values. No current-price substitution
  or model-derived Greeks were inserted. All 52 offline Node checks and two
  credential-store tests passed. See `docs/options-verification.md` for exact
  scope, artifacts and limitations. Scheduled Codex/email acceptance remains
  unverified under the new workspace acceptance contract; host activation and
  numerical price/Greek accuracy remain separate, unaccepted claims.

## Required rollout sequence

1. Keep the active `.codex/config.toml` free of these registrations during work.
2. Run offline tests and isolated startup/shutdown checks on the final source.
3. Obtain a successful live E2E report for the exact provider and final transport.
   A handshake or local schema listing is insufficient.
4. Generate the separate disabled candidate. Check absolute launch paths and
   Node availability in the actual host environment. Keep a copy of the original
   config in ignored workspace state before a later activation.
5. Validate one provider in a separate host launch, with bounded startup and tool
   timeouts. Record host behavior and available crash diagnostics before making
   any stability claim. Roll back the whole added table if a regression occurs.

No automated activation or active config writer is included. This record is
workspace memory for future agents, not a claim that the crash root cause has
been fixed.
