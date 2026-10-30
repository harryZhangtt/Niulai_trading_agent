# Options adapter verification — 2026-10-30

Credentials supplied by the user were stored atomically in ignored workspace
state, with mode-0600 files in a mode-0700 directory. No key values, headers,
account identifiers or credential URLs are included here. Active Codex market
MCP registrations remain absent. No plan purchases or trading operations ran.

## Observed results

Both Alpaca and Massive passed their first real query, three restarts and
subprocess cleanup. The broad isolated-live run then passed **51 cases, zero
failures and zero blocked cases**, from 12:55:21 to 12:59:18 UTC. It used the
actual public MCP interfaces through the shared query portals, not direct calls
that bypass their validation/retry boundaries.

| Dimension | Observed coverage |
| --- | --- |
| Instruments | AAPL equity; SPY and QQQ ETFs |
| Contract sides and expirations | Calls and puts; 2026-11-20 and 2027-01-15 |
| Alpaca tools | Twelve focused chain combinations; 20-row partial page; queued single-contract reads; multi-contract snapshots |
| Alpaca data | 65 checked snapshot observations across 56 distinct contracts; quote and trade fields in all observations |
| Greeks and IV | Present in 45 of 65 broad-run observations. A focused follow-up of twenty deep-in-money calls returned neither field on any contract. Calculation timestamps and numerical accuracy remain unverified |
| Massive reference | Eight asset/side/expiry combinations with OCC/metadata agreement; fractional strikes, standard multiplier and exercise style checked |
| Massive history | Six actual contract series, 57 returned daily bars, through October 29; one overlapping single-day query matched timestamp/OHLC/volume exactly |
| Cross-provider identity | Six identical OCC contracts queried through both vendors |
| Historical price observation | AAPL 2026-11-20 call, strike 347.5, October 29: Massive qualified-trade close and Market Data historical snapshot last both 10.85 |
| Safety | Paid-feed/URL overrides, writes, oversized pages, reversed strike bounds, current-day history and unknown contracts handled as declared |
| Lifecycle | Child-process cleanup passed; three simultaneous reads serialized with observed queue depth three |

The historical match is one descriptive observation. The two vendors may share
upstream OPRA data, and qualified-trade aggregates and quote snapshots are
different measurements. This is not a quote-accuracy benchmark.

The broad run made 20 Alpaca data requests, 18 Massive requests spaced by at
least 13 seconds, three existing Finnhub context-quote requests and one Market
Data AAPL demo request. Expected rejections were checked as negative cases.
Provider failures from those intentional rejections are not successful data reads.
The shared latency history recorded thirteen healthy chain queries and reduced
that operation's warm timeout to approximately 3.56 seconds under the existing
gradual-reduction rule; this is observed adaptation, not a measured latency SLO.

## Freshness and field availability

Quote ages in the broad run were 60,028–61,156 seconds: the returned quotes were
dated to the previous US session. They were not relabeled current by the local
adapter. A three-request follow-up retained timestamps for six known contracts:
all six had quote, trade, Greek and IV fields. Quote ages were 60,351–61,251
seconds, while trade ages ranged from 1,925 to 65,931 seconds. Quote, trade and
Greek times must therefore remain separate; there is no verified calculation
clock for Greeks.

The separate twenty-contract deep-in-money field check passed deterministic
identity/price/time validation but returned no Greeks or IV. Its last trades
were approximately 2.9–59.9 days old, while quote ages were approximately
17.1 hours. Valid timestamps do not establish fresh executable prices; a last
trade must not be relabeled a current quote. This is an observed data-availability
and liquidity limitation, not a hidden passing intraday-risk result.

The initial deep-in-money sample contained no Greeks. Broader sampling established
availability on other contracts; it did not establish universal availability.
The [Alpaca source documentation](https://docs.alpaca.markets/us/docs/historical-option-data)
also identifies indicative prices as derivatives of OPRA, with modified quotes
and delayed derivative trades. Free indicative observations do not certify NBBO
or intraday hedge accuracy. Massive daily bars add historical trade/volume
coverage and contract metadata, not current bid/ask or Greeks.

## Reproduction and evidence

The case specification and fixed resource bounds are in
[the component verification guide](../shared/market_data_mcp/verification/README.md).
No dependencies were added. Optional strike bounds were added to both relevant
tools to test meaningful near-money coverage, and Massive's current-day guard
now uses America/New_York instead of UTC. Source fingerprints are retained in
the private reports.

```sh
npm test --prefix shared/market_data_mcp --cache "$PWD/.cache/market-data-mcp/npm"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s shared/market_data_mcp/tests -p 'test_*.py' -v
node shared/market_data_mcp/options-verify.mjs
```

The first broad artifact is
`.market-data-mcp/reports/options-verification-2026-10-30T12-55-21.783Z.json`.
Its `-freshness.json` sibling holds the six-contract follow-up. The original
summary retained quote age but omitted trade-age ranges and unique Greek
coverage; the summary helper was extended afterward and checked separately.
Production adapter fingerprints matched between broad and six-contract follow-up
runs. `.market-data-mcp/reports/options-deep-field-coverage.json` records the
additional single-request deep-contract check. These follow-ups used four more
Alpaca requests, within the declared 35-request overall bound.
Do not describe those artifacts as execution of a later material production
revision. Future broad runs include both age summaries directly.

The final offline run passed 52 Node checks and two credential-store checks,
including the financial-field validators, strike-filter mapping, New York date
boundary, redaction, timeouts, cancellation, queueing, retries and process cleanup.

## Acceptance boundary

These are successful isolated-live integration and consistency checks. The
workspace's [scheduled Codex/email acceptance](deployment/runtime-acceptance.md)
remains **unverified** for this change; no future-triggered Codex session or
verified result email is claimed by this task. Its private handoff record is
`.job-runtime/acceptance/options-alpaca-massive-20261030/record.json`.
No active host registration or independent numerical pricing/Greek benchmark
has been accepted. Tradier remains skipped and Schwab remains credential-blocked.
