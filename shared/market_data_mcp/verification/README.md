# Bounded options verification

This is isolated-live development verification, not a numerical accuracy,
investment-alpha, host-rollout or scheduled-session acceptance benchmark. Cases
and criteria below were declared before the broad run; earlier narrow E2Es were
used to establish credentials and inspect the documented response envelope.

Run `node shared/market_data_mcp/options-verify.mjs` from the workspace root.
Source uses the existing isolated client; reports and resumable task state stay
under ignored `.market-data-mcp/`. No accounts, plans, trades or active MCP
registrations are changed. Supplied keys remain in the private credential store.

The matrix covers AAPL, SPY and QQQ, calls and puts, the next monthly expiration
at least two weeks away and another two months later. Three existing Finnhub
stock quotes select bounded near-money strike windows; they are context for
contract selection, not option-price ground truth. Alpaca exercises both tools,
twelve chain combinations, explicit multi-contract snapshots, page limits and
queued reads. Massive exercises eight reference combinations, six historical
daily series, an overlapping-window check, a one-row page and unknown-data cases.
Massive reads are spaced by at least 13 seconds; at most 18 data requests are
planned. Alpaca has at most 35 data requests, Finnhub three, and Market Data at
most three AAPL-only demonstration requests. Portal retries remain bounded by
the existing quota/deadline and are counted separately in the report.

Deterministic failure gates: wrong OCC underlying/expiration/side/strike;
incorrect result keys or requested bounds; nonfinite/negative quote, bar or
volume fields; crossed bid/ask; impossible OHLC bounds; unsorted/out-of-range or
future timestamps; invalid Greek sign/range where supplied; secret leakage;
accepted writes/paid-feed overrides/arbitrary URLs; or failed process cleanup.
Zero quotes, old last trades, missing Greeks, partial pages and feed delays are
reported explicitly. They do not become fabricated data or a live-risk pass.
Nonstandard deliverables are identified and excluded from standard-contract
comparisons. Massively different feeds/as-of times are never required to match
prices. Same-contract/date historical close comparisons are descriptive only:
qualified trade aggregates and quote snapshots are distinct measurements.

Permanent authentication/entitlement failures block their affected route without
replaying it unchanged. Other cases continue when independent. Cases, source
version, actual counts, failures and gaps remain in each timestamped report.
No raw credentials, response headers, provider error text or pagination URLs are
written. Separate offline tests exercise timeouts, throttling, cancellation,
storage failures and the validators. A passing small matrix establishes only
the scoped API/data contracts; absent fields and inaccessible routes remain gaps.

The 2026-10-30 broad run passed 51 cases. Its first summary retained quote ages
but omitted trade-age ranges and unique Greek coverage. The summary helper now
retains both; `options-freshness.mjs REPORT.json` provides a bounded three-read
follow-up for six contracts already present in a passing broad report. It checks
production adapter fingerprints before querying. The follow-up is additional
evidence, not a rerun of the full matrix. See `docs/options-verification.md` for
observed coverage, field gaps and the separate scheduled-acceptance boundary.
