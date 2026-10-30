# Options-data access and diversification

Verified 2026-10-30 using native web search, opened official documentation,
direct public source retrieval, the official Finnhub OpenAPI repository, and
actual TradingView/Finnhub query tests. No paid plans were purchased and no
additional accounts or active host registrations were created.

## Existing integrations

**TradingView's website has options data.** Its official
[options-chain overview](https://www.tradingview.com/support/solutions/43000760837-options-chain-overview/)
documents strikes, expirations, bid/ask, implied volatility and theoretical
Greeks. This establishes a website capability, not MCP/API access to that data.

**The current MCP integration is not an established options-chain feed.** The
[official MCP tool catalog](https://www.tradingview.com/mcp/docs) contains no
dedicated chain, expirations or Greeks tool. Live discovery originally returned
35 tools; the portal allows 19 data/research tools, all tested successfully.
A live `search_symbols` request with `type_filter="option"` was rejected.
Generic symbol/quote tools were tested for stocks, ETFs, crypto and FX. A later
search for the actual Market Data contract `AAPL261120C00342500` returned zero
symbols. Access through another TradingView-specific symbol format remains
unverified; these negative results do not prove individual quotes impossible.

**Finnhub diversifies equities and fundamentals, not verified options data.**
The project-local MCP adapter successfully queried quotes, company profiles,
symbol lookup and financial metrics through the official REST API. The
[official hosted MCP catalog](https://finnhub.io/static/finnhub-how-to-connect-mcp-server.html)
lists 70 tools but no options-chain/Greeks tool. The official
[OpenAPI schema](https://github.com/Finnhub-Stock-API/finnhub-go/blob/master/api/openapi.yaml)
was inspected: 105 endpoint paths, with none named for options, Greeks or
volatility. That supports not selecting Finnhub as the options feed; it is not
a claim about unpublished or future products. Hosted Finnhub MCP uses OAuth,
separately from the user's stored API key.

TradingView and Finnhub both returned AAPL's last close of $348.91 in this
session. Matching one prior close is a basic consistency observation, not a
quote-accuracy or latency benchmark.

## Free-compatible integrations and evidence

| Candidate | Access and free scope | What it adds | Safe adoption approach |
| --- | --- | --- | --- |
| **Alpaca** | A free paper account can start. Basic options feed is indicative; paid OPRA access is separate. | Chain and contract snapshots, with provider-supplied IV/Greeks where available. | Credentials configured; real chain/snapshot matrix passed across AAPL, SPY and QQQ, calls/puts and two expiries. Field availability varies by contract. |
| **Massive** | Options Basic is advertised as free EOD access with five API calls/minute. Live quotes and higher tiers require paid entitlements. | Daily-updated contract reference and historical daily bars. | Credentials configured; real reference checks and six daily histories passed through the local MCP's fixed GET routes. No generic executor or current quote/Greek tools exposed. |
| **Market Data** | Free account: 100 daily credits after trial. Current mode documentation restricts free/trial to fully closed historical sessions. No-key AAPL demo is available. | Expirations, bounded historical chains and single-contract quotes. | Implemented local REST-backed MCP forcing historical price mode, one expiration/side and at most ten strikes. AAPL demo passed real E2E and clean restarts. Other symbols need a key. |

Alpaca's [official MCP documentation](https://docs.alpaca.markets/us/docs/trading-api-mcp)
lists option-chain/snapshot tools and toolset filtering. Its
[market-data plans](https://docs.alpaca.markets/us/docs/about-market-data-api)
distinguish Basic from OPRA access. The
[options endpoint documentation](https://docs.alpaca.markets/us/reference/optionlatesttrades)
explicitly says indicative trades are delayed and quotes are modified. Such
quotes are suitable for integration testing, not as a precise executable NBBO
reference. Data-feed provenance must be recorded with each result.

Massive documents a vendor-hosted, OAuth-authenticated MCP at
[`mcp.massive.com`](https://massive.com/docs/ai-tools/quickstart). Its tools can
discover endpoints and execute REST calls; access follows account entitlements.
The [options pricing page](https://massive.com/pricing?product=options) advertises
Basic EOD access. Plan details were present in the indexed official page; the
opened reader view omitted the dynamically loaded options cards. Direct
retrieval of the official HTML also confirmed the Options Basic and EOD plan
content. Verify account entitlements before selecting a plan. After the user
supplied a key, real contract-reference and historical daily-bar queries passed.
Its narrower local MCP avoids the
hosted product's generic endpoint execution surface. The
[contract-reference](https://massive.com/docs/rest/options/contracts/all-contracts)
and [daily-bars](https://massive.com/docs/rest/options/aggregates/custom-bars)
documentation explicitly includes Basic, with daily/EOD recency and two years
of history. Only the successfully queried scopes are established; the account's
full subscription/entitlement inventory was not inspected.

Market Data's [pricing table](https://www.marketdata.app/pricing/) describes
Free using a 24-hour-delay shorthand. Its more specific
[data-mode documentation](https://www.marketdata.app/docs/api/universal-parameters/mode/)
says free/trial can explicitly request only historical mode; cached mode requires
payment. The adapter follows that narrower rule with no paid fallback. Its
[coverage documentation](https://www.marketdata.app/data/) identifies OPRA.
The [API introduction](https://www.marketdata.app/docs/api/) documents the
unauthenticated AAPL demo. Real tests returned 23 expirations, two contracts for
2026-11-20 and a quote for a returned contract. A first connection loss recovered
through the bounded portal retry; the final run passed without retries.

The demo returned Greeks despite the historical-mode request. Their calculation
time was not supplied or validated, so output sets `greeks_timing_verified=false`
and preserves the original fields. This is separate from explicit-date history:
the [quote documentation](https://www.marketdata.app/docs/api/options/quotes/)
says those Greeks/IV are null. No numerical accuracy benchmark was performed.
Neither demo access nor a successful quote establishes intraday risk suitability.

## Comparison discipline

The adapters share the existing retry/timeout portal, a small REST boundary and
private credential reader. Provider endpoints, field mapping and free scopes
remain separate. Fixed GET paths avoid account/trading tools and generic URL
execution. No dependencies or active host registrations were added. These are
documented integration scopes and bounded test results, not accuracy rankings.

Normalize contract identity (underlying, expiration, strike, call/put,
multiplier), currency, quote/trade timestamps, session, delay and feed before
comparing values. Distinguish last trade, midpoint, bid and ask; record Greeks'
calculation/model time separately from quote time. Several vendors redistribute
OPRA, so adding vendors does not necessarily create independent exchange data.

Use QuantLib as a separate calculation check only after explicit inputs and
model choices are set. OpenBB and charting libraries can organize or display
data but do not create another underlying quote feed. Tradier stays skipped as
requested; Schwab remains staged until Developer credentials and entitlements
are supplied. All three additional adapters are implemented as disabled
candidates. Market Data's limited AAPL demo, Alpaca indicative snapshots/chains,
and Massive reference/daily history have passed isolated live queries. Scheduled
Codex/email acceptance remains unverified. Keys belong in the hidden local
prompts documented in the [portal README](../shared/market_data_mcp/README.md).
OptionStrat has no established free API in this review; QuantLib, OpenBB and
Lightweight Charts do not themselves supply another free options quote feed.

The [2026-10-30 verification report](options-verification.md) records 51 passed
live cases, field availability, prior-session quote ages and the one descriptive
cross-vendor historical observation. Price accuracy and Greek calculation times
are not established by these consistency checks.
